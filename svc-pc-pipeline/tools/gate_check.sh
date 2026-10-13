#!/usr/bin/env bash
# gate_check.sh TASK [TASKDIR] [LANE]
#
# Composable single-task packaging gate. Builds this task's deterministic-findings block
# (judge_schema_bytes.py, run live against TASKDIR), runs both severity-calibrated reviews
# (opus, sonnet) via gate_review.sh sequentially on one lane, then prints one line: PASS or
# BLOCK with the blocking reasons.
#
# TASKDIR defaults to /root/qc/sev2_corpus/TASK. Pass it explicitly for a task whose
# sev2_corpus copy is known or suspected stale relative to what DataOS actually graded -
# see /root/qc/_prompts/gate-backtest/RESULT.md's corpus-provenance section.
# SVC-PC-38-1-0 is the confirmed case in this backtest:
#   gate_check.sh SVC-PC-38-1-0 /root/qc/_prompts/gate-backtest/scratch_realzip_38-1-0/SVC-PC-38-1-0
#
# LANE (a CLAUDE_CONFIG_DIR path, e.g. /root/.claude-q) is auto-picked from the allowed
# pool (q r m v w b c d e f g i j k l, skipping .benched/.limited_until) if not given. One
# lane is enough here since the two review calls run sequentially, not concurrently.
set -u
TASK="${1:-}"
TASKDIR="${2:-/root/qc/sev2_corpus/$TASK}"
LANE="${3:-}"
if [ -z "$TASK" ]; then
  echo "usage: gate_check.sh TASK [TASKDIR] [LANE]" >&2
  exit 1
fi
HERE=/root/qc/_prompts/gate-backtest
TOOLS=/root/qc/tools
REVIEWS_DIR=$HERE/reviews
mkdir -p "$REVIEWS_DIR" "$HERE/detfindings"

if [ -z "$LANE" ]; then
  for letter in q r m v w b c d e f g i j k l; do
    base=".claude-$letter"
    if [ ! -f "/root/qc/lanes/${base}.benched" ]; then
      lu="/root/qc/lanes/${base}.limited_until"
      if [ -f "$lu" ]; then
        ts=$(tr -dc 0-9 < "$lu" 2>/dev/null); ts=${ts:-0}
        if [ "$ts" -gt "$(date +%s)" ] 2>/dev/null; then continue; fi
      fi
      LANE="/root/.claude-$letter"
      break
    fi
  done
fi
if [ -z "$LANE" ]; then
  echo "ERROR: no free lane found in the allowed pool (q r m v w b c d e f g i j k l)" >&2
  exit 1
fi
echo "Using lane $LANE for $TASK (taskdir=$TASKDIR)" >&2

python3 "$TOOLS/gate_detfindings.py" "$TASK" "$TASKDIR" "$HERE/detfindings/$TASK.md" >&2
bash "$TOOLS/gate_review.sh" "$TASK" opus   "$LANE" "$REVIEWS_DIR/$TASK.opus.json"   >&2
bash "$TOOLS/gate_review.sh" "$TASK" sonnet "$LANE" "$REVIEWS_DIR/$TASK.sonnet.json" >&2
python3 "$TOOLS/gate_verdict.py" "$TASK" "$TASKDIR" "$REVIEWS_DIR"
