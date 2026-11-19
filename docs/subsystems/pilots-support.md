# Pilots: support-move layer

The support-move layer lets `DoublesPilot` / `VGCPilot` value non-damaging or
stat-changing moves (Foul Play, Snarl, Charm, Helping Hand, Taunt, self-heals) from move
data, inside the turn_sim decision. Read this to change which support effects exist, their
flags and constants, or to interpret the paired results. General pilot flow:
[pilots.md](pilots.md); simulator internals: [turn-sim.md](turn-sim.md).

Last verified against code: 2026-11-18

## 1. Purpose

Goal (2026-10-16 handoff): find the best team around Umbreon, whose builds vary (Foul Play,
Snarl, Taunt, Moonlight, Helping Hand, Charm...). The plain pilot values only damage this
turn, so support moves were never picked. The layer reads effects from the move DB
(`data/regmc_db.json`, built by `tools/build_regmc_db.js`), not per species, and feeds
them into `turn_sim.TurnSim`. It only works on the turn_sim path (`DOUBLES_TURN_SIM=1`,
the default). Format reminder: Reg M-C doubles, Mega legal, no Tera.

## 2. Files

| path | lines | role |
|---|---|---|
| src/support_value.py | 202 | effect names, flags, constants, DB readers (`foe_drop`, `pure_kind`, `effect_of`, `heal_fraction`, `drop_outcomes`) |
| src/pilot_actions.py | 82 | `_sim_kind` -> `"support"`, `_sim_action` builds support `Action`s |
| src/pilot_world.py | 144 | `_is_attack_candidate` admits Foul Play only with `foulplay` on |
| src/doubles_eval.py | 180 | `Evaluator.rolls`: Foul Play uses the target's Atk when on |
| src/turn_sim.py | 434 | `TurnSim`: `tr` outcome, `_drop_gain`, `_tr_cost`, support costs in `pair_value` |
| src/turn_sim_resolve.py | 247 | `Resolution` (body of `TurnSim._run`): drops (`land`), Helping Hand, Taunt vs Trick Room, heals, in move order |
| src/turn_sim_lookahead.py | 129 | `LookAhead`: optional next-turn value of drops / Trick Room |
| src/doubles_pilot.py | 246 | `self.effects`, `self.lookahead`, `sup_<effect>` counters |
| src/pilot_support.py | 75 | NOT part of the layer: dead no-op stubs |

## 3. Effects (`support_value.EFFECTS`, exactly 6)

| effect | which moves (from DB) | modelled as |
|---|---|---|
| `foulplay` | `overrideOffensivePokemon == "target"` | damage with the TARGET's Atk stat and stage (ours and foe's); otherwise Foul Play is unmodelled and left to vanilla |
| `snarl` | damaging move whose `secondary.boosts` lowers atk/spa (Snarl, Mystical Fire, Struggle Bug) | stage drop applied to later foe hits this turn + persistence term |
| `charm` | Status move, foe target, `boosts` lowers atk/spa (Charm, Noble Roar); `pure_kind == "drop"` | same drop mechanics, pure support |
| `helpinghand` | Helping Hand | x1.5 rolls on the partner's next attack this turn (priority +5 acts first) |
| `taunt` | Taunt | a foe Trick Room this turn fails (Taunt +0 beats TR -7); taunted foe cannot Protect / set TR |
| `heal` | self-target Status move with DB `heal: [n, d]`, plus `WEATHER_HEALS` | HP pmf shifted up by the fraction at the actor's place in move order |

Real values (2026-11-18): `foe_drop("snarl") = Drop((("spa", -1),), 1.0, "secondary")`;
`foe_drop("charm") = Drop((("atk", -2),), 1.0, "status")`; `foe_drop("nobleroar")` drops
both by 1. `heal_fraction`: Recover / Roost / Slack Off / Soft-Boiled 0.5; Moonlight /
Synthesis / Morning Sun 0.5, sun 2/3, rain/sand/snow/hail 0.25; Rest, Wish, Life Dew 0.0
(not modelled). Speed drops (Icy Wind) and Parting Shot (`selfSwitch`) give no Drop.
Growl is not in the DB, so it is not recognised despite the docstring.

`drop_outcomes(drop, abilities)` folds the foe's ability distribution: blocked by Clear
Body, White Smoke, Full Metal Body, Mirror Armor (treated as a block); Hyper Cutter blocks
Atk only; Shield Dust blocks secondary drops; Magic Bounce / Good as Gold block status
drops; Contrary reverses; Simple doubles; Defiant / Competitive +2 in their stat. Example:
Charm vs `{clearbody: 0.3, defiant: 0.2, None: 0.5}` -> `[(0.5, 0, 0), (0.5, -2, 0)]`.

## 4. Public API (src/support_value.py)

- `parse_effects(spec=None)` -> frozenset; None = env `DOUBLES_SUPPORT`, then `DEFAULT_SUPPORT`; `"", "0", "off", "none"` -> empty; `"all", "1", "on"` -> all 6; unknown names raise `ValueError`.
- `lookahead_enabled(flag=None)` -> bool (env `DOUBLES_LOOKAHEAD`, default off).
- `foe_drop(move)` -> `Drop | None`; `pure_kind(move)` -> `"helpinghand" | "taunt" | "heal" | "drop" | None`.
- `effect_of(move)` -> effect name or None (used for `sup_<effect>` counters).
- `pure_enabled(move, effects)` -> bool; `is_foulplay(move)` -> bool.
- `heal_fraction(move, weather=None)` -> float; `drop_outcomes(drop, abilities)` -> `[(p, d_atk, d_spa)]`.
- `shifted(boost, delta)` -> stage clamped to +-6; `discounted_turns(n, gamma)` -> `gamma + ... + gamma^n`.

## 5. Flow

1. `DoublesPilot.__init__`: `self.effects = parse_effects(support)`;
   `self.lookahead = lookahead_enabled(lookahead) and bool(self.effects)`.
2. Candidates: `_sim_kind` returns `"support"` when `pure_enabled(move, effects)`.
   `_sim_action`: heal -> `Action(slot, move, ())`; Helping Hand -> `Action(slot, move, ())`
   only if the partner `a<1-slot>` is in the world; Taunt / drop moves -> targeted like
   attacks (`_targeted`). Snarl-type and Foul Play are ordinary attack candidates.
3. `TurnSim.shortlist` keeps every support candidate; `set_candidates` turns on the foe
   `tr` outcome when `taunt` is on, a Taunt is a candidate and Trick Room is down.
4. `TurnSim._run` -> `src/turn_sim_resolve.py::Resolution` applies effects in move order
   (`our_hit`, `land`, `value`; turn-sim.md section 5).
5. `pair_value` subtracts `support_cost` (0.15) per pure-support action that is not a heal
   (a heal's cost is the attack it replaces; at full HP it is worth exactly 0).
6. Without LookAhead, after-turn value is heuristic: drop persistence
   `ally_weight * SUPPORT_HORIZON * FOE_STAY * P(landed) * P(foe alive) * _drop_gain`
   (damage saved per later turn against the move the mirror foe uses), and Taunt earns
   `_tr_cost() * (1 - P(taunted))` with `_tr_cost = TR_HORIZON * (best pair with TR up -
   best pair without)`.
7. With LookAhead (`DOUBLES_LOOKAHEAD=1`, built only when a support or drop candidate
   exists): those two terms are replaced by `h * (V1(s' + d) - V1(s'))`, `h_drop = 2.0 *
   0.7 = 1.4`, `h_tr = discounted_turns(4, 0.7) = 1.773`.
8. Chosen orders whose `effect_of` is enabled increment `sup_<effect>`.

## 6. Invariants (tests/test_support.py, 28 tests)

- Identity: with no support action among candidates, values equal the layer-off values;
  heal is identity when the effect is off; pilot offers heals only when `heal` is on.
- Snarl pays vs a special foe that moves after us, not vs a physical foe or a blocker;
  Charm worth a turn vs a strong physical foe, not vs Defiant.
- Pure support pays the tempo cost; Helping Hand boosts the partner and acts first.
- Taunt denies a likely Trick Room only when TR hurts us; inert when TR is up or the foe
  cannot set it; a Taunted foe cannot Protect or set TR; TR turns kept only while up.
- Heal: worth a turn when hurt, 0 at full HP, saves from a KO only when moving first,
  nothing if the healer is KO'd first.
- LookAhead: values Taunt vs TR with no KO this turn; no TR credit vs a foe we KO first;
  ignores TR about to end; Snarl pays vs special not physical; pilot enables it only with
  a state-changing candidate; extra time < base + 0.25 s.
- `effect_of("toxic") is None` (asserted).

## 7. Config / env / constants (src/support_value.py, read at IMPORT unless noted)

| name | default | effect |
|---|---|---|
| `DOUBLES_SUPPORT` (read at pilot init) | `DEFAULT_SUPPORT = "all"` | comma list of the 6 names, `all`, or empty/`off` |
| `DOUBLES_SUPPORT_COST` -> `SUPPORT_COST` | 0.15 | tempo cost per non-heal pure-support action |
| `DOUBLES_SUPPORT_HORIZON` -> `SUPPORT_HORIZON` | 2.0 | later turns a drop keeps paying |
| `DOUBLES_SUPPORT_STAY` -> `FOE_STAY` | 0.7 | P(dropped foe still in play) |
| `DOUBLES_TR_HORIZON` -> `TR_HORIZON` | 2.0 | turns of TR a Taunt denies (heuristic path) |
| `DOUBLES_LOOKAHEAD` (pilot init) | off (`DEFAULT_LOOKAHEAD = False`) | LookAhead continuation |
| `DOUBLES_LOOKAHEAD_GAMMA` -> `LOOKAHEAD_GAMMA` | 0.7 | discount for TR turns in LookAhead |
| `DOUBLES_LA_LOG` (doubles_pilot) | unset | JSONL of decisions the LookAhead changed, counter `la_diff` |
| `TR_TURNS_AFTER_SET`, `HELPING_HAND_MULT`, `MAX_STAGE` | 4, 1.5, 6 | constants |

Pilot kwargs `support=` / `lookahead=` win over env. All costs / horizons are untuned guesses.

## 8. Tests

`python tests/test_support.py` (28, in `bash tools/verify.sh`). Live effect only via
`tools/paired_eval.py --mode support --support <list|all> [--team a.txt,b.txt] --tag X`
(support off vs on, turn_sim on in both) or `--mode lookahead` (support on, lookahead off
vs on); Umbreon test teams in `data/paired_eval/teams/umb_*.txt`. See eval.md.

## 9. History and measured results (all `ladder` opponent, paired, same matchups)

- 2026-10-20 slice 1 (foulplay, snarl, charm, helpinghand, taunt; commit `fe46b0a`, then
  default OFF). Crash check 126 pairs: +5.6 pts [-5.3, +16.4], n.s.; Taunt never chosen.
  Full run tag `s1`, `umb_*` teams, 1206 pairs: on 77.1% vs off 72.6%, +4.6 pts [+1.2,
  +8.0], McNemar p=0.010; per team baseline +4.3, helpinghand -1.0, charm +8.3 (p=0.029),
  moonlight +6.7; chosen: foulplay 1211, snarl 694, helpinghand 109, charm 14, taunt 0.
- 2026-10-20 LookAhead (commit `82a5b3d`). Tag `la`, 2406 pairs: off 76.4% vs on 74.8%,
  -1.5 pts [-3.9, +0.8], p=0.21. Tag `ladiag` (moonlight team, 3581 pairs): +1.3 pts
  [-0.7, +3.3], p=0.21. Pooled ~6000 pairs: neutral. `DOUBLES_LA_LOG`: 398 differing
  decisions, almost all Snarl <-> Foul Play swaps; foe TR prob > 0.2 in only 4 rows. Cost
  +7 ms per decision (~+14%). Decision: LookAhead stays OFF (kept for TR-heavy matchups).
- 2026-10-20 plain-pool control (tag `ctl`, support `all` vs off, 1806 pairs, 0 errors):
  75.6% vs 73.5%, +2.2 pts [-0.5, +4.8], p=0.124 (chosen: snarl 284, helpinghand 169,
  charm 4, foulplay 0, taunt 0): no regression for builds without support moves.
- 2026-10-20 heals (slice 3a) added as the 6th effect. Planned paired run on
  `umb_moonlight`: Unverified (no result recorded).
- 2026-11-12 `DEFAULT_SUPPORT` flipped `""` -> `"all"` (commit `8b28efb`, citing the
  control above). So GA fitness battles use the layer since then.
- 2026-11-12 STATE.md section "Slice 3 Support Effects ... COMPLETED" is FALSE: it claims
  Toxic, Will-O-Wisp, Wish, Reflect, Light Screen, Tailwind effects, 12 effects and a
  `supportEffect` DB field. Code has 6 effects, no such field in `src/` or `tools/`, and
  `tests/test_support.py` asserts `effect_of("toxic") is None`.
- 2026-11-15 (docs/history/2026-11-12_to_11-18.md): q5 islands A/B (Umbreon-locked) overfit badly (train ~85% ->
  held-out ~47-49%); blamed on the fitness pilot not using Taunt / Yawn. Yawn is still
  not modelled; Taunt is valued only against Trick Room, never for Protect / setup denial.

## 10. Gotchas and how to change safely

- `support_value.py` docstring still says "empty = layer off (behaviour identical)"; the
  default is `all`. `TurnSim(effects=...)` defaults to empty: tests and direct callers get
  no layer unless they pass effects.
- `is_support` (turn_sim_types) docstring omits heals but includes them (any `pure_kind`).
- To add an effect: name in `EFFECTS`, DB reader in `support_value` (prefer DB fields over
  move lists), candidate in `_sim_kind` / `_sim_action`, mechanics in `src/turn_sim_resolve.py::Resolution.our_hit` / `land` / `value`,
  shortlist keeps it, tests for identity-when-off and value-when-on, then a paired run
  (`--mode support --support <name>`) before it can be on by default. Record the result
  with date in docs/STATE.md.
- Changing any constant here changes GA fitness; old and new scores are not comparable.
- `bash tools/verify.sh` must end `ALL PASS`.

## Related docs

- [pilots.md](pilots.md) - pilot classes, turn decision flow, pilot flags
- [turn-sim.md](turn-sim.md) - how `Resolution` (`TurnSim._run`) applies the effects; LookAhead details
- [damage.md](damage.md) - damage rolls and the move DB fields used here
- [eval.md](eval.md) - paired_eval modes
- [../reference/config-and-env.md](../reference/config-and-env.md)
