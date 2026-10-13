#!/usr/bin/env bash
# solver_grade.sh - grade a task's solver runs (glm-1, glm-2).
#
# This is the per-task grading step, run at the gate - separate from
# solver_batch.sh, which only solves and never grades.
#
# Deliberately does NOT pass --model to judge_emulate.py: judge_emulate.py
# defaults the judge to the rubric's own [judge] value (DataOS's actual
# judge), so this script must inherit that default rather than force one.
#
# Usage: solver_grade.sh <TASK>

set -euo pipefail

CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
JUDGE_EMULATE=/root/qc/tools/judge_emulate.py
RUNS_ROOT=/root/qc/runs

usage() {
  echo "Usage: $(basename "$0") <TASK>" >&2
  echo "  TASK  e.g. SVC-PC-54-2-0" >&2
}

if [ "$#" -ne 1 ]; then
  usage
  exit 2
fi

TASK="$1"

case "$TASK" in
  SVC-PC-*) ;;
  *)
    echo "ERROR: TASK must start with SVC-PC- (got: $TASK)" >&2
    exit 2
    ;;
esac

if [ ! -d "$CORPUS/$TASK" ]; then
  echo "ERROR: task directory not found: $CORPUS/$TASK" >&2
  exit 2
fi

overall_status=0

for n in 1 2; do
  RUN_DIR="$RUNS_ROOT/$TASK/glm-$n"
  APP="$RUN_DIR/app"
  REWARD_OUT="$RUN_DIR/reward-details.json"

  if [ ! -d "$APP" ]; then
    echo "== $TASK glm-$n: no app dir at $APP, skipping (not solved yet) ==" >&2
    overall_status=1
    continue
  fi

  echo "== grading $TASK glm-$n ==" >&2
  # NOTE: no --model here on purpose - judge_emulate.py's own default is the
  # rubric's [judge] value (DataOS's actual judge), and this script must not
  # override it.
  if ! python3 "$JUDGE_EMULATE" deliverable "$TASK" "$APP" \
        --corpus-root "$CORPUS" \
        --out "$REWARD_OUT" >"$RUN_DIR/judge_emulate.log" 2>&1; then
    echo "ERROR: judge_emulate.py failed for $TASK glm-$n, see $RUN_DIR/judge_emulate.log" >&2
    overall_status=1
    continue
  fi

  echo "== reward summary for $TASK glm-$n ==" >&2
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
done

exit "$overall_status"
