"""
test_battle_runner.py — unit tests for battle_runner module.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.battle import run_battle as battle_run_battle
from src.battle import run_battle_once as battle_run_battle_once
from src.battle_runner import run_battle, run_battle_once


def test_battle_runner():
    """Test that run_battle and run_battle_once can be imported from both modules."""
    # Test that functions can be imported from battle_runner
    assert run_battle is not None
    assert run_battle_once is not None

    # Test that functions can be imported from battle (should work due to import forwarding)
    assert battle_run_battle is not None
    assert battle_run_battle_once is not None

    print("PASS test_battle_runner")

if __name__ == "__main__":
    test_battle_runner()
