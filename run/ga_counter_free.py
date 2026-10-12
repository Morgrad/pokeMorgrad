"""
Unconstrained counter-meta GA. All 6 slots mutable.
"""
import asyncio, os, sys
sys.path.insert(0, os.path.expanduser("~/project/src"))
from ga_core import run_ga

LOCKED = {}   # no constraints

if __name__ == "__main__":
    asyncio.run(run_ga(
        locked=LOCKED,
        pop_size=15,
        generations=15,
        battles_per_genome=150,
        concurrency=3,
        seed_path=None,
        label="free",
    ))
