"""Add newly-scraped teams to the training pool. Holdout is untouched.

Usage:
    python3 tools/extend_train_pool.py <prefix>
    python3 tools/extend_train_pool.py louisville

Appends <prefix>_*.txt filenames to pool_split.json["train"]. Verifies:
  - New files exist on disk
  - No overlap with existing train entries
  - No overlap with pool_split_golden.json["holdout"] (if golden exists)

Never modifies ["holdout"]. The holdout stays frozen for cross-week
comparability.
"""
import json
import sys
from pathlib import Path

REPO = Path.home() / "project"
REGIONAL_DIR = REPO / "data" / "regional_teams"
SPLIT_PATH = REPO / "data" / "pool_split.json"
GOLDEN_PATH = REPO / "data" / "pool_split_golden.json"

if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)
PREFIX = sys.argv[1]

new_files = sorted(f.name for f in REGIONAL_DIR.glob(f"{PREFIX}_*.txt"))
if not new_files:
    print(f"No files matching {PREFIX}_*.txt found. Abort.")
    sys.exit(1)

split = json.loads(SPLIT_PATH.read_text())
train = set(split["train"])
holdout = set(split["holdout"])

overlap_train = set(new_files) & train
overlap_hold = set(new_files) & holdout
if overlap_train:
    print(f"WARN: {len(overlap_train)} of {len(new_files)} already in train. Skipping those.")
    new_files = [f for f in new_files if f not in train]
if overlap_hold:
    print(f"ERROR: {len(overlap_hold)} of the new files are in the holdout:")
    for f in list(overlap_hold)[:5]:
        print(f"  {f}")
    sys.exit(1)

if GOLDEN_PATH.exists():
    golden = json.loads(GOLDEN_PATH.read_text())
    if holdout != set(golden["holdout"]):
        print("WARN: current holdout differs from golden. Cross-week comparability is broken.")
        print("      Run 'diff <(jq .holdout pool_split.json) <(jq .holdout pool_split_golden.json)' to inspect.")
        if input("Continue anyway? [y/N] ").lower() != "y":
            sys.exit(1)

if not new_files:
    print("Nothing to add. Exiting.")
    sys.exit(0)

new_train = sorted(train | set(new_files))
split["train"] = new_train
SPLIT_PATH.write_text(json.dumps({"train": new_train,
                                  "holdout": sorted(holdout)}, indent=2))

print(f"Added {len(new_files)} files to train.")
print(f"  train:   {len(train)} -> {len(new_train)}")
print(f"  holdout: {len(holdout)} (unchanged)")
print(f"\nWrote {SPLIT_PATH}")
