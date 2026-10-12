#!/bin/bash
# Kill only actual tensorboard processes (not this script)
pkill -9 -f "python.*tensorboard" 2>/dev/null
sleep 1
source ~/vgc-bench-env/bin/activate
cd ~/vgc-bench
nohup tensorboard --logdir results/logs_sp --port 6006 > /tmp/tensorboard.log 2>&1 &
sleep 4
if curl -s http://localhost:6006 > /dev/null 2>&1; then
    echo "✓ TensorBoard running at http://localhost:6006"
else
    echo "✗ TensorBoard failed. Log:"
    cat /tmp/tensorboard.log
fi
