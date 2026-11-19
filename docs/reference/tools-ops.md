# tools/ reference: evaluation, diagnostics, GA ops, one-offs

Per-script details for the operational side of `tools/`: paired evaluation, BC diagnostics, the
encoder gate, GA helpers (watchdog, champion recovery, milestone log) and one-off experiments.
Index and status key: `tools.md`. `verify.sh` and `preflight.py` are only summarised here
(full coverage: `docs/runbooks/health-check.md`).

Last verified against code: 2026-11-18

## Evaluation

**paired_eval.py** (LIVE) - paired off/on comparison of a `VGCPilot` feature on held-out matchups.
- Run one shard: `SHOWDOWN_PORT=8000 python tools/paired_eval.py run --shard 0 --shards 3 --target 5500 --opp ladder`
- Flags (`run`): `--shard 0`, `--shards 1`, `--target 5500` (finished matchups per shard),
  `--chunk 0` (stop after N new, exit 10), `--minutes 0` (cap), `--concurrency 3` (matchups in
  flight; battles in flight = 2x), `--out` (default `data/paired_eval/<opp>[_<tag>]_shard<i>.jsonl`),
  `--opp heuristic|ladder` (default heuristic), `--mode turnsim|support|lookahead` (default
  turnsim), `--support all` (effects for the on arm, e.g. `foulplay,snarl`), `--team a.txt,b.txt`
  (replace our side), `--tag NAME`.
- Progress: `python tools/paired_eval.py status --opp ladder [--tag NAME]`.
- Result: `python tools/paired_eval.py report data/paired_eval/ladder_shard*.jsonl`.
- Battle timeout 90 s, 2 attempts per arm, abort after 12 consecutive unfinished matchups.
- Exit codes: 0 target reached, 10 chunk done, 2 abort, 3 time cap or nothing left.
- Full semantics, row format and statistics: `docs/subsystems/eval.md`.

**paired_run.sh** (LIVE) - `bash tools/paired_run.sh <heuristic|ladder> <target_per_shard>`, e.g.
`PY=.venv/bin/python TAG=s1 MODE=support SUPPORT=all TEAMS=data/paired_eval/teams/umb_baseline.txt,data/paired_eval/teams/umb_charm.txt nohup bash tools/paired_run.sh ladder 400 &`.
Runs shards 0-2 on ports 8000-8002; before each chunk it kills and restarts that port's Showdown
(`$SHOWDOWN_DIR`, log `/tmp/showdown_<port>.log`); kills a shard whose JSONL is not written for
`STALL_S` (300) s; gives up after 6 consecutive failures. Env: `CHUNK` 1000, `STALL_S` 300, `TAG`,
`MODE`, `SUPPORT`, `TEAMS`, `PY` (default: repo `.venv/bin/python` if it exists, else
`$HOME/venv-pokemorgad/bin/python`). Never run while a GA uses ports 8000-8002.

## Diagnostics

**bc_diagnostic.py** (STALE: the BC pilot is broken, see `docs/subsystems/bc.md`) -
`PYTHONPATH=. BC_PILOT_PATH=output/models/bc_best.pt python tools/bc_diagnostic.py [n_battles=10]`.
Baseline team (`data/baseline_team.txt`, relative path: run from repo root) piloted by
`DiagnosticBC` (BCPlayer that also asks a shadow `SimpleHeuristicsPlayer` on the same battle object)
vs a random train-pool team with the heuristic; random seed 42; battle timeout 45 s; poke_env default
server (localhost:8000). Writes `/tmp/bc_diag.jsonl` (one row per `choose_move` call:
`{"turn", "my_hp", "bc", "heur", "agree"}`, where bc/heur are `/choose ...` strings) and prints
agreement by turn bucket, by our lowest HP bucket, and the top BC-only / heuristic-only picks.
Used to find the 2026-10-12 loop bug and the ally-target bug. Calls-per-turn check: see
`docs/runbooks/bc-training.md`.

**encode_snapshot.py** (LIVE) - bit-identity gate for `src/state_encoder.py`.
`python tools/encode_snapshot.py capture` BEFORE editing (3 synthetic edge-case states + first 200
rows of `data/training_data.jsonl` if present) -> `$ENC_SNAPSHOT_REF` (default
`/tmp/enc_snapshot_ref.pt`); after editing `python tools/encode_snapshot.py check`: exit 0 = all
tensors `torch.equal`, 1 = drift (lists mismatches), 2 = bad usage. There is no `--out` flag. `/tmp` is wiped by a WSL restart, so capture and check in one session.

**debug_taunt.py** (ONE-OFF, 2026-11-12) - `python tools/debug_taunt.py` from the repo root. Prints
`support_value.parse_effects("all")`, `pure_enabled("taunt", ...)`, `pure_kind("taunt")`,
`effect_of("taunt")` and `EFFECTS`; written while debugging "Taunt never chosen". No side effects.

**test_pilots.py** (ONE-OFF, 2026-10-15) - `python tools/test_pilots.py [n_teams=20] [battles_per_team=10] [concurrency=8]`.
`SmartPlayer` vs `SimpleHeuristicsPlayer` on the SAME held-out team (first `n_teams`), port fixed to
8001; prints smart win rate with CI. Result 2026-10-15: SmartPlayer 42.5% [35.9-49.4] over 200
battles (loses to vanilla). SmartPlayer is superseded by `VGCPilot`.

## GA operations

**watch_islands.py** (LIVE, started by `run/ga_parallel.sh`) -
`python tools/watch_islands.py <run_id> <island> <pid> [stall_s=300]`. Every 30 s checks the mtime
of `/tmp/ga_<run_id>_<island>.log`; if older than `stall_s` it SIGKILLs the PID and exits
(`ga_parallel.sh` then respawns the island from its checkpoint). Exits when the PID is gone.
Known flaw (2026-10-15): a traceback loop keeps the log fresh, so a hung island can survive.

**extract_champions.py** (LIVE) - `python tools/extract_champions.py <run_id>` (e.g. `p4`). For
islands A/B/C reads the newest `<CHECKPOINT_DIR>/<run_id>_<X>/gen_NNNN.json` (parallel layout only;
paths from `src/ga/config.py`, so `POKEMORGRAD_ROOT` is honored) and writes, with the same rule as
`src/ga/checkpoint.py::write_champions`: `ga_<run_id>_island_<X>.txt` = train best (`best_ever`;
`best_val_ever` only if there is no train genome), `..._train.txt` = train best, plus
`..._val.txt` = `best_val_ever` (the GA itself does not write `_val`). `extract(run_id,
ckpt_root, champion_dir, islands)` is importable; `tests/test_extract_champions.py` pins it.
Fixed 2026-11-18: it used to write the val best as the un-suffixed file, silently replacing the
GA's train-best champion.

**log_milestone.py** (LIVE) - `python tools/log_milestone.py "Title" "One-line summary"`. Appends
`### YYYY-MM-DD HH:MM - Title`, the summary and `git log -1 --oneline` to
`docs/history/milestones.md` (created on first use), then runs `git add` + `git commit -m "docs:
log milestone - Title"` on that file itself. Only run it when a commit is wanted; it never pushes.
Repo root comes from the script path (before 2026-11-18: `~/pokeMorgrad` and
`docs/STATE_history.md`).

**preflight.py** (LIVE) - `python tools/preflight.py [--launch]`: ~2 s of pre-launch checks
(Showdown :8000 and process, 5 data files, committed `src/` and `run/`, islands configured, torch GPU (informational only since 2026-11-18, not counted),
champions dir writable, disk > 5 GB, `GA_CONCURRENCY` set to non-default);
`--launch` starts the overnight run. Details: `docs/runbooks/health-check.md`.

**verify.sh** (LIVE, the gate) - `bash tools/verify.sh`: ruff on src/run/tools/tests, import smoke
tests (including `src.eval`, `src.bc_*`, `src.state_encoder`, `src.audit_before_launch`), pool
sizes, 32 test files run one by one (stops at the first failing file), `python -m
src.audit_before_launch` (exits 1 on hard failures); must end with `ALL PASS`. It does `cd
~/pokeMorgrad` and activates `.venv` if present, else `~/venv-pokemorgad`. Details:
`docs/runbooks/health-check.md`.

## Legacy and removed

- `batch_parse.py`: LEGACY, see `tools-data.md` (overwrites `data/training_data.jsonl` with an
  outdated schema).
- `regenerate_split.py`: LEGACY / DANGEROUS, see `tools-data.md`.
- Removed 2026-10-16 (commit 1788b2a), still mentioned by old docs: `tools/pilot_probe.py`,
  `tools/*.bak`, top-level `apply_stratify.py`.
- Older scrapers, replay downloaders and the first neural pilots live in `archive/` (not imported).

## Related docs

- [tools.md](tools.md) (index), [tools-data.md](tools-data.md)
- [Evaluation subsystem](../subsystems/eval.md), [evaluation runbook](../runbooks/evaluation.md)
- [BC subsystem](../subsystems/bc.md), [BC training runbook](../runbooks/bc-training.md)
- [GA run runbook](../runbooks/ga-run.md), [run scripts](run-scripts.md)
- [Health check](../runbooks/health-check.md), [Showdown runbook](../runbooks/showdown.md)
