"""Fit foe Protect / Fake Out rates from real ladder replays -> data/opp_actions.json.

Usage:
    python tools/build_opp_actions.py            # fit on all replays, write the file
    python tools/build_opp_actions.py --dry-run  # holdout report only (fit even files, score odd)

A decision point is a turn start (turn >= 1) and a non-fainted mon in a slot of either side;
the labels are whether that mon used a Protect-family move / Fake Out / Trick Room during that turn (a mon
that switched out, flinched or fainted before moving is 0). Features come from
src.opp_actions.foe_ctx, the same function the pilot calls. Each target is a cell table times a
per-species factor shrunk toward 1.
"""
import argparse
import glob
import json
import math
import pickle
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from src import battle_memory as BM  # noqa: E402
from src import opp_actions as OA  # noqa: E402

SHRINK = {"protect": 3.0, "fakeout": 1.0, "trickroom": 3.0}   # pseudo-expected-uses pulling a species factor toward 1
MIN_SPECIES_N = 5
SMOOTH = 20.0        # pseudo-rows pulling a fine cell toward its parent cell
TARGETS = ("protect", "fakeout", "trickroom")


def hp_of(s):
    """'85/100 par' / '0 fnt' -> fraction of max HP."""
    try:
        cur, mx = s.split(" ")[0].split("/")
        return min(max(int(cur) / int(mx), 0.0), 1.0)
    except ValueError:
        return 0.0 if s.startswith("0") else 1.0


def extract(path):
    """Decision points of one replay: dicts with 'ctx' (FoeCtx), 'species' and the labels."""
    d = json.load(open(path))
    chunks = [[]]
    for line in d["log"].split("\n"):
        p = line.split("|")
        if len(p) > 1 and p[1] == "turn":
            chunks.append([])
        chunks[-1].append(p)
    m = BM.BattleMemory()
    hp = {}

    def feed(p):
        m.feed(p)
        if len(p) > 3 and p[1] in ("switch", "drag"):
            hp[BM._key(p[2])] = hp_of(p[4]) if len(p) > 4 else 1.0
        elif len(p) > 3 and p[1] in ("-damage", "-heal", "-sethp"):
            hp[BM._key(p[2])] = hp_of(p[3])
        elif len(p) > 2 and p[1] == "faint":
            hp[BM._key(p[2])] = 0.0

    for p in chunks[0]:
        feed(p)
    out = []
    for turn, chunk in enumerate(chunks[1:], start=1):
        pend = []
        tr_cond = m.condition("field", "Trick Room")
        tr_up = tr_cond is not None and tr_cond.end_turn is None
        for side in ("p1", "p2"):
            for rec in m.active_mons(side):
                if not rec.fainted:
                    pend.append((side, rec.name, OA.foe_ctx(m, side, rec.name, turn,
                                                           hp_frac=hp.get((side, rec.name), 1.0)), tr_up))
        for p in chunk:
            feed(p)
        used = defaultdict(set)
        for a in m.actions.get(turn, []):
            if a.kind == "move":
                used[(a.side, a.name)].add(a.move)
        for side, name, ctx, tr_up in pend:
            mv = used.get((side, name), set())
            out.append({"ctx": ctx, "species": ctx.species, "tr_up": tr_up,
                        "y_protect": int(bool(mv & BM.PROTECT_FAMILY)), "y_fakeout": int("fakeout" in mv),
                        "y_trickroom": int("trickroom" in mv)})
    return out


def rows_for(target, rows):
    """Rows that count for `target`: Fake Out is only legal at age 0; Trick Room is only set while it is down."""
    if target == "fakeout":
        return [r for r in rows if r["ctx"].age == 0]
    if target == "trickroom":
        return [r for r in rows if not r["tr_up"]]
    return rows


def keys_of(target, ctx):
    return OA.KEYS[target](ctx)


def fit_target(target, rows):
    """cells (smoothed toward parents), parents and the shrunk per-species factor for one target."""
    rows = rows_for(target, rows)
    par, fine, parent_of = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0]), {}
    for r in rows:
        key, parent = keys_of(target, r["ctx"])
        parent_of[key] = parent
        for t, k in ((fine, key), (par, parent)):
            t[k][0] += r["y_" + target]
            t[k][1] += 1
    parents = {k: (a + 0.5) / (n + 1) for k, (a, n) in par.items()}
    cells = {}
    for k, (a, n) in fine.items():
        cells[k] = (a + SMOOTH * parents[parent_of[k]]) / (n + SMOOTH)
    obs, exp, cnt = defaultdict(float), defaultdict(float), defaultdict(int)
    for r in rows:
        if not OA.species_applies(r["ctx"], target):
            continue
        s = r["species"]
        obs[s] += r["y_" + target]
        exp[s] += cells[keys_of(target, r["ctx"])[0]]
        cnt[s] += 1
    sh = SHRINK[target]
    rel = {s: round((obs[s] + sh) / (exp[s] + sh), 4) for s in cnt if cnt[s] >= MIN_SPECIES_N and s}
    return {"cells": {k: round(v, 4) for k, v in cells.items()},
            "parents": {k: round(v, 4) for k, v in parents.items()},
            "species_rel": rel, "n_rows": len(rows), "n_pos": sum(r["y_" + target] for r in rows)}


def fit(rows):
    return {t: fit_target(t, rows) for t in TARGETS}


def logloss(rows, target, predict):
    eps = 1e-4
    tot = 0.0
    for r in rows:
        p = min(max(predict(r), eps), 1 - eps)
        tot -= math.log(p) if r["y_" + target] else math.log(1 - p)
    return tot / len(rows)


def calibration(rows, target, predict, bins=5):
    """(bin label, n, mean predicted, observed rate) over equal-count bins of the prediction."""
    ps = sorted(((predict(r), r["y_" + target]) for r in rows))
    out = []
    for i in range(bins):
        chunk = ps[i * len(ps) // bins:(i + 1) * len(ps) // bins]
        out.append((i + 1, len(chunk), sum(p for p, _ in chunk) / len(chunk),
                    sum(y for _, y in chunk) / len(chunk)))
    return out


def rate(rows, target, pred):
    sel = [r["y_" + target] for r in rows if pred(r["ctx"])]
    return f"{sum(sel) / max(len(sel), 1):.3f} (n={len(sel)})"


def sanity(rows, rates):
    print("overall rates: Protect-family %s   Fake Out %s" % (
        rate(rows, "protect", lambda c: True), rate(rows, "fakeout", lambda c: True)))
    for a in range(4):
        print(f"  age {a}{'+' if a == 3 else ' '}: protect {rate(rows, 'protect', lambda c, a=a: min(c.age, 3) == a)}"
              f"   fakeout {rate(rows, 'fakeout', lambda c, a=a: min(c.age, 3) == a)}")
    rev = OA.protect_revealed
    print("  protect revealed        :", rate(rows, "protect", rev))
    print("  protect not revealed    :", rate(rows, "protect", lambda c: not rev(c)))
    print("  protect revealed, not last turn, age>0:", rate(rows, "protect", lambda c: rev(c) and c.age > 0 and c.protect_chain == 0))
    print("  protect revealed, protected last turn  :", rate(rows, "protect", lambda c: rev(c) and c.protect_chain > 0))
    print("  fakeout age 0 revealed  :", rate(rows, "fakeout", lambda c: c.age == 0 and "fakeout" in c.known_moves))
    print("  fakeout age 0 lead      :", rate(rows, "fakeout", lambda c: c.age == 0 and c.lead))
    print("  fakeout age 0 back      :", rate(rows, "fakeout", lambda c: c.age == 0 and not c.lead))
    free = [r for r in rows if not r["tr_up"]]
    print("  trickroom (TR down)     :", rate(free, "trickroom", lambda c: True))
    print("  trickroom revealed      :", rate(free, "trickroom", lambda c: "trickroom" in c.known_moves))
    print("  trickroom not revealed  :", rate(free, "trickroom", lambda c: "trickroom" not in c.known_moves))
    for t in TARGETS:
        rel = sorted(rates[t]["species_rel"].items(), key=lambda x: x[1])
        print(f"  {t} species factor  low: " + ", ".join(f"{s} {v}" for s, v in rel[:5]))
        print(f"  {t} species factor high: " + ", ".join(f"{s} {v}" for s, v in rel[-6:]))
    mx = max((lambda p: p.fakeout + p.protect + p.trickroom)(OA.action_probs(r["ctx"], rates)) for r in rows)
    print(f"max fakeout+protect+trickroom over all decision points: {mx:.3f} (cap {OA.MAX_P})")


def pred_fn(target, rates, species=True):
    def f(r):
        c = r["ctx"]
        if species:
            return getattr(OA.action_probs(c, rates), target)
        p = OA.cell_p(c, target, rates)
        return 0.0 if target == "fakeout" and c.age > 0 else p
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cache", help="pickle path for extracted rows (exploration only)")
    args = ap.parse_args()
    t0 = time.time()
    if args.cache and Path(args.cache).exists():
        per_file = pickle.load(open(args.cache, "rb"))
    else:
        files = sorted(f for f in glob.glob(str(REPO / "data" / "showdown_replays" / "*.json"))
                       if not f.endswith(".meta.json"))
        per_file = [extract(f) for f in files]
        if args.cache:
            pickle.dump(per_file, open(args.cache, "wb"))
    train = [r for i, rs in enumerate(per_file) if i % 2 == 0 for r in rs]
    test = [r for i, rs in enumerate(per_file) if i % 2 == 1 for r in rs]
    print(f"decision points: train {len(train)}, test {len(test)}  (extracted in {time.time() - t0:.0f}s)")
    r_tr = fit(train)
    for target in TARGETS:
        tr, te = rows_for(target, train), rows_for(target, test)
        flat = sum(r["y_" + target] for r in tr) / len(tr)
        print(f"\n== {target}: rows train {len(tr)}, test {len(te)}")
        print("holdout logloss  flat             :", round(logloss(te, target, lambda r: flat), 4))
        print("holdout logloss  cell table       :", round(logloss(te, target, pred_fn(target, r_tr, False)), 4))
        print("holdout logloss  cell x species   :", round(logloss(te, target, pred_fn(target, r_tr)), 4))
        print("calibration on holdout (equal-count bins: n, mean predicted, observed):")
        for b, n, mp, ob in calibration(te, target, pred_fn(target, r_tr)):
            print(f"  bin {b}: n={n:6d}  predicted {mp:.4f}  observed {ob:.4f}")
    print("\n-- sanity (train+test) --")
    full = fit(train + test)
    sanity(train + test, full)
    if not args.dry_run:
        out = {"targets": list(TARGETS), **full}
        (REPO / "data" / "opp_actions.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
        print("\nwrote data/opp_actions.json:", {t: (len(full[t]["cells"]), len(full[t]["species_rel"]))
                                              for t in TARGETS}, "(cells, species)")
    print(f"total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
