"""GAConfig.from_env: same variable names, defaults and parsing as the old ga_core globals
(the src/ga_core.py facade itself was removed on 2026-11-18).

Run: pytest tests/test_ga_config.py   (or: python tests/test_ga_config.py)
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import eval as EV  # noqa: E402
from src.ga import config as C  # noqa: E402
from src.ga.config import DEFAULT, GAConfig  # noqa: E402


def test_defaults_without_env():
    c = GAConfig.from_env({})
    assert (c.fitness_pilot, c.fitness_opp, c.meta_weights, c.train_sample_size) == \
        ("vgc", "ladder", True, 250)
    assert (c.battle_timeout, c.min_turns) == (20, 3)
    assert (c.early_stop_min_battles, c.early_stop_win_rate) == (50, 0.15)
    assert c.showdown_port == 8000


def test_env_overrides():
    c = GAConfig.from_env({"GA_PILOT": "heuristic", "GA_OPP": "heuristic",
                           "GA_META_WEIGHTS": "0", "GA_TRAIN_SAMPLE": "7",
                           "SHOWDOWN_PORT": "8001", "SHOWDOWN_DIR": "/opt/sd"})
    assert (c.fitness_pilot, c.fitness_opp, c.meta_weights, c.train_sample_size) == \
        ("heuristic", "heuristic", False, 7)
    assert (c.showdown_port, c.showdown_dir) == (8001, "/opt/sd")
    # only the exact string "1" turns meta weighting on, as before
    assert GAConfig.from_env({"GA_META_WEIGHTS": "true"}).meta_weights is False


def test_default_follows_env_and_eval_uses_the_ga_constants():
    assert DEFAULT == GAConfig.from_env(os.environ)
    assert (EV.FORMAT, EV.UID_MAX) == (C.FORMAT, C.UID_MAX) == ("gen9championsvgc2026regmc", 10**9)


def _raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


def test_invalid_values_fail_fast():
    # a typo used to fall back silently to the heuristic pilot
    assert _raises(lambda: GAConfig.from_env({"GA_PILOT": "vcg"}))
    assert _raises(lambda: GAConfig.from_env({"GA_OPP": "Ladder"}))
    assert _raises(lambda: GAConfig.from_env({"GA_TRAIN_SAMPLE": "0"}))
    assert _raises(lambda: GAConfig(early_stop_win_rate=1.5))
    for pilot in ("heuristic", "bc", "doubles", "ladder", "vgc"):
        assert GAConfig.from_env({"GA_PILOT": pilot, "GA_OPP": pilot}).fitness_pilot == pilot


def test_showdown_port_has_one_parser():
    # src/paths.py::showdown_port is the only SHOWDOWN_PORT parser (refactor item D2)
    from src import paths
    from src import player_factory as PF
    for env in ({}, {"SHOWDOWN_PORT": "8002"}):
        assert GAConfig.from_env(env).showdown_port == paths.showdown_port(env)
    assert paths.showdown_port({}) == 8000
    port = paths.showdown_port()
    assert PF.DEFAULT_SERVER.websocket_url == f"ws://localhost:{port}/showdown/websocket"
    assert DEFAULT.showdown_port == port


def test_pilot_names_match_player_factory():
    from src.ga.config import PILOT_NAMES
    from src.player_factory import PILOTS, make_player
    assert tuple(PILOT_NAMES) == tuple(PILOTS)
    assert _raises(lambda: make_player("nope", "", 1, "B", "gen9championsvgc2026regmc"))


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
