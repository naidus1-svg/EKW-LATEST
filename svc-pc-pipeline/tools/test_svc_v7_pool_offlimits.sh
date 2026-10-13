#!/bin/bash
# Tests claim_next / claimable_left in svc_v7_pool.sh skip tasks on _v7/do_not_touch.txt (CRLF-safe) and comment
# lines, so a lane never claims a task someone else owns or already submitted. Run on the sandbox.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
export POOL_QC="$T" POOL_EKW_WORK="$T/_ekw" POOL_SOURCE_ONLY=1
W="$T/_v7"; mkdir -p "$W/claims"
printf '# header\nSVC-PC-1-1-0\nSVC-PC-2-2-0\r\nSVC-PC-3-3-0\n' > "$W/queue.txt"
printf 'SVC-PC-1-1-0\r\nSVC-PC-2-2-0\n' > "$W/do_not_touch.txt"
# shellcheck disable=SC1091
source "$HERE/svc_v7_pool.sh" >/dev/null 2>&1
fail=0
n="$(claimable_left)"; [ "$n" = 1 ] && echo "ok   claimable_left=1" || { echo "FAIL claimable_left=$n (want 1)"; fail=1; }
t="$(claim_next)"; [ "$t" = SVC-PC-3-3-0 ] && echo "ok   claimed $t" || { echo "FAIL claimed '$t' (want SVC-PC-3-3-0)"; fail=1; }
[ -d "$W/claims/SVC-PC-1-1-0" ] && { echo "FAIL claimed an off-limits task"; fail=1; } || echo "ok   off-limits task not claimed"
t="$(claim_next)"; [ -z "$t" ] && echo "ok   nothing else claimable" || { echo "FAIL claimed '$t'"; fail=1; }
rm -f "$W/do_not_touch.txt"; rm -rf "$W/claims"/*
t="$(claim_next)"; [ "$t" = SVC-PC-1-1-0 ] && echo "ok   no list -> first task" || { echo "FAIL no-list claimed '$t'"; fail=1; }
[ "$fail" = 0 ] && echo "5/5 PASS" || { echo FAILED; exit 1; }
