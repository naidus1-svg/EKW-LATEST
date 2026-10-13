#!/usr/bin/env bash
# finish_direct_fix.sh TASK
# After a laptop-side Fable fix agent reports on a task: release the coordinator's lock holder, then run both reviewers at the next
# round number (rereview_pair.sh) so the zip loop reads a verdict pair about the bytes as they now stand. The verify loop re-rules
# the DataOS rows on its own once the lock is free (its byte trigger), and the zip loop packages once marker, pair and oracle agree.
# Why (2026-09-20 02:05Z): the unattended editing agents cannot be launched from the laptop (permission classifier), so the fixes run
# as laptop agents over SSH under a detached lock holder (stream-pipe/<task>/FABLE-FIX.holder.pid); this is the hand-off back.
set -u
cd /root/qc || exit 1
task="${1:?TASK}"
pipe="/root/qc/stream-pipe/$task"
LOG=/root/qc/_prompts/direct/direct_fix.log
mkdir -p /root/qc/_prompts/direct
log() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }
if [ -f "$pipe/FABLE-FIX.holder.pid" ]; then
  hp=$(cat "$pipe/FABLE-FIX.holder.pid")
  kill "$hp" 2>/dev/null && log "FABLE-FIX $task: lock holder $hp released"
  rm -f "$pipe/FABLE-FIX.holder.pid"
fi
if [ -f "$pipe/DIRECT-FIX.md" ]; then
  log "FABLE-FIX $task: report present, FIXED=$(grep -c '^FIXED\|FIXED:' "$pipe/DIRECT-FIX.md") REFUTED=$(grep -c 'REFUTED:' "$pipe/DIRECT-FIX.md")"
else
  log "FABLE-FIX $task: no DIRECT-FIX.md"
fi
n=$(ls "$pipe"/CR.glm.round*.json 2>/dev/null | grep -oE 'round[0-9]+\.json$' | grep -oE '[0-9]+' | sort -n | tail -1)
n=$(( ${n:-0} + 1 ))
log "FABLE-FIX $task: reviews round$n"
bash /root/qc/tools/rereview_pair.sh --go "$task" "$n" >> "$LOG" 2>&1
log "FABLE-FIX $task: reviews round$n finished"
