"""Stdlib tests for svc_build_freeze.build(): which consolidated/Combined rows freeze a task.
Run: python tools/test_svc_build_freeze.py"""

import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import svc_build_freeze as f  # noqa: E402

HDR = [
    "",
    "Submitted by",
    "Email",
    "Doc",
    "task_name",
    "Link",
    "Avail",
    "EQC Status",
    "",
    "",
    "PA",
    "PTM",
    "TC",
]


def cons_row(task, who, eqc, k="", l="", m=""):
    return ["", who, "", "", task, "", "EQC ready", eqc, "", "", k, l, m]


def run(cons, comb):
    def fake_get(tok, sid, rng):
        return [HDR] + cons if sid == f.CONS else comb

    f.get = fake_get
    return f.build(None, "svc")


def test_done_with_major_is_reject_for_ours():
    # 92-0-0 on 2026-09-27: H Done, Prompt-Tests misalignment Major, Combined already says Rejected
    r = run(
        [cons_row("SVC-PC-92-0-0", "Khiem", "Done", "Good", "Major", "Minor")],
        [["SVC-PC-92-0-0", "Khiem Doan", "Rejected"]],
    )
    assert "SVC-PC-92-0-0" not in r, r


def test_done_with_major_and_stale_submitted_combined_is_ours_to_fix():
    r = run(
        [cons_row("SVC-PC-79-2-0", "Khiem Doan", "Done", "Good", "Major", "Minor")],
        [["SVC-PC-79-2-0", "Khiem Doan", "submit for manual QC"]],
    )
    assert "SVC-PC-79-2-0" not in r, r


def test_done_without_major_still_freezes():
    r = run(
        [cons_row("SVC-PC-11-2-0", "Khiem", "Done", "Good", "Minor", "Good")],
        [["SVC-PC-11-2-0", "Khiem Doan", "Submitted for Manual QC"]],
    )
    assert "SVC-PC-11-2-0" in r, r


def test_done_with_major_on_someone_elses_task_stays_frozen():
    r = run(
        [cons_row("SVC-PC-5-1-0", "Luiz", "Done", "Major", "", "")],
        [["SVC-PC-5-1-0", "Luiz", "Rejected"]],
    )
    assert "SVC-PC-5-1-0" in r, r


def test_later_resubmission_row_pending_still_freezes():
    r = run(
        [
            cons_row("SVC-PC-24-6-0", "Khiem", "Done", "Major", "Good", "Minor"),
            cons_row("SVC-PC-24-6-0", "Khiem", ""),
        ],
        [["SVC-PC-24-6-0", "Khiem Doan", "Rejected"]],
    )
    assert "SVC-PC-24-6-0" in r, r


def test_approved_always_freezes():
    r = run(
        [cons_row("SVC-PC-3-4-0", "Khiem", "Done", "Major", "", "")],
        [["SVC-PC-3-4-0", "Khiem Doan", "Approved - Passed Manual QC"]],
    )
    assert "SVC-PC-3-4-0" in r, r


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print("%d/%d passed" % (len(tests), len(tests)))
