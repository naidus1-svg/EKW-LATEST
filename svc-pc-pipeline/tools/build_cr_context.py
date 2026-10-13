#!/usr/bin/env python3
"""build_cr_context.py - GATE-V2/HANDOFF section 3 step 3 support.

Builds the ONE text bundle the blind Opus CR call reads: instruction.md,
tests/task_prompt.txt, tests/reward.toml, every tests/deliverables*/judge.toml,
the golden's extracted text (solution/files/*), and a source index
(environment/initial_workspace/* file list + extracted text). Capped at
--budget-chars total (default ~240,000 chars, approx 60k tokens at 4
chars/token per HANDOFF.md section 3 step 3: "capped at about 60k tokens").

Read-only against the corpus. Reuses _qc_common.extract_document_text (same
MarkItDown/openpyxl/python-docx extraction the scans and judge_emulate.py use)
so the package the CR sees is the same text the judge/solver would see, not a
reimplementation.

Budget allocation, in priority order (each section gets what's left after the
ones before it, so nothing earlier is ever starved by a later section):
  1. instruction.md                 (full, no cap - always small)
  2. tests/task_prompt.txt          (full, no cap - always small)
  3. tests/reward.toml + every judge.toml   (full, no cap - always small)
  4. golden solution/files/* text   (up to --golden-chars, default 70,000)
  5. source index (initial_workspace file list + extracted text, smallest
     files first so more distinct sources fit) (remaining budget)

Usage:
    python3 build_cr_context.py <TASK> --out CONTEXT.txt
        [--corpus-root PATH] [--budget-chars N] [--golden-chars N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import DEFAULT_CORPUS_ROOT, extract_document_text, iter_deliverable_groups  # noqa: E402


def section(title: str, body: str) -> str:
    return f"\n{'=' * 80}\n{title}\n{'=' * 80}\n{body.rstrip()}\n"


def truncate(text: str, budget: int) -> tuple[str, int]:
    if budget <= 0:
        return "[omitted: no budget remaining]", 0
    if len(text) <= budget:
        return text, budget - len(text)
    cut = text[:budget]
    return cut + f"\n...[truncated {len(text) - budget} chars]", 0


def xlsx_numeric_digest(path: Path, max_distinct: int = 50) -> str:
    """Numeric summary of an xlsx that would otherwise be truncated mid-table.

    extract_document_text() only ever collects STRING cell values for an xlsx (see
    _qc_common.py), and a raw dump of a large sheet gets cut off by the per-file
    budget before it reaches the rows a reviewer needs anyway - both true on
    SVC-PC-54-2-0's Sales_Orders.xlsx, where the CR's "$84,344 untraceable" major
    only existed because the 11 ADJ-UNALLOC adjustment rows never survived either
    limitation (grep ADJ-UNALLOC on the old CONTEXT.txt: 0 hits; DataOS recomputed
    the same figure straight from the workbook). This instead reports, per sheet:
    row count, the header list, per numeric column count/sum/min/max, and for each
    text column with at most `max_distinct` distinct values, its value counts - and
    for a minority value (rare relative to the sheet), the same-row sums of every
    numeric column, which is what actually makes a figure like "ADJ-UNALLOC x 11,
    sum -84,344" visible without dumping every row.
    """
    import openpyxl
    from collections import Counter

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    lines: list[str] = []
    for ws in wb.worksheets:
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header_row = list(next(rows_iter))
        except StopIteration:
            header_row = []
        header = [str(h) if h not in (None, "") else f"col{i + 1}" for i, h in enumerate(header_row)]
        ncols = len(header)
        columns: list[list] = [[] for _ in range(ncols)]
        nrows = 0
        for row in rows_iter:
            nrows += 1
            for i in range(ncols):
                columns[i].append(row[i] if i < len(row) else None)

        lines.append(f"--- sheet: {ws.title!r} --- rows={nrows} (excluding header)")
        lines.append("headers: " + ", ".join(header))

        def is_number(v) -> bool:
            return isinstance(v, (int, float)) and not isinstance(v, bool)

        numeric_col = {}
        for i, name in enumerate(header):
            non_null = [v for v in columns[i] if v is not None and v != ""]
            numeric_col[name] = bool(non_null) and all(is_number(v) for v in non_null)

        for i, name in enumerate(header):
            if not numeric_col[name]:
                continue
            vals = [v for v in columns[i] if v is not None and v != ""]
            if not vals:
                lines.append(f"column {name!r}: numeric, n=0 (all blank)")
                continue
            lines.append(f"column {name!r}: numeric, n={len(vals)}, sum={sum(vals)!r}, min={min(vals)!r}, max={max(vals)!r}")

        for i, name in enumerate(header):
            if numeric_col[name]:
                continue
            col_vals = columns[i]
            counts = Counter(str(v) for v in col_vals if v is not None and v != "")
            if not counts:
                lines.append(f"column {name!r}: all blank")
                continue
            if len(counts) > max_distinct:
                lines.append(f"column {name!r}: text, distinct={len(counts)} (over {max_distinct}, value counts omitted)")
                continue
            minority_cutoff = max(50, nrows // 20)
            parts = []
            for value, n in sorted(counts.items(), key=lambda kv: -kv[1]):
                entry = f"{value!r} x {n}"
                if n <= minority_cutoff:
                    idxs = [j for j, v in enumerate(col_vals) if v is not None and str(v) == value]
                    sums = []
                    for oname, ocol_idx in ((h, k) for k, h in enumerate(header) if numeric_col[h]):
                        ovals = columns[ocol_idx]
                        s = sum(ovals[j] for j in idxs if j < len(ovals) and is_number(ovals[j]))
                        if s:
                            sums.append(f"{oname} sum={s!r}")
                    if sums:
                        entry += " (" + ", ".join(sums) + ")"
                parts.append(entry)
            lines.append(f"column {name!r}: text, distinct={len(counts)}, counts: " + ", ".join(parts))
    wb.close()
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task")
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--budget-chars", type=int, default=240_000)
    ap.add_argument("--golden-chars", type=int, default=70_000)
    args = ap.parse_args()

    task_dir = args.corpus_root / args.task
    if not task_dir.is_dir():
        sys.stderr.write(f"ERROR: task directory not found: {task_dir}\n")
        return 2

    out_parts: list[str] = []
    budget = args.budget_chars

    # 1. instruction.md
    instr = task_dir / "instruction.md"
    instr_text = instr.read_text(errors="replace") if instr.is_file() else "[missing instruction.md]"
    out_parts.append(section("INSTRUCTION.MD", instr_text))
    budget -= len(instr_text)

    # 2. task_prompt.txt
    tp = task_dir / "tests" / "task_prompt.txt"
    tp_text = tp.read_text(errors="replace") if tp.is_file() else "[missing tests/task_prompt.txt]"
    out_parts.append(section("TESTS/TASK_PROMPT.TXT", tp_text))
    budget -= len(tp_text)

    # 3. reward.toml + judge.toml(s)
    reward = task_dir / "tests" / "reward.toml"
    reward_text = reward.read_text(errors="replace") if reward.is_file() else "[missing tests/reward.toml]"
    out_parts.append(section("TESTS/REWARD.TOML", reward_text))
    budget -= len(reward_text)

    for grp in iter_deliverable_groups(task_dir):
        jt = grp / "judge.toml"
        if jt.is_file():
            jt_text = jt.read_text(errors="replace")
            out_parts.append(section(f"TESTS/{grp.name}/JUDGE.TOML", jt_text))
            budget -= len(jt_text)

    # 3b. task.toml, environment/Dockerfile, solution/solve.sh - always small,
    # always full text (redirect build, 2026-09-18: these three were entirely
    # missing from CONTEXT.txt, confirmed on the SVC-PC-54-2-0 test run - check
    # 1.9 came back "inconclusive: task.toml was not included in the package"
    # for a task whose task.toml is in fact fully populated, and check 1.8
    # came back "inconclusive: Dockerfile was not provided" for the same
    # reason, even though blind_cr.md's own preamble promises both are in the
    # package and canon §2 step 2 requires reading the Dockerfile before
    # judging packaging at all). Dockerfile lives under environment/ in this
    # corpus layout, not the task root.
    toml_path = task_dir / "task.toml"
    toml_text = toml_path.read_text(errors="replace") if toml_path.is_file() else "[missing task.toml]"
    out_parts.append(section("TASK.TOML", toml_text))
    budget -= len(toml_text)

    docker_path = task_dir / "environment" / "Dockerfile"
    docker_text = docker_path.read_text(errors="replace") if docker_path.is_file() else "[missing environment/Dockerfile]"
    out_parts.append(section("ENVIRONMENT/DOCKERFILE", docker_text))
    budget -= len(docker_text)

    solve_path = task_dir / "solution" / "solve.sh"
    solve_text = solve_path.read_text(errors="replace") if solve_path.is_file() else "[missing solution/solve.sh]"
    out_parts.append(section("SOLUTION/SOLVE.SH", solve_text))
    budget -= len(solve_text)

    # 4. golden solution/files
    golden_dir = task_dir / "solution" / "files"
    golden_budget = min(args.golden_chars, max(budget, 0))
    if golden_dir.is_dir():
        golden_files = sorted(p for p in golden_dir.rglob("*") if p.is_file())
        per_file_used = 0
        for gf in golden_files:
            if golden_budget - per_file_used <= 0:
                out_parts.append(section(f"SOLUTION/FILES/{gf.relative_to(golden_dir)}", "[omitted: golden budget exhausted]"))
                continue
            try:
                text = extract_document_text(gf)
            except Exception as exc:  # noqa: BLE001
                text = f"[extraction error: {exc}]"
            remaining = golden_budget - per_file_used
            clipped, _ = truncate(text, remaining)
            per_file_used += len(clipped)
            out_parts.append(section(f"SOLUTION/FILES/{gf.relative_to(golden_dir)}", clipped))
        budget -= per_file_used
    else:
        out_parts.append(section("SOLUTION/FILES", "[missing solution/files/]"))

    # 5. source index: environment/initial_workspace, smallest files first
    ws = task_dir / "environment" / "initial_workspace"
    if ws.is_dir():
        files = sorted((p for p in ws.rglob("*") if p.is_file()), key=lambda p: p.stat().st_size)
        listing = "\n".join(f"- {p.relative_to(ws)}  ({p.stat().st_size} bytes)" for p in files)
        out_parts.append(section("ENVIRONMENT/INITIAL_WORKSPACE FILE LIST", listing or "[empty]"))
        remaining = max(budget, 0)
        used = 0
        for p in files:
            if remaining - used <= 200:
                break
            try:
                text = extract_document_text(p)
            except Exception as exc:  # noqa: BLE001
                text = f"[extraction error: {exc}]"
            per_budget = min(len(text), max(remaining - used, 0))
            if p.suffix.lower() == ".xlsx" and len(text) > max(remaining - used, 0):
                # Would be truncated: swap the raw dump for a compact numeric digest
                # instead of shipping a mid-row cutoff that hides exactly the figures
                # a reviewer needs (see xlsx_numeric_digest's docstring).
                try:
                    digest = xlsx_numeric_digest(p)
                except Exception:  # noqa: BLE001
                    digest = None
                if digest:
                    text = digest
                    per_budget = min(len(text), max(remaining - used, 0))
            clipped, _ = truncate(text, per_budget)
            used += len(clipped)
            out_parts.append(section(f"SOURCE TEXT: {p.relative_to(ws)}", clipped))
        skipped = [p for p in files if str(p.relative_to(ws)) not in "".join(out_parts)]
        if used >= remaining and len(files) > 0:
            out_parts.append(section(
                "SOURCE TEXT: BUDGET NOTE",
                "Remaining sources were omitted for budget; see the file list above for names/sizes.",
            ))
    else:
        out_parts.append(section("ENVIRONMENT/INITIAL_WORKSPACE", "[missing]"))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(out_parts))
    total_chars = sum(len(p) for p in out_parts)
    sys.stderr.write(f"wrote {args.out} ({total_chars} chars, approx {total_chars // 4} tokens)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
