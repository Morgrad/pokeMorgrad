# Runbook: running the GA (launch, monitor, stop, resume, recover champions)

Step-by-step commands to launch a GA run (parallel 3-island or serial), watch it, stop it,
resume it from checkpoints and recover champions from a killed run. Read this before
starting or babysitting any GA run. First time, or explaining it to someone new: start with
`quickstart.md` (setup from zero, plain words). Engine internals: `../subsystems/ga.md`;
script arguments in detail: `../reference/run-scripts.md`.

Last verified against code: 2026-11-18

## Key facts

- Run from the repo root with the venv active (`source .venv/bin/activate`, or
  `source ~/venv-pokemorgad/bin/activate` on the original workstation). Launch Python
  entry points with `-m` (`python -m run.ga_island`), not `python run/ga_run.py`.
- Each GA process talks to ONE local Showdown server (`SHOWDOWN_PORT`, default 8000).
  Showdown checkout: `$SHOWDOWN_DIR`, default `~/pokemon-showdown`.
- Fitness environment (env, read at process start): `GA_PILOT=vgc`, `GA_OPP=ladder`,
  `GA_META_WEIGHTS=1`. Scores from different environments are not comparable.
- Islands (both launchers): A = Umbreon locked in slot 0 + seeded with
  `data/baseline_team.txt`; B = Umbreon locked in slot 0, no seed (GA fills 5 free slots);
  C = no lock, no seed. Parallel RNG seeds A=42, B=137, C=999.
- Checkpoint every generation: `output/checkpoints/v6/<run_id>/gen_NNNN.json`. Champions
  are written ONLY at the end of a run: `output/champions/ga_<run_id>_island_<X>.txt`.
- Same run_id = resume. New run_id = fresh run.

## 0. Before launching

```
python3 tools/preflight.py          # Showdown :8000, data files, src/ run/ committed, GPU, disk, GA_CONCURRENCY
bash tools/verify.sh                # must end with ALL PASS
```

`tools/preflight.py` checks only port 8000 and the serial launcher; for the parallel run
`run/ga_parallel.sh` starts 8000-8002 itself. Check that the run_id is unused:
`ls output/checkpoints/v6/ | grep <run_id>`.

## 1. Parallel run (preferred for runs over an hour)

Three processes, one island each, Showdown on 8000 (A), 8001 (B), 8002 (C), no migration.

```
nohup bash run/ga_parallel.sh 4.0 p5 > /tmp/ga_p5_launch.log 2>&1 &
echo "launch PID $!"
tail -20 /tmp/ga_p5_launch.log
```

Arguments: `[hours=4.0] [run_id=p1]`. What it does: `cd` to the repo root (from the script path), activates
the repo `.venv` if present else `~/venv-pokemorgad`, `pkill -9 -f "run.ga_island"` (kills islands of ANY
other parallel run too), starts missing Showdown servers and polls each up to 60 s, then
per island loops: `SHOWDOWN_PORT=<port> ISLAND_NAME=<X> GA_CONCURRENCY=8 python -m
run.ga_island <run_id> <remaining_h>` plus a watchdog (`tools/watch_islands.py`, kills the
island if its log is untouched for 300 s). Non-zero exit -> respawn after 5 s from the last
checkpoint with the remaining hours; exit 0 or time spent -> stop. At the end it renames
`ga_<run_id>_<X>_island_<X>.txt` -> `ga_<run_id>_island_<X>.txt` and touches
`/tmp/ga_<run_id>_done`.

Smoke test (2 generations, one island, server already up):

```
SHOWDOWN_PORT=8000 ISLAND_NAME=C GA_GENERATIONS=2 python -m run.ga_island smoke1 0.5
```

Per-island cost: 10 genomes x 50 opponents + 30 validation battles = 530 battles/gen.

## 2. Serial run (3 islands in one process, ring migration)

```
curl -s http://localhost:8000 > /dev/null || bash ops/start_server.sh 8000
GA_CONCURRENCY=8 nohup python -m run.ga_run run2 5.5 > /tmp/ga_run2.log 2>&1 &
```

Arguments: `[run_id=run1] [hours=5.0]`. RNG seed by run_id: run1=42, run2=137, run3=999,
anything else 42. Runs other than `run1` add `output/champions/ga_run1_island_<X>.txt` as
an extra seed when present (warm start). Plays all 118 train teams per genome (early stop
after 50 if < 15%), migrates the top 2 around the ring every 5 gens. `GA_CONCURRENCY`
default here is 3; set 8 (measured 2026-10-13: c=3 35 s, c=8 28 s, c=12/16 no better per
800-battle smoke).

Overnight chain (serial run1 2.5 h -> run2 2.5 h warm start -> `src.eval` of 7 teams):
`GA_CONCURRENCY=8 nohup bash run/ga_overnight.sh > /tmp/ga_overnight_launch.log 2>&1 &`
or `GA_CONCURRENCY=8 python3 tools/preflight.py --launch`. WARNING: it `rm -rf`s
`output/checkpoints/v6/run1` and `run2` first (no resume) and kills any `ga_run.py`
process.

## 3. Monitoring

Logs: parallel `/tmp/ga_<run_id>_<X>.log` (+ `_watchdog.log`, launcher log you chose);
serial: the file you redirected to (`/tmp/ga_run1.log` etc. for the overnight chain).

```
ps aux | grep -E "ga_island|pokemon-showdown start" | grep -v grep     # expect 3 python + 3 node
for n in A B C; do echo "--- $n"; tail -4 /tmp/ga_p5_${n}.log; done
grep -h "NEW ALL-TIME" /tmp/ga_p5_*.log | tail -20                       # train-best trajectory
grep -E "\] gen [0-9]+:" /tmp/ga_p5_A.log | tail -5                      # per-gen summary
grep -c "early-abort" /tmp/ga_run2.log                                   # serial only (>50 opponents)
grep -E "STAGNATION|diversity low|RESUMED|showdown|TIME BUDGET|DONE" /tmp/ga_p5_A.log
cat /tmp/ga_p5_A_watchdog.log
ls output/checkpoints/v6/p5_A/ | tail -3
stat -c '%y' /tmp/ga_p5_A.log; date                                      # stale > 5 min = stuck
```

Log line meanings: `[A] gen 12: best= 48.2%  all-time= 61.3%  stag=2  uniq=21` (gen best,
train all-time, generations without improvement, distinct base species);
`NEW VAL BEST` = validation-slice high (informational; champions use train best);
`INVALID` = genome failed the local DB check (scored 0.0); `>> checkpoint: gen_0012.json`
after every generation. `[showdown] restarting` every 10 gens is normal.

## 4. Stopping

There is no signal handler: SIGTERM and SIGKILL both stop immediately. Checkpoints written
at the end of each completed generation survive; the generation in progress is lost; no
champion files are written (recover them, section 6).

```
pkill -f "run/ga_parallel.sh"; pkill -f "tools/watch_islands.py"   # stop respawning first
pkill -9 -f "run.ga_island"                                        # then the islands
pkill -9 -f "run.ga_run"; pkill -9 -f "ga_overnight"               # serial / overnight
pkill -9 -f "pokemon-showdown start 8001"; pkill -9 -f "pokemon-showdown start 8002"   # optional
ps aux | grep -E "ga_island|ga_run|ga_parallel|ga_overnight|watch_islands" | grep -v grep || echo clean
```

Kill the launcher loop before the islands, otherwise `ga_parallel.sh` respawns them. The
overnight chain also leaves a background Showdown watchdog subshell (it restarts :8000
every 30 s if down); find it with `ps aux | grep ga_overnight`.

## 5. Resuming

Relaunch with the same run_id. Parallel: `nohup bash run/ga_parallel.sh <hours> p5 > ... &`
(each island resumes from `output/checkpoints/v6/p5_<X>/`). Serial: same
`python -m run.ga_run <run_id> <hours>`. First lines must show
`RESUMED from .../gen_NNNN.json at gen NNNN`; `Initializing islands...` means no checkpoint
was found (wrong run_id or deleted directory). `hours` counts from the relaunch. Resuming
ignores island specs (constraints and population come from the checkpoint). The island log
is overwritten (`>`) on relaunch and on every respawn: copy it first if you need it.

## 6. Recovering champions from a killed run

```
python3 tools/extract_champions.py p5
```

Reads the newest `output/checkpoints/v6/p5_<A|B|C>/gen_*.json` (the `<run_id>_<X>` layout of
parallel and single-island runs; the repo's own `output/`), writes per island the same
files a finished run writes, `ga_p5_island_<X>.txt` (primary = train best, `best_ever`) and
`ga_p5_island_<X>_train.txt`, plus `ga_p5_island_<X>_val.txt` (validation best). Safe to run
after a finished run (same primary). Train best is the selection rule since 2026-10-15
(p3: train beat val on held-out by +1.0 / +10.6 / +6.0 points). Fixed 2026-11-18: it used to
write the VAL best as the primary file. Serial run_ids (`run1/` without `_X`) are not handled.

## 7. After the run: evaluate

Champions are judged on the 100-team held-out pool, never on GA fitness (2026-11-15 q5:
train 85-90% vs held-out 47-62%). Example (see `evaluation.md` for the full procedure):

```
python -m src.eval output/champions/ga_p5_island_C.txt data/baseline_team.txt \
  --opponents heldout --pilot vgc --opp ladder --seeds 100 200 300 400 500 --concurrency 8
```

Baseline noise floor (2026-10-15): the same team measured 54.8-60.6% across 500-battle
evals, about +-5 points; never trust a single-eval gap under 3 points.

## 8. Milestone logging

After a commit that changes behavior (new module, fixed bug, changed default):
`python3 tools/log_milestone.py "Short title" "One-line summary"`. It appends a dated entry
with the last commit to `docs/history/milestones.md` AND runs `git add` + `git commit` on that
file itself. Skip for docs-only or formatting commits.

## 9. Failure modes during a run

| symptom | cause | fix |
|---|---|---|
| island exits at start with `RuntimeError ... meta-weight usage file` | `data/species_ladder_usage.json` missing | `python tools/build_meta_weights.py` or `GA_META_WEIGHTS=0` |
| `Showdown on :<port> is not answering` | server dead and restart failed | `bash ops/start_server.sh <port>`; check `$SHOWDOWN_DIR` |
| log stale, CPU 100%, ConnectionRefused loop | all servers died (p3, 2026-10-15, ~gen 10) | restart servers; the watchdog only sees log mtime, a traceback loop keeps the log fresh |
| starts at gen 1 although checkpoints exist | wrong run_id (parallel uses `<run_id>_<X>` dirs) | check `output/checkpoints/v6/` |
| many `INVALID` lines | genomes failing `DB.validate_team` (often after migration into a locked island) | expected occasionally; many = check validator / node |
| all battles time out | Showdown overloaded | lower `GA_CONCURRENCY` (try 4) |
| `KeyError: 'round'` warnings | poke_env bug with overridden moves | harmless, battle retried / None |
| WSL killed by Windows reboot | host update | resume (section 5); WSL sleep targets were masked 2026-10-15 |

## Related docs

- [../reference/run-scripts.md](../reference/run-scripts.md) - every run/ and ops/ script, args, env
- [../subsystems/ga.md](../subsystems/ga.md) - engine, invariants, known bugs
- [../subsystems/ga-loop.md](../subsystems/ga-loop.md) - per-gen steps, checkpoint and champion formats
- [showdown.md](showdown.md) - local Showdown servers
- [evaluation.md](evaluation.md) - evaluating champions
- [failure-modes.md](failure-modes.md) - general symptom -> fix table
- [health-check.md](health-check.md) - preflight and health check
