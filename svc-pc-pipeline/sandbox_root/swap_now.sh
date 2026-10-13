#!/usr/bin/env bash
# swap_now.sh - one-shot: retire the old fragmented pipeline (fleet gate cron + fix_loop cron) and put
# the one-driver-per-task pool in its place, then fire the first driver tick. Writes a report to
# fleet/swap.out. Launched detached so a dropped SSH session cannot interrupt it.
set -u
cd /root/qc || exit 1
{
  for f in task_driver.sh driver_pool.sh; do
    tr -d '\r' < "$f" > "$f.tmp" && mv "$f.tmp" "$f"; chmod +x "$f"
    if bash -n "$f"; then echo "SYNOK $f"; else echo "SYNFAIL $f"; fi
  done
  crontab -l > "/root/qc/crontab.bak-swap-$(date +%s)" 2>/dev/null
  crontab -l 2>/dev/null | grep -v 'fleet.sh' | grep -v 'fix_loop.sh' > /tmp/ct.new
  grep -q 'driver_pool.sh' /tmp/ct.new || echo '* * * * * bash /root/qc/driver_pool.sh >> /root/qc/fleet/driverpool.cron.out 2>&1' >> /tmp/ct.new
  crontab /tmp/ct.new
  # stop the stateless old gate reviewers so they cannot race driver verdicts; in-flight fix_one.sh
  # fixers are left to drain, and driver_pool skips any task they are still editing (no double writer).
  pkill -f gate_review_cold.sh 2>/dev/null; sleep 1
  bash /root/qc/driver_pool.sh
  echo "SWAP_DONE $(date -u +%FT%TZ)"
} > /root/qc/fleet/swap.out 2>&1
