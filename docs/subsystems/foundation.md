# Foundation: paths, format DB, meta weights, set archetypes

Covers the bottom layer every other subsystem imports: repo path resolution (`src/paths.py`),
the canonical Reg M-C format database and local team validator (`src/regmc_db.py`), the
opponent-team weights used by GA fitness (`src/meta_weights.py`) and the real-set archetype
posterior used by the opponent model (`src/archetypes.py`). Read it before touching file
locations, team parsing/validation, fitness weighting or opponent set inference.

Last verified against code: 2026-11-18

## 1. Purpose

- `paths.py`: single source of truth for where the repo, `data/`, `output/` and the Showdown
  checkout live. Added 2026-10-13 after hardcoded `/home/morgrad/...` paths silently produced an
  EMPTY opponent pool on a new host.
- `regmc_db.py`: torch-free data layer over `data/regmc_db.json` (Showdown dex export for format
  `gen9championsvgc2026regmc`: Reg M-C, Champions mod, doubles, Mega legal, NO Tera). Lookups,
  paste parsing, and `validate_team`, the fast LOCAL legality check (GA genome validity, audit).
  The authoritative check is Showdown's validator (`src/showdown_validator.py`, see battle-harness.md).
- `meta_weights.py`: how much each opponent team counts in the GA fitness: mean ladder usage of
  its six species. Fitness = weighted win rate (via `src/ga/fitness.py`).
- `archetypes.py`: P(which real set is this opposing mon running | what we have seen). Feeds
  `src/opp_model.py` (see damage.md). Pure data in, pure data out (no torch, no poke_env).
- `src/__init__.py`: empty (0 lines); only makes `src` a package. Run code from the repo root.

## 2. Files

| path | lines | role |
|---|---|---|
| src/paths.py | 46 | REPO_ROOT + data/output/src path helpers, Showdown dir |
| src/regmc_db.py | 354 | DB load + indexes, lookups, `normalize_species_name`, `parse_team`, `validate_team` |
| src/meta_weights.py | 91 | species usage from replays, team weight, weighted win rate |
| src/archetypes.py | 99 | archetype posterior + item/move marginals |
| src/__init__.py | 0 | package marker |
| data/regmc_db.json | (997 KB) | format DB, built by `node tools/build_regmc_db.js` (tracked) |
| data/species_ladder_usage.json | (7.5 KB) | usage table, built by `tools/build_meta_weights.py` (tracked) |
| data/species_archetypes.json | (364 KB) | archetype table, built by `tools/build_archetypes.py` (tracked) |

## 3. Key concepts and data shapes

**REPO_ROOT resolution** (`src/paths.py::_resolve_repo_root`, evaluated once at import):
1. env `POKEMORGRAD_ROOT` if set: expanded + resolved; must contain `data/` else `RuntimeError`.
2. else parent of `src/` (`Path(__file__).resolve().parent.parent`).
`showdown_dir()` is independent: env `SHOWDOWN_DIR`, default `~/pokemon-showdown`.

**data/regmc_db.json** top-level keys: `meta, rules, natures, types, typeChart, items, moves,
abilities, species`. Current `meta`: `{"format": "gen9championsvgc2026regmc", "formatName":
"[Gen 9 Champions] VGC 2026 Reg M-C", "mod": "champions", "built": "2026-10-20T18:52:31.101Z"}`.
Counts: 392 species (230 with `forme == null`), 166 items, 515 moves. Species entry (moves omitted):
```
"Garchomp": {"name": "Garchomp", "id": "garchomp", "baseSpecies": "Garchomp", "forme": null,
  "types": ["Dragon", "Ground"], "baseStats": {"hp":108,"atk":130,"def":95,"spa":80,"spd":85,"spe":102},
  "abilities": ["Sand Veil", "Rough Skin"], "tier": "OU", "isNonstandard": null,
  "megaStones": ["Garchompite", "Garchompite Z"], "moves": [...]}
```
Items carry `megaStone: {"<base species>": "<mega form>"}` for stones (e.g. Abomasite ->
`{"Abomasnow": "Abomasnow-Mega"}`). `typeChart[type]["damageTaken"][attackType]` uses Showdown
codes 0 normal, 1 weak, 2 resist, 3 immune (read by `src/damage.py`). Z-line Megas in the DB:
Absol-Mega-Z, Garchomp-Mega-Z, Lucario-Mega-Z.

**Mon dict** from `parse_team`: `{"species": str, "item": str, "ability": str|None,
"nature": str|None, "evs": {"hp": 32, "spe": 2, ...}, "moves": [str, ...]}`. EV keys are the
lowercased paste tokens (`HP` -> `hp`, `SpA` -> `spa`). EV values are Champions points (0-32
per stat, 66 total).

**Species key** (`meta_weights.species_key`): `normalize_species_name` then the DB `baseSpecies`,
then `norm()` (lowercase alnum). Every forme folds into its base: `Floette-Mega`, `Floette-Eternal`
-> `floette`; `Rotom-Wash` -> `rotom`; `Charizard-Mega-Y` -> `charizard`. Unknown names fall back to
`norm(raw.split(",")[0])`. The same key is used for paste species and replay `|poke|` lines.

**data/species_ladder_usage.json**: `{"n_sides": 10012, "floor": 0.02, "usage": {"rillaboom":
0.4165, "sneasler": 0.2986, "incineroar": 0.2946, ...}}` (204 species; usage = share of replay
team sides that carry the species; built 2026-10-16 from 5,006 replays).

**data/species_archetypes.json**: `{species: {"n": sets, "archetypes": [{"item", "nature",
"form", "count", "spreads": [{"evs", "count"}], "moves": {name: count}, "abilities": {name:
count}}]}}`. An archetype = an (item, nature) group of real sets. A Mega is stored under its BASE
species with `form` derived from the stone (pastes carry base species + stone). Current file: 145
species, 612 archetypes, 3,888 sets from 648 deduplicated teams (regional_teams + scraped
VGCPastes); 67 species have `n >= 5`. Example: Garchomp n=126, top groups (Garchompite Z, Modest,
form Garchomp-Mega-Z, 60), (Choice Scarf, Adamant, 21), (Life Orb, Jolly, 18).

## 4. Public API

paths (`src/paths.py`):
- `REPO_ROOT: Path` - resolved repo root.
- `data_path(*parts) -> str`, `output_path(*parts) -> str`, `src_path(*parts) -> str` - absolute
  path strings under `data/`, `output/`, `src/`.
- `showdown_dir() -> str` - `$SHOWDOWN_DIR` or `~/pokemon-showdown`.

regmc_db (`src/regmc_db.py`; usually imported `from src import regmc_db as DB`):
- `DB_PATH` - `data/regmc_db.json`. `norm(s) -> str` - Showdown id (`[^a-z0-9]` stripped).
- `load_db() -> dict` (lru_cached raw JSON); `_indexes()` (private; name/id lookup tables).
- `all_species()`, `all_species_base()` (forme is None), `all_items()`, `all_moves()`,
  `all_natures()` -> lists of DB dicts.
- `get_species(name)`, `get_item(name)`, `get_move(name)` -> dict or None (exact name, then id).
- `normalize_species_name(raw) -> str` - `"Hatterene (F)"` -> `Hatterene`, `"Indeedee-F (F)"` ->
  `Indeedee-F`, `"Aang (Staraptor)"` -> `Staraptor`; returns `raw` unchanged if unresolved.
- `is_legal_item(name) -> bool`; `species_can_learn(species, move) -> bool`;
  `species_has_ability(species, ability) -> bool` (formes also accept base/sibling-forme abilities,
  e.g. Salamence-Mega with Intimidate, because pastes carry the pre-Mega ability).
- `parse_team(text) -> list[mon dict]`; `validate_team(text) -> (ok: bool, errors: list[str])`.
- `python -m src.regmc_db` prints DB counts and validates `data/baseline_team.txt`.

meta_weights (`src/meta_weights.py`; imported as `MW`):
- `USAGE_PATH`, `FLOOR = 0.02`.
- `species_key(raw) -> str`; `team_keys(text) -> list[str]`.
- `usage_from_replays(replay_dir) -> (usage dict, n_sides)` - scans `*.json` (skips `*.meta.json`).
- `save_usage(usage, sides, path=USAGE_PATH)`; `load_usage(path=USAGE_PATH) -> dict` (lru_cached).
- `team_weight(text, usage=None, floor=FLOOR) -> float` - mean of `max(usage[k], floor)` over
  the team's species; `floor` if the team parses to nothing.
- `weighted_rate(outcomes, weights) -> float` - `sum(o*w)/sum(w)` over non-None outcomes, 0.0 if none.
- `effective_n(weights) -> float` - Kish effective sample size `(sum w)^2 / sum w^2`.

archetypes (`src/archetypes.py`):
- Constants `MISMATCH = 0.02`, `K = 2.0`, `MIN_SETS = 5` (MIN_SETS is read by `opp_model`).
- `load_table() -> dict` (lru_cached; `{}` if the file is missing).
- `posterior(entry, item=None, moves_seen=(), ability=None, form=None) -> [(weight, archetype)]`
  sorted desc, weights sum to 1 (`[]` if all weights are 0).
- `item_distribution(post) -> {item: p}`; `move_distribution(post) -> {move: P(set carries it)}`.

## 5. Flows

A. Local validation (`validate_team(text)`; called by `src/ga/evaluator.py` and
`src/audit_before_launch.py`):
1. `parse_team` splits on blank lines; a block whose first line has no `@` is SKIPPED.
2. Exactly 6 mons else return `(False, ["expected 6 mons, got N"])` immediately.
3. Species clause on DB `baseSpecies` (unknown species -> error); item clause on raw item strings.
4. Per mon: legal item, legal ability (normalized), exactly 4 moves, no duplicate moves,
   every move learnable, EV total <= 66, each stat <= 32.

B. Meta-weighted fitness (GA):
1. `src/ga/engine.py::_startup_checks` calls `MW.load_usage()` and raises if the file is
   unreadable (message tells you to run `tools/build_meta_weights.py` or set `GA_META_WEIGHTS=0`).
2. `src/ga/fitness.py::opp_weight` caches `MW.team_weight(text)` per opponent text (1.0 when off).
3. `src/ga/fitness.py::weighted_fitness(outcomes, opponents)` -> `(MW.weighted_rate(...), wins,
   valid_n)`; outcomes pair with opponents BY INDEX; `None` outcomes leave the denominator.

C. Rebuild usage when new replays arrive: `python tools/build_meta_weights.py [--replays
data/showdown_replays]` (writes `data/species_ladder_usage.json`, prints train/holdout weight
ranges and effective n). Needs `data/showdown_replays/` (not in git; absent in this checkout).

D. Archetype posterior (`posterior`), per archetype g of the species row:
1. If `form` is given, keep only groups with `g.form == form`; if none match, keep all.
2. `w = count_g`; revealed item (ignored if empty/`unknownitem`/`none`) that differs from
   `g.item` -> `w *= 0.02`.
3. Each seen move m: `w *= max(0.02, (c_g(m) + K * f(m)) / (count_g + K))` where `f(m)` = species
   total count of m / species `n`. Same smoothed factor for a revealed ability.
4. Normalize. Soft evidence: a move missing from a paste never zeroes a set.
Measured on real data (2026-10-16, pinned by `tests/test_mega_z_lines.py`): Garchomp no info ->
Z mass 0.4-0.8; Scarf/Life Orb revealed -> Z mass < 5%; Power Gem/Draco/Earth Power/Flamethrower
-> Z mass > 90%, top Modest 32 SpA.

## 6. Invariants

- Nothing outside `src/paths.py` builds repo paths by hand; tools bootstrap `sys.path` to the
  repo root and import `src.paths`.
- `validate_team` returns `(bool, list[str])` and takes TEXT (not mon dicts).
- Champions EV rules: <= 32 per stat, <= 66 total (also enforced by the GA genome).
- `species_key` must give the same key for a paste species and its replay `|poke|` name
  (`tests/test_meta_weights.py::test_replay_poke_line_species_matches_team_species`).
- `weighted_rate` drops `None`; `weighted_rate([1, 0, None], [3, 1, 100]) == 0.75`.
- `posterior` weights sum to 1; an unseen Mega form falls back to all groups.

## 7. Config, env vars, constants

| name | default | where read |
|---|---|---|
| `POKEMORGRAD_ROOT` | unset (use src/..) | `src/paths.py::_resolve_repo_root` at import |
| `SHOWDOWN_DIR` | `~/pokemon-showdown` | `src/paths.py::showdown_dir`; also `src/ga/config.py` |
| `GA_META_WEIGHTS` | `1` (on) | `src/ga/config.py` -> `GAConfig.meta_weights` |
| `meta_weights.FLOOR` | 0.02 | weight of a species unseen on the ladder |
| `archetypes.MISMATCH / K / MIN_SETS` | 0.02 / 2.0 / 5 | posterior + opp_model fallback threshold |

## 8. Tests

Run from the repo root with the venv active:
- `python tests/test_meta_weights.py` (6): species keys fold formes/nicknames/gender, replay vs
  paste keys match, floor, `weighted_rate`/`effective_n`, pool weights deterministic, and
  `src/ga/fitness.py::weighted_fitness` == `weighted_rate`.
- `python tests/test_archetypes.py` (6): synthetic table, no data files.
- `python tests/test_mega_z_lines.py` (10): real-data golden tests through `opp_model`.
- `python tests/test_blend_priors.py` (4): `tools/blend_priors.py` helpers with `regmc_db` natures/items.
- `bash tools/verify.sh` (the gate) imports `src.paths`, `src.regmc_db`, prints
  `data_path('regmc_db.json')`, runs these tests and `python -m src.audit_before_launch`; must end `ALL PASS`.

## 9. Gotchas and known issues

- `parse_team` drops any block whose first line lacks `@`, so an item-less mon makes
  `validate_team` fail with "expected 6 mons, got 5" rather than a clear error.
- `validate_team` does NOT check: nature validity, stone vs species match, Showdown-only rules
  (e.g. level, banned combos). Item clause compares raw strings (case/spacing variants slip
  through). Use the Showdown validator for the final word.
- `paths.REPO_ROOT` is fixed at import time: set `POKEMORGRAD_ROOT` before importing `src`.
- `damage.py` loads `regmc_db.json` a second time via its own `_raw_db()` (so "nothing else
  parses format data" in the regmc_db docstring is not strictly true).
- `meta_weights.load_usage` and `archetypes.load_table` are lru_cached per process: a rebuilt
  file is only seen by new processes.
- Weights are mild (2026-10-16): train pool 150 teams weight 0.072-0.266 (median 0.176),
  effective n 142/150; holdout 94/100. Old (pre 2026-10-16) GA scores are unweighted and not comparable.
- DB gaps (2026-10-16): empty movepools for Vivillon-Fancy, Vivillon-Pokeball, Gourgeist-Super,
  Polteageist-Antique, Sinistcha-Masterpiece. Lucario-Mega-Z was missing until
  `build_regmc_db.js` kept Megas' inherent abilities (Aura Guard is flagged `Future` by Showdown).
- Only 67 of 145 archetype species reach `MIN_SETS`; the rest use the marginal priors in
  `opp_model`. Rare Mega forms with 1 set are a single build.

## 10. How to change safely

1. New file location: add it via `data_path`/`output_path`; never hardcode `~/pokeMorgrad`.
2. Changing `validate_team` or `parse_team`: run `python -m src.regmc_db` (baseline must PASS),
   `python -m src.audit_before_launch`, and `bash tools/verify.sh`; GA genome validity depends on it.
3. Rebuilding `regmc_db.json`: `node tools/build_regmc_db.js` (needs the Showdown checkout);
   then re-run `tests/test_damage.py` (pins rolls) and `tests/test_mega_z_lines.py`.
4. Changing `species_key` or `FLOOR`: rebuild the usage file and note in docs/STATE.md that GA
   scores before/after are not comparable.
5. Changing archetype math: run `tests/test_archetypes.py` + `tests/test_mega_z_lines.py`, and
   check speed/damage consumers (`tests/test_speed_model.py`, `tests/test_mega_model.py`).

## Related docs

- [damage.md](damage.md) - damage math, speed model, opponent model, foe Mega model
- [battle-memory.md](battle-memory.md) - per-battle memory and foe action priors
- [ga.md](ga.md), [ga-genome.md](ga-genome.md) - fitness and genome legality that use this layer
- [battle-harness.md](battle-harness.md) - Showdown validator (authoritative legality)
- [../reference/data-files.md](../reference/data-files.md) - every data file
- [../reference/config-and-env.md](../reference/config-and-env.md) - all env vars
- [../runbooks/data-pipeline.md](../runbooks/data-pipeline.md) - rebuilding DB, priors, usage
