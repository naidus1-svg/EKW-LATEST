#!/usr/bin/env bash
# gate_prod_run.sh TASKLIST_FILE
# Production severity gate on CURRENT bytes (03_dataos_ready), mirroring the proven
# gate_backtest_cold.sh but: task list from a file, live taskdirs (not the graded snapshot),
# digest+detfindings built from current bytes, PASS/FAIL by rule (no hardcoded DataOS truth).
# Fires 4 calls/task (opus x2, sonnet x2) round-robin across the lane pool, ~3 per account, in
# parallel to hit ~50-60 concurrency, then writes a verdict per task to fleet/verdicts/.
# Idempotent: skips a call whose OUT_JSON is already canonical, so it is safe to re-run.
# Launch detached so it survives an ssh drop:
#   (setsid nohup bash /root/qc/gate_prod_run.sh /root/qc/fleet/tasks.txt > /root/qc/fleet/prod_run.out 2>&1 &)
set -u
HERE=/root/qc/_prompts/gate-revalidate
TOOLS=/root/qc/tools
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
FLEET=/root/qc/fleet
REVIEWS=$FLEET/reviews
DIGESTS=$HERE/digests
DETFDIR=$HERE/detfindings
mkdir -p "$REVIEWS" "$DIGESTS" "$DETFDIR" "$HERE/logs" "$HERE/prompts" "$FLEET/verdicts" "$FLEET/ready"

TASKLIST="${1:?usage: gate_prod_run.sh TASKLIST_FILE}"
mapfile -t TASKS < <(grep -vE '^[[:space:]]*(#|$)' "$TASKLIST")
[ "${#TASKS[@]}" -gt 0 ] || { echo "no tasks in $TASKLIST" >&2; exit 1; }
log(){ echo "$(date -u +%FT%TZ) $*"; }

# 1. build inputs from CURRENT bytes (skip if already present)
log "=== build digests + detfindings for ${#TASKS[@]} tasks (current bytes) ==="
for t in "${TASKS[@]}"; do
  td="$CORPUS/$t"
  if [ ! -d "$td" ]; then log "SKIP $t: no taskdir $td"; continue; fi
  if [ ! -f "$DIGESTS/$t.md" ]; then
    log "digest $t"; python3 "$TOOLS/v3digest_build.py" "$td" "$DIGESTS/$t.md" >"$HERE/logs/$t.digest.log" 2>&1 || log "digest FAILED $t (see $HERE/logs/$t.digest.log)"
  fi
  if [ ! -f "$DETFDIR/$t.md" ]; then
    log "detf $t"; python3 "$TOOLS/gate_detfindings.py" "$t" "$td" "$DETFDIR/$t.md" >"$HERE/logs/$t.detf.log" 2>&1 || log "detf FAILED $t (see $HERE/logs/$t.detf.log)"
  fi
done

# 2. lane pool (skip benched / rate-limited)
lane_free(){ local b=".claude-$1"; [ -f "/root/qc/lanes/$b.benched" ] && return 1; local lu="/root/qc/lanes/$b.limited_until"; if [ -f "$lu" ]; then local ts; ts=$(tr -dc 0-9 <"$lu" 2>/dev/null); ts=${ts:-0}; [ "$ts" -gt "$(date +%s)" ] 2>/dev/null && return 1; fi; return 0; }
ACCTS=(); for L in q r m v w b c d e f g i j k l n p t u; do lane_free "$L" && ACCTS+=("/root/.claude-$L"); done
[ "${#ACCTS[@]}" -ge 6 ] || { log "ERROR only ${#ACCTS[@]} free lanes"; exit 1; }

is_canonical(){ [ -f "$1" ] && python3 -c "import json,sys
try: j=json.load(open('$1'))
except Exception: sys.exit(1)
sys.exit(0 if j.get('overall_verdict') in ('accept','reject','invalid','needs_revision') and isinstance(j.get('checks'),list) and j['checks'] and isinstance(j.get('major_count'),int) else 1)" 2>/dev/null; }

# 3. build the 52-call job list and launch round-robin (~3/account), in parallel
JOBS=()
for t in "${TASKS[@]}"; do
  [ -f "$DIGESTS/$t.md" ] || { log "no digest for $t, excluded from run"; continue; }
  JOBS+=("$t opus 1" "$t opus 2" "$t sonnet 1" "$t sonnet 2")
done
log "=== launching ${#JOBS[@]} calls across ${#ACCTS[@]} accounts (~$(( (${#JOBS[@]}+${#ACCTS[@]}-1)/${#ACCTS[@]} ))/account) ==="
PIDS=(); k=0
for job in "${JOBS[@]}"; do
  set -- $job; t="$1"; r="$2"; run="$3"
  out="$REVIEWS/$t.$r.run$run.json"
  if is_canonical "$out"; then log "skip $t $r run$run (canonical)"; continue; fi
  lane="${ACCTS[$(( k % ${#ACCTS[@]} ))]}"; k=$((k+1))
  ( bash "$TOOLS/gate_review_cold.sh" "$t" "$r" "$lane" "$out" ) >"$HERE/logs/$t.$r.run$run.log" 2>&1 &
  PIDS+=("$!")
  [ $(( k % ${#ACCTS[@]} )) -eq 0 ] && sleep 2   # stagger each full round to avoid a launch spike
done
log "launched ${#PIDS[@]} calls; waiting"
wait 2>/dev/null
log "=== all review calls done; computing verdicts ==="

# 4. verdict per task: BLOCK if schema-block OR any-run major. golden-citation recorded advisory.
for t in "${TASKS[@]}"; do
  td="$CORPUS/$t"; rm -f "$FLEET/verdicts/$t.PASS" "$FLEET/verdicts/$t.FAIL"
  why=""
  python3 "$TOOLS/judge_schema_bytes.py" "$td" --block 4000 --warn 3500 >/dev/null 2>&1 || why="schema"
  for rr in opus.run1 opus.run2 sonnet.run1 sonnet.run2; do
    f="$REVIEWS/$t.$rr.json"; [ -f "$f" ] || { why="$why missing:$rr"; continue; }
    mc=$(python3 -c "import json;print(json.load(open('$f')).get('major_count',0))" 2>/dev/null || echo 0)
    [ "${mc:-0}" -ge 1 ] 2>/dev/null && why="$why major:$rr"
  done
  gc=$(python3 "$TOOLS/golden_citation_scan.py" --task "$t" --corpus-root "$CORPUS" 2>/dev/null | tail -1)
  [ -n "$gc" ] && echo "$gc" > "$FLEET/verdicts/$t.citation"
  if echo "$why" | grep -q "major\|schema"; then
    echo "$why" > "$FLEET/verdicts/$t.FAIL"; log "FAIL $t ($why )"
  elif echo "$why" | grep -q "missing"; then
    echo "$why" > "$FLEET/verdicts/$t.INCOMPLETE"; log "INCOMPLETE $t ($why ) - re-run to fill"
  else
    echo pass > "$FLEET/verdicts/$t.PASS"; log "PASS $t"
  fi
done
log "=== verdicts in $FLEET/verdicts/ : PASS=$(ls "$FLEET/verdicts"/*.PASS 2>/dev/null|wc -l) FAIL=$(ls "$FLEET/verdicts"/*.FAIL 2>/dev/null|wc -l) INCOMPLETE=$(ls "$FLEET/verdicts"/*.INCOMPLETE 2>/dev/null|wc -l) ==="
