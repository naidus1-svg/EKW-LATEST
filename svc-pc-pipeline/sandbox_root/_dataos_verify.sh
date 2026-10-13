#!/bin/bash
# Self-waits for the directed fixer (FIX_DONE), then verifies each fixed task on the lanes:
# oracle (golden=1.0) + static (grammar/empty-dim) + softening guard (criterion count before vs after).
# Writes VERIFY_DONE when complete. Launch detached; a laptop watcher polls VERIFY_DONE.
set -u
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
W=/root/qc/_dataosfix
PY=/root/venv/bin/python3
export QC_REWARDKIT_SITE_PACKAGES=/root/venv/lib/python3.13/site-packages
LANES=(q r m v w c e f g i j k l p u)

# 1. wait for the fixer to finish
n=0
until grep -q FIX_DONE "$W/progress.txt" 2>/dev/null; do
  n=$((n + 1)); [ "$n" -ge 240 ] && break; sleep 20
done

# 2. verify each task
: > "$W/verify.txt"
idx=0
crit_count() { grep -rh "^\[\[criterion\]\]" "$1"/deliverables*/judge.toml 2>/dev/null | wc -l; }
for t in $(cat /root/qc/_wave1_rejects.txt); do
  lane="/root/.claude-${LANES[$((idx % ${#LANES[@]}))]}"; idx=$((idx + 1))
  (
    before=$(crit_count "$W/snap/$t/tests")
    after=$(crit_count "$CORPUS/$t/tests")
    st=$($PY /root/qc/tools/svc_rubric_static_check.py "$CORPUS/$t" --judge-only --quiet 2>/dev/null | tail -1)
    CLAUDE_CONFIG_DIR="$lane" timeout 900 "$PY" /root/qc/tools/judge_emulate.py oracle "$t" \
      --runs 1 --corpus-root "$CORPUS" --out "$W/oracle_$t.json" > "$W/oracle_$t.log" 2>&1
    orc=$("$PY" -c "import json
try: print(json.load(open('$W/oracle_$t.json')).get('total_reward'))
except Exception: print('ERR')" 2>/dev/null)
    echo "$t oracle=$orc static=${st%%:*} crit=$before->$after" >> "$W/verify.txt"
  ) &
  while [ "$(jobs -r | wc -l)" -ge 12 ]; do sleep 3; done
done
wait
echo "VERIFY_DONE $(date -u +%FT%TZ)" >> "$W/verify.txt"
