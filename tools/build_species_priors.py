"""Build species → top-N-moves priors from training data."""
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.paths import data_path

DATA = data_path("training_data.jsonl")
OUT = data_path("species_move_priors.json")

counts = defaultdict(Counter)

with open(DATA) as f:
    for line in f:
        o = json.loads(line)
        side = o["side"]
        acts = o.get("chosen", {}).get(side, {})
        my_active = o["state"].get("my_active", [])
        for slot, action in acts.items():
            if not isinstance(action, dict):
                continue
            if action.get("type") != "move":
                continue
            slot_idx = 0 if slot == "a" else 1
            if slot_idx >= len(my_active):
                continue
            active = my_active[slot_idx]
            if not active:
                continue
            species = active.get("species")
            move = action.get("move")
            if species and move:
                counts[species][move] += 1

out = {sp: [{"move": m, "count": c} for m, c in cnt.most_common(30)]
       for sp, cnt in counts.items()}

json.dump(out, open(OUT, "w"), indent=2)
print(f"Wrote {len(out)} species priors -> {OUT}")

# Sample output
for sp in ["Incineroar", "Rillaboom", "Gholdengo", "Sneasler", "Charizard",
           "Salamence", "Garchomp", "Umbreon"]:
    if sp in out:
        top5 = [e["move"] for e in out[sp][:5]]
        print(f"  {sp:15s}  {top5}")
