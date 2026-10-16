#!/usr/bin/env bash
# Aegis overnight loop: relaunches Claude Code until the mission reports done.
set -u
cd "$(dirname "$0")"

MAX_RUNS=12          # hard cap on sessions so a pathological loop cannot burn tokens all night
run=0

while ! grep -q "ALL_MILESTONES_COMPLETE" PROGRESS.md 2>/dev/null; do
  run=$((run+1))
  if [ "$run" -gt "$MAX_RUNS" ]; then
    echo "[loop] max runs reached, stopping" | tee -a run.log
    break
  fi
  echo "[loop] session $run starting $(date)" | tee -a run.log
  claude -p "Read CLAUDE.md and PROMPT.md in full. Resume from the first incomplete milestone in PROGRESS.md and keep working until all milestones are complete. Follow the autonomy protocol exactly." \
    --dangerously-skip-permissions \
    --verbose >> run.log 2>&1
  echo "[loop] session $run exited $(date)" | tee -a run.log
  sleep 20
done
echo "[loop] finished $(date)" | tee -a run.log