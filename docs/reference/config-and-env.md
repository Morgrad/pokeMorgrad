# Configuration: environment variables

Every environment variable read anywhere in `src/`, `run/`, `tools/`, `ops/` and `tests/`:
default, where it is read (`file::symbol`), what it changes, and WHEN it is read.
Read this before setting a variable for a run, or before adding a new one.
Ports, paths, venvs, pyproject and tunable constants are in `config-and-env-constants.md`.

Last verified against code: 2026-11-18

## The one rule: import-time vs per-call

Most variables are read ONCE, when the module is imported, into a module constant
(or into the frozen `src/ga/config.py::DEFAULT`). Setting them later in the same
process has no effect. Always set them on the command line that starts the process:

```
SHOWDOWN_PORT=8001 GA_PILOT=heuristic python -m src.eval --pilot heuristic data/baseline_team.txt
```

"Per construction" below means the value is read each time the object is built
(pilots are built once per battle), so it can differ between battles in theory, but in
practice it is set once per process too. Constructor keyword arguments always win
over the environment for the pilot knobs.

## Showdown routing and repo location

| Variable | Default | Read at (when) | Effect |
|---|---|---|---|
| `SHOWDOWN_PORT` | `8000` | parsed only by `src/paths.py::showdown_port`; used by `src/player_factory.py::DEFAULT_SERVER` (import) | Port every poke_env player connects to (`ws://localhost:<port>/showdown/websocket`). This is the one that routes battles. |
| | | `src/ga/config.py::GAConfig.from_env` -> `DEFAULT.showdown_port` (import) | Port the GA probes at startup (`showdown_server.ensure`) and bounces every `showdown_restart_every` gens. (The old alias `ga_core.SHOWDOWN_PORT` was removed with the facade.) |
| | | `run/ga_island.py::PORT` (import) | Printed in the island banner only. |
| `SHOWDOWN_DIR` | `~/pokemon-showdown` | `src/paths.py::showdown_dir` (per call) | Showdown checkout used to (re)start servers. |
| | | `src/ga/config.py::GAConfig.from_env` -> `DEFAULT.showdown_dir` (import) | Dir the GA restarts Showdown from. |
| | | `src/showdown_validate.js` (each `node` spawn) | Loads `<dir>/dist/sim/*` for the batch team validator used by `src/showdown_validator.py::check_teams`. |
| | | `tools/build_regmc_db.js` (start) | Loads `<dir>/dist/sim/dex` to rebuild `data/regmc_db.json`. |
| | | `tools/swap_pool.py::SHOWDOWN_DIR`, `tools/build_real_ev_holdout.py::SHOWDOWN` (import) | cwd for `node pokemon-showdown validate-team`. |
| | | `ops/start_server.sh`, `run/ga_overnight.sh`, `run/ga_parallel.sh`, `tools/paired_run.sh` (`SD`) | Where the shell scripts `cd` to run `node pokemon-showdown start <port> --no-security`. |
| `POKEMORGRAD_ROOT` | unset (repo root = parent of `src/`) | `src/paths.py::_resolve_repo_root` -> `REPO_ROOT` (import) | Override repo root. Must contain `data/` or a `RuntimeError` is raised. All `data_path` / `output_path` / `src_path` derive from it. The golden harness points it at a temp dir. Shell scripts that `cd ~/pokeMorgrad` (`run/ga_parallel.sh`, `tools/verify.sh`) ignore it. |

## GA fitness environment (all import-time, `src/ga/config.py`)

`DEFAULT = GAConfig.from_env()` runs once at import. Read settings as `DEFAULT.<field>`
(the old uppercase aliases `FITNESS_PILOT`, `META_WEIGHTS`, ... died with the `ga_core`
facade on 2026-11-18; mapping in `docs/reference/ga-old-names.md`).
Tests build configs with `GAConfig.from_env({...})` instead of touching `os.environ`.

| Variable | Default | Field | Effect |
|---|---|---|---|
| `GA_PILOT` | `vgc` | `fitness_pilot` | Our pilot in fitness battles: `vgc`, `heuristic`, `doubles`, `bc`. |
| `GA_OPP` | `ladder` | `fitness_opp` | Opponent pilot: `ladder` (heuristic + Protect / Fake Out at replay rates) or `heuristic`. `GA_PILOT=heuristic GA_OPP=heuristic` reproduces the pre-2026-10-16 environment; scores are NOT comparable across settings. |
| `GA_META_WEIGHTS` | `1` | `meta_weights` | `"1"` = fitness is the win rate weighted by ladder usage of each opponent (`data/species_ladder_usage.json`); anything else = plain win rate. With `1`, a missing usage file makes `run_islands` raise at startup. |
| `GA_TRAIN_SAMPLE` | `250` | `train_sample_size` | Opponents sampled per generation when the train pool is larger. The pool is 148 teams (2026-11-18), so no sampling happens. |
| `SHOWDOWN_PORT` / `SHOWDOWN_DIR` | see above | `showdown_port` / `showdown_dir` | Server the GA ensures and restarts. |

## Concurrency and GA launchers

| Variable | Default | Read at (when) | Effect |
|---|---|---|---|
| `GA_CONCURRENCY` | `3` | `src/eval.py::CONCURRENCY` (import) | Default of `python -m src.eval --concurrency`. |
| | `3` | `src/ga/engine.py::run_islands` default arg (evaluated at import) | Used only when a caller omits `concurrency=`. |
| | `3` | `run/ga_run.py` (`__main__`) | Serial 3-island GA. `run/ga_overnight.sh` does NOT set it, so the overnight chain runs at 3 unless you export it. |
| | `8` | `run/ga_island.py::CONC` (import) | Parallel island. `run/ga_parallel.sh` always passes `GA_CONCURRENCY=8`. |
| | `3` | `tools/preflight.py::main` (check 10) | Preflight FAILS if unset or `"3"`; passes it through to `run/ga_overnight.sh` on `--launch`. |
| `ISLAND_NAME` | `A` | `run/ga_island.py::NAME` (import, upper-cased) | Picks island spec, RNG seed (A=42, B=137, C=999) and run id suffix. Not A/B/C -> exit 1. |
| `GA_GENERATIONS` | `999` | `run/ga_island.py::run_island` (per call) | Generation cap for one island process; `2` for a smoke test. |
| `GA_REPLAY_LOG` | `""` (off) | `run/ga_island.py` (import) | Non-empty passes a `src/replay_log.py::ReplayLogger` to `run_islands`: a deterministic sample of full battle logs, filtered by `src/replay_filters.py::default_ga_filter` with real fitness / outcome. Never changes GA results. |
| `GA_REPLAY_MAX_PER_GEN` | `50` | `run/ga_island.py` (import) | Max battles saved per island and generation (`ReplayLogger.max_per_gen`). |
| `GA_REPLAY_DIR` | `<repo>/output/replay_log` | `run/ga_island.py` (import) | Output root; files go to `<dir>/<run>_<X>/<X>_genNNNN.jsonl`. |

Measured (STATE 5.9, 2026-10-13, 800-battle smoke, one server): c=3 35 s, c=8 28 s,
c=12 28 s, c=16 29 s. Ceiling is 8 per Showdown server; above that the per-battle
handshake dominates.

## Pilot knobs (`src/doubles_pilot.py`, `src/vgc_pilot.py`, `src/support_value.py`, `src/turn_sim_types.py`)

`VGCPilot` (the GA's default pilot) subclasses `DoublesPilot`, so all of these apply to it.

| Variable | Default | Read at (when) | Effect |
|---|---|---|---|
| `DOUBLES_TURN_SIM` | `1` | `DoublesPilot.__init__` (per construction) | `0` turns off the `turn_sim` decision. On by default: paired +4.7 pts vs heuristic (n=17,941) and +4.5 vs ladder (n=16,506), p<0.001 (2026-10-16). Kwarg `use_turn_sim=` wins. |
| `DOUBLES_KO_BONUS` | `doubles_eval.KO_BONUS` = `1.0` | `DoublesPilot.__init__` | KO weight in the pair score. Sweep 0-4 (2026-10-16): plateau from 1.0 up, 0 about 4 pts worse. Kwarg `ko_bonus=` wins. |
| `DOUBLES_MIN_GAIN` | `doubles_eval.MIN_GAIN` = `0.01` | `DoublesPilot.__init__` | Minimum gain over the baseline pair before deviating. Kwarg `min_gain=` wins. |
| `DOUBLES_FOE_ACTIONS` | `1` | `VGCPilot.__init__` | `0` stops feeding foe Protect / Fake Out / Trick Room odds (`src/opp_actions.py`) to the sim. |
| `DOUBLES_SUPPORT` | `support_value.DEFAULT_SUPPORT` = `"all"` (ON) | `support_value.parse_effects` (per call; called in `DoublesPilot.__init__`) | Support-move layer. `all`/`1`/`on` = every effect in `EFFECTS` (`foulplay, snarl, charm, helpinghand, taunt, heal`); `""`/`0`/`off`/`none` = off; or a comma list. Unknown names raise `ValueError`. Kwarg `support=` wins. Enabled by default in commit `8b28efb`. |
| `DOUBLES_LOOKAHEAD` | `0` (`DEFAULT_LOOKAHEAD = False`) | `support_value.lookahead_enabled` (per call) | State-delta continuation (`turn_sim_lookahead`). Only active when support effects are non-empty. Paired result 2026-10-20: neutral (-1.5 [-3.9,+0.8] and +1.3 [-0.7,+3.3]), +14% decision time, so it stays off. Kwarg `lookahead=` wins. |
| `DOUBLES_LA_LOG` | unset | `DoublesPilot` refine step (per decision) | Path; when set and the lookahead is on, appends every decision where the lookahead changed the pick as JSONL. Diagnostic only. |
| `DOUBLES_SUPPORT_COST` | `0.15` | `support_value.SUPPORT_COST` (import) | Tempo cost of a pure-support action (untuned). |
| `DOUBLES_SUPPORT_HORIZON` | `2.0` | `support_value.SUPPORT_HORIZON` (import) | Further turns a stat drop keeps paying. |
| `DOUBLES_SUPPORT_STAY` | `0.7` | `support_value.FOE_STAY` (import) | P(dropped foe is still in play). |
| `DOUBLES_TR_HORIZON` | `2.0` | `support_value.TR_HORIZON` (import) | Turns of Trick Room a Taunt denies. |
| `DOUBLES_LOOKAHEAD_GAMMA` | `0.7` | `support_value.LOOKAHEAD_GAMMA` (import) | Per-turn discount in the lookahead. |
| `DOUBLES_PASSIVE_COST` | `0.30` | `src/turn_sim_types.py::PASSIVE_COST` (import) | Tempo cost per switch / Protect in the sim. Raised from 0.15 to 0.30 in commit `7f72853` because battles ran 60+ turns of Protect/switch and a GA generation took ~1 h. |

## BC training and BC pilot (import-time)

| Variable | Default | Read at | Effect |
|---|---|---|---|
| `BC_DATA` | `data/training_data.jsonl` | `src/bc_train.py::DATA` | Training JSONL (gitignored, must exist locally). |
| `BC_OUT` | `bc_candidate.pt` | `src/bc_train.py::BEST_MODEL_PATH` | File name under `output/models/`. The production `bc_best.pt` is only replaced by hand after the promotion check (see `docs/design/policy.md`). Default was `bc_best.pt` before 2026-11-18. |
| `BC_MODEL` | `v2` | `src/bc_train.py::MODEL_ARCH` | `v2` MLP or `v3` transformer. |
| `BC_BATCH` | `256` | `src/bc_train.py::BATCH` | 512/1024 lost move accuracy at matched epochs (2026-10-13). |
| `BC_EPOCHS` | `30` | `src/bc_train.py::EPOCHS` | Max epochs. |
| `BC_PATIENCE` | `3` | `src/bc_train.py::PATIENCE` | Early stop after N epochs without `val_move_acc` gain. |
| `BC_PILOT_PATH` | `output/models/bc_best.pt` | `src/bc_player.py::MODEL_PATH` | Weights used by `--pilot bc` / `GA_PILOT=bc`. |

`src/bc_train.py::DEVICE` and `src/bc_player.py::DEVICE` are `"cuda"` when
`torch.cuda.is_available()`, else `"cpu"` (on ROCm torch the AMD GPU is the `cuda` device).

## Tools, tests and process-level variables

| Variable | Default | Read at | Effect |
|---|---|---|---|
| `ENC_SNAPSHOT_REF` | `/tmp/enc_snapshot_ref.pt` | `tools/encode_snapshot.py::REF_PATH` (import) | Reference file for `capture` / `check`. |
| `PYTHONHASHSEED` | must be `0` | `tests/golden/ga_harness.py::main` | Harness exits unless `0` (genome code iterates sets). `tests/test_ga_golden.py` sets it for its subprocess. |
| `PYTHONUNBUFFERED` | set to `1` | exported by `run/ga_parallel.sh`, `run/ga_overnight.sh` | Live log lines in `/tmp/*.log`. |
| `PYTHONPATH` | unset | `tools/paired_run.sh` sets `PYTHONPATH=.` | Needed for scripts with no `sys.path` bootstrap, e.g. `PYTHONPATH=. python tools/bc_diagnostic.py 15`. The package is not pip-installed in the venv. |

The golden harness also pops `GA_PILOT`, `GA_OPP`, `GA_META_WEIGHTS`, `GA_TRAIN_SAMPLE`,
`GA_CONCURRENCY` before importing the GA, so your shell values cannot break the golden test.

## Shell-only variables

`tools/paired_run.sh` (usage `bash tools/paired_run.sh <heuristic|ladder> <target per shard>`):

| Variable | Default | Effect |
|---|---|---|
| `CHUNK` | `1000` | Matchups per shard before its server is restarted and the shard relaunched. |
| `STALL_S` | `300` | Kill and resume a shard whose log has not been written for this many seconds. |
| `TAG` | `""` | Log/result name tag (`data/paired_eval/<opp>_<tag>_shard<i>.jsonl`). |
| `MODE` | `turnsim` | `tools/paired_eval.py --mode` (`turnsim`, `support`, `lookahead`). |
| `SUPPORT` | `all` | `--support` effect list. |
| `TEAMS` | `""` | Comma list of team files (`--team`). |
| `PY` | `.venv/bin/python` if it exists, else `$HOME/venv-pokemorgad/bin/python` | Interpreter for `tools/paired_run.sh`; set `PY=...` to override. |
| `SHOWDOWN_DIR` | `$HOME/pokemon-showdown` | Checkout used to restart ports 8000-8002. |

`run/ga_parallel.sh` and `run/ga_overnight.sh` take positional arguments, not variables
(`ga_parallel.sh [hours=4.0] [run_id=p1]`). `ops/watch_server.sh` has internal constants
only (`CHECK_INTERVAL=30`, `STALL_SECONDS=300` for a different project).

ROCm variables (`GPU_MAX_HEAP_SIZE`, `HSA_ENABLE_SDMA`, `MIOPEN_*`) are not read by repo
code; they live in the venv activate script on the GPU workstation. See `docs/runbooks/environment.md`.

## Adding a new variable safely

1. Read it in one place (a module constant or a `GAConfig` field), not in several modules.
2. GA-affecting knobs belong in `src/ga/config.py::GAConfig` + `from_env`; add the default to
   `tests/test_ga_config.py::test_defaults_without_env`.
3. If it changes GA output, the golden test will fail: regenerate only if the change is intended
   (`PYTHONHASHSEED=0 python tests/golden/ga_harness.py --write`).
4. Add a row to this file.

## Related docs

- [config-and-env-constants.md](config-and-env-constants.md) - ports, paths, venvs, pyproject, tunable constants
- [../runbooks/environment.md](../runbooks/environment.md) - host, GPU, ROCm, venvs
- [../runbooks/showdown.md](../runbooks/showdown.md) - Showdown servers and ports
- [../subsystems/ga.md](../subsystems/ga.md) - GA engine, `GAConfig`
- [../subsystems/pilots.md](../subsystems/pilots.md) - pilots that read the `DOUBLES_*` knobs
- [../subsystems/bc.md](../subsystems/bc.md) - BC training
- [tests.md](tests.md) - golden test and `PYTHONHASHSEED`
