# Quick start: run the GA from zero

A step-by-step guide for anyone who can open a terminal and copy commands. It takes you
from an empty machine to a finished GA run and its result. No Python knowledge needed.
Details for experts are in `ga-run.md`; this guide links there when you want more.

Last verified against code: 2026-11-18. Steps marked (Unverified) could not be run on the
machine this was written on (it has no Showdown); they are the standard commands.

## What the GA does, in plain words

The GA (genetic algorithm) invents Pokemon teams for the VGC Reg M-C format and tests them
by playing thousands of real battles on your own copy of Pokemon Showdown. Each round it
keeps the teams that won most, mixes and changes them, and tries again. At the end it saves
the best team it found as a text file you can paste into Showdown.

Words used below:

| word | meaning |
|---|---|
| server | a local Pokemon Showdown program the battles run on, reached at a "port" (8000, 8001, 8002) |
| island | one population of teams. A and B always keep Umbreon in slot 1 (A also starts from the human baseline team); C is free |
| generation | one round: every team on an island plays its battles, then the island breeds the next teams (about 530 battles per island) |
| run_id | a name you pick for a run, e.g. `may01`. The same name later = continue that run; a new name = start over |
| champion | the best team of an island, written to `output/champions/` when the run ends |
| held-out eval | the final test of a champion against 100 real teams the GA never saw |

## Part 1: one-time setup

You need a Linux terminal. On Windows use WSL2 (this project runs on Fedora 42 under WSL2;
Ubuntu works too, use `apt` where this guide says `dnf`). All commands below are typed in
that Linux terminal.

1. Install the basic tools (Fedora):
   ```
   sudo dnf install -y git python3 nodejs npm curl
   ```
2. Install Pokemon Showdown in your home folder (Unverified on the writing machine):
   ```
   git clone https://github.com/smogon/pokemon-showdown.git ~/pokemon-showdown
   cd ~/pokemon-showdown && npm install
   node pokemon-showdown start 8000 --no-security
   ```
   Wait until it prints that it is listening, then press Ctrl+C to stop it. The first
   start builds the files the project needs. Never edit anything inside this folder.
3. Get the project and install its Python packages:
   ```
   git clone https://github.com/Morgrad/pokeMorgrad.git ~/pokeMorgrad
   cd ~/pokeMorgrad
   python3 -m venv .venv
   source .venv/bin/activate
   pip install torch --index-url https://download.pytorch.org/whl/cpu   # small CPU-only build
   pip install -e ".[dev]"
   ```
   The GA never uses the GPU. The CPU build of torch is enough (the test suite imports it).
   On the GPU workstation a ROCm build is used instead (`environment.md`).
4. Check the project (about 2 minutes). The last line must be `ALL PASS`:
   ```
   bash tools/verify.sh
   ```
5. Check that Showdown knows the format (needs step 2):
   ```
   python -m src.showdown_validator
   ```
   Expect `(True, '')` for the baseline team first. If every team fails or you see an
   error about the format, your Showdown copy is too old or not built: run
   `cd ~/pokemon-showdown && git pull && npm install`, then start it once again.

## Part 2: every time you open a new terminal

```
cd ~/pokeMorgrad
source .venv/bin/activate              # on the original GPU workstation: source ~/venv-pokemorgad/bin/activate
```

Your prompt now starts with `(.venv)` (or `(venv-pokemorgad)`). Every command in this guide
expects that. `bash tools/verify.sh` activates it by itself, so it can pass while your own
terminal still has no venv; `which python` must point inside the venv.
Servers do not survive closing WSL or rebooting Windows; the launchers below start them for
you when needed.

## Part 3: a short test run first

Before a long run, check that battles really work with one island for two generations:

```
bash ops/start_server.sh 8000
SHOWDOWN_PORT=8000 ISLAND_NAME=C GA_GENERATIONS=2 python -m run.ga_island test1 1
```

What you should see: `=== island C | run_id=test1_C | port=8000 ...`, then
`Fitness environment: our pilot=vgc  opponent pilot=ladder ...`, then a line like
`[14:02:11] === GEN 1/2  (0.0 min) ===` followed by one line per team, `>> checkpoint: gen_0001.json`, and finally
`=== DONE ===`. Two generations are about 1000 battles: about 10 minutes on the GPU
workstation (measured 2026-11-18), longer on a slower machine. The result
is `output/champions/ga_test1_C_island_C.txt`. If every team scores 0% or the battles keep
timing out, stop here and see Part 8.

## Part 4: the real run - pick ONE way

| | A. Three servers in parallel | B. One server, one island | C. One server, three islands |
|---|---|---|---|
| good for | long runs on a strong desktop (recommended) | laptops, or to focus on one island | when you want islands to share teams |
| servers | 3 (ports 8000, 8001, 8002), started for you | 1 (port 8000) | 1 (port 8000) |
| battles at once | 3 x 8 = 24 | 8 | 8 |
| islands share teams | no | - | yes, every 5 generations |
| crash recovery | automatic restart from the last generation | relaunch by hand | relaunch by hand |
| champions | `ga_<run_id>_island_A/B/C.txt` | `ga_<run_id>_<X>_island_<X>.txt` | `ga_<run_id>_island_A/B/C.txt` |

The number after the run_id is the time budget in hours. When it runs out, the run finishes
its current generation and writes the champions.

### A. Three servers in parallel (recommended)

```
nohup bash run/ga_parallel.sh 4 may01 > /tmp/ga_may01_launch.log 2>&1 &
```

This starts the three servers if they are not running, then islands A, B and C (one per
server), each with a watchdog that restarts an island that stops writing to its log.
Logs: `/tmp/ga_may01_A.log`, `_B.log`, `_C.log`. WARNING: it first stops any other island
that is already running on this machine, so never start two parallel runs at once.

### B. One server, one island

```
bash ops/start_server.sh 8000
SHOWDOWN_PORT=8000 ISLAND_NAME=A GA_CONCURRENCY=8 nohup python -m run.ga_island may01 4 > /tmp/ga_may01_A.log 2>&1 &
```

Use `ISLAND_NAME=A`, `B` or `C` (see the word table). Use another free port and its own
server if you want a second island on another port at the same time (`8001`, `8002`).

### C. One server, three islands that share teams

```
bash ops/start_server.sh 8000
GA_CONCURRENCY=8 nohup python -m run.ga_run may01 4 > /tmp/ga_may01.log 2>&1 &
```

Each team plays all 118 training opponents (options A and B play 50), so a generation is
slower. Avoid
the run_ids `run1`, `run2`, `run3` unless you know why: they have special seeds and warm
starts (`ga-run.md` section 2).

### While it runs

- Keep the WSL terminal open and do not let Windows sleep or install updates and reboot
  (an update reboot has killed overnight runs before). If it happens, just resume (Part 6).
- Do not run anything else against the same server ports during the run: two workloads on
  one server slow each other down a lot.

## Part 5: watching a run

```
tail -f /tmp/ga_may01_A.log          # live log of island A (Ctrl+C stops watching, not the run)
grep "NEW ALL-TIME" /tmp/ga_may01_*.log | tail     # every time an island found a better team
ls output/checkpoints/v6/            # one folder per island; a new gen_NNNN.json each generation
```

A summary line looks like `[A] gen 12: best= 48.2%  all-time= 61.3%  stag=2  uniq=21`:
best team this generation, best team so far, generations without improvement, number of
different species on the island. These percentages are against the training teams and are
always higher than the held-out score in Part 7. `[showdown] restarting` every 10
generations is normal. Many `battle error` lines are not (Part 8).

## Part 6: stopping and resuming

Stop a parallel run (stop the launcher first, or it restarts the islands):
```
pkill -f "run/ga_parallel.sh"; pkill -f "tools/watch_islands.py"; pkill -9 -f "run.ga_island"
```
Stop a B or C run: `pkill -9 -f "run.ga_island"` or `pkill -9 -f "run.ga_run"`.

Stopping loses only the generation in progress; every finished generation is saved. To
continue, run the SAME command with the SAME run_id (the hours count from the restart). The
log must show `RESUMED from ... at gen N`; `Initializing islands...` means it did not find the
run (check the run_id). Logs in `/tmp` are overwritten on resume: copy them first if needed.

## Part 7: the result

When a run ends normally, the champions are in `output/champions/`. If you stopped it early,
write them from the saved generations (options A and B; it writes
`ga_<run_id>_island_<X>.txt` plus `_train` and `_val` versions):
```
python tools/extract_champions.py may01
```
Each `.txt` file is a Showdown team: open it and paste it into Showdown's teambuilder.

Then measure it the honest way, against the 100 held-out teams, next to the human baseline
team (this plays 1000 battles; nothing else should use port 8000 meanwhile):
```
bash ops/start_server.sh 8000
python -m src.eval output/champions/ga_may01_island_A.txt data/baseline_team.txt \
  --opponents heldout --pilot vgc --opp ladder --seeds 100 200 300 400 500 --concurrency 8
```
It prints a win rate with a 95% range for each team. Differences under about 3 points are
noise. Always pass `--pilot vgc` (the default also loads the experimental BC pilot).

## Part 8: if something goes wrong

| what you see | what to do |
|---|---|
| `verify.sh` does not end with `ALL PASS` | the setup is incomplete; read the first `FAILED:` or error line |
| `ModuleNotFoundError: No module named 'poke_env'` (or `torch`, `numpy`) | the venv is not active in this terminal: run the `source` line of Part 2 |
| `Showdown on :8000 is not answering` | `bash ops/start_server.sh 8000`; check that `~/pokemon-showdown` exists and was built |
| every battle times out, all scores 0% | the server is down or overloaded: restart it, or use `GA_CONCURRENCY=4` |
| tracebacks ending in `KeyError: 'round'` and `Task exception was never retrieved` | a known poke_env bug with the move Round; that battle times out and is replayed. Harmless, ignore |
| many `battle error #N` lines | a program error inside battles; the first 3 of each kind show the details; send them to the maintainer |
| run starts at generation 1 although you meant to resume | wrong run_id; `ls output/checkpoints/v6/` shows the existing ones |
| `RuntimeError ... meta-weight usage file` | `python tools/build_meta_weights.py` |
| machine very slow during a parallel run | use option B (one island) or lower `GA_CONCURRENCY` |

More symptoms: `failure-modes.md`. Starting a long run on a shared machine: ask whoever
owns it first (runs take hours and use all CPU cores).

## Related docs

- [ga-run.md](ga-run.md) - the same procedures in full detail (logs, recovery, overnight chain)
- [showdown.md](showdown.md) - Showdown servers and ports
- [evaluation.md](evaluation.md) - evaluating champions, paired comparisons
- [environment.md](environment.md) - host setup, GPU, venvs
- [failure-modes.md](failure-modes.md) - symptom -> fix table
- [../reference/run-scripts.md](../reference/run-scripts.md) - every launcher argument and env var
