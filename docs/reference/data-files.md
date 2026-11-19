# data/, output/ and archive/ files

Every file under `data/` and `output/`: schema with a small real example, producer, consumers,
whether git tracks it, and size. Plus a short note on `archive/`. Read before regenerating,
deleting or hand-editing a data file, or when a script fails with FileNotFoundError on a fresh
clone. Producers are described in `tools-data.md`; workflows in `docs/runbooks/data-pipeline.md`.

Last verified against code: 2026-11-18 (sizes measured in this checkout; "absent" = gitignored
and not present in a fresh clone; counts for absent files are from old docs, dated)

## Tracking rules (.gitignore)

`data/*` is ignored except a whitelist: `baseline_team.txt, meta_items.json, pool_split.json,
pool_split_golden.json, pool_split.json.bak, species_move_priors.json, species_build_priors.json,
species_ability_priors.json, species_{build,ability}_priors.corpus.json, species_item_priors.json,
species_move_usage.json, species_archetypes.json, mega_rates.json, species_ladder_usage.json,
regmc_db.json, showdown_replays_meta/, regional_teams/`. Force-added (tracked although not
whitelisted): `data/opp_actions.json`, `data/paired_eval/teams/*.txt`. Also ignored everywhere:
`output/`, `*.jsonl`, `*.pt`, `*.bak` (except `pool_split.json.bak`). Some `output/champions/` and
`output/archive/` files are force-added. A new non-whitelisted data file needs `git add -f`.

## Summary table (data/)

| path | size | tracked | producer | consumers |
|---|---|---|---|---|
| regmc_db.json | 998 KB | yes | tools/build_regmc_db.js | src/regmc_db.py, damage.py, state_encoder.py, everything |
| baseline_team.txt | 894 B | yes | hand-written | eval.py default, audit, regmc_db, showdown_validator, run/ga_*, bc_diagnostic |
| pool_split.json | 5.4 KB | yes | swap_pool, build_real_ev_holdout, extend_train_pool | src/ga/pools.py (`regional_pool`, `heldout_pool`) |
| pool_split_golden.json | 13 KB | yes | frozen copy of the pre-2026-10-15 split | extend_train_pool.py (warning only) |
| pool_split.json.bak | 13 KB | yes | swap_pool --apply (identical to golden) | none |
| regional_teams/ | 3.1 MB | yes | scrapers + pool tools | src/ga/pools.py, build_archetypes |
| species_move_priors.json | 104 KB | yes | build_species_priors.py (ladder) | bc_train, bc_player (mask), ga/genome.py (move sampling) |
| meta_items.json | 18 KB | yes | unknown (no script in repo) | ga/genome.py `meta_items_for` (item draws) |
| species_build_priors.json | 508 KB | yes | blend_priors.py | src/opp_model.py |
| species_ability_priors.json | 51 KB | yes | blend_priors.py | src/opp_model.py |
| species_build_priors.corpus.json | 148 KB | yes | build_ev_priors.py | blend_priors.py |
| species_ability_priors.corpus.json | 17 KB | yes | build_ev_priors.py | blend_priors.py |
| species_item_priors.json | 140 KB | yes | blend_priors.py | none yet |
| species_move_usage.json | 186 KB | yes | blend_priors.py | none yet |
| species_archetypes.json | 364 KB | yes | build_archetypes.py | src/archetypes.py (-> opp_model) |
| species_ladder_usage.json | 7.5 KB | yes | build_meta_weights.py | src/meta_weights.py (GA fitness, eval) |
| mega_rates.json | 1.5 KB | yes | build_mega_rates.py | src/mega_model.py |
| opp_actions.json | 14.5 KB | yes (forced) | build_opp_actions.py | src/opp_actions.py (VGCPilot, LadderOpponent) |
| showdown_replays_meta/index.json | 756 KB | yes | scrape_replays.py | scrape_replays.py (resume) |
| paired_eval/teams/umb_*.txt | 4 x 0.9 KB | yes (forced) | hand-written | paired_eval.py `--team` |
| paired_eval/*.jsonl, .plan, _run*.log | - | absent | paired_eval.py, paired_run.sh | paired_eval.py report/status |
| showdown_replays/ | 60 MB (10,012 files) | absent | scrape_replays.py | build_training_data, build_meta_weights, build_mega_rates, build_opp_actions |
| training_data.jsonl | 159 MB, 72,048 rows | absent | build_training_data.py | bc_train (default BC_DATA), build_species_priors, encode_snapshot |
| training_data_heuristic*.jsonl | 153-176 MB | absent | generate_heuristic_dataset.py | bc_train via BC_DATA |
| scraped/vgcpastes/{raw,teams} | - | absent | scrape_vgcpastes.py | build_ev_priors, build_move_priors, build_archetypes, swap_pool, build_real_ev_holdout |
| scraped/metavgc/ | - | absent | scrape_metavgc.py | blend_priors.py |
| replays/*.jsonl | 43 MB | absent | archive/one_offs scripts | archive only (dead data) |
| species_move_priors.ladder.bak.json | 104 KB | absent | build_move_priors.py backup | none |
| pool_split.mixed_holdout.bak | 5.6 KB | absent | build_real_ev_holdout.py backup | none |

## Static game data

`regmc_db.json`: Showdown dex export. Top-level keys `meta, rules, natures, types, typeChart,
items, moves, abilities, species`. Current: 392 species, 515 moves, 166 items, 316 abilities, 25
natures. `meta = {"format": "gen9championsvgc2026regmc", "formatName": "[Gen 9 Champions] VGC 2026
Reg M-C", "mod": "champions", "built": "2026-10-20T18:52:31.101Z", "showdownPath": ...}`. Format:
doubles, Mega legal, Tera NOT legal, EVs 0-32 per stat (66 total). History: first build
2026-10-11 had 391 species; `Lucario-Mega-Z` added 2026-10-16 (breaks BC checkpoints, see
`docs/subsystems/bc.md`); move effect fields added 2026-10-20. Known gaps (2026-10-15):
`Sinistcha-Masterpiece` has `moves=[]`; Glimmora lacks Adaptability.

## Priors

- `species_move_priors.json` (191 species): `{"Gholdengo": [{"move": "Shadow Ball", "count": 867},
  {"move": "Protect", "count": 640}, ...]}` top 30 per species from ladder replays (training rows).
- `meta_items.json` (94 species): `{"Excadrill": [{"item": "Focus Sash", "count": 21, "pct": 91.3}, ...]}`.
- `species_build_priors.json` (540 keys, 154 of them `"Species @ Item"`):
  `{"Absol @ Absolite Z": [{"evs": {"atk": 32, "hp": 2, "spe": 32}, "nature": "Adamant", "count": 3}, ...]}`;
  counts are blended (corpus + 10 x metavgc share), top 10. Corpus file: 320 keys, integer counts, top 25.
- `species_ability_priors.json` (379 species): `{"Abomasnow": [{"ability": "Snow Warning", "count": 11.0}]}`.
- `species_item_priors.json` (382) and `species_move_usage.json` (345): `{species: [{"item"|"move", "pct"}]}`
  metavgc shares restricted to DB-legal entries; `__other__` holds the residual.
- `species_archetypes.json` (145 species): `{"Abomasnow": {"n": 1, "archetypes": [{"item": "Abomasite",
  "nature": "Quiet", "form": "Abomasnow-Mega", "count": 1, "spreads": [{"evs": {...}, "count": 1}],
  "moves": {"Blizzard": 1, ...}, "abilities": {"Snow Warning": 1}}]}}`.
- `species_ladder_usage.json`: `{"n_sides": 10012, "floor": 0.02, "usage": {species_key: share}}`
  (204 species; a team's weight = mean of its 6 species, unseen = floor).
- `mega_rates.json`: `{"cells": {"k0_lead|1": 0.6482, "k1|1": 0.3631, ...}, "species_rel": {...},
  "hold_floor", "n_rows", "n_stone_revealed"}`.
- `opp_actions.json`: `{"protect"|"fakeout"|"trickroom": {"cells": {"new|lead": 0.0748, ...},
  "parents", "species_rel", "n_rows", "n_pos"}, "targets": {...}}`.
Corpus scope (decision 2026-10-15): priors and archetypes use train, holdout and unsplit teams;
they describe the meta, not a team. The held-out rule governs fitness and final eval only.

## Team pools

`regional_teams/` (Showdown paste format, one team per file; 348 top-level `.txt`):
- `vgc_<TeamID>.txt` x148: current TRAIN pool (VGCPastes, real EVs; swapped in 2026-10-15 as 150,
  2 invalid removed 2026-11-14).
- `real_ev_NNN.txt` x100: current HOLDOUT (VGCPastes real EVs, frozen 2026-10-15).
- `baltimore_* 22, frankfurt_* 34, louisville_* 26, brisbane_* 9, recife_* 9` = exactly the 100
  teams of the OLD holdout (`pool_split_golden.json["holdout"]`, Limitless lists, inferred EVs).
  Not in the current split. Old docs said "add them with extend_train_pool.py": doing so mixes the
  old holdout into training and makes all pre-2026-10-15 holdout numbers incomparable.
- `_archive_2026-10-15/` (445 files): the old train pool moved out by `swap_pool.py`.
- `_rejected/`: created by `normalize_tournament.py`; empty dirs are not in git.

`pool_split.json`: `{"train": ["vgc_MC210.txt", ...148], "holdout": ["real_ev_000.txt", ...100]}`.
Entries are basenames resolved against `data/regional_teams/` (old absolute paths still resolve by
basename). `heldout_pool()` raises RuntimeError if the file is missing, the holdout list is empty, or a
file is in both lists (until 2026-11-18 a missing file silently returned the TRAIN pool). The GA
further cuts train into train + a 30-team validation slice (`VAL_POOL_SIZE=30`, seed 42,
`src/ga/pools.py::_split_train_val`). `pool_split_golden.json` = the 445/100 split from before
2026-10-15; `extend_train_pool.py` compares the current holdout to it and therefore always prompts.

`baseline_team.txt`: the hand-built Umbreon-lead seed team (Umbreon @ Leftovers, Inner Focus, Bold,
Foul Play / Snarl / Yawn / Taunt; Salamence @ Salamencite; ...). Eval baseline and island A seed.

## Replays and training data (all absent from a fresh clone)

- `showdown_replays/<format>-<id>.json`: the replay JSON from replay.pokemonshowdown.com; the
  battle log is in `"log"`. `<id>.meta.json`: `{"rating": 1446, "uploadtime": 1789066747}`.
- `showdown_replays_meta/index.json` (tracked, 5,001 entries):
  `[{"id": "gen9championsvgc2026regmc-2696504499", "rating": 1879, "uploadtime": 1791712263, "players": ["...", "..."]}]`.
- `training_data.jsonl`: one decision (turn x side) per line, schema in `tools-data.md`
  (`replay_tracker`) plus `side_won`, `target_a`, `target_b`. 72,048 rows from 5,001 replays (2026-10-13).
- `training_data_heuristic.jsonl` 60,688 rows (2026-10-13), `_v2` 66,036, `_v2_dedup` 58,293 (counts
  2026-10-16): same schema minus `replay_id`/`rating`/`legal_actions`.
- `paired_eval/<opp>[_<tag>]_shard<i>.jsonl`: one row per matchup (see `docs/subsystems/eval.md`).

## output/ (gitignored; selected files force-added)

| path | contents | producer |
|---|---|---|
| output/models/*.pt | BC checkpoints: `bc_best.pt` (production v5), `bc_heuristic*.pt`, `bc_v4_best.pt`, `bc_v5_*.pt`, `bc_v6a.pt` (Unverified list, from 2026-10-16 docs; absent here) | src/bc_train.py |
| output/checkpoints/v6/<run_id>[_<X>]/gen_NNNN.json | GA state `{"generation", "saved", "islands": [Island.to_dict()]}`; resumed automatically for the same run_id | src/ga/checkpoint.py |
| output/champions/ | `ga_<run>_island_<X>.txt` and `_train.txt`; tracked: `CHAMPION_2026-10-12.txt`, `ga_run1_island_{A,B,C}.txt`, `archive/` | src/ga/checkpoint.py::write_champions, tools/extract_champions.py |
| output/replay_log/<run>_<X>/<X>_genNNNN.jsonl | sampled battle logs when `GA_REPLAY_LOG` is set; one JSON per battle: `run_id, island, gen, genome_index, genome_fitness, opponent_index, outcome, our_species, log` | src/replay_log.py via run/ga_island.py |
| output/archive/2026-10-11-10h-run/ | README, final eval log, run1/run2 champions (tracked) | manual |

Champion semantics: the GA's `write_champions` writes the un-suffixed file from `best_ever`
(train-best; falls back to `best_val_ever`) and `_train` from `best_ever`, so both are normally the
same team. `tools/extract_champions.py` follows the same rule and also writes `_val.txt` from
`best_val_ever` (before 2026-11-18 it wrote the un-suffixed file from `best_val_ever`).
GA and Showdown logs are NOT in output/: `/tmp/ga_<run>_<X>.log`, `/tmp/ga_<run>_<X>_watchdog.log`,
`/tmp/showdown_<port>.log` (lost on WSL restart).

## archive/ (historical, not imported)

4.4 MB, tracked, read-only history; no live module imports it. `old_bot/` (first neural and
rule-based pilots, `train_bc.py`, `vocab.json`, an old `bc_model.pt`), `old_ga/` (v2/v3 GA
checkpoints and histories, `ga_set_v5.py`), `old_ops/` (old watchdog, restart and training
scripts), `one_offs/` (replay download/parse, regional scrapers, `scrape_limitless.py`), `pools/`
(`real_teams_681_limitless/` and opponent analysis), `tools/`. Use it only to recover history.

## Related docs

- [tools.md](tools.md), [tools-data.md](tools-data.md), [tools-ops.md](tools-ops.md)
- [Data pipeline runbook](../runbooks/data-pipeline.md)
- [Foundation (paths, regmc_db, meta weights)](../subsystems/foundation.md)
- [BC subsystem](../subsystems/bc.md), [evaluation subsystem](../subsystems/eval.md)
- [GA](../subsystems/ga.md), [config and env](config-and-env.md)
