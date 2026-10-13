#!/usr/bin/env python3
"""EKW deterministic gate for one task: run EKW's own check registry and give one verdict.

Runs deterministic-checks/ekw/ekw_run_checks.py (Check B + every shared check) over the native harbor
tree ekw_intake.py assembled at $EKW_ROOT/_harbor/task_<TASK>/, then sorts every non-pass verdict:

  BLOCKING  a `fail` from any check not listed below. The fix loop must clear it (or, in decide mode,
            waive it with evidence, see WAIVERS).
  HARNESS   checks about the native harbor runtime (tests/test.sh + verifier_runtime.py + verifier.json
            judge config) that the DataOS package does NOT ship: ekw_raw_to_rewardkit.py replaces the
            runtime with rewardkit's test.sh, reward.toml and a Sonnet judge. Measured on LGL-131
            2026-09-25: verifier_executability and source_truncation fail only because the check's staged
            copy drops verifier_runtime.py / verifier_lib, weight_application because the stage has no
            reward.toml, judge_determinism_config_lint on verifier.json's temperature. Logged, never block.
  ADVISORY  `warn`, and `fail` from a check named in $EKW_WORK/advisory_checks.txt (one check per line,
            owner-editable). Handed to the adversarial verify as evidence; never block on their own.
  ERROR     a check produced no verdict (tool problem). Logged; blocks only if check_b itself errors.

WAIVERS: $EKW_WORK/waivers/<TASK>.json = {"<check>": "<evidence the finding is false on this task>"}.
A waived blocking check becomes ADVISORY. Only decide mode writes waivers; each needs a source citation.

Precision of the blocking set on these tasks is NOT measured (no EKW task has been through this gate and
then DataOS). Treat it as provisional; move a check to advisory_checks.txt once it proves noisy.

Usage: ekw_gate.py <TASK> [--out <json>] [--jobs N]
Exit 0 PASS, 1 FAIL (blocking findings), 2 tool error (no summary produced).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("EKW_ROOT", "/root/ekwqc/pipeline/data/ekw_qc"))
WORK = Path(os.environ.get("EKW_WORK", "/root/qc/_ekw"))
CHECKS = Path(
    os.environ.get(
        "EKW_CHECKS", "/root/ekwqc/deterministic-checks/ekw/ekw_run_checks.py"
    )
)
PY = os.environ.get("EKW_PY", sys.executable)
HARNESS = {
    "verifier_executability",
    "source_truncation",
    "weight_application",
    "judge_determinism_config_lint",
    "harness_fragility",
    "dependency_pin",
    "task_metadata_completeness",
}
META = {"task_id", "genre", "B", "C", "D", "E"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("--out")
    ap.add_argument("--jobs", type=int, default=2)
    a = ap.parse_args()
    t = a.task
    hid = f"task_{t}"
    odir, stage = WORK / "gate" / t, WORK / "gate" / f"{t}.stage"
    for d in (odir, stage):
        if d.exists():
            shutil.rmtree(d)
    odir.mkdir(parents=True)
    res = {
        "task": t,
        "verdict": "ERROR",
        "blocking": [],
        "advisory": [],
        "harness": [],
        "errors": [],
        "waived": [],
        "checks_dir": str(odir),
    }
    if not (ROOT / "_harbor" / hid).is_dir():
        res["errors"].append(
            f"no harbor tree at {ROOT / '_harbor' / hid}; run ekw_intake.py build {t}"
        )
        return finish(res, a.out, 2)
    p = subprocess.run(
        [
            PY,
            str(CHECKS),
            hid,
            "--root",
            str(ROOT / "_harbor"),
            "--stage",
            str(stage),
            "--out-dir",
            str(odir),
            "--jobs",
            str(a.jobs),
        ],
        capture_output=True,
        text=True,
        timeout=7200,
        cwd=str(CHECKS.parent),
    )
    (odir / "run.log").write_text(p.stdout + p.stderr)
    summ = odir / "summary.csv"
    if not summ.is_file():
        res["errors"].append(
            "ekw_run_checks.py wrote no summary.csv: " + (p.stderr or p.stdout)[-800:]
        )
        return finish(res, a.out, 2)
    rows = [
        r
        for r in csv.DictReader(open(summ, encoding="utf-8"))
        if r.get("task_id") == hid
    ]
    if not rows:
        res["errors"].append("summary.csv has no row for " + hid)
        return finish(res, a.out, 2)
    row = rows[0]
    adv_file = WORK / "advisory_checks.txt"
    advisory = (
        {
            ln.strip()
            for ln in adv_file.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")
        }
        if adv_file.is_file()
        else set()
    )
    wf = WORK / "waivers" / f"{t}.json"
    waivers = json.loads(wf.read_text()) if wf.is_file() else {}
    res["letters"] = {k: row.get(k) for k in ("genre", "B", "C", "D", "E")}
    for k, v in row.items():
        if k in META or k.endswith(("_n", "_first")) or v in ("pass", "skip", "", None):
            continue
        item = {
            "check": k,
            "verdict": v,
            "count": row.get(k + "_n"),
            "first": (row.get(k + "_first") or "")[:600],
            "json": str(odir / f"{k}.json"),
        }
        if k in HARNESS:
            res["harness"].append(item)
        elif v == "error":
            res["errors"].append(item)
        elif v == "fail" and k in waivers:
            item["waiver"] = waivers[k]
            res["waived"].append(item)
        elif v == "fail" and k not in advisory:
            res["blocking"].append(item)
        else:
            res["advisory"].append(item)
    cb_err = any(isinstance(e, dict) and e["check"] == "check_b" for e in res["errors"])
    res["verdict"] = "FAIL" if (res["blocking"] or cb_err) else "PASS"
    return finish(res, a.out, 1 if res["verdict"] == "FAIL" else 0)


def finish(res: dict, out: str | None, rc: int) -> int:
    s = json.dumps(res, indent=1, ensure_ascii=False)
    if out:
        Path(out).write_text(s)
    print(s)
    return rc


if __name__ == "__main__":
    sys.exit(main())
