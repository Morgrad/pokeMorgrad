"""Fit foe-Mega timing rates from real ladder replays -> data/mega_rates.json.

Usage:
    python tools/build_mega_rates.py            # fit on all replays, write the file
    python tools/build_mega_rates.py --dry-run  # holdout report only (fit even files, score odd)

A decision point is a turn start where a side still has its Mega and a Mega-capable species is
on its field; the label is whether that mon Mega Evolved that turn. The table is indexed by
src.mega_model.cell_key (turns already had the chance x candidates on field x lead/back); the
per-species factor is shrunk toward 1 so rare species keep the table rate.
"""
import argparse
import glob
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from src import battle_memory as BM  # noqa: E402
from src import mega_model as MM  # noqa: E402

SHRINK = 30.0        # pseudo-observations pulling a species factor toward 1
MIN_SPECIES_N = 10


def extract(path):
    """Decision points of one replay: dicts with the mega_model.candidates fields plus 'y'."""
    d = json.load(open(path))
    chunks = [[]]
    for line in d["log"].split("\n"):
        p = line.split("|")
        if len(p) > 1 and p[1] == "turn":
            chunks.append([])
        chunks[-1].append(p)
    m = BM.BattleMemory()
    for p in chunks[0]:
        m.feed(p)
    out = []
    for turn, chunk in enumerate(chunks[1:], start=1):
        pend = [(side, c) for side in ("p1", "p2") for c in MM.candidates(m, side, turn)]
        for p in chunk:
            m.feed(p)
        for side, c in pend:
            rec = m.mon_by(side, c["name"])
            c["y"] = int(rec is not None and rec.mega_turn == turn)
            out.append(c)
    return out


def fit(rows):
    cells = defaultdict(lambda: [0, 0])
    for r in rows:
        t = cells[MM.cell_key(r["k"], r["ncand"], r["lead"])]
        t[0] += r["y"]
        t[1] += 1
    table = {k: (a + 1) / (n + 2) for k, (a, n) in cells.items()}
    obs, exp, cnt = defaultdict(float), defaultdict(float), defaultdict(int)
    for r in rows:
        if r["item"] or r["consumed"]:
            continue
        s = r["species"]
        obs[s] += r["y"]
        exp[s] += table[MM.cell_key(r["k"], r["ncand"], r["lead"])]
        cnt[s] += 1
    rel = {s: round((obs[s] + SHRINK) / (exp[s] + SHRINK), 4) for s in cnt if cnt[s] >= MIN_SPECIES_N}
    held = [r for r in rows if r["item"] and BM._id(r["item"]) in MM.stone_ids() and not r["consumed"]]
    return {"cells": {k: round(v, 4) for k, v in table.items()}, "species_rel": rel,
            "hold_floor": 0.8, "n_rows": len(rows), "n_stone_revealed": len(held)}


def logloss(rows, predict):
    eps = 1e-4
    tot = 0.0
    for r in rows:
        p = min(max(predict(r), eps), 1 - eps)
        tot -= math.log(p) if r["y"] else math.log(1 - p)
    return tot / len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    files = sorted(f for f in glob.glob(str(REPO / "data" / "showdown_replays" / "*.json"))
                   if not f.endswith(".meta.json"))
    per_file = [extract(f) for f in files]
    train = [r for i, rs in enumerate(per_file) if i % 2 == 0 for r in rs]
    test = [r for i, rs in enumerate(per_file) if i % 2 == 1 for r in rs]
    r_tr = fit(train)
    flat = sum(r["y"] for r in train) / len(train)
    by_k = defaultdict(lambda: [0, 0])
    for r in train:
        by_k[min(r["k"], 3)][0] += r["y"]
        by_k[min(r["k"], 3)][1] += 1
    print(f"decision points: train {len(train)}, test {len(test)}")
    print("holdout logloss  flat       :", round(logloss(test, lambda r: flat), 4))
    print("holdout logloss  by k only  :", round(logloss(
        test, lambda r: (by_k[min(r['k'], 3)][0] + 1) / (by_k[min(r['k'], 3)][1] + 2)), 4))
    print("holdout logloss  cell table :", round(logloss(
        test, lambda r: MM.p_mega_now("", r["k"], r["ncand"], r["lead"], r["item"], r["consumed"], r_tr)), 4))
    print("holdout logloss  cell x species:", round(logloss(
        test, lambda r: MM.p_mega_now(r["species"], r["k"], r["ncand"], r["lead"], r["item"],
                                      r["consumed"], r_tr)), 4))
    if not args.dry_run:
        full = fit(train + test)
        (REPO / "data" / "mega_rates.json").write_text(json.dumps(full, indent=1, sort_keys=True) + "\n")
        print("wrote data/mega_rates.json:", len(full["cells"]), "cells,", len(full["species_rel"]), "species")


if __name__ == "__main__":
    main()
