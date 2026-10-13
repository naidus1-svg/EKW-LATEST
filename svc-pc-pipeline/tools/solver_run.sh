#!/usr/bin/env bash
# solver_run.sh - GLM solver-run harness (PREP ONLY).
#
# Runs a single SVC-PC task through the GLM proxy as the solver agent, then
# grades the produced deliverable with judge_emulate.py. This is prep for the
# QC gate; the gate does NOT consume solver runs until Khiem approves.
#
# Routes through the GLM proxy via /root/.glm_env (ANTHROPIC_AUTH_TOKEN is a
# GLM proxy token, NOT an Anthropic API key). This script never sources or
# hardcodes an sk-ant key.
#
# Usage: solver_run.sh <TASK> <N>
#   TASK  e.g. SVC-PC-54-2-0
#   N     run index, e.g. 1 (lets the same task be run multiple times)

set -euo pipefail

CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
GLM_ENV=/root/.glm_env
GLM_BASE_URL=http://34.41.10.8:4000
GLM_MODEL=glm-5.2
JUDGE_EMULATE=/root/qc/tools/judge_emulate.py
RUN_TIMEOUT_SECS=3600

usage() {
  echo "Usage: $(basename "$0") <TASK> <N>" >&2
  echo "  TASK  e.g. SVC-PC-54-2-0" >&2
  echo "  N     run index, e.g. 1" >&2
}

if [ "$#" -ne 2 ]; then
  usage
  exit 2
fi

TASK="$1"
N="$2"

# --- Guardrail: refuse to run without a GLM proxy token. This script is prep
# until /root/.glm_env exists; it must never fall back to any other credential. ---
if [ ! -f "$GLM_ENV" ]; then
  echo "waiting for /root/.glm_env, prep only" >&2
  exit 3
fi

# --- Validate TASK ---
case "$TASK" in
  SVC-PC-*) ;;
  *)
    echo "ERROR: TASK must start with SVC-PC- (got: $TASK)" >&2
    exit 2
    ;;
esac

TASK_DIR="$CORPUS/$TASK"
if [ ! -d "$TASK_DIR" ]; then
  echo "ERROR: task directory not found: $TASK_DIR" >&2
  exit 2
fi

INITIAL_WORKSPACE="$TASK_DIR/environment/initial_workspace"
INSTRUCTION_SRC="$TASK_DIR/instruction.md"

if [ ! -d "$INITIAL_WORKSPACE" ]; then
  echo "ERROR: missing initial_workspace: $INITIAL_WORKSPACE" >&2
  exit 2
fi
if [ ! -f "$INSTRUCTION_SRC" ]; then
  echo "ERROR: missing instruction.md: $INSTRUCTION_SRC" >&2
  exit 2
fi

# --- Scratch dirs (absolute paths only) ---
RUN_DIR="/root/qc/runs/$TASK/glm-$N"
APP="$RUN_DIR/app"
RUN_LOG="$RUN_DIR/run.log"
EXIT_CODE_FILE="$RUN_DIR/claude_exit_code.txt"
REWARD_OUT="$RUN_DIR/reward-details.json"

echo "== solver_run.sh: TASK=$TASK N=$N ==" >&2
echo "== run dir: $RUN_DIR ==" >&2

# Clean the scratch app dir first, then recreate it.
rm -rf "$RUN_DIR"
mkdir -p "$APP"

# --- Copy ONLY environment/initial_workspace/* and instruction.md into APP.
# tests/ and solution/ (rubric + golden) must never reach the solver. ---
if [ -n "$(ls -A "$INITIAL_WORKSPACE" 2>/dev/null)" ]; then
  cp -a "$INITIAL_WORKSPACE"/. "$APP"/
fi
cp -a "$INSTRUCTION_SRC" "$APP/instruction.md"

# Assert the rubric/golden never made it into APP.
if [ -e "$APP/tests" ] || [ -e "$APP/solution" ]; then
  echo "ERROR: tests/ or solution/ leaked into $APP - aborting" >&2
  exit 1
fi

# --- Run Claude Code as the agent harness, pointed at the GLM proxy. ---
# shellcheck disable=SC1090
source "$GLM_ENV"

if [ -z "${ANTHROPIC_AUTH_TOKEN:-}" ]; then
  echo "ERROR: $GLM_ENV did not export ANTHROPIC_AUTH_TOKEN" >&2
  exit 3
fi

echo "== launching solver (claude via GLM proxy, model=$GLM_MODEL, timeout=${RUN_TIMEOUT_SECS}s) ==" >&2

set +e
(
  cd "$APP" && \
  timeout "$RUN_TIMEOUT_SECS" env IS_SANDBOX=1 ANTHROPIC_BASE_URL="$GLM_BASE_URL" \
    claude -p "$(cat "$APP/instruction.md")" \
    --model "$GLM_MODEL" \
    --dangerously-skip-permissions
) >"$RUN_LOG" 2>&1
CLAUDE_EXIT=$?
set -e

echo "$CLAUDE_EXIT" >"$EXIT_CODE_FILE"
echo "== solver exit code: $CLAUDE_EXIT (log: $RUN_LOG) ==" >&2

# --- Grade the produced APP dir against the task's rubric. ---
echo "== grading with judge_emulate.py ==" >&2
python3 "$JUDGE_EMULATE" deliverable "$TASK" "$APP" \
  --corpus-root "$CORPUS" \
  --out "$REWARD_OUT" >"$RUN_DIR/judge_emulate.log" 2>&1 || {
    echo "ERROR: judge_emulate.py failed, see $RUN_DIR/judge_emulate.log" >&2
    exit 1
  }

echo "== reward summary for $TASK (glm-$N) ==" >&2
python3 - "$REWARD_OUT" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path) as f:
    data = json.load(f)

print(f"task: {data.get('task')}")
print(f"mode: {data.get('mode')}")
print(f"total_reward: {data.get('total_reward')}")

def walk(group, prefix=""):
    name = group.get("name", "?")
    score = group.get("score")
    print(f"{prefix}group: {name}  score={score}  aggregation={group.get('aggregation')}")
    for c in group.get("criteria", []):
        mark = "PASS" if c.get("passed") else "FAIL"
        print(
            f"{prefix}  [{mark}] {c.get('id')} (weight={c.get('weight')}, "
            f"value={c.get('value')}) {c.get('name')}"
        )
        if c.get("error"):
            print(f"{prefix}    error: {c.get('error')}")
    for child in group.get("children", []):
        walk(child, prefix + "  ")

for g in data.get("groups", []):
    walk(g)

warnings = data.get("warnings") or []
if warnings:
    print("warnings:")
    for w in warnings:
        print(f"  - {w}")
PY

echo "== done: $TASK glm-$N  claude_exit=$CLAUDE_EXIT  reward_details=$REWARD_OUT ==" >&2

exit "$CLAUDE_EXIT"
