#!/bin/bash
# Directed DataOS-feedback fixer. One Sonnet agent per task, fed that task's exact DataOS findings.
# Runs on the lanes (t excluded, capped). $1 = task-list file.  Verify (oracle+static) is a separate step.
set -u
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
LIST="$1"
W=/root/qc/_dataosfix
mkdir -p "$W/logs" "$W/snap" "$W/briefs"
export QC_REWARDKIT_SITE_PACKAGES=/root/venv/lib/python3.13/site-packages
LANES=(q r m v w c e f g i j k l p u)   # 15 working lanes; t excluded (weekly-capped 2026-09-21)
: > "$W/progress.txt"
idx=0
MAXJ=12
while read -r t; do
  [ -z "$t" ] && continue
  lane="/root/.claude-${LANES[$((idx % ${#LANES[@]}))]}"
  idx=$((idx + 1))
  python3 /root/qc/tools/svc_dataos_fix_brief.py "$t" /root/qc/_findings.json > "$W/briefs/$t.md" 2>/dev/null
  (
    mkdir -p "$W/snap/$t"
    cp -a "$CORPUS/$t/tests" "$W/snap/$t/tests" 2>/dev/null
    cd "$CORPUS/$t" && CLAUDE_CONFIG_DIR="$lane" timeout 2700 claude -p "$(cat "$W/briefs/$t.md")" \
      --model sonnet --permission-mode dontAsk --allowedTools "Read,Edit,Write,Bash,Glob,Grep" \
      --output-format text > "$W/logs/$t.fix.log" 2>&1
    echo "fixed $t rc=$? lane=$lane" >> "$W/progress.txt"
  ) &
  while [ "$(jobs -r | wc -l)" -ge "$MAXJ" ]; do sleep 3; done
done < "$LIST"
wait
echo "FIX_DONE $(date -u +%FT%TZ)" >> "$W/progress.txt"
