# =============================================================================
# LEGACY — pre-`side_won` schema. DO NOT USE to regenerate training data.
# =============================================================================
# The live driver is tools/build_training_data.py. This script writes the raw
# Tracker output and never tags rows with side_won / target_a / target_b — the
# exact labels bc_train.py reads. Training on its output silently degrades the
# BC model (missing win signal + target indices). Kept for reference only;
# archived out of the active tool path.
"""Process all scraped replays → training_data.jsonl.  [LEGACY — see header above]

Each line is a decision point with state + chosen action.
Skips decisions where chosen action is incomplete.
"""
import sys
import glob
import json
import os

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_TOOLS_DIR))  # repo root, for `src.paths`
sys.path.insert(0, _TOOLS_DIR)                    # for sibling `replay_tracker`
from src.paths import data_path
from replay_tracker import Tracker

REPLAY_DIR = data_path("showdown_replays")
OUT_PATH = data_path("training_data.jsonl")

files = sorted(f for f in glob.glob(os.path.join(REPLAY_DIR, "*.json"))
               if not f.endswith(".meta.json"))

print(f"Processing {len(files)} replays → {OUT_PATH}")

n_replays_ok = 0
n_replays_fail = 0
n_decisions = 0
n_decisions_skipped = 0
n_preview_actions = 0  # future

with open(OUT_PATH, "w") as fout:
    for i, fpath in enumerate(files, 1):
        try:
            d = json.load(open(fpath))
            t = Tracker(d)
            outputs = t.run()
            n_replays_ok += 1
        except Exception as e:
            n_replays_fail += 1
            if n_replays_fail <= 5:
                print(f"  fail: {os.path.basename(fpath)}: {e}")
            continue

        for o in outputs:
            chosen = o.get("chosen", {})
            # Require at least one side to have an action
            p1_has = bool(chosen.get("p1"))
            p2_has = bool(chosen.get("p2"))
            if not (p1_has or p2_has):
                n_decisions_skipped += 1
                continue
            fout.write(json.dumps(o, default=str) + "\n")
            n_decisions += 1

        if i % 250 == 0:
            print(f"  {i}/{len(files)}  ok={n_replays_ok}  fail={n_replays_fail}  decisions={n_decisions}")

print()
print(f"DONE")
print(f"  replays OK:       {n_replays_ok}")
print(f"  replays failed:   {n_replays_fail}")
print(f"  decisions kept:   {n_decisions}")
print(f"  decisions skipped: {n_decisions_skipped}")
print(f"  output: {OUT_PATH}")
print(f"  size: {os.path.getsize(OUT_PATH) / 1024 / 1024:.1f} MB")
