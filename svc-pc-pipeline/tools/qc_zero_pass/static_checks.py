"""Run the mechanical failure-pattern checks over every staged task of a QC batch, before reviewers start.

Usage: python static_checks.py --batch b7

Runs two checks from deterministic-checks/ over <QC_REVIEW_DIR>/<batch>/work/ (the unzipped "with runs" packages):
  layout_formula_advisory_check.py  G1 sheet/cell pinned while the prompt allows free tab naming, H1 formula floor at
                                    or above the golden's own count, H2 formula gate on a prompt that does not ask for
                                    formulas, I1 xlsx + formula criteria with no recalculation step
  oracle_reward_details_audit.py    F2 oracle below 1.0 / grammar error, F3 traceback, rewardkit exit 1 or timeout in
                                    any run's verifier output
All are warnings (1 to 3 true positives each in the QC batch 1-6 analysis, qc_review/patterns/REPORT.md). A G1, H1, H2,
F2 or F3 warning goes to the task's reviewer as a lead to confirm; I1 alone is a fix note (add a recalc step), not a
fail. Writes <batch>/static_checks.json.
"""

import json
import os
import subprocess
import sys

args = sys.argv[1:]
if "--batch" not in args:
    sys.exit("usage: static_checks.py --batch bN")
BATCH = args[args.index("--batch") + 1]
BASE = os.environ.get("QC_REVIEW_DIR", os.path.expanduser("~/Documents/qc_review"))
WORK = os.path.join(BASE, BATCH, "work")
DC = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "..",
        "deterministic-checks",
    )
)
if not os.path.isdir(WORK):
    sys.exit(f"no {WORK}: unzip the batch first")

out = {}
CHECKS = (
    ("layout_formula", "layout_formula_advisory_check.py", []),
    ("oracle_runs", "oracle_reward_details_audit.py", ["--all"]),
)
for name, script, extra in CHECKS:
    dst = os.path.join(BASE, BATCH, f"static_{name}.json")
    p = subprocess.run(
        [
            sys.executable,
            os.path.join(DC, script),
            *extra,
            "--root",
            WORK,
            "--out",
            dst,
        ],
        capture_output=True,
        text=True,
    )
    print(f"== {script} (exit {p.returncode})")
    try:
        out[name] = json.load(open(dst, encoding="utf-8"))
    except (OSError, ValueError):
        out[name] = {"stdout": p.stdout[-4000:], "stderr": p.stderr[-2000:]}
        print("  could not read", dst, p.stderr[-500:])
        continue
    res = out[name].get("results")
    if res is None:  # layout_formula_advisory_check writes {"tasks": {id: {"status", "checks": {rule: {...}}}}}
        res = [{"task_id": k, "status": v.get("status"), "warn": [c for c, cv in (v.get("checks") or {}).items()
                if isinstance(cv, dict) and cv.get("status") in ("warn", "fail")]} for k, v in out[name].get("tasks", {}).items()]
    hits = [r for r in res if r.get("status") in ("warn", "fail")]
    for r in hits:
        kinds = {f.get("kind") or f.get("rule") or "?" for f in r.get("findings", [])} | set(r.get("warn") or [])
        print(f"  {r.get('task_id') or r.get('task')}: {r.get('status')} {sorted(kinds)}")
    if not hits:
        print("  no warnings")
json.dump(
    out,
    open(os.path.join(BASE, BATCH, "static_checks.json"), "w", encoding="utf-8"),
    indent=1,
)
print("wrote", os.path.join(BASE, BATCH, "static_checks.json"))
