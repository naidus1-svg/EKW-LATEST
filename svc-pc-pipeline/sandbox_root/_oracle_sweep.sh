#!/bin/bash
# Oracle sweep: golden total_reward for each static+mojibake-clean fresh candidate.
# Parallel across lanes, throttled. Valid signal here because all inputs are grammar-clean
# (<=15 criteria/dir), so the CLI-backend oracle is not masking a grammar-too-large error.
set -u
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
W=/root/qc/_oraclesweep
mkdir -p "$W/oracle"
export QC_REWARDKIT_SITE_PACKAGES=/root/venv/lib/python3.13/site-packages
PY=/root/venv/bin/python3
LANES=(q r m v w c e f g i j k l p t u)
: > "$W/progress.txt"
MAXJ=14
idx=0

run_one() {
  local t="$1" lane="$2" orc
  CLAUDE_CONFIG_DIR="$lane" timeout 900 "$PY" /root/qc/tools/judge_emulate.py oracle "$t" \
    --runs 1 --corpus-root "$CORPUS" --out "$W/oracle/$t.json" > "$W/oracle/$t.log" 2>&1
  orc=$("$PY" -c "import json,sys
try: print(json.load(open('$W/oracle/$t.json')).get('total_reward'))
except Exception as e: print('ERR')" 2>/dev/null)
  echo "oracle $t = $orc" >> "$W/progress.txt"
}

while read -r t; do
  [ -z "$t" ] && continue
  lane="/root/.claude-${LANES[$((idx % ${#LANES[@]}))]}"
  idx=$((idx + 1))
  run_one "$t" "$lane" &
  while [ "$(jobs -r | wc -l)" -ge "$MAXJ" ]; do sleep 2; done
done < /root/qc/_mojibake_clean.txt
wait
echo "SWEEP_DONE $(date -u +%FT%TZ)" >> "$W/progress.txt"
