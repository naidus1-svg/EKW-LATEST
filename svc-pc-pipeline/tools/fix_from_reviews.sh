#!/usr/bin/env bash
# fix_from_reviews.sh - 2026-09-19 01:40Z: drives ONE fix round per task from
# tools/bulk_review.sh's round0 workspace reviews (CR.glm.round0.json +
# CR.sonnet.round0.json, canon ekw-svc-comprehensive-review.md section 5
# schema), instead of gate_task.sh's own single-reviewer blind CR loop.
#
# Reuses gate_task.sh's existing fix-round mechanism EXACTLY (render
# fix_plan.md with CR_JSON + FILES_TEXT + PRIOR_PLANS_TEXT, llm_call.py
# --model opus, apply_plan.py --fix-log, run_task_scans) - the shell
# functions below are copied from tools/gate_task.sh, not sourced or
# imported, because gate_task.sh is owned by another session and must not
# be edited (see HANDOFF.md / the mechanical-fix brief). Any future change
# to gate_task.sh's own run_task_scans does NOT automatically propagate
# here; keep this file's copy in sync by hand if that ever matters.
#
# Behaviour: loops every 60s over stream-pipe/SVC-PC-*. For a task where
# both CR.glm.round0.json and CR.sonnet.round0.json parse and no
# FIX_FROM_REVIEWS_1 marker exists in STATE: builds the union of major
# findings from both (tools/build_review_union.py) into
# CR.union.round0.json. Empty union -> mark FIX_FROM_REVIEWS_1 and skip
# (no model call spent). Non-empty -> ONE fix round with an Opus lane taken
# round-robin from the 11-lane pool, fix-log to FIX-FROM-REVIEWS.md, mark
# FIX_FROM_REVIEWS_1, then launch round1 re-reviews (glm + sonnet) via
# run_workspace_review.py with the same arguments tools/bulk_review.sh uses.
#
# Concurrency cap: 12 fix-round jobs at once (matches bulk_review.sh's own
# --conc default). Idempotent and safe to relaunch: the STATE marker gates
# re-processing across script restarts, and a per-task flock
# ($PIPE/fix_from_reviews.lock, a DIFFERENT lock file from gate_task.sh's
# own gate_task.lock) gates re-processing across overlapping scan passes
# within one run (a fix round can easily outlive one 60s scan interval).
#
# 2026-09-19 01:50Z, three changes from the laptop session:
#   1. A round0 reviewer file that parses but lacks checks[]/overall_verdict
#      (a stale pre-canon file bulk_review.sh's own weaker "parses = done"
#      idempotency check never re-runs) is treated as MISSING, not
#      zero-major: quarantined to CR.<reviewer>.round0.bad.<time>.json and
#      that reviewer re-run. FIX_FROM_REVIEWS_1 is never marked until both
#      files are genuinely canon-shaped. (Caught real: SVC-PC-92-3-0's
#      CR.glm.round0.json was an old M1-M6 matrix dict with no checks[];
#      its incorrect FIX_FROM_REVIEWS_1 mark was undone by hand.)
#   2. The Opus fix-plan call prefers /root/.claude-q and /root/.claude-r
#      (fresh accounts, fix-plan-only) before falling back to the review
#      POOL, so a fix plan never competes with a Sonnet round1 review for
#      the same account's rolling window.
#   3. If the two reviewers disagree on majors-present (one majors, one
#      zero) at BOTH round0 and round1 for the same task - not resolved by
#      the fix round in between - a third review runs with --reviewer opus
#      on lane -q or -r, and ITS verdict governs; logged as ADJUDICATED in
#      STATE. A single-round disagreement is left alone as ordinary
#      reviewer noise.
#
# 2026-09-19 02:00Z, fourth change: the actuator (stage_and_zip.sh) can
# still block a task even when both reviewers say zero majors, on a
# deterministic checker cell the reviewers never see (real on
# SVC-PC-82-1-0/92-1-0/92-4-0: judge_scope_over_inclusion=fail, the same
# mechanism as DataOS's 67-1-0 major 1.5). build_review_union.py now also
# reads $PIPE/checks/recheck/summary.csv (when present) and folds in every
# cell that would block per stage_and_zip.sh's own gate rule (an exact port
# of that rule, not a paraphrase of it - see build_review_union.py's own
# comment) as a class-1.5 major finding, so an all-reviewers-clean task with
# a real blocking cell no longer gets skipped.
#
# 2026-09-19 02:55Z, fifth change (laptop coordinator finding 1): there was
# no second round - FIX_FROM_REVIEWS_1 gated a task out for good even if
# round1's re-review still showed majors, contradicting GATE-V2 rule 4 and
# lanes/MAX_ROUNDS=2. Now: once both round1 files are canon-shaped, build
# the union of round1 majors (same build_review_union.py, same recheck-csv
# fold-in, now against round1 output). Empty -> mark FIX_FROM_REVIEWS_2,
# done. Non-empty -> one more fix round (PLAN.fixreviews2.json, prior plans
# text now includes round1's own PLAN.fixreviews.json so GAP 1 escalation
# sees what round1 already tried at the same spot), mark FIX_FROM_REVIEWS_2,
# re-review both as round2. If round2's union is STILL non-empty, append to
# PARKED.md naming every surviving major finding - two rounds is the
# configured ceiling, a third round is a human decision, not this script's.
#
# Structural correction within this same change: round2 logic living only
# at process_task's own tail never fires for a task whose FIX_FROM_REVIEWS_1
# was marked in an EARLIER dispatcher run - the main scan loop's eligibility
# check used to `continue` past any FIX_FROM_REVIEWS_1-marked task
# unconditionally, before ever reaching that code. Caught real (laptop
# coordinator finding 1): 8 tasks were stuck this way. round2 now lives in
# its own process_round2 function, callable both from process_task's tail (a
# task that just went through round0->round1 in this same invocation) and
# from the main scan loop's own round2 branch (a task already marked
# FIX_FROM_REVIEWS_1 with both round1 files present) via process_round2_entry.
#
# 2026-09-19 04:00Z, sixth change (laptop coordinator, 03:59Z):
#   1. probes/oracle.json's total_reward < 1.0 blocks stage_and_zip.sh's
#      gate (exit 8, "GATE-V2 3.4, DataOS 1.1/1.5") even when both reviewers
#      and every recheck cell pass - real on SVC-PC-26-7-0 (0.973) and
#      SVC-PC-53-3-0 (0.9), neither a check cell nor a reviewer major.
#      build_review_union.py now also reads --oracle-json (when present) and
#      folds every failed criterion in as a class-1.1 major, carrying the
#      judge's own verdict_text as the finding's description - skipped
#      entirely if any criterion anywhere carries a transport error (a
#      judge-API failure, not a real golden defect).
#   2. guard_rt.py re-opens an rc=5 block (clears FIX_FROM_REVIEWS_* from
#      STATE, refreshes checks/recheck/) up to twice per task, but a full
#      alphabetical scan pass takes ~40 minutes, so a task re-opened mid-pass
#      could sit for most of that. The scan loop now checks
#      /root/qc/lanes/FIX_FROM_REVIEWS_PRIORITY (one task name per line)
#      FIRST every pass - see the PRIORITY_FILE comment below.
#
# Usage:
#   nohup /root/qc/tools/fix_from_reviews.sh \
#     > /root/qc/_prompts/fix_from_reviews.nohup.log 2>&1 &
set -uo pipefail
cd /root/qc || exit 1

# All overridable via env for dry-testing against a scratch tree without touching
# the live corpus/pipeline state; defaults are the real production paths.
CORPUS="${CORPUS:-/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready}"
TOOLS=/root/qc/tools
PROMPTS="$TOOLS/prompts"
PIPE_ROOT="${PIPE_ROOT:-/root/qc/stream-pipe}"
REVIEW_WS="${REVIEW_WS:-/root/qc/review_workspace_bulk}"   # same workspace root bulk_review.sh uses
RUNS_ROOT="${RUNS_ROOT:-/root/qc/runs}"
LOG="${FIX_FROM_REVIEWS_LOG:-/root/qc/_prompts/fix_from_reviews.log}"
CONC="${FIX_FROM_REVIEWS_CONC:-60}"
# Session-aware admission (laptop, 2026-09-19 15:35). A new task cycle starts only while fewer than CONC cycles run AND fewer than SESS_MAX pooled `claude -p` sessions
# are alive (GLM solver agents excluded: they use the GLM proxy). The load average is a poor signal here: on 2026-09-19 it read 130 to 200 on 32 cores while 26 sessions used about
# 2 cores; the rest was niced python scans and the agents' own workbook loads. The load brake stays only as an emergency (LOAD_EMERGENCY).
SESS_MAX="${FIX_FROM_REVIEWS_SESSIONS_MAX:-75}"
LOAD_EMERGENCY="${FIX_FROM_REVIEWS_LOAD_EMERGENCY:-150}"
sessions_now() { ps -eo args --no-headers | grep '[c]laude -p' | grep -vc 'glm-5'; }
admit_wait() { while [ "$(jobs -rp | wc -l)" -ge "$CONC" ] || [ "$(sessions_now)" -ge "$SESS_MAX" ] || [ "$(cut -d. -f1 /proc/loadavg)" -gt "$LOAD_EMERGENCY" ]; do sleep 10; done; }
SCAN_INTERVAL="${FIX_FROM_REVIEWS_INTERVAL:-60}"
POOL=(/root/.claude /root/.claude-b /root/.claude-c /root/.claude-d /root/.claude-e /root/.claude-f /root/.claude-g /root/.claude-i /root/.claude-j /root/.claude-k /root/.claude-l /root/.claude-p /root/.claude-m /root/.claude-v /root/.claude-w /root/.claude-x)  # 00:27Z: m unreserved, v and w added by Khiem and probed ok
# Change 2 (laptop, 2026-09-19 01:50Z): -q and -r are fresh accounts Khiem
# added specifically so an Opus fix-plan call never competes with a Sonnet
# round1 review for the same account's rolling window. Fix-round lanes try
# -q/-r first, then fall back to the same POOL the reviews use. Round1
# review lanes (next_lane/POOL) are UNCHANGED - reviews never draw from
# -q/-r, keeping the two pools disjoint in practice even though
# bulk_review.sh's own POOL was separately widened to include -q/-r too
# (that script is owned by another session; not mine to reconcile).
FIX_LANE_POOL=(/root/.claude-q /root/.claude-r "${POOL[@]}")
# Change 3's adjudication lane is restricted to just -q/-r (no pool
# fallback) - picked as a pure function of the task name, not a shared
# counter, since this is chosen from INSIDE a backgrounded process_task
# subshell where a shared mutable index wouldn't be visible across
# concurrent tasks (each subshell only sees the counter value it inherited
# at fork time).
ADJUDICATE_POOL=(/root/.claude-q /root/.claude-r)
adjudicate_lane_for() {
  local h
  h=$(printf '%s' "$1" | cksum | cut -d' ' -f1)
  echo "${ADJUDICATE_POOL[$(( h % ${#ADJUDICATE_POOL[@]} ))]}"
}

mkdir -p "$(dirname "$LOG")"
touch "$LOG"
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG" >&2; }

# shellcheck disable=SC1091
source /root/venv/bin/activate 2>/dev/null || true

json_ok() { python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$1" 2>/dev/null; }
step_done_in() { grep -qx "$2" "$1" 2>/dev/null; }   # step_done_in STATE_FILE MARKER
mark_done_in() { echo "$2" >> "$1"; }                 # mark_done_in STATE_FILE MARKER

# Change 1 (laptop, 2026-09-19 01:50Z): a reviewer file that merely PARSES is
# not necessarily a real review - bulk_review.sh's own idempotency check
# (json.load succeeds) treats any parseable JSON as "done", so a stale
# pre-canon file (e.g. SVC-PC-92-3-0's CR.glm.round0.json: an old M1-M6
# matrix dict with no checks[]/overall_verdict, left over from before the
# canon-schema redirect) is silently never re-run and silently read here as
# "0 majors" - it is not a zero-major review, it is a missing one.
canon_ok() {
  python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
sys.exit(0 if ('overall_verdict' in d and isinstance(d.get('checks'), list)) else 1)
" "$1" 2>/dev/null
}

# unknown | 0 | 1 - used by the round0-vs-round1 disagreement check (change
# 3); "unknown" for anything canon_ok would reject, so a missing/malformed
# file never counts as either side of a disagreement.
reviewer_majors() {
  local f="$1"
  if ! canon_ok "$f"; then echo unknown; return; fi
  python3 -c "
import json
d = json.load(open('$f'))
mc = d.get('major_count')
print('unknown' if mc is None else ('1' if int(mc) > 0 else '0'))
" 2>/dev/null || echo unknown
}

# ---------------------------------------------------------------------------
# Copied verbatim (in spirit - same scans, same flags) from gate_task.sh's
# run_task_scans, since gate_task.sh itself must not be edited. Any 11-scan
# list or flag change there needs the same edit made here by hand.
# ---------------------------------------------------------------------------
run_task_scans() {
  local task="$1" pipe="$2"
  local scans=(
    "formula_cache_scan.py"
    "quantifier_scope_scan.py"
    "escape_hatch_scan.py"
    "source_reliability_scan.py"
    "rubric_consistency_scan.py"
    "answer_preexposure_scan.py"
    "instruction_input_scan.py"
    "cross_group_duplicate_scan.py"
    "discretion_pin_scan.py"
    "golden_citation_scan.py"
    "muststrip_scan.py"
  )
  for s in "${scans[@]}"; do
    local stem="${s%.py}"
    local extra=()
    if [ "$stem" = "formula_cache_scan" ]; then
      extra=(--exposed-out "$pipe/checks/formula_cache_exposed.csv")
    fi
    python3 "$TOOLS/$s" --task "$task" --corpus-root "$CORPUS" \
      --out "$pipe/checks/$stem.csv" \
      --verdict-out "$pipe/checks/$stem.verdict.csv" \
      "${extra[@]}" >> "$LOG" 2>&1
    if [ $? -ne 0 ]; then
      log "WARNING: $task: $s exited non-zero (fix-from-reviews run_task_scans), see $LOG"
    fi
  done
  for s in env_size_report.py metadata_fill.py; do
    local stem="${s%.py}"
    local scratch_csv="$pipe/checks/_scratch_${stem}.csv"
    local scratch_verdict="$pipe/checks/_scratch_${stem}.verdict.csv"
    python3 "$TOOLS/$s" --corpus-root "$CORPUS" \
      --out "$scratch_csv" --verdict-out "$scratch_verdict" >> "$LOG" 2>&1
    if [ -f "$scratch_verdict" ]; then
      awk -F, -v t="$task" 'NR==1 || $1==t' "$scratch_verdict" > "$pipe/checks/$stem.verdict.csv"
    fi
  done
}

# ---------------------------------------------------------------------------
# Change 1: a round0 reviewer file that exists but fails canon_ok gets
# quarantined (moved aside, never deleted) and that reviewer re-run in
# place, same arguments bulk_review.sh's run_one uses. Per-(task,reviewer)
# flock so an overlapping scan pass does not requeue the same file twice.
# ---------------------------------------------------------------------------
requeue_reviewer() {
  local task="$1" reviewer="$2" lane="$3" pipe="$4"
  local target="$pipe/CR.$reviewer.round0.json"
  local reqlock="$pipe/fix_from_reviews.requeue.$reviewer.lock"

  exec 7>"$reqlock"
  if ! flock -n 7; then
    log "SKIP requeue $task $reviewer (already being re-run)"
    return
  fi
  if canon_ok "$target"; then
    log "SKIP requeue $task $reviewer (became valid while waiting for the lock)"
    return
  fi
  if [ -f "$target" ]; then
    local stamp bad
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    bad="$pipe/CR.$reviewer.round0.bad.$stamp.json"
    mv "$target" "$bad"
    log "QUARANTINE $task $reviewer: $target lacked checks[]/overall_verdict, moved to $bad"
  fi
  log "REQUEUE $task $reviewer lane=$(basename "$lane")"
  CLAUDE_CONFIG_DIR="$lane" python3 "$TOOLS/run_workspace_review.py" --task "$task" --corpus-root "$CORPUS" \
    --workspace-root "$REVIEW_WS/$reviewer" --runs-root "$RUNS_ROOT" --pipe-dir "$pipe" --reviewer "$reviewer" --timeout 2400 \
    --out "$target" --stats-out "$pipe/CR.$reviewer.round0.stats.json" > "$pipe/CR.$reviewer.round0.log" 2>&1
  local rc=$?
  local v
  v=$(python3 -c "import json; j=json.load(open('$target')); print(j.get('overall_verdict'), 'maj', j.get('major_count'), 'min', j.get('minor_count'))" 2>/dev/null || echo "NO-JSON rc=$rc")
  log "FINISH-REQUEUE $task $reviewer rc=$rc $v"
}

# Pure function (task+reviewer+attempt -> lane), safe to call from inside a
# backgrounded subshell (no shared counter to lose - see the next_lane/
# next_fix_lane bug fixed earlier). Only used for a round1 retry's SECOND
# attempt, so it deliberately does not need to be globally round-robin fair.
alt_lane_for() {
  local h
  h=$(printf '%s' "$1$2$3" | cksum | cut -d' ' -f1)
  echo "${POOL[$(( h % ${#POOL[@]} ))]}"
}

# ---------------------------------------------------------------------------
# Re-review for round N (N=1 or 2), same arguments tools/bulk_review.sh's
# run_one uses, just --out/--stats-out/log renamed round0 -> round$n.
#
# Monitoring check, 2026-09-19 02:21Z: found real (not rate-limit) output
# corruption on 2 of 11 completed round1 pairs. SVC-PC-17-2-0's sonnet
# round1.json is a single lone check object with no overall_verdict/
# major_count - its own .raw.txt (3,667 chars, "overall_verdict" appears
# ZERO times) shows the model's response was genuinely truncated mid-JSON,
# and llm_call.py's extract_json_object (shared, not owned by this script -
# gate_task.sh's own CR rounds call through the same path) accepted an
# inner, cleanly-closed check object instead of detecting the truncation
# and failing loudly. SVC-PC-75-1-0's sonnet round1.json is a COMPLETE but
# entirely pre-canon M1-M6 matrix dict, most likely quoted verbatim from a
# stale file the reviewing agent found while reading the staged workspace,
# again picked up by the same extractor. Not this script's bug to fix (see
# the canon_ok comment for why gate_task.sh's own equivalent code has the
# same "extractor grabbed a fragment" note already) - but retrying once on
# a different lane when the output isn't canon_ok is cheap insurance this
# script CAN own, so it does.
# ---------------------------------------------------------------------------
run_review_round() {
  local task="$1" reviewer="$2" lane="$3" pipe="$4" n="$5"
  local out="$pipe/CR.$reviewer.round${n}.json"
  local attempt this_lane rc
  for attempt in 1 2; do
    this_lane="$lane"
    [ "$attempt" -gt 1 ] && this_lane=$(alt_lane_for "$task" "$reviewer" "round${n}attempt${attempt}")
    CLAUDE_CONFIG_DIR="$this_lane" python3 "$TOOLS/run_workspace_review.py" --task "$task" --corpus-root "$CORPUS" \
      --workspace-root "$REVIEW_WS/$reviewer" --runs-root "$RUNS_ROOT" --pipe-dir "$pipe" --reviewer "$reviewer" --timeout 2400 \
      --out "$out" --stats-out "$pipe/CR.$reviewer.round${n}.stats.json" > "$pipe/CR.$reviewer.round${n}.log" 2>&1
    rc=$?
    canon_ok "$out" && break
    log "RETRY-ROUND${n} $task $reviewer attempt=$attempt lane=$(basename "$this_lane") rc=$rc (output missing or not canon-shaped - truncated response or a stray quoted JSON blob grabbed by the shared extractor, not this script's bug; retrying once on a different lane)"
  done
  local v
  v=$(python3 -c "import json; j=json.load(open('$out')); print(j.get('overall_verdict'), 'maj', j.get('major_count'), 'min', j.get('minor_count'))" 2>/dev/null || echo "NO-JSON rc=$rc")
  log "FINISH $task $reviewer round${n} rc=$rc $v"
}

# Pure function, same shape as alt_lane_for/adjudicate_lane_for - called
# from inside a backgrounded process_task subshell (round2's fix-plan lane),
# so it must not depend on a shared mutable counter. Prefers FIX_LANE_POOL
# (-q/-r first, per change 2) without needing the parent's next_fix_lane
# sequencing.
fix_lane_for() {
  local h
  h=$(printf '%s' "$1$2" | cksum | cut -d' ' -f1)
  echo "${FIX_LANE_POOL[$(( h % ${#FIX_LANE_POOL[@]} ))]}"
}

# ---------------------------------------------------------------------------
# One task's full unit of work: build union -> (skip if empty) -> one fix
# round -> mark done -> launch both round1 re-reviews concurrently, wait.
# ---------------------------------------------------------------------------
process_task() {
  local task="$1" lane_fix="$2" lane_glm="$3" lane_sonnet="$4"
  local pipe="$PIPE_ROOT/$task"
  local state="$pipe/STATE"
  local lockfile="$pipe/fix_from_reviews.lock"

  exec 8>"$lockfile"
  if ! flock -n 8; then
    log "SKIP $task (another fix_from_reviews.sh job already holds the lock)"
    return
  fi

  if step_done_in "$state" FIX_FROM_REVIEWS_1; then
    log "SKIP $task (FIX_FROM_REVIEWS_1 already marked, raced with another scan pass)"
    return
  fi

  log "START $task fix-from-reviews (lane=$(basename "$lane_fix"))"

  python3 "$TOOLS/build_review_union.py" --task "$task" \
    --glm "$pipe/CR.glm.round0.json" --sonnet "$pipe/CR.sonnet.round0.json" \
    --recheck-csv "$pipe/checks/recheck/summary.csv" \
    --oracle-json "$pipe/probes/oracle.json" \
    --out "$pipe/CR.union.round0.json" >> "$LOG" 2>&1

  local n_findings
  n_findings=$(python3 -c "import json; print(sum(1 for f in json.load(open('$pipe/CR.union.round0.json')).get('findings', []) if f.get('severity') == 'major'))" 2>/dev/null || echo 0)

  if [ "$n_findings" = "0" ]; then
    mark_done_in "$state" FIX_FROM_REVIEWS_1
    log "SKIP $task (union of round0 majors is empty, marked FIX_FROM_REVIEWS_1, no model call spent)"
    return
  fi

  log "FIX $task: $n_findings unioned major finding(s), running one fix round"

  python3 "$TOOLS/gather_files_text.py" "$pipe/CR.union.round0.json" --task "$task" --corpus-root "$CORPUS" \
    --out "$pipe/FILES_TEXT_fixreviews.txt" >> "$LOG" 2>&1

  echo "(fix-from-reviews track: first and only round for this task under this track - no prior-round edit history applies)" \
    > "$pipe/PRIOR_PLANS_fixreviews.txt"

  if ! python3 "$TOOLS/render_prompt.py" "$PROMPTS/fix_plan.md" \
      --set-lit TASK_ID="$task" --set CR_JSON="$pipe/CR.union.round0.json" \
      --set FILES_TEXT="$pipe/FILES_TEXT_fixreviews.txt" \
      --set PRIOR_PLANS_TEXT="$pipe/PRIOR_PLANS_fixreviews.txt" \
      --out "$pipe/PROMPT_fixreviews.txt" >> "$LOG" 2>&1; then
    log "ERROR $task: render_prompt.py failed on fix_plan.md (fix-from-reviews), see $LOG - not marking done, will retry next scan"
    return
  fi

  if ! CLAUDE_CONFIG_DIR="$lane_fix" python3 "$TOOLS/llm_call.py" --prompt-file "$pipe/PROMPT_fixreviews.txt" \
      --model opus --timeout 1500 --out "$pipe/PLAN.fixreviews.json" >> "$LOG" 2>&1; then
    log "ERROR $task: fix-plan call failed (fix-from-reviews, lane=$(basename "$lane_fix")), see $LOG - not marking done, will retry next scan"
    return
  fi

  python3 "$TOOLS/apply_plan.py" --plan "$pipe/PLAN.fixreviews.json" --task "$task" \
    --corpus-root "$CORPUS" --fix-log "$pipe/FIX-FROM-REVIEWS.md" >> "$LOG" 2>&1
  log "$task: apply_plan.py (fix-from-reviews) exit=$?"

  run_task_scans "$task" "$pipe"
  python3 "$TOOLS/merge_scan_verdicts.py" --reports-dir "$pipe/checks" --out "$pipe/checks/scan_summary.csv" >> "$LOG" 2>&1

  mark_done_in "$state" FIX_FROM_REVIEWS_1
  log "DONE $task fix-from-reviews round applied, FIX_FROM_REVIEWS_1 marked; launching round1 re-reviews"

  run_review_round "$task" glm "$lane_glm" "$pipe" 1 &
  local pid_glm=$!
  run_review_round "$task" sonnet "$lane_sonnet" "$pipe" 1 &
  local pid_sonnet=$!
  wait "$pid_glm" "$pid_sonnet"
  log "DONE $task round1 re-reviews both finished"

  # Change 3 (laptop, 2026-09-19 01:50Z): a single round0-vs-round1
  # disagreement (one reviewer majors, the other zero) is normal reviewer
  # noise and is left alone - the fix round + round1 re-review already
  # happened on the union of whatever either side found. But if the SAME
  # disagreement pattern is still there after the fix (majors-present at
  # round0 AND STILL majors-present-vs-zero at round1), that is not noise,
  # it is an unresolved reviewer split; break the tie with a third opinion
  # instead of shipping on whichever reviewer happened to run last.
  local g0 s0 g1 s1
  g0=$(reviewer_majors "$pipe/CR.glm.round0.json")
  s0=$(reviewer_majors "$pipe/CR.sonnet.round0.json")
  g1=$(reviewer_majors "$pipe/CR.glm.round1.json")
  s1=$(reviewer_majors "$pipe/CR.sonnet.round1.json")
  local disagree0=0 disagree1=0
  if [ "$g0" != "unknown" ] && [ "$s0" != "unknown" ] && [ "$g0" != "$s0" ]; then disagree0=1; fi
  if [ "$g1" != "unknown" ] && [ "$s1" != "unknown" ] && [ "$g1" != "$s1" ]; then disagree1=1; fi

  if [ "$disagree0" = "1" ] && [ "$disagree1" = "1" ]; then
    local adj_lane adj_out adj_rc adj_v adj_attempt
    adj_out="$pipe/CR.opus.adjudicate.json"
    log "ADJUDICATE $task: reviewers disagree on majors-present at round0 (glm=$g0 sonnet=$s0) AND round1 (glm=$g1 sonnet=$s1) - running a third opus review"
    for adj_attempt in 1 2; do
      if [ "$adj_attempt" = "1" ]; then adj_lane=$(adjudicate_lane_for "$task"); else adj_lane=$(alt_lane_for "$task" opus "$adj_attempt"); fi
      CLAUDE_CONFIG_DIR="$adj_lane" python3 "$TOOLS/run_workspace_review.py" --task "$task" --corpus-root "$CORPUS" \
        --workspace-root "$REVIEW_WS/opus" --runs-root "$RUNS_ROOT" --pipe-dir "$pipe" --reviewer opus --timeout 2400 \
        --out "$adj_out" --stats-out "$pipe/CR.opus.adjudicate.stats.json" > "$pipe/CR.opus.adjudicate.log" 2>&1
      adj_rc=$?
      canon_ok "$adj_out" && break
      log "RETRY-ADJUDICATE $task attempt=$adj_attempt lane=$(basename "$adj_lane") rc=$adj_rc (output missing or not canon-shaped, retrying once on a different lane - see run_review_round's comment)"
    done
    adj_v=$(python3 -c "import json; j=json.load(open('$adj_out')); print(j.get('overall_verdict'), 'maj', j.get('major_count'), 'min', j.get('minor_count'))" 2>/dev/null || echo "NO-JSON rc=$adj_rc")
    log "ADJUDICATED $task rc=$adj_rc $adj_v - this verdict governs"
    mark_done_in "$state" ADJUDICATED
  fi

  process_round2 "$task" "$pipe" "$state"
}

# ---------------------------------------------------------------------------
# Change 5 (laptop, 2026-09-19 02:55Z, finding 1): round2. Build the union
# of round1's majors (reviewer majors + any still-blocking gate cells);
# empty means round1's fix actually held, mark FIX_FROM_REVIEWS_2 and stop.
# Non-empty means at least one major survived the first fix - GATE-V2 rule 4
# / lanes/MAX_ROUNDS allow a second round, so run one more fix round from
# that union, with round1's own PLAN.fixreviews.json fed in as prior-round
# history (GAP 1 escalation), then re-review both as round2. If round2's
# union is STILL non-empty, append to PARKED.md naming every surviving
# major - a third round is a human decision.
#
# Standalone-callable, not just chained off process_task's own tail: a task
# marked FIX_FROM_REVIEWS_1 in an EARLIER dispatcher run (before this
# function existed) has both round1 files sitting on disk already and would
# never re-enter process_task (the main scan loop's very first eligibility
# check is `step_done_in ... FIX_FROM_REVIEWS_1 && continue`) - caught real
# on the laptop coordinator's finding 1: 8 tasks (10-5-0, 12-3-0, 13-7-0,
# 59-6-0, 75-5-0, 75-7-0, 9-1-0, 91-5-0) already had FIX_FROM_REVIEWS_1 +
# both round1 files present and were permanently unreachable until the main
# scan loop grew its own separate branch for exactly this case (see below).
# ---------------------------------------------------------------------------
process_round2() {
  local task="$1" pipe="$2" state="$3"

  if step_done_in "$state" FIX_FROM_REVIEWS_2; then
    return
  fi

  python3 "$TOOLS/build_review_union.py" --task "$task" \
    --glm "$pipe/CR.glm.round1.json" --sonnet "$pipe/CR.sonnet.round1.json" \
    --recheck-csv "$pipe/checks/recheck/summary.csv" \
    --oracle-json "$pipe/probes/oracle.json" \
    --out "$pipe/CR.union.round1.json" >> "$LOG" 2>&1

  local n_findings2
  n_findings2=$(python3 -c "import json; print(sum(1 for f in json.load(open('$pipe/CR.union.round1.json')).get('findings', []) if f.get('severity') == 'major'))" 2>/dev/null || echo 0)

  if [ "$n_findings2" = "0" ]; then
    mark_done_in "$state" FIX_FROM_REVIEWS_2
    log "SKIP-ROUND2 $task (union of round1 majors is empty, marked FIX_FROM_REVIEWS_2, round1's fix held)"
    return
  fi

  log "FIX-ROUND2 $task: $n_findings2 unioned major finding(s) remain after round1, running a second fix round"

  python3 "$TOOLS/gather_files_text.py" "$pipe/CR.union.round1.json" --task "$task" --corpus-root "$CORPUS" \
    --out "$pipe/FILES_TEXT_fixreviews2.txt" >> "$LOG" 2>&1

  {
    echo "--- PLAN.fixreviews.json (round1's fix, same fix-from-reviews track) ---"
    if [ -f "$pipe/PLAN.fixreviews.json" ]; then cat "$pipe/PLAN.fixreviews.json"; else echo "(round1 applied zero edits or its plan file is missing)"; fi
  } > "$pipe/PRIOR_PLANS_fixreviews2.txt"

  local lane_fix2
  lane_fix2=$(fix_lane_for "$task" round2)

  if ! python3 "$TOOLS/render_prompt.py" "$PROMPTS/fix_plan.md" \
      --set-lit TASK_ID="$task" --set CR_JSON="$pipe/CR.union.round1.json" \
      --set FILES_TEXT="$pipe/FILES_TEXT_fixreviews2.txt" \
      --set PRIOR_PLANS_TEXT="$pipe/PRIOR_PLANS_fixreviews2.txt" \
      --out "$pipe/PROMPT_fixreviews2.txt" >> "$LOG" 2>&1; then
    log "ERROR $task: render_prompt.py failed on fix_plan.md (fix-from-reviews round2), see $LOG - not marking done, will retry next scan"
    return
  fi

  if ! CLAUDE_CONFIG_DIR="$lane_fix2" python3 "$TOOLS/llm_call.py" --prompt-file "$pipe/PROMPT_fixreviews2.txt" \
      --model opus --timeout 1500 --out "$pipe/PLAN.fixreviews2.json" >> "$LOG" 2>&1; then
    log "ERROR $task: fix-plan call failed (fix-from-reviews round2, lane=$(basename "$lane_fix2")), see $LOG - not marking done, will retry next scan"
    return
  fi

  python3 "$TOOLS/apply_plan.py" --plan "$pipe/PLAN.fixreviews2.json" --task "$task" \
    --corpus-root "$CORPUS" --fix-log "$pipe/FIX-FROM-REVIEWS.md" >> "$LOG" 2>&1
  log "$task: apply_plan.py (fix-from-reviews round2) exit=$?"

  run_task_scans "$task" "$pipe"
  python3 "$TOOLS/merge_scan_verdicts.py" --reports-dir "$pipe/checks" --out "$pipe/checks/scan_summary.csv" >> "$LOG" 2>&1

  mark_done_in "$state" FIX_FROM_REVIEWS_2
  log "DONE $task fix-from-reviews ROUND2 applied, FIX_FROM_REVIEWS_2 marked; launching round2 re-reviews"

  local lane_glm2 lane_sonnet2
  lane_glm2=$(alt_lane_for "$task" glm round2glmpick)
  lane_sonnet2=$(alt_lane_for "$task" sonnet round2sonnetpick)

  run_review_round "$task" glm "$lane_glm2" "$pipe" 2 &
  local pid_glm2=$!
  run_review_round "$task" sonnet "$lane_sonnet2" "$pipe" 2 &
  local pid_sonnet2=$!
  wait "$pid_glm2" "$pid_sonnet2"
  log "DONE $task round2 re-reviews both finished"

  python3 "$TOOLS/build_review_union.py" --task "$task" \
    --glm "$pipe/CR.glm.round2.json" --sonnet "$pipe/CR.sonnet.round2.json" \
    --recheck-csv "$pipe/checks/recheck/summary.csv" \
    --oracle-json "$pipe/probes/oracle.json" \
    --out "$pipe/CR.union.round2.json" >> "$LOG" 2>&1

  local n_findings3
  n_findings3=$(python3 -c "import json; print(sum(1 for f in json.load(open('$pipe/CR.union.round2.json')).get('findings', []) if f.get('severity') == 'major'))" 2>/dev/null || echo 0)
  if [ "$n_findings3" != "0" ]; then
    local majors_summary
    majors_summary=$(python3 -c "
import json
d = json.load(open('$pipe/CR.union.round2.json'))
print('; '.join(f\"{f.get('class', '?')}: {f.get('description', '')[:150]}\" for f in d.get('findings', [])))
" 2>/dev/null)
    echo "$(date -u +%FT%TZ) PARKED: fix-from-reviews - $n_findings3 major finding(s) still present after round2 (MAX_ROUNDS reached): $majors_summary" \
      >> "$pipe/PARKED.md"
    log "PARKED $task: $n_findings3 major finding(s) survive round2, see $pipe/PARKED.md and $pipe/CR.union.round2.json"
  else
    log "CLEAN $task: round2 union is empty, ships clean after two fix rounds"
  fi
}

# Entry point for the main scan loop's own round2 branch (a task whose
# FIX_FROM_REVIEWS_1 was marked in an earlier dispatcher run, never reaching
# process_task's own tail call to process_round2 in THIS run). Acquires the
# same per-task flock process_task uses, so a task cannot be round2'd twice
# concurrently and cannot race a process_task call still in flight for it.
process_round2_entry() {
  local task="$1"
  local pipe="$PIPE_ROOT/$task"
  local state="$pipe/STATE"
  local lockfile="$pipe/fix_from_reviews.lock"
  exec 8>"$lockfile"
  if ! flock -n 8; then
    log "SKIP $task (another fix_from_reviews.sh job already holds the lock, round2 entry)"
    return
  fi
  process_round2 "$task" "$pipe" "$state"
}

log "FIX-FROM-REVIEWS START pid=$$ conc=$CONC interval=${SCAN_INTERVAL}s"

lane_idx=0
# Sets $NEXT_LANE (does not echo/return via command substitution): every
# call site up to 2026-09-19 02:05Z used lane=$(next_lane), and $(...)
# always forks a subshell in bash - lane_idx's increment never propagated
# back to the parent, so every call silently returned pool index 0 forever
# (POOL[0]=/root/.claude the whole run; after change 2, FIX_LANE_POOL[0]=
# -q). Caught real: every fix round and every round1 review in the first
# two runs used only the first lane in its pool, no rotation at all.
next_lane() {
  NEXT_LANE="${POOL[$(( lane_idx % ${#POOL[@]} ))]}"
  lane_idx=$((lane_idx + 1))
}

fix_lane_idx=0
next_fix_lane() {
  NEXT_LANE="${FIX_LANE_POOL[$(( fix_lane_idx % ${#FIX_LANE_POOL[@]} ))]}"
  fix_lane_idx=$((fix_lane_idx + 1))
}

# One task's eligibility check + dispatch, factored out of the scan loop so
# the SAME logic can run from the priority pass (below) and the normal
# alphabetical sweep without duplicating it.
scan_one_task() {
  local pipe="$1"
  local task="$(basename "$pipe")"
  local state="$pipe/STATE"
  local glm_json="$pipe/CR.glm.round0.json"
  local sonnet_json="$pipe/CR.sonnet.round0.json"
  local glm_ready sonnet_ready lane lane_fix lane_glm lane_sonnet

  # Change 5: a task whose FIX_FROM_REVIEWS_1 was already marked (this run
  # or an earlier one) never re-enters the round0 flow below - route it to
  # round2 instead, once and only once (FIX_FROM_REVIEWS_2 gates it) and
  # only when both round1 files are already sitting there canon-shaped
  # (round1 is launched from inside process_task itself, this loop never
  # launches it directly).
  if step_done_in "$state" FIX_FROM_REVIEWS_1; then
    if step_done_in "$state" FIX_FROM_REVIEWS_2; then return; fi
    if canon_ok "$pipe/CR.glm.round1.json" && canon_ok "$pipe/CR.sonnet.round1.json"; then
      admit_wait
      process_round2_entry "$task" &
      sleep 1
    fi
    return
  fi

  # Change 1: a file that EXISTS but fails canon_ok is quarantined and its
  # reviewer re-run; a task is only eligible for a fix round once BOTH
  # files exist and are canon_ok (possibly on a later scan pass).
  glm_ready=0
  if [ -f "$glm_json" ]; then
    if canon_ok "$glm_json"; then
      glm_ready=1
    else
      admit_wait
      next_lane; lane="$NEXT_LANE"
      requeue_reviewer "$task" glm "$lane" "$pipe" &
      sleep 1
    fi
  fi
  sonnet_ready=0
  if [ -f "$sonnet_json" ]; then
    if canon_ok "$sonnet_json"; then
      sonnet_ready=1
    else
      admit_wait
      next_lane; lane="$NEXT_LANE"
      requeue_reviewer "$task" sonnet "$lane" "$pipe" &
      sleep 1
    fi
  fi
  [ "$glm_ready" = "1" ] || return
  [ "$sonnet_ready" = "1" ] || return

  admit_wait
  next_fix_lane; lane_fix="$NEXT_LANE"
  next_lane; lane_glm="$NEXT_LANE"
  next_lane; lane_sonnet="$NEXT_LANE"
  process_task "$task" "$lane_fix" "$lane_glm" "$lane_sonnet" &
  sleep 1
}

# Laptop coordinator, 2026-09-19 03:59Z (finding 2): guard_rt.py re-opens an
# rc=5-blocked task (clears FIX_FROM_REVIEWS_* from STATE, copies the fresh
# _recheck/<T> in) up to twice per task, and a full alphabetical sweep takes
# ~40 minutes - a task re-opened right after this scan pass started sits for
# most of that before its turn comes up. PRIORITY_FILE (one task name per
# line, blank lines and #-comments ignored) is scanned FIRST every pass, so
# guard_rt.py (or anyone) can drop re-opened task names in there and have
# them picked up within the next ~60s instead of waiting on scan order. An
# already-eligible or already-done task listed here is a harmless no-op
# (scan_one_task's own checks handle it), so the file never needs pruning by
# hand - stale entries just cost one cheap STATE check per pass.
PRIORITY_FILE="${FIX_FROM_REVIEWS_PRIORITY_FILE:-/root/qc/lanes/FIX_FROM_REVIEWS_PRIORITY}"

# Laptop coordinator, 2026-09-19 05:14Z: a round2-eligible task (round1 done,
# majors still present) is ONE round from finished, but the alphabetical
# sweep treats it the same as a brand-new round0 task, so it can sit behind
# earlier-lettered round0 entries for most of a ~90min pass even though
# finishing it is cheaper than starting a fresh one. Automatic (no file to
# curate, unlike PRIORITY_FILE): scan for round2-eligible tasks -
# FIX_FROM_REVIEWS_1 marked, FIX_FROM_REVIEWS_2 not, both round1 files
# canon-shaped - and run those FIRST every pass, before the general
# alphabetical sweep. scan_one_task's own checks make this a harmless no-op
# for anything not actually round2-eligible, so this pre-pass is pure
# reordering, not new work.
round2_first_pass() {
  local pipe task state
  for pipe in "$PIPE_ROOT"/SVC-PC-*/; do
    [ -d "$pipe" ] || continue
    task="$(basename "$pipe")"
    state="$pipe/STATE"
    step_done_in "$state" FIX_FROM_REVIEWS_1 || continue
    step_done_in "$state" FIX_FROM_REVIEWS_2 && continue
    canon_ok "$pipe/CR.glm.round1.json" && canon_ok "$pipe/CR.sonnet.round1.json" || continue
    admit_wait
    process_round2_entry "$task" &
    sleep 1
  done
}

while true; do
  round2_first_pass
  if [ -f "$PRIORITY_FILE" ]; then
    while IFS= read -r ptask; do
      ptask="${ptask%%#*}"
      ptask="$(echo "$ptask" | tr -d '[:space:]')"
      [ -n "$ptask" ] || continue
      [ -d "$PIPE_ROOT/$ptask" ] && scan_one_task "$PIPE_ROOT/$ptask/"
    done < "$PRIORITY_FILE"
  fi
  for pipe in "$PIPE_ROOT"/SVC-PC-*/; do
    [ -d "$pipe" ] || continue
    scan_one_task "$pipe"
  done
  sleep "$SCAN_INTERVAL"
done
