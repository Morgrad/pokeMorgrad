"""Island specs of the parallel launcher (run/ga_island.py).

Intended layout:
  A = always seeded with the baseline team
  B = Umbreon locked in slot 0, no seed -> 5 slots free for the GA
  C = fully free: no lock, no seed

Run: pytest tests/test_island_wiring.py   (or: python tests/test_island_wiring.py)
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _load_island_module():
    # run/ga_island.py parses sys.argv at import time; give it its own argv
    saved = sys.argv
    sys.argv = ["ga_island.py", "test", "1"]
    try:
        sys.modules.pop("run.ga_island", None)
        return importlib.import_module("run.ga_island")
    finally:
        sys.argv = saved


def test_island_wiring():
    island = _load_island_module()
    specs = island.SPECS
    assert set(specs) == {"A", "B", "C"}

    # A: always seeded with the baseline team
    assert [os.path.basename(p) for p in specs["A"]["seed_paths"]] == ["baseline_team.txt"]

    # B: Umbreon lock in slot 0, no seed -> 5 free slots
    assert specs["B"]["constraints"] == {0: "Umbreon"}
    assert specs["B"]["seed_paths"] == []

    # C: fully free
    assert specs["C"]["constraints"] == {}
    assert specs["C"]["seed_paths"] == []


if __name__ == "__main__":
    test_island_wiring()
    print("PASS test_island_wiring")
