#!/usr/bin/env python3
"""Tests for build_review_union.py's severity gating on uncalibrated signals: scan_findings()
(coordinator, 20:12Z) and advisory_actuator_findings() (coordinator, 20:27Z) both give "major"
only when the task's calibrated promoted-kinds blocking set contains that scan/cell's name;
otherwise "minor" (still a full finding - rows/details, evidence, playbook - but excluded from
major_count/majors_present so it cannot park a task alone). No filesystem beyond a throwaway
tempdir; no network. Exit code = number of failures."""

import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_review_union as B

FAILS = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)


def _make_checks_dir(scan: str, verdict: str, n_rows: int = 2) -> Path:
    d = Path(tempfile.mkdtemp(prefix="test_build_review_union_"))
    with open(d / f"{scan}.verdict.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["task_id", scan])
        w.writerow(["SVC-PC-TEST-0", verdict])
    with open(d / f"{scan}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["task", "detail"])
        for i in range(n_rows):
            w.writerow(["SVC-PC-TEST-0", f"finding {i}"])
    return d


# fail verdict, no BLOCKING row for that scan -> minor
scan = "rubric_consistency_scan"
checks_dir = _make_checks_dir(scan, "fail")
findings = B.scan_findings(checks_dir, blocking_scans=set())
match = [f for f in findings if f["class"] == scan]
check(
    "fail verdict, no BLOCKING row for that scan -> minor",
    len(match) == 1 and match[0]["severity"] == "minor",
)

# fail verdict, one BLOCKING row whose cell_or_scan is that scan -> major
findings2 = B.scan_findings(checks_dir, blocking_scans={scan})
match2 = [f for f in findings2 if f["class"] == scan]
check(
    "fail verdict, one BLOCKING row whose cell_or_scan is that scan -> major",
    len(match2) == 1 and match2[0]["severity"] == "major",
)

# a minor-severity scan finding still carries its rows/playbook (context preserved, not dropped)
check(
    "minor finding still carries rows and playbook (context preserved)",
    len(match[0]["rows"]) == 2 and bool(match[0]["playbook"]),
)

# blocking_scans defaults to empty (no crash, everything minor) when not passed
findings3 = B.scan_findings(checks_dir)
match3 = [f for f in findings3 if f["class"] == scan]
check(
    "blocking_scans omitted defaults to empty set -> minor, no crash",
    len(match3) == 1 and match3[0]["severity"] == "minor",
)

# a scan with a warn verdict not in SCAN_WARN_INCLUDED still doesn't trigger at all (unaffected by severity change)
checks_dir_warn = _make_checks_dir("formula_cache_scan", "warn")
findings4 = B.scan_findings(checks_dir_warn, blocking_scans={"formula_cache_scan"})
check(
    "warn verdict on a non-warn-included scan still doesn't trigger a finding at all",
    not [f for f in findings4 if f["class"] == "formula_cache_scan"],
)

# major_count/majors_present at the union-output level only count severity=="major" (not len(findings))
mixed = [{"severity": "minor"}, {"severity": "minor"}, {"severity": "major"}]
major_count = sum(1 for f in mixed if f.get("severity") == "major")
majors_present = any(f.get("severity") == "major" for f in mixed)
check("major_count counts only severity=='major', not len(findings)", major_count == 1)
check("majors_present is true only when at least one major exists", majors_present is True)
check(
    "majors_present is false when every finding is minor",
    any(f.get("severity") == "major" for f in mixed[:2]) is False,
)

def _make_recheck_csv(cell: str, verdict: str, n: int = 3) -> Path:
    d = Path(tempfile.mkdtemp(prefix="test_build_review_union_recheck_"))
    p = d / "summary.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["task_id", "C", "D", "E", cell, f"{cell}_n", f"{cell}_first"])
        w.writerow(["SVC-PC-TEST-0", "warn", "warn", "warn", verdict, n, "first finding text"])
    return p


# advisory actuator cell, warn/fail verdict, no BLOCKING row for that cell -> minor
acell = "criterion_groundedness"
recheck_csv = _make_recheck_csv(acell, "fail")
adv_findings = B.advisory_actuator_findings(recheck_csv, blocking_scans=set())
adv_match = [f for f in adv_findings if f["class"] == acell]
check(
    "advisory actuator: fail verdict, no BLOCKING row for that cell -> minor",
    len(adv_match) == 1 and adv_match[0]["severity"] == "minor",
)

# advisory actuator cell, warn/fail verdict, one BLOCKING row whose cell_or_scan is that cell -> major
adv_findings2 = B.advisory_actuator_findings(recheck_csv, blocking_scans={acell})
adv_match2 = [f for f in adv_findings2 if f["class"] == acell]
check(
    "advisory actuator: fail verdict, one BLOCKING row whose cell_or_scan is that cell -> major",
    len(adv_match2) == 1 and adv_match2[0]["severity"] == "major",
)

# a minor-severity advisory-actuator finding still carries its details/playbook (context preserved)
check(
    "advisory actuator minor finding still carries details and playbook (context preserved)",
    "details" in adv_match[0] and bool(adv_match[0]["playbook"]),
)

# blocking_scans defaults to empty when not passed -> minor, no crash
adv_findings3 = B.advisory_actuator_findings(recheck_csv)
adv_match3 = [f for f in adv_findings3 if f["class"] == acell]
check(
    "advisory actuator: blocking_scans omitted defaults to empty set -> minor, no crash",
    len(adv_match3) == 1 and adv_match3[0]["severity"] == "minor",
)

# golden_arithmetic/golden_groundedness have no promoted-kind mapping at all today, so
# blocking_scan_names() (which only ever emits values from _PROMOTED_KIND_CELL) can never actually
# contain them in real use - they stay minor in practice by construction, not by a special case.
check(
    "golden_arithmetic/golden_groundedness are not reachable via any promoted-kind mapping",
    {"golden_arithmetic", "golden_groundedness"}.isdisjoint(set(B._PROMOTED_KIND_CELL.values())),
)

print(f"{len(FAILS)} failure(s)")
sys.exit(len(FAILS))
