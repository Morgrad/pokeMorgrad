# Operating policy and working rules

The rules for working in this repo: the user's working rules, the coding-agent rules in
`.clinerules/00-core-rules.md`, run policy (when and how to launch long jobs), daily / weekly
routines, the BC model promotion rule, evaluation discipline, and git / data rules.
Read this before editing code, committing, or launching anything that takes more than minutes.

Last verified against code: 2026-11-18

## 1. User working rules (non-negotiable)

1. Discuss / propose before editing code, committing, or launching jobs. When asked to
   analyze, give a plan and wait for the user's go-ahead ("Proceed").
2. Commit only when asked. In the Cline golden workflow below, the commit after a genuine
   `ALL PASS` is part of the task the user asked for; outside that workflow, do not commit.
   Use conventional commit messages. Never commit from a script you have not read; read the
   diff first.
3. Never launch a long GA run (or any long eval / training) without explicit approval that
   names the hours and a fresh run_id (`bash run/ga_parallel.sh <hours> <run_id>`).
4. The held-out pool is never used for fitness. GA fitness uses the training pool
   (`data/pool_split.json["train"]`, 148 teams on 2026-11-18, of which 30 form the validation
   slice); final scoring uses `["holdout"]` (100 teams). Never mix them; pool swaps
   (`tools/swap_pool.py`) never touch the holdout.
5. Format `gen9championsvgc2026regmc` (Reg M-C, Champions mod), doubles. Mega Evolution is
   legal; Terastallization is NOT legal: never write Tera logic. EVs are 0-32 per stat,
   total 66, stat term `max(2*points - 1, 0)`.
6. `data/*` is gitignored with a whitelist (`.gitignore`). Whitelisted files are added normally;
   any other file under `data/` needs `git add -f <file>` (already done for
   `data/opp_actions.json` and `data/paired_eval/teams/umb_*.txt`). `output/`, `*.pt`, `*.jsonl`
   are never committed.
7. Never hand-edit `data/regmc_db.json` (rebuild with `node tools/build_regmc_db.js`). Never
   modify `~/pokemon-showdown/`.
8. Keep the docs current: update `docs/STATE.md` (done / next / open issues) at every checkpoint.

## 2. Coding-agent rules (`.clinerules/00-core-rules.md`, summarized)

The file is authoritative; this is a summary for agents that cannot load it.

- Always run inside the venv (the file names `~/venv-pokemorgad`, the workstation venv; on a
  checkout with the repo `.venv`, use `source .venv/bin/activate`). Never use pytest; the gate
  is `bash tools/verify.sh`.
- Structure: logic in `src/`, tests in `tests/`, scripts in `tools/`, launchers in `run/`. Never
  create `.py` files in the repo root; temp files go in `/tmp/` or `output/`. A new `pip install`
  must be added to `pyproject.toml`.
- Surgical slices: never rewrite a whole file; edit one function / class at a time (50-100
  lines of diff max), then wait for approval before the next one. No surprise refactoring.
- Lint is mandatory: after editing, `ruff check --fix <files>`, then `bash tools/verify.sh`.
  Do not reformat untouched code. Never commit with ruff errors.
- Golden workflow for every edit:
  1. `cp <file> <file>.bak`
  2. edit
  3. `ruff check --fix <file>`
  4. `bash tools/verify.sh`
  5. Not `ALL PASS`: `mv <file>.bak <file>`, say "Tests failed. Restored from backup.", stop.
     Do not try to fix it.
  6. `ALL PASS`: delete the `.bak`, update the date line at the top of `docs/STATE.md`
     (`date "+%Y-%m-%d %H:%M:%S"`), then `git add <files> && git commit -m "..."` as the very
     next action, before any summary.
- If a test fails, fix the test first; never change core logic just to make a test pass.
- Never lie about results: anything other than `ALL PASS` means rollback. Since 2026-11-18
  `verify.sh` stops with `FAILED: tests/<file>.py` at the first failing test file (it used to
  print `ALL PASS` anyway); any FAIL line means rollback.
- Multi-phase tasks: stop after every phase and wait for the user's explicit message.
- Terminal: no `echo` for conversation, no emoji or unicode symbols anywhere (ASCII `[OK]`,
  `[FAIL]`). Tests print exactly `PASS <name>` / `FAIL <name>` using the runner copied from
  `tests/test_damage.py`; unit tests run in under 5 s with no Showdown and no network.

## 3. Run policy

Before launching any run longer than one hour:

1. Ask: is the PC needed for other work during this window (including the local coding LLM;
   see `docs/runbooks/environment.md`)? If yes, defer to an idle period.
2. Health check and gate: `docs/runbooks/health-check.md`, `bash tools/verify.sh` (no FAIL
   lines), `GA_CONCURRENCY=8 python3 tools/preflight.py`, `python -m src.audit_before_launch`.
3. Concurrency 8 per Showdown server (the code default is 3; `run/ga_parallel.sh` sets 8 itself).
4. Launch through a launcher: `bash run/ga_parallel.sh <hours> <run_id>` (preferred: 3 islands,
   3 processes, ports 8000-8002, 2.78x the serial throughput, watchdog + respawn) or the serial
   chain via `preflight.py --launch` (deletes run1/run2 checkpoints). A direct
   `python -m run.ga_run` / `run.ga_island` does ensure Showdown at startup but has no respawn,
   no watchdog and no final eval.
5. Use a fresh run_id per launch (p1, p2, q1, ...) so checkpoints and champions are not clobbered.

Always:
- Never run an eval while a GA uses the same Showdown server; never launch a second GA on the
  same Showdown instance.
- Never modify `src/` in the hour before a long run (and preflight requires `src/` and `run/`
  committed).
- Never overwrite `output/models/bc_best.pt` outside the promotion rule (section 5).

## 4. Daily, weekly, monthly patterns

Restored from the 2026-10 runbook (the section was later emptied), updated to the parallel launcher.

Start of a session: health check (`health-check.md`); read `docs/STATE.md` for status and next steps.

Morning after a parallel run `<run_id>`:

```
ls /tmp/ga_<run_id>_done 2>/dev/null
grep -h "NEW ALL-TIME" /tmp/ga_<run_id>_*.log | tail -20
grep -h "champion (" /tmp/ga_<run_id>_*.log
ls -lat output/champions/ga_<run_id>_island_*.txt
```

then evaluate the champions on the holdout (`docs/runbooks/evaluation.md`; >= 5 seeds) and
record the result in `docs/STATE.md`. (Serial chain: `/tmp/ga_overnight_done_*`,
`/tmp/ga_final_eval.log`.)

Weekly:
- Regenerate `pool_split.json` / swap the training pool only if new tournament data was scraped
  (`docs/runbooks/data-pipeline.md`); the holdout stays fixed.
- Retrain BC only if a new dataset exists (heuristic imitation or a larger replay corpus).
- Re-evaluate the current champion on the holdout with many seeds (18 seeds = 1800 battles was
  used on 2026-10-13) for the definitive number.

Monthly:
- `du -sh output/checkpoints/`; prune finished runs (`docs/runbooks/diagnostics.md`).
- Review `docs/STATE.md` for stale entries.

Milestones: after a commit that changes what the code can do (new module, bug fix, changed
default), append a dated entry with `python3 tools/log_milestone.py "Title" "One-line summary"`
(writes `docs/history/milestones.md` and commits that file). Docs-only or formatting commits can skip it.

## 5. BC model promotion rule

`output/models/bc_best.pt` is the model every `--pilot bc` eval and `GA_PILOT=bc` run loads
(`src/bc_player.py::DEFAULT_MODEL_PATH`). Never overwrite it without a 5-seed held-out pilot eval
showing at least +3 points over the current `bc_best.pt`. History: on 2026-10-13 a blind
`cp bc_v3_5m.pt bc_best.pt` silently regressed the pilot (v3 8.8% vs v5 19.4%) and had to be
reverted.

```
# 1. train to a NEW name (BC_OUT defaults to bc_candidate.pt since 2026-11-18; never bc_best.pt)
BC_OUT=bc_candidate.pt python -m src.bc_train
# 2. score candidate and current on the holdout, same seeds
for m in bc_candidate.pt bc_best.pt; do
  BC_PILOT_PATH=output/models/$m python -m src.eval --pilot bc --opponents heldout \
    --seeds 100 200 300 400 500 --concurrency 8 data/baseline_team.txt
done
# 3. only if candidate >= current + 3 points (and with approval):
cp output/models/bc_candidate.pt output/models/bc_best.pt
```

(The old STATE command `python -m src.eval --pilot bc output/models/<candidate>.pt` is wrong:
positional arguments are TEAM files; the model is chosen with `BC_PILOT_PATH`.)
Checkpoints are saved on the best `val_move_acc`, not the best `val_loss`. Imitation accuracy
does not predict win rate (STATE 5.12), so the live eval is the only promotion criterion.

## 6. Evaluation discipline

- Use >= 5 seeds (500 battles) for any decision; report the 95% Wilson CI that `src/eval.py`
  prints. Noise (2026-10-13): 100 battles +-5 pts, 300 +-3, 500 +-2.2. Overlapping CIs = no
  difference; gaps under 3 points need more than 500 battles or a paired comparison
  (`tools/paired_run.sh`, `docs/runbooks/evaluation.md`).
- Compare like with like: fitness-environment changes (2026-10-16 `vgc` vs `ladder`,
  meta-weighted) and the 2026-11-18 ordering fix make older GA scores incomparable.
- Champion selection: train-best is the primary champion since 2026-10-15 (val-selection
  overfit by 15-27 points); both `_train.txt` and the primary file are written.

## Related docs

- [../runbooks/health-check.md](../runbooks/health-check.md) - checks before a run
- [../runbooks/ga-run.md](../runbooks/ga-run.md) - launching and resuming
- [../runbooks/evaluation.md](../runbooks/evaluation.md) - evals and paired comparisons
- [../runbooks/bc-training.md](../runbooks/bc-training.md) - BC training
- [../runbooks/environment.md](../runbooks/environment.md) - host, GPU, local LLM
- [../reference/tests.md](../reference/tests.md) - verify gate details
- [decisions.md](decisions.md) - design decisions
