"""Encoder equivalence gate — prove StateEncoder output is bit-for-bit unchanged.

src/state_encoder.py feeds the FROZEN BC checkpoint, so any "output-equivalent"
refactor of it (e.g. the 2B precompute change: list.index() scans → dict lookups,
hoisted active_mask) must not move a single bit of any tensor. This is the
mechanical gate the refactor plan requires — not a vibe check.

Workflow:
    # 1. BEFORE editing state_encoder.py, capture the reference:
    python tools/encode_snapshot.py capture

    # 2. AFTER editing, recompute and compare (exit 0 = identical, 1 = drift):
    python tools/encode_snapshot.py check

Coverage: a handful of synthetic edge-case states that deliberately exercise the
unknown-value fallbacks (status / weather / terrain NOT in the contract lists →
bin 0, the exact branch the .index() → .get() swap touches), plus the first
N_REAL real states from data/training_data.jsonl if present.
"""
import json
import os
import sys

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.paths import data_path
from src.state_encoder import StateEncoder

REF_PATH = os.environ.get("ENC_SNAPSHOT_REF", "/tmp/enc_snapshot_ref.pt")
N_REAL = 200

# Synthetic states chosen to light up the branches 2B changes. Vocab hits don't
# matter for an equivalence test (unknown names → pad 0 identically before and
# after); what matters is covering the one-hot fallbacks and every cont[] field.
SYNTHETIC_STATES = [
    {   # known status/weather/terrain/boosts/mega/fainted — the happy path
        "my_active": [
            {"species": "Incineroar", "revealed_moves": ["Fake Out", "Flare Blitz"],
             "item": "Sitrus Berry", "ability": "Intimidate",
             "hp_now": 73, "hp_max": 100, "status": "brn",
             "boosts": {"atk": 2, "spe": -1}, "is_mega": False},
            {"species": "Rillaboom", "revealed_moves": ["Grassy Glide"],
             "hp_now": 0, "hp_max": 100, "status": "none",
             "boosts": {}, "is_mega": False},
        ],
        "my_bench": [{"species": "Amoonguss", "revealed_moves": ["Spore"],
                      "hp_now": 100, "hp_max": 100}],
        "opp_active": [{"species": "Garchomp", "revealed_moves": [],
                        "hp_now": 50, "hp_max": 100, "is_mega": True}],
        "opp_seen": [],
        "field": {"weather": "SunnyDay", "terrain": "Grassy",
                  "trick_room": True, "tailwind": {"p1": 1, "p2": 0}},
    },
    {   # UNKNOWN status/weather/terrain — must all collapse to bin 0
        "my_active": [
            {"species": "Nonexistent-Mon", "revealed_moves": ["Fake Move"],
             "item": "Not An Item", "ability": "Fake Ability",
             "hp_now": 40, "hp_max": 160, "status": "cursed",
             "boosts": {"def": 6, "spd": -6}, "is_mega": False},
            None,
        ],
        "my_bench": [],
        "opp_active": [None, None],
        "opp_seen": [],
        "field": {"weather": "Tornado", "terrain": "Lava",
                  "trick_room": False, "tailwind": {"p1": 0, "p2": 3}},
    },
    {   # near-empty state — all pads, no field
        "my_active": [], "my_bench": [], "opp_active": [], "opp_seen": [],
    },
]


def build_states():
    states = list(SYNTHETIC_STATES)
    try:
        with open(data_path("training_data.jsonl")) as f:
            for i, line in enumerate(f):
                if i >= N_REAL:
                    break
                states.append(json.loads(line)["state"])
    except FileNotFoundError:
        print("  (no training_data.jsonl — synthetic states only)")
    return states


def encode_all(enc, states):
    return [{k: v.clone() for k, v in enc.encode(s).items()} for s in states]


def capture():
    snaps = encode_all(StateEncoder(), build_states())
    torch.save(snaps, REF_PATH)
    print(f"captured {len(snaps)} encoded states -> {REF_PATH}")


def check():
    cur = encode_all(StateEncoder(), build_states())
    ref = torch.load(REF_PATH)
    if len(cur) != len(ref):
        print(f"FAIL: state count changed {len(ref)} -> {len(cur)}")
        return 1
    mismatches = 0
    for i, (a, b) in enumerate(zip(ref, cur)):
        for k in a:
            if not torch.equal(a[k], b[k]):
                mismatches += 1
                if mismatches <= 5:
                    print(f"  MISMATCH state#{i} tensor '{k}'")
    if mismatches:
        print(f"FAIL: {mismatches} tensor mismatch(es) — encoder output DRIFTED")
        return 1
    print(f"PASS: all {len(cur)} states x {len(cur[0])} tensors bit-identical")
    return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "capture":
        capture()
    elif mode == "check":
        sys.exit(check())
    else:
        print("usage: python tools/encode_snapshot.py [capture|check]")
        sys.exit(2)
