"""src/showdown_validator.py::check_teams with a faked node process (no Showdown needed).

Regression (fixed 2026-11-18): a failed node run used to become a cached (False, "")
verdict, so every genome looked illegal on a host without a built Showdown checkout.
Run: python tests/test_showdown_validator.py
"""
import os
import subprocess
import sys
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src import showdown_validator as SV  # noqa: E402

_REAL_RUN = SV.subprocess.run


def _fake(stdout="", returncode=0, stderr="", exc=None):
    calls = []

    def run(cmd, input, capture_output, text, timeout):
        calls.append(input.count("\n") + 1)
        if exc:
            raise exc
        return NS(stdout=stdout, returncode=returncode, stderr=stderr)
    return run, calls


def _raises_validator_error(fn):
    try:
        fn()
    except SV.ValidatorError:
        return True
    return False


def _reset(run):
    SV.CACHE.clear()
    SV.subprocess.run = run


def test_verdicts_parsed_in_order_and_cached():
    run, calls = _fake("OK\nFAIL:Umbreon can't learn X\nPARSE_FAIL\n")
    _reset(run)
    try:
        out = SV.check_teams(["a", "b", "c"])
        assert out == [(True, ""), (False, "Umbreon can't learn X"), (False, "PARSE_FAIL")]
        assert SV.check_teams(["b", "a"]) == [out[1], out[0]] and len(calls) == 1
    finally:
        SV.subprocess.run = _REAL_RUN


def test_node_failure_raises_and_caches_nothing():
    for run, _ in (_fake("", returncode=1, stderr="Cannot find module dist/sim/dex"),
                   _fake("OK\n"),                         # 1 verdict for 2 teams
                   _fake(exc=subprocess.TimeoutExpired("node", 60)),
                   _fake(exc=FileNotFoundError("node"))):
        _reset(run)
        try:
            assert _raises_validator_error(lambda: SV.check_teams(["a", "b"]))
            assert SV.CACHE == {}
        finally:
            SV.subprocess.run = _REAL_RUN


def test_per_team_error_is_not_cached():
    run, calls = _fake("ERR:boom\nOK\n")
    _reset(run)
    try:
        assert SV.check_teams(["a", "b"]) == [(False, "ERR:boom"), (True, "")]
        assert len(SV.CACHE) == 1
    finally:
        SV.subprocess.run = _REAL_RUN


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
