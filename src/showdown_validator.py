"""
Python wrapper around the Node TeamValidator (src/showdown_validate.js). Caches results by team hash.

The JS script needs a built Showdown checkout ($SHOWDOWN_DIR, default ~/pokemon-showdown,
with dist/). If node cannot run it (missing checkout, crash, timeout, wrong number of
verdicts) check_teams raises ValidatorError and caches nothing. Before 2026-11-18 that
case silently became a cached "illegal" verdict for the first team, so on a host without
Showdown every genome was rejected and replaced by unvalidated random genomes.
"""
import base64
import hashlib
import subprocess

from src.paths import data_path, src_path

CACHE = {}
JS_PATH = src_path("showdown_validate.js")
TIMEOUT_S = 60


class ValidatorError(RuntimeError):
    """The Node validator could not produce verdicts (see the message for node's stderr)."""


def _verdict(line):
    if line == "OK":
        return (True, "")
    if line.startswith("FAIL:"):
        return (False, line[5:])
    return (False, line)          # PARSE_FAIL or ERR:<message>


def check_teams(team_texts):
    """team_texts: list of Showdown team strings. Returns list of (ok, msg), same order.

    Raises ValidatorError if the node process fails as a whole.
    """
    results = [None] * len(team_texts)
    to_query = []
    to_query_idx = []
    for i, text in enumerate(team_texts):
        h = hashlib.md5(text.encode()).hexdigest()
        if h in CACHE:
            results[i] = CACHE[h]
        else:
            to_query.append(base64.b64encode(text.encode()).decode())
            to_query_idx.append((i, h))

    if to_query:
        try:
            proc = subprocess.run(
                ["node", JS_PATH],
                input="\n".join(to_query),
                capture_output=True, text=True, timeout=TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ValidatorError(f"node {JS_PATH} did not run: {e}") from e
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        if proc.returncode != 0 or len(lines) != len(to_query):
            raise ValidatorError(
                f"node {JS_PATH} exit code {proc.returncode}, {len(lines)} verdicts for "
                f"{len(to_query)} teams (is SHOWDOWN_DIR a built Showdown checkout?); "
                f"stderr: {proc.stderr.strip()[-800:]}")
        for (i, h), line in zip(to_query_idx, lines):
            verdict = _verdict(line)
            if not line.startswith("ERR:"):       # a per-team crash may be transient
                CACHE[h] = verdict
            results[i] = verdict

    return results


if __name__ == "__main__":
    # Quick manual check (needs node + a built Showdown checkout)
    baseline = open(data_path("baseline_team.txt")).read()
    bad = baseline.replace("Umbreon", "Greninja").replace("Inner Focus", "Battle Bond")
    results = check_teams([baseline, bad])
    for r in results:
        print(r)
