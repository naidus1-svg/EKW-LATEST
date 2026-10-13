#!/usr/bin/env bash
# opus_pilot.sh <task-list-file> [concurrency=3]
# Measurement only: run the canon workspace-mode review with Opus (the DataOS panelist model family) on a list of tasks, to score against the still-true DataOS majors
# the same way the third-Sonnet "thorough" pilot was scored (baseline on the same rows: GLM+Sonnet 3 of 39 caught at major, thorough Sonnet 3 of 39).
# Output per task: stream-pipe/<task>/CR.opus.pilot.json (+ .stats.json, .log). The name is not CR.<glm|sonnet>.round<N>.json, so neither the zip step, the actuator,
# the dispatcher nor the guard ever reads it. Idempotent: skips a parsed output. Lanes with an unexpired lanes/<lane>.limited_until are skipped.
# Log: /root/qc/_prompts/opus_pilot.log
cd /root/qc || exit 1
LIST="$1"
CONC="${2:-3}"
WS=/root/qc/review_workspace_opus
mkdir -p "$WS/opus"
C=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
POOL=(/root/.claude-q /root/.claude-r /root/.claude-b /root/.claude-c /root/.claude-d /root/.claude-e /root/.claude-f)
LOG=/root/qc/_prompts/opus_pilot.log
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }
i=0
run_one() { # task lane
  local t="$1" lane="$2" out="stream-pipe/$1/CR.opus.pilot.json"
  if python3 -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if 'overall_verdict' in d and isinstance(d.get('checks'), list) else 1)" "$out" 2> /dev/null; then
    log "SKIP $t opus pilot (canonical output exists)"
    return
  fi
  mkdir -p "stream-pipe/$t"
  log "START $t opus pilot lane=$(basename "$lane")"
  CLAUDE_CONFIG_DIR="$lane" python3 tools/run_workspace_review.py --task "$t" --corpus-root "$C" \
    --workspace-root "$WS/opus" --runs-root /root/qc/runs --pipe-dir "stream-pipe/$t" --reviewer opus --timeout 3000 \
    --out "$out" --stats-out "stream-pipe/$t/CR.opus.pilot.stats.json" > "stream-pipe/$t/CR.opus.pilot.log" 2>&1
  local rc=$?
  local v
  v=$(python3 -c "import json; j=json.load(open('$out')); print(j.get('overall_verdict'), 'maj', j.get('major_count'), 'min', j.get('minor_count'), 'checks', len(j.get('checks', [])))" 2> /dev/null || echo "NO-JSON rc=$rc")
  log "FINISH $t opus pilot rc=$rc $v"
}
log "OPUS PILOT START list=$LIST tasks=$(grep -c . "$LIST") conc=$CONC"
while read -r t; do
  [ -n "$t" ] || continue
  while [ "$(jobs -rp | wc -l)" -ge "$CONC" ]; do sleep 10; done
  lane=""
  for _k in $(seq 1 ${#POOL[@]}); do
    c="${POOL[$((i % ${#POOL[@]}))]}"
    i=$((i + 1))
    lu="/root/qc/lanes/$(basename "$c").limited_until"
    if [ -f "$lu" ] && [ "$(tr -dc 0-9 < "$lu" 2> /dev/null || echo 0)" -gt "$(date +%s)" ] 2> /dev/null; then continue; fi
    lane="$c"
    break
  done
  [ -n "$lane" ] || {
    lane="${POOL[$((i % ${#POOL[@]}))]}"
    i=$((i + 1))
  }
  run_one "$t" "$lane" &
  sleep 3
done < "$LIST"
wait
log "OPUS PILOT DONE list=$LIST"
