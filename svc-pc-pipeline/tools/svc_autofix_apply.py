#!/usr/bin/env python3
"""Apply the SVC auto-fix recipes to a scan's mechanical bucket, and write
proposed-diff artifacts for its content_review bucket.

Mechanical recipes (format_convention / pipeline_packaging Defect Class) are
ported from the two live, uncommitted fixes in C:\\ekwqc\\repo
(turing-genai-apps/EKW_QC_pipeline) as of 2026-09-12:

    apply_header_alias_fix    ports pipeline/tools/rubric_xlsx_to_verifier.py's
                               FIELD_HEADER_SUBSTRINGS["expected_value"] fix
                               (adds "acceptance standard" as a third alias)
    build_hydration_placeholder_message
                               ports pipeline/tools/hydrate_environment.py's
                               hydrate() placeholder-message branch (lines
                               ~315-352 in the live working tree)

plus two new recipes for this skill:

    prompt_copy_resync        one-directional instruction.md -> tests/task_prompt.txt
                               sync; refuses outright if ever called in reverse
    render_formatted_value    renders a raw numeric cell per its own Excel
                               number_format, for judges that were shown
                               unformatted floats instead of currency/percent

Content-class findings (content_substance / design_intent) never get a mutating
write against a live task file -- write_content_diff_artifact() only ever
writes into a separate diffs directory, for a human to review via Jafar's
existing QC pass.

Hard guard (non-negotiable, ekw/CLAUDE.md "never put the answer key in front
of the graded party"): any write this tool makes to a solver-facing path --
a file literally named instruction.md, or any path under an "environment"
directory -- is scanned first, in memory, against every expected-value /
tolerance / grading-criterion string pulled from the task's own tests/
verifier.json. If any of those strings appears verbatim in the content about
to be written, the write is refused and reported, never silently applied.
Non-solver-facing writes (verifier.json, tests/task_prompt.txt, the diff
artifacts) don't carry this specific risk by construction and are not
guard-scanned -- see is_solver_facing().

    python tools/svc_autofix_apply.py --scan ekw/svc-autofix-scan-2026-09-12.json
    python tools/svc_autofix_apply.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_APPLY_OUT = REPO_ROOT / "ekw" / "svc-autofix-apply-2026-09-12.json"
DEFAULT_DIFF_DIR = REPO_ROOT / "ekw" / "svc-autofix-diffs-2026-09-12"
DEFAULT_SEARCH_ROOTS = [
    Path(r"C:\ekwqc\corpus"),
    Path(r"C:\ekwqc\repo\pipeline\data"),
    REPO_ROOT / "ekw",
]

HEADER_ALIASES_OLD = ["expected value", "expected"]
HEADER_ALIASES_NEW = ["expected value", "expected", "acceptance standard"]
EXPECTED_FRAGMENT_RE = re.compile(r"Expected:\s*.*?\.(?=\s+[A-Z]|\s*$)")


class GuardRefused(Exception):
    pass


def is_solver_facing(path: Path) -> bool:
    if path.name.lower() == "instruction.md":
        return True
    return any(part.lower() == "environment" for part in path.parts)


def extract_protected_strings(verifier_json_path: Path, min_len: int = 8) -> set[str]:
    """Every expected-value / tolerance string a solver must never see, pulled
    from the task's own tests/verifier.json. Fragments shorter than min_len
    are dropped so the guard doesn't refuse a write over trivial incidental
    overlap (a bare number, a common word)."""
    data = json.loads(verifier_json_path.read_text(encoding="utf-8"))
    protected: set[str] = set()
    for v in data.get("verifiers", []):
        rubric = (v.get("assertion") or {}).get("rubric") or {}
        prompt = rubric.get("prompt", "")
        m = EXPECTED_FRAGMENT_RE.search(prompt)
        if m:
            value = m.group(0)[len("Expected:") : -1].strip()
            if len(value) >= min_len:
                protected.add(value)
        tolerance = (v.get("metadata") or {}).get("tolerance") or {}
        source_text = tolerance.get("source_text", "")
        if len(source_text) >= min_len:
            protected.add(source_text)
    return protected


def hard_guard_scan(new_content: str, protected_strings: set[str]) -> list[str]:
    """Every protected string found verbatim in new_content. Empty means safe."""
    return sorted(s for s in protected_strings if s and s in new_content)


def guarded_write(path: Path, new_content: str, protected_strings: set[str]) -> dict:
    if is_solver_facing(path):
        leaks = hard_guard_scan(new_content, protected_strings)
        if leaks:
            return {
                "written": False,
                "refused": True,
                "path": str(path),
                "leaked_strings": leaks,
            }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_content, encoding="utf-8")
    return {"written": True, "refused": False, "path": str(path)}


def find_header_row(ws, aliases: list[str]) -> "tuple[int, list[str], int] | None":
    for row_idx in range(1, min(30, ws.max_row) + 1):
        cells = [
            str(c.value).strip() if c.value is not None else "" for c in ws[row_idx]
        ]
        lowered = [c.lower() for c in cells]
        for col_idx, text in enumerate(lowered):
            if any(alias in text for alias in aliases):
                return row_idx, cells, col_idx
    return None


def apply_header_alias_fix(rubric_xlsx: Path, verifier_json: Path) -> dict:
    """Ports C:\\ekwqc\\repo pipeline/tools/rubric_xlsx_to_verifier.py's live,
    uncommitted fix: adding "acceptance standard" as a third alias for the
    expected_value column, so a rubric naming that column "Acceptance
    Standard" no longer resolves to a blank "Expected: ." on every criterion.
    Rebuilds only the "Expected: <value>." fragment of each affected
    verifier's rubric prompt, matched by metadata.tag == criterion_id.lower()
    (the same key build_verifier_json assigns) -- every other field is left
    untouched."""
    wb = openpyxl.load_workbook(rubric_xlsx, data_only=True)
    ws = wb.active
    old_hit = find_header_row(ws, HEADER_ALIASES_OLD)
    new_hit = find_header_row(ws, HEADER_ALIASES_NEW)
    if new_hit is None:
        return {
            "changed": False,
            "reason": "no expected-value-like column under the new alias set either",
        }
    header_row, header_cells, new_col = new_hit
    if old_hit is not None and old_hit[2] == new_col:
        return {
            "changed": False,
            "reason": "old alias set already resolves this column, nothing to fix",
        }

    id_col = next(
        (i for i, t in enumerate(header_cells) if t.strip().lower() == "id"),
        None,
    )
    if id_col is None:
        return {
            "changed": False,
            "reason": "no criterion id column found, cannot map rows to verifier.json",
        }

    expected_by_id = {}
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        if id_col >= len(row) or row[id_col] is None:
            continue
        cid = str(row[id_col]).strip()
        if not cid:
            continue
        val = row[new_col] if new_col < len(row) else None
        expected_by_id[cid.lower()] = str(val).strip() if val is not None else ""

    verifier = json.loads(verifier_json.read_text(encoding="utf-8"))
    fixed_criteria = []
    for v in verifier.get("verifiers", []):
        tag = (v.get("metadata") or {}).get("tag", "")
        new_expected = expected_by_id.get(tag)
        if not new_expected:
            continue
        rubric = v.get("assertion", {}).get("rubric", {})
        prompt = rubric.get("prompt", "")
        if EXPECTED_FRAGMENT_RE.search(prompt):
            current = EXPECTED_FRAGMENT_RE.search(prompt).group(0)
            if current == f"Expected: {new_expected}.":
                continue
            rubric["prompt"] = EXPECTED_FRAGMENT_RE.sub(
                f"Expected: {new_expected}.", prompt, count=1
            )
        else:
            rubric["prompt"] = f"{prompt} Expected: {new_expected}."
        fixed_criteria.append(tag)

    if not fixed_criteria:
        return {
            "changed": False,
            "reason": "new alias resolved a column, but no criterion needed its Expected: fragment rebuilt",
        }

    protected_strings = extract_protected_strings(verifier_json)
    write_result = guarded_write(
        verifier_json, json.dumps(verifier, indent=2), protected_strings
    )
    return {
        "changed": write_result["written"],
        "fixed_criteria": fixed_criteria,
        "write": write_result,
    }


def prompt_copy_resync(source_path: Path, dest_path: Path) -> dict:
    """One-directional resync: instruction.md (solver-facing, already vetted)
    -> tests/task_prompt.txt (grader-facing copy). Never the reverse -- that
    direction could pull judge-only content (deliverable filenames, grading
    guidance) into the file the solver actually reads. Hard-refuses outright
    if ever called with dest_path pointed at instruction.md, independent of
    the guard's content scan below."""
    if dest_path.name.lower() == "instruction.md":
        raise GuardRefused(
            f"prompt_copy_resync refused: dest {dest_path} is instruction.md, "
            "the solver-facing file -- this recipe is one-directional and may "
            "never write into it"
        )
    if not source_path.exists():
        return {"changed": False, "reason": f"source {source_path} does not exist"}
    new_content = source_path.read_text(encoding="utf-8")
    if dest_path.exists() and dest_path.read_text(encoding="utf-8") == new_content:
        return {"changed": False, "reason": "already in sync"}
    verifier_json = dest_path.parent / "verifier.json"
    protected_strings = (
        extract_protected_strings(verifier_json) if verifier_json.exists() else set()
    )
    write_result = guarded_write(dest_path, new_content, protected_strings)
    return {"changed": write_result["written"], "write": write_result}


def render_formatted_value(value, number_format: str) -> str:
    """Render a raw numeric cell per its own Excel number_format, so a judge
    reading extracted text sees "$141,553.40" / "62.59%" instead of the bare
    float a data_only=True extraction otherwise hands it."""
    if value is None:
        return ""
    if not isinstance(value, (int, float)):
        return str(value)
    fmt = number_format or "General"
    if "%" in fmt:
        decimals = len(fmt.split(".")[-1].split("%")[0]) if "." in fmt else 0
        return f"{value * 100:.{decimals}f}%"
    is_currency = "$" in fmt
    decimals = 0
    if "." in fmt:
        frac = fmt.split(".")[-1]
        decimals = sum(1 for ch in frac if ch in "0#")
    if "#,##0" in fmt or "#,###" in fmt:
        rendered = f"{value:,.{decimals}f}"
    elif decimals or "0" in fmt:
        rendered = f"{value:.{decimals}f}"
    else:
        rendered = str(value)
    return f"${rendered}" if is_currency else rendered


def extract_formatted_cells(xlsx_path: Path, sheet_name: "str | None" = None) -> dict:
    """data_only=True gives calculated values, data_only=False preserves
    number_format reliably alongside the formula text -- read both workbooks
    so a currency/percentage cell renders correctly even on a workbook saved
    without recalculation (the known verifier-extraction gap the
    tp-fp-classification SKILL.md's Methodology step 5 names)."""
    wb_values = openpyxl.load_workbook(xlsx_path, data_only=True)
    wb_formulas = openpyxl.load_workbook(xlsx_path, data_only=False)
    ws_values = wb_values[sheet_name] if sheet_name else wb_values.active
    ws_formulas = wb_formulas[sheet_name] if sheet_name else wb_formulas.active
    out = {}
    for row in ws_values.iter_rows():
        for cell in row:
            fcell = ws_formulas[cell.coordinate]
            out[cell.coordinate] = {
                "raw_value": cell.value,
                "number_format": fcell.number_format,
                "formatted": render_formatted_value(cell.value, fcell.number_format),
            }
    wb_values.close()
    wb_formulas.close()
    return out


def build_hydration_placeholder_message(
    l1_files_count: int,
    manifest_paths_count: int,
    prompt_candidates_count: int,
    unresolved_prompt_names: list[str],
    manifest_not_found: list[str],
) -> str:
    """Verbatim port of C:\\ekwqc\\repo pipeline/tools/hydrate_environment.py's
    live, uncommitted fix (hydrate(), lines ~315-352): the old code always
    wrote "confirmed reasoning-only" into _no_input_files_required.txt
    whenever out_dir ended up empty, even when resolution had actually failed
    and simply produced nothing. This version tells those two cases apart."""
    if unresolved_prompt_names or (manifest_paths_count and manifest_not_found):
        msg = (
            "This task requested input files but resolution failed. Unresolved names:\n"
        )
        for name in unresolved_prompt_names:
            msg += f"  - {name}\n"
        for entry in manifest_not_found:
            msg += f"  - {entry}\n"
        msg += "This is a hydration gap requiring manual review.\n"
        return msg
    if l1_files_count or manifest_paths_count or prompt_candidates_count:
        return (
            "Hydration found candidates (L1 folders, manifest entries, or prompt-named files) "
            "but nothing resolved successfully. Review resolution errors above. "
            "This is a hydration gap.\n"
        )
    return (
        "This task's prompt names no specific input files, has no L1-* "
        "upstream outputs, and declares no Read Me input manifest entries "
        "-- appears to be reasoning-only.\n"
    )


def find_local_task_dir(task_id: str, search_roots: list[Path]) -> "Path | None":
    normalized = task_id.lower()
    for root in search_roots:
        if not root.exists():
            continue
        for candidate in root.rglob("*"):
            if candidate.is_dir() and candidate.name.lower() == normalized:
                return candidate
    return None


def apply_mechanical_finding(finding: dict, search_roots: list[Path]) -> dict:
    task_id = str(finding.get("QC Issues Task ID", ""))
    task_dir = find_local_task_dir(task_id, search_roots)
    if task_dir is None:
        return {
            "finding_id": finding.get("_finding_id"),
            "task_id": task_id,
            "status": "skipped_no_local_package",
        }
    recipe_results = []
    rubric_candidates = [
        p for p in task_dir.rglob("*.xlsx") if "rubric" in p.name.lower()
    ]
    verifier_path = task_dir / "tests" / "verifier.json"
    if rubric_candidates and verifier_path.exists():
        recipe_results.append(
            {
                "recipe": "header_alias_fix",
                **apply_header_alias_fix(rubric_candidates[0], verifier_path),
            }
        )
    instruction_path = task_dir / "instruction.md"
    prompt_copy_path = task_dir / "tests" / "task_prompt.txt"
    if instruction_path.exists():
        recipe_results.append(
            {
                "recipe": "prompt_copy_resync",
                **prompt_copy_resync(instruction_path, prompt_copy_path),
            }
        )
    applied = any(r.get("changed") for r in recipe_results)
    return {
        "finding_id": finding.get("_finding_id"),
        "task_id": task_id,
        "status": "applied" if applied else "no_defect_confirmed",
        "recipes": recipe_results,
    }


def write_content_diff_artifact(finding: dict, out_dir: Path) -> Path:
    task_id = str(finding.get("QC Issues Task ID", "unknown"))
    lines = [
        f"Task: {task_id}",
        f"Finding: {finding.get('_finding_id')}",
        f"Defect Class: {finding.get('Defect Class', '')}",
        f"Auto-Verdict: {finding.get('Auto-Verdict', '')}",
        f"Fix Title: {finding.get('Fix Title', '')}",
        "",
        "--- issue description ---",
        str(finding.get("Issue Description", "")),
        "",
        "--- evidence excerpt (current state) ---",
        str(finding.get("Evidence Excerpt", "")),
        "",
        "--- evidence reference ---",
        str(finding.get("Evidence Reference (path)", "")),
        "",
        "--- proposed fix guidance (for human review, not auto-applied) ---",
        str(finding.get("Actionable Fix Guidance", "")),
        "",
        "--- reviewer disposition ---",
        "This is a proposed content/rubric fix. No live task file has been modified.",
        "Route through Jafar's existing QC review pass before applying.",
    ]
    content = "\n".join(lines) + "\n"
    safe_task = re.sub(r"[^a-z0-9\-]+", "-", task_id.lower()).strip("-")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{safe_task}__row{finding.get('_row', 0)}.diff.txt"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def run_selftest() -> bool:
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(
            [
                "ID",
                "Category",
                "Description",
                "Acceptance Standard",
                "Points",
                "Must-pass?",
            ]
        )
        ws.append(
            [
                "C01",
                "Revenue",
                "Revenue must be stated correctly",
                "$1,234,567",
                50,
                "Y",
            ]
        )
        ws.append(["C02", "Growth", "Growth rate must be reported", "12.5%", 50, "N"])
        rubric_path = tmp_path / "Grading_Rubric.xlsx"
        wb.save(rubric_path)

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        verifier_path = tests_dir / "verifier.json"
        verifier_path.write_text(
            json.dumps(
                {
                    "verifiers": [
                        {
                            "metadata": {"tag": "c01"},
                            "assertion": {
                                "rubric": {
                                    "prompt": "Revenue must be stated correctly Expected: ."
                                }
                            },
                        },
                        {
                            "metadata": {"tag": "c02"},
                            "assertion": {
                                "rubric": {
                                    "prompt": "Growth rate must be reported Expected: ."
                                }
                            },
                        },
                    ]
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        result = apply_header_alias_fix(rubric_path, verifier_path)
        rebuilt = json.loads(verifier_path.read_text(encoding="utf-8"))
        prompts = {
            v["metadata"]["tag"]: v["assertion"]["rubric"]["prompt"]
            for v in rebuilt["verifiers"]
        }
        header_alias_ok = (
            result.get("changed") is True
            and prompts["c01"]
            == "Revenue must be stated correctly Expected: $1,234,567."
            and prompts["c02"] == "Growth rate must be reported Expected: 12.5%."
        )
        print(
            f"[selftest] header_alias_fix: {'PASS' if header_alias_ok else 'FAIL'} -> {result}"
        )
        ok = ok and header_alias_ok

        instruction_path = tmp_path / "instruction.md"
        instruction_path.write_text(
            "Please compile the quarterly report.\n", encoding="utf-8"
        )
        resync_result = prompt_copy_resync(
            instruction_path, tests_dir / "task_prompt.txt"
        )
        resync_ok = resync_result.get("changed") is True and (
            tests_dir / "task_prompt.txt"
        ).read_text(encoding="utf-8") == instruction_path.read_text(encoding="utf-8")
        print(
            f"[selftest] prompt_copy_resync (forward): {'PASS' if resync_ok else 'FAIL'} -> {resync_result}"
        )
        ok = ok and resync_ok

        reversed_refused = False
        try:
            prompt_copy_resync(tests_dir / "task_prompt.txt", instruction_path)
        except GuardRefused:
            reversed_refused = True
        print(
            f"[selftest] prompt_copy_resync (reverse direction refused): {'PASS' if reversed_refused else 'FAIL'}"
        )
        ok = ok and reversed_refused

        fmt_ok = (
            render_formatted_value(141553.398058, '"$"#,##0.00') == "$141,553.40"
            and render_formatted_value(0.625865, "0.00%") == "62.59%"
        )
        print(f"[selftest] render_formatted_value: {'PASS' if fmt_ok else 'FAIL'}")
        ok = ok and fmt_ok

        placeholder_gap = build_hydration_placeholder_message(
            0, 1, 0, [], ["manifest:missing_file.csv"]
        )
        placeholder_clean = build_hydration_placeholder_message(0, 0, 0, [], [])
        placeholder_ok = (
            "hydration gap requiring manual review" in placeholder_gap
            and "appears to be reasoning-only" in placeholder_clean
        )
        print(
            f"[selftest] build_hydration_placeholder_message: {'PASS' if placeholder_ok else 'FAIL'}"
        )
        ok = ok and placeholder_ok

        leak_verifier_dir = tmp_path / "guard_test" / "tests"
        leak_verifier_dir.mkdir(parents=True)
        leak_verifier_path = leak_verifier_dir / "verifier.json"
        leak_verifier_path.write_text(
            json.dumps(
                {
                    "verifiers": [
                        {
                            "metadata": {"tag": "r1"},
                            "assertion": {
                                "rubric": {
                                    "prompt": "Net revenue variance must be reconciled Expected: $4,821,309.12 net revenue variance for Q3."
                                }
                            },
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        protected = extract_protected_strings(leak_verifier_path)
        leaking_content = (
            "Reconcile the quarterly figures. As computed, $4,821,309.12 net revenue "
            "variance for Q3 should be reported in the summary table.\n"
        )
        leaked_instruction = leak_verifier_dir.parent / "instruction.md"
        leak_write = guarded_write(leaked_instruction, leaking_content, protected)
        guard_caught_leak = (
            leak_write["written"] is False
            and leak_write["refused"] is True
            and "$4,821,309.12 net revenue variance for Q3"
            in leak_write["leaked_strings"]
            and not leaked_instruction.exists()
        )
        print(
            f"[selftest] hard guard CATCHES planted leak: {'PASS' if guard_caught_leak else 'FAIL'} -> {leak_write}"
        )
        ok = ok and guard_caught_leak

        clean_content = "Reconcile the quarterly figures and summarize the outcome.\n"
        clean_write = guarded_write(leaked_instruction, clean_content, protected)
        guard_allows_clean = (
            clean_write["written"] is True
            and clean_write["refused"] is False
            and leaked_instruction.exists()
            and leaked_instruction.read_text(encoding="utf-8") == clean_content
        )
        print(
            f"[selftest] hard guard ALLOWS clean write: {'PASS' if guard_allows_clean else 'FAIL'} -> {clean_write}"
        )
        ok = ok and guard_allows_clean

    print(f"[selftest] OVERALL: {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--scan", type=Path, default=None)
    p.add_argument("--out", type=Path, default=DEFAULT_APPLY_OUT)
    p.add_argument("--diff-dir", type=Path, default=DEFAULT_DIFF_DIR)
    p.add_argument("--search-root", type=Path, action="append", default=None)
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()

    if args.selftest:
        raise SystemExit(0 if run_selftest() else 1)

    if args.scan is None:
        raise SystemExit("--scan is required unless --selftest is passed")

    scan = json.loads(args.scan.read_text(encoding="utf-8"))
    buckets = scan["buckets"]
    search_roots = args.search_root or DEFAULT_SEARCH_ROOTS

    mechanical_results = [
        apply_mechanical_finding(f, search_roots) for f in buckets.get("mechanical", [])
    ]
    applied = sum(1 for r in mechanical_results if r["status"] == "applied")
    skipped_no_pkg = sum(
        1 for r in mechanical_results if r["status"] == "skipped_no_local_package"
    )
    no_defect = sum(
        1 for r in mechanical_results if r["status"] == "no_defect_confirmed"
    )

    diff_paths = [
        str(write_content_diff_artifact(f, args.diff_dir).relative_to(REPO_ROOT))
        for f in buckets.get("content_review", [])
    ]

    result = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "scan_input": str(args.scan),
        "mechanical": {
            "total": len(mechanical_results),
            "applied": applied,
            "skipped_no_local_package": skipped_no_pkg,
            "no_defect_confirmed": no_defect,
            "details": mechanical_results,
        },
        "content_review": {
            "total": len(diff_paths),
            "diff_dir": str(args.diff_dir.relative_to(REPO_ROOT)),
            "diff_files": diff_paths,
        },
        "no_action": {"total": len(buckets.get("no_action", []))},
        "needs_human": {"total": len(buckets.get("needs_human", []))},
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    print(f"Wrote {args.out}")
    print(
        f"Mechanical: {len(mechanical_results)} findings, {applied} applied, "
        f"{skipped_no_pkg} skipped (no local task package found), {no_defect} no defect confirmed"
    )
    print(
        f"Content review: {len(diff_paths)} diff artifacts written to {args.diff_dir}"
    )
    print(f"No action: {result['no_action']['total']}")
    print(f"Needs human: {result['needs_human']['total']}")


if __name__ == "__main__":
    main()
