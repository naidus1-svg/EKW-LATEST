#!/usr/bin/env bash
# reset_ws.sh - clean reset of the ws fleet: kill all drivers/reviews, release stuck task+fix locks,
# clear stale pidfiles, then let the cron relaunch and VERIFY the drivers survive. Report -> reset_ws.out
set -u
cd /root/qc || exit 1
pc(){ local n; n=$(pgrep -fc "$1" 2>/dev/null); echo "${n:-0}"; }
{
  echo "=== RESET_WS $(date -u +%FT%TZ) ==="
  free -g | awk '/Mem:/{print "mem: "$7"G avail of "$2"G total"}'
  pkill -9 -f task_driver_ws.sh 2>/dev/null
  pkill -9 -f run_workspace_review.py 2>/dev/null
  pkill -9 -f "output-format stream-json" 2>/dev/null
  sleep 4
  rm -f /run/qc_task.*.lock /run/qc_wsfix.* 2>/dev/null
  rm -f /root/qc/fleet/jobs/*.wsdriver.pid 2>/dev/null
  echo "cleared locks + pidfiles; ws procs now: $(pc task_driver_ws.sh)"
  echo "waiting 70s for a cron tick to relaunch..."
  sleep 70
  echo "ws_drivers after 1 tick: $(pc task_driver_ws.sh)   reviews: $(pc run_workspace_review.py)   load: $(cut -d' ' -f1 /proc/loadavg)"
  echo "waiting 45s to see if they SURVIVE (not insta-killed)..."
  sleep 45
  echo "ws_drivers 45s later: $(pc task_driver_ws.sh)   reviews: $(pc run_workspace_review.py)"
  echo "Killed lines in recent cronout: $(tail -8 /root/qc/fleet/driverpool_ws.cron.out 2>/dev/null | grep -c Killed)"
  echo "poollog:"; tail -3 /root/qc/fleet/driverpool_ws.log 2>/dev/null
  echo "verdicts: PASS=$(ls /root/qc/fleet/verdicts/*.PASS 2>/dev/null|wc -l) FAIL=$(ls /root/qc/fleet/verdicts/*.FAIL 2>/dev/null|wc -l) UNFIX=$(ls /root/qc/fleet/verdicts/*.UNFIXABLE 2>/dev/null|wc -l)"
  echo "=== DONE $(date -u +%FT%TZ) ==="
} > /root/qc/fleet/reset_ws.out 2>&1
