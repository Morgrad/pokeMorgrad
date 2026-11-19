# GA engine (src/ga/ package)

What the genetic algorithm is, how the `src/ga/` modules fit together, their public API,
invariants, settings, tests and known issues. Read this before changing anything under
`src/ga/`. Genome encoding, pools and priors: `ga-genome.md`; legality gate, locks,
mutation and crossover: `ga-genome-operators.md`. The per-generation loop of
`run_islands`, the checkpoint JSON and the champion files are in `ga-loop.md`.

Last verified against code: 2026-11-18

## 1. Purpose

The GA searches for 6-mon teams (format `gen9championsvgc2026regmc`, Reg M-C, Champions
mod, doubles, Mega legal, no Tera, EVs 0-32 per stat / 66 total) that beat a pool of real
tournament teams. Fitness = meta-weighted win rate of real battles played on a local
Showdown server: our side is piloted by `vgc` (VGCPilot, turn_sim on), the opponent by
`ladder` (heuristic + Protect / Fake Out at replay rates).

Pipeline position: data/ (team pool, priors, regmc_db) -> GA (this package) ->
`output/champions/*.txt` -> `src/eval.py` on the held-out pool.

Population model: N islands (sub-populations), each optionally locking a species into a
slot. In-process islands migrate around a ring; the parallel launcher runs one island per
process (no migration).

History (2026-11-18): the one-file `src/ga_core.py` was split into `src/ga/` (byte-identical
except the fitness-ordering fix, section 9); two intended changes followed (golden fixture
regenerated: injection AFTER breed, `ring_migrate` into the worst slots); then two pure
refactors (golden fixture unchanged): `genome.py` split into `genome` / `pools` /
`legality` / `operators`, and the `ga_core` facade deleted.

## 2. Files

| path | lines | role |
|---|---|---|
| `src/ga/__init__.py` | 5 | package docstring only |
| `src/ga/config.py` | 103 | `FORMAT`, `UID_MAX`, `CHECKPOINT_DIR`, `CHAMPION_DIR`, `PILOT_NAMES`; frozen, validated `GAConfig`; `DEFAULT` read from env at import |
| `src/ga/fitness.py` | 32 | meta-weighted win rate, shared with `src/eval.py` |
| `src/ga/evaluator.py` | 133 | `Evaluator`: plays one genome vs opponents, early stop, validation slice, `on_battles` replay hook |
| `src/ga/population.py` | 319 | `Island` (population + bookkeeping + checkpoint shape), `ring_migrate`, `_strip_species`, `_n_elites` |
| `src/ga/checkpoint.py` | 90 | checkpoint save / prune / load, champion files |
| `src/ga/engine.py` | 198 | `run_islands` driver + `_startup_checks`, `_resume_or_init`, `_evolve_island` |
| `src/ga/genome.py` | 398 | genome encoding, roster, move / item priors, random set and team build, text <-> genome (doc: `ga-genome.md`) |
| `src/ga/pools.py` | 112 | opponent pools: `regional_pool`, `heldout_pool`, `_split_train_val`, `VAL_POOL_SIZE` (doc: `ga-genome.md` section 8) |
| `src/ga/legality.py` | 192 | `filter_legal_genomes` (Showdown gate), `_enforce_composition`, `enforce_constraints` (doc: `ga-genome-operators.md`) |
| `src/ga/operators.py` | 220 | `mutate` (+ six `mutate_*` ops), `crossover`, `EV_BUDGET` (doc: `ga-genome-operators.md`) |
| `src/showdown_server.py` | 53 | `is_up`, `restart`, `ensure` for a local Showdown port (not GA-specific) |
| `src/meta_weights.py` | 91 | `team_weight`, `weighted_rate`, `load_usage` (used by fitness / startup check) |

Imports (torch-free, no cycles; full map in `../reference/architecture.md` section 5):
`engine` -> checkpoint, evaluator, population, pools, config; `population` -> genome,
legality, operators; `legality`, `operators` -> genome; `pools` -> `src.paths` only.
Outside callers import the defining module directly (no package-level re-export):
`run/ga_*.py` (`engine`), `src/eval.py` (`config`, `fitness`, `pools`),
`src/audit_before_launch.py` (`genome`, `operators`, `pools`), several tools, tests.

## 3. Key concepts and data structures

- genome: list of 6 mon dicts, e.g.
  `{"species": "Umbreon", "item": "Leftovers", "ability": "Inner Focus", "nature": "Calm",
  "evs": {"hp": 32, "def": 20, "spd": 14}, "moves": ["Snarl", "Foul Play", "Taunt", "Protect"]}`.
  EVs dict omits zero stats. Details in `ga-genome.md`.
- constraints: `{slot_index: species_name}`, e.g. `{0: "Umbreon"}`. Locked slots always hold
  that species and are never mutated or crossed away. In checkpoint JSON keys are strings
  (`{"0": "Umbreon"}`), converted back to int by `Island.from_dict`.
- fitness: float 0.0-1.0, meta-weighted win rate over battles that returned a result.
  Battles returning `None` (timeout, desync, < 3 turns, > 50 turns) are dropped from the
  denominator, not counted as losses. A genome failing the local `DB.validate_team`
  scores 0.0 without playing.
- opponent pools: `regional_pool()` = training list from `data/pool_split.json["train"]`
  (148 teams on 2026-11-18); `_split_train_val` carves a fixed 30-team validation slice
  (seed 42) -> 118 train teams; `heldout_pool()` = 100 teams for final eval only.
- best_ever: `{"fit": float, "genome": genome, "gen": int}`, all-time best by training
  fitness (primary champion). best_val_ever: same shape, best by validation-slice score
  (fallback champion only). Empty value: `{"fit": -1, "genome": None, "gen": None}`.
- stagnation: generations since best_ever last improved.
- history: per generation `{"gen", "best", "avg", "all_time", "stag"}`.
- meta weight of an opponent team: mean ladder usage of its 6 species from
  `data/species_ladder_usage.json` (unseen species count 0.02); weights are mild (train
  pool range about 0.07-0.27 when measured on 2026-10-16).

## 4. Public API

`src/ga/config.py`
- `FORMAT = "gen9championsvgc2026regmc"`, `UID_MAX = 10**9`
- `CHECKPOINT_DIR` = `output/checkpoints/v6`, `CHAMPION_DIR` = `output/champions` (via `src.paths.output_path`, honors `POKEMORGRAD_ROOT`)
- `PILOT_NAMES = ("heuristic", "bc", "doubles", "ladder", "vgc")` (same tuple as `src/player_factory.py::PILOTS`, no poke_env import)
- `GAConfig(...)` frozen dataclass (fields in section 7); `__post_init__` raises `ValueError` for a pilot not in `PILOT_NAMES`, `train_sample_size < 1`, `early_stop_win_rate` outside [0, 1]; `GAConfig.from_env(env=None)` -> GAConfig
- `DEFAULT` = `GAConfig.from_env()` evaluated once at import

`src/ga/fitness.py`
- `opp_weight(opp_text, meta_weights=True)` -> float (cached per team text; 1.0 when off)
- `weighted_fitness(outcomes, opponents, meta_weights=True)` -> `(fit, wins, valid_n)`; `(0.0, 0, 0)` if no valid outcome

`src/ga/evaluator.py`
- `Evaluator(config, concurrency)`; owns `asyncio.Semaphore(concurrency)`
- `await Evaluator.evaluate(mons, opponents, idx, total, on_battles=None)` -> float (early stop, logs one line); `on_battles(genome, fitness, outcomes, logs)` is called once after scoring with the played battles (replay logging, `docs/subsystems/battle-harness.md`)
- `await Evaluator.eval_on_subset(genome, opponents)` -> float (no early stop, no log; validation slice)

`src/ga/population.py`
- `Island(name, constraints=None, seed_paths=None)`
- `Island.init_population(size)`, `Island.breed(immigration_rate=0.20)` (elites = `_n_elites(n)` = `max(2, n // 3)`, placed first), `Island.unique_species()` -> int
- `Island.inject_fresh(n)` -> int: call right after `breed`; replaces up to `n` bred children (the LAST slots, never the elites) with fresh random genomes
- `Island.restart_stagnant()`: `inject_fresh(len(population) // 2)`, prints `STAGNATION: restarted N`, resets `stagnation` to 0
- `Island.replace_worst(n)` -> int: replaces the n lowest-fitness genomes; the engine no longer calls it (only the golden harness does)
- `Island.record_fitness(fits, gen_no)` -> `(best_idx, gen_best)`; `Island.record_validation(val_fit, genome, gen_no, gen_best)`; `Island.append_history(gen_no, gen_best, fits)`
- `Island.to_dict()` -> dict; `Island.from_dict(d)` -> Island (checkpoint shape)
- `ring_migrate(islands, n=2)`: island i gets copies of island i-1's top n into its n lowest-fitness slots (ties -> later slot first); `_strip_species(genome, species_set, constraints)` (private, re-exported by the facade)

`src/ga/checkpoint.py`
- `save_checkpoint(generation, islands, run_id="run1")` -> path; `load_latest_checkpoint(run_id="run1")` -> path or None
- `load_islands(path)` -> `(islands, generation)`; `write_champions(islands, run_id)`

`src/ga/engine.py`
- `await run_islands(island_specs, pop_per_island=10, generations=999, battles_per_genome=800, concurrency=int(env GA_CONCURRENCY or 3), immigration_rate=0.20, stagnation_limit=5, diversity_floor=15, migration_every=5, showdown_restart_every=10, max_hours=None, run_id="run1", replay_logger=None)` -> None (`replay_logger`: `src/replay_log.py::ReplayLogger`; replaced the never-working `save_filter` / `save_callback` on 2026-11-18)
- island_specs: list of `{"name": "A", "constraints": {0: "Umbreon"}, "seed_paths": [path, ...]}` (constraints / seed_paths optional)

`src/ga/genome.py`, `pools.py`, `legality.py`, `operators.py`: API in `ga-genome.md` and
`ga-genome-operators.md`. Most used: `genome.build_random_genome(constraints)`,
`genome.genome_to_text(mons)`, `genome.text_to_genome(text)`, `pools.regional_pool()`,
`pools.heldout_pool()`, `legality.filter_legal_genomes(genomes, constraints)`,
`legality.enforce_constraints(genome, constraints)`, `operators.mutate(mons, constraints)`,
`operators.crossover(p1, p2, constraints)`.

Removed facade `src/ga_core.py` (deleted 2026-11-18): every old name and what to use now
is in `../reference/ga-old-names.md`.
Also removed earlier on 2026-11-18 (no callers): `evaluate`, `_eval_on_subset`, `_SEM`.

## 5. Flow (summary; full step list in ga-loop.md)

1. `run_islands` builds `Evaluator(DEFAULT, concurrency)`, checks the meta-weight file and
   the Showdown port (fail fast).
2. Resume from the latest checkpoint of `run_id`, else build islands from specs (seed files
   first, random genomes after, Showdown legality gate).
3. Split pool: 118 train / 30 validation.
4. Per generation, islands in sequence; inside an island all genomes evaluate concurrently
   (bounded by the semaphore): sample `min(battles_per_genome, train_sample_size, len(train))`
   opponents, evaluate, record best, validate the gen-best on the 30-team slice, history,
   count unique species; then, if not the last generation: breed, and after breed either
   the stagnation restart (stagnant: half the children replaced) or the diversity rescue
   (unique species < 15: 3 children replaced). Last generation: nothing bred or injected.
5. Every `migration_every` gens: `ring_migrate`. Every gen: checkpoint. Every
   `showdown_restart_every` gens (counted from the resume point): bounce Showdown.
6. On `generations` reached or `max_hours` elapsed: `write_champions`.

## 6. Invariants (pinned by tests)

- Outcome i pairs with opponent i. Battles are gathered with `asyncio.gather` in submission
  order, never completion order (`tests/test_ga_eval_order.py`).
- Early stop: head of exactly `early_stop_min_battles` (50); abort iff head fitness < 0.15;
  the abort returns the partial head score (not 0.0). Unweighted 7/50 aborts, 8/50 plays
  the tail (`test_early_stop_threshold_boundary`).
- All randomness is the global `random` module, consumed in a fixed order. Seeded
  launchers reproduce populations; the golden test pins RNG state after each run.
- `run_islands` stdout lines, checkpoint JSON (key order, `indent=2`, pruning) and champion
  file names/contents are an interface (golden test; `run/ga_parallel.sh` respawns,
  `tools/extract_champions.py` and log greps depend on them).
- `Island.to_dict` keys and order: name, constraints, population, fitness, best_ever,
  best_val_ever, stagnation, history. `from_dict` tolerates missing optional keys.
- Battles are started through the module attribute `B.run_battle` (src.battle) and the
  validator through `SV.check_teams`; tests monkeypatch these attributes. Do not change to
  `from src.battle import run_battle`.
- `GAConfig.from_env` keeps the old variable names and parsing: only the exact string "1"
  turns `GA_META_WEIGHTS` on (`tests/test_ga_config.py`).
- `run_islands` raises `RuntimeError` mentioning `build_meta_weights` if the usage file is
  unreadable and `GA_META_WEIGHTS` is on (`tests/test_ga_robust.py`).
- Fresh genomes from the stagnation restart / diversity rescue reach the next generation,
  elites are never replaced, restart wins over rescue, the last generation injects nothing,
  migration spares elites after breed (`tests/test_ga_injection.py`).
- Unknown `GA_PILOT` / `GA_OPP` raise `ValueError`; `PILOT_NAMES == player_factory.PILOTS`
  (`tests/test_ga_config.py`).

## 7. Config, env vars, constants

`GAConfig` fields (defaults; env var read by `from_env`):

| field | default | env | meaning |
|---|---|---|---|
| battle_timeout | 20 s | - | hung battle -> None |
| min_turns | 3 | - | shorter battles -> None (desync/forfeit) |
| fitness_pilot | `vgc` | `GA_PILOT` | our pilot: one of `heuristic`, `bc`, `doubles`, `ladder`, `vgc`; anything else raises `ValueError` |
| fitness_opp | `ladder` | `GA_OPP` | opponent pilot, same names (normally `ladder` or `heuristic`) |
| meta_weights | True | `GA_META_WEIGHTS` ("1" = on) | weight outcomes by ladder usage |
| train_sample_size | 250 | `GA_TRAIN_SAMPLE` | cap on opponents per gen, must be >= 1 (pool is 118, so never binds today) |
| early_stop_min_battles | 50 | - | head batch size |
| early_stop_win_rate | 0.15 | - | abort threshold, must be in [0, 1] |
| showdown_port | 8000 | `SHOWDOWN_PORT` | port the GA probes / restarts |
| showdown_dir | `~/pokemon-showdown` | `SHOWDOWN_DIR` | Showdown checkout (via `src.paths.showdown_dir`) |

Other knobs: `GA_CONCURRENCY` (default of `run_islands(concurrency=)`, evaluated when
`src/ga/engine.py` is imported, default 3). Genome constants (`VAL_POOL_SIZE=30`,
`VAL_SPLIT_SEED=42`, `EV_BUDGET`, `MAX_REBUILD_TRIES`, ...) are in `ga-genome.md`.
`GA_PILOT=heuristic GA_OPP=heuristic` reproduces the pre-2026-10-16 environment; scores
across environments are not comparable.

## 8. Tests

Run from the repo root with the venv active (`python tests/<file>.py`); the gate is
`bash tools/verify.sh` (must end `ALL PASS`), which runs all of the files below.

| file | checks |
|---|---|
| `tests/test_ga_injection.py` | 4 tests: stagnation restart and diversity rescue genomes reach the next generation (children slots only), elites kept, restart wins over rescue, last gen injects nothing, `ring_migrate` targets the worst and spares elites after breed |
| `tests/test_pools.py` | 3 tests: real `pool_split.json` train / holdout disjoint and sized; `heldout_pool` raises on a missing, empty or overlapping split |
| `tests/test_ga_golden.py` | golden master: seeded fake run (no Showdown, fake battles, DB-only validator) of population operators + 3 `run_islands` calls (fresh, resume, resume with >50 opponents); compares stdout, checkpoints, champions, battle counts, RNG state with `tests/golden/ga_golden.json` |
| `tests/test_ga_eval_order.py` | outcomes weighted by their own opponent when battles finish in reverse order; early-abort path; 7/50 vs 8/50 threshold |
| `tests/test_ga_config.py` | 6 tests: `GAConfig.from_env` defaults, overrides, "1"-only meta flag, `DEFAULT == from_env(os.environ)` and `src.eval` uses `config.FORMAT` / `UID_MAX`, invalid values raise `ValueError`, `PILOT_NAMES` equals `player_factory.PILOTS`, one `SHOWDOWN_PORT` parser (`src/paths.py::showdown_port`) |
| `tests/test_ga_robust.py` | `showdown_server.restart` (GA port / dir from `DEFAULT`) waits / retries, `showdown_server.ensure` raises when dead, `run_islands` fails fast without usage file, `src.eval` reports the GA fitness |
| `tests/test_island_wiring.py` | 2 tests: `run/ga_island.py::SPECS` and `run/ga_run.py::ISLANDS`: A = Umbreon slot 0 + baseline seed, B = Umbreon slot 0 no seed, C free |
| `tests/test_extract_champions.py` | `tools/extract_champions.py::extract` writes primary = train best, `_train`, and `_val` files |

Golden fixture regeneration (ONLY for an intended behavior change; say so in the commit):
`PYTHONHASHSEED=0 python tests/golden/ga_harness.py --write`. The harness needs
`PYTHONHASHSEED=0` because genome code iterates sets.

## 9. Gotchas and known issues

- Fitness-ordering bug, fixed 2026-11-18: with more than 50 opponents per genome the old
  `evaluate` collected results in completion order but weighted them in opponent order
  (about 4 points of noise in the regression test). Affected `run/ga_run.py` (all 118 train
  teams per genome; STATE.md says 150, the pool size before the current split). Not
  affected: `run/ga_island.py` / `ga_parallel.sh` (50 opponents, single batch),
  `src/eval.py`, the validation slice. Old `ga_run.py` scores are not comparable.
- Settings are read at import. `GA_*` and `SHOWDOWN_PORT` must be set before the process
  starts. `SHOWDOWN_PORT` has one parser, `src/paths.py::showdown_port`, used at import by
  `GAConfig` (probe / restart) and `src/player_factory.py` (battle sockets).
- `GAConfig` validates itself: an unknown `GA_PILOT` / `GA_OPP`, `GA_TRAIN_SAMPLE` < 1 or
  `early_stop_win_rate` outside [0, 1] raise `ValueError`. Because `DEFAULT` is built at
  import, a bad env var fails at the first import of `src.ga.config` (engine, evaluator,
  checkpoint, `src/eval.py`, the launchers). Tools that only import `src.ga.pools` /
  `genome` (e.g. `tools/paired_eval.py`, `tools/test_pilots.py`) no longer read the `GA_*`
  variables at all (the removed facade imported config for every caller).
  Fixed 2026-11-18: no validation, and `make_player` silently mapped an unknown pilot name
  to `SimpleHeuristicsPlayer` (wrong environment, no error). `make_player` now raises
  `ValueError` too. Still check the `Fitness environment:` header line of every run.
- A battle that dies on an exception returns None (dropped, retried once) but since
  2026-11-18 is logged as `battle error #N (...)` with a traceback (first 3 per type) by
  `src/battle_runner.py`; grep the island log for it when `valid_n` drops.
- Champion = train best (`best_ever`) by design since 2026-10-15 (p3: train beat val on
  held-out by +1.0 / +10.6 / +6.0 points for A / B / C). The comment in
  `src/ga/engine.py::_evolve_island` and the `VAL_POOL_SIZE` comment in
  `src/ga/pools.py` say so (the latter fixed 2026-11-18). The validation slice is
  still played every gen (30 extra battles per island) and only used as a fallback.
- Stagnation restart and diversity rescue run AFTER `breed` via `Island.inject_fresh`,
  which replaces bred children (the last slots) and never the elites; restart (half the
  population) wins over rescue (3 genomes); nothing happens on the last generation.
  Fixed 2026-11-18: both ran BEFORE breed with fitness 0.0, so breed (keeps the top third)
  discarded every fresh genome; they were no-ops apart from RNG use and the stagnation
  reset. The golden fixture was regenerated deliberately for this.
- `ring_migrate` writes into the n lowest-fitness slots, ties toward the end of the list
  (key `(fitness, -index)`). The engine migrates right after breed, when every fitness is
  0.0, so migrants take the 2 elites of the source (first slots) and land in the last 2
  slots of the destination; elites are untouched. Fixed 2026-11-18: the old code wrote into
  the BEST slots (`ranked[-1-j]`) and only worked because of the all-zero tie.
- Fixed 2026-11-18 (refactor B2): a migrant entering a locked island could carry the
  locked species in a free slot; `enforce_constraints` did not repair the species clause and
  migrants skip the legality gate, so the genome scored 0.0 as INVALID once. Now
  `enforce_constraints` ends with `operators.repair_clauses` (`tests/test_genome_clauses.py`).
  Only `run/ga_run.py` migrates.
- Umbreon species leak (fixed 2026-10-12): migrants from a locked island carried Umbreon
  into free islands and diversity collapsed. `_strip_species` replaces species locked on
  the source but not on the destination.
- Battles lasting more than 50 turns are discarded (None) by `src/battle_runner.py`.

## 10. How to change safely

1. Decide if the change is meant to alter behavior. If not, `tests/test_ga_golden.py` must
   pass unchanged. If yes, regenerate the fixture and state it in the commit message.
2. Do not reorder `random` calls, stdout prints, checkpoint keys or champion names without
   a deliberate golden regeneration; launchers and `tools/extract_champions.py` depend on
   them.
3. Keep `asyncio.gather` (submission order) wherever outcomes meet weights.
4. New tunable: add a `GAConfig` field (and env var in `from_env` if needed) plus a
   `test_ga_config.py` case; per-run parameters belong in `run_islands` kwargs instead.
5. Import a name from the module that defines it (`src.ga.pools`, `src.ga.operators`, ...);
   there is no facade. Moving or renaming a name means updating its importers:
   `grep -rn "<name>" src run tools tests`. Tests monkeypatch module attributes
   (`P.build_random_genome`, `P.filter_legal_genomes` on `population`, `PL.data_path` /
   `PL._HELDOUT` on `pools`), so moving a name can silently disable a patch.
6. Run `python tests/test_ga_golden.py`, `python tests/test_ga_eval_order.py`,
   `python tests/test_ga_injection.py`, then
   `bash tools/verify.sh`. Before a long run, do a smoke: `GA_GENERATIONS=2` on one island
   (see `../runbooks/ga-run.md`).

## Related docs

- [ga-loop.md](ga-loop.md) - run_islands step by step, checkpoint JSON, champion files, log lines
- [ga-genome.md](ga-genome.md) - genome representation, priors, pools, splits
- [ga-genome-operators.md](ga-genome-operators.md) - mutate, crossover, constraints, legality gate
- [../runbooks/ga-run.md](../runbooks/ga-run.md) - launch, monitor, stop, resume, recover
- [../reference/run-scripts.md](../reference/run-scripts.md) - run/ and ops/ scripts
- [battle-harness.md](battle-harness.md) - run_battle, Showdown server, validator
- [eval.md](eval.md) - held-out evaluation of champions
- [../reference/config-and-env.md](../reference/config-and-env.md) - all env vars
- [../reference/tests.md](../reference/tests.md) - all tests, golden regeneration
- [../reference/ga-old-names.md](../reference/ga-old-names.md) - removed `ga_core` names -> current modules
