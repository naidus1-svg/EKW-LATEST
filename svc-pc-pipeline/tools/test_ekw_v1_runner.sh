#!/bin/bash
# Behaviour test for ekw_v1_lane_runner.sh + ekw_v1_claim.sh. Temp dirs only, no model calls: every tool the
# runner calls (ekw_intake.py, ekw_gate.py, judge_emulate.py, svc_prefilter.py, claude) is replaced by a stub whose
# result is set per case through S_* environment variables. Checks the exit-code contract and claim handling:
#   A intake finds a missing input          -> 20, parked.txt line, claim kept
#   B lane limit during the fix step        -> 10, claim released, transient.txt line
#   C same gate blocker repeats (normal)    -> 30, task in decide.txt, claim released
#   D same gate blocker repeats (decide)    -> 20, parked
#   E every gate green                      -> 0, ready zip + manifest, ready.txt line, claim kept
#   F oracle gives no reward on attempt 1   -> 10, claim released
#   G claim helper: atomic claim, skips claimed, 'left' count, exit 1 when empty
# Usage: bash test_ekw_v1_runner.sh /path/to/ekw_v1_lane_runner.sh /path/to/ekw_v1_claim.sh [python3]
set -u
R="${1:?runner path}"; C="${2:?claim helper path}"; PYX="${3:-$(command -v python3)}"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/tools"
printf '%s\n' \
'import json, os, sys' \
'me = os.path.basename(sys.argv[0]); a = sys.argv[1:]; E = os.environ' \
'def arg(flag):' \
'    return a[a.index(flag) + 1] if flag in a else None' \
'if me == "ekw_intake.py":' \
'    cmd, task = a[0], a[1]' \
'    if cmd == "normalize":' \
'        rc = int(E.get("S_NORMALIZE_RC", "0"))' \
'        if rc != 3: os.makedirs(os.path.join(E["EKW_ROOT"], "_raw", task), exist_ok=True)' \
'        print(json.dumps({"missing": ["expert_solution (no golden files)"] if rc == 3 else []})); sys.exit(rc)' \
'    if cmd == "check": sys.exit(int(E.get("S_CHECK_RC", "0")))' \
'    if cmd == "build": sys.exit(int(E.get("S_BUILD_RC", "0")))' \
'    if cmd == "package":' \
'        z = arg("--zip"); open(z, "w").write("zip"); open(z + ".manifest.json", "w").write("{}"); sys.exit(0)' \
'if me == "ekw_gate.py":' \
'    rc = int(E.get("S_GATE_RC", "0"))' \
'    d = {"verdict": "FAIL" if rc else "PASS", "advisory": [], "harness": [], "waived": [], "errors": [],' \
'         "blocking": [{"check": "rubric_schema", "verdict": "fail", "count": "1", "first": "x", "json": "j"}] if rc else []}' \
'    open(arg("--out"), "w").write(json.dumps(d)); sys.exit(rc)' \
'if me == "judge_emulate.py":' \
'    r = E.get("S_REWARD", "1.0")' \
'    if r != "none": open(arg("--out"), "w").write(json.dumps({"total_reward": float(r)}))' \
'    err = E.get("S_ORC_ERR", "")' \
'    if err: print("Traceback (most recent call last):"); print(err)' \
'    sys.exit(0)' \
'if me == "svc_prefilter.py": sys.exit(int(E.get("S_PREFILTER_RC", "0")))' \
> "$T/tools/stub.py"
for n in ekw_intake.py ekw_gate.py judge_emulate.py svc_prefilter.py; do cp "$T/tools/stub.py" "$T/tools/$n"; done
printf '#!/bin/bash\necho "${S_CLAUDE_OUT:-VERDICT: READY-TO-RESUBMIT}"\n' > "$T/claude"; chmod +x "$T/claude"
fail=0
run(){  # $1 case id, $2 task, then KEY=VAL env assignments for the stubs
  local id="$1" task="$2"; shift 2
  W="$T/w$id"; rm -rf "$W"; mkdir -p "$W/claims/$task"
  ( export EKW_WORK="$W" EKW_ROOT="$T/root$id" EKW_TOOLS="$T/tools" EKW_PY="$PYX" EKW_CLAUDE="$T/claude" \
           MAX_FIX_ATTEMPTS=4 STUCK_LIMIT=1 "$@"
    bash "$R" "$task" t ) >/dev/null 2>&1
}
ok(){ if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; fail=1; fi; }

run A TST-901 S_NORMALIZE_RC=3; rc=$?
ok "A missing input parks (rc=$rc)" '[ $rc = 20 ] && grep -q "^TST-901" "$W/parked.txt" && [ -d "$W/claims/TST-901" ]'

mkdir -p "$T/pre"; echo "VERDICT: NOT-READY v3 over-enforces" > "$T/pre/v.md"
W="$T/wB"; rm -rf "$W"; mkdir -p "$W/claims/TST-902" "$W/verify"; cp "$T/pre/v.md" "$W/verify/TST-902.verify.md"
( export EKW_WORK="$W" EKW_ROOT="$T/rootB" EKW_TOOLS="$T/tools" EKW_PY="$PYX" EKW_CLAUDE="$T/claude" \
         S_CLAUDE_OUT="You've hit your usage limit" MAX_FIX_ATTEMPTS=4; bash "$R" TST-902 t ) >/dev/null 2>&1; rc=$?
ok "B lane limit in fix step releases (rc=$rc)" '[ $rc = 10 ] && [ ! -d "$W/claims/TST-902" ] && grep -q "^TST-902" "$W/transient.txt"'

run C TST-903 S_GATE_RC=1; rc=$?
ok "C stuck blocker -> decide, released (rc=$rc)" '[ $rc = 30 ] && grep -qx TST-903 "$W/decide.txt" && [ ! -d "$W/claims/TST-903" ]'

W="$T/wD"; rm -rf "$W"; mkdir -p "$W/claims/TST-904"; echo TST-904 > "$W/decide.txt"
( export EKW_WORK="$W" EKW_ROOT="$T/rootD" EKW_TOOLS="$T/tools" EKW_PY="$PYX" EKW_CLAUDE="$T/claude" \
         S_GATE_RC=1 MAX_FIX_ATTEMPTS=6; bash "$R" TST-904 t ) >/dev/null 2>&1; rc=$?
ok "D stuck in decide mode parks (rc=$rc)" '[ $rc = 20 ] && grep -q "^TST-904" "$W/parked.txt"'

run E TST-905; rc=$?
ok "E all green -> ready (rc=$rc)" '[ $rc = 0 ] && [ -f "$W/ready/TST-905.zip" ] && [ -f "$W/ready/TST-905.zip.manifest.json" ] && grep -q "^TST-905" "$W/ready.txt" && [ -d "$W/claims/TST-905" ]'

run F TST-906 S_REWARD=none; rc=$?
ok "F no oracle reward on attempt 1 releases (rc=$rc)" '[ $rc = 10 ] && [ ! -d "$W/claims/TST-906" ]'

run H TST-907 S_REWARD=none "S_ORC_ERR=OSError: [Errno 28] No space left on device: '/tmp/x.json'"; rc=$?
ok "H disk-full oracle crash is infra: released, not parked (rc=$rc)" '[ $rc = 10 ] && [ ! -d "$W/claims/TST-907" ] && ! grep -q "^TST-907" "$W/parked.txt" 2>/dev/null'

run I TST-908 S_REWARD=none "S_ORC_ERR=AttributeError: x has no attribute y"; rc=$?
ok "I other oracle crash still parks as a tool bug (rc=$rc)" '[ $rc = 20 ] && grep -q "^TST-908" "$W/parked.txt"'

W="$T/wG"; mkdir -p "$W/claims/AAA-1"; printf 'AAA-1\r\nBBB-2\n# note\nCCC-3\n' > "$W/queue.txt"
left="$(EKW_WORK="$W" bash "$C" left)"; t1="$(EKW_WORK="$W" bash "$C")"; t2="$(EKW_WORK="$W" bash "$C")"
EKW_WORK="$W" bash "$C" >/dev/null; rc=$?
ok "G claim helper (left=$left, got $t1 then $t2, empty rc=$rc)" '[ "$left" = 2 ] && [ "$t1" = BBB-2 ] && [ "$t2" = CCC-3 ] && [ $rc = 1 ]'

[ "$fail" = 0 ] && echo "ALL PASS"; exit "$fail"
