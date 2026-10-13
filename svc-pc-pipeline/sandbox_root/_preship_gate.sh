#!/bin/bash
# Pre-ship deterministic gate: a task is SHIPPABLE only if all three pass:
#   1. oracle: golden total_reward >= 1.0 (judge_emulate, judge = rubric's claude-sonnet-4-6, CLI backend)
#   2. mojibake: no real corruption in the task's own judge.toml (--judge-only)
#   3. missing-file: no /app/_corpus_subtree path resolves to not_found (judge_input_gate)
# Catches the ~26% deterministically-checkable defect classes (1.1 + 1.8). Runs on the sandbox.
set -u
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
W=/root/qc/_preship
rm -rf "$W"; mkdir -p "$W/oracle" "$W/jir"
: > "$W/verdicts.txt"
export QC_REWARDKIT_SITE_PACKAGES=/root/venv/lib/python3.13/site-packages
PY=/root/venv/bin/python3
LANES=(q r m v w c e f g i j k l p t u); idx=0
for t in "$@"; do
  lane="/root/.claude-${LANES[$((idx % ${#LANES[@]}))]}"; idx=$((idx+1))
  (
    ok=1; reasons=""
    CLAUDE_CONFIG_DIR="$lane" timeout 2400 "$PY" /root/qc/tools/judge_emulate.py oracle "$t" \
      --runs 1 --corpus-root "$CORPUS" --out "$W/oracle/$t.json" > "$W/oracle/$t.log" 2>&1
    orc=$("$PY" -c "import json;print(json.load(open('$W/oracle/$t.json')).get('total_reward'))" 2>/dev/null)
    case "$orc" in 1.0|1|1.00) ;; *) ok=0; reasons="$reasons oracle=$orc"; esac
    mj=$("$PY" /root/qc/tools/mojibake_check.py "$CORPUS/$t" --judge-only --quiet 2>/dev/null | tail -1)
    [ "$mj" = "FAIL" ] && { ok=0; reasons="$reasons mojibake"; }
    "$PY" /root/ekwqc/deterministic-checks/judge_input_gate.py "$t" --root "$CORPUS" --out "$W/jir/$t.json" > "$W/jir/$t.log" 2>&1
    ms=$("$PY" -c "import json;d=json.load(open('$W/jir/$t.json'))[0];print(d.get('status'))" 2>/dev/null)
    [ "$ms" = "fail" ] && { ok=0; reasons="$reasons missingfile"; }
    echo "$t $([ $ok = 1 ] && echo SHIPPABLE || echo "BLOCK:$reasons") | oracle=$orc mojibake=$mj missing=$ms" >> "$W/verdicts.txt"
  ) &
done
wait
echo "ALL_DONE $(date -u +%FT%TZ)" >> "$W/verdicts.txt"
