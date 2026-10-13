#!/bin/bash
# Atomically claim the next unclaimed EKW task for a lane (same rule as svc_v7_pool.sh claim_next: first queue
# line whose $WORK/claims/<task> dir does not exist; mkdir is the lock). Prints the task id and exits 0, or exits 1
# when nothing is claimable. Subcommands:
#   ekw_v1_claim.sh            claim next            ekw_v1_claim.sh left     count claimable tasks
# Tasks listed in $WORK/do_not_touch.txt (first tab field) are skipped.
# The runner (ekw_v1_lane_runner.sh) releases its own claim on exits 10 and 30; exits 0 and 20 keep it.
set -uo pipefail
WORK="${EKW_WORK:-/root/qc/_ekw}"; QUEUE="$WORK/queue.txt"
mkdir -p "$WORK/claims"
[ -f "$QUEUE" ] || { [ "${1:-}" = left ] && echo 0; exit 1; }
n=0
while read -r t; do
  t="$(printf '%s' "$t" | tr -d '\r' | tr -d '[:space:]')"; [ -z "$t" ] && continue
  case "$t" in \#*) continue;; esac
  # already submitted by someone else (consolidated EKW tab): never claim, same list the bundler refuses
  [ -f "$WORK/do_not_touch.txt" ] && grep -qx "$t" <(tr -d '\r' < "$WORK/do_not_touch.txt" | cut -f1) && continue
  if [ "${1:-}" = left ]; then [ -d "$WORK/claims/$t" ] || n=$((n+1)); continue; fi
  if mkdir "$WORK/claims/$t" 2>/dev/null; then echo "$t"; exit 0; fi
done < "$QUEUE"
[ "${1:-}" = left ] && { echo "$n"; exit 0; }
exit 1
