"""Build data/training_data.jsonl from raw Showdown replays.

Reads data/showdown_replays/*.json, extracts decisions with the Tracker,
tags each with side_won (from |win| line), writes JSONL.
"""
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay_tracker import Tracker

REPLAY_DIR = Path(__file__).resolve().parent.parent / "data" / "showdown_replays"
OUT = Path(__file__).resolve().parent.parent / "data" / "training_data.jsonl"


def _get_player_names(log):
    p1 = p2 = None
    for line in log.split("\n"):
        if line.startswith("|player|p1|"):
            p1 = line.split("|")[3]
        elif line.startswith("|player|p2|"):
            p2 = line.split("|")[3]
    return p1, p2


def _get_winner(log):
    for line in log.split("\n"):
        if line.startswith("|win|"):
            return line.split("|", 2)[2]
    return None


def main():
    files = sorted(REPLAY_DIR.glob("*.json"))
    files = [f for f in files if not f.name.endswith(".meta.json")]
    print(f"{len(files)} replay files to process")

    n_rows = 0
    n_skipped = 0
    with open(OUT, "w") as fout:
        for i, fp in enumerate(files):
            try:
                d = json.load(open(fp))
                log = d.get("log", "")
                p1, p2 = _get_player_names(log)
                winner = _get_winner(log)
                if not (p1 and p2 and winner):
                    n_skipped += 1
                    continue

                t = Tracker(d)
                outs = t.run()

                for row in outs:
                    side = row.get("side")
                    if side == "p1":
                        row["side_won"] = (winner == p1)
                    elif side == "p2":
                        row["side_won"] = (winner == p2)
                    else:
                        continue
                    fout.write(json.dumps(row) + "\n")
                    n_rows += 1

                if (i + 1) % 500 == 0:
                    print(f"  {i+1}/{len(files)}  rows={n_rows}  "
                          f"skipped={n_skipped}", flush=True)
            except Exception as e:
                n_skipped += 1
                if n_skipped <= 10:
                    print(f"  skip {fp.name}: {type(e).__name__}: {e}")

    print(f"DONE: {n_rows} rows, {n_skipped} replays skipped")


if __name__ == "__main__":
    main()
