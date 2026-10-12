#!/bin/bash
# Stops training + training server (8000) + tensorboard.
# Leaves the eval server on 8001 untouched.

pkill -9 -f "vgc_bench.train" 2>/dev/null
pkill -9 -f "pokemon-showdown start 8000" 2>/dev/null
pkill -9 -f tensorboard 2>/dev/null
pkill -f "watch_server.sh" 2>/dev/null

echo "✓ Training, training Showdown (8000), TensorBoard, watchdog stopped"
echo "  (eval Showdown on 8001 left running)"
