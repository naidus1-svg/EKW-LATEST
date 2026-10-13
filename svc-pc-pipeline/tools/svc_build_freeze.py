#!/usr/bin/env python3
"""Build the SVC-PC do-not-touch list from the two team trackers, so our lanes never rework, and our bundler
never ships, a task that is already finished, already submitted, or owned by another person.

Why (2026-09-22): the freeze list (`_v7/accepted.txt`) held only DataOS passes WE had seen. batch_of_18 then
shipped 12-6-0 (already passed manual QC under Ezekiel Ogbu), 29-2-0 (already submitted by Salman Arshad) and
38-1-0 (already approved from our own earlier revision), and the lanes were reworking 12-1-0 (EQC Done). The
trackers knew; nothing read them.

Sources (read-only; needs `gcloud.cmd auth login --enable-gdrive-access`):
- consolidated tracker `15Z00RAT...` tab `SVC`: every task listed with an EQC status other than `Reject`
  (Done, In-progress, or blank = submitted and waiting) is SUBMITTED. A `Reject` row does not freeze.
- tracker `1JmpP38...` tab `SVC QC Tracker Combined`: status `Approved - Passed Manual QC`, any
  `Submitted ...` / `submit for manual QC` / `In review ...` status is SUBMITTED; a task assigned to anyone
  other than Khiem (and not `Available - claim me`) is HUMAN-OWNED.
A task is do-not-touch if either source says SUBMITTED or HUMAN-OWNED, except that our own Combined
"Submitted..." status is ignored when the consolidated tracker's only rows for the task are our EQC Rejects
(the Combined status is stale there; the task is ours to fix). Our own DataOS passes stay in
accepted.txt as before.

Output: `ekw/svc-do-not-touch.tsv` (task, reason) plus a summary. With --push it is copied to the sandbox as
`/root/qc/_v7/do_not_touch.txt`, which svc_ship_manifest.accepted_set() and the lane runner read alongside
accepted.txt. Re-run whenever the trackers change (at least before each bundle).

Usage: python tools/svc_build_freeze.py [--push] [--check TASK ...]
"""

import argparse, json, os, re, subprocess, sys, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "ekw", "svc-do-not-touch.tsv")
CONS, COMB = (
    "15Z00RATLJt7QcyT_-Rc6Y0jYS9WmcqUpukKp08GwAZ8",
    "1JmpP38bcOUDmKlkx_2HndB4GdncPgObC4-_vnQFNaw4",
)
OURS = ("khiem",)  # assignee prefixes that are us (Khiem, Khiem Doan, Khiem (ours))
SUBMITTED_STATUS = ("approved", "submitted", "submit for manual qc", "in review")


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


def get(tok, sid, rng):
    u = "https://sheets.googleapis.com/v4/spreadsheets/%s/values/%s" % (
        sid,
        urllib.parse.quote(rng),
    )
    req = urllib.request.Request(u, headers={"Authorization": "Bearer " + tok})
    return json.load(urllib.request.urlopen(req, timeout=60)).get("values", [])


def canon(t):
    """'SVC-12-6-0', 'SVC-PC-53-4-0\\r', ' svc-pc-1-2-0 ' -> 'SVC-PC-12-6-0'."""
    t = (t or "").strip().upper().replace("\r", "")
    if not t.startswith("SVC"):
        return None
    core = t.replace("SVC-PC-", "").replace("SVC-", "")
    # Only a bare task id. 2026-09-24: the trackers gained doc-title cells ("SVC-PC-10-1-0 - ANDREW_TEAM - DATASET
    # DESCRIPTION", "..._DATASET_DESCRIPTION.DOCX"); the old prefix test kept them, the list grew 535 -> 616, and a
    # cp1252 dash in one of them crashed svc_bundle_upload.py sweep on the sandbox.
    m = re.fullmatch(r"(\d+-\d+-\d+)", core)
    return "SVC-PC-" + m.group(1) if m else None


def canon_ekw(t):
    """'task_LGL-182', 'LGL-182 ', 'lgl-182' -> 'LGL-182'; doc titles and anything else -> None."""
    t = (t or "").strip().upper().replace("\r", "")
    if t.startswith("TASK_"):
        t = t[5:]
    return t if re.fullmatch(r"[A-Z]{2,4}-\d{2,4}", t) else None


# Workstream -> (consolidated tab, consolidated task column, Combined tab, id canonicaliser, sandbox list)
WS = {
    "svc": (
        "SVC",
        3,
        "SVC QC Tracker Combined",
        canon,
        "/root/qc/_v7/do_not_touch.txt",
    ),
    "ekw": (
        "EKW",
        4,
        "EKW QC Tracker Combined",
        canon_ekw,
        "/root/qc/_ekw/do_not_touch.txt",
    ),
}


def build(tok, ws="svc"):
    cons_tab, cons_col, comb_tab, canon, _ = WS[ws]
    reasons = {}

    def add(t, why):
        if t:
            reasons.setdefault(t, []).append(why)

    eqc_reject_ours = set()
    # Both consolidated tabs: D = Google Doc, E = task_name, G = Task Available Status, H = EQC Status.
    # 2026-09-25: this read the task from D (a doc title on most rows, so canon() dropped them) and the QC result
    # from G ("EQC ready" on every row), so a human-QC Reject never registered as one: Luiz's rejected
    # task_LGL-131 read as submitted. Task from E (D for old rows that put the id there), result from H.
    # Rows between the "Rejected" heading and the "Duplicates" heading are rejected submissions whatever H says:
    # 73-2-0 sits there with H = "Done" (QC finished, verdict reject) and is ours to rework.
    # 2026-09-27: human QC also rejects IN PLACE: H = "Done" with "Major" in K:M (Prompt ambiguity, Prompt-Tests
    # misalignment, Test coverage) and the row never moves under the Rejected heading. 92-0-0, 26-7-0, 24-6-0 and
    # 79-2-0 sat frozen that way while Combined already said "Rejected". Done + any Major is a reject.
    in_rejected = False
    for r in get(tok, CONS, "%s!A1:M3000" % cons_tab)[1:]:
        r = r + [""] * 13
        heads = [x.strip().lower() for x in r[:2]]
        if "rejected" in heads:
            in_rejected = True
            continue
        if "duplicates" in heads:
            in_rejected = False
            continue
        t = canon(r[4]) or canon(r[3])
        if t:
            eqc = "reject" if in_rejected else r[7].strip()
            if eqc.lower() == "done" and any(
                x.strip().lower() == "major" for x in r[10:13]
            ):
                eqc = "reject"
            if (
                t
                and eqc.lower() == "reject"
                and (r[1] if len(r) > 1 else "").strip().lower().startswith(OURS)
            ):
                eqc_reject_ours.add(t)
            if t and eqc.lower() != "reject":
                add(
                    t,
                    "consolidated: submitted by %s, EQC %s"
                    % ((r[1] if len(r) > 1 else "").strip() or "?", eqc or "pending"),
                )
    for r in get(tok, COMB, "'%s'!A1:C3000" % comb_tab):
        if not r:
            continue
        t = canon(r[0])
        if not t:
            continue
        who = (r[1] if len(r) > 1 else "").strip()
        st = (r[2] if len(r) > 2 else "").strip()
        if any(st.lower().startswith(s) for s in SUBMITTED_STATUS):
            # Our own "Submitted..." row whose consolidated EQC result is Reject is stale in Combined: the task
            # came back rejected and is ours to fix (11-4-0, 73-2-0 on 2026-09-22). "Approved" always freezes.
            if (
                who.lower().startswith(OURS)
                and t in eqc_reject_ours
                and t not in reasons
                and not st.lower().startswith("approved")
            ):
                continue
            add(t, "combined: %s (%s)" % (st, who or "unassigned"))
        elif who and not who.lower().startswith(OURS):
            add(t, "combined: owned by %s (%s)" % (who, st or "no status"))
        elif not who:
            # 2026-09-25 (owner): lanes work only what we are signed up for. An unassigned / "Available - claim me"
            # row can be claimed by a person at any time, and 6 tasks our lanes held went to others that way on
            # 22-23 Sep after our own 21 Sep rebalance released them. Claim it on the tracker first, then work it.
            add(t, "combined: not assigned to us (%s)" % (st or "no status"))
    return reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--check", nargs="*", default=[])
    ap.add_argument("--ws", choices=["svc", "ekw", "both"], default="both")
    a = ap.parse_args()
    tok = token()
    for ws in (["svc", "ekw"] if a.ws == "both" else [a.ws]):
        reasons = build(tok, ws)
        out = (
            OUT if ws == "svc" else OUT.replace("svc-do-not-touch", "ekw-do-not-touch")
        )
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write("# built by tools/svc_build_freeze.py; task<TAB>reasons\n")
            for t in sorted(reasons):
                f.write("%s\t%s\n" % (t, "; ".join(reasons[t])))
        sub = sum(
            1
            for v in reasons.values()
            if any("submitted" in x or "Approved" in x or "EQC" in x for x in v)
        )
        print(
            "%s do-not-touch: %d tasks (%d submitted/finished, rest owned by others or unassigned) -> %s"
            % (ws.upper(), len(reasons), sub, out)
        )
        for t in a.check:
            c = WS[ws][3](t)
            if c:
                print("  %s: %s" % (c, "; ".join(reasons.get(c, ["free to work"]))))
        if not a.push:
            continue
        # A failed or partial tracker read must never shrink the list: refuse a push under 50% of the live one.
        dst = WS[ws][4]
        ssh = [
            "ssh",
            "-p",
            "2222",
            "-i",
            os.path.expanduser("~/.ssh/kiem_sandbox"),
            "kiem-sandbox",
        ]
        live = subprocess.run(
            ssh + ["grep -c . %s 2>/dev/null || echo 0" % dst],
            capture_output=True,
            text=True,
        )
        n_live = int((live.stdout.strip().splitlines() or ["0"])[-1] or 0)
        if n_live and len(reasons) < n_live // 2:
            print(
                "  REFUSED push: %d ids vs %d live (tracker read looks partial)"
                % (len(reasons), n_live)
            )
            continue
        tmp = out + ".tasks"
        open(tmp, "w", encoding="utf-8", newline="\n").write(
            "\n".join(sorted(reasons)) + "\n"
        )
        subprocess.run(
            [
                "scp",
                "-P",
                "2222",
                "-i",
                os.path.expanduser("~/.ssh/kiem_sandbox"),
                tmp,
                "kiem-sandbox:" + dst,
            ],
            check=True,
        )
        os.remove(tmp)
        # Tasks our queue still holds that are now off-limits: these are the duplication risks to stop.
        q = subprocess.run(
            ssh
            + [
                "tr -d '\r' < %s/queue.txt | grep -v '^#' | grep ."
                % os.path.dirname(dst)
            ],
            capture_output=True,
            text=True,
        ).stdout.split()
        hit = sorted(set(q) & set(reasons))
        print(
            "pushed",
            len(reasons),
            "task ids ->",
            dst,
            "| queued tasks now off-limits:",
            hit or "none",
        )


if __name__ == "__main__":
    main()
