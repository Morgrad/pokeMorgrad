"""
test_battle_runner.py — unit tests for battle_runner module (fake players, no Showdown).
"""

import asyncio
import logging
import os
import sys
import types

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src import battle_runner as BR  # noqa: E402
from src.battle import run_battle as battle_run_battle  # noqa: E402
from src.battle import run_battle_once as battle_run_battle_once  # noqa: E402
from src.battle_runner import run_battle, run_battle_once  # noqa: E402


def test_battle_runner():
    """Test that run_battle and run_battle_once can be imported from both modules."""
    # Test that functions can be imported from battle_runner
    assert run_battle is not None
    assert run_battle_once is not None

    # Test that functions can be imported from battle (should work due to import forwarding)
    assert battle_run_battle is not None
    assert battle_run_battle_once is not None


class _Player:
    """Stand-in for a poke_env Player: battle_against raises `exc` or sleeps `sleep` s."""

    def __init__(self, exc=None, sleep=0.0):
        self.exc, self.sleep = exc, sleep
        self.n_finished_battles = self.n_won_battles = 0
        self.battles = {}
        self.ps_client = types.SimpleNamespace(stop_listening=self._stop)

    async def _stop(self):
        pass

    async def battle_against(self, opp, n_battles=1):
        if self.sleep:
            await asyncio.sleep(self.sleep)
        if self.exc is not None:
            raise self.exc


class _Records(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _once(exc=None, sleep=0.0, timeout=5):
    """run_battle_once with fake players; returns (result, captured log records)."""
    real = BR.make_player
    BR.make_player = lambda pilot, team, uid, prefix, fmt: _Player(exc, sleep) if prefix == "B" else _Player()
    h = _Records()
    BR._log.addHandler(h)
    try:
        out = asyncio.run(BR.run_battle_once("t", "o", 1, asyncio.Semaphore(1), "fmt",
                                             pilot="vgc", opp_pilot="ladder", timeout=timeout))
    finally:
        BR.make_player = real
        BR._log.removeHandler(h)
    return out, h.records


def test_pilot_exception_is_reported_not_hidden():
    BR._ERROR_COUNTS.clear()
    out, recs = _once(exc=RuntimeError("pilot exploded"))
    assert out == (None, [])                                   # still no result: the GA keeps going
    assert len(recs) == 1 and recs[0].levelno == logging.ERROR
    msg = recs[0].getMessage()
    assert "RuntimeError" in msg and "pilot exploded" in msg and "vgc vs ladder" in msg
    assert recs[0].exc_info is not None                        # full traceback attached
    assert BR.battle_error_counts() == {"RuntimeError": 1}


def test_repeated_errors_do_not_flood_the_log():
    BR._ERROR_COUNTS.clear()
    logged = []
    for _ in range(BR.TRACEBACKS_PER_TYPE + 2):
        logged += _once(exc=ValueError("again"))[1]
    assert len(logged) == BR.TRACEBACKS_PER_TYPE              # traceback for the first N only
    assert BR.battle_error_counts() == {"ValueError": BR.TRACEBACKS_PER_TYPE + 2}
    BR._ERROR_COUNTS["ValueError"] = 99
    assert len(_once(exc=ValueError("again"))[1]) == 1         # every 100th: one summary line
    BR._ERROR_COUNTS.clear()


def test_timeout_is_not_an_error():
    BR._ERROR_COUNTS.clear()
    out, recs = _once(sleep=1.0, timeout=0.05)
    assert out == (None, []) and recs == [] and BR.battle_error_counts() == {}


def test_keyerror_round_warns_and_other_keyerrors_propagate():
    BR._ERROR_COUNTS.clear()
    out, recs = _once(exc=KeyError("round"))
    assert out == (None, []) and len(recs) == 1 and recs[0].levelno == logging.WARNING
    try:
        _once(exc=KeyError("something_else"))
        raise AssertionError("expected KeyError")
    except KeyError:
        pass
    assert BR.battle_error_counts() == {}


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e!r}")
    sys.exit(1 if failed else 0)
