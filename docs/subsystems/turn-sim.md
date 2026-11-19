# Turn simulator (turn_sim)

`TurnSim` plays one doubles turn out in move order and scores a pair of our actions; it is
the decision core of `DoublesPilot` / `VGCPilot` when `DOUBLES_TURN_SIM=1` (the default).
Covers the model, value function, foe outcome model, `PASSIVE_COST`, the coarse/fine
top-K search and the optional `LookAhead` continuation. Read before changing any
simulation rule or constant.

Last verified against code: 2026-11-18

## 1. Purpose

`doubles_eval.Evaluator` scores attacks as if all land first. `TurnSim` (a subclass, same
`pair_value` interface) adds: Speed / priority order (Trick Room reverses), foe
retaliation chosen by a mirror policy, Showdown retargeting when a single target already
fainted, foe Protect / Fake Out / Trick Room outcomes, our Protect / Fake Out / switch,
HP as probability vectors, and the support layer. Pure logic: numpy + `src/damage.py`, no
poke_env. Inputs are built by the pilot mixins (pilots.md).

## 2. Files

| path | lines | role |
|---|---|---|
| src/turn_sim.py | 434 | `TurnSim` (scenario enumeration, foe model, move order, caches), `choose_pair_refined`; re-exports types, constants, `LookAhead` |
| src/turn_sim_resolve.py | 247 | `Resolution`: plays ONE scenario in move order and returns its value (the body of `TurnSim._run`) |
| src/turn_sim_types.py | 123 | constants, `FoeInfo`, `FoeAct`, `Speeds`, helpers (`act_priority`, `is_switch`, `is_protect`, `is_support`, `_prune`, `_pmf`, `_apply`, `_flip`) |
| src/turn_sim_lookahead.py | 129 | `LookAhead`: next-turn value of state deltas (lazy-imports `TurnSim`) |

Imports (no cycles): `turn_sim` -> `turn_sim_types`, `turn_sim_resolve`,
`turn_sim_lookahead`; `turn_sim_resolve` -> `turn_sim_types`, `doubles_eval`,
`support_value` (gets the `TurnSim` instance as an argument; imports it only for type
hints); `turn_sim_lookahead` -> `turn_sim` lazily.

## 3. Key concepts / data structures

- World: `{id: DE.Combatant}`; ids `o0, o1` (foes, hypotheses pruned to the `max_hyps`
  heaviest and renormalised), `a0, a1` (ours), `b0..` (bench, target of a switch).
- `our_speed`: `{slot: effective Speed}` (from `speed_model`, Tailwind / paralysis /
  Scarf / weather abilities applied by the pilot).
- `FoeInfo(moves=["bodyslam"], speeds=[(0.7, 100), (0.3, 150)], fakeout=0.0,
  protect=0.12, protect_ok=1.0, trickroom=0.0, abilities={"intimidate": 1.0},
  taunt_left=0)`. Speed `None` = unknown (coin flip). `Hypothesis.speeds` of the
  simulated build wins over `FoeInfo.speeds` (keeps Speed and damage correlated: a Mega
  build is fast AND strong).
- `FoeAct(move, targets, priority)`: a foe's planned hit, targets in world ids.
- Foe outcome kinds per foe (`_build_kinds`): `atk` (1 - pf - pp - pt), `fakeout` split
  over our active slots by "threat" (each slot's best solo attack value, from
  `set_candidates`), `protect` (pp * protect_ok), `idle` (failed Protect, pp *
  (1 - ok)), `tr` (pt, only when a Taunt candidate exists, `taunt` effect on, TR down).
  A Taunted foe (`taunt_left > 0`) gets pp = pt = 0. Kinds below `min_outcome_p` are
  dropped and the rest renormalised.
- Mirror foe (`_plan`): the attacking foes pick the (move, target) pair maximising
  `doubles_eval` pair value from THEIR side (focus fire, no overkill, avoid spread moves
  that hurt their partner); a foe with no modelable known move does nothing. Cached per
  (hypothesis combo, acting foes).

## 4. Public API

- `TurnSim(attackers, world, our_speed, foes, trick_room=False, weather=None, terrain=None, ko_bonus=KO_BONUS, ally_weight=ALLY_WEIGHT, max_hyps=MAX_HYPS, passive_cost=PASSIVE_COST, min_outcome_p=MIN_OUTCOME_P, effects=frozenset(), support_cost=SUPPORT_COST, tr_left=0)`.
- `TurnSim.set_candidates({0: [Action|None, ...], 1: [...]})` -> None; call before `pair_value` (sets Fake Out threat split and the `tr` outcome; clears caches).
- `TurnSim.pair_value((a, b))` -> float (cached per sorted action tuple); `CONFLICT = -1e9` when both slots switch to the same bench mon.
- `TurnSim.shortlist(acts, k)` -> sorted indices: 0, every None / switch / Protect / support / Fake Out, and the `k` best other attacks by solo Evaluator value.
- `TurnSim.enable_lookahead(la=None)` -> `LookAhead` (call after `set_candidates`); `disable_lookahead()`.
- `choose_pair_refined(coarse, fine, cands_a, cands_b, min_gain=MIN_GAIN, top_k=6)` -> `(ia, ib, best_v, base_v)`.
- `LookAhead(sim)`; `.v1(key=())` -> float; `.dv(key)` -> float; keys `("drop", foe, d_atk, d_spa)`, `("tr",)`.
- `DE.choose_pair(sim, a, b)` also works on a TurnSim (exhaustive; tests use it).

## 5. Flow

Pilot side (`DoublesPilot._improve_sim`): build `fine = TurnSim(...)` (MAX_HYPS 4,
MIN_OUTCOME_P 0.005) and `coarse = TurnSim(..., max_hyps=COARSE_HYPS=2,
min_outcome_p=COARSE_OUTCOME_P=0.05)`; `set_candidates` on both; if lookahead is on and a
support or stat-drop candidate exists, one `LookAhead(coarse)` shared by both; shortlist
each slot with `fine.shortlist(acts, SHORTLIST=3)`; `choose_pair_refined(coarse, fine,
..., TOP_K=6)`.

`choose_pair_refined`: score every non-baseline pair with `coarse`, take the top_k, score
them and the baseline (0, 0) with `fine`; a pair must beat the baseline by more than
`min_gain` (0.01) to be chosen.

`pair_value(actions)`:
1. Sort ours by (-priority, Speed descending, or ascending under Trick Room, slot);
   priority = DB priority, switch = `SWITCH_PRIORITY` 8.
2. For every product of foe hypotheses x foe outcome kinds, weight = product of
   hypothesis weights x kind probabilities; skip if < `MIN_SCENARIO_P` (1e-4).
3. `_outcome`: plan the attacking foes (mirror), foe Fake Out on its target slot, protecting
   foes block. Per acting foe `_order_dist` = P(exactly the first k of our sorted actions
   move before it), over its Speed list (`_ours_first`: higher priority wins; equal
   priority -> Speed, tie or unknown 0.5, TR flips). Sum `_run` over the product of cuts.
4. Subtract `passive_cost * (#switch + #Protect) + support_cost * (#pure support that is
   not a heal)`.

`TurnSim._run(ours, hi, foe_acts, cut, protecting, trfoes, wt)` (one scenario) is
`Resolution(self, hi, cut, protecting).run(ours, foe_acts, trfoes, wt)` in
`src/turn_sim_resolve.py`. Its per-scenario state is attributes of the `Resolution`:
`pmf` / `start` (HP pmf per touched combatant, lazy, starts at cur_hp), `occ` (our slot ->
mon standing in it), `blocked` (Protect), `fskip` / `oskip` (flinch), `fdrop` (stat drops
on foes), `helped` (Helping Hand), `taunted`, `extra` (drop persistence). Methods:
`get`, `alive`, `hit_pmf`, `heal_pmf`, `foe_mix`, `apply_mix`, `land` (a drop hits a foe),
`our_hit(k, a)`, `foe_hit(fid, fa)`, `run`, `value`. `run`: foes act at their cut
positions (`cut[f] = k`: right before our k-th action), ours in order.
- `our_hit`: switch moves the bench mon into the slot (it takes the slot's hits); Protect
  blocks hits on its occupant; Helping Hand marks the partner; heal shifts HP up; Taunt /
  drop status land on foes (a foe without `FoeInfo` is skipped); an attack applies rolls
  with P(hit) = P(actor alive) x (1 - P(flinched)) x accuracy x (1 - immunity) x not
  blocked; Fake Out flinches foes that have not acted; a single-target move whose target is
  dead (P) hits the other foe instead.
- `foe_hit` mirrors this: drop mixture on their attacking stat (`foe_mix`), their Fake Out
  flinches our slot, a single-target hit on a fainted mon retargets our other occupant
  (unless it is protected).

`value()` of a scenario = sum over touched combatants of
`(start_hp - E[hp]) / max_hp + ko_bonus * P(hp == 0)`, negative times `ally_weight` for
ours (bench included), plus support terms (heuristic persistence `extra` / `_tr_cost`, or
LookAhead terms). Same unit as `doubles_eval.Evaluator`. The leaf sink (`sim._sink`, used
by LookAhead) is called with `(wt, hi, pmf)` before the final sum.

`LookAhead` (multi-turn continuation, off by default):
1. Leaf `s'`: run a reference coarse sim (support effects stripped except foulplay) on the
   best plain attack pair; record per-hypothesis P(alive) and E[HP] through `_sink`;
   mons with P(alive) < 0.5 removed; HP set to the expectation; Trick Room one turn older
   (kept only if `tr_left == 0` or > 1); `taunt_left` - 1.
2. `V1(state)` = best plain attack pair value of a coarse TurnSim on that state.
3. `dv(d) = V1(s' + d) - V1(s')` (0 if the foe left the leaf); in `_run`, each landed drop
   state adds `q * P(foe alive) * h_drop * dv(("drop", f, da, ds))` with `h_drop = 1.4`;
   each foe TR outcome adds `h_tr * dv(("tr",)) * (1 - P(taunted)) * P(alive)` with
   `h_tr = discounted_turns(4, 0.7) = 1.773`. Same HP on both sides, so a KO this turn
   is not penalised; only the NEXT turn's races change.

## 6. Invariants (tests/test_turn_sim.py, 26 tests)

- No foe actions + attacks only -> equals `doubles_eval.Evaluator`.
- A faster foe that KOs us stops our attack; killing a slower foe prevents its hit;
  priority beats Speed; Trick Room flips who benefits; unknown foe Speed = coin flip;
  foe Mega Speed mixture weighted by q; per-hypothesis Speed is correlated with the build.
- Second attacker retargets when the first kills; spread moves still pay for hurting our
  partner; foe spread hits its own partner; retargeting with an empty partner slot does
  not crash (regression for `KeyError: 'a0'`, 2026-10-16).
- Mirror foes focus fire when only the pair kills, avoid self-hurting spread, idle with no
  known attack.
- Foe Fake Out flinches us whatever the Speed and targets the slot with the better attack;
  our Fake Out prevents retaliation; foe Protect blocks; our Protect against an idle foe is
  worth exactly `-PASSIVE_COST`; two slots cannot switch to the same mon.
- `DE.choose_pair` (exhaustive) on 6 x 6 candidates with 4 + 2 foe hypotheses and 3 / 2
  Speed points finishes in < 8 s.
- Pilot wiring with real poke_env `Pokemon`: Tailwind / paralysis / TR speed inputs,
  end-to-end `_improve`, Protect / switch considered when about to die, VGCPilot foe probs
  from memory. Support + LookAhead invariants: `tests/test_support.py` (pilots-support.md).
- `tests/test_turn_sim_paths.py` (3 tests, exact values recorded before the 2026-11-18
  split): Snarl into a protecting foe and into a foe without `FoeInfo` lands no drop; Charm
  on a foe without `FoeInfo` is skipped; a foe's single-target hit on our fainted mon
  retargets our partner, and is blocked when the partner protects first. With these three,
  every reachable line of the scenario code is executed by the tests (the
  `drop.kind != "secondary"` branch in `our_hit` is unreachable: `foe_drop` gives every
  damaging move kind `secondary`).

## 7. Config / constants (src/turn_sim_types.py unless noted)

| name | value | effect |
|---|---|---|
| `PASSIVE_COST` | env `DOUBLES_PASSIVE_COST`, default 0.30 (read at IMPORT) | tempo cost per switch / Protect |
| `MAX_HYPS` / `COARSE_HYPS` | 4 / 2 | foe hypotheses kept (fine / coarse) |
| `MIN_OUTCOME_P` / `COARSE_OUTCOME_P` | 0.005 / 0.05 | drop foe outcome kinds below this |
| `MIN_SCENARIO_P` | 1e-4 | skip scenario combos below this weight |
| `SHORTLIST` / `TOP_K` | 3 / 6 | plain attacks kept per slot / pairs re-scored by `fine` |
| `SWITCH_PRIORITY` | 8 | switches go first |
| `BLOCKING` | Protect, Detect, King's Shield, Spiky Shield, Baneful Bunker, Obstruct, Silk Trap, Burning Bulwark | `battle_memory_types.PROTECT_FAMILY` minus Endure |
| `CONFLICT` | -1e9 | same bench mon twice |
| `KO_BONUS`, `ALLY_WEIGHT`, `MIN_GAIN` | 1.0, 1.0, 0.01 | from `doubles_eval` (pilot env `DOUBLES_KO_BONUS`, `DOUBLES_MIN_GAIN`) |
| `SUPPORT_COST`, `SUPPORT_HORIZON`, `FOE_STAY`, `TR_HORIZON`, `LOOKAHEAD_GAMMA`, `TR_TURNS_AFTER_SET` | 0.15, 2.0, 0.7, 2.0, 0.7, 4 | `src/support_value.py` |

Pilot-level switches: `DOUBLES_TURN_SIM` (1), `DOUBLES_FOE_ACTIONS` (1),
`DOUBLES_SUPPORT` (all), `DOUBLES_LOOKAHEAD` (0), `DOUBLES_LA_LOG`.

## 8. Tests

`python tests/test_turn_sim.py` (26), `python tests/test_support.py` (28) and
`python tests/test_turn_sim_paths.py` (3); all in `bash tools/verify.sh`, synthetic stats,
no server. Live: `tools/paired_eval.py` (default
`--mode turnsim`: VGCPilot turn_sim off vs on; note both arms now also carry the default
support layer and `PASSIVE_COST` 0.30).

## 9. Gotchas and history (dated)

- 2026-10-16 v1/v2 (one slot, then joint): ~62 ms per sim turn vs ~0.8 ms for the old
  Evaluator. v3 (foe Protect / Fake Out, our specials, per-hypothesis Speed): a naive
  11x11 cross product took ~4.3 s per turn; shortlist + coarse screen + top-6 refine got
  the synthetic worst case to ~0.9 s with the same pick; live ~80 ms per sim turn.
- 2026-10-16 paired results (VGCPilot turn_sim on vs off): +4.7 pts [+3.8, +5.6] vs the
  heuristic opponent (n=17,941) and +4.5 pts [+3.6, +5.5] vs LadderOpponent (n=16,506),
  p < 0.001. Sim ran on ~2/3 of decisions and overrode vanilla on ~40% (old evaluator
  ~24%); per battle ~1.28 Protect, 0.76 switch, 0.32 Fake Out over vanilla; games +20%
  longer (9.15 vs 7.60 decisions). Made the default the same day.
- 2026-11-14 `PASSIVE_COST` 0.15 -> 0.30 (commit `7f72853`): Protect/switch stalling made
  GA battles run 60+ turns (~1 h per generation); the 50-turn cap was added the same day
  (battle-harness.md). No paired run at 0.30 is recorded. Unverified: its win-rate effect.
- 2026-10-20 LookAhead: neutral over ~6000 pairs (-1.5 and +1.3 pts, both p=0.21), +7 ms
  (~+14%) per decision; kept OFF. See pilots-support.md.
- 2026-11-16 turn_sim.py split into types / lookahead / core; `turn_sim` re-exports
  everything, so `from src import turn_sim as TS; TS.PASSIVE_COST` still works.
- 2026-11-18 `TurnSim._run` (one 173-line method with 10 nested closures sharing 8 local
  variables) moved to `src/turn_sim_resolve.py::Resolution` (closures -> methods, locals ->
  attributes, same arithmetic in the same order). Verified bit for bit: every `_run` /
  `pair_value` result and every LookAhead leaf state produced by the turn_sim, support,
  VGCPilot, mega-model and path tests (2197 records) is identical. Cost: about 3% slower
  per `_run` call (method vs closure lookups; 1.71 -> 1.76 s per 3000 calls).
- Not modelled: foe switches and back-slot foe Mega; crits; secondary effects other than
  Fake Out flinch and atk/spa drops; items / abilities on damage (Life Orb recoil,
  Intimidate, Sash, contact punish); Unburden / Quick Feet / Slow Start / Quick Claw /
  Custap; our Protect after a Protect (pilot only offers Protect at `protect_counter == 0`);
  more than one foe action per turn; anything beyond one turn except LookAhead deltas.
- Import-time env reads: set `DOUBLES_PASSIVE_COST` / `DOUBLES_SUPPORT_*` before Python
  starts; changing `os.environ` later has no effect.
- `TurnSim` constructor default `effects=frozenset()` (layer off) while the pilot default
  is all 6 effects.

## 10. How to change safely

1. Keep the value unit identical to `doubles_eval.Evaluator` (equality test) and the
   baseline + `min_gain` rule in `choose_pair_refined`.
2. New per-scenario state: add it as a `Resolution` attribute in `__init__` (one
   Resolution = one scenario, never reused). TurnSim caches (`_joint`, `_plans`, `_orders`,
   `_foe_rolls_cache`, `_gains`) are keyed on inputs - extend the key if the new state
   changes the result, and clear `_joint` where `set_candidates` does.
   `tests/test_turn_sim.py` calls `ts._run(...)` directly; keep that signature.
3. Watch cost: scenarios multiply (hypotheses x kinds x cuts). Re-run the timing tests and
   check per-decision ms in a short live smoke before a paired run.
4. Constant / rule changes alter GA fitness: paired run (`tools/paired_eval.py`), then
   record date + numbers in docs/STATE.md.
5. `bash tools/verify.sh` must end `ALL PASS`.

## Related docs

- [pilots.md](pilots.md) - how the pilot builds TurnSim inputs and candidates
- [pilots-support.md](pilots-support.md) - support effects and their results
- [damage.md](damage.md) - damage rolls, speed_model, opp_model, mega_model
- [battle-memory.md](battle-memory.md) - opp_actions priors, Taunt / TR turns
- [battle-harness.md](battle-harness.md) - 50-turn cap, TimeoutPlayer
- [eval.md](eval.md) - paired comparisons
