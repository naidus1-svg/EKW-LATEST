"""Rubric text lint: a pure-text, zero-LLM, deterministic lint over a task's own
tests/deliverables*/judge.toml files, looking for three specific criterion-authoring defects
that no other check in this project catches.

Why this exists: a rubric criterion's description text can ask for something the grading
pipeline structurally cannot see, or can talk about the wrong deliverable format, or can ask
the solver to know things about its own grading that it has no way to know. None of these are
formula/value defects (formula_health_check.py's territory) or missing-file/package defects
(the structural-audit skill's territory) -- they are defects in the criterion *text itself*,
catchable by reading judge.toml alone, with no file opened beyond judge.toml itself.

Three sub-checks, each producing its own finding `kind`:

1. extraction_blind: a criterion description references a property that is invisible to a
   judge that reads the deliverable via text extraction (MarkItDown, openpyxl with
   data_only=True, a markdown export) rather than opening the real file in Excel/Word/
   PowerPoint. Confirmed this session against a real file: a formula cell formatted as a
   percentage (e.g. 0.0%) renders to the judge as a bare decimal -- the percentage formatting
   is gone by the time the judge sees it. The same blindness applies to currency formatting,
   data validation rules, cell/sheet protection, tab color, and hidden rows/sheets: all of
   these are workbook *metadata* that a text-extraction pass drops, not content a judge model
   can grade from the extracted text. A criterion asking the judge to confirm one of these is
   unpassable by construction, regardless of how the deliverable is actually built.

2. meta_rubric_knowledge: a criterion description asks the DELIVERABLE ITSELF to state
   something about the grading/rubric that produced it -- "all 50 criteria pass", "score is
   100/100", a self-check or self-assessment section. A solver never sees judge.toml (it is
   not part of the task's environment/ or initial_workspace/), so a criterion demanding the
   deliverable assert a fact about its own rubric is unpassable by any solver, correct or not.

3. stale_format_mismatch: a criterion description names a document format (Word document,
   Excel workbook/spreadsheet, PowerPoint/slide deck, or their extensions) that the SAME
   judge.toml's own `[judge].files = [...]` list does not actually include. This is the
   signature of a criterion authored against an earlier version of a task where the
   deliverable format changed (e.g. xlsx -> docx) and the criterion text was never updated.
   A file extension or format noun that IS one of the file(s) actually graded is never flagged,
   even if a task legitimately delivers multiple formats (e.g. one .xlsx AND one .pptx) --
   only a format named in the text but absent from every file in that judge.toml's own
   files=[...] is a mismatch.

Provenance: built fresh for this project (not extracted/generalized from an existing script)
against the same generic Harbor task package shape formula_health_check.py and the
structural-audit skill use: for each task, `<task_dir>/tests/deliverables*/judge.toml` files
with a `[judge]` table (`files = [...]`) and `[[criterion]]` blocks (`name`/`description`).

Status: v1. Verified this session against real tasks at
C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready/ -- see the accompanying verification
notes for which task ids were used as positive and negative controls for each sub-check.

Usage:
    python rubric_text_lint.py <TASK-ID> [<TASK-ID> ...] --root <path-to-task-dirs> --out report.json
    python rubric_text_lint.py --all --root <path-to-task-dirs> --out report.json
    python rubric_text_lint.py --all --root <path> --id-prefix MYBENCH- --out report.json

Known limits, disclosed rather than silently dropped:
    - All three checks are keyword/phrase matches against criterion description text, not a
      semantic read. A criterion that describes the same underlying defect in different words
      will not be caught; a criterion that uses one of these phrases in a context that is not
      actually a defect (rare, given how specific the phrases are) would be a false positive.
      Every finding carries the full description text so a human can immediately see which case
      it is.
    - stale_format_mismatch only looks at format nouns/extensions explicitly listed in
      FORMAT_GROUPS below (Word/docx, Excel/spreadsheet/xlsx, PowerPoint/slide deck/pptx). A
      task delivering some other format (e.g. .csv, .pdf) is not covered by this sub-check.
    - This script reads ONLY tests/deliverables*/judge.toml for each task. It does not open
      environment/, initial_workspace/, or solution/ -- it says nothing about whether the
      deliverable itself actually has the problem a criterion describes, only about the
      criterion text's own internal consistency and gradability.
"""

# Copied into turing-context on 2026-09-14 from harbor-qc-checks/rubric_text_lint.py.
# See tools/svc_qc_tracker_build.py CHECK_META["D"]["subchecks"]["D3"]. No logic changed.

import argparse
import json
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

# Windows console defaults to cp1252, which cannot encode every Unicode character that shows
# up in real judge.toml description text (curly quotes, em dashes, arrows). Force UTF-8 with
# replacement so a printable-but-non-cp1252 character never crashes the whole sweep partway
# through a batch.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# check 1: extraction_blind
# ---------------------------------------------------------------------------

EXTRACTION_BLIND_PATTERNS = [
    r"formula-driven",
    r"computed by formula",
    r"percentage formatted",
    r"currency formatted",
    r"data validation",
    r"cell(s)? (are|is) protected",
    r"formula cells are protected",
    r"tab color",
    r"hidden row",
    r"hidden sheet",
    r"number formatting is consistent",
    r"no hard-keyed",
    r"hard-keyed answer",
]

# ---------------------------------------------------------------------------
# check 2: meta_rubric_knowledge
# ---------------------------------------------------------------------------

META_RUBRIC_PATTERNS = [
    r"criteria pass",
    r"/100",
    r"self-check",
    r"self-assessment",
    r"rubric self",
    r"score is",
    r"all must-pass criteria clear",
]

# ---------------------------------------------------------------------------
# check 3: stale_format_mismatch
# ---------------------------------------------------------------------------

# Each group: the extension(s) that count as "this format IS present", and the phrases/
# extensions in description text that name this format. A group's keywords are only ever
# checked against a judge.toml whose files=[...] does NOT already include one of its own
# extensions -- naming a format that genuinely is one of the graded files is never a defect,
# even when another format is also present (e.g. one .xlsx AND one .pptx delivered together).
FORMAT_GROUPS = {
    "docx": {
        "extensions": {".docx", ".doc"},
        "keywords": [r"word document", r"\.docx"],
    },
    "xlsx": {
        "extensions": {".xlsx", ".xlsm"},
        "keywords": [r"excel workbook", r"spreadsheet", r"\.xlsx"],
    },
    "pptx": {
        "extensions": {".pptx", ".ppt"},
        "keywords": [r"powerpoint", r"slide deck", r"\.pptx"],
    },
}


# ---------------------------------------------------------------------------
# task/file discovery
# ---------------------------------------------------------------------------


def find_task_dirs(root, task_ids=None, id_prefix=""):
    if task_ids:
        dirs = []
        for tid in task_ids:
            p = root / tid
            if not p.is_dir():
                print(f"WARNING: task dir not found, skipping: {p}", file=sys.stderr)
                continue
            dirs.append(p)
        return dirs
    return sorted(
        p for p in root.iterdir() if p.is_dir() and p.name.startswith(id_prefix)
    )


def load_judge_files(task_dir):
    """Every tests/deliverables*/judge.toml under a task dir, parsed. Returns a list of dicts,
    one per judge.toml: {path (relative to task_dir), files: [...], criteria: [{name,
    description}], parse_error}. Never raises -- a judge.toml that fails to parse is reported
    as parse_error on its own entry, with zero criteria, rather than crashing the whole task.
    """
    out = []
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return out
    for jt in sorted(tests_dir.glob("deliverables*/judge.toml")):
        rel = str(jt.relative_to(task_dir)).replace("\\", "/")
        try:
            data = tomllib.loads(jt.read_text(encoding="utf-8"))
        except Exception as e:
            out.append(
                {"path": rel, "files": [], "criteria": [], "parse_error": str(e)}
            )
            continue
        judge = data.get("judge", {}) or {}
        files = judge.get("files", []) or []
        criteria = [
            {"name": c.get("name"), "description": c.get("description") or ""}
            for c in data.get("criterion", [])
        ]
        out.append(
            {"path": rel, "files": files, "criteria": criteria, "parse_error": None}
        )
    return out


# ---------------------------------------------------------------------------
# the three checks
# ---------------------------------------------------------------------------


# A meta_rubric_knowledge keyword match sitting just after a negation cue ("contains no
# grading/rubric/scoring/self-assessment content") is the OPPOSITE of the defect: it is a
# well-formed anti-leakage criterion demanding the deliverable NOT talk about its own grading,
# not a criterion demanding it DOES. Confirmed as a real false-positive shape this session:
# "self-assessment" alone, ungated, flags every one of SVC-PC-93-2-0 through 93-6-0's "no
# grading content" criteria. Scoped to meta_rubric_knowledge only -- extraction_blind and
# stale_format_mismatch findings do not have a comparable negated-is-fine reading.
NEGATION_WINDOW = 40
NEGATION_RE = re.compile(
    r"\b(no|not|zero|without|free of|exclude[sd]?|excluding|absent|none of|containing no)\b",
    re.IGNORECASE,
)


def check_keyword_patterns(kind, patterns, file_rel, criteria, negation_guard=False):
    """Shared implementation for extraction_blind and meta_rubric_knowledge: both are a flat
    list of case-insensitive phrase/regex patterns checked against every criterion's
    description. One finding per (criterion, matched pattern) -- a description matching two
    different keywords produces two findings, each naming its own matched text, so nothing is
    collapsed away.

    negation_guard=True (meta_rubric_knowledge only) skips a match preceded within
    NEGATION_WINDOW characters by a negation cue -- see NEGATION_RE's docstring above.
    """
    findings = []
    for c in criteria:
        desc = c["description"]
        for pat in patterns:
            m = re.search(pat, desc, re.IGNORECASE)
            if not m:
                continue
            if negation_guard:
                window = desc[max(0, m.start() - NEGATION_WINDOW) : m.start()]
                if NEGATION_RE.search(window):
                    continue
            findings.append(
                {
                    "kind": kind,
                    "file": file_rel,
                    "criterion": c["name"],
                    "matched": m.group(0),
                    "description": desc,
                }
            )
    return findings


def check_stale_format_mismatch(file_rel, files_list, criteria):
    present_exts = {Path(f).suffix.lower() for f in files_list if Path(f).suffix}
    if not present_exts:
        return []

    findings = []
    for c in criteria:
        desc = c["description"]
        for group in FORMAT_GROUPS.values():
            if group["extensions"] & present_exts:
                # this format IS one of the files actually graded here -- naming it is
                # correct, not stale, even if another format is also present.
                continue
            for kw_pattern in group["keywords"]:
                m = re.search(kw_pattern, desc, re.IGNORECASE)
                if m:
                    findings.append(
                        {
                            "kind": "stale_format_mismatch",
                            "file": file_rel,
                            "criterion": c["name"],
                            "matched": m.group(0),
                            "description": desc,
                            "files_extensions": sorted(present_exts),
                        }
                    )
                    break  # one finding per (criterion, competing format group)
    return findings


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(task_dir):
    task_id = task_dir.name
    judge_files = load_judge_files(task_dir)

    result = {
        "task_id": task_id,
        "files_scanned": [jf["path"] for jf in judge_files if not jf["parse_error"]],
        "findings": [],
        "errors": [],
    }

    if not judge_files:
        result["errors"].append(
            "no tests/deliverables*/judge.toml found for this task -- nothing for this "
            "lint to check"
        )
        result["summary"] = {"n_findings": 0, "by_kind": {}}
        return result

    for jf in judge_files:
        if jf["parse_error"]:
            result["errors"].append(
                f"{jf['path']}: judge.toml failed to parse: {jf['parse_error']}"
            )
            continue
        rel = jf["path"]
        criteria = jf["criteria"]
        result["findings"].extend(
            check_keyword_patterns(
                "extraction_blind", EXTRACTION_BLIND_PATTERNS, rel, criteria
            )
        )
        result["findings"].extend(
            check_keyword_patterns(
                "meta_rubric_knowledge",
                META_RUBRIC_PATTERNS,
                rel,
                criteria,
                negation_guard=True,
            )
        )
        result["findings"].extend(
            check_stale_format_mismatch(rel, jf["files"], criteria)
        )

    by_kind = {}
    for f in result["findings"]:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
    result["summary"] = {"n_findings": len(result["findings"]), "by_kind": by_kind}
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(
        description="Pure-text lint over a task's own tests/deliverables*/judge.toml "
        "criteria: extraction-blind properties, meta-rubric-knowledge asks, and stale "
        "document-format mentions."
    )
    ap.add_argument(
        "task_ids",
        nargs="*",
        help="one or more task ids (directory names under --root)",
    )
    ap.add_argument(
        "--all", action="store_true", help="run every task directory found under --root"
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=None,
        required=False,
        help="root directory containing one subdirectory per task (REQUIRED -- no default, "
        "this must not silently assume a project-specific path)",
    )
    ap.add_argument(
        "--id-prefix",
        default="",
        help="when using --all, only treat subdirectories starting with this prefix as tasks "
        "(default: empty, i.e. every subdirectory is treated as a task)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the aggregate JSON report here (default: print summary only)",
    )
    args = ap.parse_args()

    if args.root is None:
        ap.error(
            "--root is required (point it at the directory containing your task folders)"
        )

    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")

    task_dirs = find_task_dirs(
        args.root, None if args.all else args.task_ids, id_prefix=args.id_prefix
    )
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        sys.exit(1)

    results = []
    for i, task_dir in enumerate(task_dirs, 1):
        print(f"[{i}/{len(task_dirs)}] {task_dir.name} ...", file=sys.stderr)
        try:
            r = analyze_task(task_dir)
        except Exception as e:  # never let one task's crash kill the whole batch
            r = {
                "task_id": task_dir.name,
                "files_scanned": [],
                "findings": [],
                "errors": [f"unhandled exception analyzing this task: {e}"],
                "summary": {"n_findings": 0, "by_kind": {}},
            }
        results.append(r)
        print(
            f"    -> {r['summary']['n_findings']} finding(s)  "
            f"({len(r.get('errors', []))} errors)",
            file=sys.stderr,
        )

    n_findings_total = sum(r["summary"]["n_findings"] for r in results)
    n_clean = sum(1 for r in results if r["summary"]["n_findings"] == 0)
    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "n_tasks": len(results),
        "results": results,
    }

    print(
        f"\n{n_clean}/{len(results)} task(s) clean, {n_findings_total} total finding(s)"
    )
    for r in results:
        kinds = ", ".join(
            f"{k}={v}" for k, v in r.get("summary", {}).get("by_kind", {}).items()
        )
        status = "clean" if r["summary"]["n_findings"] == 0 else "flagged"
        print(f"  {r['task_id']}: {status}" + (f"  [{kinds}]" if kinds else ""))
        for e in r.get("errors", []):
            print(f"      ! {e}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
