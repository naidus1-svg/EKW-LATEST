#!/usr/bin/env python3
"""Fix mojibake in SVC-PC package file/dir NAMES and the config paths that reference them.

The corruption is a UTF-8 string misread through a single-byte code page (classically CP437):
e.g. an em-dash (U+2014) becomes a 3-char run. The signal that a non-ASCII run IS mojibake is that
re-encoding it through that code page and decoding as UTF-8 SUCCEEDS and yields a different string
(clean text like an em-dash does not round-trip). The fix applies that repair consistently to
(a) every file/dir name and (b) every text config file (.toml/.txt/.md/.json/.csv), so judge.toml
paths keep matching the renamed files.

Only NAMES and text refs are touched; binary bytes (xlsx/docx/pdf/pptx) are renamed, never edited.
Deterministic. Verify after with the mojibake check, the missing-file check, and the oracle.

Usage: svc_fix_mojibake_names.py <task_dir> [--apply]   (dry-run without --apply)
"""

import argparse
import os
import re
import sys

CODEPAGES = ["cp437", "cp1252", "latin-1"]
NONASCII_RUN = re.compile(r"[^\x00-\x7F]+")


def demojibake_token(tok):
    for cp in CODEPAGES:
        try:
            fixed = tok.encode(cp).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if fixed != tok:
            return fixed
    return None


def repair_string(s):
    """Repair every mojibake run; iterate to undo double-encoding. Returns (new, changed)."""
    changed = False
    for _ in range(4):
        step = s
        for m in list(NONASCII_RUN.finditer(step)):
            tok = m.group(0)
            fixed = demojibake_token(tok)
            if fixed is not None:
                step = step.replace(tok, fixed)
        if step == s:
            break
        s, changed = step, True
    return s, changed


def fix_task(task_dir, apply=False):
    renames, edited = [], []

    # 1. rename files/dirs deepest-first so parent renames do not invalidate child paths
    for root, dirs, files in os.walk(task_dir, topdown=False):
        for name in files + dirs:
            new, ch = repair_string(name)
            if ch and new != name:
                renames.append((os.path.join(root, name), os.path.join(root, new)))
    if apply:
        for old, new in renames:
            if os.path.exists(old) and not os.path.exists(new):
                os.rename(old, new)

    # 2. repair text config contents (paths + any inline mojibake)
    for root, _, files in os.walk(task_dir):
        for fn in files:
            if not fn.lower().endswith((".toml", ".txt", ".md", ".json", ".csv")):
                continue
            p = os.path.join(root, fn)
            try:
                with open(p, encoding="utf-8") as f:
                    txt = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            new, ch = repair_string(txt)
            if ch:
                edited.append(p)
                if apply:
                    with open(p, "w", encoding="utf-8", newline="\n") as f:
                        f.write(new)
    return renames, edited


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task_dir")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    renames, edited = fix_task(a.task_dir, a.apply)
    name = os.path.basename(os.path.normpath(a.task_dir))
    print(
        f"{name}: {len(renames)} name(s) to rename, {len(edited)} text file(s) to repair"
    )
    for old, new in renames[:6]:
        print(f"  rename: {os.path.basename(old)!r} -> {os.path.basename(new)!r}")
    for p in edited[:6]:
        print(f"  edit:   {os.path.relpath(p, a.task_dir)}")
    print(f"{name}: {'APPLIED' if a.apply else 'DRY-RUN'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
