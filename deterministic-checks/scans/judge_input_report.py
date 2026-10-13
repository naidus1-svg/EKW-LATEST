#!/usr/bin/env python3
"""judge_input_report.py - GATE-V2 (verifier spec, FOR-PIPE2.md item 1,
2026-09-19): the ONE deterministic check that finds what no amount of reading
can. DataOS's 67-1-0/8-2-0 majors are both harbor-rewardkit's own
`_MAX_FILE_SIZE = 1 MiB` silent skip - nothing our local text extraction
produces contains that evidence string, because we never built the real /app
content root and ran it through rewardkit's own function. This script does
exactly that: no model call, seconds per task.

Requires the `rewardkit` package (0.2.0 on the pipeline this was ported from)
importable in whatever interpreter runs this script. If it lives in a
separate venv's site-packages, point QC_REWARDKIT_SITE_PACKAGES at that
directory (sandbox example: /root/venv/lib/python3.13/site-packages, run
with /root/venv/bin/python3) -- otherwise a normal `pip install rewardkit`
into the interpreter you invoke this with is enough. Without it importable
either way, this script prints a clear error on stderr and exits 2; it never
guesses at the marker.

Content root: environment/initial_workspace/* copied into a scratch /app,
then overlaid with solution/files/* (--mode oracle, the default) or an
arbitrary deliverable directory (--mode deliverable --deliverable-dir DIR) -
this mirrors what the Dockerfile actually does (COPY initial_workspace/ /app/)
plus solve.sh's own `cp -a /solution/files/. /app/` (oracle) or a real
solver's write into /app (deliverable), which judge_emulate.py's own
`content_root = task_dir / "solution" / "files"` never did - that stand-in
directory has ONLY the deliverable, so every environment SOURCE file named in
files= resolved to "[not found]" regardless of its real size, silently
hiding the real "[skipped: file too large]" marker DataOS's own grader
actually produces.

Every `files=` entry (group-level `[judge]` files, and any per-criterion
`[[criterion]]` files override) is resolved against that root and handed,
ONE ENTRY AT A TIME, to rewardkit's own `_build_user_content` (never
reimplemented) so the marker is byte-identical to what the real judge call
would see: "ok" | "not_found" | "skipped_too_large" | "no_block" (a binary
file that isn't image/document-typed and fails UTF-8 decode - _read_file_blocks
returns an empty list for it, same as a real judge call would get: nothing).

Gate rule (03-acceptance-test.md, non-negotiable): "not_found" or
"skipped_too_large" on ANY files= entry is a blocking major - never a warn.

Usage:
    python3 judge_input_report.py --task TASK \
        [--corpus-root PATH] [--mode oracle|deliverable] [--deliverable-dir DIR] \
        --out probes/judge_input.json
(sandbox example: /root/venv/bin/python3 judge_input_report.py ...)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tomllib
from pathlib import Path

_rewardkit_site_packages = os.environ.get("QC_REWARDKIT_SITE_PACKAGES")
if _rewardkit_site_packages:
    sys.path.insert(0, _rewardkit_site_packages)
try:
    from rewardkit.judges import _build_user_content, _text_from_blocks  # noqa: E402
except ImportError as exc:  # noqa: BLE001
    sys.stderr.write(
        "ERROR: could not import rewardkit.judges - install rewardkit into this "
        "interpreter, or point QC_REWARDKIT_SITE_PACKAGES at a site-packages dir "
        "that has it (sandbox example: /root/venv/lib/python3.13/site-packages, "
        f"run with /root/venv/bin/python3) ({exc})\n"
    )
    raise SystemExit(2)

DEFAULT_CORPUS_ROOT = Path(os.environ.get("QC_CORPUS_ROOT", "."))


def build_app_root(
    task_dir: Path, scratch: Path, mode: str, deliverable_dir: Path | None
) -> Path:
    """Builds a scratch /app exactly as the real container does: the whole
    environment/initial_workspace/ tree, then the graded deliverable(s)
    overlaid on top (oracle: solution/files/*; deliverable: the given dir's
    contents) - matching the Dockerfile's COPY + solve.sh's/the solver's own
    write into /app, never just the deliverable alone."""
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)

    env_src = task_dir / "environment" / "initial_workspace"
    if env_src.is_dir():
        shutil.copytree(env_src, scratch, dirs_exist_ok=True)

    if mode == "oracle":
        overlay = task_dir / "solution" / "files"
    else:
        if deliverable_dir is None:
            raise SystemExit("--deliverable-dir is required with --mode deliverable")
        overlay = deliverable_dir
    if overlay.is_dir():
        shutil.copytree(overlay, scratch, dirs_exist_ok=True)

    return scratch


def resolve_entry(entry: str, task_dir: Path, app_root: Path) -> Path:
    if entry.startswith("/app/"):
        return app_root / entry[len("/app/") :]
    if entry.startswith("/tests/"):
        return task_dir / entry[1:]
    if entry.startswith("/"):
        return task_dir / entry.lstrip("/")
    return task_dir / entry


def classify(entry: str, resolved: Path) -> dict:
    blocks = _build_user_content((str(resolved),))
    text = _text_from_blocks(blocks)
    exists = resolved.is_file()
    size = resolved.stat().st_size if exists else None

    if not blocks:
        marker = "no_block" if exists else "not_found"
        # _build_user_content itself emits a "[not found]" text block for a
        # missing path (never an empty list) - an empty list here means the
        # path exists but _read_file_blocks silently dropped it (binary,
        # non-document, UnicodeDecodeError).
    elif any(
        "[not found]" in b.get("text", "") for b in blocks if b.get("type") == "text"
    ):
        marker = "not_found"
    elif any(
        "[skipped: file too large]" in b.get("text", "")
        for b in blocks
        if b.get("type") == "text"
    ):
        marker = "skipped_too_large"
    else:
        marker = "ok"

    return {
        "entry": entry,
        "resolved_path": str(resolved),
        "exists": exists,
        "size_bytes": size,
        "marker": marker,
        "char_count": len(text),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--task", required=True)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    ap.add_argument("--mode", choices=["oracle", "deliverable"], default="oracle")
    ap.add_argument("--deliverable-dir", type=Path, default=None)
    ap.add_argument(
        "--scratch-root",
        type=Path,
        default=Path(os.environ.get("QC_SCRATCH_ROOT", "reports/judge_input_app")),
        help="scratch /app build directory (env QC_SCRATCH_ROOT; sandbox example "
        "/root/qc/checks_scratch/judge_input_app)",
    )
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    task_dir = args.corpus_root / args.task
    if not task_dir.is_dir():
        sys.stderr.write(f"ERROR: task directory not found: {task_dir}\n")
        return 2

    scratch = args.scratch_root / args.task
    app_root = build_app_root(task_dir, scratch, args.mode, args.deliverable_dir)

    groups = []
    blocking_major = False
    for jt in sorted(task_dir.glob("tests/deliverables*/judge.toml")):
        doc = tomllib.loads(jt.read_text())
        group_name = jt.parent.name
        group_files = doc.get("judge", {}).get("files", []) or []

        group_report = {
            "group": group_name,
            "judge_toml": str(jt.relative_to(task_dir)),
            "group_files": [],
            "criteria_with_own_files": [],
        }
        for entry in group_files:
            resolved = resolve_entry(entry, task_dir, app_root)
            row = classify(entry, resolved)
            group_report["group_files"].append(row)
            if row["marker"] in ("not_found", "skipped_too_large"):
                blocking_major = True
        # group_total_chars: ONE combined _build_user_content call over the
        # whole group's file list, matching how rewardkit.runner actually
        # calls it (judges.py:370, `_build_user_content(files)` - the whole
        # tuple at once, not per-entry) - the per-entry classify() calls
        # above are for an unambiguous marker/size per file, and undercount
        # the real char total slightly (no inter-block "\n\n" joins between
        # entries when each is fetched alone).
        resolved_paths = [
            str(resolve_entry(e, task_dir, app_root)) for e in group_files
        ]
        group_report["group_total_chars"] = len(
            _text_from_blocks(_build_user_content(tuple(resolved_paths)))
        )

        for crit in doc.get("criterion", []):
            crit_files = crit.get("files")
            if not crit_files:
                continue
            rows = []
            for entry in crit_files:
                resolved = resolve_entry(entry, task_dir, app_root)
                row = classify(entry, resolved)
                rows.append(row)
                if row["marker"] in ("not_found", "skipped_too_large"):
                    blocking_major = True
            group_report["criteria_with_own_files"].append(
                {"criterion": crit.get("name"), "files": rows}
            )

        groups.append(group_report)

    out = {
        "task": args.task,
        "mode": args.mode,
        "app_root": str(app_root),
        "blocking_major": blocking_major,
        "groups": groups,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    n_bad = sum(
        1
        for g in groups
        for row in g["group_files"]
        + [r for c in g["criteria_with_own_files"] for r in c["files"]]
        if row["marker"] in ("not_found", "skipped_too_large")
    )
    print(
        f"[judge-input] {args.task} ({args.mode}): {n_bad} blocking entries, wrote {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
