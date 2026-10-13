#!/usr/bin/env bash
# task_driver_ws.sh TASK LANE - ONE driver owns ONE task end to end, THE v4 PLAN WAY: workspace-mode
# comprehensive review (a real agent reading the task's files, never a text digest), three reviewers
# (opus, opus, glm), looping fix->re-review until every reviewer reports ZERO major, or UNFIXABLE.
# Handles ANY task size (no digest, no 10MB stdin limit -> the 95 "oversize" tasks go through here too).
#
# Verdict: a major from ANY reviewer is 100% unsubmittable -> fix. PASS = all three reviewers canonical
# AND major_count==0. A review that fails to produce a canonical verdict is TRANSIENT -> retried, never
# a silent pass and never an auto-drop. Hardened per adversarial review 2026-09-20 (F1-F5).
set -u
t="${1:?TASK}"; lane="${2:?LANE}"
Q=/root/qc; TOOLS=$Q/tools; FLEET=$Q/fleet
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready; TD="$CORPUS/$t"
VERD=$FLEET/verdicts; REVIEWS=$FLEET/wsreviews; RFAIL=$FLEET/reviewfail; FA=$FLEET/fixattempts
WSROOT=$FLEET/ws; RUNS=$FLEET/runs; PIPE=$FLEET/pipe
RWR=$TOOLS/run_workspace_review.py
CLAUDE_BIN="$(command -v claude || echo /usr/bin/claude)"
mkdir -p "$VERD" "$REVIEWS" "$RFAIL" "$FA" "$WSROOT" "$RUNS" "$PIPE" "$FLEET/driverlogs"
MAXATT=2            # fix attempts before UNFIXABLE - counted ON DISK ($FA/$t) so the cap holds across relaunches
REVIEW_TRIES=2      # in-round retries to get a canonical verdict from a reviewer
RFAIL_MAX=12        # flag REVIEW_STALLED for visibility after this many failures, but KEEP retrying
RTIMEOUT=2700       # per-review agent timeout (s)
FIXSLOTS=8          # max concurrent Opus fixes fleet-wide
REVIEWERS="opus:1 glm:1 glm:2"    # CAPACITY (user-approved 2026-09-20): 1 Opus (Max lane, the wall) +
                                  # 2 GLM (own proxy, no Max window) - halves Max burn per task, keeps
                                  # one Opus on the quality-critical checks. 3/3 zero-major bar unchanged.
DL="$FLEET/driverlogs/$t.log"
say(){ echo "$(date -u +%FT%TZ) [$t] $*" >> "$DL"; }
[ -d "$TD" ] || { echo "no taskdir" > "$VERD/$t.UNFIXABLE"; say "no taskdir"; exit 0; }

# F2: per-task lock. Structurally guarantees ONE driver per task regardless of any pool-side pidfile
# race or PID reuse, so two fixers can never edit $TD at once. Released when this process exits.
exec 9>"/run/qc_task.$t.lock"; flock -n 9 || { say "another driver already holds $t; exiting"; exit 0; }

# F3: canonical AND independently-derived major count. Rejects a review whose self-reported major_count
# disagrees with its own checks[] (an internally inconsistent LLM output), and rejects JSON booleans
# (isinstance(True,int) is True in Python). Prints the DERIVED count; non-canonical -> returns 1.
canon_mc(){ python3 -c "import json,sys
try: j=json.load(open('$1'))
except Exception: sys.exit(1)
if j.get('overall_verdict') not in ('accept','reject','invalid','needs_revision'): sys.exit(1)
ch=j.get('checks')
if not isinstance(ch,list) or not ch: sys.exit(1)
mc=j.get('major_count')
if type(mc) is not int: sys.exit(1)
real=sum(1 for c in ch if isinstance(c,dict) and c.get('severity')=='major')
if mc!=real: sys.exit(1)
print(real)" 2>/dev/null; }

run_review(){  # run_review REVIEWER RUN OUT
  local rev="$1" run="$2" out="$3" ws="$WSROOT/$t.$1$2" pd="$PIPE/$t.$1$2"
  mkdir -p "$ws" "$pd"
  CLAUDE_CONFIG_DIR="$lane" timeout -k 60 $((RTIMEOUT+180)) python3 "$RWR" \
    --task "$t" --corpus-root "$CORPUS" --workspace-root "$ws" --runs-root "$RUNS" \
    --pipe-dir "$pd" --out "$out" --stats-out "${out%.json}.stats.json" \
    --reviewer "$rev" --timeout "$RTIMEOUT" >> "$DL" 2>&1
}

review_and_tally(){  # runs/reuses the 3 reviews on current bytes; sets globals canon, anymajor, majtxt
  local spec rev run out try mc
  for spec in $REVIEWERS; do
    rev=${spec%%:*}; run=${spec##*:}; out="$REVIEWS/$t.$rev.run$run.json"
    if canon_mc "$out" >/dev/null && [ -z "$(find "$TD" -type f -newer "$out" -print -quit 2>/dev/null)" ]; then
      say "reuse $rev.run$run (bytes unchanged)"; continue
    fi
    rm -f "$out"
    for try in $(seq 1 "$REVIEW_TRIES"); do
      run_review "$rev" "run$run" "$out"
      canon_mc "$out" >/dev/null && break
      say "$rev.run$run not canonical (try $try), retrying"
    done
  done
  canon=0; anymajor=0; majtxt=""
  for spec in $REVIEWERS; do
    rev=${spec%%:*}; run=${spec##*:}; mc=$(canon_mc "$REVIEWS/$t.$rev.run$run.json")
    if [ -n "$mc" ]; then canon=$((canon+1)); [ "$mc" -ge 1 ] 2>/dev/null && { anymajor=1; majtxt="$majtxt $rev$run:$mc"; }; fi
  done
}

# Fix attempts are counted on disk (F4), so the MAXATT cap holds even when a driver defers its fix and a
# later relaunch continues the task; the loop's only exits are PASS, UNFIXABLE, transient, and defer.
while :; do
  say "workspace review (opus, opus, glm) on $(basename "$lane")"
  review_and_tally
  if [ "$canon" -lt 3 ]; then
    rf=$(cat "$RFAIL/$t" 2>/dev/null || echo 0); rf=$((rf+1)); echo "$rf" > "$RFAIL/$t"
    rm -f "$VERD/$t.PASS"
    say "only $canon/3 canonical reviews (rfail=$rf) - transient, leaving unverdicted to retry"
    [ "$rf" -ge "$RFAIL_MAX" ] && { echo "reviews failed $rf times; still retried, never auto-dropped" > "$VERD/$t.REVIEW_STALLED"; say "flagged REVIEW_STALLED at rfail=$rf"; }
    exit 0
  fi
  rm -f "$RFAIL/$t" "$VERD/$t.REVIEW_STALLED"
  if [ "$anymajor" -eq 0 ]; then
    rm -f "$VERD/$t.FAIL" "$VERD/$t.UNFIXABLE" "$FA/$t"; echo "pass 3/3 zero-major" > "$VERD/$t.PASS"
    say "PASS (3/3 canonical, zero majors) -> done"; exit 0
  fi
  echo "majors:$majtxt" > "$VERD/$t.FAIL"; say "FAIL (majors:$majtxt)"
  fa=$(cat "$FA/$t" 2>/dev/null || echo 0)
  if [ "$fa" -ge "$MAXATT" ]; then
    echo "majors remain after $fa fix attempts:$majtxt" > "$VERD/$t.UNFIXABLE"; rm -f "$VERD/$t.FAIL"
    say "UNFIXABLE after $fa fix attempts"; exit 0
  fi
  # admission control on the expensive Opus fix (reviews stay uncapped)
  FIXFD=""
  for s in $(seq 1 "$FIXSLOTS"); do
    exec {tryfd}>"/run/qc_wsfix.$s" 2>/dev/null || continue
    if flock -n "$tryfd"; then FIXFD="$tryfd"; break; else eval "exec ${tryfd}>&-"; fi
  done
  [ -z "$FIXFD" ] && { say "all $FIXSLOTS fix slots busy - deferring fix, will relaunch"; exit 0; }
  echo $((fa+1)) > "$FA/$t"    # F4: persist the attempt BEFORE running the fixer
  brief="$FLEET/driverlogs/$t.brief.md"
  {
    echo "Fix SVC-PC harbor task $t so its Comprehensive Review has ZERO majors. Your CWD is the task"
    echo "package. Verify each major against the real files before changing anything, then fix the root"
    echo "cause. You may edit EVERY file in the package, INCLUDING THE RUBRIC (tests/deliverables*/judge.toml)."
    echo "Most Comprehensive Review majors are rubric defects (1.4 alignment, 1.5 coverage), not deliverable"
    echo "defects, and they are fixed by editing the rubric. Do that when the finding is a rubric defect."
    echo "SOUNDNESS repair is REQUIRED and allowed: add a criterion for a graded requirement the rubric omits"
    echo "(1.5); remove or narrow a criterion that enforces something the instruction never states, or that a"
    echo "correct compliant deliverable fails (1.4 over-enforcement); split an over-bundled criterion so each"
    echo "grades one thing; fix an expected value or FAIL clause that is factually wrong against the golden"
    echo "(1.1). SOFTENING stays forbidden and is a different act: do NOT lower a pass threshold, delete a"
    echo "legitimate graded requirement, or make a hard task trivial to dodge a finding. Test: does the change"
    echo "make the rubric grade the instruction correctly (soundness, allowed) or make a real requirement"
    echo "easier to pass (softening, forbidden)? Recompute every number from environment/initial_workspace/."
    echo "Edit instruction.md AND tests/task_prompt.txt identically. Do not wb.save() a golden xlsx without"
    echo "restoring formula caches; the golden must pass its own rubric on its actual content. If you edit the"
    echo "rubric, re-hand-grade the golden against the edited rubric and confirm it still passes every"
    echo "criterion. LF line endings only. When done, stop; the driver re-reviews."
    echo
    echo "MAJOR findings from the three reviewers:"
    for spec in $REVIEWERS; do
      rev=${spec%%:*}; run=${spec##*:}; f="$REVIEWS/$t.$rev.run$run.json"
      [ -e "$f" ] || continue
      python3 -c "import json
j=json.load(open('$f'))
for c in j.get('checks',[]):
    if isinstance(c,dict) and c.get('severity')=='major':
        print('- ['+str(c.get('id'))+' via $rev] '+str(c.get('justification',''))[:900].replace(chr(10),' '))
        print('  SUGGESTED FIX: '+str(c.get('suggested_fix',''))[:400].replace(chr(10),' '))" 2>/dev/null
    done
  } > "$brief"
  say "fixing with Opus (attempt $((fa+1))/$MAXATT, fix slot acquired)"
  ( cd "$TD" && CLAUDE_CONFIG_DIR="$lane" timeout -k 60 2700 "$CLAUDE_BIN" -p "$(cat "$brief")" \
      --model opus --permission-mode dontAsk --allowedTools "Read,Edit,Write,Bash,Glob,Grep" \
      --output-format text ) 9>&- >> "$FLEET/driverlogs/$t.fix.$fa.log" 2>&1 < /dev/null
  say "fix attempt $((fa+1)) complete (rc=$?)"
  eval "exec ${FIXFD}>&-"
done
