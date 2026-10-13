"""Recompute each unzipped task's zero-pass tests from the zip's own agent runs and diff them against manifest.json.
A test counts as zero-pass when it scores 0 in every graded (non-oracle) run of the latest revision. Run this before
reviewing: on QC_batch6 the manifest's zero lists (built from the Test Results Matrix) missed 16 tests on SVC-PC-31-4-0
and undercounted several others. Reviewers compute the true share of reward from reward.toml; "share" here is a screen.

Limitation: criteria are keyed by name. A criterion graded several times per run (judge.toml, judge_s2, judge_s3) is
merged correctly, but an EKW task that reuses one name across different verifiers (FIN-410's "consolidation" on v1, v7
and v10) is merged too and under-reports. Check the verifier ids when a task has repeated names.

Usage: python zero_recompute.py --batch b6 [TASK ...]   (default: every task folder under <batch>/work/)
"""

import glob
import json
import os
import sys

args = sys.argv[1:]
if "--batch" not in args:
    sys.exit("usage: zero_recompute.py --batch bN [TASK ...]")
i = args.index("--batch")
BATCH = args[i + 1]
del args[i : i + 2]
BASE = os.environ.get("QC_REVIEW_DIR", os.path.expanduser("~/Documents/qc_review"))
HERE = os.path.join(BASE, BATCH)
man = json.load(open(os.path.join(BASE, "manifest.json"), encoding="utf-8"))
by_task = {}
for v in man.values():
    if isinstance(v, dict) and v.get("batch") == BATCH:
        by_task[v["task"]] = v
        if v.get("dataos_name"):
            by_task[v["dataos_name"]] = v


def crits(d):
    if isinstance(d, dict):
        if "criteria" in d and isinstance(d["criteria"], list):
            for c in d["criteria"]:
                yield c
        for v in d.values():
            if isinstance(v, (dict, list)):
                yield from crits(v)
    elif isinstance(d, list):
        for v in d:
            yield from crits(v)


tasks = args or sorted(
    t for t in os.listdir(os.path.join(HERE, "work")) if t in by_task
)
for t in tasks:
    # The zip's top folder is the DataOS name, which can differ from the sheet name (task_358 -> task_358_dataos_r18).
    revs = sorted(
        glob.glob(os.path.join(HERE, "work", t, t, "rev_*"))
        or glob.glob(os.path.join(HERE, "work", t, "*", "rev_*")),
        key=lambda p: int(p.split("rev_")[1].split("__")[0]),
    )
    if not revs:
        print(f"{t}: not unzipped")
        continue
    runs = [
        p
        for p in glob.glob(
            os.path.join(
                revs[-1],
                "evaluations",
                "*",
                "eval_files",
                "verifier",
                "reward-details.json",
            )
        )
        if "__oracle" not in p
    ]
    # A criterion can be graded several times per run (judge.toml, judge_s2, judge_s3 on FIN-408), so track which
    # runs it appeared in rather than counting entries. A run with no criteria at all is a verifier crash (for
    # example a judge quota error writing reward 0.0); it is reported and left out of the denominator.
    vals, seen, empty = {}, {}, []
    for i, p in enumerate(runs):
        cs = list(crits(json.load(open(p, encoding="utf-8"))))
        if not cs:
            empty.append(p.split(os.sep + "evaluations" + os.sep)[-1].split(os.sep)[0])
        for c in cs:
            vals.setdefault(c["name"], []).append(
                (c.get("value") or 0, c.get("weight"))
            )
            seen.setdefault(c["name"], set()).add(i)
    graded = len(runs) - len(empty)
    zero = sorted(
        n
        for n, v in vals.items()
        if len(seen[n]) == graded and all(x[0] == 0 for x in v)
    )
    if empty:
        print(f"{t}: WARNING runs with no criteria (verifier crash?) {empty}")
    w = sum(vals[n][0][1] or 0 for n in zero)
    # Share of reward: aggregators normalise by the total weight, which is not always 1.0 (SVC-PC-58-10-0 sums to 1.263).
    tot = sum(v[0][1] or 0 for v in vals.values()) or 1.0
    share = w / tot
    listed = set(by_task[t].get("zero", []))
    extra, missing = sorted(set(zero) - listed), sorted(listed - set(zero))
    print(
        f"{t}: runs={len(runs)} zero={len(zero)} weight={w:.4f} share={share:.2%} total_weight={tot:.3f} listed={len(listed)} unlisted={extra} listed_not_zero={missing}"
    )
