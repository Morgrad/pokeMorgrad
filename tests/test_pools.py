"""Train / held-out pool loading (src/ga/pools.py::regional_pool, heldout_pool).

The held-out pool is only for final scoring: it must never fall back to, or overlap,
the training pool. Uses temporary pool_split.json files; the real data/regional_teams/
is read for team texts. Run: python tests/test_pools.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.ga import pools as PL  # noqa: E402


def _with_split(split):
    """Point pools.data_path('pool_split.json') at a temp file (None = missing)."""
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "pool_split.json")
    if split is not None:
        json.dump(split, open(path, "w"))
    real = PL.data_path
    PL.data_path = lambda *p: path if p == ("pool_split.json",) else real(*p)
    PL._HELDOUT = None
    PL._REGIONAL = None
    return real


def _restore(real):
    PL.data_path = real
    PL._HELDOUT = None
    PL._REGIONAL = None


def _raises(fn):
    try:
        fn()
    except RuntimeError:
        return True
    return False


def test_real_split_is_disjoint_and_sized():
    PL._HELDOUT = PL._REGIONAL = None
    split = json.load(open(PL.data_path("pool_split.json")))
    train = {os.path.basename(f) for f in split["train"]}
    hold = {os.path.basename(f) for f in split["holdout"]}
    assert train and hold and not (train & hold)
    assert len(PL.heldout_pool()) == len(hold)
    assert len(PL.regional_pool()) == len(train)


def test_missing_split_does_not_fall_back_to_train():
    real = _with_split(None)
    try:
        assert _raises(PL.heldout_pool)
    finally:
        _restore(real)


def test_empty_or_overlapping_holdout_raises():
    files = sorted(os.listdir(PL._REGIONAL_DIR))[:3]
    for split in ({"train": files, "holdout": []},
                  {"train": files, "holdout": [files[0]]}):
        real = _with_split(split)
        try:
            assert _raises(PL.heldout_pool)
        finally:
            _restore(real)


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e!r}")
    sys.exit(1 if failed else 0)
