#!/bin/bash
# Pre-ship deterministic gate: a task is SHIPPABLE only if all hard checks pass:
#   0. static: <=15 criteria per judge dir (grammar-too-large) + every dim has a grader
#      (svc_rubric_static_check). Runs FIRST, instant, catches the 1.8 grammar bomb our CLI
#      oracle FALSE-PASSES. This is the highest-value deterministic block (62/202 corpus fail it).
#   1. mojibake: no real corruption in the task's own judge.toml (--judge-only)
#   2. missing-file: no /app/_corpus_subtree path resolves to not_found (judge_input_gate)
#   3. oracle: golden total_reward >= 1.0 (judge_emulate, judge = rubric's claude-sonnet-4-6, CLI backend)
#      An oracle of None/ERR is a LOCAL-env limit (e.g. a render_source_pack.py reading the container's
#      /app path), NOT a golden defect, so it is flagged 'oracle-unverified', not blocked; only a
#      numeric oracle < 1.0 (golden fails its own rubric) hard-blocks.
# Catches the deterministically-checkable defect classes (1.8 grammar/packaging + golden-broken). Sandbox.
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
    ok=1; reasons=""; flags=""
    # 0. static (fast, fail early on the grammar bomb)
    st=$("$PY" /root/qc/tools/svc_rubric_static_check.py "$CORPUS/$t" --judge-only --quiet 2>/dev/null | tail -1)
    [ "${st#FAIL}" != "$st" ] && { ok=0; reasons="$reasons static"; }
    # 1. mojibake
    mj=$("$PY" /root/qc/tools/mojibake_check.py "$CORPUS/$t" --judge-only --quiet 2>/dev/null | tail -1)
    [ "$mj" = "FAIL" ] && { ok=0; reasons="$reasons mojibake"; }
    # 2. missing-file
    "$PY" /root/ekwqc/deterministic-checks/judge_input_gate.py "$t" --root "$CORPUS" --out "$W/jir/$t.json" > "$W/jir/$t.log" 2>&1
    ms=$("$PY" -c "import json;d=json.load(open('$W/jir/$t.json'))[0];print(d.get('status'))" 2>/dev/null)
    [ "$ms" = "fail" ] && { ok=0; reasons="$reasons missingfile"; }
    # 3. oracle (last, slow). None/ERR = locally unverifiable = flag, not block.
    CLAUDE_CONFIG_DIR="$lane" timeout 2400 "$PY" /root/qc/tools/judge_emulate.py oracle "$t" \
      --runs 1 --corpus-root "$CORPUS" --out "$W/oracle/$t.json" > "$W/oracle/$t.log" 2>&1
    orc=$("$PY" -c "import json;print(json.load(open('$W/oracle/$t.json')).get('total_reward'))" 2>/dev/null)
    case "$orc" in
      1.0|1|1.00) ;;
      ""|None|ERR) flags="$flags oracle-unverified" ;;
      *) ok=0; reasons="$reasons oracle=$orc" ;;
    esac
    echo "$t $([ $ok = 1 ] && echo SHIPPABLE || echo "BLOCK:$reasons")$flags | static=$st mojibake=$mj missing=$ms oracle=$orc" >> "$W/verdicts.txt"
  ) &
  while [ "$(jobs -r | wc -l)" -ge 14 ]; do sleep 2; done
done
wait
echo "ALL_DONE $(date -u +%FT%TZ)" >> "$W/verdicts.txt"
