#!/bin/bash
# Watchdog: keep Showdown alive, kill training if it stalls.
# Run with: nohup bash ~/project/ops/watch_server.sh > /tmp/watch_server.log 2>&1 &

TB_DIR=~/vgc-bench/results/logs_sp
STALL_SECONDS=300   # kill training if no TB write in 5 min
CHECK_INTERVAL=30

echo "$(date) watchdog started"
while true; do
    # 1. Showdown health
    if ! curl -s http://localhost:8000 > /dev/null 2>&1; then
        echo "$(date) Showdown DOWN — restarting"
        bash ~/project/ops/start_server.sh
        sleep 5
    fi

    # 2. Training stall detection (only if training is running)
    if pgrep -f "vgc_bench.train" > /dev/null; then
        NEWEST=$(find "$TB_DIR" -type f -name "events.out.tfevents.*" -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | awk '{print $1}')
        if [ -n "$NEWEST" ]; then
            NOW=$(date +%s)
            AGE=$(( NOW - ${NEWEST%.*} ))
            if [ "$AGE" -gt "$STALL_SECONDS" ]; then
                echo "$(date) Training stalled (TB age ${AGE}s) — killing training"
                pkill -9 -f "vgc_bench.train"
            fi
        fi
    fi

    sleep $CHECK_INTERVAL
done
