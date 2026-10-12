#!/bin/bash
# Usage: bash start_training.sh <run_id> <total_steps>
RUN_ID=${1:-200}
STEPS=${2:-500000}

source ~/vgc-bench-env/bin/activate
cd ~/vgc-bench

nohup python -u -m vgc_bench.train \
    --reg mc \
    --run_id $RUN_ID \
    --num_teams 20 \
    --num_envs 2 \
    --num_eval_workers 1 \
    --total_steps $STEPS \
    --self_play \
    --port 8000 \
    --log_level 40 \
    --device cuda \
    > /tmp/train_${RUN_ID}.log 2>&1 &

echo "Training launched (PID $!)"
echo "Run ID: $RUN_ID"
echo "Steps: $STEPS"
echo ""
echo "Check progress: bash ~/pokemon-ai/check_progress.sh $RUN_ID"
echo "TensorBoard:   bash ~/pokemon-ai/start_tensorboard.sh"
