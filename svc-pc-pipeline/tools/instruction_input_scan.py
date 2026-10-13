#!/usr/bin/env python3
"""
instruction_input_scan.py - GATE-V2 class C/O: input files/documents the
INSTRUCTION names that do not exist in the environment.

For each task, extracts from instruction.md and tests/task_prompt.txt two
kinds of named inputs:

  - exact-filename: filename-shaped tokens (*.xlsx/.docx/.csv/.pdf/.doc/
    .pptx), resolved by exact then fuzzy filename match against
    environment/initial_workspace/ (unchanged from the original version of
    this script).
  - named-document (class O, added 2026-09-18): descriptive references of
    the form "the <X> agreement|contract|policy|memo|letter|brief|plan|
    report|register|schedule|analysis" (e.g. "the NovaTex agreement"),
    resolved in two steps: (a) fuzzy-match against a shipped filename in
    initial_workspace/ (same fuzzy matcher as exact-filename), then, only
    if that fails, (b) fuzzy-match against lines of text extracted from
    every environment file, looking for the phrase's keywords co-occurring
    as if naming a document title inside another file (a memo's Sources
    list, an email, an index). A named document that resolves to NEITHER
    is a class O phantom document (e.g. 10-2-0 "the NovaTex agreement":
    absent as a filename AND absent as a title anywhere in the extracted
    text; the underlying terms live in Product_Supplier_Comparison.xlsx
    cells instead).

Step (b) is lazy: full-text extraction of every environment file is only
run for tasks that have at least one named-document candidate unresolved
by filename match, since it is the expensive path (reuses
_qc_common.extract_document_text, parallelized, per-file soft timeout).

Note: instruction.md's "Graded deliverable filenames" section names OUTPUT
files, not inputs. Those are extracted the same way as everything else (no
reliable way to separate the two sections in every task's prose), so an
output filename will legitimately show as exact-filename/MISSING against
initial_workspace -- read the CSV with that in mind; class C/O findings are
about a named SOURCE the instruction claims exists that genuinely is not
shipped, not about the deliverable name itself.

READ-ONLY: only reads corpus files, never modifies them. Run corpus-wide.

Output: CSV [task, named_input, kind, resolved_to] at reports/instruction_inputs.csv
(same path as before; two new columns: kind in {exact-filename, named-document},
resolved_to replaces found_or_missing -- a relative path / "title in <file>
line N" when resolved, else MISSING).

Usage:
    python3 instruction_input_scan.py [--corpus-root PATH] [--out PATH]
        [--task NAME] [--workers N]
"""
from __future__ import annotations

import argparse
import re
import signal
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import (
    DEFAULT_CORPUS_ROOT,
    DEFAULT_REPORTS_DIR,
    build_file_index,
    extract_document_text,
    extract_filename_tokens,
    find_exact_filename,
    find_fuzzy_filename,
    list_tasks,
    normalize_keywords,
    read_text_safe,
    write_csv,
)

# Class O noun list, exactly as specified: "the <X> agreement|contract|
# policy|memo|letter|brief|plan|report|register|schedule|analysis".
_CLASS_O_NOUNS = (
    "agreement", "contract", "policy", "memo", "letter", "brief", "plan",
    "report", "register", "schedule", "analysis",
)
# Qualifier words must not themselves be "the/a/an": without this, a
# sentence like "the base gross margin the plan runs at" would let the
# qualifier span across the second "the" and mis-capture "base gross
# margin the plan" as one phrase instead of stopping and (correctly)
# dropping the too-generic "the plan".
_QUALIFIER_WORD = r"(?!(?:the|a|an)\b)[A-Za-z0-9/&'\-]+"
_CLASS_O_RE = re.compile(
    r"\bthe\s+(%s(?:\s+%s){0,3}\s+(?:%s))\b"
    % (_QUALIFIER_WORD, _QUALIFIER_WORD, "|".join(_CLASS_O_NOUNS)),
    re.IGNORECASE,
)

PER_FILE_TIMEOUT_S = 25
TITLE_OVERLAP_MIN = 0.6


class _TimeoutErr(Exception):
    pass


def _alarm(_signum, _frame):
    raise _TimeoutErr()


def extract_class_o_named_documents(text: str) -> set[str]:
    """'the NovaTex agreement' -> {'NovaTex agreement'}. Drops a bare 'the
    <noun>' with no qualifier (e.g. 'the plan') -- too generic to be a
    citation; requires at least one qualifier word before the noun."""
    found: set[str] = set()
    for m in _CLASS_O_RE.finditer(text):
        phrase = re.sub(r"\s+", " ", m.group(1)).strip()
        words = phrase.split()
        if len(words) >= 2:  # at least one qualifier + the noun
            found.add(phrase)
    return found


def scan_task_filenames(task_dir: Path) -> tuple[list[tuple[str, str, str, str]], list[str]]:
    """Exact-filename kind (unchanged behavior) + list of unresolved
    named-document phrases (kind=named-document, resolved via filename
    match only so far)."""
    instr = task_dir / "instruction.md"
    prompt = task_dir / "tests" / "task_prompt.txt"
    workspace = task_dir / "environment" / "initial_workspace"

    text = read_text_safe(instr) + "\n" + read_text_safe(prompt)
    if not text.strip():
        return [], []

    index = build_file_index(workspace)

    exact_rows = []
    for name in sorted(extract_filename_tokens(text)):
        hit = find_exact_filename(name, index)
        if hit is None:
            hit = find_fuzzy_filename(name, index)
        resolved = str(hit.relative_to(task_dir)) if hit else "MISSING"
        exact_rows.append((task_dir.name, name, "exact-filename", resolved))

    named_rows = []
    unresolved_phrases = []
    for phrase in sorted(extract_class_o_named_documents(text)):
        hit = find_fuzzy_filename(phrase, index)
        if hit is not None:
            named_rows.append((task_dir.name, phrase, "named-document", str(hit.relative_to(task_dir))))
        else:
            unresolved_phrases.append(phrase)

    return exact_rows + named_rows, unresolved_phrases


def _title_search_worker(job: tuple[str, str]) -> list[tuple[str, str]]:
    """job = (relpath, abspath). Returns [(relpath, line_text), ...] for
    every non-trivial line of extracted text (title-search candidates)."""
    relpath, abspath_s = job
    abspath = Path(abspath_s)
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(PER_FILE_TIMEOUT_S)
    try:
        text = extract_document_text(abspath)
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        return [(relpath, ln) for ln in lines]
    except _TimeoutErr:
        print(f"TIMEOUT>{PER_FILE_TIMEOUT_S}s skipped: {abspath}", file=sys.stderr)
        return []
    except Exception as exc:
        print(f"ERROR {abspath}: {exc}", file=sys.stderr)
        return []
    finally:
        signal.alarm(0)


def resolve_via_title_search(
    task_dir: Path,
    phrases: list[str],
    workers: int,
) -> dict[str, str]:
    """For each unresolved named-document phrase, search every environment
    file's extracted text for a line whose keywords overlap the phrase's
    keywords at >= TITLE_OVERLAP_MIN. Returns {phrase: resolved_to or
    'MISSING'}."""
    workspace = task_dir / "environment" / "initial_workspace"
    files = [p for p in workspace.rglob("*") if p.is_file()] if workspace.is_dir() else []
    jobs = [(str(p.relative_to(task_dir)), str(p)) for p in files]

    all_lines: list[tuple[str, str]] = []
    if len(jobs) <= 8:
        for job in jobs:
            all_lines.extend(_title_search_worker(job))
    else:
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as ex:
            futs = [ex.submit(_title_search_worker, job) for job in jobs]
            for fut in as_completed(futs):
                try:
                    all_lines.extend(fut.result())
                except Exception:
                    pass

    result: dict[str, str] = {}
    for phrase in phrases:
        kws = normalize_keywords(phrase)
        best: tuple[float, str, str] | None = None
        if kws:
            for relpath, line in all_lines:
                line_kws = normalize_keywords(line)
                if not line_kws:
                    continue
                overlap = len(kws & line_kws) / len(kws)
                if overlap >= TITLE_OVERLAP_MIN and (best is None or overlap > best[0]):
                    best = (overlap, relpath, line[:120])
        result[phrase] = f"title in {best[1]}: \"{best[2]}\"" if best else "MISSING"
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT, help="corpus root directory")
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR / "instruction_inputs.csv", help="output CSV path")
    ap.add_argument("--task", type=str, default=None, help="restrict to a single task name (debugging)")
    ap.add_argument("--workers", type=int, default=16, help="parallel workers for the title-search fallback")
    ap.add_argument("--verdict-out", type=Path, default=None, help="write task_id,instruction_input_scan pass|fail summary CSV")
    args = ap.parse_args()
    try:  # admission control: at most K heavy scans at once, W workers each (scan_slots.py, fail-open)
        import scan_slots

        scan_slots.acquire(Path(__file__).stem, args.task or "")
        args.workers = scan_slots.workers(args.workers)
    except Exception as exc:
        print(f"scan_slots unavailable, running unbounded: {exc}", file=sys.stderr)

    tasks = list_tasks(args.corpus_root)
    if args.task:
        tasks = [t for t in tasks if t.name == args.task]
    if not tasks:
        print(f"ERROR: no matching task directories under {args.corpus_root}", file=sys.stderr)
        return 1

    all_rows: list[tuple[str, str, str, str]] = []
    errors: list[str] = []
    tasks_needing_fallback = 0
    for i, task_dir in enumerate(tasks, 1):
        try:
            rows, unresolved = scan_task_filenames(task_dir)
            all_rows.extend(rows)
            if unresolved:
                tasks_needing_fallback += 1
                resolved_map = resolve_via_title_search(task_dir, unresolved, args.workers)
                for phrase in unresolved:
                    all_rows.append((task_dir.name, phrase, "named-document", resolved_map[phrase]))
        except Exception as exc:
            errors.append(f"{task_dir.name}: {exc}")
        if i % 25 == 0:
            print(f"  ...{i}/{len(tasks)} tasks scanned ({tasks_needing_fallback} needed title-search fallback so far)", file=sys.stderr)

    n = write_csv(args.out, ["task", "named_input", "kind", "resolved_to"], all_rows)
    missing = [r for r in all_rows if r[3] == "MISSING"]
    phantom_named_docs = [r for r in all_rows if r[2] == "named-document" and r[3] == "MISSING"]
    tasks_with_missing = {r[0] for r in missing}
    tasks_with_phantom = {r[0] for r in phantom_named_docs}

    print(f"instruction_input_scan: {n} named inputs extracted across {len(tasks)} tasks, written to {args.out}")
    print(f"  {len(missing)} named inputs MISSING (any kind), across {len(tasks_with_missing)} tasks")
    print(f"  {len(phantom_named_docs)} class-O phantom named-documents (resolved to NEITHER filename NOR extracted title), across {len(tasks_with_phantom)} tasks")
    print(f"  {tasks_needing_fallback} tasks needed the title-search fallback (named doc not resolved by filename)")
    if errors:
        print(f"  {len(errors)} tasks raised errors during scan:", file=sys.stderr)
        for e in errors:
            print(f"    {e}", file=sys.stderr)

    if args.verdict_out:
        verdict_rows = sorted(
            (t.name, "fail" if t.name in tasks_with_missing else "pass") for t in tasks
        )
        vn = write_csv(args.verdict_out, ["task_id", "instruction_input_scan"], verdict_rows)
        print(f"instruction_input_scan: verdict CSV written, {vn} rows, to {args.verdict_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
