"""Watchdog for parallel GA islands.

Each island writes progress to /tmp/ga_<run_id>_<name>.log every ~1-2 min.
If a log's mtime stalls for >STALL_SECONDS, that island is hung.

This watchdog kills the hung process and lets the parent ga_parallel.sh
respawn it. Runs as a background subprocess alongside the three islands.

Usage: python3 tools/watch_islands.py <run_id> <island_name> <pid> [stall_s]
"""
import os
import signal
import sys
import time
from pathlib import Path

RUN_ID = sys.argv[1]
ISLAND = sys.argv[2]
PID = int(sys.argv[3])
STALL = int(sys.argv[4]) if len(sys.argv) > 4 else 300

LOG = Path(f"/tmp/ga_{RUN_ID}_{ISLAND}.log")
CHECK_INTERVAL = 30

print(f"[watchdog-{ISLAND}] monitoring PID {PID}, log {LOG}, stall>{STALL}s")

def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

while True:
    time.sleep(CHECK_INTERVAL)
    if not alive(PID):
        print(f"[watchdog-{ISLAND}] process {PID} gone, exiting")
        break
    if not LOG.exists():
        continue
    age = time.time() - LOG.stat().st_mtime
    if age > STALL:
        print(f"[watchdog-{ISLAND}] STALLED: log age {age:.0f}s > {STALL}s, killing {PID}")
        try:
            os.kill(PID, signal.SIGKILL)
        except OSError:
            pass
        break
