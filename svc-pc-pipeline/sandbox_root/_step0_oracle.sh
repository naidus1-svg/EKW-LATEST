#!/bin/bash
# Step 0: run the EXISTING oracle gate (judge_emulate.py, judge=rubric's claude-sonnet-4-6, CLI backend)
# on the exact bytes we shipped in batch15, to measure how many goldens score < 1.0 (i.e. how many the
# gate we bypassed would have blocked). --runs 1 is a lower bound (the real gate takes min of 3).
set -u
Z=/root/qc/dataos-batch-15-2026-09-20.zip
W=/root/qc/_step0
rm -rf "$W"; mkdir -p "$W/corpus" "$W/out"
( cd "$W/corpus" && unzip -q "$Z" )
cd /root/qc || exit 3
IDS="SVC-PC-12-1-0 SVC-PC-82-1-0 SVC-PC-46-3-0 SVC-PC-5-2-0 SVC-PC-15-4-0 SVC-PC-20-1-0 SVC-PC-16-1-0 SVC-PC-67-3-0 SVC-PC-38-3-0 SVC-PC-2-7-0 SVC-PC-31-5-0 SVC-PC-26-8-0 SVC-PC-15-1-0 SVC-PC-15-2-0 SVC-PC-14-4-0"
LANES=(q r m v w b c d e f g i j k l)
i=0
for t in $IDS; do
  lane="/root/.claude-${LANES[$((i % ${#LANES[@]}))]}"; i=$((i+1))
  ( CLAUDE_CONFIG_DIR="$lane" timeout 2400 /root/venv/bin/python3 tools/judge_emulate.py oracle "$t" \
      --runs 1 --corpus-root "$W/corpus" --out "$W/out/$t.json" > "$W/out/$t.log" 2>&1
    echo "done $t rc=$? lane=$(basename $lane)" >> "$W/progress.txt" ) &
done
wait
{
  echo "STEP0 oracle on shipped batch15 bytes (runs=1)  $(date -u +%FT%TZ)"
  echo "DataOS outcome key: PASS=12-1-0,5-2-0 ; the other 13 = FAIL"
  for t in $IDS; do
    r=$(/root/venv/bin/python3 -c "import json;d=json.load(open('$W/out/$t.json'));print(d.get('total_reward'))" 2>/dev/null)
    inf=$(/root/venv/bin/python3 -c "import json;d=json.load(open('$W/out/$t.json'));print('infra' if d.get('infra_failure') else '')" 2>/dev/null)
    echo "$t total_reward=$r $inf"
  done
} > "$W/RESULTS.txt" 2>&1
echo "ALL_DONE $(date -u +%FT%TZ)" >> "$W/progress.txt"
