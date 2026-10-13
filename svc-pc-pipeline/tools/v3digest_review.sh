#!/usr/bin/env bash
# v3digest_review.sh TASK REVIEWER(opus|sonnet) LANE OUT_JSON
#
# One task, one reviewer, one digest-mode review call. Builds the prompt
# (digest-mode note + canon review spec + severity-addendum-v2.md + this
# task's digest + closing instruction, via v3digest_build_prompt.py), runs
# `claude -p --model REVIEWER --tools "" --output-format json
# --permission-mode dontAsk` on LANE (CLAUDE_CONFIG_DIR=LANE, or the
# ambient account if LANE is ""), fed the prompt on stdin (never as an
# argument - these prompts run hundreds of KB to tens of MB). Extracts and
# validates the canonical CR JSON via v3digest_extract_result.py. Retries
# once (same LANE - lane re-picking across attempts is the PILOT's job, not
# this per-call script's) on a failed or non-canonical result. Writes
# OUT_JSON only on a canonical result; always writes OUT_JSON's
# ".stats.json" sidecar (usage, cost, wall seconds, both attempts).
#
# If both attempts fail AND either attempt's verbatim error mentions a
# context/length limit, marks the sidecar status TOO_LARGE instead of
# MISSING - the caller (v3digest_pilot.sh) reads this to decide whether more
# than 3 tasks need a --budget rebuild.
#
# claude -p is invoked with the prompt on STDIN per this task's own hard
# rule (prompts run hundreds of KB), --tools "" (no tools - single-shot
# read), --permission-mode dontAsk (never --dangerously-skip-permissions,
# refused for root; never bare, which would block on a permission prompt
# with stdin already consumed by the prompt).
set -u
TASK="$1"; REVIEWER="$2"; LANE="$3"; OUT_JSON="$4"
if [ -z "${TASK:-}" ] || [ -z "${REVIEWER:-}" ] || [ -z "${OUT_JSON:-}" ]; then
  echo "usage: v3digest_review.sh TASK REVIEWER(opus|sonnet) LANE OUT_JSON" >&2
  exit 1
fi
case "$REVIEWER" in
  opus|sonnet) ;;
  *) echo "REVIEWER must be opus or sonnet, got: $REVIEWER" >&2; exit 1 ;;
esac

TOOLS_DIR=/root/qc/tools
CANON=$TOOLS_DIR/prompts/ekwqc/ekw-svc-comprehensive-review.workspace-mode.md
ADDENDUM=/root/qc/_prompts/fable-severity/severity-addendum-v2.md
DIGEST=/root/qc/_prompts/v3digest/digests_cited/$TASK.md
PROMPT_DIR=/root/qc/_prompts/v3digest/prompts
STATS_JSON="${OUT_JSON%.json}.stats.json"
mkdir -p "$PROMPT_DIR" "$(dirname "$OUT_JSON")"
rm -f "$STATS_JSON"  # fresh per invocation - this script owns its own sidecar, not an accumulation across pilot re-runs

if [ ! -f "$DIGEST" ]; then
  echo "ERROR: digest not found: $DIGEST (run v3digest_build.py first)" >&2
  exit 2
fi
if [ ! -f "$CANON" ]; then
  echo "ERROR: canon review spec not found: $CANON" >&2
  exit 2
fi
if [ ! -f "$ADDENDUM" ]; then
  echo "ERROR: severity addendum not found: $ADDENDUM" >&2
  exit 2
fi

PROMPT_FILE="$PROMPT_DIR/$TASK.$REVIEWER.prompt.txt"
python3 "$TOOLS_DIR/v3digest_build_prompt.py" "$CANON" "$ADDENDUM" "$DIGEST" "$PROMPT_FILE" || exit 3

looks_too_large() {  # $1 = verbatim error text; heuristic match on known context/length phrasings
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

# Both attempts failed. Decide TOO_LARGE vs MISSING from the verbatim errors
# recorded by v3digest_extract_result.py in the stats sidecar.
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
