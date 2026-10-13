#!/bin/bash
# Aggressive fix on the 9 wave-1 tasks: snapshot rubrics, Opus repairs every detected 1.4/1.5
# over-enforcement + duplication (edits judge.toml), then oracle-verify the golden still scores 1.0.
set -u
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
W=/root/qc/_aggfix; rm -rf "$W"; mkdir -p "$W/logs" "$W/snap" "$W/oracle"
BRIEF=/root/qc/_aggfix_brief.md
: > "$W/progress.txt"
export QC_REWARDKIT_SITE_PACKAGES=/root/venv/lib/python3.13/site-packages
PY=/root/venv/bin/python3
TASKS="SVC-PC-1-2-0 SVC-PC-10-2-0 SVC-PC-11-3-0 SVC-PC-12-2-0 SVC-PC-13-3-0 SVC-PC-14-1-0 SVC-PC-15-5-0 SVC-PC-19-4-0 SVC-PC-20-3-0"
for t in $TASKS; do mkdir -p "$W/snap/$t"; cp -a "$CORPUS/$t/tests" "$W/snap/$t/tests" 2>/dev/null; done
LANES=(q r m v w c e f g i j k l p t u); idx=0
for t in $TASKS; do
  lane="/root/.claude-${LANES[$((idx % ${#LANES[@]}))]}"; idx=$((idx+1))
  ( cd "$CORPUS/$t" && CLAUDE_CONFIG_DIR="$lane" timeout 2700 claude -p "$(sed "s/<TASK>/$t/g" "$BRIEF")" \
      --model opus --permission-mode dontAsk --allowedTools "Read,Edit,Write,Bash,Glob,Grep" \
      --output-format text > "$W/logs/$t.fix.log" 2>&1
    echo "fixed $t rc=$?" >> "$W/progress.txt" ) &
done
wait
echo "FIX_DONE $(date -u +%FT%TZ)" >> "$W/progress.txt"
idx=0
for t in $TASKS; do
  lane="/root/.claude-${LANES[$((idx % ${#LANES[@]}))]}"; idx=$((idx+1))
  ( CLAUDE_CONFIG_DIR="$lane" timeout 2400 "$PY" /root/qc/tools/judge_emulate.py oracle "$t" \
      --runs 1 --corpus-root "$CORPUS" --out "$W/oracle/$t.json" > "$W/oracle/$t.log" 2>&1
    orc=$("$PY" -c "import json;print(json.load(open('$W/oracle/$t.json')).get('total_reward'))" 2>/dev/null)
    # count judge.toml changes vs snapshot
    ch=$(diff -rq "$W/snap/$t/tests" "$CORPUS/$t/tests" 2>/dev/null | grep -c judge.toml)
    echo "oracle $t = $orc  (judge.toml files changed: $ch)" >> "$W/progress.txt" ) &
done
wait
echo "ALL_DONE $(date -u +%FT%TZ)" >> "$W/progress.txt"
