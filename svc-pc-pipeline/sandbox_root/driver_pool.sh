#!/usr/bin/env bash
# driver_pool.sh - keep up to POOL task_drivers running, ONE per undone task, and backfill as each
# finishes, until every task in fleet_tasks.txt is PASS or UNFIXABLE. This is the whole concurrency
# budget: each driver holds one claude call at a time, so POOL drivers == POOL concurrent calls, spent
# on the WHOLE loop (review or fix, whichever that task needs now). No sub-caps. Run every minute:
#   * * * * * bash /root/qc/driver_pool.sh >> /root/qc/fleet/driverpool.cron.out 2>&1
# Pure bash, zero LLM tokens. Re-entrant (fd lock); a dead driver re-launches next tick; resumes from
# the verdict/pid markers on disk after any hiccup or reboot, so nothing stalls for hours.
set -u
cd /root/qc || exit 1
exec 6>/run/driverpool.lock
flock -n 6 || exit 0
Q=/root/qc; FLEET=$Q/fleet; VERD=$FLEET/verdicts; JOBS=$FLEET/jobs
POOL=18          # concurrent drivers. Each driver's review pipes a multi-MB digest through claude -p,
                 # which is CPU-heavy (each call spawns ~6 procs). At 40 concurrent, load hit 96-130 and
                 # reviews STALLED for hours. ~18 (one per lane) is the box's real review capacity; the
                 # governor below is the hard backstop. Raise only after measuring load stays under ~1.4x.
MAXLAUNCH=6      # per-tick ramp only, so we reach POOL over a few minutes instead of a cold thundering herd
mkdir -p "$JOBS" "$FLEET/driverlogs" "$VERD"
echo "$(date +%s)" > "$FLEET/driverpool.heartbeat"
echo "$(date +%s)" > "$FLEET/fleet.heartbeat"   # keep the existing phone dashboard's heartbeat fresh too
[ -f "$FLEET/fleet_tasks.txt" ] || { echo "$(date -u +%FT%TZ) driverpool: no fleet_tasks.txt" >> "$FLEET/driverpool.log"; exit 0; }

lane_free(){ local b=".claude-$1"; [ -f "/root/qc/lanes/$b.benched" ] && return 1; local lu="/root/qc/lanes/$b.limited_until"; if [ -f "$lu" ]; then local ts; ts=$(tr -dc 0-9 <"$lu" 2>/dev/null); ts=${ts:-0}; [ "$ts" -gt "$(date +%s)" ] 2>/dev/null && return 1; fi; return 0; }
ACCTS=(); for L in q r m v w b c d e f g i j k l p t u; do lane_free "$L" && ACCTS+=("/root/.claude-$L"); done
[ "${#ACCTS[@]}" -ge 2 ] || { echo "$(date -u +%FT%TZ) driverpool: too few lanes ${#ACCTS[@]}" >> "$FLEET/driverpool.log"; exit 0; }
# Budget counts drivers AND any old fix_one.sh still draining, so the total heavy claude procs stay at
# POOL through the handover instead of stacking 52 drivers on top of the fixers. As fixers finish,
# drivers fill the freed budget automatically.
live_drivers(){ local a b; a=$(pgrep -fc task_driver.sh 2>/dev/null); b=$(pgrep -fc fix_one.sh 2>/dev/null); echo $(( ${a:-0} + ${b:-0} )); }

# Load governor - the admission control the rebuild was missing (load hit 130 with no brake). If the
# box is already saturated, launch NOTHING this tick and let it drain. Heartbeat is already fresh above,
# so the dashboard stays live; running drivers keep working; the next tick re-checks.
CORES=$(nproc 2>/dev/null || echo 32)
MAXLOAD=$(( CORES * 3 / 2 ))   # hold new launches once load reaches ~1.5x cores
load1=$(cut -d' ' -f1 /proc/loadavg 2>/dev/null | cut -d. -f1); load1=${load1:-0}
if [ "$load1" -ge "$MAXLOAD" ]; then
  echo "$(date -u +%FT%TZ) driverpool HELD load=$load1 >= ${MAXLOAD} (drivers=$(pgrep -fc task_driver.sh 2>/dev/null) fixers=$(pgrep -fc 'permission-mode dontAsk' 2>/dev/null)); launching nothing" >> "$FLEET/driverpool.log"
  exit 0
fi

launched=0; k=0
while read -r t; do
  [ -n "$t" ] || continue
  case "$t" in \#*) continue;; esac
  # terminal states: done. OVERSIZE = flagged for workspace review (cannot be digest-gated).
  { [ -f "$VERD/$t.PASS" ] || [ -f "$VERD/$t.UNFIXABLE" ] || [ -f "$VERD/$t.OVERSIZE" ]; } && continue
  pidf="$JOBS/$t.driver.pid"
  [ -f "$pidf" ] && kill -0 "$(cat "$pidf" 2>/dev/null)" 2>/dev/null && continue
  # Do not launch a driver on a task an OLD fix_one.sh is still editing: two writers on one task dir is
  # the exact corruption we must never recreate. Skip it until that fixer's wrapper exits, then take it.
  ofix="$JOBS/$t.fix.pid"
  [ -f "$ofix" ] && kill -0 "$(cat "$ofix" 2>/dev/null)" 2>/dev/null && continue
  [ $(( $(live_drivers) + launched )) -ge "$POOL" ] && break
  [ "$launched" -ge "$MAXLAUNCH" ] && break
  lane="${ACCTS[$(( k % ${#ACCTS[@]} ))]}"; k=$((k+1))
  ( bash "$Q/task_driver.sh" "$t" "$lane" ) 6>&- &
  echo $! > "$pidf"; launched=$((launched+1))
done < "$FLEET/fleet_tasks.txt"
tickline="$(date -u +%FT%TZ) driverpool launched=$launched live=$(live_drivers) pass=$(ls "$VERD"/*.PASS 2>/dev/null|wc -l) fail=$(ls "$VERD"/*.FAIL 2>/dev/null|wc -l) unfix=$(ls "$VERD"/*.UNFIXABLE 2>/dev/null|wc -l)"
echo "$tickline" >> "$FLEET/driverpool.log"
echo "$tickline" >> "$FLEET/fleet.log"   # existing phone dashboard tails fleet.log; keep it current
