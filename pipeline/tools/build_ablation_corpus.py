#!/usr/bin/env python3
"""Assemble the labeled + full-trajectory ablation corpus.

The v18 calibration goldens (pipeline/specs/calibration/v18/task_<id>/) carry an
expert `expected_verdict.txt` but their evals were slimmed to `verifier/` only —
trajectories were dropped. A separate k=10 / 6-model eval drop
(ekwbench_k10_6model_evals/) has the FULL trajectories + verifier + deliverables
for the SAME five tasks, but in a different on-disk layout and without labels.

This tool joins the two: it copies the (small) QC'd artifact + expert label from
the calibration set and OVERLAYS the full evals from the drop, normalised into
the `<task_dir>/evals/<model>/trial_*/` layout the QC loader expects. The heavy
eval trees are symlinked (not copied) so the 4 GB drop stays in place.

Result: a corpus where every task has BOTH an expert verdict and live model
trajectories — the substrate for a true labeled ablation of the trajectory dims.

Drop layout   : <drop>/ekwbench-task_<id>/v1/execution_1/<model>/trial_*/...
Calib layout  : <calib>/task_<id>/{task.toml,instruction.md,environment,solution,tests,expected_verdict.txt}
Output layout : <out>/task_<id>/{...artifact...}/evals/<model> -> (symlink) drop model dir
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

DEFAULT_TASKS = ["24", "48", "53", "111", "116"]
# Files/dirs copied verbatim from the calibration artifact.
_ARTIFACT_ITEMS = [
    "task.toml",
    "instruction.md",
    "environment",
    "solution",
    "tests",
    "expected_verdict.txt",
]


def build_task(task_id: str, drop: Path, calib: Path, out: Path,
               *, force: bool) -> tuple[bool, str]:
    """Assemble one task dir. Returns (ok, message)."""
    src_artifact = calib / f"task_{task_id}"
    src_evals = drop / f"ekwbench-task_{task_id}" / "v1" / "execution_1"
    dest = out / f"task_{task_id}"

    if not src_artifact.is_dir():
        return False, f"calibration artifact missing: {src_artifact}"
    if not src_evals.is_dir():
        return False, f"drop evals missing: {src_evals}"

    if dest.exists():
        if not force:
            return False, f"dest exists (use --force): {dest}"
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    # 1. Copy the QC'd artifact + the expert label.
    copied = []
    for item in _ARTIFACT_ITEMS:
        s = src_artifact / item
        if not s.exists():
            continue
        d = dest / item
        if s.is_dir():
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)
        copied.append(item)
    if "expected_verdict.txt" not in copied:
        return False, f"no expected_verdict.txt in {src_artifact}"

    # 2. Symlink each model's full eval tree into evals/<model>.
    evals_dir = dest / "evals"
    evals_dir.mkdir()
    models = sorted(p for p in src_evals.iterdir() if p.is_dir())
    n_models = 0
    n_trials = 0
    for m in models:
        link = evals_dir / m.name
        link.symlink_to(m.resolve())
        n_models += 1
        n_trials += sum(1 for t in m.iterdir()
                        if t.is_dir() and t.name.startswith("trial_"))

    verdict = (dest / "expected_verdict.txt").read_text(encoding="utf-8").strip()
    return True, (f"task_{task_id}: verdict={verdict}  "
                  f"models={n_models}  trials={n_trials}  artifact={copied}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drop", type=Path,
                    default=Path("~/Downloads/ekwbench_k10_6model_evals").expanduser(),
                    help="root of the k=10/6-model eval drop")
    ap.add_argument("--calib", type=Path,
                    default=Path(__file__).resolve().parents[1] / "specs" / "calibration" / "v18",
                    help="root of the v18 calibration goldens")
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parents[2] / "runs" / "ablation_corpus",
                    help="output corpus root")
    ap.add_argument("--tasks", default=",".join(DEFAULT_TASKS),
                    help="comma-separated task ids (default: the 5 labeled goldens)")
    ap.add_argument("--force", action="store_true", help="overwrite existing task dirs")
    args = ap.parse_args()

    drop = args.drop.expanduser().resolve()
    calib = args.calib.expanduser().resolve()
    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()]

    print(f"drop  : {drop}")
    print(f"calib : {calib}")
    print(f"out   : {out}\n")

    ok_count = 0
    for tid in task_ids:
        ok, msg = build_task(tid, drop, calib, out, force=args.force)
        print(("  OK  " if ok else " FAIL ") + msg)
        ok_count += int(ok)

    print(f"\n{ok_count}/{len(task_ids)} tasks assembled → {out}")
    return 0 if ok_count == len(task_ids) else 1


if __name__ == "__main__":
    raise SystemExit(main())
