#!/usr/bin/env bash
set -u; cd /root/qc || exit 1
C=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
OUT=/root/qc/_prompts/gate-triage/digests; mkdir -p "$OUT"
LOG=/root/qc/_prompts/gate-triage/prebuild.log
n=0; done=0
for d in $C/SVC-PC-*; do
  t=$(basename "$d"); o="$OUT/$t.md"
  [ -f "$o" ] && { done=$((done+1)); continue; }
  timeout 300 python3 tools/v3digest_build.py "$d" "$o" --mode cited >> "$LOG" 2>&1 && n=$((n+1))
done
echo "$(date -u +%FT%TZ) PREBUILD DONE built=$n already=$done total=$(ls $OUT/*.md 2>/dev/null | wc -l)" >> "$LOG"
