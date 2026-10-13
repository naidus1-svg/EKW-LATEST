#!/usr/bin/env python3
"""Collect built task packages into one tree and zip it for Data-OS.

Data-OS's new-dataset form takes a single `.zip` (its file input is `accept=".zip"`,
labelled "ZIP archive of Harbor tasks"). Packages can live across several build trees,
as the 2026-08-31 batch of 39 did after being rebuilt in three passes, so they have to
be gathered first. Pass `--tree` once per build tree, in search order.

Copy, never move: the build trees stay intact so the packages can be rebuilt or
re-verified afterwards. Every package is re-verified from the COLLECTED tree rather than
from its origin, because the thing that can go wrong here is the collection step losing
or truncating a file, and checking the source would not catch that.

Two defects have shipped from this step and neither was visible in the file content, but
they are handled differently and the difference matters. A `.sh` carrying CRLF killed
every task in dataset 643, because Linux read the carriage return as part of the
interpreter name and exited 127; that is detected here and the archive is refused. A `.sh`
with no executable bit killed Oracle run #2314; that one is not detected, it is prevented,
because `_unix_info` writes 0o755 for every `.sh` regardless of the source file's mode. The
exec-bit scan near the end therefore checks this file against itself, not the input.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
import zipfile
from pathlib import Path

DEFAULT_TREES = [
    "C:/b/_out_all32/03_dataos_ready",
    "C:/b/_out_six/03_dataos_ready",
    "C:/b/_out_15/03_dataos_ready",
]
DEFAULT_DEST = "C:/b/_upload39"
DEFAULT_ZIP = "C:/b/_upload39.zip"
REQUIRED = ["task.toml", "instruction.md", "tests", "solution"]


def find_noexec_sh(z: zipfile.ZipFile) -> list[str]:
    """.sh entries in an open zip whose external_attr carries no exec bit.

    Shared with tools/svc_fast_zip.py so both packaging paths check the exact
    same condition instead of two hand-written copies drifting apart.
    """
    return [
        i.filename
        for i in z.infolist()
        if i.filename.endswith(".sh") and not ((i.external_attr >> 16) & 0o111)
    ]


def find_crlf_sh(z: zipfile.ZipFile, names: list[str]) -> list[str]:
    """.sh entries in an open zip carrying CRLF, which breaks the Linux grader.

    Shared with tools/svc_fast_zip.py, same reason as find_noexec_sh above.
    """
    return [nm for nm in names if nm.endswith(".sh") and b"\r\n" in z.read(nm)]


def _unix_info(arcname: str, src: Path) -> zipfile.ZipInfo:
    """A ZipInfo carrying Unix permissions, because the grader runs on Linux.

    This is the defect that killed Data-OS batch Oracle run #2314 on 2026-08-31.
    `ZipFile.write()` copies the source file's mode, and on Windows there is no
    executable bit to copy, so all 78 `.sh` entries went in at 0o666 with
    create_system 0. On the grader `tests/test.sh` was then not executable, the
    verifier never ran, no `reward.txt` was ever written, and all 39 tasks threw
    `RewardFileNotFoundError`. Nothing about the task content was wrong, and no
    content check could have caught it: the bytes were perfect and the file mode
    was not.

    So permissions are set explicitly rather than inherited: 0o755 for shell
    scripts, 0o644 for everything else, and create_system 3 (Unix) so the mode in
    external_attr is honoured on extraction.

    Note what that means for the exec-bit scan further down. The mode here comes
    from the arcname alone, never from `src.stat()`, so a source file with no
    executable bit is silently corrected rather than caught. That scan is a
    self-consistency assertion on this function, not a guard against bad input,
    and it can only fire if this line stops forcing the mode. The CRLF and
    no-shell-scripts checks ARE input guards and do refuse real defects.
    """
    st = src.stat()
    zi = zipfile.ZipInfo(arcname, date_time=time.localtime(st.st_mtime)[:6])
    zi.create_system = 3
    mode = 0o755 if arcname.endswith(".sh") else 0o644
    zi.external_attr = (mode & 0o7777) << 16
    return zi


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default="C:/b/_the39.json")
    ap.add_argument(
        "--tree",
        action="append",
        dest="trees",
        metavar="PATH",
        help="an 03_dataos_ready root to draw packages from; repeatable, "
        "searched in the order given. Defaults to the three trees that built "
        "the 2026-08-31 batch.",
    )
    ap.add_argument("--dest", default=DEFAULT_DEST, help="collected tree")
    ap.add_argument("--zip", dest="zip_path", default=DEFAULT_ZIP)
    args = ap.parse_args()

    trees = [Path(p) for p in (args.trees or DEFAULT_TREES)]
    dest = Path(args.dest)
    zip_path = Path(args.zip_path)
    absent_trees = [str(t) for t in trees if not t.is_dir()]
    if absent_trees:
        print(f"no such build tree: {', '.join(absent_trees)}")
        return 2

    tasks = json.loads(Path(args.list).read_text(encoding="utf-8"))
    print(f"staging {len(tasks)} tasks from {len(trees)} tree(s)")
    for t in trees:
        print(f"  tree: {t}")

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    placed, missing, incomplete = {}, [], []
    for t in tasks:
        src = next((tree / t for tree in trees if (tree / t).is_dir()), None)
        if src is None:
            missing.append(t)
            continue
        shutil.copytree(src, dest / t)
        absent = [r for r in REQUIRED if not (dest / t / r).exists()]
        if absent:
            incomplete.append((t, absent))
        placed[t] = src.parent.parent.name

    print(f"  copied   : {len(placed)}")
    if missing:
        print(f"  MISSING  : {missing}")
    if incomplete:
        print("  INCOMPLETE (required entry absent after copy):")
        for t, a in incomplete:
            print(f"    {t}: {a}")
    if missing or incomplete:
        print("\nrefusing to zip an incomplete set")
        return 1

    dirs = sorted(p.name for p in dest.iterdir() if p.is_dir())
    if len(dirs) != len(tasks):
        print(f"\ncount mismatch: {len(dirs)} dirs for {len(tasks)} tasks")
        return 1

    if zip_path.exists():
        zip_path.unlink()
    n = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(dest.rglob("*")):
            if f.is_file():
                rel = f.relative_to(dest).as_posix()
                z.writestr(_unix_info(rel, f), f.read_bytes(), zipfile.ZIP_DEFLATED)
                n += 1

    # Read the archive back rather than trusting the write, and confirm every task is
    # represented by at least one entry under its own top-level folder.
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        bad = z.testzip()
        noexec = find_noexec_sh(z)
        shcount = sum(1 for nm in names if nm.endswith(".sh"))
        crlf = find_crlf_sh(z, names)
    tops = {nm.split("/")[0] for nm in names}
    print(f"\nzip: {zip_path}  {zip_path.stat().st_size:,} bytes, {n} files")
    print(f"  integrity  : {'ok' if bad is None else 'CORRUPT at ' + bad}")
    print(f"  top-level  : {len(tops)} folders")
    print(
        f"  .sh entries: {shcount}, without an exec bit: {len(noexec)}, carrying CRLF: {len(crlf)}"
    )
    if noexec:
        # Unreachable while _unix_info forces 0o755 by arcname. If this ever fires,
        # the bug is in this file, not in the packages it was handed.
        print("  REFUSING: these would not be executable on the grader")
        for nm in noexec[:5]:
            print(f"    {nm}")
        return 1
    if crlf:
        print(
            "  REFUSING: Linux reads the carriage return as part of the interpreter name"
        )
        for nm in crlf[:5]:
            print(f"    {nm}")
        return 1
    if shcount == 0:
        print("  REFUSING: no .sh entries at all, so nothing would run on the grader")
        return 1
    absent = sorted(set(tasks) - tops)
    print(
        f"  all tasks present: {not absent}" + (f"  MISSING {absent}" if absent else "")
    )

    per_tree = {}
    for t, tree in placed.items():
        per_tree[tree] = per_tree.get(tree, 0) + 1
    print(f"  sourced from: {per_tree}")
    (zip_path.with_name(zip_path.stem + "_manifest.json")).write_text(
        json.dumps(
            {
                "tasks": tasks,
                "source_tree": placed,
                "zip_bytes": zip_path.stat().st_size,
                "file_count": n,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0 if (bad is None and not absent) else 1


if __name__ == "__main__":
    raise SystemExit(main())
