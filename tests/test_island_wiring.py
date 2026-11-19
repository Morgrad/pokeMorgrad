"""Island specs of both GA launchers (run/ga_island.py and run/ga_run.py).

Intended layout:
  A = Umbreon locked in slot 0 + always seeded with the baseline team
  B = Umbreon locked in slot 0, no seed -> 5 slots free for the GA
  C = fully free: no lock, no seed

Run: python tests/test_island_wiring.py   (or: pytest tests/test_island_wiring.py)
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _load(module, argv):
    # Both launchers parse sys.argv at import time; give them their own argv.
    saved = sys.argv
    sys.argv = argv
    try:
        sys.modules.pop(module, None)
        return importlib.import_module(module)
    finally:
        sys.argv = saved


def _check_layout(specs):
    assert set(specs) == {"A", "B", "C"}

    # A: Umbreon lock + always seeded with the baseline team
    assert specs["A"]["constraints"] == {0: "Umbreon"}
    assert [os.path.basename(p) for p in specs["A"]["seed_paths"]][:1] == ["baseline_team.txt"]

    # B: Umbreon lock in slot 0, no baseline seed -> 5 free slots
    assert specs["B"]["constraints"] == {0: "Umbreon"}
    assert not any(os.path.basename(p) == "baseline_team.txt" for p in specs["B"]["seed_paths"])

    # C: fully free
    assert specs["C"]["constraints"] == {}
    assert not any(os.path.basename(p) == "baseline_team.txt" for p in specs["C"]["seed_paths"])


def test_island_wiring():
    island = _load("run.ga_island", ["ga_island.py", "test", "1"])
    _check_layout(island.SPECS)
    # The parallel launcher never warm-starts: B and C have no seed at all.
    assert island.SPECS["A"]["seed_paths"] == [island.BASELINE]
    assert island.SPECS["B"]["seed_paths"] == []
    assert island.SPECS["C"]["seed_paths"] == []


def test_serial_launcher_matches():
    # run_id "run1" -> no warm start, so the seeds are exactly the spec.
    serial = _load("run.ga_run", ["ga_run.py", "run1", "1"])
    _check_layout({spec["name"]: spec for spec in serial.ISLANDS})
    assert serial.ISLANDS[0]["seed_paths"] == [serial.BASELINE]


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
