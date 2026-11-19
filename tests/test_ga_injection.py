"""Stagnation restart, diversity rescue and migration really change the next generation.

Before 2026-11-18 the engine injected fresh genomes BEFORE breed(); they had fitness 0
and breed() keeps only the top third by fitness, so they were always discarded (both
mechanisms were no-ops). Now they go into the bred children's slots after breed().

No Showdown: the legality gate is patched to identity and fitness comes from a fake
evaluator. Run: python tests/test_ga_injection.py
"""
import asyncio
import copy
import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.ga import engine as E  # noqa: E402
from src.ga import population as P  # noqa: E402

_REAL_BUILD = P.build_random_genome
POP = 10
FITS = [0.10, 0.90, 0.20, 0.80, 0.30, 0.70, 0.40, 0.60, 0.50, 0.05]


class _FakeEvaluator:
    class config:
        train_sample_size = 250

    async def evaluate(self, genome, opponents, idx, total, on_battles=None):
        return FITS[idx]

    async def eval_on_subset(self, genome, opponents):
        return 0.0


def _gen(number, last=5, stagnation_limit=5, diversity_floor=0):
    return E._Generation(number=number, last=last, battles_per_genome=50,
                         immigration_rate=0.0, stagnation_limit=stagnation_limit,
                         diversity_floor=diversity_floor, replay_logger=None)


def _fresh_marker(constraints):
    return [{"species": "MARKER", "fresh": True}]


def _island(seed):
    random.seed(seed)
    isl = P.Island("T", {})
    isl.init_population(POP)
    assert len(isl.population) == POP
    return isl


def _run(isl, g):
    asyncio.run(E._evolve_island(isl, g, _FakeEvaluator(), ["opp"] * 60, ["val"] * 30))


def _markers(isl):
    return [i for i, gnm in enumerate(isl.population) if gnm and gnm[0].get("fresh")]


def _top3(isl):
    order = sorted(range(POP), key=lambda i: -FITS[i])[:3]
    return [[m["species"] for m in isl.population[i]] for i in order]


def _with_patches(fn):
    def wrapped():
        saved = (P.filter_legal_genomes, P.build_random_genome)
        P.filter_legal_genomes = lambda genomes, constraints: genomes
        try:
            return fn()
        finally:
            P.filter_legal_genomes, P.build_random_genome = saved
    wrapped.__name__ = fn.__name__
    return wrapped


@_with_patches
def test_stagnation_restart_reaches_next_generation():
    isl = _island(1)
    elites = _top3(isl)
    isl.best_ever = {"fit": 2.0, "genome": None, "gen": 0}   # no new best -> stagnation += 1
    isl.stagnation = 4
    P.build_random_genome = _fresh_marker
    _run(isl, _gen(0, stagnation_limit=5))
    assert _markers(isl) == [5, 6, 7, 8, 9], _markers(isl)     # half, children slots only
    assert [[m["species"] for m in isl.population[i]] for i in range(3)] == elites
    assert isl.stagnation == 0


@_with_patches
def test_diversity_rescue_reaches_next_generation():
    isl = _island(2)
    isl.best_ever = {"fit": 2.0, "genome": None, "gen": 0}
    P.build_random_genome = _fresh_marker
    _run(isl, _gen(0, diversity_floor=10_000))                # always "low diversity"
    assert _markers(isl) == [7, 8, 9], _markers(isl)
    assert isl.stagnation == 1


@_with_patches
def test_restart_wins_over_rescue_and_last_generation_injects_nothing():
    isl = _island(3)
    isl.best_ever = {"fit": 2.0, "genome": None, "gen": 0}
    isl.stagnation = 4
    P.build_random_genome = _fresh_marker
    _run(isl, _gen(0, stagnation_limit=5, diversity_floor=10_000))
    assert len(_markers(isl)) == 5                           # restart only, no extra +3

    P.build_random_genome = _REAL_BUILD
    isl2 = _island(4)
    before = copy.deepcopy(isl2.population)
    isl2.best_ever = {"fit": 2.0, "genome": None, "gen": 0}
    isl2.stagnation = 4
    P.build_random_genome = _fresh_marker
    _run(isl2, _gen(4, last=5, stagnation_limit=5, diversity_floor=10_000))
    assert isl2.population == before and _markers(isl2) == []


@_with_patches
def test_ring_migrate_targets_worst_and_spares_elites_after_breed():
    a, b = _island(5), _island(6)
    # real fitness: migrants replace the destination's two WORST genomes
    a.fitness = list(FITS)
    b.fitness = list(reversed(FITS))
    b_best = copy.deepcopy(b.population[b.fitness.index(max(b.fitness))])
    P.ring_migrate([a, b], n=2)
    assert b_best in b.population
    # after breed (all fitness 0.0): migrants land in the last slots, elites stay
    a.fitness = list(FITS)
    a.breed(immigration_rate=0.0)
    b.fitness = list(FITS)
    b.breed(immigration_rate=0.0)
    b_elites = copy.deepcopy(b.population[:3])
    P.ring_migrate([a, b], n=2)
    assert b.population[:3] == b_elites


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e!r}")
    sys.exit(1 if failed else 0)
