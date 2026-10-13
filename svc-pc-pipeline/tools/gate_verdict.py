#!/usr/bin/env python3
"""gate_verdict.py TASK TASKDIR REVIEWS_DIR [--json]

Composes the gate verdict for ONE task from already-computed evidence:
  - runs judge_schema_bytes.py fresh against TASKDIR (cheap, deterministic, always live -
    never trusts a cached number)
  - reads REVIEWS_DIR/TASK.opus.json and REVIEWS_DIR/TASK.sonnet.json (gate_review.sh's
    canonical output) for major_count

Gate rule (per the gate-backtest task spec): BLOCK if the schema check hits its block
threshold (>=4000 bytes on any judge group) OR if either reviewer's major_count >= 1.
PASS only if all three clear.

Prints one line: "TASK: PASS" or "TASK: BLOCK (reason1; reason2; ...)". With --json, also
prints a machine-readable JSON object on the following line.
"""

import json
import subprocess
import sys
from pathlib import Path

BLOCK = 4000
WARN = 3500


def schema_check(taskdir: str):
    proc = subprocess.run(
        [
            sys.executable,
            "/root/qc/tools/judge_schema_bytes.py",
            taskdir,
            "--block",
            str(BLOCK),
            "--warn",
            str(WARN),
        ],
        capture_output=True,
        text=True,
    )
    worst_groups = []
    for line in proc.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 5 and parts[-1] in ("BLOCK", "warn", "ok"):
            group, crit, sbytes, verdict = parts[-4], parts[-3], parts[-2], parts[-1]
            if verdict == "BLOCK":
                worst_groups.append(f"{group}={sbytes}B/{crit}crit")
    return proc.returncode, worst_groups, proc.stdout.strip()


def load_review(reviews_dir: str, task: str, reviewer: str):
    p = Path(reviews_dir) / f"{task}.{reviewer}.json"
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"error": f"unparseable: {e}"}
    majors = [c["id"] for c in d.get("checks", []) if c.get("severity") == "major"]
    return {
        "overall_verdict": d.get("overall_verdict"),
        "major_count": d.get("major_count"),
        "major_checks": majors,
    }


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    want_json = "--json" in sys.argv[1:]
    if len(args) != 3:
        print(
            "usage: gate_verdict.py TASK TASKDIR REVIEWS_DIR [--json]", file=sys.stderr
        )
        return 2
    task, taskdir, reviews_dir = args

    exit_code, blocked_groups, table = schema_check(taskdir)
    schema_blocks = exit_code >= 2

    opus = load_review(reviews_dir, task, "opus")
    sonnet = load_review(reviews_dir, task, "sonnet")

    reasons = []
    if schema_blocks:
        reasons.append(f"schema-block[{','.join(blocked_groups)}]")
    for name, r in (("opus", opus), (("sonnet"), sonnet)):
        if r is None:
            reasons.append(f"{name}=MISSING")
        elif "error" in r:
            reasons.append(f"{name}=ERROR({r['error']})")
        elif (r.get("major_count") or 0) >= 1:
            reasons.append(f"{name}_major_count={r['major_count']}{r['major_checks']}")

    missing = [n for n, r in (("opus", opus), ("sonnet", sonnet)) if r is None]
    verdict = (
        "BLOCK"
        if (
            schema_blocks
            or any(
                (r or {}).get("major_count", 0) >= 1
                for r in (opus, sonnet)
                if r and "error" not in r
            )
        )
        else "PASS"
    )
    if missing and verdict == "PASS":
        verdict = "INCOMPLETE"

    print(f"{task}: {verdict}" + (f" ({'; '.join(reasons)})" if reasons else ""))
    if want_json:
        print(
            json.dumps(
                {
                    "task": task,
                    "verdict": verdict,
                    "schema_exit_code": exit_code,
                    "schema_blocked_groups": blocked_groups,
                    "schema_table": table,
                    "opus": opus,
                    "sonnet": sonnet,
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
