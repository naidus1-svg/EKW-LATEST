#!/usr/bin/env bash
# recover3.sh - one-shot: install the fix-slot driver and drop the load-130 spike by killing the heavy
# Opus fix agents. driver_pool then relaunches with fixes capped at FIXSLOTS=8 concurrent (reviews stay
# uncapped). Report -> fleet/recover3.out. Detached so a dropped SSH session cannot interrupt it.
set -u
cd /root/qc || exit 1
{
  echo "=== RECOVER3 $(date -u +%FT%TZ) fix-slot admission control ==="
  tr -d '\r' < task_driver.sh > task_driver.tmp && mv task_driver.tmp task_driver.sh; chmod +x task_driver.sh
  if bash -n task_driver.sh; then echo "task_driver.sh SYNOK"; else echo "task_driver.sh SYNFAIL - ABORT"; exit 1; fi
  # drop the load: stop drivers, kill the heavy Opus FIX agents (unique --permission-mode dontAsk flag,
  # so the user's own interactive claude is untouched), stop review wrappers. All relaunch via cron.
  pkill -f task_driver.sh 2>/dev/null
  pkill -f "permission-mode dontAsk" 2>/dev/null
  pkill -f gate_review_cold.sh 2>/dev/null
  sleep 4
  echo "post-kill: drivers=$(pgrep -fc task_driver.sh 2>/dev/null||echo 0) fixers=$(pgrep -fc 'permission-mode dontAsk' 2>/dev/null||echo 0) reviews=$(pgrep -fc gate_review_cold.sh 2>/dev/null||echo 0)"
  echo "load: $(uptime | sed 's/.*load/load/')"
  echo "mem: $(free -g | awk '/Mem:/{print $7"G avail of "$2"G"}')"
  echo "verdicts: PASS=$(ls /root/qc/fleet/verdicts/*.PASS 2>/dev/null|wc -l) FAIL=$(ls /root/qc/fleet/verdicts/*.FAIL 2>/dev/null|wc -l) UNFIX=$(ls /root/qc/fleet/verdicts/*.UNFIXABLE 2>/dev/null|wc -l) OVERSIZE=$(ls /root/qc/fleet/verdicts/*.OVERSIZE 2>/dev/null|wc -l) STALL=$(ls /root/qc/fleet/verdicts/*.REVIEW_STALLED 2>/dev/null|wc -l)"
  echo "=== DONE $(date -u +%FT%TZ) ==="
} > /root/qc/fleet/recover3.out 2>&1
