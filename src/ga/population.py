"""
Island model: one GA sub-population per Island, plus ring migration between them.

The production GA runs N semi-isolated populations ("islands"), each optionally
locking a different species. Top genomes migrate around a ring every few
generations; stagnant islands restart their worst half. Island.to_dict/from_dict
is the on-disk checkpoint shape (src/ga/checkpoint.py) — do not change it.

All randomness comes from the global `random` module, in a fixed order: seeded
launchers (run/ga_run.py, run/ga_island.py) rely on that for reproducible
populations. tests/test_ga_golden.py pins it.
"""
from __future__ import annotations

import copy
import os
import random

from src import regmc_db as DB
from src.ga.genome import (
    _BASE_SPECIES,
    _SPECIES_BY_NAME,
    _fresh_mon,
    build_random_genome,
    text_to_genome,
)
from src.ga.legality import enforce_constraints, filter_legal_genomes
from src.ga.operators import _used_bases, _used_items, crossover, mutate


def _top_up(population, size, constraints):
    """Append fresh random genomes until `population` has `size` entries (in place)."""
    while len(population) < size:
        g = build_random_genome(constraints)
        if g:
            population.append(g)


def _empty_best():
    return {"fit": -1, "genome": None, "gen": None}


def _n_elites(n):
    """How many top genomes breed() keeps unchanged: the top third, at least 2."""
    return max(2, n // 3)


class Island:
    """One GA sub-population plus its evolve/checkpoint bookkeeping.

    constraints   = {slot: species} locked for this island (may be empty).
    best_ever     = all-time best genome by training fitness (survives stagnation
                    restarts; the primary champion).
    best_val_ever = best genome by validation-slice score (champion fallback).
    stagnation    = generations since best_ever improved (drives the restart).
    history       = one dict per generation: gen, best, avg, all_time, stag.
    """

    def __init__(self, name, constraints=None, seed_paths=None):
        self.name = name
        self.constraints = constraints or {}
        self.population = []
        self.fitness = []
        self.best_ever = _empty_best()
        self.best_val_ever = _empty_best()
        self.stagnation = 0
        self.history = []
        self.seed_paths = seed_paths or []

    # --- population -----------------------------------------------------------

    def init_population(self, size):
        """Fill the population to `size`: seed files first, then random genomes.

        Runs the legality gate once, then tops up again (the gate can drop
        genomes it couldn't legalize). The final list may still be short if the
        roster can't produce `size` legal genomes, which is acceptable.
        """
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
        _top_up(self.population, size, self.constraints)
        self.population = filter_legal_genomes(self.population, self.constraints)
        _top_up(self.population, size, self.constraints)
        self.fitness = [0.0] * len(self.population)

    def breed(self, immigration_rate=0.20):
        """Produce the next generation: elites + crossovers + immigrants.

        Keeps the top third (≥2) as elites, then fills the rest by either injecting a
        fresh random genome (probability immigration_rate, for ongoing diversity) or
        breeding a mutated crossover of two elites. The new population is legality-
        gated and topped back up to the original size. Fitness resets to zero.
        """
        n = len(self.population)
        if n < 4:
            return
        ranked = sorted(range(n), key=lambda i: -self.fitness[i])
        n_elites = _n_elites(n)
        elites = [enforce_constraints(copy.deepcopy(self.population[i]), self.constraints)
                  for i in ranked[:n_elites]]
        new_pop = list(elites)
        while len(new_pop) < n:
            if random.random() < immigration_rate:
                fresh = build_random_genome(self.constraints)
                if fresh:
                    new_pop.append(fresh)
                continue
            p1, p2 = random.sample(elites, 2)
            child = mutate(crossover(p1, p2, self.constraints), self.constraints)
            new_pop.append(child)
        new_pop = filter_legal_genomes(new_pop, self.constraints)
        _top_up(new_pop, n, self.constraints)
        self.population = new_pop[:n]
        self.fitness = [0.0] * len(self.population)

    def replace_worst(self, n):
        """Replace the `n` lowest-fitness genomes with fresh random ones. Returns count replaced.

        Used for the diversity rescue (a few immigrants) and the stagnation restart
        (worst half). Targets the lowest-fitness slots so a contender is never evicted.
        """
        if not self.fitness:
            return 0
        ranked = sorted(range(len(self.population)), key=lambda i: self.fitness[i])
        replaced = 0
        for idx in ranked[:n]:
            fresh = build_random_genome(self.constraints)
            if fresh:
                self.population[idx] = fresh
                self.fitness[idx] = 0.0
                replaced += 1
        return replaced

    def inject_fresh(self, n):
        """Replace up to `n` bred children with fresh random genomes. Returns the count.

        Call right after breed(): breed() puts the elites first and the children after
        them, so the tail is replaced and the elites are never touched. (Injecting BEFORE
        breed() does not work: the fresh genomes have fitness 0 and breed() keeps only the
        top third by fitness, so they were always discarded - the bug fixed 2026-11-18.)
        """
        size = len(self.population)
        n = max(0, min(n, size - _n_elites(size)))
        replaced = 0
        for idx in range(size - n, size):
            fresh = build_random_genome(self.constraints)
            if fresh:
                self.population[idx] = fresh
                if idx < len(self.fitness):
                    self.fitness[idx] = 0.0
                replaced += 1
        return replaced

    def restart_stagnant(self):
        """Escape a local optimum, right after breed(): replace half the population with
        fresh random genomes (children only, the elites stay) and reset the stagnation counter."""
        replaced = self.inject_fresh(len(self.population) // 2)
        print(f"  [{self.name}] STAGNATION: restarted {replaced}")
        self.stagnation = 0

    def unique_species(self):
        """Count distinct base species across the island — the diversity metric."""
        seen = set()
        for g in self.population:
            if not g:
                continue
            for m in g:
                sp = _SPECIES_BY_NAME.get(m["species"])
                if sp:
                    seen.add(DB.norm(sp["baseSpecies"]))
        return len(seen)

    # --- per-generation bookkeeping -------------------------------------------

    def record_fitness(self, fits, gen_no):
        """Store this generation's scores and update best_ever / stagnation.

        Returns (best_idx, gen_best). `gen_no` is the 1-based generation number.
        """
        self.fitness = list(fits)
        best_idx = max(range(len(fits)), key=lambda i: fits[i])
        gen_best = fits[best_idx]
        if gen_best > self.best_ever["fit"]:
            self.best_ever = {
                "fit": gen_best,
                "genome": copy.deepcopy(self.population[best_idx]),
                "gen": gen_no,
            }
            self.stagnation = 0
            print(f"  [{self.name}] NEW ALL-TIME (train): {gen_best*100:.1f}%")
        else:
            self.stagnation += 1
        return best_idx, gen_best

    def record_validation(self, val_fit, genome, gen_no, gen_best):
        """Keep `genome` as best_val_ever if its validation score is a new high."""
        if val_fit > self.best_val_ever["fit"]:
            self.best_val_ever = {
                "fit": val_fit,
                "genome": copy.deepcopy(genome),
                "gen": gen_no,
            }
            print(f"  [{self.name}] NEW VAL BEST: {val_fit*100:.1f}% "
                  f"(train {gen_best*100:.1f}%)")

    def append_history(self, gen_no, gen_best, fits):
        self.history.append({
            "gen": gen_no,
            "best": gen_best,
            "avg": sum(fits) / len(fits) if fits else 0,
            "all_time": self.best_ever["fit"],
            "stag": self.stagnation,
        })

    # --- checkpoint shape (do not change: resumes depend on it) -------------------

    def to_dict(self):
        """Serialize to the JSON checkpoint shape (constraint keys → str for JSON)."""
        return {
            "name": self.name,
            "constraints": {str(k): v for k, v in self.constraints.items()},
            "population": self.population,
            "fitness": self.fitness,
            "best_ever": self.best_ever,
            "best_val_ever": self.best_val_ever,
            "stagnation": self.stagnation,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, d):
        """Rebuild an Island from a checkpoint dict (constraint keys → int again)."""
        isl = cls(d["name"], {int(k): v for k, v in d.get("constraints", {}).items()})
        isl.population = d["population"]
        isl.fitness = d.get("fitness", [0.0] * len(isl.population))
        isl.best_ever = d["best_ever"]
        isl.best_val_ever = d.get("best_val_ever", _empty_best())
        isl.stagnation = d.get("stagnation", 0)
        isl.history = d.get("history", [])
        return isl


def _strip_species(genome, species_set, constraints):
    """Replace any mon whose species is in species_set with a fresh random mon.
    Preserves species + item clauses. Never touches constrained slots.
    """
    if not genome:
        return genome
    stripped = copy.deepcopy(genome)

    for slot, mon in enumerate(stripped):
        if slot in constraints:
            continue
        if mon and mon.get("species") in species_set:
            # species / items of the OTHER slots (shared helpers in src/ga/operators.py)
            used_items = _used_items(stripped, exclude_slot=slot)
            used_bases = _used_bases(stripped, exclude_slot=slot)
            cands = [s["name"] for s in _BASE_SPECIES
                     if s["name"] not in species_set
                     and DB.norm(s["baseSpecies"]) not in used_bases
                     and len(s["moves"]) >= 4]
            if not cands:
                continue
            new_sp = random.choice(cands)
            fresh = _fresh_mon(new_sp, used_items)
            if fresh:
                stripped[slot] = fresh
    return stripped


def ring_migrate(islands, n=2):
    """Copy each island's top `n` genomes into the next island's worst `n` slots.

    Migration runs around a ring (island i receives from island i-1). Incoming
    genomes are constraint-enforced for the destination, and any species that is
    locked on the SOURCE but not here is stripped — see the inline note below for
    the diversity-collapse bug that motivated it.

    Ties: the engine migrates right after breed(), when every fitness is 0.0. Then
    the "top n" are the first n slots (the elites) and the "worst n" are the last n
    slots (bred children), so elites are never overwritten. Before 2026-11-18 the
    destination slots were picked from the wrong end of the ranking (best instead
    of worst), which only went unnoticed because of that all-zero tie.
    """
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
        # worst first; equal fitness -> later slot first (bred children before elites)
        ranked = sorted(range(len(isl.population)), key=lambda j: (isl.fitness[j], -j))
        for j, genome in enumerate(incoming):
            if j >= len(ranked):
                break
            fixed = enforce_constraints(genome, isl.constraints)
            # Strip any species that is a lock on the SOURCE island but
            # not locked here. Without this, Umbreon leaks from island A
            # into B/C and diversity collapses over generations.
            src_constraints = islands[(i - 1) % len(islands)].constraints
            foreign_locks = set(src_constraints.values()) - set(isl.constraints.values())
            if foreign_locks:
                fixed = _strip_species(fixed, foreign_locks, isl.constraints)
            isl.population[ranked[j]] = fixed
            isl.fitness[ranked[j]] = 0.0
