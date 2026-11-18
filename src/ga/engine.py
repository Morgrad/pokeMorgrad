"""
GA driver: run_islands evolves N islands with migration, restarts and checkpoints.

Per generation, per island: sample opponents, evaluate every genome, update the
all-time / validation bests, rescue diversity or restart a stagnant island, then
breed. Every `migration_every` gens the ring migrates; every
`showdown_restart_every` gens the Showdown server is bounced. Each generation is
checkpointed, so a multi-hour run survives a crash and resumes where it stopped.

run_islands' signature, stdout and output files are an interface: the launchers
(run/ga_run.py, run/ga_island.py), ga_parallel.sh respawns and the logs depend on
them. tests/test_ga_golden.py pins all three.
"""
import asyncio
import os
import random
import time
from dataclasses import dataclass

from src import meta_weights as MW
from src import showdown_server
from src.ga import config as C
from src.ga.checkpoint import load_islands, load_latest_checkpoint, save_checkpoint, write_champions
from src.ga.evaluator import Evaluator
from src.ga.genome import _split_train_val, regional_pool
from src.ga.population import Island, ring_migrate


@dataclass(frozen=True)
class _Generation:
    """Per-run knobs the per-island step needs (all from run_islands' arguments)."""
    number: int              # 0-based generation index
    last: int                # `generations` argument (exclusive upper bound)
    battles_per_genome: int
    immigration_rate: float
    stagnation_limit: int
    diversity_floor: int
    save_filter: object
    save_callback: object


def _startup_checks(cfg):
    """Fail fast on a missing meta-weight file or a dead Showdown server."""
    if cfg.meta_weights:   # fail now, not on the first evaluation
        try:
            MW.load_usage()
        except (OSError, ValueError, KeyError) as e:
            raise RuntimeError(f"meta-weight usage file {MW.USAGE_PATH} unreadable ({e}); "
                               "run tools/build_meta_weights.py or set GA_META_WEIGHTS=0") from e
    # The island exits non-zero on a dead server, so run/ga_parallel.sh respawns it
    # from the last checkpoint instead of the GA scoring every genome 0.0.
    showdown_server.ensure(cfg.showdown_port, cfg.showdown_dir)


def _resume_or_init(island_specs, pop_per_island, run_id):
    """(islands, start_gen): from the latest checkpoint of `run_id`, else fresh from specs."""
    islands, start_gen = [], 0
    ckpt = load_latest_checkpoint(run_id)
    if ckpt:
        try:
            islands, start_gen = load_islands(ckpt)
            print(f"RESUMED from {ckpt} at gen {start_gen}")
        except Exception as e:
            print(f"checkpoint load failed ({e}); fresh start")
            islands = []

    if not islands:
        print("Initializing islands...")
        for spec in island_specs:
            isl = Island(
                spec["name"],
                constraints=spec.get("constraints", {}),
                seed_paths=spec.get("seed_paths", []),
            )
            isl.init_population(pop_per_island)
            islands.append(isl)
            print(f"  [{isl.name}] {len(isl.population)} genomes, "
                  f"constraints={isl.constraints}")
    return islands, start_gen


async def _evolve_island(isl, g, evaluator, train_pool, val_pool):
    """One generation of one island: evaluate, track bests, rescue, breed."""
    n_sample = min(g.battles_per_genome, evaluator.config.train_sample_size, len(train_pool))
    gen_opps = random.sample(train_pool, n_sample)
    fits = await asyncio.gather(*[
        evaluator.evaluate(genome, gen_opps, i, len(isl.population),
                           save_filter=g.save_filter, save_callback=g.save_callback)
        for i, genome in enumerate(isl.population)
    ])
    best_idx, gen_best = isl.record_fitness(fits, g.number + 1)

    # Champion selection: evaluate this generation's training-best on
    # the held-back validation slice. Champions come from
    # best_val_ever, not best_ever — Island B (2026-10-13) showed
    # the training best overfits by ~10 points on held-out.
    val_fit = await evaluator.eval_on_subset(isl.population[best_idx], val_pool)
    isl.record_validation(val_fit, isl.population[best_idx], g.number + 1, gen_best)
    isl.append_history(g.number + 1, gen_best, fits)

    uniq = isl.unique_species()
    if uniq < g.diversity_floor:
        added = isl.replace_worst(3)
        print(f"  [{isl.name}] diversity low ({uniq}): injected {added}")

    if isl.stagnation >= g.stagnation_limit:
        isl.restart_stagnant()

    if g.number < g.last - 1:
        isl.breed(immigration_rate=g.immigration_rate)

    print(f"  [{isl.name}] gen {g.number+1}: best={gen_best*100:5.1f}%  "
          f"all-time={isl.best_ever['fit']*100:5.1f}%  stag={isl.stagnation}  "
          f"uniq={uniq}")


async def run_islands(
    island_specs,
    pop_per_island=10,
    generations=999,
    battles_per_genome=800,
    concurrency=int(os.environ.get("GA_CONCURRENCY", "3")),
    immigration_rate=0.20,
    stagnation_limit=5,
    diversity_floor=15,
    migration_every=5,
    showdown_restart_every=10,
    max_hours=None,
    run_id="run1",
    save_filter=None,
    save_callback=None,
):
    """Production GA driver: evolve N islands with migration, restart, checkpoints.

    Resumes from the latest checkpoint for `run_id` if one exists, else builds
    islands from island_specs. Each generation, per island: evaluate fitness,
    track the all-time best, rescue diversity (replace_worst) or escape local
    optima (stagnation restart), then breed. Every `migration_every` gens the ring
    migrates; every `showdown_restart_every` gens the server is bounced. Stops at
    `generations` or when `max_hours` elapses. Writes a champion file per island.
    """
    cfg = C.DEFAULT
    evaluator = Evaluator(cfg, concurrency)
    _startup_checks(cfg)

    islands, start_gen = _resume_or_init(island_specs, pop_per_island, run_id)

    print(f"=== GA: {len(islands)} islands × {pop_per_island} ===")
    print(f"Gens {start_gen}..{generations}, {battles_per_genome} battles/genome")

    train_pool, val_pool = _split_train_val(regional_pool())
    print(f"Fitness environment: our pilot={cfg.fitness_pilot}  opponent pilot={cfg.fitness_opp}  "
          f"meta-weighted={cfg.meta_weights}")
    print(f"Fitness pool: {len(train_pool)} teams   "
          f"Validation slice: {len(val_pool)} teams")
    t0 = time.time()
    time_budget_seconds = (max_hours * 3600) if max_hours else None

    for gen in range(start_gen, generations):
        if time_budget_seconds and (time.time() - t0) > time_budget_seconds:
            print(f"\n=== TIME BUDGET REACHED ({max_hours}h) at gen {gen} ===")
            break
        if gen > start_gen and (gen - start_gen) % showdown_restart_every == 0 and gen > 0:
            if not showdown_server.restart(cfg.showdown_port, cfg.showdown_dir):
                raise RuntimeError(
                    f"Showdown on :{cfg.showdown_port} did not come back after a restart")

        print(f"\n[{time.strftime('%H:%M:%S')}] === GEN {gen+1}/{generations}  "
              f"({(time.time()-t0)/60:.1f} min) ===")

        g = _Generation(gen, generations, battles_per_genome, immigration_rate,
                        stagnation_limit, diversity_floor, save_filter, save_callback)
        for isl in islands:
            await _evolve_island(isl, g, evaluator, train_pool, val_pool)

        if (gen + 1) % migration_every == 0 and gen < generations - 1:
            ring_migrate(islands, n=2)
            print(f"  >> migration done at gen {gen+1}")

        ckpt_path = save_checkpoint(gen + 1, islands, run_id)
        print(f"  >> checkpoint: {os.path.basename(ckpt_path)}")

    os.makedirs(C.CHAMPION_DIR, exist_ok=True)
    print("\n=== DONE ===")
    write_champions(islands, run_id)
