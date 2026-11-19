# Runbook: evaluating teams and comparing pilots

Step-by-step commands to score a team on the held-out pool, compare GA champions, compare pilot
settings, run a paired A/B comparison of a pilot feature, and read the numbers correctly. Code
details: `docs/subsystems/eval.md`.

Last verified against code: 2026-11-18

## 0. Before you start

- Activate the venv: `source .venv/bin/activate` (original workstation: `source ~/venv-pokemorgad/bin/activate`).
- A Showdown server must answer on the port you use (default 8000): `curl -s localhost:8000 >/dev/null && echo up`.
  Start one: `cd ~/pokemon-showdown && nohup node pokemon-showdown start 8000 --no-security > /tmp/showdown_8000.log 2>&1 &`
  (see `docs/runbooks/showdown.md`).
- Never evaluate on a port a GA run is using: both slow down ~10x and the GA's numbers suffer.
  Parallel GA runs use 8000-8002; stop the GA first or wait for it to finish.
- `SHOWDOWN_PORT=<port>` points `src.eval` and `tools/paired_eval.py` at another server.
- Pools: holdout = 100 `real_ev_*` teams (frozen 2026-10-15); train = 148 `vgc_*` teams.
  Check: `python -c "from src.ga.pools import regional_pool, heldout_pool; print(len(regional_pool()), len(heldout_pool()))"` -> `148 100`.

## 1. Score one or more teams (heuristic pilot, the classic number)

```
python -m src.eval data/baseline_team.txt output/champions/ga_run1_island_C.txt \
    --pilot heuristic --opp heuristic --seeds 100 200 300 400 500 --concurrency 8 \
    2>&1 | tee /tmp/eval_$(date +%m%d_%H%M).log
```
- ALWAYS pass `--pilot`: the default is `both`, which also runs the BC pilot (currently broken,
  see `docs/subsystems/bc.md`).
- Each seed = one pass over the 100 held-out teams = 100 battles. 5 seeds = 500 battles.
- `--concurrency 8` was the measured sweet spot (2026-10-13: c=3 35 s, c=8 28 s, c=12+ no gain).
- Battle timeout 20 s, one retry; failed battles are dropped from both wins and games.

## 2. Score in the GA's fitness environment

```
python -m src.eval output/champions/ga_<run>_island_A.txt output/champions/ga_<run>_island_A_train.txt \
    data/baseline_team.txt --pilot vgc --opp ladder --seeds 100 200 300 400 500 --concurrency 8
```
Our side `VGCPilot` (turn_sim on by default; forfeits after turn 50 as `TimeoutPlayer`), opponent
`LadderOpponent` (heuristic + Protect/Fake Out at ladder rates). This is the environment the GA
optimises since 2026-10-16 (`GA_PILOT=vgc`, `GA_OPP=ladder`); scores are NOT comparable with
`--pilot heuristic --opp heuristic` numbers.

## 3. Read the output

```
--- Pilot: HEURISTIC ---
  baseline_team.txt          268/ 500 =  53.6%  95% CI [49.2-57.9]  meta-weighted  NN.N%
```
- `W/G = pct%`: raw win rate over completed battles. `95% CI`: Wilson interval.
- `meta-weighted`: the GA fitness formula (opponents weighted by ladder usage of their species,
  `data/species_ladder_usage.json`); with `GA_META_WEIGHTS=0` it equals the raw rate. Use it to
  compare a holdout score with a GA's printed fitness. (53.6% [49.2-57.9] is the real baseline
  result of 2026-11-15; the meta-weighted value of that run was not recorded.)
- Rules (noise floor measured 2026-10-13/15): 100 battles +-5 pts, 500 battles +-2.2 pts; the same
  500-battle eval has read anywhere from 54.8% to 60.6%. Use >= 5 seeds; treat unpaired gaps
  < 3 pts as noise; overlapping CIs do not separate two teams. For small effects use a paired run (section 6).
- If a team shows `MISSING`, the path is wrong; if G is far below 500, look for timeouts
  (server overloaded, or another job on the port).

## 4. Compare GA champions after a run

1. Champions are written by the GA to `output/champions/ga_<run>_island_<X>.txt` (train-best)
   and `..._train.txt`. If a run was killed: `python tools/extract_champions.py <run_id>` (same
   rule as the GA, plus a `_val.txt` with the validation-best genome; see `docs/reference/tools-ops.md`).
2. Evaluate all of them plus the baseline in ONE command (same server state), 5 seeds, both
   environments if the decision matters (sections 1 and 2).
3. Record team, environment (pilot/opp), holdout version, seeds, W/G, CI and date in STATE/history.
   Reference points: q5 (2026-11-15) island C 62.4% [58.1-66.5] vs baseline 53.6% held-out;
   islands A/B 49.2%/47.0% (overfit: 85-90% on train).

## 5. Compare pilots on the same team

- Heuristic vs BC side by side (when BC works again): `python -m src.eval data/baseline_team.txt --pilot both --seeds 100 200 300 400 500`
  (prints a HEUR/BC/Delta table). Pick a BC model with `BC_PILOT_PATH=output/models/<file>.pt`.
- Other pilots: run `--pilot heuristic`, `--pilot doubles`, `--pilot vgc` as separate commands with
  the same seeds and opponent; only heuristic and bc appear in the delta table.
- These are unpaired comparisons: they need large samples. For a yes/no on a pilot FEATURE use section 6.

## 6. Paired A/B of a pilot feature (tools/paired_eval.py)

What it does: every matchup (our holdout team i vs foe holdout team j, fixed seed 2026) is played
twice at the same time, feature off and on; only the discordant matchups decide the McNemar test.
Modes: `turnsim` (use_turn_sim off/on), `support` (support layer off/on, turn_sim on in both),
`lookahead` (support on in both, lookahead off/on).

Single shard (one server, quick check):
```
SHOWDOWN_PORT=8000 python tools/paired_eval.py run --opp ladder --mode support --support all \
    --team data/paired_eval/teams/umb_baseline.txt,data/paired_eval/teams/umb_charm.txt \
    --tag mytest --target 200 --concurrency 3
```
Three shards on ports 8000-8002 with automatic server restarts (long runs; no GA running!):
```
PY=.venv/bin/python TAG=mytest MODE=support SUPPORT=all \
  TEAMS=data/paired_eval/teams/umb_baseline.txt,data/paired_eval/teams/umb_moonlight.txt \
  nohup bash tools/paired_run.sh ladder 1000 > /tmp/paired_mytest.out 2>&1 &
```
(`PY` defaults to the repo `.venv/bin/python` if it exists, else `~/venv-pokemorgad/bin/python`.)

Monitor: `python tools/paired_eval.py status --opp ladder --tag mytest` (per shard done/target,
rate, RUNNING vs STALLED/STOPPED, ETA, running estimate); shard logs in
`data/paired_eval/ladder_mytest_run<i>.log`. Stop: `pkill -f paired_run.sh; pkill -f "paired_eval.py run"`.
Resume: rerun the same command (finished matchups are skipped, errored ones retried).

Final report: `python tools/paired_eval.py report data/paired_eval/ladder_mytest_shard*.jsonl`
```
matchups logged: N
  off: W/N = x%  95% CI [..]  errors E  mean battle S s
  on : W/N = y%  95% CI [..]  errors E  mean battle S s
paired (both finished) n=N: on-off = +d pts  95% CI [lo, hi]  on-only wins b, off-only wins c, McNemar p=P
```
Real example (tag `s1`, 2026-10-20): n=1206, off 72.6%, on 77.1%, +4.6 pts [+1.2, +8.0], p=0.010.
- Accept a feature only if the paired CI excludes 0 (p < 0.05) AND per-team rows (printed with
  `--team`) do not hide a large regression; then also run a plain-pool control (no `--team`) to
  check builds without the feature do not regress (done for support, tag `ctl`, 2026-10-20).
- Check the counters: `flag-on counters` (`overrides`, `sim_*`, `sup_<effect>`) show whether the
  feature fired at all; a null result with ~0 uses means "not exercised", not "useless".
- `errors` > a few % means server trouble; fix it before trusting the numbers.
- Past decisions and numbers: table in `docs/subsystems/eval.md` section 9.

## 7. Before a GA launch: audit

`python -m src.audit_before_launch` (~15 s, no server). Read the counts: species/items issues 0,
"Invalid regional teams" 0 (train pool only), fuzz failures 0/500, mutations "lock held" and
VALID, crossovers 0/500, baseline VALID. It exits 1 and prints `AUDIT FAILED` plus one `FAIL`
line per problem when a hard check fails (since 2026-11-18; species with < 4 moves are only a
warning: Ditto).

## Related docs

- [Evaluation subsystem](../subsystems/eval.md), [BC subsystem](../subsystems/bc.md)
- [GA run runbook](ga-run.md), [Showdown runbook](showdown.md), [health check](health-check.md)
- [Pilots](../subsystems/pilots.md), [policy](../design/policy.md)
- [tools-ops.md](../reference/tools-ops.md), [data files](../reference/data-files.md)
