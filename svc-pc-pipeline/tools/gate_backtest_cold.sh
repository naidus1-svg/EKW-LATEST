#!/usr/bin/env bash
# gate_backtest_cold.sh
#
# Cold revalidation of the severity gate: graded/ bytes (the exact packages DataOS graded
# in batch 10), the decontaminated addendum, fresh digests built from graded/ (never the
# stale v3digest/digests_cited/ copy), 2 runs per model per task (opus x2, sonnet x2 = 4
# calls/task), sequential per lane, one lane per task (10 in flight).
#
# Requires digests already built (see gate_prebuild_digests_cold.sh or the one-off loop
# documented in RESULT-COLD.md) - this script does not build them itself, so a missing
# digest fails loudly instead of silently falling back to something stale.
set -u
HERE=/root/qc/_prompts/gate-revalidate
TOOLS=/root/qc/tools
GRADED=$HERE/graded
DIGESTS=$HERE/digests
REVIEWS_DIR=$HERE/reviews
mkdir -p "$REVIEWS_DIR" "$HERE/detfindings" "$HERE/logs" "$HERE/prompts"

TASKS=(SVC-PC-11-4-0 SVC-PC-12-6-0 SVC-PC-73-2-0 SVC-PC-17-2-0 SVC-PC-17-7-0 SVC-PC-2-6-0 SVC-PC-21-3-0 SVC-PC-67-3-0 SVC-PC-9-5-0 SVC-PC-38-1-0)

for t in "${TASKS[@]}"; do
  if [ ! -d "$GRADED/$t" ]; then
    echo "ERROR: graded taskdir missing for $t: $GRADED/$t" >&2
    exit 1
  fi
  if [ ! -f "$DIGESTS/$t.md" ]; then
    echo "ERROR: fresh digest missing for $t: $DIGESTS/$t.md (build it first)" >&2
    exit 1
  fi
done

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

echo "=== 1. deterministic findings (fresh, against graded/) ==="
for t in "${TASKS[@]}"; do
  python3 "$TOOLS/gate_detfindings.py" "$t" "$GRADED/$t" "$HERE/detfindings/$t.md"
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
echo "Lanes (1 per task, opus x2 + sonnet x2 sequential = 4 calls/lane, ${#LANES[@]} in flight): ${LANES[*]}"

is_canonical() {  # $1 = path to review json; exit 0 if canonical, 1 otherwise
  [ -f "$1" ] || return 1
  python3 -c "
import json, sys
try:
    j = json.load(open('$1'))
except Exception:
    sys.exit(1)
if j.get('overall_verdict') not in ('accept', 'reject', 'invalid', 'needs_revision'):
    sys.exit(1)
checks = j.get('checks')
if not isinstance(checks, list) or not checks:
    sys.exit(1)
if not isinstance(j.get('major_count'), int):
    sys.exit(1)
sys.exit(0)
" 2>/dev/null
}

run_if_needed() {  # task reviewer lane out_json
  local t="$1" reviewer="$2" lane="$3" out="$4"
  if is_canonical "$out"; then
    echo "SKIP $t $reviewer $(basename "$out") (already canonical, e.g. prior smoke test)"
    return 0
  fi
  bash "$TOOLS/gate_review_cold.sh" "$t" "$reviewer" "$lane" "$out"
}

echo
echo "=== 3. launching review calls (2 models x 2 runs x 10 tasks = 40 calls, skipping any already-canonical output) ==="
PIDS=()
for i in "${!TASKS[@]}"; do
  t="${TASKS[$i]}"
  lane="${LANES[$i]}"
  (
    for run in 1 2; do
      run_if_needed "$t" opus "$lane" "$REVIEWS_DIR/$t.opus.run$run.json"
    done
    for run in 1 2; do
      run_if_needed "$t" sonnet "$lane" "$REVIEWS_DIR/$t.sonnet.run$run.json"
    done
  ) > "$HERE/logs/$t.log" 2>&1 &
  PIDS+=("$!")
  echo "  launched $t on $(basename "$lane") (pid $!)"
done
echo "Waiting on ${#PIDS[@]} pipelines..."
wait "${PIDS[@]}"
echo "All review calls finished at $(date -u +%FT%TZ)."

echo
echo "=== 4. raw completion check ==="
for t in "${TASKS[@]}"; do
  for reviewer in opus sonnet; do
    for run in 1 2; do
      f="$REVIEWS_DIR/$t.$reviewer.run$run.json"
      if [ -f "$f" ]; then
        echo "  OK   $t $reviewer run$run"
      else
        echo "  MISS $t $reviewer run$run"
      fi
    done
  done
done
echo "COLD BACKTEST DONE. Run gate_verdict_cold.py next for the confusion matrices."
