# Reference: run/ and ops/ scripts

Every file in `run/` and `ops/`: purpose, arguments, environment variables, what each
starts or kills, and what it writes. Read this before running, editing or wrapping a
launcher. For the operational procedure (launch, monitor, stop, resume) see
`../runbooks/ga-run.md`.

Last verified against code: 2026-11-18

## Overview

| file | lines | kind | purpose |
|---|---|---|---|
| `run/__init__.py` | 0 | package marker | lets `python -m run.<name>` work |
| `run/ga_run.py` | 68 | Python entry | serial GA: 3 islands in one process, ring migration |
| `run/ga_island.py` | 105 | Python entry | one island per process (used by ga_parallel.sh), optional replay logging |
| `run/ga_parallel.sh` | 133 | bash | 3 island processes on Showdown 8000/8001/8002 with watchdog + respawn |
| `run/ga_overnight.sh` | 73 | bash | serial run1 -> run2 -> final eval chain on :8000 |
| `ops/start_server.sh` | 10 | bash | (re)start one Showdown server port |
| `ops/watch_server.sh` | 37 | bash | keep :8000 alive (plus a stall killer for another project) |

Common facts: all GA entry points call `src.ga.engine.run_islands` (implemented in
`src/ga/engine.py`). `run/` is not an installed package; run from the repo root with
`python -m run.<name>`. GA settings are read from the environment once at import
(`GA_PILOT` default `vgc`, `GA_OPP` default `ladder`, `GA_META_WEIGHTS` default `1`,
`GA_TRAIN_SAMPLE` default 250, `SHOWDOWN_PORT` default 8000, `SHOWDOWN_DIR` default
`~/pokemon-showdown`). Islands: A = Umbreon slot 0 + baseline seed, B = Umbreon slot 0,
C = free.

## run/ga_run.py

Serial launcher. `python -m run.ga_run [run_id=run1] [hours=5.0]`.
- Calls `random.seed({"run1": 42, "run2": 137, "run3": 999}.get(run_id, 42))` at import.
- Islands: A `{0: "Umbreon"}` seeds `[data/baseline_team.txt]`; B `{0: "Umbreon"}` no
  seed; C `{}` no seed. If `run_id != "run1"`, each island also seeds from
  `output/champions/ga_run1_island_<X>.txt` when that file exists (warm start).
- `run_islands(pop_per_island=10, generations=999, battles_per_genome=800,
  concurrency=int(GA_CONCURRENCY or 3), immigration_rate=0.20, stagnation_limit=5,
  diversity_floor=15, migration_every=5, showdown_restart_every=10, max_hours=hours,
  run_id=run_id)`. 800 is capped to the 118-team train pool, so every genome plays the
  whole pool (early-stop path active). This is the launcher affected by the 2026-11-18
  fitness-ordering fix; older ga_run scores are not comparable.
- Env: `GA_CONCURRENCY`, all GA settings above, `SHOWDOWN_PORT`.
- Starts nothing external besides Showdown restarts done by the engine (on
  `SHOWDOWN_PORT`, every 10 gens, or at startup if the port is dead).
- Writes `output/checkpoints/v6/<run_id>/gen_NNNN.json` per gen;
  `output/champions/ga_<run_id>_island_{A,B,C}.txt` and `..._train.txt` at the end. Stdout
  only (redirect it).
- The module runs the GA when executed as `__main__` only; importing it does not launch.

## run/ga_island.py

Single-island launcher. `ISLAND_NAME=<A|B|C> SHOWDOWN_PORT=<port> python -m run.ga_island [run_id=p1] [hours=4.0]`.
- Env: `ISLAND_NAME` (default A, uppercased; other values exit 1), `SHOWDOWN_PORT`
  (default 8000; only printed here, the engine and battle code read it themselves),
  `GA_CONCURRENCY` (default 8), `GA_GENERATIONS` (default 999; 2 for a smoke test),
  `GA_REPLAY_LOG` (non-empty enables replay logging), `GA_REPLAY_MAX_PER_GEN` (default 50,
  max battles saved per generation), `GA_REPLAY_DIR` (default `<repo>/output/replay_log`).
- SPECS: A `{0: "Umbreon"}` + `[data/baseline_team.txt]`; B `{0: "Umbreon"}`, no seed;
  C `{}`, no seed. RNG seed A=42, B=137, C=999 (`random.seed` at import). Pinned by
  `tests/test_island_wiring.py` (A lock + seed, B lock + no seed, C free; both launchers).
- `run_islands([that one island], pop_per_island=10, generations=GA_GENERATIONS,
  battles_per_genome=50, concurrency=CONC, immigration_rate=0.20, stagnation_limit=5,
  diversity_floor=15, migration_every=999, showdown_restart_every=10, max_hours=hours,
  run_id=f"{run_id}_{NAME}", replay_logger=make_replay_logger())`. 50 opponents = single batch, never the early-stop path.
- Prints `=== island A | run_id=p1_A | port=8000 | 4.0h | conc=8 | seed=42 ===`.
- Writes `output/checkpoints/v6/<run_id>_<X>/`, champions
  `output/champions/ga_<run_id>_<X>_island_<X>.txt` and `..._train.txt` (ga_parallel.sh
  renames the first). With `GA_REPLAY_LOG`: `<GA_REPLAY_DIR>/<run_id>_<X>/<X>_genNNNN.jsonl`
  (see `docs/subsystems/battle-harness.md`, replay logging).
- Docstring fixed 2026-11-18 (it claimed "Umbreon lock removed 2026-11-15"). The lock was
  restored on A and B on 2026-11-17 (commit 6762c32); `tests/test_island_wiring.py` pins the
  specs of both launchers.
- Replay logging redesigned 2026-11-18 (`src/replay_log.py`): real fitness / outcome /
  generation, a real per-generation cap, a private RNG, so a run with logging gives exactly
  the same GA results as one without. The old version saved empty histories.

## run/ga_parallel.sh

`bash run/ga_parallel.sh [hours=4.0] [run_id=p1]` (run with nohup; see runbook).
1. `cd` to the repo root from the script's own path (any checkout location), activates the repo `.venv` if it exists, else `~/venv-pokemorgad` (since 2026-11-18;
   before, the workstation venv was hard-coded),
   `PYTHONUNBUFFERED=1`.
2. Kills: `pkill -9 -f "run.ga_island"` - every island process on the host, any run_id.
3. Starts Showdown on each of 8000, 8001, 8002 that does not answer curl:
   `node pokemon-showdown start <port> --no-security` from `${SHOWDOWN_DIR:-$HOME/pokemon-showdown}`,
   log `/tmp/showdown_<port>.log`. Polls each port up to 60 s; exits 1 if one stays down.
4. Per island (A:8000, B:8001, C:8002, started 2 s apart) a respawn loop:
   `SHOWDOWN_PORT=<port> ISLAND_NAME=<X> GA_CONCURRENCY=8 python -m run.ga_island <run_id> <remaining_h>`
   (`GA_CONCURRENCY` is forced to 8), log `/tmp/ga_<run_id>_<X>.log` (truncated on every
   (re)launch), plus `python3 tools/watch_islands.py <run_id> <X> <pid> 300`, log
   `/tmp/ga_<run_id>_<X>_watchdog.log`. The watchdog checks every 30 s and SIGKILLs the
   island if its log mtime is older than 300 s. Exit 0 -> done; non-zero (including 137
   from the watchdog) -> respawn after 5 s unless the time budget is spent; remaining hours
   never go below 0.05.
5. After all three exit: renames `output/champions/ga_<run_id>_<X>_island_<X>.txt` to
   `ga_<run_id>_island_<X>.txt` (the `_train.txt` file keeps the doubled name), lists them,
   touches `/tmp/ga_<run_id>_done`.
- Env honored: `SHOWDOWN_DIR`. GA settings (`GA_PILOT`, ...) pass through to the islands.
- Measured 2026-10-14: 2.78x serial throughput. Known weakness (2026-10-15): a traceback
  loop keeps the log fresh, so the mtime watchdog does not catch it.

## run/ga_overnight.sh

`bash run/ga_overnight.sh` (no arguments; usually `GA_CONCURRENCY=8 nohup bash run/ga_overnight.sh > /tmp/ga_overnight_launch.log 2>&1 &`,
or launched by `python3 tools/preflight.py --launch`).
1. `cd` to the repo (from the script path), activates the repo `.venv` if it exists, else `~/venv-pokemorgad` (since 2026-11-18;
   before, the workstation venv was hard-coded),
   `PYTHONUNBUFFERED=1`.
2. Kills: `pkill -9 -f "ga_run.py"` (a `python -m run.ga_run` process does not match it).
   A second `pkill -9 -f "ga_core"` was removed on 2026-11-18 with `src/ga_core.py`; no
   process could match it any more.
3. Starts Showdown on 8000 if down (log `/tmp/showdown_ga.log`), exits 1 if still down.
4. DESTRUCTIVE: `rm -rf output/checkpoints/v6/run1 output/checkpoints/v6/run2`.
5. Background watchdog subshell: every 30 s restarts Showdown :8000 if curl fails (log
   `/tmp/showdown_watchdog.log`). It is never killed by the script.
6. `python -m run.ga_run run1 2.5 | tee /tmp/ga_run1.log`, then `run2 2.5` (warm start from
   run1 champions) `| tee /tmp/ga_run2.log`. The printed `rc=$?` is tee's exit code.
7. `python -m src.eval data/baseline_team.txt` + the six run1/run2 champions with eval
   defaults (`--opponents heldout --pilot both --opp heuristic`, not the GA environment)
   `| tee /tmp/ga_final_eval.log`.
8. Touches `/tmp/ga_overnight_done_<YYYYmmdd_HHMMSS>`.
- Env: `SHOWDOWN_DIR`; `GA_CONCURRENCY` is not set by the script but inherited (ga_run
  default 3 if unset).

## ops/start_server.sh

`bash ops/start_server.sh [port=8000]`: `pkill -9 -f "pokemon-showdown start <port>( |$)"`
(only that port), sleep 2, `node pokemon-showdown start <port> --no-security` from
`${SHOWDOWN_DIR:-$HOME/pokemon-showdown}` with nohup, log `/tmp/showdown_<port>.log`,
sleep 5, curl check, prints a success or failure line. It used to kill every Showdown
process, which took down 8001/8002 mid-run; it is port-scoped now.

## ops/watch_server.sh

`nohup bash ops/watch_server.sh > /tmp/watch_server.log 2>&1 &`. Infinite loop every 30 s:
if :8000 does not answer curl, runs `ops/start_server.sh` (port 8000 only). Second half
targets the separate `~/vgc-bench` project: if a `vgc_bench.train` process is running and
no TensorBoard event file under `~/vgc-bench/results/logs_sp` changed for 300 s, it
`pkill -9`s it. Irrelevant to this repo. Does not watch 8001/8002.

## Related tools (documented in tools.md)

- `tools/watch_islands.py <run_id> <island> <pid> [stall_s=300]` - island watchdog used by ga_parallel.sh.
- `tools/extract_champions.py <run_id>` - champions from parallel checkpoints, same rule as the GA (primary = train best, `_train` = train best, `_val` = val best).
- `tools/preflight.py [--launch]` - pre-launch checks; `--launch` starts ga_overnight.sh.
- `tools/log_milestone.py "Title" "Summary"` - appends to `docs/history/milestones.md` and commits that file.

## Related docs

- [../runbooks/ga-run.md](../runbooks/ga-run.md) - launch, monitor, stop, resume, recover
- [../subsystems/ga.md](../subsystems/ga.md) - GA engine
- [../subsystems/ga-loop.md](../subsystems/ga-loop.md) - generation loop, checkpoints, champions
- [../runbooks/showdown.md](../runbooks/showdown.md) - Showdown servers and ports
- [tools.md](tools.md) - tools/ reference
- [config-and-env.md](config-and-env.md) - all env vars
