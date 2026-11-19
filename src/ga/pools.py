"""Opponent team pools for the GA: training pool, validation slice, held-out pool.

Teams are Showdown pastes in data/regional_teams/; data/pool_split.json lists which files
are "train" and which are "holdout". The held-out pool is for final scoring only
(src/eval.py, tools/paired_eval.py) and never feeds the GA. Both pools are loaded once
and cached (_REGIONAL, _HELDOUT; tests/test_pools.py resets them).

Split out of src/ga/genome.py on 2026-11-18 (code unchanged).
"""
import glob
import json
import os
import random

from src.paths import data_path

# --- Champion selection ---
# Reserve a slice of the training pool that the GA never samples for fitness.
# Each generation's best is scored on it (Island.best_val_ever). Since 2026-10-15 the
# primary champion is the TRAIN best (best_ever); the validation best is only the
# fallback (src/ga/checkpoint.py::write_champions, docs/design/decisions.md).
# Original motivation: island B (2026-10-13) was 68% on the training pool but
# 58.7% held-out.
VAL_POOL_SIZE = 30

VAL_SPLIT_SEED = 42

_REGIONAL_DIR = data_path("regional_teams")

def _load_teams(files, label):
    """Load team strings from a list of paths.

    pool_split.json historically stored absolute paths from another host, so
    each entry is resolved by basename against the local regional_teams dir.
    Loud on failure: a silently-empty pool used to look like a 0% eval.
    """
    teams, missing = [], 0
    for f in files:
        path = os.path.join(_REGIONAL_DIR, os.path.basename(f))
        try:
            text = open(path).read().strip()
            if text:
                teams.append(text)
            else:
                missing += 1
        except OSError:
            missing += 1
    if missing:
        print(f"WARNING: {label} pool: {missing}/{len(files)} teams failed to load "
              f"from {_REGIONAL_DIR}")
    if files and not teams:
        raise RuntimeError(
            f"{label} pool is empty: none of {len(files)} team files could be "
            f"read from {_REGIONAL_DIR}. Check data/regional_teams/ exists."
        )
    return teams

_REGIONAL = None

def regional_pool():
    """Training pool of team strings."""
    global _REGIONAL
    if _REGIONAL is None:
        split_path = data_path("pool_split.json")
        if os.path.exists(split_path):
            split = json.load(open(split_path))
            _REGIONAL = _load_teams(split.get("train", []), "training")
        else:
            files = sorted(glob.glob(os.path.join(_REGIONAL_DIR, "*.txt")))
            _REGIONAL = _load_teams(files, "training")
    return _REGIONAL

_HELDOUT = None

def _split_train_val(pool, val_size=VAL_POOL_SIZE, seed=VAL_SPLIT_SEED):
    """Deterministically split the training pool into (train, val) by index.

    Index-based, not string-based, because regional teams can duplicate.
    Union of train and val equals the original pool.
    """
    rng = random.Random(seed)
    idxs = list(range(len(pool)))
    rng.shuffle(idxs)
    val_idxs = set(idxs[:val_size])
    train = [pool[i] for i in range(len(pool)) if i not in val_idxs]
    val = [pool[i] for i in sorted(val_idxs)]
    return train, val

def heldout_pool():
    """Held-out pool (100 teams). Used for final eval only.

    Raises RuntimeError if data/pool_split.json is missing, has no "holdout" list, or
    shares a team file with "train". (Before 2026-11-18 a missing split file silently
    returned the TRAINING pool, so a "held-out" score could be a training score.)
    """
    global _HELDOUT
    if _HELDOUT is None:
        split_path = data_path("pool_split.json")
        if not os.path.exists(split_path):
            raise RuntimeError(f"{split_path} is missing: no held-out pool is defined "
                               "(refusing to fall back to the training pool)")
        split = json.load(open(split_path))
        holdout = split.get("holdout", [])
        if not holdout:
            raise RuntimeError(f"{split_path} has an empty 'holdout' list")
        overlap = ({os.path.basename(f) for f in holdout}
                   & {os.path.basename(f) for f in split.get("train", [])})
        if overlap:
            raise RuntimeError(f"{split_path}: {len(overlap)} team files are in both 'train' "
                               f"and 'holdout', e.g. {sorted(overlap)[:3]}")
        _HELDOUT = _load_teams(holdout, "held-out")
    return _HELDOUT
