"""Single-island GA launcher.

Spawned by run/ga_parallel.sh. Reads island config from env, runs ONE
island, exits. No cross-process migration - the three islands evolve
independently for maximum diversity.

Env vars:
    ISLAND_NAME        "A" | "B" | "C"
    SHOWDOWN_PORT      8000 | 8001 | 8002
    GA_CONCURRENCY     default 8
    GA_GENERATIONS     default 999 (set 2 for a smoke test)
    GA_REPLAY_LOG      if set (non-empty), saves a sample of full battle logs
    GA_REPLAY_MAX_PER_GEN default 50: max battles saved per island and generation
    GA_REPLAY_DIR      default <repo>/output/replay_log -> <dir>/<run_id>_<X>/<X>_genNNNN.jsonl
                       (see src/replay_log.py; logging never changes the GA's results)

Args:
    argv[1]            run_id (default "p1")
    argv[2]            hours (default 4.0)

Island specs (same as run/ga_run.py; pinned by tests/test_island_wiring.py):
    A = Umbreon locked in slot 0 + seeded with data/baseline_team.txt
    B = Umbreon locked in slot 0, no seed -> the GA fills the 5 free slots
    C = fully free: no lock, no seed

History: the lock was removed on 2026-11-15 and restored on A and B on 2026-11-17.

Per-island RNG seed: A=42, B=137, C=999, so islands with the same constraints
do not evolve identical streams.
"""
import asyncio
import os
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.ga.engine import run_islands
from src.paths import data_path, output_path, showdown_port
from src.replay_log import ReplayLogger

NAME = os.environ.get("ISLAND_NAME", "A").upper()
PORT = showdown_port()
CONC = int(os.environ.get("GA_CONCURRENCY", "8"))
RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "p1"
HOURS = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0

BASELINE = data_path("baseline_team.txt")

# Check if replay logging is enabled
GA_REPLAY_LOG = os.environ.get("GA_REPLAY_LOG", "")
GA_REPLAY_MAX_PER_GEN = int(os.environ.get("GA_REPLAY_MAX_PER_GEN", "50"))
GA_REPLAY_DIR = os.environ.get("GA_REPLAY_DIR") or output_path("replay_log")

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


def make_replay_logger():
    """ReplayLogger when GA_REPLAY_LOG is set, else None."""
    if not GA_REPLAY_LOG:
        return None
    return ReplayLogger(GA_REPLAY_DIR, run_id=f"{RUN_ID}_{NAME}",
                        max_per_gen=GA_REPLAY_MAX_PER_GEN, seed=SEEDS[NAME])


async def run_island():
    print(f"=== island {NAME} | run_id={RUN_ID}_{NAME} | port={PORT} | "
          f"{HOURS}h | conc={CONC} | seed={SEEDS[NAME]} ===", flush=True)
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
        replay_logger=make_replay_logger(),
    )


if __name__ == "__main__":
    asyncio.run(run_island())
