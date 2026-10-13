"""Regression tests for the two svc_eval_regrade.py gate bugs found 2026-09-24 (7 tasks parked as "stuck").

Bug 1 (94-0-0, 25-2-0, 31-5-0): decide-mode "keep" exemptions were applied AFTER the LLM re-grade decided
whether to run, so the re-grade was skipped and the task failed with "did not confirm loosened criteria: {}".
Bug 2 (40-1-0, 52-5-0, 41-3-0, 25-4-0): the gate compared judge.toml only and could not see a coverage fix
made in checks.py (including criteria registered in a loop), so it failed with "no criterion added or rewritten".
Usage: python tools/test_svc_eval_regrade_gate.py [path/to/svc_eval_regrade.py]"""

import importlib.util, re, sys

path = sys.argv[1] if len(sys.argv) > 1 else "tools/svc_eval_regrade.py"
spec = importlib.util.spec_from_file_location("rg", path)
rg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rg)
src_text = open(path, encoding="utf-8").read()
fail = 0


def check(label, ok):
    global fail
    print(("PASS " if ok else "FAIL ") + label)
    fail += not ok


BASE = """
import rewardkit as rk
from rewardkit.session import criterion
WEEKS = 3
LIMIT = 100

def _helper(x):
    return x < LIMIT

@criterion(description="total ties")
def total_ok(workspace, path="a.xlsx"):
    return _helper(1)

@criterion(description="week matches")
def week_ok(workspace, week, path="a.xlsx"):
    return week > 0

rk.total_ok("a.xlsx", weight=0.1, name="d001")
for _w in range(1, WEEKS + 1):
    rk.week_ok("a.xlsx", week=_w, weight=0.1, name=f"r{_w:02d}")
"""
has = getattr(rg, "load_checks_criteria", None)
check(
    "load_checks_criteria exists (checks.py criteria are visible to the gate)",
    callable(has),
)
if callable(has):
    a = rg.load_checks_criteria(BASE)
    check("constant-name registration found (d001)", "d001" in a)
    check(
        "loop registrations found (r01..r03, 52-5-0 shape)",
        all(k in a for k in ("r01", "r02", "r03")),
    )
    b = rg.load_checks_criteria(BASE)
    check("unchanged file -> identical fingerprints", a == b)
    c = rg.load_checks_criteria(BASE.replace("LIMIT = 100", "LIMIT = 50"))
    check(
        "constant used by a helper changed -> d001 counts as rewritten",
        c["d001"] != a["d001"] and c["r01"] == a["r01"],
    )
    d = rg.load_checks_criteria(BASE.replace("return week > 0", "return week > 1"))
    check(
        "criterion body changed -> r01 rewritten, d001 untouched",
        d["r01"] != a["r01"] and d["d001"] == a["d001"],
    )
    e = rg.load_checks_criteria(
        BASE.replace('description="total ties"', 'description="total ties exactly"')
    )
    check("decorator description changed -> d001 rewritten", e["d001"] != a["d001"])

body = src_text[src_text.index("def cmd_regrade") :]
i_kept = body.find("kept = {}")
i_llm = body.find('llm = {"ran": False')
check(
    "decision exemptions are applied BEFORE the LLM re-grade decides whether to run",
    0 <= i_kept < i_llm,
)
check(
    "gate emits GATE-ERROR when a required re-grade did not run", '"GATE-ERROR"' in body
)
print("ALL PASS" if not fail else "%d FAIL" % fail)
sys.exit(1 if fail else 0)
