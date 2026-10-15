#!/bin/bash
# Parallel GA launcher: three islands, three processes, three Showdown
# instances (8000/8001/8002). Each island evolves independently.
#
# Does NOT kill anything or run eval. Caller is responsible for killing
# the serial GA before invoking this.
#
# Usage: bash run/ga_parallel.sh [hours] [run_id]

set -u

HOURS=${1:-4.0}
RUN_ID=${2:-p1}

cd ~/project
source ~/llm-env/bin/activate
export PYTHONUNBUFFERED=1

echo "=== parallel GA: ${HOURS}h x 3 islands, run_id=${RUN_ID} ==="

# Safety: no stale ga_island processes
pkill -9 -f "run.ga_island" 2>/dev/null
sleep 1

# Ensure Showdown on 8000, 8001, 8002
for port in 8000 8001 8002; do
  if ! curl -s "http://localhost:$port" > /dev/null 2>&1; then
    echo "[showdown] starting :$port"
    cd ~/pokemon-showdown
    nohup node pokemon-showdown start "$port" --no-security \
      > "/tmp/showdown_${port}.log" 2>&1 &
    cd ~/project
  fi
done
sleep 8
for port in 8000 8001 8002; do
  curl -s "http://localhost:$port" > /dev/null \
    && echo "[showdown] :$port UP" \
    || { echo "[showdown] :$port DOWN - abort"; exit 1; }
done

# Launch three island processes, each with a watchdog + auto-respawn loop.
# A stalled island (no log output for 5 min) is SIGKILLed and respawned
# from its last checkpoint. Prevents the infinite-hang failure mode.

run_island() {
  local name=$1
  local port=$2
  local start_ts
  start_ts=$(date +%s)

  while true; do
    # Compute remaining hours so a respawned island doesn't run past deadline
    local now_ts elapsed_s remaining_h
    now_ts=$(date +%s)
    elapsed_s=$(( now_ts - start_ts ))
    remaining_h=$(awk -v h="$HOURS" -v e="$elapsed_s" 'BEGIN { r = h - e/3600.0; if (r < 0.05) r = 0.05; printf "%.3f", r }')

    echo "[island $name] launching on port $port (remaining ${remaining_h}h)"
    SHOWDOWN_PORT=$port ISLAND_NAME=$name GA_CONCURRENCY=8 \
      python -m run.ga_island "$RUN_ID" "$remaining_h" \
      > "/tmp/ga_${RUN_ID}_${name}.log" 2>&1 &
    local pid=$!

    python3 "$REPO_ROOT/tools/watch_islands.py" "$RUN_ID" "$name" "$pid" 300 \
      > "/tmp/ga_${RUN_ID}_${name}_watchdog.log" 2>&1 &
    local wd_pid=$!

    wait "$pid"
    local rc=$?
    kill "$wd_pid" 2>/dev/null
    sleep 0.5

    if [ "$rc" -eq 0 ]; then
      echo "[island $name] exited cleanly"
      break
    fi
    # Watchdog kill = SIGKILL = rc 137. Any non-zero means respawn.
    local now_ts2 elapsed_total
    now_ts2=$(date +%s)
    elapsed_total=$(( now_ts2 - start_ts ))
    local budget_s
    budget_s=$(awk -v h="$HOURS" 'BEGIN { printf "%d", h * 3600 }')
    if [ "$elapsed_total" -ge "$budget_s" ]; then
      echo "[island $name] time budget exhausted, not respawning"
      break
    fi
    echo "[island $name] exited rc=$rc, respawning in 5s..."
    sleep 5
  done
}

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

for name in A B C; do
  case $name in
    A) port=8000 ;;
    B) port=8001 ;;
    C) port=8002 ;;
  esac
  run_island "$name" "$port" &
  sleep 2
done

echo "[main] waiting for all three islands..."
wait

# Rename champions: ga_p1_A_island_A.txt -> ga_p1_island_A.txt
for name in A B C; do
  src="output/champions/ga_${RUN_ID}_${name}_island_${name}.txt"
  dst="output/champions/ga_${RUN_ID}_island_${name}.txt"
  if [ -f "$src" ]; then
    mv "$src" "$dst"
    echo "[island $name] champion -> $dst"
  fi
done

echo "[main] all islands done. Champions:"
ls -la output/champions/ga_${RUN_ID}_island_*.txt 2>/dev/null
touch "/tmp/ga_${RUN_ID}_done"
echo "[main] done"
