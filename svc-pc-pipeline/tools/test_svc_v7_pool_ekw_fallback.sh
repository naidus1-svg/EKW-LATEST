#!/bin/bash
# Behaviour test for the 2026-09-25 EKW fallback in svc_v7_pool.sh (stubs, fake lane T, temp dir only):
#   A. an SVC task in queue.txt is claimed before any EKW task
#   B. once the SVC queue is empty, the lane claims and runs the EKW task with the EKW runner
# Usage: bash test_svc_v7_pool_ekw_fallback.sh /path/to/svc_v7_pool.sh
set -u
POOL="${1:?path to svc_v7_pool.sh}"
T=$(mktemp -d); trap 'touch "$T/_v7/POOL_STOP"; sleep 1; rm -rf "$T"' EXIT
mkdir -p "$T/_v7" "$T/bin" "$T/_ekw/claims"
printf '#!/bin/bash\necho OK\n' > "$T/bin/claude"; chmod +x "$T/bin/claude"
printf '%s\n' '#!/bin/bash' 'echo "svc $1 $(date +%s%N)" >> "$(dirname "$0")/runs.log"; sleep 1; exit 0' > "$T/svc_v7_lane_runner.sh"
printf '%s\n' '#!/bin/bash' 'echo "ekw $1 $(date +%s%N)" >> "$(dirname "$0")/runs.log"; sleep 1; exit 0' > "$T/ekw_runner.sh"
printf '%s\n' '#!/bin/bash' 'while read -r t; do [ -z "$t" ] && continue; mkdir "$EKW_WORK/claims/$t" 2>/dev/null && { echo "$t"; exit 0; }; done < "$EKW_WORK/queue.txt"; exit 1' > "$T/ekw_claim.sh"
printf 'SVC-PC-1-1-0\n' > "$T/_v7/queue.txt"
printf 'LGL-999\n' > "$T/_ekw/queue.txt"
PATH="$T/bin:$PATH" POOL_QC="$T" POOL_IDLE_POLL=2 POOL_EKW_WORK="$T/_ekw" POOL_EKW_CLAIM="$T/ekw_claim.sh" \
  POOL_EKW_RUNNER="$T/ekw_runner.sh" bash "$POOL" "T" > "$T/pool.out" 2>&1 &
for i in $(seq 1 40); do grep -q "^ekw LGL-999" "$T/runs.log" 2>/dev/null && break; sleep 1; done
fail=0
first=$(head -1 "$T/runs.log" 2>/dev/null | cut -d' ' -f1-2)
if [ "$first" = "svc SVC-PC-1-1-0" ]; then echo "PASS A SVC task ran first"; else echo "FAIL A first run: '$first'"; fail=1; fi
if grep -q "^ekw LGL-999" "$T/runs.log" 2>/dev/null && grep -q "claim LGL-999 (ekw)" "$T/_v7/pool.log"; then echo "PASS B empty SVC queue -> EKW task claimed and run"; else echo "FAIL B"; fail=1; fi
touch "$T/_v7/POOL_STOP"; sleep 3
[ "$fail" = 0 ] && echo "ALL PASS"; exit "$fail"
