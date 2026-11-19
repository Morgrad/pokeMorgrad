"""Clause fuzz: every way the GA builds or repairs a genome must keep the species clause
(no two mons of the same base species), the item clause (no duplicate items) and the
locked slots. Seeded, no Showdown (refactor roadmap item B2).

Run: python tests/test_genome_clauses.py
"""
import copy
import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src import regmc_db as DB  # noqa: E402
from src.ga import genome as G  # noqa: E402
from src.ga import population as P  # noqa: E402
from src.ga.legality import enforce_constraints  # noqa: E402
from src.ga.operators import crossover, mutate  # noqa: E402

LOCKS = [{}, {0: "Umbreon"}, {0: "Umbreon", 3: "Incineroar"}]


def _base(mon):
    sp = DB.get_species(mon["species"]) or {}
    return DB.norm(sp.get("baseSpecies") or mon["species"])


def _problems(g, constraints):
    """List of clause / lock violations of genome g (empty = fine)."""
    out = []
    bases = [_base(m) for m in g]
    if len(set(bases)) != len(bases):
        out.append(f"species clause: {sorted(b for b in set(bases) if bases.count(b) > 1)}")
    items = [m["item"] for m in g]
    if len(set(items)) != len(items):
        out.append(f"item clause: {sorted(i for i in set(items) if items.count(i) > 1)}")
    for slot, sp in constraints.items():
        if g[slot]["species"] != sp:
            out.append(f"lock {slot}={sp} broken ({g[slot]['species']})")
    if len(g) != 6:
        out.append(f"{len(g)} mons")
    return out


def _check(label, g, constraints, fails):
    for p in _problems(g, constraints):
        fails.append(f"{label}: {p}")


def _genomes(rng_seed, constraints, n):
    random.seed(rng_seed)
    out = []
    while len(out) < n:
        g = G.build_random_genome(constraints)
        if g is not None:
            out.append(g)
    return out


def test_random_builds_keep_the_clauses():
    fails = []
    for k, c in enumerate(LOCKS):
        for g in _genomes(100 + k, c, 40):
            _check(f"build {c}", g, c, fails)
    assert not fails, fails[:5]


def test_mutation_and_crossover_keep_the_clauses():
    fails = []
    for k, c in enumerate(LOCKS):
        pop = _genomes(200 + k, c, 20)
        random.seed(300 + k)
        for i in range(200):
            p1, p2 = random.choice(pop), random.choice(pop)
            child = mutate(crossover(p1, p2, c), c)
            _check(f"crossover+mutate {c}", child, c, fails)
            pop[i % len(pop)] = child
    assert not fails, fails[:5]


def test_enforce_constraints_repairs_genomes_from_other_islands():
    # a genome bred on a free island (or under other locks) entering a locked island:
    # ring_migrate and seed files go through enforce_constraints
    fails = []
    foreign = _genomes(400, {}, 60) + _genomes(401, {3: "Incineroar"}, 30)
    # make sure the hard case is present: the locked species already in a free slot
    random.seed(402)
    for g in foreign[:30]:
        g[random.randint(1, 5)] = G._fresh_mon("Umbreon", {m["item"] for m in g}) or g[1]
    for c in LOCKS[1:]:
        for g in foreign:
            out = enforce_constraints(copy.deepcopy(g), c)
            _check(f"enforce {c}", out, c, fails)
    assert not fails, (len(fails), fails[:5])


def test_ring_migration_keeps_the_clauses():
    fails = []
    random.seed(500)
    islands = [P.Island("A", {0: "Umbreon"}), P.Island("B", {}), P.Island("C", {3: "Incineroar"})]
    for k, isl in enumerate(islands):
        isl.population = _genomes(510 + k, isl.constraints, 8)
        isl.fitness = [random.random() for _ in isl.population]
    for _ in range(10):
        P.ring_migrate(islands, n=3)
        for isl in islands:
            for g in isl.population:
                _check(f"migrate into {isl.name}", g, isl.constraints, fails)
            isl.fitness = [random.random() for _ in isl.population]
    assert not fails, (len(fails), fails[:5])


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {str(e)[:300]}")
    sys.exit(1 if failed else 0)
