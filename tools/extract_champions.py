"""Write champion files from the latest GA checkpoints, without running the GA.

Usage:
    python tools/extract_champions.py p3

Reads output/checkpoints/v6/p3_<A|B|C>/gen_NNNN.json (latest per island) and writes,
per island, the same files the GA writes at the end of a run (same rule as
src/ga/checkpoint.py::write_champions):
    ga_p3_island_X.txt        primary champion = train best (best_ever); the val best
                              only if the checkpoint has no train genome
    ga_p3_island_X_train.txt  train best
plus one extra file the GA does not write:
    ga_p3_island_X_val.txt    best genome on the 30-team validation slice (best_val_ever)

(Before 2026-11-18 this tool wrote the val best as the primary file, which silently
replaced the GA's own train-best champion when run after a finished run.)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.ga.config import CHAMPION_DIR, CHECKPOINT_DIR
from src.ga.genome import genome_to_text


def _write(path, genome):
    path.write_text(genome_to_text(genome))
    return path.name


def extract(run_id, ckpt_root=CHECKPOINT_DIR, champion_dir=CHAMPION_DIR, islands=("A", "B", "C")):
    """Write the champion files for `run_id`; returns {island: [file names written]}."""
    out_dir = Path(champion_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for name in islands:
        isl_dir = Path(ckpt_root) / f"{run_id}_{name}"
        ckpts = sorted(isl_dir.glob("gen_*.json")) if isl_dir.exists() else []
        if not ckpts:
            print(f"  {name}: no checkpoints in {isl_dir}")
            continue
        latest = ckpts[-1]
        isl = next((e for e in json.loads(latest.read_text()).get("islands", [])
                    if e.get("name") == name), None)
        if isl is None:
            print(f"  {name}: island not found in {latest.name}")
            continue
        best = isl.get("best_ever") or {}
        val = isl.get("best_val_ever") or {}
        files = []
        primary = best if best.get("genome") else val
        if primary.get("genome"):
            label = "train" if best.get("genome") else "val"
            files.append(_write(out_dir / f"ga_{run_id}_island_{name}.txt", primary["genome"]))
            print(f"  {name}: champion ({label}) {primary['fit']*100:.1f}%  -> {files[-1]}")
        if best.get("genome"):
            files.append(_write(out_dir / f"ga_{run_id}_island_{name}_train.txt", best["genome"]))
        if val.get("genome"):
            files.append(_write(out_dir / f"ga_{run_id}_island_{name}_val.txt", val["genome"]))
            print(f"  {name}: val best {val['fit']*100:.1f}% "
                  f"(train best {best.get('fit', 0)*100:.1f}%)  -> {files[-1]}")
        print(f"  {name}: source {latest.name}")
        written[name] = files
    return written


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    extract(sys.argv[1])
