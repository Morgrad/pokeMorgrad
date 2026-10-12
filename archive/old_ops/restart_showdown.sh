#!/bin/bash
pkill -f "node pokemon-showdown" 2>/dev/null
sleep 2
cd ~/pokemon-showdown && nohup node pokemon-showdown start --no-security > /tmp/showdown.log 2>&1 &
sleep 5
curl -s http://localhost:8000 > /dev/null && echo "Showdown OK" || echo "Showdown FAILED"
