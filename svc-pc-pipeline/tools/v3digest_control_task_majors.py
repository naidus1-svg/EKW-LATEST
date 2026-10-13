#!/usr/bin/env python3
"""v3digest_control_task_majors.py - COPY of
/root/qc/_prompts/sev2/control_task_majors.py (read-only original, never
edited), adapted only for this measurement's reviewer names (opus, sonnet
instead of glm, sonnet) and review-output location (flat
reviews/<task>.<reviewer>.json instead of sev2_pipe/<task>/CR.sev2.<reviewer>.json).

Prints every MAJOR-severity check either digest-mode reviewer filed on the
control task SVC-PC-2-7-0 (0 known DataOS majors), quoted in full, for the
false-major check: a person checks every one against the shipped files; a
major with no file:line or cell quote behind it is a false major.
"""

import json
from pathlib import Path

TASK = "SVC-PC-2-7-0"
REVIEWS_DIR = Path("/root/qc/_prompts/v3digest/reviews")

for reviewer in ("opus", "sonnet"):
    p = REVIEWS_DIR / f"{TASK}.{reviewer}.json"
    print(f"=== {reviewer} ===")
    if not p.is_file():
        print("  NOT YET AVAILABLE")
        continue
    j = json.loads(p.read_text(encoding="utf-8"))
    print(
        f"  overall_verdict={j.get('overall_verdict')} major_count={j.get('major_count')} minor_count={j.get('minor_count')}"
    )
    checks = j.get("checks")
    if j.get("overall_verdict") not in (
        "accept",
        "reject",
        "invalid",
        "needs_revision",
    ) or not isinstance(checks, list):
        print(
            f"  REVIEW OUTPUT NON-CANONICAL (checks={checks!r}) - not usable, treat as missing/unscored"
        )
        print()
        continue
    majors = [
        c
        for c in checks
        if isinstance(c, dict) and str(c.get("severity", "")).lower() == "major"
    ]
    if not majors:
        print("  no MAJOR checks filed")
    for c in majors:
        print(f"  --- check {c.get('id')} {c.get('name')} ---")
        print(f"  evidence_status: {c.get('evidence_status')}")
        print(f"  justification: {c.get('justification')}")
        print(f"  suggested_fix: {c.get('suggested_fix')}")
    print()
