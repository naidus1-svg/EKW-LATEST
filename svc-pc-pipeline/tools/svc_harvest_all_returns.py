#!/usr/bin/env python3
"""Harvest EVERY DataOS return we have, across ALL rounds, into durable artifacts.

Why this exists: DataOS feedback arrives as `*_with_runs*.zip` files dropped in Downloads, one per graded
batch. As of 2026-09-21 there are 13 of them (70 distinct graded tasks). Left as loose zips, the feedback
is neither durable nor systematically applied - a new session cannot see it. This tool turns the pile into:

  1. ekw/dataos-returns-ledger-2026-09-21.md   - one row per zip: tasks, accept/needs_revision/reject/invalid
  2. ekw/dataos-findings-allrounds-2026-09-21.json - per task, every MAJOR finding across all rounds (deduped)
  3. _targeted_briefs/<task>.md               - a directed fix brief (accumulated findings + the full sweep)
                                                 for each graded task still in the pipeline; pushed to the
                                                 sandbox /root/qc/_targeted/ and used by svc_fullsweep_pool.sh

Re-run whenever a new return zip lands. Pass --briefs to (re)generate the directed briefs; default only
refreshes the ledger + findings json. Pass a different Downloads dir as arg1 if needed.

Operative pass rule (confirmed by the user 2026-09-21): a task passes when 2 of 3 (or both of 2) reviewers
give 0 MAJOR checks; GPT-5.6-sol's ceiling verdict is needs_revision, so needs_revision-with-0-majors is a
pass. This tool records MAJOR findings only (those are what a fix must clear)."""

import json, re, zipfile, sys, os, glob, datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)  # repo root (tools/..)
DL = (
    sys.argv[1]
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--")
    else os.path.join(os.path.expanduser("~"), "Downloads")
)
MK_BRIEFS = "--briefs" in sys.argv
STAMP = datetime.date.today().isoformat()
LEDGER = os.path.join(HERE, "ekw", "dataos-returns-ledger-%s.md" % STAMP)
FINDINGS = os.path.join(HERE, "ekw", "dataos-findings-allrounds-%s.json" % STAMP)
BRIEF_TPL = open(
    os.path.join(HERE, "tools", "svc_fullsweep_brief.md"), encoding="utf-8"
).read()
OUTDIR = os.path.join(HERE, "_targeted_briefs")
FILL = os.path.join(HERE, "_fill.txt")
inpipe = set()
if os.path.exists(FILL):
    inpipe = {x.strip() for x in open(FILL).read().splitlines() if x.strip()} | {
        "SVC-PC-12-2-0",
        "SVC-PC-19-4-0",
    }


def last_verdict_json(text):
    for pos in reversed([m.start() for m in re.finditer(r'"overall_verdict"', text)]):
        s = text.rfind("{", 0, pos)
        d = 0
        for i in range(s, len(text)):
            if text[i] == "{":
                d += 1
            elif text[i] == "}":
                d -= 1
                if d == 0:
                    try:
                        j = json.loads(text[s : i + 1])
                        if isinstance(j, dict) and isinstance(j.get("checks"), list):
                            return j
                    except Exception:
                        pass
                    break
    return None


zips = sorted(glob.glob(os.path.join(DL, "*_with_runs*.zip")))
acc = {}  # (task,cid,name60) -> finding
ledger_rows = []  # per zip
for zp in zips:
    zn = os.path.basename(zp)
    try:
        z = zipfile.ZipFile(zp)
    except Exception as e:
        ledger_rows.append((zn, 0, 0, 0, 0, 0, "UNREADABLE %s" % e))
        continue
    tasks = sorted(
        {
            m.group(1)
            for n in z.namelist()
            for m in [re.match(r"(SVC-PC-\d+-\d+-\d+)/", n)]
            if m
        }
    )
    a = nr = rj = iv = 0
    for t in tasks:
        seatv = []
        for n in z.namelist():
            if (
                n.startswith(t + "/")
                and "/verifications/comprehensive_review_" in n
                and n.endswith(".md")
            ):
                d = last_verdict_json(z.read(n).decode("utf-8", "replace"))
                if not d:
                    continue
                if "gpt-5.6-sol" not in n and "opus-5" not in n:
                    continue
                maj = [
                    c
                    for c in d.get("checks", [])
                    if str(c.get("severity", "")).lower() == "major"
                ]
                if "gpt-5.6-sol" in n:
                    seatv.append((str(d.get("overall_verdict")), len(maj)))
                for c in maj:
                    cid = str(c.get("check") or c.get("check_id") or c.get("id") or "?")
                    nm = str(c.get("name") or "")
                    key = (t, cid, nm[:60])
                    e = acc.setdefault(
                        key,
                        {
                            "t": t,
                            "cid": cid,
                            "nm": nm,
                            "just": "",
                            "fix": "",
                            "rounds": set(),
                        },
                    )
                    e["rounds"].add(zn)
                    j = c.get("justification") or c.get("reason") or ""
                    f = c.get("suggested_fix") or ""
                    if len(j) > len(e["just"]):
                        e["just"] = j
                    if len(f) > len(e["fix"]):
                        e["fix"] = f
        gpt = [v for v in seatv]
        passed = len(gpt) > 0 and all(v == "accept" or (m == 0) for v, m in gpt)
        if any(v == "invalid" for v, _ in gpt):
            iv += 1
        elif passed:
            nr += 1  # 0-major from all GPT seats = our pass bar
        else:
            rj += 1
    ledger_rows.append((zn, len(tasks), nr, rj, iv, 0, ""))

bytask = {}
for (t, cid, n60), e in acc.items():
    bytask.setdefault(t, []).append(e)
graded = sorted(bytask)

# ledger md
os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
with open(LEDGER, "w", encoding="utf-8", newline="\n") as f:
    f.write("# DataOS returns ledger (%s)\n\n" % STAMP)
    f.write(
        "Regenerate: `python tools/svc_harvest_all_returns.py [--briefs]`. Source zips live in Downloads "
        "(`*_with_runs*.zip`); this is the durable record of what came back.\n\n"
    )
    f.write(
        "**%d return zips, %d distinct graded tasks.** Pass = 0 MAJOR from all GPT seats "
        "(needs_revision-0-major counts).\n\n" % (len(zips), len(graded))
    )
    f.write(
        "| zip | tasks | pass (0-major) | fail (major) | invalid |\n|---|---|---|---|---|\n"
    )
    for zn, nt, nr, rj, iv, _, note in ledger_rows:
        f.write(
            "| %s | %d | %d | %d | %d |%s\n"
            % (zn, nt, nr, rj, iv, (" " + note) if note else "")
        )
    f.write("\nDistinct graded tasks (%d): %s\n" % (len(graded), ", ".join(graded)))
print("ledger -> %s" % LEDGER)

rec = {
    t: [
        {"cid": e["cid"], "name": e["nm"], "rounds": sorted(e["rounds"])}
        for e in bytask[t]
    ]
    for t in graded
}
open(FINDINGS, "w", encoding="utf-8").write(json.dumps(rec, indent=2))
print("findings -> %s" % FINDINGS)

if MK_BRIEFS:
    os.makedirs(OUTDIR, exist_ok=True)
    w = 0
    for t in graded:
        if inpipe and t not in inpipe:
            continue
        lines = []
        for e in sorted(bytask[t], key=lambda e: e["cid"]):
            rd = ",".join(sorted(os.path.splitext(r)[0] for r in e["rounds"]))
            ln = "[%s] %s" % (e["cid"], e["nm"])
            if e["just"]:
                ln += "\n   why: " + e["just"][:400]
            if e["fix"]:
                ln += "\n   suggested_fix: " + e["fix"][:300]
            ln += "\n   (seen in: %s)" % rd
            lines.append(ln)
        body = (
            BRIEF_TPL.replace("{TASK}", t)
            + "\n\n=== DataOS findings on this task across ALL rounds graded so far. Address EVERY one AND "
            "complete the full coverage sweep above (the sweep is the superset; these are holes DataOS "
            "already caught, do not regress any) ===\n\n" + "\n\n".join(lines) + "\n"
        )
        open(
            os.path.join(OUTDIR, t + ".md"), "w", encoding="utf-8", newline="\n"
        ).write(body)
        w += 1
    print("directed briefs (in-pipeline graded) -> %s (%d)" % (OUTDIR, w))
print(
    "\nzips found: %d ; graded tasks: %d ; in-pipeline: %d"
    % (len(zips), len(graded), len([t for t in graded if not inpipe or t in inpipe]))
)
