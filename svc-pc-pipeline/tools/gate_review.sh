#!/usr/bin/env bash
# gate_review.sh TASK REVIEWER(opus|sonnet) LANE OUT_JSON
#
# Variant of /root/qc/tools/v3digest_review.sh (read-only source, never edited) for the
# gate-backtest severity-calibrated review. One task, one reviewer, one digest-mode review
# call, identical mechanics to v3digest_review.sh (same digest, same canon, same addendum,
# same claude -p invocation, same retry-once-then-TOO_LARGE/MISSING logic, same extractor),
# with two gate-only additions inserted into the prompt by gate_build_prompt.py:
#   - the gate calibration note (/root/qc/_prompts/gate-backtest/gate-calibration-note.md)
#   - this task's deterministic-findings block
#     (/root/qc/_prompts/gate-backtest/detfindings/<task>.md, must exist - build it first
#     with gate_detfindings.py)
#
# Requires the SAME cited-mode digest v3digest_build.py already built at
# /root/qc/_prompts/v3digest/digests_cited/<task>.md (reused read-only; this script never
# rebuilds a digest, since the graded bytes and the digest-build mechanics are unchanged
# from the v3digest measurement).
set -u
TASK="$1"; REVIEWER="$2"; LANE="$3"; OUT_JSON="$4"
if [ -z "${TASK:-}" ] || [ -z "${REVIEWER:-}" ] || [ -z "${OUT_JSON:-}" ]; then
  echo "usage: gate_review.sh TASK REVIEWER(opus|sonnet) LANE OUT_JSON" >&2
  exit 1
fi
case "$REVIEWER" in
  opus|sonnet) ;;
  *) echo "REVIEWER must be opus or sonnet, got: $REVIEWER" >&2; exit 1 ;;
esac

TOOLS_DIR=/root/qc/tools
CANON=$TOOLS_DIR/prompts/ekwqc/ekw-svc-comprehensive-review.workspace-mode.md
ADDENDUM=/root/qc/_prompts/fable-severity/severity-addendum-v2.md
CALIB=/root/qc/_prompts/gate-backtest/gate-calibration-note.md
DETF=/root/qc/_prompts/gate-backtest/detfindings/$TASK.md
DIGEST=/root/qc/_prompts/v3digest/digests_cited/$TASK.md
PROMPT_DIR=/root/qc/_prompts/gate-backtest/prompts
STATS_JSON="${OUT_JSON%.json}.stats.json"
mkdir -p "$PROMPT_DIR" "$(dirname "$OUT_JSON")"
rm -f "$STATS_JSON"  # fresh per invocation

for f in "$DIGEST" "$CANON" "$ADDENDUM" "$CALIB" "$DETF"; do
  if [ ! -f "$f" ]; then
    echo "ERROR: required input not found: $f" >&2
    exit 2
  fi
done

PROMPT_FILE="$PROMPT_DIR/$TASK.$REVIEWER.prompt.txt"
python3 "$TOOLS_DIR/gate_build_prompt.py" "$CANON" "$ADDENDUM" "$CALIB" "$DETF" "$DIGEST" "$PROMPT_FILE" || exit 3

looks_too_large() {
  echo "$1" | grep -qiE "prompt is too long|too many tokens|context length|context window|maximum context|exceeds the model.?s context|input length|request too large"
}

run_attempt() {  # $1 = attempt number -> sets ATTEMPT_OK=0/1
  local n="$1"
  local raw="${OUT_JSON}.raw.attempt${n}.json"
  local err="${OUT_JSON}.attempt${n}.stderr.txt"
  local start end wall
  start=$(date +%s)
  if [ -n "$LANE" ]; then
    CLAUDE_CONFIG_DIR="$LANE" claude -p --model "$REVIEWER" --tools "" \
      --output-format json --permission-mode dontAsk \
      < "$PROMPT_FILE" > "$raw" 2> "$err"
  else
    claude -p --model "$REVIEWER" --tools "" \
      --output-format json --permission-mode dontAsk \
      < "$PROMPT_FILE" > "$raw" 2> "$err"
  fi
  end=$(date +%s)
  wall=$((end - start))
  python3 "$TOOLS_DIR/v3digest_extract_result.py" "$raw" "$err" "$TASK" "$REVIEWER" "$n" "$wall" "$OUT_JSON" "$STATS_JSON"
  ATTEMPT_OK=$?
}

echo "$(date -u +%FT%TZ) START $TASK $REVIEWER lane=$([ -n "$LANE" ] && basename "$LANE" || echo none)"
run_attempt 1
if [ "$ATTEMPT_OK" -eq 0 ]; then
  echo "$(date -u +%FT%TZ) FINISH $TASK $REVIEWER attempt=1 canonical"
  exit 0
fi
echo "$(date -u +%FT%TZ) RETRY $TASK $REVIEWER (attempt 1 failed or non-canonical)"
run_attempt 2
if [ "$ATTEMPT_OK" -eq 0 ]; then
  echo "$(date -u +%FT%TZ) FINISH $TASK $REVIEWER attempt=2 canonical"
  exit 0
fi

STATUS="MISSING"
if [ -f "$STATS_JSON" ]; then
  ERRTEXT=$(python3 -c "
import json
d = json.load(open('$STATS_JSON'))
print('\n'.join(a.get('error_verbatim') or '' for a in d.get('attempts', [])))
" 2>/dev/null)
  if looks_too_large "$ERRTEXT"; then
    STATUS="TOO_LARGE"
  fi
fi
python3 -c "
import json
p = '$STATS_JSON'
d = json.load(open(p))
d['status'] = '$STATUS'
json.dump(d, open(p, 'w'), indent=2)
" 2>/dev/null
echo "$(date -u +%FT%TZ) $STATUS $TASK $REVIEWER (failed or non-canonical after 2 attempts)"
exit 4
