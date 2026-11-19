"""src/battle_runner.py: battle log capture and the run_battle log_sink hook (no Showdown).

Regression (fixed 2026-11-18): the old hook read `battle.log`, which poke_env 0.17 does
not have, and called its filter with fitness 0.0 / outcome "unknown"; every captured
history was empty. Run: python tests/test_battle_hook.py
"""
import asyncio
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import battle_runner as BR  # noqa: E402
from src.battle import run_battle  # noqa: E402


def test_run_battle_signature():
    params = inspect.signature(run_battle).parameters
    assert params["log_sink"].default is None
    assert "save_filter" not in params and "save_callback" not in params


def test_battle_log_lines_reads_poke_env_replay_data():
    battle = NS(_replay_data=[["", "move", "p1a: Umbreon", "Moonlight", "p1a: Umbreon"],
                              ["", "turn", "2"]])
    assert BR.battle_log_lines(battle) == ["|move|p1a: Umbreon|Moonlight|p1a: Umbreon", "|turn|2"]
    assert BR.battle_log_lines(NS(log=["|turn|1"])) == ["|turn|1"]       # legacy attribute
    assert BR.battle_log_lines(NS()) == [] and BR.battle_log_lines(None) == []


def test_log_sink_gets_final_attempt_result_and_log():
    attempts = [(None, []), (1, ["|win|B1"])]
    calls, uids = [], []

    async def fake_once(team, opp, uid, sem, fmt, **kw):
        uids.append(uid)
        return attempts[len(uids) - 1]

    real = BR.run_battle_once
    BR.run_battle_once = fake_once
    try:
        result = asyncio.run(BR.run_battle("t", "o", 5, None, "fmt", retries=1,
                                           log_sink=lambda r, lines: calls.append((r, lines))))
    finally:
        BR.run_battle_once = real
    assert result == 1 and calls == [(1, ["|win|B1"])]
    assert uids == [5, 5 + BR.RETRY_STRIDE]


def test_log_sink_errors_never_break_the_battle():
    async def fake_once(*a, **kw):
        return 0, ["|turn|1"]

    def bad_sink(result, lines):
        raise RuntimeError("disk full")

    real = BR.run_battle_once
    BR.run_battle_once = fake_once
    try:
        assert asyncio.run(BR.run_battle("t", "o", 1, None, "fmt", log_sink=bad_sink)) == 0
    finally:
        BR.run_battle_once = real


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
