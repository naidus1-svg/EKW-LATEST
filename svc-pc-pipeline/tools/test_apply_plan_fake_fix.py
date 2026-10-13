#!/usr/bin/env python3
"""Tests for apply_plan.py's fake-fix guard (coordinator, 2026-09-19 22:50Z): a text edit to
judge.toml that introduces a softening clause ("not graded", "not required", "any of", "optional")
not present before the edit is reverted, not applied, and reported. Reconstructed from
SVC-PC-21-2-0 r023 (the coordinator's own description of the incident - the live task's exact bytes
have since moved past this specific state under concurrent fixing, so the fixture text below is
built from the coordinator's account, not read from the live file). No filesystem beyond a
throwaway tempdir; no network. Exit code = number of failures."""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import apply_plan as A

FAILS = []


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        FAILS.append(name)


def _tmp_file(content: str, name: str = "judge.toml") -> Path:
    d = Path(tempfile.mkdtemp(prefix="test_apply_plan_"))
    p = d / name
    p.write_text(content, newline="")
    return p


# ---------------------------------------------------------------------------
# Direct unit checks on _softening_clause_gained
# ---------------------------------------------------------------------------
check(
    "'is not graded' newly introduced is detected",
    A._softening_clause_gained("Expected: every row present.", "Expected: exhaustive coverage is not graded.")
    == "is not graded",
)
check(
    "'not required' newly introduced is detected",
    A._softening_clause_gained("Expected: X.", "Expected: X is not required.") is not None,
)
check(
    "'optional' newly introduced is detected",
    A._softening_clause_gained("Expected: X.", "Expected: X is optional.") is not None,
)
check(
    "'any of' newly introduced is detected",
    A._softening_clause_gained("Expected: X and Y.", "Expected: any of X or Y.") is not None,
)
check(
    "a phrase already present before the edit is NOT flagged (not newly gained)",
    A._softening_clause_gained("Expected: any of X or Y already.", "Expected: any of X or Y, reworded.") is None,
)
check(
    "an edit with no softening phrase at all is not flagged",
    A._softening_clause_gained("Expected: X.", "Expected: X and Y, worded more precisely.") is None,
)

# ---------------------------------------------------------------------------
# apply_replace_literal: reverts on judge.toml, applies normally elsewhere
# ---------------------------------------------------------------------------

# Reconstructed SVC-PC-21-2-0 r023 (coordinator's account): the criterion originally required
# exhaustive coverage of every task; the flagged pass rewrote it to excuse the very omission the
# reviewers filed by declaring exhaustive coverage "is not graded".
R023_BEFORE = (
    '[[criterion]]\nname = "r023"\ndescription = '
    "'''Every task in the quarter appears as its own row in the Activity Map, with no omissions. "
    "Expected: exhaustive coverage of every task, one row each.'''\ntype = \"binary\"\nweight = 0.02\n"
)
R023_SOFTENED = (
    '[[criterion]]\nname = "r023"\ndescription = '
    "'''Every task in the quarter appears as its own row in the Activity Map. Exhaustive coverage "
    "of every task is not graded; the presence of the required rows is what determines pass. "
    "Expected: the required rows are present.'''\ntype = \"binary\"\nweight = 0.02\n"
)

p1 = _tmp_file(R023_BEFORE)
before_bytes = p1.read_text()
outcome, detail = A.apply_replace_literal(
    p1,
    "Expected: exhaustive coverage of every task, one row each.",
    "Exhaustive coverage of every task is not graded; the presence of the required rows is what "
    "determines pass. Expected: the required rows are present.",
)
check("SVC-PC-21-2-0 r023 reconstruction: outcome is 'reverted'", outcome == "reverted")
check("SVC-PC-21-2-0 r023 reconstruction: detail names the guard and the phrase", "FAKE-FIX GUARD" in detail and "is not graded" in detail)
check("SVC-PC-21-2-0 r023 reconstruction: file left byte-unchanged", p1.read_text() == before_bytes)
shutil.rmtree(p1.parent, ignore_errors=True)

# A legitimate edit to judge.toml (no softening clause) still applies normally.
p2 = _tmp_file('description = \'\'\'Old wording.\'\'\'\n')
outcome2, detail2 = A.apply_replace_literal(p2, "Old wording.", "New wording, still precise.")
check("a legitimate judge.toml edit (no softening clause) still applies", outcome2 == "applied")
check("a legitimate judge.toml edit's content actually changed", "New wording" in p2.read_text())
shutil.rmtree(p2.parent, ignore_errors=True)

# The same softening phrase text in a NON-judge.toml file (e.g. instruction.md) is NOT reverted -
# scope is judge.toml only, per the coordinator's literal instruction.
p3 = _tmp_file("Old text.", name="instruction.md")
outcome3, detail3 = A.apply_replace_literal(p3, "Old text.", "New text: this step is optional.")
check("the same clause in instruction.md (not judge.toml) is NOT reverted - scope is judge.toml only", outcome3 == "applied")
shutil.rmtree(p3.parent, ignore_errors=True)

# A phrase already present before the edit, in a DIFFERENT part of the file the edit doesn't touch,
# is not "gained" by this edit and must not cause a revert.
p4 = _tmp_file(
    "[[criterion]]\ndescription = '''r001: any of the two named vendors is acceptable.'''\n\n"
    "[[criterion]]\ndescription = '''r002: old wording for a different fact.'''\n"
)
outcome4, detail4 = A.apply_replace_literal(p4, "old wording for a different fact.", "new wording for a different fact.")
check("a pre-existing 'any of' elsewhere in the file does not block an unrelated edit", outcome4 == "applied")
shutil.rmtree(p4.parent, ignore_errors=True)

# ---------------------------------------------------------------------------
# apply_append_text: same guard
# ---------------------------------------------------------------------------
p5 = _tmp_file("[[criterion]]\nname = \"r099\"\n")
outcome5, detail5 = A.apply_append_text(
    p5, '[[criterion]]\nname = "r100"\ndescription = \'\'\'This check is optional.\'\'\'\n'
)
check("append_text with a softening clause on judge.toml is reverted", outcome5 == "reverted")
check("reverted append_text leaves the file unchanged", p5.read_text() == "[[criterion]]\nname = \"r099\"\n")
shutil.rmtree(p5.parent, ignore_errors=True)

# ---------------------------------------------------------------------------
# main-loop wiring: a reverted edit counts toward any_failed (exit 1), and `notes` is logged.
# ---------------------------------------------------------------------------
import json as _json

task_root = Path(tempfile.mkdtemp(prefix="test_apply_plan_main_"))
task_dir = task_root / "SVC-PC-TEST-0"
(task_dir / "tests" / "deliverables_01").mkdir(parents=True)
jt = task_dir / "tests" / "deliverables_01" / "judge.toml"
jt.write_text(R023_BEFORE)
plan_path = task_root / "PLAN.json"
plan_path.write_text(
    _json.dumps(
        {
            "task": "SVC-PC-TEST-0",
            "edits": [
                {
                    "file": "tests/deliverables_01/judge.toml",
                    "op": "replace_literal",
                    "find": "Expected: exhaustive coverage of every task, one row each.",
                    "replace": "Exhaustive coverage of every task is not graded. Expected: the required rows are present.",
                    "reason": "fixes check 1.5",
                    "finding_id": "1.5",
                }
            ],
            "notes": "r012: not fixable without a person",
        }
    )
)
fix_log = task_root / "FIX-FROM-DATAOS.md"

import importlib

importlib.reload(A)
old_argv = sys.argv
sys.argv = [
    "apply_plan.py",
    "--plan",
    str(plan_path),
    "--task",
    "SVC-PC-TEST-0",
    "--corpus-root",
    str(task_root),
    "--fix-log",
    str(fix_log),
]
try:
    rc = A.main()
finally:
    sys.argv = old_argv

check("main() exits non-zero when an edit is reverted (any_failed)", rc == 1)
check("judge.toml is unchanged after main() reverted the only edit", jt.read_text() == R023_BEFORE)
log_text = fix_log.read_text()
check("the fix log records REVERTED for the edit", "REVERTED" in log_text)
check("the fix log records the fixer's notes field", "not fixable without a person" in log_text)
shutil.rmtree(task_root, ignore_errors=True)

print(f"{len(FAILS)} failure(s)")
sys.exit(len(FAILS))
