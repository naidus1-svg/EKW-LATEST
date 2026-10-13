#!/usr/bin/env python3
"""Send SVC or EKW tasks that PASSED DataOS but were then REJECTED by a human review (TFRL manual QC, or our own
internal zero-pass review) back to the lanes. Sandbox, stdlib only. Dry run by default; --apply to write.

svc_record_return.py / ekw_record_return.py handle DataOS rejects; nothing handled a later human reject, so a task that
passed DataOS stayed on accepted.txt (never re-touched, never re-shipped). 2026-09-27: 92-0-0, 26-7-0, 24-6-0,
79-2-0, then 49-8-0, 67-2-0, 93-5-0, 11-4-0, 72-3-0 and EKW LGL-140. For each task this does what the return tool
does for a DataOS reject, plus un-freezing:

  0. refuse unless: the task is on accepted.txt, NOT on do_not_touch.txt (run `svc_build_freeze.py --push` first;
     it releases our own consolidated rows with EQC "Done" + a Major rating), and an owner note carrying the
     verdict exists (svc: _deepbriefs/_owner_notes/<task>.md, appended to every fix prompt by the runner;
     ekw: _ekw/briefs/_owner_notes/<task>.md, seeded into the brief and the NOT-READY verify record);
  1. write the lastreject.sha = the tests/ fingerprint of the SHIPPED zip, so Gate 5 refuses a resubmission whose
     rubric did not change;
  2. archive the verify/regrade/gate records and the ready zip + manifest (the old PASS must not carry forward);
  3. ekw only: write briefs/<task>.md and seed verify/<task>.verify.md with the owner note ending
     "VERDICT: NOT-READY" (the EKW runner starts in fix mode from that record), and drop it from decide.txt;
  4. remove the task from accepted.txt (backup first), release its claim, put it at the head of queue.txt below any
     comment lines.
Read back after writing.

Usage: python3 tools/svc_requeue_qc_reject.py [--ws svc|ekw] TASK [...] [--apply]
"""

import argparse, os, shutil, sys, tempfile, time, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import svc_build_upload_zip as bz  # noqa: E402

QC = os.environ.get("SVC_QC_ROOT", "/root/qc")
WS = {
    "svc": dict(
        W=QC + "/_v7",
        LR=QC + "/_deepfix",
        NOTES=QC + "/_deepbriefs/_owner_notes",
        ARCH=QC + "/_deepfix",
        RECS=[QC + "/_deepfix/{t}.verify.md", QC + "/_deepfix/{t}.regrade.json"],
    ),
    "ekw": dict(
        W=QC + "/_ekw",
        LR=QC + "/_ekw/lastreject",
        NOTES=QC + "/_ekw/briefs/_owner_notes",
        ARCH=QC + "/_ekw/verify",
        RECS=[QC + "/_ekw/verify/{t}.verify.md", QC + "/_ekw/gate/{t}.gate.json"],
    ),
}
EKW_HEADER = """You are fixing EKW task {t}. It PASSED DataOS, then a later human review REJECTED it. The OWNER DECISION
below carries that verdict verbatim and says how to close each point; it is the target for this round.

=== OWNER DECISION (binding; overrides any finding it conflicts with) ===
"""


def lines(p):
    return [ln.strip() for ln in open(p) if ln.strip()] if os.path.isfile(p) else []


def shipped_tests_hash(zp, task):
    with tempfile.TemporaryDirectory() as d:
        with zipfile.ZipFile(zp) as z:
            assert z.testzip() is None, "ready zip is corrupt: " + zp
            z.extractall(d)
        return bz.tests_hash(os.path.join(d, task))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks", nargs="+")
    ap.add_argument("--ws", choices=sorted(WS), default="svc")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    P = WS[a.ws]
    W, LR, NOTES = P["W"], P["LR"], P["NOTES"]
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    acc = lines(W + "/accepted.txt")
    dnt = set(lines(W + "/do_not_touch.txt"))
    ok, shas = [], {}
    for t in a.tasks:
        why = []
        if t not in acc:
            why.append("not on accepted.txt")
        if t in dnt:
            why.append("on do_not_touch.txt (run svc_build_freeze.py --push first)")
        if not os.path.isfile(os.path.join(NOTES, t + ".md")):
            why.append("no owner note at %s/%s.md" % (NOTES, t))
        zp = os.path.join(W, "ready", t + ".zip")
        if not why:
            shas[t] = shipped_tests_hash(zp, t) if os.path.isfile(zp) else None
        msg = (
            ("REFUSED: " + "; ".join(why))
            if why
            else (
                "requeue (shipped tests sha %s)"
                % ((shas[t] or "none, no ready zip")[:12])
            )
        )
        print("  %-16s %s" % (t, msg))
        if not why:
            ok.append(t)
    if not a.apply:
        print("\nDRY RUN. Re-run with --apply to write.")
        return 1 if len(ok) < len(a.tasks) else 0
    if not ok:
        return 1
    arch_rec = os.path.join(P["ARCH"], "_pre_manualqc_" + ts)
    arch_rd = os.path.join(W, "ready", "_manualqc_reject_" + ts)
    for d in (arch_rec, arch_rd, LR):
        os.makedirs(d, exist_ok=True)
    for t in ok:
        if shas[t]:
            open(os.path.join(LR, t + ".lastreject.sha"), "w").write(shas[t] + "\n")
        for pat in P["RECS"]:
            p = pat.format(t=t)
            if os.path.exists(p):
                shutil.move(p, os.path.join(arch_rec, os.path.basename(p)))
        for p in (
            os.path.join(W, "ready", t + ".zip"),
            os.path.join(W, "ready", t + ".zip.manifest.json"),
        ):
            if os.path.exists(p):
                shutil.move(p, os.path.join(arch_rd, os.path.basename(p)))
        if a.ws == "ekw":
            note = open(os.path.join(NOTES, t + ".md"), encoding="utf-8").read().strip()
            brief = EKW_HEADER.format(
                t=t
            ) + note + "\n\nVERDICT: NOT-READY (human review rejected %s after its DataOS " "pass; close every point above)\nMETHOD_VERSION: manual-qc-reject/%s\n" % (
                t,
                ts,
            )
            for d, name in (("briefs", t + ".md"), ("verify", t + ".verify.md")):
                os.makedirs(os.path.join(W, d), exist_ok=True)
                open(
                    os.path.join(W, d, name), "w", encoding="utf-8", newline="\n"
                ).write(brief)
        shutil.rmtree(os.path.join(W, "claims", t), ignore_errors=True)
    dec = W + "/decide.txt"
    if a.ws == "ekw" and os.path.isfile(dec):
        keep = [ln for ln in open(dec) if ln.strip() not in ok]
        if len(keep) != len(open(dec).readlines()):
            shutil.copy(dec, dec + ".bak." + ts)
            open(dec, "w").write("".join(keep))
    shutil.copy(W + "/accepted.txt", W + "/accepted.txt.bak." + ts)
    keep = [ln for ln in open(W + "/accepted.txt") if ln.strip() not in ok]
    open(W + "/accepted.txt", "w").write("".join(keep))
    q = W + "/queue.txt"
    if os.path.isfile(q):
        shutil.copy(q, q + ".bak." + ts)
    old = [ln.rstrip("\n") for ln in open(q)] if os.path.isfile(q) else []
    comments = [ln for ln in old if ln.strip().startswith("#")]
    rest = [
        ln
        for ln in old
        if ln.strip() and not ln.strip().startswith("#") and ln.strip() not in ok
    ]
    open(q, "w").write("\n".join(comments + ok + rest) + "\n")
    # read back
    acc_now = set(lines(W + "/accepted.txt"))
    q_now = [ln for ln in lines(q) if not ln.startswith("#")]
    assert not (acc_now & set(ok)), "accepted.txt readback failed"
    assert q_now[: len(ok)] == ok, "queue readback failed"
    assert all(
        not os.path.exists(os.path.join(W, "ready", t + ".zip")) for t in ok
    ), "ready zip still present"
    assert all(
        not os.path.exists(os.path.join(W, "claims", t)) for t in ok
    ), "claim still held"
    assert all(
        open(os.path.join(LR, t + ".lastreject.sha")).read().strip() == shas[t]
        for t in ok
        if shas[t]
    )
    if a.ws == "ekw":
        assert all(
            "VERDICT: NOT-READY"
            in open(os.path.join(W, "verify", t + ".verify.md")).read()
            for t in ok
        )
    print(
        "\nAPPLIED + read back: %d un-frozen and requeued at the head of %s; archive %s"
        % (len(ok), q, arch_rd)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
