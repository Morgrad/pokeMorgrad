"""Golden-master test: the GA engine must produce exactly the recorded output.

Covers population operators, run_islands stdout, checkpoint JSON (shape, key order,
pruning), champion files, resume-from-checkpoint and RNG consumption. See
tests/golden/ga_harness.py for how the run is faked and how to regenerate.

Run: pytest tests/test_ga_golden.py   (or: python tests/test_ga_golden.py)
"""
import difflib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HARNESS = REPO / "tests" / "golden" / "ga_harness.py"
FIXTURE = REPO / "tests" / "golden" / "ga_golden.json"


def _run_harness():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "snap.json"
        env = {**os.environ, "PYTHONHASHSEED": "0"}
        r = subprocess.run([sys.executable, str(HARNESS), "--out", str(out)],
                           cwd=REPO, env=env, capture_output=True, text=True, timeout=600)
        assert r.returncode == 0, f"harness failed:\n{r.stdout}\n{r.stderr}"
        return out.read_text()


def test_ga_matches_golden():
    got = _run_harness()
    want = FIXTURE.read_text()
    if got != want:
        diff = "".join(list(difflib.unified_diff(
            want.splitlines(True), got.splitlines(True), "golden", "now", n=2))[:120])
        raise AssertionError(f"GA output differs from tests/golden/ga_golden.json:\n{diff}")
    assert json.loads(got)["population"]["roundtrip_equal"] is True


if __name__ == "__main__":
    try:
        test_ga_matches_golden()
        print("PASS test_ga_matches_golden")
    except AssertionError as e:
        print(f"FAIL test_ga_matches_golden: {e}")
        sys.exit(1)
