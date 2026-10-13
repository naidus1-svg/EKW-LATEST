#!/usr/bin/env bash
# rereview_pair.sh [--go] TASK ROUND
# Re-run BOTH reviewers at ROUND through the dispatcher's own run_review_round, whether or not a file exists at that round.
# Why (2026-09-19 23:30Z): rereview_stuck.sh only replaces a file that exists and is not canonical. A task whose round>=2 pair was
# archived (a guard re-open, or by hand) and whose fix moved bytes after its round-1 pair has no re-review path at all: the zip loop
# says "bytes differ from what the reviewers read" for good and the dispatcher re-reviews only after its own fix rounds
# (17-2-0: pair 20:29/20:38Z, last fix 20:39Z). Same per-task lock, same lane choice, same canon check as the dispatcher.
# Dry run unless --go. Output: _prompts/fix_from_reviews.log (the dispatcher's log) plus stdout.
set -u
cd /root/qc || exit 1
go=0
[ "${1:-}" = "--go" ] && { go=1; shift; }
task="${1:?TASK}"
n="${2:?ROUND}"
pipe="/root/qc/stream-pipe/$task"
[ -d "$pipe" ] || { echo "no such task dir $pipe"; exit 2; }
SRC=/root/qc/tools/fix_from_reviews.sh
N=$(grep -n '^while true; do$' "$SRC" | tail -1 | cut -d: -f1)
# shellcheck disable=SC1090
source <(head -n $((N - 1)) "$SRC" | grep -v '^log "FIX-FROM-REVIEWS START')
exec 8>"$pipe/fix_from_reviews.lock"
if ! flock -n 8; then echo "$task: fix lock held, not now"; exit 3; fi
pids=()
for reviewer in glm sonnet; do
  lane=$(alt_lane_for "$task" "$reviewer" "pair${n}")
  if [ "$go" = 1 ]; then
    log "REREVIEW-PAIR START $task $reviewer round$n on $(basename "$lane")"
    (
      run_review_round "$task" "$reviewer" "$lane" "$pipe" "$n"
      if canon_ok "$pipe/CR.$reviewer.round${n}.json"; then log "REREVIEW-PAIR DONE $task $reviewer round$n: canonical"
      else log "REREVIEW-PAIR FAILED $task $reviewer round$n: not canonical"; fi
    ) &
    pids+=($!)
  else
    echo "$task $reviewer round$n: WOULD run on $(basename "$lane")"
  fi
done
[ "${#pids[@]}" -gt 0 ] && wait "${pids[@]}"
exit 0
