# BC (behaviour cloning) neural pilot

Covers the neural pilot stack: `src/state_encoder.py` (battle state -> tensors), `src/bc_model.py`
(v2 MLP, v3 transformer, checkpoint contract), `src/bc_player.py` (poke_env Player) and
`src/bc_train.py` (trainer). Read before touching any of them, loading a checkpoint, or
interpreting BC numbers. Runbook for training/promotion: `docs/runbooks/bc-training.md`.

Last verified against code: 2026-11-18

## 1. Purpose

BC was the project's first pilot: a net trained on human Showdown replays (5,001 Reg M-C replays
-> 72,048 decision rows, 2026-10-12) to play any 6-mon team. It lost to poke_env's
`SimpleHeuristicsPlayer` by ~40 points and is NOT used by the GA by default (GA fitness uses
`GA_PILOT=vgc` = `VGCPilot` vs `GA_OPP=ladder` = `LadderOpponent`, see `docs/subsystems/pilots.md`). It is kept as a possible foundation for search
or RL warm-start. Pipeline position: replays -> `tools/build_training_data.py` -> JSONL ->
`src/bc_train.py` -> `output/models/*.pt` -> `src/bc_player.py` (selected by `--pilot bc` in
`src/eval.py`, or `pilot="bc"` in `src/player_factory.py::make_player`).

STATUS 2026-11-18: the `mon_view` `TypeError` that crashed every BC decision is fixed and pinned
by `tests/test_bc_state.py` (section 9 item 1). Still open: old checkpoints may not load against
the current DB vocab (section 9 item 2); no `.pt` file exists on the 2026-11-18 checkout.

## 2. Files

| path | lines | role |
|---|---|---|
| src/state_encoder.py | 252 | `StateEncoder`: vocab from `data/regmc_db.json`, state dict -> 6 tensors |
| src/bc_model.py | 266 | `BCModel` (v2), `BCModelV3`, `build_move_mask`, `save_checkpoint`, constants |
| src/bc_player.py | 321 | `BCPlayer(Player)`, `_get_shared_model` (the only checkpoint loader) |
| src/bc_train.py | 405 | `BCDataset`, `slot_loss`, `run_epoch`, `build_model`, `main` |

Related tools: `tools/build_training_data.py`, `tools/replay_tracker.py`,
`tools/generate_heuristic_dataset.py`, `tools/build_species_priors.py`, `tools/encode_snapshot.py`,
`tools/bc_diagnostic.py` (see `docs/reference/tools-data.md` and `tools-ops.md`).

## 3. Key concepts and data structures

State dict (one decision point, one side). Training rows carry it under `"state"`:
```
{"my_active": [mon|None, mon|None], "my_bench": [mon,...], "opp_active": [...], "opp_seen": [...],
 "field": {"weather": "RainDance"|None, "terrain": None, "trick_room": bool,
           "tailwind": {"p1": 0|1, "p2": 0|1}}}
mon = {"species": "Incineroar", "gender": "M", "hp_now": 73, "hp_max": 100, "status": "brn"|None,
       "boosts": {"atk": 2}, "revealed_moves": ["Fake Out", ...], "item": str|None,
       "ability": str|None, "is_mega": bool}
```
Vocab (`StateEncoder.__init__`): `sorted()` keys of `species/moves/items/abilities` in
`data/regmc_db.json`, 1-based; index 0 = pad/unknown. Current sizes (DB built 2026-10-20):
`n_species=393, n_moves=516, n_items=167, n_abilities=317` (each = vocab + 1).

`StateEncoder.encode(state)` returns (12 slots in FIXED order: my 2 active, my 4 bench, opp 2
active, opp 4 seen; short lists padded with None, long ones truncated):

| key | shape | dtype |
|---|---|---|
| species_ids | [12] | long |
| move_ids | [12, 4] | long |
| item_ids | [12] | long |
| ability_ids | [12] | long |
| continuous | [12, 17] | float32 |
| field | [17] | float32 |

`continuous` per mon (`CONT_DIM=17`): [0] hp_now/hp_max clamped 0-1; [1] min(1, hp_max/200);
[2:7] boosts atk,def,spa,spd,spe each /6; [7:14] status one-hot none,brn,par,slp,psn,tox,frz;
[14] is_mega; [15] fainted (hp_now == 0); [16] active flag (1 for slots 0,1,6,7).
`field` (17 wide, unrelated layout): [0:9] weather one-hot (none, SunnyDay, RainDance, Sandstorm,
Snow, Hail, DesolateLand, PrimordialSea, DeltaStream); [9:14] terrain one-hot (none, Electric,
Grassy, Psychic, Misty); [14] trick room; [15] tailwind p1; [16] tailwind p2.
Unknown status/weather/terrain fall into bin 0 ("none").

Models (`src/bc_model.py`). Embeddings: species 32, move 16 (x4), item 16, ability 16, all
`padding_idx=0`. Per mon = 32+64+16+16+17 = 145; flat input = 145*12 + 17 = 1757.
- `BCModel` (v2, production, 1,528,768 params at current vocab): trunk Linear(1757,512)-ReLU-
  Dropout(0.3)-Linear(512,256)-ReLU-Dropout(0.3); heads per active slot a/b: `type_head_*` (3:
  move/switch/none), `move_head_*` (n_moves), `switch_head_*` (n_species). `OUTPUTS = 6`.
- `BCModelV3` (5,538,890 params): per-slot Linear(145->384) tokens + field token (13 tokens),
  positional embedding, 4 pre-LN transformer blocks (6 heads, ff 768, dropout 0.1); heads read
  token 0 (slot a) and token 1 (slot b); adds `target_head_*` (N_TARGETS=5). `OUTPUTS = 8`.
- Target classes: 0 our right, 1 our left, 2 none, 3 opp left, 4 opp right.
- Action types: `TYPE_MOVE=0, TYPE_SWITCH=1, TYPE_NONE=2`. Mask sentinel `NEG_INF=-1e4` (finite on
  purpose: -inf produces NaN on all-masked rows).

Checkpoint payload (`save_checkpoint`): `{model_state, epoch, val_loss, val_acc, val_move_acc,
val_switch_acc, encoder_v (=2, never read), arch ("v2"|"v3"), val_target_acc (v3 only)}`.
`bc_best.pt` predates `arch` and stores `arch=None`; the loader treats None as v2.

Move mask (`build_move_mask(priors, encoder)`): (n_species x n_moves) 0/1 from
`data/species_move_priors.json` (191 species, ladder counts); Struggle and column 0 always 0.
Used only in training (loss + accuracy). `BCPlayer` builds it but never applies it: inference
scores only `battle.valid_orders`, which are already legal.

## 4. Public API

- `StateEncoder()` -> loads `data/regmc_db.json`; attrs `species_idx, move_idx, item_idx, ability_idx, n_*`.
- `StateEncoder.encode(state_dict)` -> dict of 6 tensors (table above).
- `StateEncoder.encode_mon(mon)` -> `(species_id, move_ids[4], item_id, ability_id, cont[17])`.
- `StateEncoder.encode_field(field)` -> `np.ndarray[17]`.
- `BCModel(n_species, n_moves, n_items, n_abilities)`; `forward(sp, mv, it, ab, cont, field)` -> 6 logits.
- `BCModelV3(...same..., d_model=384, n_heads=6, n_layers=4, ff_dim=768, dropout=0.1)` -> 8 logits.
- `build_move_mask(priors, encoder, verbose=True)` -> float tensor [n_species, n_moves].
- `save_checkpoint(path, model, *, epoch, val_loss, val_acc, val_move_acc, val_switch_acc, encoder_v=2, arch=None, val_target_acc=None)`.
- `BCPlayer(**poke_env Player kwargs)`; `choose_move(battle)` -> `DoubleBattleOrder`.
- `src/bc_player.py::_get_shared_model()` -> `(encoder, model, priors, mask, arch)`, cached per DEVICE.
- `src/bc_train.py::main()` (run as `python -m src.bc_train`); `slot_loss`, `run_epoch`, `BCDataset`.

## 5. Flow

Training (`src/bc_train.py::main`):
1. Seed 42 (random, numpy, torch). Build encoder and move mask; load all rows of `BC_DATA`.
2. Drop consecutive rows with the same (side, turn) (Showdown re-asks and an old loop bug).
3. Chunk rows into battles (a new battle starts when `turn == 1` repeats for a side); keep only
   chunks with <= 100 rows and both sides p1/p2.
4. Battle-level split: shuffle battles (seed 42), 10% val (`VAL_FRAC`). Row-level split leaks
   battles and inflated val_move_acc by ~20 pts (old OPERATIONS runbook, 2026-10-13; see `docs/history/`).
5. `BCDataset`: per row, slot labels `(type, move_idx, switch_idx, acting_species_id, target)`
   from `chosen[side]["a"|"b"]`; a move not in the species' priors becomes `TYPE_NONE`; rows with
   `side_won` true are added twice (outcome weighting).
6. Loss per slot = CE(type) + CE(masked move | type==move) [+ CE(target), v3] + CE(switch masked
   to bench species | type==switch); total = slot a + slot b.
7. AdamW (lr 1e-3, wd 1e-5), cosine annealing over `BC_EPOCHS`, batch `BC_BATCH`, `pin_memory=False`
   and `num_workers=0` (ROCm on WSL2).
8. Save `output/models/$BC_OUT` whenever val_move_acc improves (NOT val_loss: the -1e4 mask makes
   loss spiky); early stop after `BC_PATIENCE` epochs without improvement.

Inference (`BCPlayer.choose_move`):
1. Non-doubles battle, or `valid_orders` not two non-empty lists -> `choose_random_move`.
2. `_state_to_dict(battle)`: HP as percent (`hp_max=100`), `item=None`, `ability=None`,
   `is_mega=False`, `terrain=None`; `opp_seen` = all of `battle.opponent_team` (includes actives).
3. Encode, one forward pass on DEVICE (cuda if available, else cpu).
4. `_score_options` per slot: switch = logP(switch type) + logP(species); move = logP(move type) +
   logP(move) [+ logP(target), v3]; minus `ALLY_TARGET_PENALTY=5.0` when the order targets our
   own side (-1/-2) and the move is not in `ALLY_TARGET_MOVES` (Helping Hand, Follow Me, Pollen
   Puff, ...). Unknown species/move -> -inf.
5. Argmax per slot. If both slots switch to the same species, the lower-scoring slot takes its
   best move, else another switch, else the whole turn goes random.

## 6. Invariants (checkpoint contract)

- Do not rename attributes of `BCModel`/`BCModelV3` (state_dict keys) or change `EMB_*`,
  `N_SLOTS=12`, `N_MOVES_PER=4`, `CONT_DIM=17`, `FIELD_DIM=17`, `N_TARGETS=5`.
- Do not reorder/append `STATUSES`, `WEATHERS`, `TERRAINS`, `BOOST_STATS`; "none" stays at index 0.
- Vocab = sorted DB keys. ANY species/move/item/ability added to or removed from
  `data/regmc_db.json` changes table sizes and shifts indices: old checkpoints stop loading.
- Payload keys read by the loader: `arch`, `model_state`, `val_target_acc`, `val_move_acc`, `epoch`.
- Target index order is shared by `bc_player._TARGET_MAP`, `tools/build_training_data.py::_target_idx`
  and `tools/generate_heuristic_dataset.py::TARGET_MAP_REV`.
- Encoder refactors must be bit-identical: `tools/encode_snapshot.py capture` before, `check` after.

## 7. Config and env vars

| name | default | read in |
|---|---|---|
| `BC_PILOT_PATH` | `output/models/bc_best.pt` | `bc_player.py` at import |
| `BC_DATA` | `data/training_data.jsonl` | `bc_train.py` |
| `BC_OUT` | `bc_candidate.pt` (under `output/models/`) | `bc_train.py`; production `bc_best.pt` is only replaced by hand (promotion rule) |
| `BC_MODEL` | `v2` (`v3` = transformer) | `bc_train.py` |
| `BC_BATCH` / `BC_EPOCHS` / `BC_PATIENCE` | 256 / 30 / 3 | `bc_train.py` |
| constants | LR 1e-3, WEIGHT_DECAY 1e-5, VAL_FRAC 0.1, SEED 42 | `bc_train.py` |
| `ENC_SNAPSHOT_REF` | `/tmp/enc_snapshot_ref.pt` | `tools/encode_snapshot.py` |

The `bc_train.py` docstring lists only BC_MODEL/BC_OUT/BC_EPOCHS/BC_PATIENCE.
Fixed 2026-11-18: `BC_OUT` defaulted to `bc_best.pt`, so a training run without it
overwrote the production model and bypassed the promotion rule.

## 8. Tests

`tests/test_bc_state.py` (2 tests, in `tools/verify.sh`, needs torch but no model file and no
Showdown): a stub battle goes through `BCPlayer._state_to_dict` and
`tools/generate_heuristic_dataset.py::state_from_battle`; checks active / bench / opponent
lists, revealed moves and non-zero boosts. Run `python tests/test_bc_state.py`.
No unit test covers `state_encoder`, `bc_model` or `bc_train`, nor loading a real checkpoint
(`tests/test_state_encoder.py` cited in old docs does not exist). `tools/verify.sh` also imports
`src.bc_train`, `src.bc_player`, `src.bc_model`, `src.state_encoder`. The encoder gate is
`python tools/encode_snapshot.py capture|check` (exit 0 identical, 1 drift).

## 9. Gotchas and known issues

1. Fixed 2026-11-18 (broken since commit 1788b2a "unused params", 2026-10-16):
   `BCPlayer._state_to_dict` called `mon_view(m, True)` for opponent mons but the nested
   `mon_view(mon)` takes one argument -> `TypeError` on every BC decision. Same break in
   `tools/generate_heuristic_dataset.py::state_from_battle` (`_mon_view(m, encoder, True)`), where
   the exception was swallowed and the generator wrote 0 rows. All calls now pass one mon (plus
   `encoder` in the tool); `tests/test_bc_state.py` pins both. Since 2026-11-18
   `run_battle_once` logs such per-battle exceptions (`battle error #N` with traceback), so a
   future pilot crash shows up in the log instead of only as dropped battles.
2. Vocab drift: `data/regmc_db.json` gained `Lucario-Mega-Z` on 2026-10-16 (391 -> 392 species).
   Every checkpoint trained before that (all known ones, incl. `bc_best.pt`, 2026-10-13) has
   `sp_emb` / `switch_head_*` sized for 392 rows and indices shifted after "Lucario-Mega", so
   `load_state_dict` will fail (current vocab: `n_species` 393). NOT fixed. Unverified on a real
   file: no `.pt` files in this checkout.
3. Train/inference mismatch: replay rows (`replay_tracker`) and heuristic rows carry revealed
   item/ability names, but `BCPlayer` always sends `item=None, ability=None`, so `it_emb`/`ab_emb`
   see index 0 (a zero vector) at inference. `gender` is collected but never encoded. `is_mega` and
   terrain are always False/None at inference. (Refactor roadmap C5.)
4. `hp_max=100` at inference makes cont[1] (bulk proxy) a constant 0.5. Unverified: public replay
   logs also report HP as `n/100`, which would make the "bulk" feature constant in training too.
5. Imitation accuracy does not predict win rate (measured 4 times, STATE.md 5.12): pick models by
   live 5-seed eval, not val_move_acc.
6. v3 target head (51% accurate vs ~47% trivial) adds noise to option scores; v3 played at 8.8%.
7. `valid_orders` lists ally-target variants first; before the 5.0 penalty (2026-10-13) the pilot
   hit its own ally on every attack (0.3% win rate).

Measured results (all: our team `data/baseline_team.txt`, heuristic opponent, OLD 100-team holdout
in use before the 2026-10-15 real-EV holdout swap, 5 seeds = 500 battles; NOT comparable to scores
on today's holdout):

| model (file) | data | val_move_acc | win rate | date |
|---|---|---|---|---|
| heuristic pilot (reference) | - | - | 61.0% (other runs 54.8-60.6%) | 2026-10-13 |
| v5 = `bc_best.pt` (v2 MLP) | older v5 human set (est. 150k rows) | 0.579 | 19.4% (18.3% earlier) | 2026-10-13 |
| `bc_v6a.pt` (v2) | 72k human rows | 0.527 | not promoted | 2026-10-13 |
| `bc_v3_5m.pt` (v3) | 72k human rows | 0.581 (target 0.513) | 8.8% | 2026-10-13 |
| `bc_heuristic.pt` (v2) | 60,688 heuristic rows | 0.6875 | 30.4% [26.5-34.6] | 2026-10-13 |
| heuristic v2 +items | same | 0.734 | 23.0% [19.5-26.9] | 2026-10-14 |
| `bc_heuristic_v1c.pt` | same, honest split | 0.62 | ~32% | 2026-10-14 |

Conclusion (2026-10-14, STATE.md 5.16): BC imitating the heuristic is capped by the heuristic;
stop BC-on-heuristic work; a stronger pilot needs search/RL. bf16 autocast gave no speedup and
batch 512/1024 lost accuracy (2026-10-13).

## 10. How to change safely

- [ ] Encoder change: `python tools/encode_snapshot.py capture` first, edit, then `check` must PASS.
      If the output must change, it is a new checkpoint contract: bump `encoder_v`, retrain.
- [ ] Rebuilding `data/regmc_db.json` changes the vocab: retrain BC afterwards (or pin the old DB).
- [ ] After any `bc_player.py` change: run `PYTHONPATH=. python tools/bc_diagnostic.py 3` and check
      calls/turn < 5 and no `[Invalid choice]` (method in `docs/runbooks/bc-training.md`).
- [ ] Set `BC_OUT` to a dated candidate name when training (default `bc_candidate.pt`); promote
      to `bc_best.pt` by hand only per the rule (5-seed eval, +3 pts).
- [ ] Keep target-index order identical in the three files listed in section 6.
- [ ] Planned cleanup (refactor roadmap Tier 2, after next retrain): delete `BCModelV3` + v3 branches
      (C1), drop `encoder_v` (C3), the `load_checkpoint` tombstone (C4), item/ability/gender residue (C5).
- [ ] `bash tools/verify.sh` must end with `ALL PASS` (it covers state building, not model loading or
      win rate, see section 8).

## Related docs

- [BC training runbook](../runbooks/bc-training.md)
- [Evaluation subsystem](eval.md) and [evaluation runbook](../runbooks/evaluation.md)
- [Pilots](pilots.md), [battle harness](battle-harness.md)
- [Data files](../reference/data-files.md), [tools index](../reference/tools.md)
- [Refactor roadmap](../design/refactor-roadmap.md), [history](../history/README.md)
