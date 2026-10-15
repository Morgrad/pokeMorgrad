"""Build a real-EV holdout from freshly scraped VGCPastes teams.

Usage:
    python3 tools/build_real_ev_holdout.py --dry-run
    python3 tools/build_real_ev_holdout.py --apply

Steps:
1. Validate every /tmp/vgc_scraped/*.txt via showdown validate-team
2. Compute species+item signature
3. Reject any file matching:
   - p4's train pool (data/regional_teams/vgc_*.txt)
   - current holdout (pool_split.json["holdout"])
4. Shuffle remaining with fixed seed
5. Reserve first 100 as new holdout -> copy as data/regional_teams/real_ev_NN.txt
6. Back up pool_split.json -> pool_split.mixed_holdout.bak
7. Write new pool_split.json: same train, holdout = new 100
"""
import argparse
import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path.home() / "project"
sys.path.insert(0, str(REPO))
from src import regmc_db as DB

SCRAPED = Path("/tmp/vgc_scraped")
POOL = REPO / "data" / "regional_teams"
SPLIT = REPO / "data" / "pool_split.json"
SHOWDOWN = Path.home() / "pokemon-showdown"
FORMAT = "gen9championsvgc2026regmc"
SEED = 20261015
HOLDOUT_SIZE = 100


def signature(text):
    mons = DB.parse_team(text)
    if not mons or len(mons) != 6:
        return None
    return tuple(sorted(
        (m["species"].strip(), (m["item"] or "").strip())
        for m in mons
    ))


def validate(path):
    try:
        r = subprocess.run(
            ["node", "pokemon-showdown", "validate-team", FORMAT],
            cwd=str(SHOWDOWN),
            input=path.read_text(),
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        print("must pass --dry-run or --apply")
        sys.exit(1)
    dry = not args.apply

    split = json.loads(SPLIT.read_text())
    train_files = set(split["train"])
    old_holdout = set(split["holdout"])
    print(f"current split: {len(train_files)} train / {len(old_holdout)} holdout")

    # --- signature the contaminated sets ---
    train_sigs = set()
    for name in train_files:
        p = POOL / name
        if p.exists():
            s = signature(p.read_text())
            if s:
                train_sigs.add(s)
    old_holdout_sigs = set()
    for name in old_holdout:
        p = POOL / name
        if p.exists():
            s = signature(p.read_text())
            if s:
                old_holdout_sigs.add(s)
    print(f"train sigs: {len(train_sigs)}  old_holdout sigs: {len(old_holdout_sigs)}")

    # --- validate scraped ---
    candidates = sorted(SCRAPED.glob("*.txt"))
    print(f"\nvalidating {len(candidates)} scraped teams...")
    valid, invalid = [], []
    for i, f in enumerate(candidates):
        if validate(f):
            valid.append(f)
        else:
            invalid.append(f.name)
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(candidates)} valid={len(valid)} invalid={len(invalid)}")
    print(f"  valid: {len(valid)}  invalid: {len(invalid)}")

    # --- dedup ---
    print("\ndeduping vs train and old holdout...")
    kept, dup_train, dup_old = [], [], []
    seen = set()
    for f in valid:
        sig = signature(f.read_text())
        if sig is None:
            continue
        if sig in seen:
            continue
        if sig in train_sigs:
            dup_train.append(f.name)
            continue
        if sig in old_holdout_sigs:
            dup_old.append(f.name)
            continue
        seen.add(sig)
        kept.append(f)
    print(f"  kept:          {len(kept)}")
    print(f"  dup vs train:  {len(dup_train)}")
    print(f"  dup vs old HO: {len(dup_old)}")

    if len(kept) < HOLDOUT_SIZE:
        print(f"\nERROR: only {len(kept)} clean candidates, need {HOLDOUT_SIZE}")
        sys.exit(1)

    # --- stratified holdout pick ---
    import json as _json
    _meta = _json.loads(Path("/tmp/vgc_raw/m-c.csv").read_text())
    _meta_by_id = {m["Team ID"]: m for m in _meta}

    def _provenance(f):
        tid = f.stem
        tourn = (_meta_by_id.get(tid, {}).get("Tournament / Event") or "").strip()
        if tourn in ("", "-"):
            return "empty"
        if tourn.lower() == "video":
            return "video"
        return "tournament"

    tier1 = [f for f in kept if _provenance(f) == "tournament"]
    tier2 = [f for f in kept if _provenance(f) == "video"]
    tier3 = [f for f in kept if _provenance(f) == "empty"]

    rng = random.Random(SEED)
    rng.shuffle(tier1)
    rng.shuffle(tier2)
    rng.shuffle(tier3)

    new_holdout_files = tier1 + tier2
    new_holdout_files = new_holdout_files[:HOLDOUT_SIZE]
    # only fall to tier3 if we can't fill otherwise
    if len(new_holdout_files) < HOLDOUT_SIZE:
        new_holdout_files += tier3[:HOLDOUT_SIZE - len(new_holdout_files)]

    print(f"\n  provenance of holdout candidates:")
    print(f"    tournament: {len(tier1)}")
    print(f"    video:      {len(tier2)}")
    print(f"    empty:      {len(tier3)}")
    print(f"  holdout picked: {len(new_holdout_files)}")
    # report actual mix in chosen set
    from collections import Counter
    mix = Counter(_provenance(f) for f in new_holdout_files)
    print(f"  holdout mix: {dict(mix)}")

    # tournament breakdown
    from collections import Counter
    meta = json.loads(Path("/tmp/vgc_raw/m-c.csv").read_text())
    meta_by_id = {m["Team ID"]: m for m in meta}
    tc = Counter()
    for f in new_holdout_files:
        tid = f.stem  # e.g. MC210
        tourn = (meta_by_id.get(tid, {}).get("Tournament / Event") or "").strip()
        tc[tourn] += 1
    print(f"\n  new holdout tournaments (top 10):")
    for k, v in tc.most_common(10):
        print(f"    {(k or '(empty)')[:50]:<50} {v}")

    if dry:
        print("\n=== DRY RUN — no changes ===")
        return

    # --- apply ---
    print("\n=== APPLYING ===")
    # backup current split (different name than swap_pool's backup)
    bak = SPLIT.with_name("pool_split.mixed_holdout.bak")
    shutil.copy(SPLIT, bak)
    print(f"  backed up split -> {bak.name}")

    # copy new holdout files with real_ev_ prefix
    new_names = []
    for i, f in enumerate(new_holdout_files):
        dst = POOL / f"real_ev_{i:03d}.txt"
        shutil.copy(f, dst)
        new_names.append(dst.name)
    print(f"  wrote {len(new_names)} real_ev_*.txt files")

    # write new split
    new_split = {
        "train": sorted(train_files),
        "holdout": sorted(new_names),
    }
    SPLIT.write_text(json.dumps(new_split, indent=2))
    print(f"  wrote {SPLIT}")
    print(f"  new split: {len(new_split['train'])} train / "
          f"{len(new_split['holdout'])} holdout")


if __name__ == "__main__":
    main()
