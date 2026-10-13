#!/usr/bin/env bash
# status.sh - live zero-token phone dashboard (tmux 'status' window). Points at the WS pipeline
# (task_driver_ws.sh / driver_pool_ws.sh / driverpool_ws.log), not the retired single-shot pool.
while true; do
  clear
  echo "######## HEALTH (watchdog, every 5 min) ########"
  cat /root/qc/fleet/HEALTH.txt 2>/dev/null || echo "(watchdog has not run yet)"
  echo "################################################"
  echo
  echo "===== SVC-PC WS FLEET   $(date -u +%FT%TZ) ====="
  hb=$(cat /root/qc/fleet/driverpool.heartbeat 2>/dev/null || echo 0)
  echo "pool heartbeat: $(( $(date +%s) - hb ))s ago   (healthy under 120; cron every 60s)"
  P=$(ls /root/qc/fleet/verdicts/*.PASS 2>/dev/null | wc -l)
  F=$(ls /root/qc/fleet/verdicts/*.FAIL 2>/dev/null | wc -l)
  U=$(ls /root/qc/fleet/verdicts/*.UNFIXABLE 2>/dev/null | wc -l)
  S=$(ls /root/qc/fleet/verdicts/*.REVIEW_STALLED 2>/dev/null | wc -l)
  D=$(pgrep -fc '[t]ask_driver_ws.sh' 2>/dev/null); D=${D:-0}
  echo "verdicts:  PASS=$P  FAIL=$F  UNFIXABLE=$U  STALLED=$S   of 202   (finished=$((P+U)))"
  echo "live drivers=$D   load: $(cut -d' ' -f1 /proc/loadavg) (32 cores)"
  echo "lanes in use:"
  ps -eo args 2>/dev/null | grep -F task_driver_ws.sh | grep -v grep \
    | grep -oE 'claude-[a-z]+' | sort | uniq -c | awk '{print "   "$2": "$1}'
  echo "--- driverpool_ws.log (last 6 ticks) ---"
  tail -6 /root/qc/fleet/driverpool_ws.log 2>/dev/null
  echo
  echo "(auto-refresh 20s. detach: Ctrl-b then d. scroll: Ctrl-b then [ , q to exit)"
  sleep 20
done
