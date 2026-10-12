#!/bin/bash
RUN_ID=${1:-101}
echo "=== Training process ==="
pgrep -af "vgc_bench.train" | head -3 || echo "(no training running)"

echo ""
echo "=== Checkpoints in seed$RUN_ID ==="
ls -la ~/vgc-bench/results/saves_sp/reg_mc/20_teams/seed$RUN_ID/ 2>/dev/null || echo "(no checkpoints yet)"

echo ""
echo "=== Last 5 lines of training log ==="
tail -5 /tmp/train_${RUN_ID}.log 2>/dev/null || echo "(no log)"
