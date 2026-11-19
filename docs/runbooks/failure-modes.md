# Failure modes: symptom -> cause -> fix

Lookup table of every known failure in this project: what you see, why it happens, and what
to do. Covers Showdown, GA runs, the verify gate, preflight, environment, and known noise.
Read it when something fails; search it for the exact error text.

Last verified against code: 2026-11-18

Key facts: battles need a local Showdown server (port 8000; 8001/8002 for parallel islands).
A hung battle returns `None` after 20 s (not a loss) and is retried once. The GA restarts its
Showdown every 10 generations (`src/showdown_server.py::restart`). Commands assume the repo root
and an active venv.

## Showdown and battles

| Symptom | Cause | Fix |
|---|---|---|
| Eval or GA hangs, no output, low CPU | Showdown down; every battle waits for the 20 s timeout plus one retry | `curl -s localhost:8000` per port; restart with `bash ops/start_server.sh <port>` (see `showdown.md`) |
| Islands at 100% CPU, logs full of `ConnectionRefused` (2026-10-15, run p3: all 3 servers died around gen 10) | Showdown servers died mid-run; the GA only restarts them every 10 gens | Restart the ports by hand; the island recovers. Prevention used then: WSL sleep targets masked on the workstation (Unverified: exact command) |
| `RuntimeError: Showdown on :800X is not answering and could not be restarted` at island start | `src/showdown_server.py::ensure` failed: no checkout at `$SHOWDOWN_DIR`, `node` missing, or port busy | Check `ls ~/pokemon-showdown`, `node --version`, `/tmp/showdown_<port>.log`; `run/ga_parallel.sh` keeps respawning the island every 5 s until its time budget ends, so fix or stop it |
| `RuntimeError: Showdown on :800X did not come back after a restart` mid-run | 10-gen restart failed twice (60 s each) | Same as above; the island exits and is respawned from its checkpoint |
| Server takes > 30 s to answer, battles slow after hours | Node server leaks memory / sockets over thousands of battles | Restart it; the GA does this every 10 gens, `tools/paired_run.sh` every `CHUNK` matchups |
| Eval very slow while a GA runs | Two workloads on one server (about 10x slowdown) | Never share a port with a GA island; stop the GA (`ga-run.md`) or use a free port |
| All battles time out | Server overwhelmed | Lower concurrency (`GA_CONCURRENCY=4`, `--concurrency 4`); 8 is the ceiling per server |
| `ValidatorError: node .../showdown_validate.js exit code ...` (GA island exits at startup or breeding) | No built Showdown checkout (or node crashed / timed out); the message ends with node's stderr | Install / build `~/pokemon-showdown` or set `SHOWDOWN_DIR`; test with `python -m src.showdown_validator`. (Before 2026-11-18 this silently marked every team illegal.) |
| `[Invalid choice] Can't move: X needs a target` | Random genome contained a `randomNormal` move (Outrage, Thrash, Uproar) | Fixed: excluded in `src/ga/genome.py::_random_mon` and `src/ga/operators.py::mutate_move`. Opponent pool teams can still contain Outrage (STATE 5.19); stripping them at `src/ga/pools.py::_load_teams` was proposed, not implemented |
| Many dropped battles (low `valid_n`), no obvious cause | A pilot or player raises on some decision; the battle returns None | Since 2026-11-18 logged: `grep -c "battle error" /tmp/ga_<run>_<X>.log`, the first 3 per exception type carry a traceback (`src/battle_runner.py::_report_battle_error`). Timeouts are not logged |
| `[Invalid choice] Can't switch: ... can only switch in once` | BC pilot sent both slots to the same bench mon | Fixed: switch-collision handling in `src/bc_player.py::BCPlayer.choose_move` |
| `Greninja (Greninja-Bond) does not exist in Gen 9` | Illegal form in a genome | Fixed: legality gate (`filter_legal_genomes`) |
| `KeyError: 'round'` in poke_env `parse_message` | poke_env does not parse the Round chain message | fixed 2026-11-18 by `src/poke_env_fixes.py` (the battle used to hang until its timeout and be replayed). Still seeing it means an old checkout: `git pull` |
| poke_env CRITICAL "cannot reject open team sheets" / "already made your decision about agreeing to open team sheets" | Benign protocol noise | Filtered by `_DropVGCNoise` in `src/player_factory.py` (and a copy in `src/battle_runner.py`) |
| Battles of 60+ turns, GA generation takes about 1 hour | Pilot overused Protect / switch | Fixed in commit `7f72853`: `PASSIVE_COST` 0.15 -> 0.30 and our `vgc` pilot forfeits after turn 50 (`src/player_factory.py::TimeoutPlayer`, counts as a loss) |

## GA runs

| Symptom | Cause | Fix |
|---|---|---|
| Checkpoint exists but the run starts at gen 1 | Different run_id, or wrong dir | Parallel checkpoints are `output/checkpoints/v6/<run_id>_A/` (and `_B`, `_C`); relaunch with the SAME run_id to resume (look for `RESUMED from` in the log) |
| run1 / run2 checkpoints gone | `run/ga_overnight.sh` (and `preflight.py --launch`) `rm -rf` them at start by design | Use the parallel launcher or a fresh run_id; extract champions first if needed |
| Island hung 15 min but watchdog did nothing (2026-10-15) | `tools/watch_islands.py` only checks log mtime; a traceback loop keeps the log fresh | `tail -50 /tmp/ga_<run_id>_<X>.log`; `pkill -9 -f "run.ga_island"` for that island only by PID (`pgrep -af run.ga_island`) |
| Run killed before champions were written | Crash, kill, reboot | `python3 tools/extract_champions.py <run_id>` |
| Windows Update / reboot killed WSL | OS restart | Restart Showdown, relaunch with the same run_id (checkpoints survive; `/tmp` logs do not) |
| `RuntimeError: meta-weight usage file ... unreadable` | `data/species_ladder_usage.json` missing / bad with `GA_META_WEIGHTS=1` | `python tools/build_meta_weights.py`, or `GA_META_WEIGHTS=0` (scores then not comparable) |
| `RuntimeError: training pool is empty` / `WARNING: ... teams failed to load` | `data/regional_teams/` missing or `pool_split.json` names do not match | Count the files in `data/regional_teams/` and check `data/pool_split.json` (148 train / 100 holdout on 2026-11-18) |
| Scores do not match older runs | Fitness environment changed: `vgc` pilot vs `ladder` opponent, meta-weighted (2026-10-16); ordering fix for >50 opponents (2026-11-18, affects `run/ga_run.py`) | Compare only runs with the same settings; re-evaluate both teams with `python -m src.eval` on the holdout |
| Two evals of the same team differ by 5 points | Binomial noise: 100 battles +-5 pts, 500 battles +-2.2 pts (STATE 5.8) | Use >= 5 seeds; overlapping Wilson CIs mean "no difference" |
| `ERROR: ISLAND_NAME must be A, B, or C` | Bad env value | Set `ISLAND_NAME` to A, B or C |

## Gate, tests, preflight

| Symptom | Cause | Fix |
|---|---|---|
| `verify.sh` ends `FAILED: tests/<file>.py` | That test file failed; the gate stops there (since 2026-11-18; before, a mid-chain failure was skipped and `ALL PASS` still printed) | Read the FAIL lines above it; fix the test or roll back |
| Real-replay tests in `tests/test_battle_memory.py` print PASS instantly | `data/showdown_replays/` (gitignored) is missing on this host, so all 5 skip (the OTS one got its guard 2026-11-18) | Copy the replays from the workstation to exercise them |
| `FAIL test_ga_matches_golden` with a JSON diff | GA output changed | If not intended, fix the code. If intended: `PYTHONHASHSEED=0 python tests/golden/ga_harness.py --write`, and say so in the commit |
| Harness exits `run with PYTHONHASHSEED=0` | Ran the harness directly without the variable | Prefix `PYTHONHASHSEED=0` |
| `AUDIT FAILED: N problem(s)` and `FAIL <msg>` lines | A hard audit check failed (exit 1 since 2026-11-18; before, the audit never failed the gate) | Investigate the named check: DB, regional teams, genome fuzz, lock, baseline |
| ruff errors in verify | Lint | `ruff check --fix <files>`; never commit with ruff errors |
| Preflight `[FAIL] torch CUDA available` | CPU-only torch wheel (e.g. `torch 2.15.0+cpu` in the laptop `.venv`), ROCm not loaded, or a fresh shell without the venv | `python -c "import torch; print(torch.__version__, torch.cuda.is_available())"`; on the GPU workstation use the ROCm venv. The GA does not need the GPU |
| Preflight `[FAIL] GA_CONCURRENCY set` | Unset or 3 | `GA_CONCURRENCY=8 python3 tools/preflight.py` |
| Preflight `[FAIL] src/ and run/ committed` | Unstaged changes | Commit (with approval) or stash before a long run |
| Preflight `[FAIL] src/ga: <name>` | Constraint / early-stop code removed or renamed | Restore it, or update the check list in `tools/preflight.py` deliberately |

## Environment

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'src'` | Not in the repo root, or running a tool without a `sys.path` bootstrap; the project is not pip-installed in this venv | `cd ~/pokeMorgrad`; use `python -m ...`, or `PYTHONPATH=. python tools/<tool>.py`, or once `pip install -e .` |
| `ModuleNotFoundError: poke_env` / `torch` | venv not active | `source .venv/bin/activate` (or `~/venv-pokemorgad/bin/activate`) |
| `ModuleNotFoundError: bs4` / `openpyxl` | Scrape extra not installed | `pip install beautifulsoup4 openpyxl` (declared as extra `scrape`) |
| `bash: python: command not found` | Outside the venv | Activate the venv or use `python3` |
| `run/ga_parallel.sh`: `~/venv-pokemorgad/bin/activate: No such file or directory` | Neither the repo `.venv` nor `~/venv-pokemorgad` exists (the scripts try `.venv` first since 2026-11-18) | Create the venv: `python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"` |
| `FileNotFoundError ... bc_best.pt` | `output/` and `*.pt` are gitignored; no model on this host | Copy the model from the workstation / a backup; it cannot be restored from git |
| `RuntimeError: POKEMORGRAD_ROOT=... does not look like the repo` | Env var points at a dir without `data/` | Unset it or fix the path |
| `agent.cpp:608] sysfs nodes path '/sys/class/kfd/kfd/topology/nodes' does not exist` | ROCm probing under WSL2 | Harmless, ignore |
| Pasted script truncated / mangled file | Windows Terminal multi-line paste limit (about 5 KiB) | See `environment.md` (paste-limit workaround) |
| `assert old_x in s` from a patch script | File already modified by an earlier patch | `git diff`, restore from git if needed; do not re-run patch scripts blindly |
| BC training OOM or very slow while a local LLM runs | The LLM holds most of the 24 GB VRAM | Do not train BC while the LLM is loaded (`environment.md`) |

## Related docs

- [health-check.md](health-check.md) - first checks, preflight, verify gate
- [showdown.md](showdown.md) - server management and restart logic
- [diagnostics.md](diagnostics.md) - log greps and cleanup
- [ga-run.md](ga-run.md) - launch, stop, resume
- [environment.md](environment.md) - host, ROCm, venvs, paste limit
- [../reference/tests.md](../reference/tests.md) - gate details, golden test
