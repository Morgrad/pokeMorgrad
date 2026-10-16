# src/ module reference

Verified by reading the code (line cites are `file:line`). "Unclear" = could not be established from the code alone.
Imports below are intra-repo (`src.*`) only. Dependency direction: arrows mean "imports".

## Contents
- [Dependency map](#dependency-map)
- [Foundation: paths, regmc_db, showdown_validator](#paths-regmc_db-showdown_validator)
- [Damage stack: damage, opp_model, doubles_eval, doubles_pilot, smart_player](#damage-stack)
- [GA: ga_core (by section), battle, eval, audit_before_launch](#ga_corepy)
- [BC stack (torch): state_encoder, bc_model, bc_player, bc_train](#bc-stack-torch)
- [Env vars read by src/](#env-vars-read-by-src)

## Dependency map
```
paths  <-- regmc_db, state_encoder, showdown_validator, damage, opp_model, ga_core, bc_player, bc_train, eval
regmc_db <-- damage, ga_core, audit_before_launch
damage <-- smart_player, doubles_eval, opp_model, doubles_pilot
opp_model, doubles_eval, smart_player <-- doubles_pilot
battle <-- ga_core, eval            (battle lazily imports bc_player / doubles_pilot)
state_encoder <-- bc_model <-- bc_player, bc_train ; state_encoder <-- bc_player, bc_train
ga_core <-- eval, audit_before_launch ; ga_core <-- run/*
```
- Torch-importing modules: `state_encoder` (torch at `state_encoder.py:30`), `bc_model`, `bc_player`, `bc_train`.
- Torch-free: `paths, regmc_db, showdown_validator, damage, opp_model, doubles_eval, smart_player, doubles_pilot, ga_core, battle, eval`.
  `battle` reaches torch only through the lazy `BCPlayer` import (`battle.py:84-86`); `DoublesPilot` import is also lazy (`battle.py:87-89`).

---

## paths.py (46 lines)
Single source of truth for repo-relative locations.
- `REPO_ROOT`: `POKEMORGRAD_ROOT` env (must contain `data/`, else `RuntimeError`, `paths.py:14-24`), else parent of `src/`.
- `data_path(*p)`, `output_path(*p)`, `src_path(*p)`, `showdown_dir()` (env `SHOWDOWN_DIR`, default `~/pokemon-showdown`, `paths.py:43-44`).
- Imports nothing from src. Gotcha: `ga_core` does not use `showdown_dir()` (see ga_core Island section).

## regmc_db.py (397 lines)
Canonical, torch-free data layer over `data/regmc_db.json` (cached with `lru_cache`).
- Lookups: `get_species/get_item/get_move/get_ability`, `all_species`, `all_species_base` (forme is None), `normalize_species_name` (strips `(M)/(F)` and nicknames), `species_has_ability` (formes inherit from base or sibling formes), `species_can_learn`, `moves_by_category`, `mega_stones_for`.
- `parse_team(text)` parses Showdown paste into mon dicts; `validate_team(mons)` is the LOCAL legality check: 6 mons, species clause, item clause, legal item, ability, exactly 4 distinct learnable moves, EVs <= 66 total and <= 32 per stat.
- Importers: damage, ga_core, audit_before_launch. Has a `__main__` smoke test.
- Gotcha: this is the DB-based check; the authoritative check is Showdown via `showdown_validator`.

## showdown_validator.py (56 lines)
`check_teams(list[str]) -> list[(ok, msg)]` validating team texts against the real Showdown format rules.
- Spawns `node src/showdown_validate.js` once per call, teams base64-encoded on stdin, timeout 60s; in-process md5-keyed `CACHE`. Missing verdicts become `(False, "no-verdict")`. The JS file itself was not read: its internals are unclear.
- Imports `paths`. Used by `ga_core.filter_legal_genomes`.

---

## Damage stack

### damage.py (305 lines)
Champions-format damage estimator mirroring Showdown's `data/mods/champions` math (docstring `damage.py:1-18`).
- Stat formula: EV points 0-32, term `max(2*pts-1, 0)` (`_ev_term`, `damage.py:53`); `stat_at_level` with nature 1.1/0.9.
- Type effectiveness from `typeChart` damageTaken codes `{0:1,1:2,2:.5,3:0}`; immune code is 3 (`damage.py:36`; regression-pinned in tests).
- `_rolls_core` (`damage.py:132`) is the shared core: 16 rolls (85..100%), spread x0.75 (only if `include_spread` and target is allAdjacent/allAdjacentFoes), weather, crit, STAB, eff, burn (not with Guts), terrain (only if `attacker_grounded`), screens (2/3 in doubles, ignored on crit), floor of 1 if eff > 0.
- Entry points: `damage_rolls` (species + EVs + nature), `damage_rolls_from_stats` (final stat ints, level fixed 50; used by doubles_eval), `damage_range` -> (min, mean, max), `ko_chance`.
- Imports `regmc_db`, `paths`. Torch-free. Reads `data/regmc_db.json` via `_raw_db()`.
- Gotchas: `defender_ability`, `defender_grounded` are accepted by `damage_rolls` but unused in the math; `defender_level` is used for the defender stat. The docstring lists `defender_ability` as "damage-relevant" (`damage.py:15`) but nothing consumes it.

### opp_model.py (140 lines)
Torch-free, poke_env-free model of hidden opposing builds.
- `Build` dataclass (weight, stats, max_hp); `opponent_builds(species)` returns up to `TOP_K=3` weighted builds from `data/species_build_priors.json`, else a generic spread (Adamant/Modest, 32 HP / 32 offense / 2 Spe).
- `_prior_key` falls back to the base species for `-Mega` forms; `resolve_species`, `stats_for`, `immunity_prob(species, move_type, ability)` mixes `data/species_ability_priors.json` with the `IMMUNITY_ABILITIES` map. LEVEL=50.
- Imports `damage`, `paths`. Importers: doubles_pilot, tests.

### doubles_eval.py (171 lines)
Pure-logic joint scoring of a PAIR of attack actions (numpy + damage; no poke_env).
- Value = sum over targets of `weight * (E[capped dmg]/max_hp + KO_BONUS * P(KO))`, ally targets negative (`doubles_eval.py:135-150`).
- Constants: `KO_BONUS=1.0` (swept, `:27`), `ALLY_WEIGHT=1.0`, `MIN_GAIN=0.01`.
- Dataclasses `Hypothesis, Combatant, Attacker, Action`; `Evaluator` (roll cache, `p_hit = accuracy * (1 - immune)`, two attackers on one target combined via outer sum of rolls, `_hits` at `:117`); `choose_pair` (index 0 is the vanilla baseline; deviate only if gain > `min_gain`, `:153-171`).
- Explicitly not modelled: speed order, Protect/Fake Out/redirection, retaliation, secondary effects, defender item/ability modifiers (`:14-16`).

### doubles_pilot.py (219 lines)
`DoublesPilot(SimpleHeuristicsPlayer)`: vanilla decision, then re-picks move + target of both attackers jointly when both slots chose plain damaging moves.
- Constants `LOCKED_MOVES`, `UNMODELLED_MOVES` (leave vanilla's choice), item/ability multipliers (Choice Band/Specs, Huge/Pure Power, Life Orb).
- `_attacker` (needs `mon.stats`), `_foe` (opp_model mixture; unknown species returns base), `_ally`, `_action`, `_improve` (skips on force_switch; mega never used), `choose_move` (any exception falls back to base; `stats_counter` = turns/overrides/errors).
- Env: `DOUBLES_KO_BONUS`, `DOUBLES_MIN_GAIN` (`doubles_pilot.py:70-73`; constructor kwargs win).
- Imports `damage, doubles_eval, opp_model` and four helpers from `smart_player` (`_boosts_dict, _terrain_name, _type_to_db, _weather_name`). Torch-free; created lazily by `battle.make_player` for `pilot="doubles"`.

### smart_player.py (205 lines)
`SmartPlayer(SimpleHeuristicsPlayer)` overriding `choose_singles_move` (a SINGLES hook) with damage-calc scoring (KO_BONUS=8.0 etc.).
- Not wired into `battle.make_player`. The format is doubles, so the override appears never to run (docs/STATE.md §5.20 reportedly calls it inert; not re-verified here).
- Still load-bearing as a helper module: doubles_pilot imports `_type_to_db, _weather_name, _terrain_name, _boosts_dict`. `_stats_dict` is used only by `SmartPlayer`.
- Imports `damage`.

---

## ga_core.py
1556 lines, torch-free. Imports `regmc_db`, `showdown_validator`, `battle`, `paths`. Organised in banner sections:

| Lines | Section | Content |
|---|---|---|
| 1-109 | Header + constants | `FORMAT="gen9championsvgc2026regmc"`, `UID_MAX`, `EV_BUDGET=66`, `EV_STAT_CAP=32`, `MAX_REBUILD_TRIES=20`, `BATTLE_TIMEOUT=20`, `MIN_TURNS=3`, `SEED_POOL=30`, `VAL_POOL_SIZE=30`, `TRAIN_SAMPLE_SIZE` (env `GA_TRAIN_SAMPLE`, 250, `:75`), `VAL_SPLIT_SEED=42`, early-stop (`EARLY_STOP_MIN_BATTLES=50`, `EARLY_STOP_WIN_RATE=0.15`), `CANONICAL_ITEMS`, `PROTECT_MOVES`, `FAKEOUT_MOVES` |
| 110-229 | Cached roster + data loaders | `_BASE_SPECIES`, `move_priors_for` (`data/species_move_priors.json`, top 8), `meta_items_for` (`data/meta_items.json`), `_load_teams` (resolves by basename in `data/regional_teams`; raises if a non-empty list loads zero), `regional_pool` (pool_split.json "train", else glob), `_split_train_val` (deterministic shuffle), `heldout_pool` ("holdout") |
| 230-530 | Set generation | `_legal_items_for` (lru_cache; mega stone / itemUser filtering), `_species_role` (physical/special/support), `_random_mon` (priors-first, role-matched; EVs/nature follow role; excludes "randomNormal" target moves), `_pick_item_for` (mega stone -> meta-weighted -> canonical -> any legal), `build_random_genome(constraints)` |
| 532-560 | Serialization | `genome_to_text` (Level 50, always writes `EVs:`), `text_to_genome` (None unless exactly 6 mons) |
| 562-628 | Realism constraints | `_force_move_on_slot`, `_enforce_composition` (soft: Protect and Fake Out/redirection coverage) |
| 630-701 | Legality filter | `filter_legal_genomes` (`:633`): batched `SV.check_teams`, rebuild failed slots up to 20 tries, then composition pass. Output may be SHORTER than input |
| 703-890 | Operators | `mutate_species/item/ability/nature/evs/move`, `mutate(mons, constraints, n=1-4)` on a deepcopy over free slots; `crossover` (per-slot parent pick; locked slots take the parent holding the species; species/item clause repair) |
| 892-969 | Fitness | `async evaluate(mons, opponents, idx, total)` (`:910`) |
| 971-1060 | Legacy `run_ga` | single population, elites `max(2, pop//5)`, writes `output/champions/ga_{label}.txt`, `output/ga_history.json`, `random.seed(42)`. No live callers found in `run/` |
| 1062-1557 | Island model | `Island`, `ring_migrate`, `restart_showdown`, checkpoints, `breed`, `_eval_on_subset`, `run_islands` |

### Key behaviours (ga_core)
- Genome = list of 6 dicts `{species, item, ability, nature, evs, moves}`; constraints = `{slot: species}` (locked slots). Island constraint keys are stringified for JSON.
- `evaluate`: invalid genomes (local `DB.validate_team`) score 0.0; plays 50 "head" battles first and aborts if head fitness < 0.15, else plays the tail; `None` battle results are dropped from the denominator. Pilot is always the heuristic here (via `battle.run_battle`, `min_turns=3`).
- Train/val: training pool is split with seed 42 into train / `VAL_POOL_SIZE=30` val; heldout pool is for final eval only. Per-generation opponent sample = `min(battles_per_genome, TRAIN_SAMPLE_SIZE, len(train_pool))`.
- `_SEM` is a module-global semaphore set by `run_ga`/`run_islands`.
- `Island` (`:1091`): name, constraints, population, fitness, `best_ever`, `best_val_ever`, stagnation, history, `seed_paths`; `to_dict/from_dict`.
- `inject_immigrants(island, n)` replaces the worst n; `ring_migrate(n=2)`: island i receives from i-1, replaces worst, strips foreign locked species (`_strip_species`).
- `restart_showdown` (`:1275`): `pkill -9 -f "pokemon-showdown start {port}"`, relaunch `node pokemon-showdown start {port} --no-security`, polls up to 15s.
- `save_checkpoint` writes `output/checkpoints/v6/<run_id>/gen_NNNN.json`, keeping newest plus multiples of 5; `load_latest_checkpoint` resumes.
- `breed`: elites `max(2, n//3)`, immigration rate 0.20, `filter_legal_genomes`, top up to pop size.
- `run_islands` defaults (`:1393-1400`): pop 10, gens 999, battles 800, `concurrency=int(env GA_CONCURRENCY, "3")` (evaluated at def time), immigration 0.20, stagnation_limit 5, diversity_floor 15 unique species, migration_every 5, showdown_restart_every 10. Per gen: evaluate islands sequentially (genomes within an island concurrently) -> val-evaluate the train-best -> diversity rescue (3 immigrants) -> stagnation restart (replace worst half) -> ring migration -> checkpoint every gen.
- Outputs at end (`ga_core.py:1540-1556`): `output/champions/ga_<run_id>_island_<name>.txt` and `..._train.txt`.

### Gotchas (ga_core)
- `META_ITEM_BIAS=0.70` (`:50`) is defined and never referenced anywhere in src/, run/, tools/ (grep). Item choice uses meta items via `_pick_item_for` regardless.
- Champion selection comments say "by validation score" (`:1542`) but the code picks `best_ever` (train-selected) whenever it exists, so `ga_<id>_island_X.txt` and `_X_train.txt` are identical in practice; val is only a fallback.
- `SHOWDOWN_DIR` is hard-coded `os.path.expanduser("~/pokemon-showdown")` (`:1071`), ignoring `paths.showdown_dir()` / env `SHOWDOWN_DIR`. `SHOWDOWN_PORT` is read from env at import (`:1072`).
- `FORMAT` and `UID_MAX` are shared with eval via import from here.

---

## battle.py (154 lines)
Shared poke_env harness for GA and eval (replaces duplicated logic; see its docstring).
- `make_player(pilot, team_str, uid, prefix, battle_format)`: `pilot` in `heuristic | bc | doubles`; account via `AccountConfiguration.generate(prefix+uid, rand=False)` (deterministic names).
- `run_battle_once` (semaphore-bounded, `asyncio.wait_for`, always `stop_listening` in finally; returns 1/0/None; `min_turns` guard) and `run_battle` (`retries=1`, uid offset by `RETRY_STRIDE=999_983`).
- Reads `SHOWDOWN_PORT` at import (`:59`, default 8000) to build `DEFAULT_SERVER`. Does NOT read `GA_CONCURRENCY`.
- Installs `_DropVGCNoise` log filter on poke_env loggers (`:37-50`). Opponent is always `SimpleHeuristicsPlayer`.
- Does not import ga_core (circular); format passed in.

## eval.py (163 lines)
CLI `python -m src.eval` for evaluating team files (default `baseline_team.txt`) against a pool.
- Flags (from main_async): `--opponents heldout|all`, `--pilot heuristic|bc|doubles|both`, `--concurrency`; seeds `DEFAULT_SEEDS=[100,200,300]`, `TIMEOUT=20`; Wilson CI helper `wilson_ci`; `evaluate_team` runs seeds sequentially under one semaphore with `random.seed(seed)`.
- Env: `GA_CONCURRENCY` (default "3", `eval.py:27`).
- Imports `ga_core` (pools, `FORMAT`, `UID_MAX`) so it is not independent of the GA module; torch only if `bc`.
- Gotcha: the HEUR/BC/Delta comparison table only covers heuristic and bc pilots; `doubles` is not in it.

## audit_before_launch.py (188 lines)
Pre-launch sanity script; has NO `__main__` guard, so everything runs at import. Run as `python -m src.audit_before_launch`.
- Nine sections: DB integrity, name sanity, mega stones, regional teams validate, fuzz 500 Umbreon-locked genomes, fuzz 500 free, 2000 mutations, 500 crossovers, baseline team.
- Uses `DB.validate_team` (local), not the Showdown validator. Seeds random with 0, 42, 1. Imports `regmc_db`, `ga_core`, `paths`.

---

## BC stack (torch)

### state_encoder.py (251 lines)
`StateEncoder`: turns a battle state dict into tensors. Imports torch (`:30`) and `paths`.
- Vocab built from `regmc_db.json`, sorted, 1-based, 0 = pad.
- `encode_mon` -> `cont[17]` (hp frac, bulk, 5 boosts, 7 status one-hot, mega, fainted, active); `encode_field` -> 17 wide (9 weather, 5 terrain, trick room, tailwind p1/p2); `encode` -> 12 fixed slots (my 2 active + 4 bench, opp 2 active + 4 seen).
- Frozen contract constants: `N_SLOTS=12, N_MOVES_PER=4, CONT_DIM=17`. `__main__` benchmarks on `data/training_data.jsonl`.

### bc_model.py (266 lines)
- `BCModel` v2: MLP trunk 512/256, dropout 0.3, `OUTPUTS=6`. `BCModelV3`: transformer d_model 384, 4 layers, 6 heads, 13 tokens, `OUTPUTS=8` (adds target heads, `N_TARGETS=5`).
- `build_move_mask(priors, encoder)` (zeroes Struggle/pad), `save_checkpoint` (keys `model_state, epoch, val_*, encoder_v, arch`; `val_target_acc` for v3). No loader here.
- Gotcha: `encoder_v` is written but never read (unclear whether intended for future checks).
- Imports `state_encoder` constants.

### bc_player.py (320 lines)
`BCPlayer(Player)`: neural doubles pilot.
- Env `BC_PILOT_PATH` (read at import; default `output/models/bc_best.pt`, `bc_player.py:33`). Loads `data/species_move_priors.json`. `_get_shared_model` caches per device and defaults arch to `"v2"`; `torch.load` is used without `weights_only`.
- `_state_to_dict`, `_score_options` (log P(type)+log P(move) [+ target]; `ALLY_TARGET_PENALTY=5.0` for ally targets unless in `ALLY_TARGET_MOVES`), `choose_move` (uses `battle.valid_orders`, resolves switch collisions, random fallback).
- Gotcha: the encoder is fed `item/ability=None`, `is_mega=False`, `terrain=None`, `hp_max=100` (hp as percent); `opp_seen` includes opposing actives (duplicates). Training-time inputs may differ: unclear.

### bc_train.py (398 lines)
Behavioural-cloning trainer. Env: `BC_DATA` (default `data/training_data.jsonl`), `BC_OUT` (default `bc_best.pt` under `output/models/`), `BC_MODEL` v2|v3, `BC_BATCH` 256, `BC_EPOCHS` 30, `BC_PATIENCE` 3. `LR=1e-3`, `WD=1e-5`, `VAL_FRAC=0.1`, `SEED=42`.
- `BCDataset` (winner samples duplicated 2x; moves not in priors become TYPE_NONE), `slot_loss`, `run_epoch`, `build_model`, `main`.
- `main`: drops consecutive duplicate (side, turn) rows, splits battles on a second `turn==1`, 90/10 battle-level split, AdamW + cosine annealing, saves on best `val_move_acc`, early stops on `PATIENCE`.
- Gotcha: module docstring (`:4-7`) lists only BC_MODEL/BC_OUT/BC_EPOCHS/BC_PATIENCE, not BC_DATA/BC_BATCH.

---

## Env vars read by src/
| Var | Where | Default |
|---|---|---|
| `POKEMORGRAD_ROOT` | paths.py:15 | repo parent of src/ |
| `SHOWDOWN_DIR` | paths.py:43 | `~/pokemon-showdown` (not used by ga_core) |
| `SHOWDOWN_PORT` | battle.py:59, ga_core.py:1072 | 8000 |
| `GA_CONCURRENCY` | ga_core.py:1398, eval.py:27 | "3" |
| `GA_TRAIN_SAMPLE` | ga_core.py:75 | 250 |
| `BC_PILOT_PATH` | bc_player.py:33 | output/models/bc_best.pt |
| `BC_DATA/OUT/MODEL/BATCH/EPOCHS/PATIENCE` | bc_train.py | see above |
| `DOUBLES_KO_BONUS`, `DOUBLES_MIN_GAIN` | doubles_pilot.py:70-73 | 1.0 / 0.01 |
