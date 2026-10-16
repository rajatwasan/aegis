#!/usr/bin/env bash
set -u
cd "$(dirname "$0")"
MAX_RUNS=8
run=0
while ! grep -q "FRONTEND_COMPLETE" PROGRESS.md 2>/dev/null; do
  run=$((run+1))
  [ "$run" -gt "$MAX_RUNS" ] && { echo "[loop] max runs reached" | tee -a run.log; break; }
  echo "[loop] frontend session $run $(date)" | tee -a run.log
  claude -p "Read CLAUDE.md and FRONTEND.md in full. Resume from the first incomplete F-milestone in PROGRESS.md and keep working until FRONTEND_COMPLETE. Existing tests must stay green after every commit." \
    --dangerously-skip-permissions --verbose >> run.log 2>&1
  sleep 20
done