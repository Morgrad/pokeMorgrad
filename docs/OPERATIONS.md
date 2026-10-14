# Operations runbook

> Copy-paste commands for running, monitoring, resuming, and stopping every
> service in this project. Written to be usable at 2am with a hung terminal.
> For *what* the project is, see `STATE.md`; for *why* decisions were made,
> see `STATE_history.md`. This file is *how to drive it*.

**Quick rule of thumb:** every long-running process depends on the Showdown
server on `:8000`. Nothing works if it's down — and you can't always tell
because battle attempts just hang with a 20s timeout and 1 retry (so a
2000-battle eval can sit silently for 20+ minutes doing nothing).

---

## 0. Health check (run this first, always)

```bash
cd ~/project
source ~/llm-env/bin/activate

echo "=== Showdown ==="
curl -s http://localhost:8000 > /dev/null && echo "UP" || echo "DOWN  <-- fix this first"

echo "=== Processes ==="
ps aux | grep -E "ga_run|src.eval|bc_train|pokemon-showdown" | grep -v grep

echo "=== Disk artifacts ==="
ls -la output/champions/ | tail -5
ls -la output/checkpoints/v6/run1/ | tail -3
ls -la output/checkpoints/v6/run2/ | tail -3
