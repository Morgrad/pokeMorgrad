# Diagnostics, useful one-liners and cleanup

Copy-paste commands for inspecting a running or finished GA, diagnosing the BC pilot,
checking encoder equivalence, and cleaning up disk / logs. Read it when something looks
wrong and the health check (`health-check.md`) did not explain it, or when disk is filling.

Last verified against code: 2026-11-18

All commands run from the repo root with the venv active. Log strings below are quoted from
the code that prints them (`src/ga/engine.py`, `src/ga/population.py`, `src/ga/evaluator.py`,
`src/ga/checkpoint.py`), so they are safe to grep.

## Is anything running? Is Showdown up?

```
pgrep -af "ga_island|ga_run|ga_parallel|ga_overnight|src.eval|bc_train|paired_eval|pokemon-showdown"
for p in 8000 8001 8002; do curl -s --max-time 2 http://localhost:$p > /dev/null && echo ":$p UP" || echo ":$p DOWN"; done
```

## GA progress (parallel run, run_id `p2` as the example)

Logs: `/tmp/ga_<run_id>_<A|B|C>.log` (parallel), `/tmp/ga_run1.log` / `/tmp/ga_run2.log` (serial).

```
# last lines per island
for n in A B C; do echo "--- island $n ---"; tail -4 /tmp/ga_p2_${n}.log; done

# generation summaries: "[A] gen 12: best= 63.0%  all-time= 66.0%  stag=2  uniq=41"
grep -h "\] gen [0-9]*:" /tmp/ga_p2_A.log | tail -10

# all-time-best trajectory (train fitness)
grep -h "NEW ALL-TIME" /tmp/ga_p2_*.log | tail -20

# validation-slice bests (tracked, not used for the primary champion since 2026-10-15)
grep -h "NEW VAL BEST" /tmp/ga_p2_*.log | tail -10

# early-stop is working: genomes aborted after 50 battles below 15%
grep -c "early-abort" /tmp/ga_p2_*.log

# stagnation restarts, diversity injections, server restarts
grep -hE "STAGNATION|diversity low|\[showdown\]" /tmp/ga_p2_*.log | tail -20

# resumed from a checkpoint? finished?
grep -h "RESUMED from" /tmp/ga_p2_*.log
grep -lE "=== DONE ===|TIME BUDGET REACHED" /tmp/ga_p2_*.log
ls /tmp/ga_p2_done 2>/dev/null

# is it stuck? (log older than 5 min and CPU low = stuck)
for n in A B C; do echo "$n $(stat -c '%y' /tmp/ga_p2_${n}.log)"; done; date
grep -h "STALLED" /tmp/ga_p2_*_watchdog.log
```

Note: opponents per genome = `min(battles_per_genome, GA_TRAIN_SAMPLE=250, train pool size)`
(`src/ga/engine.py`). The early-abort path only runs with MORE than
`early_stop_min_battles` = 50 opponents. `run/ga_island.py` passes 50 battles per genome, so
parallel islands never early-abort (count 0 is expected). The serial `run/ga_run.py` passes 800,
capped by the train pool (about 118 teams on 2026-11-18: 148 minus the 30-team validation
slice), so it does early-abort.

Champions and checkpoints:

```
ls -lat output/champions/ga_p2_island_*.txt
grep -h "champion (" /tmp/ga_p2_*.log          # fitness of each written champion
for n in A B C; do ls output/checkpoints/v6/p2_${n}/ 2>/dev/null | tail -1; done
```

Champion files contain only the team text (no header). For a run killed before it wrote
champions: `python3 tools/extract_champions.py p2` (reads the latest checkpoint per island;
writes the train best as the primary file, like the GA, plus `_val.txt`).

Copy a champion into the baseline used by island A next time (changes GA input; only with
approval, and note `data/baseline_team.txt` is tracked):

```
cp output/champions/ga_p2_island_A.txt data/baseline_team.txt
```

## Repo-wide audit

```
python -m src.audit_before_launch | grep -E "Failures|Invalid regional|Final|VALID|LOCK"
```

Checks DB integrity, name sanity, Mega stones, regional-team validity, 500 + 500 genome
fuzz, 2000 mutations, 500 crossovers, baseline validity (about 27 s). It never exits
non-zero; read the counts (healthy: every `Failures: 0/500`, `Final: VALID`).

## BC pilot vs heuristic decision comparison

Needs Showdown on :8000 and a BC model file (none on the 2026-11-18 laptop checkout).
`tools/bc_diagnostic.py` has no `sys.path` bootstrap, so set `PYTHONPATH`:

```
BC_PILOT_PATH=output/models/bc_heuristic_v1c.pt PYTHONPATH=. python tools/bc_diagnostic.py 15
```

Plays N battles (default 10) of the BC pilot vs heuristic opponents and asks a shadow
`SimpleHeuristicsPlayer` for its choice on the same battle object each turn. Prints agreement
buckets by turn number and by our lowest HP; writes every decision to `/tmp/bc_diag.jsonl`.
Used in October 2026 to find the BC move-loop bug and the ally-target scoring bug.
Classify disagreements (structural / target-only / action):

```
python3 -c "
import json
def parse(msg):
    if not msg: return None
    out = []
    for p in msg.replace('/choose ', '').split(', '):
        p = p.strip()
        if p in ('pass', 'default'): out.append(('pass', None, None)); continue
        t = p.split()
        if len(t) >= 2: out.append((t[0], t[1], t[2] if len(t) > 2 else None))
    return out
tot = {'agree': 0, 'target_only': 0, 'action': 0, 'structural': 0}
for line in open('/tmp/bc_diag.jsonl'):
    d = json.loads(line); b, h = parse(d['bc']), parse(d['heur'])
    if not b or not h: tot['structural'] += 1; continue
    if b == h: tot['agree'] += 1; continue
    same = len(b) == len(h) and all(x[0] == y[0] and x[1] == y[1] for x, y in zip(b, h))
    tot['target_only' if same else 'action'] += 1
print(tot)
"
```

## Encoder equivalence gate

`src/state_encoder.py` feeds frozen BC checkpoints, so a refactor must not change one bit:

```
python tools/encode_snapshot.py capture    # BEFORE editing state_encoder.py
# ... edit ...
python tools/encode_snapshot.py check      # exit 0 = identical, 1 = drift
```

Reference file: `$ENC_SNAPSHOT_REF` (default `/tmp/enc_snapshot_ref.pt`). Covers synthetic
edge-case states plus the first 200 states of `data/training_data.jsonl` if present.
(The old runbook's `capture --out ...` syntax does not exist.)

## Pilot / lookahead diagnostics

- `DOUBLES_LA_LOG=/tmp/la.jsonl` with the lookahead on (`DOUBLES_LOOKAHEAD=1`) appends every
  decision the lookahead changed (picks, values, dv, V1, foe Trick Room prob, HP).
- Paired live comparison of pilot variants: `bash tools/paired_run.sh <heuristic|ladder> <target>`
  and `python tools/paired_eval.py status --opp ladder`; see `docs/runbooks/evaluation.md`.

## Cleanup

Checkpoints prune themselves: `src/ga/checkpoint.py::save_checkpoint` keeps the newest file
and every generation that is a multiple of 5. Whole old runs can go once their champions
exist (irreversible; ask first):

```
du -sh output/checkpoints/v6/* | sort -h | tail
ls output/champions/ga_p1_island_*.txt && rm -rf output/checkpoints/v6/p1_A output/checkpoints/v6/p1_B output/checkpoints/v6/p1_C
```

Models: `ls -lat output/models/*.pt`. Never delete or overwrite `output/models/bc_best.pt`
(promotion rule in `docs/design/policy.md`); delete superseded candidates by name only.

Smoke-test champions (from runs with a throwaway run_id):

```
mkdir -p output/champions/_smoke_archive
mv output/champions/ga_<smoke_run_id>_island_*.txt output/champions/_smoke_archive/
```

Temp files and logs (stop runs first; these are the only copies of the logs):

```
rm -f /tmp/ga_run*.log /tmp/ga_overnight*.log /tmp/ga_final_eval.log /tmp/showdown*.log
rm -rf /tmp/ga_golden_*          # leftovers from tests/test_ga_golden.py runs before 2026-11-18
rm -rf /tmp/test_decisions       # leftover of the removed tests/test_decision_logger.py
```

Python bytecode and Windows metadata files:

```
find . -name "__pycache__" -type d -not -path "./.git/*" -not -path "./.venv/*" -exec rm -rf {} +
find . -name "*:Zone.Identifier" -not -path "./.git/*" -delete
```

Disk check: `df -h . | tail -1` (preflight requires more than 5 GB free).

## Monthly (from the old runbook)

Audit `du -sh output/checkpoints/`, prune old runs, and review `docs/STATE.md` for stale entries.

## Related docs

- [health-check.md](health-check.md) - first checks, preflight, verify gate
- [showdown.md](showdown.md) - server start / restart
- [failure-modes.md](failure-modes.md) - symptom -> cause -> fix
- [ga-run.md](ga-run.md) - launch, stop, resume, recover champions
- [evaluation.md](evaluation.md) - eval and paired comparisons
- [../reference/tools.md](../reference/tools.md) - every tool script
