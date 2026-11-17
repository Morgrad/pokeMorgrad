# src/ module reference

Verified by reading the code (line cites are `file:line`). "Unclear" = could not be established from the code alone.
Imports below are intra-repo (`src.*`) only. Dependency direction: arrows mean "imports".

## Contents
- [Dependency map](#dependency-map)
- [Foundation: paths, regmc_db, showdown_validator](#paths-regmc_db-showdown_validator)
- [Damage stack: damage, opp_model, speed_model, mega_model, battle_memory, battle_memory_parser, battle_memory_types, doubles_eval, doubles_pilot, smart_player](#damage-stack)
- [GA: ga_core (by section), battle, eval, audit_before_launch](#ga_corepy)
- [BC stack (torch): state_encoder, bc_model, bc_player, bc_train](#bc-stack-torch)
- [Env vars read by src/](#env-vars-read-by-src)

## Dependency map
## Dependency map
```
paths  <-- regmc_db, state_encoder, showdown_validator, damage, opp_model, ga_core, bc_player, bc_train, eval
regmc_db <-- damage, ga_core, audit_before_launch
damage <-- smart_player, doubles_eval, opp_model, speed_model, doubles_pilot
opp_model <-- speed_model
regmc_db <-- battle_memory   (move priority); battle_memory <-- vgc_pilot; speed_model + doubles_eval + battle_memory <-- turn_sim <-- doubles_pilot (flag); battle_memory <-- opp_actions <-- vgc_pilot
opp_model, doubles_eval, smart_player <-- doubles_pilot
battle <-- ga_core, eval            (battle lazily imports bc_player / doubles_pilot / vgc_pilot)
state_encoder <-- bc_model <-- bc_player, bc_train ; state_encoder <-- bc_player, bc_train
ga_core <-- eval, audit_before_launch ; ga_core <-- run/*
battle_memory <-- battle_memory_parser, battle_memory_types
bc_model <-- state_encoder
bc_player <-- bc_model, state_encoder
bc_train <-- bc_model, state_encoder
opp_actions <-- battle_memory
pilot_actions <-- doubles_eval, support_value, pilot_world
pilot_sim_input <-- doubles_eval, opp_model, speed_model, turn_sim, pilot_world
pilot_support <-- None
pilot_world <-- damage, opp_model, speed_model, doubles_eval, mega_model, smart_player
player_factory <-- vgc_pilot
replay_filters <-- ga_core
smart_player <-- damage
speed_model <-- damage, opp_model, mega_model
state_encoder <-- None
support_value <-- damage
turn_sim <-- doubles_eval, turn_sim_lookahead, turn_sim_types
turn_sim_lookahead <-- doubles_eval, support_value, turn_sim_types
turn_sim_types <-- damage, doubles_eval, support_value, battle_memory
vgc_pilot <-- opp_actions, battle_memory, doubles_pilot, mega_model, opp_model
```
- Torch-importing modules: `state_encoder` (torch at `state_encoder.py:30`), `bc_model`, `bc_player`, `bc_train`.
- Torch-free: `paths, regmc_db, showdown_validator, damage, opp_model, speed_model, mega_model, battle_memory (poke_env only imported inside `repair_mega_forms`), doubles_eval, smart_player, doubles_pilot, vgc_pilot, ga_core, battle, eval, decision_logger, ga_genome, ladder_opp, meta_weights, opp_actions, pilot_actions, pilot_sim_input, pilot_support, pilot_world, player_factory, replay_filters, support_value, turn_sim, turn_sim_lookahead, turn_sim_types`.
  `battle` reaches torch only through the lazy `BCPlayer` import (`battle.py:84-86`); `DoublesPilot` import is also lazy (`battle.py:87-89`).

---
## Dependency map
```
paths  <-- regmc_db, state_encoder, showdown_validator, damage, opp_model, ga_core, bc_player, bc_train, eval
regmc_db <-- damage, ga_core, audit_before_launch
damage <-- smart_player, doubles_eval, opp_model, speed_model, doubles_pilot
opp_model <-- speed_model
regmc_db <-- battle_memory   (move priority); battle_memory <-- vgc_pilot; speed_model + doubles_eval + battle_memory <-- turn_sim <-- doubles_pilot (flag); battle_memory <-- opp_actions <-- vgc_pilot
opp_model, doubles_eval, smart_player <-- doubles_pilot
battle <-- ga_core, eval            (battle lazily imports bc_player / doubles_pilot / vgc_pilot)
state_encoder <-- bc_model <-- bc_player, bc_train ; state_encoder <-- bc_player, bc_train
ga_core <-- eval, audit_before_launch ; ga_core <-- run/*
battle_memory <-- battle_memory_parser, battle_memory_types
bc_model <-- state_encoder
bc_player <-- bc_model, state_encoder
bc_train <-- bc_model, state_encoder
opp_actions <-- battle_memory
pilot_actions <-- doubles_eval, support_value, pilot_world
pilot_sim_input <-- doubles_eval, opp_model, speed_model, turn_sim, pilot_world
pilot_support <-- None
pilot_world <-- damage, opp_model, speed_model, doubles_eval, mega_model, smart_player
player_factory <-- vgc_pilot
replay_filters <-- ga_core
smart_player <-- damage
speed_model <-- damage, opp_model, mega_model
state_encoder <-- None
support_value <-- damage
```
- Torch-importing modules: `state_encoder` (torch at `state_encoder.py:30`), `bc_model`, `bc_player`, `bc_train`.
- Torch-free: `paths, regmc_db, showdown_validator, damage, opp_model, speed_model, mega_model, battle_memory (poke_env only imported inside `repair_mega_forms`), doubles_eval, smart_player, doubles_pilot, vgc_pilot, ga_core, battle, eval, decision_logger, ga_genome, ladder_opp, meta_weights, opp_actions, pilot_actions, pilot_sim_input, pilot_support, pilot_world, player_factory, replay_filters, support_value`.
  `battle` reaches torch only through the lazy `BCPlayer` import (`battle.py:84-86`); `DoublesPilot` import is also lazy (`battle.py:87-89`).

---
## Dependency map
```
paths  <-- regmc_db, state_encoder, showdown_validator, damage, opp_model, ga_core, bc_player, bc_train, eval
regmc_db <-- damage, ga_core, audit_before_launch
damage <-- smart_player, doubles_eval, opp_model, speed_model, doubles_pilot
opp_model <-- speed_model
regmc_db <-- battle_memory   (move priority); battle_memory <-- vgc_pilot; speed_model + doubles_eval + battle_memory <-- turn_sim <-- doubles_pilot (flag); battle_memory <-- opp_actions <-- vgc_pilot
opp_model, doubles_eval, smart_player <-- doubles_pilot
battle <-- ga_core, eval            (battle lazily imports bc_player / doubles_pilot / vgc_pilot)
state_encoder <-- bc_model <-- bc_player, bc_train ; state_encoder <-- bc_player, bc_train
ga_core <-- eval, audit_before_launch ; ga_core <-- run/*
battle_memory <-- battle_memory_parser, battle_memory_types
bc_model <-- state_encoder
bc_player <-- bc_model, state_encoder
bc_train <-- bc_model, state_encoder
opp_actions <-- battle_memory
pilot_actions <-- doubles_eval, support_value, pilot_world
pilot_sim_input <-- doubles_eval, opp_model, speed_model, turn_sim, pilot_world
pilot_support <-- None
pilot_world <-- damage, opp_model, speed_model, doubles_eval, mega_model, smart_player
player_factory <-- vgc_pilot
```
- Torch-importing modules: `state_encoder` (torch at `state_encoder.py:30`), `bc_model`, `bc_player`, `bc_train`.
- Torch-free: `paths, regmc_db, showdown_validator, damage, opp_model, speed_model, mega_model, battle_memory (poke_env only imported inside `repair_mega_forms`), doubles_eval, smart_player, doubles_pilot, vgc_pilot, ga_core, battle, eval, decision_logger, ga_genome, ladder_opp, meta_weights, opp_actions, pilot_actions, pilot_sim_input, pilot_support, pilot_world, player_factory`.
  `battle` reaches torch only through the lazy `BCPlayer` import (`battle.py:84-86`); `DoublesPilot` import is also lazy (`battle.py:87-89`).

---
## Dependency map
```
paths  <-- regmc_db, state_encoder, showdown_validator, damage, opp_model, ga_core, bc_player, bc_train, eval
regmc_db <-- damage, ga_core, audit_before_launch
damage <-- smart_player, doubles_eval, opp_model, speed_model, doubles_pilot
opp_model <-- speed_model
regmc_db <-- battle_memory   (move priority); battle_memory <-- vgc_pilot; speed_model + doubles_eval + battle_memory <-- turn_sim <-- doubles_pilot (flag); battle_memory <-- opp_actions <-- vgc_pilot
opp_model, doubles_eval, smart_player <-- doubles_pilot
battle <-- ga_core, eval            (battle lazily imports bc_player / doubles_pilot / vgc_pilot)
state_encoder <-- bc_model <-- bc_player, bc_train ; state_encoder <-- bc_player, bc_train
ga_core <-- eval, audit_before_launch ; ga_core <-- run/*
battle_memory <-- battle_memory_parser, battle_memory_types
bc_model <-- state_encoder
bc_player <-- bc_model, state_encoder
bc_train <-- bc_model, state_encoder
opp_actions <-- battle_memory
doubles_pilot <-- doubles_eval, support_value, turn_sim
decision_logger <-- ga_core
ga_genome <-- ga_core
ladder_opp <-- battle
mega_model <-- battle_memory, damage
meta_weights <-- regmc_db
```
- Torch-importing modules: `state_encoder` (torch at `state_encoder.py:30`), `bc_model`, `bc_player`, `bc_train`.
- Torch-free: `paths, regmc_db, showdown_validator, damage, opp_model, speed_model, mega_model, battle_memory (poke_env only imported inside `repair_mega_forms`), doubles_eval, smart_player, doubles_pilot, vgc_pilot, ga_core, battle, eval, decision_logger, ga_genome, ladder_opp, meta_weights, opp_actions`.
  `battle` reaches torch only through the lazy `BCPlayer` import (`battle.py:84-86`); `DoublesPilot` import is also lazy (`battle.py:87-89`).

---
## Dependency map
```
paths  <-- regmc_db, state_encoder, showdown_validator, damage, opp_model, ga_core, bc_player, bc_train, eval
regmc_db <-- damage, ga_core, audit_before_launch
damage <-- smart_player, doubles_eval, opp_model, speed_model, doubles_pilot
opp_model <-- speed_model
regmc_db <-- battle_memory   (move priority); battle_memory <-- vgc_pilot; speed_model + doubles_eval + battle_memory <-- turn_sim <-- doubles_pilot (flag); battle_memory <-- opp_actions <-- vgc_pilot
opp_model, doubles_eval, smart_player <-- doubles_pilot
battle <-- ga_core, eval            (battle lazily imports bc_player / doubles_pilot / vgc_pilot)
state_encoder <-- bc_model <-- bc_player, bc_train ; state_encoder <-- bc_player, bc_train
ga_core <-- eval, audit_before_launch ; ga_core <-- run/*
battle_memory <-- battle_memory_parser, battle_memory_types
bc_model <-- state_encoder
bc_player <-- bc_model, state_encoder
bc_train <-- bc_model, state_encoder
doubles_pilot <-- doubles_eval, support_value, turn_sim
decision_logger <-- ga_core
ga_genome <-- ga_core
ladder_opp <-- battle
mega_model <-- battle_memory, damage
meta_weights <-- regmc_db
```
- Torch-importing modules: `state_encoder` (torch at `state_encoder.py:30`), `bc_model`, `bc_player`, `bc_train`.
- Torch-free: `paths, regmc_db, showdown_validator, damage, opp_model, speed_model, mega_model, battle_memory (poke_env only imported inside `repair_mega_forms`), doubles_eval, smart_player, doubles_pilot, vgc_pilot, ga_core, battle, eval, decision_logger, ga_genome, ladder_opp, meta_weights`.
  `battle` reaches torch only through the lazy `BCPlayer` import (`battle.py:84-86`); `DoublesPilot` import is also lazy (`battle.py:87-89`).

---
## Dependency map
```
paths  <-- regmc_db, state_encoder, showdown_validator, damage, opp_model, ga_core, bc_player, bc_train, eval
regmc_db <-- damage, ga_core, audit_before_launch
damage <-- smart_player, doubles_eval, opp_model, speed_model, doubles_pilot
opp_model <-- speed_model
regmc_db <-- battle_memory   (move priority); battle_memory <-- vgc_pilot; speed_model + doubles_eval + battle_memory <-- turn_sim <-- doubles_pilot (flag); battle_memory <-- opp_actions <-- vgc_pilot
opp_model, doubles_eval, smart_player <-- doubles_pilot
battle <-- ga_core, eval            (battle lazily imports bc_player / doubles_pilot / vgc_pilot)
state_encoder <-- bc_model <-- bc_player, bc_train ; state_encoder <-- bc_player, bc_train
ga_core <-- eval, audit_before_launch ; ga_core <-- run/*
battle_memory <-- battle_memory_parser, battle_memory_types
bc_model <-- state_encoder
bc_player <-- bc_model, state_encoder
bc_train <-- bc_model, state_encoder
doubles_pilot <-- doubles_eval, support_value, turn_sim
decision_logger <-- ga_core
```
- Torch-importing modules: `state_encoder` (torch at `state_encoder.py:30`), `bc_model`, `bc_player`, `bc_train`.
- Torch-free: `paths, regmc_db, showdown_validator, damage, opp_model, speed_model, mega_model, battle_memory (poke_env only imported inside `repair_mega_forms`), doubles_eval, smart_player, doubles_pilot, vgc_pilot, ga_core, battle, eval, decision_logger`.
  `battle` reaches torch only through the lazy `BCPlayer` import (`battle.py:84-86`); `DoublesPilot` import is also lazy (`battle.py:87-89`).

---
## Dependency map
```
paths  <-- regmc_db, state_encoder, showdown_validator, damage, opp_model, ga_core, bc_player, bc_train, eval
regmc_db <-- damage, ga_core, audit_before_launch
damage <-- smart_player, doubles_eval, opp_model, speed_model, doubles_pilot
opp_model <-- speed_model
regmc_db <-- battle_memory   (move priority); battle_memory <-- vgc_pilot; speed_model + doubles_eval + battle_memory <-- turn_sim <-- doubles_pilot (flag); battle_memory <-- opp_actions <-- vgc_pilot
opp_model, doubles_eval, smart_player <-- doubles_pilot
battle <-- ga_core, eval            (battle lazily imports bc_player / doubles_pilot / vgc_pilot)
state_encoder <-- bc_model <-- bc_player, bc_train ; state_encoder <-- bc_player, bc_train
ga_core <-- eval, audit_before_launch ; ga_core <-- run/*
battle_memory <-- battle_memory_parser, battle_memory_types
bc_model <-- state_encoder
bc_player <-- bc_model, state_encoder
bc_train <-- bc_model, state_encoder
```
- Torch-importing modules: `state_encoder` (torch at `state_encoder.py:30`), `bc_model`, `bc_player`, `bc_train`.
- Torch-free: `paths, regmc_db, showdown_validator, damage, opp_model, speed_model, mega_model, battle_memory (poke_env only imported inside `repair_mega_forms`), doubles_eval, smart_player, doubles_pilot, vgc_pilot, ga_core, battle, eval`.
  `battle` reaches torch only through the lazy `BCPlayer` import (`battle.py:84-86`); `DoublesPilot` import is also lazy (`battle.py:87-89`).

---
```
paths  <-- regmc_db, state_encoder, showdown_validator, damage, opp_model, ga_core, bc_player, bc_train, eval
regmc_db <-- damage, ga_core, audit_before_launch
damage <-- smart_player, doubles_eval, opp_model, speed_model, doubles_pilot
opp_model <-- speed_model
regmc_db <-- battle_memory   (move priority); battle_memory <-- vgc_pilot; speed_model + doubles_eval + battle_memory <-- turn_sim <-- doubles_pilot (flag); battle_memory <-- opp_actions <-- vgc_pilot
opp_model, doubles_eval, smart_player <-- doubles_pilot
battle <-- ga_core, eval            (battle lazily imports bc_player / doubles_pilot / vgc_pilot)
state_encoder <-- bc_model <-- bc_player, bc_train ; state_encoder <-- bc_player, bc_train
ga_core <-- eval, audit_before_launch ; ga_core <-- run/*
```
- Torch-importing modules: `state_encoder` (torch at `state_encoder.py:30`), `bc_model`, `bc_player`, `bc_train`.
- Torch-free: `paths, regmc_db, showdown_validator, damage, opp_model, speed_model, mega_model, battle_memory (poke_env only imported inside `repair_mega_forms`), doubles_eval, smart_player, doubles_pilot, vgc_pilot, ga_core, battle, eval`.
  `battle` reaches torch only through the lazy `BCPlayer` import (`battle.py:84-86`); `DoublesPilot` import is also lazy (`battle.py:87-89`).

---

## paths.py (46 lines)
Single source of truth for repo-relative locations.
- `REPO_ROOT`: `POKEMORGRAD_ROOT` env (must contain `data/`, else `RuntimeError`, `paths.py:14-24`), else parent of `src/`.
- `data_path(*p)`, `output_path(*p)`, `src_path(*p)`, `showdown_dir()` (env `SHOWDOWN_DIR`, default `~/pokemon-showdown`, `paths.py:43-44`).
- Imports nothing from src. Gotcha: `ga_core` does not use `showdown_dir()` (see ga_core Island section).

## regmc_db.py (397 lines)
Canonical, torch-free data layer over `data/regmc_db.json` (cached with `lru_cache`).
- Lookups: `get_species/get_item/get_move`, `all_species`, `all_species_base` (forme is None), `normalize_species_name` (strips `(M)/(F)` and nicknames), `species_has_ability` (formes inherit from base or sibling formes), `species_can_learn`.
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

### opp_model.py (~155 lines)
Torch-free, poke_env-free model of hidden opposing builds.
- `Build` dataclass (weight, nature, evs, stats, item, form, form_stats; `max_hp`); `opponent_builds(species, k=None, item=None, moves_seen=(), ability=None)`: with >= 5 real sets in `data/species_archetypes.json` (via `src/archetypes.py`) it returns the top `ARCHETYPE_K=6` builds of the posterior given the revealed item / moves / ability / Mega form (`form_stats` = stats after the Mega); otherwise up to `TOP_K=3` marginal builds from `data/species_build_priors.json`, else a generic spread (Adamant/Modest, 32 HP / 32 offense / 2 Spe). `item_distribution` / `move_distribution(species, item, moves_seen)` give the marginals ({} without real sets). See STATE.md §5.24.
- `_prior_key` falls back to the base species for `-Mega` forms; `resolve_species`, `stats_for`, `ability_distribution(species, known_ability=None)` -> `{ability id: prob}` (a Mega form returns its DB Mega ability with certainty, because the priors hold the paste/pre-Mega ability) from `data/species_ability_priors.json` (revealed ability = certain, DB abilities uniform if no prior); `immunity_prob(species, move_type, ability)` is built on it with the `IMMUNITY_ABILITIES` map. LEVEL=50.
- Imports `archetypes`, `damage`, `paths`. Importers: doubles_pilot, speed_model, tests.

### archetypes.py (new 2026-10-16)
Pure posterior over real-set archetypes (item+nature groups per species, `data/species_archetypes.json`). `posterior(entry, item, moves_seen, ability, form)` -> `[(weight, archetype)]`: count x P(evidence|group), item mismatch x0.02, smoothed move/ability likelihood (K=2, floor 0.02), Mega-form filter with fallback. `item_distribution`, `move_distribution`, `load_table`. Tests: `tests/test_archetypes.py`, `tests/test_mega_z_lines.py`.

### speed_model.py (~105 lines, new 2026-10-16, stage 1 of the new VGC pilot)
Pure (torch-free, poke_env-free) probability that we move before an opposing mon. See STATE.md §5.22 for the plan.
- `SpeedMods(stage, paralyzed, tailwind, scarf, weather, terrain)`: battle-time modifiers on one mon's Speed. `effective_speed(stat, mods, ability)`: floor after the stage multiplier, then Scarf x1.5, weather/terrain speed ability x2 (`SPEED_ABILITIES`: swiftswim/rain, chlorophyll/sun, sandrush/sand, slushrush/snow, surgesurfer/electric), Tailwind x2, paralysis x0.5.
- `SpeedHypothesis(weight, stat, ability, scarf=False, mega_stat=None)`; `SpeedBelief(hypotheses)` (weights renormalized): `speeds(mods, mega)`, `p_faster(our_speed, mods, trick_room, mega)` (`mega` = P(this mon Megas now), True = 1.0: only hypotheses carrying `mega_stat` can Evolve, each with `conditional_q(mega, their total weight)`, split into post/pre-Mega speed) (ties 0.5, Trick Room inverts, empty belief = 0.5).
- `belief_for(species, known_ability=None, item=None, moves_seen=())`: opp_model builds (conditioned on item/moves) x ability distribution; a Choice Scarf set carries `scarf`, a Mega set carries `mega_stat`. Stage 1 = prior only. Stage 2 (not built): `observe_*` to reweight from observed move order.
- Not modelled: Unburden/Quick Feet/Slow Start, Quick Claw/Custap/Lagging Tail/Stall. (Unrevealed Scarf and Mega speed are modelled via archetypes.)
- Tests: `tests/test_speed_model.py` (9).

### battle_memory.py (new 2026-10-16, step 2 of the new VGC pilot)
`BattleMemory.feed(split_line)` is pure (poke_env-free): one Showdown protocol line in, state out. `BattleMemoryMixin` (put BEFORE the poke_env Player base) overrides `_handle_battle_message`, feeds every line of a block first, then calls super, so memory is complete when `choose_move` runs; `memory_for(battle)`. Memory keeps its own `turn` (equals `battle.turn`, checked live).
- Slots: `active` (slot -> mon name, set on switch/drag) and `active_mons(side)` (records, fainted ones until replaced).
- Mega: exact form from `|detailschange|` (always immediately before `|-mega|`), stone from `|-mega|`, `mega_used[side]`, `mega_available(side)`. `repair_mega_forms(battle, mem)` fixes a poke_env bug: `mega_evolve("Garchompite Z")` applies Garchomp-Mega (Spe 92) instead of Garchomp-Mega-Z (151); the mixin re-applies the logged form after each block.
- Conditions: `weather`, `conditions[(scope,name)]` (Trick Room, Tailwind, terrains, screens, hazards with layers) with start turn, source, setter, `history` (end_reason expired/replaced). `turns_left(cond, now)` -> (min, max) incl. the current turn; max assumes Rocks/Light Clay/Terrain Extender. Conditions set after the residual tick (turn 0, end-of-turn replacements) start next turn. Validated on 5006 real replays (Tailwind 4 turns in 930/930; Trick Room/terrain/weather 5 turns in >90%).
- Action order: `actions[turn]`, `turn_order(turn)` (chosen switches then moves/cant; `[from]` copies except lockedmove are not actions; pivot/replacement/drag switches are `chosen=False`), `first_mover[turn]`, `speed_pairs(turn)` (consecutive same-priority moves on untainted turns; taint = After You, Quash, Quick Claw, Custap, Dancer, Instruct). Caller still discounts Trick Room and Speed abilities/items.
- Protect: `protect_success_prob(ident)` = 1/3^chain for consecutive turns, fail resets (real replays: 67% fail on the 2nd use). Wide Guard/Quick Guard/Mat Block do NOT share the counter.
- Open Team Sheets: `|showteam|` is parsed into `ots[side]` (species, item, ability, moves, nature, gender; EVs are hidden); `ots_set(ident_or_species, side)` matches by species (a Mega form matches its base, nicknames handled). Validated on real replays: every OTS item equals the stone that later Mega'd. Feeding it to `opp_model.opponent_builds(species, item=, moves_seen=, ability=)` collapses the archetype posterior to the real set (to be wired in `VGCPilot._foe`). poke_env only requests OTS when the Player is built with `accept_open_team_sheet=True`; ladder games rarely have it (1.5%), Bo3 forces it.
- Speed flags: `speed_flags(ident)` -> item_consumed, status, slow_start, turns_since_switch_in (inputs for Unburden/Quick Feet/Slow Start; not yet used by speed_model).
- Per-mon volatiles (`VOLATILES`: Taunt 3, Encore 3, Yawn 2 turns; `MonRecord.volatiles` start turn, `BattleMemory.volatile_left(ident, name)`), cleared on switch / faint / `-end`. VGCPilot feeds `FoeInfo.taunt_left` and `TurnSim(tr_left=)` from memory (base pilot falls back to poke_env presence / field start turn).
- Tests: `tests/test_battle_memory.py` (25: 20 synthetic/edge-case + 5 on real replays). Live check: 6 poke_env battles on :8000, memory turn == battle.turn and Mega flags agree with poke_env.

### doubles_eval.py (171 lines)
Pure-logic joint scoring of a PAIR of attack actions (numpy + damage; no poke_env).
- Value = sum over targets of `weight * (E[capped dmg]/max_hp + KO_BONUS * P(KO))`, ally targets negative (`doubles_eval.py:135-150`).
- Constants: `KO_BONUS=1.0` (swept, `:27`), `ALLY_WEIGHT=1.0`, `MIN_GAIN=0.01`.
- Dataclasses `Hypothesis` (optional `types` overrides the combatant's types for that hypothesis, used for post-Mega forms), `Combatant, Attacker, Action`; `Evaluator` (roll cache, `p_hit = accuracy * (1 - immune)`, two attackers on one target combined via outer sum of rolls, `_hits` at `:117`); `choose_pair` (index 0 is the vanilla baseline; deviate only if gain > `min_gain`, `:153-171`).
- Explicitly not modelled: speed order, Protect/Fake Out/redirection, retaliation, secondary effects, defender item/ability modifiers (`:14-16`).

### doubles_pilot.py (~270 lines)
## regmc_db.py (397 lines)
Canonical, torch-free data layer over `data/regmc_db.json` (cached with `lru_cache`).
- Lookups: `get_species/get_item/get_move`, `all_species`, `all_species_base` (forme is None), `normalize_species_name` (strips `(M)/(F)` and nicknames), `species_has_ability` (formes inherit from base or sibling formes), `species_can_learn`.
- `parse_team(text)` parses Showdown paste into mon dicts; `validate_team(mons)` is the LOCAL legality check: 6 mons, species clause, item clause, legal item, ability, exactly 4 distinct learnable moves, EVs <= 66 total and <= 32 per stat.
- Importers: damage, ga_core, audit_before_launch. Has a `__main__` smoke test.
- Gotcha: this is the DB-based check; the authoritative check is Showdown via `showdown_validator`.

## archetypes.py (99 lines)
Opponent set posterior from real-team archetypes (data/species_archetypes.json).
An archetype is an (item, nature) group of real sets for one species (tools/build_archetypes.py).
Given what we have seen of an opposing mon (its item, moves used, ability, Mega form) this returns
a weighted list of archetypes: weight = (#sets in the group) x P(evidence | group). It is what lets
a Garchomp that used Power Gem be recognised as the Garchompite Z special set and one holding a
Choice Scarf as a physical set, instead of mixing both.

Evidence model (soft, because pastes are not exhaustive):
  - revealed item: matches the group's item or is down-weighted to MISMATCH.
  - Mega form seen (e.g. Garchomp-Mega-Z): only groups whose stone yields that form.
  - each revealed move m: P(m | group) = (c_group(m) + K * f_species(m)) / (n_group + K), floored.
  - revealed ability: same smoothed form over the group's ability counts.

Torch-free and poke_env-free: pure data in, pure data out.
- `load_table()` - Loads the archetype table from JSON data
- `posterior(entry, item=None, moves_seen=(), ability=None, form=None)` - Calculates posterior probabilities for archetypes given evidence
- `item_distribution(post)` - Returns P(item) marginalised over a posterior
- `move_distribution(post)` - Returns P(species carries move m) marginalised over a posterior (each group's move share)

## showdown_validator.py (56 lines)
`check_teams(list[str]) -> list[(ok, msg)]` validating team texts against the real Showdown format rules.
- Spawns `node src/showdown_validate.js` once per call, teams base64-encoded on stdin, timeout 60s; in-process md5-keyed `CACHE`. Missing verdicts become `(False, "no-verdict")`. The JS file itself was not read: its internals are unclear.
- Imports `paths`. Used by `ga_core.filter_legal_genomes`.

---


`DoublesPilot(SimpleHeuristicsPlayer)`: vanilla decision, then re-picks move + target of both attackers jointly when both slots chose plain damaging moves.
- Constants `LOCKED_MOVES`, `UNMODELLED_MOVES` (leave vanilla's choice), item/ability multipliers (Choice Band/Specs, Huge/Pure Power, Life Orb).
- `_attacker` (needs `mon.stats`), `_foe` (opp_model mixture; unknown species returns base), `_ally`, `_action`, `_improve` (skips on force_switch; never Megas, `VGCPilot` adds it), `choose_move` (any exception falls back to base; `stats_counter` = turns/overrides/errors).
- Env: `DOUBLES_KO_BONUS`, `DOUBLES_MIN_GAIN`, `DOUBLES_TURN_SIM` (default 1; constructor kwargs win). `use_turn_sim` (default ON since 2026-10-16) routes the decision through `_improve_sim` and `turn_sim.TurnSim`: slots whose vanilla pick is an attack, Fake Out, Protect or a switch are free (Fake Out only on `first_turn`, Protect only at `protect_counter == 0`, switches to `available_switches`, bench = `b0..` combatants via `_ally`); candidates are shortlisted and scored with `choose_pair_refined`. Inputs built by `_our_speed`, `_foe` (each hypothesis carries its Speed list), `_foe_info` (known attack moves or a Body Slam / Hyper Voice proxy, fallback speeds, `_foe_action_probs`: zeros in the base pilot, `opp_actions` in `VGCPilot`) and `_speed_mods` (stage, paralysis, Tailwind, Scarf, weather, terrain); Trick Room from `battle.fields`. Counters `sim_turns`, `sim_protect`, `sim_switch`, `sim_fakeout`.
- Imports `damage, doubles_eval, opp_model` and four helpers from `smart_player` (`_boosts_dict, _terrain_name, _type_to_db, _weather_name`). Torch-free; created lazily by `battle.make_player` for `pilot="doubles"`; `VGCPilot` subclasses it.

### turn_sim.py (new)
Pure one-turn simulation, drop-in for `doubles_eval.Evaluator` (`TurnSim(attackers, world, our_speed, foes, trick_room, ..., max_hyps, passive_cost, min_outcome_p)`, same `pair_value`/`choose_pair`).
- Plays the turn in move order (priority, switch = 8, then Speed, Trick Room reverses). `FoeInfo(moves, speeds, fakeout, protect, protect_ok)`; the order is collapsed to P(first k of our sorted actions move before this foe), using `Hypothesis.speeds` of the simulated build (fallback `FoeInfo.speeds`; Speed `None` = coin flip).
- HP is a probability vector per combatant (lazy, only touched mons are valued); an actor acts with the probability it is still alive; accuracy per hit. Single-target moves whose target already fainted retarget to the other foe (ours and the foe's).
- Foe outcomes per foe (`_kinds`): attack, Fake Out (target split by our slots' threat, set by `set_candidates`), Protect that works, nothing. Attack = mirror foe (`_plan`, cached per hypothesis combo x acting foes): the foes' (move, target) pair is the argmax of `doubles_eval` pair value from THEIR side; foe spread moves hit their own partner (applied, and avoided by the planner when it costs them).
## doubles_eval.py (180 lines)
Joint (two-slot) attack evaluation for doubles — pure logic, no poke_env.
- Core evaluation module that scores pairs of attack actions in doubles battles.
- Computes expected fraction of opposing mon's max HP removed plus KO bonus, minus same for our own ally.
- Handles hidden opposing stats through plausible build mixtures from src.opp_model.
- Supports focus-fire KO probability computation against one build at a time, then mixed.
- Provides pair_value method that evaluates simultaneous attack actions against fixed world snapshots.
- Importers: damage, support_value. Tests: `tests/test_doubles_eval.py`.
- Our actions: attack, Fake Out (flinches a foe that has not moved), Protect (`BLOCKING` = Protect family minus Endure), switch (`SWITCH`, target = bench id `b0..`, the bench mon takes the slot's hits). Switch/Protect pay `passive_cost` (0.15, env `DOUBLES_PASSIVE_COST`); two slots switching to the same bench mon = `CONFLICT`.
- `shortlist(acts, k)` and `choose_pair_refined(coarse, fine, ...)` keep the cost down (specials + top-k attacks, coarse screen, full re-score of the top pairs).
- Value = foe (HP fraction + KO_BONUS * P(KO)) minus ours (retaliation and own spread damage). With no foe actions it equals the Evaluator.
- Not modelled: foe switches / back-slot foe Mega, crits, secondary effects (other than the Fake Out flinch), items/abilities on damage, Unburden/Quick Feet/Slow Start, Quick Claw/Custap, our Protect after a Protect.
- Support layer (flag `effects`, default empty = identical behaviour): `_run` applies Snarl/Charm stage drops to later foe hits (mixture over the drop distribution, `support_value.drop_outcomes`), adds a persistence term (`_drop_gain`), Helping Hand x1.5 on the partner's attack, Taunt vs the foe `tr` outcome (`_tr_cost`), self-heals (`heal_pmf`: HP pmf shifted up by `support_value.heal_fraction`, at the actor's place in the move order, no `support_cost`), `support_cost` per other pure-support action; `shortlist` keeps every support candidate. Foul Play uses the target's Atk in `doubles_eval.Evaluator.rolls` and `_foe_rolls`. See `src/support_value.py` (pure data side: `parse_effects`, `foe_drop`, `pure_kind`, `effect_of`, `heal_fraction`, `drop_outcomes`) and `tests/test_support.py` (28).
- Lookahead (`LookAhead`, `enable_lookahead()`, flag `DOUBLES_LOOKAHEAD`, default off): replaces the persistence / `_tr_cost` heuristics with `h x (V1(s'+d) - V1(s'))`, where `s'` is the mean-field post-turn state of the best plain attack pair and `V1` the best attack pair of a coarse sim (cached per delta key `("drop", foe, dAtk, dSpA)` / `("tr",)`). `_run` accepts the weight of its branch (`wt`) so the leaf reference sim can accumulate per-hypothesis alive/HP through `_sink`. Built by `DoublesPilot._improve_sim` only when a support or stat-drop candidate exists; one LookAhead is shared by the fine and coarse sims. `tools/paired_eval.py --mode lookahead` compares it off/on.
- Tests: `tests/test_turn_sim.py` (26: order, Trick Room, priority, retaliation, unknown Speed, Mega q, retargeting, spread, mirror foe, foe-on-foe, per-hypothesis Speed, Fake Out both ways, foe Protect, our Protect/switch, switch conflict, pilot wiring with real `Pokemon`).

### ladder_opp.py (new)
`LadderOpponent(BattleMemoryMixin, SimpleHeuristicsPlayer)`, pilot name `"ladder"` in `battle.make_player` (`opp_pilot` kwarg of `run_battle_once` / `run_battle`, default `"heuristic"`). Keeps the heuristic's order, then per slot swaps in Protect / Fake Out (first turn only) at the `opp_actions.action_probs` rate for mons that carry the move; falls back to the heuristic order on error. `stats_counter` = turns / protect / fakeout / errors. Tests: `tests/test_ladder_opp.py` (5).

### meta_weights.py (new)
Opponent-team importance from ladder-replay species usage. `species_key(raw)` = `normalize_species_name` then `baseSpecies` (every forme folds into base; nicknames / gender tags dropped); `team_keys(text)`; `usage_from_replays(dir)` -> (share of replay sides carrying each species, n sides); `team_weight(text)` = mean usage of the six species, floor 0.02; `weighted_rate(outcomes, weights)`; `effective_n`. Data `data/species_ladder_usage.json` (tracked) is rebuilt by `tools/build_meta_weights.py`. Used by `ga_core._fitness`. Tests: `tests/test_meta_weights.py` (6).

### opp_actions.py (new)
Foe action prior, pure logic. `foe_ctx(mem, side, name, turn, known_moves, moves_complete, hp_frac)` -> `FoeCtx` (single feature builder, used by the fit and by `VGCPilot._foe_action_probs`); `action_probs(ctx)` -> `ActionProbs(fakeout, protect, trickroom)` (fakeout + protect capped at 0.98; Trick Room rate from the `trickroom` table: revealed x age 0/1/2+ x species factor, fills the leftover). Protect: table over revealed x chain x age x HP bucket (smoothed toward a parent cell) x species factor when not revealed; Fake Out: age 0 only, revealed x lead/back x species factor. A full OTS move set (`moves_complete`) zeroes moves the mon cannot have. Rates: `data/opp_actions.json` from `tools/build_opp_actions.py` (5006 replays; holdout logloss Protect 0.3482 flat -> 0.3148, Fake Out 0.2985 -> 0.1576). Tests: `tests/test_opp_actions.py` (9).

### mega_model.py (new)
## replay_filters.py (38 lines)
Replay filtering logic for battle data processing.
- Provides filtering functions for battle replays based on fitness, outcome, and trigger events.
- Implements a default filter that accepts top performers, near-best losers, battles with diagnostic triggers, and random samples.
- Uses trigger strings to identify terrain, weather, and Trick Room events in battle history.
- Supports configurable random sampling rate (2% by default) for unbiased data selection.
- Importers: None. Tests: `tests/test_replay_filters.py`.

## smart_player.py (202 lines)
KO-aware heuristic pilot with real damage estimation.
- Subclass of SimpleHeuristicsPlayer that replaces crude base_power scoring with real damage estimates.
- Adds KO detection, HP-aware move scoring, and predicted-damage-taken penalty for the next turn.
- Falls back to parent scoring on any exception so behavior is never strictly worse.
- Provides damage scoring functions for moves including KO bonus and damage weight calculations.
- Importers: damage. Tests: `tests/test_smart_player.py`.

## speed_model.py (127 lines)
Speed model: who moves first, as a probability (staged plan, stage 1).
## turn_sim.py (598 lines)
One-turn simulation for doubles: move order, retaliation, retargeting, Protect, Fake Out, switches.
- Implements a full turn simulation that plays out moves in proper order rather than scoring them as if they all land first.
- Handles complex battle mechanics including speed ordering, retaliation, retargeting (Showdown-style), and priority moves.
- Supports foe hypotheses with stats/types/HP/Speed, foe outcomes (attacks, Fake Out, Protect), and mirror foe behavior.
- Includes support layer for effects like Foul Play, Snarl, Charm, Helping Hand, Taunt, and self-heals.
- Provides value calculation based on HP fractions removed, KO bonuses, and damage propagation.
- Importers: damage, doubles_eval, support_value, turn_sim_lookahead, turn_sim_types. Tests: `tests/test_turn_sim.py`.

## turn_sim_lookahead.py (129 lines)
LookAhead: next-turn state-delta valuation (split from turn_sim.py).
- Implements next-turn value calculation for state deltas using coarse one-turn simulations.
- Handles leaf state calculations after best attack pairs and computes value differences.
- Manages stat drops on foes, Trick Room changes, and other state modifications.
- Provides caching of V1 values per delta to avoid recomputation.
- Importers: doubles_eval, support_value, turn_sim_types. Tests: `tests/test_turn_sim_lookahead.py`.

## turn_sim_types.py (123 lines)
Types, constants, and helpers for turn_sim. Split from turn_sim.py for modularity.
- Defines core types including FoeInfo, FoeAct, and Speeds for battle simulation.
- Contains constants for simulation parameters like MAX_HYPS, MIN_SCENARIO_P, PASSIVE_COST, etc.
- Provides helper functions for move priority, action priority, switch/protect/support detection.
- Includes utilities for pruning hypotheses, probability mass functions, and applying damage rolls.
- Importers: damage, doubles_eval, support_value, battle_memory. Tests: `tests/test_turn_sim_types.py`.

## vgc_pilot.py (128 lines)
VGC pilot (thin layer): DoublesPilot + battle memory + Mega logic.
- Thin wrapper around DoublesPilot that adds battle memory and Mega evolution logic.
- Handles Mega evolution decisions for both own Pokémon and opponent Pokémon.
- Implements logic for when to use Mega Evolution based on damage gain calculations.
- Manages foe Mega probability calculations using src.mega_model.
- Supports battle memory tracking for opponent actions, Protect success probabilities, and volatile conditions.
- Importers: opp_actions, battle_memory, doubles_pilot, mega_model, opp_model. Tests: `tests/test_vgc_pilot.py`.
- Estimates opponent speed using weighted hypotheses built from build priors.
- Handles stat stages, paralysis, Tailwind, Choice Scarf, weather/terrain speed abilities and Trick Room.
- Implements prior mixture only (stage 1) with planned reweighting from observed move order (stage 2).
- Supports Mega evolution speed calculations and effective speed computation with battle modifiers.
- Importers: damage, opp_model, mega_model. Tests: `tests/test_speed_model.py`.

## state_encoder.py (252 lines)
State encoder that converts battle dictionaries to tensors for BC model input.
- Converts battle state dictionaries into tensors for the embedding BC model.
- Handles species, move, item, and ability encoding with fixed slot order (12 slots total).
- Encodes global field state including weather, terrain, Trick Room, and Tailwind conditions.
- Provides continuous vector encoding for each Pokémon with status, boost, HP, and other stats.
- Importers: None. Tests: `tests/test_state_encoder.py`.

## support_value.py (200 lines)
Support-move layer for doubles pilot with effect handling.
- Manages support effects including Foul Play, Snarl, Charm, Helping Hand, Taunt, and Heal.
- Provides functions to parse enabled effects from environment variables.
- Implements drop outcome calculations considering ability distributions and blocking mechanics.
- Handles stat stage clamping, damage calculation, and effect value computations.
- Importers: damage. Tests: `tests/test_support_value.py`.
## pilot_actions.py (82 lines)
Pilot actions handling and target resolution for battle moves.
- Handles move targeting logic for different move types including normal, allAdjacentFoes, and allAdjacent targets.
- Implements attack candidate filtering based on move categories and flags.
- Supports special move handling like Fake Out, Protect, and support moves.
- Provides action resolution for attacks, protection, support moves, switching, and fakeout moves.
- Importers: doubles_eval, support_value, pilot_world. Tests: `tests/test_pilot_actions.py`.

## pilot_sim_input.py (59 lines)
Pilot simulation input preparation for battle simulations.
- Prepares input data for turn simulations including speed calculations, foe information, and action probabilities.
- Handles speed modifications based on abilities, items, and field conditions.
- Manages taunt tracking and Trick Room probability calculations.
- Provides foe action probabilities (Fake Out, Protect-family) for simulation inputs.
- Importers: doubles_eval, opp_model, speed_model, turn_sim, pilot_world. Tests: `tests/test_pilot_sim_input.py`.

## pilot_support.py (75 lines)
Support-move resolution logic for doubles pilot.
- Contains functions to resolve various support move effects including Taunt, Heal, Helping Hand, Snarl, Charm, and Foul Play.
- Handles battle mechanics for different support moves that affect opponent Pokémon.
- Provides basic framework for support move effect resolution in doubles format.
- Importers: None (pure logic functions). Tests: `tests/test_pilot_support.py`.

## pilot_world.py (144 lines)
Pilot world state representation and damage modeling.
- Creates world state representations for battle simulations including attacker, foe, and ally information.
- Handles Mega evolution probability calculations and conditional probabilities.
- Implements damage hypothesis generation for different Pokémon builds and forms.
- Provides speed modification calculations and immunity probability computations.
- Importers: damage, opp_model, speed_model, doubles_eval, mega_model, smart_player. Tests: `tests/test_pilot_world.py`.

## player_factory.py (90 lines)
Player factory for constructing poke_env Players for battles.
- Creates different player types based on pilot configuration (bc, doubles, ladder, vgc).
- Handles timeout players that automatically forfeit battles after turn limits.
- Manages account and server configurations for battle connections.
- Supports multi-instance battle handling with unique identifiers and battle formats.
- Importers: vgc_pilot. Tests: `tests/test_player_factory.py`.
Foe Mega prediction from real ladder replays. `candidates(mem, side, turn=None)` = active, non-fainted, not-yet-Mega'd mons of Mega-capable species while the side's Mega is unused, with `k` (turns already had the chance = turn - max(switch_in_turn+1, 1)), `ncand`, `lead`, item flags. `p_mega_now(species, k, ncand, lead, item, consumed)` = cell table (`cell_key`: k0 lead/back, k1, k2, k3+ x 1|2 candidates) x per-species factor from `data/mega_rates.json`; revealed non-stone item -> 0, consumed item -> 0.02. `foe_mega_probs(mem, side)` renormalises so a side's probabilities sum to at most 1 (one Mega per side). `conditional_q(p_now, form_mass)` turns the marginal into P(Megas | set carries the stone). `mega_gain(species, stone)` = (offence gain, Speed gain) for our own Mega choice.
- Fit: `tools/build_mega_rates.py [--dry-run]` (5006 replays, 15755 decision points). Holdout log-loss (fit even files, score odd): flat 0.693, by k only 0.628, cell table 0.601, cell x species 0.555.
- Tests: `tests/test_mega_model.py` (7).

### vgc_pilot.py
`VGCPilot(BattleMemoryMixin, DoublesPilot)`: foe Mega prediction, then DoublesPilot's decision, then our own Mega.
- Foe: `choose_move` computes `foe_mega_probs` into `_foe_mega`; `DoublesPilot._mega_prob(mon)` (0.0 in the base pilot, overridden here) feeds `_foe`, which splits each Mega-capable build's weight into post-Mega (`form_stats`) and pre-Mega stats with `conditional_q`. The post-Mega hypothesis also carries the Mega form's types (`Hypothesis.types`) and the immunity map mixes pre/post-Mega abilities.
- Own: `mega_variant(order, valid)` finds the `mega=True` twin (same move id and `move_target`); `add_mega(battle, base, mega_free, score=None)` picks the slot with the highest `score` among slots that can Mega and have a move twin (score = `mega_gain` of the held stone; ties go to the lower slot). Switch orders never Mega; at most one Mega per turn.
- No Mega "hold" rule: replay win rate shows no difference by timing (turn 1 41.9%, first-opportunity later 41.8%, delayed 43.1%, never 46.1%; confounded), so we Mega on the first opportunity.
- `stats_counter` adds `mega_opportunities / mega_used / mega_errors / foe_mega_turns / foe_mega_errors` (errors fall back to the base order). Torch-free; `battle.make_player` creates it lazily for `pilot="vgc"`. Tests: `tests/test_vgc_pilot.py` (5, synthetic orders).
- Predictive by default; no OTS use yet (`accept_open_team_sheet` is not set).

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
| 1-109 | Header + constants | `FORMAT="gen9championsvgc2026regmc"`, `UID_MAX`, `EV_BUDGET=66`, `EV_STAT_CAP=32`, `MAX_REBUILD_TRIES=20`, `BATTLE_TIMEOUT=20`, `MIN_TURNS=3`, `VAL_POOL_SIZE=30`, `TRAIN_SAMPLE_SIZE` (env `GA_TRAIN_SAMPLE`, 250, `:75`), `VAL_SPLIT_SEED=42`, early-stop (`EARLY_STOP_MIN_BATTLES=50`, `EARLY_STOP_WIN_RATE=0.15`), `CANONICAL_ITEMS`, `PROTECT_MOVES`, `FAKEOUT_MOVES` |
| 110-229 | Cached roster + data loaders | `_BASE_SPECIES`, `move_priors_for` (`data/species_move_priors.json`, top 8), `meta_items_for` (`data/meta_items.json`), `_load_teams` (resolves by basename in `data/regional_teams`; raises if a non-empty list loads zero), `regional_pool` (pool_split.json "train", else glob), `_split_train_val` (deterministic shuffle), `heldout_pool` ("holdout") |
| 230-530 | Set generation | `_legal_items_for` (lru_cache; mega stone / itemUser filtering), `_species_role` (physical/special/support), `_random_mon` (priors-first, role-matched; EVs/nature follow role; excludes "randomNormal" target moves), `_pick_item_for` (mega stone -> meta-weighted -> canonical -> any legal), `build_random_genome(constraints)` |
| 532-560 | Serialization | `genome_to_text` (Level 50, always writes `EVs:`), `text_to_genome` (None unless exactly 6 mons) |
| 562-628 | Realism constraints | `_force_move_on_slot`, `_enforce_composition` (soft: Protect and Fake Out/redirection coverage) |
| 630-701 | Legality filter | `filter_legal_genomes` (`:633`): batched `SV.check_teams`, rebuild failed slots up to 20 tries, then composition pass. Output may be SHORTER than input |
| 703-890 | Operators | `mutate_species/item/ability/nature/evs/move`, `mutate(mons, constraints, n=1-4)` on a deepcopy over free slots; `crossover` (per-slot parent pick; locked slots take the parent holding the species; species/item clause repair) |
| 892-969 | Fitness | `async evaluate(mons, opponents, idx, total)` (`:910`) |
| 967-1462 | Island model | `Island`, `ring_migrate`, `restart_showdown`, checkpoints, `breed`, `_eval_on_subset`, `run_islands` |

### Key behaviours (ga_core)
- Genome = list of 6 dicts `{species, item, ability, nature, evs, moves}`; constraints = `{slot: species}` (locked slots). Island constraint keys are stringified for JSON.
- `evaluate`: invalid genomes (local `DB.validate_team`) score 0.0; plays 50 "head" battles first and aborts if head fitness < 0.15, else plays the tail; `None` battle results are dropped from the denominator. Fitness is the meta-weighted win rate (`_fitness`, `META_WEIGHTS`, `src/meta_weights.py`; head, tail and `_eval_on_subset` all weighted). Pilot = `FITNESS_PILOT` (default `vgc`, flag `use_turn_sim` on) vs `FITNESS_OPP` (default `ladder`), via `battle.run_battle`, `min_turns=3`; `GA_PILOT=heuristic GA_OPP=heuristic` restores the old environment.
- Train/val: training pool is split with seed 42 into train / `VAL_POOL_SIZE=30` val; heldout pool is for final eval only. Per-generation opponent sample = `min(battles_per_genome, TRAIN_SAMPLE_SIZE, len(train_pool))`.
- `_SEM` is a module-global semaphore set by `run_islands`.
- `Island` (`:997`): name, constraints, population, fitness, `best_ever`, `best_val_ever`, stagnation, history, `seed_paths`; `to_dict/from_dict`.
- `inject_immigrants(island, n)` replaces the worst n; `ring_migrate(n=2)`: island i receives from i-1, replaces worst, strips foreign locked species (`_strip_species`).
- `restart_showdown` (`:1275`): `pkill -9 -f "pokemon-showdown start {port}"`, relaunch `node pokemon-showdown start {port} --no-security`, polls up to `wait_s`=60 s, retries the kill+launch once (`tries=2`), returns bool. `ensure_showdown()` (called at the start of `run_islands`) starts the server if it is down; `run_islands` raises `RuntimeError` if a mid-run restart fails, so the island exits non-zero and `ga_parallel.sh` respawns it from the last checkpoint. `run_islands` also loads the meta-weight usage file at startup and fails with a hint if it is missing.
- `save_checkpoint` writes `output/checkpoints/v6/<run_id>/gen_NNNN.json`, keeping newest plus multiples of 5; `load_latest_checkpoint` resumes.
- `breed`: elites `max(2, n//3)`, immigration rate 0.20, `filter_legal_genomes`, top up to pop size.
- `run_islands` defaults (`:1393-1400`): pop 10, gens 999, battles 800, `concurrency=int(env GA_CONCURRENCY, "3")` (evaluated at def time), immigration 0.20, stagnation_limit 5, diversity_floor 15 unique species, migration_every 5, showdown_restart_every 10. Per gen: evaluate islands sequentially (genomes within an island concurrently) -> val-evaluate the train-best -> diversity rescue (3 immigrants) -> stagnation restart (replace worst half) -> ring migration -> checkpoint every gen.
- Outputs at end (`ga_core.py:1540-1556`): `output/champions/ga_<run_id>_island_<name>.txt` and `..._train.txt`.

### Gotchas (ga_core)
- `META_ITEM_BIAS` was an unused constant and has been removed. Item choice uses meta items via `_pick_item_for`.
- Champion selection is train-best by design (STATE.md §5, val-selection dropped); `ga_<id>_island_X.txt` and `_X_train.txt` are identical in practice, val is only a fallback. The code comment now says so.
- `SHOWDOWN_DIR = paths.showdown_dir()` (env `SHOWDOWN_DIR` honored). `SHOWDOWN_PORT` is read from env at import.
- `FORMAT` and `UID_MAX` are shared with eval via import from here.
- **Correction**: The documentation was inaccurate in its claim that "Everything here is CPU/async orchestration; the only heavy dependency is poke_env". While ga_core does use poke_env for battle execution, it also uses several other significant dependencies including asyncio, subprocess, urllib, and has complex data processing logic. The statement about heavy dependencies should be clarified to reflect that the main computational load comes from battle simulation rather than from torch usage.

## opp_actions.py (163 lines)
Foe action prediction: P(a foe mon uses a Protect-family move / Fake Out / Trick Room THIS turn).
- Predicts opponent actions including Protect-family moves, Fake Out, and Trick Room usage.
- Uses data/opp_actions.json built from real ladder replays to determine action probabilities.
- Context features include species, turn number, age on field, known moves, protect chain, and HP fraction.
- Implements cell-based probability tables with fine-grained context features and parent cells for smoothing.
- Importers: battle_memory. Tests: `tests/test_opp_actions.py`.

## opp_model.py (210 lines)
Opponent build estimation (hidden stats / abilities) for battle-time damage math.
- Estimates opponent hidden stats and abilities from scraped build priors.
- Uses data/species_build_priors.json to get top-K most common (EVs, nature) builds per species.
- Handles fallback to generic spreads when no priors are available.
- Supports archetype-based estimation with posterior distributions when enough real sets exist.
- Provides ability distribution and immunity probability calculations for damage modeling.
- Importers: archetypes, damage. Tests: `tests/test_opp_model.py`.

## damage.py (287 lines)
Champions-format stat + base damage estimator.
- Mirrors Showdown's data/mods/champions/scripts.ts statModify + battle-actions damage math. Verified against Showdown for base cases.
- EV points are Champions points (0-32). Stat term uses max(2*points - 1, 0).
- Modifier coverage (all optional kwargs, defaults = no modifier):
  - crit:         1.5x damage (ignores screens)
  - burn:         0.5x physical (skipped if attacker_ability == 'Guts')
  - weather:      'rain' | 'sun' | 'sand' | 'snow'
  - terrain:      'electric' | 'grassy' | 'psychic' | 'misty'
  - attacker_boosts / defender_boosts: dict of stat -> stage (-6..+6)
  - reflect / light_screen / aurora_veil: bool
  - attacker_ability: for damage-relevant abilities
- Order of operations follows Showdown's battle-actions.modifyDamage exactly.
- Importers: doubles_eval, smart_player, speed_model. Tests: `tests/test_damage.py`.

## decision_logger.py (49 lines)
Decision logger that records battle decisions and outcomes to JSONL files.
- Records detailed battle state including teams, active mons, HP, field conditions, legal moves, chosen actions, and heuristic choices.
- Each battle gets its own JSONL file with one row per turn.
- Importers: ga_core. Tests: `tests/test_decision_logger.py`.

## doubles_pilot.py (246 lines)
Doubles pilot that improves on simple heuristics with turn simulation.
- Extends SimpleHeuristicsPlayer to make better decisions in doubles format.
- Uses turn simulation for improved move selection, including support move effects and lookahead.
- Supports various environment variables for tuning: DOUBLES_KO_BONUS, DOUBLES_MIN_GAIN, DOUBLES_TURN_SIM, DOUBLES_LOOKAHEAD.
- Importers: doubles_eval, support_value, turn_sim. Tests: `tests/test_doubles_pilot.py`.

## bc_model.py (266 lines)
Neural models + checkpoint I/O for the BC pilot.
- Two architectures live here; a checkpoint's `arch` field decides which one a loader instantiates:
  BCModel    (v2) — flat MLP trunk. The production model; bc_best.pt was trained
                    with this. OUTPUTS=6 (type/move/switch × two slots a/b).
  BCModelV3  (v3) — transformer over 12 slot tokens + 1 field token, plus a
                    per-slot target head. OUTPUTS=8.
- Callers check `model.OUTPUTS` to know whether to unpack 6 or 8 tensors
  (see bc_player._get_shared_model / choose_move).
- CHECKPOINT CONTRACT: every name and dimension below is frozen — the saved
  state_dict in output/models/bc_best.pt is keyed by these exact attribute names
  and sized by these exact constants. See the banner by the constants. Comment
  freely; renaming a head or resizing an embedding silently breaks load_state_dict.

## bc_player.py (320 lines)
BC pilot — uses poke_env's valid_orders for action legality.
- Supports v2 (MLP, 6 heads) and v3 (transformer, 8 heads with target head).
- Checkpoint `arch` field decides which. Override the model via
  BC_PILOT_PATH env var (default: output/models/bc_best.pt).
- For v3, the target head contributes to option scoring so that
  "move X targeting opp-left" and "move X targeting opp-right" get
  different scores instead of being arbitrary tie-breaks.

## bc_train.py (398 lines)
Behavioural-cloning trainer. Env: BC_DATA (default `data/training_data.jsonl`), BC_OUT (default `bc_best.pt` under `output/models/`), BC_MODEL v2|v3, BC_BATCH 256, BC_EPOCHS 30, BC_PATIENCE 3. LR=1e-3, WD=1e-5, VAL_FRAC=0.1, SEED=42.
- `BCDataset` (winner samples duplicated 2x; moves not in priors become TYPE_NONE), `slot_loss`, `run_epoch`, `build_model`, `main`.
- `main`: drops consecutive duplicate (side, turn) rows, splits battles on a second `turn==1`, 90/10 battle-level split, AdamW + cosine annealing, saves on best `val_move_acc`, early stops on `PATIENCE`.
- Gotcha: module docstring (`:4-7`) lists only BC_MODEL/BC_OUT/BC_EPOCHS/BC_PATIENCE, not BC_DATA/BC_BATCH.

---

## Env vars read by src/
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
- Flags (from main_async): `--opponents heldout|all`, `--pilot heuristic|bc|doubles|vgc|both`, `--opp heuristic|ladder` (opponent pilot), `--concurrency`; `evaluate_team` returns `(wins, games, weighted_rate)` where `weighted_rate` is `ga_core._fitness` (the GA's meta-weighted fitness), printed as `meta-weighted`, so a holdout run with `--pilot vgc --opp ladder` is comparable with GA scores; seeds `DEFAULT_SEEDS=[100,200,300]`, `TIMEOUT=20`; Wilson CI helper `wilson_ci`; `evaluate_team` runs seeds sequentially under one semaphore with `random.seed(seed)`.
- Env: `GA_CONCURRENCY` (default "3", `eval.py:27`).
- Imports `ga_core` (pools, `FORMAT`, `UID_MAX`) so it is not independent of the GA module; torch only if `bc`.
- Gotcha: the HEUR/BC/Delta comparison table only covers heuristic and bc pilots; `doubles` is not in it.
- **Correction**: eval.py imports `ga_core` for access to pools, FORMAT, and UID_MAX, but the module itself is designed to be independent of the GA core for the most part. The import is used for shared constants and data loading rather than for GA-specific logic.

## audit_before_launch.py (188 lines)
Pre-launch sanity script; logic lives in `main()` behind a `__main__` guard (importing it is silent). Run as `python -m src.audit_before_launch`.
- Nine sections: DB integrity, name sanity, mega stones, regional teams validate, fuzz 500 Umbreon-locked genomes, fuzz 500 free, 2000 mutations, 500 crossovers, baseline team.
- Uses `DB.validate_team` (local), not the Showdown validator. Seeds random with 0, 42, 1. Imports `regmc_db`, `ga_core`, `paths`.

## __init__.py
Empty initialization file. This file serves as a Python package initializer and currently contains no specific functionality or imports.

---
## ga_genome.py (821 lines)
Genetic algorithm genome builder for VGC teams.
- Generates and evolves Pokémon teams using a genetic algorithm approach.
- Handles EV distribution, species selection, item picking, ability assignment, and move selection.
- Implements constraints and realism checks to produce viable tournament teams.
- Uses move priors and meta data to guide evolution toward realistic team compositions.
- Importers: ga_core. Tests: `tests/test_ga_genome.py`.

## ladder_opp.py (77 lines)
Ladder-like opponent that mimics human behavior patterns.
- Extends SimpleHeuristicsPlayer to add Protect and Fake Out usage at human rates.
- Uses opp_actions data to determine when opponents use Protect or Fake Out moves.
- Maintains statistics on how often it applies these behaviors during battles.
- Importers: battle. Tests: `tests/test_ladder_opp.py`.

## mega_model.py (98 lines)
Foe Mega prediction: P(an opposing mon Mega Evolves THIS turn), from real ladder replays.
- Predicts the probability that an opponent will Mega evolve on their current turn.
- Rates come from data/mega_rates.json built from real ladder replays.
- Handles renormalization of probabilities across a side to ensure at most one Mega per side.
- Importers: battle_memory, damage. Tests: `tests/test_mega_model.py`.

## meta_weights.py (91 lines)
Meta weights: how much each opponent team should count, from ladder-replay species usage.
- Calculates team weights based on ladder replay data to weight opponents appropriately.
- Uses species usage data to determine how representative a team is of ladder play.
- Teams built from commonly seen species get higher weights in fitness calculations.
- Importers: regmc_db. Tests: `tests/test_meta_weights.py`.

## damage.py (287 lines)
Champions-format stat + base damage estimator.
- Mirrors Showdown's data/mods/champions/scripts.ts statModify + battle-actions damage math. Verified against Showdown for base cases.
- EV points are Champions points (0-32). Stat term uses max(2*points - 1, 0).
- Modifier coverage (all optional kwargs, defaults = no modifier):
  - crit:         1.5x damage (ignores screens)
  - burn:         0.5x physical (skipped if attacker_ability == 'Guts')
  - weather:      'rain' | 'sun' | 'sand' | 'snow'
  - terrain:      'electric' | 'grassy' | 'psychic' | 'misty'
  - attacker_boosts / defender_boosts: dict of stat -> stage (-6..+6)
  - reflect / light_screen / aurora_veil: bool
  - attacker_ability: for damage-relevant abilities
- Order of operations follows Showdown's battle-actions.modifyDamage exactly.
- Importers: doubles_eval, smart_player, speed_model. Tests: `tests/test_damage.py`.

## decision_logger.py (49 lines)
Decision logger that records battle decisions and outcomes to JSONL files.
- Records detailed battle state including teams, active mons, HP, field conditions, legal moves, chosen actions, and heuristic choices.
- Each battle gets its own JSONL file with one row per turn.
- Importers: ga_core. Tests: `tests/test_decision_logger.py`.

## doubles_pilot.py (246 lines)
Doubles pilot that improves on simple heuristics with turn simulation.
- Extends SimpleHeuristicsPlayer to make better decisions in doubles format.
- Uses turn simulation for improved move selection, including support move effects and lookahead.
- Supports various environment variables for tuning: DOUBLES_KO_BONUS, DOUBLES_MIN_GAIN, DOUBLES_TURN_SIM, DOUBLES_LOOKAHEAD.
- Importers: doubles_eval, support_value, turn_sim. Tests: `tests/test_doubles_pilot.py`.

## bc_model.py (266 lines)
Neural models + checkpoint I/O for the BC pilot.
- Two architectures live here; a checkpoint's `arch` field decides which one a loader instantiates:
  BCModel    (v2) — flat MLP trunk. The production model; bc_best.pt was trained
                    with this. OUTPUTS=6 (type/move/switch × two slots a/b).
  BCModelV3  (v3) — transformer over 12 slot tokens + 1 field token, plus a
                    per-slot target head. OUTPUTS=8.
- Callers check `model.OUTPUTS` to know whether to unpack 6 or 8 tensors
  (see bc_player._get_shared_model / choose_move).
- CHECKPOINT CONTRACT: every name and dimension below is frozen — the saved
  state_dict in output/models/bc_best.pt is keyed by these exact attribute names
  and sized by these exact constants. See the banner by the constants. Comment
  freely; renaming a head or resizing an embedding silently breaks load_state_dict.

## bc_player.py (320 lines)
BC pilot — uses poke_env's valid_orders for action legality.
- Supports v2 (MLP, 6 heads) and v3 (transformer, 8 heads with target head).
- Checkpoint `arch` field decides which. Override the model via
  BC_PILOT_PATH env var (default: output/models/bc_best.pt).
- For v3, the target head contributes to option scoring so that
  "move X targeting opp-left" and "move X targeting opp-right" get
  different scores instead of being arbitrary tie-breaks.

## bc_train.py (398 lines)
Behavioural-cloning trainer. Env: BC_DATA (default `data/training_data.jsonl`), BC_OUT (default `bc_best.pt` under `output/models/`), BC_MODEL v2|v3, BC_BATCH 256, BC_EPOCHS 30, BC_PATIENCE 3. LR=1e-3, WD=1e-5, VAL_FRAC=0.1, SEED=42.
- `BCDataset` (winner samples duplicated 2x; moves not in priors become TYPE_NONE), `slot_loss`, `run_epoch`, `build_model`, `main`.
- `main`: drops consecutive duplicate (side, turn) rows, splits battles on a second `turn==1`, 90/10 battle-level split, AdamW + cosine annealing, saves on best `val_move_acc`, early stops on `PATIENCE`.
- Gotcha: module docstring (`:4-7`) lists only BC_MODEL/BC_OUT/BC_EPOCHS/BC_PATIENCE, not BC_DATA/BC_BATCH.

---

## Env vars read by src/



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
## damage.py (287 lines)
Champions-format stat + base damage estimator.
- Mirrors Showdown's data/mods/champions/scripts.ts statModify + battle-actions damage math. Verified against Showdown for base cases.
- EV points are Champions points (0-32). Stat term uses max(2*points - 1, 0).
- Modifier coverage (all optional kwargs, defaults = no modifier):
  - crit:         1.5x damage (ignores screens)
  - burn:         0.5x physical (skipped if attacker_ability == 'Guts')
  - weather:      'rain' | 'sun' | 'sand' | 'snow'
  - terrain:      'electric' | 'grassy' | 'psychic' | 'misty'
  - attacker_boosts / defender_boosts: dict of stat -> stage (-6..+6)
  - reflect / light_screen / aurora_veil: bool
  - attacker_ability: for damage-relevant abilities
- Order of operations follows Showdown's battle-actions.modifyDamage exactly.
- Importers: doubles_eval, smart_player, speed_model. Tests: `tests/test_damage.py`.

## decision_logger.py (49 lines)
Decision logger that records battle decisions and outcomes to JSONL files.
- Records detailed battle state including teams, active mons, HP, field conditions, legal moves, chosen actions, and heuristic choices.
- Each battle gets its own JSONL file with one row per turn.
- Importers: ga_core. Tests: `tests/test_decision_logger.py`.

## doubles_pilot.py (246 lines)
Doubles pilot that improves on simple heuristics with turn simulation.
- Extends SimpleHeuristicsPlayer to make better decisions in doubles format.
- Uses turn simulation for improved move selection, including support move effects and lookahead.
- Supports various environment variables for tuning: DOUBLES_KO_BONUS, DOUBLES_MIN_GAIN, DOUBLES_TURN_SIM, DOUBLES_LOOKAHEAD.
- Importers: doubles_eval, support_value, turn_sim. Tests: `tests/test_doubles_pilot.py`.

## bc_model.py (266 lines)
Neural models + checkpoint I/O for the BC pilot.
- Two architectures live here; a checkpoint's `arch` field decides which one a loader instantiates:
  BCModel    (v2) — flat MLP trunk. The production model; bc_best.pt was trained
                    with this. OUTPUTS=6 (type/move/switch × two slots a/b).
  BCModelV3  (v3) — transformer over 12 slot tokens + 1 field token, plus a
                    per-slot target head. OUTPUTS=8.
- Callers check `model.OUTPUTS` to know whether to unpack 6 or 8 tensors
  (see bc_player._get_shared_model / choose_move).
- CHECKPOINT CONTRACT: every name and dimension below is frozen — the saved
  state_dict in output/models/bc_best.pt is keyed by these exact attribute names
  and sized by these exact constants. See the banner by the constants. Comment
  freely; renaming a head or resizing an embedding silently breaks load_state_dict.

## bc_player.py (320 lines)
BC pilot — uses poke_env's valid_orders for action legality.
- Supports v2 (MLP, 6 heads) and v3 (transformer, 8 heads with target head).
- Checkpoint `arch` field decides which. Override the model via
  BC_PILOT_PATH env var (default: output/models/bc_best.pt).
- For v3, the target head contributes to option scoring so that
  "move X targeting opp-left" and "move X targeting opp-right" get
  different scores instead of being arbitrary tie-breaks.

## bc_train.py (398 lines)
Behavioural-cloning trainer. Env: BC_DATA (default `data/training_data.jsonl`), BC_OUT (default `bc_best.pt` under `output/models/`), BC_MODEL v2|v3, BC_BATCH 256, BC_EPOCHS 30, BC_PATIENCE 3. LR=1e-3, WD=1e-5, VAL_FRAC=0.1, SEED=42.
- `BCDataset` (winner samples duplicated 2x; moves not in priors become TYPE_NONE), `slot_loss`, `run_epoch`, `build_model`, `main`.
- `main`: drops consecutive duplicate (side, turn) rows, splits battles on a second `turn==1`, 90/10 battle-level split, AdamW + cosine annealing, saves on best `val_move_acc`, early stops on `PATIENCE`.
- Gotcha: module docstring (`:4-7`) lists only BC_MODEL/BC_OUT/BC_EPOCHS/BC_PATIENCE, not BC_DATA/BC_BATCH.

---

## Env vars read by src/
- Gotcha: the encoder is fed `item/ability=None`, `is_mega=False`, `terrain=None`, `hp_max=100` (hp as percent); `opp_seen` includes opposing actives (duplicates). Training-time inputs may differ: unclear.

### bc_train.py (398 lines)
Behavioural-cloning trainer. Env: `BC_DATA` (default `data/training_data.jsonl`), `BC_OUT` (default `bc_best.pt` under `output/models/`), `BC_MODEL` v2|v3, `BC_BATCH` 256, `BC_EPOCHS` 30, `BC_PATIENCE` 3. `LR=1e-3`, `WD=1e-5`, `VAL_FRAC=0.1`, `SEED=42`.
- `BCDataset` (winner samples duplicated 2x; moves not in priors become TYPE_NONE), `slot_loss`, `run_epoch`, `build_model`, `main`.
- `main`: drops consecutive duplicate (side, turn) rows, splits battles on a second `turn==1`, 90/10 battle-level split, AdamW + cosine annealing, saves on best `val_move_acc`, early stops on `PATIENCE`.
- Gotcha: module docstring (`:4-7`) lists only BC_MODEL/BC_OUT/BC_EPOCHS/BC_PATIENCE, not BC_DATA/BC_BATCH.

---

## battle_memory.py (372 lines)
Battle memory tracking system that maintains state during battles.
- Maintains battle state including mon records, weather conditions, volatile statuses, and action history.
- Implements `BattleMemory` class with methods for querying battle state like active mons, weather, volatiles, and protection probabilities.
- Provides `BattleMemoryMixin` to integrate with poke_env Players for automatic battle state tracking.
- Importers: battle_memory_parser, battle_memory_types. Tests: `tests/test_battle_memory.py`.
- Gotcha: The `repair_mega_forms` function corrects poke_env's incorrect mega evolution handling.

## battle_memory_parser.py (287 lines)
Battle memory parser that handles raw battle message parsing and event tracking.
- Parses battle messages from Showdown to populate battle state.
- Implements the `BattleMemoryParserMixin` class with methods for handling different battle events like switches, moves, status conditions, weather changes, etc.
- Importers: battle_memory. Tests: `tests/test_battle_memory.py`.

## battle_memory_types.py (103 lines)
Data types and constants used by battle memory tracking.
- Defines dataclasses: `Condition`, `Action`, `MonRecord` for representing battle events and state.
- Constants for move families, weather types, terrain types, etc.
- Importers: battle_memory_parser, battle_memory. Tests: `tests/test_battle_memory.py`.

## battle_runner.py (151 lines)
## battle_runner.py (151 lines)
Battle runner that executes battles with poke_env.
- `run_battle_once`, `run_battle` functions for executing battles and managing connections to Showdown server.
- Handles battle execution, timeouts, retries, and result processing.
- Importers: battle. Tests: `tests/test_battle_runner.py`.

---

## bc_model.py (266 lines)
Neural models + checkpoint I/O for the BC pilot.
- Two architectures live here; a checkpoint's `arch` field decides which one a loader instantiates:
  BCModel    (v2) — flat MLP trunk. The production model; bc_best.pt was trained
                    with this. OUTPUTS=6 (type/move/switch × two slots a/b).
  BCModelV3  (v3) — transformer over 12 slot tokens + 1 field token, plus a
                    per-slot target head. OUTPUTS=8.
- Callers check `model.OUTPUTS` to know whether to unpack 6 or 8 tensors
  (see bc_player._get_shared_model / choose_move).
- CHECKPOINT CONTRACT: every name and dimension below is frozen — the saved
  state_dict in output/models/bc_best.pt is keyed by these exact attribute names
  and sized by these exact constants. See the banner by the constants. Comment
  freely; renaming a head or resizing an embedding silently breaks load_state_dict.

## bc_player.py (320 lines)
BC pilot — uses poke_env's valid_orders for action legality.
- Supports v2 (MLP, 6 heads) and v3 (transformer, 8 heads with target head).
- Checkpoint `arch` field decides which. Override the model via
  BC_PILOT_PATH env var (default: output/models/bc_best.pt).
- For v3, the target head contributes to option scoring so that
  "move X targeting opp-left" and "move X targeting opp-right" get
  different scores instead of being arbitrary tie-breaks.

## bc_train.py (398 lines)
Behavioural-cloning trainer. Env: BC_DATA (default `data/training_data.jsonl`), BC_OUT (default `bc_best.pt` under `output/models/`), BC_MODEL v2|v3, BC_BATCH 256, BC_EPOCHS 30, BC_PATIENCE 3. LR=1e-3, WD=1e-5, VAL_FRAC=0.1, SEED=42.
- `BCDataset` (winner samples duplicated 2x; moves not in priors become TYPE_NONE), `slot_loss`, `run_epoch`, `build_model`, `main`.
- `main`: drops consecutive duplicate (side, turn) rows, splits battles on a second `turn==1`, 90/10 battle-level split, AdamW + cosine annealing, saves on best `val_move_acc`, early stops on `PATIENCE`.
- Gotcha: module docstring (`:4-7`) lists only BC_MODEL/BC_OUT/BC_EPOCHS/BC_PATIENCE, not BC_DATA/BC_BATCH.

---

## Env vars read by src/
Battle runner that executes battles with poke_env.
- `run_battle_once`, `run_battle` functions for executing battles and managing connections to Showdown server.
- Handles battle execution, timeouts, retries, and result processing.
- Importers: battle. Tests: `tests/test_battle_runner.py`.

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
