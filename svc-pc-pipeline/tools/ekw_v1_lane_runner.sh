#!/bin/bash
# EKW v1 per-task fix on ONE lane, with an internal fix loop. The EKW twin of svc_v7_lane_runner.sh: same shape
# (gate -> feed the specific finding back into a targeted fix -> repeat) and the SAME exit-code contract, so the
# pool can treat an EKW task exactly like an SVC one:
#   0  READY    verified package zip in $WORK/ready/<TASK>.zip (+ .manifest.json), line in ready.txt. Claim kept.
#   10 TRANSIENT lane capped / infra; the runner has already RELEASED its claim; retry on another lane.
#   20 PARKED   a real stop that needs a person (missing golden/verifier, stuck in decide mode). Claim kept.
#   30 DECIDE   stuck on one blocker in normal mode; task added to $WORK/decide.txt, claim RELEASED, the next
#               lane runs it in decide mode.
# Nothing here uploads, writes to Drive/Sheets, or sends messages. READY means "ready for a human to upload".
#
# Where things live (see tools/ekw_intake.py for the full layout):
#   $EKW_ROOT/_pull/<TASK>   Drive copy (read-only)       $EKW_ROOT/_raw/<TASK>   authoring source; the fix step edits ONLY this
#   $EKW_ROOT/_harbor/...    native tree for EKW checks   $EKW_ROOT/<TASK>        DataOS package (regenerated every attempt)
#
# One attempt = [fix step, skipped on attempt 1 of a fresh task] -> schema check -> build (harbor tree + package)
#   -> EKW deterministic gate (ekw_gate.py over ekw_run_checks.py) -> oracle (judge_emulate.py, golden vs its own
#   rubric, must be 1.0) -> adversarial verify (READY/NOT-READY) -> oracle confirm on the final bytes -> prefilter
#   (svc_prefilter.py HARD defects) -> zip + manifest.
# The oracle and verify are the same tools the SVC lanes use: ekw_raw_to_rewardkit.py emits the same package shape.
#
# Usage: ekw_v1_lane_runner.sh <TASK> <LANE>      e.g. ekw_v1_lane_runner.sh LGL-131 b
set -uo pipefail

TASK="${1:?task id}"; LANE="${2:?lane letter}"
QC="${EKW_QC:-/root/qc}"; TOOLS="${EKW_TOOLS:-$QC/tools}"; WORK="${EKW_WORK:-$QC/_ekw}"
export EKW_ROOT="${EKW_ROOT:-/root/ekwqc/pipeline/data/ekw_qc}" EKW_WORK="$WORK"
PY="${EKW_PY:-/root/venv/bin/python3}"
MAX_FIX_ATTEMPTS="${MAX_FIX_ATTEMPTS:-10}"; STUCK_LIMIT="${STUCK_LIMIT:-5}"
LAST_SIG=""; SAME=0
mkdir -p "$WORK/logs" "$WORK/ready" "$WORK/verify" "$WORK/snaps" "$WORK/waivers" "$WORK/claims"
LOG="$WORK/logs/$TASK.log"
CB="${EKW_CLAUDE:-$(command -v claude 2>/dev/null || echo /usr/bin/claude)}"
export CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0
export CLAUDE_CODE_BIN="$CB" CLAUDE_CONFIG_DIR="/root/.claude-$LANE" \
       QC_REWARDKIT_SITE_PACKAGES=/root/venv/lib/python3.13/site-packages
RAW="$EKW_ROOT/_raw/$TASK"; PKG="$EKW_ROOT/$TASK"
VREC="$WORK/verify/$TASK.verify.md"; GJ="$WORK/gate/$TASK.gate.json"; mkdir -p "$WORK/gate"
log(){ echo "$(date -u +%FT%TZ) $TASK[$LANE] $*" | tee -a "$LOG"; }
parked(){    log "PARKED $*";    echo "$TASK	$LANE	$(date -u +%FT%TZ)	$*" >> "$WORK/parked.txt"; exit 20; }
release_claim(){ rm -rf "$WORK/claims/$TASK"; }
transient(){ log "TRANSIENT $*"; echo "$TASK	$LANE	$(date -u +%FT%TZ)	$*" >> "$WORK/transient.txt"; release_claim; exit 10; }
to_decide(){
  grep -qx "$TASK" "$WORK/decide.txt" 2>/dev/null || echo "$TASK" >> "$WORK/decide.txt"
  echo "$TASK	$LANE	$(date -u +%FT%TZ)	$*" >> "$WORK/auto_decide.txt"
  log "AUTO-DECIDE: $*; added to decide.txt, released for a decide-mode round"
  release_claim; exit 30
}
capped(){ if [ "$IS_DECIDE" = 0 ]; then to_decide "attempt cap: $*"; fi; parked "attempt cap in decide mode: $*"; }
LIMIT_RE="hit your (weekly|usage|session|daily) limit|usage limit (reached|exceeded)|weekly limit|infra refusal"
log_mark(){ wc -l < "$LOG"; }
limit_since(){ tail -n +"$(( $1 + 1 ))" "$LOG" | grep -qiE "$LIMIT_RE"; }
cap_exit(){ transient "usage limit hit during $1 (lane capped, not a task defect); released without spending an attempt"; }
progress(){   # $1 blocker signature, $2 description. Identical blocker STUCK_LIMIT times running -> decide / park.
  if [ "$1" = "$LAST_SIG" ]; then SAME=$((SAME+1)); else SAME=0; fi
  LAST_SIG="$1"
  if [ "$SAME" -ge "$STUCK_LIMIT" ]; then
    [ "$IS_DECIDE" = 0 ] && to_decide "identical blocker $SAME attempts ($2)"
    parked "no progress in decide mode: identical blocker $SAME attempts ($2)"
  fi
}
touch "$LOG"
log "START ekw v1 (max $MAX_FIX_ATTEMPTS attempts, stuck limit $STUCK_LIMIT)"
for _w in $(seq 1 24); do [ -x "$CB" ] && break; sleep 5; CB="$(command -v claude 2>/dev/null || echo /usr/bin/claude)"; done
[ -x "$CB" ] || transient "no usable claude binary ($CB) - env broken, retry elsewhere"
RULES_FILE="$TOOLS/svc_fix_method_rules.md"
if [ -f "$RULES_FILE" ]; then RULES="$(cat "$RULES_FILE")"; MV="$(head -1 "$RULES_FILE" | sed -n 's/^METHOD_VERSION: *//p')"; else RULES=""; MV="none"; fi
EKW_MV="ekw-v1/${MV}"

freeze_check(){
  grep -qx "$TASK" "$WORK/accepted.txt" 2>/dev/null && parked "on the EKW accepted list - never re-touched"
  grep -qx "$TASK" "$WORK/do_not_touch.txt" 2>/dev/null && parked "on the EKW do-not-touch list"
  return 0
}
freeze_check

# Retire a stale ready zip the moment the task is reworked (the SVC stale-zip lesson, 2026-09-22).
if [ -f "$WORK/ready/$TASK.zip" ] || [ -f "$WORK/ready/$TASK.zip.manifest.json" ]; then
  mkdir -p "$WORK/ready/_superseded"; STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  for f in "$WORK/ready/$TASK.zip" "$WORK/ready/$TASK.zip.manifest.json"; do [ -f "$f" ] && mv "$f" "$WORK/ready/_superseded/$(basename "$f").$STAMP"; done
  log "retired the existing ready zip (task is being reworked)"
fi

# Intake: _pull -> _raw once. rc 3 = an input no fix can create (no verifier.json, prompt or golden) -> park.
if [ ! -d "$RAW" ]; then
  NOUT="$("$PY" "$TOOLS/ekw_intake.py" normalize "$TASK" 2>&1)"; NRC=$?
  printf '%s\n' "$NOUT" >> "$LOG"
  [ "$NRC" = 3 ] && parked "intake: missing input no fix can create: $(printf '%s' "$NOUT" | tr '\n' ' ' | grep -oE '"missing": \[[^]]*\]' | cut -c1-200)"
  [ "$NRC" = 2 ] && parked "intake tool error: $(printf '%s' "$NOUT" | tail -3 | tr '\n' ' ' | cut -c1-200)"
fi
[ -d "$RAW" ] || parked "no _raw package at $RAW after intake"
rm -rf "$WORK/snaps/$TASK"; cp -r "$RAW" "$WORK/snaps/$TASK"   # recoverable if a fix step wrecks the source

IS_DECIDE=0; grep -qx "$TASK" "$WORK/decide.txt" 2>/dev/null && IS_DECIDE=1
[ "$IS_DECIDE" = 1 ] && STUCK_LIMIT=2
# Seed: a NOT-READY verify record on disk -> start in fix mode from it; decide list -> decide; else gate first.
if [ "$IS_DECIDE" = 1 ]; then MODE="decide"; DIRECTIVE="$( [ -s "$GJ" ] && cat "$GJ"; [ -s "$VREC" ] && cat "$VREC" )"
elif [ -s "$VREC" ] && grep -qi "VERDICT: *NOT-READY" "$VREC"; then MODE="fix"; DIRECTIVE="$(cat "$VREC")"; log "seeding fix mode from the existing NOT-READY verify record"
else MODE="gate"; DIRECTIVE=""; fi

EDIT_SCOPE="Edit ONLY files under $RAW: verifier.json (the rubric; keep the EKW schema: {task_id, config:{models, temperature}, verifiers:[{name, metadata:{how_justification (string), why_justification (string), tag (string), weight, grading_role, importance}, source:{type:\"file\", file:{type, command:\"extract_text\", arguments:{path:\"output/<deliverable>\"}}}, assertion:{type:\"rubric\", expected:true, rubric:{prompt:\"<string>\"}}}]}, weights summing to 1.0), prompt.txt (the solver prompt), and files in expert_solution/ (the golden). Source documents in source_documents/ are evidence: never edit them. Never edit $PKG or $EKW_ROOT/_harbor: they are regenerated from $RAW after you finish. Never put expected values, rubric text or golden content into prompt.txt."

VPROMPT="Adversarially audit EKW task $TASK. The authoring source is $RAW (prompt.txt, verifier.json, expert_solution/ = golden, source_documents/ = inputs); the package DataOS grades is $PKG (instruction.md, tests/deliverables*/judge.toml, solution/files/). Read the prompt, every judge.toml criterion, the golden and the sources. Produce a per-criterion table (criterion | what it grades | prompt line | verdict) and check ALL of:
(1) OVER-ENFORCEMENT: a criterion fails a response for something the prompt does not require, forbids something it permits, or pins one method/figure/format the prompt leaves open.
(2) COVERAGE: a prompt requirement no criterion grades.
(3) GOLDEN-SATISFIES-EVERY-CRITERION: open the golden and confirm it passes each criterion; name any it fails.
(4) GROUNDING: every value a criterion expects is derivable from source_documents/ (recompute the key figures; name any criterion whose expected value the sources contradict or cannot settle).
(5) VERIFIABILITY: a criterion the judge cannot check from the extracted text of the graded file (formula cells without stored values, content in images, a file the criterion's files= list does not include).
(6) LEAKS: prompt.txt / instruction.md carrying expected values, rubric wording or golden content.
The deterministic EKW checks already ran; their non-blocking findings are below as evidence to weigh (a finding there is not automatically a defect).
For EVERY blocking defect give the criterion (verifier name in verifier.json), the file, and the exact edit to $RAW that fixes it. End with 'VERDICT: READY-TO-RESUBMIT' only if (1)-(6) have no blocking defect, else 'VERDICT: NOT-READY' naming each defect and its fix. Do not edit any file.
${RULES:+
=== THE FIX RULES (tools/svc_fix_method_rules.md, $MV; written for SVC, apply the ones about criteria, coverage and goldens) ===
$RULES}"

attempt=0
while [ "$attempt" -lt "$MAX_FIX_ATTEMPTS" ]; do
  attempt=$((attempt+1)); freeze_check
  log "=== attempt $attempt/$MAX_FIX_ATTEMPTS (mode=$MODE) ==="

  # 1. fix / decide step (skipped when MODE=gate: a fresh task runs the gates before any edit)
  if [ "$MODE" != "gate" ]; then
    if [ "$MODE" = "decide" ]; then
      PROMPT="DECISION RUN for EKW task $TASK. Earlier attempts repeated one fix against one blocker and failed the same gate. Do not repeat that edit. For EACH blocking finding below decide exactly one:
 (a) FIX: make the edit that closes it (rubric, prompt or golden), recomputing any value from the sources.
 (b) WAIVE (deterministic EKW check findings only): the finding is false on this task. Add an entry to $WORK/waivers/$TASK.json as {\"<check name>\": \"<evidence: the file and record that proves the finding false>\"} (merge with existing entries). A waiver without a concrete citation is not allowed.
 (c) DROP: delete a criterion that grades something the sources cannot settle or the prompt does not require; renormalise the remaining weights to sum to 1.0.
This is non-interactive: run every command in the foreground and finish all edits before you stop. Print a table of your decisions at the end.
$EDIT_SCOPE
BLOCKING FINDINGS:
$DIRECTIVE"
      TO=2400
    else
      PROMPT="TARGETED FIX for EKW task $TASK. Fix every finding below, and for each one fix the whole family it belongs to (every period, party, file, section the same defect applies to), not only the cited member. Recompute any value you touch from source_documents/ and show the computation. Re-read every criterion you change and confirm the golden in expert_solution/ satisfies it. Do not rewrite criteria no finding touches.
$EDIT_SCOPE
FINDINGS:
$DIRECTIVE${RULES:+

=== THE FIX RULES (tools/svc_fix_method_rules.md, $MV) ===
$RULES}"
      TO=1800
    fi
    M0="$(log_mark)"
    ( cd "$RAW" && timeout "$TO" "$CB" -p "$PROMPT" --model opus --permission-mode dontAsk \
        --allowedTools "Read,Edit,Write,Bash,Glob,Grep" ) >> "$LOG" 2>&1
    log "fix step rc=$? (attempt $attempt, mode $MODE)"
    limit_since "$M0" && cap_exit "the fix step"
  fi
  [ "$IS_DECIDE" = 1 ] && MODE="decide" || MODE="fix"

  # 2. schema check of the authoring source
  COUT="$("$PY" "$TOOLS/ekw_intake.py" check "$TASK" 2>&1)"; CRC=$?
  printf '%s\n' "$COUT" >> "$LOG"
  [ "$CRC" = 3 ] && parked "missing input no fix can create: $(printf '%s' "$COUT" | grep -oE '"missing": \[[^]]*\]' | cut -c1-200)"
  [ "$CRC" = 2 ] && transient "schema check tool error (not a task defect): $(printf '%s' "$COUT" | tail -2 | tr '\n' ' ' | cut -c1-200)"
  if [ "$CRC" != 0 ]; then
    progress "schema:$(printf '%s' "$COUT" | md5sum | cut -c1-12)" "verifier.json schema"
    DIRECTIVE="verifier.json does not validate against the EKW verifier library schema (the copy tasks execute). Rewrite it into the schema, keeping every criterion's intent, weight and graded file. Validator output:
$COUT"; log "schema check failed; feeding back"; continue
  fi

  # 3. build: harbor tree for the EKW checks + the DataOS package
  BOUT="$("$PY" "$TOOLS/ekw_intake.py" build "$TASK" 2>&1)"; BRC=$?
  printf '%s\n' "$BOUT" >> "$LOG"
  [ "$BRC" = 3 ] && parked "build: missing input: $(printf '%s' "$BOUT" | tail -3 | tr '\n' ' ' | cut -c1-200)"
  if [ "$BRC" != 0 ]; then
    progress "build:$(printf '%s' "$BOUT" | grep -E 'REFUSED|PROBLEM|ASSEMBLE' | md5sum | cut -c1-12)" "build/convert refusal"
    DIRECTIVE="Building the DataOS package from $RAW failed (converter refusal or self-check problem). Fix the cause in $RAW (for example: a graded deliverable name with no matching golden in expert_solution/, a source file with the same name as a graded deliverable, a verifier with no output/<file> path). Build output:
$BOUT"; log "build failed; feeding back"; continue
  fi

  # 4. EKW deterministic gate (Check B + shared checks)
  GOUT="$("$PY" "$TOOLS/ekw_gate.py" "$TASK" --out "$GJ" 2>&1)"; GRC=$?
  printf '%s\n' "$GOUT" | tail -60 >> "$LOG"
  [ "$GRC" = 2 ] && transient "EKW gate produced no verdict (tool error, not a task defect)"
  if [ "$GRC" != 0 ]; then
    BL="$("$PY" -c "import json;d=json.load(open('$GJ'));print('\n'.join('- %s (%s x%s): %s  [details: %s]'%(b['check'],b['verdict'],b['count'],b['first'],b['json']) for b in d['blocking']))" 2>&1)"
    progress "gate:$("$PY" -c "import json;print(sorted(b['check'] for b in json.load(open('$GJ'))['blocking']))" 2>/dev/null | md5sum | cut -c1-12)" "EKW gate blocking checks"
    DIRECTIVE="The EKW deterministic checks (ekw_run_checks.py) FAIL on this task. Each line names the check, its first finding, and the JSON with every finding. Read the JSON, then fix the cause in $RAW:
$BL"; log "EKW gate FAIL: $(printf '%s' "$BL" | cut -c1-80 | tr '\n' ';')"; continue
  fi
  log "EKW gate PASS ($("$PY" -c "import json;d=json.load(open('$GJ'));print('advisory=%d harness=%d waived=%d errors=%d'%(len(d['advisory']),len(d['harness']),len(d['waived']),len(d['errors'])))" 2>/dev/null))"

  # 5. oracle: the golden must score 1.0 against its own rubric (one run per attempt; a confirm run before the zip)
  rm -f "/tmp/${TASK}_ekw.json"
  # 2026-09-29: outer oracle timeout 2400 -> 5400 s. judge_emulate grades judge groups one at a time, and
  # SVC-PC-68-0-0 (24 groups, 322 criteria) was killed at 2400 s 125 times since 09-25, each read as TRANSIENT
  # and released without an attempt, while an unbounded run scored its golden 1.0. EKW oracle median 313 s, p90 886 s.
  ORC_OUT="$(timeout 5400 "$PY" "$TOOLS/judge_emulate.py" oracle "$TASK" --runs 1 --corpus-root "$EKW_ROOT" --out "/tmp/${TASK}_ekw.json" 2>&1)"
  printf '%s\n' "$ORC_OUT" >> "$LOG"
  # 2026-09-28: judge_emulate prints "infra refusal" for ANY backend failure, and LIMIT_RE matches that, so a judge
  # call that simply timed out was released as "lane capped". SCO-205 looped 174 times across lanes on this. A timeout
  # with no real usage-limit text is the task's judge input being too large: feed it back as a fix, counted by progress.
  if printf '%s' "$ORC_OUT" | grep -q "timed out after" \
     && ! printf '%s' "$ORC_OUT" | grep -qiE "hit your (weekly|usage|session|daily) limit|usage limit (reached|exceeded)|weekly limit"; then
    progress "orc:judge-timeout" "oracle judge call timed out (task judge input too large)"
    DIRECTIVE="The oracle could not grade the golden: the judge call timed out twice at 300s. That is this task's judge input being too large or slow, not a lane cap. Find the judge group(s) with the largest judge prompt (criteria count, plus the size of the files each group's files= list feeds the judge) and shrink them: split any group over 15 criteria, narrow files= to the files those criteria actually grade, drop duplicate criteria. Do not remove required coverage and do not lower difficulty."
    log "oracle judge timed out (task-side, not a cap); feeding back"; continue
  fi
  printf '%s' "$ORC_OUT" | grep -qiE "$LIMIT_RE" && cap_exit "the oracle"
  REW="$("$PY" -c "import json;print(json.load(open('/tmp/${TASK}_ekw.json')).get('total_reward'))" 2>/dev/null || echo none)"
  log "oracle total_reward=$REW (attempt $attempt)"
  if [ "$REW" != "1.0" ]; then
    if [ "$REW" = "none" ] || [ "$REW" = "None" ] || [ -z "$REW" ]; then
      # 2026-09-26: a full disk (OSError Errno 28) parked 10 EKW tasks as a tool bug; it is infra: release and retry.
      printf '%s' "$ORC_OUT" | grep -qE "No space left on device|Errno 28" && transient "disk full during the oracle (infra, not the task); released"
      printf '%s' "$ORC_OUT" | grep -q "^Traceback" && parked "oracle CRASHED (judge_emulate.py traceback, a tool bug): $(printf '%s' "$ORC_OUT" | grep -E '^[A-Za-z]+(Error|Exception)' | tail -1 | cut -c1-160)"
      transient "oracle produced no reward (lane capped / infra); released"
    fi
    progress "orc:$REW" "golden stuck at oracle reward $REW"
    DIRECTIVE="The oracle scored the golden at $REW (< 1.0): the golden in expert_solution/ FAILS at least one criterion. Per-criterion scores are in /tmp/${TASK}_ekw.json. For each criterion below 1: if the golden is wrong, recompute the value from source_documents/ and fix the golden file; if the criterion over-enforces against a correct golden, loosen or delete it in verifier.json. Do not add criteria."
    log "oracle below 1.0; feeding back"; continue
  fi

  # 6. adversarial verify (read-only agent). Temp file first: a refused/empty verify never replaces the last verdict.
  ADV="$("$PY" -c "import json;d=json.load(open('$GJ'));print('\n'.join('- %s %s x%s: %s'%(x['check'],x['verdict'],x['count'],x['first'][:300]) for x in d['advisory']+d['waived']))" 2>/dev/null)"
  M0="$(log_mark)"
  ( cd "$RAW" && timeout 1800 "$CB" -p "$VPROMPT
=== NON-BLOCKING EKW CHECK FINDINGS ===
${ADV:-none}" --model opus --permission-mode dontAsk --allowedTools "Read,Bash,Glob,Grep" ) > "$VREC.tmp" 2>> "$LOG"
  if grep -qiE "$LIMIT_RE" "$VREC.tmp" || limit_since "$M0"; then rm -f "$VREC.tmp"; cap_exit "the adversarial verify"; fi
  [ -s "$VREC.tmp" ] || { rm -f "$VREC.tmp"; transient "adversarial verify produced no output; released"; }
  mv -f "$VREC.tmp" "$VREC"; printf '\nMETHOD_VERSION: %s\n' "$EKW_MV" >> "$VREC"
  LASTV="$(grep -oiE 'VERDICT: *\**(READY-TO-RESUBMIT|NOT-READY)' "$VREC" | tail -1)"
  if ! printf '%s' "$LASTV" | grep -qi "READY-TO-RESUBMIT"; then
    # 2026-09-25: the signature is the criteria named in the closing VERDICT paragraph (the blocking defects), not every
    # criterion id in the record. The record always carries the full per-criterion table, so the old signature never
    # changed and parked LGL-178 as "no progress" while each round fixed different blocking defects.
    # 2026-09-26: this matched a lowercase-only v<N> pattern, so tasks whose criteria are named V05 / NUM01 / FC01
    # never matched a real criterion; it matched "v1" and "v8" inside the METHOD_VERSION line appended to every
    # verify record instead, so ANY two NOT-READY verdicts read as "the same blocker" and SCO-226 / SCO-174 parked
    # as stuck while each round found a different defect. Fingerprint only the task's REAL criterion names (from
    # verifier.json) cited in the closing verdict paragraph, never the METHOD_VERSION line; fall back to the
    # paragraph text when no criterion is named.
    VPARA="$(awk 'BEGIN{IGNORECASE=1} /VERDICT:/{buf=""} {buf=buf"\n"$0} END{print buf}' "$VREC" | grep -v '^METHOD_VERSION:')"
    CNAMES="$("$PY" -c "import json,sys
try:
    print('\n'.join(v.get('name','') for v in json.load(open(sys.argv[1],encoding='utf-8')).get('verifiers',[]) if v.get('name')))
except Exception:
    pass" "$RAW/verifier.json" 2>/dev/null)"
    VSIG=""
    [ -n "$CNAMES" ] && VSIG="$(printf '%s\n' "$VPARA" | grep -owF -f <(printf '%s\n' "$CNAMES") | sort -u | tr '\n' ' ')"
    [ -z "$VSIG" ] && VSIG="$(printf '%s' "$VPARA" | tr -s '[:space:]' ' ' | cut -c1-400)"
    progress "vf:$(printf '%s' "$VSIG" | md5sum | cut -c1-12)" "adversarial verify blocks on the same criteria ($VSIG)"
    DIRECTIVE="$(cat "$VREC")"; log "adversarial verify NOT-READY; feeding back"; continue
  fi
  log "adversarial verify READY (attempt $attempt)"

  # 7. oracle confirm on the final bytes (the second of two 1.0 runs)
  rm -f "/tmp/${TASK}_ekwc.json"
  ORC_OUT="$(timeout 5400 "$PY" "$TOOLS/judge_emulate.py" oracle "$TASK" --runs 1 --corpus-root "$EKW_ROOT" --out "/tmp/${TASK}_ekwc.json" 2>&1)"
  printf '%s\n' "$ORC_OUT" >> "$LOG"
  printf '%s' "$ORC_OUT" | grep -qiE "$LIMIT_RE" && cap_exit "the oracle confirm run"
  REW2="$("$PY" -c "import json;print(json.load(open('/tmp/${TASK}_ekwc.json')).get('total_reward'))" 2>/dev/null || echo none)"
  log "oracle confirm total_reward=$REW2 (attempt $attempt)"
  if [ "$REW2" != "1.0" ]; then
    { [ "$REW2" = "none" ] || [ "$REW2" = "None" ] || [ -z "$REW2" ]; } && transient "oracle confirm produced no reward; released"
    progress "orc2:$REW2" "criterion flips between oracle runs"
    DIRECTIVE="The golden scored 1.0 on the first oracle run but $REW2 on the confirm run: a criterion flips on identical bytes (details /tmp/${TASK}_ekwc.json). Split multi-clause criteria into one-fact criteria in verifier.json, or make the golden state the fact unambiguously. Do not loosen a criterion to fit a wrong golden."
    log "oracle confirm not 1.0; feeding back"; continue
  fi

  # 8. prefilter HARD defects on the package (grammar bomb, files= gap, answer-key leak, lease.json, mojibake)
  POUT="$("$PY" "$TOOLS/svc_prefilter.py" "$PKG" 2>&1)"; PRC=$?
  printf '%s\n' "$POUT" >> "$LOG"
  if [ "$PRC" != 0 ]; then
    progress "pf:$(printf '%s' "$POUT" | grep -i hard | md5sum | cut -c1-12)" "prefilter HARD defect"
    DIRECTIVE="The package pre-screen found HARD defects. Fix their cause in $RAW (the package is regenerated from it):
$POUT"; log "prefilter HARD; feeding back"; continue
  fi

  # 9. zip + freshness manifest (hashes of every packaged file, the verify record, gate JSON and raw verifier)
  ZOUT="$("$PY" "$TOOLS/ekw_intake.py" package "$TASK" --zip "$WORK/ready/$TASK.zip" --evidence "$VREC" --evidence "$GJ" 2>&1)"; ZRC=$?
  printf '%s\n' "$ZOUT" >> "$LOG"
  [ "$ZRC" = 0 ] || parked "zip cold audit refused a package every gate passed (tool/packaging bug): $(printf '%s' "$ZOUT" | tr '\n' ' ' | cut -c1-200)"
  # 9b. 2026-09-29: a fix round after a DataOS reject can leave the package byte-identical to the rejected shipment
  # (MKT-160: fix step 3 min, no edit, then local oracle 1.0 + verify READY on the bytes ekw-v1-batch57 rejected 0 of 2).
  # The bundler refuses those bytes, so the task sat READY and refused with no lane on it. Never finish READY on bytes
  # DataOS already rejected: drop the zip and feed the DataOS findings back. A never-graded task (needs_regrade.txt)
  # is exempt. A constant signature lets a repeat escalate to decide mode through progress().
  if [ -s "$WORK/shipped/$TASK.json" ] && [ -s "$WORK/lastreject/$TASK.lastreject.sha" ] \
     && ! grep -qx "$TASK" "$WORK/needs_regrade.txt" 2>/dev/null; then
    UNCH="$("$PY" -c 'import json,sys; sys.path.insert(0,"/root/qc/tools"); import ekw_bundle_upload as b; p=json.load(open(sys.argv[1])); m=json.load(open(sys.argv[2])); print(("same " if p.get("pkg_hash")==b.pkg_hash(m.get("files") or {}) else "diff ")+str(p.get("bundle")))' "$WORK/shipped/$TASK.json" "$WORK/ready/$TASK.zip.manifest.json" 2>>"$LOG")"
    if [ "${UNCH%% *}" = same ]; then
      rm -f "$WORK/ready/$TASK.zip" "$WORK/ready/$TASK.zip.manifest.json"
      progress "unchanged-after-reject" "fix round left the package byte-identical to the rejected ${UNCH#* }"
      DIRECTIVE="DataOS REJECTED these exact package bytes in ${UNCH#* }, and this round left the package unchanged, so it cannot be resubmitted. A local oracle of 1.0 and a READY verify are not evidence it is fixed: DataOS's reviewers found the majors in the brief below. Close each one with an edit in $RAW (prompt.txt, verifier.json or the golden in expert_solution/), following the brief's method and any OWNER DECISION in it.
$(cat "$WORK/briefs/$TASK.md" 2>/dev/null)"
      log "package byte-identical to the rejected ${UNCH#* }; feeding the DataOS findings back"; continue
    fi
  fi
  log "READY -> $WORK/ready/$TASK.zip (converged in $attempt attempt(s))"
  echo "$TASK	$LANE	$(date -u +%FT%TZ)	attempts=$attempt" >> "$WORK/ready.txt"
  exit 0
done
capped "did not converge in $MAX_FIX_ATTEMPTS attempts (last blocker: ${LAST_SIG:-unknown})"
