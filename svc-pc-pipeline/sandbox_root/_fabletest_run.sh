#!/bin/bash
# Decisive test: does Fable catch 1.4/1.5 defects that DataOS's Opus seat (and ours) misses?
# 8 batch15 fail tasks (bytes already staged at _step0/corpus), reviewed by Fable AND Opus, workspace mode.
set -u
RWR=/root/qc/tools/run_workspace_review.py
CORPUS=/root/qc/_step0/corpus
W=/root/qc/_fabletest
rm -rf "$W"; mkdir -p "$W/out" "$W/ws" "$W/runs" "$W/pipe"
TASKS="SVC-PC-14-4-0 SVC-PC-15-2-0 SVC-PC-15-4-0 SVC-PC-26-8-0 SVC-PC-31-5-0 SVC-PC-46-3-0 SVC-PC-16-1-0 SVC-PC-82-1-0"
LANES=(q r m v w b c d e f g i j k l p t u)
i=0
for t in $TASKS; do
  for rev in fable opus; do
    lane="/root/.claude-${LANES[$((i % ${#LANES[@]}))]}"; i=$((i+1))
    out="$W/out/$t.$rev.json"
    ( CLAUDE_CONFIG_DIR="$lane" timeout 3000 python3 "$RWR" --task "$t" --corpus-root "$CORPUS" \
        --workspace-root "$W/ws/$t.$rev" --runs-root "$W/runs" --pipe-dir "$W/pipe/$t.$rev" \
        --out "$out" --stats-out "$W/out/$t.$rev.stats.json" --reviewer "$rev" --timeout 2700 \
        > "$W/out/$t.$rev.log" 2>&1
      echo "done $t $rev rc=$? lane=$(basename $lane)" >> "$W/progress.txt" ) &
  done
done
wait
echo "ALL_DONE $(date -u +%FT%TZ)" >> "$W/progress.txt"
