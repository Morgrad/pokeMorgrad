# Evaluation: team eval, paired pilot comparisons, pre-launch audit

Covers `src/eval.py` (score team files vs the held-out pool), `tools/paired_eval.py` +
`tools/paired_run.sh` (paired A/B of pilot features with McNemar), and
`src/audit_before_launch.py` (data/genome sanity audit run by `tools/verify.sh`). Read before
changing any of them or before trusting a number they print. How-to: `docs/runbooks/evaluation.md`.

Last verified against code: 2026-11-18

## 1. Purpose

- `src/eval.py`: "how good is this team?" Plays each team file against every team of a pool
  (default: the 100-team held-out pool from `data/pool_split.json`), once per seed, and prints raw
  win rate, a 95% Wilson CI and the GA's meta-weighted rate (same number the GA optimises, so a
  holdout score is comparable with GA fitness).
- `tools/paired_eval.py`: "does pilot feature X help?" Plays every matchup twice (feature off /
  on) with identical teams, so the comparison is paired; reports the paired difference and an
  exact McNemar test. Used to accept/reject `use_turn_sim`, the support layer and the lookahead.
- `src/audit_before_launch.py`: before a GA run, check the DB, the train pool and that random
  genome building/mutation/crossover always yields locally legal teams.

## 2. Files

| path | lines | role |
|---|---|---|
| src/eval.py | 170 | CLI `python -m src.eval`; `evaluate_team`, `wilson_ci`, `main_async` |
| src/audit_before_launch.py | 226 | `main()`: 9 printed audit sections, returns the list of hard failures; the module exits 1 if any |
| tools/paired_eval.py | 301 | `run` / `status` / `report` subcommands; JSONL logs in `data/paired_eval/` |
| tools/paired_run.sh | 62 | 3-shard launcher on ports 8000-8002 with server restarts and resume |

## 3. Key concepts

- Pools: `regional_pool()` = `pool_split.json["train"]` (148 `vgc_*.txt` teams since 2026-11-14),
  `heldout_pool()` = `["holdout"]` (100 `real_ev_*.txt`, frozen since 2026-10-15). Both in
  `src/ga/pools.py`. `heldout_pool()` raises RuntimeError if
  `pool_split.json` is missing, its holdout list is empty, or a file is in both lists (until
  2026-11-18 a missing file silently returned the train pool).
- Seeds: `random.seed(seed)` only fixes account ids/sampling on our side. Showdown's battle RNG is
  not client-seedable, so a "seed" is just one more pass over the pool (100 battles on holdout).
- Meta-weighted rate: `src/ga/fitness.py::weighted_fitness(outcomes, opponents, DEFAULT.meta_weights)`
  -> each opponent team weighs the mean ladder usage of its 6 species (`data/species_ladder_usage.json`,
  floor 0.02); `GA_META_WEIGHTS=0` makes it the plain rate. Outcomes pair with opponents by index.
- None outcomes (timeout/error after 1 retry) are excluded from wins and games.
- Paired matchup k (`paired_eval.matchups`): `random.Random(2026)` draws (i, j) distinct indices of
  the held-out pool; our side = holdout[i], foe = holdout[j]; `--team a.txt,b.txt` replaces our side
  with team number `(k // shards) % n_teams`.
- Arms `off`/`on`: our pilot is always `vgc` (`make_player("vgc", ..., prefix "B")`, which is
  `TimeoutPlayer`: forfeits after turn 50). Mode `turnsim`: `use_turn_sim = arm`; mode `support`:
  turn_sim on, `effects = parse_effects(support if on else "")`; mode `lookahead`: turn_sim on,
  effects on, `lookahead = arm`.
- Paired JSONL row (one line per matchup, appended and flushed):
  `{"k": 17, "ours": 3, "theirs": 41, "t": 1792000000.0, "off": {"win": 1, "turns": 9, "secs": 14.2,
  "counters": {...}, "foe": {...}}, "on": {...}}`; a failed arm is `{"win": null, "error": "..."}`.
  `<log>.plan` holds the run's arguments. Report keeps the LAST row per k.

## 4. Public API

- `src/eval.py::evaluate_team(pilot, team_str, opponents, seeds, concurrency, opp_pilot="heuristic")`
  (async) -> `(wins, games, weighted_rate)`.
- `src/eval.py::wilson_ci(wins, games, z=1.96)` -> `(lo, hi)` fractions.
- `src/eval.py` constants: `TIMEOUT=20` s per battle, `DEFAULT_SEEDS=[100, 200, 300]`,
  `CONCURRENCY=int(GA_CONCURRENCY or 3)`, `FORMAT`/`UID_MAX` from `src/ga/config.py`.
- `tools/paired_eval.py::matchups(n)`, `one_battle(k, arm, ours, theirs, sem, opp, mode, support)`,
  `load_rows(paths)`, `finished(row)`, `mcnemar_p(b, c)`, `wilson(w, n)`, `report(paths)`,
  `status(opp, tag)`. Constants `TIMEOUT=90`, `SEED=2026`, `MAX_CONSEC_ERRORS=12`.
- `src/audit_before_launch.py::main()` -> list of hard failures (runs the `check_*`
  functions in `CHECKS`, one per report section; `runbooks/health-check.md`).

## 5. Flow

`python -m src.eval [teams...] [flags]`:
1. Teams default to `data/baseline_team.txt`; `--opponents heldout` (default) or `all` (train pool).
2. `--pilot` in `heuristic|bc|doubles|vgc|both`; DEFAULT IS `both` (= heuristic then bc).
3. For each pilot and team: `evaluate_team` runs seeds sequentially; per seed, one
   `src.battle.run_battle` per opponent (retries=1, timeout 20 s, min_turns 0), one shared semaphore.
4. Prints `name  W/G = pct%  95% CI [lo-hi]  meta-weighted x%`; with 2 pilots, a HEUR/BC/Delta table.

`paired_eval.py run`: resumes (skips k with both arms finished), writes `.plan`, runs
`--concurrency` workers over k = shard, shard+shards, ...; stops at `--target` finished matchups,
after `--chunk` new ones, after `--minutes`, or after 12 consecutive unfinished matchups.
Exit codes: 0 target reached, 10 chunk done, 2 aborted (server down?), 3 time cap / no work left.

`paired_run.sh <opp> <target>`: for shards 0-2 (port 8000+i): kill and restart
`node pokemon-showdown start <port> --no-security` (log `/tmp/showdown_<port>.log`), wait up to 60 s,
run one chunk (`CHUNK`, default 1000); if the shard's JSONL has no write for `STALL_S` (300 s) kill
and resume; rc 10 -> next chunk, rc 0 -> done, other -> retry, give up after 6 consecutive failures.
Per-shard log `data/paired_eval/<name>_run<i>.log`.

`report`: per arm W/N, Wilson CI, errors, mean battle seconds; paired n (both finished),
on-off difference with 95% CI (normal approx. on discordant pairs), b = on-only wins,
c = off-only wins, McNemar exact two-sided p = min(1, 2 * sum_{i<=min(b,c)} C(b+c, i) / 2^(b+c));
summed pilot counters (`overrides`, `sim_*`, `sup_*`, ...), per-team rows when `--team` was used,
opponent counters. `status`: per shard done/target, rate over last 5 min, RUNNING if last write
< 120 s, totals with ETA and the running paired estimate.

Audit sections (`python -m src.audit_before_launch`): 1 DB integrity (counts, `meta.built`);
2 name sanity (species need name, baseSpecies, abilities, >= 4 moves); 3 Mega stone legality and
`_legal_items_for` on 5 species; 4 every TRAIN-pool team through `regmc_db.validate_team` (holdout
not checked); 5 500 random genomes with slot 0 locked to Umbreon; 6 500 free genomes; 7 2000
mutations of one locked genome (lock must hold); 8 500 crossovers; 9 baseline team validity.
Seeds 0, then 42 (section 7), then 1 (section 8). Local validator only, no Showdown needed.

## 6. Invariants

- `evaluate_team` must collect outcomes in submission order (`asyncio.gather`) and pass the
  matching opponent list to `_fitness` (pinned by `tests/test_ga_robust.py::test_eval_reports_the_ga_fitness`
  and `tests/test_ga_eval_order.py`).
- The held-out pool is never used by the GA and never mixed into train (`docs/runbooks/data-pipeline.md`).
- Paired logs are append-only; a matchup's arms always run concurrently in the same process so
  both arms see the same server state.
- Matchup list depends only on SEED 2026 and the holdout order: changing `pool_split.json["holdout"]`
  invalidates resuming old paired logs.

## 7. Config and env vars

| name | default | where |
|---|---|---|
| `GA_CONCURRENCY` | 3 | `src/eval.py` default for `--concurrency` |
| `GA_META_WEIGHTS` | 1 | `src/ga/config.py` (used by `_fitness`) |
| `SHOWDOWN_PORT` | 8000 | `src/paths.py::showdown_port` via `src/player_factory.py` (eval and paired_eval connect here) |
| `BC_PILOT_PATH` | `output/models/bc_best.pt` | which model `--pilot bc` loads |
| `DOUBLES_TURN_SIM`, `DOUBLES_SUPPORT`, `DOUBLES_LOOKAHEAD` | see pilots.md | pilot defaults for `--pilot vgc|doubles` |
| `CHUNK` / `STALL_S` | 1000 / 300 | `tools/paired_run.sh` |
| `TAG` / `MODE` / `SUPPORT` / `TEAMS` | "" / turnsim / all / "" | `tools/paired_run.sh` |
| `PY` | `.venv/bin/python` if it exists, else `$HOME/venv-pokemorgad/bin/python` | `tools/paired_run.sh` |
| `SHOWDOWN_DIR` | `~/pokemon-showdown` | `tools/paired_run.sh` |

## 8. Tests

- `tests/test_ga_robust.py::test_eval_reports_the_ga_fitness`: `evaluate_team` passes `opp_pilot`
  through and returns the GA fitness of the outcomes (fake `run_battle`, no server).
- `tests/test_meta_weights.py`, `tests/test_ga_eval_order.py`: `_fitness` weighting and pairing.
- Nothing tests `paired_eval.py` or the audit; the audit itself runs as the last `tools/verify.sh` step.
Run: `python tests/test_ga_robust.py`; gate: `bash tools/verify.sh` (must end `ALL PASS`).

## 9. Gotchas and known issues

- Plain `python -m src.eval` also runs the BC pilot (default `--pilot both`), which is broken
  (see `docs/subsystems/bc.md`) and needs torch + `output/models/bc_best.pt`. Always pass `--pilot`.
- `--pilot vgc` runs as `TimeoutPlayer` (forfeit after turn 50) because eval's player prefix is "B".
- Noise floor (2026-10-13/15, baseline team): 100 battles +-5 pts, 500 battles +-2.2 pts; the same
  500-battle eval read 54.8/55.0/55.8/57.2/60.6%. Use >= 5 seeds; a < 3-pt gap between two
  unpaired evals is noise. Paired runs need far fewer battles for the same power.
- Score environments are not comparable across: holdout changes (real-EV holdout from 2026-10-15),
  pilot/opponent (`--pilot heuristic --opp heuristic` vs `--pilot vgc --opp ladder`), weighting.
  Baseline team on the current holdout: 53.6% [49.2-57.9] (q5 eval vs heuristic opponent,
  2026-11-15; older "57%" figures are from the pre-2026-10-15 holdout).
- Never run eval or paired runs while a GA uses the same Showdown port; `paired_run.sh` KILLS and
  restarts the servers on 8000-8002 (the GA's ports).
- `paired_run.sh` uses the repo `.venv/bin/python` if it exists, else
  `$HOME/venv-pokemorgad/bin/python`; `PY=...` overrides both.
- `paired_eval.py run --opp` defaults to `heuristic` but `status --opp` defaults to `ladder`.
- The audit exits 1 on any hard failure (prints `AUDIT FAILED` and one `FAIL` line each), so
  `verify.sh` stops there. Fixed 2026-11-18: it used to always exit 0.
- Raw paired logs (`data/paired_eval/*.jsonl|.plan|.log`) are gitignored; only
  `data/paired_eval/teams/umb_*.txt` is tracked. This checkout has no logs.

Paired results so far (`ladder` opponent unless noted, held-out matchups):

| tag / mode | n pairs | off | on | paired diff [95% CI] | p | date |
|---|---|---|---|---|---|---|
| turnsim vs heuristic | 17,941 | - | - | +4.7 | < 0.001 | 2026-10-16 |
| turnsim vs ladder | 16,506 | - | - | +4.5 | < 0.001 | 2026-10-16 |
| `s1` support, umb_* teams | 1,206 | 72.6% | 77.1% | +4.6 [+1.2, +8.0] | 0.010 | 2026-10-20 |
| `la` lookahead, umb_* | 2,406 | 76.4% | 74.8% | -1.5 [-3.9, +0.8] | 0.21 | 2026-10-20 |
| `ladiag` lookahead, moonlight | 3,581 | 74.2% | 75.5% | +1.3 [-0.7, +3.3] | 0.21 | 2026-10-20 |
| `ctl` support, plain pool | 1,806 | 73.5% | 75.6% | +2.2 [-0.5, +4.8] | 0.124 | 2026-10-20 |

Decisions: turn_sim made default; lookahead stays off; support layer default still off
(`support_value.DEFAULT_SUPPORT`). Source: STATE.md handoff entries.

## 10. How to change safely

- [ ] Changing `evaluate_team` or `_fitness`: keep index pairing; run `python tests/test_ga_robust.py`
      and `python tests/test_ga_eval_order.py`.
- [ ] Adding a paired mode: add to `--mode` choices and the branch in `one_battle`; keep both arms
      in one `asyncio.gather`; new tag so old logs are not mixed.
- [ ] Never change `SEED`, matchup generation or the holdout while a paired run is being resumed.
- [ ] Audit: keep it import-silent (logic in `main()`), keep sections cheap (~15 s).
- [ ] `bash tools/verify.sh` must end with `ALL PASS`.

## Related docs

- [Evaluation runbook](../runbooks/evaluation.md)
- [BC subsystem](bc.md), [pilots](pilots.md), [battle harness](battle-harness.md)
- [GA](ga.md), [foundation (meta weights)](foundation.md)
- [Showdown runbook](../runbooks/showdown.md), [health check](../runbooks/health-check.md)
- [Data files](../reference/data-files.md), [tools index](../reference/tools.md)
