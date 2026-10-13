#!/usr/bin/env bash
# v3digest_pilot.sh [TASK_LIST_FILE]
#
# Dispatches v3digest_review.sh for every task in TASK_LIST_FILE (default:
# /root/qc/_prompts/sev2/tasks23.txt - the exact 22 measured tasks plus the
# control task SVC-PC-2-7-0 the sev2 run used) across BOTH reviewers (opus,
# sonnet), honouring:
#   - lane pool restricted to /root/.claude-h, -m, -o, -q, -r, -s ONLY (this
#     task's own hard rule - NOT sev2_pilot.sh's -b..-l pool, which this
#     measurement must never touch)
#   - /root/qc/lanes/<lane>.benched and .limited_until, checked at pick time
#   - at most 2 calls per lane at a time, at most 8 in flight overall
#   - both reviewers draw from the SAME lane pool (unlike the sev2 pilot,
#     where glm used a separate proxy with no lane contention) - so both
#     reviewers' jobs are dispatched from ONE combined loop that enforces the
#     shared per-lane and overall caps jointly, not two independent pilots
#
# Output: /root/qc/_prompts/v3digest/reviews/<task>.<reviewer>.json (+
# .stats.json sidecar, written by v3digest_review.sh / v3digest_extract_result.py).
# Log: /root/qc/_prompts/v3digest/pilot.log (UTC timestamps, start/finish/failure).
#
# Idempotent: skips a (task, reviewer) pair whose output already exists and
# is canonical.
set -u
cd /root/qc || exit 1

LIST="${1:-/root/qc/_prompts/sev2/tasks23.txt}"
if [ ! -f "$LIST" ]; then
  echo "usage: v3digest_pilot.sh [TASK_LIST_FILE] (default $LIST not found)" >&2
  exit 1
fi

REVIEWERS=(opus sonnet)
# Allowed pool ONLY - never the sev2 pilot's -b..-l pool, never any lane not
# on this exact list (this task's hard rule).
POOL=(/root/.claude-h /root/.claude-m /root/.claude-o /root/.claude-q /root/.claude-r /root/.claude-s)
MAX_PER_LANE=2
MAX_INFLIGHT=8

OUT_DIR=/root/qc/_prompts/v3digest/reviews
LANE_JOBS_DIR=/root/qc/_prompts/v3digest/lane_jobs
LOG=/root/qc/_prompts/v3digest/pilot.log
mkdir -p "$OUT_DIR" "$LANE_JOBS_DIR"
rm -f "$LANE_JOBS_DIR"/*  # stale pidfiles from a previous aborted run would wrongly count toward the per-lane cap

log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }

is_canonical_file() {  # $1 = path; exit 0 if canonical
  python3 -c "
import json, sys
try:
    j = json.load(open('$1'))
except Exception:
    sys.exit(1)
if j.get('overall_verdict') not in ('accept', 'reject', 'invalid', 'needs_revision'):
    sys.exit(1)
checks = j.get('checks')
if not isinstance(checks, list) or not checks:
    sys.exit(1)
for c in checks:
    if not isinstance(c, dict) or c.get('severity') not in ('major', 'minor', 'good'):
        sys.exit(1)
sys.exit(0)
" 2>/dev/null
}

lane_busy_count() {  # $1 = lane path -> prints count of live pidfiles for that lane
  local base; base="$(basename "$1")"
  local n=0 f pid
  for f in "$LANE_JOBS_DIR/$base".*; do
    [ -e "$f" ] || continue
    pid="${f##*.}"
    if kill -0 "$pid" 2>/dev/null; then
      n=$((n + 1))
    else
      rm -f "$f"  # stale pidfile, job already gone
    fi
  done
  echo "$n"
}

I=0
pick_lane() {  # sets global CHOSEN_LANE, honouring benched/limited_until/per-lane cap.
  # Same command-substitution trap as sev2_pilot.sh: never call this as
  # lane="$(pick_lane)" - that forks a subshell and silently discards the
  # I=$((I+1)) round-robin advance for every caller. Call it plain, then read
  # $CHOSEN_LANE.
  CHOSEN_LANE=""
  local sweep
  for sweep in 1 2 3; do
    local k
    for k in $(seq 1 ${#POOL[@]}); do
      local c="${POOL[$(( I % ${#POOL[@]} ))]}"; I=$((I + 1))
      local base; base="$(basename "$c")"
      if [ -f "/root/qc/lanes/${base}.benched" ]; then continue; fi
      local lu="/root/qc/lanes/${base}.limited_until"
      if [ -f "$lu" ] && [ "$(tr -dc 0-9 < "$lu" 2>/dev/null || echo 0)" -gt "$(date +%s)" ] 2>/dev/null; then continue; fi
      if [ "$(lane_busy_count "$c")" -ge "$MAX_PER_LANE" ]; then continue; fi
      CHOSEN_LANE="$c"; return
    done
    sleep 5
  done
  # Last resort after 3 full sweeps with nothing eligible: do NOT silently
  # exceed the per-lane cap. Report and let the main loop keep waiting
  # (CHOSEN_LANE stays empty; caller must re-poll rather than dispatch).
  CHOSEN_LANE=""
}

run_one() {  # task reviewer lane
  local t="$1" rv="$2" lane="$3"
  local out="$OUT_DIR/$t.$rv.json"
  local base; base="$(basename "$lane")"
  local pidfile="$LANE_JOBS_DIR/$base.$$"
  touch "$pidfile"
  log "START $t $rv lane=$base"
  if bash /root/qc/tools/v3digest_review.sh "$t" "$rv" "$lane" "$out" >> "$LOG" 2>&1; then
    log "FINISH $t $rv (canonical)"
  else
    log "FAILED $t $rv (see $out.stats.json)"
  fi
  rm -f "$pidfile"
}

log "V3DIGEST PILOT START list=$LIST tasks=$(grep -c . "$LIST") reviewers=${REVIEWERS[*]} pool=${#POOL[@]} max_per_lane=$MAX_PER_LANE max_inflight=$MAX_INFLIGHT"

# Build the combined (task, reviewer) job list, interleaved per task.
JOBLIST=()
while read -r t; do
  [ -n "$t" ] || continue
  for rv in "${REVIEWERS[@]}"; do
    out="$OUT_DIR/$t.$rv.json"
    if [ -f "$out" ] && is_canonical_file "$out"; then
      log "SKIP $t $rv (already canonical)"
      continue
    fi
    JOBLIST+=("$t $rv")
  done
done < "$LIST"

log "V3DIGEST PILOT: ${#JOBLIST[@]} jobs to run"

for job in "${JOBLIST[@]}"; do
  t="${job%% *}"; rv="${job##* }"
  while [ "$(jobs -rp | wc -l)" -ge "$MAX_INFLIGHT" ]; do sleep 5; done
  pick_lane
  while [ -z "$CHOSEN_LANE" ]; do
    log "WAIT $t $rv (no lane free under per-lane cap $MAX_PER_LANE, retrying)"
    sleep 5
    pick_lane
  done
  run_one "$t" "$rv" "$CHOSEN_LANE" &
  sleep 2
done
wait
log "V3DIGEST PILOT DONE list=$LIST"
