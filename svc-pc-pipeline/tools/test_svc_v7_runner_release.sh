#!/bin/bash
# Behaviour test for the 2026-09-24 runner exits in svc_v7_lane_runner.sh (temp dir only, no model calls):
#   A. transient() releases the task's own claim and exits 10
#   B. deferred() in normal mode adds the task to decide.txt, releases the claim, exits 30
#   C. deferred() in decide mode parks (parked.txt line, exit 20)
# It extracts the helper functions from the runner so the test exercises the real definitions.
# Usage: bash test_svc_v7_runner_release.sh /path/to/svc_v7_lane_runner.sh
set -u
R="${1:?path to svc_v7_lane_runner.sh}"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
sed -n '/^log(){/p; /^parked(){/p; /^release_claim(){/p; /^transient(){/p; /^deferred(){/,/^}/p' "$R" > "$T/fns.sh"
fail=0
run(){  # $1 = IS_DECIDE, $2 = function call
  mkdir -p "$T/w/claims/TASK-X"; : > "$T/w/decide.txt"; : > "$T/w/parked.txt"
  ( WORK="$T/w"; TASK=TASK-X; LANE=t; LOG="$T/log"; IS_DECIDE="$1"; . "$T/fns.sh"; eval "$2" ) >/dev/null 2>&1
}
run 0 'transient "lane capped"'; rc=$?
if [ "$rc" = 10 ] && [ ! -d "$T/w/claims/TASK-X" ]; then echo "PASS A transient released its claim (rc=10)"; else echo "FAIL A rc=$rc"; fail=1; fi
run 0 'deferred "attempt cap: test"'; rc=$?
if [ "$rc" = 30 ] && [ ! -d "$T/w/claims/TASK-X" ] && grep -qx TASK-X "$T/w/decide.txt"; then echo "PASS B cap in normal mode -> decide (rc=30)"; else echo "FAIL B rc=$rc"; fail=1; fi
run 1 'deferred "attempt cap: test"'; rc=$?
if [ "$rc" = 20 ] && grep -q "^TASK-X" "$T/w/parked.txt"; then echo "PASS C cap in decide mode parks (rc=20)"; else echo "FAIL C rc=$rc"; fail=1; fi
[ "$fail" = 0 ] && echo "ALL PASS"; exit "$fail"
