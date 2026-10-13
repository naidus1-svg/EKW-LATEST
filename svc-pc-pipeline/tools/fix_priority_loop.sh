#!/usr/bin/env bash
# fix_priority_loop.sh - a second, priority-only scan loop for the fix dispatcher.
#
# fix_from_reviews.sh reads lanes/FIX_FROM_REVIEWS_PRIORITY only at the start of each full pass, and a pass now takes about
# 90 minutes, so a task that guard_rt.py re-opens waits out the whole sweep (its own comment promises pickup within ~60 s).
# This loop sources that script's functions from the live file at start (its main loop cut off, so it never runs a sweep) and
# scans only the priority list every SCAN_INTERVAL seconds with its own small concurrency. process_task and
# process_round2_entry take the same per-task flock as the main instance, so the two cannot fix one task twice.
# Log lines go to the same _prompts/fix_from_reviews.log. Restart it after fix_from_reviews.sh's functions change.
FIX_FROM_REVIEWS_CONC="${FIX_FROM_REVIEWS_CONC:-12}"
export FIX_FROM_REVIEWS_CONC
SRC=/root/qc/tools/fix_from_reviews.sh
N=$(grep -n '^while true; do$' "$SRC" | tail -1 | cut -d: -f1)
[ -n "$N" ] || { echo "fix_priority_loop: no main loop found in $SRC" >&2; exit 1; }
# The dropped line is the main script's own "FIX-FROM-REVIEWS START pid=" log line: guard_rt.py takes the newest such line in the log
# as the dispatcher's pid, so this loop must not write one or a dead dispatcher would look alive.
# shellcheck disable=SC1090
source <(head -n $((N - 1)) "$SRC" | grep -v '^log "FIX-FROM-REVIEWS START')
log "FIX-PRIORITY-LOOP START pid=$$ conc=$CONC (sourced $((N - 1)) lines of $SRC)"
while true; do
  if [ -f "$PRIORITY_FILE" ]; then
    while IFS= read -r ptask; do
      ptask="${ptask%%#*}"
      ptask="$(echo "$ptask" | tr -d '[:space:]')"
      [ -n "$ptask" ] || continue
      [ -d "$PIPE_ROOT/$ptask" ] && scan_one_task "$PIPE_ROOT/$ptask/"
    done < "$PRIORITY_FILE"
  fi
  sleep "$SCAN_INTERVAL"
done
