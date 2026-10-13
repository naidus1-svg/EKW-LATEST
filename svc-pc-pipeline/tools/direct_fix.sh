#!/usr/bin/env bash
# direct_fix.sh TASK LANE
# One Claude agent per task, end to end: brief from the open DataOS majors (direct_fix_brief.py), Opus, working inside the task's
# package directory under the same per-task lock the dispatcher, the DataOS fixer and the verify loop respect; then both reviewers
# re-read the files (rereview_pair.sh at the next round number) so the zip loop has a pair that matches the bytes. The verify loop's
# byte trigger re-rules the rows on its own once the lock is free.
# Why (2026-09-20 00:50Z): the plan-then-apply fixer stalled on 11 tasks and produced five fake-fix shapes; the remaining rows are
# authoring work. Launch: (setsid nohup bash tools/direct_fix.sh SVC-PC-X-Y-Z /root/.claude-b > _prompts/direct/X-Y-Z.nohup 2>&1 < /dev/null &)
set -u
cd /root/qc || exit 1
task="${1:?TASK}"
lane="${2:?LANE}"
pipe="/root/qc/stream-pipe/$task"
T="/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready/$task"
LOG=/root/qc/_prompts/direct/direct_fix.log
mkdir -p /root/qc/_prompts/direct
log() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }
# 2026-09-20 01:12Z: /usr/bin/claude was relinked mid-run and six agents died rc=127 "claude: not found"; resolve it once and check
CLAUDE_BIN="$(command -v claude || echo /usr/bin/claude)"
[ -x "$CLAUDE_BIN" ] || { log "$task: claude binary not found at $CLAUDE_BIN"; exit 5; }
[ -d "$T" ] || { log "$task: no task dir"; exit 2; }
python3 /root/qc/tools/direct_fix_brief.py "$task" > "$pipe/DIRECT-FIX-BRIEF.md" || { log "$task: no open rows, nothing to do"; exit 0; }
(
  exec 8>"$pipe/fix_from_reviews.lock"
  if ! flock -n 8; then log "$task: lock held, not launched"; exit 3; fi
  log "DIRECT-FIX START $task lane=$(basename "$lane") rows=$(grep -c '^### ' "$pipe/DIRECT-FIX-BRIEF.md")"
  cd "$T" || exit 1
  rm -f "$pipe/DIRECT-FIX.md"
  # root cannot use --dangerously-skip-permissions (refused); the unattended form is dontAsk plus an explicit tool allowlist
  CLAUDE_CONFIG_DIR="$lane" timeout 3000 "$CLAUDE_BIN" -p "$(cat "$pipe/DIRECT-FIX-BRIEF.md")" --model opus --permission-mode dontAsk \
    --allowedTools "Read,Edit,Write,Bash,Glob,Grep" --output-format text > "$pipe/DIRECT-FIX.log" 2>&1 < /dev/null
  rc=$?
  if [ -f "$pipe/DIRECT-FIX.md" ]; then
    log "DIRECT-FIX DONE $task rc=$rc report=yes not-fixable=$(grep -c 'NOT FIXABLE WITHOUT A PERSON' "$pipe/DIRECT-FIX.md")"
    # 00:15Z: the guard's gate_reopen clears FIX_FROM_REVIEWS markers and the zip loop then waits for the (now retired) dispatcher
    # to write FIX_FROM_REVIEWS_1 ("SKIP fix pending"); a finished direct fix is that fix, so record it in STATE
    grep -qx FIX_FROM_REVIEWS_1 "$pipe/STATE" 2>/dev/null || echo "FIX_FROM_REVIEWS_1" >> "$pipe/STATE"
  else
    log "DIRECT-FIX DONE $task rc=$rc report=NO (agent wrote no DIRECT-FIX.md)"
    [ "$rc" -eq 0 ] || exit 4
  fi
  exit "$rc"
)
rc=$?
[ "$rc" -eq 3 ] && exit 3
# no re-reviews unless the agent actually ran and finished: a failed launch must not spend two reviews on unchanged files
[ "$rc" -eq 0 ] || { log "DIRECT-FIX $task ended rc=$rc, no re-review"; exit "$rc"; }
# fresh review pair at the next round number, so the zip loop reads verdicts about the bytes as they now stand
n=$(ls "$pipe"/CR.glm.round*.json 2>/dev/null | grep -oE 'round[0-9]+\.json$' | grep -oE '[0-9]+' | sort -n | tail -1)
n=$(( ${n:-0} + 1 ))
log "DIRECT-FIX REVIEWS $task round$n"
bash /root/qc/tools/rereview_pair.sh --go "$task" "$n" >> "$LOG" 2>&1
log "DIRECT-FIX REVIEWS DONE $task round$n"
exit 0
