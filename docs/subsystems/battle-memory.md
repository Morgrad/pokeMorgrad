# Battle memory and foe action priors

Covers `BattleMemory` (per-battle event memory built from raw Showdown protocol lines:
`src/battle_memory.py`, `src/battle_memory_parser.py`, `src/battle_memory_types.py`) and the
foe Protect / Fake Out / Trick Room probabilities fitted on ladder replays (`src/opp_actions.py`
+ `data/opp_actions.json`). Read it before touching protocol parsing, condition durations,
Mega tracking, Open Team Sheets or the foe action model.

Last verified against code: 2026-11-18

## 1. Purpose

poke_env lacks what a doubles pilot needs: real weather/terrain start turns, who moved first,
the exact Mega form (it applies the wrong form for Z-line Megas), Protect success chains, failed
Protects (`|-fail|` is ignored, so `protect_counter` still increments), volatile durations, Open
Team Sheet sets. `BattleMemory` keeps that state, pure Python, fed one split protocol line at a
time. The SAME class runs live (through `BattleMemoryMixin` on `VGCPilot` and `LadderOpponent`)
and offline on replay logs (`tools/build_mega_rates.py`, `tools/build_opp_actions.py`), so fitted
rates and inference use identical features. `opp_actions` turns a memory record into
P(Fake Out / Protect / Trick Room this turn) for `turn_sim` (through `VGCPilot`) and for the
ladder-like GA opponent (`src/ladder_opp.py`). Built 2026-10-16; split into three files 2026-11-16
(commit c51e5e1).

## 2. Files

| path | lines | role |
|---|---|---|
| src/battle_memory.py | 199 | `BattleMemory` queries, `BattleMemoryMixin`, `repair_mega_forms`; re-exports types |
| src/battle_memory_parser.py | 287 | `BattleMemoryParserMixin.feed` + one `_on_<event>` handler per protocol event |
| src/battle_memory_types.py | 103 | constants, `Condition`, `Action`, `MonRecord`, ident helpers |
| src/opp_actions.py | 163 | `FoeCtx`, `foe_ctx`, cell keys, `action_probs` |
| data/opp_actions.json | (14.5 KB) | fitted rates, built by `tools/build_opp_actions.py` (tracked) |

Import `from src import battle_memory as BM`; it re-exports `PROTECT_FAMILY, WEATHERS, TERRAINS,
PERMANENT_WEATHER, DURATIONS, VOLATILES, TAINT_ACTIVATE, Condition, Action, MonRecord` (and
`_id` is used by other modules as `BM._id`).

## 3. Key concepts and data shapes

**Input**: one protocol line split on `|`, e.g. `"|switch|p2a: Garchomp|Garchomp, L50, M|100/100"
.split("|")` -> `["", "switch", "p2a: Garchomp", "Garchomp, L50, M", "100/100"]`. `p[1]` is the
event; `feed` dispatches to `_on_<event without leading '-', '-' -> '_'>`.
**Mon key** = `(side, name)` from the ident (`"p2a: Garchomp"` -> `("p2", "Garchomp")`): keyed by
NICKNAME, slot letter ignored. Species comes from the details field.

**MonRecord** fields: `side, name, species, first_seen_turn, switch_in_turn, mega_form,
mega_stone, mega_turn, item, item_consumed, status, slow_start, fainted, protect_uses,
protect_fails, protect_chain, protect_last_turn, volatiles {name: start_turn}`.
**Condition**: `name, scope ('field'|'p1'|'p2'), kind (DURATIONS key or name), start_turn,
source ('move' or e.g. 'ability: Drizzle'), setter, end_turn, end_reason ('expired'|'replaced'),
layers`. **Action**: `turn, seq, side, slot, name, kind ('move'|'cant'|'switch'|'drag'), move
(id), priority (DB base priority), megaed, chosen` (False for pivot/replacement/drag switches).

Constants (`battle_memory_types.py`):
- `DURATIONS` (min, max turns): weather (5, 8), terrain (5, 8), Trick Room (5, 5), Tailwind
  (4, 4), Reflect / Light Screen / Aurora Veil (5, 8), Gravity / Magic Room / Wonder Room (5, 5).
  Max assumes an extender item (rocks, Light Clay, Terrain Extender).
- `PERMANENT_WEATHER`: DesolateLand, PrimordialSea, DeltaStream (open-ended).
- `VOLATILES`: Taunt 3, Encore 3, Yawn 2.
- `PROTECT_FAMILY`: protect, detect, endure, kingsshield, spikyshield, banefulbunker, obstruct,
  silktrap, burningbulwark (Wide Guard / Quick Guard / Mat Block do NOT share the stall counter).
- `TAINT_ACTIVATE`: After You, Quash, Quick Claw, Custap Berry, Dancer, Instruct -> turn tainted
  (its order is not a pure Speed comparison).

**Start-turn rule** (`_start_turn`): a condition or volatile set during turn 0 or after the
residual tick (`|upkeep|` seen) starts at `turn + 1`, because the first tick it faces is next turn's.

**OTS** (`|showteam|`): `ots[side] = [{"species", "id", "item" (id), "ability" (id), "moves" [ids],
"nature", "gender"}]` (EVs hidden). Only when the opponent accepted Open Team Sheets: 15 of 1,000
ladder games (Bo3 forces it).

**data/opp_actions.json**: `{"targets": ["protect", "fakeout", "trickroom"], "<target>": {"cells":
{key: p}, "parents": {key: p}, "species_rel": {species: factor}, "n_rows", "n_pos"}}`. Current
values: protect `new|a0|h2` 0.0975, `rev|c0|a1|h2` 0.1832, `rev|c1|a1|h2` 0.0411, `rev|c2|a1|h2`
0.2931 (n_rows 137,107); fakeout `new|lead` 0.0748, `rev|back` 0.5334 (n_rows 48,862);
trickroom `new|a0` 0.0228, `rev|a0` 0.213 (n_rows 119,246).

## 4. Public API

BattleMemory (`src/battle_memory.py`; attributes `turn, mons, mega_used {side: turn|None},
weather, conditions {(scope, name): Condition}, history, actions {turn: [Action]}, taint {turn:
set}, first_mover {turn: Action}, ots, active {'p1a': name}, repaired`):
- `feed(p: list[str]) -> None` - consume one split line.
- `mon(ident)`, `mon_by(side, name)` -> MonRecord | None.
- `ots_set(ident_or_species, side=None) -> dict | None` - matches species id; a Mega form
  matches its base (`Golisopod-Mega` -> Golisopod sheet).
- `active_mons(side) -> [MonRecord]` (fainted ones included until replaced).
- `mega_available(side) -> bool`.
- `protect_success_prob(ident, turn=None) -> float` - `1 / 3**min(chain, 6)` if the last
  successful Protect was on `turn - 1`, else 1.0.
- `speed_flags(ident) -> {item_consumed, status, slow_start, turns_since_switch_in}`.
- `condition(scope, name)`, `terrain()` -> Condition | None.
- `turns_left(cond, now=None) -> (min, max) | None` - counts turn `now`; `(0, 0)` if ended/None;
  None = open-ended (hazards, permanent weather).
- `volatile_left(ident, name, now=None) -> int`.
- `turn_order(turn) -> [Action]` - chosen, non-drag, in resolution order.
- `speed_pairs(turn) -> [(faster, slower)]` - consecutive same-priority moves on an untainted turn.
- `BattleMemoryMixin.memory_for(battle) -> BattleMemory` (keyed by `battle.battle_tag`).
- `repair_mega_forms(battle, mem) -> None`.

opp_actions (`src/opp_actions.py`; `MAX_P=0.98`, `DEFAULT_CELL=0.05`):
- `FoeCtx(species, turn, age, lead, known_moves, moves_complete, protect_chain, protect_uses,
  hp_frac)`; `ActionProbs(fakeout, protect, trickroom=0.0)`.
- `foe_ctx(mem, side, name, turn, known_moves=(), moves_complete=False, hp_frac=1.0) -> FoeCtx`.
- `action_probs(ctx, rates=None) -> ActionProbs`.
- Helpers used by the fit tool/tests: `base_species`, `protect_revealed`, `protect_keys`,
  `fakeout_keys`, `trickroom_keys`, `KEYS`, `species_applies`, `cell_p`, `RATES_PATH`, `_rates`.

## 5. Flows

A. Live feed (`BattleMemoryMixin._handle_battle_message`; mix in BEFORE the Player base:
`class VGCPilot(BattleMemoryMixin, DoublesPilot)`):
1. For a `>battle-...` block, a fresh memory on `|init|`; feed every line of the block FIRST.
2. Then `super()._handle_battle_message` (poke_env updates, may call `choose_move`), so memory
   is complete when the pilot decides. Memory `turn` equals `battle.turn` (checked live, 6 battles).
3. Then `repair_mega_forms`: re-applies the logged Mega form from the poke_env gen-9 pokedex via
   `Pokemon._update_from_pokedex` (poke_env maps `Garchompite Z` to Garchomp-Mega, Spe 92,
   instead of Garchomp-Mega-Z, Spe 151).

B. Main handlers: `switch`/`drag` (species, `switch_in_turn`, `active` slot, clears protect chain,
volatiles, slow_start; chosen only if not drag, not after upkeep and no move yet this turn);
`detailschange` then `-mega` (exact form incl. Z, stone, `mega_used[side]`; `|detailschange|`
always immediately precedes `|-mega|` in 5,006 replays); `move` (ignored if any `[from]` tag
other than `[from]lockedmove`: Dancer/Instruct/Sleep Talk copies are not actions; Protect-family
waits for `-fail`/`-singleturn` to update the chain); `cant`; `faint`; `-status`/`-curestatus`;
`-item` (item id) / `-enditem` (consumed); `-start`/`-end` (Slow Start, VOLATILES);
`-weather` (`[upkeep]` lines ignored, `none` ends it); `-fieldstart`/`-fieldend` (a new terrain
replaces the old); `-sidestart`/`-sideend` (Spikes/Toxic Spikes stack `layers`); `-activate`
(taint); `showteam` (OTS); `turn` (resets per-turn flags); `upkeep`.

C. Foe action probability (`VGCPilot._foe_probs` per foe mon each turn, unless
`DOUBLES_FOE_ACTIONS=0`; `LadderOpponent._humanise` uses it for its OWN mons with their full
move list and `moves_complete=True`, so it gives P(uses it | carries it)):
1. `foe_ctx`: moves seen in turns `< turn` + `known_moves` (VGCPilot adds the OTS moves and sets
   `moves_complete` when a sheet exists); `age = max(turn - 1 - switch_in_turn, 0)` (0 = Fake Out
   legal); `lead = turn == 1`; chain counts only if the last success was `turn - 1`. Works both
   with `mem.turn == turn` (pilot) and `mem.turn == turn - 1` (fit tool).
2. Keys: protect revealed -> `rev|c{min(chain,2)}|a{min(age,1)}|h{0,1,2}` else
   `new|a{min(age,3)}|h..` (h0: hp <= 0.5, h1: < 1.0, h2: full); fakeout `{rev|new}|{lead|back}`;
   trickroom `{rev|new}|a{min(age,2)}`. Fine cell -> parent -> 0.05.
3. `p = cell * species_rel[base species]` only while the move is not revealed; clamp [0, 0.98].
4. Fake Out = 0 when `age > 0`. With `moves_complete`, moves not on the sheet are 0.
5. If fakeout + protect > 0.98 they are scaled to sum 0.98; Trick Room (if the file has the table)
   is capped to the leftover `0.98 - fakeout - protect`.

## 6. Invariants

- `feed` ignores lines with fewer than 2 fields and events without a handler (malformed known
  events can still raise; the live mixin does not catch).
- Exactly one Mega per side; `mega_form` contains "Mega" and `_id(item) == _id(mega_stone)`.
- Tailwind lasts 4 turns (930/930 in replays); Trick Room / weather / terrain 5 in > 90%.
- Protect on the 2nd consecutive use fails ~2/3 (real replays 67%; test accepts 0.58-0.75).
- Every OTS item equals the stone that later Megas (real replays).
- `first_mover[turn]` is a chosen `move`/`cant` action.
- `foe_ctx` gives the same features under both call conventions (fit/inference parity).
- `fakeout + protect + trickroom <= 0.98`.

## 7. Config, env vars, constants

| name | default | where read |
|---|---|---|
| `DOUBLES_FOE_ACTIONS` | `1` | `src/vgc_pilot.py::VGCPilot.__init__` (0 = foe actions off) |
| `MAX_P`, `DEFAULT_CELL` | 0.98, 0.05 | `src/opp_actions.py` |
| fit `SHRINK` | protect 3, fakeout 1, trickroom 3 | `tools/build_opp_actions.py` (species factor toward 1) |
| fit `SMOOTH`, `MIN_SPECIES_N` | 20 pseudo-rows, 5 | `tools/build_opp_actions.py` |

Refit: `python tools/build_opp_actions.py [--dry-run]` (needs `data/showdown_replays/`).

## 8. Tests

- `python tests/test_battle_memory.py` (25): 20 synthetic (Mega/Z form, copied moves, cant,
  chosen vs pivot vs drag switches, speed pairs and taint, weather/terrain/Trick Room/Tailwind
  timing, hazard layers, Protect chain, OTS, speed flags, `repair_mega_forms` with poke_env,
  Taunt/Encore/Yawn) + 5 on real replays from `data/showdown_replays/` (each returns early,
  and still prints PASS, when that directory is absent; the OTS-item test got its skip guard
  on 2026-11-18).
- `python tests/test_opp_actions.py` (11): hand-made rate tables, both `foe_ctx` conventions,
  OTS completeness, parent fallback, Trick Room leftover; real-file check skipped if missing.
- Related: `tests/test_mega_model.py`, `tests/test_ladder_opp.py`, `tests/test_vgc_pilot.py`,
  `tests/test_turn_sim.py` build memories too. All run in `bash tools/verify.sh`.

## 9. Gotchas and known issues

- `data/showdown_replays/` is NOT in git and absent in the 2026-11-18 checkout. All 5 real-replay
  tests then return early, so on such a host the real-replay checks are not exercised even
  though `bash tools/verify.sh` reaches `ALL PASS`. Fixed 2026-11-18:
  `test_real_replays_ots_item_matches_the_stone_that_later_megas` had no skip guard and failed
  with `(0, 0)`, which blocked the gate on hosts without the replays.
- Mons are keyed by nickname: two same-named mons on different sides are separate records, but
  `repair_mega_forms` matches poke_env mons by `mon.name` across BOTH teams and records
  `(name, form)` without side, so a same-named unmegaed mon on the other side could be repaired.
  It also uses private poke_env API (`_update_from_pokedex`, `_handle_battle_message`, `_battles`).
- `Action.priority` is the DB base priority: Prankster, Gale Wings, Grassy Glide, Trick Room
  quirks are not applied, so `speed_pairs` callers must still discount them.
- `MonRecord.item` is an id after `-item` but the raw stone name after `-mega`; compare with `_id`.
- A Protect/Fake Out seen only on an OTS counts as revealed (treated like already used), which
  probably overstates its rate.
- `trickroom` probability is only meaningful while Trick Room is not up; the caller must check.
- Fit facts (5,006 replays, 2026-10-16): Protect 10.9% and Fake Out 3.2% of decision points;
  Protect is flat across age (0.10-0.12) but 0.23 when revealed and not used last turn; Fake Out
  0.09 at age 0, ~0 after, 0.53 when revealed. Holdout log-loss (fit even files, score odd):
  Protect flat 0.3482 -> cells 0.3358 -> cells x species 0.3148; Fake Out 0.2985 -> 0.2784 ->
  0.1576. The `trickroom` table was added with the support layer (2026-10-20).
- Not tracked: foe switch prediction, back-slot Megas, Unburden/Quick Feet use of `speed_flags`.

## 10. How to change safely

1. New protocol event: add `_on_<event>` in `battle_memory_parser.py`, a synthetic test in
   `tests/test_battle_memory.py`, and keep fields in `battle_memory_types.py`.
2. Changing `foe_ctx` or cell keys changes the fitted features: refit `data/opp_actions.json`
   with replays, compare the `--dry-run` log-loss with the numbers above, then run
   `tests/test_opp_actions.py`, `tests/test_ladder_opp.py`, `tests/test_vgc_pilot.py`.
3. Changing Mega fields: also refit `data/mega_rates.json` (`tools/build_mega_rates.py`) and run
   `tests/test_mega_model.py`.
4. Keep `BattleMemory` free of poke_env imports (only `repair_mega_forms` imports it lazily).
5. Run `bash tools/verify.sh`; the 5 real-replay tests only exercise anything where
   `data/showdown_replays/` exists (see Gotchas).

## Related docs

- [damage.md](damage.md) - mega_model (reads BattleMemory), speed model
- [pilots.md](pilots.md) - VGCPilot, LadderOpponent, DoublesPilot
- [turn-sim.md](turn-sim.md) - how foe action probabilities branch the simulated turn
- [foundation.md](foundation.md) - regmc_db (move priority), paths
- [../reference/data-files.md](../reference/data-files.md) - opp_actions.json, mega_rates.json, replays
- [../runbooks/failure-modes.md](../runbooks/failure-modes.md) - symptom -> fix
