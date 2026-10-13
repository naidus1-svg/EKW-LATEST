#!/usr/bin/env bash
# gate_backtest.sh
#
# Runs the severity-calibrated packaging gate (judge_schema_bytes.py + opus + sonnet
# gate_review.sh, cited-mode digest) on the 10 batch-10 tasks and prints the confusion
# matrix against DataOS's own batch-10 ground truth (Khiem's rule: zero-major review
# passes, 2-of-3 reviews passes the task). See RESULT.md for the full per-task detail,
# the corpus-provenance caveats, and what changed between the plain v3digest reviews and
# this calibrated gate.
#
# 10 tasks, one lane each (opus then sonnet, sequential per lane) => 10 in flight, 2 calls
# per lane, exactly the budget in this task's own instructions.
set -u
HERE=/root/qc/_prompts/gate-backtest
TOOLS=/root/qc/tools
REVIEWS_DIR=$HERE/reviews
mkdir -p "$REVIEWS_DIR" "$HERE/detfindings" "$HERE/logs"

# task -> taskdir. SVC-PC-38-1-0 is special-cased: see RESULT.md's corpus-provenance
# section. /root/qc/sev2_corpus/SVC-PC-38-1-0/tests/deliverables_03/judge.toml (12
# criteria, 3040 bytes, mtime 2026-09-19 04:02) is the batch-6-to-8 upload, not what
# DataOS graded in batch 10. DataOS's own review text says deliverables_03 "packs 24
# criteria"; /root/qc/out/pipe/SVC-PC-38-1-0.zip (built 2026-09-19 22:03) has exactly 24
# criteria there, compiling to 4574 bytes (over the 4000-byte block threshold) - extracted
# once, read-only from then on, to scratch_realzip_38-1-0/.
declare -A TASKDIR=(
  [SVC-PC-11-4-0]=/root/qc/sev2_corpus/SVC-PC-11-4-0
  [SVC-PC-12-6-0]=/root/qc/sev2_corpus/SVC-PC-12-6-0
  [SVC-PC-73-2-0]=/root/qc/sev2_corpus/SVC-PC-73-2-0
  [SVC-PC-17-2-0]=/root/qc/sev2_corpus/SVC-PC-17-2-0
  [SVC-PC-17-7-0]=/root/qc/sev2_corpus/SVC-PC-17-7-0
  [SVC-PC-2-6-0]=/root/qc/sev2_corpus/SVC-PC-2-6-0
  [SVC-PC-21-3-0]=/root/qc/sev2_corpus/SVC-PC-21-3-0
  [SVC-PC-67-3-0]=/root/qc/sev2_corpus/SVC-PC-67-3-0
  [SVC-PC-9-5-0]=/root/qc/sev2_corpus/SVC-PC-9-5-0
  [SVC-PC-38-1-0]=/root/qc/_prompts/gate-backtest/scratch_realzip_38-1-0/SVC-PC-38-1-0
)
declare -A DATAOS=(
  [SVC-PC-11-4-0]=ACCEPT
  [SVC-PC-12-6-0]=ACCEPT
  [SVC-PC-73-2-0]=ACCEPT
  [SVC-PC-17-2-0]=REJECT
  [SVC-PC-17-7-0]=REJECT
  [SVC-PC-2-6-0]=REJECT
  [SVC-PC-21-3-0]=REJECT
  [SVC-PC-67-3-0]=REJECT
  [SVC-PC-9-5-0]=REJECT
  [SVC-PC-38-1-0]=REJECT
)
TASKS=(SVC-PC-11-4-0 SVC-PC-12-6-0 SVC-PC-73-2-0 SVC-PC-17-2-0 SVC-PC-17-7-0 SVC-PC-2-6-0 SVC-PC-21-3-0 SVC-PC-67-3-0 SVC-PC-9-5-0 SVC-PC-38-1-0)

is_lane_free() {  # $1 = letter
  local base=".claude-$1"
  [ -f "/root/qc/lanes/${base}.benched" ] && return 1
  local lu="/root/qc/lanes/${base}.limited_until"
  if [ -f "$lu" ]; then
    local ts
    ts=$(tr -dc 0-9 < "$lu" 2>/dev/null); ts=${ts:-0}
    if [ "$ts" -gt "$(date +%s)" ] 2>/dev/null; then return 1; fi
  fi
  return 0
}

echo "=== 1. deterministic findings ==="
for t in "${TASKS[@]}"; do
  python3 "$TOOLS/gate_detfindings.py" "$t" "${TASKDIR[$t]}" "$HERE/detfindings/$t.md"
done

echo
echo "=== 2. lane pool ==="
LANES=()
for letter in q r m v w b c d e f g i j k l; do
  if is_lane_free "$letter"; then
    LANES+=("/root/.claude-$letter")
  fi
  [ "${#LANES[@]}" -ge "${#TASKS[@]}" ] && break
done
if [ "${#LANES[@]}" -lt "${#TASKS[@]}" ]; then
  echo "ERROR: only ${#LANES[@]} free lanes in the allowed pool, need ${#TASKS[@]}" >&2
  exit 1
fi
echo "Lanes (1 per task, opus+sonnet sequential = 2 calls/lane, ${#LANES[@]} in flight): ${LANES[*]}"

echo
echo "=== 3. launching review calls ==="
PIDS=()
for i in "${!TASKS[@]}"; do
  t="${TASKS[$i]}"
  lane="${LANES[$i]}"
  (
    bash "$TOOLS/gate_review.sh" "$t" opus   "$lane" "$REVIEWS_DIR/$t.opus.json"
    bash "$TOOLS/gate_review.sh" "$t" sonnet "$lane" "$REVIEWS_DIR/$t.sonnet.json"
  ) > "$HERE/logs/$t.log" 2>&1 &
  PIDS+=("$!")
  echo "  launched $t on $(basename "$lane") (pid $!)"
done
echo "Waiting on ${#PIDS[@]} pipelines..."
wait "${PIDS[@]}"
echo "All review calls finished."

echo
echo "=== 4. verdicts ==="
declare -A GATE
TP=0; FN=0; TN=0; FP=0; INC=0
printf "%-16s %-8s %-10s %s\n" "task" "dataos" "gate" "reasons"
for t in "${TASKS[@]}"; do
  line=$(python3 "$TOOLS/gate_verdict.py" "$t" "${TASKDIR[$t]}" "$REVIEWS_DIR")
  gv=$(echo "$line" | sed -E 's/^[^:]+: ([A-Z]+).*/\1/')
  reasons=$(echo "$line" | sed -E 's/^[^:]+: [A-Z]+ ?//')
  GATE[$t]="$gv"
  d="${DATAOS[$t]}"
  printf "%-16s %-8s %-10s %s\n" "$t" "$d" "$gv" "$reasons"
  case "$d:$gv" in
    REJECT:BLOCK) TP=$((TP+1)) ;;
    REJECT:*) FN=$((FN+1)) ;;
    ACCEPT:PASS) TN=$((TN+1)) ;;
    ACCEPT:*) FP=$((FP+1)) ;;
  esac
  [ "$gv" = "INCOMPLETE" ] && INC=$((INC+1))
done

echo
echo "=== CONFUSION MATRIX ==="
echo "DataOS REJECT (7): gate BLOCKED $TP, gate missed $FN   -> recall = $TP/7"
echo "DataOS ACCEPT (3): gate PASSED  $TN, gate falsely blocked $FP   -> specificity = $TN/3"
if [ "$INC" -gt 0 ]; then
  echo "WARNING: $INC task(s) INCOMPLETE (a review call did not produce a canonical result) - not counted as PASS or BLOCK above without checking why"
fi
