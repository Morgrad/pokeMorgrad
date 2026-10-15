"""Single-island GA launcher.

Spawned by run/ga_parallel.sh. Reads island config from env, runs ONE
island, exits. No cross-process migration - the three islands evolve
independently for maximum diversity.

Env vars:
    ISLAND_NAME        "A" | "B" | "C"
    SHOWDOWN_PORT      8000 | 8001 | 8002
    GA_CONCURRENCY     default 8

Args:
    argv[1]            run_id (default "p1")
    argv[2]            hours (default 4.0)

Island specs mirror run/ga_run.py:
    A = Umbreon locked slot 0, seeded from baseline
    B = Umbreon locked slot 0, no seed
    C = fully free, no seed

Per-island RNG seed: A=42, B=137, C=999. Different streams so B and C
(which share constraints={}) don't evolve identically.
"""
import asyncio
import os
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.ga_core import run_islands
from src.paths import data_path

NAME = os.environ.get("ISLAND_NAME", "A").upper()
PORT = os.environ.get("SHOWDOWN_PORT", "8000")
CONC = int(os.environ.get("GA_CONCURRENCY", "8"))
RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "p1"
HOURS = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0

BASELINE = data_path("baseline_team.txt")

SPECS = {
    "A": {"constraints": {0: "Umbreon"}, "seed_paths": [BASELINE]},
    "B": {"constraints": {0: "Umbreon"}, "seed_paths": []},
    "C": {"constraints": {},             "seed_paths": []},
}
SEEDS = {"A": 42, "B": 137, "C": 999}

if NAME not in SPECS:
    print(f"ERROR: ISLAND_NAME must be A, B, or C (got {NAME!r})", flush=True)
    sys.exit(1)

random.seed(SEEDS[NAME])

spec = SPECS[NAME]
print(f"=== island {NAME} | run_id={RUN_ID}_{NAME} | port={PORT} | "
      f"{HOURS}h | conc={CONC} | seed={SEEDS[NAME]} ===", flush=True)

asyncio.run(run_islands(
    island_specs=[{
        "name": NAME,
        "constraints": spec["constraints"],
        "seed_paths": spec["seed_paths"],
    }],
    pop_per_island=10,
    generations=999,
    battles_per_genome=800,
    concurrency=CONC,
    immigration_rate=0.20,
    stagnation_limit=5,
    diversity_floor=15,
    migration_every=999,        # single island -> disable ring migration
    showdown_restart_every=10,
    max_hours=HOURS,
    run_id=f"{RUN_ID}_{NAME}",  # checkpoints: v6/p1_A, v6/p1_B, v6/p1_C
))
