#!/usr/bin/env python3
"""Harvest DataOS comprehensive-review findings from every graded round into one repair table.

For each Downloads/*_with_runs*.zip, each task, each comprehensive_review markdown: parse the model's
answer-body JSON (after the '\\nA:' marker; the verdict object has 'overall_verdict' + a 'checks' list -
NOT 'findings'; the '## status' header is job status, ignore it). Emit one row per (task, seat, check).

Output: ekw/dataos-findings.json = {task_id: {verdicts:[...], rounds:[zip...], findings:[{...}]}}.
Buckets: 1.4->over_enforcement, 1.5->missing_coverage, 1.3->ambiguity, 1.1/1.8->deterministic, else other.

Usage: svc_harvest_dataos_findings.py [downloads_dir] [out_json]
"""

import glob
import json
import os
import re
import sys
from collections import defaultdict

REJECT = {"reject", "invalid"}
BUCKET = {
    "1.1": "deterministic",
    "1.3": "ambiguity",
    "1.4": "over_enforcement",
    "1.5": "missing_coverage",
    "1.6": "leakage",
    "1.7": "source_consistency",
    "1.8": "deterministic",
    "1.9": "metadata",
    "1.10": "other",
}


def verdict_obj(txt):
    ans = txt[txt.find("\nA:") + 3 :] if "\nA:" in txt else txt
    best = None
    for m in re.finditer(r"\{", ans):
        s = m.start()
        depth = 0
        for k in range(s, len(ans)):
            c = ans[k]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    b = ans[s : k + 1]
                    if '"overall_verdict"' in b and '"checks"' in b:
                        try:
                            best = json.loads(b)
                        except Exception:
                            pass
                    break
    return best


def seat_of(name):
    return "gpt" if "gpt-5.6-sol" in name else "opus" if "opus-5" in name else "?"


def main():
    dl = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\khiem.doan_turing\Downloads"
    out = (
        sys.argv[2]
        if len(sys.argv) > 2
        else os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "ekw",
            "dataos-findings.json",
        )
    )

    import zipfile

    tasks = defaultdict(lambda: {"verdicts": [], "rounds": set(), "findings": []})
    zips = sorted(glob.glob(os.path.join(dl, "*_with_runs*.zip")))
    for zp in zips:
        zname = os.path.basename(zp)
        try:
            z = zipfile.ZipFile(zp)
        except Exception:
            continue
        for n in z.namelist():
            if "/verifications/comprehensive_review_" not in n or not n.endswith(".md"):
                continue
            task = n.split("/")[0]
            j = verdict_obj(z.read(n).decode("utf-8", "replace"))
            if not j:
                continue
            seat = seat_of(n)
            ov = j.get("overall_verdict")
            tasks[task]["verdicts"].append(
                {"round": zname, "seat": seat, "overall_verdict": ov}
            )
            tasks[task]["rounds"].add(zname)
            for c in j.get("checks", []):
                if str(c.get("result")).lower() != "fail":
                    continue
                cid = str(c.get("id"))
                tasks[task]["findings"].append(
                    {
                        "round": zname,
                        "seat": seat,
                        "check_id": cid,
                        "bucket": BUCKET.get(cid, "other"),
                        "name": c.get("name"),
                        "severity": c.get("severity"),
                        "justification": (c.get("justification") or "")[:1200],
                        "suggested_fix": (c.get("suggested_fix") or "")[:1200],
                    }
                )

    result = {}
    for t, d in tasks.items():
        # a task is rejected if any round had >=2 reject-class seats
        by_round = defaultdict(list)
        for v in d["verdicts"]:
            by_round[v["round"]].append(v["overall_verdict"])
        rejected = any(
            sum(1 for x in vs if x in REJECT) >= 2 for vs in by_round.values()
        )
        result[t] = {
            "rejected": rejected,
            "rounds": sorted(d["rounds"]),
            "verdicts": d["verdicts"],
            "findings": d["findings"],
        }

    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)

    # summary
    ntask = len(result)
    nrej = sum(1 for d in result.values() if d["rejected"])
    bc = defaultdict(int)
    for d in result.values():
        if d["rejected"]:
            for fnd in d["findings"]:
                if fnd["severity"] and str(fnd["severity"]).lower() == "major":
                    bc[fnd["bucket"]] += 1
    nfix = sum(
        1
        for d in result.values()
        if d["rejected"] and any(fnd.get("suggested_fix") for fnd in d["findings"])
    )
    print(f"harvested {ntask} graded tasks across {len(zips)} rounds -> {out}")
    print(f"  rejected: {nrej} | with a suggested_fix: {nfix}")
    print(
        f"  MAJOR findings by bucket (rejected tasks): {dict(sorted(bc.items(), key=lambda kv: -kv[1]))}"
    )


if __name__ == "__main__":
    main()
