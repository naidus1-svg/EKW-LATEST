"""Audit live sheets: every CONFIRMED_MAJOR is marked; no other row carries the internal-review tag."""

import glob
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

BASE = os.environ.get("QC_REVIEW_DIR", os.path.expanduser("~/Documents/qc_review"))
C = "15Z00RATLJt7QcyT_-Rc6Y0jYS9WmcqUpukKp08GwAZ8"
S = "1JmpP38bcOUDmKlkx_2HndB4GdncPgObC4-_vnQFNaw4"
# The "QC batch" column is found by header after the sheet is read; EKW gained an "offboarded" column on
# 2026-09-28 that moved it from R to S, and a hard-coded index silently matched no rows.
BCOL = {}
TRK = {"SVC": "SVC QC Tracker Combined", "EKW": "EKW QC Tracker Combined"}
# Every bN folder under BASE is a batch; bN maps to the DataOS dataset and sheet label QC_batchN.
BATCH = {
    d: "QC_batch" + d[1:]
    for d in sorted(os.listdir(BASE), key=lambda s: int(s[1:]) if s[1:].isdigit() else 0)
    if re.fullmatch(r"b\d+", d) and os.path.isdir(os.path.join(BASE, d))
}
TAG = "Internal zero-pass review (Khiem's team, not TFRL QC)"
tok = subprocess.run(
    ["gcloud.cmd", "auth", "print-access-token"], capture_output=True, text=True
).stdout.strip()


def get(sid, a1):
    r = urllib.request.Request(
        f"https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/"
        + urllib.parse.quote(a1)
    )
    r.add_header("Authorization", "Bearer " + tok)
    return json.loads(urllib.request.urlopen(r).read()).get("values", [])


def key(s):
    s = re.sub(r"\s+", "", s.lower()).replace("svc-pc", "svc").replace("_", "-")
    s = re.sub(r"-(final|fixed|v\d+|resubmit\w*|copy|dataos.*|ready.*)$", "", s)
    return re.sub(r"^(taskid-|task-)", "", s)


man = json.load(open(os.path.join(BASE, "manifest.json"), encoding="utf-8"))
by_copy = {v["copy"]: v for v in man.values()}
fails = []
for b in BATCH:
    for vv in glob.glob(os.path.join(BASE, b, "verdicts", "*.verify.json")):
        if json.load(open(vv, encoding="utf-8")).get("overall") == "CONFIRMED_MAJOR":
            first = json.load(
                open(vv.replace(".verify.json", ".json"), encoding="utf-8")
            )
            fails.append(by_copy[str(first["dataos_id"]).strip()])
cons = {t: get(C, f"'{t}'!A1:T1000") for t in ("SVC", "EKW")}
for _ws, _rows in cons.items():
    _hdr = [h.strip().lower() for h in (_rows[0] if _rows else [])]
    if "qc batch" not in _hdr:
        sys.exit(f"{_ws}: no 'QC batch' header on the consolidated sheet")
    BCOL[_ws] = _hdr.index("qc batch")
trk = {ws: get(S, f"'{t}'!A1:C2000") for ws, t in TRK.items()}
bad = []
tagged_expected = set()
for m in fails:
    ws, batch = m["ws"], BATCH[m["batch"]]
    rows = [
        i
        for i, r in enumerate(cons[ws], 1)
        if len(r) > BCOL[ws]
        and r[BCOL[ws]].strip() == batch
        and r[4].strip() == m["task"]
    ]
    if len(rows) != 1:
        bad.append((m["task"], f"consolidated rows matched: {rows}"))
    for i in rows:
        r = (cons[ws][i - 1] + [""] * 20)[:20]
        tagged_expected.add((ws, i))
        if r[7] != "Done" or TAG not in r[13] or "Major" not in (r[10], r[11], r[12]):
            bad.append(
                (
                    m["task"],
                    f"row {i} H={r[7]!r} KLM={r[10:13]} tag={'yes' if TAG in r[13] else 'NO'}",
                )
            )
    tr = [r for r in trk[ws] if r and key(r[0]) == key(m["task"])]
    au = m["author"].lower().split()[0]
    ok = [r for r in tr if len(r) > 2 and r[2].strip() == "Rejected"]
    if not ok:
        bad.append((m["task"], "tracker not Rejected: " + str([r[:3] for r in tr])))
stray = [
    (ws, i, r[4])
    for ws in cons
    for i, r in enumerate(cons[ws], 1)
    if len(r) > 13 and TAG in r[13] and (ws, i) not in tagged_expected
]
print(
    "confirmed fails:",
    len(fails),
    "| consolidated rows tagged:",
    sum(1 for ws in cons for r in cons[ws] if len(r) > 13 and TAG in r[13]),
)
print("problems:", bad or "none")
print("tagged rows not in the confirmed list:", stray or "none")

import sys
if "--show" in sys.argv:
    for m in fails:
        ws, b = m["ws"], BATCH[m["batch"]]
        for i, r in enumerate(cons[ws], 1):
            if len(r) > BCOL[ws] and r[BCOL[ws]].strip() == b and r[4].strip() == m["task"]:
                r = (r + [""] * 20)[:20]
                k = r[13].find(TAG)
                print(ws, i, m["task"], "| H", r[7], "| KLM", r[10:13], "| note:", r[13][k:k+160].replace(chr(10), " "))
