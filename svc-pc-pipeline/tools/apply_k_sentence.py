#!/usr/bin/env python3
"""apply_k_sentence.py - GATE-V2 3.3/3.6 class K, item (1): append the cached-
value disclosure sentence to instruction.md and tests/task_prompt.txt for a
task with an xlsx deliverable. Idempotent (checks presence first). Byte-exact
(newline="" preserved), read-back verified, like rewardkit_pin.py's own
--apply-task.

Usage:
    python3 apply_k_sentence.py <TASK> --corpus-root PATH
Exit 0 and prints "applied" / "already-present" per file; exit 2 on error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

K_SENTENCE = (
    "The grader reads each cell's stored value, not its formula. Formula cells "
    "must carry their computed values when the file is read programmatically "
    "(write the value alongside the formula, or recalculate before saving)."
)


def append_if_absent(path: Path) -> str:
    if not path.is_file():
        return f"MISSING: {path}"
    content = path.read_text(newline="")
    if K_SENTENCE in content:
        return f"already-present: {path}"
    sep = "\n\n" if content and not content.endswith("\n\n") else ""
    if content.endswith("\n\n"):
        sep = ""
    elif content.endswith("\n"):
        sep = "\n"
    new_content = content + sep + K_SENTENCE + "\n"
    path.write_text(new_content, newline="")
    check = path.read_text(newline="")
    if K_SENTENCE not in check:
        return f"FAILED write-verify: {path}"
    return f"applied: {path}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("task")
    ap.add_argument("--corpus-root", type=Path, required=True)
    args = ap.parse_args()

    task_dir = args.corpus_root / args.task
    results = []
    for rel in ("instruction.md", "tests/task_prompt.txt"):
        results.append(append_if_absent(task_dir / rel))

    ok = True
    for r in results:
        print(r)
        if r.startswith("MISSING") or r.startswith("FAILED"):
            ok = False
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
