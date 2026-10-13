#!/bin/bash
# Behaviour test for svc_v7_pool.sh with a stub runner and a stub `claude`. Runs anywhere with bash + pgrep;
# touches nothing under /root/qc. Lanes T and U are fake, so real runners on real lanes never match.
#   1. tasks requeued AFTER every worker went idle still get claimed (the 2026-09-23 starvation bug)
#   2. a lane held by an outside runner (svc_release_launch.sh) is not given a second runner
#   3. POOL_STOP ends the pool cleanly
# Usage: bash test_svc_v7_pool.sh /path/to/svc_v7_pool.sh
set -u
POOL="${1:?path to svc_v7_pool.sh}"
T=$(mktemp -d); trap 'touch "$T/_v7/POOL_STOP"; sleep 1; rm -rf "$T"' EXIT
mkdir -p "$T/_v7" "$T/bin"
printf '#!/bin/bash\necho OK\n' > "$T/bin/claude"; chmod +x "$T/bin/claude"
cat > "$T/svc_v7_lane_runner.sh" <<'EOF'
#!/bin/bash
echo "$(date +%s.%N) start $1 $2" >> "$(dirname "$0")/runs.log"
sleep "${STUB_SECS:-3}"
echo "$(date +%s.%N) end $1 $2" >> "$(dirname "$0")/runs.log"
EOF
fail=0; ok(){ echo "PASS $1"; }; bad(){ echo "FAIL $1"; fail=1; }

echo SVC-PC-900-1-0 > "$T/_v7/queue.txt"
PATH="$T/bin:$PATH" POOL_QC="$T" POOL_IDLE_POLL=2 bash "$POOL" "T U" > "$T/pool.out" 2>&1 &
PID=$!
sleep 8                                            # task 1 done; both workers now idle
printf 'SVC-PC-900-2-0\nSVC-PC-900-3-0\n' >> "$T/_v7/queue.txt"   # a DataOS return requeues two rejects
sleep 14
n=$(grep -c " end SVC-PC-900-[123]-0 " "$T/runs.log" 2>/dev/null || echo 0)
[ "$n" -eq 3 ] && ok "1 requeued tasks claimed after workers idled ($n/3 ran)" || bad "1 only $n/3 ran"

STUB_SECS=12 bash "$T/svc_v7_lane_runner.sh" SVC-PC-900-9-0 T &   # outside runner owns lane T
EXT=$!
sleep 1
echo SVC-PC-900-4-0 >> "$T/_v7/queue.txt"
sleep 8
lane=$(grep " start SVC-PC-900-4-0 " "$T/runs.log" | awk '{print $4}')
[ "$lane" = "U" ] && ok "2 busy lane T skipped; task 4 ran on U" || bad "2 task 4 ran on '${lane:-nothing}' while T was held"
wait $EXT

touch "$T/_v7/POOL_STOP"
for i in $(seq 1 30); do kill -0 $PID 2>/dev/null || break; sleep 1; done
kill -0 $PID 2>/dev/null && { bad "3 pool still running 30s after POOL_STOP"; kill $PID; } || ok "3 POOL_STOP ends the pool"
grep -q "POOL_DONE" "$T/_v7/pool.log" && ok "3b POOL_DONE logged" || bad "3b no POOL_DONE"
[ $fail -eq 0 ] && echo "ALL PASS" || { echo "--- pool.log"; cat "$T/_v7/pool.log"; echo "--- runs.log"; cat "$T/runs.log"; }
exit $fail
