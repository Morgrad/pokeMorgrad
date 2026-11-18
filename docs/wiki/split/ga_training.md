# GA engine

The genetic algorithm that searches for counter-meta teams. Full reference:
`../src-modules.md` (section "GA engine"). Settings: `../config-and-env.md`.

## src/ga_core.py (facade)
Re-exports every historical name so `from src.ga_core import ...` keeps working
(`run_islands`, `FORMAT`, `UID_MAX`, `CHAMPION_DIR`, genome helpers, `_fitness`,
`Island`, `restart_showdown`, ...). No logic of its own.

## src/ga/ (package)
- `config.py` — `FORMAT`, `UID_MAX`, output dirs; frozen `GAConfig` (pilot / opponent,
  meta weighting, opponent sample size, early stop, Showdown port/dir), read from the
  environment once at import as `DEFAULT`.
- `genome.py` — genome = 6 mon dicts; random genomes from priors, `mutate`,
  `crossover`, `enforce_constraints`, `filter_legal_genomes` (Showdown validator),
  `regional_pool` / `heldout_pool` / train-val split.
- `fitness.py` — meta-weighted win rate; outcome i pairs with opponent i.
- `evaluator.py` — `Evaluator(config, concurrency)`: `evaluate` (50-battle head,
  abort under 15%, then tail) and `eval_on_subset` (validation slice).
- `population.py` — `Island` (init, breed, replace_worst, restart_stagnant,
  best/validation/history bookkeeping, checkpoint shape) and `ring_migrate`.
- `checkpoint.py` — `output/checkpoints/v6/<run_id>/gen_NNNN.json` and champion files.
- `engine.py` — `run_islands`: resume or init, per-generation loop, migration,
  Showdown restarts, checkpoints, champions.

## src/showdown_server.py
`is_up`, `restart`, `ensure` for the local Showdown server (port and dir passed in).

## run/
- `ga_run.py` — serial launcher, 3 islands in one process, ring migration.
- `ga_island.py` — one island per process (A seeded with the baseline team,
  B Umbreon locked in slot 0, C free); `ga_parallel.sh` starts 3 of them on ports
  8000-8002 and respawns crashed ones from their checkpoint.

## Tests
`tests/test_ga_golden.py` (golden master of a seeded fake run: stdout, checkpoints,
champions, RNG use), `test_ga_eval_order.py`, `test_ga_config.py`, `test_ga_robust.py`,
`test_island_wiring.py`.
