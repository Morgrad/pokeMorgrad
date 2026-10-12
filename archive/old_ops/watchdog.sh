#!/bin/bash
while true; do
    if ! curl -s http://localhost:8000 > /dev/null 2>&1; then
        echo "$(date): Showdown dead — restarting" >> ~/project/watchdog.log
        bash ~/project/restart_showdown.sh >> ~/project/watchdog.log 2>&1
    fi
    sleep 60
done
