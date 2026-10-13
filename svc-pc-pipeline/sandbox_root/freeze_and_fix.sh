#!/usr/bin/env bash
# freeze_and_fix.sh - one-shot recovery from the false-PASS bug. Report -> fleet/freeze.out.
#   1. install the fixed task_driver.sh (require 4 canonical reviews before any PASS)
#   2. freeze the stager so nothing can ship while we clean up
#   3. kill the drivers + review calls still running the OLD (false-passing) code
#   4. purge every PASS verdict that does not have 4 canonical reviews, so it gets re-gated cleanly
# driver_pool cron (unchanged, every minute) then relaunches fresh drivers with the fixed code.
# Launched detached so a dropped SSH session cannot interrupt it.
set -u
cd /root/qc || exit 1
{
  echo "=== FREEZE_AND_FIX $(date -u +%FT%TZ) ==="
  # 1. install fixed driver
  tr -d '\r' < task_driver.sh > task_driver.tmp && mv task_driver.tmp task_driver.sh; chmod +x task_driver.sh
  if bash -n task_driver.sh; then echo "task_driver.sh SYNOK"; else echo "task_driver.sh SYNFAIL - ABORT"; exit 1; fi
  # 2. freeze stager
  crontab -l > "crontab.bak-freeze-$(date +%s)" 2>/dev/null
  crontab -l 2>/dev/null | grep -v batch_stager.sh > /tmp/ct.f; crontab /tmp/ct.f
  pkill -f batch_stager.sh 2>/dev/null
  echo "stager frozen; crontab now:"; crontab -l
  # 3. stop old-code drivers + their review calls (fix_one fixers keep draining; they never write PASS)
  pkill -f task_driver.sh 2>/dev/null; pkill -f gate_review_cold.sh 2>/dev/null; sleep 2
  echo "post-kill: drivers=$(pgrep -fc task_driver.sh 2>/dev/null || echo 0) reviews=$(pgrep -fc gate_review_cold.sh 2>/dev/null || echo 0) fix_one=$(pgrep -fc fix_one.sh 2>/dev/null || echo 0)"
  # 4. purge false passes
  kept=0; purged=0
  for v in /root/qc/fleet/verdicts/*.PASS; do
    [ -e "$v" ] || continue
    t=$(basename "$v" .PASS); n=0
    for spec in opus:1 opus:2 sonnet:1 sonnet:2; do
      r=${spec%%:*}; nn=${spec##*:}; f="/root/qc/fleet/reviews/$t.$r.run$nn.json"
      python3 -c "import json,sys
try: j=json.load(open('$f'))
except Exception: sys.exit(1)
sys.exit(0 if j.get('overall_verdict') in ('accept','reject','invalid','needs_revision') and isinstance(j.get('checks'),list) and j['checks'] and isinstance(j.get('major_count'),int) else 1)" 2>/dev/null && n=$((n+1))
    done
    if [ "$n" -lt 4 ]; then rm -f "$v"; purged=$((purged+1)); else kept=$((kept+1)); fi
  done
  echo "PASS purge: kept_real=$kept purged_false=$purged"
  echo "verdicts now: PASS=$(ls /root/qc/fleet/verdicts/*.PASS 2>/dev/null|wc -l) FAIL=$(ls /root/qc/fleet/verdicts/*.FAIL 2>/dev/null|wc -l) UNFIX=$(ls /root/qc/fleet/verdicts/*.UNFIXABLE 2>/dev/null|wc -l)"
  echo "load: $(uptime | sed 's/.*load/load/')"
  echo "=== DONE $(date -u +%FT%TZ) ==="
} > /root/qc/fleet/freeze.out 2>&1
