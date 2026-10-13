"""Build data/training_data.jsonl from raw Showdown replays.

THIS is the training-data driver — the one bc_train.py consumes. It reads
data/showdown_replays/*.json, replays each with the Tracker to recover per-turn
decisions, tags every row with:
  - side_won   (bool, from the |win| line vs the |player| names)
  - target_a / target_b  (canonical target index per active slot, see _target_idx)
and writes one JSON object per line.

Do NOT regenerate training data with tools/batch_parse.py (archived) — it predates
the side_won/target_* schema and silently degrades bc_train. Keep this file's
output schema in lockstep with bc_train's reader (bc_train.py).

Usage:
  python tools/build_training_data.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay_tracker import Tracker

REPLAY_DIR = Path(__file__).resolve().parent.parent / "data" / "showdown_replays"
OUT = Path(__file__).resolve().parent.parent / "data" / "training_data.jsonl"


def parse_log(log):
    """Return (p1_name, p2_name, winner_name, is_tie). All may be None."""
    p1 = p2 = winner = None
    is_tie = False
    for line in log.splitlines():
        if line.startswith("|player|p1|") and p1 is None:
            parts = line.split("|")
            if len(parts) >= 4 and parts[3]:
                p1 = parts[3]
        elif line.startswith("|player|p2|") and p2 is None:
            parts = line.split("|")
            if len(parts) >= 4 and parts[3]:
                p2 = parts[3]
        elif line.startswith("|win|"):
            parts = line.split("|", 2)
            if len(parts) >= 3:
                winner = parts[2]
        elif line.startswith("|tie|"):
            is_tie = True
    return p1, p2, winner, is_tie



def _target_idx(side, target_str):
    """Normalize Showdown target string to canonical index.

    0 = our right (-2), 1 = our left (-1), 2 = no target (0),
    3 = opp left (1), 4 = opp right (2).
    """
    if not target_str or target_str.startswith("no "):
        return 2
    # Strip the " : SpeciesName" suffix that Showdown appends
    slot = target_str.split(":", 1)[0].strip()
    if side == "p1":
        my_left, my_right, opp_left, opp_right = "p1a", "p1b", "p2a", "p2b"
    else:
        my_left, my_right, opp_left, opp_right = "p2a", "p2b", "p1a", "p1b"
    if slot == my_left:  return 1
    if slot == my_right: return 0
    if slot == opp_left:  return 3
    if slot == opp_right: return 4
    return 2  # fallback


def main():
    files = sorted(f for f in REPLAY_DIR.glob("*.json")
                   if not f.name.endswith(".meta.json"))
    print(f"{len(files)} replay files to process", flush=True)

    n_rows = 0
    skip_reasons = {}
    with open(OUT, "w") as fout:
        for i, fp in enumerate(files):
            try:
                d = json.load(open(fp))
                log = d.get("log", "")
                if not log:
                    skip_reasons["no_log"] = skip_reasons.get("no_log", 0) + 1
                    continue

                p1, p2, winner, is_tie = parse_log(log)
                if is_tie:
                    skip_reasons["tie"] = skip_reasons.get("tie", 0) + 1
                    continue
                if not (p1 and p2):
                    skip_reasons["no_players"] = skip_reasons.get("no_players", 0) + 1
                    continue
                if not winner:
                    skip_reasons["no_winner"] = skip_reasons.get("no_winner", 0) + 1
                    continue

                outs = Tracker(d).run()
                if not outs:
                    skip_reasons["tracker_empty"] = skip_reasons.get("tracker_empty", 0) + 1
                    continue

                for row in outs:
                    side = row.get("side")
                    if side == "p1":
                        row["side_won"] = (winner == p1)
                    elif side == "p2":
                        row["side_won"] = (winner == p2)
                    else:
                        continue
                    # Extract target_idx per slot from `chosen`
                    chosen = row.get("chosen", {}).get(side, {}) or {}
                    for slot_name in ("a", "b"):
                        act = chosen.get(slot_name) or {}
                        tgt = act.get("target")
                        row[f"target_{slot_name}"] = _target_idx(side, tgt)
                    fout.write(json.dumps(row) + "\n")
                    n_rows += 1

                if (i + 1) % 500 == 0:
                    print(f"  {i+1}/{len(files)}  rows={n_rows}  "
                          f"skipped={sum(skip_reasons.values())}", flush=True)
            except Exception as e:
                key = f"exc_{type(e).__name__}"
                skip_reasons[key] = skip_reasons.get(key, 0) + 1
                if skip_reasons[key] <= 3:
                    print(f"  {fp.name}: {type(e).__name__}: {e}")

    print(f"DONE: {n_rows} rows")
    print(f"Skip reasons: {skip_reasons}")


if __name__ == "__main__":
    main()
