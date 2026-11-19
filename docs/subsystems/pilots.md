# Pilots (battle players)

The poke_env Player classes that choose moves: `VGCPilot` (our GA fitness pilot),
`DoublesPilot` and its mixins, `LadderOpponent` (GA fitness opponent), the legacy
`SmartPlayer`, and the pure-logic pair scorer `doubles_eval`. Read this to change how a
turn decision is made, which pilot plays where, or the env flags that switch features.
The support-move layer is in [pilots-support.md](pilots-support.md); the one-turn
simulator in [turn-sim.md](turn-sim.md).

Last verified against code: 2026-11-18

## 1. Purpose

poke_env's `SimpleHeuristicsPlayer` runs a singles heuristic per slot in doubles: no
ally awareness, never Megas, never Protects, never uses Fake Out, never switches by
choice. Our pilots keep its decision as a BASELINE and re-decide on top of it:
`DoublesPilot` re-allocates both slots jointly (attacks, plus Protect / Fake Out / switch
/ support moves when `turn_sim` is on), `VGCPilot` adds battle memory, foe action / Mega
priors and our own Mega. `LadderOpponent` makes the heuristic opponent Protect / Fake Out
at rates fitted on real ladder replays. Format: `gen9championsvgc2026regmc` (Reg M-C,
doubles, Mega legal, Terastallization NOT legal - never model Tera).

Who plays where (built by `src/player_factory.py::make_player`, see battle-harness.md):
GA fitness = `GA_PILOT` (default `vgc` -> `TimeoutPlayer(VGCPilot)`) vs `GA_OPP`
(default `ladder`); `src/eval.py --pilot heuristic|bc|doubles|vgc|both --opp heuristic|ladder`.

## 2. Files

| path | lines | role |
|---|---|---|
| src/vgc_pilot.py | 128 | `VGCPilot(BattleMemoryMixin, DoublesPilot)`: foe Mega / action priors from memory, own Mega (`add_mega`) |
| src/doubles_pilot.py | 246 | `DoublesPilot`: vanilla baseline -> `_improve` (evaluator path) or `_improve_sim` (turn_sim path) |
| src/pilot_world.py | 144 | `PilotWorldMixin`: `_attacker`, `_foe` (opp_model builds, Mega split, per-build Speed), `_ally`, `_speed_mods`; `_is_attack_candidate`, `LOCKED_MOVES`, `UNMODELLED_MOVES` |
| src/pilot_actions.py | 82 | `PilotActionsMixin`: order -> `DE.Action` (`_action`, `_targeted`, `_sim_kind`, `_sim_action`) |
| src/pilot_sim_input.py | 60 | `PilotSimInputMixin`: `_our_speed`, `_foe_info` and base-pilot hooks (`_taunt_left`, `_trick_room_left`, `_foe_trick_room_prob`, `_foe_action_probs`) |
| src/doubles_eval.py | 180 | pure logic: `Hypothesis`, `Combatant`, `Attacker`, `Action`, `Evaluator.pair_value`, `choose_pair` |
| src/ladder_opp.py | 77 | `LadderOpponent(BattleMemoryMixin, SimpleHeuristicsPlayer)` |
| src/smart_player.py | 202 | legacy `SmartPlayer` (singles hook, unused in battles) + helpers `_type_to_db`, `_weather_name`, `_terrain_name`, `_boosts_dict`, `_stats_dict` |
| src/support_value.py | 202 | support-move layer, pure data side (see pilots-support.md) |
| src/pilot_support.py | 75 | DEAD CODE: no-op stubs `_resolve_*`; imported only by `tests/test_pilot_support.py` |

## 3. Key concepts / data structures

Class composition (actual MRO of `VGCPilot`): `VGCPilot -> BattleMemoryMixin ->
DoublesPilot -> PilotSimInputMixin -> PilotActionsMixin -> PilotWorldMixin ->
SimpleHeuristicsPlayer -> Player`. `TimeoutPlayer` (battle harness) subclasses `VGCPilot`.
Hooks defined in the mixins return "no model" values; `VGCPilot` overrides them from
`BattleMemory` (`src/battle_memory.py`): `_mega_prob`, `_foe_action_probs`,
`_foe_trick_room_prob`, `_taunt_left`, `_trick_room_left`.

World ids (strings, shared with turn_sim): `o0`, `o1` foe slots; `a0`, `a1` our slots;
`b0`, `b1`.. our bench (turn_sim path only, from `battle.available_switches`).

`doubles_eval` shapes (real examples):
- `Hypothesis(weight=0.4, stats={"hp":180,"atk":150,"def":110,"spa":90,"spd":110,"spe":100}, max_hp=180, cur_hp=126, types=None, speeds=[(0.7, 100), (0.3, 150)])`
  (`types` set for a post-Mega build; `speeds` = (weight, effective Speed) for THIS build).
- `Combatant(hyps=[...], types=["Dark"], boosts={"atk": -1}, is_ally=False, immune_prob={"Ground": 0.35})`.
  Foes get up to several weighted hypotheses; our mons exactly one (`is_ally=True`).
- `Attacker(stats=..., types=["Fire","Dark"], boosts={}, burn=False, ability=None, final_mult=1.3)`
  (Choice Band / Specs x1.5 and Huge / Pure Power x2 are folded into `stats`; Life Orb ->
  `final_mult`; only Guts is passed as `ability`).
- `Action(attacker=0, move="bodyslam", targets=("o0",))`; spread
  `Action(0, "earthquake", ("o0", "o1", "a1"))`; turn_sim specials
  `Action(1, "protect", ())`, `Action(0, "fakeout", ("o1",))`, `Action(0, "switch", ("b0",))`.

Value unit (Evaluator and TurnSim): per target and hypothesis
`weight * (E[min(dmg, cur_hp)] / max_hp + KO_BONUS * P(KO))`, foes positive, our mons
negative times `ALLY_WEIGHT`. Two attackers on one target use the outer sum of their
damage rolls, so focus fire / overkill / ally-hurting spread moves fall out of one number.

Candidate kinds (`PilotActionsMixin._sim_kind`): `"attack"` (`_is_attack_candidate`:
damaging, base power > 0, not charge/recharge, target `normal|any|allAdjacentFoes|
allAdjacent`, not in `LOCKED_MOVES` / `UNMODELLED_MOVES`), `"support"` (enabled
pure-support move), `"protect"` (`turn_sim.BLOCKING` = Protect family minus Endure),
`"fakeout"`, `"switch"`. Anything else (setup, other status) leaves that slot on vanilla.

`stats_counter` (per player): DoublesPilot `turns, overrides, errors, sim_turns,
sim_protect, sim_switch, sim_fakeout, sup_<effect>`, plus `sim_lookahead`, `la_diff`
when used; VGCPilot adds `mega_opportunities, mega_used, mega_errors, foe_mega_turns,
foe_mega_errors`; LadderOpponent `turns, protect, fakeout, errors`.

## 4. Public API

- `vgc_pilot.py::VGCPilot(*args, **kwargs)` -> poke_env Player; same kwargs as DoublesPilot.
- `vgc_pilot.py::mega_variant(order, valid)` -> the `mega=True` twin (same move id and `move_target`) or None.
- `vgc_pilot.py::add_mega(battle, base, mega_free, score=None)` -> `(order, slot)` with Mega on the best-scoring capable slot, else `(base, None)`.
- `doubles_pilot.py::DoublesPilot(*args, ko_bonus=None, min_gain=None, use_turn_sim=None, support=None, lookahead=None, **kwargs)`; `None` = env / default.
- `doubles_pilot.py::DoublesPilot.choose_move(battle)` -> `DoubleBattleOrder` (any exception -> vanilla order, `errors += 1`).
- `ladder_opp.py::LadderOpponent(*args, rng=None, **kwargs)`; `.choose_move(battle)`.
- `doubles_eval.py::Evaluator(attackers, world, weather=None, terrain=None, ko_bonus=KO_BONUS, ally_weight=ALLY_WEIGHT, effects=frozenset())`; `.pair_value(actions)` -> float; `.rolls(action, tid, hi)` -> int64 array; `.modelable(move)` -> bool.
- `doubles_eval.py::choose_pair(ev, cands_a, cands_b, min_gain=MIN_GAIN)` -> `(ia, ib, best_v, base_v)`; index 0 = baseline.
- `pilot_world.py::_is_attack_candidate(move, effects=frozenset())` -> bool (used by actions / sim-input mixins).
- `smart_player.py::_type_to_db`, `_weather_name` (`rain|sun|sand|snow|None`), `_terrain_name` (`electric|grassy|psychic|misty|None`), `_boosts_dict` - used by `doubles_pilot.py` and `pilot_world.py`.

## 5. Flow: one turn of `VGCPilot.choose_move(battle)`

1. Foe Mega: `mega_model.foe_mega_probs(memory, foe_side)` -> `self._foe_mega`
   {mon name: P(Megas this turn)}; failure -> `{}`, `foe_mega_errors += 1`.
2. `DoublesPilot.choose_move`: `base = SimpleHeuristicsPlayer.choose_move(battle)`; not a
   `DoubleBattle` -> return base; else `turns += 1`, `_improve(battle, base)`.
3. `_improve`: return base on any `force_switch`, non-`DoubleBattleOrder` base or empty
   `valid_orders`. Build `world`: each live foe `o<i>` via `_foe(mon, battle if
   use_turn_sim else None)` (opp_model builds; a Mega-capable build splits into post-Mega
   `form_stats` with weight q and pre-Mega 1-q, q from `mega_model.conditional_q`; immunity
   map mixes pre/post-Mega abilities). If ANY foe has no builds -> return base. Our live
   mons -> `attackers[i]` (`_attacker`, needs `mon.stats`) and `world["a<i>"]` (`_ally`).
4. turn_sim OFF (`DOUBLES_TURN_SIM=0`): per slot, if vanilla picked an attack candidate,
   candidates = baseline + every other attack order with the same mega / tera / dynamax /
   z flags; `doubles_eval.choose_pair` with `min_gain`; `(0, 0)` -> base.
5. turn_sim ON (default) -> `_improve_sim`: add bench `b<k>`; a slot is free when it has an
   attacker and vanilla's order is a sim kind; candidates = baseline + valid orders of a sim
   kind (Protect only if `protect_counter == 0`, Fake Out only on `first_turn`, same Mega
   flag as baseline). Build `ours` speeds (`_our_speed`), `foes` (`_foe_info`: revealed
   attack moves or a Body Slam / Hyper Voice proxy, Speed belief, Fake Out / Protect /
   Trick Room probs, abilities, `taunt_left`), `tr_left`. Make `fine` and `coarse` TurnSims,
   `set_candidates`, optional `LookAhead`, shortlist (`SHORTLIST=3`), then
   `turn_sim.choose_pair_refined(coarse, fine, ..., min_gain, TOP_K=6)`; count chosen
   specials / support effects. Details: turn-sim.md.
6. Back in VGCPilot: skip on force_switch; if `memory.mega_available(role)`, `add_mega`
   puts Mega on the capable slot with the largest `mega_gain(species, item)` (offence gain;
   ties -> lower slot); switches never Mega; at most one per turn.

`LadderOpponent.choose_move`: heuristic order; per active slot whose order is a move, if
the mon carries a Protect-family move (any turn) or Fake Out (only `mon.first_turn`), draw
`u ~ U(0,1)` once: `u < p.fakeout` -> random Fake Out order; `p.fakeout <= u < p.fakeout +
p.protect` -> first Protect order (same Mega flag as base); probabilities from
`opp_actions.action_probs(foe_ctx(..., known_moves=own moves, moves_complete=True))`.

## 6. Invariants (pinned by tests)

- Baseline wins ties: a pair must beat the vanilla pair by more than `min_gain` (only the
  first deviation pays it) - `test_doubles_eval.py`, `choose_pair_refined` in turn_sim.
- With no foe actions and attacks only, TurnSim value == Evaluator value
  (`test_without_foe_actions_matches_the_evaluator`).
- Pilot-level fallbacks: any exception -> vanilla order; force-switch turns untouched.
- `DoublesPilot.effects` / `.lookahead` are CLASS attributes (`frozenset()`, `False`):
  tests build pilots with `DoublesPilot.__new__` without `__init__`.
- Mega: twin must match move id and target; one slot only; none after Mega used or on a
  switch (`test_vgc_pilot.py`). LadderOpponent keeps the base Mega flag, leaves switches
  alone, matches the fitted rate over many draws (`test_ladder_opp.py`).

## 7. Config / env vars

| name | default | read where / when | effect |
|---|---|---|---|
| `DOUBLES_TURN_SIM` | `1` | `DoublesPilot.__init__` | `0` = old Evaluator path (attacks only) |
| `DOUBLES_KO_BONUS` | `1.0` (`doubles_eval.KO_BONUS`) | `DoublesPilot.__init__` | KO term weight |
| `DOUBLES_MIN_GAIN` | `0.01` (`doubles_eval.MIN_GAIN`) | `DoublesPilot.__init__` | deviation threshold |
| `DOUBLES_FOE_ACTIONS` | `1` | `VGCPilot.__init__` | `0` = foes never Fake Out / Protect / set TR in the sim |
| `DOUBLES_SUPPORT` | `all` | `support_value.parse_effects` at pilot init | support effects; see pilots-support.md |
| `DOUBLES_LOOKAHEAD` | `0` | `support_value.lookahead_enabled` at pilot init | LookAhead; needs effects |
| `DOUBLES_LA_LOG` | unset | `_improve_sim` | path: JSONL of decisions the lookahead changed |
| `DOUBLES_PASSIVE_COST` | `0.30` | `turn_sim_types` at IMPORT | tempo cost per Protect / switch |
| `DOUBLES_SUPPORT_COST`, `_HORIZON`, `_STAY`, `DOUBLES_TR_HORIZON`, `DOUBLES_LOOKAHEAD_GAMMA` | 0.15, 2.0, 0.7, 2.0, 0.7 | `support_value` at IMPORT | support layer constants |
| `ALLY_WEIGHT` | 1.0 | constant `doubles_eval.py` | own-mon damage cost |
| `SmartPlayer.KO_BONUS`, `DAMAGE_WEIGHT` | 8.0, 3.0 | constants | legacy pilot only |

Constructor kwargs beat env vars. Import-time constants must be set before the process
starts. `GA_PILOT` / `GA_OPP` choose pilots for the GA (see ga.md).

## 8. Tests

All run as `python tests/<file>.py` (no server needed) and are in `bash tools/verify.sh`:
- `tests/test_doubles_eval.py` (10): opp_model builds / Mega forms / immunity, focus fire,
  overkill redirect, baseline-on-tie, spread vs fragile or immune ally, status/None free.
- `tests/test_turn_sim.py` (26): sim behaviour plus pilot wiring with real poke_env
  `Pokemon` (speed inputs, end-to-end `_improve`, Protect/switch when about to die,
  VGCPilot foe probs from memory).
- `tests/test_support.py` (28): support layer and lookahead (pilots-support.md).
- `tests/test_vgc_pilot.py` (6): Mega twin, slot choice, score, memory-fed Taunt / TR turns.
- `tests/test_ladder_opp.py` (5).
Also in verify.sh since 2026-11-18: `tests/test_pilot_support.py` (import check of dead code).
Live behaviour is only measured by paired runs (`tools/paired_eval.py`, see eval.md).

## 9. Gotchas, history, measured results

- 2026-10-15 SmartPlayer (KO-aware singles scoring) lost to vanilla: 42.5% [35.9-49.4]
  over 200 same-team mirror battles. `choose_singles_move` is a singles hook; it is not in
  `make_player` and is only used by `tools/test_pilots.py`. The module stays because its
  helpers are imported by the pilots.
- 2026-10-15 DoublesPilot (Evaluator path) vs heuristic, baseline team vs held-out pool:
  pooled 2000 each 52.9% -> 58.9%, +6.0 pts, z ~ 3.8. Same day: a damage-chart bug
  (`damage._CODE_TO_MULT` code 4 vs DB immune code 3) had made every type immunity x1.0.
- 2026-10-15 vanilla `SimpleHeuristicsPlayer` never Mega-evolves (21 opportunities, 0
  used); DoublesPilot keeps that, VGCPilot adds Mega.
- 2026-10-16 `KO_BONUS` sweep (MIN_GAIN 0.01, 4000 battles per cell, SE ~0.8 pts):
  0 -> 56.3, 0.25 -> 58.5, 0.5 -> 59.3, 1 -> 60.5, 2 -> 60.6, 4 -> 60.5; default 1.0.
  `MIN_GAIN` 0 / 0.01 / 0.03 / 0.06 -> 60.2 / 60.5 / 58.9 / 59.1; 0.01 kept.
- 2026-10-16 Mega policy from 5006 replays: 79% of real Megas happen at the first
  opportunity; win rate by timing is flat (turn 1 41.9%, later first chance 41.8%,
  delayed 43.1%, never 46.1%; confounded); with two candidates humans Mega the larger
  offence gain 74% of 499 turn-1 pairs. Hence: Mega ASAP, pick by `mega_gain`.
- 2026-10-16 turn_sim on vs off inside VGCPilot (paired, same matchups): +4.7 pts
  [+3.8, +5.6] vs heuristic opponent (66.3% -> 71.0%, n=17,941); +4.5 pts [+3.6, +5.5]
  vs LadderOpponent (69.3% -> 73.8%, n=16,506), both p < 0.001. Made default 2026-10-16.
  Measured with `PASSIVE_COST` 0.15 and support off; today's defaults (0.30, support
  `all`) have no equivalent paired run. Unverified: any later re-measurement.
- 2026-10-16 LadderOpponent live check (95 matchups): Protect on 30% of turns where the
  mon carries it, Fake Out on 8%; over all ladder decision points Protect is 10.9%, Fake
  Out 3.2%. Both pilot arms win MORE against it than against the plain heuristic.
- `pilot_support.py` (extracted 2026-11-15) is dead: every function is `pass`, it checks
  string keys in `mon.effects`, and its comment on Foul Play is wrong (Foul Play uses the
  TARGET's Attack). Real support logic: `support_value.py`, `turn_sim.py`, `pilot_actions.py`.
- `doubles_pilot.py` / mixins contain runs of blank lines and stray section comments
  left by the 2026-11-16 mixin split; harmless.
- No `accept_open_team_sheet` in `src/`; VGCPilot reads `memory.ots_set` when a sheet
  exists. Unverified: whether local Champions-format battles ever deliver Team Sheets.
- Not modelled anywhere: Yawn, Toxic, Will-O-Wisp, Wish, screens, Tailwind setting,
  redirection, foe switches, crits, Tera (illegal).

## 10. How to change safely

1. Keep "vanilla baseline + `min_gain`" and the exception fallback in `choose_move`.
2. New hook a VGCPilot overrides: add the no-model default in the right mixin first.
3. New candidate kind: `_sim_kind` + `_sim_action` + TurnSim handling + shortlist rule.
4. Changing defaults (`DOUBLES_*`, `KO_BONUS`, `PASSIVE_COST`) changes GA fitness: run a
   paired comparison (`tools/paired_eval.py`), record the result and date in docs/STATE.md.
5. `bash tools/verify.sh` must end `ALL PASS`; add a synthetic test next to the existing
   ones (`tests/test_turn_sim.py` / `tests/test_support.py` style, no server).

## Related docs

- [pilots-support.md](pilots-support.md) - support-move layer, its flags and results
- [turn-sim.md](turn-sim.md) - TurnSim model, value function, LookAhead
- [battle-harness.md](battle-harness.md) - `make_player`, `TimeoutPlayer`, run_battle
- [damage.md](damage.md) - damage rolls, speed_model, opp_model, mega_model
- [battle-memory.md](battle-memory.md) - BattleMemory, opp_actions
- [eval.md](eval.md) - paired_eval / eval CLI
- [ga.md](ga.md) - `GA_PILOT` / `GA_OPP` fitness environment
- [../reference/config-and-env.md](../reference/config-and-env.md)
