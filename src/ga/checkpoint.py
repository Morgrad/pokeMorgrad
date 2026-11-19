"""
Checkpoint and champion files of a GA run.

Both on-disk formats are fixed: resumes, run/ga_parallel.sh respawns and
tools/extract_champions.py depend on them.

  output/checkpoints/v6/<run_id>/gen_NNNN.json
      {"generation", "saved", "islands": [Island.to_dict(), ...]}, indent=2.
      Retention: the newest is always kept, older ones only on multiples of 5.
  output/champions/ga_<run_id>_island_<name>.txt         primary champion
  output/champions/ga_<run_id>_island_<name>_train.txt   training-best
"""
import json
import os
import time

from src.ga import config as C
from src.ga.genome import genome_to_text
from src.ga.population import Island


def save_checkpoint(generation, islands, run_id="run1"):
    """Write a full-run checkpoint and prune old ones, keeping every 5th gen.

    Retention: the latest checkpoint is always kept; older ones survive only if
    their generation is a multiple of 5. This bounds disk use over a long run
    while still leaving periodic restore points. Returns the path written.
    """
    base = os.path.join(C.CHECKPOINT_DIR, run_id)
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"gen_{generation:04d}.json")
    state = {
        "generation": generation,
        "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
        "islands": [isl.to_dict() for isl in islands],
    }
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
    all_ckpts = sorted(f for f in os.listdir(base) if f.startswith("gen_"))
    for f in all_ckpts[:-1]:   # never prune the newest
        try:
            gen = int(f.split("_")[1].split(".")[0])
            if gen % 5 != 0:   # keep multiples of 5 as periodic restore points
                os.remove(os.path.join(base, f))
        except Exception:
            pass
    return path


def load_latest_checkpoint(run_id="run1"):
    """Path of the highest-numbered checkpoint for a run, or None if none exist."""
    base = os.path.join(C.CHECKPOINT_DIR, run_id)
    if not os.path.isdir(base):
        return None
    files = sorted(f for f in os.listdir(base) if f.startswith("gen_"))
    if not files:
        return None
    return os.path.join(base, files[-1])


def load_islands(path):
    """(islands, generation) from a checkpoint file. Raises on a missing/corrupt file."""
    with open(path) as f:
        state = json.load(f)
    return [Island.from_dict(d) for d in state["islands"]], state["generation"]


def write_champions(islands, run_id):
    """Write each island's champion files and print one line per file written.

    Primary champion = train best (val-selection was dropped 2026-10-15, see docs/design/decisions.md); fall
    back to the val best only if no train genome exists.
    """
    os.makedirs(C.CHAMPION_DIR, exist_ok=True)
    for isl in islands:
        best = isl.best_ever if isl.best_ever["genome"] else isl.best_val_ever
        label = "train" if isl.best_ever["genome"] else "val"
        if best["genome"]:
            path = os.path.join(C.CHAMPION_DIR, f"ga_{run_id}_island_{isl.name}.txt")
            with open(path, "w") as f:
                f.write(genome_to_text(best["genome"]))
            print(f"  [{isl.name}] champion ({label}): {best['fit']*100:.1f}% "
                  f"(train best {isl.best_ever['fit']*100:.1f}%) -> {path}")
        if isl.best_ever["genome"]:
            path = os.path.join(
                C.CHAMPION_DIR, f"ga_{run_id}_island_{isl.name}_train.txt")
            with open(path, "w") as f:
                f.write(genome_to_text(isl.best_ever["genome"]))
            print(f"  [{isl.name}] champion (train): "
                  f"{isl.best_ever['fit']*100:.1f}% -> {path}")
