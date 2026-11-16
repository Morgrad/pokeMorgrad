"""Single-island GA launcher.

Spawned by run/ga_parallel.sh. Reads island config from env, runs ONE
island, exits. No cross-process migration - the three islands evolve
independently for maximum diversity.

Env vars:
    ISLAND_NAME        "A" | "B" | "C"
    SHOWDOWN_PORT      8000 | 8001 | 8002
    GA_CONCURRENCY     default 8
    GA_GENERATIONS     default 999 (set 2 for a smoke test)

Args:
    argv[1]            run_id (default "p1")
    argv[2]            hours (default 4.0)

Island specs mirror run/ga_run.py:
    A = Umbreon locked slot 0, seeded from baseline
    B = Umbreon locked slot 0, no seed
    C = fully free, no seed

Umbreon lock removed 2026-11-15; pilot cannot use Taunt/Yawn (see STATE_history).
Re-add when pilot is fixed.

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
from src.decision_logger import DecisionLogger
from src.replay_filters import default_ga_filter

NAME = os.environ.get("ISLAND_NAME", "A").upper()
PORT = os.environ.get("SHOWDOWN_PORT", "8000")
CONC = int(os.environ.get("GA_CONCURRENCY", "8"))
RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "p1"
HOURS = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0

BASELINE = data_path("baseline_team.txt")

# Check if replay logging is enabled
GA_REPLAY_LOG = os.environ.get("GA_REPLAY_LOG", "")
GA_REPLAY_MAX_PER_GEN = int(os.environ.get("GA_REPLAY_MAX_PER_GEN", "50"))
GA_REPLAY_DIR = os.environ.get("GA_REPLAY_DIR", "output/replay_log")

# Initialize logger if replay logging is enabled
logger = None
if GA_REPLAY_LOG:
    logger = DecisionLogger(GA_REPLAY_DIR, max_rows_per_battle=GA_REPLAY_MAX_PER_GEN)

SPECS = {
    "A": {"constraints": {}, "seed_paths": [BASELINE]},
    "B": {"constraints": {}, "seed_paths": ["data/candidates/ga_q5_island_C_62p4.txt"]},
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

# Closure for save_callback that enforces GA_REPLAY_MAX_PER_GEN
async def run_island_with_logging():
    try:
        await run_islands(
            island_specs=[{
                "name": NAME,
                "constraints": spec["constraints"],
                "seed_paths": spec["seed_paths"],
            }],
            pop_per_island=10,
            generations=int(os.environ.get("GA_GENERATIONS", "999")),
            battles_per_genome=50,
            concurrency=CONC,
            immigration_rate=0.20,
            stagnation_limit=5,
            diversity_floor=15,
            migration_every=999,        # single island -> disable ring migration
            showdown_restart_every=10,
            max_hours=HOURS,
            run_id=f"{RUN_ID}_{NAME}",  # checkpoints: v6/p1_A, v6/p1_B, v6/p1_C
        )
    finally:
        if logger is not None:
            logger.close()

if __name__ == "__main__":
    asyncio.run(run_island_with_logging())
