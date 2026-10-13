"""Move finished DataOS task downloads (<uuid>.tmp zips in Downloads) into qc_review/<batch>/zips as TASK__ID.zip.

Routing is by the DataOS task id inside the zip (TASK/rev_N__ID/), looked up in ids_to_batch.json. A file is finished
when it opens as a valid zip and its size is unchanged across two polls. Files whose id is not in the map are left in
Downloads. Stops when every mapped id is staged or after MAX_MIN minutes.
"""

import glob
import json
import os
import shutil
import sys
import time
import zipfile

BASE = os.environ.get("QC_REVIEW_DIR", os.path.expanduser("~/Documents/qc_review"))
DL = os.path.expanduser("~/Downloads")
MAP = json.load(open(os.path.join(BASE, "ids_to_batch.json")))
MAX_MIN = int(sys.argv[1]) if len(sys.argv) > 1 else 90
for b in set(MAP.values()):
    os.makedirs(os.path.join(BASE, b, "zips"), exist_ok=True)


def staged():
    have = set()
    for b in set(MAP.values()):
        for f in glob.glob(os.path.join(BASE, b, "zips", "*.zip")):
            have.add(os.path.basename(f).rsplit("__", 1)[-1][:-4])
    return have


seen = {}
t0 = time.time()
while time.time() - t0 < MAX_MIN * 60:
    for f in glob.glob(os.path.join(DL, "*.tmp")):
        if os.path.getmtime(f) < t0 - 3600:
            continue
        try:
            s = os.path.getsize(f)
        except OSError:
            continue
        if seen.get(f) != s:
            seen[f] = s
            continue
        try:
            with zipfile.ZipFile(f) as z:
                first = z.namelist()[0].split("/")
            task, tid = first[0], first[1].split("__")[-1]
        except Exception:
            continue
        b = MAP.get(tid)
        if not b:
            continue
        dst = os.path.join(BASE, b, "zips", f"{task}__{tid}.zip")
        try:
            if os.path.exists(dst):
                os.remove(f)
            else:
                shutil.move(f, dst)
            print(
                time.strftime("%H:%M:%S"),
                b,
                "staged",
                os.path.basename(dst),
                s,
                flush=True,
            )
        except OSError as e:
            print("move failed", f, e, flush=True)
    missing = set(MAP) - staged()
    if not missing:
        print("all", len(MAP), "staged", flush=True)
        break
    time.sleep(5)
print("final: missing", sorted(set(MAP) - staged()), flush=True)
