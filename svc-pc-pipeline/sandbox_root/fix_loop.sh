#!/usr/bin/env bash
# fix_loop.sh - re-entrant Opus fixer supervisor for gate FAILs. Run from cron every 3 min:
#   */3 * * * * bash /root/qc/fix_loop.sh >> /root/qc/fleet/fixloop.cron.out 2>&1
# For each verdicts/*.FAIL task under MAXATT attempts and not already being fixed, launch fix_one.sh on
# a free lane, capped at MAXFIXERS concurrent (Opus fixers are heavy). After MAXATT attempts still
# failing, mark <task>.UNFIXABLE and move on. Safe: a bad fix just re-fails the gate and never ships.
set -u
cd /root/qc || exit 1
exec 7>/run/fixloop_int.lock
flock -n 7 || exit 0
Q=/root/qc; FLEET=$Q/fleet; VERD=$FLEET/verdicts; ATT=$FLEET/fix_attempts
mkdir -p "$ATT" "$FLEET/jobs" "$FLEET/fixlogs"
MAXATT=2
MAXFIXERS=16
echo "$(date +%s)" > "$FLEET/fixloop.heartbeat"
lane_free(){ local b=".claude-$1"; [ -f "/root/qc/lanes/$b.benched" ] && return 1; local lu="/root/qc/lanes/$b.limited_until"; if [ -f "$lu" ]; then local ts; ts=$(tr -dc 0-9 <"$lu" 2>/dev/null); ts=${ts:-0}; [ "$ts" -gt "$(date +%s)" ] 2>/dev/null && return 1; fi; return 0; }
ACCTS=(); for L in q r m v w b c d e f g i j k l p t u; do lane_free "$L" && ACCTS+=("/root/.claude-$L"); done
[ "${#ACCTS[@]}" -ge 2 ] || { echo "$(date -u +%FT%TZ) fixloop: too few lanes" >> "$FLEET/fixloop.log"; exit 0; }
live_fixers(){ local n; n=$(pgrep -fc fix_one.sh 2>/dev/null); echo "${n:-0}"; }
k=0; launched=0
for f in "$VERD"/*.FAIL; do
  [ -e "$f" ] || continue
  t=$(basename "$f" .FAIL)
  a=$(cat "$ATT/$t" 2>/dev/null || echo 0)
  if [ "$a" -ge "$MAXATT" ]; then cp "$f" "$VERD/$t.UNFIXABLE" 2>/dev/null; rm -f "$f"; continue; fi
  pidf="$FLEET/jobs/$t.fix.pid"
  [ -f "$pidf" ] && kill -0 "$(cat "$pidf" 2>/dev/null)" 2>/dev/null && continue
  [ $(( $(live_fixers) + launched )) -ge "$MAXFIXERS" ] && continue
  lane="${ACCTS[$(( k % ${#ACCTS[@]} ))]}"; k=$((k+1))
  ( bash /root/qc/fix_one.sh "$t" "$lane" ) 7>&- &
  echo $! > "$pidf"; launched=$((launched+1))
done
echo "$(date -u +%FT%TZ) fixloop launched=$launched live_fixers=$(live_fixers) fails=$(ls "$VERD"/*.FAIL 2>/dev/null|wc -l) unfixable=$(ls "$VERD"/*.UNFIXABLE 2>/dev/null|wc -l) pass=$(ls "$VERD"/*.PASS 2>/dev/null|wc -l)" >> "$FLEET/fixloop.log"
