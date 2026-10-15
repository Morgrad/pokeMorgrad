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

# Launch three island processes
for name in A B C; do
  case $name in
    A) port=8000 ;;
    B) port=8001 ;;
    C) port=8002 ;;
  esac
  echo "[island $name] launching on port $port"
  SHOWDOWN_PORT=$port ISLAND_NAME=$name GA_CONCURRENCY=8 \
    python -m run.ga_island "$RUN_ID" "$HOURS" \
    > "/tmp/ga_${RUN_ID}_${name}.log" 2>&1 &
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
