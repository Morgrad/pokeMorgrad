"""
Python wrapper around the Node TeamValidator. Caches results by team hash.
"""
import base64, hashlib, os, subprocess, sys

CACHE = {}
JS_PATH = os.path.expanduser("~/project/src/showdown_validate.js")

def check_teams(team_texts):
    """team_texts: list of Showdown team strings. Returns list of (ok, msg)."""
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
        proc = subprocess.run(
            ["node", JS_PATH],
            input="\n".join(to_query),
            capture_output=True, text=True, timeout=60,
        )
        lines = proc.stdout.strip().split("\n")
        for j, (i, h) in enumerate(to_query_idx):
            if j >= len(lines):
                results[i] = (False, "no-verdict")
                continue
            line = lines[j]
            if line == "OK":
                verdict = (True, "")
            elif line.startswith("FAIL:"):
                verdict = (False, line[5:])
            else:
                verdict = (False, line)
            CACHE[h] = verdict
            results[i] = verdict

    return results


if __name__ == "__main__":
    # Quick test
    baseline = open(os.path.expanduser("~/project/data/baseline_team.txt")).read()
    bad = baseline.replace("Umbreon", "Greninja").replace("Inner Focus", "Battle Bond")
    results = check_teams([baseline, bad])
    for r in results:
        print(r)
