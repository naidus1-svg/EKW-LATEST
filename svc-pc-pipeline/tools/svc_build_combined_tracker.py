import subprocess, json, urllib.request, urllib.parse, sys, re
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
APPLY = "--apply" in sys.argv
TOK = subprocess.run(
    ["gcloud.cmd", "auth", "print-access-token"], capture_output=True, text=True
).stdout.strip()
H = {"Authorization": "Bearer " + TOK, "Content-Type": "application/json"}
MAIN = "1JmpP38bcOUDmKlkx_2HndB4GdncPgObC4-_vnQFNaw4"
CONS = "15Z00RATLJt7QcyT_-Rc6Y0jYS9WmcqUpukKp08GwAZ8"
SNAP2 = "1MbKMJQ1dPjm9eS9PntOnhLzyappKv4I6rXkslEBv6ys"  # 2 days ago
SNAP1 = "17Du5Zqp4rFU_d30lp9mhJD6pqJcgO9wbwkQzWYZvzi4"  # yesterday
TA, TB = "SVC QC Tracker A", "Team B SVC Tracker"


def gv(sid, rng):
    u = "https://sheets.googleapis.com/v4/spreadsheets/%s/values/%s" % (
        sid,
        urllib.parse.quote(rng),
    )
    return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=H))).get(
        "values", []
    )


# submissions per canonical name
subs_raw = {}
for r in gv(CONS, "'SVC Submitted Count'!A2:B80"):
    if (
        len(r) >= 2
        and r[0].strip()
        and r[0].strip().lower() not in ("duplicates", "grand total")
    ):
        try:
            subs_raw[r[0].strip()] = subs_raw.get(r[0].strip(), 0) + int(float(r[1]))
        except Exception:
            pass

# canonical-name aliasing for the protected set + Khiem
ALIAS = {
    "salman arshad": "Salman",
    "salman": "Salman",
    "khiem": "Khiem",
    "khiem doan": "Khiem",
    "matheus brito": "Matheus",
    "matheus": "Matheus",
    "ezekiel ogbu": "Ezekiel",
    "ezekiel": "Ezekiel",
    "rakesh das": "Rakesh",
    "rakesh": "Rakesh",
    "vinícius luiz noggoszeki": "Vinicius",
    "vinicius luiz noggoszeki": "Vinicius",
    "vinicius": "Vinicius",
    "vinícius": "Vinicius",
    "andrés felipe navarro gómez": "Andres",
    "andres felipe navarro gomez": "Andres",
    "andres.g2": "Andres",
    "andres": "Andres",
    "andrés": "Andres",
    "jonas marques silva de campos": "Jonas",
    "jonas.c": "Jonas",
    "jonas": "Jonas",
    "brijmohan tiwari": "Brijmohan",
    "brijmohan": "Brijmohan",
    "shaheer amjad": "Shaheer",
    "shaheer": "Shaheer",
    "jyotsana jalan": "Jyotsana",
    "jyotsana": "Jyotsana",
    "muhammad usman": "Usman",
    "usman": "Usman",
}


def canon(name):
    n = str(name).strip()
    if not n:
        return ""
    key = n.lower()
    if key in ALIAS:
        return ALIAS[key]
    # first-token fallback for the protected first names
    first = key.split()[0] if key.split() else key
    if first in ALIAS:
        return ALIAS[first]
    return n  # non-protected: keep raw


# submissions by canonical
subs = Counter()
for n, c in subs_raw.items():
    subs[canon(n)] += c
PROTECTED = {
    "Salman",
    "Khiem",
    "Matheus",
    "Ezekiel",
    "Rakesh",
    "Vinicius",
    "Andres",
    "Jonas",
    "Brijmohan",
    "Shaheer",
    "Jyotsana",
    "Usman",
}
print("protected submission counts:", {p: subs.get(p, 0) for p in PROTECTED})


def split_assignees(cell):
    return [canon(x) for x in re.split(r"[+/,]", str(cell)) if x.strip()]


# read a team tab into {task: (assignees_list, status)}
def read_team(sid, tab, status_col):
    out = {}
    grid = gv(sid, "'%s'!A2:AJ1000" % tab)
    for r in grid:
        t = r[0].strip() if r else ""
        if not t.startswith("SVC-PC-"):
            continue
        assignees = split_assignees(r[1]) if len(r) > 1 else []
        status = (
            r[status_col].strip()
            if (len(r) > status_col and r[status_col].strip())
            else ""
        )
        out[t] = (assignees, status)
    return out


SNAP0 = "1NwMdmCVKy4_yNHx-4tVeZmFpPdRbpGSfsh4kbxKPvxg"  # Sep 18 revision copy (4th, oldest point)
curA = read_team(MAIN, TA, 2)  # Team A status col C=2
curB = read_team(MAIN, TB, 3)  # Team B status col D=3
s2A = read_team(SNAP2, TA, 2)
s2B = read_team(SNAP2, TB, 3)
s1A = read_team(SNAP1, TA, 2)
s1B = read_team(SNAP1, TB, 3)
s0A = read_team(SNAP0, TA, 2)
s0B = read_team(SNAP0, TB, 3)
# 5 Salman no-progress tasks handed to Jonas (preserve across rebuilds)
JONAS_OVERRIDE = {
    "SVC-PC-51-0-0",
    "SVC-PC-60-0-0",
    "SVC-PC-60-2-0",
    "SVC-PC-60-6-0",
    "SVC-PC-61-2-0",
}

# submitted tasks from consolidated SVC (task col D=3, submitter B=1, avail F=5, eqc G=6)
submitted = {}
for r in gv(CONS, "SVC!A2:H1052"):
    task = r[3].strip() if len(r) > 3 else ""
    by = r[1].strip() if len(r) > 1 else ""
    if task.startswith("SVC-PC-") and (by or (len(r) > 5 and r[5].strip())):
        submitted.setdefault(task.upper(), by or "?")
print("submitted tasks in consolidated:", len(submitted))


def progressed(task, curT, s1T, s2T, s0T):
    # progress = the status changed at ANY point across Sep18 -> Sep19 -> Sep20 -> today (4 points)
    trail = [
        s0T.get(task, ([], ""))[1],
        s2T.get(task, ([], ""))[1],
        s1T.get(task, ([], ""))[1],
        curT.get(task, ([], ""))[1],
    ]
    return len(set(trail)) > 1


alltasks = sorted(
    set(curA) | set(curB), key=lambda t: [int(x) for x in re.findall(r"\d+", t)] or [0]
)
active_rows, submitted_rows = [], []
reason_ct = Counter()
MANUAL_QC_STATUS = {
    "submit for manual qc",
    "done- manual qc passed",
    "done - manual qc passed",
}
for t in alltasks:
    tu = t.upper()
    aA = curA.get(t, ([], ""))[0]
    aB = curB.get(t, ([], ""))[0]
    statusA = curA.get(t, ([], ""))[1]
    if tu in submitted or statusA.strip().lower() in MANUAL_QC_STATUS:
        who = submitted.get(tu) or (aA[0] if aA else (aB[0] if aB else "?"))
        src = "consolidated" if tu in submitted else ("tracker: " + statusA)
        submitted_rows.append([t, who, "Submitted for Manual QC", "", src])
        reason_ct["submitted"] += 1
        continue
    progA = progressed(t, curA, s1A, s2A, s0A)
    progB = progressed(t, curB, s1B, s2B, s0B)
    cands = []  # (name, progressed, status)
    for nm in aA:
        cands.append((nm, progA, curA.get(t, ([], ""))[1]))
    for nm in aB:
        cands.append((nm, progB, curB.get(t, ([], ""))[1]))
    owner, note, status = "", "", ""
    if any(c[0] == "Khiem" for c in cands):
        owner, note = "Khiem", "kept: Khiem"
        status = next((c[2] for c in cands if c[0] == "Khiem"), "")
    else:
        prot = [c for c in cands if c[0] in PROTECTED]
        if prot:
            prot.sort(key=lambda c: (subs.get(c[0], 0), c[1]), reverse=True)
            owner, note, status = (
                prot[0][0],
                "kept: top-12 (%d subs)" % subs.get(prot[0][0], 0),
                prot[0][2],
            )
        else:
            active = [c for c in cands if c[1]]
            if active:
                active.sort(key=lambda c: subs.get(c[0], 0), reverse=True)
                owner, note, status = (
                    active[0][0],
                    "kept: active (made progress)",
                    active[0][2],
                )
            else:
                owner, note, status = (
                    "",
                    "HEADROOM (released: stale/idle)",
                    "Available - claim me",
                )
    if tu in JONAS_OVERRIDE:
        owner, note = "Jonas", "reassigned 2026-09-21: Salman no-progress -> Jonas"
    reason_ct[note.split(":")[0].split(" (")[0]] += 1
    active_rows.append([t, owner, status, "", note])

# order active: headroom first (so people see claimable at top), then assigned
active_rows.sort(key=lambda r: (r[1] != "", r[1]))
print("\n=== SUMMARY ===")
print("total tasks:", len(alltasks))
print("submitted (-> bottom):", len(submitted_rows))
print("active pool:", len(active_rows))
print("reasons:", dict(reason_ct))
owners = Counter(r[1] if r[1] else "(HEADROOM)" for r in active_rows)
print("active owners:", owners.most_common(18))
print(
    "\n=== FAIRNESS: protected holdings vs submissions (holds >> subs = over-allocated) ==="
)
for p in sorted(PROTECTED, key=lambda x: -owners.get(x, 0)):
    h = owners.get(p, 0)
    s = subs.get(p, 0)
    ratio = (h / s) if s else 0
    print("  %-10s holds %3d  subs %2d  ratio %.1fx" % (p, h, s, ratio))

import io

with io.open("_combined_preview.tsv", "w", encoding="utf-8", newline="\n") as f:
    f.write("Task ID\tAssigned to\tStatus\tClaimed at\tResolution note\n")
    for r in active_rows:
        f.write("\t".join(r) + "\n")
    f.write("\t\t\t\t\n=== SUBMITTED FOR MANUAL QC ===\t\t\t\t\n")
    for r in submitted_rows:
        f.write("\t".join(r) + "\n")
print(
    "preview -> _combined_preview.tsv (%d active + %d submitted rows)"
    % (len(active_rows), len(submitted_rows))
)
if not APPLY:
    print("\n(dry run; pass --apply to create/write the tab)")
    sys.exit(0)

# ---- build the full grid and write it as the first tab ----
TITLE = "SVC QC Tracker Combined"
grid_out = [
    ["SVC QC Tracker Combined - de-duplicated, one owner per task (built 2026-09-21)"],
    [
        "Top section = ACTIVE pool. Blank 'Assigned to' = HEADROOM: claim it by adding your name + timestamp. "
        "Protected (kept): Khiem + top-12 producers by submission count. Non-protected STALE claims (no status "
        "change across the last 2 daily snapshots) were released to headroom; active claims kept. "
        "Bottom = Submitted for Manual QC (from the consolidated tracker + tracker manual-QC statuses)."
    ],
    [""],
    ["Task ID", "Assigned to", "Status", "Claimed at", "Resolution note"],
]
grid_out += active_rows
grid_out += [["", "", "", "", ""], ["=== SUBMITTED FOR MANUAL QC ===", "", "", "", ""]]
grid_out += submitted_rows

# find or create the tab
u = (
    "https://sheets.googleapis.com/v4/spreadsheets/%s?fields=sheets(properties(sheetId,title,index))"
    % MAIN
)
sheets = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=H)))[
    "sheets"
]
existing = next(
    (s["properties"] for s in sheets if s["properties"]["title"] == TITLE), None
)
reqs = []
if existing is None:
    reqs.append(
        {
            "addSheet": {
                "properties": {
                    "title": TITLE,
                    "index": 0,
                    "gridProperties": {
                        "rowCount": len(grid_out) + 20,
                        "columnCount": 6,
                        "frozenRowCount": 4,
                    },
                }
            }
        }
    )
else:
    sid_tab = existing["sheetId"]
    reqs.append(
        {
            "updateSheetProperties": {
                "properties": {"sheetId": sid_tab, "index": 0},
                "fields": "index",
            }
        }
    )
    reqs.append(
        {"updateCells": {"range": {"sheetId": sid_tab}, "fields": "userEnteredValue"}}
    )  # clear all
body = json.dumps({"requests": reqs}).encode()
uu = "https://sheets.googleapis.com/v4/spreadsheets/%s:batchUpdate" % MAIN
resp = json.load(
    urllib.request.urlopen(
        urllib.request.Request(uu, data=body, headers=H, method="POST")
    )
)
if existing is None:
    new_sid = resp["replies"][0]["addSheet"]["properties"]["sheetId"]
    print("created tab sheetId=%s at index 0" % new_sid)
else:
    print(
        "reused + cleared existing tab sheetId=%s, moved to index 0"
        % existing["sheetId"]
    )

# write values
wr = json.dumps({"values": grid_out}).encode()
wu = (
    "https://sheets.googleapis.com/v4/spreadsheets/%s/values/%s!A1?valueInputOption=RAW"
    % (MAIN, urllib.parse.quote("'%s'" % TITLE))
)
wresp = json.load(
    urllib.request.urlopen(urllib.request.Request(wu, data=wr, headers=H, method="PUT"))
)
print(
    "wrote %s cells across %s rows"
    % (wresp.get("updatedCells"), wresp.get("updatedRows"))
)

# readback: first data row + the submitted header row
rb = gv(MAIN, "'%s'!A1:E6" % TITLE)
print("readback top:")
for r in rb:
    print("  ", r)
print(
    "DONE: %d active (%d headroom) + %d submitted, tab is first in the main tracker"
    % (len(active_rows), sum(1 for r in active_rows if not r[1]), len(submitted_rows))
)
