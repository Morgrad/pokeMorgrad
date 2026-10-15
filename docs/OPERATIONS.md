# Operations runbook

Copy-paste commands for running, monitoring, resuming, and stopping every
service in this project. Written to be usable with a hung terminal at 2 AM.

Related docs:
- `STATE.md` — current status and roadmap
- `STATE_history.md` — chronological log of what changed and why
- `GLOSSARY.md` — terms and acronyms

Every long-running process depends on the Showdown server on :8000. When
Showdown is down, the failure mode is silent: battle attempts hang for a
20s timeout plus one retry, so a 2000-battle eval can sit idle for 20+
minutes without any error. Always check Showdown first.

---

## 0. Health check (run this first, always)

    cd ~/project
    source ~/llm-env/bin/activate

    echo "=== Showdown ==="
    curl -s http://localhost:8000 > /dev/null && echo "UP" || echo "DOWN"
    pgrep -f "pokemon-showdown start" > /dev/null && echo "process OK" || echo "process MISSING"

    echo "=== Processes ==="
    ps aux | grep -E "ga_run|src.eval|bc_train|pokemon-showdown" | grep -v grep

    echo "=== Recent artifacts ==="
    ls -lat output/champions/ | head -6
    ls -lat output/checkpoints/v6/run1/ 2>/dev/null | head -3
    ls -lat output/checkpoints/v6/run2/ 2>/dev/null | head -3

    echo "=== Disk ==="
    df -h ~/project | tail -1

Healthy output for a running GA: Showdown UP, `python -m run.ga_run run{1,2}`
in the process list at high CPU, `bash run/ga_overnight.sh` present, checkpoints
written within the last few minutes.

Red flags:
- Showdown DOWN but GA process alive — GA is hung. Kill GA, restart Showdown,
  resume.
- GA alive, CPU below 10% — same. Check log freshness (see §4).
- No checkpoints newer than 15 minutes — stuck.
- No `node pokemon-showdown start` process — Showdown is dead.

---

## 1. Pre-flight

Before any overnight run:

    cd ~/project
    source ~/llm-env/bin/activate
    GA_CONCURRENCY=8 python3 tools/preflight.py

Runs ten checks in about two seconds:
1. Showdown reachable on :8000
2. Showdown process alive
3. Required data files present
4. src/ and run/ have no uncommitted changes
5. Constraint functions present in ga_core (silent-removal guard)
6. Island spec configured in run/ga_run.py
7. Torch CUDA available
8. output/champions writable
9. Disk free above 5 GB
10. GA_CONCURRENCY set to a non-default value

Pass to launch. Fail means fix first. Use `--launch` to start the overnight
chain only if all checks pass:

    GA_CONCURRENCY=8 python3 tools/preflight.py --launch

---

## 2. Showdown

Start or restart:

    pkill -9 -f "pokemon-showdown start"
    sleep 1
    cd ~/pokemon-showdown
    nohup node pokemon-showdown start 8000 --no-security > /tmp/showdown.log 2>&1 &
    echo "Showdown PID $!"
    sleep 8
    curl -s http://localhost:8000 > /dev/null && echo "UP" || (echo "FAILED"; tail -20 /tmp/showdown.log)

Stop:

    pkill -9 -f "pokemon-showdown"

When to restart:
- Before any overnight run (unless `run/ga_overnight.sh` is launching, which
  handles it)
- After a WSL restart or Windows reboot
- If battles start timing out en masse (more than 20% of a generation)
- Every ten generations during a long GA (handled automatically by
  `showdown_restart_every=10`)

---

## 3. Launching a GA run

### Option A — overnight chain (recommended for runs above one hour)

Runs `run1` (5.5h) → `run2` (5.5h, warm-start) → final eval → done marker.
Handles Showdown startup, watchdog, and cleanup.

    cd ~/project
    source ~/llm-env/bin/activate
    GA_CONCURRENCY=8 nohup bash run/ga_overnight.sh > /tmp/ga_overnight_launch.log 2>&1 &
    echo "PID $!"
    sleep 60
    tail -15 /tmp/ga_run1.log

Or via preflight (safer, runs checks first):

    GA_CONCURRENCY=8 python3 tools/preflight.py --launch

Logs written:
- `/tmp/ga_overnight_launch.log` — orchestrator
- `/tmp/ga_run1.log`, `/tmp/ga_run2.log` — per-run (via `tee`)
- `/tmp/ga_final_eval.log` — final scores
- `/tmp/ga_overnight_done_<stamp>` — completion marker

### Option B — direct launch (short runs, tests)

Requires Showdown to already be up. Does not chain to eval.

    curl -s http://localhost:8000 > /dev/null || (cd ~/pokemon-showdown && nohup node pokemon-showdown start 8000 --no-security > /tmp/showdown.log 2>&1 & sleep 8)

    cd ~/project
    source ~/llm-env/bin/activate
    GA_CONCURRENCY=8 nohup python -m run.ga_run run2 5.5 > /tmp/ga_run2.log 2>&1 &
    echo "PID $!"
    sleep 30
    tail -15 /tmp/ga_run2.log

### Resuming a crashed run

Checkpoints are saved every generation. Relaunching with the same `run_id`
resumes from the latest checkpoint automatically.

    cd ~/project
    source ~/llm-env/bin/activate
    GA_CONCURRENCY=8 nohup python -m run.ga_run run2 5.5 > /tmp/ga_run2.log 2>&1 &
    sleep 20
    head -5 /tmp/ga_run2.log

Look for `RESUMED from .../gen_NNNN.json at gen NNNN` in the first lines.

---

## 4. Monitoring a GA

Per-generation progress:

    # All-time-best trajectory (all runs)
    grep "NEW ALL-TIME" /tmp/ga_run*.log | tail -30

    # Generation summaries
    grep -E "gen [0-9]+:" /tmp/ga_run1.log | tail -10

    # Live tail (Ctrl+C exits, does not kill the run)
    tail -f /tmp/ga_run1.log

Early-stop signal (proof the throughput optimization is active):

    grep -c "early-abort" /tmp/ga_run1.log

Roughly 40 to 90 percent of random genomes should be aborted each generation.

Champions (updated on every new all-time best):

    ls -lat output/champions/ga_run*_island_*.txt
    head -20 output/champions/ga_run1_island_A.txt

Checkpoints:

    ls output/checkpoints/v6/run1/ | wc -l
    ls -lat output/checkpoints/v6/run1/ | head -3

Log freshness check (is it stuck?):

    stat -c '%y' /tmp/ga_run1.log
    date

If the log timestamp is more than 5 minutes old and CPU is below 10 percent,
the run is stuck.

Process tree for a healthy overnight:

    ps aux | grep -E "ga_run run1|ga_overnight|watchdog" | grep -v grep

Should show three processes: the orchestrator, the run, and the watchdog
subshell.

---

## 5. Stopping a GA

Order matters. Killing the orchestrator first leaves the run and watchdog
orphaned.

    # Graceful stop (writes a final checkpoint if SIGTERM lands mid-gen)
    pkill -TERM -f "ga_run"
    sleep 3

    # Force if still alive after 3s
    pkill -9 -f "ga_run"

    # Then the orchestrator and watchdog
    pkill -9 -f "ga_overnight"
    pkill -9 -f "watchdog"

    # Optional: free Showdown RAM
    pkill -9 -f "pokemon-showdown"

    # Confirm everything is gone
    ps aux | grep -E "ga_run|ga_overnight|watchdog|pokemon-showdown" | grep -v grep || echo "clean"

Checkpoints survive a `kill -9`. Resume from §3.

---

## 6. Evaluating teams

Never run eval while a GA is running. Both use Showdown on :8000; concurrent
loads throttle each other by an order of magnitude. Stop the GA first (§5),
run eval, then resume (§3).

Basic eval (heuristic pilot, 5 seeds, held-out pool):

    cd ~/project
    source ~/llm-env/bin/activate
    python3 -m src.eval \
        output/champions/ga_run1_island_A.txt \
        output/champions/ga_run1_island_B.txt \
        output/champions/ga_run1_island_C.txt \
        data/baseline_team.txt \
        --seeds 100 200 300 400 500 \
        --concurrency 8

Args:
- `--pilot heuristic` (default) — fast, no torch
- `--pilot bc` — neural pilot, slower, uses GPU
- `--pilot both` — side-by-side delta table
- `--opponents all` — use the 300-team training pool (not recommended for
  scoring)
- `--opponents heldout` (default) — the 100-team test pool
- `--seeds N N N` — RNG seeds, one 100-battle pass each
- `--concurrency N` — concurrent battles; overrides GA_CONCURRENCY

Against a specific checkpoint as the pilot:

    BC_PILOT_PATH=output/models/bc_heuristic_v1c.pt \
        python3 -m src.eval --pilot bc data/baseline_team.txt \
        --seeds 100 200 300 --concurrency 8

Interpreting the output:

    ga_run1_island_A.txt   331/ 500 = 66.2%  95% CI [61.9-70.2]
    baseline_team.txt      282/ 500 = 56.4%  95% CI [52.0-60.7]

Wilson CIs are printed alongside every score. Two CIs that overlap cannot
distinguish their underlying rates at 95% confidence. See STATE §5.8 for the
noise floor: single-seed 100-battle runs vary by ±5 points; 500-battle runs
by ±2.2. Always run at least five seeds for decisions.

---

## 7. Training BC

Train the neural pilot on a dataset:

    cd ~/project
    source ~/llm-env/bin/activate
    BC_DATA=data/training_data.jsonl \
    BC_OUT=bc_new.pt \
    BC_EPOCHS=40 \
    BC_PATIENCE=6 \
        python3 -m src.bc_train

Environment variables:
- `BC_DATA` — input JSONL (default `data/training_data.jsonl`)
- `BC_OUT` — output checkpoint under `output/models/` (default `bc_best.pt`)
- `BC_EPOCHS` — maximum epochs (default 30)
- `BC_PATIENCE` — early-stop after N epochs without val_move_acc improvement
- `BC_MODEL` — `v2` (default, MLP) or `v3` (transformer)
- `BC_BATCH` — batch size (default 256; 512 and 1024 reduce epochs but lose
  move accuracy on this model, verified 2026-10-13)

Checkpoints save on the epoch with the best `val_move_acc`, not best
`val_loss` (see STATE §5.12).

The trainer does a battle-level train/val split, not row-level. Row-level
shuffling leaks rows from the same battle into both splits and inflates
val_move_acc by roughly 20 points.

---

## 8. Data pipeline

Rebuild canonical DB from Showdown:

    node tools/build_regmc_db.js

Requires Showdown running and SHOWDOWN_DIR set (defaults to
`~/pokemon-showdown`).

Scrape human replays from Limitless:

    python3 tools/scrape_replays.py              # default 1600 rating, 200 pages
    python3 tools/scrape_replays.py 1500 300     # custom floor, pages

Resumes from the last indexed replay. Writes JSON files to
`data/showdown_replays/`.

Parse replays into training rows:

    python3 tools/build_training_data.py

Reads `data/showdown_replays/*.json`, runs each through `replay_tracker.Tracker`,
tags each row with `side_won`, `target_a`, `target_b`, writes
`data/training_data.jsonl`.

Generate heuristic-imitation data (for the BC-on-heuristic pilot):

    python3 tools/generate_heuristic_dataset.py --battles 5000 \
        --out data/training_data_heuristic.jsonl

Runs N heuristic-vs-regional battles, records every heuristic decision as a
training row. Battle-level split is applied at train time, not generation time.

Rebuild species move priors:

    python3 tools/build_species_priors.py

Reads `data/showdown_replays/`, writes `data/species_move_priors.json`.

---

## 9. Diagnostics

BC vs heuristic decision comparison (used to find the loop bug and target
scoring bug):

    cd ~/project
    source ~/llm-env/bin/activate
    BC_PILOT_PATH=output/models/bc_heuristic_v1c.pt \
        python3 tools/bc_diagnostic.py 15

Runs 15 battles with the BC pilot and a shadow heuristic on the same battle
object. Prints agreement rate bucketed by turn number and by our lowest-HP.
Writes the full log to `/tmp/bc_diag.jsonl`. Analyze the log with:

    python3 -c "
    import json
    def parse(msg):
        if not msg: return None
        parts = msg.replace('/choose ', '').split(', ')
        out = []
        for p in parts:
            p = p.strip()
            if p in ('pass', 'default'): out.append(('pass', None, None)); continue
            t = p.split()
            if len(t) >= 2:
                out.append((t[0], t[1], t[2] if len(t) > 2 else None))
        return out
    tot = {'agree': 0, 'target_only': 0, 'action': 0, 'structural': 0}
    with open('/tmp/bc_diag.jsonl') as f:
        for line in f:
            d = json.loads(line)
            b, h = parse(d['bc']), parse(d['heur'])
            if not b or not h: tot['structural'] += 1; continue
            if b == h: tot['agree'] += 1; continue
            if len(b) == len(h) and all(x[0] == y[0] and x[1] == y[1] for x, y in zip(b, h)):
                tot['target_only'] += 1
            else:
                tot['action'] += 1
    print(tot)
    "

Repo-wide audit:

    python3 -m src.audit_before_launch

Checks DB integrity, name sanity, mega stone integrity, pool load, fuzz
tests on genome build/mutate/crossover.

Encoder state snapshot (verify encoder changes are bit-identical):

    python3 tools/encode_snapshot.py capture --out /tmp/enc_before.pt
    # ... apply encoder change ...
    python3 tools/encode_snapshot.py capture --out /tmp/enc_after.pt
    # then compare: torch.equal on each tensor

---

## 10. Cleanup

Prune superseded model checkpoints (deletes the file, keeps the current best):

    # List all models by size and date
    ls -lat output/models/*.pt

    # Delete specific superseded checkpoints
    rm output/models/bc_heuristic_v2.pt
    rm output/models/bc_v3_5m.pt

Archive smoke-test champions:

    mkdir -p output/champions/_smoke_archive
    mv output/champions/ga_*_island_T.txt output/champions/_smoke_archive/

Prune checkpoints to the latest 3 plus multiples of 5:

    cd output/checkpoints/v6/run1
    ls -1t gen_*.json | tail -n +4 | grep -vE "gen_00[0-9]?5\.json" | xargs -r rm

(Not for the faint of heart; save_checkpoint already prunes automatically.)

Clear /tmp GA logs:

    rm -f /tmp/ga_run*.log /tmp/ga_overnight*.log /tmp/ga_final_eval.log \
          /tmp/bc_*.log /tmp/showdown*.log

Remove Python bytecode:

    find . -name "__pycache__" -type d -not -path "./.git/*" -exec rm -rf {} +

Zone.Identifier files (Windows metadata):

    find . -name "*:Zone.Identifier" -delete 2>/dev/null

---

## 11. Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Eval or GA hangs with no output, low CPU | Showdown down | Restart Showdown (§2) |
| Eval slow while GA running | Showdown contention | Stop GA (§5), run eval, resume |
| `[Invalid choice] Can't move: X needs a target` | Random genome contains a `randomNormal` move | Fixed 2026-10-13 (excluded in `_random_mon`) |
| `[Invalid choice] Can't switch: ... can only switch in once` | Double-same-species switch from BC pilot | Fixed 2026-10-14 in `bc_player.choose_move` collision handler |
| `KeyError: 'round'` in poke_env | Round chain mechanic not parsed | Harmless, battle returns None |
| `Greninja (Greninja-Bond) does not exist in Gen 9` | Illegal form in genome | Fixed 2026-10-14 (legality gate in generator) |
| `ModuleNotFoundError: src.*` | Not in repo root, or venv not active | `cd ~/project && source ~/llm-env/bin/activate` |
| `ModuleNotFoundError: poke_env` | venv not active | Same |
| `FileNotFoundError: bc_best.pt` | Model missing or moved | `ls output/models/`; restore from git or backup |
| GA checkpoint exists but starts at gen 1 | Wrong run_id, or checkpoint dir mismatch | Check `output/checkpoints/v6/<run_id>/` matches `run/ga_run.py` args |
| Windows Update reboot killed WSL | OS scheduled update | Resume from checkpoint (§3) |
| All battles time out | Showdown overwhelmed | Lower GA_CONCURRENCY (try 4) |
| `torch.cuda.is_available() == False` | ROCm not loaded, or GPU busy | Check `rocm-smi` (if available), rerun in fresh shell |
| `assert old_x in s` from a patch script | File was already modified by a prior patch | Check `git diff`, restore from git if needed |

---

## 12. Useful one-liners

Is anything running:

    pgrep -af "ga_run|src.eval|bc_train|pokemon-showdown"

Showdown health:

    curl -s http://localhost:8000 > /dev/null && echo UP || echo DOWN

Latest champion per island:

    for r in 1 2; do for i in A B C; do
      f=output/champions/ga_run${r}_island_${i}.txt
      [ -f "$f" ] && echo "$f: $(head -1 $f)"
    done; done

Count early-aborts:

    grep -c "early-abort" /tmp/ga_run*.log

All-time-best trajectory in one screen:

    grep "NEW ALL-TIME" /tmp/ga_run*.log | awk '{print $1, $NF}'

Copy a champion into the working baseline for the next run:

    cp output/champions/ga_run1_island_A.txt data/baseline_team.txt

Restart Showdown and clear state:

    pkill -9 -f pokemon-showdown; sleep 1; cd ~/pokemon-showdown && nohup node pokemon-showdown start 8000 --no-security > /tmp/showdown.log 2>&1 & sleep 8

Stop everything cleanly:

    pkill -TERM -f "ga_run"; sleep 3; pkill -9 -f "ga_run|ga_overnight|watchdog"; echo done

---

## 13. Policy

Before launching any run longer than one hour:

1. Ask: is the PC needed for other work during this window? If yes, defer
   to a period when it is idle.
2. Run `tools/preflight.py` and confirm all checks pass.
3. Set `GA_CONCURRENCY=8` explicitly (default is 3).
4. Launch through `run/ga_overnight.sh` or `--launch` from preflight, not by
   direct `run.ga_run` invocation. Direct invocation does not start Showdown
   or chain to eval.

Never run eval while a GA is running. Never launch a second GA while one is
already running on the same Showdown instance.

Never commit to `main` from a script you have not read. Patch scripts get
mangled easily; use a saveable file and read the diff before applying.

Never modify `src/` in the hour before a long run.

---

## 14. Environment

| Item | Value |
|---|---|
| Host | Windows 11, WSL2 (Fedora 42) |
| GPU | AMD 7900 XTX (ROCm 7.2) |
| Torch | 2.14.1+rocm7.2 |
| Python | 3.12 |
| Venv | `~/llm-env` |
| Repo root | `~/project` on PC, `~/pokeMorgrad` on the laptop |
| Showdown | `~/pokemon-showdown`, port 8000 |
| Default GA concurrency | 3 (override to 8 with `GA_CONCURRENCY=8`) |
| Model | `output/models/bc_best.pt` |
| Champions | `output/champions/ga_<run>_island_<X>.txt` |
| Checkpoints | `output/checkpoints/v6/run{1,2}/gen_NNNN.json` |

ROCm environment variables live in `~/llm-env/bin/activate`:

    GPU_MAX_HEAP_SIZE=100
    GPU_MAX_ALLOC_PERCENT=100
    HSA_ENABLE_SDMA=0
    MIOPEN_FIND_MODE=2
    MIOPEN_FIND_ENFORCE=3

`python` may not exist outside the venv. Always `source ~/llm-env/bin/activate`
first, or use `python3` explicitly.

Harmless warning, ignore: `agent.cpp:608] sysfs nodes path
'/sys/class/kfd/kfd/topology/nodes' does not exist` — ROCm probing WSL2.

---

## 15. Paste limit workaround

Windows Terminal refuses multi-line pastes over 5 KiB by default. The paste
is silently truncated, which has caused several mangled files in this project.
Two fixes:

Edit Windows Terminal User Settings JSON (top level, not inside profiles):

    "multiLinePasteWarning": false,
    "largePasteWarning": false,
    "warning.multiLinePaste": false,
    "warning.largePaste": false,

Close every Windows Terminal window (not just the tab) for the change to take
effect. If the warning still appears — some WSL relays enforce their own
limit — use the file pattern:

1. In VS Code, Ctrl+N for a new file
2. Paste the script content (editor has no size limit)
3. Save as `~/project/apply_X.py` with `.py` extension
4. In the terminal: `cd ~/project && python3 apply_X.py`
5. Verify, then `rm apply_X.py`

---

## 16. Daily and weekly patterns
---

## 17. Parallel GA (2026-10-14 onwards)

Three islands, three processes, three Showdown instances
(8000/8001/8002). 2.78x throughput vs the serial single-process GA.
Preferred for any run above one hour. See STATE.md §5.18.

### Prerequisites

- `run/ga_parallel.sh` (executable) — orchestrates the three processes
- `run/ga_island.py` — single-island entry point
- Showdown instances on 8000, 8001, 8002 (script starts any missing)
- `SHOWDOWN_PORT` routing patched in `src/battle.py` + `src/ga_core.py`

### Launch

    cd ~/project && source ~/llm-env/bin/activate
    pkill -9 -f "run.ga_island" 2>/dev/null; sleep 1
    nohup bash run/ga_parallel.sh 2.5 p2 > /tmp/ga_p2_launch.log 2>&1 &
    echo "launch PID $!"
    sleep 60
    tail -20 /tmp/ga_p2_launch.log

Args: `<hours> <run_id>`. Use a fresh run_id each launch (p1, p2, p3…)
so checkpoints and champions don't clobber.

### Monitoring

    ps aux | grep -E "ga_island|pokemon-showdown start" | grep -v grep
    # expect 6 processes: 3x python -m run.ga_island + 3x node

    for n in A B C; do echo "--- island $n ---"; tail -4 /tmp/ga_p2_${n}.log; done

    for n in A B C; do
      echo "--- island $n val ---"
      grep "NEW VAL BEST" /tmp/ga_p2_${n}.log | tail -5
    done

### Champions

Per island, two files:

    output/champions/ga_p2_island_A.txt         # val-selected
    output/champions/ga_p2_island_A_train.txt   # train-selected

Both are valid; eval tells you which is better. Background: STATE.md §5.18.

### Eval

Wait for all three to finish (`=== DONE ===` in all three logs), then:

    cd ~/project && source ~/llm-env/bin/activate
    python -m src.eval \
      output/champions/ga_p2_island_A.txt \
      output/champions/ga_p2_island_A_train.txt \
      output/champions/ga_p2_island_B.txt \
      output/champions/ga_p2_island_B_train.txt \
      output/champions/ga_p2_island_C.txt \
      output/champions/ga_p2_island_C_train.txt \
      data/baseline_team.txt \
      --opponents heldout --pilot heuristic \
      --seeds 100 200 300 400 500 --concurrency 8 \
      2>&1 | tee /tmp/eval_p2.log

### Stop

    pkill -9 -f "run.ga_island"
    pkill -9 -f "pokemon-showdown start 8001"
    pkill -9 -f "pokemon-showdown start 8002"

Checkpoints under `output/checkpoints/v6/p2_A/`, `p2_B/`, `p2_C/`.
Rerunning same run_id resumes per-island independently.

### Caveats

- Ring migration disabled in parallel mode (§5.18).
- Val-selection overfits; both selection rules are written.
- Concurrency per process = 8. Higher doesn't help (§5.9).


Morning after an overnight run:

    ls -la /tmp/ga_overnight_done_* 2>/dev/null
    cat /tmp/ga_final_eval.log
    grep "NEW ALL-TIME" /tmp/ga_run*.log | tail -20
    ls -lat output/champions/

Weekly:
- Regenerate `pool_split.json` only if new tournament data has been scraped
- Retrain BC only if a new dataset is available (heuristic-imitation,
  larger replay corpus)
- Re-evaluate the current champion against the held-out pool with 18 seeds
  for the definitive number

Monthly:
- Audit `output/` size: `du -sh output/checkpoints/`
- Prune old checkpoints
- Review `docs/STATE.md` for stale entries