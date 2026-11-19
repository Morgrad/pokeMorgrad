"""tools/extract_champions.py writes the same primary champion as the GA (train best).

Uses a temporary checkpoint tree; nothing in output/ is touched.
Run: python tests/test_extract_champions.py
"""
import importlib.util
import json
import os
import random
import sys
import tempfile
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from src.ga.genome import build_random_genome, genome_to_text  # noqa: E402


def _tool():
    spec = importlib.util.spec_from_file_location(
        "extract_champions", os.path.join(ROOT, "tools", "extract_champions.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_primary_is_train_best_and_val_gets_its_own_file():
    random.seed(11)
    train_g, val_g = build_random_genome({}), build_random_genome({})
    tmp = Path(tempfile.mkdtemp())
    ck = tmp / "ckpt" / "r1_A"
    ck.mkdir(parents=True)
    island = {"name": "A", "best_ever": {"fit": 0.9, "genome": train_g, "gen": 4},
              "best_val_ever": {"fit": 0.6, "genome": val_g, "gen": 3}}
    (ck / "gen_0004.json").write_text(json.dumps({"generation": 4, "islands": [island]}))
    out = tmp / "champions"
    written = _tool().extract("r1", ckpt_root=tmp / "ckpt", champion_dir=out, islands=("A", "B"))
    assert written == {"A": ["ga_r1_island_A.txt", "ga_r1_island_A_train.txt",
                             "ga_r1_island_A_val.txt"]}
    assert (out / "ga_r1_island_A.txt").read_text() == genome_to_text(train_g)
    assert (out / "ga_r1_island_A_train.txt").read_text() == genome_to_text(train_g)
    assert (out / "ga_r1_island_A_val.txt").read_text() == genome_to_text(val_g)


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
