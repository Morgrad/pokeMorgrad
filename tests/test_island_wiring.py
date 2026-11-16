import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def test_island_wiring():
    import run.ga_island as island

    # Assert no Umbreon lock
    assert "Umbreon" not in str(island.SPECS["A"]["constraints"])
    assert "Umbreon" not in str(island.SPECS["B"]["constraints"])
    assert "Umbreon" not in str(island.SPECS["C"]["constraints"])

    # Assert Island B seed
    b_seed = island.SPECS["B"]["seed_paths"][0]
    assert b_seed.endswith("ga_q5_island_C_62p4.txt")

    print("PASS test_island_wiring")
    return True

if __name__ == "__main__":
    if not test_island_wiring():
        exit(1)
