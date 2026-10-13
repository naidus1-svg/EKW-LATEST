#!/usr/bin/env python3
"""Record SVC-PC submissions in the consolidated tracker (`15Z00RAT...`, tab `SVC`), per the QC-team SOP
(Google Doc 1IL2s3ezzkoMpQLuGTGEK4ZU9Rjb2c_qkF0x60ye_2Zo, section 7c). Every row goes in the MAIN table, at the
bottom of the live queue above Rejected; nothing is ever written under the lower Duplicates heading and no row
is ever moved. Stdlib only; needs `gcloud.cmd auth login --enable-gdrive-access`. Dry run by default.

Row kinds:
  Columns are found by header text (2026-09-24 layout: B Submitted by | C Email Id | D Google Doc | E task_name |
  F DataOS link | G Task Available Status | H EQC Status). Letters below are the pre-09-24 layout, for history.
  --main TASK=REV (new)        B submitter | C =HYPERLINK(doc url, doc title) | D task | E DataOS link | F EQC ready
  --main, earlier row under Rejected (resubmission): as above, F "EQC Ready Revision", and the "Resubmission
      change" column (found by header) = "Resubmit- Previous submission major check failed. <--resubmit-note>"
  --dup "TASK=REV=WHO" (someone else's submission passed): C "Duplicate - already submitted by WHO",
      F EQC ready, G EQC Status "Skip- duplicate" (the sheet highlights it yellow)

Safety (each from a past incident):
- The Duplicates heading is FOUND by its text in column B, never assumed by row number.
- The main list has a "Rejected" heading: rows above it are the live EQC queue, rows below it (to Duplicates)
  are EQC rejects. New rows go ONLY into the live queue, into empty rows after its last filled row; if there
  are too few, --apply inserts the missing rows directly above the Rejected heading (dry run says so).
- A task already in the live queue is skipped and reported (a second row double-counts it). A task whose only
  rows are under Rejected is a resubmission: it gets a fresh live-queue row whose C names the prior link and
  row; the reject row is never edited.
- Repeated --main / --dup flags accumulate (2026-09-22: a second --main silently replaced the first).
- A duplicate row is skipped when the same task + link is already in the live queue.
- Rows go into EMPTY rows only (main: the empty rows after the last filled main-list row and above the
  Duplicates heading, never a hole inside the list; duplicates: the first empty rows below the heading). Each target row is re-read and must still be empty in the same step as its write;
  the tool never inserts rows or shifts anything. If there is no empty row, it stops and says so.
- The tab A:G is snapshotted to `_scratch_consolidated_snapshot_<ts>.json` before writing, and every written
  row is read back.

Usage:
  python tools/svc_consolidated_record.py --doc QCR_group_22092026 \
      --main SVC-PC-11-2-0=137969 SVC-PC-2-7-0=137976 \
      --dup "SVC-PC-12-6-0=137972=Ezekiel Ogbu" [--submitter Khiem] [--apply]
"""

import re, argparse, json, os, subprocess, sys, time, urllib.parse, urllib.request

SHEET = "15Z00RATLJt7QcyT_-Rc6Y0jYS9WmcqUpukKp08GwAZ8"
TAB = "SVC"
WIDTH, RESUB_COL = 7, 13  # set from the header row at run time
URL = "https://data-os.turing.com/tasks/"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def token():
    p = subprocess.run(
        ["gcloud.cmd", "auth", "print-access-token"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if p.returncode != 0 or not p.stdout.strip():
        sys.exit(
            "gcloud has no token. Run: gcloud.cmd auth login --enable-gdrive-access"
        )
    return p.stdout.strip()


TOK = None


def api(method, path, body=None):
    req = urllib.request.Request(
        "https://sheets.googleapis.com/v4/spreadsheets/%s%s" % (SHEET, path),
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Authorization": "Bearer " + TOK, "Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req, timeout=60))


def getv(a1):
    return api("GET", "/values/" + urllib.parse.quote("%s!%s" % (TAB, a1))).get(
        "values", []
    )


def norm(t):
    t = (t or "").strip().upper().replace("\r", "")
    return t.replace("SVC-PC-", "").replace("SVC-", "")


def empty(r):
    # Column A is the row number: blank on the SVC tab, an =A<n-1>+1 formula on every EKW row. It never marks a
    # row as used, and this tool never writes it (2026-09-25: the EKW tab had 12 free rows the old check missed).
    return not any((c or "").strip() for c in r[1:])


def main():
    global TOK
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", required=True, help="QCR doc title for the main-list rows")
    # 2026-09-23 (owner): column C must be a working link to the QCR doc, not the bare title.
    ap.add_argument(
        "--doc-url",
        default="",
        help="QCR doc URL; column C becomes =HYPERLINK(url, title)",
    )
    ap.add_argument("--main", nargs="*", action="extend", default=[], help="TASK=REVID")
    ap.add_argument(
        "--dup",
        nargs="*",
        action="extend",
        default=[],
        help="TASK=REVID=WHO (who already submitted it)",
    )
    ap.add_argument("--submitter", default="Khiem")
    ap.add_argument("--email", default="khiem.doan@turing.com")
    ap.add_argument(
        "--resubmit-note",
        default="Fixed every major the DataOS comprehensive review raised; the resubmitted build re-graded with 0 majors on both reviews.",
        help="what changed since the rejected submission (goes after the SOP prefix in the Resubmission change column)",
    )
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.main and not a.doc_url.startswith("https://"):
        sys.exit(
            "ABORT: --main rows need --doc-url <QCR doc URL>; column C must link to the doc"
        )
    TOK = token()

    # Column positions come from the header row. 2026-09-24: an "Email Id" column was inserted at C, shifting doc,
    # task, link and status one to the right; hardcoded indexes would have written every field one column off.
    hdr = [(c or "").strip().lower() for c in ((getv("A1:Z1") or [[]])[0])]

    def col(*names):
        for n in names:
            hit = [i for i, h in enumerate(hdr) if h.startswith(n)]
            if hit:
                return hit[0]
        sys.exit("ABORT: no %r header in row 1; check the tab layout" % (names,))

    # the EKW tab spells it "Submittted By" (three t's); accept both
    C_SUB, C_EMAIL, C_DOC = (
        col("submitted by", "submittted by"),
        col("email"),
        col("google doc"),
    )
    C_TASK, C_LINK = col("task_name", "task name"), col("link in data-os", "link")
    C_AVAIL, C_EQC = col("task available status"), col("eqc status")
    # QC verdict columns (Prompt ambiguity / Prompt-Tests misalignment / Test coverage). 2026-09-28: QC rejects in
    # place (EQC "Done" + a Major here, row left above the Rejected heading), same rule as svc_build_freeze.py.
    C_CHECKS = [
        col("prompt ambiguity"),
        col("prompt-tests", "prompt tests", "prompt–tests"),
        col("test coverage"),
    ]

    def rejected_in_place(r):
        r = r + [""] * 26
        eqc = r[C_EQC].strip().lower()
        return eqc == "reject" or (
            eqc == "done" and any("major" in r[c].lower() for c in C_CHECKS)
        )

    def layout():
        rows = getv("A1:Z1000")
        rows += [[]] * (1000 - len(rows))
        heads = [
            i
            for i, r in enumerate(rows, 1)
            if len(r) > 1 and r[1].strip().lower() == "duplicates"
        ]
        if len(heads) != 1:
            sys.exit(
                "ABORT: expected exactly one 'Duplicates' heading in column B, found rows %s"
                % heads
            )
        H = heads[0]
        # The main list is split by a "Rejected" heading (column A or B). Rows above it are the live EQC queue;
        # rows between it and Duplicates are EQC rejects. 2026-09-22: rows appended after the last filled row
        # landed under Rejected, so EQC read four fresh submissions as rejected.
        rj = [
            i
            for i, r in enumerate(rows, 1)
            if i < H and any((c or "").strip().lower() == "rejected" for c in r[:2])
        ]
        if len(rj) > 1:
            sys.exit("ABORT: more than one 'Rejected' heading, rows %s" % rj)
        R = rj[0] if rj else H
        # 2026-09-23: the EQC team added a "Put your tasks above in the table ^^^ Do not move tasks below (read
        # SOP!)" row above Rejected. It is the live queue's real end: counted as a filled row, it pushed a new
        # submission to the row BELOW it, outside the table.
        note = [
            i
            for i, r in enumerate(rows, 1)
            if i < R and any("put your tasks above" in (c or "").lower() for c in r[:3])
        ]
        if note:
            R = note[0]
        return rows, H, R

    rows, H, R = layout()
    # Column positions come from the header row, not from memory: "Resubmission change" is where the QC-team SOP
    # wants a resubmission's note (the SOP text says "column M"; M is the QC team's own Detailed Feedback).
    global WIDTH, RESUB_COL
    rc = [i for i, h in enumerate(hdr) if h.startswith("resubmission")]
    # 2026-09-25: the EKW tab has no "Resubmission change" column. It is only needed for a resubmission row, so a
    # tab without it still takes first submissions and duplicates; a resubmission there aborts below.
    RESUB_COL = rc[0] if rc else None
    WIDTH = (
        RESUB_COL if rc else max(C_SUB, C_EMAIL, C_DOC, C_TASK, C_LINK, C_AVAIL, C_EQC)
    ) + 1
    print(
        "tab %s: live queue rows 2-%d, Rejected heading %s, Duplicates heading %d"
        % (TAB, R - 1, R if R != H else "(none)", H)
    )

    def active(rows, R):
        return {i: r for i, r in enumerate(rows, 1) if 2 <= i < R}

    main_rows = active(rows, R)
    dup_rows = {i: r for i, r in enumerate(rows, 1) if i > H}
    rej_rows = {i: r for i, r in enumerate(rows, 1) if R < i < H}

    todo = []  # (task, rev, doc cell)
    for spec in a.main:
        t, rev = spec.split("=")
        same = [
            i
            for i, r in main_rows.items()
            if len(r) > C_TASK and norm(r[C_TASK]) == norm(t)
        ]
        live = [i for i in same if not rejected_in_place(main_rows[i])]
        if live:
            r = main_rows[live[0]] + [""] * 26
            print(
                "  SKIP main %s: already in the live queue at row %s (%s, %s)"
                % (t, live, r[C_LINK], r[C_EQC])
            )
            continue
        # A task whose only rows are under Rejected is a RESUBMISSION. QC-team SOP (2026-09-23): a fresh
        # live-queue row with Task Available Status "EQC Ready Revision" and the "Resubmission change" column
        # saying "Resubmit- Previous submission major check failed" plus what changed; C stays the doc link.
        # The reject row is never edited.
        prior = [
            i
            for i, r in rej_rows.items()
            if len(r) > C_TASK and norm(r[C_TASK]) == norm(t)
        ] + same  # rows rejected in place count as the prior submission

        if prior:
            todo.append(
                (
                    t,
                    rev,
                    a.doc,
                    "resubmit",
                    "Resubmit- Previous submission major check failed. "
                    + a.resubmit_note,
                )
            )
        else:
            todo.append((t, rev, a.doc, "main", ""))
    # QC-team SOP (2026-09-23): a task someone else already submitted and PASSED goes in the MAIN table (bottom of
    # the live queue, above Rejected) with EQC Status "Skip- duplicate" - never in the lower Duplicates section.
    for spec in a.dup:
        t, rev, who = spec.split("=", 2)
        mine = [
            i
            for i, r in main_rows.items()
            if len(r) > C_LINK
            and norm(r[C_TASK]) == norm(t)
            and r[C_LINK].strip() == URL + rev
        ]
        if mine:
            print(
                "  SKIP dup %s: same task + link already in the live queue at row %s"
                % (t, mine)
            )
            continue
        todo.append((t, rev, "Duplicate - already submitted by " + who, "dup", ""))

    def free_rows(rows, R):
        m = active(rows, R)
        # Only rows BELOW the last filled live-queue row: a blank row inside the list is a hole in someone else's
        # numbered batch (2026-09-22: row 89 sat between another submitter's #95 and #97), not free space.
        last = max([i for i, r in m.items() if not empty(r)] or [1])
        return sorted(i for i, r in m.items() if empty(r) and i > last)

    need = len(todo)
    free = free_rows(rows, R)
    if need > len(free):
        add = need - len(free)
        if R == H:
            sys.exit(
                "ABORT: no Rejected heading and no room above Duplicates; add rows by hand"
            )
        if not a.apply:
            print(
                "  would INSERT %d empty row(s) directly above the Rejected heading (row %d)"
                % (add, R)
            )
            free = free + list(range(R, R + add))
        else:
            sid = next(
                x["properties"]["sheetId"]
                for x in api("GET", "?fields=sheets.properties(sheetId,title)")[
                    "sheets"
                ]
                if x["properties"]["title"] == TAB
            )
            api(
                "POST",
                ":batchUpdate",
                {
                    "requests": [
                        {
                            "insertDimension": {
                                "range": {
                                    "sheetId": sid,
                                    "dimension": "ROWS",
                                    "startIndex": R - 1,
                                    "endIndex": R - 1 + add,
                                },
                                "inheritFromBefore": True,
                            }
                        }
                    ]
                },
            )
            print(
                "  INSERTED %d row(s) above the Rejected heading (was row %d)"
                % (add, R)
            )
            rows, H, R = layout()
            dup_rows = {i: r for i, r in enumerate(rows, 1) if i > H}
            free = free_rows(rows, R)
            if need > len(free):
                sys.exit("ABORT: still only %d free row(s) after insert" % len(free))
    plan = []
    for (t, rev, doc, kind, note), rown in zip(todo, free):
        vals = [""] * WIDTH
        vals[C_SUB], vals[C_EMAIL] = a.submitter, a.email
        vals[C_TASK], vals[C_LINK], vals[C_AVAIL] = t, URL + rev, "EQC ready"
        if kind == "dup":
            vals[C_DOC], vals[C_EQC] = doc, "Skip- duplicate"
        else:
            vals[C_DOC] = (
                '=HYPERLINK("%s","%s")' % (a.doc_url, doc.replace('"', "'"))
                if a.doc_url
                else doc
            )
        if kind == "resubmit":
            if RESUB_COL is None:
                sys.exit(
                    "ABORT: %s is a resubmission but this tab has no 'Resubmission change' column"
                    % t
                )
            vals[C_AVAIL], vals[RESUB_COL] = "EQC Ready Revision", note
        plan.append((rown, vals))

    for rown, vals in plan:
        print("  row %d <- %s" % (rown, vals))
    if not a.apply or not plan:
        print("DRY RUN." if plan else "nothing to write.")
        return
    snap = os.path.join(
        HERE, "_scratch_consolidated_snapshot_%d.json" % int(time.time())
    )
    json.dump(rows, open(snap, "w", encoding="utf-8"), ensure_ascii=False)
    print("snapshot:", snap)
    for rown, vals in plan:
        cur = getv("A%d:%s%d" % (rown, chr(ord("A") + WIDTH - 1), rown))
        if cur and not empty(cur[0]):
            print("  ABORT row %d: no longer empty (%s) - not written" % (rown, cur[0]))
            continue
        api(
            "PUT",
            "/values/"
            + urllib.parse.quote(
                "%s!B%d:%s%d" % (TAB, rown, chr(ord("A") + WIDTH - 1), rown)
            )
            + "?valueInputOption=USER_ENTERED",
            {"values": [vals[1:]]},  # column A (row number / formula) is never written
        )
    time.sleep(1)
    ok = 0
    for rown, vals in plan:
        back = getv("A%d:%s%d" % (rown, chr(ord("A") + WIDTH - 1), rown))
        got = back[0] if back else []
        # a =HYPERLINK cell reads back as its label, so compare against the label
        want = [re.sub(r'^=HYPERLINK\("[^"]*","(.*)"\)$', r"\1", c) for c in vals]
        got = got + [""] * (len(want) - len(got))
        # 2026-09-28: compare only the cells this writer filled. The EKW tab gained a "Resubmission change" column at T,
        # so the write range now spans P (an ARRAYFORMULA spill, "Verdict (auto, from J:L)") and every row read back
        # as MISMATCH on a formula value the writer never set.
        good = all(
            got[i].strip() == want[i].strip()
            for i in range(1, len(want))
            if want[i].strip()
        )
        ok += good
        print("  row %d readback %s: %s" % (rown, "OK" if good else "MISMATCH", got))
    print("confirmed %d/%d row(s)" % (ok, len(plan)))


if __name__ == "__main__":
    main()
