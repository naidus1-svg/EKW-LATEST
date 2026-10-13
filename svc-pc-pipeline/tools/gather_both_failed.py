#!/usr/bin/env python3
"""gather_both_failed.py - GATE-V2 3.1: "a criterion both runs fail goes to
the blind CR agent with the run artifacts." Builds the {{BOTH_FAILED_TEXT}}
section of the step-5 adjudication prompt: every criterion where BOTH GLM
runs failed, each run's own judge reasoning (verdict_text), and each run's
deliverable text (capped).

Usage:
    python3 gather_both_failed.py --task TASK --runs-root /root/qc/runs \
        --out BOTH_FAILED.txt [--per-file-chars 20000]
Exits 1 (no output written) if either run's reward-details.json is missing -
the caller should treat that as "not ready for adjudication yet", not proceed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import extract_document_text  # noqa: E402


def criterion_rows(reward_json: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}

    def walk(group, group_name):
        for c in group.get("criteria", []):
            key = c.get("id") or c.get("name")
            out[key] = {**c, "group": group_name}
        for child in group.get("children", []):
            walk(child, child.get("name", group_name))

    for g in reward_json.get("groups", []):
        walk(g, g.get("name"))
    return out


def deliverable_text(app_dir: Path, cap: int) -> str:
    if not app_dir.is_dir():
        return "[no deliverable directory]"
    parts = []
    used = 0
    for p in sorted(app_dir.rglob("*")):
        if not p.is_file() or p.name == "instruction.md":
            continue
        if used >= cap:
            parts.append(f"\n[remaining files omitted, budget exhausted]")
            break
        try:
            text = extract_document_text(p)
        except Exception as exc:  # noqa: BLE001
            text = f"[extraction error: {exc}]"
        remaining = cap - used
        clipped = text[:remaining]
        used += len(clipped)
        parts.append(f"\n--- {p.relative_to(app_dir)} ---\n{clipped}")
    return "".join(parts) or "[empty deliverable directory]"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", required=True)
    ap.add_argument("--runs-root", type=Path, default=Path("/root/qc/runs"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--per-file-chars", type=int, default=20_000)
    args = ap.parse_args()

    rd1 = args.runs_root / args.task / "glm-1" / "reward-details.json"
    rd2 = args.runs_root / args.task / "glm-2" / "reward-details.json"
    if not rd1.is_file() or not rd2.is_file():
        sys.stderr.write(f"reward-details.json missing for one or both runs ({rd1}, {rd2})\n")
        return 1

    r1 = criterion_rows(json.loads(rd1.read_text()))
    r2 = criterion_rows(json.loads(rd2.read_text()))

    both_failed = [cid for cid in r1 if cid in r2 and not r1[cid].get("passed") and not r2[cid].get("passed")]

    if not both_failed:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("[no criterion failed both runs - nothing to adjudicate]\n")
        print("wrote (empty) - no both-failed criteria")
        return 0

    parts = []
    for cid in sorted(both_failed):
        c1, c2 = r1[cid], r2[cid]
        parts.append(f"\n{'=' * 80}\nCriterion {cid} (group {c1.get('group')}, weight {c1.get('weight')})\n{'=' * 80}")
        parts.append(f"\nrun glm-1 verdict_text: {c1.get('verdict_text')}")
        parts.append(f"\nrun glm-2 verdict_text: {c2.get('verdict_text')}")

    parts.append(f"\n\n{'#' * 80}\nGLM-1 DELIVERABLE\n{'#' * 80}\n")
    parts.append(deliverable_text(args.runs_root / args.task / "glm-1" / "app", args.per_file_chars))
    parts.append(f"\n\n{'#' * 80}\nGLM-2 DELIVERABLE\n{'#' * 80}\n")
    parts.append(deliverable_text(args.runs_root / args.task / "glm-2" / "app", args.per_file_chars))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(parts))
    print(f"wrote {args.out} ({len(both_failed)} both-failed criteria)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
