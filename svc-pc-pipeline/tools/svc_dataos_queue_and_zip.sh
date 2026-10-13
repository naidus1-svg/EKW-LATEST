#!/bin/bash
# Self-sequencing queue: wait for the current (round-1, 7-task) overnight run to finish, snapshot its
# results, then run the 17 dual-basis fixes, then build DataOS resubmit zips from BOTH rounds' locally
# verified (oracle-1.0 + deterministic-clean) task sets. Fire-and-forget; the laptop launches it detached.
# Building the zip is allowed; UPLOAD stays the user's action.
#
# $1 = the 17-task dual-basis list file (briefs already pushed to /root/qc/_targeted/).
set -u
QC=/root/qc
W=$QC/_dataosfix
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
OUTZIP=$QC/_zips
mkdir -p "$OUTZIP"
LIST17="$1"
LOG=$QC/_queue.log
log() { echo "[queue $(date -u +%FT%TZ)] $*" >> "$LOG"; }

log "START; waiting for round-1 (7-task) OVERNIGHT_DONE (cap 90 min)"
# 1) wait for the current round: overnight.sh writes OVERNIGHT_DONE to progress.txt at the very end,
#    AFTER ready.txt. External marker, confirmed to exist -> legitimate poll.
done1=0
for _ in $(seq 1 90); do
  if grep -q "OVERNIGHT_DONE" "$W/progress.txt" 2>/dev/null; then done1=1; break; fi
  sleep 60
done
if [ "$done1" -ne 1 ]; then log "round-1 did not finish within 90 min; aborting"; exit 1; fi

# 2) snapshot round-1 results BEFORE the 17-round reuses (and clobbers) the shared work dir
cp -f "$W/ready.txt" "$QC/_round1_ready.txt" 2>/dev/null || : > "$QC/_round1_ready.txt"
cp -f "$W/held.txt" "$QC/_round1_held.txt" 2>/dev/null || :
log "round-1 ready=$(wc -l < "$QC/_round1_ready.txt" 2>/dev/null || echo 0); starting 17 dual-basis fixes (opus)"

# 3) run the 17 dual-basis fixes + deterministic/oracle verify (reuses overnight.sh; briefs in _targeted/)
bash "$QC/svc_dataos_overnight.sh" "$LIST17" opus
cp -f "$W/ready.txt" "$QC/_round2_ready.txt" 2>/dev/null || : > "$QC/_round2_ready.txt"
log "17-round ready=$(wc -l < "$QC/_round2_ready.txt" 2>/dev/null || echo 0)"

# 4) build a DataOS zip from each round's ready set (format = corpus task dirs, per _assemble_ready_wave.sh)
build() { # $1=ready-file  $2=zip-path
  local rf="$1" zn="$2"
  mapfile -t T < <(grep . "$rf" 2>/dev/null | sort -u)
  if [ "${#T[@]}" -eq 0 ]; then log "no ready tasks for $(basename "$zn"); skip"; return; fi
  rm -f "$zn"
  ( cd "$CORPUS" && zip -rq "$zn" "${T[@]}" )
  /root/venv/bin/python3 - "$zn" <<'PY' >> "$LOG" 2>&1
import zipfile, os, sys
z = zipfile.ZipFile(sys.argv[1])
bad = z.testzip()
tasks = sorted({n.split('/')[0] for n in z.namelist() if n.startswith('SVC-PC-')})
print(f"  built {sys.argv[1]}  bytes={os.path.getsize(sys.argv[1])}  testzip={bad}  tasks={len(tasks)}")
PY
}
TS=$(date -u +%Y%m%d-%H%M)
build "$QC/_round1_ready.txt" "$OUTZIP/resubmit-wave1round2-$TS.zip"
build "$QC/_round2_ready.txt" "$OUTZIP/dualbasis-17-$TS.zip"
log "QUEUE_DONE; zips in $OUTZIP"
ls -la "$OUTZIP" >> "$LOG" 2>&1
