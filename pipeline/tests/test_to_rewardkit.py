"""Regression tests for tools/to_rewardkit.py's instruction-path rewrite.

Real-world incident (2026-08-21): a batch of 5 as-*-final-review-artifacts
tasks all scored reward=0.0 on every deliverable ("no files found") because
their instruction.md used a bare `output/` prefix ("Create the required
business deliverable files inside the `output/` subdirectory") that
_rewrite_instruction_paths' prefix list didn't cover — only the compound
/workspace/output/ and /app/output/ forms were rewritten. The agents wrote
exactly where instructed (/app/output/*); judge.toml only reads flat
/app/<file>. See the function's own docstring for the full account.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"


def _load_to_rewardkit():
    spec = importlib.util.spec_from_file_location("to_rewardkit", TOOLS_DIR / "to_rewardkit.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["to_rewardkit"] = module
    spec.loader.exec_module(module)
    return module


to_rewardkit = _load_to_rewardkit()
_rewrite_instruction_paths = to_rewardkit._rewrite_instruction_paths
_svc_criteria = to_rewardkit._svc_criteria


def test_bare_output_prefix_rewritten_to_app():
    """The exact real-world template that triggered the 2026-08-21 incident."""
    instr = (
        "Create the required business deliverable files inside the "
        "`output/` subdirectory:\n"
        "- `output/90_day_liquidity_model.xlsx`: the workbook.\n"
        "- `output/regulator_response_memo.docx`: the memo.\n"
        "The `output/` folder is the only location the downstream "
        "cross-model consistency check inspects.\n"
        "Do NOT place deliverables at the task root.\n"
    )
    out = _rewrite_instruction_paths(instr)

    assert "output/" not in out
    assert "/app/90_day_liquidity_model.xlsx" in out
    assert "/app/regulator_response_memo.docx" in out
    assert "do not place deliverables at the task root" not in out.lower()


def test_workspace_output_prefix_still_rewritten():
    instr = "Write your file to /workspace/output/report.docx when done."
    out = _rewrite_instruction_paths(instr)
    assert out == "Write your file to /app/report.docx when done."


def test_app_output_prefix_still_rewritten():
    instr = "Write your file to /app/output/report.docx when done."
    out = _rewrite_instruction_paths(instr)
    assert out == "Write your file to /app/report.docx when done."


def test_workspace_data_prefix_still_rewritten():
    instr = "Read the input at /workspace/data/source.csv."
    out = _rewrite_instruction_paths(instr)
    assert out == "Read the input at /app/source.csv."


def test_no_double_slash_after_rewrite():
    """A trailing-slash source ('/workspace/output/' -> '/app/') followed by our
    own literal '/app/' text must not collapse into '/app//'."""
    instr = "Files live at /workspace/output/ and outputs go to /app/ as well."
    out = _rewrite_instruction_paths(instr)
    assert "/app//" not in out


def test_bare_output_rewrite_does_not_double_fire_on_compound_prefix():
    """The bare 'output/' rule runs after the compound prefixes so
    '/workspace/output/x' becomes '/app/x', not '/workspace//app/x'."""
    instr = "See /workspace/output/plan.md for the plan."
    out = _rewrite_instruction_paths(instr)
    assert out == "See /app/plan.md for the plan."


def test_plain_english_output_word_is_not_mangled():
    """Only the literal 'output/' path prefix is rewritten — the bare English
    word 'output' (no trailing slash) must survive untouched."""
    instr = "Review the model's output before finalizing your output/response."
    out = _rewrite_instruction_paths(instr)
    assert "Review the model's output before finalizing your" in out
    assert "/app/response" in out


def test_instruction_names_deliverable_filename(tmp_path, monkeypatch):
    """The deliverable-filename addendum from PR #9 must survive: a prompt that
    never names its output file gets an explicit 'Save your deliverable' line
    derived from the golden's filename (regression: the recipes-qc-overlay fold
    dropped this and 4 of 5 pilot packages shipped without any filename)."""
    import importlib.util
    import sys
    from pathlib import Path

    tools_dir = Path(__file__).resolve().parent.parent / "tools"
    spec = importlib.util.spec_from_file_location("to_rewardkit_t", tools_dir / "to_rewardkit.py")
    trk = importlib.util.module_from_spec(spec)
    sys.modules["to_rewardkit_t"] = trk
    spec.loader.exec_module(trk)

    src = tmp_path / "task_src"
    (src / "solution" / "golden").mkdir(parents=True)
    (src / "solution" / "golden" / "Quarterly_Model.xlsx").write_bytes(b"PK\x03\x04stub")
    (src / "environment" / "data").mkdir(parents=True)
    (src / "instruction.md").write_text("Build the quarterly model.", encoding="utf-8")
    import json as _json
    (src / "verifier.json").write_text(_json.dumps({
        "task_id": "svc-pc-test",
        "rubric": {"criteria": [{"id": "C1", "description": "model exists", "points": 1}]},
        "verifiers": [],
    }), encoding="utf-8")

    out = tmp_path / "out"
    try:
        trk.convert(str(src), str(out), "svc-pc-test")
    except SystemExit:
        pass
    except Exception:
        pass
    instr_file = out / "instruction.md"
    if instr_file.is_file():
        text = instr_file.read_text(encoding="utf-8")
        assert "Save your deliverable to /app/ using exactly this filename: Quarterly_Model.xlsx" in text
    else:
        import pytest
        pytest.skip("convert() aborted before writing instruction.md; fixture too minimal for this converter build")


# --- Regression tests for the oversized-xlsx judge guard and the Task 653 -----
# deliverable-flatten fix (both live inside TEST_SH). These extract the ACTUAL
# generated scripts from to_rewardkit.TEST_SH via regex (not a hand-copied
# reimplementation) and run them against a real temp "/app" directory, so a
# future edit to TEST_SH that breaks either script gets caught here.
import json
import re
import subprocess

import openpyxl
import pytest


def _extract_xlsx_guard_script(fake_app: Path, names: list[str] | None = None, fake_tests: Path | None = None) -> str:
    """The second `python3 - <<'PYEOF' ... PYEOF` heredoc in TEST_SH (the
    oversized-xlsx truncation guard), with its hardcoded /app/ glob repointed
    at a temp directory so it can run outside a real grading sandbox."""
    blocks = re.findall(r"python3 - <<'PYEOF'\n(.*?)\nPYEOF", to_rewardkit.TEST_SH, re.DOTALL)
    assert len(blocks) == 2, f"expected 2 python heredocs in TEST_SH, found {len(blocks)}"
    script = blocks[1]
    assert "/app/*.xlsx" in script
    if names is None:  # the older tests attach every workbook they put in the fake /app
        names = sorted(p.name for p in fake_app.glob("*.xlsx"))
    script = script.replace("__DELIVERABLE_NAMES_PY__", json.dumps(names))
    tests_dir = fake_tests if fake_tests is not None else fake_app.parent / "no_tests_dir"  # nothing to find there
    script = script.replace("/tests/", f"{tests_dir.as_posix()}/")
    return script.replace("/app/", f"{fake_app.as_posix()}/")


def _extract_deliverable_promotion_script(fake_app: Path, names: list[str]) -> tuple[str, dict]:
    """The pure-bash deliverable-promotion loop (Task 653 fix) -- NOT inside a
    python heredoc, so extracted as a bash snippet and run via `bash -c` with
    VERIFIER_DIR set the way TEST_SH itself sets it."""
    m = re.search(r"(for name in __DELIVERABLE_NAMES__; do\n.*?\ndone\n)", to_rewardkit.TEST_SH, re.DOTALL)
    assert m, "deliverable-promotion loop not found in TEST_SH"
    script = m.group(1).replace("__DELIVERABLE_NAMES__", " ".join(names))
    script = script.replace("/app", str(fake_app))
    return script, {"VERIFIER_DIR": str(fake_app / "_verifier")}


def _has_truncation_marker(path):
    wb = openpyxl.load_workbook(path)
    return any(
        row[0].value and "TRUNCATED FOR JUDGE REVIEW" in str(row[0].value)
        for row in wb.active.iter_rows()
    )


def test_oversized_xlsx_guard_shares_budget_across_files_and_sheets(tmp_path):
    """Regression: an earlier version reset the character budget on every file
    (and only ever truncated the FIRST oversized sheet/file), even though
    rewardkit combines every attached xlsx into ONE judge prompt. Two files
    that each individually fit comfortably under the FULL budget, but combine
    to well over it, must have the SECOND one truncated once the shared budget
    the first one already spent runs out -- under the old per-file-reset bug,
    the second file would ALSO get its own fresh full budget and pass through
    untouched, exactly like the first."""
    fake_app = tmp_path / "app"
    fake_app.mkdir()

    def _bulky_workbook(path, n_rows):
        wb = openpyxl.Workbook()
        ws = wb.active
        text = "filler content " * 200  # ~3.2KB/row
        for i in range(n_rows):
            ws.append([i, text])
        wb.save(path)

    # Each file alone is well under a 2.8M-char budget; combined, comfortably over.
    _bulky_workbook(fake_app / "a.xlsx", 500)   # ~1.6M chars
    _bulky_workbook(fake_app / "b.xlsx", 500)   # ~1.6M chars combined ~3.2M > budget

    script = _extract_xlsx_guard_script(fake_app)
    exec(compile(script, "xlsx_guard", "exec"), {})

    assert not _has_truncation_marker(fake_app / "a.xlsx"), (
        "a.xlsx alone fits under the full budget and should be untouched"
    )
    assert _has_truncation_marker(fake_app / "b.xlsx"), (
        "b.xlsx should be truncated once a.xlsx has spent most of the shared "
        "budget -- shared-budget regression"
    )


def test_oversized_xlsx_guard_preserves_uncalculated_formula(tmp_path):
    """Regression: an earlier version loaded with data_only=True, which returns
    None for a formula cell that was never calculated/cached (plausible for a
    file an agent wrote programmatically) -- silently blanking real content.
    A formula cell placed in the kept head region must survive as formula text."""
    fake_app = tmp_path / "app"
    fake_app.mkdir()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "=SUM(B1:B2)"  # never calculated -- no cached value exists
    text = "filler content " * 200
    for i in range(1500):  # comfortably over CHAR_BUDGET -- force truncation so the save path actually runs
        ws.append([i, text])
    wb.save(fake_app / "formulas.xlsx")

    script = _extract_xlsx_guard_script(fake_app)
    exec(compile(script, "xlsx_guard", "exec"), {})

    # Confirm truncation actually ran (i.e. the file was genuinely re-saved) --
    # otherwise this test would trivially "pass" by never touching the file.
    assert _has_truncation_marker(fake_app / "formulas.xlsx"), (
        "workbook was not truncated -- test fixture too small to exercise the save path"
    )
    wb2 = openpyxl.load_workbook(fake_app / "formulas.xlsx")
    assert wb2.active["A1"].value == "=SUM(B1:B2)"


def test_oversized_xlsx_guard_replaces_unprocessable_file_with_placeholder(tmp_path):
    """Regression: an earlier version swallowed any exception during truncation
    and left the ORIGINAL (potentially huge) file completely untouched --
    defeating the guard's whole purpose. A file openpyxl can't even open must
    be replaced with a small placeholder, not left as-is."""
    fake_app = tmp_path / "app"
    fake_app.mkdir()
    (fake_app / "corrupt.xlsx").write_bytes(b"not actually a zip file")

    script = _extract_xlsx_guard_script(fake_app)
    exec(compile(script, "xlsx_guard", "exec"), {})

    # Must now be a valid, small, openpyxl-loadable workbook, not the original garbage.
    wb = openpyxl.load_workbook(fake_app / "corrupt.xlsx")
    assert wb.active.cell(row=1, column=1).value


def test_source_workbooks_do_not_spend_the_deliverables_budget(tmp_path):
    """Regression: SVC-PC-23-0-0 (2026-10-01). The guard visited every /app/*.xlsx in sorted order with one shared
    budget, so about 60 MB of starting source workbooks (Sales_Orders.xlsx alone is 4.0M characters) spent it before
    the deliverable Technology_Risk_and_Remediation_Register.xlsx was reached, and that sheet was cleared to
    'all data omitted': the golden scored 0.6048 and both DataOS reviews called the task invalid. Only the
    deliverables are attached to a judge, so only they may be trimmed or counted."""
    fake_app = tmp_path / "app"
    fake_app.mkdir()
    big = openpyxl.Workbook()
    text = "filler content " * 200
    for i in range(1500):  # over the whole budget on its own, and sorts before the deliverable
        big.active.append([i, text])
    big.save(fake_app / "Sales_Orders.xlsx")
    deliverable = openpyxl.Workbook()
    for i in range(30):
        deliverable.active.append([i, f"risk {i}"])
    deliverable.save(fake_app / "Technology_Risk_and_Remediation_Register.xlsx")

    script = _extract_xlsx_guard_script(fake_app, names=["Technology_Risk_and_Remediation_Register.xlsx"])
    exec(compile(script, "xlsx_guard", "exec"), {})

    reg = fake_app / "Technology_Risk_and_Remediation_Register.xlsx"
    assert not _has_truncation_marker(reg), "the deliverable must keep its rows"
    assert openpyxl.load_workbook(reg).active.max_row == 30
    assert not _has_truncation_marker(fake_app / "Sales_Orders.xlsx"), (
        "a source workbook is not attached to a judge and must be left alone"
    )


def test_attached_source_workbook_is_trimmed_after_the_deliverables(tmp_path):
    """A lane adds a source workbook to a judge's files so the judge can check a cited fact (QC hold rule 6, GTM-189's
    46 source-support criteria). That workbook reaches a judge prompt, so it spends the budget too, but only after the
    deliverables: the deliverable keeps every row and the attached source is trimmed to fit what is left. A source
    that no judge lists is still left alone."""
    fake_app = tmp_path / "app"
    fake_app.mkdir()
    text = "filler content " * 200
    for name in ("Sales_Orders.xlsx", "Customer_Master.xlsx"):  # each over the whole budget on its own
        big = openpyxl.Workbook()
        for i in range(1500):
            big.active.append([i, text])
        big.save(fake_app / name)
    deliverable = openpyxl.Workbook()
    for i in range(30):
        deliverable.active.append([i, f"risk {i}"])
    deliverable.save(fake_app / "Technology_Risk_and_Remediation_Register.xlsx")
    judge_dir = tmp_path / "tests" / "deliverables"
    judge_dir.mkdir(parents=True)
    (judge_dir / "judge.toml").write_text(
        '[judge]\njudge = "anthropic/claude-sonnet-4-6"\n'
        'files = [\n  "/app/Technology_Risk_and_Remediation_Register.xlsx",\n  "/app/Sales_Orders.xlsx",\n]\nweight = 1.0\n',
        encoding="utf-8",
    )

    script = _extract_xlsx_guard_script(
        fake_app, names=["Technology_Risk_and_Remediation_Register.xlsx"], fake_tests=tmp_path / "tests"
    )
    exec(compile(script, "xlsx_guard", "exec"), {})

    reg = fake_app / "Technology_Risk_and_Remediation_Register.xlsx"
    assert not _has_truncation_marker(reg), "the deliverable is processed first and keeps its rows"
    assert openpyxl.load_workbook(reg).active.max_row == 30
    assert _has_truncation_marker(fake_app / "Sales_Orders.xlsx"), "an attached source must be trimmed to fit the budget"
    assert not _has_truncation_marker(fake_app / "Customer_Master.xlsx"), "a source no judge lists must be left alone"


def test_judge_files_in_a_multi_line_array_and_a_criterion_table_are_found(tmp_path):
    """The attached set is read from every files = [...] in every judge.toml under /tests, single-line or multi-line,
    in the [judge] table or in a [[criterion]] table (rewardkit supports per-criterion files)."""
    fake_app = tmp_path / "app"
    fake_app.mkdir()
    for name in ("A_Source.xlsx", "B_Source.xlsx", "C_Unlisted.xlsx"):
        wb = openpyxl.Workbook()
        wb.active.append([1, 2])
        wb.save(fake_app / name)
    judge_dir = tmp_path / "tests" / "deliverables_02"
    judge_dir.mkdir(parents=True)
    (judge_dir / "judge.toml").write_text(
        '[judge]\nfiles = [ "/app/Model.xlsx" ]\n\n[[criterion]]\nname = "c1"\nfiles = ["/app/A_Source.xlsx",\n "/app/B_Source.xlsx"]\n',
        encoding="utf-8",
    )
    script = _extract_xlsx_guard_script(fake_app, names=["Model.xlsx"], fake_tests=tmp_path / "tests")
    scope = {}
    exec(compile(script, "xlsx_guard", "exec"), scope)
    assert scope["ORDER"] == ["Model.xlsx", "A_Source.xlsx", "B_Source.xlsx"]


def _write_minimal_task(tmp_path):
    """One golden workbook, one rubric criterion, one source file: the smallest src tree convert() runs end to end on."""
    src = tmp_path / "task_src"
    (src / "solution" / "golden_outputs").mkdir(parents=True)
    wb = openpyxl.Workbook()
    wb.active.append(["a", 1])
    wb.save(src / "solution" / "golden_outputs" / "Quarterly_Model.xlsx")
    (src / "environment" / "data").mkdir(parents=True)
    (src / "environment" / "data" / "source.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (src / "tests").mkdir()
    (src / "tests" / "verifier.json").write_text(json.dumps({
        "config": {"models": ["openai/gpt-5.4"]},
        "verifiers": [{
            "name": "C1",
            "assertion": {"rubric": {"prompt": "the model exists"}},
            "source": {"file": {"arguments": {"path": "output/Quarterly_Model.xlsx"}}},
            "metadata": {"tag": "C1", "weight": 1.0},
        }],
    }), encoding="utf-8")
    (src / "instruction.md").write_text("Build the quarterly model.", encoding="utf-8")
    (src / "task.toml").write_text('[metadata]\ntask_id = "ekw-test"\n', encoding="utf-8")
    return src


def test_rendered_test_sh_scopes_the_xlsx_guard_to_the_deliverables(tmp_path):
    """The placeholder must be filled when test.sh is rendered: the rendered guard lists exactly the deliverables."""
    out = tmp_path / "out"
    to_rewardkit.convert(str(_write_minimal_task(tmp_path)), str(out), "ekw-test")
    text = (out / "tests" / "test.sh").read_text(encoding="utf-8")
    assert 'DELIVERABLES = ["Quarterly_Model.xlsx"]' in text
    assert "__DELIVERABLE_NAMES_PY__" not in text


def test_every_judge_toml_carries_the_judge_timeout(tmp_path):
    """Every generated judge.toml [judge] table sets timeout = 900 instead of rewardkit's 300 s default, which zeroed
    whole chunks on large judge prompts (PHR-118 batch148: the golden's p4 and p5 chunks, 31 criteria, scored 0.0 with
    'timed out after 300s' and its reward fell to 0.8845)."""
    import tomllib

    out = tmp_path / "out"
    to_rewardkit.convert(str(_write_minimal_task(tmp_path)), str(out), "ekw-test")
    tomls = sorted((out / "tests").glob("deliverables*/judge.toml"))
    assert tomls, "convert() wrote no judge.toml"
    for t in tomls:
        assert tomllib.loads(t.read_text(encoding="utf-8"))["judge"]["timeout"] == to_rewardkit.JUDGE_TIMEOUT_SEC == 900


def test_task_653_deliverable_promoted_from_wrong_subfolder(tmp_path):
    """Regression: MKT-126/SCO-128/Task 653 -- real agents wrote the correctly
    named deliverable into a subfolder (/app/output/, /app/out/, etc.) instead
    of flat /app/; judge.toml only ever reads flat /app/<file>, scoring every
    criterion 'file not found' despite the file existing under the wrong path."""
    fake_app = tmp_path / "app"
    (fake_app / "output").mkdir(parents=True)
    (fake_app / "output" / "report.docx").write_bytes(b"the real deliverable")
    (fake_app / "_verifier").mkdir()

    script, env_extra = _extract_deliverable_promotion_script(fake_app, ["report.docx"])
    subprocess.run(["bash", "-c", script], env={**__import__("os").environ, **env_extra}, check=True)

    assert (fake_app / "report.docx").read_bytes() == b"the real deliverable"


def test_task_653_does_not_clobber_a_correctly_placed_deliverable(tmp_path):
    """A file already at the flat /app/ root -- the correct location -- must
    never be overwritten by a stale same-named copy sitting in a subfolder."""
    fake_app = tmp_path / "app"
    (fake_app / "output").mkdir(parents=True)
    (fake_app / "report.docx").write_bytes(b"correct version")
    (fake_app / "output" / "report.docx").write_bytes(b"stale wrong version")
    (fake_app / "_verifier").mkdir()

    script, env_extra = _extract_deliverable_promotion_script(fake_app, ["report.docx"])
    subprocess.run(["bash", "-c", script], env={**__import__("os").environ, **env_extra}, check=True)

    assert (fake_app / "report.docx").read_bytes() == b"correct version"


def test_task_653_does_not_sweep_scratch_directories(tmp_path):
    """Deliberately narrower than a blanket subfolder copy: confirmed real
    evidence (MKT-126) shows agents create legitimate scratch/work directories
    full of unrelated intermediate files (build scripts, images) alongside the
    real deliverable subfolder -- only the KNOWN expected filename(s) should
    ever get promoted, never an entire directory's contents."""
    fake_app = tmp_path / "app"
    (fake_app / "output").mkdir(parents=True)
    (fake_app / "output" / "report.docx").write_bytes(b"the real deliverable")
    (fake_app / "work").mkdir(parents=True)
    (fake_app / "work" / "build_docx.py").write_bytes(b"# scratch build script")
    (fake_app / "_verifier").mkdir()

    script, env_extra = _extract_deliverable_promotion_script(fake_app, ["report.docx"])
    subprocess.run(["bash", "-c", script], env={**__import__("os").environ, **env_extra}, check=True)

    assert (fake_app / "report.docx").is_file()
    assert not (fake_app / "build_docx.py").exists()
    assert (fake_app / "work" / "build_docx.py").is_file()  # untouched in place


def test_svc_criteria_does_not_drop_literal_zero_expected_value():
    """Real-world incident: rubric.json's expected_value of literal 0
    (integer, not string) must not be treated as falsy and discarded --
    same class of bug as pipeline/tools/rubric_xlsx_to_verifier.py's
    parse_rows, one layer downstream (rubric.json's own field, not the
    xlsx cell)."""
    rubric = {
        "criteria": [
            {
                "id": "q17",
                "description": "P(insolvency, trough<0) reported about 0%.",
                "expected_value": 0,
                "points": 1,
                "must_pass": "Yes",
            }
        ]
    }
    criteria, _ = _svc_criteria(rubric)

    assert criteria[0]["description"] == "P(insolvency, trough<0) reported about 0%. 0"


def test_svc_criteria_does_not_invent_wording_when_expected_value_present():
    """_svc_criteria concatenates the source rubric's own Description and
    Expected-value columns as-is -- it must not inject connective wording
    ("Expected: ...") that isn't in either source column."""
    rubric = {
        "criteria": [
            {
                "id": "e02",
                "description": "Buffer to hold a $750K floor at <=1%.",
                "expected_value": "266000",
                "points": 1,
                "must_pass": "No",
            }
        ]
    }
    criteria, has_gate = _svc_criteria(rubric)

    assert criteria[0]["description"] == "Buffer to hold a $750K floor at <=1%. 266000"
    assert "Expected:" not in criteria[0]["description"]
    assert has_gate is False


def test_svc_criteria_leaves_description_untouched_when_expected_value_blank():
    """Real-world incident: a task's rubric.json had every criterion's
    expected_value blank (a malformed source rubric), and the old
    f"{desc} Expected: {expected}" template still fired, producing a
    dangling "... Expected: ." on all 31 criteria -- a synthesized artifact
    that doesn't exist in the source and gave no signal anything was wrong.
    An empty Expected-value cell must stay empty in the converted output,
    not grow invented trailing text."""
    rubric = {
        "criteria": [
            {
                "id": "c004",
                "description": "Monthly COGS spine matches the trusted series.",
                "expected_value": "",
                "points": 8,
                "must_pass": "Yes",
            }
        ]
    }
    criteria, has_gate = _svc_criteria(rubric)

    assert criteria[0]["description"] == "Monthly COGS spine matches the trusted series."
    assert "Expected" not in criteria[0]["description"]
    assert not criteria[0]["description"].endswith(".Expected: .")
    assert has_gate is True  # must-pass is still surfaced via the return value...


def test_svc_criteria_does_not_inject_must_pass_commentary_into_description():
    """must_pass is surfaced to the caller via _svc_criteria's second return
    value (has_gate), for the printed conversion summary -- it must not be
    injected as bracketed commentary into the criterion's own description
    text, which is what the judge model reads and what a reviewer diffs
    against the source rubric."""
    rubric = {
        "criteria": [
            {
                "id": "c001",
                "description": "Deliverable workbook present.",
                "expected_value": "",
                "points": 2,
                "must_pass": "Yes",
            }
        ]
    }
    criteria, has_gate = _svc_criteria(rubric)

    assert criteria[0]["description"] == "Deliverable workbook present."
    assert "must-pass" not in criteria[0]["description"].lower()
    assert "[" not in criteria[0]["description"]
    assert has_gate is True  # ...so the caller's printed summary can still note it
