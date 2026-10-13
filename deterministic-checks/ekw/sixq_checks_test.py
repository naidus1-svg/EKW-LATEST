#!/usr/bin/env python3
"""Fixture tests for sixq_checks.py: per check one flag case, one clean case, one missing-input case.

No model is called: the AI reader is replaced by a fake. Run: python sixq_checks_test.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sixq_checks as sq  # noqa: E402


def make_task(root: Path, name: str, instruction: str, rules: list[tuple[str, str, float]],
              files=("/app/.qc_evidence/submission_0.txt",), golden: dict | None = None,
              emap: dict | None = None) -> Path:
    t = root / name
    (t / "tests" / "deliverables_00").mkdir(parents=True)
    (t / "solution" / "files").mkdir(parents=True)
    (t / "instruction.md").write_text(instruction, encoding="utf-8")
    body = "[judge]\nfiles = [" + ", ".join(json.dumps(f) for f in files) + "]\nweight = 1.0\n\n"
    for nm, desc, w in rules:
        body += f'[[criterion]]\nname = "{nm}"\ndescription = {json.dumps(desc)}\ntype = "binary"\nweight = {w}\n\n'
    (t / "tests" / "deliverables_00" / "judge.toml").write_text(body, encoding="utf-8")
    for fn, txt in (golden or {}).items():
        (t / "solution" / "files" / fn).write_text(txt, encoding="utf-8")
    if emap is not None:
        (t / "tests" / "__support").mkdir()
        (t / "tests" / "__support" / "evidence_map.json").write_text(json.dumps(emap), encoding="utf-8")
    return t


def run(task: Path, q: str, llm=None) -> dict:
    old = sq.LLM
    if llm is not None:
        sq.LLM = llm
    try:
        return sq.check_task(task, q, use_llm=llm is not None)
    finally:
        sq.LLM = old


INSTR = "Write a memo with the total payable.\nUse the attached contract.\n"


def test_f1_flag():
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", INSTR, [("v1", "Pass if the memo states exactly $205,153 as the amount payable.", 0.1)])
        r = run(t, "F1")
        assert r["status"] == "warn" and r["findings"][0]["kind"] == "strict_form_pinned_figure", r
        assert r["findings"][0]["file"].endswith("judge.toml") and isinstance(r["findings"][0]["line"], int)


def test_f1_clean():
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", INSTR, [("v1", "Pass if the memo states $205,153; accept rounding or equivalent wording.", 0.1)])
        assert run(t, "F1")["status"] == "pass"


def test_f1_missing_input():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d) / "t"
        t.mkdir()
        assert run(t, "F1")["status"] == "skip"


def test_f1_ai_reader_flag_and_drop():
    reply = json.dumps({"flags": [
        {"rule": "deliverables_00/v1", "other_form": "rounded to thousands", "rule_quote": "states $205,153"},
        {"rule": "deliverables_00/nope", "other_form": "x", "rule_quote": "y"},
    ]})
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", INSTR, [("v1", "Pass if the memo states $205,153.", 0.1)])
        sq.claude_available = lambda: True
        r = run(t, "F1", llm=lambda p: reply)
        kinds = [f["kind"] for f in r["findings"]]
        assert kinds == ["ai_reader_f1"], r
        assert r["info"]["dropped_from_reader"] == 1, r


def test_f2_flag():
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", INSTR, [("v1", "Pass if the memo is at most 300 words and has a sheet named \"Summary\".", 0.1)])
        r = run(t, "F2")
        kinds = {f["kind"] for f in r["findings"]}
        assert r["status"] == "warn" and kinds == {"constraint_number_not_in_instruction", "required_name_not_in_instruction"}, r


def test_f2_clean():
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", "Write a memo of at most 300 words. Add a sheet named \"Summary\".\n",
                      [("v1", "Pass if the memo is at most 300 words and has a sheet named \"Summary\".", 0.1)])
        assert run(t, "F2")["status"] == "pass"


def test_f2_missing_input():
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", "", [("v1", "Pass if x.", 0.1)])
        (t / "instruction.md").unlink()
        assert run(t, "F2")["status"] == "skip"


def test_f3_flag():
    reply = json.dumps({"flags": [{"rule": "deliverables_00/v1", "instruction_line": 1, "other_reading": "period could end in June", "loses_rule": True}]})
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", INSTR, [("v1", "Pass if the total is $5.", 0.1)])
        sq.claude_available = lambda: True
        r = run(t, "F3", llm=lambda p: reply)
        assert r["status"] == "warn" and r["findings"][0]["instruction_line"] == 1, r


def test_f3_clean():
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", INSTR, [("v1", "Pass if the total is $5.", 0.1)])
        sq.claude_available = lambda: True
        assert run(t, "F3", llm=lambda p: json.dumps({"flags": []}))["status"] == "pass"


def test_f3_missing_input_no_login():
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", INSTR, [("v1", "Pass if x.", 0.1)])
        sq.claude_available = lambda: False
        r = run(t, "F3")
        assert r["status"] == "skip" and "claude" in r["note"], r


def test_f3_dropped_without_instruction_line():
    reply = json.dumps({"flags": [{"rule": "deliverables_00/v1", "other_reading": "x", "loses_rule": True}]})
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", INSTR, [("v1", "Pass if x.", 0.1)])
        sq.claude_available = lambda: True
        r = run(t, "F3", llm=lambda p: reply)
        assert r["status"] == "pass" and r["info"]["dropped_from_reader"] == 1, r


def test_f4_flag():
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", INSTR, [("v1", "Pass if there are no errors in the workbook.", 0.2), ("v2", "Pass if the file exists.", 0.1)])
        r = run(t, "F4")
        assert {f["kind"] for f in r["findings"]} == {"passes_on_absence", "existence_only"}, r
        assert abs(r["info"]["weight_on_flagged_rules"] - 0.3) < 1e-9, r


def test_f4_clean():
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", INSTR, [("v1", "Pass if the memo states a total of $205,153 for base fees.", 0.2)])
        assert run(t, "F4")["status"] == "pass"


def test_f4_missing_input():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d) / "t"
        (t / "tests").mkdir(parents=True)
        assert run(t, "F4")["status"] == "skip"


def test_f5_flag_file_not_visible():
    emap = {"groups": {"deliverables_00": {"paths": ["memo.docx"]}}}
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", INSTR, [("v1", "Pass if model.xlsx shows the total of $5.", 0.1)], emap=emap)
        r = run(t, "F5")
        assert r["status"] == "warn" and r["findings"][0]["kind"] == "rule_names_file_judge_cannot_see", r


def test_f5_flag_priority_weight():
    instr = "The most important result is the termination capital gains fee calculation.\nWrite a memo.\n"
    rules = [("v1", "Pass if the termination capital gains fee calculation is correct.", 0.01),
             ("v2", "Pass if the memo has a heading.", 0.3), ("v3", "Pass if the memo has a date.", 0.3)]
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", instr, rules)
        r = run(t, "F5")
        assert any(f["kind"] == "priority_sentence_weight_below_median" for f in r["findings"]), r


def test_f5_clean():
    emap = {"groups": {"deliverables_00": {"paths": ["memo.docx"]}}}
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", INSTR, [("v1", "Pass if memo.docx shows the total of $5.", 0.1)], emap=emap)
        assert run(t, "F5")["status"] == "pass"


def test_f5_missing_input():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d) / "t"
        t.mkdir()
        assert run(t, "F5")["status"] == "skip"


def test_f6_flag():
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", INSTR, [("v1", "Pass if the memo states $205,153 payable.", 0.1)], golden={"memo.txt": "The total payable is 208,000."})
        r = run(t, "F6")
        assert r["status"] == "warn" and r["findings"][0]["kind"] == "rule_number_not_in_golden", r


def test_f6_clean_with_rounding():
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", INSTR, [("v1", "Pass if the memo states $205,153 payable.", 0.1)], golden={"memo.txt": "The total payable is 205,153.40."})
        assert run(t, "F6")["status"] == "pass"


def test_f6_missing_input():
    with tempfile.TemporaryDirectory() as d:
        t = make_task(Path(d), "t", INSTR, [("v1", "Pass if $205,153.", 0.1)])
        r = run(t, "F6")
        assert r["status"] == "skip" and "golden" in r["note"], r


# a child that answers the way pdftotext does (UTF-8 bytes, here with one stray byte) or echoes its standard input back
CHILD_PDF = (
    "import sys\n"
    "sys.stdout.buffer.write('Total: \\u20ac1,234 \\u2192 r\\u00e9sum\\u00e9'.encode('utf-8') + b' bad:\\xff end')\n"
)
CHILD_ECHO = "import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read())\n"


def _through_child(code: str, seen: list):
    """A subprocess.run stand-in that runs `code` in place of the command and keeps every other argument as the caller gave it."""
    real = sq.subprocess.run

    def fake(argv, **kw):
        seen.append((list(argv), dict(kw)))
        return real([sys.executable, "-c", code], **kw)

    return fake


def test_pdf_text_is_read_as_utf8_not_the_system_code_page():
    seen: list = []
    with mock.patch.object(sq.shutil, "which", return_value="pdftotext"), mock.patch.object(sq.subprocess, "run", _through_child(CHILD_PDF, seen)):
        text = sq._read_numbers_text(Path("golden.pdf"))
    assert "Total: €1,234 → résumé" in text, text  # not the junk a cp1252 read gives
    assert "bad:� end" in text, text  # a byte that is not UTF-8 is replaced; the old read dropped the whole file
    argv, kw = seen[0]
    assert argv[:4] == ["pdftotext", "-q", "-enc", "UTF-8"], argv
    assert (kw["encoding"], kw["errors"]) == ("utf-8", "replace"), kw


def test_claude_prompt_goes_in_and_out_as_utf8():
    seen: list = []
    prompt = "€1,234 → 本語 résumé"
    with mock.patch.object(sq.subprocess, "run", _through_child(CHILD_ECHO, seen)):
        assert sq.call_claude(prompt) == prompt  # a narrow code page cannot encode this prompt
    assert (seen[0][1]["encoding"], seen[0][1]["errors"]) == ("utf-8", "replace")


def test_no_anchor_dropped():
    r = {"rule_id": "x", "file": "f", "line": None}
    assert not sq._anchor_ok(r)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as exc:
            failed += 1
            print(f"  {t.__name__}: FAIL - {type(exc).__name__}: {exc}")
    print(f"TESTS {passed}/{passed + failed} passed")
    sys.exit(1 if failed else 0)
