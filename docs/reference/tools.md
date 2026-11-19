# tools/ index

One-line index of every file in `tools/` (32 scripts) with status, plus the data-flow map and
cross-cutting caveats. Details (arguments, inputs, outputs) live in `tools-data.md` (scrape, pool,
priors, DB, training data) and `tools-ops.md` (evaluation, diagnostics, GA ops, one-offs, legacy).
Load this file first to find the right script.

Last verified against code: 2026-11-18

## Status key

- LIVE: part of a current workflow; safe to run as documented.
- ONE-OFF: ran for a specific migration/experiment; re-running changes shared state or is pointless.
- STALE: still runs but its assumptions are outdated, or it is currently broken.
- LEGACY: do not use.
All commands run from the repo root with the venv active (`source .venv/bin/activate`, or
`source ~/venv-pokemorgad/bin/activate` on the original workstation). There is no top-level helper
script any more (`apply_stratify.py` and `tools/pilot_probe.py` were deleted 2026-10-16).

## Index

| file | lines | status | purpose | details |
|---|---|---|---|---|
| batch_parse.py | 73 | LEGACY | old replay -> JSONL parser without `side_won`/`target_*`; degrades BC | tools-data.md |
| bc_diagnostic.py | 152 | STALE (BC broken) | BC vs shadow heuristic decision agreement, `/tmp/bc_diag.jsonl` | tools-ops.md |
| blend_priors.py | 201 | LIVE | blend corpus priors with metavgc -> 4 `species_*` prior files | tools-data.md |
| build_archetypes.py | 126 | LIVE | real-set archetypes -> `data/species_archetypes.json` | tools-data.md |
| build_ev_priors.py | 186 | LIVE | VGCPastes corpus -> `species_{build,ability}_priors.corpus.json` | tools-data.md |
| build_mega_rates.py | 114 | LIVE | fit foe Mega timing from replays -> `data/mega_rates.json` | tools-data.md |
| build_meta_weights.py | 35 | LIVE | ladder species usage -> `data/species_ladder_usage.json` (GA fitness weights) | tools-data.md |
| build_move_priors.py | 104 | ONE-OFF (never applied) | tournament move priors; would OVERWRITE `species_move_priors.json` | tools-data.md |
| build_opp_actions.py | 237 | LIVE | fit foe Protect/Fake Out/Trick Room rates -> `data/opp_actions.json` | tools-data.md |
| build_real_ev_holdout.py | 217 | ONE-OFF (done 2026-10-15) | built the 100 `real_ev_*` holdout; rewrites the split | tools-data.md |
| build_regmc_db.js | 244 | LIVE (rare) | Showdown dex -> `data/regmc_db.json` (Node) | tools-data.md |
| build_species_priors.py | 62 | LIVE (BC) | training rows -> `species_move_priors.json` (ladder, top 30) | tools-data.md |
| build_training_data.py | 135 | LIVE | replays -> `data/training_data.jsonl` (BC training set) | tools-data.md |
| debug_taunt.py | 32 | ONE-OFF | prints `support_value` effect parsing for Taunt | tools-ops.md |
| encode_snapshot.py | 126 | LIVE | bit-identity gate for `src/state_encoder.py` refactors | tools-ops.md |
| extend_train_pool.py | 69 | LIVE | append `<prefix>_*.txt` to `pool_split.json["train"]` | tools-data.md |
| extract_champions.py | 72 | LIVE | rebuild champion files from parallel-run checkpoints (same rule as the GA, plus `_val`) | tools-ops.md |
| generate_heuristic_dataset.py | 334 | STALE | record heuristic decisions as BC rows (0-row bug fixed 2026-11-18, not re-run) | tools-data.md |
| log_milestone.py | 47 | LIVE | append to `docs/history/milestones.md` AND git commit | tools-ops.md |
| normalize_tournament.py | 164 | LIVE | fix species names/items in scraped `<prefix>_*.txt` | tools-data.md |
| paired_eval.py | 301 | LIVE | paired off/on pilot comparison, McNemar | tools-ops.md, subsystems/eval.md |
| paired_run.sh | 62 | LIVE | 3-shard paired run with Showdown restarts | tools-ops.md, subsystems/eval.md |
| preflight.py | 129 | LIVE | pre-launch checks (GPU check informational), optional `--launch` | runbooks/health-check.md |
| regenerate_split.py | 66 | LEGACY / DANGEROUS | reshuffles ALL regional teams into a new split | tools-data.md |
| replay_tracker.py | 625 | LIVE (library) | Showdown log -> per-turn decision rows (`Tracker`) | tools-data.md |
| scrape_metavgc.py | 97 | LIVE | metavgc.com usage tables -> `data/scraped/metavgc/` | tools-data.md |
| scrape_replays.py | 159 | LIVE | Showdown replay search -> `data/showdown_replays/` | tools-data.md |
| scrape_tournament.py | 131 | LIVE (per event) | Limitless team lists -> `data/regional_teams/<name>_NN.txt` | tools-data.md |
| scrape_vgcpastes.py | 287 | LIVE | VGCPastes sheet + pokepastes -> `data/scraped/vgcpastes/` | tools-data.md |
| swap_pool.py | 189 | ONE-OFF (done 2026-10-15) | replace train pool with validated VGCPastes teams | tools-data.md |
| test_pilots.py | 131 | ONE-OFF (2026-10-15) | SmartPlayer vs vanilla heuristic, same team, port 8001 | tools-ops.md |
| verify.sh | 37 | LIVE (the gate) | ruff + imports + 32 test files (stops at first failure) + audit, ends `ALL PASS` | runbooks/health-check.md |
| watch_islands.py | 48 | LIVE | per-island stall watchdog used by `run/ga_parallel.sh` | tools-ops.md |

## Data-flow map

```
Showdown ladder replays (replay.pokemonshowdown.com)
  scrape_replays.py -> data/showdown_replays/*.json (+ .meta.json), showdown_replays_meta/index.json
    build_training_data.py (uses replay_tracker.py) -> data/training_data.jsonl -> src/bc_train.py
      build_species_priors.py -> data/species_move_priors.json (BC mask + GA move sampling)
    build_meta_weights.py -> data/species_ladder_usage.json (GA fitness weights)
    build_mega_rates.py   -> data/mega_rates.json      (pilot: foe Mega timing)
    build_opp_actions.py  -> data/opp_actions.json     (pilot + ladder opponent: Protect/Fake Out/TR)
generate_heuristic_dataset.py (live Showdown) -> data/training_data_heuristic*.jsonl -> src/bc_train.py

VGCPastes Google sheet -> scrape_vgcpastes.py -> data/scraped/vgcpastes/{raw,teams}
  swap_pool.py (train pool) / build_real_ev_holdout.py (holdout) -> data/regional_teams/, pool_split.json
  build_ev_priors.py -> species_{build,ability}_priors.corpus.json --+
metavgc.com -> scrape_metavgc.py -> data/scraped/metavgc/species.json --+-> blend_priors.py
     -> species_build_priors.json, species_ability_priors.json (src/opp_model.py),
        species_item_priors.json, species_move_usage.json (no consumer yet)
  build_archetypes.py (regional_teams + vgcpastes teams) -> species_archetypes.json (src/archetypes.py)
Limitless tournament -> scrape_tournament.py -> normalize_tournament.py -> extend_train_pool.py

Showdown dex (~/pokemon-showdown/dist) -> build_regmc_db.js -> data/regmc_db.json (everything)
```

## Cross-cutting caveats

- Hard-coded `Path.home() / "pokeMorgrad"` (ignores `POKEMORGRAD_ROOT`; breaks if the repo lives
  elsewhere): `build_ev_priors`, `build_move_priors`, `build_real_ev_holdout`, `extend_train_pool`,
  `extract_champions`, `log_milestone`, `normalize_tournament`, `regenerate_split`,
  `scrape_tournament`, `swap_pool`, `test_pilots`. The others resolve from `__file__` or `src.paths`.
- No `sys.path` bootstrap: `bc_diagnostic.py` (run `PYTHONPATH=. python tools/bc_diagnostic.py`),
  `debug_taunt.py` (inserts `.`, so run from the repo root).
- Showdown port: most battle tools use `SHOWDOWN_PORT` via `src/player_factory.py` (parsed by
  `src/paths.py::showdown_port`);
  `bc_diagnostic.py` and `generate_heuristic_dataset.py` use poke_env's default (localhost:8000);
  `test_pilots.py` is fixed to 8001.
- Optional deps: `bs4` (scrape_tournament) and `openpyxl` (scrape_vgcpastes) come from
  `pip install -e ".[scrape]"`.
- `data/scraped/`, replays, training JSONL, paired logs, `output/models/` and
  `output/checkpoints/` are gitignored and absent from a fresh clone; tools that need them fail
  with FileNotFoundError (see `docs/reference/data-files.md`).
- Two writers of `data/species_move_priors.json`: `build_species_priors.py` (ladder, live file)
  and `build_move_priors.py` (tournament, never applied). Whichever runs last wins, and the file
  drives both the BC move mask and GA move sampling.

## Related docs

- [tools-data.md](tools-data.md), [tools-ops.md](tools-ops.md)
- [Data files](data-files.md), [data pipeline runbook](../runbooks/data-pipeline.md)
- [Evaluation subsystem](../subsystems/eval.md), [BC subsystem](../subsystems/bc.md)
- [Health check](../runbooks/health-check.md), [run scripts](run-scripts.md)
