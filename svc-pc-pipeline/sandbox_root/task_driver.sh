#!/usr/bin/env bash
# task_driver.sh TASK LANE - ONE driver owns ONE task end to end: review the CURRENT bytes, and if it
# fails, fix the root causes with Opus and re-review, iterating until it PASSES (zero majors, all four
# reviews canonical) or is UNFIXABLE. One driver per task; the pool runs ~40 at once.
#
# GUARDS (each one is a bug we already hit):
#  * PASS requires all four reviews canonical AND zero majors AND schema ok. Incomplete reviews are
#    never a pass; they are retried, never auto-dropped.
#  * A digest bigger than claude -p can take on stdin is flagged .OVERSIZE (workspace review needed),
#    never silently dropped, never retried into the ground.
#  * The expensive Opus FIX runs only if it can grab one of FIXSLOTS admission slots; reviews (light,
#    API-bound) stay uncapped. This keeps the box off its knees without throttling review throughput.
#  * Digest and reviews are reused when the task bytes have not changed, so a deferred fix does not
#    rebuild a 700k-token digest or re-run four reviews for nothing.
set -u
t="${1:?TASK}"; lane="${2:?LANE}"
Q=/root/qc; HERE=$Q/_prompts/gate-revalidate; TOOLS=$Q/tools; FLEET=$Q/fleet
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready; TD="$CORPUS/$t"
VERD=$FLEET/verdicts; REVIEWS=$FLEET/reviews; RFAIL=$FLEET/reviewfail
CLAUDE_BIN="$(command -v claude || echo /usr/bin/claude)"
mkdir -p "$VERD" "$REVIEWS" "$RFAIL" "$HERE/digests" "$HERE/detfindings" "$HERE/logs" "$FLEET/driverlogs"
MAXATT=2                 # fix rounds before UNFIXABLE (only for tasks actually reviewed)
REVIEW_TRIES=3           # in-round retries to get all four reviews canonical
RFAIL_MAX=20             # flag REVIEW_STALLED for visibility after this many failures, but KEEP retrying
OVERSIZE_BYTES=9500000   # claude -p rejects piped stdin >10MB; a digest over this cannot be gated this way
FIXSLOTS=8               # max concurrent Opus fixes across the whole fleet (32-core box); reviews uncapped
DL="$FLEET/driverlogs/$t.log"
say(){ echo "$(date -u +%FT%TZ) [$t] $*" >> "$DL"; }
[ -d "$TD" ] || { echo "no taskdir" > "$VERD/$t.UNFIXABLE"; say "no taskdir"; exit 0; }

canon_mc(){ python3 -c "import json,sys
try: j=json.load(open('$1'))
except Exception: sys.exit(1)
ok = j.get('overall_verdict') in ('accept','reject','invalid','needs_revision') and isinstance(j.get('checks'),list) and j['checks'] and isinstance(j.get('major_count'),int)
if not ok: sys.exit(1)
print(j['major_count'])" 2>/dev/null; }

for round in $(seq 0 "$MAXATT"); do
  dig="$HERE/digests/$t.md"; dbuilt=0
  if [ ! -f "$dig" ] || [ -n "$(find "$TD" -type f -newer "$dig" -print -quit 2>/dev/null)" ]; then
    say "round $round: build digest + detfindings from current bytes"; dbuilt=1
    python3 "$TOOLS/v3digest_build.py" "$TD" "$dig" >> "$DL" 2>&1
    python3 "$TOOLS/gate_detfindings.py" "$t" "$TD" "$HERE/detfindings/$t.md" >> "$DL" 2>&1
  else
    say "round $round: digest fresh (bytes unchanged), reusing"
    [ -f "$HERE/detfindings/$t.md" ] || python3 "$TOOLS/gate_detfindings.py" "$t" "$TD" "$HERE/detfindings/$t.md" >> "$DL" 2>&1
  fi
  digsz=$(stat -c%s "$dig" 2>/dev/null || echo 0)
  if [ "$digsz" -gt "$OVERSIZE_BYTES" ]; then
    rm -f "$VERD/$t.FAIL"
    echo "digest ${digsz}B exceeds ${OVERSIZE_BYTES}B claude -p stdin limit; needs workspace review" > "$VERD/$t.OVERSIZE"
    say "OVERSIZE digest=${digsz}B -> flagged for workspace review (NOT dropped, NOT retried)"
    exit 0
  fi

  # reviews: reuse the four if bytes unchanged since they were written; else run them fresh
  canon=0
  if [ "$dbuilt" -eq 0 ]; then
    fresh=1
    for spec in opus:1 opus:2 sonnet:1 sonnet:2; do
      r=${spec%%:*}; n=${spec##*:}; f="$REVIEWS/$t.$r.run$n.json"
      canon_mc "$f" >/dev/null || { fresh=0; break; }
      [ -n "$(find "$TD" -type f -newer "$f" -print -quit 2>/dev/null)" ] && { fresh=0; break; }
    done
    [ "$fresh" -eq 1 ] && { canon=4; say "round $round: reusing 4 canonical reviews (bytes unchanged)"; }
  fi
  if [ "$canon" -ne 4 ]; then
    rm -f "$REVIEWS/$t".*.json
    for rtry in $(seq 1 "$REVIEW_TRIES"); do
      for spec in opus:1 opus:2 sonnet:1 sonnet:2; do
        r=${spec%%:*}; n=${spec##*:}; f="$REVIEWS/$t.$r.run$n.json"
        canon_mc "$f" >/dev/null && continue
        bash "$TOOLS/gate_review_cold.sh" "$t" "$r" "$lane" "$f" >> "$DL" 2>&1
      done
      canon=0
      for spec in opus:1 opus:2 sonnet:1 sonnet:2; do
        r=${spec%%:*}; n=${spec##*:}; canon_mc "$REVIEWS/$t.$r.run$n.json" >/dev/null && canon=$((canon+1))
      done
      [ "$canon" -eq 4 ] && break
      say "round $round: $canon/4 canonical after review try $rtry, retrying"
    done
  fi
  if [ "$canon" -lt 4 ]; then
    rf=$(cat "$RFAIL/$t" 2>/dev/null || echo 0); rf=$((rf+1)); echo "$rf" > "$RFAIL/$t"
    rm -f "$VERD/$t.PASS"
    say "round $round: only $canon/4 canonical reviews (rfail=$rf) - transient, leaving unverdicted to retry"
    [ "$rf" -ge "$RFAIL_MAX" ] && { echo "reviews failed $rf times; still retried, never auto-dropped" > "$VERD/$t.REVIEW_STALLED"; say "flagged REVIEW_STALLED at rfail=$rf (still retried)"; }
    exit 0
  fi
  rm -f "$RFAIL/$t" "$VERD/$t.REVIEW_STALLED"

  why=""
  python3 "$TOOLS/judge_schema_bytes.py" "$TD" --block 4000 --warn 3500 >/dev/null 2>&1 || why="schema"
  for spec in opus:1 opus:2 sonnet:1 sonnet:2; do
    r=${spec%%:*}; n=${spec##*:}; mc=$(canon_mc "$REVIEWS/$t.$r.run$n.json"); mc=${mc:-0}
    [ "$mc" -ge 1 ] 2>/dev/null && why="$why major:$r$n"
  done
  if [ -z "$why" ]; then
    rm -f "$VERD/$t.FAIL" "$VERD/$t.UNFIXABLE"; echo pass > "$VERD/$t.PASS"
    say "round $round: PASS (4/4 canonical, zero majors) -> done"; exit 0
  fi
  echo "$why" > "$VERD/$t.FAIL"
  say "round $round: FAIL ($why)"
  [ "$round" -ge "$MAXATT" ] && break

  # admission control: only fix if a fix slot is free, else defer (leave FAIL, relaunch later)
  FIXFD=""
  for s in $(seq 1 "$FIXSLOTS"); do
    exec {tryfd}>"/run/qc_fixslot.$s" 2>/dev/null || continue
    if flock -n "$tryfd"; then FIXFD="$tryfd"; break; else eval "exec ${tryfd}>&-"; fi
  done
  if [ -z "$FIXFD" ]; then
    say "round $round: all $FIXSLOTS fix slots busy - deferring fix, driver_pool will relaunch"
    exit 0
  fi

  brief="$FLEET/driverlogs/$t.brief.md"
  {
    echo "Fix SVC-PC harbor task $t so its Comprehensive Review has ZERO majors. The task package is"
    echo "your current working directory. Make MINIMAL root-cause edits for each major finding below."
    echo "Never lower task difficulty. Recompute every number from environment/initial_workspace/."
    echo "Edit instruction.md AND tests/task_prompt.txt identically. Do not wb.save() a golden xlsx"
    echo "without restoring its formula caches. The golden must pass its own rubric. LF line endings only."
    echo
    echo "MAJOR findings to resolve:"
    for spec in opus:1 opus:2 sonnet:1 sonnet:2; do
      r=${spec%%:*}; n=${spec##*:}; f="$REVIEWS/$t.$r.run$n.json"
      [ -e "$f" ] || continue
      python3 -c "import json
j=json.load(open('$f'))
for c in j.get('checks',[]):
    if c.get('severity')=='major':
        print('- ['+str(c.get('id'))+'] '+str(c.get('justification',''))[:900].replace(chr(10),' '))
        print('  SUGGESTED FIX: '+str(c.get('suggested_fix',''))[:400].replace(chr(10),' '))" 2>/dev/null
    done
    echo "When done, stop. Do not run the grader; the driver re-verifies."
  } > "$brief"
  say "round $round: fixing with Opus (fix slot $FIXSLOTS-cap acquired)"
  ( cd "$TD" && CLAUDE_CONFIG_DIR="$lane" timeout 2700 "$CLAUDE_BIN" -p "$(cat "$brief")" \
      --model opus --permission-mode dontAsk --allowedTools "Read,Edit,Write,Bash,Glob,Grep" \
      --output-format text ) >> "$FLEET/driverlogs/$t.fix.$round.log" 2>&1 < /dev/null
  say "round $round: fix pass complete (rc=$?)"
  eval "exec ${FIXFD}>&-"   # release fix slot
done
echo "${why:-max attempts}" > "$VERD/$t.UNFIXABLE"; rm -f "$VERD/$t.FAIL"
say "UNFIXABLE after $MAXATT rounds"
exit 0
