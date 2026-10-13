#!/usr/bin/env bash
# Third DataOS-majors fixer pass, run to completion over lanes/FIX_FROM_DATAOS_R3_TARGETS (one task id per line, SVC-PC- prefix).
# Why (2026-09-19 20:50Z): fix_from_dataos.sh SKIPs a task whose fix lock is held and never retries it, and three of the nine
# targets were inside fix-from-reviews cycles at launch. Each iteration: rebuild the frozen fixer copies from the current
# rulings (tools/build_fixer_copies.py), clear DATAOS_MAJORS_1 on every target that is free and not yet done in this pass,
# shelve the previous pass's CR.*.dataos.* artifacts, run the fixer once (synchronously, it waits for its re-reviews), then
# mark R3_DONE on every target it re-marked. Stops when every target is done or after MAX_ITER iterations. Re-reads the
# targets file each iteration, so ids can be appended while it runs (5-4-0 and 88-0-0 join after the verify loop rules them).
# Launch: (setsid nohup bash tools/fix_from_dataos_r3.sh > _prompts/fix_from_dataos_r3.nohup.log 2>&1 < /dev/null &)
set -u
cd /root/qc || exit 1
T=lanes/FIX_FROM_DATAOS_R3_TARGETS
LOG=_prompts/fix_from_dataos_r3_wrapper.log
FRESH=/root/qc/_prompts/verify/dataos-fresh
MAX_ITER="${MAX_ITER:-10}"
SLEEP="${SLEEP:-300}"
log() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }
held() { python3 - "$1" <<'PY'
import fcntl, os, sys
lp = f"/root/qc/stream-pipe/{sys.argv[1]}/fix_from_reviews.lock"
if not os.path.exists(lp):
    sys.exit(1)
try:
    fd = os.open(lp, os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    fcntl.flock(fd, fcntl.LOCK_UN)
    sys.exit(1)
except OSError:
    sys.exit(0)
PY
}
log "R3 START pid=$$ targets=$(grep -c . "$T") max_iter=$MAX_ITER sleep=$SLEEP"
for i in $(seq 1 "$MAX_ITER"); do
  python3 tools/build_fixer_copies.py --fresh "$FRESH" >> "$LOG" 2>&1 || { log "copy rebuild failed, abort"; exit 2; }
  set=()
  pend=0
  while IFS= read -r t; do
    t="${t%%#*}"; t="$(echo "$t" | tr -d '[:space:]')"; [ -n "$t" ] || continue
    d="stream-pipe/$t"; [ -d "$d" ] || { log "iter $i: no such task dir $t"; continue; }
    [ -f "$d/R3_DONE" ] && continue
    pend=$((pend + 1))
    if held "$t"; then log "iter $i: $t lock held, wait"; continue; fi
    sed -i '/^DATAOS_MAJORS_1$/d' "$d/STATE"
    st=$(date -u +%H%M%S)
    for f in "$d"/CR.glm.dataos.* "$d"/CR.sonnet.dataos.* "$d"/CR.union.dataos.json "$d"/FILES_TEXT_dataos.txt; do
      [ -e "$f" ] && mv "$f" "$f.r3-$st"
    done
    set+=("$t")
  done < "$T"
  if [ "$pend" -eq 0 ]; then log "R3 ALL DONE after $((i - 1)) iteration(s)"; exit 0; fi
  if [ "${#set[@]}" -gt 0 ]; then
    log "iter $i: running fixer on ${set[*]}"
    DATAOS_STATUS_CSV="$FRESH/fixer/status.csv" DATAOS_MAJORS_CSV="$FRESH/fixer/majors.csv" \
      FIX_FROM_DATAOS_LOG=/root/qc/_prompts/fix_from_dataos_fresh3.log FIX_FROM_DATAOS_CONC="${FIX_FROM_DATAOS_CONC:-4}" \
      bash tools/fix_from_dataos.sh >> _prompts/fix_from_dataos_fresh3.nohup.log 2>&1 < /dev/null
    for t in "${set[@]}"; do
      if grep -qx DATAOS_MAJORS_1 "stream-pipe/$t/STATE"; then touch "stream-pipe/$t/R3_DONE"; log "iter $i: $t done"
      else log "iter $i: $t not re-marked (skipped or failed), retry next iteration"; fi
    done
  else
    log "iter $i: nothing free ($pend pending)"
  fi
  sleep "$SLEEP"
done
log "R3 STOP after $MAX_ITER iterations with $pend target(s) pending"
