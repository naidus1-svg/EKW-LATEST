#!/usr/bin/env python3
"""Validate nop_floor_check.py against DataOS's own NOP evals.

Reads every *-with-runs.zip in a DataOS return directory. For each task revision that has a NOP eval
(evaluations/<id>__attempt_N__nop/), it runs nop_floor_check.estimate() on that revision's task_files/tests/ and sets
the result beside the NOP reward DataOS recorded (verifier/reward.json). Label: a revision is a WEAK_GRADER failure
when its NOP reward is above the threshold, which is the condition DataOS files the major on.

Prints one row per revision, the confusion matrix at the threshold, and per-criterion agreement (of the criteria the
check calls exposed, how many the NOP judge actually passed; of the ones it calls safe, how many it passed anyway).
It also lists any judge group whose files= path exists in environment/initial_workspace, because an empty submission
leaves that file in /app for the judge to read and the static check cannot see what it says.

Usage:
  python nop_floor_validate.py [--src DIR] [--threshold 0.20] [--zips GLOB] [--criteria]
"""

import argparse, glob, json, os, re, sys, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nop_floor_check as nfc  # noqa: E402

DEFAULT_SRC = os.path.expanduser("~/.config/opencode/data-platform-output")


def revisions(zp):
    z = zipfile.ZipFile(zp)
    names = z.namelist()
    revs = sorted(
        {m.group(1) for n in names if (m := re.match(r"([^/]+/rev_[^/]+)/", n))}
    )
    for rev in revs:
        nops = sorted(
            {
                m.group(1)
                for n in names
                if (m := re.match(re.escape(rev) + r"/evaluations/([^/]*__nop)/", n))
            }
        )
        if not nops:
            continue
        tests = rev + "/task_files/"
        files = {
            n[len(tests) :]: z.read(n).decode("utf-8")
            for n in names
            if re.fullmatch(
                re.escape(tests) + r"tests/(reward\.toml|[^/]+/judge\.toml)", n
            )
        }
        ws = {
            n[len(tests) + len("environment/initial_workspace/") :]
            for n in names
            if n.startswith(tests + "environment/initial_workspace/")
            and not n.endswith("/")
        }
        for nop in nops:
            vd = f"{rev}/evaluations/{nop}/eval_files/verifier/"
            try:
                reward = json.loads(z.read(vd + "reward.json"))
            except KeyError:
                continue
            try:
                details = json.loads(z.read(vd + "reward-details.json"))
            except KeyError:
                details = {}
            yield dict(
                zip=os.path.basename(zp),
                task=rev.split("/")[0],
                rev=rev.split("/")[1],
                files=files,
                workspace=ws,
                nop_reward=reward.get("reward") or 0.0,
                details=details,
            )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--zips", default="*-with-runs.zip")
    ap.add_argument("--threshold", type=float, default=nfc.THRESHOLD)
    ap.add_argument(
        "--criteria", action="store_true", help="print per-criterion disagreements"
    )
    a = ap.parse_args(argv)
    rows, crit = [], {
        "exp_pass": 0,
        "exp_fail": 0,
        "safe_pass": 0,
        "safe_fail": 0,
        "gated_pass": 0,
        "gated_fail": 0,
    }
    disagree = []
    for zp in sorted(glob.glob(os.path.join(a.src, a.zips))):
        for r in revisions(zp):
            try:
                rep = nfc.estimate(r["files"])
            except Exception as e:  # report, never drop silently
                print(f"SKIP {r['zip']} {r['task']} {r['rev']}: {e}")
                continue
            ws_groups = [
                g["group"]
                for g in rep["groups"]
                if any(f.split("/app/", 1)[-1] in r["workspace"] for f in g["files"])
            ]
            for g in rep["groups"]:
                verdicts = {
                    c["name"]: c.get("value")
                    for c in r["details"].get(g["group"], {}).get("criteria", [])
                }
                for c in g["criteria"]:
                    v = verdicts.get(c["name"])
                    if v is None:
                        continue
                    key = (
                        "gated" if c["gated"] else "exp" if c["exposed"] else "safe"
                    ) + ("_pass" if v > 0 else "_fail")
                    crit[key] += 1
                    if (c["exposed"] and not v) or (not c["exposed"] and v):
                        disagree.append(
                            (
                                r["task"],
                                r["zip"],
                                g["group"],
                                c["name"],
                                c["weight"],
                                c["exposed"],
                                v,
                            )
                        )
            rows.append(
                dict(
                    task=r["task"],
                    zip=r["zip"].replace("-with-runs.zip", ""),
                    rev=r["rev"],
                    nop=r["nop_reward"],
                    est=rep["estimate"],
                    n=rep["n_criteria"],
                    exposed=rep["n_exposed"],
                    gated=rep["n_gated"],
                    ws_groups=ws_groups,
                )
            )
    t = a.threshold
    print(
        f"{'NOP':>6} {'EST':>6}  {'task':16} {'return zip':20} {'crit':>4} {'exp':>4} {'gate':>4}  label/flag"
    )
    for r in sorted(rows, key=lambda r: -r["est"]):
        lab = "FAIL" if r["nop"] > t else "pass"
        flag = "FLAG" if r["est"] > t else "ok"
        mark = {
            ("FAIL", "FLAG"): "TP",
            ("pass", "ok"): "TN",
            ("pass", "FLAG"): "FP",
            ("FAIL", "ok"): "FN",
        }[(lab, flag)]
        ws = (
            f"  workspace-read groups: {','.join(r['ws_groups'])}"
            if r["ws_groups"]
            else ""
        )
        print(
            f"{r['nop']:6.3f} {r['est']:6.3f}  {r['task']:16} {r['zip']:20} {r['n']:4} {r['exposed']:4} "
            f"{r['gated']:4}  {lab}/{flag} {mark}{ws}"
        )
    tp = sum(r["nop"] > t and r["est"] > t for r in rows)
    fp = sum(r["nop"] <= t and r["est"] > t for r in rows)
    fn = sum(r["nop"] > t and r["est"] <= t for r in rows)
    tn = len(rows) - tp - fp - fn
    print(
        f"\nrevisions with a NOP eval: {len(rows)} (from {len(set(r['zip'] for r in rows))} return zips); "
        f"NOP reward above {t:.2f}: {tp + fn}"
    )
    print(
        f"threshold {t:.2f}: TP={tp} FP={fp} FN={fn} TN={tn}  precision={tp / (tp + fp) if tp + fp else 0:.2f} "
        f"recall={tp / (tp + fn) if tp + fn else 0:.2f}"
    )
    print(
        f"criteria with a NOP verdict: exposed {crit['exp_pass']} passed / {crit['exp_fail']} failed; "
        f"safe {crit['safe_pass']} passed / {crit['safe_fail']} failed; "
        f"gated {crit['gated_pass']} passed / {crit['gated_fail']} failed"
    )
    if a.criteria:
        for d in disagree:
            print("  disagree", *d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
