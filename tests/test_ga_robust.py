"""Tests for the GA's server-restart handling and fail-fast startup (no server, no battles).

Run: pytest tests/test_ga_robust.py   (or: python tests/test_ga_robust.py)
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import eval as E  # noqa: E402
from src import ga_core as G  # noqa: E402
from src import meta_weights as MW  # noqa: E402


class _Fake:
    """Replaces ga_core's subprocess / sleep / server probe; the server 'answers' from probe N on."""

    def __init__(self, up_from_probe):
        self.up_from, self.probes, self.launches = up_from_probe, 0, 0

    def run(self, *a, **k):
        pass

    def popen(self, *a, **k):
        self.launches += 1

    def up(self):
        self.probes += 1
        return self.up_from is not None and self.probes >= self.up_from


def _patched(fake, fn):
    saved = (G.subprocess.run, G.subprocess.Popen, G.time.sleep, G._showdown_up)
    G.subprocess.run, G.subprocess.Popen, G.time.sleep, G._showdown_up = fake.run, fake.popen, (lambda s: None), fake.up
    try:
        return fn()
    finally:
        G.subprocess.run, G.subprocess.Popen, G.time.sleep, G._showdown_up = saved


def test_restart_waits_past_15s():
    f = _Fake(up_from_probe=40)
    assert _patched(f, lambda: G.restart_showdown(wait_s=60, tries=2)) is True
    assert f.launches == 1


def test_restart_retries_once_then_gives_up():
    f = _Fake(up_from_probe=None)
    assert _patched(f, lambda: G.restart_showdown(wait_s=5, tries=2)) is False
    assert f.launches == 2 and f.probes == 10


def test_restart_second_attempt_can_succeed():
    f = _Fake(up_from_probe=7)
    assert _patched(f, lambda: G.restart_showdown(wait_s=5, tries=2)) is True
    assert f.launches == 2


def test_ensure_showdown_raises_when_dead_and_skips_restart_when_up():
    dead = _Fake(up_from_probe=None)
    try:
        _patched(dead, lambda: G.ensure_showdown())
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass
    up = _Fake(up_from_probe=1)
    _patched(up, lambda: G.ensure_showdown())
    assert up.launches == 0


def test_run_islands_fails_fast_without_usage_file():
    saved = MW.USAGE_PATH, MW.load_usage
    def boom(*a, **k):
        raise FileNotFoundError("missing")
    MW.load_usage = boom
    try:
        asyncio.run(G.run_islands([{"name": "A"}], max_hours=0.01, run_id="_test_no_such_run"))
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "build_meta_weights" in str(e)
    finally:
        MW.load_usage = saved[1]


def test_eval_reports_the_ga_fitness():
    pool = G.regional_pool()[:3]
    calls = []

    async def fake_battle(team, opp, uid, sem, fmt, **kw):
        calls.append(kw["opp_pilot"])
        return 1 if opp == pool[0] else 0

    saved = E.B.run_battle
    E.B.run_battle = fake_battle
    try:
        w, g, fit = asyncio.run(E.evaluate_team("vgc", "team", pool, [1, 2], 4, opp_pilot="ladder"))
    finally:
        E.B.run_battle = saved
    assert (w, g) == (2, 6) and set(calls) == {"ladder"}
    assert abs(fit - G._fitness([1, 0, 0, 1, 0, 0], pool + pool)[0]) < 1e-12


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
