#!/bin/bash
# Tests the pool watchdog in sandbox_housekeep.sh with a fake pool script: dead -> relaunched once; alive -> not
# launched again; POOL_STOP present -> not relaunched. Run on the sandbox. Never touches the real pool.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"; mkdir -p "$T/_v7"
printf '#!/bin/bash\nsleep 60\n' > "$T/fakepool.sh"
mkdir -p "$T/tmp"
# The reaper only ever sees this test's own fake lane, so no test run can touch a real lane's process.
L="hkt$$"
export HK_POOL="$T/fakepool.sh" HK_POOLWORK="$T/_v7" HK_LOG="$T/hk.log" LOW_GB=0 HK_TMP="$T/tmp" TMP_PCT=101 \
  HK_REAP_LOG="$T/reaper.log" REAP_LANE_RE="$L"
cnt(){ pgrep -fc "^bash $T/fakepool.sh\$"; }
stop(){ for p in $(pgrep -f "^bash $T/fakepool.sh\$"); do kill "$p"; done; sleep 1; }
fail=0
bash "$HERE/sandbox_housekeep.sh"; sleep 1
[ "$(cnt)" = 1 ] && grep -q POOL_RELAUNCHED "$T/hk.log" && echo "ok   dead pool relaunched once" || { echo "FAIL relaunch (procs=$(cnt))"; fail=1; }
bash "$HERE/sandbox_housekeep.sh"; sleep 1
[ "$(cnt)" = 1 ] && echo "ok   live pool not launched twice" || { echo "FAIL double launch (procs=$(cnt))"; fail=1; }
stop; touch "$T/_v7/POOL_STOP"; bash "$HERE/sandbox_housekeep.sh"; sleep 1
[ "$(cnt)" = 0 ] && echo "ok   POOL_STOP respected" || { echo "FAIL relaunched despite POOL_STOP"; fail=1; }
stop
# /tmp inode cleanup (2026-09-28): old lane scratch goes, fresh work and system entries stay; nothing below threshold
mkdir -p "$T/tmp/regrade_old/x" "$T/tmp/fresh_dir" "$T/tmp/systemd-private-abc" "$T/tmp/.X11-unix"; touch "$T/tmp/tmpold.json"
touch -d "2 days ago" "$T/tmp/regrade_old" "$T/tmp/tmpold.json" "$T/tmp/systemd-private-abc" "$T/tmp/.X11-unix"
TMP_PCT=101 bash "$HERE/sandbox_housekeep.sh"; stop
[ -d "$T/tmp/regrade_old" ] && echo "ok   below threshold nothing removed" || { echo "FAIL removed below threshold"; fail=1; }
TMP_PCT=0 bash "$HERE/sandbox_housekeep.sh"; stop
[ ! -e "$T/tmp/regrade_old" ] && [ ! -e "$T/tmp/tmpold.json" ] && echo "ok   old scratch removed" || { echo "FAIL old scratch kept"; fail=1; }
[ -d "$T/tmp/fresh_dir" ] && echo "ok   fresh dir kept" || { echo "FAIL fresh dir removed"; fail=1; }
[ -d "$T/tmp/systemd-private-abc" ] && [ -d "$T/tmp/.X11-unix" ] && echo "ok   system entries kept" || { echo "FAIL system entry removed"; fail=1; }
grep -q TMP_CLEANED "$T/hk.log" && echo "ok   cleanup logged" || { echo "FAIL not logged"; fail=1; }
# Orphan reaper (2026-09-29): real orphans (setsid + subshell exit, so the parent is PID 1) carrying a fake lane's
# CLAUDE_CONFIG_DIR. Fakes are single processes (blocking builtin read on a fifo, no children) so a kill never
# leaves a second orphan behind. cwd is a fake source_documents dir so the log's cwd field is checked too.
mkfifo "$T/fifo"; mkdir -p "$T/SCO-T/source_documents"
mk(){ printf '#!/bin/bash\n%s\n' "$2" > "$T/$1"; chmod +x "$T/$1"; }
mk spin.sh 'while :; do :; done'
mk idle.sh "read -t 900 <> $T/fifo"
mk svc_v7_pool.sh "read -t 900 <> $T/fifo"
mk svc_v7_lane_runner.sh "read -t 900 <> $T/fifo"
mk judge_emulate.py "read -t 900 <> $T/fifo"
mk stubborn.sh "trap '' TERM; while :; do read -t 1 <> $T/fifo; done"
cp "$(command -v sleep)" "$T/claude"
orphan(){ (cd "$T/SCO-T/source_documents"; setsid nohup env CLAUDE_CONFIG_DIR=/root/.claude-$L "$@" > /dev/null 2>&1 < /dev/null &); }
pid_of(){ pgrep -f -x "$1" | head -1; }
alive(){ [ -n "$1" ] && [ -d "/proc/$1" ] && [ "$(sed 's/.*) //' /proc/$1/stat | cut -d' ' -f1)" != Z ]; }
chk(){ if (eval "$2"); then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
orphan bash "$T/spin.sh"; orphan bash "$T/idle.sh"; orphan bash "$T/svc_v7_pool.sh"
orphan bash "$T/svc_v7_lane_runner.sh" HKT-1 "$L"; orphan bash "$T/judge_emulate.py" oracle HKT-1 --runs 1
orphan bash "$T/judge_emulate.py" oracle HKT-2 --runs 1; orphan "$T/claude" 900
(setsid nohup bash "$T/idle.sh" untagged > /dev/null 2>&1 < /dev/null &)
env CLAUDE_CONFIG_DIR=/root/.claude-$L bash "$T/idle.sh" child > /dev/null 2>&1 < /dev/null & CHILD=$!
sleep 1
P_SPIN=$(pid_of "bash $T/spin.sh"); P_IDLE=$(pid_of "bash $T/idle.sh"); P_POOL=$(pid_of "bash $T/svc_v7_pool.sh")
P_RUN=$(pid_of "bash $T/svc_v7_lane_runner.sh HKT-1 $L"); P_J1=$(pid_of "bash $T/judge_emulate.py oracle HKT-1 --runs 1")
P_J2=$(pid_of "bash $T/judge_emulate.py oracle HKT-2 --runs 1"); P_CL=$(pid_of "$T/claude 900"); P_UN=$(pid_of "bash $T/idle.sh untagged")
chk "fakes are real orphans (parent PID 1)" '[ "$(ps -o ppid= -p "$P_IDLE" | tr -d " ")" = 1 ] && [ "$(ps -o ppid= -p "$P_J2" | tr -d " ")" = 1 ]'
ALL="$P_SPIN $P_IDLE $P_POOL $P_RUN $P_J1 $P_J2 $P_CL"
# 1. production thresholds: fresh orphans are below all of them, every one is spared and says why
bash "$HERE/sandbox_housekeep.sh"; stop
chk "default thresholds kill nothing" 'for p in $ALL $CHILD; do alive $p || exit 1; done'
chk "spared: below thresholds logged" 'grep -q "SPARE pid=$P_IDLE lane=$L why=\"below thresholds" "$T/reaper.log"'
chk "spared: lane runner logged" 'grep -q "SPARE pid=$P_RUN .*why=\"lane runner\"" "$T/reaper.log"'
chk "spared: pool logged" 'grep -q "SPARE pid=$P_POOL .*why=\"pool\"" "$T/reaper.log"'
chk "spared: claude process logged" 'grep -q "SPARE pid=$P_CL .*why=\"claude process\"" "$T/reaper.log"'
chk "spared: judge_emulate with live runner logged" 'grep -q "SPARE pid=$P_J1 .*judge_emulate.py with a live runner (HKT-1" "$T/reaper.log"'
chk "untagged orphan and non-orphan never considered" '! grep -qE "pid=($P_UN|$CHILD) " "$T/reaper.log"'
# 2. dry run with the RSS bar at 0: decisions printed, nothing killed, nothing logged, no other step runs
n_r=$(wc -l < "$T/reaper.log"); n_h=$(wc -l < "$T/hk.log")
out=$(REAP_RSS_GB=0 bash "$HERE/sandbox_housekeep.sh" --reap-dry-run)
chk "dry run prints WOULD-KILL" 'grep -q "WOULD-KILL pid=$P_IDLE " <<< "$out" && grep -q "WOULD-KILL pid=$P_J2 " <<< "$out" && grep -q "DRY-RUN summary" <<< "$out"'
chk "dry run kills nothing" 'for p in $ALL; do alive $p || exit 1; done'
chk "dry run writes no log and skips other steps" '[ "$(wc -l < "$T/reaper.log")" = "$n_r" ] && [ "$(wc -l < "$T/hk.log")" = "$n_h" ]'
# 3. elapsed + CPU rule: only the spinner has burned CPU, the idle orphan with the same age is spared
sleep 2
REAP_ELAPSED_S=2 REAP_CPU_S=1 bash "$HERE/sandbox_housekeep.sh"; stop
chk "cpu+elapsed rule kills the spinner" '! alive $P_SPIN && grep -q "KILL pid=$P_SPIN lane=$L .*why=\"elapsed" "$T/reaper.log"'
chk "cpu+elapsed rule spares idle orphans" 'alive $P_IDLE && alive $P_J2'
# 4. RSS rule: bar at 0 kills every unexcluded orphan; exclusions and the non-orphan survive
REAP_RSS_GB=0 bash "$HERE/sandbox_housekeep.sh"; stop
chk "rss rule kills unexcluded orphans" '! alive $P_IDLE && ! alive $P_J2'
chk "rss rule spares runner, pool, claude, judged task, non-orphan" 'for p in $P_RUN $P_POOL $P_CL $P_J1 $CHILD; do alive $p || exit 1; done'
chk "kill line carries pid lane cwd rss elapsed args" 'grep -qE "KILL pid=$P_IDLE lane=$L cwd=$T/SCO-T/source_documents rss_kb=[0-9]+ elapsed_s=[0-9]+ cpu_s=[0-9]+ why=\"rss .* args=\"bash $T/idle.sh" "$T/reaper.log"'
chk "housekeep log counts the reap" 'grep -q "REAPED=2" "$T/hk.log"'
# 5. a process that ignores TERM gets KILL after the grace period
orphan bash "$T/stubborn.sh"; sleep 1; P_ST=$(pid_of "bash $T/stubborn.sh")
REAP_RSS_GB=0 REAP_GRACE_S=2 bash "$HERE/sandbox_housekeep.sh"; stop
chk "TERM-ignoring orphan is SIGKILLed" '! alive $P_ST && grep -q "SIGKILL pid=$P_ST " "$T/reaper.log"'
kill -9 $P_RUN $P_POOL $P_CL $P_J1 $P_UN $CHILD 2>/dev/null; sleep 1
rm -rf "$T"
[ "$fail" = 0 ] && echo "26/26 PASS" || { echo FAILED; exit 1; }
