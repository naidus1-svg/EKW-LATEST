#!/bin/bash
# v7 per-task fix on ONE lane, with an INTERNAL FIX LOOP. Sandbox-resident: designed to run under
# setsid/nohup so it survives the laptop closing. Does the whole v7 pipeline for one task and leaves a
# verified, upload-ready zip in _v7/ready/ or a loudly-logged reason in _v7/parked.txt.
#
# THE LOOP (this is the change 2026-09-22): rebuild -> oracle -> growth guard -> adversarial verify, and
# on ANY gate failure it feeds the SPECIFIC finding back into another TARGETED fix attempt, up to
# MAX_FIX_ATTEMPTS, instead of parking after one shot. It parks ONLY when it genuinely cannot converge,
# and the park message names the residual defect. This is plan step 7b/9 (feed findings back, iterate,
# do not resubmit an under-fixed task) made mechanical. The old single-shot behaviour "eh, verify failed,
# park it" is gone - a defect the verify or oracle can name is a defect the next attempt tries to fix.
#
# 2026-09-22 (v8.1): every prompt embeds tools/svc_fix_method_rules.md (the single source of the fix rules:
# category-aware 1.4 delete / 1.5 add, fix the whole class, re-audit every rewrite) and every verify record is
# stamped with its METHOD_VERSION. A task's existing ready/ zip is retired the moment the task is reworked,
# and every zip carries a freshness manifest that svc_bundle_upload.py re-checks before bundling. See
# svc_ship_manifest.py for why (the stale-zip hole).
#
# Usage (called by the pool, or directly): svc_v7_lane_runner.sh <TASK> <LANE>
#   TASK  e.g. SVC-PC-16-1-0
#   LANE  e.g. m  (uses CLAUDE_CONFIG_DIR=/root/.claude-m)
set -uo pipefail

TASK="${1:?task id}"; LANE="${2:?lane letter}"
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
QC=/root/qc; WORK="$QC/_v7"
BRIEF="$QC/${BRIEF_DIR:-_deepbriefs}/$TASK.md"
# The local fix loop is FREE (no DataOS cost), so we do NOT cap it at a small number - we work a task until
# it converges or is genuinely stuck. MAX_FIX_ATTEMPTS is a high safety ceiling, not the real stop. The real
# stop is STUCK_LIMIT: park only when the SAME blocker repeats with no progress. (The plan's "cap 3" is about
# paid DataOS ROUNDS, not this free local loop - conflating them was the bug that parked fixable tasks.)
# 2026-09-23 (user decision): cap 10, and a task that hits the cap is DEFERRED, not parked. ready.txt showed 41 of
# 42 converged tasks needed <= 8 attempts (one needed 12), while lanes sat on attempts 9-17 of the old 25 ceiling
# with 118 tasks waiting. Deferred tasks go to deferred.txt (claim kept) and are requeued once the queue drains.
MAX_FIX_ATTEMPTS="${MAX_FIX_ATTEMPTS:-10}"
STUCK_LIMIT="${STUCK_LIMIT:-5}"                     # park only after this many IDENTICAL blockers in a row
LAST_SIG=""; SAME=0
mkdir -p "$WORK/logs" "$WORK/ready" "$WORK/snaps"
LOG="$WORK/logs/$TASK.log"
CB="$(command -v claude 2>/dev/null || echo /usr/bin/claude)"   # FIX(#5): fallback; a relinked/missing
                                                                 # claude 404'd a cached path and killed 6 agents 2026-09-20
export CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0
export CLAUDE_CODE_BIN="$CB" CLAUDE_CONFIG_DIR="/root/.claude-$LANE" \
       QC_REWARDKIT_SITE_PACKAGES=/root/venv/lib/python3.13/site-packages
PY=/root/venv/bin/python3
VREC="$QC/_deepfix/$TASK.verify.md"; mkdir -p "$QC/_deepfix"
log(){ echo "$(date -u +%FT%TZ) $TASK[$LANE] $*" | tee -a "$LOG"; }
# Two kinds of stop, so the pool knows whether to retry:
#  parked (exit 20)  = a real defect that N fix attempts could not close - names the residual, needs a human.
#  transient (exit 10) = infra (lane capped mid-run, oracle could not run, env) - RELEASE and let another lane retry.
parked(){    log "PARKED $*";    echo "$TASK	$LANE	$*" >> "$WORK/parked.txt"; exit 20; }
# 2026-09-24: the runner releases its OWN claim on every release exit. The pool used to do it, but a pool restart
# orphans running runners, so their exit-10/30 releases never happened: 5 tasks sat claimed with no lane for up to
# 28h. The pool's own rm after these exits is now a harmless repeat.
release_claim(){ rm -rf "$WORK/claims/$TASK"; }
# 2026-09-24: the attempt cap used to "defer" (claim kept, exit 20) and nothing ever requeued deferred.txt, so
# 75-2-0 and 77-0-0 sat a full day. A normal-mode task at the cap now goes to decide mode like any dead-end; a
# decide-mode task at the cap parks with its reason in parked.txt.
deferred(){
  log "DEFERRED $*";  echo "$TASK	$LANE	$(date -u +%FT%TZ)	$*" >> "$WORK/deferred.txt"
  if [ "${IS_DECIDE:-0}" = 0 ]; then
    grep -qx "$TASK" "$WORK/decide.txt" 2>/dev/null || echo "$TASK" >> "$WORK/decide.txt"
    echo "$TASK	$LANE	$(date -u +%FT%TZ)	attempt cap: $*" >> "$WORK/auto_decide.txt"
    log "AUTO-DECIDE: attempt cap ($*); added to decide.txt, released for a decide-mode round"
    release_claim; exit 30
  fi
  parked "attempt cap in decide mode: $*"
}
transient(){ log "TRANSIENT $*"; echo "$TASK	$LANE	$*" >> "$WORK/transient.txt"; release_claim; exit 10; }
# Usage-limit refusals are a LANE cap, never a task defect. 2026-09-22/23: lanes hit the Claude session and weekly
# limits mid-loop; the runner counted every refusal as a failed attempt, so 21-0-0, 36-3-0, 2-4-0 and 21-2-0 were
# "did not converge" with their content already fixed, and a refusal overwrote 36-3-0's last real verify record.
# judge_emulate.py reports these as "infra refusal".
LIMIT_RE="hit your (weekly|usage|session|daily) limit|usage limit (reached|exceeded)|weekly limit|infra refusal"
log_mark(){ wc -l < "$LOG"; }
limit_since(){ tail -n +"$(( $1 + 1 ))" "$LOG" | grep -qiE "$LIMIT_RE"; }
cap_exit(){ transient "usage limit hit during $1 (lane capped, not a task defect); released without spending an attempt"; }
# progress(): call before every fix-feedback continue with a short signature of the CURRENT blocker.
# If the signature is identical for STUCK_LIMIT attempts in a row, the loop is making no progress on a real
# dead-end, so park (naming it). Otherwise it keeps working - a changing blocker means we ARE closing defects.
progress(){
  local sig="$1" what="$2"
  if [ "$sig" = "$LAST_SIG" ]; then SAME=$((SAME+1)); else SAME=0; fi
  LAST_SIG="$sig"
  if [ "$SAME" -ge "$STUCK_LIMIT" ]; then
    # 2026-09-24 (owner): a normal-mode dead-end goes to DECIDE mode automatically instead of parking. Decide mode
    # rescued 8 of the first 12 dead-ends by hand; parking them first only delayed that. Exit 30 tells the pool to
    # release the claim so the next lane runs a decide round. Only a task already in decide mode parks.
    if [ "$IS_DECIDE" = 0 ]; then
      grep -qx "$TASK" "$WORK/decide.txt" 2>/dev/null || echo "$TASK" >> "$WORK/decide.txt"
      echo "$TASK	$LANE	$(date -u +%FT%TZ)	$what" >> "$WORK/auto_decide.txt"
      log "AUTO-DECIDE: identical blocker $SAME attempts ($what); added to decide.txt, released for a decide-mode round"
      release_claim; exit 30
    fi
    parked "no progress: identical blocker $SAME attempts running ($what) - genuinely stuck, needs a human or a different approach"
  fi
}

log "START (loop, max $MAX_FIX_ATTEMPTS attempts)"
# Claude Code auto-updates relink /usr/bin/claude; a runner that starts inside that window sees no binary.
# 2026-09-22 18:39:21Z an update landed the same second the pool relaunched and every task went TRANSIENT,
# burning retries. Wait out the relink (up to 2 min) before calling it an env failure.
for _w in $(seq 1 24); do [ -x "$CB" ] && break; sleep 5; CB="$(command -v claude 2>/dev/null || echo /usr/bin/claude)"; done
[ -x "$CB" ]           || transient "no usable claude binary ($CB) on lane $LANE after 2 min - env broken, retry elsewhere"
[ -f "$BRIEF" ]        || parked "no complete brief at $BRIEF (run svc_build_directed_briefs.py first)"
[ -d "$CORPUS/$TASK" ] || parked "no task package $CORPUS/$TASK"
RULES_FILE="$QC/tools/svc_fix_method_rules.md"
[ -f "$RULES_FILE" ]   || transient "no rules file $RULES_FILE - deploy tools/ before running"
RULES="$(cat "$RULES_FILE")"
MV="$(head -1 "$RULES_FILE" | sed -n 's/^METHOD_VERSION: *//p')"
[ -n "$MV" ]           || transient "rules file has no METHOD_VERSION on line 1"
# Team-wide do-not-touch (tools/svc_build_freeze.py, from both trackers): already submitted or finished by
# anyone, or owned by another person. 2026-09-22: lanes were reworking 6-2-0 (Salman's), 15-2-0 (Jyotsana's,
# passed), 2-6-0 (ours, already EQC Done), 17-4-0 and 17-7-0 (other owners).
# Checked at start AND at the top of every attempt: the lists are refreshed every 30 minutes while a task runs.
# 2026-09-23: 73-2-0 joined do_not_touch mid-run; the runner checked only at start, the zip gate then refused it
# as frozen, and the runner read that refusal as a defect and looped 19 attempts (6.5 h of lane z).
freeze_check(){
  if grep -qx "$TASK" "$WORK/accepted.txt" 2>/dev/null; then
    parked "on the accepted freeze list - DataOS passed it; never re-touched"
  fi
  if grep -qx "$TASK" "$WORK/do_not_touch.txt" 2>/dev/null; then
    parked "on the team do-not-touch list (submitted/finished or owned by someone else per the trackers)"
  fi
}
freeze_check

# STALE-ZIP GUARD (2026-09-22): the moment a task is being reworked, any zip already in ready/ describes bytes
# that are about to change. Retire it NOW, so no bundler can pick it up while this run edits the package.
# Batch1 shipped four 04:00Z zips whose packages a later pass had re-edited and re-verified NOT-READY.
if [ -f "$WORK/ready/$TASK.zip" ] || [ -f "$WORK/ready/$TASK.zip.manifest.json" ]; then
  mkdir -p "$WORK/ready/_superseded"
  STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  for f in "$WORK/ready/$TASK.zip" "$WORK/ready/$TASK.zip.manifest.json"; do
    [ -f "$f" ] && mv "$f" "$WORK/ready/_superseded/$(basename "$f").$STAMP"
  done
  log "retired the existing ready zip (task is being reworked) -> ready/_superseded/"
fi

# snapshot tests/ so a bad rebuild is recoverable
rm -rf "$WORK/snaps/$TASK" 2>/dev/null; cp -r "$CORPUS/$TASK/tests" "$WORK/snaps/$TASK"

# The adversarial verify prompt (the ship gate + the loop's feedback source). Checks 1-4 are the classes
# that kept passing our oracle and failing DataOS: over/under-enforcement, golden-fails-own-criterion, and
# criteria unverifiable under the pinned reader.
VPROMPT="Adversarially audit the rubric for $TASK in $CORPUS/$TASK against instruction.md. Read instruction.md, the golden under solution/, and every tests/deliverables*/judge.toml. Produce a per-criterion audit table (criterion id | what it grades | instruction line | verdict) and check ALL of:
(1) OVER-ENFORCEMENT (1.4): does any criterion FAIL a response for something the instruction does not require, forbid something it permits, pin one scenario/time-step/method/line-count the instruction leaves open, or is it unscoped?
(2) COVERAGE (1.5): is any instruction requirement graded by no criterion?
(3) GOLDEN-SATISFIES-EVERY-CRITERION: open the golden and confirm the golden's OWN content passes each criterion, especially any criterion demanding a locator, a stored formula value, an exact figure, or a citation. Name any criterion the golden itself would fail.
(4) VERIFIABILITY under the pinned grader (rewardkit 0.1.7 -> MarkItDown): a criterion that needs a stored computed value is uncheckable if the reader extracts a broken formula identically to a live one - flag any such criterion.
(5) CLASS COVERAGE: where a criterion family covers a set (every holder, every period, every refund, every file), enumerate the set from the source files and confirm EVERY member is covered, not only one a finding cited.
(6) REWRITE RISK: re-audit every criterion, golden cell and instruction line changed since the last DataOS grade as if it were never reviewed; a rewrite is fresh surface GPT audits cold.
(7) COVERAGE TRACE (mechanically checked after you finish): run \`$PY $QC/tools/svc_coverage_trace.py list $CORPUS/$TASK\`. For EVERY unit it prints, write one TSV row to $QC/_deepfix/$TASK.coverage.tsv: <id><TAB><hash><TAB><names of the criteria that grade that unit, comma-separated, exactly as in judge.toml name=><TAB><note>. Use '-' for criteria only when the unit is not a gradeable requirement, with a note starting NOT-A-REQUIREMENT:. A unit marked [STRONG] that no criterion grades is a (2) COVERAGE defect: say so, do not paper over it. Only a unit that cannot be graded under the pinned reader (R6) may take '-', with NOT-A-REQUIREMENT: <why>. Write the file with Bash (overwrite it).
For EVERY blocking defect, give the criterion id, the judge.toml file, and the EXACT edit that fixes it, following the rules below (1.4 delete/loosen, 1.5 add one-fact criterion for the whole class, compound split, 1.1 fix the golden from source). Output a self-contained record ending with 'VERDICT: READY-TO-RESUBMIT' ONLY if none of (1)-(6) has a blocking defect, else 'VERDICT: NOT-READY' naming each defect and its fix. Be adversarial; this gates a paid grade.

=== THE RULES (tools/svc_fix_method_rules.md, $MV) ===
$RULES"

# Seed the loop.
#  - a NOT-READY verify record on disk -> fix-mode from its findings (do not throw away what we know is wrong);
#  - a READY record made under an OLDER method version -> reverify: re-run the gates under the current rules
#    WITHOUT editing first (the rules changed, not the task). A NOT-READY result then feeds the normal fix loop.
#    This is how a rules change reaches every task: the builder refuses an old-method verify record, so an
#    old-method task can only ship by passing this re-audit.
#  - otherwise -> full directed rebuild from the complete brief.
VMV="$(sed -n 's/^METHOD_VERSION: *//p' "$VREC" 2>/dev/null | tail -1)"
if [ -s "$VREC" ] && grep -qi "VERDICT: *NOT-READY" "$VREC"; then
  MODE="fix"; DIRECTIVE="$(cat "$VREC")"; log "seeding fix-mode from existing NOT-READY verify record"
elif [ -s "$VREC" ] && grep -qi "VERDICT: *READY-TO-RESUBMIT" "$VREC" && [ "$VMV" != "$MV" ]; then
  MODE="reverify"; DIRECTIVE=""; log "READY record is from method '${VMV:-none}', current is '$MV': re-verifying under the current rules"
elif grep -qx "$TASK" "$WORK/targeted.txt" 2>/dev/null; then
  # Triage (_v7/targeted.txt, written from the latest return's majors): <= 2 majors total. A surgical fix
  # driven by the complete brief is enough; the rules still demand the full per-criterion audit (R4) and the
  # same gates run after. Saves the 50-min wholesale rebuild on small, well-scoped findings.
  MODE="fix"; DIRECTIVE="$(cat "$BRIEF")"; log "triage: <= 2 majors, starting in targeted-fix mode from the complete brief"
else
  MODE="rebuild"; DIRECTIVE="$(cat "$BRIEF")"
fi

# VERIFY-CAP PILOT (owner-authorised 2026-09-23, L2 only). 24h of logs: L2 median 9 attempts / 8h per task, and
# the LLM verify's NOT-READY caused 371 loop-backs while its READY predicts DataOS ~21% of the time. After
# VERIFY_CAP verify loop-backs, a non-L3 task ships on the deterministic gates alone (oracle 1.0 x2 on the final
# bytes, regrade PASS, coverage trace clean, prefilter + loader), tagged verify_capped in the manifest so the
# cohort's DataOS pass rate is measured on its own. L3 tasks (_v7/l3.txt) keep the full verify gate.
# PILOT RESULT 2026-09-23 (#444, batch10a): verify_capped 1/18 passed DataOS, full-READY 5/10. The verify does
# predict DataOS; the cap is OFF (99 = never reached within MAX_FIX_ATTEMPTS). Set VERIFY_CAP=2 to re-enable.
VERIFY_CAP="${VERIFY_CAP:-99}"; VLOOPS=0; CAPPED=0
IS_L3=0; grep -qx "$TASK" "$WORK/l3.txt" 2>/dev/null && IS_L3=1

# DECIDE MODE (owner-approved 2026-09-23, "item D"). Twelve tasks had used ~237 attempts between them repeating one
# kind of fix against one blocker: 7 with a 1.0 golden whose eval-regrade kept failing (the DataOS-flagged answers
# still scored 0 on the rewritten criterion; 5-1-0 and 52-3-0 never changed the flagged criterion at all) and 3 whose
# golden failed its own rubric (20-8-0 0.97, 31-4-0 ~0.77, 55-0-0 0.88). A task listed in _v7/decide.txt gets a
# decision prompt instead: per failing criterion pick REWRITE / DROP / KEEP (answer genuinely wrong, cited) /
# FIX-GOLDEN, prove it, and write _deepfix/<task>.decision.json, which svc_eval_regrade.py --decision honours.
# The same blocker twice under DECIDE parks the task with the decision record, instead of 10 more attempts.
IS_DECIDE=0; grep -qx "$TASK" "$WORK/decide.txt" 2>/dev/null && IS_DECIDE=1
DECISION_FILE="$QC/_deepfix/${TASK}.decision.json"
decide_prompt(){
  local base=""
  for z in $(ls -t "$QC/_returns/"*_with_runs*.zip 2>/dev/null); do
    case "$(unzip -l "$z" 2>/dev/null)" in *"$TASK/"*) base="$z"; break;; esac
  done
  cat <<EOP
DECISION RUN for $TASK. Earlier attempts repeated one kind of fix many times and failed the same gate every time. Do not repeat that edit. Your job is to DECIDE, per failing criterion, and prove the decision.
THIS IS A NON-INTERACTIVE RUN: it ends the moment you stop, and nothing will notify you or resume you later. Run every command in the FOREGROUND and wait for its output (never run_in_background, never '&', never "I'll check when it finishes"). Finish by writing the decision file below; a run that ends without it is wasted.
EVIDENCE:
- $QC/_deepfix/$TASK.regrade.json (if present): direction_A.targets maps each criterion DataOS flagged to the answer ids it wrongly failed; direction_A.unaddressed lists flagged criteria still unchanged; llm_regrade.detail gives '<answer id>:<criterion>' -> score under the CURRENT rubric (below 1.0 = still failing); 'why' is the gate's reason.
- The DataOS-graded answers are in the return zip ${base:-<none found>}: list with \`unzip -l <zip> | grep $TASK\`. Each answer id is an evaluation run holding the agent's deliverable. Extract only what you need to /tmp.
- For the golden: \`$PY $QC/tools/judge_emulate.py oracle $TASK --runs 1 --corpus-root $CORPUS --out /tmp/${TASK}_diag.json\` shows every criterion the golden scores below 1.
FOR EACH still-failing criterion (an answer below 1.0, a flagged criterion left unchanged, or a criterion the golden fails), read the criterion text, the answer's or golden's relevant content, and the source records under environment/initial_workspace/ it depends on. Choose exactly one:
 (a) REWRITE: the answer (or golden) is correct per the sources and the criterion wrongly fails it. Rewrite the criterion so it passes, still one fact and checkable. Confirm the golden passes and an answer missing the fact would still fail.
 (b) DROP: the criterion grades something the sources cannot settle or the instruction does not require. Delete it; keep reward weights valid.
 (c) KEEP: the answer really is wrong per the sources (DataOS's false-rejection call was mistaken). Leave the criterion unchanged and cite the exact file and record that proves the answer wrong.
 (d) FIX-GOLDEN: the golden fails a correct criterion. Recompute the value from source and fix the golden.
Then overwrite $DECISION_FILE with JSON: {"task":"$TASK","decisions":[{"criterion":"<id>","action":"rewrite|drop|keep|fix-golden","answers":["<answer ids>"],"evidence":"<source file + sheet/row/page/record>","reason":"<one or two sentences>"}]}
Every still-failing criterion appears exactly once. A keep without a real source citation is rejected by the gate. Print the decisions as a table when done.
EOP
}
if [ "$IS_DECIDE" = 1 ]; then
  STUCK_LIMIT=2; MODE="decide"; log "DECIDE mode (_v7/decide.txt): one decision per failing criterion, record at $DECISION_FILE"
fi

attempt=0
while [ "$attempt" -lt "$MAX_FIX_ATTEMPTS" ]; do
  attempt=$((attempt+1))
  freeze_check
  log "=== attempt $attempt/$MAX_FIX_ATTEMPTS (mode=$MODE) ==="

  # 1. fix / rebuild step. rebuild = full directed rebuild from the complete brief (attempt 1 only, unless
  #    seeded). fix = surgical: apply the named findings, 1.4 delete/loosen, 1.5 add one-fact, no wholesale rebuild.
  if [ "$MODE" = "reverify" ]; then
    log "reverify: no edit this attempt; running the gates under $MV"
    MODE="fix"   # any failure below feeds a targeted fix on the next attempt
  else
    if [ "$MODE" = "decide" ]; then
      # 2026-09-25: decide limit 2400 -> 5400 s; 2400 killed 25-1-0's decide runs mid-work twice
      # 2026-09-29: 5400 -> 9000 s; 24-6-0 hit 5400 twice and parked as a TOOL problem
      TO=9000; PROMPT="$(decide_prompt)

=== THE RULES (tools/svc_fix_method_rules.md, $MV) ===
$RULES"
    elif [ "$MODE" = "rebuild" ]; then
      TO=3000; PROMPT="$DIRECTIVE

=== REQUIREMENT WALK (do this before you finish) ===
Run \`$PY $QC/tools/svc_coverage_trace.py list $CORPUS/$TASK\` and, for EVERY unit it prints, name the criterion that grades it. Any unit marked [STRONG] with no criterion is a 1.5 hole: add the one-fact criterion (value re-derived from source; the golden must pass it; at most 15 criteria per judge dir), unless it cannot be graded under the pinned reader (R6). A later mechanical check fails the task on any unmapped requirement.

=== THE RULES (tools/svc_fix_method_rules.md, $MV) - these override anything above that conflicts ===
$RULES"
    else
      TO=1800
      # 2026-09-23: this prompt used to say "apply the fixes ... and then STOP", which beat R2/R4 appended below it:
      # agents closed the cited item only, and 26-8-0 took 13 rounds on a new coverage gap each round. The
      # prompt now demands the class enumeration and the requirement walk as OUTPUT, so skipping them is visible.
      PROMPT="TARGETED FIX for $TASK. Do not rebuild the task wholesale and do not rewrite criteria no finding touches (every rewrite is fresh surface the grader audits cold). But a finding is a symptom of a PATTERN, so do all four steps and print each step's output:
STEP 1 CLASS: for every finding below, name the criterion family it belongs to (every holder, period, refund, file, section, metric...), enumerate EVERY member of that family from the source files under environment/initial_workspace/ (print the list), and fix the whole family, not only the cited member. 1.4 over-enforcement -> delete or loosen every criterion in the family with the same over-reach; 1.5 coverage hole -> one one-fact criterion per uncovered member; compound -> split, preserving weight; 1.1 -> recompute from source.
STEP 2 RECOMPUTE: for every golden value and every Expected: value you touched or that a finding cites, recompute it from the source files (show the computation) and fix the golden or the criterion when they disagree with source.
STEP 3 REQUIREMENT WALK: run \`$PY $QC/tools/svc_coverage_trace.py list $CORPUS/$TASK\` and, for EVERY unit, name the criterion that grades it. Any unit marked [STRONG] with no criterion is a 1.5 hole: add the one-fact criterion now (checked against the source-derived value; the golden must pass it; at most 15 criteria per judge dir), unless it cannot be graded under the pinned reader (R6).
STEP 4 RE-AUDIT: re-audit every criterion, golden cell and instruction line you changed as if never reviewed (R3), and confirm the golden satisfies each changed criterion's letter (R5).
Never add qualifying text to an existing criterion. Edit the judge.toml / golden files directly. FINDINGS:

$DIRECTIVE

=== THE RULES (tools/svc_fix_method_rules.md, $MV) ===
$RULES"
    fi
    # Owner decisions ride on EVERY fix/rebuild prompt, not only the brief the run was seeded from: later attempts are
    # driven by verify/regrade findings and never re-read the brief (2026-09-23: L3 exemplar notes).
    OWNER_NOTE="$QC/_deepbriefs/_owner_notes/$TASK.md"
    if [ -f "$OWNER_NOTE" ]; then
      PROMPT="$PROMPT

=== OWNER DECISION (binding; overrides any finding above it conflicts with) ===
$(cat "$OWNER_NOTE")"
    fi
    M0="$(log_mark)"
    STEP_MODE="$MODE"; DT0="$(date +%s)"
    ( cd "$CORPUS/$TASK" && timeout "$TO" claude -p "$PROMPT" \
        --model opus --permission-mode dontAsk --allowedTools "Read,Edit,Write,Bash,Glob,Grep" ) >> "$LOG" 2>&1
    SRC=$?
    log "fix/rebuild step rc=$SRC (attempt $attempt)"
    limit_since "$M0" && cap_exit "the fix/rebuild step"
    # A decide attempt that wrote no fresh decision record did nothing the gates can use (2026-09-24: 55-0-0's first
    # decide run launched its judge runs in the background and ended its turn; claude -p never resumes).
    if [ "$STEP_MODE" = "decide" ]; then
      if [ ! -s "$DECISION_FILE" ] || [ "$(stat -c %Y "$DECISION_FILE")" -lt "$DT0" ]; then
        # 2026-09-25: a decide run killed by our own time limit (rc 124) is a TOOL problem, not a task blocker. It used
        # to count toward "no progress" and parked 25-1-0 as "genuinely stuck". Two timeouts park as a tool problem in
        # gate_errors.txt (reported every cycle) so the limit gets raised instead of the task written off.
        if [ "$SRC" = 124 ]; then
          DTO=$(( ${DTO:-0} + 1 ))
          log "decide run hit the ${TO}s limit (timeout $DTO); tool limit, not a task blocker"
          if [ "$DTO" -ge 2 ]; then
            echo "$TASK	$LANE	$(date -u +%FT%TZ)	DECIDE-TIMEOUT	decide hit the ${TO}s limit twice" >> "$WORK/gate_errors.txt"
            parked "TOOL problem, not a task defect: decide run hit the ${TO}s limit twice - raise TO in svc_v7_lane_runner.sh, then release"
          fi
          MODE="decide"; continue
        fi
        progress "decide:no-record" "decide run ended without writing $DECISION_FILE"
        log "decide attempt wrote no decision record; retrying decide"
        MODE="decide"; continue
      fi
      log "decision record: $("$PY" -c "import json;d=json.load(open('$DECISION_FILE'));print(', '.join('%s=%s'%(x.get('criterion'),x.get('action')) for x in d.get('decisions',[])))" 2>&1 | cut -c1-300)"
    fi
  fi

  # 2. oracle 2x (the golden-passes-its-own-rubric gate; necessary, not sufficient).
  # Remove the previous attempt's result first: a run that dies before writing must read as "no reward", never
  # as the last attempt's score. Capture the emulator's own output so a Python crash is told apart from a cap.
  # 2026-09-23: ONE run per loop attempt, and a confirm run on the final bytes just before the zip (step 4c).
  # The oracle was 38% of all lane time (24h, 90 tasks) and most attempts loop back after it anyway; the ship
  # condition is unchanged (two runs at 1.0 on the same bytes; judge_emulate's total_reward is the min).
  rm -f "/tmp/${TASK}_v7.json"
  # 2026-09-29: outer oracle timeout 2400 -> 5400 s. judge_emulate grades judge groups one at a time, and
  # SVC-PC-68-0-0 (24 groups, 322 criteria) was killed at 2400 s 125 times since 09-25, each read as TRANSIENT
  # and released without an attempt, while an unbounded run scored its golden 1.0. EKW oracle median 313 s, p90 886 s.
  ORC_OUT="$(timeout 5400 "$PY" "$QC/tools/judge_emulate.py" oracle "$TASK" --runs 1 \
      --corpus-root "$CORPUS" --out "/tmp/${TASK}_v7.json" 2>&1)"
  printf '%s\n' "$ORC_OUT" >> "$LOG"
  printf '%s' "$ORC_OUT" | grep -qiE "$LIMIT_RE" && cap_exit "the oracle"
  REW="$("$PY" -c "import json;print(json.load(open('/tmp/${TASK}_v7.json')).get('total_reward'))" 2>/dev/null || echo none)"
  log "oracle total_reward=$REW (attempt $attempt)"
  # 2026-09-23: judge_emulate.py crashed (AttributeError) on programmatic checks and the runner called it "lane
  # capped", releasing 1-5-0, 73-0-0, 41-4-0 and parking 77-8-0 as transient x3. A traceback is a tool bug: say so.
  # 2026-09-26: the sandbox disk (and /tmp inodes) filled at ~07:40Z and 17 tasks parked here as "tool bug" on
  # OSError Errno 28. A full disk is infrastructure, never the task: release and retry.
  if { [ "$REW" = "none" ] || [ "$REW" = "None" ]; } && printf '%s' "$ORC_OUT" | grep -qE "No space left on device|Errno 28"; then
    transient "disk full during the oracle (infra, not the task); released"
  fi
  if { [ "$REW" = "none" ] || [ "$REW" = "None" ]; } && printf '%s' "$ORC_OUT" | grep -q "^Traceback"; then
    parked "oracle CRASHED (judge_emulate.py traceback, a tool bug, not a lane cap): $(printf '%s' "$ORC_OUT" | grep -E '^[A-Za-z]+(Error|Exception)' | tail -1 | cut -c1-160)"
  fi
  if [ "$REW" != "1.0" ]; then
    if [ "$REW" = "none" ] || [ -z "$REW" ] || [ "$REW" = "None" ]; then
      # Oracle produced no score. On attempt 1 this is almost always infra (lane capped mid-oracle) -> release.
      # On a later attempt it is more likely a rubric/reward.toml config bug the fix should chase.
      if [ "$attempt" -eq 1 ]; then
        transient "oracle produced no reward on first attempt (lane capped mid-run / infra); release for another lane"
      fi
      MODE="fix"; DIRECTIVE="The oracle produced NO total_reward (null). Run: $PY $QC/tools/judge_emulate.py oracle $TASK --runs 1 --corpus-root $CORPUS --out /tmp/${TASK}_diag.json and read the error. A null reward usually means a criterion errors or tests/reward.toml has no valid [[reward]] table / weights do not resolve. Fix the config so a real reward computes. Do not add criteria."
      continue
    fi
    # numeric < 1.0: the golden fails at least one criterion.
    if [ "$attempt" -lt "$MAX_FIX_ATTEMPTS" ]; then
      progress "orc:$REW" "golden stuck at oracle reward $REW"
      MODE="fix"; DIRECTIVE="The oracle scored the golden at $REW (< 1.0), so the golden FAILS at least one criterion. Run: $PY $QC/tools/judge_emulate.py oracle $TASK --runs 1 --corpus-root $CORPUS --out /tmp/${TASK}_diag.json and identify which criteria score below 1. For each, decide: is the GOLDEN wrong (recompute that value from environment/initial_workspace/ and fix the golden cell) or does the CRITERION over-enforce against a correct golden (loosen/delete it)? Make the golden score 1.0 on 2 runs. Do not add criteria."
      [ "$IS_DECIDE" = 1 ] && MODE="decide"
      continue
    fi
    deferred "attempt cap: golden not 1.0 after $attempt attempts (last=$REW)"
  fi

  # 3. Find the last-graded baseline return zip. SIGPIPE-safe: read the listing into a var and match with
  #    `case`, never `unzip -l | grep -q` - grep -q exits on first match, SIGPIPEs unzip, and under
  #    `set -o pipefail` that non-zero status reads a real match as "not found". That bug silently disabled
  #    this lookup on every task (confirmed 2026-09-22: logged "no baseline" for tasks whose baseline exists).
  #    This zip is also the eval-regrade gate's input.
  BASE=""
  for z in $(ls -t "$QC/_returns/"*_with_runs*.zip 2>/dev/null); do
    listing="$(unzip -l "$z" 2>/dev/null)"
    case "$listing" in *"$TASK/"*) BASE="$z"; break;; esac
  done

  # 3a. Growth diff = INFORMATIONAL only (no longer a hard block). Delete-only is wrong for 1.5 coverage
  #     fixes: the only batch-1 pass GREW its rubric by a whole memo directory, exactly the fix a rejected
  #     task was failed for lacking. The eval-regrade gate (3b) now decides shippability; the diff is logged
  #     so a human can see what moved.
  if [ -n "$BASE" ]; then
    "$PY" "$QC/tools/svc_rubric_growth_diff.py" --current "$CORPUS/$TASK" --baseline "$BASE" --task "$TASK" >> "$LOG" 2>&1 || true
    log "growth diff logged vs $(basename "$BASE") (informational, not blocking)"
  fi

  # 3b. EVAL-REGRADE GATE (load-bearing): re-grade the real answer DataOS saved, against the CURRENT rubric.
  #     Direction A: every criterion a compliant answer failed must now pass. Direction B (1.5 coverage): a
  #     hollow variant must now fail. Not-PASS feeds the exact failing criteria back for another targeted fix.
  #     A task with no graded baseline has no answer to re-grade, so the gate is N/A and the verify + oracle carry.
  if [ -n "$BASE" ]; then
    M0="$(log_mark)"
    "$PY" "$QC/tools/svc_eval_regrade.py" regrade "$TASK" --zip "$BASE" \
        --rubric "$CORPUS/$TASK/tests" --out "$QC/_deepfix" \
        --judge-emulate "$QC/tools/judge_emulate.py" --corpus-root "$CORPUS" --python "$PY" \
        --decision "$DECISION_FILE" >> "$LOG" 2>&1 || true
    limit_since "$M0" && cap_exit "the eval-regrade"
    RG="$("$PY" -c "import json;print(json.load(open('$QC/_deepfix/${TASK}.regrade.json')).get('verdict'))" 2>/dev/null || echo MISSING)"
    log "eval-regrade verdict=$RG"
    # 2026-09-24 (owner): a blocker inside our own gate must never be worked as a task defect. 7 tasks spent their
    # fix and decide rounds on two svc_eval_regrade.py bugs and were parked as "genuinely stuck". Now: the gate's
    # own GATE-ERROR verdict, or a decide round whose decision.json disputes the gate (gate_note) while the gate
    # still fails, parks as a GATE problem in gate_errors.txt, which every cycle reports as a tool bug to fix.
    if [ "$RG" = "GATE-ERROR" ] || { [ "$RG" != "PASS" ] && [ "$IS_DECIDE" = 1 ] && [ -f "$DECISION_FILE" ] \
         && "$PY" -c "import json,sys;sys.exit(0 if str(json.load(open('$DECISION_FILE')).get('gate_note','')).strip() else 1)" 2>/dev/null; }; then
      GWHY="$("$PY" -c "import json;print(json.load(open('$QC/_deepfix/${TASK}.regrade.json')).get('why'))" 2>/dev/null || echo unknown)"
      echo "$TASK	$LANE	$(date -u +%FT%TZ)	$RG	$GWHY" >> "$WORK/gate_errors.txt"
      parked "GATE problem, not a task defect (verdict=$RG; decide-mode gate_note present=$IS_DECIDE): $GWHY - fix svc_eval_regrade.py, then release"
    fi
    if [ "$RG" != "PASS" ]; then
      if [ "$attempt" -lt "$MAX_FIX_ATTEMPTS" ]; then
        WHY="$("$PY" -c "import json;print(json.load(open('$QC/_deepfix/${TASK}.regrade.json')).get('why'))" 2>/dev/null || echo unknown)"
        progress "rg:$WHY" "eval-regrade blocker unchanged"
        MODE="fix"; DIRECTIVE="The eval-regrade gate did NOT pass: $WHY. A real answer DataOS graded is still not handled by the fixed rubric. For each unaddressed/failing criterion: loosen it so the compliant answer passes (1.4), or for a coverage hole (1.5) add a one-fact criterion a hollow answer fails. Details in $QC/_deepfix/${TASK}.regrade.json."
        [ "$IS_DECIDE" = 1 ] && MODE="decide"
        log "eval-regrade not PASS; feeding back (attempt $attempt)"
        continue
      fi
      deferred "attempt cap: eval-regrade gate not PASS after $attempt attempts (see $QC/_deepfix/${TASK}.regrade.json)"
    fi
    log "eval-regrade GATE PASS (attempt $attempt)"
  else
    log "WARN no graded baseline for $TASK; eval-regrade gate N/A (verify+oracle carry)"
  fi

  # 4. adversarial verify (the ship gate AND the loop's feedback source).
  # Written to a temp file first: a refused or empty verify must never replace the last real verdict.
  M0="$(log_mark)"
  ( cd "$CORPUS/$TASK" && timeout 1800 claude -p "$VPROMPT" \
      --model opus --permission-mode dontAsk --allowedTools "Read,Bash,Glob,Grep" ) > "$VREC.tmp" 2>> "$LOG"
  if grep -qiE "$LIMIT_RE" "$VREC.tmp" || limit_since "$M0"; then rm -f "$VREC.tmp"; cap_exit "the adversarial verify"; fi
  if [ ! -s "$VREC.tmp" ]; then rm -f "$VREC.tmp"; transient "adversarial verify produced no output (killed or crashed); released"; fi
  mv -f "$VREC.tmp" "$VREC"
  # stamp the rules version this verdict was reached under (the builder + bundler refuse any other version)
  printf '\nMETHOD_VERSION: %s\n' "$MV" >> "$VREC"
  # the LAST verdict line decides (a record that quotes the instruction text must not read as READY)
  LASTV="$(grep -oiE 'VERDICT: *\**(READY-TO-RESUBMIT|NOT-READY)' "$VREC" | tail -1)"
  CAPPED=0
  if ! printf '%s' "$LASTV" | grep -qi "READY-TO-RESUBMIT" && [ "$IS_L3" -eq 0 ] && [ "$VLOOPS" -ge "$VERIFY_CAP" ]; then
    CAPPED=1
    log "verify NOT-READY after $VLOOPS verify loop-backs: VERIFY-CAP, shipping on the deterministic gates (findings kept in $VREC)"
  elif ! printf '%s' "$LASTV" | grep -qi "READY-TO-RESUBMIT"; then
    VLOOPS=$((VLOOPS+1))
    if [ "$attempt" -lt "$MAX_FIX_ATTEMPTS" ]; then
      progress "vf:$(grep -oE '[a-z]{1,4}[0-9]{1,3}[a-z]?' "$VREC" 2>/dev/null | sort -u | md5sum | cut -d' ' -f1)" "adversarial verify flags the same criteria"
      MODE="fix"; DIRECTIVE="$(cat "$VREC")"
      log "adversarial verify NOT-READY; feeding its findings back for a targeted fix (attempt $attempt)"
      continue
    fi
    deferred "attempt cap: adversarial verify still NOT-READY after $attempt attempts (residual defect in $VREC)"
  fi
  [ "$CAPPED" -eq 0 ] && log "adversarial verify READY (attempt $attempt)"

  # 4b. COVERAGE TRACE (2026-09-23). The verify wrote a requirement -> criterion map; check it mechanically.
  #     rc 1 = a requirement no criterion grades -> targeted fix. rc 2 = map missing/malformed: the verifier's
  #     output problem, not the task's, so it is logged and does not block (a fixer cannot repair a map).
  CT_OUT="$("$PY" "$QC/tools/svc_coverage_trace.py" check "$CORPUS/$TASK" "$QC/_deepfix/$TASK.coverage.tsv" 2>&1)"; CT_RC=$?
  printf '%s\n' "$CT_OUT" >> "$LOG"
  if [ "$CT_RC" -eq 1 ]; then
    if [ "$attempt" -lt "$MAX_FIX_ATTEMPTS" ]; then
      progress "ct:$(printf '%s' "$CT_OUT" | grep UNCOVERED | md5sum | cut -d' ' -f1)" "coverage trace flags the same requirements"
      MODE="fix"; DIRECTIVE="The coverage trace found instruction requirements that no criterion grades (1.5 coverage holes, the most common DataOS major). For each, add one one-fact criterion checked against the value re-derived from source; the golden must pass it:
$CT_OUT"
      log "coverage trace: uncovered requirements; feeding back (attempt $attempt)"
      continue
    fi
    deferred "attempt cap: coverage trace still reports uncovered requirements after $attempt attempts"
  elif [ "$CT_RC" -ne 0 ] && [ "$CAPPED" -eq 1 ]; then
    # a capped ship needs a CLEAN trace; with no usable map, fall back to one more verify-driven fix
    MODE="fix"; DIRECTIVE="$(cat "$VREC")"; CAPPED=0
    log "VERIFY-CAP refused: coverage trace map missing/malformed (rc=$CT_RC); one more fix from the verify findings"
    continue
  elif [ "$CT_RC" -ne 0 ]; then
    log "WARN coverage trace map missing/malformed (rc=$CT_RC); not blocking: $(printf '%s' "$CT_OUT" | head -1)"
  else
    log "coverage trace clean"
  fi

  # 4c. oracle confirm run on the final bytes (the second of the two 1.0 runs the ship condition needs).
  rm -f "/tmp/${TASK}_v7c.json"
  ORC_OUT="$(timeout 5400 "$PY" "$QC/tools/judge_emulate.py" oracle "$TASK" --runs 1 \
      --corpus-root "$CORPUS" --out "/tmp/${TASK}_v7c.json" 2>&1)"
  printf '%s\n' "$ORC_OUT" >> "$LOG"
  printf '%s' "$ORC_OUT" | grep -qiE "$LIMIT_RE" && cap_exit "the oracle confirm run"
  REW2="$("$PY" -c "import json;print(json.load(open('/tmp/${TASK}_v7c.json')).get('total_reward'))" 2>/dev/null || echo none)"
  log "oracle confirm total_reward=$REW2 (attempt $attempt)"
  if [ "$REW2" != "1.0" ]; then
    if [ "$REW2" = "none" ] || [ "$REW2" = "None" ] || [ -z "$REW2" ]; then
      transient "oracle confirm run produced no reward (lane capped / infra); release for another lane"
    fi
    if [ "$attempt" -lt "$MAX_FIX_ATTEMPTS" ]; then
      MODE="fix"; DIRECTIVE="The golden scored 1.0 on the first oracle run but $REW2 on the confirm run: a criterion FLIPS between runs on identical bytes. Run: $PY $QC/tools/judge_emulate.py oracle $TASK --runs 2 --corpus-root $CORPUS --out /tmp/${TASK}_diag.json and read its 'flips' field. Split a multi-clause criterion into one-fact criteria, or make the golden state the fact unambiguously. Do not loosen a criterion to fit a wrong golden."
      log "oracle confirm not 1.0; feeding the flip back (attempt $attempt)"
      continue
    fi
    deferred "attempt cap: oracle confirm run not 1.0 after $attempt attempts (last=$REW2)"
  fi

  # 5. gated zip: svc_build_upload_zip runs the pre-screen (HARD defects block) + requires the verify record,
  #    excludes junk, cold-audits. Output lands in ready/ for the user to upload.
  CAPARGS=()
  if [ "$CAPPED" -eq 1 ]; then
    cp -f "/tmp/${TASK}_v7c.json" "$QC/_deepfix/${TASK}.oracle_confirm.json"
    CAPARGS=(--fast-track "verify-capped L2 pilot (owner-authorised 2026-09-23): verify NOT-READY after $VLOOPS loop-backs; oracle 1.0 x2, regrade PASS, coverage trace clean" \
             --oracle-json "$QC/_deepfix/${TASK}.oracle_confirm.json" --verify-capped)
  fi
  if "$PY" "$QC/tools/svc_build_upload_zip.py" "$TASK" --prefilter "$QC/tools/svc_prefilter.py" \
        --verify-dir "$QC/_deepfix" "${CAPARGS[@]}" --out "$WORK/ready/${TASK}.zip" >> "$LOG" 2>&1; then
    CAPTAG=""; [ "$CAPPED" -eq 1 ] && CAPTAG="verify_capped"
    log "READY -> $WORK/ready/${TASK}.zip (converged in $attempt attempt(s)) $CAPTAG"
    echo "$TASK	$LANE	$(date -u +%FT%TZ)	attempts=$attempt	$CAPTAG" >> "$WORK/ready.txt"
    exit 0
  fi
  # gated zip refused despite green gates -> a pre-screen HARD defect the verify did not surface; feed it back.
  if [ "$attempt" -lt "$MAX_FIX_ATTEMPTS" ]; then
    MODE="fix"; DIRECTIVE="The gated upload builder refused the zip even though oracle and verify passed. Run $PY $QC/tools/svc_prefilter.py $CORPUS/$TASK and fix every HARD defect it reports (grammar bomb >15 criteria/dir, files= gap, answer-key leak, lease.json, mojibake). Do not add criteria."
    log "gated zip refused; feeding prefilter findings back (attempt $attempt)"
    continue
  fi
  deferred "attempt cap: gated zip refused after $attempt attempts (pre-screen HARD defect)"
done

# Loop exhausted without a return path above (defensive; each failure branch above already parks at the cap).
deferred "attempt cap: did not converge in $MAX_FIX_ATTEMPTS attempts"
