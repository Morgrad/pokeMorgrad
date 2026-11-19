"""Append a dated milestone entry to docs/history/milestones.md (created if missing).

Usage:
    python3 tools/log_milestone.py "Title" "One-line summary"

Also commits that one file (git add + commit), so only run it when a commit is wanted.
(Before 2026-11-18 it appended to docs/STATE_history.md, now split into docs/history/.)
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)

TITLE = sys.argv[1]
SUMMARY = sys.argv[2]

REPO = Path(__file__).resolve().parent.parent
h = REPO / "docs" / "history" / "milestones.md"
if not h.exists():
    h.write_text("# Milestones\n\nDated entries appended by tools/log_milestone.py "
                 "(newest last). Index: README.md in this folder.\n")
commit = subprocess.run(
    ["git", "log", "-1", "--oneline"],
    capture_output=True, text=True, cwd=str(REPO),
).stdout.strip()

entry = f"""

### {datetime.now().strftime('%Y-%m-%d %H:%M')} - {TITLE}

{SUMMARY}

Commit: {commit}
"""

h.write_text(h.read_text().rstrip() + entry)
print(f"appended: {TITLE}")
print(f"  commit: {commit}")

# Auto-commit the doc change so it doesn't linger unstaged
subprocess.run(["git", "add", str(h)], cwd=str(REPO), check=True)
subprocess.run(["git", "commit", "-m", f"docs: log milestone - {TITLE}"],
               cwd=str(REPO), check=True)
