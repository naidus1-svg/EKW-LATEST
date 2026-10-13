#!/bin/bash
# Few-shot severity-calibration test: run calibrated Opus + Fable (via --prompt-file) on the SAME
# batch15 tasks we have uncalibrated baselines for. 8 fails (recall) + 2 passes (precision).
# Compare to _fabletest (fails) and _prectest (passes) uncalibrated results.
set -u
RWR=/root/qc/tools/run_workspace_review.py
CORPUS=/root/qc/_step0/corpus                     # all batch15 tasks staged here
PROMPT=/root/qc/_calibrated_prompt.md             # scp'd calibrated prompt
W=/root/qc/_caltest
rm -rf "$W"; mkdir -p "$W/out" "$W/ws" "$W/runs" "$W/pipe"
FAILS="SVC-PC-14-4-0 SVC-PC-15-2-0 SVC-PC-15-4-0 SVC-PC-26-8-0 SVC-PC-31-5-0 SVC-PC-46-3-0 SVC-PC-16-1-0 SVC-PC-82-1-0"
PASSES="SVC-PC-12-1-0 SVC-PC-5-2-0"
TASKS="$FAILS $PASSES"
LANES=(q r m v w c e f g i j k l p t u)
idx=0
for t in $TASKS; do
  for rev in fable opus; do
    lane="/root/.claude-${LANES[$((idx % ${#LANES[@]}))]}"; idx=$((idx+1))
    ( CLAUDE_CONFIG_DIR="$lane" timeout 3000 python3 "$RWR" --task "$t" --corpus-root "$CORPUS" \
        --workspace-root "$W/ws/$t.$rev" --runs-root "$W/runs" --pipe-dir "$W/pipe/$t.$rev" \
        --out "$W/out/$t.$rev.json" --stats-out "$W/out/$t.$rev.stats.json" \
        --reviewer "$rev" --prompt-file "$PROMPT" --timeout 2700 \
        > "$W/out/$t.$rev.log" 2>&1
      echo "done $t $rev rc=$? lane=$(basename $lane)" >> "$W/progress.txt" ) &
  done
done
wait
echo "ALL_DONE $(date -u +%FT%TZ)" >> "$W/progress.txt"
