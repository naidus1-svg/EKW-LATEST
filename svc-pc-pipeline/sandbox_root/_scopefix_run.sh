#!/bin/bash
# Single-task scope-breadth fix for SVC-PC-13-3-0 on one opus lane. Snapshot, fix, mark done.
set -u
C=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready/SVC-PC-13-3-0
W=/root/qc/_scopefix
mkdir -p "$W/snap"
cp -a "$C/tests" "$W/snap/tests" 2>/dev/null
cp -a "$C/solution" "$W/snap/solution" 2>/dev/null
export QC_REWARDKIT_SITE_PACKAGES=/root/venv/lib/python3.13/site-packages
cd "$C"
CLAUDE_CONFIG_DIR=/root/.claude-q timeout 2400 claude -p "$(cat "$W/13-3-0.md")" \
  --model opus --permission-mode dontAsk --allowedTools "Read,Edit,Write,Bash,Glob,Grep" \
  --output-format text > "$W/13-3-0.log" 2>&1
echo "SCOPEFIX_DONE rc=$? $(date -u +%FT%TZ)" >> "$W/13-3-0.status"
