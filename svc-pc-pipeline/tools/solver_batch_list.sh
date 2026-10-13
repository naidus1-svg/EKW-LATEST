#!/usr/bin/env bash
# solver_batch_list.sh - derived from solver_batch.sh (laptop, 2026-09-19): limited to $SOLVER_ONLY_LIST, fixed concurrency $SOLVER_LIMIT.
# solver_batch.sh - SOLVE NOW, GRADE LATER.
#
# Runs the GLM solver (same copy+run logic as solver_run.sh) across the
# queued SVC-PC tasks, glm-1 and glm-2 each. This script never grades -
# grading is a separate, per-task step (see solver_grade.sh) run at the gate.
#
# SAFETY:
#   - Dry-run by default. Without --go this only prints the queue plan and
#     exits 0. It can never do anything by accident.
#   - Even with --go, refuses (exit 3) if /root/.glm_env is absent.
#   - Never echoes the GLM proxy token.
#
# Usage:
#   solver_batch.sh            # dry-run: print queue plan, exit 0
#   solver_batch.sh --go       # actually launch runs (still gated on glm_env)

set -euo pipefail

CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
GLM_ENV=/root/.glm_env
GLM_BASE_URL=http://34.41.10.8:4000
GLM_MODEL=glm-5.2
RUN_TIMEOUT_SECS=3600
BATCH1_RETURNS_DIR=/root/qc/in/dataos-cr-batch1-returns
OUT_GLOB_ROOT=/root/qc/out
RUNS_ROOT=/root/qc/runs
BATCH_LOG="$RUNS_ROOT/BATCH.log"

GO=0
for arg in "$@"; do
  case "$arg" in
    --go) GO=1 ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: $(basename "$0") [--go]" >&2
      exit 2
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Build the queue: (1) batch-1 returned tasks, (2) tasks with a zip under
# /root/qc/out/*/, (3) remaining corpus tasks. De-duped, order preserved.
# ---------------------------------------------------------------------------
declare -a QUEUE=()
declare -A SEEN=()

add_task() {
  local t="$1"
  if [ -z "${SEEN[$t]:-}" ]; then
    QUEUE+=("$t")
    SEEN[$t]=1
  fi
}

# (1) main's batch-1 returns: task id is the SVC-PC-<a>-<b>-<c> prefix of the
# filename, before the first "__" (or ".json" if there is no "__").
if [ -d "$BATCH1_RETURNS_DIR" ]; then
  for f in "$BATCH1_RETURNS_DIR"/*.json; do
    [ -e "$f" ] || continue
    base="$(basename "$f")"
    if [[ "$base" =~ ^(SVC-PC-[0-9]+-[0-9]+-[0-9]+) ]]; then
      add_task "${BASH_REMATCH[1]}"
    fi
  done
fi

# (2) any task with a zip under /root/qc/out/*/SVC-PC-*.zip
for f in "$OUT_GLOB_ROOT"/*/SVC-PC-*.zip; do
  [ -e "$f" ] || continue
  base="$(basename "$f" .zip)"
  if [[ "$base" =~ ^(SVC-PC-[0-9]+-[0-9]+-[0-9]+) ]]; then
    add_task "${BASH_REMATCH[1]}"
  fi
done

# (3) everything else in the corpus, in directory order.
for d in "$CORPUS"/SVC-PC-*; do
  [ -d "$d" ] || continue
  add_task "$(basename "$d")"
done

# solver_batch_list.sh: keep only the tasks named in $SOLVER_ONLY_LIST
if [ -n "${SOLVER_ONLY_LIST:-}" ]; then
  declare -a QUEUE2=()
  for t in "${QUEUE[@]}"; do
    if grep -qx "$t" "$SOLVER_ONLY_LIST"; then QUEUE2+=("$t"); fi
  done
  QUEUE=("${QUEUE2[@]}")
fi

# Expand to (task, n) jobs, n in 1 2.
declare -a JOBS=()
for t in "${QUEUE[@]}"; do
  JOBS+=("$t:1" "$t:2")
done

echo "== solver_batch.sh queue plan ==" >&2
echo "tasks queued: ${#QUEUE[@]}  (jobs: ${#JOBS[@]}, n=1,2 each)" >&2
echo "order: (1) batch-1 returns, (2) tasks with an out/*/ zip, (3) remaining corpus tasks" >&2
i=0
for t in "${QUEUE[@]}"; do
  i=$((i + 1))
  echo "  $i. $t" >&2
done

if [ "$GO" -ne 1 ]; then
  echo "== dry-run: pass --go to execute; no runs launched, nothing touched ==" >&2
  exit 0
fi

# --- Guardrail: refuse to run without a GLM proxy token, even with --go. ---
if [ ! -f "$GLM_ENV" ]; then
  echo "waiting for /root/.glm_env, prep only (refusing --go)" >&2
  exit 3
fi

# shellcheck disable=SC1090
source "$GLM_ENV"

# Key rotation (16:40Z): /root/.glm_keys = one token per line (chmod 600). Job i uses key i mod N.
# Absent that file, the single ANTHROPIC_AUTH_TOKEN from .glm_env is used. Keys are never echoed.
KEYS=()
if [ -s /root/.glm_keys ]; then
  while IFS= read -r k; do k=$(echo "$k" | tr -d '\r[:space:]'); [ -n "$k" ] && [ "${k:0:1}" != "#" ] && KEYS+=("$k"); done < /root/.glm_keys
fi
[ "${#KEYS[@]}" -eq 0 ] && [ -n "${ANTHROPIC_AUTH_TOKEN:-}" ] && KEYS+=("$ANTHROPIC_AUTH_TOKEN")
[ "${#KEYS[@]}" -gt 0 ] && ANTHROPIC_AUTH_TOKEN="${KEYS[0]}"
if [ -z "${ANTHROPIC_AUTH_TOKEN:-}" ]; then
  echo "ERROR: $GLM_ENV did not export ANTHROPIC_AUTH_TOKEN" >&2
  exit 3
fi

mkdir -p "$RUNS_ROOT"
touch "$BATCH_LOG"

log_batch() {
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >>"$BATCH_LOG"
}

# ---------------------------------------------------------------------------
# Idempotency: skip a run whose app dir already has deliverables (i.e. the
# solver wrote files beyond the initial_workspace + instruction.md copy) AND
# whose instruction.sha256 matches the current instruction.md.
# ---------------------------------------------------------------------------
is_already_done() {
  local task="$1" n="$2"
  local run_dir="$RUNS_ROOT/$task/glm-$n"
  local app_dir="$run_dir/app"
  local sha_file="$run_dir/instruction.sha256"
  local task_dir="$CORPUS/$task"
  local instr="$task_dir/instruction.md"
  local iw="$task_dir/environment/initial_workspace"

  [ -d "$app_dir" ] || return 1
  [ -f "$sha_file" ] || return 1
  # 2026-09-18 14:52Z fix: a run killed mid-flight leaves app/ populated but no
  # exit code; without this line it was skipped as complete on restart.
  [ -f "$run_dir/claude_exit_code.txt" ] || return 1
  [ -f "$instr" ] || return 1

  local cur_sha prev_sha
  cur_sha="$(sha256sum "$instr" | cut -d' ' -f1)"
  prev_sha="$(cat "$sha_file" 2>/dev/null || echo "")"
  [ "$cur_sha" = "$prev_sha" ] || return 1

  local iw_count app_count
  iw_count=$(find "$iw" -type f 2>/dev/null | wc -l)
  app_count=$(find "$app_dir" -type f 2>/dev/null | wc -l)
  # baseline = copied initial_workspace files + the copied instruction.md
  if [ "$app_count" -gt "$((iw_count + 1))" ]; then
    return 0
  fi
  return 1
}

# ---------------------------------------------------------------------------
# One job: copy environment/initial_workspace + instruction.md into a clean
# app dir, record instruction.sha256, run the GLM solver. No grading here.
# ---------------------------------------------------------------------------
run_job() {
  local task="$1" n="$2"
  local task_dir="$CORPUS/$task"
  local iw="$task_dir/environment/initial_workspace"
  local instr_src="$task_dir/instruction.md"
  local run_dir="$RUNS_ROOT/$task/glm-$n"
  local app="$run_dir/app"
  local run_log="$run_dir/run.log"
  local sha_file="$run_dir/instruction.sha256"

  log_batch "START $task glm-$n key=$(( ${3:-0} % ${#KEYS[@]} + 1 ))/${#KEYS[@]}"

  rm -rf "$run_dir"
  mkdir -p "$app"
  if [ -n "$(ls -A "$iw" 2>/dev/null)" ]; then
    cp -a "$iw"/. "$app"/
  fi
  cp -a "$instr_src" "$app/instruction.md"

  if [ -e "$app/tests" ] || [ -e "$app/solution" ]; then
    {
      echo "ERROR: tests/ or solution/ leaked into $app - aborting job"
    } >>"$run_log"
    echo "1" >"$run_dir/claude_exit_code.txt"
    log_batch "FINISH $task glm-$n exit=1 (leak-guard)"
    return 1
  fi

  sha256sum "$instr_src" | cut -d' ' -f1 >"$sha_file"

  set +e
  (
    cd "$app" && \
    timeout "$RUN_TIMEOUT_SECS" env IS_SANDBOX=1 CLAUDE_CODE_MAX_OUTPUT_TOKENS=64000 ANTHROPIC_BASE_URL="$GLM_BASE_URL" ANTHROPIC_AUTH_TOKEN="${KEYS[$(( ${3:-0} % ${#KEYS[@]} ))]}" \
      claude -p "$(cat "$app/instruction.md")" \
      --model "$GLM_MODEL" \
      --dangerously-skip-permissions
  ) >"$run_log" 2>&1
  local exit_code=$?
  set -e

  echo "$exit_code" >"$run_dir/claude_exit_code.txt"
  log_batch "FINISH $task glm-$n exit=$exit_code"
  return "$exit_code"
}

# ---------------------------------------------------------------------------
# Scheduler: concurrency ramp 20 -> 40 (raised 15:07Z: 32 cores, 114 GB free, real 429s now detected); halve on any 429/5xx seen in a
# just-finished job's run.log (floor 1).
# ---------------------------------------------------------------------------
check_backoff() {
  local log="$1"
  [ -f "$log" ] || return 1
  # 2026-09-18 14:50Z fix: the old pattern matched any 429/5xx digit run, including
  # dollar figures in the solver's own output ("$571,438", "6,504 units"), and
  # throttled the batch to limit=1 on clean runs. Match HTTP error signals only.
  grep -Eiq 'rate.?limit|too many requests|overloaded|api error:? *(429|5[0-9]{2})|status(_code)?[=: ]+(429|5[0-9]{2})|"type": *"(api|overloaded|rate_limit)_error"|HTTP/[0-9.]+ (429|5[0-9]{2})' "$log" 2>/dev/null
}

LIMIT="${SOLVER_LIMIT:-8}"
running=0
completed_at_current_limit=0
declare -A PID_TASK
declare -A PID_N

bump_limit_if_clean() {
  [ "${SOLVER_RAMP:-0}" = 1 ] || return 0
  local new_limit
  if [ "$LIMIT" -lt 40 ]; then
    new_limit=40
  elif [ "$LIMIT" -lt 80 ]; then
    new_limit=80
  else
    new_limit=80
  fi
  if [ "$new_limit" -ne "$LIMIT" ]; then
    LIMIT=$new_limit
    log_batch "RAMP-UP limit=$LIMIT"
  fi
}

backoff() {
  local new_limit=$(( LIMIT / 2 ))
  [ "$new_limit" -lt 1 ] && new_limit=1
  if [ "$new_limit" -ne "$LIMIT" ]; then
    LIMIT=$new_limit
    log_batch "BACKOFF limit=$LIMIT"
  fi
  completed_at_current_limit=0
}

reap_one() {
  local finished_pid
  wait -n -p finished_pid || true   # 16:00Z fix: a solver exit=1 killed the scheduler under set -e
  local t="${PID_TASK[$finished_pid]:-unknown}"
  local n="${PID_N[$finished_pid]:-?}"
  unset "PID_TASK[$finished_pid]"
  unset "PID_N[$finished_pid]"
  running=$((running - 1))

  local run_log="$RUNS_ROOT/$t/glm-$n/run.log"
  if check_backoff "$run_log"; then
    backoff
  else
    completed_at_current_limit=$((completed_at_current_limit + 1))
    if [ "$completed_at_current_limit" -ge "$LIMIT" ]; then
      completed_at_current_limit=0
      bump_limit_if_clean
    fi
  fi
}

log_batch "BATCH START total_jobs=${#JOBS[@]} initial_limit=$LIMIT"

for job in "${JOBS[@]}"; do
  task="${job%%:*}"
  n="${job##*:}"

  if is_already_done "$task" "$n"; then
    log_batch "SKIP $task glm-$n (idempotent: deliverables present, instruction unchanged)"
    continue
  fi

  while [ "$running" -ge "$LIMIT" ]; do
    reap_one
  done

  JOB_IDX=$(( ${JOB_IDX:-0} + 1 ))
  run_job "$task" "$n" "$JOB_IDX" &
  pid=$!
  PID_TASK[$pid]="$task"
  PID_N[$pid]="$n"
  running=$((running + 1))
done

while [ "$running" -gt 0 ]; do
  reap_one
done

log_batch "BATCH DONE"
echo "== solver_batch.sh done, see $BATCH_LOG ==" >&2
