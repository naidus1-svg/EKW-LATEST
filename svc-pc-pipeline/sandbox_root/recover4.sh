#!/usr/bin/env bash
# recover4.sh - relieve load, deploy the load-governor pool, and DIAGNOSE why fixers hit 33 despite the
# FIXSLOTS=8 cap. Report -> fleet/recover4.out. Detached.
set -u
cd /root/qc || exit 1
{
  echo "=== RECOVER4 $(date -u +%FT%TZ) ==="
  # relieve load: kill the Opus fix agents
  pkill -f "permission-mode dontAsk" 2>/dev/null; sleep 3
  echo "post-kill: fixers=$(pgrep -fc 'permission-mode dontAsk' 2>/dev/null||echo 0) load=$(cut -d' ' -f1 /proc/loadavg)"
  # deploy driver_pool WITH load governor
  tr -d '\r' < driver_pool.sh > dp.tmp && mv dp.tmp driver_pool.sh; chmod +x driver_pool.sh
  if bash -n driver_pool.sh; then echo "driver_pool.sh SYNOK"; else echo "driver_pool.sh SYNFAIL"; fi
  echo "--- DIAGNOSE fix-slot cap ---"
  echo "bash: $(bash --version | head -1)"
  echo "flock: $(command -v flock || echo MISSING)"
  echo "fixslot code in deployed task_driver.sh:"; grep -n "FIXSLOTS=\|qc_fixslot\|flock -n \"\$tryfd\"\|deferring fix\|fix slot .*acquired" task_driver.sh
  echo "slot lock files:"; ls -la /run/qc_fixslot.* 2>/dev/null || echo "  none exist"
  echo "who holds them:"; for s in 1 2 3 4 5 6 7 8; do f=/run/qc_fixslot.$s; [ -e "$f" ] && echo "  slot$s fuser: $(fuser "$f" 2>/dev/null || echo free)"; done
  echo "--- rogue old fixers? ---"
  echo "fix_one.sh procs: $(pgrep -fc fix_one.sh 2>/dev/null||echo 0)   fix_loop.sh procs: $(pgrep -fc fix_loop.sh 2>/dev/null||echo 0)"
  echo "crontab:"; crontab -l 2>/dev/null | sed 's/^/  /'
  echo "sample fixer cmdlines (up to 3):"; pgrep -fa "permission-mode dontAsk" 2>/dev/null | head -3 | sed 's/^/  /'
  echo "=== DONE $(date -u +%FT%TZ) ==="
} > /root/qc/fleet/recover4.out 2>&1
