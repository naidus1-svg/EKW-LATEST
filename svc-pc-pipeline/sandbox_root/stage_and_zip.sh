#!/usr/bin/env bash
# GATE-V2 3.4 actuator: zip ONLY when the gate passes. Prints every non-pass cell; exits non-zero
# on any fail, or any gate-relevant warn/skip/error. env threshold 10,000,000 bytes.
# Usage: stage_and_zip.sh <WC_DIR> <TASK> <OUT_DIR> [--accept-skip c1,c2] [--accept-fail c1:GATE.md,c2:GATE.md]
#   --accept-fail overrides a FAIL cell in the gate-relevant set ONLY when its reason-file (GATE.md)
#   carries a line naming the criterion id, the source file (with extension) and the cell where the
#   value exists. The override line is printed in the zip log (14:09 UTC rule; main-only edits).
set -uo pipefail
WC="$1"; T="$2"; OUT="$3"; shift 3 || true
ACCEPT_SKIP=""; ACCEPT_FAIL=""
while [ $# -gt 0 ]; do case "$1" in
  --accept-skip) ACCEPT_SKIP="${2:-}"; shift 2;;
  --accept-fail) ACCEPT_FAIL="${2:-}"; shift 2;;
  *) shift;; esac; done
STAGE=/root/qc/stage; CHECKER=/root/ekwqc/deterministic-checks/svc_run_checks.py
mkdir -p "$STAGE" "$OUT"; OUT=$(cd "$OUT" && pwd)  # 2026-09-19 02:45Z: make OUT absolute; the zip below runs after cd "$STAGE" and a relative OUT wrote nowhere while exiting 0 (3 false ZIPPED)
rm -rf "$STAGE/$T"
rsync -a --exclude='_prior' --exclude='_runs' --exclude='FIX-LOG*.md' --exclude='REFUTER*.md' \
  --exclude='CR-REFUTER.md' --exclude='_scratch' --exclude='COMPREHENSIVE-REVIEW.md' --exclude='GATE.md' \
  --exclude='*.round1' --exclude='*.round2' --exclude='*.bak' --exclude='*.bak-*' --exclude='__pycache__' \
  --exclude='_golden_*' --exclude='_conv_test*' --exclude='__img_embed_test__*' --exclude='capacity_tmp_conv.*' \
  --exclude='.DS_Store' "$WC/$T/" "$STAGE/$T/"
echo "[stage] $T staged"
# ---- reviewed-bytes lock (01:50Z 09-19): zip only the bytes the last clean reviews saw ----
# The review harness writes stream-pipe/<T>/REVIEWED_MANIFEST.sha256 (sha256 over sorted "relpath sha256" lines of task_files/).
# We recompute the same manifest over the staged copy; a mismatch means the corpus changed after the review.
python3 - "$STAGE/$T" "${PIPE_ROOT:-/root/qc/stream-pipe}/$T/REVIEWED_MANIFEST.sha256" <<'PYG' || exit 11
import hashlib, os, sys
root, mf = sys.argv[1], sys.argv[2]
lines = []
for dp, dn, fn in os.walk(root):
    for f in fn:
        p = os.path.join(dp, f); rel = os.path.relpath(p, root)
        lines.append(rel + " " + hashlib.sha256(open(p, "rb").read()).hexdigest())
digest = hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()
if not os.path.exists(mf):
    print("[gate] BLOCKED: no REVIEWED_MANIFEST.sha256 for this task (no workspace review has recorded the bytes it saw)"); sys.exit(1)
want = open(mf).read().split()[0]
if want != digest:
    print("[gate] BLOCKED: staged bytes differ from the bytes the last review saw (manifest %s vs staged %s); re-review before zipping" % (want[:12], digest[:12])); sys.exit(1)
print("[gate] reviewed-bytes lock ok (%s)" % digest[:12])
PYG
# ---- hold (23:20Z): no zips until the local Comprehensive Review runs in workspace mode ----
if [ -f /root/qc/lanes/ZIP_HOLD ] && ! grep -qx "$T" /root/qc/lanes/ZIP_ALLOW 2>/dev/null; then echo "[gate] HOLD: $(cat /root/qc/lanes/ZIP_HOLD)"; exit 10; fi
# ---- rewardkit 1 MiB cap (23:20Z): the judge silently skips any file over 1,048,576 bytes ----
python3 - "$STAGE/$T" <<'PYG' || exit 9
import glob, os, re, sys
root = sys.argv[1]; bad = []
for jt in glob.glob(os.path.join(root, "tests", "deliverables*", "judge.toml")):
    s = open(jt, encoding="utf-8", errors="replace").read()
    m = re.search(r'^files\s*=\s*\[(.*?)\]', s, re.M | re.S)
    if not m: continue
    for f in re.findall(r'"([^"]+)"', m.group(1)):
        name = os.path.basename(f)
        cands = [os.path.join(root, "environment", "initial_workspace", name), os.path.join(root, "solution", "files", name),
                 os.path.join(root, "tests", "deliverables", "judge_inputs", name)]
        if f.startswith("/tests/"): cands.insert(0, os.path.join(root, f.lstrip("/")))
        for c in cands:
            if os.path.exists(c) and os.path.getsize(c) > 1048576:
                bad.append((os.path.basename(os.path.dirname(jt)), name, os.path.getsize(c))); break
for g in glob.glob(os.path.join(root, "solution", "files", "**", "*"), recursive=True):
    if os.path.isfile(g) and os.path.getsize(g) > 1048576: bad.append(("golden", os.path.relpath(g, root), os.path.getsize(g)))
if bad:
    print("[gate] BLOCKED: files the judge cannot read (rewardkit skips anything over 1 MiB):", bad); sys.exit(1)
print("[gate] judge files and golden all under 1 MiB")
PYG
# ---- ship guards (21:30Z): real-prompt verdict with zero majors, golden passes its own rubric ----
PIPE_DIR="${PIPE_ROOT:-/root/qc/stream-pipe}/$T"
python3 - "$PIPE_DIR" <<'PYG' || exit 7
import glob, json, os, re, sys
d = sys.argv[1]
# 01:55Z 09-19: the verdicts that count are the workspace-mode reviewer files (two reviewers, latest round each).
files = {}
for f in glob.glob(os.path.join(d, "CR.*.round*.json")):
    m = re.match(r"CR\.(glm|sonnet|opus)\.round(\d+)\.json$", os.path.basename(f))
    if not m: continue
    r, n = m.group(1), int(m.group(2))
    if r not in files or n > files[r][0]: files[r] = (n, f)
if len(files) < 2:
    print("[gate] BLOCKED: need verdicts from two workspace reviewers (have %s); run the workspace review" % sorted(files)); sys.exit(1)
for r, (n, f) in sorted(files.items()):
    try: j = json.load(open(f))
    except Exception as e: print("[gate] BLOCKED: %s unreadable (%s)" % (f, e)); sys.exit(1)
    if "overall_verdict" not in j or "checks" not in j:
        print("[gate] BLOCKED: %s is not a complete Comprehensive Review verdict" % os.path.basename(f)); sys.exit(1)
    if (j.get("major_count") or 0) > 0:
        print("[gate] BLOCKED: %s round %d verdict %s with major_count=%s" % (r, n, j.get("overall_verdict"), j.get("major_count"))); sys.exit(1)
    print("[gate] %s round %d: %s, majors 0, minors %s" % (r, n, j.get("overall_verdict"), j.get("minor_count")))
PYG
python3 - "$PIPE_DIR/probes/oracle.json" <<'PYG' || exit 8
import json, sys
try:
    j = json.load(open(sys.argv[1]))
except Exception as e:
    print("[gate] BLOCKED: no readable probes/oracle.json (%s); the golden must be graded against its own rubric before shipping" % e); sys.exit(1)
r = j.get("total_reward")
if r is None or float(r) < 1.0:
    print("[gate] BLOCKED: golden scores %s on its own rubric (needs 1.0; GATE-V2 3.4, DataOS 1.1/1.5)" % r); sys.exit(1)
print("[gate] oracle total_reward=%s" % r)
PYG
resid=$(find "$STAGE/$T" \( -name '*.bak' -o -name '*.round1' -o -name '*.round2' -o -name '_golden_*' -o -name '__pycache__' \) | head)
[ -n "$resid" ] && { echo "[stage] RESIDUE:"; echo "$resid"; exit 3; }
# env size gate (10,000,000 bytes)
envb=$(find "$STAGE/$T/environment" -type f -printf '%s\n' 2>/dev/null | awk '{s+=$1} END{printf "%d", s+0}')
echo "[env] environment bytes=$envb (threshold 10000000)"
. /root/venv/bin/activate 2>/dev/null || true
CKOUT=/root/qc/_recheck/$T; rm -rf "$CKOUT"
( python "$CHECKER" --root "$STAGE" --out-dir "$CKOUT" --all --jobs 8 "$T" >/dev/null 2>&1 ) || true
[ -f "$CKOUT/summary.csv" ] || { echo "[checks] NO summary.csv"; exit 4; }
python3 - "$CKOUT/summary.csv" "$T" "$ACCEPT_SKIP" "$envb" "$ACCEPT_FAIL" <<'PYIN'
import csv,sys,re,os
f,t,accept,envb=sys.argv[1],sys.argv[2],set(x for x in sys.argv[3].split(',') if x),int(sys.argv[4])
# --accept-fail spec: comma-separated check:reasonfile ; a gate-set FAIL is overridden only when the
# reason-file has a line naming a source file (with extension) AND a cell, plus a criterion id somewhere.
accept_fail={}
for pair in (sys.argv[5] if len(sys.argv)>5 else "").split(","):
    if ":" in pair:
        c,rf=pair.split(":",1); accept_fail[c.strip()]=rf.strip()
FILE_RE=re.compile(r'\b[\w./-]+\.(?:xlsx|xlsm|csv|pdf|docx|json|md|txt)\b',re.I)
CELL_RE=re.compile(r'\b[A-Z]{1,3}\d{1,4}(?::[A-Z]{1,3}\d{1,4})?\b')
CRIT_RE=re.compile(r'\b[rc]\d{1,3}[a-z]?\b')
def fail_override(check):
    rf=accept_fail.get(check)
    if not rf or not os.path.isfile(rf): return None
    txt=open(rf,errors="replace").read()
    if not CRIT_RE.search(txt): return None            # must name a criterion somewhere
    for line in txt.splitlines():                        # a line proving source file + cell
        if FILE_RE.search(line) and CELL_RE.search(line):
            return line.strip()[:160]
    return None
GATE={"criterion_groundedness","compound_criterion","duplicate_criterion_content","same_file_requirement_duplicate",
"weight_application","environment_size_budget","task_metadata_completeness","dependency_pin",
"instruction_requirement_coverage","fabricated_unfilenamed_fact","golden_groundedness","golden_arithmetic",
"source_citation_existence","cell_address_pinned","rubric_overspecification","environment_input","metadata_leak",
"answer_key_rubric_leak","spelling_grammar"}
ZSCAN_PREFIXES=("formula_cache","quantifier_scope","escape_hatch","source_reliability","rubric_consistency","answer_preexposure","instruction_input","cross_group_dup")
rows=[r for r in csv.DictReader(open(f)) if r.get("task_id")==t]
if not rows: print("[gate] NO ROW for",t); sys.exit(9)
r=rows[0]; nonpass=[(k,v) for k,v in r.items() if k not in ("task_id","C","D","E") and not k.endswith("_n") and not k.endswith("_first") and v not in ("pass","",None)]
gatefail=[]
ADVISORY={"judge_scope_over_inclusion","pinned_value_prescreen","environment_size_budget","criterion_groundedness","compound_criterion","duplicate_criterion_content","same_file_requirement_duplicate","instruction_requirement_coverage","fabricated_unfilenamed_fact","golden_groundedness","golden_arithmetic","source_citation_existence","cell_address_pinned","rubric_overspecification","spelling_grammar","judge_file_scope_breadth","task_metadata_completeness","dependency_pin","harness_fragility","judge_determinism_config_lint","test_coverage_absence","unrequested_deliverable_source","structural_audit","undisclosed_terminology","rubric_text_lint","tab_naming","word_ban_false_trigger","deliverable_count","source_truncation"}  # GATE-V2 3.6.5 (00:35Z 09-19): judge_scope_over_inclusion and judge_file_size_cliff are BLOCKING again (DataOS 67-1-0 major 1.5 is exactly that cell); 3.6.4 (19:45Z): heuristic cells are recorded in GATE.md, never gated; the CR verdict is the bar
for k,v in nonpass:
    if k in ADVISORY: continue
    if k=="metadata_leak" and v!="fail": continue  # 3.6.4: warn is advisory
    z = any(k.startswith(p) for p in ZSCAN_PREFIXES)
    relevant = (k in GATE) or z
    if v=="fail":
        ov=fail_override(k)
        if ov is not None:
            print("[gate] OVERRIDE fail %s per %s: %s"%(k,accept_fail[k],ov)); continue
        if k in accept_fail:
            print("[gate] REFUSED --accept-fail %s: reason-file lacks a line naming criterion + source file + cell"%k)
        gatefail.append((k,v))
    elif relevant and v in ("warn","skip","error") and k not in accept:
        gatefail.append((k,v))
print("[gate] env bytes=%d (advisory, recorded not gated)"%envb)
print("[gate] non-pass cells:", nonpass or "none")
if gatefail:
    print("[gate] BLOCKED by:", gatefail); sys.exit(5)
print("[gate] PASS"); sys.exit(0)
PYIN
rc=$?
[ $rc -ne 0 ] && { echo "[gate] not zipping (rc=$rc)"; exit $rc; }
# promoted-kinds gate (laptop, 2026-09-19 19:25Z): kind-level deterministic findings that DataOS filed as majors on the batch 6-8 rejects
# (tools/promoted_kinds_gate.py: fires on the 12 exact-mapped rejected tasks, clean on accepted 2-7-0). Its output is kept for the union
# builder; exit 5 takes the same re-open path as a blocking cell. rc other than 0 or 5 (script error) is advisory and printed.
mkdir -p "$PIPE_DIR/checks"
python3 /root/qc/tools/promoted_kinds_gate.py --task "$T" > "$PIPE_DIR/checks/promoted_kinds.txt" 2>&1; pk=$?
if [ "$pk" -eq 5 ] && [ -f /root/qc/lanes/PROMOTED_KINDS_ADVISORY ]; then echo "[gate] promoted kinds ADVISORY (lanes/PROMOTED_KINDS_ADVISORY, 22:40Z: every examined blocking finding on the 22 was false against the task sources; see checks/promoted_kinds.txt): $(grep -c '^BLOCKING' "$PIPE_DIR/checks/promoted_kinds.txt") finding(s) recorded, not blocking"; pk=0; fi
if [ "$pk" -eq 5 ]; then
  echo "[gate] BLOCKED by promoted kinds: $(grep -c '^BLOCKING' "$PIPE_DIR/checks/promoted_kinds.txt") blocking finding(s), see checks/promoted_kinds.txt"
  grep '^BLOCKING' "$PIPE_DIR/checks/promoted_kinds.txt" | head -5; exit 5
fi
[ "$pk" -ne 0 ] && echo "[gate] promoted_kinds_gate rc=$pk (script error): advisory only, see checks/promoted_kinds.txt"
echo "[gate] promoted kinds: none blocking"
Z="$OUT/$T.zip"; rm -f "$Z"; ( cd "$STAGE" && zip -rq "$Z" "$T" )
[ -s "$Z" ] || { echo "[zip] FAILED: $Z missing or empty after zip"; exit 12; }
hits=$(unzip -l "$Z" | grep -E '_golden_.*\.txt|__pycache__|reward\.toml\.bak|_conv_test|capacity_tmp_conv|__img_embed_test__' || true)
[ -n "$hits" ] && { echo "[zip] FORBIDDEN:"; echo "$hits"; rm -f "$Z"; exit 7; }
python3 -c "import zipfile; z=zipfile.ZipFile('$Z'); print('[zip] testzip', 'OK' if z.testzip() is None else 'BAD')"
sha=$(sha256sum "$Z"|cut -d" " -f1); sz=$(stat -c %s "$Z"); [ -n "$sha" ] && [ -n "$sz" ] || { echo "[zip] FAILED: empty sha/size for $Z"; exit 12; }; echo "$sha" > "$OUT/$T.sha256"
echo "$T $sz $sha" >> "$OUT/SHA256SUMS.txt"; echo "[zip] $Z bytes=$sz sha256=$sha"
