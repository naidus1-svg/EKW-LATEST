#!/usr/bin/env bash
# pipe_batch.sh - HANDOFF.md section 3/4: run gate_task.sh over the full
# queue, detached. Order: main's 14 returned tasks, then every task with a
# pre-gate-v2 zip in out/, then the rest (task_order.py).
#
# Launch:  nohup bash /root/qc/tools/pipe_batch.sh > /root/qc/stream-pipe/PIPE.nohup.log 2>&1 &
# Watch:   watch -n 30 bash /root/qc/tools/pipe_status.sh
#
# ACCOUNT LANES (2026-09-18 16:00Z, laptop session)
#   A lane is a Claude Max login living in its own config dir. Every dir
#   matching /root/.claude or /root/.claude-* that holds .credentials.json
#   is a lane. Lanes are re-detected before EVERY task launch, so adding an
#   account needs no restart:
#       CLAUDE_CONFIG_DIR=/root/.claude-<letter> claude     ->  /login  ->  /exit
#   Use a NEW letter per account. Logging into an existing dir overwrites
#   that account (happened twice on 2026-09-18 with -b).
#   Concurrency = PER_LANE x live, unbenched lanes.
#
# LANE BENCHING
#   When a task fails and its pipeline.log shows a rate-limit / usage-limit
#   message, the lane it ran on is benched for BENCH_MIN minutes (a file in
#   /root/qc/lanes/) and the task is pushed to RETRY.txt. Benched lanes are
#   skipped by refresh_lanes; after BENCH_MIN they return automatically. The
#   Max limit is a rolling 5-hour window per account, so a lane that hit its
#   cap recovers gradually; BENCH_MIN=60 re-probes it hourly. RETRY.txt is
#   drained after the main queue, on whatever lanes are live then. Safe to
#   re-run this whole script at any time: DONE and PARKED tasks exit at once.
set -uo pipefail

TOOLS=/root/qc/tools
PIPE_ROOT=/root/qc/stream-pipe
LANE_ROOT=/root/qc/lanes
QUEUE_FILE="$PIPE_ROOT/QUEUE.txt"
RETRY_FILE="$PIPE_ROOT/RETRY.txt"
PIPE_LOG="$PIPE_ROOT/PIPE.log"
PER_LANE_FILE=/root/qc/lanes/PER_LANE   # edit this file to retune without a restart
PER_LANE=6
BENCH_MIN=180
RATE_RE='rate.?limit|usage limit|hit your limit|too many requests|429|overloaded|out of extra usage|limit reached|resets at|weekly limit|hit your [a-z ]*limit|resets [A-Z][a-z]{2} [0-9]'

mkdir -p "$PIPE_ROOT" "$LANE_ROOT"
: > "$RETRY_FILE"

lane_benched() {  # $1 = lane dir; true if benched within BENCH_MIN
  local f="$LANE_ROOT/$(basename "$1").benched"
  [ -f "$f" ] || return 1
  local age=$(( ($(date +%s) - $(stat -c %Y "$f")) / 60 ))
  if [ "$age" -ge "$BENCH_MIN" ]; then rm -f "$f"; return 1; fi
  return 0
}

refresh_lanes() {
  [ -s "$PER_LANE_FILE" ] && PER_LANE=$(tr -dc 0-9 < "$PER_LANE_FILE") && [ -n "$PER_LANE" ] || PER_LANE=6
  LANES=()
  for d in /root/.claude /root/.claude-*; do
    [ -d "$d" ] && [ -f "$d/.credentials.json" ] || continue
    lane_benched "$d" && continue
    LANES+=("$d")
  done
  [ "${#LANES[@]}" -eq 0 ] && LANES=(/root/.claude)   # never zero; last resort
  CONCURRENCY=$(( PER_LANE * ${#LANES[@]} ))
}

run_one() {
  local task="$1" lane="$2"
  local t0 t1
  t0=$(date -u +%s)
  if pgrep -fa "gate_task.sh" | awk '{print $NF}' | grep -qx "$task"; then
    echo "[$(date -u +%FT%TZ)] SKIP   $task already running under another process" >> "$PIPE_LOG"; return 0
  fi
  echo "[$(date -u +%FT%TZ)] START  $task lane=$lane" >> "$PIPE_LOG"
  if CLAUDE_CONFIG_DIR="$lane" bash "$TOOLS/gate_task.sh" "$task" >> "$PIPE_ROOT/$task/run.out" 2>&1; then
    t1=$(date -u +%s)
    echo "[$(date -u +%FT%TZ)] DONE   $task ($((t1 - t0))s) lane=$lane" >> "$PIPE_LOG"
  else
    t1=$(date -u +%s)
    local reason="failed"
    if [ -f "$PIPE_ROOT/$task/PARKED.md" ]; then
      reason="parked: $(tail -1 "$PIPE_ROOT/$task/PARKED.md")"
    elif tail -40 "$PIPE_ROOT/$task/pipeline.log" 2>/dev/null | grep -qiE "$RATE_RE" \
      || tail -40 "$PIPE_ROOT/$task/run.out" 2>/dev/null | grep -qiE "$RATE_RE"; then
      date -u +%FT%TZ > "$LANE_ROOT/$(basename "$lane").benched"
      echo "$task" >> "$RETRY_FILE"
      reason="rate-limited on $lane, lane benched ${BENCH_MIN}m, task queued for retry"
    else
      echo "$task" >> "$RETRY_FILE"
      reason="failed (queued for one retry)"
    fi
    echo "[$(date -u +%FT%TZ)] STOP   $task ($((t1 - t0))s) lane=$lane - $reason" >> "$PIPE_LOG"
  fi
}

drain_queue() {  # $1 = file of task ids
  local qfile="$1" running=0 i=0 task lane
  refresh_lanes
  LAST_LANE_COUNT=${#LANES[@]}
  while IFS= read -r task; do
    [ -z "$task" ] && continue
    mkdir -p "$PIPE_ROOT/$task"
    refresh_lanes
    if [ "${#LANES[@]}" -ne "$LAST_LANE_COUNT" ]; then
      echo "[$(date -u +%FT%TZ)] LANES  now ${#LANES[@]} (${LANES[*]}), concurrency=$CONCURRENCY" | tee -a "$PIPE_LOG"
      LAST_LANE_COUNT=${#LANES[@]}
    fi
    lane="${LANES[$(( i % ${#LANES[@]} ))]}"
    i=$((i + 1))
    run_one "$task" "$lane" &
    running=$((running + 1))
    if [ "$running" -ge "$CONCURRENCY" ]; then
      wait -n || true
      running=$((running - 1))
    fi
  done < "$qfile"
  wait
}

python3 "$TOOLS/task_order.py" --out "$QUEUE_FILE"
n_tasks=$(wc -l < "$QUEUE_FILE")
refresh_lanes
echo "[$(date -u +%FT%TZ)] pipe_batch.sh: queue built, $n_tasks tasks, lanes=${#LANES[@]} (${LANES[*]}), concurrency=$CONCURRENCY, per_lane=$PER_LANE" | tee -a "$PIPE_LOG"

drain_queue "$QUEUE_FILE"

if [ -s "$RETRY_FILE" ]; then
  n_retry=$(sort -u "$RETRY_FILE" | wc -l)
  sort -u "$RETRY_FILE" > "$RETRY_FILE.run"
  : > "$RETRY_FILE"
  echo "[$(date -u +%FT%TZ)] pipe_batch.sh: retry pass, $n_retry tasks" | tee -a "$PIPE_LOG"
  drain_queue "$RETRY_FILE.run"
fi

echo "[$(date -u +%FT%TZ)] pipe_batch.sh: queue drained, $n_tasks tasks attempted, $(sort -u "$RETRY_FILE" | wc -l) still failing (see RETRY.txt)" | tee -a "$PIPE_LOG"
