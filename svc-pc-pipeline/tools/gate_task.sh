#!/usr/bin/env bash
# gate_task.sh - HANDOFF.md section 3: the scripted GATE-V2 pipeline, model
# calls at exactly three points (step 3 blind CR, step 4 fix plan, step 5
# both-runs-failed adjudication), everything else script. Safe to run several
# copies concurrently (pipe_batch.sh does, at concurrency 6): every mutable
# path this script touches outside the corpus is keyed by $TASK, and the
# corpus edits (apply_plan.py, apply_k_sentence.py, rewardkit_pin.py
# --apply-task, muststrip_scan.py --apply-task) only ever touch
# <corpus-root>/<task>/, never another task's directory.
#
# Usage: gate_task.sh <TASK>
#   TASK  e.g. SVC-PC-22-5-0
#
# Resumable: every step's completion is recorded in <pipe-dir>/STATE (one
# step name per line). Re-running this script on a task that already has a
# STATE file skips whatever is already marked done and continues from there
# - a killed/restarted batch does not redo finished work or re-spend model
# calls.
set -uo pipefail

CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
TOOLS=/root/qc/tools
PROMPTS="$TOOLS/prompts"
PIPE_ROOT=/root/qc/stream-pipe
OUT_DIR=/root/qc/out/pipe
CLAIMS=/root/qc/claims
RUNS_ROOT=/root/qc/runs
# GATE-V2 (laptop, 2026-09-18 23:20Z): workspace-mode review staging root - a
# dedicated tree, NOT /root/qc/stage (the actuator's own staging dir, which
# stage_and_zip.sh unconditionally `rm -rf`s and rebuilds on every call; using
# it here would race with the actuator staging the same task for the zip).
REVIEW_WORKSPACE_ROOT=/root/qc/review_workspace

if [ "$#" -ne 1 ]; then
  echo "Usage: $(basename "$0") <TASK>" >&2
  exit 2
fi
TASK="$1"
case "$TASK" in
  SVC-PC-*) ;;
  *) echo "ERROR: TASK must start with SVC-PC- (got: $TASK)" >&2; exit 2 ;;
esac

if [ ! -d "$CORPUS/$TASK" ]; then
  echo "ERROR: task directory not found: $CORPUS/$TASK" >&2
  exit 2
fi

PIPE="$PIPE_ROOT/$TASK"
mkdir -p "$PIPE" "$PIPE/checks" "$PIPE/probes"
STATE_FILE="$PIPE/STATE"
LOG="$PIPE/pipeline.log"
touch "$STATE_FILE" "$LOG"

# Per-task mutex: any launcher (this script is safe to invoke from more than
# one queue driver at once, and on 2026-09-18 two independent ones both
# picked up the same task within seconds of PARKED.md being removed) must
# not run two instances of this script on the same task concurrently - both
# instances would read/edit the same corpus files (including the same
# apply_plan.py .tmp_apply path for a binary op), racing on writes. A second
# instance backs off immediately rather than duplicating or corrupting work;
# the lock is released automatically when this process exits, whatever the
# exit path.
LOCK_FILE="$PIPE/gate_task.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[$(date -u +%FT%TZ)] $TASK: another gate_task.sh instance holds the lock ($LOCK_FILE), backing off" \
    | tee -a "$LOG" >&2
  exit 1
fi

if grep -qx DONE "$STATE_FILE" 2>/dev/null; then
  echo "[$(date -u +%FT%TZ)] $TASK: already DONE (see $STATE_FILE), nothing to do" | tee -a "$LOG" >&2
  exit 0
fi
if [ -f "$PIPE/PARKED.md" ]; then
  echo "[$(date -u +%FT%TZ)] $TASK: already PARKED (see $PIPE/PARKED.md), not re-spending model calls; a human must resolve and rm PARKED.md to retry" \
    | tee -a "$LOG" >&2
  exit 1
fi

# shellcheck disable=SC1091
source /root/venv/bin/activate 2>/dev/null || true

log() { echo "[$(date -u +%FT%TZ)] $TASK: $*" | tee -a "$LOG" >&2; }
step_done() { grep -qx "$1" "$STATE_FILE" 2>/dev/null; }
mark_done() { echo "$1" >> "$STATE_FILE"; }
park() {
  echo "$(date -u +%FT%TZ) PARKED: $*" >> "$PIPE/PARKED.md"
  log "PARKED: $*"
  exit 1
}

# ---------------------------------------------------------------------------
# Step 1: claim + snapshot
# ---------------------------------------------------------------------------
if step_done CLAIM; then
  log "step 1 (claim): already done, skipping"
else
  log "step 1: claiming and snapshotting"
  echo "pipe $(date -u +%FT%TZ)" > "$CLAIMS/$TASK"
  rm -rf "$PIPE/_before"
  rsync -a "$CORPUS/$TASK/" "$PIPE/_before/"
  mark_done CLAIM
fi

# ---------------------------------------------------------------------------
# Step 2: mechanical
# ---------------------------------------------------------------------------
run_task_scans() {
  # 11 scans that support --task, into $PIPE/checks/. Safe to call more than
  # once (rescanned after a fix round); each call overwrites its own files.
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
      extra=(--exposed-out "$PIPE/checks/formula_cache_exposed.csv")
    fi
    python3 "$TOOLS/$s" --task "$TASK" --corpus-root "$CORPUS" \
      --out "$PIPE/checks/$stem.csv" \
      --verdict-out "$PIPE/checks/$stem.verdict.csv" \
      "${extra[@]}" >> "$LOG" 2>&1
    if [ $? -ne 0 ]; then
      log "WARNING: $s exited non-zero, see $LOG"
    fi
  done

  # 2 scans with no --task: run corpus-wide to scratch, filter to our row.
  for s in env_size_report.py metadata_fill.py; do
    local stem="${s%.py}"
    local scratch_csv="$PIPE/checks/_scratch_${stem}.csv"
    local scratch_verdict="$PIPE/checks/_scratch_${stem}.verdict.csv"
    python3 "$TOOLS/$s" --corpus-root "$CORPUS" \
      --out "$scratch_csv" --verdict-out "$scratch_verdict" >> "$LOG" 2>&1
    if [ -f "$scratch_verdict" ]; then
      awk -F, -v t="$TASK" 'NR==1 || $1==t' "$scratch_verdict" > "$PIPE/checks/$stem.verdict.csv"
    fi
  done
}

if step_done MECHANICAL; then
  log "step 2 (mechanical): already done, skipping"
else
  log "step 2: mechanical fixes + scans"

  # K sentence, only if this task has an xlsx deliverable (formula_cache_scan
  # --exposed-out tells us, run first so the exposed-set CSV exists).
  python3 "$TOOLS/formula_cache_scan.py" --task "$TASK" --corpus-root "$CORPUS" \
    --out "$PIPE/checks/formula_cache.csv" \
    --verdict-out "$PIPE/checks/formula_cache.verdict.csv" \
    --exposed-out "$PIPE/checks/formula_cache_exposed.csv" >> "$LOG" 2>&1
  if [ -f "$PIPE/checks/formula_cache_exposed.csv" ] && grep -q "^$TASK," "$PIPE/checks/formula_cache_exposed.csv" 2>/dev/null; then
    python3 "$TOOLS/apply_k_sentence.py" "$TASK" --corpus-root "$CORPUS" | tee "$PIPE/checks/k_sentence_applied.txt" >> "$LOG"
  else
    echo "N/A: no xlsx deliverable for $TASK" | tee "$PIPE/checks/k_sentence_applied.txt" >> "$LOG"
  fi

  # rewardkit pin, per-task owner apply (GATE-V2 3.6.3 / rewardkit_pin.py --apply)
  python3 "$TOOLS/rewardkit_pin.py" --apply "$TASK" --confirm-apply --corpus-root "$CORPUS" \
    > "$PIPE/checks/rewardkit_pin_apply.log" 2>&1
  log "rewardkit_pin --apply exit=$?"

  # must-pass strip, per-task owner apply
  python3 "$TOOLS/muststrip_scan.py" --apply-task "$TASK" --confirm-apply --corpus-root "$CORPUS" \
    > "$PIPE/checks/muststrip_apply.log" 2>&1
  log "muststrip_scan --apply-task exit=$?"

  # GATE-V2 (laptop, 2026-09-18 23:20Z), item 3, solver-deliverable half:
  # mechanical, no model call - see render_guard_apply.py's own docstring.
  python3 "$TOOLS/render_guard_apply.py" --apply-task "$TASK" --confirm-apply --corpus-root "$CORPUS" \
    > "$PIPE/checks/render_guard_apply.log" 2>&1
  log "render_guard_apply --apply-task exit=$?"

  # item 3, SOURCE half: needs per-task column judgment, so one fix_plan.md
  # call (not mechanical) - but only when the scan actually finds something,
  # and only once (OVERSIZE_SOURCE_FIX checkpoint) - re-running gate_task.sh
  # on a task that already passed this does not re-spend the call.
  if step_done OVERSIZE_SOURCE_FIX; then
    log "step 2: oversize-source fix: already done, skipping"
  else
    python3 "$TOOLS/oversize_source_scan.py" --task "$TASK" --corpus-root "$CORPUS" \
      --out "$PIPE/checks/oversize_findings.json" >> "$LOG" 2>&1
    if [ "$(python3 -c "import json; print('1' if json.load(open('$PIPE/checks/oversize_findings.json')).get('findings') else '0')" 2>/dev/null || echo 0)" = "1" ]; then
      log "step 2: oversize-source fix (files= source(s) over 1 MiB found)"
      if ! python3 "$TOOLS/gather_files_text.py" "$PIPE/checks/oversize_findings.json" --task "$TASK" \
          --corpus-root "$CORPUS" --out "$PIPE/checks/oversize_files_text.txt" >> "$LOG" 2>&1; then
        park "gather_files_text.py failed (oversize-source fix), see $LOG"
      fi
      echo "(N/A: oversize-source fix round, not a CR round - no prior-round edit history applies)" \
        > "$PIPE/checks/oversize_prior_plans.txt"
      if ! python3 "$TOOLS/render_prompt.py" "$PROMPTS/fix_plan.md" \
          --set-lit TASK_ID="$TASK" --set CR_JSON="$PIPE/checks/oversize_findings.json" \
          --set FILES_TEXT="$PIPE/checks/oversize_files_text.txt" \
          --set PRIOR_PLANS_TEXT="$PIPE/checks/oversize_prior_plans.txt" \
          --out "$PIPE/checks/oversize_prompt.txt" >> "$LOG" 2>&1; then
        park "render_prompt.py failed on fix_plan.md (oversize-source fix), see $LOG"
      fi
      if ! python3 "$TOOLS/llm_call.py" --prompt-file "$PIPE/checks/oversize_prompt.txt" \
          --model opus --timeout 1500 --out "$PIPE/checks/oversize_plan.json" >> "$LOG" 2>&1; then
        lane_refused && refused_exit "oversize-source fix plan"
        park "oversize-source fix-plan call failed, see $LOG"
      fi
      python3 "$TOOLS/apply_plan.py" --plan "$PIPE/checks/oversize_plan.json" --task "$TASK" \
        --corpus-root "$CORPUS" --fix-log "$PIPE/FIX-LOG.md" >> "$LOG" 2>&1
      log "apply_plan.py oversize-source fix exit=$?"
    else
      log "step 2: oversize-source fix: nothing found, skipping"
    fi
    mark_done OVERSIZE_SOURCE_FIX
  fi

  run_task_scans
  python3 "$TOOLS/merge_scan_verdicts.py" --reports-dir "$PIPE/checks" --out "$PIPE/checks/scan_summary.csv" >> "$LOG" 2>&1

  mark_done MECHANICAL
fi

# ---------------------------------------------------------------------------
# Step 3 + 4: blind CR, then up to MAX_ROUNDS fix rounds (model calls).
# 16:55Z (laptop): every model output is checkpointed to its own file and a
# STATE marker, so a re-run after a kill re-spends nothing; MAX_ROUNDS is read
# from /root/qc/lanes/MAX_ROUNDS (default 4); a REFUSED model call (usage limit,
# rate limit) is a lane problem, not a task verdict: exit 4 without parking so
# the launcher benches the lane and retries the task.
# ---------------------------------------------------------------------------
MAX_ROUNDS=$(tr -dc 0-9 < /root/qc/lanes/MAX_ROUNDS 2>/dev/null); [ -n "$MAX_ROUNDS" ] || MAX_ROUNDS=4
LIMIT_RE='usage limit|session limit|weekly limit|hit your [a-z ]*limit|rate.?limit|too many requests|resets [0-9]|resets [A-Z][a-z]{2} [0-9]|overloaded'

json_ok() { python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$1" 2>/dev/null; }
lane_refused() { tail -40 "$LOG" | grep -qiE "$LIMIT_RE"; }
refused_exit() {
  log "LANE REFUSED: $1 (usage/rate limit on this account), not parking; exit 4 so the launcher benches the lane and retries"
  exit 4
}

run_blind_cr() {
  # $1 = output CR.json path, $2 = round label - used for EVERY round, not just
  # round 0 (redirect build, 2026-09-18, GAP 2 of fix-task-from-review.SKILL.md:
  # a gate that only re-examines what the round touched is not comprehensive -
  # two real majors sat untouched through several diff-scoped passes on a real
  # task. The pre-redirect narrower recheck_cr.md was removed for exactly this
  # reason.
  #
  # GATE-V2 (laptop, 2026-09-18 23:20Z): workspace-mode review, not a
  # single-shot llm_call.py completion any more. DataOS batch 4 rejected two
  # tasks (SVC-PC-67-1-0 reject/2 majors, SVC-PC-8-2-0 INVALID/6 majors) that
  # this exact prompt, single-shot over a 60K-token truncated CONTEXT.txt, had
  # passed with zero majors - the misses (a rewardkit-silent 1 MiB file skip,
  # a leaked near-final answer doc among 119 environment files, a source-name
  # mismatch, an unsourced rubric value, files= paying reward with no
  # deliverable) are all things a truncated text blob cannot show but a real
  # agent with Read/Glob/Grep/Bash over the actual staged files can find
  # directly. run_workspace_review.py stages task_files/+evaluations/+
  # prior_verifications/ and runs `claude -p` as a real tool-using agent over
  # them - see that script's own docstring for the full design and the
  # `--permission-mode dontAsk` (not bypassPermissions - refused for root)
  # substitution. External interface unchanged: still writes $out (CR.json
  # shape) and $out.raw.txt, still returns nonzero on failure, so every
  # existing caller (`if ! run_blind_cr ...; then park; fi`) needs no changes.
  local out="$1" label="$2"
  python3 "$TOOLS/run_workspace_review.py" --task "$TASK" --corpus-root "$CORPUS" \
    --workspace-root "$REVIEW_WORKSPACE_ROOT" --runs-root "$RUNS_ROOT" --pipe-dir "$PIPE" \
    --out "$out" --stats-out "$PIPE/CR_STATS_${label}.json" \
    --model opus --timeout 2400 >> "$LOG" 2>&1
}

# build_recheck_static_text / run_recheck_cr removed in the redirect build
# (2026-09-18): every CR round now calls run_blind_cr (a full review) instead
# of a narrower diff-scoped recheck; see run_blind_cr's comment above and
# tools/prompts/recheck_cr.md.unused-since-redirect (kept only as a reference
# copy, no longer read by this script).

majors_of() {
  # Redirect build (2026-09-18), correction from Khiem: the ship bar is
  # major_count == 0 straight from the canon prompt's own §4/§5 (accept, OR
  # needs_revision carrying only minors) - NOT overall_verdict == "accept"
  # alone. Minors are written into GATE.md and the task ships; a fix round is
  # never spent on minors by themselves (canon §1a: "a passed package is not
  # edited"). Falls back to the old majors_present boolean if a CR.json was
  # somehow produced by the pre-redirect schema, then to "1" (treat unparsable
  # as majors-present so the task parks rather than ships blind).
  python3 -c "
import json
d = json.load(open('$1'))
checks = d.get('checks')
if 'major_count' in d and isinstance(checks, list) and len(checks) >= 1:
    print('1' if int(d.get('major_count') or 0) > 0 else '0')
elif 'majors_present' in d:
    print('1' if d.get('majors_present') else '0')
else:
    # Neither schema's shape is present - e.g. llm_call.py's JSON extractor
    # grabbed a fragment (confirmed real failure mode on the SVC-PC-54-2-0
    # redirect test, before extract_json_object was fixed to require the
    # candidate close the text exactly: it returned a single nested check
    # object with none of major_count/majors_present/checks[], and this
    # branch's old unconditional 'd.get(\"majors_present\")' silently read
    # that as False and shipped the task with no real review at all).
    # Treat an unrecognized shape as majors-present so the task parks for a
    # human instead of shipping blind.
    print('1')
" 2>/dev/null || echo "1"
}

# GATE-V2 (laptop, 2026-09-18 21:32Z): SVC-PC-73-2-0 and SVC-PC-76-2-0 zipped
# with a CR.json that has no overall_verdict - their CR_AND_FIX marker was set
# by the pre-redirect blind_cr.md, before the canon-prompt swap, and this
# script trusted the checkpoint alone. Seeded pre-canon checkpoints exist on
# most tasks, so this is the common path right now, not an edge case.
cr_is_canon() {
  # "true" (exit 0) only if $PIPE/CR.json parses AND carries overall_verdict
  # (the canon ekw-svc-comprehensive-review.md §5 schema). A pre-redirect
  # CR.json (verdict/majors_present, no overall_verdict) or a missing/corrupt
  # file both count as "not canon" here.
  python3 -c "
import json
d = json.load(open('$PIPE/CR.json'))
raise SystemExit(0 if 'overall_verdict' in d else 1)
" 2>/dev/null
}

discard_stale_pre_canon_state() {
  # Archives (never deletes) every CR/FIX/CHECKFIX/PROBES artifact and clears
  # their STATE markers, so the existing round-loop and check-fix/probes steps
  # below re-run from scratch exactly as if this task had never been reviewed.
  # CHECKFIX and PROBES are invalidated too, not just CR/FIX: a fresh canon
  # review can find majors and edit the corpus, which would make an
  # already-recorded checkfix/oracle result (computed against the pre-edit
  # corpus) stale as well.
  mkdir -p "$PIPE/_stale-pre-canon"
  mv "$PIPE"/CR*.json "$PIPE"/CR*.json.raw.txt "$PIPE"/PLAN.round*.json* "$PIPE"/FIX-LOG*.* \
    "$PIPE"/prompt_cr_*.txt "$PIPE"/prompt_fix_*.txt "$PIPE"/FILES_TEXT_round*.txt \
    "$PIPE"/PRIOR_PLANS_round*.txt "$PIPE/_stale-pre-canon/" 2>/dev/null
  grep -vE '^(CR_AND_FIX|CR_ROUND_[0-9]+|FIX_ROUND_[0-9]+|CHECKFIX|CHECKFIX_ROUND_[0-9]+|PROBES|ORACLE_FIX_ROUND_[0-9]+|ORACLE_FIX_CR_[0-9]+|ORACLE_RECHECK_[0-9]+)$' \
    "$STATE_FILE" > "$STATE_FILE.tmp" 2>/dev/null
  mv "$STATE_FILE.tmp" "$STATE_FILE" 2>/dev/null || true
}

if step_done CR_AND_FIX && ! cr_is_canon; then
  log "step 3: CR_AND_FIX marker predates the canon prompt (CR.json has no overall_verdict) - discarding stale CR/FIX/CHECKFIX/PROBES checkpoints and re-running from a fresh canon review"
  discard_stale_pre_canon_state
fi

if step_done CR_AND_FIX; then
  log "steps 3-4 (CR + fix): already done under the canon schema, skipping"
else
  # round 0 blind CR, checkpointed as CR.round0.json + CR_ROUND_0
  if step_done CR_ROUND_0 && json_ok "$PIPE/CR.round0.json"; then
    log "step 3: blind CR (round 0): checkpoint present, reusing CR.round0.json"
    cp "$PIPE/CR.round0.json" "$PIPE/CR.json"
  else
    log "step 3: blind CR (round 0)"
    if ! run_blind_cr "$PIPE/CR.json" "round0"; then
      lane_refused && refused_exit "blind CR round 0"
      park "blind CR call failed (round 0), see $LOG and $PIPE/CR.json.raw.txt"
    fi
    cp "$PIPE/CR.json" "$PIPE/CR.round0.json"; mark_done CR_ROUND_0
  fi
  majors_present=$(majors_of "$PIPE/CR.json")

  round=1
  while [ "$majors_present" = "1" ] && [ "$round" -le "$MAX_ROUNDS" ]; do
    # fix plan for this round, checkpointed as PLAN.roundN.json + FIX_ROUND_N
    if step_done "FIX_ROUND_$round" && json_ok "$PIPE/PLAN.round${round}.json"; then
      log "step 4: fix round $round: checkpoint present, plan already applied"
    else
      log "step 4: fix round $round (majors present, max $MAX_ROUNDS)"
      cp "$PIPE/CR.json" "$PIPE/CR.round${round}.before-fix.json"
      python3 "$TOOLS/gather_files_text.py" "$PIPE/CR.json" --task "$TASK" --corpus-root "$CORPUS" \
        --out "$PIPE/FILES_TEXT_round${round}.txt" >> "$LOG" 2>&1
      # GAP 1 (fix-task-from-review.SKILL.md, redirect build 2026-09-18): the
      # fix-plan call must see every prior round's own plan to detect "this
      # criterion has already been wording-tweaked 2+ times" before proposing
      # another wording tweak. Concatenate every earlier round's PLAN.jsonN;
      # round 1 has none.
      {
        found_prior=0
        for r in $(seq 1 $((round - 1))); do
          [ -f "$PIPE/PLAN.round${r}.json" ] || continue
          found_prior=1
          echo "--- PLAN.round${r}.json ---"
          cat "$PIPE/PLAN.round${r}.json"
          echo
        done
        [ "$found_prior" = "1" ] || echo "(round $round: no prior fix-plan rounds exist yet)"
      } > "$PIPE/PRIOR_PLANS_round${round}.txt"
      # Same class of bug fixed here as in the check-fix loop (laptop session,
      # 2026-09-18 19:50Z): render_prompt.py's exit code must be checked, or a
      # crash silently falls through to llm_call.py failing on the unwritten
      # prompt file with a misleading FileNotFoundError.
      if ! python3 "$TOOLS/render_prompt.py" "$PROMPTS/fix_plan.md" \
          --set-lit TASK_ID="$TASK" --set CR_JSON="$PIPE/CR.json" --set FILES_TEXT="$PIPE/FILES_TEXT_round${round}.txt" \
          --set PRIOR_PLANS_TEXT="$PIPE/PRIOR_PLANS_round${round}.txt" \
          --out "$PIPE/prompt_fix_round${round}.txt" >> "$LOG" 2>&1; then
        park "render_prompt.py failed on fix_plan.md (round $round), see $LOG"
      fi
      if ! python3 "$TOOLS/llm_call.py" --prompt-file "$PIPE/prompt_fix_round${round}.txt" \
          --model opus --timeout 1500 --out "$PIPE/PLAN.round${round}.json" >> "$LOG" 2>&1; then
        lane_refused && refused_exit "fix plan round $round"
        park "fix-plan call failed (round $round), see $LOG"
      fi
      fixlog_before=$(wc -l < "$PIPE/FIX-LOG.md" 2>/dev/null || echo 0)
      python3 "$TOOLS/apply_plan.py" --plan "$PIPE/PLAN.round${round}.json" --task "$TASK" \
        --corpus-root "$CORPUS" --fix-log "$PIPE/FIX-LOG.md" >> "$LOG" 2>&1
      log "apply_plan.py round $round exit=$?"
      tail -n +"$((fixlog_before + 1))" "$PIPE/FIX-LOG.md" > "$PIPE/FIX-LOG_round${round}.txt" 2>/dev/null
      [ -s "$PIPE/FIX-LOG_round${round}.txt" ] || echo "(no new FIX-LOG lines recorded for round $round)" > "$PIPE/FIX-LOG_round${round}.txt"
      run_task_scans
      python3 "$TOOLS/merge_scan_verdicts.py" --reports-dir "$PIPE/checks" --out "$PIPE/checks/scan_summary.csv" >> "$LOG" 2>&1
      mark_done "FIX_ROUND_$round"
    fi

    # re-check after the fix, checkpointed as CR.roundN.json + CR_ROUND_N. Every
    # round is a FULL blind CR re-read via run_blind_cr (GAP 2, see its comment
    # above) - not a diff-scoped recheck of only what this round touched.
    if step_done "CR_ROUND_$round" && json_ok "$PIPE/CR.round${round}.json"; then
      log "step 3: blind CR (round $round): checkpoint present, reusing CR.round${round}.json"
      cp "$PIPE/CR.round${round}.json" "$PIPE/CR.json"
    else
      log "step 3: blind CR (round $round, full re-audit after fix)"
      if ! run_blind_cr "$PIPE/CR.json" "round${round}"; then
        lane_refused && refused_exit "blind CR round $round"
        park "blind CR call failed (round $round), see $LOG"
      fi
      cp "$PIPE/CR.json" "$PIPE/CR.round${round}.json"; mark_done "CR_ROUND_$round"
    fi
    majors_present=$(majors_of "$PIPE/CR.json")
    round=$((round + 1))
  done

  if [ "$majors_present" = "1" ]; then
    park "majors still present after $MAX_ROUNDS fix rounds, parked for a human with CR.json"
  fi

  mark_done CR_AND_FIX
fi

# ---------------------------------------------------------------------------
# Step 4.5: check-fix against the SAME 45-check checker the actuator runs
# (GATE-V2 3.4/3.6, stage_and_zip.sh lines 15/25-31). The blind CR (steps
# 3-4 above) never sees these cells, so a task can clear CR_AND_FIX and still
# be blocked at step 6's actuator - see SVC-PC-76-2-0, which reached
# stage_and_zip.sh rc=5 on gate-relevant warn/fail cells the CR never
# reviewed (zip.log, _recheck/SVC-PC-76-2-0/summary.csv). This step runs that
# checker early, accepts only the two cells a GATE-V2 3.6 ruling already
# covers (task_metadata_completeness 3.6.2 "do not add", environment_size_budget
# 3.6.1, advisory), and spends up to CHECKFIX_MAX_ROUNDS fix-plan model calls
# (same prompt/applier as step 4) on everything else the checker flags.
# GATE.md's "Accepted cells" section (step 6) is written from the ruling
# table below, kept static so it never drifts from what --accept-skip passes
# to the actuator.
#
# GATE/ADVISORY/ZSCAN_PREFIXES below are copied VERBATIM from
# stage_and_zip.sh (owned by the laptop session, not edited here) so the
# actuator's gate and this pre-check never diverge on what counts as
# gate-relevant. If stage_and_zip.sh's sets change, this copy must be
# updated by hand.
# ---------------------------------------------------------------------------
CHECKFIX_MAX_ROUNDS=2
CHECKFIX_STAGE="$PIPE/checks/_stage_checkfix"
CHECKFIX_OUT="$PIPE/checks/recheck"
CHECKER45=/root/ekwqc/deterministic-checks/svc_run_checks.py

checkfix_stage_and_run() {
  # Stage exactly as the actuator stages (stage_and_zip.sh lines 17-21,
  # copied verbatim), then run the same checker into $CHECKFIX_OUT
  # (analogous to the actuator's $CKOUT).
  rm -rf "$CHECKFIX_STAGE"; mkdir -p "$CHECKFIX_STAGE"
  rsync -a --exclude='_prior' --exclude='_runs' --exclude='FIX-LOG*.md' --exclude='REFUTER*.md' \
    --exclude='CR-REFUTER.md' --exclude='_scratch' --exclude='COMPREHENSIVE-REVIEW.md' --exclude='GATE.md' \
    --exclude='*.round1' --exclude='*.round2' --exclude='*.bak' --exclude='*.bak-*' --exclude='__pycache__' \
    --exclude='_golden_*' --exclude='_conv_test*' --exclude='__img_embed_test__*' --exclude='capacity_tmp_conv.*' \
    --exclude='.DS_Store' "$CORPUS/$TASK/" "$CHECKFIX_STAGE/$TASK/" >> "$LOG" 2>&1
  rm -rf "$CHECKFIX_OUT"
  ( python3 "$CHECKER45" --root "$CHECKFIX_STAGE" --out-dir "$CHECKFIX_OUT" --all --jobs 8 "$TASK" >> "$LOG" 2>&1 ) || true
  [ -f "$CHECKFIX_OUT/summary.csv" ]
}

checkfix_classify() {
  # $1 = out json path (accepted[] / blocked[] / nonpass[])
  python3 - "$CHECKFIX_OUT/summary.csv" "$TASK" "$1" "$CORPUS" <<'PYEOF'
import csv, glob, json, os, sys
f, t, outp, corpus_root = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
# Verbatim from stage_and_zip.sh's own python block (14:12-14:45Z rules) - do not edit
# independently of that script.
GATE={"criterion_groundedness","compound_criterion","duplicate_criterion_content","same_file_requirement_duplicate",
"weight_application","environment_size_budget","task_metadata_completeness","dependency_pin",
"instruction_requirement_coverage","fabricated_unfilenamed_fact","golden_groundedness","golden_arithmetic",
"source_citation_existence","cell_address_pinned","rubric_overspecification","environment_input","metadata_leak",
"answer_key_rubric_leak","spelling_grammar"}
ZSCAN_PREFIXES=("formula_cache","quantifier_scope","escape_hatch","source_reliability","rubric_consistency","answer_preexposure","instruction_input","cross_group_dup")
ADVISORY={"pinned_value_prescreen","environment_size_budget","criterion_groundedness","compound_criterion","duplicate_criterion_content","same_file_requirement_duplicate","instruction_requirement_coverage","fabricated_unfilenamed_fact","golden_groundedness","golden_arithmetic","source_citation_existence","cell_address_pinned","rubric_overspecification","spelling_grammar","judge_file_scope_breadth","task_metadata_completeness","dependency_pin","harness_fragility","judge_determinism_config_lint","test_coverage_absence","unrequested_deliverable_source","structural_audit","undisclosed_terminology","rubric_text_lint","tab_naming","word_ban_false_trigger","deliverable_count","source_truncation"}  # GATE-V2 3.6.5 (00:35Z 09-19): judge_scope_over_inclusion and judge_file_size_cliff are BLOCKING again (DataOS 67-1-0 major 1.5 is exactly that cell); 3.6.4 (19:45Z): heuristic cells are recorded in GATE.md, never gated; the CR verdict is the bar
# 2026-09-18 (this build): task_metadata_completeness is NO LONGER auto-accepted under
# 3.6.2 - the laptop session is filling task.toml metadata corpus-wide right now, so a
# warn here just means re-run the check, not waive it. environment_size_budget stays out
# of this dict too: it is already globally ADVISORY above and never reaches this branch.
ACCEPTED_BY_RULING = {}

def golden_has_numeric_cells(task_dir):
    import openpyxl
    for xf in glob.glob(os.path.join(task_dir, "solution", "files", "*.xlsx")):
        try:
            wb = openpyxl.load_workbook(xf, data_only=True, read_only=True)
        except Exception:
            continue
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                for v in row:
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        return True
    return False

rows=[r for r in csv.DictReader(open(f)) if r.get("task_id")==t]
if not rows:
    print("[checkfix] NO ROW for", t); sys.exit(9)
r=rows[0]
nonpass=[(k,v) for k,v in r.items() if k not in ("task_id","C","D","E") and not k.endswith("_n") and not k.endswith("_first") and v not in ("pass","",None)]
accepted=[]; blocked=[]
# Mirrors stage_and_zip.sh exactly: a FAIL cell blocks unconditionally (GATE/Z-scan
# membership is irrelevant to it, same as the actuator's own gatefail.append under
# `if v=="fail"` before its `elif relevant` branch); only warn/skip/error need the
# gate-relevant check, and only those two verdicts are ever eligible for a ruling accept.
for k,v in nonpass:
    if k in ADVISORY:
        continue
    if k=="metadata_leak" and v!="fail":
        continue  # 3.6.4: warn is advisory (mirrors stage_and_zip.sh)
    evidence=r.get(k+"_first","") or ""
    if v=="fail":
        blocked.append({"check":k,"verdict":v,"evidence":evidence})
        continue
    z=any(k.startswith(p) for p in ZSCAN_PREFIXES)
    if not ((k in GATE) or z):
        continue
    # golden_arithmetic=skip on a deliverable with no numeric golden cells is
    # structurally N/A (nothing to arithmetic-check), not a defect to fix.
    if k == "golden_arithmetic" and v == "skip" and not golden_has_numeric_cells(os.path.join(corpus_root, t)):
        accepted.append({"check":k,"verdict":v,"ruling":"N/A: no numeric golden cells","evidence":evidence}); continue
    if k in ACCEPTED_BY_RULING:
        accepted.append({"check":k,"verdict":v,"ruling":ACCEPTED_BY_RULING[k],"evidence":evidence}); continue
    blocked.append({"check":k,"verdict":v,"evidence":evidence})
json.dump({"accepted":accepted,"blocked":blocked,"nonpass":[{"check":k,"verdict":v} for k,v in nonpass]}, open(outp,"w"), indent=2)
print("[checkfix] accepted=%d blocked=%d"%(len(accepted),len(blocked)))
PYEOF
}

checkfix_build_findings() {
  # $1 = classify json (has .blocked), $2 = out findings json (CR.json shape:
  # task/findings/majors_present, so gather_files_text.py and fix_plan.md
  # work on it unchanged).
  python3 - "$1" "$TASK" "$CORPUS" "$2" <<'PYEOF'
import glob, json, os, re, sys
blocked_path, task, corpus_root, out_path = sys.argv[1:5]
d = json.load(open(blocked_path))
task_dir = os.path.join(corpus_root, task)
def exists(rel):
    return os.path.isfile(os.path.join(task_dir, rel))
default_files = [p for p in ("instruction.md", "tests/task_prompt.txt", "tests/reward.toml", "tests/test.sh", "task.toml") if exists(p)]
for jt in glob.glob(os.path.join(task_dir, "tests", "**", "judge.toml"), recursive=True):
    default_files.append(os.path.relpath(jt, task_dir))
default_files = sorted(set(default_files))
FILE_RE = re.compile(r'\b[\w./-]+\.(?:xlsx|xlsm|csv|pdf|docx|json|md|txt|toml|sh)\b', re.I)
findings = []
for i, cell in enumerate(d.get("blocked", []), start=1):
    ev = cell.get("evidence", "") or ""
    affected = set(default_files)
    for m in FILE_RE.findall(ev):
        if exists(m):
            affected.add(m)
        elif exists(os.path.join("tests", m)):
            affected.add(os.path.join("tests", m))
    findings.append({
        "id": "CF%d" % i,
        "class": cell["check"],
        "severity": "major",
        "criterion_ids": [],
        "affected_files": sorted(affected),
        "description": "45-check gate checker (%s=%s) blocks the actuator (GATE-V2 3.4); not covered by any GATE-V2 3.6 ruling." % (cell["check"], cell["verdict"]),
        "evidence": ev,
        "fix_direction": "",
    })
json.dump({"task": task, "findings": findings, "majors_present": bool(findings)}, open(out_path, "w"), indent=2)
print("[checkfix] wrote %d findings to %s" % (len(findings), out_path))
PYEOF
}

blocked_count() { python3 -c "import json,sys; print(len(json.load(open(sys.argv[1])).get('blocked',[])))" "$1" 2>/dev/null || echo 999; }

if step_done CHECKFIX; then
  log "step 4.5 (check-fix): already done, skipping"
else
  log "step 4.5: 45-check checker recheck (round 0, pre-fix)"
  if ! checkfix_stage_and_run; then
    park "checkfix: checker produced no summary.csv (round 0), see $LOG"
  fi
  checkfix_classify "$PIPE/checks/checkfix_round0.json"

  cfround=1
  while [ "$(blocked_count "$PIPE/checks/checkfix_round$((cfround - 1)).json")" -gt 0 ] && [ "$cfround" -le "$CHECKFIX_MAX_ROUNDS" ]; do
    if step_done "CHECKFIX_ROUND_$cfround" && json_ok "$PIPE/checks/checkfix_plan_round${cfround}.json"; then
      log "step 4.5: check-fix round $cfround: checkpoint present, plan already applied"
    else
      log "step 4.5: check-fix round $cfround (blocked gate-relevant cells present, max $CHECKFIX_MAX_ROUNDS)"
      if ! checkfix_build_findings "$PIPE/checks/checkfix_round$((cfround - 1)).json" "$PIPE/checks/checkfix_findings_round${cfround}.json" >> "$LOG" 2>&1 \
          || ! json_ok "$PIPE/checks/checkfix_findings_round${cfround}.json"; then
        park "checkfix_build_findings failed to write a valid checkfix_findings_round${cfround}.json (round $cfround), see $LOG"
      fi
      if ! python3 "$TOOLS/gather_files_text.py" "$PIPE/checks/checkfix_findings_round${cfround}.json" --task "$TASK" \
          --corpus-root "$CORPUS" --out "$PIPE/checks/checkfix_files_text_round${cfround}.txt" >> "$LOG" 2>&1; then
        park "gather_files_text.py failed (check-fix round $cfround), see $LOG"
      fi
      # Step 4.5 is the 45-check mechanical checker's own fix loop, not a CR
      # round - there is no PLAN.round*.json edit history to feed GAP 1 here.
      echo "(N/A: check-fix round against the deterministic 45-check checker, not a CR/fix round - no prior-round edit history applies)" \
        > "$PIPE/checks/checkfix_prior_plans_round${cfround}.txt"
      # Bug fixed here (laptop session, 2026-09-18 19:50Z): render_prompt.py's
      # exit code was never checked, so a crash (e.g. an unreadable --set
      # file) left checkfix_prompt_round${cfround}.txt unwritten and silently
      # fell through to the llm_call.py line below, which then failed with a
      # confusing FileNotFoundError on the PROMPT file - 15 tasks parked that
      # way with the real cause (render_prompt.py) never logged as the
      # failure. Now checked and parked at the actual failure point.
      if ! python3 "$TOOLS/render_prompt.py" "$PROMPTS/fix_plan.md" \
          --set-lit TASK_ID="$TASK" --set CR_JSON="$PIPE/checks/checkfix_findings_round${cfround}.json" \
          --set FILES_TEXT="$PIPE/checks/checkfix_files_text_round${cfround}.txt" \
          --set PRIOR_PLANS_TEXT="$PIPE/checks/checkfix_prior_plans_round${cfround}.txt" \
          --out "$PIPE/checks/checkfix_prompt_round${cfround}.txt" >> "$LOG" 2>&1; then
        park "render_prompt.py failed on fix_plan.md (check-fix round $cfround), see $LOG"
      fi
      if ! python3 "$TOOLS/llm_call.py" --prompt-file "$PIPE/checks/checkfix_prompt_round${cfround}.txt" \
          --model opus --timeout 1500 --out "$PIPE/checks/checkfix_plan_round${cfround}.json" >> "$LOG" 2>&1; then
        lane_refused && refused_exit "check-fix plan round $cfround"
        park "check-fix plan call failed (round $cfround), see $LOG"
      fi
      python3 "$TOOLS/apply_plan.py" --plan "$PIPE/checks/checkfix_plan_round${cfround}.json" --task "$TASK" \
        --corpus-root "$CORPUS" --fix-log "$PIPE/FIX-LOG.md" >> "$LOG" 2>&1
      log "apply_plan.py check-fix round $cfround exit=$?"
      mark_done "CHECKFIX_ROUND_$cfround"
    fi

    log "step 4.5: 45-check checker recheck (round $cfround, post-fix)"
    if ! checkfix_stage_and_run; then
      park "checkfix: checker produced no summary.csv (round $cfround), see $LOG"
    fi
    checkfix_classify "$PIPE/checks/checkfix_round${cfround}.json"
    cfround=$((cfround + 1))
  done

  last_cf_round=$((cfround - 1))
  if [ "$(blocked_count "$PIPE/checks/checkfix_round${last_cf_round}.json")" -gt 0 ]; then
    still=$(python3 -c "
import json
d = json.load(open('$PIPE/checks/checkfix_round${last_cf_round}.json'))
print(', '.join('%s=%s' % (c['check'], c['verdict']) for c in d['blocked']))
")
    park "check-fix: still blocked after $CHECKFIX_MAX_ROUNDS round(s): $still (see checks/checkfix_round${last_cf_round}.json)"
  fi

  # Persist the final accepted set so step 6 can build --accept-skip and the
  # GATE.md "Accepted cells" section from it without re-deriving anything -
  # this run's accepts only, never a hardcoded list (golden_arithmetic's N/A
  # carve-out is per-task, not a standing ruling).
  python3 -c "
import json
d = json.load(open('$PIPE/checks/checkfix_round${last_cf_round}.json'))
json.dump(d.get('accepted', []), open('$PIPE/checks/checkfix_accepted.json', 'w'), indent=2)
"
  mark_done CHECKFIX
fi

# Redirect build (2026-09-18): class K (xlsx cached-value grading) applicability
# is now derived structurally from the shipped deliverable, not from a
# class_k_applicable field - the canon ekw-svc-comprehensive-review.md schema has
# no such field (its §1.2 covers formula caching as prose within check 1.2, not
# a top-level flag), so reading it from CR.json would always be empty/None and
# silently disable the no-cache probe on every xlsx task.
if ls "$CORPUS/$TASK"/solution/files/*.xlsx > /dev/null 2>&1; then
  CLASS_K=1
else
  CLASS_K=0
fi

# ---------------------------------------------------------------------------
# Step 5: probes
# GATE-V2 (laptop, 2026-09-18 21:32Z): SVC-PC-73-2-0 zipped with
# probes/oracle.json total_reward=0.88 (2/14 criteria fail on the golden
# itself). A golden failing its own rubric is a major under canon 1.1/1.5,
# and GATE-V2 3.4 requires oracle == 1.0 - fix it here, before the actuator
# can ever see a sub-1.0 oracle, instead of shipping a low-oracle zip.
oracle_needs_fix() {
  # $1 = oracle.json path. "1" only if it parses AND total_reward < 1.0.
  # "0" both when it is already 1.0 and when it does not parse at all (a
  # different, pre-existing failure mode this loop does not touch).
  python3 -c "
import json
try:
    d = json.load(open('$1'))
    r = float(d.get('total_reward'))
except Exception:
    print('0'); raise SystemExit
print('1' if r < 1.0 else '0')
" 2>/dev/null || echo "0"
}

build_oracle_findings() {
  # $1 = oracle.json, $2 = out findings json (CR.json shape: task/findings/
  # majors_present, same shape checkfix_build_findings uses, so
  # gather_files_text.py and fix_plan.md work on it unchanged).
  python3 - "$1" "$TASK" "$2" <<'PYEOF'
import json, sys
oracle_path, task, out_path = sys.argv[1:4]
d = json.load(open(oracle_path))
def walk(g):
    out = []
    for c in g.get("criteria", []):
        out.append(c)
    for ch in g.get("children", []):
        out.extend(walk(ch))
    return out
rows = []
for g in d.get("groups", []):
    rows.extend(walk(g))
failing = [r for r in rows if not r.get("passed")]
findings = []
for i, c in enumerate(failing, start=1):
    findings.append({
        "id": "OR%d" % i,
        "class": "golden_fails_own_rubric",
        "severity": "major",
        "criterion_ids": [c.get("id")],
        "affected_files": [],
        "description": ("Oracle run: golden fails criterion %s (%s) on its own rubric - a major "
                         "under canon 1.1/1.5 (the golden must satisfy its own rubric) unless the "
                         "criterion itself is wrong under a reading the instruction permits, in "
                         "which case fix the criterion instead of the golden." % (c.get("id"), c.get("name"))),
        "evidence": json.dumps(c),
        "fix_direction": "",
    })
json.dump({"task": task, "findings": findings, "majors_present": bool(findings)}, open(out_path, "w"), indent=2)
print("[oracle-fix] wrote %d findings to %s" % (len(findings), out_path))
PYEOF
}

build_adjudication_findings() {
  # $1 = ADJUDICATE.json, $2 = out findings json (CR.json shape: task/
  # findings/majors_present, same shape checkfix_build_findings/
  # build_oracle_findings use, so gather_files_text.py and fix_plan.md work
  # on it unchanged). One major finding per criterion the adjudication call
  # marked "false_rejection" (GATE-V2 3.1) - "solver_error" verdicts are not
  # findings, they are the model's fault, not the task's.
  python3 - "$1" "$TASK" "$2" <<'PYEOF'
import json, sys
adj_path, task, out_path = sys.argv[1:4]
d = json.load(open(adj_path))
findings = []
for i, a in enumerate(d.get("adjudications", []), start=1):
    if a.get("verdict") != "false_rejection":
        continue
    findings.append({
        "id": "AJ%d" % i,
        "class": "false_rejection",
        "severity": "major",
        "criterion_ids": [a.get("criterion_id")],
        "affected_files": [],
        "description": ("Adjudication (GATE-V2 3.1): criterion %s (group %s) false-rejects a "
                         "compliant reading of the instruction - %s" % (
                             a.get("criterion_id"), a.get("group"), a.get("reasoning", ""))),
        "evidence": json.dumps(a),
        "fix_direction": a.get("fix_direction", ""),
    })
json.dump({"task": task, "findings": findings, "majors_present": bool(findings)}, open(out_path, "w"), indent=2)
print("[adjudication-fix] wrote %d findings to %s" % (len(findings), out_path))
PYEOF
}

# ---------------------------------------------------------------------------
if step_done PROBES; then
  log "step 5 (probes): already done, skipping"
else
  log "step 5: oracle probe"
  python3 "$TOOLS/judge_emulate.py" oracle "$TASK" --corpus-root "$CORPUS" --out "$PIPE/probes/oracle.json" \
    >> "$LOG" 2>&1
  log "oracle exit=$?"

  oround=1
  while [ "$(oracle_needs_fix "$PIPE/probes/oracle.json")" = "1" ] && [ "$oround" -le "$MAX_ROUNDS" ]; do
    log "step 5: oracle reward < 1.0 (round $oround, max $MAX_ROUNDS) - fixing the failing criteria/golden"
    if step_done "ORACLE_FIX_ROUND_$oround" && json_ok "$PIPE/probes/oracle_plan_round${oround}.json"; then
      log "step 5: oracle-fix round $oround: checkpoint present, plan already applied"
    else
      if ! build_oracle_findings "$PIPE/probes/oracle.json" "$PIPE/probes/oracle_findings_round${oround}.json" >> "$LOG" 2>&1 \
          || ! json_ok "$PIPE/probes/oracle_findings_round${oround}.json"; then
        park "build_oracle_findings failed (oracle-fix round $oround), see $LOG"
      fi
      if ! python3 "$TOOLS/gather_files_text.py" "$PIPE/probes/oracle_findings_round${oround}.json" --task "$TASK" \
          --corpus-root "$CORPUS" --out "$PIPE/probes/oracle_files_text_round${oround}.txt" >> "$LOG" 2>&1; then
        park "gather_files_text.py failed (oracle-fix round $oround), see $LOG"
      fi
      echo "(N/A: oracle-fix round against a failing oracle probe, not a CR round - no prior-round edit history applies)" \
        > "$PIPE/probes/oracle_prior_plans_round${oround}.txt"
      if ! python3 "$TOOLS/render_prompt.py" "$PROMPTS/fix_plan.md" \
          --set-lit TASK_ID="$TASK" --set CR_JSON="$PIPE/probes/oracle_findings_round${oround}.json" \
          --set FILES_TEXT="$PIPE/probes/oracle_files_text_round${oround}.txt" \
          --set PRIOR_PLANS_TEXT="$PIPE/probes/oracle_prior_plans_round${oround}.txt" \
          --out "$PIPE/probes/oracle_prompt_round${oround}.txt" >> "$LOG" 2>&1; then
        park "render_prompt.py failed on fix_plan.md (oracle-fix round $oround), see $LOG"
      fi
      if ! python3 "$TOOLS/llm_call.py" --prompt-file "$PIPE/probes/oracle_prompt_round${oround}.txt" \
          --model opus --timeout 1500 --out "$PIPE/probes/oracle_plan_round${oround}.json" >> "$LOG" 2>&1; then
        lane_refused && refused_exit "oracle-fix plan round $oround"
        park "oracle-fix plan call failed (round $oround), see $LOG"
      fi
      python3 "$TOOLS/apply_plan.py" --plan "$PIPE/probes/oracle_plan_round${oround}.json" --task "$TASK" \
        --corpus-root "$CORPUS" --fix-log "$PIPE/FIX-LOG.md" >> "$LOG" 2>&1
      log "apply_plan.py oracle-fix round $oround exit=$?"
      mark_done "ORACLE_FIX_ROUND_$oround"
    fi

    if step_done "ORACLE_FIX_CR_$oround" && json_ok "$PIPE/CR.oraclefix${oround}.json"; then
      log "step 5: canon re-review after oracle-fix round $oround: checkpoint present"
      cp "$PIPE/CR.oraclefix${oround}.json" "$PIPE/CR.json"
    else
      log "step 5: canon re-review after oracle-fix round $oround"
      if ! run_blind_cr "$PIPE/CR.json" "oraclefix${oround}"; then
        lane_refused && refused_exit "canon re-review after oracle-fix round $oround"
        park "canon re-review failed after oracle-fix round $oround, see $LOG"
      fi
      cp "$PIPE/CR.json" "$PIPE/CR.oraclefix${oround}.json"
      mark_done "ORACLE_FIX_CR_$oround"
    fi
    if [ "$(majors_of "$PIPE/CR.json")" = "1" ]; then
      park "oracle-fix round $oround introduced or left a major per the canon re-review, see CR.json"
    fi

    if step_done "ORACLE_RECHECK_$oround" && json_ok "$PIPE/probes/oracle_round${oround}.json"; then
      log "step 5: oracle recheck (round $oround): checkpoint present, reusing"
      cp "$PIPE/probes/oracle_round${oround}.json" "$PIPE/probes/oracle.json"
    else
      log "step 5: re-running oracle probe after oracle-fix round $oround"
      python3 "$TOOLS/judge_emulate.py" oracle "$TASK" --corpus-root "$CORPUS" --out "$PIPE/probes/oracle.json" \
        >> "$LOG" 2>&1
      log "oracle exit=$? (round $oround)"
      cp "$PIPE/probes/oracle.json" "$PIPE/probes/oracle_round${oround}.json"
      mark_done "ORACLE_RECHECK_$oround"
    fi
    oround=$((oround + 1))
  done

  if [ "$(oracle_needs_fix "$PIPE/probes/oracle.json")" = "1" ]; then
    park "oracle reward still < 1.0 after $MAX_ROUNDS oracle-fix round(s), see probes/oracle.json"
  fi

  if [ "$CLASS_K" = "1" ]; then
    log "step 5: no-cache probe (class K)"
    python3 "$TOOLS/formula_cache_scan.py" --probe "$TASK" --corpus-root "$CORPUS" \
      --scratch-root "$PIPE/probes/_nocache_scratch" --probe-out "$PIPE/probes/nocache.json" \
      --model claude-sonnet-4-6 >> "$LOG" 2>&1
    log "no-cache probe exit=$?"
  else
    log "step 5: no-cache probe N/A (not class K)"
  fi

  log "step 5: echo probe (script-generated, no model call)"
  python3 "$TOOLS/build_echo_probe.py" "$TASK" --corpus-root "$CORPUS" --out "$PIPE/probes/echo_deliverable.txt" \
    >> "$LOG" 2>&1
  python3 "$TOOLS/judge_emulate.py" echo "$TASK" "$PIPE/probes/echo_deliverable.txt" --corpus-root "$CORPUS" \
    --out "$PIPE/probes/echo.json" >> "$LOG" 2>&1
  log "echo probe exit=$?"
  # GATE-V2 (verifier spec, FOR-PIPE2.md item 6, 2026-09-19): GATE-V2 3.1
  # requires echo < 0.3 (assertions restated, no figures, must not pass the
  # rubric) - this was computed and written to GATE.md but gated on nothing;
  # SVC-PC-8-2-0 shipped with echo=0.9798 in the log and no branch on it at
  # all. Block here, the cheapest detector this pipeline owns.
  echo_reward=$(python3 -c "
import json
try:
    d = json.load(open('$PIPE/probes/echo.json'))
    print(d.get('total_reward'))
except Exception:
    print('null')
" 2>/dev/null || echo "null")
  if [ "$echo_reward" != "null" ] && python3 -c "import sys; sys.exit(0 if float('$echo_reward') >= 0.3 else 1)" 2>/dev/null; then
    park "echo probe scored $echo_reward >= 0.3 (GATE-V2 3.1 requires < 0.3 - restated assertions with no figures should not pass the rubric), see probes/echo.json"
  fi

  log "step 5: GLM solver grading"
  bash "$TOOLS/solver_grade.sh" "$TASK" >> "$LOG" 2>&1
  log "solver_grade.sh exit=$?"

  # both-runs-failed adjudication (model call, only if both runs graded and
  # at least one criterion failed both).
  if python3 "$TOOLS/gather_both_failed.py" --task "$TASK" --runs-root "$RUNS_ROOT" \
      --out "$PIPE/BOTH_FAILED.txt" >> "$LOG" 2>&1; then
    if ! grep -q "nothing to adjudicate" "$PIPE/BOTH_FAILED.txt" 2>/dev/null; then
      log "step 5: both-runs-failed adjudication"
      python3 "$TOOLS/build_cr_context.py" "$TASK" --corpus-root "$CORPUS" --out "$PIPE/CONTEXT.txt" >> "$LOG" 2>&1
      if ! python3 "$TOOLS/render_prompt.py" "$PROMPTS/adjudicate.md" \
          --set-lit TASK_ID="$TASK" --set PACKAGE_TEXT="$PIPE/CONTEXT.txt" --set BOTH_FAILED_TEXT="$PIPE/BOTH_FAILED.txt" \
          --out "$PIPE/prompt_adjudicate.txt" >> "$LOG" 2>&1; then
        park "render_prompt.py failed on adjudicate.md, see $LOG"
      fi
      if python3 "$TOOLS/llm_call.py" --prompt-file "$PIPE/prompt_adjudicate.txt" \
          --model opus --timeout 1500 --out "$PIPE/ADJUDICATE.json" >> "$LOG" 2>&1; then
        any_fr=$(python3 -c "import json; d=json.load(open('$PIPE/ADJUDICATE.json')); print('1' if d.get('any_false_rejection') else '0')" 2>/dev/null || echo "0")
        if [ "$any_fr" = "1" ]; then
          # GATE-V2 (laptop, 2026-09-18 22:55Z): route this into the pipeline
          # instead of parking on the first hit. Build a major finding per
          # false-rejected criterion from ADJUDICATE.json, apply one seed fix
          # round against it, then force the full canon CR/FIX + check-fix +
          # oracle-fix machinery to reconverge fresh (reusing
          # discard_stale_pre_canon_state + the same self-re-exec pattern as
          # the actuator rc=7/rc=8 retries above) - within MAX_ROUNDS by
          # construction, since that fresh pass's own round loops are each
          # bounded by MAX_ROUNDS. One-shot retry guard: park for a human only
          # if adjudication still finds a false rejection after this.
          if [ -f "$PIPE/.retried_adjudication" ]; then
            park "adjudication found a false rejection after one automatic fix-and-retry, see ADJUDICATE.json - needs a human"
          fi
          log "step 5: adjudication found a false rejection - building findings, seeding one fix round, then retrying the full pipeline fresh"
          touch "$PIPE/.retried_adjudication"
          if ! build_adjudication_findings "$PIPE/ADJUDICATE.json" "$PIPE/adjudicate_findings.json" >> "$LOG" 2>&1 \
              || ! json_ok "$PIPE/adjudicate_findings.json"; then
            park "build_adjudication_findings failed, see $LOG"
          fi
          if ! python3 "$TOOLS/gather_files_text.py" "$PIPE/adjudicate_findings.json" --task "$TASK" \
              --corpus-root "$CORPUS" --out "$PIPE/adjudicate_files_text.txt" >> "$LOG" 2>&1; then
            park "gather_files_text.py failed (adjudication seed fix), see $LOG"
          fi
          echo "(N/A: adjudication seed fix, not a CR round - no prior-round edit history applies)" \
            > "$PIPE/adjudicate_prior_plans.txt"
          if ! python3 "$TOOLS/render_prompt.py" "$PROMPTS/fix_plan.md" \
              --set-lit TASK_ID="$TASK" --set CR_JSON="$PIPE/adjudicate_findings.json" \
              --set FILES_TEXT="$PIPE/adjudicate_files_text.txt" \
              --set PRIOR_PLANS_TEXT="$PIPE/adjudicate_prior_plans.txt" \
              --out "$PIPE/adjudicate_prompt.txt" >> "$LOG" 2>&1; then
            park "render_prompt.py failed on fix_plan.md (adjudication seed fix), see $LOG"
          fi
          if ! python3 "$TOOLS/llm_call.py" --prompt-file "$PIPE/adjudicate_prompt.txt" \
              --model opus --timeout 1500 --out "$PIPE/adjudicate_plan.json" >> "$LOG" 2>&1; then
            lane_refused && refused_exit "adjudication seed fix plan"
            park "adjudication seed fix-plan call failed, see $LOG"
          fi
          python3 "$TOOLS/apply_plan.py" --plan "$PIPE/adjudicate_plan.json" --task "$TASK" \
            --corpus-root "$CORPUS" --fix-log "$PIPE/FIX-LOG.md" >> "$LOG" 2>&1
          log "apply_plan.py adjudication seed fix exit=$?"
          discard_stale_pre_canon_state
          exec bash "$0" "$TASK"
        fi
      else
        log "WARNING: adjudication call failed, continuing without it (see $LOG)"
      fi
    fi
  else
    log "both-runs-failed check: runs not graded yet (see $LOG), continuing without adjudication"
  fi

  mark_done PROBES
fi

# ---------------------------------------------------------------------------
# Step 6: assemble GATE.md, actuator
# ---------------------------------------------------------------------------
append_accepted_cells_section() {
  # Dynamic, read from checks/checkfix_accepted.json (this task's own run) - never
  # a hardcoded list, so GATE.md can't drift from what --accept-skip actually passed.
  # environment_size_budget is the one standing exception: it is globally ADVISORY
  # in stage_and_zip.sh (never reaches checkfix_accepted.json at all), so it is
  # always noted here regardless of what this task's checker run happened to flag.
  {
    echo ""
    echo "## 8. Accepted cells (GATE-V2 3.6 rulings / structural N/A; not fixed, not blocking)"
    echo ""
    echo "- \`environment_size_budget\`: advisory corpus-wide per GATE-V2 3.6.1 (size recorded in zip.log, never gated)."
    if [ -f "$PIPE/checks/checkfix_accepted.json" ]; then
      python3 -c "
import json
d = json.load(open('$PIPE/checks/checkfix_accepted.json'))
for c in d:
    print('- \`%s\` (%s): accepted per %s.' % (c['check'], c['verdict'], c.get('ruling', 'no ruling recorded')))
" 2>/dev/null
    fi
    echo ""
    echo "\`task_metadata_completeness\` is NOT on this list (2026-09-18): the laptop session is"
    echo "filling task.toml metadata corpus-wide, so a warn here is re-checked/fixed like any"
    echo "other cell, not waived under 3.6.2 any more."
    echo ""
    echo "Evidence: \`checks/checkfix_round0.json\` (pre-fix), \`checks/checkfix_round*.json\`"
    echo "(post-fix rounds), \`checks/checkfix_accepted.json\` (this run's final accepted set)."
  } >> "$PIPE/GATE.md"
}

append_severity_calibration_section() {
  # Redirect build (2026-09-18): the homegrown "GATE-V2 3.3 refinement" severity
  # table this function used to append is gone (pipe2-prompt3.txt: "do not write
  # our own severity table") - it referenced map a/b/e and classes B/M/O, none of
  # which exist in the canon ekw-svc-comprehensive-review.md schema this task was
  # actually reviewed against (section 1's GATE.md already carries that schema's
  # own overall_verdict/major_count/minor_count and the §4 decisive test lives in
  # blind_cr.md verbatim). This section is now only the historical calibration
  # data point, as a factual reference, never a competing rule.
  {
    echo ""
    echo "## 9. Severity calibration - historical reference only"
    echo ""
    echo "This run's severity comes entirely from CR.json's own overall_verdict/major_count/"
    echo "minor_count (section 1 above), graded against the canon ekw-svc-comprehensive-review.md"
    echo "\`major\`/\`minor\`/\`good\` rules (its own §4, embedded verbatim in \`tools/prompts/blind_cr.md\`)."
    echo "No locally-authored severity table is applied on top of it."
    echo ""
    echo "For context only: three real DataOS Comprehensive Reviews on SVC-PC-54-2-0 (2026-09-18,"
    echo "pre-redirect) returned Claude Opus 5 (0 major/2 minor), Codex GPT-5.6 review 1 (2 major/2"
    echo "minor), Codex review 2 (1 major/1 minor) - see \`/root/qc/in/dataos-cr-batch3-returns/\`."
  } >> "$PIPE/GATE.md"
}

log "step 6: assembling GATE.md"
python3 "$TOOLS/assemble_gate.py" --pipe-dir "$PIPE" --task "$TASK" --out "$PIPE/GATE.md" >> "$LOG" 2>&1

log "step 6: actuator (stage_and_zip.sh)"
ACCEPT_SKIP_LIST=$(python3 -c "
import json
try:
    d = json.load(open('$PIPE/checks/checkfix_accepted.json'))
except Exception:
    d = []
print(','.join(sorted(set(c['check'] for c in d))))
" 2>/dev/null)
bash /root/qc/stage_and_zip.sh "$CORPUS" "$TASK" "$OUT_DIR" \
  ${ACCEPT_SKIP_LIST:+--accept-skip "$ACCEPT_SKIP_LIST"} > "$PIPE/zip.log" 2>&1
zip_rc=$?
log "stage_and_zip.sh exit=$zip_rc (accept-skip: ${ACCEPT_SKIP_LIST:-none})"

# Regenerate GATE.md once more so its actuator section reflects zip.log, then
# append the accepted-cells and severity-calibration records (assemble_gate.py
# overwrites the file).
python3 "$TOOLS/assemble_gate.py" --pipe-dir "$PIPE" --task "$TASK" --out "$PIPE/GATE.md" >> "$LOG" 2>&1
append_accepted_cells_section
append_severity_calibration_section

if [ "$zip_rc" -eq 0 ]; then
  mark_done DONE
  log "DONE: $OUT_DIR/$TASK.zip"
  exit 0
elif [ "$zip_rc" -eq 7 ]; then
  # GATE-V2 (laptop, 2026-09-18 21:32Z): rc=7 = the actuator's own check found
  # CR.json without overall_verdict - "needs review", not a park. One
  # automatic retry (guarded by a marker file so a persistent rc=7 still
  # parks for a human instead of looping forever): discard the stale CR/FIX/
  # CHECKFIX/PROBES state exactly as the step-3 guard above does, then
  # re-invoke this same script. `exec` replaces the process image but keeps
  # this process's already-open lock fd (9) intact, so no other instance can
  # race in; the re-invocation's own `exec 9>"$LOCK_FILE"` cleanly reopens and
  # re-flocks it in the same process.
  if [ -f "$PIPE/.retried_rc7" ]; then
    park "actuator rc=7 (CR.json lacks overall_verdict) persisted after one automatic canon-review retry, see $PIPE/zip.log - needs a human"
  fi
  log "step 6: actuator rc=7 (CR.json lacks overall_verdict) - discarding stale CR/FIX/CHECKFIX/PROBES state, retrying once with a fresh canon review"
  touch "$PIPE/.retried_rc7"
  discard_stale_pre_canon_state
  exec bash "$0" "$TASK"
elif [ "$zip_rc" -eq 8 ]; then
  # rc=8 = the actuator's own check found oracle total_reward < 1.0 - "needs
  # oracle fix", not a park. Same one-shot-retry-then-park guard as rc=7.
  if [ -f "$PIPE/.retried_rc8" ]; then
    park "actuator rc=8 (oracle < 1.0) persisted after one automatic oracle-fix retry, see $PIPE/zip.log - needs a human"
  fi
  log "step 6: actuator rc=8 (oracle < 1.0) - clearing PROBES state, retrying once with the oracle-fix loop"
  touch "$PIPE/.retried_rc8"
  grep -vE '^(PROBES|ORACLE_FIX_ROUND_[0-9]+|ORACLE_FIX_CR_[0-9]+|ORACLE_RECHECK_[0-9]+)$' "$STATE_FILE" > "$STATE_FILE.tmp" 2>/dev/null
  mv "$STATE_FILE.tmp" "$STATE_FILE" 2>/dev/null || true
  exec bash "$0" "$TASK"
else
  park "actuator (stage_and_zip.sh) failed, rc=$zip_rc, see $PIPE/zip.log"
fi
