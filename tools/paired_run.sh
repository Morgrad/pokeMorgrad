#!/usr/bin/env bash
# Launch the paired eval on the 3 Showdown servers (one shard per server).
# Every CHUNK matchups a shard's Showdown server is restarted and the shard process is relaunched
# (resumes from its log), like the GA's showdown_restart_every. A shard with no log write for STALL_S
# seconds is killed and resumed; a crashed shard is restarted (up to 6 times in a row).
# usage: bash tools/paired_run.sh <opp: heuristic|ladder> <target matchups per shard>
# env: CHUNK (default 1000), STALL_S (default 300)
set -u
OPP=${1:-ladder}; TARGET=${2:-5500}; CHUNK=${CHUNK:-1000}; STALL_S=${STALL_S:-300}
cd "$(dirname "$0")/.."
PY=${PY:-$HOME/venv-pokemorgad/bin/python}
SD=${SHOWDOWN_DIR:-$HOME/pokemon-showdown}
mkdir -p data/paired_eval

restart_server() {  # kill + relaunch the Showdown server on port $1, wait until it answers
  local port=$1
  pkill -9 -f "pokemon-showdown start $port" 2>/dev/null
  sleep 2
  (cd "$SD" && nohup node pokemon-showdown start "$port" --no-security > "/tmp/showdown_${port}.log" 2>&1 &)
  for _ in $(seq 1 60); do
    curl -s "http://localhost:$port" > /dev/null && return 0
    sleep 1
  done
  return 1
}

run_shard() {
  local i=$1 port=$((8000 + $1))
  local out=data/paired_eval/${OPP}_shard$i.jsonl log=data/paired_eval/${OPP}_run$i.log
  local fails=0
  while true; do
    if ! restart_server "$port"; then
      echo "[$(date +%T)] shard $i: Showdown :$port did not come up" >> "$log"
      fails=$((fails + 1)); [ $fails -ge 6 ] && return 1; sleep 20; continue
    fi
    echo "[$(date +%T)] shard $i: server :$port restarted, launching chunk" >> "$log"
    SHOWDOWN_PORT=$port PYTHONPATH=. $PY tools/paired_eval.py run --shard "$i" --shards 3 \
      --target "$TARGET" --chunk "$CHUNK" --opp "$OPP" >> "$log" 2>&1 &
    local pid=$! launched; launched=$(date +%s)
    while kill -0 "$pid" 2>/dev/null; do
      sleep 20
      local m ref; m=$(stat -c %Y "$out" 2>/dev/null || echo 0)
      ref=$(( m > launched ? m : launched ))
      if [ $(( $(date +%s) - ref )) -gt "$STALL_S" ]; then
        echo "[$(date +%T)] shard $i: no write for ${STALL_S}s, killing (will resume)" >> "$log"
        kill -9 "$pid" 2>/dev/null
      fi
    done
    wait "$pid"; local rc=$?
    case $rc in
      0)  echo "[$(date +%T)] shard $i: target reached" >> "$log"; return 0 ;;
      10) fails=0 ;;
      *)  fails=$((fails + 1)); echo "[$(date +%T)] shard $i: exited rc=$rc ($fails/6)" >> "$log"
          [ $fails -ge 6 ] && return 1; sleep 20 ;;
    esac
  done
}

for i in 0 1 2; do run_shard $i & done
wait
