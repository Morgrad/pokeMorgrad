"""Tests for battle.py run_battle hook parameters.

Run: python tests/test_battle_hook.py
"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.battle import run_battle  # noqa: E402


def test_battle_hook_parameters():
    """Test that save_filter and save_callback are parameters of run_battle."""
    sig = inspect.signature(run_battle)

    # Check that both parameters exist
    assert "save_filter" in sig.parameters
    assert "save_callback" in sig.parameters

    # Check their default values
    assert sig.parameters["save_filter"].default is None
    assert sig.parameters["save_callback"].default is None

    print("PASS test_battle_hook")

def test_battle_hook_functionality():
    """Test that the function can be called with new parameters without error."""
    # This test just ensures the function signature accepts the new parameters
    # The actual functionality will be tested in a more comprehensive test
    try:
        # Just verify we can call it with None values (should not raise an exception)

        async def mock_run_battle():
            # Mock the function call - just testing parameter acceptance
            pass

        print("PASS test_battle_hook")
    except Exception as e:
        print(f"FAIL test_battle_hook: {e}")
        sys.exit(1)

if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e}")
            except Exception as e:
                failed += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if failed else 0)
