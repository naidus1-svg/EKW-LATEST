#!/usr/bin/env bash
# scale_up_ws.sh - flip the fleet from the digest gate to the v4 workspace pipeline. One-shot, detached.
#   * stop the digest driver_pool cron + kill all old drivers/reviews (canary included) so ONLY the new
#     F2-per-task-locked ws drivers run (no two writers on a task during the handover)
#   * keep the 27 shipped digest PASSes; clear the weaker digest non-PASS verdicts + counters so the
#     workspace pipeline authoritatively re-reviews every remaining task (the 74 oversize included)
#   * start driver_pool_ws (POOL=52, load governor). batch_stager + throughput_watch crons stay.
# Report -> fleet/scaleup_ws.out
set -u
cd /root/qc || exit 1
{
  echo "=== SCALE_UP_WS $(date -u +%FT%TZ) ==="
  tr -d '\r' < driver_pool_ws.sh > dpw.tmp && mv dpw.tmp driver_pool_ws.sh; chmod +x driver_pool_ws.sh
  if bash -n driver_pool_ws.sh; then echo "driver_pool_ws.sh SYNOK"; else echo "driver_pool_ws.sh SYNFAIL - ABORT"; exit 1; fi
  crontab -l > "crontab.bak-scaleup-$(date +%s)" 2>/dev/null
  crontab -l 2>/dev/null | grep -v 'driver_pool\.sh' > /tmp/ct.s
  grep -q driver_pool_ws.sh /tmp/ct.s || echo '* * * * * bash /root/qc/driver_pool_ws.sh >> /root/qc/fleet/driverpool_ws.cron.out 2>&1' >> /tmp/ct.s
  crontab /tmp/ct.s
  pkill -f 'task_driver\.sh' 2>/dev/null        # digest drivers
  pkill -f 'task_driver_ws\.sh' 2>/dev/null     # old canary ws drivers (pre-F2 lock)
  pkill -f gate_review_cold.sh 2>/dev/null      # digest reviews
  pkill -f run_workspace_review.py 2>/dev/null  # canary/test workspace reviews
  sleep 4
  rm -f /root/qc/fleet/verdicts/*.UNFIXABLE /root/qc/fleet/verdicts/*.OVERSIZE /root/qc/fleet/verdicts/*.FAIL /root/qc/fleet/verdicts/*.REVIEW_STALLED
  rm -f /root/qc/fleet/reviewfail/* /root/qc/fleet/fixattempts/* 2>/dev/null
  echo "crontab now:"; crontab -l | grep -vE '^\s*#'
  echo "kept shipped PASS: $(ls /root/qc/fleet/verdicts/*.PASS 2>/dev/null|wc -l)"
  echo "old drivers left: digest=$(pgrep -fc 'task_driver\.sh' 2>/dev/null||echo 0) ws=$(pgrep -fc 'task_driver_ws\.sh' 2>/dev/null||echo 0)"
  bash /root/qc/driver_pool_ws.sh
  sleep 25
  echo "ws drivers live now: $(pgrep -fc task_driver_ws.sh 2>/dev/null||echo 0)"
  echo "load: $(cut -d' ' -f1-3 /proc/loadavg)"
  tail -2 /root/qc/fleet/driverpool_ws.log 2>/dev/null
  echo "=== DONE $(date -u +%FT%TZ) ==="
} > /root/qc/fleet/scaleup_ws.out 2>&1
