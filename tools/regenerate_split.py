"""Regenerate data/pool_split.json from the full regional_teams pool.

Backs up any existing split. Shuffles all .txt files in
data/regional_teams/ with a fixed seed, takes the first 100 as holdout
and the rest as train. Deterministic: rerunning with the same seed
produces the same split.

Usage:
    python3 tools/regenerate_split.py            # uses default seed
    python3 tools/regenerate_split.py 12345      # custom seed
"""
import json
import random
import sys
from collections import Counter
from pathlib import Path

REGIONAL_DIR = Path.home() / "project/data/regional_teams"
SPLIT_PATH = Path.home() / "project/data/pool_split.json"
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 20261015
HOLDOUT_SIZE = 100

all_teams = sorted(f.name for f in REGIONAL_DIR.glob("*.txt"))
print(f"Total .txt files in {REGIONAL_DIR}: {len(all_teams)}")

pre = Counter(t.split("_")[0] for t in all_teams)
print("\nBreakdown by tournament:")
for p, n in sorted(pre.items()):
    print(f"  {p:12s}: {n}")

rng = random.Random(SEED)
shuffled = list(all_teams)
rng.shuffle(shuffled)

holdout = sorted(shuffled[:HOLDOUT_SIZE])
train = sorted(shuffled[HOLDOUT_SIZE:])

overlap = set(train) & set(holdout)
print(f"\nTrain:   {len(train)}")
print(f"Holdout: {len(holdout)}")
print(f"Overlap: {len(overlap)}")
assert len(overlap) == 0, "overlap detected"

print("\nPer-tournament distribution in the new split:")
for p in sorted(pre.keys()):
    n_train = sum(1 for t in train if t.startswith(p + "_"))
    n_hold = sum(1 for t in holdout if t.startswith(p + "_"))
    pct = n_hold / (n_train + n_hold) * 100 if (n_train + n_hold) else 0
    print(f"  {p:12s}  train={n_train:3d}  holdout={n_hold:3d}  ({pct:.0f}% in holdout)")

missing = [t for t in train + holdout if not (REGIONAL_DIR / t).exists()]
if missing:
    print(f"\nWARN: {len(missing)} filenames not on disk (first 5):")
    for m in missing[:5]:
        print(f"  {m}")
else:
    print("\nAll filenames verified on disk")

if SPLIT_PATH.exists():
    backup = SPLIT_PATH.with_suffix(".json.bak")
    backup.write_text(SPLIT_PATH.read_text())
    print(f"\nBacked up old split to {backup}")

with open(SPLIT_PATH, "w") as f:
    json.dump({"train": train, "holdout": holdout}, f, indent=2)
print(f"Wrote new split to {SPLIT_PATH}")
