#!/bin/bash
pkill -9 -f "pokemon-showdown" 2>/dev/null
sleep 2
cd ~/pokemon-showdown
nohup node pokemon-showdown start 8000 --no-security > /tmp/showdown.log 2>&1 &
sleep 5
curl -s http://localhost:8000 > /dev/null && echo "✓ Server up on :8000" || echo "✗ Server failed to start"
