#!/usr/bin/env bash
# recover5.sh - deploy POOL=18 governor pool, hard-reset the fleet, let it ramp, then MEASURE load at
# the new setting (waits ~3 min internally so the reading is real, not a mid-kill transient).
# Report -> fleet/recover5.out. Detached.
set -u
cd /root/qc || exit 1
{
  echo "=== RECOVER5 $(date -u +%FT%TZ) POOL=18 + load governor ==="
  tr -d '\r' < driver_pool.sh > dp.tmp && mv dp.tmp driver_pool.sh; chmod +x driver_pool.sh
  if bash -n driver_pool.sh; then echo "driver_pool.sh SYNOK POOL=$(grep -m1 '^POOL=' driver_pool.sh)"; else echo "SYNFAIL - ABORT"; exit 1; fi
  # hard reset: stop drivers and ALL their claude children (reviews = output-format json, fixes = text)
  pkill -f task_driver.sh 2>/dev/null
  pkill -f gate_review_cold.sh 2>/dev/null
  pkill -f "output-format json --permission-mode dontAsk" 2>/dev/null
  pkill -f "output-format text --permission-mode dontAsk" 2>/dev/null
  sleep 5
  echo "post-reset: drivers=$(pgrep -fc task_driver.sh 2>/dev/null||echo 0) reviews=$(pgrep -fc 'output-format json --permission-mode dontAsk' 2>/dev/null||echo 0) fixes=$(pgrep -fc 'output-format text --permission-mode dontAsk' 2>/dev/null||echo 0) load=$(cut -d' ' -f1 /proc/loadavg)"
  echo "waiting 3 min for POOL=18 to ramp, then measuring..."
  sleep 180
  echo "--- MEASURED at POOL=18 ($(date -u +%FT%TZ)) ---"
  echo "load: $(cut -d' ' -f1-3 /proc/loadavg)"
  echo "live: drivers=$(pgrep -fc task_driver.sh 2>/dev/null||echo 0) reviews=$(pgrep -fc 'output-format json --permission-mode dontAsk' 2>/dev/null||echo 0) fixes=$(pgrep -fc 'output-format text --permission-mode dontAsk' 2>/dev/null||echo 0)"
  echo "mem: $(free -g | awk '/Mem:/{print $7"G avail of "$2"G"}')"
  echo "verdicts: PASS=$(ls /root/qc/fleet/verdicts/*.PASS 2>/dev/null|wc -l) FAIL=$(ls /root/qc/fleet/verdicts/*.FAIL 2>/dev/null|wc -l) UNFIX=$(ls /root/qc/fleet/verdicts/*.UNFIXABLE 2>/dev/null|wc -l) OVERSIZE=$(ls /root/qc/fleet/verdicts/*.OVERSIZE 2>/dev/null|wc -l) STALL=$(ls /root/qc/fleet/verdicts/*.REVIEW_STALLED 2>/dev/null|wc -l)"
  echo "governor holds so far: $(grep -c 'driverpool HELD' /root/qc/fleet/driverpool.log 2>/dev/null)"
  echo "--- driverpool.log tail ---"; tail -4 /root/qc/fleet/driverpool.log 2>/dev/null
  echo "=== DONE $(date -u +%FT%TZ) ==="
} > /root/qc/fleet/recover5.out 2>&1
