"""Mechanical cleanup for stray backup files left in a task's solution/files/ directory.

Provenance: the first C/D-category (structural / mechanical) autofix built for this project,
following the safety discipline tools/svc_formula_cache_autofix.py already uses for the E
(formula-cache) category -- itself generalized from the sibling harbor-qc-checks repo's script
of the same name. Same rule, applied to a different defect shape: never fabricate a value or
guess at intent, only act when the fix can be independently proven safe from the filesystem
itself, and leave anything in doubt untouched and reported rather than silently skipped.

Why this exists: SVC-PC-21-2-0's solution/files/ carries both
Close_Authority_and_Review_Map.xlsx and Close_Authority_and_Review_Map.xlsx.orig side by side --
almost certainly a leftover backup written by a formula_cache_autofix.py pass (that script backs
up to "<file>.orig" before every write, see its patch_workbook_file()) that was never cleaned up
afterward. No existing gating script flags this. A stray .orig/.bak file sitting in a graded
deliverable directory does not belong there: it can get zipped into evals.zip, bloats the task
package, and confuses anyone diffing solution/files/ by hand.

What counts as "safe" here, and what does not
-----------------------------------------------
This script deletes ONLY a backup-shaped file (name ends in ".orig" or ".bak", case-insensitive)
for which the real, non-backup file it is a backup OF is independently confirmed present, in the
SAME directory, and non-empty (size > 0 bytes). "Independently confirmed" means this script
never trusts the backup file's own existence as proof the real file is fine -- it re-derives the
expected real filename by stripping the exact suffix, then does a fresh filesystem stat on that
path, separate from anything already known about the backup.

If the real file is missing, or exists but is zero bytes, the candidate is left untouched and
reported as unsafe_skip: deleting the backup in that state could leave a task with neither a
real deliverable nor a recovery copy, which is strictly worse than a messy directory. This is
the same worst-case posture formula_cache_autofix.py takes (revert to backup on any doubt, never
leave a task in an unverifiable state), applied in the opposite direction: here the backup is
the thing being removed, so the bar is proving the file it backs up is not just present but
actually usable.

A file that merely ends in ".orig" or ".bak" but has NO same-directory non-suffixed counterpart
at all (e.g. a source file that legitimately happens to be named that way) is also left alone
and reported as unsafe_skip -- there is nothing to independently confirm, so nothing is assumed
about why it is there.

This script makes no judgment about WHY a backup file exists, never inspects file contents
(byte-identical or not is irrelevant to the safety gate -- only presence and non-emptiness of
the real file matter), and never writes to the real (non-backup) file. It only ever considers
deleting the backup-shaped file, and only after the safety gate above passes.

Fix mechanism
-------------
1. Recursively walk each task's solution/files/ directory (task dirs given on the command line,
   or --all to sweep every task under --root). rglob, not a flat listdir, so a backup file
   sitting in a nested subdirectory of solution/files/ is still found.
2. For every file whose name (case-insensitive) ends in ".orig" or ".bak", strip that exact
   suffix to get the candidate's expected real-file path in the same directory.
3. Stat that real-file path fresh. The candidate is delete-eligible only if the real file
   exists, is a regular file, and has size > 0 bytes.
4. Report-only by default. Nothing is deleted unless --apply is passed explicitly; --dry-run is
   accepted as an explicit alias for the (already default) report-only mode, so a command copied
   from planning notes that says --dry-run does exactly what it says and nothing more.
5. On an --apply run, every deletion is logged to the JSON report (task id, backup path, backup
   size and sha256, its real counterpart's path and size, UTC timestamp) BEFORE the delete is
   issued, then the log entry is marked confirmed only after unlink() returns without error --
   so a report entry is never written for a delete that did not actually happen, and nothing is
   deleted without first being logged.
6. Before that unlink, the backup file is byte-copied to --quarantine-dir and the copy's size is
   checked against the source; the delete is aborted for that file if the copy did not land
   cleanly. After the unlink, the real (non-backup) counterpart is re-statted and its size
   compared against what was recorded immediately before the delete -- this script never writes
   to that file, so any drift means something unexpected happened, and the entry is flagged
   (action "delete_failed_real_file_changed") rather than reported as a clean success. Every
   file this script ever removes is therefore recoverable from --quarantine-dir; quarantine
   content is left on disk for a human to review or clear, this script never deletes its own
   quarantine copies.

CLI:
    python tools/svc_stray_backup_cleanup.py SVC-PC-21-2-0 --root <path> --out report.json
    python tools/svc_stray_backup_cleanup.py --all --root <path> --dry-run --out report.json
    python tools/svc_stray_backup_cleanup.py --all --root <path> --apply --out report.json \
        --quarantine-dir <path>
"""

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUARANTINE = (
    REPO_ROOT / "ekw" / "svc-stray-backup-cleanup-2026-09-14-quarantine"
)

BACKUP_SUFFIXES = (".orig", ".bak")


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# task discovery (mirrors the find_task_dirs shape used across tools/svc_*_check.py)
# ---------------------------------------------------------------------------


def find_task_dirs(root, task_ids=None, id_prefix="SVC-PC-"):
    if task_ids:
        dirs = []
        for tid in task_ids:
            p = root / tid
            if not p.is_dir():
                print(f"WARNING: task dir not found, skipping: {p}", file=sys.stderr)
                continue
            dirs.append(p)
        return dirs
    return sorted(
        p for p in root.iterdir() if p.is_dir() and p.name.startswith(id_prefix)
    )


# ---------------------------------------------------------------------------
# candidate discovery + safety gate
# ---------------------------------------------------------------------------


def find_candidates(task_dir):
    """Returns a list of candidate dicts for every backup-shaped file under
    task_dir/solution/files/. Each candidate has been through the safety gate already
    (safe / unsafe_skip_missing_real / unsafe_skip_empty_real) -- this function makes no
    filesystem writes, so it is exactly what both --dry-run and --apply see."""
    files_dir = task_dir / "solution" / "files"
    if not files_dir.is_dir():
        return []

    candidates = []
    for p in sorted(files_dir.rglob("*")):
        if not p.is_file():
            continue
        name_lower = p.name.lower()
        suffix = next((s for s in BACKUP_SUFFIXES if name_lower.endswith(s)), None)
        if suffix is None:
            continue

        real_name = p.name[: -len(suffix)]
        real_path = p.parent / real_name

        backup_stat = p.stat()
        entry = {
            "task_id": task_dir.name,
            "backup_path": str(p.relative_to(task_dir)).replace("\\", "/"),
            "backup_size": backup_stat.st_size,
            "real_path": str(real_path.relative_to(task_dir)).replace("\\", "/"),
        }

        if not real_path.is_file():
            entry["safe"] = False
            entry["reason"] = (
                "no non-backup counterpart file exists in the same directory"
            )
            entry["real_size"] = None
        else:
            real_size = real_path.stat().st_size
            entry["real_size"] = real_size
            if real_size == 0:
                entry["safe"] = False
                entry["reason"] = (
                    "counterpart file exists but is zero bytes -- deleting the backup "
                    "could leave the task with no usable deliverable and no recovery copy"
                )
            else:
                entry["safe"] = True
                entry["reason"] = "counterpart file confirmed present and non-empty"

        candidates.append(entry)
    return candidates


# ---------------------------------------------------------------------------
# per-task driver
# ---------------------------------------------------------------------------


def process_task(task_dir, apply_deletes, quarantine_root=None):
    """quarantine_root, when apply_deletes is True: every backup file is byte-copied here
    (under <quarantine_root>/<task_id>/<backup filename>) and the copy is size-verified
    BEFORE the original is unlinked, so every delete this script performs stays fully
    undoable even though the deleted content is, by definition, a redundant copy. After
    the unlink, the real (non-backup) counterpart is re-statted and its size compared
    against what was recorded before the delete -- this script never touches the real
    file, so any drift there means something unexpected happened and the deletion is
    flagged rather than reported as a clean success. This is the same "prove it, revert
    on doubt" posture formula_cache_autofix.py uses for its own writes, applied to a
    delete rather than a patch."""
    candidates = find_candidates(task_dir)
    result = {
        "task_id": task_dir.name,
        "n_candidates": len(candidates),
        "candidates": [],
    }
    for c in candidates:
        entry = dict(c)
        if not c["safe"]:
            entry["action"] = "unsafe_skip"
        elif apply_deletes:
            abs_backup = task_dir / c["backup_path"]
            abs_real = task_dir / c["real_path"]
            entry["timestamp"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            # Log before delete: a report entry must exist even if the delete below throws.
            entry["action"] = "delete_attempted"
            try:
                pre_real_size = abs_real.stat().st_size
                entry["sha256"] = sha256_of(abs_backup)

                quarantine_path = quarantine_root / task_dir.name / abs_backup.name
                quarantine_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(abs_backup, quarantine_path)
                if (
                    not quarantine_path.is_file()
                    or quarantine_path.stat().st_size != c["backup_size"]
                ):
                    entry["action"] = "delete_skipped_quarantine_mismatch"
                    entry["error"] = (
                        "quarantine copy did not land at the source size -- delete "
                        "aborted for this file, nothing removed"
                    )
                    result["candidates"].append(entry)
                    continue
                entry["quarantine_path"] = str(quarantine_path)

                abs_backup.unlink()

                if abs_backup.exists():
                    entry["action"] = "delete_failed"
                    entry["error"] = "unlink() returned but the file still exists"
                elif not abs_real.is_file() or abs_real.stat().st_size != pre_real_size:
                    entry["action"] = "delete_failed_real_file_changed"
                    entry["error"] = (
                        "real (non-backup) counterpart changed or disappeared after "
                        "the backup delete -- should be impossible, only the backup "
                        "was touched; the deleted backup is still in quarantine"
                    )
                else:
                    entry["action"] = "deleted"
            except OSError as e:
                entry["action"] = "delete_failed"
                entry["error"] = str(e)
        else:
            entry["action"] = "would_delete"
        result["candidates"].append(entry)
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(
        description="Remove stray .orig/.bak backup files from a task's solution/files/ "
        "directory, only when the real file they back up is confirmed present and non-empty."
    )
    ap.add_argument(
        "task_ids",
        nargs="*",
        help="one or more task ids (directory names under --root)",
    )
    ap.add_argument(
        "--all", action="store_true", help="run every task dir found under --root"
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=None,
        help="root directory containing one subdirectory per task (REQUIRED)",
    )
    ap.add_argument(
        "--id-prefix",
        default="SVC-PC-",
        help="when using --all, only treat subdirectories starting with this prefix as tasks",
    )
    ap.add_argument("--out", type=Path, default=None, help="write the JSON report here")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="actually delete safe candidates (default: report only, nothing is deleted)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="explicit alias for the default report-only mode; overrides --apply if both given",
    )
    ap.add_argument(
        "--quarantine-dir",
        type=Path,
        default=DEFAULT_QUARANTINE,
        help="every deleted file is byte-copied here first and size-verified before the "
        "original is removed, so an --apply run stays fully undoable (default: "
        f"{DEFAULT_QUARANTINE})",
    )
    args = ap.parse_args()

    if args.root is None:
        ap.error(
            "--root is required (point it at the directory containing your task folders)"
        )
    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")

    apply_deletes = args.apply and not args.dry_run

    task_dirs = find_task_dirs(
        args.root, None if args.all else args.task_ids, id_prefix=args.id_prefix
    )
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        sys.exit(1)

    results = []
    for i, task_dir in enumerate(task_dirs, 1):
        r = process_task(task_dir, apply_deletes, quarantine_root=args.quarantine_dir)
        if r["n_candidates"]:
            print(
                f"[{i}/{len(task_dirs)}] {task_dir.name}: {r['n_candidates']} candidate(s)"
            )
        results.append(r)

    all_candidates = [c for r in results for c in r["candidates"]]
    by_action = {}
    for c in all_candidates:
        by_action.setdefault(c["action"], []).append(
            f"{c['task_id']}:{c['backup_path']}"
        )

    aggregate = {
        "tool": "svc_stray_backup_cleanup",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "mode": "apply" if apply_deletes else "report_only",
        "n_tasks_scanned": len(results),
        "n_tasks_with_candidates": sum(1 for r in results if r["n_candidates"]),
        "n_candidates_total": len(all_candidates),
        "by_action": {k: len(v) for k, v in by_action.items()},
        "results": [r for r in results if r["n_candidates"]],
    }

    print(
        f"\n{len(results)} task(s) scanned, {aggregate['n_tasks_with_candidates']} with "
        f"candidate(s), {len(all_candidates)} candidate file(s) total "
        f"({'apply' if apply_deletes else 'report only'})"
    )
    for action, items in sorted(by_action.items()):
        print(f"  {action}: {len(items)}")
        for item in items[:20]:
            print(f"      {item}")
        if len(items) > 20:
            print(f"      ... and {len(items) - 20} more")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2)
        print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
