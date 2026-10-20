# tools/ reference

Every script in `tools/` plus top-level `apply_stratify.py`. All Python is run from the repo root inside the venv (`source ~/venv-pokemorgad/bin/activate`; see `config-and-env.md`). Line citations are to the files as of 2026-10-16.

Contents
- [Pipeline map](#pipeline-map)
- [1. Scrape](#1-scrape)
- [2. Normalize / pool management](#2-normalize--pool-management)
- [3. Build priors and DB](#3-build-priors-and-db)
- [4. Training data](#4-training-data)
- [5. GA ops and diagnostics](#5-ga-ops-and-diagnostics)
- [6. Legacy, backups, one-offs](#6-legacy-backups-one-offs)
- [Cross-cutting caveats](#cross-cutting-caveats)

## Pipeline map

There are two scrape sources and they feed different artifacts.

```
Showdown ladder replays                      VGCPastes sheet / Limitless tournaments
  scrape_replays.py                            scrape_vgcpastes.py   scrape_tournament.py
    -> data/showdown_replays/*.json              -> data/scraped/vgcpastes/teams/*.txt -> data/regional_teams/<prefix>_NN.txt
  build_training_data.py (+replay_tracker.py)  swap_pool.py / build_real_ev_holdout.py   normalize_tournament.py
    -> data/training_data.jsonl                  -> regional_teams/vgc_*.txt, real_ev_*.txt, pool_split.json
  build_species_priors.py                      extend_train_pool.py -> pool_split.json["train"] (append only)
    -> species_move_priors.json (ladder)       build_ev_priors.py   -> species_build_priors.json, species_ability_priors.json
  generate_heuristic_dataset.py                build_move_priors.py -> species_move_priors.json (tournament; PENDING)
    -> training_data_heuristic*.jsonl
  src/bc_train.py (not in tools/) -> output/models/*.pt
```
build_regmc_db.js (Showdown dex -> `data/regmc_db.json`) is independent of both. Pilot/GA ops scripts (section 5) sit outside the data pipeline.

Pipeline status key: PIPE = normal pipeline step; OPS = operational helper; ONE-OFF = ran once / situational; LEGACY = do not use.

## 1. Scrape

| Script | Status | Invocation | Reads | Writes |
|---|---|---|---|---|
| `scrape_replays.py` | PIPE | `python tools/scrape_replays.py [RATING_FLOOR=1600] [MAX_PAGES=200]` (positional, `sys.argv`, lines 22-23) | Showdown public replay search API (format `gen9championsvgc2026regmc`); resumes from existing index and on-disk replays | `data/showdown_replays_meta/index.json`, `data/showdown_replays/<id>.json` (+ `<id>.meta.json`). Tunables: SLEEP 0.25s, PAGE_SIZE 51, UNRATED_CAP 500 (lines 26-29) |
| `scrape_vgcpastes.py` | PIPE | `python3 tools/scrape_vgcpastes.py {fetch-csv\|report\|filter-balanced\|fetch-teams}` (lines 3-6) | Google Sheet id `1axlwmz...`, tab "Champions M-C", downloaded as XLSX and read with openpyxl for hyperlink targets | `data/scraped/vgcpastes/raw/` (CSV/XLSX; m-c.csv), `data/scraped/vgcpastes/teams/*.txt` (gitignored; `filter-balanced --all-tournaments` keeps every EVs=Yes team, 558). `BALANCED_TOURNAMENTS` whitelist at line 29 |
| `scrape_tournament.py` | PIPE (per tournament) | `python3 tools/scrape_tournament.py <limitless_tournament_id> <shortname>` e.g. `445 louisville` | `https://limitlessvgc.com/tournaments/<id>/teams` (needs `bs4`, not in pyproject) | `data/regional_teams/<shortname>_NN.txt`. Does NOT touch pool_split.json (line 7-9) |

## 2. Normalize / pool management

Pool files live in `data/regional_teams/`; the split is `data/pool_split.json` (`{"train": [...], "holdout": [...]}`). See `data-files.md`.

| Script | Status | Invocation | Reads | Writes |
|---|---|---|---|---|
| `normalize_tournament.py` | PIPE | `python3 tools/normalize_tournament.py <prefix>` (e.g. `louisville`) | `data/regional_teams/<prefix>_*.txt` | Rewrites those files in place (species-name fixes like "Female Indeedee" -> "Indeedee-F", strips "Held Item:" artifacts); unfixable files moved to `data/regional_teams/_rejected/`. Idempotent |
| `extend_train_pool.py` | PIPE | `python3 tools/extend_train_pool.py <prefix>` | `regional_teams/<prefix>_*.txt`, `pool_split.json`, `pool_split_golden.json` | Appends filenames to `pool_split.json["train"]`; refuses if any are in holdout; warns (interactive y/N prompt) if holdout differs from golden. Never edits holdout (lines 7-13, 49-55) |
| `swap_pool.py` | ONE-OFF (done 2026-10-15) | `python3 tools/swap_pool.py --dry-run` or `--apply` | `data/scraped/vgcpastes/teams/*.txt`; validates each via `node pokemon-showdown validate-team` in `~/pokemon-showdown` (hard-coded, line 33); dedups by (species,item) signature vs new, holdout, train | `--apply`: moves old train files to `regional_teams/_archive_YYYY-MM-DD/`, copies new teams as `vgc_<id>.txt`, backs up split to `pool_split.json.bak`, rewrites train (holdout unchanged) |
| `build_real_ev_holdout.py` | ONE-OFF (done 2026-10-15) | `python3 tools/build_real_ev_holdout.py --dry-run` or `--apply` | `data/scraped/vgcpastes/teams/*.txt`; rejects overlaps with `vgc_*.txt` train and the old holdout; seed 20261015 (line 35), HOLDOUT_SIZE 100 | `regional_teams/real_ev_NN.txt`; backs up split to `pool_split.mixed_holdout.bak`; new holdout = the 100 real-EV teams, train unchanged. Has a duplicated provenance/meta block (apply_stratify.py was patched into it) |
| `regenerate_split.py` | LEGACY / DANGEROUS | `python3 tools/regenerate_split.py [seed=20261015]` | Globs ALL `data/regional_teams/*.txt` (line 23) | Overwrites `pool_split.json` with a fresh shuffled 100-holdout split. Today that would mix vgc_/real_ev_/tournament files and destroy the frozen holdout. Do not run |

## 3. Build priors and DB

| Script | Status | Invocation | Reads | Writes |
|---|---|---|---|---|
| `build_regmc_db.js` | PIPE (rare) | `node tools/build_regmc_db.js [format=gen9championsvgc2026regmc] [outPath=data/regmc_db.json]` (lines 8-19) | Showdown `dist/sim/dex` under `$SHOWDOWN_DIR` (default `~/pokemon-showdown`) | `data/regmc_db.json` (species, moves, items, abilities, rules) |
| `build_ev_priors.py` | PIPE | `python3 tools/build_ev_priors.py` (no args) | `data/scraped/vgcpastes/teams/*.txt`, `src.regmc_db` | `data/species_build_priors.corpus.json` (keys "Species @ Item" and "Species"; top 25 EV/nature spreads; item-key needs >=3 teams, species-key >=2) and `data/species_ability_priors.json` (top 5 abilities). Constants lines 32-35 |
| `scrape_metavgc.py` | PIPE | `python tools/scrape_metavgc.py {fetch\|parse}` | metavgc.com `/pokemon/<slug>` (slugs from `regmc_db`, 1.5 s apart, raw cached) | `data/scraped/metavgc/raw/*.html`, `species.json` (moves, builds, abilities, items with %) |
| `build_archetypes.py` | PIPE | `python tools/build_archetypes.py [--dry-run]` | `data/regional_teams/*.txt` + `data/scraped/vgcpastes/teams/*.txt` (dedup by content) | `data/species_archetypes.json` (item+nature set groups; see STATE 5.24) |
| `build_mega_rates.py` | PIPE | `python tools/build_mega_rates.py [--dry-run]` | `data/showdown_replays/*.json` (replays through `BattleMemory`) | `data/mega_rates.json` (foe Mega timing; prints holdout log-loss; STATE 5.26) |
| `build_opp_actions.py` | PIPE | `python tools/build_opp_actions.py [--dry-run] [--cache]` | `data/showdown_replays/*.json` (through `BattleMemory`, `opp_actions.foe_ctx`) | `data/opp_actions.json` (foe Protect / Fake Out / Trick Room odds; prints holdout log-loss; STATE turn_sim v3) |
| `build_meta_weights.py` | OPS | `python tools/build_meta_weights.py [--replays data/showdown_replays]` | `data/showdown_replays/*.json` | Writes `data/species_ladder_usage.json` (species -> share of ladder teams); prints top species and weight spread of the train / holdout pools. Re-run when new replays arrive |
| `paired_run.sh` | EVAL | `bash tools/paired_run.sh ladder 5500` (nohup it) | 3 Showdown servers | runs 3 `paired_eval.py` shards; every `CHUNK` (1000) matchups restarts that shard's Showdown server + process, kills a stalled shard (`STALL_S` 300 s), restarts a crashed one; resumes from `data/paired_eval/*.jsonl`; progress = `paired_eval.py status --opp ladder` |
| `paired_eval.py` | EVAL | `SHOWDOWN_PORT=8000 python tools/paired_eval.py run --shard 0 --shards 3 --minutes 60`; `python tools/paired_eval.py report /tmp/paired_eval/*.jsonl`; `--opp ladder` plays the Protect/Fake-Out-aware opponent; `--mode support --support all` compares the support layer off/on (turn_sim on in both), `--team a.txt,b.txt` replaces our side (e.g. `data/paired_eval/teams/umb_*.txt`), `--tag` names the logs; `paired_run.sh` takes env `TAG MODE SUPPORT TEAMS` | held-out team pool (seeded matchups) | JSONL per shard; report = win rate per arm (`use_turn_sim` off / on), paired diff + CI, McNemar |
| `blend_priors.py` | PIPE | `python tools/blend_priors.py [--dry-run]` | `*.corpus.json` priors + `scraped/metavgc/species.json` | `species_{build,ability,item}_priors.json`, `species_move_usage.json` (see STATE 5.23) |
| `build_move_priors.py` | PIPE, PENDING | `python3 tools/build_move_priors.py` (no args) | `data/scraped/vgcpastes/teams/*.txt` | Overwrites `data/species_move_priors.json` with tournament-sourced top-20 moves (MAX_MOVES line 23); first copies the old file to `species_move_priors.ladder.bak.json` if absent. On disk today the live file is still byte-identical to the ladder backup (md5 match), so this has not been applied |
| `build_species_priors.py` | PIPE | `python3 tools/build_species_priors.py` | `data/training_data.jsonl` | `data/species_move_priors.json` (ladder-derived, TOP_N_MOVES=30, line 25). Writes the SAME file as `build_move_priors.py`; whichever runs last wins. Consumed by BC mask (`src/bc_train.py:28`, `src/bc_player.py:34`) |

## 4. Training data

| Script | Status | Invocation | Reads | Writes |
|---|---|---|---|---|
| `build_training_data.py` | PIPE (the live driver) | `python tools/build_training_data.py` (no args) | `data/showdown_replays/*.json`, `replay_tracker.Tracker` | `data/training_data.jsonl`; each row tagged `side_won`, `target_a`, `target_b` (docstring lines 1-12). Paths derived from `__file__`, not `src.paths` |
| `replay_tracker.py` | PIPE (library, 626 lines) | imported by `build_training_data.py`, `batch_parse.py` | n/a | Parses a Showdown log into per-turn decision points: `{replay_id, rating, turn, side, state{my_active,my_bench,opp_active,opp_seen,field}, legal_actions{slot_a,slot_b}, chosen{slot_a,slot_b}}` (docstring lines 1-30) |
| `generate_heuristic_dataset.py` | PIPE (BC-imitation variant) | `python tools/generate_heuristic_dataset.py --battles N --out data/training_data_heuristic.jsonl` | Needs a live Showdown server (port via `src.battle`/`SHOWDOWN_PORT`); random genome vs random regional team; `StateEncoder` | JSONL in the same row shape as `build_training_data.py`; records SimpleHeuristicsPlayer choices. TIMEOUT 30s. Flags beyond `--battles/--out` not enumerated here (unclear) |
| `encode_snapshot.py` | OPS (refactor gate) | `python tools/encode_snapshot.py capture` then `... check` (exit 0 identical, 1 drift) | `data/training_data.jsonl` first 200 rows + synthetic states; reference at `$ENC_SNAPSHOT_REF` (default `/tmp/enc_snapshot_ref.pt`, line 30) | Reference tensor file on capture. No `--out` flag (OPERATIONS.md says there is one: stale) |

## 5. GA ops and diagnostics

| Script | Status | Invocation | Reads | Writes / effect |
|---|---|---|---|---|
| `preflight.py` | OPS | `python3 tools/preflight.py [--launch]` | Showdown :8000 only, data files (regmc_db, meta_items, species_move_priors, ...), GPU, git state | Prints OK/FAIL per check (10 checks in code, not ~16 as OPERATIONS.md says). `--launch` starts the serial overnight run via `GA_CONCURRENCY` (lines 104-118). Does not check ports 8001/8002 or the new priors files |
| `watch_islands.py` | OPS (used by ga_parallel.sh) | `python3 tools/watch_islands.py <run_id> <island> <pid> [stall_s=300]` | mtime of `/tmp/ga_<run_id>_<island>.log` | SIGKILLs the island PID if the log is stale > stall seconds; polls every 30s. ga_parallel.sh then respawns from the last checkpoint |
| `extract_champions.py` | OPS | `python3 tools/extract_champions.py <run_id>` e.g. `p3` | `output/checkpoints/v6/<run_id>_{A,B,C}/gen_*.json` (latest) | Writes champion files to `output/champions/` for islands A/B/C. Only works for the parallel layout (`<run_id>_<X>` dirs) |
| `log_milestone.py` | OPS | `python3 tools/log_milestone.py "Title" "One-line summary"` | `git log -1 --oneline`, `docs/STATE_history.md` | Appends a dated entry to `docs/STATE_history.md` AND auto-runs `git add` + `git commit` (lines 38-41). OPERATIONS.md does not mention the auto-commit |
| `verify.sh` | OPS | `bash tools/verify.sh` | repo | `ruff check src run tools`; import smoke tests; prints pool sizes; runs `python -m src.audit_before_launch`; ends "ALL PASS". `cd ~/pokeMorgrad`, activates `~/venv-pokemorgad` |
| `pilot_probe.py` | ONE-OFF (untracked in git) | `SHOWDOWN_PORT=8001 python3 tools/pilot_probe.py [n_battles=200] [out_path=output/replays/pilot_probe.jsonl]` | `heldout_pool()`, `data/baseline_team.txt` (relative path, must run from repo root) | JSONL of per-turn snapshots (turn, active mons, hp, field, moves, chosen order) for heuristic pilot vs holdout; account names carry the port to allow 3 parallel instances. 60s battle timeout |
| `test_pilots.py` | ONE-OFF | `python3 tools/test_pilots.py [n_teams] [battles_per_team] [concurrency]` | `heldout_pool()`; `src.smart_player.SmartPlayer` | Prints SmartPlayer vs SimpleHeuristicsPlayer same-team win rate. Port hard-coded to 8001 (line 26) |
| `bc_diagnostic.py` | ONE-OFF | `python3 bc_diagnostic.py [n_battles]` (run as module/with repo on path; imports `src.*`) | BC model, `data/baseline_team.txt`, `regional_pool()` | `/tmp/bc_diag.jsonl`; prints BC vs heuristic agreement by turn and HP bucket. Read-only |

## 6. Legacy, backups, one-offs

| File | Status | Notes |
|---|---|---|
| `batch_parse.py` | LEGACY | Header (lines 1-8) says do not use: predates `side_won`/`target_*` schema and degrades `bc_train`. Replaced by `build_training_data.py`. Still in tools/ (docs say "archived") |
| `pilot_probe.py.bak` | backup | Older copy of `pilot_probe.py` (129 vs 155 lines). Backup only |
| `scrape_louisville.py.bak` | backup | Older Louisville-specific scraper; superseded by `scrape_tournament.py`. Backup only |
| `../apply_stratify.py` (repo root, untracked) | ONE-OFF, already applied | A bash heredoc (`cd ~/pokeMorgrad && python3 - <<'PYEOF' ...`) saved with a `.py` extension; it is not valid Python. It patches `tools/build_real_ev_holdout.py` to a provenance-stratified pick (reads `data/scraped/vgcpastes/raw/m-c.csv`). Safe to delete |

## Cross-cutting caveats

- Many tools hard-code `Path.home() / "pokeMorgrad"` instead of `src.paths` (`swap_pool`, `build_*_priors`, `extend_train_pool`, `extract_champions`, `normalize_tournament`, `scrape_tournament`, `test_pilots`, `log_milestone`, `regenerate_split`). Moving the repo again or setting `POKEMORGRAD_ROOT` does not redirect them; `sed` the string if the directory is renamed.
- `scrape_vgcpastes.py`, `build_ev_priors.py` and `build_archetypes.py` use `data/scraped/vgcpastes/`. `build_move_priors.py`, `swap_pool.py` and `build_real_ev_holdout.py` also read `data/scraped/vgcpastes/{teams,raw}` now (no /tmp dependency left).
- `bs4` (scrape_tournament) and `openpyxl` (scrape_vgcpastes) are in the optional extra: `pip install -e ".[scrape]"`.
- `species_build_priors.json` is documented as the sampler for `ga_core._random_mon` (build_ev_priors.py lines 11-13) but `src/ga_core.py` never reads it; only `src/opp_model.py:63` does (battle-time opponent build guess for DoublesPilot).
