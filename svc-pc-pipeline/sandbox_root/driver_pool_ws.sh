#!/usr/bin/env bash
# driver_pool_ws.sh - keep up to POOL task_driver_ws.sh drivers running, ONE per undone task, over ALL
# 202 tasks (no oversize exclusion - workspace review handles any size). Backfills as each finishes.
# Run every minute from cron:
#   * * * * * bash /root/qc/driver_pool_ws.sh >> /root/qc/fleet/driverpool_ws.cron.out 2>&1
# Pure bash, zero LLM tokens. Re-entrant (fd lock); dead drivers relaunch next tick; resumes from the
# on-disk verdict/pid markers after any hiccup. A load governor is the hard backstop against a meltdown.
set -u
cd /root/qc || exit 1
exec 6>/run/driverpool_ws.lock
flock -n 6 || exit 0
Q=/root/qc; FLEET=$Q/fleet; VERD=$FLEET/verdicts; JOBS=$FLEET/jobs
POOL=18          # ~1.2 concurrent reviews per alive lane. The POOL=52 failures were 429 rate-limiting
                 # from 2.6/lane hammering each account, NOT window exhaustion (a probe found 15 of 18
                 # lanes alive). 18 stays well under that 2.6/lane storm threshold on the 15 live lanes
                 # while giving real throughput. Dead lanes are benched (lanes/.claude-X.limited_until).
MAXLAUNCH=4      # gentle ramp
mkdir -p "$JOBS" "$FLEET/driverlogs" "$VERD"
echo "$(date +%s)" > "$FLEET/driverpool.heartbeat"
echo "$(date +%s)" > "$FLEET/fleet.heartbeat"
[ -f "$FLEET/fleet_tasks.txt" ] || { echo "$(date -u +%FT%TZ) driverpool_ws: no fleet_tasks.txt" >> "$FLEET/driverpool_ws.log"; exit 0; }

lane_free(){ local b=".claude-$1"; [ -f "/root/qc/lanes/$b.benched" ] && return 1; local lu="/root/qc/lanes/$b.limited_until"; if [ -f "$lu" ]; then local ts; ts=$(tr -dc 0-9 <"$lu" 2>/dev/null); ts=${ts:-0}; [ "$ts" -gt "$(date +%s)" ] 2>/dev/null && return 1; fi; return 0; }
ACCTS=(); for L in q r m v w b c d e f g i j k l p t u; do lane_free "$L" && ACCTS+=("/root/.claude-$L"); done
[ "${#ACCTS[@]}" -ge 2 ] || { echo "$(date -u +%FT%TZ) driverpool_ws: too few lanes ${#ACCTS[@]}" >> "$FLEET/driverpool_ws.log"; exit 0; }
live_drivers(){ local n; n=$(pgrep -fc task_driver_ws.sh 2>/dev/null); echo "${n:-0}"; }

# Load governor: the box has 32 cores. Hold new launches once load reaches ~1.5x so a burst of fix
# passes / tool-call bursts cannot spiral. Heartbeat is already fresh; running drivers keep working.
CORES=$(nproc 2>/dev/null || echo 32)
MAXLOAD=$(( CORES * 3 / 2 ))
load1=$(cut -d' ' -f1 /proc/loadavg 2>/dev/null | cut -d. -f1); load1=${load1:-0}
if [ "$load1" -ge "$MAXLOAD" ]; then
  echo "$(date -u +%FT%TZ) driverpool_ws HELD load=$load1 >= ${MAXLOAD} (drivers=$(live_drivers)); launching nothing" >> "$FLEET/driverpool_ws.log"
  exit 0
fi

launched=0
# per-lane running-driver counts: launch onto the LEAST-loaded free lane so idle lanes
# actually get used and no single account (q) piles up past the 429 threshold.
declare -A LANELOAD
for a in "${ACCTS[@]}"; do L="${a##*-}"; c=$(pgrep -fc "task_driver_ws.sh.*claude-$L$" 2>/dev/null); LANELOAD["$L"]=${c:-0}; done
while read -r t; do
  [ -n "$t" ] || continue
  case "$t" in \#*) continue;; esac
  { [ -f "$VERD/$t.PASS" ] || [ -f "$VERD/$t.UNFIXABLE" ]; } && continue
  pidf="$JOBS/$t.wsdriver.pid"
  [ -f "$pidf" ] && kill -0 "$(cat "$pidf" 2>/dev/null)" 2>/dev/null && continue
  [ $(( $(live_drivers) + launched )) -ge "$POOL" ] && break
  [ "$launched" -ge "$MAXLAUNCH" ] && break
  lane=""; min=999999
  for a in "${ACCTS[@]}"; do L="${a##*-}"; c=${LANELOAD["$L"]:-0}; if [ "$c" -lt "$min" ]; then min=$c; lane="$a"; fi; done
  LANELOAD["${lane##*-}"]=$(( ${LANELOAD["${lane##*-}"]:-0} + 1 ))
  ( bash "$Q/task_driver_ws.sh" "$t" "$lane" ) 6>&- &
  echo $! > "$pidf"; launched=$((launched+1))
done < "$FLEET/fleet_tasks.txt"
tickline="$(date -u +%FT%TZ) driverpool_ws launched=$launched live=$(live_drivers) pass=$(ls "$VERD"/*.PASS 2>/dev/null|wc -l) fail=$(ls "$VERD"/*.FAIL 2>/dev/null|wc -l) unfix=$(ls "$VERD"/*.UNFIXABLE 2>/dev/null|wc -l) stall=$(ls "$VERD"/*.REVIEW_STALLED 2>/dev/null|wc -l)"
echo "$tickline" >> "$FLEET/driverpool_ws.log"
echo "$tickline" >> "$FLEET/fleet.log"
