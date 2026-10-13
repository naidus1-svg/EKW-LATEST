#!/usr/bin/env python3
"""STATUS: v0, UNVALIDATED. This threshold has not been calibrated against any real labeled examples of true/false duplicates. Treat every reported pair as a candidate for human review, never as a confirmed duplicate.

duplicate_task_detector_v0.py: a first-pass duplicate / near-duplicate task
detector for a directory of Harbor-style task packages.

For every task under --root, this reads that task's instruction.md in full,
normalizes whitespace and case, and compares it against every other task's
instruction.md using Python's stdlib difflib.SequenceMatcher.ratio(). Any
pair scoring at or above --threshold (default 0.85) is reported as a
possible duplicate, sorted by similarity descending.

Similarity method: difflib.SequenceMatcher.ratio() on whitespace/case
normalized text. This was chosen over a shingled-token Jaccard approach
because it is the simpler of the two to implement correctly with zero new
pip dependencies: SequenceMatcher does the alignment work internally, while
a Jaccard implementation would still need its own tokenizer and shingle
window and is more places to get subtly wrong for a v0 pass. ratio() is
also more sensitive to instruction.md edits that reorder or lightly
rephrase text than a token-set Jaccard would be, at the cost of being O(n*m)
per pair, which is acceptable at the task-count scale this is meant for.

This is a first-pass screen, not a judgment. It has never been checked
against a labeled set of tasks known to be true duplicates or known to be
merely similar-but-distinct, so there is no evidence yet about what
threshold separates the two, or whether SequenceMatcher.ratio() is even the
right axis to separate them on. Every reported pair still needs a human to
open both instruction.md files and decide.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path
from typing import List, NamedTuple

STATUS_LINE = (
    "STATUS: v0, UNVALIDATED. This threshold has not been calibrated against "
    "any real labeled examples of true/false duplicates. Treat every reported "
    "pair as a candidate for human review, never as a confirmed duplicate."
)

INSTRUCTION_FILENAME = "instruction.md"

_WHITESPACE_RE = re.compile(r"\s+")


class Task(NamedTuple):
    task_id: str
    path: str
    raw_text: str
    normalized_text: str


class DuplicatePair(NamedTuple):
    task_a: str
    task_b: str
    task_a_path: str
    task_b_path: str
    similarity: float


def normalize_text(text: str) -> str:
    """Lowercase the text and collapse all whitespace runs to single spaces.

    This is deliberately minimal: no stemming, no punctuation stripping, no
    stopword removal. It exists only to stop trivial formatting differences
    (trailing spaces, blank-line counts, tabs vs spaces, case) from lowering
    a similarity score that should otherwise be high.
    """
    return _WHITESPACE_RE.sub(" ", text.lower()).strip()


def find_tasks(root: Path) -> List[Task]:
    """Find every instruction.md under root and load it as a Task.

    A task's id is its instruction.md's parent directory path, relative to
    root, with forward slashes so the id is stable across platforms.
    """
    tasks: List[Task] = []
    for instruction_path in sorted(root.rglob(INSTRUCTION_FILENAME)):
        try:
            raw_text = instruction_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(
                f"warning: could not read {instruction_path}: {exc}",
                file=sys.stderr,
            )
            continue

        task_dir = instruction_path.parent
        try:
            relative_dir = task_dir.relative_to(root)
            task_id = (
                relative_dir.as_posix() if str(relative_dir) != "." else task_dir.name
            )
        except ValueError:
            task_id = task_dir.name

        tasks.append(
            Task(
                task_id=task_id,
                path=str(instruction_path),
                raw_text=raw_text,
                normalized_text=normalize_text(raw_text),
            )
        )
    return tasks


def compute_similarity(text_a: str, text_b: str) -> float:
    """Similarity in [0.0, 1.0] between two already-normalized strings.

    Uses difflib.SequenceMatcher.ratio(), the stdlib's standard measure of
    sequence similarity: 2 * (number of matching characters) / (total
    length of both sequences).
    """
    return difflib.SequenceMatcher(None, text_a, text_b).ratio()


def find_duplicate_pairs(tasks: List[Task], threshold: float) -> List[DuplicatePair]:
    pairs: List[DuplicatePair] = []
    n = len(tasks)
    for i in range(n):
        for j in range(i + 1, n):
            task_a = tasks[i]
            task_b = tasks[j]
            similarity = compute_similarity(
                task_a.normalized_text, task_b.normalized_text
            )
            if similarity >= threshold:
                pairs.append(
                    DuplicatePair(
                        task_a=task_a.task_id,
                        task_b=task_b.task_id,
                        task_a_path=task_a.path,
                        task_b_path=task_b.path,
                        similarity=similarity,
                    )
                )
    pairs.sort(key=lambda p: p.similarity, reverse=True)
    return pairs


def build_report(
    root: Path, threshold: float, tasks: List[Task], pairs: List[DuplicatePair]
) -> dict:
    n = len(tasks)
    pairs_compared = n * (n - 1) // 2
    return {
        "status": STATUS_LINE,
        "root": str(root),
        "threshold": threshold,
        "similarity_method": (
            "difflib.SequenceMatcher.ratio() over whitespace/case-normalized "
            "instruction.md text (stdlib only, no new pip dependencies)"
        ),
        "tasks_scanned": n,
        "pairs_compared": pairs_compared,
        "possible_duplicates_found": len(pairs),
        "possible_duplicates": [
            {
                "task_a": pair.task_a,
                "task_b": pair.task_b,
                "task_a_instruction_path": pair.task_a_path,
                "task_b_instruction_path": pair.task_b_path,
                "similarity": round(pair.similarity, 6),
            }
            for pair in pairs
        ],
    }


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="duplicate_task_detector_v0.py",
        description=(
            "v0, UNVALIDATED first-pass duplicate/near-duplicate task detector. "
            "Reads every task's instruction.md under --root, compares each pair "
            "with difflib.SequenceMatcher.ratio() on normalized text, and "
            "reports pairs at or above --threshold as candidates for human "
            "review. This threshold has not been calibrated against any "
            "labeled true/false duplicate examples."
        ),
    )
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Directory to search recursively for task instruction.md files.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help=(
            "Minimum similarity ratio (0.0-1.0) for a pair to be reported as a "
            "possible duplicate. Default 0.85. UNCALIBRATED: chosen as a "
            "starting point, not derived from labeled data."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Path to write the JSON report to. If omitted, the report is "
            "printed to stdout."
        ),
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.root.exists():
        print(f"error: --root does not exist: {args.root}", file=sys.stderr)
        return 2
    if not args.root.is_dir():
        print(f"error: --root is not a directory: {args.root}", file=sys.stderr)
        return 2
    if not (0.0 <= args.threshold <= 1.0):
        print(
            f"error: --threshold must be between 0.0 and 1.0, got {args.threshold}",
            file=sys.stderr,
        )
        return 2

    print(f"[{STATUS_LINE}]", file=sys.stderr)

    tasks = find_tasks(args.root)
    print(
        f"Found {len(tasks)} task(s) with an instruction.md under {args.root}",
        file=sys.stderr,
    )

    if len(tasks) < 2:
        print(
            "warning: fewer than 2 tasks found; no pairs to compare.",
            file=sys.stderr,
        )

    pairs = find_duplicate_pairs(tasks, args.threshold)
    report = build_report(args.root, args.threshold, tasks, pairs)

    output_text = json.dumps(report, indent=2)

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output_text, encoding="utf-8")
        print(f"Wrote report to {args.out}", file=sys.stderr)
    else:
        print(output_text)

    print(
        f"{len(pairs)} possible duplicate pair(s) at or above threshold "
        f"{args.threshold} out of {report['pairs_compared']} pair(s) compared.",
        file=sys.stderr,
    )
    print(
        "Reminder: these are candidates for human review, not confirmed "
        "duplicates. See the module docstring.",
        file=sys.stderr,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
