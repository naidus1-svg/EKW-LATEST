#!/usr/bin/env bash
# throughput_watch.sh - low-token (pure bash, zero LLM) health + THROUGHPUT watchdog. Run every 5 min:
#   */5 * * * * bash /root/qc/throughput_watch.sh >> /root/qc/fleet/watch.cron.out 2>&1
# Writes fleet/HEALTH.txt (OK or a loud ALERT with reasons) which the phone dashboard prints at the TOP,
# so a stall becomes visible on a glance instead of silent. Also does two SAFE self-heals. It cannot fix
# a novel code bug - it makes the stall loud so a human acts; that is the honest limit of unattended ops.
set -u
cd /root/qc || exit 1
FLEET=/root/qc/fleet; VERD=$FLEET/verdicts
now=$(date +%s)
# pgrep -fc prints "0" AND exits nonzero on no match; a bare `|| echo 0` then yields "0\n0" and breaks
# every $(( )) using it. Capture into a var (ignoring exit) and default empty -> always one clean int.
pcount(){ local n; n=$(pgrep -fc "$1" 2>/dev/null); echo "${n:-0}"; }
pass=$(ls "$VERD"/*.PASS 2>/dev/null | wc -l)
unfix=$(ls "$VERD"/*.UNFIXABLE 2>/dev/null | wc -l)
finished=$(( pass + unfix ))
total=$(grep -cve '^#' -e '^$' "$FLEET/fleet_tasks.txt" 2>/dev/null || echo 202)
undone=$(( total - finished ))
load1=$(cut -d' ' -f1 /proc/loadavg 2>/dev/null | cut -d. -f1); load1=${load1:-0}
cores=$(nproc 2>/dev/null || echo 32)
hb=$(cat "$FLEET/driverpool.heartbeat" 2>/dev/null || echo 0); hbage=$(( now - hb ))
drivers=$(( $(pcount task_driver_ws.sh) + $(pcount task_driver.sh) ))

# SAFE self-heal 1: drop stale pid files whose process is dead, so the pool can relaunch that task.
for p in "$FLEET/jobs"/*.pid; do
  [ -e "$p" ] || continue
  pid=$(cat "$p" 2>/dev/null)
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null || rm -f "$p"
done
# SAFE self-heal 2: kill a driver stuck far past any legitimate runtime (3 reviews + 2 fixes < ~3h), so
# a wedged process cannot hold a task forever. The pool then relaunches it fresh.
for d in $(pgrep -f "task_driver_ws.sh|task_driver.sh" 2>/dev/null); do
  et=$(ps -o etimes= -p "$d" 2>/dev/null | tr -d ' '); et=${et:-0}
  [ "$et" -gt 11000 ] 2>/dev/null && kill -9 "$d" 2>/dev/null
done

# THROUGHPUT snapshot: (ts finished). Evaluate a stall only against a snapshot >=45 min old, then roll.
# Track PASS (real shippable output), not finished, so tasks churning to UNFIXABLE cannot hide a stall
# of actual passes. Window 75 min: a workspace task legitimately takes ~1-2h, so a shorter window would
# false-alarm; 75 min with several tasks in flight still catches a real wedge (tonight PASS sat for hours).
snap="$FLEET/.throughput_snap"
prev_ts=0; prev_pass=0
[ -f "$snap" ] && read -r prev_ts prev_pass < "$snap" 2>/dev/null
prev_ts=${prev_ts:-0}; prev_pass=${prev_pass:-0}
stall=""
if [ "$prev_ts" -gt 0 ] && [ $(( now - prev_ts )) -ge 4500 ]; then
  [ "$pass" -le "$prev_pass" ] && [ "$undone" -gt 0 ] && stall="THROUGHPUT STALL: PASS stuck at $pass for $(( (now-prev_ts)/60 ))min with $undone tasks left"
  echo "$now $pass" > "$snap"     # roll the window
elif [ "$prev_ts" -eq 0 ]; then
  echo "$now $pass" > "$snap"      # first run
fi

alerts=()
[ "$hbage" -gt 180 ] && alerts+=("pool heartbeat STALE ${hbage}s - the driver_pool cron is not ticking")
{ [ "$drivers" -eq 0 ] && [ "$undone" -gt 0 ] && [ "$load1" -lt $(( cores*3/2 )) ]; } && alerts+=("0 drivers with $undone tasks left and load only $load1 - pool not launching")
[ "$load1" -ge $(( cores*2 )) ] && alerts+=("load $load1 >= 2x cores - overload")
[ -n "$stall" ] && alerts+=("$stall")

ts=$(date -u +%FT%TZ)
if [ "${#alerts[@]}" -eq 0 ]; then
  printf '%s  HEALTH OK   finished=%s/%s  undone=%s  drivers=%s  load=%s\n' "$ts" "$finished" "$total" "$undone" "$drivers" "$load1" > "$FLEET/HEALTH.txt"
else
  { printf '%s  *** HEALTH ALERT ***   finished=%s/%s  undone=%s  drivers=%s  load=%s\n' "$ts" "$finished" "$total" "$undone" "$drivers" "$load1"
    printf '   !! %s\n' "${alerts[@]}"; } > "$FLEET/HEALTH.txt"
fi
