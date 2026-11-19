# Configuration: ports, paths, venvs, pyproject, tunable constants

Second half of the configuration reference: Showdown ports, repo paths and log locations,
virtualenvs, `pyproject.toml`, and the hard-coded tunable constants outside the GA genome.
Read it when you need a path, a port, or want to know which constant to change for a behavior.
Environment variables are in `config-and-env.md`.

Last verified against code: 2026-11-18

## Ports (local Pokemon Showdown, `node pokemon-showdown start <port> --no-security`)

| Port | Used by | Started by |
|---|---|---|
| 8000 | Default for everything (`SHOWDOWN_PORT` unset): `python -m src.eval`, serial GA (`run/ga_run.py`), island A of the parallel GA, paired-eval shard 0 | `run/ga_parallel.sh`, `run/ga_overnight.sh`, `ops/start_server.sh` (default port), `tools/paired_run.sh`, the GA itself (`src/showdown_server.py::ensure` / `restart`) |
| 8001 | Island B; paired-eval shard 1; `tools/test_pilots.py::PORT` is hard-coded to 8001 | `run/ga_parallel.sh`, `tools/paired_run.sh`, `ops/start_server.sh 8001` |
| 8002 | Island C; paired-eval shard 2 | `run/ga_parallel.sh`, `tools/paired_run.sh`, `ops/start_server.sh 8002` |

`tools/preflight.py` and `ops/watch_server.sh` only look at 8000.
One Showdown server saturates at about 8 concurrent battles (see `GA_CONCURRENCY`).

## Paths

All Python code resolves repo files through `src/paths.py` (`REPO_ROOT`, `data_path`,
`output_path`, `src_path`, `showdown_dir`). Shell scripts use `~/pokeMorgrad` or
`$BASH_SOURCE`-relative roots.

| Path | What | Defined at |
|---|---|---|
| `~/pokeMorgrad` | Repo root (Linux path). Hard-coded by `tools/verify.sh` (`cd ~/pokeMorgrad`); `run/ga_parallel.sh` finds the repo from its own path. | `src/paths.py::REPO_ROOT` (parent of `src/`, or `POKEMORGRAD_ROOT`) |
| `~/pokemon-showdown` | Showdown checkout, a separate git repo. Never edit it. Needs a built `dist/` for the validator and DB builder. | `src/paths.py::showdown_dir` |
| `data/` | Inputs. `data/*` is gitignored with a whitelist of small canonical files (see `.gitignore`). | `data_path()` |
| `data/regmc_db.json` | Canonical format DB, built by `node tools/build_regmc_db.js`. Never hand-edit. | `src/regmc_db.py`, `src/state_encoder.py::REGM_DB` |
| `data/pool_split.json` | Train / holdout team lists (basenames in `data/regional_teams/`). | GA pool loaders |
| `data/showdown_replays/` | Raw replays, gitignored, not on every host (needed by `tests/test_battle_memory.py` real-replay tests). | |
| `output/checkpoints/v6/<run_id>/gen_NNNN.json` | GA checkpoints. Parallel runs use `<run_id>_A` (`_B`, `_C`). Pruned on save: newest kept, older kept only if gen % 5 == 0. | `src/ga/config.py::CHECKPOINT_DIR`, `src/ga/checkpoint.py::save_checkpoint` |
| `output/champions/ga_<run_id>_island_<X>.txt` (+ `_train.txt`) | Champion teams. | `src/ga/config.py::CHAMPION_DIR` |
| `output/models/bc_best.pt` | Promoted BC pilot. | `src/bc_player.py::DEFAULT_MODEL_PATH` |
| `output/replay_log/` | Saved battle logs when `GA_REPLAY_LOG` is set: `<run>_<X>/<X>_genNNNN.jsonl`. | `run/ga_island.py::GA_REPLAY_DIR` (default `src.paths.output_path("replay_log")`) |
| `data/paired_eval/` | Paired-eval shards and logs (gitignored except `data/paired_eval/teams/umb_*.txt`, force-added). | `tools/paired_run.sh` |

Logs (all in `/tmp`, lost on WSL restart):

| Log | Writer |
|---|---|
| `/tmp/ga_<run_id>_<X>.log`, `/tmp/ga_<run_id>_<X>_watchdog.log`, `/tmp/ga_<run_id>_done` | `run/ga_parallel.sh` |
| `/tmp/ga_run1.log`, `/tmp/ga_run2.log`, `/tmp/ga_final_eval.log`, `/tmp/showdown_watchdog.log`, `/tmp/ga_overnight_done_<stamp>` | `run/ga_overnight.sh` |
| `/tmp/ga_overnight_launch.log` | `tools/preflight.py --launch` |
| `/tmp/showdown_<port>.log` | `run/ga_parallel.sh`, `ops/start_server.sh`, `tools/paired_run.sh` |
| `/tmp/showdown_ga.log` | `run/ga_overnight.sh` |
| `/tmp/bc_diag.jsonl` | `tools/bc_diagnostic.py` |

`src/showdown_server.py::restart` discards the server's stdout/stderr (no log file).

## Virtualenvs

| Venv | Where | Notes |
|---|---|---|
| repo `.venv` | `~/pokeMorgrad/.venv` | Preferred by `tools/verify.sh` when `.venv/bin/activate` exists. On the 2026-11-18 checkout: Python 3.13.13, torch 2.15.0+cpu, poke_env 0.17.0, numpy 2.5.5, ruff 0.17.5, pytest 9.2.0; no bs4 / openpyxl. |
| `~/venv-pokemorgad` | home dir | The original GPU workstation's venv (ROCm torch). Fallback in `tools/verify.sh`, `run/ga_parallel.sh`, `run/ga_overnight.sh` and `tools/paired_run.sh` (`PY`): each uses the repo `.venv` first when it exists (since 2026-11-18). |

The project is NOT pip-installed into either venv (`pip show pokemorgrad` finds nothing).
Run modules from the repo root (`python -m src.eval`, `python -m run.ga_island`); test files
and most tools insert the repo root into `sys.path` themselves.

## pyproject.toml

- Project `pokemorgrad` 0.1.0, `requires-python >=3.10`, setuptools build, MIT.
- `packages = ["src", "src.ga"]` only; `run/`, `tools/`, `tests/` are not packaged.
- Dependencies: `torch>=2.0`, `numpy`, `poke-env>=0.8`.
- Extras: `dev = ["ruff", "pytest"]`, `scrape = ["beautifulsoup4", "openpyxl"]`
  (used by `tools/scrape_tournament.py` and `tools/scrape_vgcpastes.py`).
  Install with `pip install -e ".[dev,scrape]"` if you want them. Unverified: whether an
  editable install changes anything for the scripts (none rely on it).
- Ruff: `line-length = 100`, `target-version = "py310"`, `select = ["E","F","W","I"]`,
  `ignore = ["E501","E701","E702"]`; per-file `E402` ignored for `tools/*`, `run/*`,
  `src/battle.py`. Tests use `# noqa: E402` inline. `tools/verify.sh` runs
  `ruff check src run tools tests`. No pytest config section.
- Rule (`.clinerules`): if you `pip install` a package, add it to `pyproject.toml`.

## Tunable constants outside the GA genome

Changing any of these changes behavior (not correctness). Values as of 2026-11-18.

Battle harness and evaluation:

| Constant | Value | Where | Effect |
|---|---|---|---|
| `TIMEOUT` | `20` s | `src/eval.py` | Battle abandoned as hung -> `None` (not a loss). |
| `DEFAULT_SEEDS` | `[100, 200, 300]` | `src/eval.py` | Default `--seeds`; each seed plays every opponent once. Use >= 5 seeds for decisions. |
| `run_battle(timeout=20, retries=1)` | | `src/battle_runner.py::run_battle` | One retry with a new uid on a `None` result. |
| `RETRY_STRIDE` | `999_983` | `src/player_factory.py` (re-exported by `src/battle.py`); copy in `tools/paired_eval.py` | uid offset per retry. |
| turn limit | `battle.turn > 50` | `src/player_factory.py::TimeoutPlayer.choose_move` | Our side (`pilot="vgc"`, prefix `B`) forfeits after turn 50 (counts as a loss). |
| `FORMAT` | `gen9championsvgc2026regmc` | `src/ga/config.py` (re-exported by `src/eval.py`); also `src/showdown_validate.js` | Showdown format everywhere. |
| `UID_MAX` | `10**9` | `src/ga/config.py` | Random per-battle account id range. |
| validator timeout | `60` s | `src/showdown_validator.py::check_teams` | One `node` process per batch. |
| restart wait | `wait_s=60`, `tries=2` | `src/showdown_server.py::restart` | Poll for up to 60 s per attempt, 2 attempts. |

Pilot and turn simulation:

| Constant | Value | Where | Effect |
|---|---|---|---|
| `KO_BONUS` / `ALLY_WEIGHT` / `MIN_GAIN` | `1.0` / `1.0` / `0.01` | `src/doubles_eval.py` | Pair-score weights (env overrides: `DOUBLES_KO_BONUS`, `DOUBLES_MIN_GAIN`). |
| `PASSIVE_COST` | `0.30` (env `DOUBLES_PASSIVE_COST`) | `src/turn_sim_types.py` | Tempo cost of Protect / switch in the sim. |
| `SHORTLIST` / `TOP_K` | `3` / `6` | `src/turn_sim_types.py` | Plain attacks kept per slot; pairs re-scored with the full sim. |
| `MAX_HYPS` / `COARSE_HYPS` | `4` / `2` | `src/turn_sim_types.py` | Opponent build hypotheses per foe (fine / coarse stage). |
| `MIN_SCENARIO_P` / `MIN_OUTCOME_P` / `COARSE_OUTCOME_P` | `1e-4` / `0.005` / `0.05` | `src/turn_sim_types.py` | Probability pruning thresholds. |
| `DEFAULT_SUPPORT` | `"all"` | `src/support_value.py` | Support layer on by default. |
| `DEFAULT_LOOKAHEAD` | `False` | `src/support_value.py` | Lookahead off by default. |
| `TR_TURNS_AFTER_SET` / `HELPING_HAND_MULT` | `4` / `1.5` | `src/support_value.py` | Trick Room turns after setting; Helping Hand multiplier. |
| `LEVEL` / `TOP_K` / `ARCHETYPE_K` | `50` / `3` / `6` | `src/opp_model.py` | Battle level; opponent builds per species (marginal / archetype-conditioned). |
| `MISMATCH` / `MIN_SETS` | `0.02` / `5` | `src/archetypes.py` | Likelihood floor; min sets before falling back to marginal priors. |
| `MAX_P` / `DEFAULT_CELL` | `0.98` / `0.05` | `src/opp_actions.py` | Cap and fallback for foe Protect / Fake Out / Trick Room rates. |
| `CONSUMED_P` / `MAX_P` | `0.02` / `0.98` | `src/mega_model.py` | Foe Mega prediction. |
| `FLOOR` | `0.02` | `src/meta_weights.py` | Minimum usage weight of an opponent team. |
| `SmartPlayer.KO_BONUS` / `DAMAGE_WEIGHT` | `8.0` / `3.0` | `src/smart_player.py` | Older pilot class; only `tools/test_pilots.py` plays it (the GA/eval pilots import only its helper functions `_weather_name`, `_terrain_name`, ...). |

BC training (`src/bc_train.py`): `LR=1e-3`, `WEIGHT_DECAY=1e-5`, `VAL_FRAC=0.1` (battle-level
split), `SEED=42`, `NUM_WORKERS=0`. Frozen architecture constants tied to saved checkpoints:
`src/bc_model.py` (`EMB_SPECIES` 32, `EMB_MOVE`/`EMB_ITEM`/`EMB_ABILITY` 16, `N_TARGETS` 5,
`FIELD_DIM` 17, `NEG_INF` -1e4) and `src/state_encoder.py` (`N_SLOTS` 12, `N_MOVES_PER` 4,
`CONT_DIM` 17, `HP_MAX_NORM` 200.0, `BOOST_STAGE_MAX` 6.0, `STATUSES`/`WEATHERS`/`TERRAINS`/`BOOST_STATS`).
Changing those invalidates `output/models/*.pt`; gate encoder edits with `tools/encode_snapshot.py`.

## GA constants (pointer only; documented in the GA docs)

| Name | Value | Where |
|---|---|---|
| `GAConfig.battle_timeout` / `min_turns` | `20` / `3` | `src/ga/config.py` |
| `GAConfig.early_stop_min_battles` / `early_stop_win_rate` | `50` / `0.15` | `src/ga/config.py` |
| `CHECKPOINT_DIR` / `CHAMPION_DIR` | `output/checkpoints/v6` / `output/champions` | `src/ga/config.py` |
| `EV_BUDGET` / `EV_STAT_CAP` | `66` / `32` | `src/ga/operators.py` |
| `MAX_REBUILD_TRIES` | `20` | `src/ga/legality.py` |
| `VAL_POOL_SIZE` / `VAL_SPLIT_SEED` | `30` / `42` | `src/ga/pools.py` |
| `CANONICAL_ITEMS` / `PROTECT_MOVES`, `FAKEOUT_MOVES` | tuples | `src/ga/genome.py` / `src/ga/legality.py` |
| `run_islands(...)` defaults | pop 10, battles 800, migration 5, restart every 10 | `src/ga/engine.py`; launchers override (`run/ga_island.py` uses 50 battles/genome, `migration_every=999`) |

Details: `docs/subsystems/ga.md`, `docs/subsystems/ga-genome.md`.

## Related docs

- [config-and-env.md](config-and-env.md) - every environment variable
- [../runbooks/environment.md](../runbooks/environment.md) - host, venvs, ROCm
- [../runbooks/showdown.md](../runbooks/showdown.md) - servers and ports
- [../subsystems/ga.md](../subsystems/ga.md), [../subsystems/ga-genome.md](../subsystems/ga-genome.md) - GA constants
- [../subsystems/turn-sim.md](../subsystems/turn-sim.md), [../subsystems/pilots.md](../subsystems/pilots.md)
- [data-files.md](data-files.md) - data and output files
