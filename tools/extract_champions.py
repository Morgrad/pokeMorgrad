"""Extract val and train champions from GA checkpoints, without running the GA.

Usage:
    python3 tools/extract_champions.py p3

Reads output/checkpoints/v6/p3_<A|B|C>/gen_NNNN.json (latest per island),
writes both champion files.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "project"))
from src.ga_core import genome_to_text, CHAMPION_DIR

CKPT_ROOT = Path.home() / "project" / "output" / "checkpoints" / "v6"

if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)
RUN_ID = sys.argv[1]

Path(CHAMPION_DIR).mkdir(parents=True, exist_ok=True)

for island_name in ("A", "B", "C"):
    isl_dir = CKPT_ROOT / f"{RUN_ID}_{island_name}"
    if not isl_dir.exists():
        print(f"  {island_name}: no checkpoint dir {isl_dir}")
        continue
    ckpts = sorted(isl_dir.glob("gen_*.json"))
    if not ckpts:
        print(f"  {island_name}: no checkpoints")
        continue
    latest = ckpts[-1]
    data = json.loads(latest.read_text())

    # islands is a LIST of dicts, find the matching one by name
    isl_data = None
    for entry in data.get("islands", []):
        if entry.get("name") == island_name:
            isl_data = entry
            break
    if isl_data is None:
        print(f"  {island_name}: not found in {latest.name}")
        continue

    best_ever = isl_data.get("best_ever", {})
    best_val = isl_data.get("best_val_ever", {})

    # Val champion
    if best_val.get("genome"):
        path = Path(CHAMPION_DIR) / f"ga_{RUN_ID}_island_{island_name}.txt"
        path.write_text(genome_to_text(best_val["genome"]))
        print(f"  {island_name}: val   {best_val['fit']*100:.1f}%  "
              f"(train {best_ever.get('fit', 0)*100:.1f}%)  -> {path.name}")
    else:
        print(f"  {island_name}: no val genome in {latest.name}")

    # Train champion
    if best_ever.get("genome"):
        path = Path(CHAMPION_DIR) / f"ga_{RUN_ID}_island_{island_name}_train.txt"
        path.write_text(genome_to_text(best_ever["genome"]))
        print(f"  {island_name}: train {best_ever['fit']*100:.1f}%  "
              f"-> {path.name}")
    else:
        print(f"  {island_name}: no train genome in {latest.name}")

print(f"\nSource checkpoint: {latest.name}")
