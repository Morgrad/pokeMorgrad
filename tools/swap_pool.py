"""Validate, dedup, and swap the training pool with VGCPastes data.

Usage:
    python3 tools/swap_pool.py --dry-run    # report only, no file changes
    python3 tools/swap_pool.py --apply      # do the archive + swap

Pipeline:
  1. Validate every file in /tmp/vgc_scraped/ via showdown validate-team
  2. Dedup new-vs-new by (species, item) signature
  3. Dedup new-vs-holdout (drop matches — holdout must stay pure)
  4. Dedup new-vs-current-train (drop matches — don't double-count)
  5. In --apply mode:
       - Move current train files to data/regional_teams/_archive_YYYY-MM-DD/
       - Copy new teams into data/regional_teams/ as vgc_<id>.txt
       - Backup pool_split.json -> .bak
       - Rewrite pool_split.json: train = new list, holdout = unchanged
"""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path.home() / "project"
sys.path.insert(0, str(REPO))
from src import regmc_db as DB

NEW_DIR = Path("/tmp/vgc_scraped")
POOL_DIR = REPO / "data" / "regional_teams"
SPLIT_PATH = REPO / "data" / "pool_split.json"
SHOWDOWN_DIR = Path.home() / "pokemon-showdown"
FORMAT = "gen9championsvgc2026regmc"

ARCHIVE_NAME = f"_archive_{datetime.now().strftime('%Y-%m-%d')}"
ARCHIVE_DIR = POOL_DIR / ARCHIVE_NAME


def team_signature(text):
    """Return sorted tuple of (species, item) or None if parse fails."""
    mons = DB.parse_team(text)
    if not mons or len(mons) != 6:
        return None
    return tuple(sorted(
        (m["species"].strip(), (m["item"] or "").strip())
        for m in mons
    ))


def validate_file(path):
    """True if file passes showdown validate-team."""
    try:
        r = subprocess.run(
            ["node", "pokemon-showdown", "validate-team", FORMAT],
            cwd=str(SHOWDOWN_DIR),
            input=path.read_text(),
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


def load_split():
    return json.loads(SPLIT_PATH.read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        print("must pass --dry-run or --apply")
        sys.exit(1)
    dry = not args.apply

    split = load_split()
    current_train = set(split["train"])
    current_holdout = set(split["holdout"])
    print(f"current pool: {len(current_train)} train / {len(current_holdout)} holdout")

    # ---- 1. Validate ----
    new_files = sorted(NEW_DIR.glob("*.txt"))
    print(f"\n=== validating {len(new_files)} new files ===")
    valid, invalid = [], []
    for i, f in enumerate(new_files):
        if validate_file(f):
            valid.append(f)
        else:
            invalid.append(f.name)
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(new_files)}  valid={len(valid)} invalid={len(invalid)}")
    print(f"  valid: {len(valid)}  invalid: {len(invalid)}")
    if invalid[:5]:
        print(f"  sample invalid: {invalid[:5]}")

    # ---- 2/3. Dedup ----
    # Signature lookup for holdout + current train
    def sig_lookup(filenames):
        lookup = {}
        for name in filenames:
            path = POOL_DIR / name
            if not path.exists():
                continue
            sig = team_signature(path.read_text())
            if sig:
                lookup[sig] = name
        return lookup

    print("\n=== building signatures for existing pool ===")
    holdout_sigs = sig_lookup(current_holdout)
    train_sigs = sig_lookup(current_train)
    print(f"  holdout sigs: {len(holdout_sigs)}")
    print(f"  train sigs:   {len(train_sigs)}")

    print("\n=== dedup new teams ===")
    seen_new_sigs = {}
    kept, dup_holdout, dup_train, dup_new, unparsable = [], [], [], [], []
    for f in valid:
        sig = team_signature(f.read_text())
        if sig is None:
            unparsable.append(f.name)
            continue
        if sig in holdout_sigs:
            dup_holdout.append(f.name)
            continue
        if sig in train_sigs:
            dup_train.append(f.name)
            continue
        if sig in seen_new_sigs:
            dup_new.append(f.name)
            continue
        seen_new_sigs[sig] = f.name
        kept.append(f)
    print(f"  kept:                {len(kept)}")
    print(f"  dup vs holdout:      {len(dup_holdout)}")
    print(f"  dup vs current train:{len(dup_train)}")
    print(f"  dup vs new (self):   {len(dup_new)}")
    print(f"  unparsable:          {len(unparsable)}")

    # ---- 4. Report & apply ----
    print(f"\n=== PLAN ===")
    print(f"  archive {len(current_train)} files -> {ARCHIVE_DIR}")
    print(f"  copy    {len(kept)} files -> {POOL_DIR}/vgc_<id>.txt")
    print(f"  new train count: {len(kept)}")
    print(f"  holdout count:   {len(current_holdout)} (unchanged)")

    if dry:
        print("\n=== DRY RUN — no changes made ===")
        print("re-run with --apply to execute")
        return

    # ---- 5. Apply ----
    print(f"\n=== APPLYING ===")
    ARCHIVE_DIR.mkdir(exist_ok=True)
    archived = 0
    for name in current_train:
        src = POOL_DIR / name
        if src.exists():
            shutil.move(str(src), str(ARCHIVE_DIR / name))
            archived += 1
    print(f"  archived {archived} files")

    copied = 0
    for f in kept:
        dst = POOL_DIR / f"vgc_{f.stem}.txt"
        shutil.copy(str(f), str(dst))
        copied += 1
    print(f"  copied {copied} new files")

    bak = SPLIT_PATH.with_suffix(".json.bak")
    shutil.copy(str(SPLIT_PATH), str(bak))
    print(f"  backed up split to {bak.name}")

    new_train = sorted(f"vgc_{f.stem}.txt" for f in kept)
    new_split = {
        "train": new_train,
        "holdout": sorted(current_holdout),
    }
    SPLIT_PATH.write_text(json.dumps(new_split, indent=2))
    print(f"  wrote {SPLIT_PATH}")
    print(f"  new pool: {len(new_train)} train / {len(new_split['holdout'])} holdout")


if __name__ == "__main__":
    main()
