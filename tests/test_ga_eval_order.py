"""Regression test: GA fitness must pair each outcome with ITS opponent's meta weight.

Before the fix, the >EARLY_STOP_MIN_BATTLES path collected outcomes in completion
order (asyncio.wait / as_completed) and weighted them by opponents in submission
order, so the weighted fitness was noise. Battles here finish in reverse order.

Run: pytest tests/test_ga_eval_order.py   (or: python tests/test_ga_eval_order.py)
"""
import asyncio
import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import battle as B  # noqa: E402
from src.ga import fitness as F  # noqa: E402
from src.ga.config import DEFAULT, GAConfig  # noqa: E402
from src.ga.evaluator import Evaluator  # noqa: E402
from src.ga.genome import text_to_genome  # noqa: E402
from src.ga.pools import regional_pool  # noqa: E402
from src.paths import data_path  # noqa: E402


def _evaluate_with(outcome_for, n_opps, config=DEFAULT, out=None):
    pool = regional_pool()[:n_opps]
    assert len(pool) == n_opps
    order = {t: i for i, t in enumerate(pool)}

    async def fake_run_battle(team, opp, uid, sem, fmt, **kw):
        i = order[opp]
        await asyncio.sleep(0.0005 * (n_opps - i))   # later opponents finish first
        return outcome_for(i)

    genome = text_to_genome(open(data_path("baseline_team.txt")).read())

    async def run():
        return await Evaluator(config, concurrency=8).evaluate(genome, pool, 0, 1)

    saved = B.run_battle
    B.run_battle = fake_run_battle
    try:
        with contextlib.redirect_stdout(out if out is not None else io.StringIO()):
            fit = asyncio.run(run())
    finally:
        B.run_battle = saved
    return fit, pool


def test_full_run_weights_follow_opponents():
    def outcome(i):
        return None if i % 11 == 0 else (1 if i % 3 else 0)
    fit, pool = _evaluate_with(outcome, 70)
    want = F.weighted_fitness([outcome(i) for i in range(70)], pool, DEFAULT.meta_weights)[0]
    assert abs(fit - want) < 1e-12, (fit, want)


def test_early_abort_weights_follow_opponents():
    head = DEFAULT.early_stop_min_battles

    def outcome(i):
        return 1 if i % 10 == 0 else 0   # ~10% in the head -> early abort
    fit, pool = _evaluate_with(outcome, head + 20)
    want = F.weighted_fitness([outcome(i) for i in range(head)], pool[:head], DEFAULT.meta_weights)[0]
    assert want < DEFAULT.early_stop_win_rate
    assert abs(fit - want) < 1e-12, (fit, want)


def test_early_stop_threshold_boundary():
    """Unweighted head of 50: 7 wins (14%) aborts, 8 wins (16%) plays the tail."""
    plain = GAConfig(meta_weights=False)
    head = plain.early_stop_min_battles

    def run(head_wins):
        out = io.StringIO()
        fit, _ = _evaluate_with(lambda i: 1 if i < head_wins or i >= head else 0,
                                head + 10, config=plain, out=out)
        return fit, "early-abort" in out.getvalue()

    fit, aborted = run(7)
    assert aborted and abs(fit - 7 / 50) < 1e-12, (fit, aborted)
    fit, aborted = run(8)
    assert not aborted and abs(fit - 18 / 60) < 1e-12, (fit, aborted)


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e!r}")
    sys.exit(1 if failed else 0)
