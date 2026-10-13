#!/usr/bin/env python3
"""
muststrip_scan.py - GATE-V2 class H, 3.3: "must-pass" text with no gate in
reward.toml.

Finds every occurrence of the sentence "This is a must-pass criterion."
(and close case/hyphenation variants: "must pass" without the hyphen,
any capitalization) in tests/deliverables*/judge.toml across the corpus,
per task + criterion.

This build is REPORT-ONLY by default. `--apply` (corpus-wide) is
implemented (gated, off by default) for a later coordinated pass --
GATE-V2 3.3 H says "Delete the sentence", but 202 tasks' judge.toml files
are owned across multiple concurrent sessions, so Z does not apply it
unilaterally corpus-wide here. Do not pass corpus-wide --apply in this
build; that application must be coordinated by main/Khiem in one pass
(like the rewardkit pin).

--apply-task <TASK> --confirm-apply is the single-task exception: an OWNER
applying the strip to their OWN claimed task. It strips ONLY
03_dataos_ready/<TASK>/tests/deliverables_*/judge.toml -- no other task
directory is read or written.

Both --apply and --apply-task remove ONLY the matched sentence (plus a
single leading space, so no double-space/trailing-space artifact is left
behind), leaving each criterion's `description` otherwise byte-identical,
and preserve LF line endings exactly (files are read/written with
newline="" so no CRLF translation occurs).

READ-ONLY (in this build): never modifies corpus files unless --apply or
--apply-task is explicitly passed (each gated behind its own confirmation
flag).

Output: CSV [task, group, criterion_id, line].

Usage:
    python3 muststrip_scan.py [--corpus-root PATH] [--out PATH] [--task NAME]
    python3 muststrip_scan.py --apply   # NOT run in this build; future coordinated pass only
    python3 muststrip_scan.py --apply-task <TASK> --confirm-apply
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import (
    DEFAULT_CORPUS_ROOT,
    DEFAULT_REPORTS_DIR,
    iter_deliverable_groups,
    list_tasks,
    write_csv,
)

# "This is a must-pass criterion." and close variants: hyphen optional,
# case-insensitive, trailing period optional. Deliberately narrow so it
# does NOT match other must-pass prose ("(the must-pass deliverable)",
# "fail must-pass and 0", "GROUNDING GATE (must-pass):") -- those are a
# different sentence shape and not the H fix target.
MUST_PASS_SENTENCE_RE = re.compile(r"This is a must[- ]pass criterion\.?", re.IGNORECASE)
# Apply-mode removal also eats one leading space so no double-space is left.
MUST_PASS_REMOVE_RE = re.compile(r" ?This is a must[- ]pass criterion\.?", re.IGNORECASE)

NAME_LINE_RE = re.compile(r'^\s*name\s*=\s*"([^"]*)"\s*$')
CRITERION_HEADER_RE = re.compile(r"^\s*\[\[criterion\]\]\s*$")


def scan_judge_toml(task_name: str, group: str, judge_path: Path) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    try:
        text = judge_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return rows

    lines = text.split("\n")
    current_name = "?"
    awaiting_name = False
    for i, line in enumerate(lines, start=1):
        if CRITERION_HEADER_RE.match(line):
            awaiting_name = True
            current_name = "?"
            continue
        if awaiting_name:
            m = NAME_LINE_RE.match(line)
            if m:
                current_name = m.group(1)
                awaiting_name = False
        for _ in MUST_PASS_SENTENCE_RE.finditer(line):
            rows.append((task_name, group, current_name, str(i)))
    return rows


def apply_strip(judge_path: Path) -> int:
    """Remove the must-pass sentence from a judge.toml file in place,
    preserving LF line endings and leaving everything else byte-identical.
    Returns the number of sentences removed."""
    with judge_path.open("r", encoding="utf-8", newline="") as f:
        original = f.read()
    new_text, n = MUST_PASS_REMOVE_RE.subn("", original)
    if n:
        with judge_path.open("w", encoding="utf-8", newline="") as f:
            f.write(new_text)
    return n


def apply_single_task_strip(task_dir: Path) -> int:
    """Strip the must-pass sentence from ONLY task_dir's
    tests/deliverables_*/judge.toml files.

    Scope: ONLY this one task. Never lists or touches any other task
    directory -- the caller is responsible for passing a single task_dir,
    and this function never walks the corpus.

    Byte-exact: apply_strip() reads/writes each judge.toml with newline=""
    so LF line endings are preserved exactly; only the matched sentence
    (plus one leading space) is removed, leaving each criterion's
    `description` otherwise byte-identical.

    Idempotent: apply_strip() only writes when it finds a match (n > 0),
    so a judge.toml with no remaining match is a no-op on a second run.

    Returns a process exit code (0 success, 1 error).
    """
    groups = iter_deliverable_groups(task_dir)
    judge_files = [g / "judge.toml" for g in groups if (g / "judge.toml").is_file()]
    if not judge_files:
        print(
            f"ERROR: {task_dir.name}: no tests/deliverables*/judge.toml files found",
            file=sys.stderr,
        )
        return 1

    total_removed = 0
    for jt in judge_files:
        before_rows = scan_judge_toml(task_dir.name, jt.parent.name, jt)
        removed = apply_strip(jt)
        total_removed += removed
        if removed:
            print(f"{task_dir.name}/{jt.parent.name}/judge.toml: removed {removed} sentence(s)")
            for _, _, criterion_id, line in before_rows:
                print(f"  - criterion '{criterion_id}' (line {line}): sentence removed")
        else:
            print(f"{task_dir.name}/{jt.parent.name}/judge.toml: no match, no changes made (idempotent no-op)")

        # Read back and confirm.
        with jt.open("r", encoding="utf-8", newline="") as f:
            confirmed = f.read()
        if MUST_PASS_SENTENCE_RE.search(confirmed):
            print(
                f"ERROR: {task_dir.name}/{jt.parent.name}/judge.toml: sentence still present after apply",
                file=sys.stderr,
            )
            return 1

    print(
        f"{task_dir.name}: {total_removed} sentence(s) removed across {len(judge_files)} judge.toml file(s), "
        "read-back confirmed clean"
    )
    return 0


def scan_task(task_dir: Path) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for group_dir in iter_deliverable_groups(task_dir):
        jt = group_dir / "judge.toml"
        if jt.is_file():
            rows.extend(scan_judge_toml(task_dir.name, group_dir.name, jt))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR / "muststrip.csv")
    ap.add_argument("--task", type=str, default=None)
    ap.add_argument(
        "--apply",
        action="store_true",
        help="DANGER, gated: actually strip the sentence from every matched judge.toml. "
        "Not run in this build -- corpus-wide application is a coordinated main/Khiem pass.",
    )
    ap.add_argument(
        "--i-understand-this-is-corpus-wide-and-coordinated",
        action="store_true",
        dest="confirm_apply",
        help="Required alongside --apply as a second confirmation flag.",
    )
    ap.add_argument("--verdict-out", type=Path, default=None, help="write task_id,muststrip_scan pass|fail summary CSV")
    ap.add_argument(
        "--apply-task",
        type=str,
        default=None,
        metavar="TASK",
        help="strip must-pass sentences from ONLY this task's tests/deliverables_*/judge.toml "
        "(single-task scope; an owner applying the fix to their own claimed task). Requires "
        "--confirm-apply. Bypasses the corpus-wide scan entirely.",
    )
    ap.add_argument(
        "--confirm-apply",
        action="store_true",
        dest="confirm_apply_task",
        help="required alongside --apply-task, second confirmation flag "
        "(separate from --i-understand-this-is-corpus-wide-and-coordinated, which gates corpus-wide --apply)",
    )
    args = ap.parse_args()

    if args.apply_task:
        if not args.confirm_apply_task:
            print(
                "REFUSING --apply-task without --confirm-apply: pass both flags to strip must-pass "
                "sentences from this one task.",
                file=sys.stderr,
            )
            return 2
        task_dir = args.corpus_root / args.apply_task
        if not task_dir.is_dir():
            print(f"ERROR: task directory not found: {task_dir}", file=sys.stderr)
            return 1
        if not task_dir.name.startswith("SVC-PC-"):
            print(f"ERROR: {task_dir.name} is not an SVC-PC task directory", file=sys.stderr)
            return 1
        return apply_single_task_strip(task_dir)

    tasks = list_tasks(args.corpus_root)
    if args.task:
        tasks = [t for t in tasks if t.name == args.task]
    if not tasks:
        print(f"ERROR: no matching task directories under {args.corpus_root}", file=sys.stderr)
        return 1

    all_rows: list[tuple[str, str, str, str]] = []
    errors: list[str] = []
    for i, task_dir in enumerate(tasks, 1):
        try:
            all_rows.extend(scan_task(task_dir))
        except Exception as exc:
            errors.append(f"{task_dir.name}: {exc}")
        if i % 25 == 0:
            print(f"  ...{i}/{len(tasks)} tasks scanned", file=sys.stderr)

    n = write_csv(args.out, ["task", "group", "criterion_id", "line"], all_rows)
    tasks_flagged = {r[0] for r in all_rows}
    print(f"muststrip_scan: {n} must-pass sentences across {len(tasks_flagged)} of {len(tasks)} tasks, written to {args.out}")

    if args.apply:
        if not args.confirm_apply:
            print(
                "REFUSING --apply without --i-understand-this-is-corpus-wide-and-coordinated: "
                "this is a report-only build. Corpus-wide muststrip application must be "
                "coordinated by main/Khiem in one pass (GATE-V2 4 step 1 note).",
                file=sys.stderr,
            )
            return 2
        total_removed = 0
        for task_dir in tasks:
            for group_dir in iter_deliverable_groups(task_dir):
                jt = group_dir / "judge.toml"
                if jt.is_file():
                    total_removed += apply_strip(jt)
        print(f"muststrip_scan --apply: removed {total_removed} sentences", file=sys.stderr)

    if errors:
        print(f"  {len(errors)} tasks raised errors during scan:", file=sys.stderr)
        for e in errors:
            print(f"    {e}", file=sys.stderr)

    if args.verdict_out:
        verdict_rows = sorted(
            (t.name, "fail" if t.name in tasks_flagged else "pass") for t in tasks
        )
        vn = write_csv(args.verdict_out, ["task_id", "muststrip_scan"], verdict_rows)
        print(f"muststrip_scan: verdict CSV written, {vn} rows, to {args.verdict_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
