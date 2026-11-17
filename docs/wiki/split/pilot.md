# Pilot System

This section covers the decision making and battle simulation logic components.

## pilot.py (180 lines)
Pure-logic VGC pilot using the new `battle_memory` + `opp_model` stack.
- `VGCPilot` is the main entry point; `choose_move` calls `select_action`.
- `select_action` uses `battle_memory` to compute move order, then `opp_model` to estimate opponent builds and moves.
- `pilot.py` imports `battle_memory`, `opp_model`, `doubles_eval`, `speed_model`, `paths`.

## doubles_pilot.py (120 lines)
VGC pilot with full battle memory support, including:
- Uses `battle_memory` for precise turn tracking and state management.
- `choose_move` -> `select_action` that computes move order from `speed_model`.
- `choose_pair` (from `doubles_eval`) to select the best pair of moves for a doubles team.

## speed_model.py (~105 lines, new 2026-10-16, stage 1 of the new VGC pilot)
Pure (torch-free, poke_env-free) probability that we move before an opposing mon. See STATE.md §5.22 for the plan.
- `SpeedMods(stage, paralyzed, tailwind, scarf, weather, terrain)`: battle-time modifiers on one mon's Speed. `effective_speed(stat, mods, ability)`: floor after the stage multiplier, then Scarf x1.5, weather/terrain speed ability x2 (`SPEED_ABILITIES`: swiftswim/rain dish/hydration) or x0.5 (sandrush/slush rush). `speed_at_level(stat, level)` is `stat * 1.1` if level > 50, else `stat * 0.9`.
- `speed_diff(a, b, a_ability, b_ability, a_item, b_item)` returns how many times a is faster than b (not just the difference). The speed diff is used by `battle_memory.py` to compute the move order.
- `base_speed(species, ability, item)` = 0 for a species with no base speed, else the base speed from the DB. `base_speed` is not directly used in the new VGC pilot; it's used only for testing.

## battle_memory.py (new 2026-10-16, step 2 of the new VGC pilot)
Pure memory of battle state (poke_env-free): no items/abilities/pokemon details, no team info, no opponent mons, no switches, no moves, no battle history. It tracks only what's needed for the new VGC pilot to make decisions.
- `BattleMemory` is pure (poke_env-free): one Showdown protocol line in, state out. `BattleMemoryMixin` (put BEFORE the poke_env Player base) overrides `_handle_battle_message`, feeds every line of a block first, then calls super, so memory is complete when `choose_move` runs; `memory_for(battle)`. Memory keeps its own `turn` (equals `battle.turn`, checked live).
- Slots: `active` (slot -> mon name, set on switch/drag) and `active_mons(side)` (records, fainted ones until replaced).
- Mega: exact form from `|detailschange|` (always immediately before `|-mega|`), stone from `|-mega|`, `mega_used[side]`, `mega_available(side)`. `repair_mega_forms(battle, mem)` fixes a poke_env bug: `mega_evolve("Garchompite Z")` applies Garchomp-Mega (Spe 92) instead of Garchomp-Mega-Z (151); the mixin re-applies the logged form after each block.
- Conditions: `weather`, `conditions[(scope,name)]` (Trick Room, Tailwind, terrains, screens, hazards with layers) with start turn, source, setter, `history` (end_reason expired/replaced). `turns_left(cond, now)` -> (min, max) incl. the current turn; max assumes Rocks/Light Clay/Terrain Extender. Conditions set after the residual tick (turn 0, end-of-turn replacements) start next turn. Validated on 5006 real replays (Tailwind 4 turns in 930/930; Trick Room/terrain/weather 5 turns in >90%).
- Action order: `actions[turn]`, `turn_order(turn)` (chosen switches then moves/cant; `[from]` copies except lockedmove are not actions; pivot/replacement/drag switches are `chosen=False`), `first_mover[turn]`, `speed_pairs(turn)` (consecutive same-priority moves on untainted turns; taint = After You, Quash, Quick Claw, Custap, Dancer, Instruct). Caller still discounts Trick Room and Speed abilities/items.
- Protect: `protect_success_prob(ident)` = 1/3^chain for consecutive turns, fail resets (real replays: 67% fail on the 2nd use). Wide Guard/Quick Guard/Mat Block do NOT share the counter.
- Open Team Sheets: `|showteam|` is parsed into `ots[side]` (species, item, ability, moves, nature, gender; EVs are hidden); `ots_set(ident_or_species, side)` matches by species (a Mega form matches its base, nicknames handled). Validated on real replays: every OTS item equals the stone that later Mega'd. Feeding it to `opp_model.opponent_builds(species, item=, moves_seen=, ability=)` collapses the archetype posterior to the real set (to be wired in `VGCPilot._foe`). poke_env only requests OTS when the Player is built with `accept_open_team_sheet=True`; ladder games rarely have it (1.5%), Bo3 forces it.
- Speed flags: `speed_flags(ident)` -> item_consumed, status, slow_start, turns_since_switch_in (inputs for Unburden/Quick Feet/Slow Start; not yet used by speed_model).
- Per-mon volatiles (`VOLATILES`: Taunt 3, Encore 3, Yawn 2 turns; `MonRecord.volatiles` start turn, `BattleMemory.volatile_left(ident, name)`), cleared on switch / faint / `-end`. VGCPilot feeds `FoeInfo.taunt_left` and `TurnSim(tr_left=)` from memory (base pilot falls back to poke_env presence / field start turn).
- Tests: `tests/test_battle_memory.py` (25: 20 synthetic/edge-case + 5 on real replays). Live check: 6 poke_env battles on :8000, memory turn == battle.turn and Mega flags agree with poke_env.