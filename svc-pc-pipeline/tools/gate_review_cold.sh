#!/usr/bin/env bash
# gate_review_cold.sh TASK REVIEWER(opus|sonnet) LANE OUT_JSON
#
# COLD-revalidation copy of /root/qc/tools/gate_review.sh (which is left unmodified).
# Same mechanics (same claude -p invocation, same retry-once-then-TOO_LARGE/MISSING
# logic, same extractor) with three inputs redirected so nothing fed to the reviewer can
# name or answer for any of the 10 batch-10 tasks:
#   - ADDENDUM  -> severity-addendum-clean.md (task IDs, eval/review numbers and quoted
#                  per-task majors stripped; general rules and generalized calibration
#                  principles kept)
#   - CALIB     -> gate-calibration-note-clean.md (pointer; the real calibration content
#                  now lives inside the clean addendum's own section, decontaminated)
#   - DIGEST    -> /root/qc/_prompts/gate-revalidate/digests/<task>.md, built FRESH from
#                  the exact graded/ bytes (never the stale v3digest/digests_cited/ copy,
#                  which predates graded/ by ~3 hours and inherits the same corpus-
#                  provenance problem the prior backtest already found)
# CANON is unchanged (general review spec, not task-specific, read-only).
set -u
TASK="$1"; REVIEWER="$2"; LANE="$3"; OUT_JSON="$4"
if [ -z "${TASK:-}" ] || [ -z "${REVIEWER:-}" ] || [ -z "${OUT_JSON:-}" ]; then
  echo "usage: gate_review_cold.sh TASK REVIEWER(opus|sonnet) LANE OUT_JSON" >&2
  exit 1
fi
case "$REVIEWER" in
  opus|sonnet) ;;
  *) echo "REVIEWER must be opus or sonnet, got: $REVIEWER" >&2; exit 1 ;;
esac

TOOLS_DIR=/root/qc/tools
HERE=/root/qc/_prompts/gate-revalidate
CANON=$TOOLS_DIR/prompts/ekwqc/ekw-svc-comprehensive-review.workspace-mode.md
ADDENDUM=$HERE/severity-addendum-clean.md
CALIB=$HERE/gate-calibration-note-clean.md
DETF=$HERE/detfindings/$TASK.md
DIGEST=$HERE/digests/$TASK.md
PROMPT_DIR=$HERE/prompts
STATS_JSON="${OUT_JSON%.json}.stats.json"
mkdir -p "$PROMPT_DIR" "$(dirname "$OUT_JSON")"
rm -f "$STATS_JSON"  # fresh per invocation

for f in "$DIGEST" "$CANON" "$ADDENDUM" "$CALIB" "$DETF"; do
  if [ ! -f "$f" ]; then
    echo "ERROR: required input not found: $f" >&2
    exit 2
  fi
done

PROMPT_FILE="$PROMPT_DIR/$(basename "${OUT_JSON%.json}").prompt.txt"
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

echo "$(date -u +%FT%TZ) START $TASK $REVIEWER lane=$([ -n "$LANE" ] && basename "$LANE" || echo none) out=$(basename "$OUT_JSON")"
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
