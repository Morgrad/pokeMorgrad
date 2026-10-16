#!/bin/bash
# Usage: start_server.sh [port]   (default 8000). Restarts only that port's server.
PORT="${1:-8000}"
SHOWDOWN_DIR="${SHOWDOWN_DIR:-$HOME/pokemon-showdown}"
pkill -9 -f "pokemon-showdown start $PORT( |\$)" 2>/dev/null
sleep 2
cd "$SHOWDOWN_DIR"
nohup node pokemon-showdown start "$PORT" --no-security > "/tmp/showdown_${PORT}.log" 2>&1 &
sleep 5
curl -s "http://localhost:$PORT" > /dev/null && echo "✓ Server up on :$PORT" || echo "✗ Server failed to start"
