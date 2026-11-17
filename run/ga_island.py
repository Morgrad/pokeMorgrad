"""Single-island GA launcher.

Spawned by run/ga_parallel.sh. Reads island config from env, runs ONE
island, exits. No cross-process migration - the three islands evolve
independently for maximum diversity.

Env vars:
    ISLAND_NAME        "A" | "B" | "C"
    SHOWDOWN_PORT      8000 | 8001 | 8002
    GA_CONCURRENCY     default 8
    GA_GENERATIONS     default 999 (set 2 for a smoke test)
    GA_REPLAY_LOG      if set, enables replay logging
    GA_REPLAY_MAX_PER_GEN default 50
    GA_REPLAY_DIR      default "output/replay_log"

Args:
    argv[1]            run_id (default "p1")
    argv[2]            hours (default 4.0)

Island specs mirror run/ga_run.py:
    A = seeded from baseline
    B = seeded from q5 candidate C
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

from src.decision_logger import DecisionLogger
from src.ga_core import run_islands
from src.paths import data_path
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

logger = None
if GA_REPLAY_LOG:
    logger = DecisionLogger(GA_REPLAY_DIR, max_rows_per_battle=GA_REPLAY_MAX_PER_GEN)

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

def save_callback(battle_history, genome_species, fitness, outcome):
    if logger:
        logger.log_turn(
            battle_id=f"{NAME}_{random.randint(100000, 999999)}",
            island=NAME,
            gen=0,
            genome_fitness=fitness,
            outcome=outcome,
            our_team=genome_species,
            opp_team=[], our_active=[], opp_active=[], our_hp=[], opp_hp=[],
            field={}, legal_moves=[], chosen="", heuristic_choice="", target="", battle_history=battle_history
        )

async def run_island_with_logging():
    print(f"=== island {NAME} | run_id={RUN_ID}_{NAME} | port={PORT} | "
          f"{HOURS}h | conc={CONC} | seed={SEEDS[NAME]} ===", flush=True)

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
            migration_every=999,
            showdown_restart_every=10,
            max_hours=HOURS,
            run_id=f"{RUN_ID}_{NAME}",
            save_filter=default_ga_filter if GA_REPLAY_LOG else None,
            save_callback=save_callback if GA_REPLAY_LOG else None,
        )
    finally:
        if logger is not None:
            logger.close()

if __name__ == "__main__":
    asyncio.run(run_island_with_logging())
