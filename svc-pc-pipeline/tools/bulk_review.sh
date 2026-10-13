#!/usr/bin/env bash
# bulk_review.sh - run the workspace-mode Comprehensive Review with two reviewers (glm via the
# proxy, sonnet on a pool Max lane) on a list of tasks, N at a time. Outputs per task:
#   stream-pipe/<task>/CR.glm.round0.json, CR.sonnet.round0.json (+ .stats.json, .log)
# Usage: bulk_review.sh <task-list-file> [concurrency=12]
# Skips a task/reviewer pair whose output JSON already parses (idempotent, safe to relaunch).
cd /root/qc || exit 1
LIST="$1"; CONC="${2:-12}"
WS=/root/qc/review_workspace_bulk; mkdir -p "$WS"
C=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
POOL=(/root/.claude /root/.claude-b /root/.claude-c /root/.claude-d /root/.claude-e /root/.claude-f /root/.claude-g /root/.claude-i /root/.claude-j /root/.claude-k /root/.claude-l /root/.claude-q /root/.claude-r /root/.claude-p)
LOG=/root/qc/_prompts/bulk_review.log
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }
i=0
run_one() {  # task reviewer lane
  local t="$1" r="$2" lane="$3" out="stream-pipe/$1/CR.$2.round0.json"
  if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$out" 2>/dev/null; then log "SKIP $t $r (done)"; return; fi
  mkdir -p "stream-pipe/$t"
  log "START $t $r lane=$(basename "$lane")"
  CLAUDE_CONFIG_DIR="$lane" python3 tools/run_workspace_review.py --task "$t" --corpus-root "$C" \
    --workspace-root "$WS/$r" --runs-root /root/qc/runs --pipe-dir "stream-pipe/$t" --reviewer "$r" --timeout 2400 \
    --out "$out" --stats-out "stream-pipe/$t/CR.$r.round0.stats.json" > "stream-pipe/$t/CR.$r.round0.log" 2>&1
  local rc=$?
  local v; v=$(python3 -c "import json; j=json.load(open('$out')); print(j.get('overall_verdict'), 'maj', j.get('major_count'), 'min', j.get('minor_count'))" 2>/dev/null || echo "NO-JSON rc=$rc")
  log "FINISH $t $r rc=$rc $v"
}
log "BULK START list=$LIST tasks=$(grep -c . "$LIST") conc=$CONC"
while read -r t; do
  [ -n "$t" ] || continue
  for r in glm sonnet; do
    while [ "$(jobs -rp | wc -l)" -ge "$CONC" ]; do sleep 10; done
    # 2026-09-19 guard_rt: skip a lane whose usage limit has not reset (lanes/<lane>.limited_until holds the reset epoch)
    lane=""; for _k in $(seq 1 ${#POOL[@]}); do c="${POOL[$(( i % ${#POOL[@]} ))]}"; i=$((i+1)); lu="/root/qc/lanes/$(basename "$c").limited_until"; if [ -f "$lu" ] && [ "$(tr -dc 0-9 < "$lu" 2>/dev/null || echo 0)" -gt "$(date +%s)" ] 2>/dev/null; then continue; fi; lane="$c"; break; done
    [ -n "$lane" ] || { lane="${POOL[$(( i % ${#POOL[@]} ))]}"; i=$((i+1)); }
    run_one "$t" "$r" "$lane" &
    sleep 2
  done
done < "$LIST"
wait
log "BULK DONE list=$LIST"
