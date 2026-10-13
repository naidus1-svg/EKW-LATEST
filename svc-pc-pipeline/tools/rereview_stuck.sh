#!/usr/bin/env bash
# rereview_stuck.sh [--go] TASK:REVIEWER:ROUND ...
#
# A reviewer verdict can land under its canonical file name in a shape canon_ok() rejects (checks as an object, a verdict with no checks,
# a one-key wrapper, a per-criterion map) after run_review_round's own two attempts. Nothing re-runs it: scan_one_task requeues only
# round-0 files, normalize_reviews.py cannot invent severities, and the actuator (rc=7, "not a complete Comprehensive Review verdict")
# refuses the file, so the task sits at "one reviewer done" for hours (2026-09-19: 8-4-0, 12-7-0, 21-0-0, 25-1-0, 3-1-0, 73-0-0, 26-2-0).
#
# This calls the dispatcher's own run_review_round again for each TASK:REVIEWER:ROUND: same per-task lock, same run_workspace_review.py
# call, same canon check with one retry on another lane. The old file stays in place until a new one is written over it, so nothing reads a
# missing verdict meanwhile. A triple is skipped when its file is already canonical, when a review of that task and reviewer is running,
# or when another fix job holds the task lock. Dry run unless --go. Output goes to _prompts/fix_from_reviews.log (the dispatcher's log).
cd /root/qc || exit 1
GO=0
if [ "$1" = "--go" ]; then
  GO=1
  shift
fi
[ "$#" -gt 0 ] || { echo "usage: rereview_stuck.sh [--go] TASK:REVIEWER:ROUND ..." >&2; exit 1; }
SRC=/root/qc/tools/fix_from_reviews.sh
N=$(grep -n '^while true; do$' "$SRC" | tail -1 | cut -d: -f1)
[ -n "$N" ] || { echo "rereview_stuck: no main loop found in $SRC" >&2; exit 1; }
# shellcheck disable=SC1090
source <(head -n $((N - 1)) "$SRC" | grep -v '^log "FIX-FROM-REVIEWS START')

one() {
  local task="$1" reviewer="$2" n="$3"
  local pipe="$PIPE_ROOT/$task"
  local out="$pipe/CR.$reviewer.round${n}.json"
  [ -d "$pipe" ] || { echo "$task: no such task dir"; return; }
  [ -f "$out" ] || { echo "$task $reviewer round$n: no such file, skipped"; return; }
  if canon_ok "$out"; then
    echo "$task $reviewer round$n: already canonical, skipped"
    return
  fi
  if pgrep -f "[r]un_workspace_review.py --task $task .*--reviewer $reviewer" > /dev/null; then
    echo "$task $reviewer round$n: a review is running, skipped"
    return
  fi
  exec 8> "$pipe/fix_from_reviews.lock"
  if ! flock -n 8; then
    echo "$task $reviewer round$n: another fix job holds the task lock, skipped"
    return
  fi
  local lane
  lane=$(alt_lane_for "$task" "$reviewer" "stuck${n}")
  if [ "$GO" != "1" ]; then
    echo "$task $reviewer round$n: WOULD re-run on $(basename "$lane") (latest file not canon-shaped, $(stat -c %s "$out") bytes)"
    return
  fi
  log "REREVIEW-STUCK START $task $reviewer round$n on $(basename "$lane") (latest file not canon-shaped, kept in place until a new one lands)"
  run_review_round "$task" "$reviewer" "$lane" "$pipe" "$n"
  if canon_ok "$out"; then
    log "REREVIEW-STUCK DONE $task $reviewer round$n: canonical"
  else
    log "REREVIEW-STUCK DONE $task $reviewer round$n: still NOT canonical after two more attempts"
  fi
}

for triple in "$@"; do
  IFS=: read -r t r n <<< "$triple"
  case "$t" in SVC-PC-*) ;; *) t="SVC-PC-$t" ;; esac
  while [ "$(jobs -rp | wc -l)" -ge 4 ]; do sleep 5; done
  ( one "$t" "$r" "$n" ) &
  sleep 1
done
wait
