#!/usr/bin/env python3
"""oversize_source_scan.py - GATE-V2 (laptop, 2026-09-18 23:20Z), item 3, the
SOURCE half: rewardkit silently replaces any files= entry over 1 MiB with
"[skipped: file too large]" (mirrors stage_and_zip.sh's own exit-9 size check,
verbatim candidate-path list, so this pre-check and the actuator's own gate
never diverge on what "oversized" means). Unlike the solver-deliverable half
(render_guard_apply.py, fully mechanical), a SOURCE workbook needs a human/
model judgment call about which sheet/columns the rubric actually needs
(the 54-2-0 pattern: Sales_Orders.xlsx, 3.5 MB, condensed to
Sales_Orders_judge_extract.xlsx, a few columns, under 400 KB) - this script
only finds the candidates and writes a CR.json-shape findings file
(gather_files_text.py / fix_plan.md's own generic shape) for ONE fix_plan.md
+ apply_plan.py call to resolve via the create_xlsx_extract op.

Flags a files= entry when: its basename resolves to
environment/initial_workspace/<name> (a SOURCE, not solution/files/<name> or
an existing tests/deliverables/judge_inputs/<name> - those are out of scope
here, the render-guard and "already fixed" cases respectively) AND that file
is over 1 MiB AND no judge_inputs/<name>_judge_extract.<ext> already exists
for it (idempotent - a prior round's fix is not re-flagged).

Usage:
    python3 oversize_source_scan.py --task TASK --corpus-root PATH --out FINDINGS.json
Exit 0 always; --out's "findings" list is empty when nothing needs fixing
(mirrors checkfix_build_findings/build_oracle_findings's own convention).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True)
    ap.add_argument("--corpus-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    task_dir = args.corpus_root / args.task
    findings = []
    seen_names = set()

    for jt in glob.glob(str(task_dir / "tests" / "deliverables*" / "judge.toml")):
        text = open(jt, encoding="utf-8", errors="replace").read()
        m = re.search(r'^files\s*=\s*\[(.*?)\]', text, re.M | re.S)
        if not m:
            continue
        for f in re.findall(r'"([^"]+)"', m.group(1)):
            name = os.path.basename(f)
            if name in seen_names:
                continue
            source_cand = task_dir / "environment" / "initial_workspace" / name
            extract_cands = list((task_dir / "tests" / "deliverables" / "judge_inputs").glob(
                Path(name).stem + "_judge_extract.*"
            ))
            if extract_cands:
                continue  # already fixed by a prior round
            if source_cand.is_file() and source_cand.stat().st_size > 1_048_576:
                seen_names.add(name)
                findings.append({
                    "id": "OS%d" % (len(findings) + 1),
                    "class": "oversized_source",
                    "severity": "major",
                    "criterion_ids": [],
                    "affected_files": [
                        os.path.relpath(jt, task_dir),
                        os.path.relpath(source_cand, task_dir),
                    ],
                    "description": (
                        "files= entry %r resolves to %s (%d bytes, over the 1 MiB rewardkit "
                        "silently skips before the judge ever reads it - confirmed real "
                        "failure mode, DataOS batch 4 on this exact task). Create a condensed "
                        "extract under tests/deliverables/judge_inputs/ with only the "
                        "sheet/columns the criteria in %s actually grade (the 54-2-0 pattern: "
                        "Sales_Orders.xlsx -> Sales_Orders_judge_extract.xlsx), under 400 KB, "
                        "and repoint files= at it."
                        % (f, os.path.relpath(source_cand, task_dir), source_cand.stat().st_size,
                           os.path.relpath(jt, task_dir))
                    ),
                    "evidence": "size=%d bytes, cap=1048576 bytes" % source_cand.stat().st_size,
                    "fix_direction": "",
                })

    out = {"task": args.task, "findings": findings, "majors_present": bool(findings)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f"[oversize-source] {args.task}: {len(findings)} oversized source(s) found, wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
