#!/usr/bin/env bash
# oracle_refresh_all.sh TASK... : re-run the answer-key probe (judge_emulate.py oracle, 3 runs) on the CURRENT bytes of each task,
# rotating over lanes, N at a time. Why (2026-09-20 00:40Z): tools/oracle_stale_audit.py found all 22 resubmit probes older than
# their bytes; every zip today (10 already uploaded) shipped on a pre-fix score. Results: _prompts/oracle_refresh.log, one line per
# task with the fresh total_reward and the failing criteria, plus a summary line at the end.
set -u
cd /root/qc || exit 1
C=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
LOG=/root/qc/_prompts/oracle_refresh.log
LANES=(/root/.claude-b /root/.claude-c /root/.claude-e /root/.claude-f /root/.claude-g /root/.claude-i /root/.claude-j /root/.claude-k /root/.claude-l /root/.claude-m /root/.claude-v /root/.claude-w)
PAR=${PAR:-6}
log() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }
one() {
  local t="$1" lane="$2" d="/root/qc/stream-pipe/$1"
  mkdir -p "$d/probes"
  [ -f "$d/probes/oracle.json" ] && mv "$d/probes/oracle.json" "$d/probes/oracle.stale-$(date -u +%H%M%S).json"
  log "START $t on $(basename "$lane")"
  CLAUDE_CONFIG_DIR="$lane" timeout 3600 python3 tools/judge_emulate.py oracle "$t" --runs 3 --corpus-root "$C" --out "$d/probes/oracle.json" >> "$d/probes/oracle.log" 2>&1
  local rc=$?
  local res
  res=$(python3 - "$d/probes/oracle.json" <<'PY' 2>/dev/null
import json, sys
o = json.load(open(sys.argv[1]))
fails = [f"{g.get('name')}/{c.get('name')}" for g in o.get("groups", []) for c in g.get("criteria", []) if not c.get("passed", True)]
print(f"reward={o.get('total_reward')} infra={o.get('infra_failure', False)} fails={' '.join(fails) if fails else '-'}")
PY
)
  log "DONE $t rc=$rc ${res:-unparseable}"
}
i=0; n=0
for t in "$@"; do
  lane="${LANES[$(( i % ${#LANES[@]} ))]}"; i=$((i+1))
  one "$t" "$lane" &
  n=$((n+1))
  if [ "$n" -ge "$PAR" ]; then wait -n; n=$((n-1)); fi
done
wait
log "SUMMARY $(grep -c ' DONE ' "$LOG") done; below 1.0: $(grep ' DONE ' "$LOG" | grep -v 'reward=1.0 ' | awk '{print $3}' | tr '\n' ' ')"
