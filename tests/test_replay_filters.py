import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.replay_filters import default_ga_filter


def test_replay_filters():
    class MockRng:
        def __init__(self, val):
            self.val = val
        def random(self):
            return self.val

    try:
        assert default_ga_filter(0.76, "win", [], [], rng=MockRng(0.99)), "Test 1"
        assert not default_ga_filter(0.66, "win", [], [], rng=MockRng(0.99)), "Test 2"
        assert default_ga_filter(0.66, "loss", [], [], rng=MockRng(0.99)), "Test 3"

        history = ["|move|p1a: Pelipper|Tailwind|p1a: Pelipper"]
        assert default_ga_filter(0.1, "loss", [], history, rng=MockRng(0.99)), "Test 4 (Tailwind)"

        history = ["|move|p2a: Indeedee|Trick Room|p2a: Indeedee"]
        assert default_ga_filter(0.1, "loss", [], history, rng=MockRng(0.99)), "Test 5 (TR)"

        assert default_ga_filter(0.1, "loss", [], [], rng=MockRng(0.01)), "Test 6 (Random pass)"
        assert not default_ga_filter(0.1, "loss", [], [], rng=MockRng(0.03)), "Test 7 (Random fail)"

    except AssertionError as e:
        print(f"FAIL test_replay_filters - {e}")
        return False

    print("PASS test_replay_filters")
    return True

if __name__ == "__main__":
    if not test_replay_filters():
        exit(1)
