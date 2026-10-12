"""
GA v6 — island model with diversity preservation + checkpointing.
"""
import asyncio
import copy
import json
import os
import random
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.expanduser("~/project/src"))

import ga_core as CORE
import regmc_db as DB
import showdown_validator as SV
from ga_core import (
    build_random_genome,
    genome_to_text,
    text_to_genome,
    mutate,
    crossover,
    filter_legal_genomes,
    regional_pool,
    heldout_pool,
    meta_items_for,
    _SPECIES_BY_NAME,
)

CHECKPOINT_DIR = os.path.expanduser("~/project/output/checkpoints/v6")
CHAMPION_DIR = os.path.expanduser("~/project/output/champions")
SHOWDOWN_DIR = os.path.expanduser("~/pokemon-showdown")
SHOWDOWN_PORT = 8000


class Island:
    def __init__(self, name, constraints=None, seed_paths=None):
        self.name = name
        self.constraints = constraints or {}
        self.population = []
        self.fitness = []
        self.best_ever = {"fit": -1, "genome": None, "gen": None}
        self.stagnation = 0
        self.history = []
        self.seed_paths = seed_paths or []

    def init_population(self, size):
        self.population = []
        for path in self.seed_paths:
            if os.path.exists(path):
                try:
                    g = text_to_genome(open(path).read())
                    if g:
                        g = enforce_constraints(g, self.constraints)
                        self.population.append(g)
                        print(f"  [{self.name}] seeded with {os.path.basename(path)}")
                except Exception:
                    pass
        while len(self.population) < size:
            g = build_random_genome(self.constraints)
            if g:
                self.population.append(g)
        self.population = filter_legal_genomes(self.population, self.constraints)
        while len(self.population) < size:
            g = build_random_genome(self.constraints)
            if g:
                self.population.append(g)
        self.fitness = [0.0] * len(self.population)

    def to_dict(self):
        return {
            "name": self.name,
            "constraints": {str(k): v for k, v in self.constraints.items()},
            "population": self.population,
            "fitness": self.fitness,
            "best_ever": self.best_ever,
            "stagnation": self.stagnation,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, d):
        isl = cls(d["name"], {int(k): v for k, v in d.get("constraints", {}).items()})
        isl.population = d["population"]
        isl.fitness = d.get("fitness", [0.0] * len(isl.population))
        isl.best_ever = d["best_ever"]
        isl.stagnation = d.get("stagnation", 0)
        isl.history = d.get("history", [])
        return isl


def enforce_constraints(genome, constraints):
    """Rebuild any locked slot whose species doesn't match. Returns a new genome."""
    if not constraints or not genome:
        return genome
    import copy as _copy
    g = _copy.deepcopy(genome)
    for slot, want in constraints.items():
        current = g[slot].get("species") if slot < len(g) else None
        if current != want:
            mon = build_random_genome({slot: want})
            if mon and slot < len(mon):
                g[slot] = mon[slot]
    return g


def count_unique_species(island):
    seen = set()
    for g in island.population:
        if not g:
            continue
        for m in g:
            sp = _SPECIES_BY_NAME.get(m["species"])
            if sp:
                seen.add(DB.norm(sp["baseSpecies"]))
    return len(seen)


def inject_immigrants(island, n):
    if not island.fitness:
        return 0
    ranked = sorted(range(len(island.population)), key=lambda i: island.fitness[i])
    added = 0
    for idx in ranked[:n]:
        fresh = build_random_genome(island.constraints)
        if fresh:
            island.population[idx] = fresh
            island.fitness[idx] = 0.0
            added += 1
    return added


def ring_migrate(islands, n=2):
    tops = []
    for isl in islands:
        if not isl.fitness:
            tops.append([])
            continue
        ranked = sorted(range(len(isl.population)), key=lambda i: -isl.fitness[i])
        tops.append([copy.deepcopy(isl.population[i]) for i in ranked[:n]])
    for i, isl in enumerate(islands):
        incoming = tops[(i - 1) % len(islands)]
        if not incoming:
            continue
        ranked = sorted(range(len(isl.population)), key=lambda j: isl.fitness[j])
        for j, genome in enumerate(incoming):
            if j >= len(ranked):
                break
            # Enforce destination island's constraints on the incoming genome
            fixed = enforce_constraints(genome, isl.constraints)
            isl.population[ranked[-1 - j]] = fixed
            isl.fitness[ranked[-1 - j]] = 0.0


def restart_showdown():
    print(f"  [showdown] restarting on :{SHOWDOWN_PORT}...")
    subprocess.run(["pkill", "-9", "-f", f"pokemon-showdown start {SHOWDOWN_PORT}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    subprocess.Popen(
        ["node", "pokemon-showdown", "start", str(SHOWDOWN_PORT), "--no-security"],
        cwd=SHOWDOWN_DIR,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(15):
        try:
            urllib.request.urlopen(f"http://localhost:{SHOWDOWN_PORT}", timeout=2)
            print(f"  [showdown] back up")
            return True
        except Exception:
            time.sleep(1)
    print(f"  [showdown] FAILED")
    return False


def save_checkpoint(generation, islands, run_id="run1"):
    base = os.path.join(CHECKPOINT_DIR, run_id)
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"gen_{generation:04d}.json")
    state = {
        "generation": generation,
        "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
        "islands": [isl.to_dict() for isl in islands],
    }
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
    all_ckpts = sorted(f for f in os.listdir(base) if f.startswith("gen_"))
    for f in all_ckpts[:-1]:
        try:
            gen = int(f.split("_")[1].split(".")[0])
            if gen % 5 != 0:
                os.remove(os.path.join(base, f))
        except Exception:
            pass
    return path


def load_latest_checkpoint(run_id="run1"):
    base = os.path.join(CHECKPOINT_DIR, run_id)
    if not os.path.isdir(base):
        return None
    files = sorted(f for f in os.listdir(base) if f.startswith("gen_"))
    if not files:
        return None
    return os.path.join(base, files[-1])


def breed(island, immigration_rate=0.20):
    n = len(island.population)
    if n < 4:
        return
    ranked = sorted(range(n), key=lambda i: -island.fitness[i])
    n_elites = max(2, n // 3)
    elites = [enforce_constraints(copy.deepcopy(island.population[i]), island.constraints)
              for i in ranked[:n_elites]]
    new_pop = list(elites)
    while len(new_pop) < n:
        if random.random() < immigration_rate:
            fresh = build_random_genome(island.constraints)
            if fresh:
                new_pop.append(fresh)
            continue
        p1, p2 = random.sample(elites, 2)
        child = mutate(crossover(p1, p2, island.constraints), island.constraints)
        new_pop.append(child)
    new_pop = filter_legal_genomes(new_pop, island.constraints)
    while len(new_pop) < n:
        fresh = build_random_genome(island.constraints)
        if fresh:
            new_pop.append(fresh)
    island.population = new_pop[:n]
    island.fitness = [0.0] * len(island.population)


async def run_islands(
    island_specs,
    pop_per_island=10,
    generations=999,
    battles_per_genome=800,
    concurrency=3,
    immigration_rate=0.20,
    stagnation_limit=5,
    diversity_floor=15,
    migration_every=5,
    showdown_restart_every=10,
    max_hours=None,
    run_id="run1",
):
    CORE._SEM = asyncio.Semaphore(concurrency)

    islands = []
    start_gen = 0
    ckpt = load_latest_checkpoint(run_id)
    if ckpt:
        try:
            state = json.load(open(ckpt))
            islands = [Island.from_dict(d) for d in state["islands"]]
            start_gen = state["generation"]
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
            print(f"  [{isl.name}] {len(isl.population)} genomes, constraints={isl.constraints}")

    print(f"=== GA v6: {len(islands)} islands × {pop_per_island} ===")
    print(f"Gens {start_gen}..{generations}, {battles_per_genome} battles/genome")

    opp_pool = regional_pool()
    t0 = time.time()
    time_budget_seconds = (max_hours * 3600) if max_hours else None

    for gen in range(start_gen, generations):
        if time_budget_seconds and (time.time() - t0) > time_budget_seconds:
            print(f"\n=== TIME BUDGET REACHED ({max_hours}h) at gen {gen} ===")
            break
        if gen > start_gen and (gen - start_gen) % showdown_restart_every == 0 and gen > 0:
            restart_showdown()

        print(f"\n[{time.strftime('%H:%M:%S')}] === GEN {gen+1}/{generations}  "
              f"({(time.time()-t0)/60:.1f} min) ===")

        for isl in islands:
            gen_opps = random.sample(opp_pool, min(battles_per_genome, len(opp_pool)))
            fits = await asyncio.gather(*[
                CORE.evaluate(g, gen_opps, i, len(isl.population))
                for i, g in enumerate(isl.population)
            ])
            isl.fitness = list(fits)
            best_idx = max(range(len(fits)), key=lambda i: fits[i])
            gen_best = fits[best_idx]

            if gen_best > isl.best_ever["fit"]:
                isl.best_ever = {
                    "fit": gen_best,
                    "genome": copy.deepcopy(isl.population[best_idx]),
                    "gen": gen + 1,
                }
                isl.stagnation = 0
                print(f"  [{isl.name}] NEW ALL-TIME: {gen_best*100:.1f}%")
            else:
                isl.stagnation += 1

            isl.history.append({
                "gen": gen + 1,
                "best": gen_best,
                "avg": sum(fits) / len(fits) if fits else 0,
                "all_time": isl.best_ever["fit"],
                "stag": isl.stagnation,
            })

            uniq = count_unique_species(isl)
            if uniq < diversity_floor:
                added = inject_immigrants(isl, 3)
                print(f"  [{isl.name}] diversity low ({uniq}): injected {added}")

            if isl.stagnation >= stagnation_limit:
                n_restart = len(isl.population) // 2
                ranked = sorted(range(len(isl.fitness)), key=lambda i: isl.fitness[i])
                for j in ranked[:n_restart]:
                    fresh = build_random_genome(isl.constraints)
                    if fresh:
                        isl.population[j] = fresh
                        isl.fitness[j] = 0.0
                print(f"  [{isl.name}] STAGNATION: restarted {n_restart}")
                isl.stagnation = 0

            if gen < generations - 1:
                breed(isl, immigration_rate=immigration_rate)

            print(f"  [{isl.name}] gen {gen+1}: best={gen_best*100:5.1f}%  "
                  f"all-time={isl.best_ever['fit']*100:5.1f}%  stag={isl.stagnation}  "
                  f"uniq={uniq}")

        if (gen + 1) % migration_every == 0 and gen < generations - 1:
            ring_migrate(islands, n=2)
            print(f"  >> migration done at gen {gen+1}")

        ckpt_path = save_checkpoint(gen + 1, islands, run_id)
        print(f"  >> checkpoint: {os.path.basename(ckpt_path)}")

    os.makedirs(CHAMPION_DIR, exist_ok=True)
    print(f"\n=== DONE ===")
    for isl in islands:
        if isl.best_ever["genome"]:
            path = os.path.join(CHAMPION_DIR, f"ga_{run_id}_island_{isl.name}.txt")
            open(path, "w").write(genome_to_text(isl.best_ever["genome"]))
            print(f"  [{isl.name}] champion: {isl.best_ever['fit']*100:.1f}% "
                  f"(gen {isl.best_ever['gen']}) -> {path}")
