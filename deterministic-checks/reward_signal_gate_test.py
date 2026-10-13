"""Calibration regression for reward_signal_gate.py against the QCR_EKW_16092026 expert findings.

Runs only when the feedback bundle is present (skips otherwise). Each assertion is one expert
finding the gate must keep catching on the PRE-FIX package.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import reward_signal_gate as G  # noqa: E402

FB = HERE.parent / "dataos_qc_runs" / "74-ekw-sprint" / "feedback_16092026"
pytestmark = pytest.mark.skipif(not FB.is_dir(), reason="feedback bundle not present")


def cands(task: str, lint: str) -> dict[str, list]:
    r = G.check_task(FB / f"{task}_fixed")
    out: dict[str, list] = {}
    for c in r["checks"][lint].get("candidates", []):
        for n in str(c["criterion"]).split(","):
            out.setdefault(n, []).append(c["evidence"])
    return out


def test_task24_v22_budget_contradiction():
    ev = cands("task_24", "G4_fail_contradiction")
    assert "v22" in ev
    assert any("budget" in str(e) for e in ev["v22"]), ev["v22"]


def test_task63_source_blind_status_criteria():
    ev = cands("task_63", "G1_source_blind")
    assert {"v1", "v8", "v16"} <= set(ev), sorted(ev)


def test_task3_cross_deliverable_v15b():
    ev = cands("task_3", "G1_source_blind")
    assert "v15b" in ev, sorted(ev)


def test_task29_exact_cents():
    ev = cands("task_29", "G3_numeric_pin")
    assert "v4" in ev and any("no tolerance" in str(e) or "exact" in str(e) for e in ev["v4"]), ev.get("v4")


def test_task17_conditional_escapes_source_blind():
    ev = cands("task_17", "G1_source_blind")
    assert any(n.endswith(":audio") for n in ev) and any(n.endswith(":sampler") for n in ev), sorted(ev)


def test_task4_v12_sourcing_contradiction():
    ev = cands("task_4", "G4_fail_contradiction") | cands("task_4", "G1_source_blind")
    assert "v12" in ev, sorted(ev)


def test_uncached_library_detection():
    r = G.check_task(FB / "task_31_fixed")
    assert r["checks"]["G6_uncached_formulas"]["status"] == "fail"


def test_judge_samples_policy():
    r = G.check_task(FB / "task_31_fixed")
    assert r["checks"]["G9_judge_samples"]["status"] == "fail"
