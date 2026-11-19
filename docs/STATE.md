# Project state

Current status, open issues and next steps. Short on purpose: the dated log lives in
`history/` and the how-it-works detail in `subsystems/`. Update this file whenever a fact here
changes (the agent workflow in `../.clinerules/00-core-rules.md` asks for it after every commit).

Last updated: 2026-11-18
Last verified against code: 2026-11-18
Branch: `main` (GitHub `Morgrad/pokeMorgrad`). The 2026-11-18 work was pushed that day:
`16d0bb3` (GA package split + fitness-ordering fix), `0572ca9` (everything under "Changes on
2026-11-18" below), then docs follow-ups. `git log origin/main..main` lists anything unpushed.

## Goal
Find the strongest team for Reg M-C (`gen9championsvgc2026regmc`, doubles, Mega legal, no Tera)
around Umbreon, by a GA that scores teams in real Showdown battles, and keep the pipeline
reusable for the next regulation.

## Status by component
| Component | Status |
|---|---|
| GA engine (`src/ga/`: config, genome, pools, legality, operators, fitness, evaluator, population, checkpoint, engine; no facade) | Working. Behavior pinned by a golden master. Stagnation restart / diversity rescue really work since 2026-11-18 (they were no-ops). |
| GA fitness environment | Ours `VGCPilot` (`GA_PILOT=vgc`) vs `LadderOpponent` (`GA_OPP=ladder`), meta-weighted win rate (`GA_META_WEIGHTS=1`). Unknown pilot names now fail at startup. |
| Pilot defaults | turn_sim on, support layer `all` (6 effects: foulplay, snarl, charm, helpinghand, taunt, heal), lookahead off, `PASSIVE_COST` 0.30 (since 2026-11-14), 50-turn cap. |
| Islands | A = Umbreon slot 0 + baseline seed, B = Umbreon slot 0 (5 free slots), C = free. Parallel run: 50 opponents/genome, no migration, ports 8000-8002. |
| Pools | `data/pool_split.json`: 148 train (118 fitness + 30 validation slice) / 100 holdout. Disjoint; `heldout_pool()` refuses to fall back to train. |
| Held-out results | Heuristic baseline 53.6% (2026-11-15). Run q5 (2026-11-15): island C champion 62.4%; Umbreon islands A/B overfit (train ~85%, held-out 49.2% / 47.0%). |
| BC pilot | Parked. Crash on every decision fixed 2026-11-18, but existing checkpoints may not load against the current DB vocabulary (392 species since 2026-10-16) - untested, no `.pt` files on this machine. Best old result ~30% held-out on the pre-swap holdout. |
| Replay logging (`GA_REPLAY_LOG`) | Redesigned 2026-11-18 (`src/replay_log.py`): full battle logs, real fitness / outcome / generation, deterministic capped sample per island and generation, never changes GA results. Not yet run against a live server. |
| Gate | `bash tools/verify.sh`: ruff, imports, pools, 32 test files (219 PASS), audit -> `ALL PASS`. |
| Local-LLM readiness | Code split for a small context (largest `src/` file 434 lines; `turn_sim.py`), `.clineignore` keeps big / generated files out of Cline, docs router `docs/README.md`. |

## Machines
- Original workstation: Windows 11 + WSL2 Fedora, AMD 7900 XTX (ROCm), `~/venv-pokemorgad`,
  Showdown in `~/pokemon-showdown`, models and replays present. Long runs happen here. The user
  is moving the coding agent to a local Qwen3-Coder-30B on this GPU (see `runbooks/environment.md`).
- Secondary checkout (where the 2026-11-18 work was done): repo `.venv` (Python 3.13, poke-env
  0.17.0, CPU torch), no Showdown, no models, no replays, no checkpoints. Unit tests, ruff and
  the audit run here; battles, evals, GA runs and BC training do not. GitHub CLI (`gh`)
  login set up in WSL on 2026-11-18, so `git push` works from here.

## Changes on 2026-11-18
Committed (`16d0bb3`): `ga_core.py` split into `src/ga/` (config, genome, fitness, evaluator,
population, checkpoint, engine) + `src/showdown_server.py`; byte-identical except the fix of
fitness weighting with more than 50 opponents per genome (results were paired with opponents
in completion order). Affects `run/ga_run.py` (118 opponents/genome); not `ga_island.py`.

Committed in `0572ca9`, all tested (gate ALL PASS):
1. `tools/verify.sh` printed ALL PASS after a failing test file (skipped the rest); now stops at
   the first failure and runs every test file (32 now). Audit exits 1 on hard failures. Replay test skips
   without replay data.
2. GA: stagnation restart and diversity rescue inject fresh genomes after breeding (were
   discarded); `ring_migrate` targets the worst slots. Golden master regenerated on purpose.
3. BC pilot / heuristic dataset `mon_view` TypeError fixed.
4. Fail loudly: unknown pilot names, invalid `GAConfig` values, Node validator failures (no
   more cached false verdicts), missing/overlapping held-out split.
5. `tools/extract_champions.py` writes the same primary champion as the GA (train best) plus a
   `_val` file. Launch scripts use the repo `.venv` when present. `bc_train` writes
   `bc_candidate.pt` by default (never `bc_best.pt`). Preflight GPU check is informational.
6. Docs rewritten into `docs/` (this structure), `AGENTS.md`, `QWEN.md`.
7. Replay logging rebuilt (approved by the user): logs read from poke_env's
   `battle._replay_data`; `run_battle(log_sink=...)`, `Evaluator.evaluate(on_battles=...)`,
   `run_islands(replay_logger=...)` replace the old `save_filter` / `save_callback`;
   `src/decision_logger.py` removed. Golden master unchanged (logging off = identical GA).
8. Pure refactors for the local model (approved; inputs and outputs identical, each proven
   against a snapshot taken BEFORE the change):
   - `src/ga/genome.py` (834 lines) -> `genome.py` (398), `pools.py` (110), `legality.py`
     (182), `operators.py` (205), code moved verbatim. Golden master unchanged; a seeded
     snapshot of every moved function is byte-identical.
   - `src/ga_core.py` facade deleted; all callers import `src.ga.*` (old -> new table in
     `reference/ga-old-names.md`). Side effect: tools that only import `src.ga.pools`
     (e.g. `tools/paired_eval.py`) no longer validate `GA_*` env vars at import.
   - `TurnSim._run` (173-line closure nest) -> `src/turn_sim_resolve.py::Resolution`
     (`turn_sim.py` 598 -> 434 lines). New `tests/test_turn_sim_paths.py` (3 tests) covers
     the branches no test reached; all 2197 recorded `_run` / `pair_value` / leaf-state
     results are bit-identical. About 3% slower per `_run` call.
   - `src/audit_before_launch.py::main` (206 lines) -> one `check_*` function per section;
     report text byte-identical.
   - `.clineignore` added (data/ big files, output/, archive/, docs/history/, golden fixture).
9. Roadmap items (approved): D6 stale comments / `eval --help` text fixed; D2
   `SHOWDOWN_PORT` parsed only by `src/paths.py::showdown_port`; `run_battle_once` logs
   battle-killing exceptions (result still None, GA unchanged); B2 clause fuzz
   (`tests/test_genome_clauses.py`, failed on the old code) then one shared
   `operators.repair_clauses`, which also fixes `enforce_constraints` leaving the locked
   species twice in migrants. Golden master unchanged, audit byte-identical.

## Open issues (most important first)
1. GA overfits the pilot: train scores far above held-out, worst on the Umbreon islands.
   Structural fitness (`design/structural-fitness.md`) is not implemented.
2. No paired validation of the current pilot defaults (`PASSIVE_COST` 0.30, support `all`):
   the +4.7 / +4.5 pt results were measured with 0.15 and support off.
3. Replay logging depends on poke_env's private `battle._replay_data`: check that the first
   live run with `GA_REPLAY_LOG=1` writes non-empty logs.
4. BC checkpoints vs current DB vocabulary: verify on the workstation; retrain or drop BC
   (`design/refactor-roadmap.md` Tier 2).
5. Realism gaps in genomes: no offensive type coverage, no synergy, natures/EVs from 3 fixed
   role spreads; build/ability priors not used by the GA; move priors are ladder-sourced.
6. Support effects not modelled: Toxic, Yawn, Will-O-Wisp, Wish, screens, Tailwind,
   Follow Me / Rage Powder; Taunt valued only against Trick Room.
7. turn_sim ignores foe switches, back-slot foe Megas, crits, most item/ability effects.
   Speed model stage 2 not built.
8. Battles over 50 turns are discarded (and retried) in the GA but count as losses in
   `tools/paired_eval.py`.
9. A battle that dies on an exception still counts as no result (`None`, retried once); it
   is now logged (`battle error #N` with traceback, `battle_runner.battle_error_counts()`),
   but nothing stops a run whose pilot crashes on every battle: watch the logs.
10. Debt: REFACTOR B5 (lazy globals), opponent Outrage never stripped,
    `tools/watch_islands.py` stall detection by log mtime, `tools/paired_eval.py` restarts
    Showdown itself (D3), several tools hard-code
    `~/pokeMorgrad`, `src/bc_train.py::main` 154 lines (wait for the BC decision).

## Next steps (each needs the user's go-ahead)
1. On the workstation: `git pull`, `bash tools/verify.sh` (expect `ALL PASS`, 219 PASS), then
   the short test run of `runbooks/quickstart.md` Part 3 (or
   `GA_GENERATIONS=2 bash run/ga_parallel.sh 1 smoke1`).
2. Decide on a long run (`bash run/ga_parallel.sh <hours> <run_id>`; quickstart Part 4).
3. During the smoke run, also try `GA_REPLAY_LOG=1` and check `output/replay_log/`.
4. Paired check of `PASSIVE_COST` 0.30 vs 0.15 and support `all` vs off.
5. Decide on structural fitness and wiring the priors into the genome.
6. Decide keep / drop BC. If dropped: move `src/bc_*.py`, `src/state_encoder.py`,
   `tools/replay_tracker.py`, `tools/build_training_data.py` and the BC tools to `archive/`
   (removes the two remaining big files, `bc_train.py` 405 and `replay_tracker.py` 625 lines).
   If kept: split `bc_train.py::main` (154 lines) and check the checkpoint / vocab mismatch.

## Related docs
- `README.md` - docs router
- `history/README.md` - dated log
- `design/refactor-roadmap.md`, `design/decisions.md`, `design/policy.md`
