#!/bin/bash
# Behaviour test for the 2026-09-24 release rules in svc_v7_pool.sh (stub runner, fake lane T, temp dir only):
#   A. runner exit 30 (auto-decide) releases the claim and the task runs again
#   B. runner exit 10 (lane limit) three times in a row never parks the task
# Usage: bash test_svc_v7_pool_release.sh /path/to/svc_v7_pool.sh
set -u
POOL="${1:?path to svc_v7_pool.sh}"
T=$(mktemp -d); trap 'touch "$T/_v7/POOL_STOP"; sleep 1; rm -rf "$T"' EXIT
mkdir -p "$T/_v7" "$T/bin"
printf '#!/bin/bash\necho OK\n' > "$T/bin/claude"; chmod +x "$T/bin/claude"
# Stub runner: task A exits 30 on its first run, 0 after; task B exits 10 on its first 3 runs, 0 after.
printf '%s\n' '#!/bin/bash' \
  'd="$(dirname "$0")"; n=$(( $(cat "$d/count_$1" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$d/count_$1"' \
  'echo "run $1 $n" >> "$d/runs.log"; sleep 1' \
  'case "$1" in' \
  '  TASK-A) [ "$n" -eq 1 ] && exit 30; exit 0;;' \
  '  TASK-B) [ "$n" -le 3 ] && exit 10; exit 0;;' \
  'esac' > "$T/svc_v7_lane_runner.sh"
printf 'TASK-A\nTASK-B\n' > "$T/_v7/queue.txt"
fail=0
PATH="$T/bin:$PATH" POOL_QC="$T" POOL_IDLE_POLL=2 bash "$POOL" "T" > "$T/pool.out" 2>&1 &
for i in $(seq 1 60); do
  a=$(cat "$T/count_TASK-A" 2>/dev/null || echo 0); b=$(cat "$T/count_TASK-B" 2>/dev/null || echo 0)
  [ "$a" -ge 2 ] && [ "$b" -ge 4 ] && break; sleep 1
done
a=$(cat "$T/count_TASK-A" 2>/dev/null || echo 0); b=$(cat "$T/count_TASK-B" 2>/dev/null || echo 0)
if [ "$a" -ge 2 ] && grep -q "AUTO-DECIDE on TASK-A" "$T/_v7/pool.log"; then echo "PASS A auto-decide released and re-ran (runs=$a)"; else echo "FAIL A (runs=$a)"; fail=1; fi
if [ "$b" -ge 4 ] && ! grep -q "TASK-B" "$T/_v7/parked.txt" 2>/dev/null; then echo "PASS B lane limit x3 never parked (runs=$b)"; else echo "FAIL B (runs=$b)"; fail=1; fi
touch "$T/_v7/POOL_STOP"; sleep 3
[ "$fail" = 0 ] && echo "ALL PASS"; exit "$fail"
