"""
Umbreon-constrained counter-meta GA.

Edit LOCKED to lock other slots too, e.g.:
  LOCKED = {0: "Umbreon", 2: "Incineroar", 5: "Garchomp"}
Any species can be locked in any slot.
"""
import asyncio, os, sys
sys.path.insert(0, os.path.expanduser("~/project/src"))
from ga_core import run_ga

LOCKED = {0: "Umbreon"}   # edit me

if __name__ == "__main__":
    asyncio.run(run_ga(
        locked=LOCKED,
        pop_size=15,
        generations=15,
        battles_per_genome=150,
        concurrency=3,
        seed_path=os.path.expanduser("~/project/data/baseline_team.txt"),
        label="umbreon",
    ))
