#!/bin/bash
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHOWDOWN_DIR="${SHOWDOWN_DIR:-$HOME/pokemon-showdown}"

STAMP=$(date +%Y%m%d_%H%M%S)
LOG=/tmp/ga_overnight.log

echo "===== $(date) OVERNIGHT CHAIN START ====="

cd "$REPO_ROOT"
source ~/llm-env/bin/activate
export PYTHONUNBUFFERED=1

# Kill stale GA processes
pkill -9 -f "ga_run.py" 2>/dev/null
pkill -9 -f "ga_core" 2>/dev/null
sleep 2

# Ensure Showdown up
if ! curl -s http://localhost:8000 > /dev/null 2>&1; then
    echo "[$(date)] Starting Showdown"
    cd "$SHOWDOWN_DIR"
    nohup node pokemon-showdown start 8000 --no-security > /tmp/showdown_ga.log 2>&1 &
    sleep 8
    cd "$REPO_ROOT"
fi
curl -s http://localhost:8000 > /dev/null 2>&1 || { echo "FATAL: Showdown down"; exit 1; }
echo "[$(date)] Showdown UP"

# Fresh checkpoint dirs
rm -rf "$REPO_ROOT/output/checkpoints/v6/run1" "$REPO_ROOT/output/checkpoints/v6/run2"
mkdir -p "$REPO_ROOT/output/checkpoints/v6"

# Watchdog
(
  while true; do
    if ! curl -s http://localhost:8000 > /dev/null 2>&1; then
      echo "[$(date)] watchdog: Showdown DOWN, restart"
      cd "$SHOWDOWN_DIR"
      nohup node pokemon-showdown start 8000 --no-security > /tmp/showdown_ga.log 2>&1 &
      sleep 8
      cd "$REPO_ROOT"
    fi
    sleep 30
  done
) > /tmp/showdown_watchdog.log 2>&1 &

echo ""
echo "===== $(date) RUN 1 (5h) ====="
python -m run.ga_run run1 2.5 2>&1 | tee /tmp/ga_run1.log
echo "[$(date)] RUN 1 finished rc=$?"

echo ""
echo "===== $(date) RUN 2 (5h, warm-start) ====="
python -m run.ga_run run2 2.5 2>&1 | tee /tmp/ga_run2.log
echo "[$(date)] RUN 2 finished rc=$?"

echo ""
echo "===== $(date) FINAL EVAL ====="
python -m src.eval \
    "$REPO_ROOT/data/baseline_team.txt" \
    "$REPO_ROOT/output/champions/ga_run1_island_A.txt" \
    "$REPO_ROOT/output/champions/ga_run1_island_B.txt" \
    "$REPO_ROOT/output/champions/ga_run1_island_C.txt" \
    "$REPO_ROOT/output/champions/ga_run2_island_A.txt" \
    "$REPO_ROOT/output/champions/ga_run2_island_B.txt" \
    "$REPO_ROOT/output/champions/ga_run2_island_C.txt" \
    2>&1 | tee /tmp/ga_final_eval.log

touch /tmp/ga_overnight_done_$STAMP
echo ""
echo "[$(date)] ALL DONE. Marker: /tmp/ga_overnight_done_$STAMP"
