#!/bin/bash
# Tests reap_orphans in svc_v7_pool.sh: an orphan claim (no runner, older than REAP_AGE, last log TRANSIENT) is
# released; a PARKED claim, a fresh claim and a claim with a live runner are kept. Run on the sandbox (needs pgrep).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"; trap 'kill $SLEEPER 2>/dev/null; rm -rf "$T"' EXIT
export POOL_QC="$T" POOL_EKW_WORK="$T/_ekw" POOL_REAP_AGE=60 POOL_SOURCE_ONLY=1
W="$T/_v7"; mkdir -p "$W/claims" "$W/logs"
old(){ touch -d '-2 hours' "$W/claims/$1"; }
mk(){ mkdir -p "$W/claims/$1"; printf '%s\n' "$2" > "$W/logs/$1.log"; }
mk SVC-PC-1-1-0 "2026-09-25T01:00:00Z SVC-PC-1-1-0[g] TRANSIENT usage limit hit during the oracle"; old SVC-PC-1-1-0
mk SVC-PC-2-2-0 "2026-09-25T01:00:00Z SVC-PC-2-2-0[g] PARKED golden stuck"; old SVC-PC-2-2-0
mk SVC-PC-3-3-0 "2026-09-25T01:00:00Z SVC-PC-3-3-0[g] TRANSIENT usage limit"            # fresh claim
mk SVC-PC-4-4-0 "2026-09-25T01:00:00Z SVC-PC-4-4-0[g] TRANSIENT usage limit"; old SVC-PC-4-4-0
# a live runner for 4-4-0: a process whose command line matches "svc_v7_lane_runner.sh SVC-PC-4-4-0 "
bash -c "exec -a 'bash svc_v7_lane_runner.sh SVC-PC-4-4-0 q' sleep 30" & SLEEPER=$!
sleep 1
# shellcheck disable=SC1091
source "$HERE/svc_v7_pool.sh" >/dev/null 2>&1
plog(){ :; }
reap_orphans "$W" svc_v7_lane_runner.sh
fail=0
chk(){ if [ "$2" = gone ] && [ -d "$W/claims/$1" ]; then echo "FAIL $1 should be reaped"; fail=1
       elif [ "$2" = kept ] && [ ! -d "$W/claims/$1" ]; then echo "FAIL $1 should be kept"; fail=1
       else echo "ok   $1 $2"; fi; }
chk SVC-PC-1-1-0 gone
chk SVC-PC-2-2-0 kept
chk SVC-PC-3-3-0 kept
chk SVC-PC-4-4-0 kept
[ "$fail" = 0 ] && echo "4/4 PASS" || { echo "FAILED"; exit 1; }
