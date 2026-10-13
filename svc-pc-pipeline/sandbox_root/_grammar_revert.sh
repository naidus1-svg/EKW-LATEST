#!/bin/bash
# Revert unnecessary grammar splits: for each split task, if its PRE-split max criteria/dir <= MAX (20),
# the split was unnecessary (that count grades fine at DataOS), so restore the pre-split snapshot.
# Keep the split only where the pre-split max was a true bomb (> MAX).
set -u
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
SNAP=/root/qc/_grammar_snap
MAX=20
reverted=0; kept=0; rlist=""; klist=""
for d in "$SNAP"/SVC-PC-*/; do
  t=$(basename "$d")
  [ -d "$d/tests" ] || continue
  maxc=$(for j in "$d/tests/deliverables"*/judge.toml; do grep -c "^\[\[criterion\]\]" "$j" 2>/dev/null; done | sort -n | tail -1)
  maxc=${maxc:-0}
  if [ "$maxc" -le "$MAX" ]; then
    rm -rf "$CORPUS/$t/tests" && cp -a "$d/tests" "$CORPUS/$t/tests"
    reverted=$((reverted + 1)); rlist="$rlist $t(max=$maxc)"
  else
    kept=$((kept + 1)); klist="$klist $t(max=$maxc)"
  fi
done
echo "REVERTED (pre-split max <= $MAX, split was unnecessary): $reverted"
echo "$rlist" | tr " " "\n" | grep . | sort | tr "\n" " "; echo
echo "KEPT SPLIT (pre-split max > $MAX, real grammar bomb): $kept"
echo "$klist" | tr " " "\n" | grep . | sort | tr "\n" " "; echo
