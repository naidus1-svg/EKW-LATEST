#!/usr/bin/env python3
"""gate_verdict_cold.py [--apply-construct FILE.json]

Cold-revalidation confusion-matrix builder. For each of the 10 batch-10 tasks, reads all
4 review runs (opus x2, sonnet x2) from /root/qc/_prompts/gate-revalidate/reviews/, runs
judge_schema_bytes.py fresh against the graded/ taskdir (never cached, never trusted from
a prior run), and prints two confusion matrices against DataOS's own batch-10 verdict:

  - "any major in any run": BLOCK if schema blocks OR any of the 4 runs has major_count>=1
  - "2-of-4 voting":        BLOCK if schema blocks OR any single check id is major in
                            at least 2 of the 4 runs (kills single-call variance)

With no arguments, also writes majors-for-classification.json: every major-severity check
across all (up to) 40 runs, with its full justification text, for a human/agent to
classify CONSTRUCTED (names the specific passing-yet-wrong input/output) vs ARGUED (states
the possibility without constructing it) - the construct-the-exploit rule this task tests
separately.

With --apply-construct FILE.json, FILE.json must map "TASK|REVIEWER|runN|CHECK_ID" -> true
(constructed, counts) or false/absent (argued only, dropped) and both matrices are
recomputed with only constructed majors counted.

Never edits gate_verdict.py or any pre-existing tool; never trusts a cached schema result.
"""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path("/root/qc/_prompts/gate-revalidate")
GRADED = HERE / "graded"
REVIEWS_DIR = HERE / "reviews"
BLOCK = 4000
WARN = 3500

TASKS = [
    "SVC-PC-11-4-0",
    "SVC-PC-12-6-0",
    "SVC-PC-73-2-0",
    "SVC-PC-17-2-0",
    "SVC-PC-17-7-0",
    "SVC-PC-2-6-0",
    "SVC-PC-21-3-0",
    "SVC-PC-67-3-0",
    "SVC-PC-9-5-0",
    "SVC-PC-38-1-0",
]
DATAOS = {
    "SVC-PC-11-4-0": "ACCEPT",
    "SVC-PC-12-6-0": "ACCEPT",
    "SVC-PC-73-2-0": "ACCEPT",
    "SVC-PC-17-2-0": "REJECT",
    "SVC-PC-17-7-0": "REJECT",
    "SVC-PC-2-6-0": "REJECT",
    "SVC-PC-21-3-0": "REJECT",
    "SVC-PC-67-3-0": "REJECT",
    "SVC-PC-9-5-0": "REJECT",
    "SVC-PC-38-1-0": "REJECT",
}
RUNS = [("opus", 1), ("opus", 2), ("sonnet", 1), ("sonnet", 2)]


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
    return proc.returncode, worst_groups


def load_run(task, reviewer, run):
    p = REVIEWS_DIR / f"{task}.{reviewer}.run{run}.json"
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"error": f"unparseable: {e}"}
    checks = d.get("checks", [])
    majors = [c for c in checks if c.get("severity") == "major"]
    return {
        "overall_verdict": d.get("overall_verdict"),
        "major_count": d.get("major_count"),
        "major_checks": [c.get("id") for c in majors],
        "major_detail": majors,
    }


def main():
    apply_construct = None
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--apply-construct":
        apply_construct = json.loads(Path(args[1]).read_text(encoding="utf-8"))

    all_majors_dump = []
    per_task = {}
    for t in TASKS:
        taskdir = str(GRADED / t)
        exit_code, blocked_groups = schema_check(taskdir)
        schema_blocks = exit_code >= 2

        runs = {}
        missing = []
        for reviewer, run in RUNS:
            r = load_run(t, reviewer, run)
            key = f"{reviewer}.run{run}"
            runs[key] = r
            if r is None:
                missing.append(key)
                continue
            if "error" in r:
                continue
            for c in r["major_detail"]:
                all_majors_dump.append(
                    {
                        "task": t,
                        "reviewer": reviewer,
                        "run": run,
                        "vote_key": f"{t}|{reviewer}|run{run}|{c.get('id')}",
                        "check_id": c.get("id"),
                        "name": c.get("name"),
                        "justification": c.get("justification"),
                        "suggested_fix": c.get("suggested_fix"),
                    }
                )

        vote_counts = {}
        any_run_major = False
        for reviewer, run in RUNS:
            key = f"{reviewer}.run{run}"
            r = runs.get(key)
            if not r or "error" in r:
                continue
            for c in r["major_detail"]:
                cid = c.get("id")
                if apply_construct is not None:
                    vote_key = f"{t}|{reviewer}|run{run}|{cid}"
                    if not apply_construct.get(vote_key, False):
                        continue
                vote_counts[cid] = vote_counts.get(cid, 0) + 1
                any_run_major = True

        voted_majors = sorted([cid for cid, n in vote_counts.items() if n >= 2])

        verdict_any = "BLOCK" if (schema_blocks or any_run_major) else "PASS"
        verdict_vote = "BLOCK" if (schema_blocks or voted_majors) else "PASS"

        def summarize(r):
            if r is None:
                return None
            if "error" in r:
                return {"error": r["error"]}
            return {
                "overall_verdict": r["overall_verdict"],
                "major_count": r["major_count"],
                "major_checks": r["major_checks"],
            }

        per_task[t] = {
            "dataos": DATAOS[t],
            "schema_blocks": schema_blocks,
            "schema_blocked_groups": blocked_groups,
            "runs": {k: summarize(v) for k, v in runs.items()},
            "missing": missing,
            "vote_counts": vote_counts,
            "voted_majors": voted_majors,
            "verdict_any": verdict_any,
            "verdict_vote": verdict_vote,
        }

    def confusion(rule_key):
        tp = fn = tn = fp = 0
        for t in TASKS:
            d = per_task[t]["dataos"]
            g = per_task[t][rule_key]
            if d == "REJECT":
                if g == "BLOCK":
                    tp += 1
                else:
                    fn += 1
            else:
                if g == "PASS":
                    tn += 1
                else:
                    fp += 1
        return tp, fn, tn, fp

    print("=== PER-TASK ===")
    for t in TASKS:
        p = per_task[t]
        print(
            f"{t}: dataos={p['dataos']} schema_blocks={p['schema_blocks']} "
            f"verdict_any={p['verdict_any']} verdict_vote={p['verdict_vote']} "
            f"vote_counts={p['vote_counts']} missing={p['missing']}"
        )

    for label, key in (
        ("ANY MAJOR IN ANY RUN", "verdict_any"),
        ("2-of-4 VOTING", "verdict_vote"),
    ):
        tp, fn, tn, fp = confusion(key)
        print(f"\n=== CONFUSION MATRIX ({label}) ===")
        print(
            f"DataOS REJECT (7): gate BLOCKED {tp}, gate missed {fn} -> recall = {tp}/7"
        )
        print(
            f"DataOS ACCEPT (3): gate PASSED {tn}, gate falsely blocked {fp} -> specificity = {tn}/3"
        )

    out_suffix = "-construct" if apply_construct is not None else ""
    Path(HERE / f"verdict-detail{out_suffix}.json").write_text(
        json.dumps(per_task, indent=2), encoding="utf-8", newline="\n"
    )
    if apply_construct is None:
        Path(HERE / "majors-for-classification.json").write_text(
            json.dumps(all_majors_dump, indent=2), encoding="utf-8", newline="\n"
        )
        print(
            f"\nWrote {len(all_majors_dump)} major findings to majors-for-classification.json "
            f"for construct-vs-argue review."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
