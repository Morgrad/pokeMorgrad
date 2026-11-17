# Foundation Modules

This section covers the core infrastructure and data handling components of the pokeMorgrad system.

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
