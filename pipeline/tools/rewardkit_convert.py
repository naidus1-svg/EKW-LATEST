#!/usr/bin/env python3
"""Wrapper around to_rewardkit.py: auto-detects genre (ekw | dermots), picks an
output folder name, runs the conversion, then validates the result against the
constraints that have actually broken uploads before:
  - every [[criterion]] name matches reward-kit's ^[a-zA-Z0-9_-]{1,64}$ and is unique
  - criterion weights sum to ~1.0
  - task.toml/instruction.md/environment/solution/tests all present
  - deliverable files referenced in judge.toml exist under solution/files/

Usage: python3 rewardkit_convert.py <src_task_dir> [out_dir] [--prefix ekw|dermots]
  src_task_dir  an old-format harbor task (instruction.md, task.toml, environment/,
                solution/, tests/verifier.json)
  out_dir       defaults to a sibling "rewardkit/<slug>" next to src_task_dir's parent
  --prefix      defaults to auto-detect: dermots if environment/data has dated
                snapshot folders (YYYY-MM-DD__E##) or task.toml has case_id/snapshot_key;
                else ekw
"""
import os
import re
import sys
import glob
import json
import tomllib
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
CONVERTER = os.path.join(HERE, "to_rewardkit.py")

_SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}__E\d+$")


def detect_prefix(src):
    st_path = os.path.join(src, "task.toml")
    if os.path.isfile(st_path):
        om = tomllib.load(open(st_path, "rb")).get("metadata", {}) or {}
        if om.get("case_id") or om.get("snapshot_key"):
            return "dermots"
    data_dir = os.path.join(src, "environment", "data")
    if os.path.isdir(data_dir):
        for entry in os.listdir(data_dir):
            if _SNAPSHOT_RE.match(entry):
                return "dermots"
    return "ekw"


def default_out(src, prefix):
    st_path = os.path.join(src, "task.toml")
    slug = None
    if os.path.isfile(st_path):
        om = tomllib.load(open(st_path, "rb")).get("metadata", {}) or {}
        task_id = str(om.get("task_id", ""))
        base = task_id.split("__")[-1] if "__" in task_id else task_id
        slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    slug = slug or re.sub(r"[^a-z0-9]+", "-", os.path.basename(os.path.normpath(src)).lower()).strip("-")
    parent = os.path.dirname(os.path.normpath(src))
    return os.path.join(parent, "rewardkit", slug)


def validate(out):
    problems = []
    for p in ("task.toml", "instruction.md", "environment/Dockerfile", "solution/solve.sh",
              "tests/test.sh"):
        if not os.path.exists(os.path.join(out, p)):
            problems.append(f"missing required file: {p}")
    # to_rewardkit.py writes tests/deliverables/judge.toml when the whole rubric fits in one
    # judge file, and tests/deliverables_01..NN/judge.toml when it chunks (max_criteria_per_judge,
    # default 12). Nearly every EKW task chunks (median 20 verifiers), so a validator that only
    # looked for the single-file layout reported "missing required file" on 10 of 11 real tasks
    # on 2026-09-14 while the conversion had in fact succeeded. Read every judge file, and check
    # names/weights across all of them, which is also what reward-kit's weighted_mean sees.
    judge_files = sorted(
        glob.glob(os.path.join(out, "tests", "deliverables", "judge.toml"))
        + glob.glob(os.path.join(out, "tests", "deliverables_*", "judge.toml"))
    )
    if not judge_files:
        problems.append("missing required file: tests/deliverables/judge.toml "
                        "(or tests/deliverables_NN/judge.toml when chunked)")
    names, wsum = [], 0.0
    for jt in judge_files:
        j = tomllib.load(open(jt, "rb"))
        crits = j.get("criterion", [])
        names += [c["name"] for c in crits]
        wsum += sum(float(c.get("weight") or 0) for c in crits)
        for f in j.get("judge", {}).get("files", []):
            rel = f.lstrip("/").split("/", 1)[-1] if f.startswith("/app/") else f
            if not os.path.isfile(os.path.join(out, "solution", "files", os.path.basename(rel))):
                problems.append(f"{os.path.relpath(jt, out)} references {f} but "
                                f"solution/files/{os.path.basename(rel)} is missing")
    if judge_files:
        bad = [n for n in names if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", n)]
        if bad:
            problems.append(f"invalid/oversized criterion name(s): {bad}")
        if len(names) != len(set(names)):
            problems.append("duplicate criterion names")
        wsum = round(wsum, 4)
        if abs(wsum - 1.0) > 0.01:
            problems.append(f"criterion weights sum to {wsum}, expected ~1.0")
    return problems


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--prefix")]
    prefix_arg = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--prefix=")), None)
    if len(args) < 1:
        print(__doc__)
        sys.exit(1)
    src = os.path.normpath(args[0])
    prefix = prefix_arg or detect_prefix(src)
    out = os.path.normpath(args[1]) if len(args) > 1 else default_out(src, prefix)

    print(f"src={src}\nprefix={prefix} (auto-detected)" if not prefix_arg else f"src={src}\nprefix={prefix} (given)")
    print(f"out={out}")
    subprocess.run([sys.executable, CONVERTER, src, out, prefix], check=True)

    problems = validate(out)
    if problems:
        print("\nVALIDATION FAILED:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("\nValidation OK: criterion names ≤64 chars & unique, weights sum to 1.0, all required files present.")


if __name__ == "__main__":
    main()
