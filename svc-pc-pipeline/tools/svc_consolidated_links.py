"""Which of Khiem's consolidated SVC-tab rows have NO link in column C? Reads cell link metadata (hyperlink,
rich-text link runs, smart chips, =HYPERLINK formula), not just the text. Read-only.
Writes _scratch_unlinked.json (scratch output): [[row, task, title], ...]"""

import os, sys, json, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import svc_consolidated_record as c

c.TOK = c.token()
rng = urllib.parse.quote("%s!B1:D1000" % c.TAB)
fields = urllib.parse.quote(
    "sheets.data.rowData.values(formattedValue,hyperlink,userEnteredValue,"
    "textFormatRuns.format.link,chipRuns)"
)
d = c.api("GET", "?ranges=%s&includeGridData=true&fields=%s" % (rng, fields))
rows = d["sheets"][0]["data"][0].get("rowData", [])
unlinked, linked = [], 0
for i, r in enumerate(rows, 1):
    v = (r.get("values") or []) + [{}] * 3
    who = (v[0].get("formattedValue") or "").strip().lower()
    cc = v[1]
    title = (cc.get("formattedValue") or "").strip()
    if who not in ("khiem", "khiem doan") or not title or title.startswith("Duplicate"):
        continue
    f = (cc.get("userEnteredValue") or {}).get("formulaValue", "")
    has = bool(
        cc.get("hyperlink")
        or f.upper().startswith("=HYPERLINK")
        or title.startswith("http")
        or any(
            (run.get("format") or {}).get("link")
            for run in cc.get("textFormatRuns") or []
        )
        or cc.get("chipRuns")
    )
    if has:
        linked += 1
    else:
        unlinked.append([i, (v[2].get("formattedValue") or ""), title])
print("Khiem rows with a doc in C: %d linked, %d unlinked" % (linked, len(unlinked)))
for u in unlinked:
    print(*u, sep="\t")
json.dump(unlinked, open("_scratch_unlinked.json (scratch output)", "w"))
