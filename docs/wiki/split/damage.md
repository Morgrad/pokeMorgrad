# Damage System

This section covers the core battle calculation and evaluation components.

## damage.py (305 lines)
Champions-format damage estimator mirroring Showdown's `data/mods/champions` math (docstring `damage.py:1-18`).
- Stat formula: EV points 0-32, term `max(2*pts-1, 0)` (`_ev_term`, `damage.py:53`); `stat_at_level` with nature 1.1/0.9.
- Type effectiveness from `typeChart` damageTaken codes `{0:1,1:2,2:.5,3:0}`; immune code is 3 (`damage.py:36`; regression-pinned in tests).
- `_rolls_core` (`damage.py:132`) is the shared core: 16 rolls (85..100%), spread x0.75 (only if `include_spread` and target is allAdjacent/allAdjacentFoes), weather, crit, STAB, eff, burn (not with Guts), terrain (only if `attacker_grounded`), screens (2/3 in doubles, ignored on crit), floor of 1 if eff > 0.
- Entry points: `damage_rolls` (species + EVs + nature), `damage_rolls_from_stats` (final stat ints, level fixed 50; used by doubles_eval), `damage_range` -> (min, mean, max), `ko_chance`.
- Imports `regmc_db`, `paths`. Torch-free. Reads `data/regmc_db.json` via `_raw_db()`.
- Gotchas: `defender_ability`, `defender_grounded` are accepted by `damage_rolls` but unused in the math; `defender_level` is used for the defender stat. The docstring lists `defender_ability` as "damage-relevant" (`damage.py:15`) but nothing consumes it.

## opp_model.py (~155 lines)
Torch-free, poke_env-free model of hidden opposing builds.
- `Build` dataclass (weight, nature, evs, stats, item, form, form_stats; `max_hp`); `opponent_builds(species, k=None, item=None, moves_seen=(), ability=None)`: with >= 5 real sets in `data/species_archetypes.json` (via `src/archetypes.py`) it returns the top `ARCHETYPE_K=6` builds of the posterior given the revealed item / moves / ability / Mega form (`form_stats` = stats after the Mega); otherwise up to `TOP_K=3` marginal builds from `data/species_build_priors.json`, else a generic spread (Adamant/Modest, 32 HP / 32 offense / 2 Spe). `item_distribution` / `move_distribution(species, item, moves_seen)` give the marginals ({} without real sets). See STATE.md §5.24.
- `_prior_key` falls back to the base species for `-Mega` forms; `resolve_species`, `stats_for`, `ability_distribution(species, known_ability=None)` -> `{ability id: prob}` (a Mega form returns its DB Mega ability with certainty, because the priors hold the paste/pre-Mega ability) from `data/species_ability_priors.json` (revealed ability = certain, DB abilities uniform if no prior); `immunity_prob(species, move_type, ability)` is built on it with the `IMMUNITY_ABILITIES` map. LEVEL=50.
- Imports `archetypes`, `damage`, `paths`. Importers: doubles_pilot, speed_model, tests.