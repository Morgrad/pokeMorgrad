# Configuration, environment, and tunables

Scope: `src/`, `run/`, `ops/`, `pyproject.toml`. Line numbers as of 2026-10-16. "Behavior-changing" constants only; pure dimensions/vocab lists (e.g. `state_encoder.py` N_SLOTS, `bc_model.py` EMB_*) are architecture constants tied to the frozen BC checkpoint and are listed at the end.

Contents
- [Python environment and pyproject](#python-environment-and-pyproject)
- [Showdown servers](#showdown-servers)
- [Environment variables](#environment-variables)
- [CLI arguments and defaults](#cli-arguments-and-defaults)
- [GA tunables (src/ga_core.py)](#ga-tunables-srcga_corepy)
- [GA run parameters (run/)](#ga-run-parameters-run)
- [Pilot and evaluation tunables](#pilot-and-evaluation-tunables)
- [BC training constants](#bc-training-constants)
- [Frozen architecture constants](#frozen-architecture-constants)

## Python environment and pyproject

- Venv: `~/venv-pokemorgad` on this host. Activate with `source ~/venv-pokemorgad/bin/activate`. `run/ga_parallel.sh:16` and `tools/verify.sh:4` hard-code this. README setup says `.venv` (stale for this host).
- `pyproject.toml`: project `pokemorgrad` 0.1.0, `requires-python >=3.10`, setuptools build, `packages = ["src"]` only (`run/` and `tools/` are not packaged; run `python -m run.ga_island`, `python -m src.eval` from the repo root). Dependencies: `torch>=2.0`, `numpy`, `poke-env>=0.8`. Optional `dev`: `ruff`, `pytest`. Ruff: line-length 100, target py310, select `E,F,W,I`, ignore `E501,E701,E702`, per-file E402 ignore for `tools/*`, `run/*`, `src/battle.py`. No pytest config section. `bs4` and `openpyxl` (used by tools/scrape_*) are not declared.
- Tests: `tests/test_damage.py`, `tests/test_doubles_eval.py`, `tests/test_speed_model.py`, `tests/test_blend_priors.py`, `tests/test_archetypes.py`, `tests/test_mega_z_lines.py`, `tests/test_battle_memory.py` (plain scripts, pytest also works).
- Showdown/Node: Showdown checkout at `~/pokemon-showdown` (run with `node pokemon-showdown ...`).

## Showdown servers

| Port | Role | Started by |
|---|---|---|
| 8000 | default server; serial GA; island A in the parallel run | `ops/start_server.sh:6`, `run/ga_overnight.sh:25`, `run/ga_parallel.sh:30` |
| 8001 | island B in parallel run; also eval/diagnostics (`tools/test_pilots.py:26` hard-codes it) | `run/ga_parallel.sh` |
| 8002 | island C in parallel run | `run/ga_parallel.sh` |

Start command (all scripts): `cd ~/pokemon-showdown && nohup node pokemon-showdown start <port> --no-security > /tmp/showdown_<port>.log 2>&1 &`. `ops/start_server.sh [port]` (default 8000) kills and restarts only that port's server and logs to `/tmp/showdown_<port>.log`. `ga_parallel.sh:26-40` starts any of 8000-8002 that does not answer `curl localhost:<port>`, waits 8s, aborts if one is down. Port-to-island map is `ga_parallel.sh:95-100` (A=8000, B=8001, C=8002). Other ops: `ops/watch_server.sh` (watches 8000 only).

Each island process runs with `GA_CONCURRENCY=8` and its own `SHOWDOWN_PORT` (`ga_parallel.sh:60`); `tools/watch_islands.py` kills an island whose `/tmp/ga_<run>_<X>.log` is stale for 300s (`ga_parallel.sh:65`) and the loop respawns it from checkpoint with the remaining time budget (lines 52-90). Details of operation: `docs/OPERATIONS.md`.

## Environment variables

| Variable | Default | Read at | Effect |
|---|---|---|---|
| `SHOWDOWN_PORT` | `8000` | `src/battle.py:59`; `src/ga_core.py:1072`; `run/ga_island.py:37`; `tools/pilot_probe.py:23` | Port poke_env players connect to (`ws://localhost:<port>/showdown/websocket`) and the port the GA restarts every `showdown_restart_every` gens (`ga_core.py:1283-1294`). Set per island by ga_parallel.sh. Read at import time, so it must be set before the process starts. `src/eval.py` has no port flag, only this variable |
| `GA_CONCURRENCY` | `3` (src/eval.py:27, ga_core.py:1398, run/ga_run.py:60); `8` in `run/ga_island.py:38`; `8` forced by ga_parallel.sh:60 | same files | Simultaneous battles per server. Serial GA/eval default 3; parallel island default 8. Also the default for `eval --concurrency` |
| `ISLAND_NAME` | `A` | `run/ga_island.py:36` | Island selector, uppercased; must be A, B or C (else exit 1, lines 51-53). Selects constraints, seed paths, RNG seed (below) |
| `GA_TRAIN_SAMPLE` | `250` | `src/ga_core.py:75` | Opponents sampled per generation from the train pool when it is larger. Current train pool is 150, so no sampling occurs |
| `GA_PILOT` | `vgc` | `src/ga_core.py` (`FITNESS_PILOT`) | Our pilot in GA fitness battles (`heuristic`, `vgc`, `doubles`, `bc`). `heuristic` + `GA_OPP=heuristic` = the pre-2026-10-16 environment; scores are not comparable across settings |
| `GA_OPP` | `ladder` | `src/ga_core.py` (`FITNESS_OPP`) | Opponent pilot in GA fitness battles (`ladder` = heuristic + Protect/Fake Out at replay rates, or `heuristic`) |
| `GA_META_WEIGHTS` | `1` | `src/ga_core.py` (`META_WEIGHTS`) | `1` = fitness is the win rate weighted by ladder usage of each opponent team (`data/species_ladder_usage.json`); `0` = plain win rate |
| `GA_GENERATIONS` | `999` | `run/ga_island.py` | Generation cap for one island process (2 for a smoke test) |
| `DOUBLES_KO_BONUS` | `1.0` (falls back to `doubles_eval.KO_BONUS`) | `src/doubles_pilot.py:70-71` | KO term weight in DoublesPilot's pair score. Sweep 0-4 on 2026-10-16 found a plateau from 1.0 up, 0 about 4 points worse (comment `doubles_eval.py:27`). Overridden by the `ko_bonus=` constructor arg |
| `DOUBLES_MIN_GAIN` | `0.01` (falls back to `doubles_eval.MIN_GAIN`) | `src/doubles_pilot.py:72-73` | Minimum improvement over vanilla's pair before DoublesPilot deviates |
| `DOUBLES_TURN_SIM` | `1` | `src/doubles_pilot.py` | on by default (paired +4.5 / +4.7 pts, p<0.001); `0` turns off the `turn_sim` decision; when on the pilot decides with `turn_sim.TurnSim` (attacks + Fake Out / Protect / switch) |
| `DOUBLES_FOE_ACTIONS` | `1` | `src/vgc_pilot.py` | `0` stops `VGCPilot` feeding foe Protect / Fake Out odds (`opp_actions`) to the sim |
| `DOUBLES_PASSIVE_COST` | `0.15` | `src/turn_sim.py` | tempo cost per switch / Protect in the sim (untuned) |
| `POKEMORGRAD_ROOT` | unset (repo root = parent of `src/`) | `src/paths.py:15` | Override repo root; must contain `data/` or raises. `data_path`/`output_path`/`src_path` derive from it. Tools that hard-code `~/pokeMorgrad` ignore it |
| `SHOWDOWN_DIR` | `~/pokemon-showdown` | `src/paths.py:43` (`showdown_dir()`); `src/showdown_validate.js:5`; `tools/build_regmc_db.js:13`; `ops/start_server.sh:2`; `run/ga_overnight.sh:5` | Showdown checkout. Also honored by `src/ga_core.py` (restarts), `run/ga_parallel.sh`, `tools/swap_pool.py`, `tools/build_real_ev_holdout.py` |
| `BC_DATA` | `data/training_data.jsonl` | `src/bc_train.py:27` | Training JSONL (use heuristic variants for imitation runs) |
| `BC_OUT` | `bc_best.pt` | `src/bc_train.py:30` | Output filename under `output/models/` |
| `BC_MODEL` | `v2` | `src/bc_train.py:31` | BC architecture variant selector |
| `BC_BATCH` | `256` | `src/bc_train.py:34` | Batch size |
| `BC_EPOCHS` | `30` | `src/bc_train.py:35` | Max epochs |
| `BC_PATIENCE` | `3` | `src/bc_train.py:41` | Early-stop patience |
| `BC_PILOT_PATH` | `output/models/bc_best.pt` | `src/bc_player.py:33` | Weights used by `--pilot bc` |
| `ENC_SNAPSHOT_REF` | `/tmp/enc_snapshot_ref.pt` | `tools/encode_snapshot.py:30` | Encoder-equivalence reference file |
| `PYTHONUNBUFFERED` | set to `1` | `run/ga_parallel.sh:17` | Unbuffered island logs |

## CLI arguments and defaults

Only `src/eval.py` uses argparse (lines 150-159). `run/` scripts use positional `sys.argv`.

| Entry | Argument | Default | Meaning |
|---|---|---|---|
| `python -m src.eval` | `teams...` (positional) | `data/baseline_team.txt` | Team files to score |
| | `--opponents {heldout,all}` | `heldout` | holdout pool (100) vs all train teams (help text says "300"/"100", stale: pools are 150/100) |
| | `--seeds N...` | `100 200 300` | RNG seeds; each seed replays every opponent once |
| | `--pilot {heuristic,bc,doubles,both}` | `both` (= heuristic + bc) | Pilot for OUR side; opponent is always `SimpleHeuristicsPlayer` (`battle.py:13`). OPERATIONS.md says heuristic default: stale |
| | `--concurrency N` | `$GA_CONCURRENCY` or 3 | Battles per server |
| `python -m run.ga_run [run_id] [hours]` | positional | `run1`, `5.0` | Serial 3-island GA. RNG base seed `{run1:42, run2:137, run3:999}`, else 42 (line 26); runs other than `run1` warm-start from `ga_run1_island_*.txt` champions (lines 29-32) |
| `python -m run.ga_island [run_id] [hours]` | positional + `ISLAND_NAME` | `p1`, `4.0` | One island. Run ID becomes `<run_id>_<name>` |
| `bash run/ga_parallel.sh [hours] [run_id]` | positional | `4.0`, `p1` | Launches 3 islands (ports 8000-8002) with watchdogs (lines 12-13) |
| `bash run/ga_overnight.sh` | none | n/a | Serial run1 then run2 at 2.5h each (lines 52,57), deletes `output/checkpoints/v6/run1` and `run2` first (line 33) |
| `tools/*` | see `tools.md` | | |

## GA tunables (src/ga_core.py)

Defined at `ga_core.py:39-107`; changing them changes GA behavior.

| Name | Default | Effect |
|---|---|---|
| `FORMAT` | `gen9championsvgc2026regmc` | Showdown format string used everywhere |
| `UID_MAX` | `10**9` | Range of random per-battle account ids |
| `EV_BUDGET` / `EV_STAT_CAP` | `66` / `32` | Total EVs per mutated spread and per-stat cap (Champions-style 32-point scale) |
| `MAX_REBUILD_TRIES` | `20` | Attempts to rebuild an illegal genome before dropping it |
| `BATTLE_TIMEOUT` | `20` s | Hung battle becomes `None`, not a loss |
| `MIN_TURNS` | `3` | GA discards battles shorter than this (desync/forfeit) |
| `VAL_POOL_SIZE` / `VAL_SPLIT_SEED` | `30` / `42` | Validation slice carved from train pool (ga_core.py:202,1449) |
| `TRAIN_SAMPLE_SIZE` | `250` (`GA_TRAIN_SAMPLE`) | Per-generation opponent sample |
| `EARLY_STOP_MIN_BATTLES` / `EARLY_STOP_WIN_RATE` | `50` / `0.15` | A genome scoring below 15% after 50 battles skips the remaining battles |
| `CANONICAL_ITEMS` | 8 items (Leftovers, Sitrus Berry, Focus Sash, Life Orb, Choice Scarf, Choice Specs, Assault Vest, Rocky Helmet) | Fallback item set for species without a `meta_items.json` entry |
| `PROTECT_MOVES` / `FAKEOUT_MOVES` | tuples, ga_core.py:100-106 | Team-realism constraint pools (forced Protect and a Fake Out/Follow Me/Rage Powder slot) |
| `CHECKPOINT_DIR` / `CHAMPION_DIR` | `output/checkpoints/v6` / `output/champions` | ga_core.py:1069-1070 |
| `battle.RETRY_STRIDE` | `999_983` | uid offset on a retry (`src/battle.py:68`); `retries=1` default in `run_battle` |

## GA run parameters (run/)

Passed to `run_islands` (`ga_core.py:1393-1406`); the same values appear in `run/ga_run.py:55-67` and `run/ga_island.py:61-78`.

| Parameter | Library default | ga_run.py | ga_island.py | Effect |
|---|---|---|---|---|
| `pop_per_island` | 10 | 10 | 10 | Population per island |
| `generations` | 999 | 999 | 999 | Effectively time-limited |
| `battles_per_genome` | 800 | 800 | 800 | Battles per fitness evaluation |
| `concurrency` | `$GA_CONCURRENCY` or 3 | same | `GA_CONCURRENCY` (8) | |
| `immigration_rate` | 0.20 | 0.20 | 0.20 | Immigrant injection on diversity loss |
| `stagnation_limit` | 5 | 5 | 5 | Gens without best_ever improvement before restart |
| `diversity_floor` | 15 | 15 | 15 | Diversity threshold for immigrants |
| `migration_every` | 5 | 5 | 999 | Ring migration; disabled for single-island processes |
| `showdown_restart_every` | 10 | 10 | 10 | Server bounce interval (gens) |
| `max_hours` | none | argv[2] | argv[2] | Wall-clock cap |

Island specs: `ga_island.py:44-49`: A = lock slot 0 to Umbreon, seeded with `baseline_team.txt`, RNG seed 42; B = lock slot 0 Umbreon, no seed, seed 137; C = unconstrained, no seed, seed 999. `ga_run.py:34-51` has the same three. Its comment says B's other 5 slots are free; code locks Umbreon into slot 0 for both A and B.

## Pilot and evaluation tunables

| Name | Value | Where | Effect |
|---|---|---|---|
| `KO_BONUS` | `1.0` | `src/doubles_eval.py:27` | KO weight in DoublesPilot pair score (env `DOUBLES_KO_BONUS`) |
| `ALLY_WEIGHT` | `1.0` | `doubles_eval.py:28` | Cost of damage to own ally relative to a foe |
| `MIN_GAIN` | `0.01` | `doubles_eval.py:29` | Deviation threshold (env `DOUBLES_MIN_GAIN`) |
| `LOCKED_MOVES`, `UNMODELLED_MOVES` | sets | `src/doubles_pilot.py:33-41` | Moves left to vanilla / excluded from allocation |
| `ITEM_ATK_MULT`, `ABILITY_ATK_MULT`, `ITEM_FINAL_MULT` | band/specs 1.5, huge/pure power 2.0, life orb 1.3 | `doubles_pilot.py:42-44` | Attacker modifiers fed to the damage formula |
| `TOP_K`, `LEVEL` | `3`, `50` | `src/opp_model.py:21-22` | Opponent builds per species in the mixture; battle level |
| `SmartPlayer.KO_BONUS` etc. | 8.0, DAMAGE_WEIGHT 3.0 | `src/smart_player.py:112-113` | Class constants of the older SmartPlayer; only used by `tools/test_pilots.py` (not by the GA/eval pilot switch) |
| `eval.TIMEOUT` | `20` s | `src/eval.py:28` | Battle timeout; eval uses `min_turns=0` so every finished game counts |
| `eval.DEFAULT_SEEDS` | `[100,200,300]` | `src/eval.py:30` | |

## BC training constants

`src/bc_train.py:27-41`: `WEIGHT_DECAY=1e-5`, `VAL_FRAC=0.1`, `SEED=42`, `NUM_WORKERS=0`, `DEVICE = cuda if available else cpu`; env-controlled values in the table above. `src/bc_player.py:35` selects device the same way.

## Frozen architecture constants

Tied to the frozen BC checkpoint; changing them invalidates saved weights: `src/bc_model.py:33-52` (EMB_SPECIES 32, EMB_MOVE/ITEM/ABILITY 16, N_TARGETS 5, FIELD_DIM 17, NEG_INF -1e4); `src/state_encoder.py:44-72` (STATUSES, WEATHERS, TERRAINS, BOOST_STATS, N_SLOTS 12, N_MOVES_PER 4, CONT_DIM 17, HP_MAX_NORM 200.0, BOOST_STAGE_MAX 6.0). `tools/encode_snapshot.py` is the bit-equivalence gate for edits to the encoder.
