#!/bin/bash
# Full pause: back up + clear cron so nothing relaunches, then hard-kill the fleet. Detached so an
# SSH drop cannot abort it. Verdict files under fleet/verdicts are left untouched (earned data).
crontab -l > /root/qc/crontab.full.bak.20260920 2>/dev/null
crontab -r 2>/dev/null
for i in 1 2 3; do
  pkill -9 -f task_driver_ws.sh
  pkill -9 -f driver_pool_ws.sh
  pkill -9 -f 'claude -p'
  sleep 2
done
sleep 2
{
  echo "PAUSE $(date -u +%FT%TZ)"
  echo "cron_lines=$(crontab -l 2>/dev/null | grep -vc '^[[:space:]]*#')"
  echo "pool=$(pgrep -fc '[d]river_pool_ws.sh')"
  echo "drivers=$(pgrep -fc '[t]ask_driver_ws.sh')"
  echo "claudep=$(pgrep -fc -- 'claude -p')"
  echo "load=$(cut -d' ' -f1-3 /proc/loadavg)"
} > /root/qc/_killcheck.txt 2>&1
