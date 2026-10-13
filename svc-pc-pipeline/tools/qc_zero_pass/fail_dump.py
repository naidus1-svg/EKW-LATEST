"""Dump every CONFIRMED_MAJOR task with author and confirmed findings, for drafting author messages."""

import glob
import json
import os
from collections import defaultdict

BASE = os.environ.get("QC_REVIEW_DIR", os.path.expanduser("~/Documents/qc_review"))
man = json.load(open(os.path.join(BASE, "manifest.json"), encoding="utf-8"))
by_copy = {v["copy"]: v for v in man.values()}
out = defaultdict(list)
n = 0
batches = sorted((d for d in os.listdir(BASE) if d[:1] == "b" and d[1:].isdigit()), key=lambda d: int(d[1:]))
for b in batches:
    for vv in sorted(glob.glob(os.path.join(BASE, b, "verdicts", "*.verify.json"))):
        ver = json.load(open(vv, encoding="utf-8"))
        if ver.get("overall") != "CONFIRMED_MAJOR":
            continue
        first = json.load(open(vv.replace(".verify.json", ".json"), encoding="utf-8"))
        m = by_copy.get(str(first.get("dataos_id", "")).strip())
        if not m:
            print("NO MANIFEST", vv)
            continue
        n += 1
        conf = [
            f"{x.get('id')}: {x.get('reason')}"
            for x in ver.get("findings", [])
            if x.get("verify_call") == "CONFIRMED"
        ]
        out[m["author"]].append(
            {
                "batch": b,
                "ws": m["ws"],
                "task": m["task"],
                "copy": m["copy"],
                "ratings": ver.get("ratings"),
                "confirmed": conf,
            }
        )
json.dump(
    out,
    open(os.path.join(BASE, "confirmed_fails.json"), "w", encoding="utf-8"),
    ensure_ascii=False,
    indent=1,
)
print("confirmed fails:", n, "authors:", len(out))
for a, ts in sorted(out.items(), key=lambda x: -len(x[1])):
    print(f"{a}: {len(ts)}: " + ", ".join(f"{t['batch']} {t['task']}" for t in ts))
