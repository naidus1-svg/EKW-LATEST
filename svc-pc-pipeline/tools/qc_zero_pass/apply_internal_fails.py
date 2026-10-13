"""Mark CONFIRMED internal zero-pass fails on the consolidated sheet and the live tracker, like manual QC.

A task is a confirmed fail when <batch>/verdicts/<TASK>.json has verdict MAJOR and <TASK>.verify.json has
overall CONFIRMED_MAJOR. Ratings come from the verify file (the verifier's confirmed ratings).

Consolidated (15Z00RAT...): row with task_name == manifest task AND QC batch == QC_batchN:
  H = "Done", K/L/M = ratings, N appended with "Internal zero-pass review (Khiem's team, not TFRL QC), <date>: <feedback>"
Tracker (1JmpP38b...): Combined tab row for the task, C = "Rejected" (old task_N EKW ids only when assignee matches).
Rows already carrying this pass's note are skipped (idempotent). Snapshot to fails_applied_<ts>.json, read back.
usage: python apply_internal_fails.py [--apply] [--batch b1]
"""

import datetime
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
DATE = datetime.date.today().isoformat()  # the day the fails are marked
only = sys.argv[sys.argv.index("--batch") + 1] if "--batch" in sys.argv else None
tok = subprocess.run(
    ["gcloud.cmd", "auth", "print-access-token"], capture_output=True, text=True
).stdout.strip()


def api(sid, method, path, body=None):
    r = urllib.request.Request(
        f"https://sheets.googleapis.com/v4/spreadsheets/{sid}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
    )
    r.add_header("Authorization", "Bearer " + tok)
    r.add_header("Content-Type", "application/json")
    return json.loads(urllib.request.urlopen(r).read())


def get(sid, a1):
    return api(sid, "GET", "/values/" + urllib.parse.quote(a1)).get("values", [])


def key(s):
    s = re.sub(r"\s+", "", s.lower()).replace("svc-pc", "svc").replace("_", "-")
    s = re.sub(r"-(final|fixed|v\d+|resubmit\w*|copy|dataos.*|ready.*)$", "", s)
    return re.sub(r"^(taskid-|task-)", "", s)


man = json.load(open(os.path.join(BASE, "manifest.json"), encoding="utf-8"))
by_copy = {v["copy"]: v for v in man.values()}
# Tasks already marked by an earlier --apply. Authors then fix and resubmit, which clears the note or moves the
# tracker status on; re-marking would re-reject work in progress (FIN-304, HLT-202 and 5 others on 2026-09-27).
LEDGER = os.path.join(BASE, "applied_tasks.json")
applied = json.load(open(LEDGER, encoding="utf-8")) if os.path.exists(LEDGER) else {}
fails, other = [], []
for b in BATCH:
    if only and b != only:
        continue
    for vf in glob.glob(os.path.join(BASE, b, "verdicts", "*.json")):
        if vf.endswith(".verify.json"):
            continue
        v = json.load(open(vf, encoding="utf-8"))
        cid = str(v.get("dataos_id", "")).strip()
        m = by_copy.get(cid) or next(
            (
                x
                for x in man.values()
                if x["batch"] == b and key(x["dataos_name"]) == key(v.get("task", ""))
            ),
            None,
        )
        if not m:
            other.append((b, os.path.basename(vf), "no manifest match"))
            continue
        vv = vf[:-5] + ".verify.json"
        ver = json.load(open(vv, encoding="utf-8")) if os.path.exists(vv) else None
        if (
            v.get("verdict") == "MAJOR"
            and ver
            and ver.get("overall") == "CONFIRMED_MAJOR"
        ):
            # A confirmed fail must carry a Major rating, or the sheet shows a reject with no Major in K:M.
            # num-598 (QC_batch5) did: feedback said MAJOR, ratings were Minor/Good/Good. Fix the verify file first.
            if "Major" not in (ver.get("ratings") or {}).values():
                other.append((b, m["task"], "CONFIRMED_MAJOR but no Major in verify ratings; not written"))
                continue
            if f"{b}/{m['task']}" in applied:
                other.append((b, m["task"], "already applied " + applied[f"{b}/{m['task']}"] + "; not re-written"))
                continue
            fails.append((m, v, ver))
        elif v.get("verdict") == "MAJOR":
            other.append(
                (
                    b,
                    m["task"],
                    "MAJOR not confirmed: "
                    + (ver.get("overall") if ver else "no verify file"),
                )
            )
print(
    f"confirmed fails: {len(fails)}; majors not confirmed: {len([o for o in other if o[2].startswith('MAJOR')])}"
)
for o in other:
    print("  skip", o)

cons = {t: get(C, f"'{t}'!A1:T1000") for t in ("SVC", "EKW")}
for _ws, _rows in cons.items():
    _hdr = [h.strip().lower() for h in (_rows[0] if _rows else [])]
    if "qc batch" not in _hdr:
        sys.exit(f"{_ws}: no 'QC batch' header on the consolidated sheet")
    BCOL[_ws] = _hdr.index("qc batch")
trk = {ws: get(S, f"'{t}'!A1:C2000") for ws, t in TRK.items()}
writes_c, writes_t, snap, problems = [], [], [], []
for m, v, ver in fails:
    ws, batch = m["ws"], BATCH[m["batch"]]
    rt = ver.get("ratings") or {}
    K = rt.get("prompt_ambiguity") or v.get("prompt_ambiguity") or "Good"
    L = (
        rt.get("prompt_tests_misalignment")
        or v.get("prompt_tests_misalignment")
        or "Good"
    )
    M = rt.get("test_coverage") or v.get("test_coverage") or "Good"
    fb = (ver.get("feedback") or v.get("feedback") or "").strip()
    hits = [
        i
        for i, r in enumerate(cons[ws], 1)
        if len(r) > BCOL[ws]
        and r[BCOL[ws]].strip() == batch
        and r[4].strip() == m["task"]
    ]
    if not hits:
        problems.append((m["task"], "no consolidated row with QC batch " + batch))
        continue
    for i in hits:
        r = (cons[ws][i - 1] + [""] * 20)[:20]
        if TAG in r[13]:
            continue
        note = (r[13] + "\n\n" if r[13].strip() else "") + f"{TAG}, {DATE}: {fb}"
        vals = {"H": "Done", "K": K, "L": L, "M": M, "N": note}
        snap.append(
            {
                "sheet": "consolidated",
                "ws": ws,
                "row": i,
                "old": {c: r[ord(c) - 65] for c in vals},
            }
        )
        writes_c += [
            {"range": f"'{ws}'!{c}{i}", "values": [[x]]} for c, x in vals.items()
        ]
    au = m["author"].lower().split()[0] if m["author"] else ""
    th = [i for i, r in enumerate(trk[ws], 1) if r and key(r[0]) == key(m["task"])]
    for i in th:
        r = (trk[ws][i - 1] + ["", "", ""])[:3]
        if (
            ws == "EKW"
            and re.match(r"task_\d+$", r[0].strip(), re.I)
            and r[1].strip()
            and au
            and r[1].strip().lower().split()[0] != au
        ):
            problems.append(
                (
                    m["task"],
                    f"tracker row {i} assignee {r[1]!r} differs from author, skipped",
                )
            )
            continue
        if r[2].strip() != "Rejected":
            snap.append({"sheet": "tracker", "ws": ws, "row": i, "old": {"C": r[2]}})
            writes_t.append({"range": f"'{TRK[ws]}'!C{i}", "values": [["Rejected"]]})
    if not th:
        problems.append((m["task"], "not on tracker"))
print(f"consolidated cells: {len(writes_c)}, tracker cells: {len(writes_t)}")
for p in problems:
    print("  note", p)
for m, v, ver in fails:
    print("  FAIL", m["batch"], m["ws"], m["task"], m["author"])
if "--apply" not in sys.argv:
    sys.exit("dry run")
ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
json.dump(
    snap,
    open(os.path.join(BASE, f"fails_applied_{ts}.json"), "w", encoding="utf-8"),
    ensure_ascii=False,
    indent=0,
)
for sid, w in ((C, writes_c), (S, writes_t)):
    for j in range(0, len(w), 400):
        if w[j : j + 400]:
            api(
                sid,
                "POST",
                "/values:batchUpdate",
                {"valueInputOption": "RAW", "data": w[j : j + 400]},
            )
bad = []
for sid, w in ((C, writes_c), (S, writes_t)):
    for x in w:
        got = (get(sid, x["range"]) or [[""]])[0]
        got = got[0] if got else ""
        if got != x["values"][0][0]:
            bad.append(x["range"])
print("read back:", "all OK" if not bad else bad)
if not bad:
    applied.update({f"{m['batch']}/{m['task']}": ts for m, v, ver in fails})
    json.dump(applied, open(LEDGER, "w", encoding="utf-8"), indent=1, sort_keys=True)
    print("ledger:", len(applied), "tasks in", LEDGER)
