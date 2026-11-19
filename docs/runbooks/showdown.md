# Local Pokemon Showdown servers

How the project uses local Pokemon Showdown: where it lives, ports 8000-8002, how to start,
stop and restart servers (by hand, by `ops/` scripts, and automatically from the GA), why
long runs bounce them, and the Node team validator. Read this when battles hang, before a
run, or after a reboot.

Last verified against code: 2026-11-18

## Facts

- Checkout: `~/pokemon-showdown` (override with `SHOWDOWN_DIR`). It is a separate git repo:
  never edit it. Format used: `gen9championsvgc2026regmc` (Reg M-C, Champions mod).
- Start command used everywhere: `node pokemon-showdown start <port> --no-security`, run from
  the checkout. `--no-security` lets the random throwaway accounts battle without login; it is
  for a local, trusted machine only.
- A server is "up" when `curl -s http://localhost:<port>` answers
  (`src/showdown_server.py::is_up` uses a 2 s timeout).
- The 2026-11-18 laptop checkout has Node v22.22.0 but NO `~/pokemon-showdown`; there, no
  battles, no eval and no live GA can run (unit tests and `verify.sh` still work).
  Unverified: Node version on the original GPU workstation.

## Ports

| Port | Used by |
|---|---|
| 8000 | Default (`SHOWDOWN_PORT` unset): `python -m src.eval`, serial GA `run/ga_run.py`, parallel island A, paired-eval shard 0, `tools/preflight.py` check |
| 8001 | Parallel island B, paired-eval shard 1, `tools/test_pilots.py` (hard-coded) |
| 8002 | Parallel island C, paired-eval shard 2 |

Python processes pick the port from `SHOWDOWN_PORT` at import time (parsed by
`src/paths.py::showdown_port`; used by `src/player_factory.py::DEFAULT_SERVER` and
`src/ga/config.py::DEFAULT`). One server tops out
around 8 concurrent battles (`GA_CONCURRENCY=8`; measured 2026-10-13). Two workloads on one
server throttle each other by about an order of magnitude: never run an eval, a paired eval
or `tools/test_pilots.py` against a port a GA island is using.

## Start, check, stop

Start or restart ONE port (kills only that port's server, logs to `/tmp/showdown_<port>.log`):

```
bash ops/start_server.sh 8000
```

Start all three if missing (what `run/ga_parallel.sh` does):

```
for p in 8000 8001 8002; do
  curl -s --max-time 2 http://localhost:$p > /dev/null || \
    (cd "${SHOWDOWN_DIR:-$HOME/pokemon-showdown}" && nohup node pokemon-showdown start $p --no-security > /tmp/showdown_$p.log 2>&1 < /dev/null &)
done
sleep 8
for p in 8000 8001 8002; do curl -s --max-time 2 http://localhost:$p > /dev/null && echo ":$p UP" || echo ":$p DOWN"; done
```

Check:

```
pgrep -af "pokemon-showdown start"
```

Stop one port, or all:

```
pkill -9 -f "pokemon-showdown start 8001( |$)"
pkill -9 -f "pokemon-showdown start"
```

Careful: `pkill -f pokemon-showdown` with no port kills every server, including those of
running GA islands. `ops/start_server.sh` was made port-scoped for exactly this reason.

When to (re)start by hand: after a WSL restart or Windows reboot (servers do not survive
it), before a run if a port is down, and when more than about 20% of a generation's battles
time out.

## ops/ scripts

| Script | What it does |
|---|---|
| `ops/start_server.sh [port]` | Default 8000. `pkill -9 -f "pokemon-showdown start <port>( \|$)"`, sleep 2, start from `$SHOWDOWN_DIR`, sleep 5, curl check (prints a check mark or a cross; non-ASCII output). |
| `ops/watch_server.sh` | Loop every 30 s: if :8000 does not answer, run `start_server.sh` (8000 only). Its second half (training-stall killer) targets a different project (`~/vgc-bench`) and is irrelevant here. Run with `nohup bash ops/watch_server.sh > /tmp/watch_server.log 2>&1 &`. |

The launchers start their own servers: `run/ga_parallel.sh` starts any of 8000-8002 that
does not answer, polls up to 60 s each, and aborts if one stays down;
`run/ga_overnight.sh` starts 8000 and runs its own 30 s watchdog loop
(`/tmp/showdown_watchdog.log`); `tools/paired_run.sh` restarts each shard's port before
every chunk.

## Automatic restarts inside the GA (src/showdown_server.py)

Why: the Node server leaks memory / sockets over thousands of battles; a server a few hours
old has taken more than 30 s to answer HTTP (docstring of `restart`). So long runs bounce it.

- `restart(port, showdown_dir, wait_s=60, tries=2)`: `pkill -9 -f "pokemon-showdown start <port>"`,
  sleep 1, launch `node pokemon-showdown start <port> --no-security` with output discarded,
  poll `is_up` once per second for up to 60 s; repeat the whole kill+launch once more if it
  never answered. Returns True/False. (`tests/test_ga_robust.py` pins the 60 s wait and retry.)
- `ensure(port, showdown_dir)`: if not up, `restart`; raises `RuntimeError` if it still is not.
- `src/ga/engine.py::_startup_checks` calls `ensure` when `run_islands` starts (also on every
  respawn), so an island on a dead server exits non-zero instead of scoring every genome 0.0;
  `run/ga_parallel.sh` then respawns it from its last checkpoint after 5 s.
- `run_islands` calls `restart` every `showdown_restart_every` generations (10 in both
  launchers), counted from the generation the process started or resumed at. If the restart
  fails it raises `RuntimeError` (island exits non-zero -> respawn).
- The GA calls `restart` / `ensure` with `src.ga.config.DEFAULT.showdown_port` / `showdown_dir`
  (the old `ga_core` wrappers `restart_showdown`, `ensure_showdown`, `_showdown_up` were removed
  on 2026-11-18).
- `src/eval.py` does NOT check or restart Showdown: with the server down, an eval just
  produces timeouts (`None` results).

A server that dies in the middle of a generation is only brought back at the next 10-gen
restart, by a respawn, or by a watchdog. History (2026-10-15, run p3): all three servers died
around gen 10 and the islands spun in `ConnectionRefused` loops at 100% CPU until restarted
by hand; WSL sleep targets were masked on the workstation as prevention (Unverified: the
exact command used).

## Team validation through Showdown

Two validators exist. Python `src/regmc_db.py::validate_team` (no node; used by the audit and
the evaluator) and the real Showdown validator:

- `src/showdown_validator.py::check_teams(team_texts)` spawns ONE `node src/showdown_validate.js`
  per batch (timeout 60 s), sends each team as a base64 line on stdin, and reads one verdict per
  line: `OK`, `FAIL:<first error>`, `PARSE_FAIL`, `ERR:<message>`. Returns `[(ok, msg), ...]`;
  verdicts are cached in-process by md5 of the team text (`CACHE`).
- `src/showdown_validate.js` loads `dist/sim/dex`, `dist/sim/teams`, `dist/sim/team-validator`
  from the checkout. It needs the built checkout, not a running server.
- Used by `src/ga/legality.py::filter_legal_genomes` (batched: one call for the population, one
  per rebuild round). Without a working checkout node prints nothing, every verdict is
  False, and the GA cannot build a legal population.
- Smoke test (needs the checkout):

```
python -m src.showdown_validator
# expect (True, '') for data/baseline_team.txt, then (False, '...') for a Greninja-Bond variant
```

- `tools/swap_pool.py` and `tools/build_real_ev_holdout.py` instead run the CLI
  `node pokemon-showdown validate-team gen9championsvgc2026regmc` (team on stdin, timeout 30 s,
  return code 0 = valid).
- `node tools/build_regmc_db.js [format] [outPath]` rebuilds `data/regmc_db.json` from
  `$SHOWDOWN_DIR/dist/sim/dex`. It reads the dex directly; a running server is not required.

## Gotchas

- `SHOWDOWN_PORT` is read at import: set it on the command line that starts the process.
- `tools/preflight.py` and `ops/watch_server.sh` only know port 8000.
- Server logs: `/tmp/showdown_<port>.log` (scripts), `/tmp/showdown_ga.log` (overnight);
  servers started by `src/showdown_server.py::restart` have no log.
- `/tmp` logs and running servers are lost on a WSL restart; checkpoints survive.

## Related docs

- [health-check.md](health-check.md) - first checks every session
- [ga-run.md](ga-run.md) - launching the GA (starts servers itself)
- [failure-modes.md](failure-modes.md) - hangs, timeouts, ConnectionRefused
- [../reference/config-and-env.md](../reference/config-and-env.md) - `SHOWDOWN_PORT`, `SHOWDOWN_DIR`
- [../subsystems/battle-harness.md](../subsystems/battle-harness.md) - battle runner, validator code
- [../reference/run-scripts.md](../reference/run-scripts.md) - run/ and ops/ scripts
