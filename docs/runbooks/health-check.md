# Health check, pre-flight and the verify gate

What to run first in any session (health check), what to run before a long GA run
(`tools/preflight.py`, `src/audit_before_launch.py`), and the code gate before any commit
(`tools/verify.sh`). Read this at the start of a session and before launching anything.

Last verified against code: 2026-11-18

Key fact: every battle needs a local Showdown server (port 8000, plus 8001 and 8002 for the
parallel GA). When Showdown is down the failure is often silent: battles time out after 20 s
plus one retry, so a long eval can sit idle for many minutes with no error.

## 0. Health check (run first, always)

From the repo root with the venv active (`source .venv/bin/activate`, or
`source ~/venv-pokemorgad/bin/activate` on the original workstation):

```
echo "=== Showdown ==="
for p in 8000 8001 8002; do curl -s --max-time 2 http://localhost:$p > /dev/null && echo ":$p UP" || echo ":$p DOWN"; done
pgrep -af "pokemon-showdown start" || echo "no Showdown process"

echo "=== Processes ==="
pgrep -af "ga_island|ga_run|ga_parallel|ga_overnight|src.eval|bc_train|paired_eval|watch_islands" || echo "nothing running"

echo "=== Recent artifacts ==="
ls -lat output/champions/ 2>/dev/null | head -6
ls -1dt output/checkpoints/v6/*/ 2>/dev/null | head -3
ls -lat /tmp/ga_*.log 2>/dev/null | head -6

echo "=== Disk ==="
df -h . | tail -1
```

Healthy output during a parallel GA (`run/ga_parallel.sh`): three Showdown ports UP, three
`node pokemon-showdown start 800X` processes, three `python -m run.ga_island` processes at
high CPU plus three `tools/watch_islands.py` watchdogs, and `/tmp/ga_<run_id>_<A|B|C>.log`
written within the last few minutes. Nothing running is also healthy when idle.
On a host without the Showdown checkout (`~/pokemon-showdown` missing) every port is DOWN;
you can still run the unit tests and `verify.sh`, but no battles.

Red flags:

| Signal | Meaning | Action |
|---|---|---|
| Showdown port DOWN but its GA island alive | Island will fail its next restart or hang | Restart that port (`bash ops/start_server.sh 8001`); `ga_parallel.sh` respawns a dead island from its checkpoint |
| GA process alive, CPU below 10% | Hung | Check log freshness: `stat -c '%y' /tmp/ga_<run_id>_A.log; date` |
| Log older than 5 min and CPU low | Stuck | Stop it (`docs/runbooks/ga-run.md`), restart Showdown, relaunch with the same run_id to resume |
| Log fresh but only tracebacks | Traceback loop; `tools/watch_islands.py` only checks log mtime, so it does not catch this (seen 2026-10-15, island A hung 15 min) | `tail -50` the log; kill the island process |
| No checkpoint newer than about 15 min | Stuck (checkpoints are written every generation; a parallel gen took about 10 min/island in the 2026-10-16 smoke) | As above |
| Disk under 5 GB free | Preflight will fail | Prune `output/checkpoints/` (see `docs/runbooks/diagnostics.md`) |

## 1. Pre-flight before a long run

Two launch paths exist (details in `docs/runbooks/ga-run.md`):
- Parallel (preferred for anything over 1 hour): `bash run/ga_parallel.sh <hours> <run_id>`.
  Preflight does NOT launch or validate this path. Run preflight without `--launch` for the
  checks, then launch directly.
- Serial (legacy): `GA_CONCURRENCY=8 python3 tools/preflight.py --launch` starts
  `run/ga_overnight.sh` (run1 2.5 h -> run2 2.5 h -> eval). WARNING: that script deletes
  `output/checkpoints/v6/run1` and `run2` before starting. It activates the repo `.venv` if
  present, else `~/venv-pokemorgad`.

Never launch a long run without the user's explicit approval (hours and run_id).

```
GA_CONCURRENCY=8 python3 tools/preflight.py
```

`tools/preflight.py::main` prints `[OK  ]` / `[FAIL]` lines, about 20 checks, a few seconds:

| # | Check | Passes when | Notes |
|---|---|---|---|
| 1 | `Showdown :8000` | `urlopen("http://localhost:8000", timeout=3)` succeeds | Only port 8000; 8001/8002 are not checked (`ga_parallel.sh` starts them itself). |
| 2 | `showdown process` | `pgrep -f "pokemon-showdown start"` finds one | |
| 3 | data files (5 lines) | `data/regmc_db.json`, `data/baseline_team.txt`, `data/pool_split.json`, `data/meta_items.json`, `data/species_move_priors.json` exist | All tracked in git. |
| 4 | `src/ and run/ committed` | `git diff --quiet src/ run/` | Unstaged changes only; staged-but-uncommitted changes pass. |
| 5 | `src/ga: <name>` (7 lines) | Each of `_species_role`, `_preferred_pool`, `_enforce_composition`, `move_priors_for`, `CANONICAL_ITEMS`, `VAL_POOL_SIZE`, `early_stop_min_battles` appears in the text of `src/ga/*.py` | Guard against constraint / early-stop code being silently removed. Fixed 2026-11-18 to look in `src/ga/` (it had been failing since the genome code left `ga_core.py`); the names now live in `genome.py`, `legality.py`, `pools.py`, `config.py`. |
| 6 | `islands configured` | The string `ISLANDS` appears in `run/ga_run.py` | Serial path only; parallel specs (`run/ga_island.py::SPECS`) are not checked (they are pinned by `tests/test_island_wiring.py`). |
| 7 | `torch CUDA available` | `python3 -c "import torch; print(torch.cuda.is_available())"` prints True | Uses whatever `python3` is on PATH. FAILS on a CPU-only torch (the 2026-11-18 laptop `.venv`). The GA itself does not need a GPU; only BC training / the BC pilot do. |
| 8 | `champions/ writable` | Writes and deletes `output/champions/.preflight_probe` | Creates `output/champions/` if missing. |
| 9 | `disk free > 5 GB` | `shutil.disk_usage` of the repo | |
| 10 | `GA_CONCURRENCY set` | env value is not `"3"` (unset counts as 3) | Production value is 8. `ga_parallel.sh` sets 8 per island anyway. |

Result: `=== All checks passed ===`, or `=== Some checks FAILED ... ===` with exit code 1.
With `--launch` and all checks passing it runs `nohup bash run/ga_overnight.sh` in a new
session, logging to `/tmp/ga_overnight_launch.log`, with `GA_CONCURRENCY` passed through.

### Repo-wide audit

```
python -m src.audit_before_launch
```

`src/audit_before_launch.py::main` (seeded, about 27 s) runs the 9 `check_*` functions of
`CHECKS` in order (one report section each; seeds 0, then 42 and 1 for the mutation and
crossover tests, so the report is deterministic): DB integrity
(format, species / items / moves counts; 2026-11-18: 392 species, 230 base), name sanity,
Mega stone integrity, regional teams (`Loaded: 148 teams`, `Invalid regional teams: 0`),
fuzz of 500 Umbreon-locked and 500 free random genomes, 2000 mutations on a locked genome,
500 crossovers, and baseline team validity. It validates with `src/regmc_db.py::validate_team`
(Python, no node). Any hard failure prints `AUDIT FAILED: N problem(s)` and one
`FAIL <msg>` line each, and the command exits 1 (species with fewer than 4 moves are a
warning only). Healthy:

```
python -m src.audit_before_launch | grep -E "Failures|Invalid regional|Final|VALID|LOCK"
# expect: Failures: 0/500 (three times), Invalid regional teams: 0, Final: VALID, baseline VALID
```

## 2. The code gate: tools/verify.sh

Run after every code change and before any commit; it must end with `ALL PASS`:

```
ruff check --fix <changed files>
bash tools/verify.sh
```

Steps: ruff on `src run tools tests`, import checks, path and pool checks, 33 test files run
one by one (the script exits 1 with `FAILED: tests/<file>.py` at the first failing file), then
the audit (exits 1 with `AUDIT FAILED` on any hard failure). Full step table in
`docs/reference/tests.md`. Expected on 2026-11-18: 223 `PASS` lines, 0 `FAIL`, last line
`ALL PASS`.

```
bash tools/verify.sh 2>&1 | tee /tmp/verify.log | tail -1
grep -c "^PASS" /tmp/verify.log    # 223 on 2026-11-18
```

Fixed 2026-11-18: the tests used to run as one `a && b && ...` chain under `set -e`, so a
failing file silently skipped every later file and the script still printed `ALL PASS`; the
audit always exited 0; and the OTS real-replay test in `tests/test_battle_memory.py` failed on
hosts without `data/showdown_replays/` (it now skips like the other four replay tests).

Agent rule (`.clinerules`): anything other than a genuine `ALL PASS` means restore the
backup and stop; never report "passed with minor issues".

## Checklist before a long GA run

1. Health check above: nothing else running (never run an eval or a second GA against the
   same Showdown while a GA runs).
2. `bash tools/verify.sh` -> `ALL PASS` and no FAIL lines.
3. `GA_CONCURRENCY=8 python3 tools/preflight.py` -> all OK (check 7 may be ignored for a
   GA-only run on a CPU host; say so explicitly).
4. `python -m src.audit_before_launch` -> zero failures.
5. Do not modify `src/` in the hour before a long run.
6. Get the user's go-ahead with hours and a fresh run_id, then launch per `docs/runbooks/ga-run.md`.

## Related docs

- [showdown.md](showdown.md) - starting / restarting servers
- [ga-run.md](ga-run.md) - launch, monitor, stop, resume
- [diagnostics.md](diagnostics.md) - one-liners, cleanup
- [failure-modes.md](failure-modes.md) - symptom -> cause -> fix
- [../reference/tests.md](../reference/tests.md) - every test and the verify steps
- [../design/policy.md](../design/policy.md) - operating policy
