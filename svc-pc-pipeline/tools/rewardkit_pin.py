#!/usr/bin/env python3
"""
rewardkit_pin.py - GATE-V2 class I: harbor-rewardkit[all] unpinned in test.sh.

Finds every task whose tests/test.sh installs `harbor-rewardkit[all]`
unpinned (no ==version) and reports the exact current line plus a proposed
pinned replacement line.

This script is REPORT-ONLY by default. It does not edit any test.sh unless
--apply is passed. Corpus-wide application is Khiem's PR into
EKW_QC_pipeline (GATE-V2 3.3: "corpus-wide template fixes, one PR ...
applied to all 202 by script before the next batch"). Use --print-diff to
see a unified diff per affected task without writing anything.

Pin version (report/scan mode): defaults to 0.2.0 (GATE-V2 4:
"harbor-rewardkit==0.2.0 or the installed version"). Pass --version to
override, or --detect-installed to read the version from `pip show
harbor-rewardkit` on this machine.

Per-task apply mode (GATE-V2 3.6.3): --apply <TASK> --confirm-apply edits
ONLY 03_dataos_ready/<TASK>/tests/test.sh, pinning its unpinned
harbor-rewardkit[all] install to harbor-rewardkit[all]==0.1.7 (the version
DataOS graded the corpus with) -- not the 0.2.0 scan default above. This is
for an OWNER applying the fix to their OWN claimed task; it touches no
other task directory. Byte-exact (reads/writes with newline="" so LF line
endings are preserved exactly, only the matched install-line text
changes), idempotent (a no-op if the line is already pinned), and reads
the file back after writing to confirm the pin landed.

READ-ONLY except under --apply: absent --apply, only reads tests/test.sh
and never modifies the corpus.

Output (scan mode): CSV [task, current_line, proposed_line].

Usage:
    python3 rewardkit_pin.py [--corpus-root PATH] [--out PATH] [--version X.Y.Z]
                              [--detect-installed] [--print-diff]
    python3 rewardkit_pin.py --apply <TASK> --confirm-apply
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import DEFAULT_CORPUS_ROOT, DEFAULT_REPORTS_DIR, list_tasks, read_text_safe, write_csv

DEFAULT_VERSION = "0.2.0"

# Per-task --apply pins to this exact version (GATE-V2 3.6.3: the version
# DataOS graded the corpus with). Deliberately different from
# DEFAULT_VERSION above, which is the report-only scan's proposed pin
# (GATE-V2 4) absent a --version override.
APPLY_PIN_VERSION = "0.1.7"

# Matches `pip install --quiet 'harbor-rewardkit[all]'` (or similar quoting)
# with NO version pin after the closing extras bracket.
UNPINNED_RE = re.compile(
    r"pip install[^\n]*['\"]harbor-rewardkit\[all\](?!==)['\"]"
)
# Matches the same install line once it already carries ANY version pin
# (used to detect the already-pinned/idempotent-no-op state under --apply).
ALREADY_PINNED_RE = re.compile(
    r"pip install[^\n]*['\"]harbor-rewardkit\[all\]=="
)


def detect_installed_version() -> str | None:
    try:
        out = subprocess.run(
            ["pip", "show", "harbor-rewardkit"], capture_output=True, text=True, timeout=10
        ).stdout
        for line in out.splitlines():
            if line.lower().startswith("version:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None


def scan_task(task_dir: Path, pin_version: str) -> tuple[str, str] | None:
    test_sh = task_dir / "tests" / "test.sh"
    text = read_text_safe(test_sh)
    if not text:
        return None
    for line in text.splitlines():
        if UNPINNED_RE.search(line):
            proposed = line.replace(
                "harbor-rewardkit[all]", f"harbor-rewardkit[all]=={pin_version}"
            )
            return (line.strip(), proposed.strip())
    return None


def apply_single_task(task_dir: Path, pin_version: str) -> int:
    """Pin harbor-rewardkit[all] in task_dir/tests/test.sh to ==pin_version.

    Scope: ONLY this one task's test.sh. Never lists or touches any other
    task directory -- the caller is responsible for passing a single
    task_dir, and this function never walks the corpus.

    Byte-exact: reads/writes with newline="" so LF line endings are
    preserved exactly; only the matched install-line text changes, via a
    regex substitution scoped to the matched span (everything else in the
    file, including all other lines, is untouched).

    Idempotent: if the install line is already pinned (to any version,
    including pin_version), no write occurs and this reports a no-op.

    Returns a process exit code (0 success, 1 error).
    """
    test_sh = task_dir / "tests" / "test.sh"
    if not test_sh.is_file():
        print(f"ERROR: {test_sh} does not exist", file=sys.stderr)
        return 1

    with test_sh.open("r", encoding="utf-8", newline="") as f:
        original = f.read()

    if not UNPINNED_RE.search(original):
        if ALREADY_PINNED_RE.search(original):
            print(f"{task_dir.name}: already pinned, no changes made (idempotent no-op)")
            return 0
        print(
            f"ERROR: {task_dir.name}: no harbor-rewardkit[all] install line found in {test_sh}",
            file=sys.stderr,
        )
        return 1

    old_lines = [line.strip() for line in original.splitlines() if UNPINNED_RE.search(line)]

    def repl(m: re.Match) -> str:
        return m.group(0).replace("harbor-rewardkit[all]", f"harbor-rewardkit[all]=={pin_version}")

    new_text, n = UNPINNED_RE.subn(repl, original)
    if n == 0:
        print(f"ERROR: {task_dir.name}: substitution matched but produced no changes", file=sys.stderr)
        return 1

    with test_sh.open("w", encoding="utf-8", newline="") as f:
        f.write(new_text)

    # Read back and confirm the pin landed byte-exact.
    with test_sh.open("r", encoding="utf-8", newline="") as f:
        confirmed = f.read()
    if confirmed != new_text:
        print(f"ERROR: {task_dir.name}: read-back mismatch after write", file=sys.stderr)
        return 1
    if UNPINNED_RE.search(confirmed):
        print(f"ERROR: {task_dir.name}: unpinned pattern still present after apply", file=sys.stderr)
        return 1

    new_lines = [
        line.strip() for line in confirmed.splitlines() if f"harbor-rewardkit[all]=={pin_version}" in line
    ]

    print(f"{task_dir.name}: pinned {n} line(s) in {test_sh}")
    for old, new in zip(old_lines, new_lines):
        print(f"  - {old}")
        print(f"  + {new}")
    print(f"{task_dir.name}: read-back confirmed, pin landed byte-exact")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT, help="corpus root directory")
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORTS_DIR / "rewardkit_pin.csv", help="output CSV path")
    ap.add_argument("--version", type=str, default=None, help=f"pin version (default {DEFAULT_VERSION}; --apply uses {APPLY_PIN_VERSION} unless overridden here)")
    ap.add_argument("--detect-installed", action="store_true", help="use `pip show harbor-rewardkit` version instead of default")
    ap.add_argument("--print-diff", action="store_true", help="print a unified diff line per affected task, apply nothing")
    ap.add_argument("--verdict-out", type=Path, default=None, help="write task_id,rewardkit_pin pass|fail summary CSV")
    ap.add_argument(
        "--apply",
        type=str,
        default=None,
        metavar="TASK",
        help="apply the rewardkit pin to ONLY this task's tests/test.sh (single-task scope; an owner "
        "applying the fix to their own claimed task). Requires --confirm-apply. Bypasses the "
        "corpus-wide scan entirely.",
    )
    ap.add_argument(
        "--confirm-apply",
        action="store_true",
        help="required alongside --apply, second confirmation flag",
    )
    args = ap.parse_args()

    if args.apply:
        if not args.confirm_apply:
            print(
                "REFUSING --apply without --confirm-apply: pass both flags to pin this one task's test.sh.",
                file=sys.stderr,
            )
            return 2
        apply_version = args.version if args.version is not None else APPLY_PIN_VERSION
        task_dir = args.corpus_root / args.apply
        if not task_dir.is_dir():
            print(f"ERROR: task directory not found: {task_dir}", file=sys.stderr)
            return 1
        if not task_dir.name.startswith("SVC-PC-"):
            print(f"ERROR: {task_dir.name} is not an SVC-PC task directory", file=sys.stderr)
            return 1
        return apply_single_task(task_dir, apply_version)

    pin_version = args.version
    if pin_version is None:
        if args.detect_installed:
            pin_version = detect_installed_version() or DEFAULT_VERSION
        else:
            pin_version = DEFAULT_VERSION

    tasks = list_tasks(args.corpus_root)
    if not tasks:
        print(f"ERROR: no SVC-PC-* task directories found under {args.corpus_root}", file=sys.stderr)
        return 1

    rows = []
    for task_dir in tasks:
        result = scan_task(task_dir, pin_version)
        if result:
            rows.append((task_dir.name, result[0], result[1]))

    n = write_csv(args.out, ["task", "current_line", "proposed_line"], rows)
    print(f"rewardkit_pin: {len(tasks)} tasks scanned, {n} unpinned, pin target ==={pin_version}, written to {args.out}")

    if args.print_diff:
        for task_name, current, proposed in rows:
            print(f"--- {task_name}/tests/test.sh")
            print(f"-{current}")
            print(f"+{proposed}")

    if args.verdict_out:
        flagged = {r[0] for r in rows}
        verdict_rows = sorted(
            (t.name, "fail" if t.name in flagged else "pass") for t in tasks
        )
        vn = write_csv(args.verdict_out, ["task_id", "rewardkit_pin"], verdict_rows)
        print(f"rewardkit_pin: verdict CSV written, {vn} rows, to {args.verdict_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
