#!/usr/bin/env bash
# fleet.sh - re-entrant severity-gate supervisor. Run every minute via cron+flock:
#   * * * * * flock -n /run/fleet.lock bash /root/qc/fleet.sh >> /root/qc/fleet/fleet.cron.out 2>&1
# For every task in fleet/all_tasks.txt that has a digest and no final verdict, it keeps that task's
# four review calls (opus x2, sonnet x2) progressing up to a global concurrency cap, then writes a
# PASS/FAIL verdict. Pure bash, zero LLM tokens. Idempotent and self-healing: a dead call re-launches
# on the next tick, a hiccup or reboot resumes from the markers on disk, so nothing stalls for hours.
set -u
cd /root/qc || exit 1
# Own singleton lock on a dedicated fd; children close fd 9 (9>&-) so the lock releases the moment
# this tick returns, not when the launched review calls finish. Run from cron WITHOUT external flock.
exec 9>/run/fleet_int.lock
flock -n 9 || exit 0
HERE=/root/qc/_prompts/gate-revalidate
TOOLS=/root/qc/tools
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
FLEET=/root/qc/fleet
REVIEWS=$FLEET/reviews
DIGESTS=$HERE/digests
VERD=$FLEET/verdicts
JOBS=$FLEET/jobs
MAXCONC=52
mkdir -p "$REVIEWS" "$VERD" "$JOBS" "$FLEET/ready" "$HERE/logs" "$HERE/detfindings"
echo "$(date +%s)" > "$FLEET/fleet.heartbeat"
[ -f "$FLEET/fleet_tasks.txt" ] || { echo "$(date -u +%FT%TZ) no fleet_tasks.txt" >> "$FLEET/fleet.log"; exit 0; }

lane_free(){ local b=".claude-$1"; [ -f "/root/qc/lanes/$b.benched" ] && return 1; local lu="/root/qc/lanes/$b.limited_until"; if [ -f "$lu" ]; then local ts; ts=$(tr -dc 0-9 <"$lu" 2>/dev/null); ts=${ts:-0}; [ "$ts" -gt "$(date +%s)" ] 2>/dev/null && return 1; fi; return 0; }
ACCTS=(); for L in q r m v w b c d e f g i j k l n p t u; do lane_free "$L" && ACCTS+=("/root/.claude-$L"); done
[ "${#ACCTS[@]}" -ge 4 ] || { echo "$(date -u +%FT%TZ) too few lanes ${#ACCTS[@]}" >> "$FLEET/fleet.log"; exit 0; }

is_canonical(){ [ -f "$1" ] && python3 -c "import json,sys
try: j=json.load(open('$1'))
except Exception: sys.exit(1)
sys.exit(0 if j.get('overall_verdict') in ('accept','reject','invalid','needs_revision') and isinstance(j.get('checks'),list) and j['checks'] and isinstance(j.get('major_count'),int) else 1)" 2>/dev/null; }
live_total(){ local n; n=$(pgrep -fc gate_review_cold.sh 2>/dev/null); echo "${n:-0}"; }

launched=0; k=0
while read -r t; do
  [ -n "$t" ] || continue
  case "$t" in \#*) continue;; esac
  { [ -f "$VERD/$t.PASS" ] || [ -f "$VERD/$t.FAIL" ]; } && continue
  [ -f "$DIGESTS/$t.md" ] || continue
  [ -f "$HERE/detfindings/$t.md" ] || python3 "$TOOLS/gate_detfindings.py" "$t" "$CORPUS/$t" "$HERE/detfindings/$t.md" >/dev/null 2>&1
  done_calls=0
  for rr in opus.run1 opus.run2 sonnet.run1 sonnet.run2; do
    r="${rr%%.*}"; run="${rr#*.run}"; out="$REVIEWS/$t.$rr.json"
    if is_canonical "$out"; then done_calls=$((done_calls+1)); continue; fi
    pidf="$JOBS/$t.$rr.pid"
    if [ -f "$pidf" ] && kill -0 "$(cat "$pidf" 2>/dev/null)" 2>/dev/null; then continue; fi
    [ $(( $(live_total) + launched )) -ge "$MAXCONC" ] && continue
    lane="${ACCTS[$(( k % ${#ACCTS[@]} ))]}"; k=$((k+1))
    ( bash "$TOOLS/gate_review_cold.sh" "$t" "$r" "$lane" "$out" >"$HERE/logs/$t.$rr.log" 2>&1 ) 9>&- &
    echo $! > "$pidf"; launched=$((launched+1))
  done
  if [ "$done_calls" -eq 4 ]; then
    why=""
    python3 "$TOOLS/judge_schema_bytes.py" "$CORPUS/$t" --block 4000 --warn 3500 >/dev/null 2>&1 || why="schema"
    for rr in opus.run1 opus.run2 sonnet.run1 sonnet.run2; do
      mc=$(python3 -c "import json;print(json.load(open('$REVIEWS/$t.$rr.json')).get('major_count',0))" 2>/dev/null || echo 0)
      [ "${mc:-0}" -ge 1 ] 2>/dev/null && why="$why major:$rr"
    done
    if echo "$why" | grep -q "major\|schema"; then echo "$why" > "$VERD/$t.FAIL"; else echo pass > "$VERD/$t.PASS"; fi
  fi
done < "$FLEET/fleet_tasks.txt"
echo "$(date -u +%FT%TZ) tick launched=$launched live=$(live_total) pass=$(ls "$VERD"/*.PASS 2>/dev/null|wc -l) fail=$(ls "$VERD"/*.FAIL 2>/dev/null|wc -l) digests=$(ls "$DIGESTS"/*.md 2>/dev/null|wc -l)" >> "$FLEET/fleet.log"
