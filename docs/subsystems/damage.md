# Damage, speed, opponent-set and foe-Mega models

Covers the pure-math layer the battle pilots score with: Champions stat and damage rolls
(`src/damage.py`), who-moves-first probabilities (`src/speed_model.py`), hidden opponent
builds/abilities (`src/opp_model.py`) and P(foe Mega Evolves this turn) (`src/mega_model.py`).
Read it before changing damage numbers, speed order, opponent inference or Mega prediction.

Last verified against code: 2026-11-18

## 1. Purpose

poke_env does not know Champions EVs, never fills opposing `Pokemon.stats`, and does not track
speed order or foe Megas. These four torch-free, poke_env-free modules turn "species + what we
have seen" into numbers: damage roll lists, P(we move first), weighted build mixtures and
P(Mega now). Consumers: `src/doubles_eval.py`, `src/turn_sim.py`, `src/turn_sim_types.py`,
`src/pilot_world.py`, `src/pilot_sim_input.py`, `src/pilot_actions.py`, `src/support_value.py`,
`src/smart_player.py`, `src/vgc_pilot.py` (see pilots.md, turn-sim.md).
Format facts: `gen9championsvgc2026regmc`, doubles, level 50, Mega legal, NO Tera,
EVs are points 0-32 per stat (66 total) with stat term `max(2*pts-1, 0)`.

## 2. Files

| path | lines | role |
|---|---|---|
| src/damage.py | 305 | stats at level, 16-roll damage, range, KO chance |
| src/speed_model.py | 127 | effective Speed, SpeedBelief mixture, `p_faster` |
| src/opp_model.py | 210 | opponent build mixture, ability/item/move distributions, immunity prob |
| src/mega_model.py | 108 | foe Mega candidates, P(Mega now), Mega gain |

Data read: `data/regmc_db.json` (damage `_raw_db`, via `src/regmc_db.py`),
`data/species_build_priors.json` + `data/species_ability_priors.json` (opp_model, blended corpus +
metavgc priors, `tools/blend_priors.py`), `data/species_archetypes.json` (via `src/archetypes.py`),
`data/mega_rates.json` (`tools/build_mega_rates.py`). All tracked in git.

## 3. Key formulas and data structures

**Stat** (`damage.stat_at_level(species, stat, ev=0, iv=31, nature=None, level=50)`), pts clamped 0..32,
`E = max(2*pts - 1, 0)`:
- HP: `floor((2*B + IV + E) * L / 100) + L + 10`
- other: `floor((2*B + IV + E) * L / 100) + 5`, then nature `int(x * 1.1)` / `int(x * 0.9)` (`NATURE_MODS`).
- Examples: Garchomp HP 0 pts = 183, 32 pts = 215; Garchomp Jolly 32 Spe = 169;
  Garchomp-Mega-Z Modest 32 Spe = 203. Unknown species -> 0.

**Damage** (`damage._rolls_core`, shared by both entry points). A/D are post-stage stats
(`_stage_mult`: +n -> (2+n)/2, -n -> 2/(2+n), clamped +-6):
1. Sand: Rock defender x1.5 SpD vs special; Snow: Ice defender x1.5 Def vs physical.
2. `base = floor(floor((2L/5 + 2) * BP * A / D) / 50) + 2` (integer ops, L = attacker level).
3. Spread x0.75 if doubles, `include_spread` and move target is `allAdjacent`/`allAdjacentFoes`.
4. Weather: rain Water x1.5 / Fire x0.5; sun Fire x1.5 / Water x0.5. Crit x1.5.
5. 16 rolls `int(base * (85+i) / 100)`, i = 0..15 (sorted ascending).
6. Per roll, each truncated: STAB x1.5 -> type effectiveness -> burn x0.5 (physical, not Guts)
   -> terrain (only if `attacker_grounded`: Electric/Grassy/Psychic boost own type x1.3, Misty
   Dragon x0.5) -> screens (Reflect/Light Screen/Aurora Veil: 2/3 in doubles, 1/2 singles,
   ignored on crit). A roll is at least 1 if effectiveness > 0.
- Effectiveness: product over defender types of typeChart codes `{0: 1, 1: 2, 2: 0.5, 3: 0}`.
- Status moves and BP <= 0 moves return `[]`.

**Speed** (`speed_model.effective_speed(stat, mods, ability, scarf)`):
`floor(stat * stage_mult)`, then x1.5 Scarf, x2 weather/terrain ability (`SPEED_ABILITIES`:
swiftswim/rain, chlorophyll/sun, sandrush/sand, slushrush/snow, surgesurfer/electric), x2 Tailwind,
x0.5 paralysis, floor once at the end.
- `SpeedMods(stage=0, paralyzed=False, tailwind=False, scarf=False, weather=None, terrain=None)`.
- `SpeedHypothesis(weight, stat, ability, scarf=False, mega_stat=None)`.
- `SpeedBelief(hypotheses)`: weights renormalized; falsy when empty.

**Build** (`opp_model.Build`, frozen): `weight, nature, evs, stats` (level-50, includes hp),
`item` (archetype path only), `form` (Mega form the set turns into, e.g. `Garchomp-Mega-Z`),
`form_stats` (stats after that Mega; None if no Mega or already Mega); `max_hp` property.
Example: `opponent_builds("Garchomp", moves_seen=["Power Gem"])[0]` -> item Garchompite Z,
nature Modest, Spe 154, `form_stats` Spe 203 / SpA 212.

**mega_rates.json**: `{"cells": {"k0_lead|1": 0.6482, "k0_back|1": 0.6945, "k0_lead|2": 0.313,
"k1|1": 0.3631, "k2|1": 0.1404, "k3|1": 0.0769, ...}, "hold_floor": 0.8, "n_rows": 15755,
"n_stone_revealed": 18, "species_rel": {"Excadrill": 0.1636, "Blastoise": 1.4103, ...}}`.
`cell_key(k, ncand, lead)` = `k0_lead|n` / `k0_back|n` for k <= 0, else `k{min(k,3)}|n`,
n = min(max(ncand,1),2).

## 4. Public API

damage (`src/damage.py`):
- `stat_at_level(species_name, stat, ev=0, iv=31, nature=None, level=50) -> int`.
- `damage_rolls(attacker_species, attacker_evs, attacker_nature, move_name, defender_species,
  defender_evs, defender_nature, attacker_level=50, defender_level=50, is_doubles=True,
  include_spread=True, crit=False, burn=False, weather=None, terrain=None, attacker_boosts=None,
  defender_boosts=None, attacker_grounded=True, reflect=False, light_screen=False,
  aurora_veil=False, attacker_ability=None) -> list[int]` (16 rolls or []).
- `damage_rolls_from_stats(attacker_stats, attacker_types, attacker_boosts, move_name,
  defender_stats, defender_types, defender_boosts, **same modifier kwargs) -> list[int]` - final
  stats (dict hp/atk/def/spa/spd/spe), DB-cased types, level fixed 50. Used by doubles_eval,
  turn_sim, smart_player.
- `damage_range(...) -> (min, mean, max)` ((0,0,0) if no rolls); `ko_chance(...) -> float`
  (fraction of rolls >= defender max HP).
- Used by other modules: `damage.DB` (the `regmc_db` module), `_raw_db()` (raw DB dict),
  `_stage_mult`, `_effectiveness(move_type, defender_types)`.

speed_model (`src/speed_model.py`):
- `effective_speed(stat, mods=SpeedMods(), ability=None, scarf=False) -> int`.
- `SpeedBelief.speeds(mods=SpeedMods(), mega=0.0) -> [(weight, speed)]` - `mega` = P(this mon
  Megas now) (True = 1.0); only hypotheses with `mega_stat` can Evolve, each with
  `q = conditional_q(mega, mass of those hypotheses)`, split into post-Mega (q) and pre-Mega (1-q).
- `SpeedBelief.p_faster(our_speed, mods=SpeedMods(), trick_room=False, mega=0.0) -> float` -
  P(we act first among same-priority moves); ties count 0.5; Trick Room inverts; empty belief 0.5.
- `belief_for(species, known_ability=None, item=None, moves_seen=()) -> SpeedBelief` - opp_model
  builds x ability distribution; a Choice Scarf build sets `scarf`, a Mega build sets `mega_stat`.

opp_model (`src/opp_model.py`; constants `LEVEL=50`, `TOP_K=3`, `ARCHETYPE_K=6`):
- `opponent_builds(species, k=None, item=None, moves_seen=(), ability=None) -> list[Build]`
  (weights sum to 1; [] if species unknown).
- `ability_distribution(species, known_ability=None) -> {ability_id: p}`.
- `immunity_prob(species, move_type, known_ability=None) -> float` (via `IMMUNITY_ABILITIES`:
  levitate/eartheater Ground; flashfire/wellbakedbody Fire; waterabsorb/stormdrain/dryskin Water;
  voltabsorb/lightningrod/motordrive Electric; sapsipper Grass).
- `item_distribution(species, item=None, moves_seen=())`, `move_distribution(species, item=None,
  moves_seen=())` -> dicts ({} without enough real sets).
- `resolve_species(species) -> DB name | None`; `to_id(name)`; `stats_for(db_name, evs, nature)`.

mega_model (`src/mega_model.py`; constants `CONSUMED_P=0.02`, `MAX_P=0.98`):
- `capable_species() -> frozenset` (DB species with `megaStones`); `stone_ids() -> frozenset`.
- `p_mega_now(species, k, ncand, lead, item=None, consumed=False, rates=None) -> float`.
- `candidates(mem, side, turn=None) -> [dict(name, species, k, ncand, lead, item, consumed)]`.
- `foe_mega_probs(mem, side, rates=None) -> {mon name: p}` (sum <= 1).
- `conditional_q(p_now, form_mass) -> float` = `min(1, p_now / form_mass)` (0 if mass 0).
- `mega_gain(species, stone) -> (offence gain, Speed gain) | None` in base stats; offence =
  `max(atk, spa)` difference. `mega_gain("Garchomp", "garchompitez") == (11, 49)`.

## 5. Flows

A. Opponent builds (`opponent_builds`):
1. `resolve_species` (id match over DB names/ids); unknown -> [].
2. Archetype path if `species_archetypes.json` has >= `MIN_SETS` (5) sets for the species (a Mega
   species looks up its base row and filters by its own form; ability evidence is dropped for a
   Mega'd mon because the table holds pre-Mega paste abilities). Posterior (foundation.md) ->
   each group split by its spreads -> merge by (nature, evs, item, form) -> top `ARCHETYPE_K`.
3. Else marginal priors: top `TOP_K` entries of `species_build_priors.json` by count (key = exact
   name, else the part before `-Mega`).
4. Else one generic build: Adamant 32 HP/32 Atk/2 Spe if Atk >= SpA else Modest 32 HP/32 SpA/2 Spe.

B. Ability distribution: revealed -> certain; Mega form -> uniform over its DB abilities (priors
hold the pre-Mega ability: Golisopod-Mega -> Tough Claws, Golisopod -> Emergency Exit); else
`species_ability_priors.json` counts; else uniform over DB abilities.

C. Foe Mega (`VGCPilot.choose_move` -> `foe_mega_probs(memory, foe_side)`):
1. No candidates if the side already Mega'd. Candidates = active, not fainted, not Mega'd mons of
   Mega-capable species; `k = turn - max(switch_in_turn + 1, 1)`, `lead = switch_in_turn == 0`.
2. `p_mega_now`: item consumed -> 0.02; revealed non-stone item -> 0.0; else
   `cells[cell_key] * species_rel[species]` (missing cell -> back cell -> 0.1); a revealed stone
   gives `min(cell / hold_floor, 0.98)` instead. Clamp to [0, 0.98].
3. Renormalize the side's probabilities if their sum > 1 (one Mega per side).
4. The pilot feeds P (`VGCPilot._mega_prob`) into `SpeedBelief.speeds(..., mega=p)`
   (`src/pilot_sim_input.py`) and into `src/pilot_world.py::PilotWorldMixin._foe` (Mega types /
   stats / immunity mixture via `conditional_q`). The base `DoublesPilot` returns 0.0.

## 6. Invariants

- Immune typeChart code is 3 (`_CODE_TO_MULT`). Before 2026-10-15 code 4 was mapped, so every
  immunity was x1.0 (Earthquake hit Flying); pinned by `test_type_immunities_deal_zero`.
- Rolls: 16 values, sorted ascending; `damage_range(GARCHOMP_EQ) == (134, 147, 162)`.
- `opponent_builds` and `SpeedBelief` weights sum to 1; `speeds(mega=x)` weights sum to 1.
- `foe_mega_probs` sums to <= 1 per side; `p_mega_now` <= 0.98.
- `p_faster` == 0.5 for an empty belief; Trick Room inverts the comparison.
- A Mega'd species' build has `form_stats is None`; Garchomp-Mega-Z: Spe 203, SpA 212, Levitate.

## 7. Config, env vars, constants

No env vars are read by these four modules. Tunables live as module constants: `TOP_K=3`,
`ARCHETYPE_K=6`, `IMMUNITY_ABILITIES`, `SPEED_ABILITIES`, `CONSUMED_P=0.02`, `MAX_P=0.98`.
Fit-time constants: `tools/build_mega_rates.py` `SHRINK=30` pseudo-observations toward
species factor 1, `MIN_SPECIES_N=10`. Rebuild rates: `python tools/build_mega_rates.py [--dry-run]`
(needs `data/showdown_replays/`, not in git).

## 8. Tests

- `python tests/test_damage.py` (10): regression pins (spread/single-target rolls, crit, burn,
  rain, stats variant, immunities, range, KO chance). Pins were captured from the code after a
  ~12k-case bit-identity check with the pre-refactor version; they are NOT a Showdown oracle.
- `python tests/test_speed_model.py` (9): modifiers, ability conditions, ties, Trick Room,
  mixtures, `belief_for`, Mega ability (also covers `opp_model.ability_distribution`).
- `python tests/test_mega_z_lines.py` (10): real-data golden tests for Garchomp/Lucario/Absol Z lines.
- `python tests/test_mega_model.py` (9): candidates from memory, k growth, probability shape,
  side sum, `conditional_q`, `mega_gain`, `DoublesPilot._foe` Mega type split (needs poke_env).
- All four run in `bash tools/verify.sh` (must end `ALL PASS`). There is no `tests/test_opp_model.py`.

## 9. Gotchas and known issues

- Accuracy vs Showdown: 2026-10-15 the base formula was checked on Garchomp/Incineroar/Rillaboom
  and base/rain/-1 Atk/+2 Def/crit/burn/Reflect cases matched. Unverified: any systematic
  comparison since. Rounding uses Python `int()` truncation per step, Showdown uses 4096-based
  `modify` rounding, so 1-point differences are possible.
- Not modelled in damage: items (Choice Band/Specs, Life Orb, Expert Belt...), abilities other than
  Guts-vs-burn (Intimidate only via `attacker_boosts`), Helping Hand (handled in `support_value`),
  variable-BP and multi-hit moves, crits ignoring stages, Grassy Terrain halving Earthquake,
  Psychic Terrain blocking priority. Misty Terrain's Dragon halving is gated on the ATTACKER
  being grounded (Showdown checks the target). The 0.75 spread factor applies even if only one
  target remains. `attacker_ability` is used only for Guts.
- `damage_rolls_from_stats` always uses level 50.
- Speed not modelled: Unburden, Quick Feet, Slow Start, Quick Claw / Custap / Lagging Tail / Stall
  (BattleMemory already exposes `speed_flags`); speed stage 2 (reweight from observed order via
  `BattleMemory.speed_pairs`) is planned, not built.
- `opp_model._build_priors` / `_ability_priors` raise FileNotFoundError if the JSON is missing
  (no fallback, unlike `archetypes.load_table`).
- poke_env keeps a foe's `item` as `unknown_item` after it Megas, so a Mega'd foe is identified
  by species name, not item.
- Mega data findings (5,006 replays, 2026-10-16): 85% of sides Mega; 79% on the mon's first
  opportunity, 52% on turn 1; P(Mega now) by k: 61%, 33%, 12%, 9%, 7%; two candidates on field ->
  35% each at first opportunity vs 67% alone. Holdout log-loss: flat 0.693, by k 0.628, cell table
  0.601, cell x species 0.555. Humans Mega the larger offence gain in 74% of 499 turn-1 pairs
  (hence `mega_gain`); win rate by Mega timing is flat, so there is no "save the Mega" rule.
- `mega_model` only covers mons on the field; a back-slot foe's Mega is ignored until it enters.

## 10. How to change safely

1. Damage change: keep `_rolls_core` shared by both entry points; run `python tests/test_damage.py`.
   If pins move on purpose, re-derive them and say why in the commit; recheck an immunity case.
2. Speed change: `tests/test_speed_model.py`, `tests/test_mega_z_lines.py`, `tests/test_mega_model.py`,
   `tests/test_turn_sim.py` (turn_sim orders moves with `speeds`).
3. opp_model change: `tests/test_mega_z_lines.py` (Garchomp acceptance) and `tests/test_doubles_eval.py`.
4. Refit `mega_rates.json` only with replays present; compare `--dry-run` log-loss to 0.555 first.
5. Run `bash tools/verify.sh`; behaviour changes need a paired live comparison (see eval.md).

## Related docs

- [foundation.md](foundation.md) - regmc_db, archetype posterior, paths
- [battle-memory.md](battle-memory.md) - BattleMemory (input of mega_model) and opp_actions
- [pilots.md](pilots.md), [turn-sim.md](turn-sim.md) - consumers of these models
- [eval.md](eval.md) - paired comparisons for behaviour changes
- [../reference/data-files.md](../reference/data-files.md) - priors, archetypes, mega_rates
- [../runbooks/data-pipeline.md](../runbooks/data-pipeline.md) - rebuilding priors and rates
