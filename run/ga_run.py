"""
5-hour GA run — parametrized by run_id.

Usage:
    python ga_run.py <run_id> [<hours>]

Islands:
    A = Umbreon locked in slot 0
    B = free
    C = free
"""
import asyncio
import os
import random
import sys

sys.path.insert(0, os.path.expanduser("~/project/src"))
from src.ga_core import run_islands

BASELINE = os.path.expanduser("~/project/data/baseline_team.txt")
CHAMP_DIR = os.path.expanduser("~/project/output/champions")

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "run1"
HOURS = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0

seed_base = {"run1": 42, "run2": 137, "run3": 999}.get(RUN_ID, 42)
random.seed(seed_base)

warm_a = os.path.join(CHAMP_DIR, "ga_run1_island_A.txt")
warm_b = os.path.join(CHAMP_DIR, "ga_run1_island_B.txt")
warm_c = os.path.join(CHAMP_DIR, "ga_run1_island_C.txt")
use_warm = RUN_ID != "run1"

ISLANDS = [
    {
        "name": "A",
        "constraints": {0: "Umbreon"},
        "seed_paths": [BASELINE] + ([warm_a] if use_warm and os.path.exists(warm_a) else []),
    },
    {
        "name": "B",
        "constraints": {},
        "seed_paths": [BASELINE] + ([warm_b] if use_warm and os.path.exists(warm_b) else []),
    },
    {
        "name": "C",
        "constraints": {},
        "seed_paths": ([warm_c] if use_warm and os.path.exists(warm_c) else []),
    },
]

if __name__ == "__main__":
    print(f"=== {RUN_ID}: {HOURS}h, seed {seed_base} ===")
    asyncio.run(run_islands(
        island_specs=ISLANDS,
        pop_per_island=10,
        generations=999,
        battles_per_genome=800,
        concurrency=3,
        immigration_rate=0.20,
        stagnation_limit=5,
        diversity_floor=15,
        migration_every=5,
        showdown_restart_every=10,
        max_hours=HOURS,
        run_id=RUN_ID,
    ))
