# Docs router

Which docs to load for which task. Every doc is a self-contained file of at most ~270 lines
(about 3-5k tokens), so a small-context agent can load 2-3 of them next to the code it edits.
Start with `../AGENTS.md` (project map, hard rules, commands). Current status: `STATE.md`.
Last verified against code: 2026-11-18

## Task -> files to load
| Task | Load | Then look at code |
|---|---|---|
| Understand the project end to end | `reference/architecture.md` | - |
| Change the GA loop (generations, islands, migration, restarts, early stop, checkpoints) | `subsystems/ga.md`, `subsystems/ga-loop.md` | `src/ga/engine.py`, `population.py`, `evaluator.py` |
| Change genomes (random teams, mutation, crossover, constraints, locks, legality, pools) | `subsystems/ga-genome.md`, `subsystems/ga-genome-operators.md` | `src/ga/genome.py`, `operators.py`, `legality.py`, `pools.py` |
| Change fitness (meta weights, weighted win rate) | `subsystems/ga.md`, `subsystems/foundation.md` | `src/ga/fitness.py`, `src/meta_weights.py` |
| Set up a machine and run the GA for the first time / explain it to someone new | `runbooks/quickstart.md` | - |
| Run / monitor / stop / resume a GA | `runbooks/ga-run.md`, `reference/run-scripts.md` | `run/` |
| How one battle runs (poke-env, accounts, retries, timeouts, validator) | `subsystems/battle-harness.md` | `src/battle_runner.py`, `player_factory.py` |
| Change how a pilot picks moves | `subsystems/pilots.md` (+ `pilots-support.md` for support moves) | `src/doubles_pilot.py`, `vgc_pilot.py`, `pilot_*.py` |
| Change the one-turn simulator / lookahead | `subsystems/turn-sim.md` | `src/turn_sim.py` (scenarios, foe model), `src/turn_sim_resolve.py` (one scenario in move order), `turn_sim_types.py`, `turn_sim_lookahead.py` |
| Damage, speed, opponent-set or Mega models | `subsystems/damage.md` | `src/damage.py`, `speed_model.py`, `opp_model.py`, `mega_model.py` |
| What the pilot remembers in battle; opponent action rates | `subsystems/battle-memory.md` | `src/battle_memory*.py`, `opp_actions.py` |
| Paths, canonical format DB, team validation | `subsystems/foundation.md` | `src/paths.py`, `regmc_db.py` |
| Behavior-cloning pilot | `subsystems/bc.md`, `runbooks/bc-training.md` | `src/bc_*.py`, `state_encoder.py` |
| Evaluate a team / compare pilots / paired runs | `runbooks/evaluation.md`, `subsystems/eval.md` | `src/eval.py`, `tools/paired_eval.py` |
| Data: scraping, priors, DB rebuild, pool swap | `runbooks/data-pipeline.md`, `reference/data-files.md` | `tools/` |
| What a tool in `tools/` does | `reference/tools.md` (index) -> `tools-data.md` or `tools-ops.md` | the tool |
| Environment variables and constants | `reference/config-and-env.md`, `config-and-env-constants.md` | - |
| Tests: what exists, how to run, golden master | `reference/tests.md` | `tests/` |
| Before a run: health check, preflight, audit | `runbooks/health-check.md` | `tools/preflight.py`, `src/audit_before_launch.py` |
| Showdown servers (start, ports, restart) | `runbooks/showdown.md` | `src/showdown_server.py`, `ops/` |
| Something broke | `runbooks/failure-modes.md`, then `runbooks/diagnostics.md` | - |
| Host setup: WSL2, ROCm 7900 XTX, venvs, local LLM next to GPU jobs | `runbooks/environment.md` | - |
| Rules: what needs approval, promotion rule, commits | `design/policy.md` | `../.clinerules/00-core-rules.md` |
| Why something is the way it is | `design/decisions.md` | - |
| Planned refactors and their status | `design/refactor-roadmap.md` | - |
| Structural-fitness proposal (team-value surrogate) | `design/structural-fitness.md`, `structural-fitness-priors.md` | - |
| A term or constant you do not know | `reference/glossary.md`, `glossary-constants.md` | - |
| Old code or notes use `ga_core` / `G.<name>` | `reference/ga-old-names.md` | - |
| What happened on a past date | `history/README.md` (index), then one period file | - |

## Folders
- `subsystems/` - one file per part of `src/`: purpose, files, API, flow, invariants, config,
  tests, gotchas, how to change it safely.
- `reference/` - lookup tables: architecture and dependency map, env vars, constants, data
  files, tools, tests, run scripts, glossary, GA old names.
- `runbooks/` - step-by-step procedures with copy-paste commands.
- `design/` - policy, decisions, roadmap, proposals.
- `history/` - the dated project log, verbatim (code paths there are historical). Read only
  when asked about the past; it is about 2,600 lines.

## Conventions
- Code is cited as `path/file.py::symbol`; find it with `grep -n "def symbol" -r src`.
  No line numbers (they drift).
- Commands run from the repo root with the venv active (`source .venv/bin/activate`, or
  `source ~/venv-pokemorgad/bin/activate` on the original workstation).
- `Unverified:` marks a claim nobody could check against code or data.
- When code changes, update the matching subsystem doc and `STATE.md` in the same commit.

## Related docs
- `../AGENTS.md` - entry point
- `STATE.md` - current status, open issues, next steps
