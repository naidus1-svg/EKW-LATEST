#!/usr/bin/env python3
"""Zip a set of built task packages straight from a build tree, using 7z.

This is the fast alternative to svc_stage_upload.py, described only as an unverified
prose command in ekw/svc-session-handoff-2026-09-14.md Section 4 until this script:

    7z a -tzip -mx=1 -mmt=on <dest> "@<listfile>"

run from the 03_dataos_ready tree, listfile written with newline='\n' explicitly
(Windows text mode injects \r\n into the listfile and 7z chokes on that).

The speed comes from skipping svc_stage_upload.py's copy step. That script copies
every task into a fresh --dest tree first and zips the copy, specifically so the
zip can be re-verified from the collected tree rather than the origin (see its own
docstring). This script has no --dest and no copy: it points 7z straight at --tree
and zips in place. That is real time saved on a large batch, and it is also exactly
why this script's own integrity checks matter more, not less: there is no second
copy of the files to fall back on, only the one 7z just read.

7z's own zip writer sets Unix permissions from what it can see on the source
filesystem. On Windows there is no exec bit for it to see, so a .sh file zipped by
7z from a Windows source tree will typically come out with no exec bit set on any
platform, and 7z will not fail or warn about it. svc_stage_upload.py sidesteps this
entirely by forcing 0o755 into every .sh entry's external_attr by hand.

This script now fixes the same defect as a post-processing pass rather than just
reporting it: after 7z writes the zip, _patch_exec_bits re-opens it and rewrites
only the central directory, forcing 0o755 onto every .sh entry the same way
svc_stage_upload.py does, by calling its _unix_info directly rather than
re-implementing the bit math. The fix is possible without recompressing anything
because Unix permission bits live only in a zip's central directory, never in a
local file record, so every local record (header + compressed bytes, .sh or not)
gets copied through byte for byte and only the central directory is rebuilt. A
ZIP64 archive (relevant once this corpus is closer to the full 635-task
population than to this 50-task test batch) falls outside that raw-copy path, so
_patch_exec_bits_recompress handles that case instead: correct but slower,
because it has to decompress and recompress every entry through the public
zipfile API rather than splice bytes directly.

The two checks that matter for this corpus are reused directly from
svc_stage_upload.py (find_noexec_sh, find_crlf_sh) rather than re-implemented here,
so both packaging paths refuse on exactly the same condition instead of two
hand-written copies drifting apart over time.
"""

from __future__ import annotations

import argparse
import copy
import json
import struct
import subprocess
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from svc_stage_upload import (  # noqa: E402
    REQUIRED,
    _unix_info,
    find_crlf_sh,
    find_noexec_sh,
)

# The stdlib zipfile module's own struct formats for a central-directory record and
# an end-of-central-directory record, imported rather than retyped so a mismatch
# with the format this Python's zipfile actually writes would surface as an
# ImportError, not a silently wrong binary layout.
_CENTRAL_DIR_FMT = zipfile.structCentralDir
_CENTRAL_DIR_SIG = zipfile.stringCentralDir
_END_ARCHIVE_FMT = zipfile.structEndArchive
_END_ARCHIVE_SIG = zipfile.stringEndArchive
_UINT32_MAX = 0xFFFFFFFF
_MAX_ENTRIES_NO_ZIP64 = 0xFFFF - 1

# Standard 7-Zip installer locations. The Windows installer does not add itself to
# PATH by default, so a PATH-only check (shutil.which) reports "not found" even on
# a box that has 7-Zip sitting right there. Check PATH first, then these, before
# giving up for real.
COMMON_7Z_PATHS = [
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
]


def find_7z() -> str | None:
    import shutil

    exe = shutil.which("7z") or shutil.which("7z.exe")
    if exe:
        return exe
    for p in COMMON_7Z_PATHS:
        if Path(p).is_file():
            return p
    return None


def _needs_zip64(infolist: list[zipfile.ZipInfo], central_dir_offset: int) -> bool:
    """True if the raw-copy path's fixed-width 32-bit fields cannot hold this zip.

    Local file records are never touched by the raw-copy path, so only the values
    that go into the rebuilt central directory matter here: the entry count, the
    central directory's own offset, and each entry's size/offset fields.
    """
    if len(infolist) > _MAX_ENTRIES_NO_ZIP64:
        return True
    if central_dir_offset > _UINT32_MAX:
        return True
    for zi in infolist:
        if zi.file_size > _UINT32_MAX or zi.compress_size > _UINT32_MAX:
            return True
        if zi.header_offset > _UINT32_MAX:
            return True
    return False


def _sh_exec_bits(arcname: str, tree: Path) -> tuple[int, int]:
    """(external_attr, create_system) for a .sh entry, straight from svc_stage_upload.

    Not reimplemented: this calls svc_stage_upload._unix_info directly and keeps
    only the two fields that matter for permissions, so the fast and slow packaging
    paths can never disagree bit-for-bit on what "executable" means in a zip.
    """
    unix = _unix_info(arcname, tree / arcname)
    return unix.external_attr, unix.create_system


def _write_patched_central_directory(
    fp, infolist: list[zipfile.ZipInfo], tree: Path, comment: bytes
) -> None:
    """Write a central directory + EOCD record for infolist to fp at its current
    position, identical to what zipfile.ZipFile itself would write on close(),
    except .sh entries get svc_stage_upload's exec-bit external_attr/create_system
    instead of whatever 7z wrote. Every other field, including every other entry's
    external_attr, is carried through unchanged from the original zip.
    """
    start = fp.tell()
    for zi in infolist:
        if zi.filename.endswith(".sh"):
            external_attr, create_system = _sh_exec_bits(zi.filename, tree)
        else:
            external_attr, create_system = zi.external_attr, zi.create_system

        dt = zi.date_time
        dosdate = (dt[0] - 1980) << 9 | dt[1] << 5 | dt[2]
        dostime = dt[3] << 11 | dt[4] << 5 | (dt[5] // 2)
        filename, flag_bits = zi._encodeFilenameFlags()
        record = struct.pack(
            _CENTRAL_DIR_FMT,
            _CENTRAL_DIR_SIG,
            zi.create_version,
            create_system,
            zi.extract_version,
            zi.reserved,
            flag_bits,
            zi.compress_type,
            dostime,
            dosdate,
            zi.CRC,
            zi.compress_size,
            zi.file_size,
            len(filename),
            len(zi.extra),
            len(zi.comment),
            0,
            zi.internal_attr,
            external_attr,
            zi.header_offset,
        )
        fp.write(record)
        fp.write(filename)
        fp.write(zi.extra)
        fp.write(zi.comment)

    central_dir_size = fp.tell() - start
    endrec = struct.pack(
        _END_ARCHIVE_FMT,
        _END_ARCHIVE_SIG,
        0,
        0,
        len(infolist),
        len(infolist),
        central_dir_size,
        start,
        len(comment),
    )
    fp.write(endrec)
    fp.write(comment)


def _patch_exec_bits_recompress(
    zip_path: Path, tree: Path, infolist: list[zipfile.ZipInfo]
) -> None:
    """Correct but slow fallback for a zip the raw-copy path's ZIP64 guard rejects.

    Out of reach for this 50-task test batch (around 9,000 entries, well under
    the 65,535-entry ZIP64 threshold); relevant once the corpus this script zips
    is closer to the full 635-task population. Every entry is read and rewritten
    through the public zipfile API, at a low compresslevel to keep this path from
    being much slower than it has to be, since correctness here matters more than
    speed: this only runs for the archives too large for the fast path to trust.
    """
    tmp_path = zip_path.with_name(zip_path.name + ".execfix.tmp")
    with zipfile.ZipFile(zip_path) as src, zipfile.ZipFile(
        tmp_path, "w", allowZip64=True
    ) as dst:
        dst.comment = src.comment
        for zi in infolist:
            data = src.read(zi.filename)
            if zi.filename.endswith(".sh"):
                new_zi = _unix_info(zi.filename, tree / zi.filename)
                new_zi.compress_type = zi.compress_type
            else:
                new_zi = copy.copy(zi)
            compresslevel = 1 if new_zi.compress_type == zipfile.ZIP_DEFLATED else None
            dst.writestr(new_zi, data, compresslevel=compresslevel)
    tmp_path.replace(zip_path)


def patch_exec_bits(zip_path: Path, tree: Path) -> None:
    """Rewrite the zip 7z just wrote so every .sh entry carries the 0o755 exec bit.

    This is the fix for the bug this script shipped with: 7z on Windows has no
    exec bit to copy from the source filesystem, so every .sh entry comes out of
    the 7z write with no executable permission in its central-directory
    external_attr. svc_stage_upload.py already showed what that does for real on
    the grader: Data-OS batch Oracle run #2314, all 39 tasks, RewardFileNotFoundError,
    because tests/test.sh was never executable so the verifier never ran.

    Nothing about the compressed bytes 7z wrote is wrong, only 4 bytes of
    metadata per .sh entry (plus create_system, the host-OS byte that tells an
    extractor the external_attr bits are Unix permissions at all rather than a
    DOS/FAT attribute byte to ignore), so this patches only that metadata rather
    than recompressing. Local file records carry no Unix permission bits at all,
    for any entry: those live solely in the central directory. So every local
    record is copied through unchanged, .sh or not, and only the central
    directory is rebuilt entry by entry.
    """
    with zipfile.ZipFile(zip_path) as zf:
        infolist = zf.infolist()
        central_dir_offset = zf.start_dir
        comment = zf.comment

    if _needs_zip64(infolist, central_dir_offset):
        _patch_exec_bits_recompress(zip_path, tree, infolist)
        return

    tmp_path = zip_path.with_name(zip_path.name + ".execfix.tmp")
    with open(zip_path, "rb") as src, open(tmp_path, "wb") as dst:
        remaining = central_dir_offset
        while remaining:
            chunk = src.read(min(4 * 1024 * 1024, remaining))
            if not chunk:
                raise OSError(
                    f"short read copying local file records from {zip_path} "
                    f"({remaining} bytes still expected)"
                )
            dst.write(chunk)
            remaining -= len(chunk)
        _write_patched_central_directory(dst, infolist, tree, comment)

    tmp_path.replace(zip_path)


def resolve_task_ids(args: argparse.Namespace) -> list[str]:
    if args.list:
        return json.loads(Path(args.list).read_text(encoding="utf-8"))
    if args.tasks:
        return list(args.tasks)
    raise SystemExit(
        "give task ids as positional arguments, or --list <json array file> "
        "(same shape as svc_stage_upload.py's --list)"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "tasks", nargs="*", help="task ids, space-separated (alternative to --list)"
    )
    ap.add_argument(
        "--list",
        help="json array file of task ids, same shape as svc_stage_upload.py's --list",
    )
    ap.add_argument(
        "--tree",
        required=True,
        help="the 03_dataos_ready root to zip from. Single tree only: 7z zips in "
        "place from one cwd, it does not search multiple trees the way "
        "svc_stage_upload.py's repeatable --tree does.",
    )
    ap.add_argument("--zip", dest="zip_path", required=True, help="output zip path")
    args = ap.parse_args()

    sevenzip = find_7z()
    if sevenzip is None:
        print("7z not found on PATH or in the standard 7-Zip install locations.")
        print("Install 7-Zip (https://www.7-zip.org/) and ensure 7z.exe is on PATH,")
        print("or use tools/svc_stage_upload.py instead (slower, no 7z dependency,")
        print("built-in copy-and-verify).")
        return 3

    tree = Path(args.tree)
    if not tree.is_dir():
        print(f"no such build tree: {tree}")
        return 2

    tasks = resolve_task_ids(args)
    zip_path = Path(args.zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"zipping {len(tasks)} tasks from {tree} (7z: {sevenzip})")

    missing, incomplete = [], []
    for t in tasks:
        src = tree / t
        if not src.is_dir():
            missing.append(t)
            continue
        absent = [r for r in REQUIRED if not (src / r).exists()]
        if absent:
            incomplete.append((t, absent))

    if missing:
        print(f"  MISSING  : {missing}")
    if incomplete:
        print("  INCOMPLETE (required entry absent in source tree):")
        for t, a in incomplete:
            print(f"    {t}: {a}")
    if missing or incomplete:
        print("\nrefusing to zip an incomplete set")
        return 1

    if zip_path.exists():
        zip_path.unlink()

    listfile_path = zip_path.with_name(zip_path.stem + "_listfile.txt")
    with open(listfile_path, "w", encoding="utf-8", newline="\n") as f:
        for t in tasks:
            f.write(t + "\n")

    cmd = [
        sevenzip,
        "a",
        "-tzip",
        "-mx=1",
        "-mmt=on",
        str(zip_path.resolve()),
        f"@{listfile_path.resolve()}",
    ]
    t0 = time.time()
    result = subprocess.run(cmd, cwd=str(tree), capture_output=True, text=True)
    zip_elapsed = time.time() - t0
    if result.returncode != 0:
        print(f"\n7z FAILED (exit {result.returncode}), {zip_elapsed:.1f}s")
        print(result.stdout)
        print(result.stderr)
        return 1
    if not zip_path.is_file():
        print("\n7z reported success but the zip was not written; not trusting it")
        return 1

    t1 = time.time()
    patch_exec_bits(zip_path, tree)
    patch_elapsed = time.time() - t1

    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        bad = z.testzip()
        noexec = find_noexec_sh(z)
        shcount = sum(1 for nm in names if nm.endswith(".sh"))
        crlf = find_crlf_sh(z, names)
    tops = {nm.split("/")[0] for nm in names}
    absent = sorted(set(tasks) - tops)

    size = zip_path.stat().st_size
    total_elapsed = zip_elapsed + patch_elapsed
    print(f"\nzip: {zip_path}  {size:,} bytes, {len(names)} entries")
    print(
        f"  7z write   : {zip_elapsed:.1f}s, exec-bit patch: {patch_elapsed:.1f}s, "
        f"total: {total_elapsed:.1f}s"
    )
    print(f"  testzip    : {'ok' if bad is None else 'CORRUPT at ' + bad}")
    print(f"  top-level  : {len(tops)} folders")
    print(
        f"  all tasks present: {not absent}" + (f"  MISSING {absent}" if absent else "")
    )
    print(
        f"  .sh entries: {shcount}, without an exec bit: {len(noexec)}, "
        f"carrying CRLF: {len(crlf)}"
    )
    if noexec:
        print("  FAIL: these would not be executable on the grader")
        for nm in noexec[:5]:
            print(f"    {nm}")
    if crlf:
        print("  FAIL: Linux reads the carriage return as part of the interpreter name")
        for nm in crlf[:5]:
            print(f"    {nm}")
    if shcount == 0:
        print("  WARNING: no .sh entries at all, nothing would run on the grader")

    ok = bad is None and not absent and not noexec and not crlf and shcount > 0
    print(f"\noverall: {'PASS' if ok else 'FAIL'}")

    (zip_path.with_name(zip_path.stem + "_manifest.json")).write_text(
        json.dumps(
            {
                "tasks": tasks,
                "source_tree": str(tree),
                "zip_bytes": size,
                "entry_count": len(names),
                "zip_seconds": round(zip_elapsed, 1),
                "exec_bit_patch_seconds": round(patch_elapsed, 1),
                "total_seconds": round(total_elapsed, 1),
                "testzip_ok": bad is None,
                "noexec_sh": noexec,
                "crlf_sh": crlf,
                "sh_count": shcount,
                "missing_tops": absent,
                "overall_pass": ok,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
