#!/bin/bash
# Pre-upload batch check: a last look over everything the pool put in _v7/ready/ BEFORE the user spends
# DataOS grades on it. Runs the deterministic gates once more per task (they should already pass - this
# catches drift), and with --deep also runs the strengthened Opus adversarial audit per task (the same one
# the lane runner uses), so the deep check lands on the ~40 that survived, not all 72 unattended.
# Usage: svc_v7_batch_precheck.sh [--deep]
set -uo pipefail
QC=/root/qc; WORK="$QC/_v7"; CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
PY=/root/venv/bin/python3
DEEP=0; [ "${1:-}" = "--deep" ] && DEEP=1
CB="$(command -v claude 2>/dev/null || echo /usr/bin/claude)"
REPORT="$WORK/precheck.txt"; : > "$REPORT"
say(){ echo "$*" | tee -a "$REPORT"; }

zips="$(ls "$WORK/ready/"*.zip 2>/dev/null)"
[ -n "$zips" ] || { say "no zips in $WORK/ready/"; exit 0; }
say "=== pre-upload batch check $(date -u +%FT%TZ)  deep=$DEEP ==="

pass=0; flag=0
for z in $zips; do
  T="$(basename "$z" .zip)"
  D="$CORPUS/$T"
  [ -d "$D" ] || { say "$T  FLAG  no corpus dir"; flag=$((flag+1)); continue; }
  notes=""
  # 1. prefilter (HARD defects must be zero)
  "$PY" "$QC/tools/svc_prefilter.py" "$D" >/dev/null 2>&1 || notes="$notes prefilter-HARD"
  # 2. growth guard vs the batch baseline that contains this task
  BASE=""
  for b in $(ls -t "$QC/_returns/"*_with_runs*.zip 2>/dev/null); do
    unzip -l "$b" 2>/dev/null | grep -q "$T/" && { BASE="$b"; break; }
  done
  if [ -n "$BASE" ]; then
    "$PY" "$QC/tools/svc_rubric_growth_diff.py" --current "$D" --baseline "$BASE" --task "$T" --fail-on-growth >/dev/null 2>&1 \
      || notes="$notes rubric-grew"
  else
    notes="$notes no-baseline"
  fi
  # 3. deep adversarial audit (optional): golden-satisfies-every-criterion + over/under-enforcement
  if [ "$DEEP" = "1" ]; then
    VP="Adversarially audit $T in $D against instruction.md and confirm the GOLDEN under solution/ itself satisfies EVERY criterion (a bare citation with no locator, a formula with no stored value, or a figure the golden does not actually contain all fail). End with 'VERDICT: READY' only if the golden passes every criterion and no criterion over/under-enforces, else 'VERDICT: NOT-READY' and the defect."
    out="$( cd "$D" && CLAUDE_CODE_BIN="$CB" CLAUDE_CONFIG_DIR=/root/.claude-r timeout 1200 claude -p "$VP" --model opus --permission-mode dontAsk --allowedTools "Read,Bash,Glob,Grep" 2>/dev/null )"
    echo "$out" | grep -qi "VERDICT: *READY" || notes="$notes deep-NOT-READY"
    echo "$out" > "$WORK/precheck_$T.md"
  fi
  if [ -z "$notes" ]; then say "$T  PASS"; pass=$((pass+1)); else say "$T  FLAG $notes"; flag=$((flag+1)); fi
done
say "=== $pass pass, $flag flagged. Upload only the PASS set; FLAG tasks need a look (see $REPORT). ==="
