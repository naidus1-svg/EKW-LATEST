#!/usr/bin/env bash
# thorough_pilot.sh - run the canon workspace-mode review PLUS tools/prompts/ekwqc/thorough-addendum.md (worksheets W1-W5,
# argued-away rule, severity follows the spec) as a third reviewer on a list of tasks, N at a time.
# Output per task: stream-pipe/<task>/CR.thorough.round0.json (+ .stats.json, .log). Idempotent: skips a parsed output.
# Usage: thorough_pilot.sh <task-list-file> [concurrency=10]
# Log: /root/qc/_prompts/thorough_pilot.log   Lane choice skips lanes with an unexpired lanes/<lane>.limited_until.
cd /root/qc || exit 1
LIST="$1"; CONC="${2:-10}"
WS=/root/qc/review_workspace_thorough; mkdir -p "$WS"
C=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
POOL=(/root/.claude /root/.claude-b /root/.claude-c /root/.claude-d /root/.claude-e /root/.claude-f /root/.claude-g /root/.claude-i /root/.claude-j /root/.claude-k /root/.claude-l /root/.claude-q /root/.claude-r)
LOG=/root/qc/_prompts/thorough_pilot.log
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }
i=0
run_one() {  # task lane
  local t="$1" lane="$2" out="stream-pipe/$1/CR.thorough.round0.json"
  if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$out" 2>/dev/null; then log "SKIP $t thorough (done)"; return; fi
  mkdir -p "stream-pipe/$t"
  log "START $t thorough lane=$(basename "$lane")"
  CLAUDE_CONFIG_DIR="$lane" python3 tools/run_workspace_review_thorough.py --task "$t" --corpus-root "$C" \
    --workspace-root "$WS/sonnet" --runs-root /root/qc/runs --pipe-dir "stream-pipe/$t" --reviewer sonnet --timeout 3000 \
    --out "$out" --stats-out "stream-pipe/$t/CR.thorough.round0.stats.json" > "stream-pipe/$t/CR.thorough.round0.log" 2>&1
  local rc=$?
  local v; v=$(python3 -c "import json; j=json.load(open('$out')); print(j.get('overall_verdict'), 'maj', j.get('major_count'), 'min', j.get('minor_count'))" 2>/dev/null || echo "NO-JSON rc=$rc")
  log "FINISH $t thorough rc=$rc $v"
}
log "PILOT START list=$LIST tasks=$(grep -c . "$LIST") conc=$CONC"
while read -r t; do
  [ -n "$t" ] || continue
  while [ "$(jobs -rp | wc -l)" -ge "$CONC" ]; do sleep 10; done
  lane=""
  for _k in $(seq 1 ${#POOL[@]}); do
    c="${POOL[$(( i % ${#POOL[@]} ))]}"; i=$((i+1))
    lu="/root/qc/lanes/$(basename "$c").limited_until"
    if [ -f "$lu" ] && [ "$(tr -dc 0-9 < "$lu" 2>/dev/null || echo 0)" -gt "$(date +%s)" ] 2>/dev/null; then continue; fi
    lane="$c"; break
  done
  [ -n "$lane" ] || { lane="${POOL[$(( i % ${#POOL[@]} ))]}"; i=$((i+1)); }
  run_one "$t" "$lane" &
  sleep 3
done < "$LIST"
wait
log "PILOT DONE list=$LIST"
