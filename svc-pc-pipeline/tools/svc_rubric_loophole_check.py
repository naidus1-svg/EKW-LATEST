#!/usr/bin/env python3
"""svc_rubric_loophole_check.py - ADVISORY static scan for the rubric loopholes that survived a round-1 fix
and got the task rejected again in round 2 (measured on the wave-1 resubmit, 2026-09-21).

It flags, per criterion `description` in every tests/*/judge.toml:

  DUAL_BASIS   - an "Expected:" that offers two different accepted values/bases joined by "or"
                 (e.g. "Expected: $120.41 on the post-bridge basis, or $125.xx on the export basis").
                 This literally tells the judge to accept either, so a wrong-basis answer passes. This is
                 exactly the 1-2-0 round-2 failure, and a grammar-split COPIES it into every child criterion.

  OR_ALT       - a weaker signal: "Expected:" text with an " or " between two $/number tokens even without
                 the word "basis" (a permissive alternative that may or may not be legitimate).

ADVISORY ONLY: it prints flags, always exits 0. Do NOT wire it as a hard block until precision is measured on
tasks that MUST pass (per the promoted-kinds-precision rule). Legitimate uses of "or" exist (an acceptable
rounding band, "N/A or blank"); this scan is a review prompt for the fixer, not a verdict.

Usage:
    python svc_rubric_loophole_check.py <task_dir_or_tests_dir> [more dirs...]
    # walks each path for */judge.toml
"""

from __future__ import annotations

import os
import re
import sys

# an "Expected:" clause = from 'Expected:' to the next sentence end or end of string
EXPECTED = re.compile(r"Expected:\s*(.+?)(?:\.\s|\.'|\.\"|$)", re.S)
MONEY = re.compile(r"\$\s?[\d,]+(?:\.\d+)?")
NUMBER = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")
BASIS = re.compile(r"\bbasis\b", re.I)
# split a description into its criterion name + the description body
NAME = re.compile(r'name\s*=\s*["\']([^"\']+)["\']')


def scan_toml(text: str):
    """Return a list of (criterion_name, kind, snippet) flags for one judge.toml's text."""
    flags = []
    # split into [[criterion]] blocks (tolerant of [[criteria]] etc.)
    blocks = re.split(r"(?m)^\s*\[\[", text)
    for b in blocks:
        nm = NAME.search(b)
        name = nm.group(1) if nm else "?"
        for m in EXPECTED.finditer(b):
            clause = m.group(1)
            if " or " not in clause.lower():
                continue
            monies = MONEY.findall(clause)
            # two different money values around an "or" -> dual accepted value
            distinct_money = len({x.replace(" ", "") for x in monies})
            has_basis = bool(BASIS.search(clause))
            if has_basis and (
                distinct_money >= 2 or clause.lower().count(" basis") >= 2
            ):
                flags.append((name, "DUAL_BASIS", clause.strip()[:200]))
            elif distinct_money >= 2:
                flags.append((name, "OR_ALT", clause.strip()[:200]))
    return flags


def walk_judge_tomls(root: str):
    if os.path.isfile(root) and root.endswith(".toml"):
        yield root
        return
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            if f == "judge.toml":
                yield os.path.join(dp, f)


def main(argv):
    if not argv:
        print(__doc__)
        return 0
    total = 0
    for root in argv:
        for tp in walk_judge_tomls(root):
            try:
                text = open(tp, encoding="utf-8", errors="replace").read()
            except Exception as e:  # noqa: BLE001
                print(f"  <read err {tp}: {e}>")
                continue
            for name, kind, snip in scan_toml(text):
                total += 1
                rel = tp.replace("\\", "/")
                print(f"[{kind}] {rel} :: {name}\n    Expected: {snip}")
    print(f"\n{total} loophole flag(s). ADVISORY - review, do not auto-block.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
