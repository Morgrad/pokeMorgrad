# GA engine: the run_islands generation loop, checkpoints and champions

Step-by-step behavior of `src/ga/engine.py::run_islands` from startup to champion files,
plus the exact checkpoint JSON shape, retention rule, champion file names and every log
line the loop prints. Read this when debugging a run, parsing logs or checkpoints, or
changing the loop. Package overview, API and invariants: `ga.md`.

Last verified against code: 2026-11-18

## Key facts (repeated from ga.md)

- Genome = list of 6 mon dicts `{species, item, ability, nature, evs, moves}`;
  constraints = `{slot: species}` locked slots.
- Fitness = meta-weighted win rate over battles that returned a result (None dropped).
  Our pilot `vgc` vs opponent pilot `ladder` by default (`GA_PILOT`, `GA_OPP`).
- Pools on 2026-11-18: 148 training teams -> 118 train + 30 validation (fixed split, seed
  42); 100 held-out teams are never used by the GA.
- Settings are read from the environment once at import (`src/ga/config.py::DEFAULT`).

## 1. Startup

1. `cfg = C.DEFAULT`; `evaluator = Evaluator(cfg, concurrency)` (semaphore = max
   simultaneous battles in this process).
2. `_startup_checks(cfg)`:
   - if `cfg.meta_weights`: `MW.load_usage()`; on OSError/ValueError/KeyError raise
     `RuntimeError("meta-weight usage file ... unreadable ...; run tools/build_meta_weights.py or set GA_META_WEIGHTS=0")`.
   - `showdown_server.ensure(cfg.showdown_port, cfg.showdown_dir)`: if nothing answers HTTP
     on the port, `restart` (kill + relaunch, up to 2 tries, 60 s wait each); raises
     `RuntimeError` if it cannot. The process then exits non-zero, which is what makes
     `run/ga_parallel.sh` respawn it.
3. `_resume_or_init(island_specs, pop_per_island, run_id)`:
   - `load_latest_checkpoint(run_id)` = highest `gen_NNNN.json` in
     `output/checkpoints/v6/<run_id>/`. If found, `load_islands` -> prints
     `RESUMED from <path> at gen <N>`. A corrupt file prints
     `checkpoint load failed (<err>); fresh start` and falls through.
   - Resuming ignores `island_specs` and `pop_per_island` entirely: islands, constraints and
     populations come from the checkpoint. `seed_paths` are not stored in checkpoints.
   - Fresh: prints `Initializing islands...`; per spec `Island(name, constraints,
     seed_paths).init_population(pop_per_island)` and prints
     `  [A] 10 genomes, constraints={0: 'Umbreon'}`. `init_population` loads each existing
     seed file via `text_to_genome` + `enforce_constraints` (prints
     `  [A] seeded with baseline_team.txt`), tops up with random genomes, runs the Showdown
     legality gate, tops up again (second top-up is not gated).
4. Prints the header: `=== GA: <n> islands x <pop> ===` (the real line uses the Unicode
   multiplication sign; grep for `=== GA:`), `Gens <start>..<generations>, <b> battles/genome`,
   `Fitness environment: our pilot=vgc  opponent pilot=ladder  meta-weighted=True`,
   `Fitness pool: 118 teams   Validation slice: 30 teams`.
5. `train_pool, val_pool = _split_train_val(regional_pool())`; `t0 = time.time()`.

## 2. Per generation (`for gen in range(start_gen, generations)`)

1. Time budget: if `max_hours` and elapsed > budget -> print
   `=== TIME BUDGET REACHED (<h>h) at gen <gen> ===` and leave the loop. Checked only at the
   top of a generation, so a run overshoots by up to one generation. `t0` is the process
   start, so after a respawn the budget restarts (ga_parallel.sh passes the remaining hours).
2. Showdown bounce: if `gen > start_gen` and `(gen - start_gen) % showdown_restart_every == 0`
   -> `showdown_server.restart(port, dir)` (prints `  [showdown] restarting on :<port>
   (attempt 1/2)...`, `  [showdown] back up` or `  [showdown] FAILED`). Failure raises
   `RuntimeError` (process exits non-zero). Reason: the Node server leaks memory/sockets
   over thousands of battles.
3. Print `[HH:MM:SS] === GEN <gen+1>/<generations>  (<m> min) ===`.
4. For each island in order (sequential), `_evolve_island`:
   1. `n_sample = min(battles_per_genome, cfg.train_sample_size, len(train_pool))`;
      `gen_opps = random.sample(train_pool, n_sample)`. Same opponents for every genome of
      the island this generation. `run/ga_island.py`: 50 of 118. `run/ga_run.py`
      (800 requested): all 118, shuffled.
   2. All genomes evaluated concurrently with `asyncio.gather` (`Evaluator.evaluate`):
      - `DB.validate_team` fails -> prints `  [i/total] INVALID: [...]`, fitness 0.0.
      - `len(opponents) <= 50`: one batch, fitness over all.
      - otherwise head = first 50 opponents; if head fitness < 0.15 -> prints the score
        line with `early-abort` and returns the head score; else plays the tail and scores
        head + tail together in opponent order.
      - Score line: `  [HH:MM:SS]  3/10   48.2%  (24W/50)  Umbreon / Salamence / ...`
        followed by an empty line.
      - Only with a `replay_logger` (`GA_REPLAY_LOG=1` in `run/ga_island.py`): before the
        gather `start_generation(island, gen+1)`, each genome reports its battles through
        `on_battles`, and after it `  [A] replay log: N battles saved` (see
        `docs/subsystems/battle-harness.md`). Uses no global randomness: results are the same.
   3. `isl.record_fitness(fits, gen+1)`: stores fitness, picks the gen best; a new
      all-time high replaces `best_ever` (deep copy), resets stagnation and prints
      `  [A] NEW ALL-TIME (train): 61.3%`; otherwise `stagnation += 1`.
   4. Validation: `eval_on_subset(gen-best genome, val_pool)` (30 battles, no early stop);
      `record_validation` keeps a new high in `best_val_ever` and prints
      `  [A] NEW VAL BEST: 63.3% (train 61.3%)`.
   5. `append_history(gen+1, gen_best, fits)`.
   6. `uniq = unique_species()` (distinct base species across the island) and
      `stagnant = stagnation >= stagnation_limit` (5), both computed BEFORE breeding.
   7. Only if NOT the last generation (`gen < generations - 1`); on the last generation
      nothing is bred or injected:
      1. Breed: elites = top `_n_elites(n)` = `max(2, n // 3)` by fitness (3 of 10),
         constraint-enforced copies placed first; fill to n with immigrants (probability
         `immigration_rate`, 0.20) or `mutate(crossover(p1, p2))` of two random elites;
         legality gate; top up; fitness reset to 0.0.
      2. Then exactly one of:
         - stagnant -> `restart_stagnant()`: `inject_fresh(n // 2)` replaces half the
           population (the last slots = bred children, never the elites), prints
           `  [A] STAGNATION: restarted <k>`, resets stagnation to 0.
         - else if `uniq < diversity_floor` (15) -> `inject_fresh(3)`, prints
           `  [A] diversity low (<uniq>): injected <k>`.
      `inject_fresh(n)` caps n at `size - _n_elites(size)`, so elites always survive.
      Fixed 2026-11-18: restart and rescue used to run BEFORE breed (via `replace_worst`)
      with fitness 0.0, so breed discarded every fresh genome (both were no-ops).
   8. Print `  [A] gen <g>: best= 48.2%  all-time= 61.3%  stag=2  uniq=21` (`uniq` is the
      pre-breed count; `stag` is 0 after a restart).
5. Migration: if `(gen + 1) % migration_every == 0` and not the last gen ->
   `ring_migrate(islands, n=2)`, print `  >> migration done at gen <gen+1>`. Island i
   receives copies of island i-1's top 2 into its 2 lowest-fitness slots (ties broken
   toward the end of the list, key `(fitness, -index)`), constraint-enforced, with species
   locked on the source but not here stripped (`_strip_species`). Right after breed all
   fitness is 0.0, so the source's elites (first slots) land in the destination's last 2
   slots and its elites are untouched. Fixed 2026-11-18: destinations were the BEST slots.
   With one island (ga_island.py, `migration_every=999`) it never fires in practice.
6. `save_checkpoint(gen + 1, islands, run_id)`, print `  >> checkpoint: gen_<NNNN>.json`.

## 3. End of run

`os.makedirs(CHAMPION_DIR)`, print `=== DONE ===`, then `write_champions(islands, run_id)`.
Champion files are written ONLY here: a run killed before this point leaves none (use
`tools/extract_champions.py`, see `../runbooks/ga-run.md`). `=== DONE ===` is printed
before the champion lines.

## 4. Checkpoint files

Path: `output/checkpoints/v6/<run_id>/gen_NNNN.json` (`NNNN` = generations completed,
zero-padded to 4). Written after every generation. Retention: after each save, every older
file whose number is not a multiple of 5 is deleted; the newest is always kept. Disk use
stays bounded; a killed run loses at most the generation in progress.

Shape (`json.dump(..., indent=2)`, key order fixed):

```
{
  "generation": 12,
  "saved": "2026-11-18 14:03:11",
  "islands": [
    {
      "name": "A",
      "constraints": {"0": "Umbreon"},
      "population": [ [ {mon}, ... 6 ], ... pop ],
      "fitness": [0.0, ...],
      "best_ever": {"fit": 0.613, "genome": [ {mon} x6 ], "gen": 9},
      "best_val_ever": {"fit": 0.633, "genome": [...], "gen": 9},
      "stagnation": 3,
      "history": [{"gen": 1, "best": 0.41, "avg": 0.22, "all_time": 0.41, "stag": 0}, ...]
    }
  ]
}
```

- `population` / `fitness` are the state AFTER breeding, so `fitness` is all 0.0 except
  after the last generation (no breed) or right after a migration (migrants 0.0 too).
- Parallel runs use run_id `<run_id>_<X>` (e.g. `p2_A`), one island per file.
- Resume = relaunch with the same run_id. To restart fresh, use a new run_id (or delete the
  directory; `run/ga_overnight.sh` does `rm -rf` of run1/run2).
- `tools/extract_champions.py` reads `islands[*].best_ever` / `best_val_ever` from the
  latest checkpoint and applies the same rule as `write_champions` (below).

## 5. Champion files

`src/ga/checkpoint.py::write_champions`, per island, in `output/champions/`:

| file | content |
|---|---|
| `ga_<run_id>_island_<name>.txt` | primary: `best_ever` (train best); `best_val_ever` only if no train genome exists |
| `ga_<run_id>_island_<name>_train.txt` | `best_ever` (identical to the primary in practice) |

Log lines: `  [A] champion (train): 61.3% (train best 61.3%) -> <path>` and
`  [A] champion (train): 61.3% -> <path>`. Content is `genome_to_text` (Showdown paste,
`Level: 50`, no Tera line). For parallel runs the run_id is `<run_id>_<X>`, so the engine
writes `ga_p2_A_island_A.txt`; `run/ga_parallel.sh` renames only the primary to
`ga_p2_island_A.txt` at the end (the `_train` file keeps the doubled name).

`write_champions` does NOT write a validation file. `tools/extract_champions.py <run>`
(for parallel runs killed before `=== DONE ===`) reads the latest checkpoint of each
`<run>_<X>` directory and writes `ga_<run>_island_<X>.txt` (same rule: train best, val best
only if no train genome), `ga_<run>_island_<X>_train.txt`, and
`ga_<run>_island_<X>_val.txt` = `best_val_ever`.

## 6. Cost and throughput (measured, dated)

- Battles per island per generation = pop x n_sample + 30 validation (minus early-abort
  tails). `ga_island.py`: 10 x 50 + 30 = 530. `ga_run.py`: up to 10 x 118 + 30 = 1210 per
  island, 3 islands in sequence.
- 2026-10-16 smoke (3 islands on 8000-8002, concurrency 8, vgc vs ladder, 120 opponents per
  genome): about 10 min per generation per island, about 120 battles/min per island.
- 2026-10-14 (old heuristic environment): parallel = 2.78x serial throughput (72.4
  battles/s across 3 processes vs about 26 serial); a 2.5 h parallel run reached 130-148
  gens per island vs 30-50 serial. Not comparable with today's slower pilot.
- Early stop: aborts about 85% of the wall time for a bottom-third genome. At 50 battles
  the Wilson 95% CI is about +-10 points, so a genome truly at 30%+ has < 1% chance to show
  < 15%.

## Related docs

- [ga.md](ga.md) - package overview, API, invariants, gotchas
- [ga-genome.md](ga-genome.md) - genome representation, pools
- [ga-genome-operators.md](ga-genome-operators.md) - breed internals: mutate, crossover, legality gate
- [../runbooks/ga-run.md](../runbooks/ga-run.md) - launch, monitor, stop, resume, recover champions
- [../reference/run-scripts.md](../reference/run-scripts.md) - launchers and their arguments
- [battle-harness.md](battle-harness.md) - run_battle, retries, Showdown server
