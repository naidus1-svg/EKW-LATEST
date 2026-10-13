#!/usr/bin/env python3
"""measure_group_chars.py - laptop coordinator, 2026-09-19 17:20Z, job 1: some
judge groups' TOTAL extracted-text char count exceeds the judge model's
context window even though no single files= entry exceeds the 1 MiB byte cap
(judge_emulate.py's own bucket log already reports the group total; this
script breaks that total down PER FILE so the worst text contributors -
often a wide/tall xlsx that converts to a huge markdown table despite being
under 1 MiB - can be identified and shrunk).

Reuses rewardkit's own _build_user_content/_text_from_blocks (same functions
judge_emulate.py and judge_input_report.py use, never reimplemented) and
judge_input_report.py's own build_app_root/resolve_entry for path
resolution, so a file's measured size here matches what the real judge sees
byte-for-byte.

MUST be run with /root/venv/bin/python3 (rewardkit 0.2.0 lives there).

Usage:
    /root/venv/bin/python3 measure_group_chars.py --task TASK [--corpus-root PATH]
Prints, per tests/deliverables*/judge.toml group: the group's total char
count and every files= entry's own contribution, sorted descending.
"""
from __future__ import annotations

import argparse
import glob
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, "/root/venv/lib/python3.13/site-packages")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rewardkit.judges import _build_user_content, _text_from_blocks  # noqa: E402
from judge_input_report import build_app_root, resolve_entry  # noqa: E402

DEFAULT_CORPUS_ROOT = Path("/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True)
    ap.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    ap.add_argument("--scratch", type=Path, default=None)
    args = ap.parse_args()

    task_dir = args.corpus_root / args.task
    scratch = args.scratch or Path(f"/root/qc/checks_scratch/measure_group_chars/{args.task}")
    app_root = build_app_root(task_dir, scratch, "oracle", None)

    for jt in sorted(glob.glob(str(task_dir / "tests" / "deliverables*" / "judge.toml"))):
        jt_path = Path(jt)
        rel = jt_path.relative_to(task_dir)
        text = jt_path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^files\s*=\s*\[(.*?)\]", text, re.M | re.S)
        entries = re.findall(r'"([^"]+)"', m.group(1)) if m else []
        if not entries:
            continue

        per_file = []
        total = 0
        for e in entries:
            resolved = resolve_entry(e, task_dir, app_root)
            blocks = _build_user_content((str(resolved),))
            t = _text_from_blocks(blocks)
            n = len(t)
            per_file.append((n, e, resolved.is_file()))
            total += n

        print(f"\n=== {rel} === total {total:,} chars")
        for n, e, exists in sorted(per_file, reverse=True):
            flag = "" if exists else "  [NOT FOUND]"
            print(f"  {n:>10,}  {e}{flag}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
