#!/usr/bin/env bash
# adjudicate_loop.sh - keep stream-pipe/<T>/ADJUDICATE.json fresh for every task in the ready pool (a zip in out/pipe that is not on SUBMITTED.txt), plus any
# task id listed in lanes/ADJUDICATE_QUEUE. A fix changes files, which makes an earlier adjudication stale by construction (build_review_union.py counts only an
# adjudication newer than every file), so this loop is what re-grades the SAME solver outputs against the fixed rubric and adjudicates again.
#
# Skips: a task whose status is NEED_SOLVE or NEED_RESOLVE and whose inputs have not changed (nothing to do until someone solves); a task whose last attempt
# ended GRADE_TAINTED or ADJUDICATION_INCOMPLETE less than 30 minutes ago (no hammering the judge). Holds off while the host load average is above 64.
# Detached start: (setsid nohup bash tools/adjudicate_loop.sh > _prompts/adjudicate_loop.out 2>&1 < /dev/null &); exit 0
# Log: /root/qc/_prompts/adjudicate.log. Stop: touch lanes/ADJUDICATE_LOOP_OFF.
cd /root/qc || exit 1
LOG=/root/qc/_prompts/adjudicate.log
INTERVAL="${ADJ_INTERVAL:-300}"
CONC="${ADJ_CONC:-12}"
POOL=(/root/.claude-q /root/.claude-r /root/.claude-b /root/.claude-c /root/.claude-e /root/.claude-f /root/.claude-g /root/.claude-i)
i=0
echo "$(date -u +%FT%TZ) ADJUDICATE LOOP START pid=$$ conc=$CONC interval=${INTERVAL}s" | tee -a "$LOG"
while true; do
  [ -f /root/qc/lanes/ADJUDICATE_LOOP_OFF ] && { echo "$(date -u +%FT%TZ) ADJUDICATE LOOP OFF" | tee -a "$LOG"; exit 0; }
  CANDS=$(python3 - <<'PYEOF'
import glob, os, sys, time
Q = "/root/qc"
if f"{Q}/tools" not in sys.path:
    sys.path.insert(0, f"{Q}/tools")
import oracle_refresh as o
C = "/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready"
sub = set(open(f"{Q}/SUBMITTED.txt").read().split())
ids = [os.path.basename(z)[:-4] for z in sorted(glob.glob(f"{Q}/out/pipe/SVC-PC-*.zip"))]
try:
    for x in open(f"{Q}/lanes/ADJUDICATE_QUEUE").read().split():
        ids.append(x if x.startswith("SVC-PC-") else f"SVC-PC-{x}")
except OSError:
    pass
seen, out = set(), []
for t in ids:
    if t in seen or t in sub:
        continue
    seen.add(t)
    pipe = f"{Q}/stream-pipe/{t}"
    st = open(f"{pipe}/ADJUDICATE.status").read().strip() if os.path.exists(f"{pipe}/ADJUDICATE.status") else ""
    sm = os.path.getmtime(f"{pipe}/ADJUDICATE.status") if st else 0
    if st in ("GRADE_TAINTED", "ADJUDICATION_INCOMPLETE", "ADJUDICATION_FAILED") and time.time() - sm < 1800:
        continue
    try:
        newest = o.newest_staged(t)[0]
    except Exception:
        newest = 0
    aj = f"{pipe}/ADJUDICATE.json"
    fresh = st == "OK" and os.path.exists(aj) and os.path.getmtime(aj) >= newest
    if st in ("NEED_SOLVE", "NEED_RESOLVE"):
        # re-check only when a run has finished since the status was written
        runs = [f"{Q}/runs/{t}/glm-{n}/claude_exit_code.txt" for n in (1, 2)]
        if not any(os.path.exists(r) and os.path.getmtime(r) > sm for r in runs):
            continue
    if not fresh:
        out.append(t)
print(" ".join(out))
PYEOF
)
  for t in $CANDS; do
    while [ "$(jobs -rp | wc -l)" -ge "$CONC" ] || [ "$(ps -eo args --no-headers | grep '[c]laude -p' | grep -vc 'glm-5')" -ge "${ADJ_SESSIONS_MAX:-75}" ]; do sleep 20; done
    [ -f /root/qc/lanes/ADJUDICATE_LOOP_OFF ] && break
    lane="${POOL[$((i % ${#POOL[@]}))]}"
    i=$((i + 1))
    ADJ_LANE="$lane" bash /root/qc/tools/adjudicate_task.sh "$t" > /dev/null 2>&1 &
    sleep 3
  done
  wait
  # A fix can change instruction.md (the fixer does when a criterion tests something the instruction never asked for), which makes both solver runs stale; a task with no
  # finished run at all is in the same position. Send those to the solver batch (idempotent: it skips a run whose recorded instruction sha matches, so a task already
  # solved is a no-op) unless a batch is already running.
  NEED=$(for f in /root/qc/stream-pipe/SVC-PC-*/ADJUDICATE.status; do s=$(cat "$f" 2>/dev/null); case "$s" in NEED_SOLVE|NEED_RESOLVE) basename "$(dirname "$f")";; esac; done)
  if [ -n "$NEED" ] && ! pgrep -f "[s]olver_batch_list.sh --go" > /dev/null; then
    printf '%s\n' $NEED | sort -u > /root/qc/lanes/SOLVER_ONLY_LIST
    echo "$(date -u +%FT%TZ) SOLVER BATCH for $(wc -l < /root/qc/lanes/SOLVER_ONLY_LIST) task(s) that need solving or re-solving" | tee -a "$LOG"
    (SOLVER_ONLY_LIST=/root/qc/lanes/SOLVER_ONLY_LIST SOLVER_LIMIT=24 setsid nohup bash /root/qc/tools/solver_batch_list.sh --go > /root/qc/runs/BATCH_LIST.nohup.log 2>&1 < /dev/null &)
  fi
  sleep "$INTERVAL"
done
