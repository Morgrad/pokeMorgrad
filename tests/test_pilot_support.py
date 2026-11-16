"""
test_pilot_support.py — unit tests for pilot_support module.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pilot_support import _resolve_support_move


def test_pilot_support():
    """Test that pilot support module loads correctly."""
    # Test that the module can be imported
    assert _resolve_support_move is not None
    print("PASS test_pilot_support")

if __name__ == "__main__":
    test_pilot_support()
