#!/usr/bin/env python3
"""Judge file-size cliff check (row 31): WARN-tier advisory that flags tasks whose
environment corpus contains data-shaped files large enough that a compliant solver
embedding them into the graded deliverable could plausibly produce a submission
exceeding harbor-rewardkit's 1 MiB silent-truncation cliff.

WHY THIS EXISTS

harbor-rewardkit's judges.py defines ``_MAX_FILE_SIZE = 1024 * 1024`` (1 MiB) and
silently replaces any graded file over that size with the literal text
``"[skipped: file too large]"`` before the LLM judge ever sees it (confirmed by
reading rewardkit/judges.py lines 144/180-181 in both the installed 0.2.0 and the
0.1.7 extraction; the behavior is unchanged across both versions). Two real
incidents motivated this check:

  - SVC-PC-66-2-0: a 1,112,742-byte compliant SOLVER SUBMISSION was truncated and
    scored 0.0 because the judge saw "[skipped: file too large]" instead of the
    workbook.
  - SVC-PC-52-6-0: a 1,675-formula all-NaN-cached SOLVER SUBMISSION scored 1.0
    because the judge could not tell a live workbook from a dead one. This is a
    formula-health issue (already covered by formula_health_check.py), not a
    cliff issue, but the task shares the same large corpus subtree that makes
    bloat physically possible.

A prior round drafted a checker that tested whether GOLDEN reference files exceed
1 MiB. Two validation passes found 0/202 goldens exceed 1 MiB: goldens are always
small curated reference files. That checker cannot catch anything because it
validates against the wrong population. The truncation applies to the SOLVER
SUBMISSION (the graded file), not the golden.

WHY GOLDEN STRUCTURAL COMPLEXITY WAS INVESTIGATED AND REJECTED

The brief suggested building a size-risk heuristic from the golden's own structural
complexity (formula count, sheet count, row/column extent) as a proxy for how large
a compliant submission could grow. This was investigated for real against the full
202-task SVC-PC subset (openpyxl parse of every xlsx golden, measuring sheets,
formulas, max rows, max cols). The result is conclusive: the heuristic CANNOT work.

The incident task's golden (SVC-PC-66-2-0: 7 sheets, 45 formulas, 25 max rows, 6
max cols) sits at the MEDIAN of every structural complexity metric across the
corpus (corpus medians: 7 sheets, 42 formulas, 34 max rows, 9 max cols). Any
threshold that flags the incident task flags roughly half the corpus. Any
threshold selective enough to flag a small fraction misses the incident entirely.
Golden structural complexity cannot distinguish the incident task from ~100
others because the bloat does not come from the deliverable SHAPE being complex:
it comes from the solver embedding source DATA into the deliverable. The golden
is always small because it is a curated answer that does not carry the raw source
data; a compliant solver rebuilds the deliverable from that data and may keep it
embedded. The golden's complexity measures the answer's shape, not the data
volume that drives bloat.

WHAT THIS CHECK MEASURES INSTEAD

The environment's data file sizes: the ACTUAL source of bloat. The environment IS
part of the task package, so this is a real per-task signal from the task package
alone, with no submissions corpus needed. It walks the environment workspace
(environment/initial_workspace/ for SVC-PC, environment/data/ for EKW: same
WORKSPACE_DIRNAME_BY_FORMAT split environment_input_check.py established) and
measures every data-shaped file (csv, json, xlsx, xls, xml, tsv, parquet). The
largest single data file is the primary "bloat fuel" metric: a solver building a
workbook from a 4 MiB CSV export has enough data available that embedding even a
fraction of it pushes the submission past the cliff.

THRESHOLD (NAMED, NOT ARBITRARY)

256 KiB = 262,144 bytes = cliff / 4x overhead.

The reasoning, grounded in the format and the one real data point:

  - The cliff is 1,048,576 bytes (1 MiB, confirmed from rewardkit source).
  - An xlsx embedding tabular data from a source file incurs roughly 3-5x
    overhead (OOXML XML wrapping, shared-strings table, cell metadata). This is
    a well-known property of the xlsx format, not an assumption.
  - At 4x overhead (the middle estimate), a 256 KiB source file produces 1 MiB of
    xlsx content: exactly the cliff. Adding the golden's own ~17-50 KiB pushes
    the total past it.
  - The incident data point confirms this: SVC-PC-66-2-0's environment had a
    4,021,135-byte orders_export_1.csv. The solver embedded roughly 7% of it
    (about 274 KiB of source data at 4x overhead) to produce a 1,112,742-byte
    submission. A source file of 256 KiB is enough to reproduce this.
  - This is ONE data point, not a validated ratio. The threshold is named
    ("cliff-equivalent single-file size at 4x xlsx overhead") and grounded in
    the format property, not overfit to the incident.

The 202-task corpus's largest-data-file distribution is bimodal: files are either
small (under 100 KiB, personal template files) or large (3.5-4 MiB, shared
corpus exports). Any threshold between 256 KiB and 3.5 MiB flags the same 89
xlsx-golden tasks, so the exact threshold value is not sensitive in practice:
the bimodality means the threshold separates "has large shared corpus data"
from "does not" cleanly, with no tasks sitting in the ambiguous middle.

WHAT IT FLAGS

WARN (never FAIL) when BOTH conditions hold:
  1. The golden deliverable is an xlsx (the data-accumulating format where
     embedding source data is the natural construction approach). Non-xlsx
     goldens (docx, pptx) are not flagged: the bloat mechanism is different and
     not calibrated against any real incident. This is a disclosed coverage gap,
     not a hidden one.
  2. The environment's largest data-shaped file (csv/json/xlsx/xml/tsv/parquet)
     is at least 256 KiB (262,144 bytes).

WARN, not FAIL, because whether the solver actually embeds the data depends on
the solver's approach, not the task package. This check can only say the
environment HAS enough data to push a compliant submission past the cliff, not
that it WILL.

THE REAL FIX BELONGS IN harbor-rewardkit

The truncation is SILENT: the file is replaced with "[skipped: file too large]"
with no error, no warning to the pipeline, and no visible marker the judge LLM
can recognize as a truncation. Making it LOUD (raising an error that blocks
grading, or injecting a marker the judge is prompted to treat as a hard zero)
would prevent both incident classes at the source. This per-task check is a
COMPLEMENTARY advisory that surfaces which tasks carry the most risk so the
pipeline can prioritize the harness fix or pre-check submission sizes before
grading. It is not a replacement for fixing rewardkit.

KNOWN LIMITS (disclosed, not hidden)

  - xlsx-only: the check flags tasks with xlsx goldens. A docx or pptx golden
    with a large environment is not flagged (different bloat mechanism, no
    calibration data). The cliff applies to any file format, but only the xlsx
    embedding mechanism has a real incident to calibrate against.
  - Bimodal threshold insensitivity: because the corpus's largest-data-file
    distribution is bimodal (small personal files vs large shared corpus
    exports), the exact threshold between 256 KiB and 3.5 MiB does not change
    which tasks are flagged. The 256 KiB threshold is the most conservative
    (lowest) theoretically grounded value; a higher threshold would flag the
    same tasks.
  - No solver-behavior model: this check measures the ENVIRONMENT's data
    volume, not the solver's embedding behavior. A task with a 4 MiB CSV in its
    environment where the solver produces a 50 KiB workbook (just derived
    results) is flagged but does not actually bloat. The WARN is "could
    plausibly," not "will."
  - Shared-corpus tasks: many SVC-PC tasks share the same _corpus_subtree
    (the same fictional company's data exports). 89/202 tasks are flagged
    because 89 tasks have xlsx goldens AND share the large corpus. This is the
    real at-risk population, not a false-positive rate: every one of those
    tasks genuinely has enough data in its environment to push a compliant
    submission past the cliff.
  - One data point: the 4x overhead estimate and the 256 KiB threshold are
    calibrated against ONE real incident (SVC-PC-66-2-0). The other cited
    incident (SVC-PC-52-6-0) is a formula-health issue, not a cliff issue. A
    second cliff incident would refine the estimate; with one point, the
    threshold is named and theoretically grounded, not statistically validated.

CLI shape (same as judge_file_scope_breadth_check.py, style="rubric_schema"):

    python judge_file_size_cliff_check.py <root> [--task TASK-ID] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

CLIFF = 1024 * 1024  # 1,048,576 bytes -- rewardkit/judges.py _MAX_FILE_SIZE

# 256 KiB: cliff / 4x xlsx embedding overhead. See module docstring Threshold.
CLIFF_EQUIVALENT_SINGLE_FILE = CLIFF // 4  # 262,144

# Data-shaped file extensions whose content a solver embeds into a workbook.
DATA_EXTS = frozenset({".csv", ".json", ".xlsx", ".xls", ".xml", ".tsv", ".parquet"})

# Office formats that accumulate embedded data (the bloat mechanism this check
# is calibrated for). Only xlsx today; the check is xlsx-only by design (see
# Known limits).
BLOAT_FORMATS = frozenset({".xlsx"})

WORKSPACE_DIRNAME_BY_FORMAT = {"svc_pc": "initial_workspace", "ekw": "data"}


# ---------------------------------------------------------------------------
# task-format detection (lightweight, self-contained -- same convention
# environment_size_budget_check.py uses, duplicated rather than imported to
# avoid pulling environment_input_check.py's heavier dependency chain)
# ---------------------------------------------------------------------------


def _has_svc_pc_config(task_dir: Path) -> bool:
    tests_dir = task_dir / "tests"
    return tests_dir.is_dir() and any(tests_dir.glob("*/judge.toml"))


def _has_ekw_config(task_dir: Path) -> bool:
    return (task_dir / "tests" / "verifier.json").is_file()


def detect_task_format(task_dir: Path) -> str:
    if _has_svc_pc_config(task_dir):
        return "svc_pc"
    if _has_ekw_config(task_dir):
        return "ekw"
    return "svc_pc"


def resolve_workspace_dir(task_dir: Path) -> Path:
    fmt = detect_task_format(task_dir)
    return task_dir / "environment" / WORKSPACE_DIRNAME_BY_FORMAT[fmt]


# ---------------------------------------------------------------------------
# golden / environment scanning
# ---------------------------------------------------------------------------


_DELIVERABLE_EXTS = frozenset(
    {".xlsx", ".xlsm", ".docx", ".doc", ".pptx", ".ppt", ".pdf", ".json", ".csv", ".txt", ".md"}
)
_NON_DELIVERABLE = frozenset({".sh", ".py", ".toml", ".yaml", ".yml", ".jsonl"})


def golden_files(task_dir: Path) -> list[Path]:
    """Deliverable files under solution/, excluding scripts and backups. Globs
    recursively (solution/files/ for SVC-PC, solution/golden_outputs/ for EKW)
    and keeps only known deliverable extensions, so golden_bytes is not inflated
    by solve.sh or other non-deliverable scripts that live alongside the goldens."""
    sol = task_dir / "solution"
    if not sol.is_dir():
        return []
    return [
        p
        for p in sol.rglob("*")
        if p.is_file()
        and not p.name.endswith((".orig", ".bak"))
        and p.suffix.lower() in _DELIVERABLE_EXTS
        and p.suffix.lower() not in _NON_DELIVERABLE
    ]


def golden_format(gf: list[Path]) -> str:
    """Primary golden format: the largest file's extension, or 'none'."""
    if not gf:
        return "none"
    biggest = max(gf, key=lambda p: p.stat().st_size)
    return biggest.suffix.lower()


def env_data_files(ws_dir: Path) -> list[tuple[int, str, str]]:
    """[(size, ext, relpath)] for data-shaped files under the workspace, sorted
    largest-first."""
    if not ws_dir.is_dir():
        return []
    out = []
    for p in ws_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in DATA_EXTS:
            out.append((p.stat().st_size, p.suffix.lower(), str(p.relative_to(ws_dir))))
    out.sort(key=lambda x: -x[0])
    return out


# ---------------------------------------------------------------------------
# per-task check
# ---------------------------------------------------------------------------


def check_task(task_dir: Path) -> dict:
    """One per-task result dict. Shape matches the rubric_schema convention:
    a bare dict keyed by 'task', accumulated into a list by the CLI."""
    res = {
        "task": task_dir.name,
        "format": detect_task_format(task_dir),
        "cliff": CLIFF,
        "threshold": CLIFF_EQUIVALENT_SINGLE_FILE,
        "golden_format": "none",
        "golden_bytes": 0,
        "golden_n_files": 0,
        "env_n_data_files": 0,
        "env_total_data_bytes": 0,
        "env_largest_data_bytes": 0,
        "env_largest_data_ext": "",
        "env_largest_data_name": "",
        "findings": [],
        "ok": True,
    }

    gf = golden_files(task_dir)
    res["golden_n_files"] = len(gf)
    res["golden_bytes"] = sum(p.stat().st_size for p in gf)
    res["golden_format"] = golden_format(gf)

    ws_dir = resolve_workspace_dir(task_dir)
    dfs = env_data_files(ws_dir)
    res["env_n_data_files"] = len(dfs)
    res["env_total_data_bytes"] = sum(d[0] for d in dfs)
    if dfs:
        res["env_largest_data_bytes"] = dfs[0][0]
        res["env_largest_data_ext"] = dfs[0][1]
        res["env_largest_data_name"] = dfs[0][2][:200]

    # WARN condition: xlsx golden AND largest data file >= threshold.
    if (
        res["golden_format"] in BLOAT_FORMATS
        and res["env_largest_data_bytes"] >= CLIFF_EQUIVALENT_SINGLE_FILE
    ):
        estimated_bloat = res["env_largest_data_bytes"] * 4 + res["golden_bytes"]
        res["findings"].append(
            {
                "kind": "size_cliff_risk",
                "golden_format": res["golden_format"],
                "golden_bytes": res["golden_bytes"],
                "env_largest_data_bytes": res["env_largest_data_bytes"],
                "env_largest_data_ext": res["env_largest_data_ext"],
                "env_largest_data_name": res["env_largest_data_name"],
                "env_total_data_bytes": res["env_total_data_bytes"],
                "cliff": CLIFF,
                "threshold": CLIFF_EQUIVALENT_SINGLE_FILE,
                "estimated_bloat_upper": estimated_bloat,
                "reason": (
                    f"environment's largest data file "
                    f"({res['env_largest_data_bytes']:,} bytes, "
                    f"{res['env_largest_data_ext']}) exceeds the 256 KiB "
                    f"cliff-equivalent threshold ({CLIFF_EQUIVALENT_SINGLE_FILE:,} "
                    f"bytes = 1 MiB / 4x xlsx overhead). A solver embedding this "
                    f"file into the xlsx deliverable could plausibly produce a "
                    f"submission exceeding rewardkit's 1 MiB silent-truncation "
                    f"cliff. Estimated upper bound: {estimated_bloat:,} bytes. "
                    f"This is a WARN-tier advisory: whether the solver embeds "
                    f"the data depends on the solver's approach, not the task "
                    f"package."
                ),
            }
        )
        res["ok"] = False

    return res


# ---------------------------------------------------------------------------
# CLI -- same shape as judge_file_scope_breadth_check.py (rubric_schema style)
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "root",
        help="a directory containing one subdirectory per task, or a single task directory",
    )
    ap.add_argument(
        "--task",
        action="append",
        default=[],
        help="limit to these task ids (repeatable)",
    )
    ap.add_argument("--json", help="also write the full result set here")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2

    if (root / "tests").is_dir():
        task_dirs = [root]
    else:
        task_dirs = sorted(d for d in root.iterdir() if d.is_dir())
    if args.task:
        want = set(args.task)
        task_dirs = [d for d in task_dirs if d.name in want]
    if not task_dirs:
        sys.stderr.write(f"no task directories matched under {root}\n")
        return 2

    results = []
    for i, d in enumerate(task_dirs, 1):
        if len(task_dirs) > 20:
            print(f"[{i}/{len(task_dirs)}] {d.name} ...", file=sys.stderr)
        results.append(check_task(d))

    warned = [r for r in results if r["findings"]]
    n_xlsx = sum(1 for r in results if r["golden_format"] in BLOAT_FORMATS)
    n_with_data = sum(
        1
        for r in results
        if r["env_largest_data_bytes"] >= CLIFF_EQUIVALENT_SINGLE_FILE
    )

    for r in results:
        flag = "WARN " if r["findings"] else "OK   "
        print(
            f"{flag} {r['task']:<20} [{r['format']:<6}] "
            f"golden={r['golden_format']:<5} {r['golden_bytes']:>8,}B  "
            f"largest_data={r['env_largest_data_bytes']:>10,}B "
            f"({r['env_largest_data_ext']:<5})  "
            f"total_data={r['env_total_data_bytes']:>12,}B"
        )
        for f in r["findings"]:
            print(
                f"       SIZE_CLIFF_RISK: largest data file "
                f"{f['env_largest_data_bytes']:,}B ({f['env_largest_data_ext']}) "
                f">= {CLIFF_EQUIVALENT_SINGLE_FILE:,}B threshold, "
                f"est. bloat upper {f['estimated_bloat_upper']:,}B vs cliff {CLIFF:,}B"
            )

    print(
        f"\n{len(results) - len(warned)}/{len(results)} clean, "
        f"{len(warned)} WARN  |  {n_xlsx}/{len(results)} xlsx goldens  |  "
        f"{n_with_data}/{len(results)} tasks with data file >= threshold"
    )
    if args.json:
        Path(args.json).write_text(
            json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"wrote {args.json}")
    # WARN never gates the exit code: this is an advisory, not a gate.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
