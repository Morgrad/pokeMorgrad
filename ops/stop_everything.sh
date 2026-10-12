#!/bin/bash
bash ~/project/ops/stop_all.sh
pkill -9 -f "pokemon-showdown start 8001" 2>/dev/null
pkill -9 -f "evaluate_team_v2.py" 2>/dev/null
echo "✓ Eval server + eval processes also stopped"
