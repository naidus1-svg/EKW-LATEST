#!/usr/bin/env bash
# adjudicate_task.sh TASK - step A: grade both GLM solver runs against the CURRENT rubric, then adjudicate every criterion that BOTH runs failed.
#
# A criterion both compliant-looking runs fail is either a solver error or a false rejection (the criterion wants something the instruction never asked
# for). A false rejection is a major at any weight (DataOS 1.5; GATE-V2 3.1) and the old gate track found 347 of them across 45 tasks, then nothing in the
# new pipeline read the result. This script produces a FRESH stream-pipe/<T>/ADJUDICATE.json against the bytes as they stand; build_review_union.py turns a
# fresh false rejection into a fix finding and the zip bar can require a fresh one.
#
# Output files (all under stream-pipe/<T>/):
#   ADJUDICATE.json      {task, adjudications[], any_false_rejection, notes, _meta{...}}  (only ever written whole, after validation)
#   ADJUDICATE.status    one word: OK | NEED_SOLVE | NEED_RESOLVE | GRADE_TAINTED | ADJUDICATION_INCOMPLETE | ADJUDICATION_FAILED
# Exit: 0 done (OK), 10 not enough finished runs, 11 instruction changed after the runs (re-solve needed), 12 grading tainted by judge errors,
#       13 adjudication call failed or incomplete. Idempotent: an ADJUDICATE.json newer than every task file, the runs and the grading is kept unless --force.
#
# Usage: adjudicate_task.sh TASK [--force]      Env: ADJ_LANE (claude config dir for the judge and the adjudication call, default /root/.claude-q)
set -uo pipefail
cd /root/qc || exit 1
T="${1:?task}"; shift || true
case "$T" in SVC-PC-*) ;; *) T="SVC-PC-$T" ;; esac
FORCE=0; [ "${1:-}" = "--force" ] && FORCE=1
C=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
PIPE=/root/qc/stream-pipe/$T
RUNS=/root/qc/runs/$T
TOOLS=/root/qc/tools
LOG=/root/qc/_prompts/adjudicate.log
LANE="${ADJ_LANE:-/root/.claude-q}"
# shellcheck disable=SC1091
source /root/venv/bin/activate 2>/dev/null || true
log() { echo "$(date -u +%FT%TZ) $T $*" | tee -a "$LOG" >&2; }
status() { echo "$1" > "$PIPE/ADJUDICATE.status"; }
mkdir -p "$PIPE"
exec 9>"$PIPE/adjudicate.lock"
flock -n 9 || { log "SKIP another adjudication is running"; exit 0; }

mt() { stat -c %Y "$@" 2>/dev/null | sort -n | tail -n 1; }

# 1. two finished solver runs
for n in 1 2; do
  if [ "$(cat "$RUNS/glm-$n/claude_exit_code.txt" 2>/dev/null)" != "0" ] || [ ! -d "$RUNS/glm-$n/app" ]; then
    log "NEED_SOLVE glm-$n has no finished run"; status NEED_SOLVE; exit 10
  fi
done
# A run answers the prompt it was given. Each run keeps its own copy (app/instruction.md), so compare BYTES, not file times: file times flagged 39 tasks
# as instruction-stale where only 7 of the 48 ready ones really differ (an edit that touched tests/task_prompt.txt, or a rewrite with the same text).
for n in 1 2; do
  if ! cmp -s "$C/$T/instruction.md" "$RUNS/glm-$n/app/instruction.md"; then
    log "NEED_RESOLVE glm-$n received a different instruction.md than the one now in the corpus"; status NEED_RESOLVE; exit 11
  fi
done
rubric=$(mt "$C/$T"/tests/*/judge.toml "$C/$T/tests/reward.toml")
# the guard's own definition of "the newest file the zip would ship" (paths carry spaces, so this is not done with a shell glob)
newest_file=$(python3 -c "import sys; sys.path.insert(0, '/root/qc/tools'); import oracle_refresh as o; print(int(o.newest_staged('$T')[0]))" 2>/dev/null || echo 0)

# 2. keep a fresh adjudication
if [ "$FORCE" = 0 ] && [ -f "$PIPE/ADJUDICATE.json" ] && [ "$(cat "$PIPE/ADJUDICATE.status" 2>/dev/null)" = "OK" ]; then
  aj=$(stat -c %Y "$PIPE/ADJUDICATE.json")
  if [ "$aj" -ge "${newest_file:-0}" ] && [ "$aj" -ge "$(mt "$RUNS/glm-1/reward-details.json" "$RUNS/glm-2/reward-details.json")" ]; then
    log "KEEP adjudication is newer than every file and the grading"; exit 0
  fi
fi

# 3. grade against the current rubric (a grading older than the rubric, or missing, is redone)
graded_ok() {
  for n in 1 2; do
    rd="$RUNS/glm-$n/reward-details.json"
    [ -f "$rd" ] && [ "$(stat -c %Y "$rd")" -ge "${rubric:-0}" ] || return 1
  done
}
taint() {
  python3 - "$RUNS/glm-1/reward-details.json" "$RUNS/glm-2/reward-details.json" <<'PYEOF'
import json, sys
bad = 0
for p in sys.argv[1:]:
    try:
        d = json.load(open(p))
    except Exception:
        bad += 1
        continue
    def walk(g):
        global bad
        for c in g.get("criteria", []) or []:
            if c.get("error"):
                bad += 1
        for ch in g.get("children", []) or []:
            walk(ch)
    for g in d.get("groups", []):
        walk(g)
print(bad)
PYEOF
}
if ! graded_ok; then
  log "GRADE both runs against the current rubric (lane $(basename "$LANE"))"
  CLAUDE_CONFIG_DIR="$LANE" bash "$TOOLS/solver_grade.sh" "$T" >> "$LOG" 2>&1
fi
if ! graded_ok || [ "$(taint)" != "0" ]; then
  log "retry grading once (missing or judge errors: $(taint))"
  CLAUDE_CONFIG_DIR="$LANE" bash "$TOOLS/solver_grade.sh" "$T" >> "$LOG" 2>&1
fi
if ! graded_ok || [ "$(taint)" != "0" ]; then
  log "GRADE_TAINTED judge errors remain ($(taint)); not adjudicating on infrastructure failures"; status GRADE_TAINTED; exit 12
fi

# 4. package text at the current bytes, and the criteria both runs failed
python3 "$TOOLS/build_cr_context.py" "$T" --corpus-root "$C" --out "$PIPE/CONTEXT.txt" >> "$LOG" 2>&1
python3 "$TOOLS/gather_both_failed.py" --task "$T" --runs-root /root/qc/runs --out "$PIPE/BOTH_FAILED.txt" >> "$LOG" 2>&1 || { log "gather_both_failed failed"; status ADJUDICATION_FAILED; exit 13; }

BOTH=$(python3 - "$RUNS" <<'PYEOF'
import json, sys
def rows(p):
    d = json.load(open(p)); out = {}
    def walk(g):
        for c in g.get("criteria", []) or []:
            out[c.get("id") or c.get("name")] = bool(c.get("passed"))
        for ch in g.get("children", []) or []:
            walk(ch)
    for g in d.get("groups", []):
        walk(g)
    return out
a, b = rows(sys.argv[1] + "/glm-1/reward-details.json"), rows(sys.argv[1] + "/glm-2/reward-details.json")
print(" ".join(sorted(k for k in a if k in b and not a[k] and not b[k])))
PYEOF
)

write_result() { # $1 = json file with the adjudication object (or "" for none)
  python3 - "$PIPE/ADJUDICATE.json" "$1" "$T" "$C" "$RUNS" "$BOTH" <<'PYEOF'
import hashlib, glob, json, os, sys, time
out, src, task, corpus, runs, both = sys.argv[1:7]
both = both.split()
d = json.load(open(src)) if src else {"task": task, "adjudications": [], "any_false_rejection": False, "notes": "no criterion failed both runs"}
adjs = [a for a in d.get("adjudications", []) if isinstance(a, dict)]
d["adjudications"] = adjs
d["any_false_rejection"] = any(a.get("verdict") == "false_rejection" for a in adjs)
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
d["_meta"] = {
    "adjudicated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "instruction_sha": sha(f"{corpus}/{task}/instruction.md"),
    "rubric_sha": {os.path.basename(os.path.dirname(p)): sha(p) for p in sorted(glob.glob(f"{corpus}/{task}/tests/*/judge.toml"))},
    "runs_graded": {n: os.path.getmtime(f"{runs}/glm-{n}/reward-details.json") for n in (1, 2)},
    "both_failed": both,
}
tmp = out + ".tmp"
json.dump(d, open(tmp, "w"), indent=2)
if os.path.exists(out):  # keep the earlier judgment (the old gate track's, or an earlier run's); the union builder reads only ADJUDICATE.json
    os.replace(out, out[:-5] + ".prev.%d.json" % int(os.path.getmtime(out)))
os.replace(tmp, out)
print(len(adjs), "adjudications,", "any_false_rejection=" + str(d["any_false_rejection"]))
PYEOF
}

if [ -z "$BOTH" ]; then
  write_result "" >> "$LOG" 2>&1
  status OK; log "OK no criterion failed both runs"; exit 0
fi

log "ADJUDICATE $(echo $BOTH | wc -w) both-failed criteria: $BOTH"
python3 "$TOOLS/render_prompt.py" "${ADJ_PROMPT:-$TOOLS/prompts/adjudicate.md}" --set-lit TASK_ID="$T" --set PACKAGE_TEXT="$PIPE/CONTEXT.txt" \
  --set BOTH_FAILED_TEXT="$PIPE/BOTH_FAILED.txt" --out "$PIPE/prompt_adjudicate.txt" >> "$LOG" 2>&1 || { log "render failed"; status ADJUDICATION_FAILED; exit 13; }

complete() { # does the adjudication cover exactly the both-failed set?
  python3 - "$1" "$BOTH" <<'PYEOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("no"); sys.exit()
got = {str(a.get("criterion_id")) for a in d.get("adjudications", []) if isinstance(a, dict) and a.get("verdict") in ("solver_error", "false_rejection")}
print("yes" if got == set(sys.argv[2].split()) else "no")
PYEOF
}

for attempt in 1 2; do
  rm -f "$PIPE/ADJUDICATE.new.json"
  CLAUDE_CONFIG_DIR="$LANE" python3 "$TOOLS/llm_call.py" --prompt-file "$PIPE/prompt_adjudicate.txt" --model opus --timeout 1500 \
    --out "$PIPE/ADJUDICATE.new.json" >> "$LOG" 2>&1
  if [ -f "$PIPE/ADJUDICATE.new.json" ] && [ "$(complete "$PIPE/ADJUDICATE.new.json")" = "yes" ]; then
    write_result "$PIPE/ADJUDICATE.new.json" >> "$LOG" 2>&1
    status OK
    log "OK $(python3 -c "import json; d=json.load(open('$PIPE/ADJUDICATE.json')); print(sum(1 for a in d['adjudications'] if a.get('verdict')=='false_rejection'), 'false rejection(s) of', len(d['adjudications']))")"
    exit 0
  fi
  log "attempt $attempt: adjudication missing or does not cover exactly the both-failed set ($BOTH)"
done
status ADJUDICATION_INCOMPLETE
exit 13
