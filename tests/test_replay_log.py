"""GA replay logging (src/replay_log.py + Evaluator on_battles + engine wiring), no Showdown.

Pins the 2026-11-18 redesign: real fitness / outcome / generation reach the filter, the
saved sample is capped per island and generation, it is deterministic regardless of the
order battles finish in, and logging never changes the GA's results or random stream.
Run: python tests/test_replay_log.py
"""
import asyncio
import json
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src import battle as B  # noqa: E402
from src.ga import engine as E  # noqa: E402
from src.ga import population as P  # noqa: E402
from src.ga.config import GAConfig  # noqa: E402
from src.ga.evaluator import Evaluator  # noqa: E402
from src.ga.genome import build_random_genome  # noqa: E402
from src.replay_log import ReplayLogger  # noqa: E402

GENOME = [{"species": s} for s in ("Umbreon", "Incineroar", "Garchomp",
                                   "Amoonguss", "Sylveon", "Kingambit")]


def _keep_all(**kw):
    return True


def _logger(**kw):
    return ReplayLogger(tempfile.mkdtemp(), "r1_A", **kw)


def _read(path):
    return [json.loads(line) for line in open(path)]


def test_rows_carry_real_values_and_cap_per_generation():
    rl = _logger(max_per_gen=3, keep=_keep_all)
    rl.start_generation("A", 4)
    rl.for_genome("A", 4, 1)(GENOME, 0.8, [1, 0, None], [["|win|x"], ["|turn|9"], []])
    rl.for_genome("A", 4, 0)(GENOME, 0.4, [0, 1], [["|a"], ["|b"]])
    assert rl.end_generation("A", 4) == 3
    rows = _read(os.path.join(rl.out_dir, "A_gen0004.jsonl"))
    # (genome, opponent) order, no matter which genome reported first; empty logs skipped
    assert [(r["genome_index"], r["opponent_index"]) for r in rows] == [(0, 0), (0, 1), (1, 0)]
    assert rows[2]["genome_fitness"] == 0.8 and rows[2]["outcome"] == "win"
    assert rows[0]["outcome"] == "loss" and rows[0]["gen"] == 4 and rows[0]["island"] == "A"
    assert rows[2]["our_species"][0] == "Umbreon" and rows[2]["log"] == ["|win|x"]


def test_filter_gets_real_inputs_and_private_deterministic_rng():
    seen = []

    def keep(fitness, outcome, genome_species, battle_history, rng):
        seen.append((fitness, outcome, len(genome_species), battle_history[0]))
        return rng.random() < 0.5

    def run():
        rl = _logger(max_per_gen=100, keep=keep, seed=7)
        rl.start_generation("B", 2)
        logs = [[f"|turn|{i}"] for i in range(40)]
        rl.for_genome("B", 2, 3)(GENOME, 0.66, [i % 2 for i in range(40)], logs)
        n = rl.end_generation("B", 2)
        return n, open(os.path.join(rl.out_dir, "B_gen0002.jsonl")).read()

    state = random.getstate()
    a, b = run(), run()
    assert random.getstate() == state          # the global stream is untouched
    assert a == b and 0 < a[0] < 40            # same sample every time, a real sample
    assert seen[0] == (0.66, "loss", 6, "|turn|0") and seen[1][1] == "win"


def _fake_run_battle(outcome_of):
    async def fake(team, opp, uid, sem, fmt, log_sink=None, **kw):
        result = outcome_of(opp)
        if log_sink is not None:
            log_sink(result, [f"|player|{opp}", f"|result|{result}"])
        return result
    return fake


def test_evaluator_reports_battles_and_logging_does_not_change_results():
    real = B.run_battle
    B.run_battle = _fake_run_battle(lambda opp: 1 if opp % 3 else 0)
    try:
        cfg = GAConfig(meta_weights=False)
        opps = list(range(60))                  # > 50: head + tail path
        got = []
        random.seed(3)
        team = build_random_genome({})          # a real, legal genome
        random.seed(1)
        fit_off = asyncio.run(Evaluator(cfg, 4).evaluate(team, opps, 0, 1))
        state_off = random.getstate()
        random.seed(1)
        fit_on = asyncio.run(Evaluator(cfg, 4).evaluate(
            team, opps, 0, 1, on_battles=lambda *a: got.append(a)))
        assert fit_on == fit_off and random.getstate() == state_off
        genome, fit, outcomes, logs = got[0]
        assert fit == fit_on and len(outcomes) == len(logs) == 60
        assert logs[7] == ["|player|7", "|result|1"] and outcomes[7] == 1 and outcomes[9] == 0

        # early abort: only the 50 head battles are reported
        B.run_battle = _fake_run_battle(lambda opp: 0)
        got.clear()
        asyncio.run(Evaluator(cfg, 4).evaluate(team, opps, 0, 1,
                                               on_battles=lambda *a: got.append(a)))
        assert len(got[0][2]) == len(got[0][3]) == 50
    finally:
        B.run_battle = real


def test_engine_writes_one_file_per_island_generation_and_keeps_rng():
    real_run, real_filter = B.run_battle, P.filter_legal_genomes
    B.run_battle = _fake_run_battle(lambda opp: 1 if hash(opp) % 2 else 0)
    P.filter_legal_genomes = lambda genomes, constraints: genomes
    try:
        def one_gen(rl):
            random.seed(5)
            isl = P.Island("C", {})
            isl.init_population(4)
            g = E._Generation(number=2, last=10, battles_per_genome=8, immigration_rate=0.2,
                              stagnation_limit=5, diversity_floor=0, replay_logger=rl)
            ev = Evaluator(GAConfig(meta_weights=False), 4)
            asyncio.run(E._evolve_island(isl, g, ev, [f"t{i}" for i in range(20)], ["v"] * 3))
            return isl.to_dict(), random.getstate()

        off = one_gen(None)
        rl = _logger(max_per_gen=5, keep=_keep_all)
        rl.run_id = "r1_C"
        on = one_gen(rl)
        assert on == off                                     # same population, same RNG
        rows = _read(os.path.join(rl.out_dir, "C_gen0003.jsonl"))
        assert len(rows) == 5 and {r["gen"] for r in rows} == {3}
        assert all(r["log"][0].startswith("|player|t") for r in rows)
    finally:
        B.run_battle, P.filter_legal_genomes = real_run, real_filter


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
