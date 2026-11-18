"""GAConfig.from_env: same variable names, defaults and parsing as the old ga_core globals.

Run: pytest tests/test_ga_config.py   (or: python tests/test_ga_config.py)
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import ga_core as G  # noqa: E402
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


def test_ga_core_aliases_follow_default():
    assert DEFAULT == GAConfig.from_env(os.environ)
    assert (G.FITNESS_PILOT, G.FITNESS_OPP, G.META_WEIGHTS, G.TRAIN_SAMPLE_SIZE) == \
        (DEFAULT.fitness_pilot, DEFAULT.fitness_opp, DEFAULT.meta_weights, DEFAULT.train_sample_size)
    assert (G.BATTLE_TIMEOUT, G.MIN_TURNS, G.SHOWDOWN_PORT, G.SHOWDOWN_DIR) == \
        (DEFAULT.battle_timeout, DEFAULT.min_turns, DEFAULT.showdown_port, DEFAULT.showdown_dir)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
