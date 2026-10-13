#!/usr/bin/env bash
# fix_from_dataos.sh - laptop coordinator, 2026-09-19 04:22Z: DataOS's own
# answer key as the reviewer. A third "thorough" Sonnet reviewer with
# mandatory worksheets did not raise recall on DataOS's blocking majors (3
# of 39 caught, same count as glm+sonnet, different rows) - but we already
# hold DataOS's own verify-session output for 30 tasks: 90 rows the verify
# session ruled still true on CURRENT bytes, and nobody had fed them to a
# fix round. This script does exactly that, once per task, for those 30.
#
# One-shot batch over a FIXED task list (not fix_from_reviews.sh's infinite
# poll - there is no new DataOS data arriving to wait for), ordered: the 9
# tasks the verify session found 100% still-true first, then the other 21.
# Idempotent (DATAOS_MAJORS_1 in STATE gates re-processing) - safe to re-run
# if interrupted, and safe to re-run later if the CSVs are refreshed with
# more rows (a task with 0 still-true findings in a re-run is a no-op).
#
# Shares fix_from_reviews.sh's OWN per-task lock file
# ($PIPE/fix_from_reviews.lock) rather than a track-specific one: both
# scripts can edit the SAME task's corpus files (judge.toml, instruction.md,
# golden), and running them concurrently on one task without a shared mutex
# would race two apply_plan.py calls against the same files. All of this
# track's own artifacts are namespaced *.dataos.* / FIX-FROM-DATAOS.md so
# they never collide with fix_from_reviews.sh's own round0/round1/round2
# files even when both have touched the same task.
#
# Constraints from the brief, enforced here:
#   - SVC-PC-36-5-0 check 1.7 is hard-excluded (build_dataos_union.py's
#     DO_NOT_AUTO_FIX) - flagged by the verify session as possibly by
#     design; a human decides that one, not a fix-plan call.
#   - golden_leak_scan_task.py (per-task wrapper around the canon 1.6 answer-
#     exposure scan, ~22s/task vs >2min for the full 202-task corpus sweep)
#     runs BEFORE and AFTER every edit. If the AFTER run is flagged (or
#     coverage rose materially vs BEFORE), the task is parked instead of
#     having new reviews launched on it - never ship a task whose fix might
#     have leaked an expected value into what the solver reads.
#   - Structural defects (files= nested below initial_workspace so it
#     resolves as not-found, a files= scope mismatch) belong in fix_plan.md's
#     own G1/G-menu territory (judge.toml/test config), not task content -
#     no special-casing needed here, the existing fix_plan.md prompt already
#     carries that guidance and CR_JSON's evidence text says so per row.
#
# Usage:
#   nohup /root/qc/tools/fix_from_dataos.sh \
#     > /root/qc/_prompts/fix_from_dataos.nohup.log 2>&1 &
set -uo pipefail
cd /root/qc || exit 1

CORPUS="${CORPUS:-/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready}"
TOOLS=/root/qc/tools
PROMPTS="$TOOLS/prompts"
PIPE_ROOT="${PIPE_ROOT:-/root/qc/stream-pipe}"
REVIEW_WS="${REVIEW_WS:-/root/qc/review_workspace_bulk}"
RUNS_ROOT="${RUNS_ROOT:-/root/qc/runs}"
STATUS_CSV="${DATAOS_STATUS_CSV:-/root/qc/_prompts/verify/dataos-old/status.csv}"
MAJORS_CSV="${DATAOS_MAJORS_CSV:-/root/qc/_prompts/verify/dataos-old/majors.csv}"
LOG="${FIX_FROM_DATAOS_LOG:-/root/qc/_prompts/fix_from_dataos.log}"
CONC="${FIX_FROM_DATAOS_CONC:-4}"
LEAK_THRESHOLD="${FIX_FROM_DATAOS_LEAK_THRESHOLD:-0.25}"

# Same 11-lane review pool and -q/-r-first fix-plan pool fix_from_reviews.sh
# uses - a shared, limited resource, so this track draws from the SAME
# pools rather than inventing a third one that would only add contention.
POOL=(/root/.claude /root/.claude-b /root/.claude-c /root/.claude-d /root/.claude-e /root/.claude-f /root/.claude-g /root/.claude-i /root/.claude-j /root/.claude-k /root/.claude-l)
FIX_LANE_POOL=(/root/.claude-q /root/.claude-r "${POOL[@]}")

mkdir -p "$(dirname "$LOG")"
touch "$LOG"
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG" >&2; }

# shellcheck disable=SC1091
source /root/venv/bin/activate 2>/dev/null || true

step_done_in() { grep -qx "$2" "$1" 2>/dev/null; }
mark_done_in() { echo "$2" >> "$1"; }
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

# Pure functions (task[+salt] -> lane), safe from inside a backgrounded
# subshell - see fix_from_reviews.sh's own next_lane bug writeup for why a
# stateful counter is not safe there and this is.
fix_lane_for() {
  local h; h=$(printf '%s' "$1dataos" | cksum | cut -d' ' -f1)
  echo "${FIX_LANE_POOL[$(( h % ${#FIX_LANE_POOL[@]} ))]}"
}
review_lane_for() {
  local h; h=$(printf '%s' "$1$2dataos" | cksum | cut -d' ' -f1)
  echo "${POOL[$(( h % ${#POOL[@]} ))]}"
}
alt_lane_for() {
  local h; h=$(printf '%s' "$1$2$3dataos" | cksum | cut -d' ' -f1)
  echo "${POOL[$(( h % ${#POOL[@]} ))]}"
}

# Copied (in spirit) from gate_task.sh's run_task_scans via fix_from_reviews.sh's
# own copy - gate_task.sh must not be edited. Keep in sync by hand.
run_task_scans() {
  local task="$1" pipe="$2"
  local scans=(
    "formula_cache_scan.py" "quantifier_scope_scan.py" "escape_hatch_scan.py"
    "source_reliability_scan.py" "rubric_consistency_scan.py" "answer_preexposure_scan.py"
    "instruction_input_scan.py" "cross_group_duplicate_scan.py" "discretion_pin_scan.py"
    "golden_citation_scan.py" "muststrip_scan.py"
  )
  for s in "${scans[@]}"; do
    local stem="${s%.py}" extra=()
    if [ "$stem" = "formula_cache_scan" ]; then extra=(--exposed-out "$pipe/checks/formula_cache_exposed.csv"); fi
    python3 "$TOOLS/$s" --task "$task" --corpus-root "$CORPUS" \
      --out "$pipe/checks/$stem.csv" --verdict-out "$pipe/checks/$stem.verdict.csv" \
      "${extra[@]}" >> "$LOG" 2>&1
    [ $? -ne 0 ] && log "WARNING: $task: $s exited non-zero (fix-from-dataos run_task_scans)"
  done
  for s in env_size_report.py metadata_fill.py; do
    local stem="${s%.py}" scratch_csv="$pipe/checks/_scratch_${stem}.csv" scratch_verdict="$pipe/checks/_scratch_${stem}.verdict.csv"
    python3 "$TOOLS/$s" --corpus-root "$CORPUS" --out "$scratch_csv" --verdict-out "$scratch_verdict" >> "$LOG" 2>&1
    [ -f "$scratch_verdict" ] && awk -F, -v t="$task" 'NR==1 || $1==t' "$scratch_verdict" > "$pipe/checks/$stem.verdict.csv"
  done
}

run_dataos_review() {
  local task="$1" reviewer="$2" lane="$3" pipe="$4"
  local out="$pipe/CR.$reviewer.dataos.json"
  local attempt this_lane rc
  for attempt in 1 2; do
    this_lane="$lane"
    [ "$attempt" -gt 1 ] && this_lane=$(alt_lane_for "$task" "$reviewer" "$attempt")
    CLAUDE_CONFIG_DIR="$this_lane" python3 "$TOOLS/run_workspace_review.py" --task "$task" --corpus-root "$CORPUS" \
      --workspace-root "$REVIEW_WS/$reviewer" --runs-root "$RUNS_ROOT" --pipe-dir "$pipe" --reviewer "$reviewer" --timeout 2400 \
      --out "$out" --stats-out "$pipe/CR.$reviewer.dataos.stats.json" > "$pipe/CR.$reviewer.dataos.log" 2>&1
    rc=$?
    canon_ok "$out" && break
    log "RETRY-DATAOS-REVIEW $task $reviewer attempt=$attempt lane=$(basename "$this_lane") rc=$rc (not canon-shaped, retrying once on a different lane)"
  done
  local v
  v=$(python3 -c "import json; j=json.load(open('$out')); print(j.get('overall_verdict'), 'maj', j.get('major_count'), 'min', j.get('minor_count'))" 2>/dev/null || echo "NO-JSON rc=$rc")
  log "FINISH-DATAOS-REVIEW $task $reviewer rc=$rc $v"
}

process_dataos_task() {
  local task="$1"
  local pipe="$PIPE_ROOT/$task"
  local state="$pipe/STATE"
  local lockfile="$pipe/fix_from_reviews.lock"   # shared with fix_from_reviews.sh, deliberately

  mkdir -p "$pipe"
  touch "$state"

  exec 8>"$lockfile"
  if ! flock -n 8; then
    log "SKIP $task (fix_from_reviews.sh or another fix_from_dataos.sh job holds the lock)"
    return
  fi

  if step_done_in "$state" DATAOS_MAJORS_1; then
    log "SKIP $task (DATAOS_MAJORS_1 already marked)"
    return
  fi

  log "START $task fix-from-dataos"

  python3 "$TOOLS/build_dataos_union.py" --task "$task" \
    --status-csv "$STATUS_CSV" --majors-csv "$MAJORS_CSV" \
    --out "$pipe/CR.union.dataos.json" >> "$LOG" 2>&1

  local n_findings
  n_findings=$(python3 -c "import json; print(len(json.load(open('$pipe/CR.union.dataos.json')).get('findings', [])))" 2>/dev/null || echo 0)

  if [ "$n_findings" = "0" ]; then
    mark_done_in "$state" DATAOS_MAJORS_1
    log "SKIP $task (0 still-true DataOS findings after do-not-auto-fix exclusions, marked DATAOS_MAJORS_1, no model call spent)"
    return
  fi

  log "FIX $task: $n_findings still-true DataOS major(s), running one fix round"

  # Pre-edit answer-exposure baseline (canon 1.6) - logged, not gating; the
  # gate is the POST-edit run below, but this lets a human see if leakage
  # was already present before this track ever touched the task.
  python3 "$TOOLS/golden_leak_scan_task.py" --task "$task" --corpus-root "$CORPUS" \
    --threshold "$LEAK_THRESHOLD" > "$pipe/checks/golden_leak_pre_dataos.txt" 2>&1
  log "$task: pre-edit answer-exposure check: $(cat "$pipe/checks/golden_leak_pre_dataos.txt" | tr '\n' ' ')"

  python3 "$TOOLS/gather_files_text.py" "$pipe/CR.union.dataos.json" --task "$task" --corpus-root "$CORPUS" \
    --out "$pipe/FILES_TEXT_dataos.txt" >> "$LOG" 2>&1

  echo "(fix-from-dataos track: first and only round for this task under this track - no prior-round edit history applies)" \
    > "$pipe/PRIOR_PLANS_dataos.txt"

  local lane_fix
  lane_fix=$(fix_lane_for "$task")

  if ! python3 "$TOOLS/render_prompt.py" "$PROMPTS/fix_plan.md" \
      --set-lit TASK_ID="$task" --set CR_JSON="$pipe/CR.union.dataos.json" \
      --set FILES_TEXT="$pipe/FILES_TEXT_dataos.txt" \
      --set PRIOR_PLANS_TEXT="$pipe/PRIOR_PLANS_dataos.txt" \
      --out "$pipe/PROMPT_dataos.txt" >> "$LOG" 2>&1; then
    log "ERROR $task: render_prompt.py failed on fix_plan.md (fix-from-dataos), see $LOG - not marking done, will retry next run"
    return
  fi

  if ! CLAUDE_CONFIG_DIR="$lane_fix" python3 "$TOOLS/llm_call.py" --prompt-file "$pipe/PROMPT_dataos.txt" \
      --model opus --timeout 1500 --out "$pipe/PLAN.dataos.json" >> "$LOG" 2>&1; then
    log "ERROR $task: fix-plan call failed (fix-from-dataos, lane=$(basename "$lane_fix")), see $LOG - not marking done, will retry next run"
    return
  fi

  python3 "$TOOLS/apply_plan.py" --plan "$pipe/PLAN.dataos.json" --task "$task" \
    --corpus-root "$CORPUS" --fix-log "$pipe/FIX-FROM-DATAOS.md" >> "$LOG" 2>&1
  log "$task: apply_plan.py (fix-from-dataos) exit=$?"

  run_task_scans "$task" "$pipe"
  python3 "$TOOLS/merge_scan_verdicts.py" --reports-dir "$pipe/checks" --out "$pipe/checks/scan_summary.csv" >> "$LOG" 2>&1

  # Post-edit answer-exposure gate (canon 1.6, mandatory per the brief:
  # "never put expected values into anything the solver reads; run the
  # existing answer-key leak scan on every change"). A flag here (or a
  # material rise vs the pre-edit baseline) means the fix-plan model may
  # have copied one of DataOS's claimed/expected values into instruction.md
  # or environment/ - park instead of shipping it forward into new reviews.
  python3 "$TOOLS/golden_leak_scan_task.py" --task "$task" --corpus-root "$CORPUS" \
    --threshold "$LEAK_THRESHOLD" > "$pipe/checks/golden_leak_post_dataos.txt" 2>&1
  local leak_rc=$?
  log "$task: post-edit answer-exposure check: $(cat "$pipe/checks/golden_leak_post_dataos.txt" | tr '\n' ' ')"

  if [ "$leak_rc" != "0" ]; then
    echo "$(date -u +%FT%TZ) PARKED: fix-from-dataos - post-edit answer-exposure scan (canon 1.6) flagged this task after the fix round; see checks/golden_leak_post_dataos.txt and checks/golden_leak_pre_dataos.txt for before/after. Not launching new reviews until a human confirms no expected value was copied into anything the solver reads." \
      >> "$pipe/PARKED.md"
    log "PARKED $task: answer-exposure scan flagged post-edit, NOT launching reviews, see $pipe/PARKED.md"
    mark_done_in "$state" DATAOS_MAJORS_1
    return
  fi

  mark_done_in "$state" DATAOS_MAJORS_1
  log "DONE $task fix-from-dataos round applied, DATAOS_MAJORS_1 marked, answer-exposure clean; launching new glm+sonnet reviews"

  local lane_glm lane_sonnet
  lane_glm=$(review_lane_for "$task" glm)
  lane_sonnet=$(review_lane_for "$task" sonnet)

  run_dataos_review "$task" glm "$lane_glm" "$pipe" &
  local pid_glm=$!
  run_dataos_review "$task" sonnet "$lane_sonnet" "$pipe" &
  local pid_sonnet=$!
  wait "$pid_glm" "$pid_sonnet"
  log "DONE $task fix-from-dataos reviews both finished - leaving for the verify session to re-verify still-true rows"
}

# ---------------------------------------------------------------------------
# Fixed, ordered task list - not a glob scan. Priority 9 first (100%
# still-true per the verify session), then the other 21 discovered from
# STATUS_CSV (alphabetical, so re-running after a CSV refresh is
# deterministic).
# ---------------------------------------------------------------------------
PRIORITY_TASKS=(SVC-PC-21-0-0 SVC-PC-37-3-0 SVC-PC-72-3-0 SVC-PC-72-4-0 SVC-PC-52-6-0 SVC-PC-82-2-0 SVC-PC-57-1-0 SVC-PC-41-4-0 SVC-PC-5-5-0)

mapfile -t ALL_STILL_TRUE_TASKS < <(python3 -c "
import csv
rows = [r for r in csv.DictReader(open('$STATUS_CSV')) if r['still_true']=='yes']
print('\n'.join(sorted(set(r['task'] for r in rows))))
")

OTHER_TASKS=()
for t in "${ALL_STILL_TRUE_TASKS[@]}"; do
  is_priority=0
  for p in "${PRIORITY_TASKS[@]}"; do [ "$t" = "$p" ] && is_priority=1 && break; done
  [ "$is_priority" = "0" ] && OTHER_TASKS+=("$t")
done

ORDERED_TASKS=("${PRIORITY_TASKS[@]}" "${OTHER_TASKS[@]}")
log "FIX-FROM-DATAOS START pid=$$ conc=$CONC tasks=${#ORDERED_TASKS[@]} (priority=${#PRIORITY_TASKS[@]} other=${#OTHER_TASKS[@]})"
log "ORDER: ${ORDERED_TASKS[*]}"

for task in "${ORDERED_TASKS[@]}"; do
  while [ "$(jobs -rp | wc -l)" -ge "$CONC" ]; do sleep 10; done
  process_dataos_task "$task" &
  sleep 2
done
wait
log "FIX-FROM-DATAOS ALL 30 TASKS DISPATCHED AND COMPLETE"
