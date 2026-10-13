#!/usr/bin/env bash
# pool_build.sh TASKLIST [CAP=8]
# Parallel-build the digest + deterministic-findings for a task list, from CURRENT bytes.
# No claude/API use (pure local extraction), so it is safe to run alongside review runs.
# Idempotent: skips a task whose digest AND detfindings already exist.
set -u
HERE=/root/qc/_prompts/gate-revalidate
TOOLS=/root/qc/tools
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
mkdir -p "$HERE/digests" "$HERE/detfindings" "$HERE/logs"
LIST="${1:?usage: pool_build.sh TASKLIST [CAP]}"
CAP="${2:-8}"
built=0; skipped=0
while read -r t; do
  [ -n "$t" ] || continue
  case "$t" in \#*) continue;; esac
  td="$CORPUS/$t"
  if [ ! -d "$td" ]; then echo "skip $t: no taskdir"; continue; fi
  if [ -f "$HERE/digests/$t.md" ] && [ -f "$HERE/detfindings/$t.md" ]; then skipped=$((skipped+1)); continue; fi
  while [ "$(jobs -rp | wc -l)" -ge "$CAP" ]; do sleep 3; done
  (
    [ -f "$HERE/digests/$t.md" ]     || python3 "$TOOLS/v3digest_build.py" "$td" "$HERE/digests/$t.md" > "$HERE/logs/$t.digest.log" 2>&1
    [ -f "$HERE/detfindings/$t.md" ] || python3 "$TOOLS/gate_detfindings.py" "$t" "$td" "$HERE/detfindings/$t.md" > "$HERE/logs/$t.detf.log" 2>&1
    echo "$(date -u +%FT%TZ) built $t"
  ) &
  built=$((built+1))
done < "$LIST"
wait
echo "$(date -u +%FT%TZ) POOL BUILD DONE: attempted=$built pre-existing=$skipped"
