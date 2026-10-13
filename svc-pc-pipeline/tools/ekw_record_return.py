#!/usr/bin/env python3
"""Intake one EKW DataOS `*_with_runs*.zip` return on the sandbox. The EKW twin of svc_record_return.py: the
same pass rule, the same fingerprint, the same archive-and-requeue shape, pointed at the EKW lane work dir
(/root/qc/_ekw). Stdlib only. Dry run by default; --apply writes and reads back.

Pass rule (NOT re-derived here): each comprehensive review is parsed by svc_dataos_returns_parse.review_summary
and the verdict is svc_record_return.verdicts()'s rule: a review with 0 MAJOR checks passes, a task passes when
>= 2 reviews and EVERY review (read or not) is read at 0 majors. The SVC parser only enumerates SVC-PC-* roots, so this tool enumerates EKW roots
(LGL-131, SCO-198) itself and hands every review .md to the same review_summary. test_ekw_record_return.py
proves the two give identical verdicts on the same reviews.

For every task in the return:
  PASS   -> append to <work>/accepted.txt (the freeze list the runner's freeze_check and ekw_bundle_upload.py
            both honour). The claim is KEPT, so ekw_v1_claim.sh never hands the task to a lane again.
  REJECT -> 1. <work>/lastreject/<task>.lastreject.sha = svc_record_return.tests_hash_from_zip over the graded
               task_files/tests/ (the fingerprint of the bytes DataOS actually graded);
            2. archive <work>/verify/<task>.verify.md and <work>/gate/<task>.gate.json to
               <work>/verify/_pre_<return>/, and <work>/ready/<task>.zip + .manifest.json to
               <work>/ready/_returned_<return>/ (a READY made before the return never carries into the next round);
            3. write the directed brief <work>/briefs/<task>.md: every major + moderate finding for the task
               across every EKW return recorded so far, both reviewer seats, full text;
            4. seed <work>/verify/<task>.verify.md with that brief, ending "VERDICT: NOT-READY". The lane runner
               starts in fix mode from a NOT-READY verify record and feeds it to the fix step as FINDINGS, so this
               is where the brief lands without a runner change. The runner's own adversarial verify overwrites
               the record before any zip is built;
            5. drop it from <work>/decide.txt (a new DataOS round is new evidence, not the old stuck blocker);
            6. release <work>/claims/<task> and put it at the head of <work>/queue.txt (comment lines stay on top).
  A reject on do_not_touch.txt is recorded but not requeued. A task with zero parsed reviews was never graded
  (DataOS exception): it goes to <work>/needs_regrade.txt, not the queue. A task a lane runner is working on
  right now is refused and left alone.
Also copies the return zip into <returns-dir> (verified byte for byte) and appends one line per task to
<work>/returns_recorded.tsv. A (return sha256, task) pair already in that ledger is skipped, so re-running the
same return changes nothing (it never releases a claim a lane has since taken).

Nothing here uploads, writes to Drive/Sheets, or sends messages.

Usage: python3 tools/ekw_record_return.py /root/qc/_returns/<name>_with_runs.zip [--apply]
"""

import argparse
import hashlib
import os
import re
import shutil
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import svc_dataos_returns_parse as rp  # noqa: E402  (review parsing)
import svc_record_return as srr  # noqa: E402  (tests/ fingerprint)
import svc_ship_manifest as sm  # noqa: E402  (accepted_set, file_sha)
import ekw_bundle_upload as ebu  # noqa: E402  (TASK_RE, live_runner)

QC = "/root/qc"
WORK = QC + "/_ekw"
RETURNS = QC + "/_returns"
LEDGER = "returns_recorded.tsv"


def task_roots(names, task_re=ebu.TASK_RE):
    return sorted({n.split("/")[0] for n in names if task_re.match(n.split("/")[0])})


def reviews_by_task(z, task_re=ebu.TASK_RE):
    """{task: [review_summary, ...]} exactly as svc_dataos_returns_parse.main collects rec['reviews']:
    every verifications/*.md under the task root whose file name does not start with qc_.
    """
    names = z.namelist()
    out = {}
    for t in task_roots(names, task_re):
        revs = []
        for n in names:
            if n.startswith(t + "/") and "/verifications/" in n and n.endswith(".md"):
                s = rp.review_summary(z.read(n).decode("utf-8", "replace"))
                s["file"] = n.split("/")[-1]
                if not s["file"].startswith("qc_"):
                    revs.append(s)
        out[t] = revs
    return out


def verdicts_from_reviews(by_task):
    """svc_record_return.verdicts()'s rule, applied to the same review_summary records."""
    res = {}
    for t, reviews in by_task.items():
        revs = [r for r in reviews if r.get("parsed")]
        passes = sum(1 for r in revs if r.get("major_count") == 0)
        ok = len(reviews) >= 2 and passes == len(reviews)
        res[t] = ("PASS" if ok else "FAIL", passes, len(revs))
    return res


def findings_by_task(zip_path, tasks):
    """{task: [(round label, seat, verdict, [(cid, sev, name, why, fix)])]}, majors + moderates at full text,
    from the comprehensive reviews (the same selection svc_build_directed_briefs.py makes).
    """
    zn = os.path.basename(zip_path).replace("_with_runs", "").replace(".zip", "")
    per = {}
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            t = n.split("/")[0]
            if (
                t not in tasks
                or "/verifications/comprehensive_review_" not in n
                or not n.endswith(".md")
            ):
                continue
            d = rp.last_verdict_json(z.read(n).decode("utf-8", "replace"))
            if not d:
                continue
            m = re.search(r"___(.+)\.md$", n)
            seat = m.group(1) if m else "?"
            parts = n.split("/")
            rnd = zn + ("/" + parts[1] if len(parts) > 2 else "")
            fs = []
            for c in d.get("checks", []):
                sev = str(c.get("severity", "")).lower()
                if sev not in ("major", "moderate"):
                    continue
                fs.append(
                    (
                        str(c.get("check") or c.get("check_id") or c.get("id") or "?"),
                        sev,
                        (c.get("name") or "").strip(),
                        (c.get("justification") or c.get("reason") or "").strip(),
                        (c.get("suggested_fix") or "").strip(),
                    )
                )
            if fs:
                per.setdefault(t, []).append(
                    (rnd, seat, str(d.get("overall_verdict")), fs)
                )
    return per


HEADER = """DataOS REJECTED EKW task {T} (return {R}: {P} of {N} comprehensive reviews at 0 majors; a pass needs 2).
This is a directed rebuild from DataOS's own findings. GPT re-audits the WHOLE task every round, so close EVERY
finding below (every numbered sub-point inside each one), then audit every criterion, not only the cited ones.

WHERE DataOS's WORDS POINT IN THE AUTHORING SOURCE (edit only the source; the package is regenerated from it):
  instruction.md / tests/task_prompt.txt   -> prompt.txt
  tests/deliverables*/judge.toml criteria  -> verifier.json verifiers (one criterion = one verifier entry)
  solution/files/ (the golden)             -> expert_solution/
  environment/initial_workspace/           -> source_documents/ (evidence: never edit)

METHOD:
1. Re-derive every graded fact from source_documents/; if the golden disagrees with the sources, fix the golden.
2. Per finding, match the fix to the category: over-enforcement (1.4) -> loosen or delete the criterion;
   coverage hole (1.5) -> add one criterion enforcing the uncovered prompt requirement against your re-derived
   value; compound criterion -> split into one-fact criteria keeping the total weight; golden wrong (1.1) ->
   fix the golden; ambiguity (1.3) -> edit prompt.txt; answer leak (1.6) -> no expected value in prompt.txt;
   consistency (1.7) -> fix the mismatched figure; packaging (1.8) -> <=15 criteria per graded file.
3. FULL RUBRIC AUDIT: go verifier by verifier through verifier.json against prompt.txt and report a table
   (verifier | what it grades | prompt line | aligned / over-enforces / under-covers / unscoped | action).
4. Weights still sum to 1.0; the golden must still satisfy every criterion.
In your final report, list each finding below and name the verifier that now closes it.
"""


def build_brief(task, rounds, res_row, ret_name, owner_note):
    blocks = []
    for rnd, seat, verdict, fs in rounds:
        lines = ["--- round: %s | seat: %s | verdict: %s ---" % (rnd, seat, verdict)]
        for cid, sev, name, why, fix in fs:
            lines.append("[%s | %s] %s" % (cid, sev, name))
            if why:
                lines.append("  WHY: " + why)
            if fix:
                lines.append("  FIX: " + fix)
        blocks.append("\n".join(lines))
    if not blocks:
        blocks.append(
            "(the reviews carried no major or moderate check the parser could read; open the return's "
            "verifications/ for %s and audit every criterion)" % task
        )
    owner = ""
    if owner_note:
        owner = (
            "=== OWNER DECISION (binding; overrides any finding it conflicts with) ===\n"
            + owner_note.strip()
            + "\n\n"
        )
    return (
        HEADER.format(T=task, R=ret_name, P=res_row[1], N=res_row[2])
        + "\n"
        + owner
        + "=== COMPLETE DataOS finding ledger for %s (every EKW round, both seats, majors + moderates) ===\n\n"
        % task
        + "\n\n".join(blocks)
        + "\n\nVERDICT: NOT-READY (DataOS rejected %s in %s; close every finding above)\n"
        % (task, ret_name)
        + "METHOD_VERSION: dataos-return/%s\n" % ret_name
    )


def read_ledger(path):
    rows = []
    if os.path.isfile(path):
        for ln in open(path, encoding="utf-8"):
            c = ln.rstrip("\n").split("\t")
            if len(c) >= 5 and not ln.startswith("#"):
                rows.append(c)
    return rows


def lines_of(path):
    return [ln.strip() for ln in open(path)] if os.path.isfile(path) else []


def svc_rule_equivalence(zp):
    """Read-only proof that this tool's rule IS svc_record_return's: run both over the same real SVC return
    (svc_record_return.verdicts shells out to the SVC parser) and compare task for task. Exit 0 = identical.
    """
    svc = srr.verdicts(zp)
    with zipfile.ZipFile(zp) as z:
        mine = verdicts_from_reviews(
            reviews_by_task(z, re.compile(r"^SVC-PC-\d+-\d+-\d+$"))
        )
    diff = {
        t: (svc.get(t), mine.get(t))
        for t in set(svc) | set(mine)
        if svc.get(t) != mine.get(t)
    }
    print(
        "rule equivalence on %s: %d tasks (svc_record_return) vs %d (this tool), %d PASS, %d FAIL, %d differ %s"
        % (
            os.path.basename(zp),
            len(svc),
            len(mine),
            sum(v[0] == "PASS" for v in svc.values()),
            sum(v[0] != "PASS" for v in svc.values()),
            len(diff),
            diff or "",
        )
    )
    return 0 if svc and not diff else 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("zip")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--work", default=WORK)
    ap.add_argument("--returns-dir", default=RETURNS)
    ap.add_argument(
        "--svc-rule-equivalence",
        action="store_true",
        help="read-only: treat ZIP as an SVC return and compare this tool's verdicts with svc_record_return's",
    )
    a = ap.parse_args(argv)
    if a.svc_rule_equivalence:
        return svc_rule_equivalence(a.zip)
    W = a.work
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    name = os.path.basename(a.zip)
    base = name.replace(".zip", "")
    ret_sha = sm.file_sha(a.zip)
    if not ret_sha:
        print("no such file:", a.zip)
        return 2

    dest = os.path.join(a.returns_dir, name)
    copy_needed = os.path.realpath(a.zip) != os.path.realpath(dest)
    if copy_needed:
        print("copy return ->", dest)
    with zipfile.ZipFile(a.zip) as z:
        assert z.testzip() is None, "return zip is corrupt"
        res = verdicts_from_reviews(reviews_by_task(z))
        shas = {t: srr.tests_hash_from_zip(z, t) for t in res}
        ungraded = srr.ungraded_evals_from_zip(z, res)
    if not res:
        print(
            "%s: no EKW task roots (like LGL-131) in this zip; nothing to record" % name
        )
        return 1

    ledger_p = os.path.join(W, LEDGER)
    ledger = read_ledger(ledger_p)
    done = {(r[0], r[3]) for r in ledger}
    already = sorted(t for t in res if (ret_sha, t) in done)
    accepted = sm.accepted_set(os.path.join(W, "accepted.txt"))
    passes = sorted(t for t, r in res.items() if r[0] == "PASS")
    all_rejects = sorted(t for t, r in res.items() if r[0] != "PASS")
    unreviewed = [t for t in all_rejects if res[t][2] == 0 and t not in accepted]
    skipped = [t for t in all_rejects if t in accepted]
    rejects = [t for t in all_rejects if t not in accepted and t not in unreviewed]
    live = [t for t in rejects if t not in already and ebu.live_runner(t)]
    # Near-misses first (2026-09-26, owner): a reject where one DataOS seat already returned 0 majors is one seat
    # from passing, so it goes to the very head of the queue ahead of 0-of-2 rejects (same rule as
    # svc_triage_queue.py's clean-seats key). Ties keep task order.
    act_rejects = sorted(
        (t for t in rejects if t not in already and t not in live),
        key=lambda t: (-res[t][1], t),
    )
    act_unrev = [t for t in unreviewed if t not in already]

    print(
        "%s: %d tasks, %d PASS, %d FAIL (%d to requeue, %d do-not-touch, %d never graded)"
        % (
            name,
            len(res),
            len(passes),
            len(all_rejects),
            len(rejects),
            len(skipped),
            len(unreviewed),
        )
    )
    for t in sorted(res):
        print(
            "  %-10s %s (%d of %d reviews at 0 majors)"
            % (t, res[t][0], res[t][1], res[t][2])
        )
    for t in passes:
        total, u = ungraded.get(t, (0, []))
        if u:
            print(srr.format_ungraded_warning(t, total, u))
    for t in all_rejects:
        total, u = ungraded.get(t, (0, []))
        if u:
            print(srr.format_ungraded_note(t, total, u))
    if already:
        print(
            "already recorded from this exact return (skipped, no change): %s" % already
        )
    if skipped:
        print("rejects NOT requeued (accepted / do-not-touch): %s" % skipped)
    if unreviewed:
        print(
            "NO REVIEWS (DataOS exception) -> needs_regrade.txt, not requeued: %s"
            % unreviewed
        )
    if live:
        print(
            "REFUSED (a lane runner is working on it right now; re-run later): %s"
            % live
        )

    new_acc = [t for t in passes if t not in accepted]
    print("\naccepted.txt += %s" % (new_acc or "nothing new"))

    # Brief sources: every EKW return already in the ledger, then this one (oldest round first).
    srcs = []
    for r in ledger:
        p = r[2]
        if p not in srcs and os.path.isfile(p) and sm.file_sha(p) != ret_sha:
            srcs.append(p)
    srcs.append(a.zip)
    per = {}
    for p in srcs:
        for t, rounds in findings_by_task(p, set(act_rejects)).items():
            per.setdefault(t, []).extend(rounds)
    briefs = {}
    for t in act_rejects:
        note_p = os.path.join(W, "briefs", "_owner_notes", t + ".md")
        note = open(note_p, encoding="utf-8").read() if os.path.isfile(note_p) else ""
        briefs[t] = build_brief(t, per.get(t, []), res[t], base, note)
        print(
            "reject %s: lastreject.sha=%s, archive records + ready zip, brief %d rounds / %d findings / %d chars, "
            "seed verify record, release claim, requeue at head"
            % (
                t,
                (shas[t] or "NONE")[:12],
                len(per.get(t, [])),
                sum(len(x[3]) for x in per.get(t, [])),
                len(briefs[t]),
            )
        )
    if not a.apply:
        print("\nDRY RUN. Re-run with --apply to write.")
        return 0

    # ---- apply ----
    if copy_needed:
        os.makedirs(a.returns_dir, exist_ok=True)
        if not os.path.isfile(dest) or sm.file_sha(dest) != ret_sha:
            shutil.copy2(a.zip, dest)
        assert sm.file_sha(dest) == ret_sha, "copy mismatch"
    acc_p = os.path.join(W, "accepted.txt")
    if new_acc:
        if os.path.isfile(acc_p):
            shutil.copy(acc_p, acc_p + ".bak." + ts)
        with open(acc_p, "a") as f:
            f.write("".join(t + "\n" for t in new_acc))
    if act_unrev:
        nr = os.path.join(W, "needs_regrade.txt")
        have = set(open(nr).read().split()) if os.path.exists(nr) else set()
        with open(nr, "a") as f:
            f.write("".join(t + "\n" for t in act_unrev if t not in have))
    # 2026-09-29: a task graded by this return (pass or reject) is no longer never-graded; drop it from
    # needs_regrade.txt so ekw_bundle_upload.py stops treating its bytes as a first grade.
    graded = set(new_acc) | set(act_rejects)
    nr = os.path.join(W, "needs_regrade.txt")
    if graded and os.path.exists(nr):
        lines_nr = open(nr).read().splitlines()
        keep = [ln for ln in lines_nr if ln.strip() not in graded]
        if len(keep) != len(lines_nr):
            shutil.copy(nr, nr + ".bak." + ts)
            with open(nr, "w") as f:
                f.write("".join(ln + "\n" for ln in keep))
    arch_v = os.path.join(W, "verify", "_pre_" + base)
    arch_r = os.path.join(W, "ready", "_returned_" + base)
    for d in ("lastreject", "briefs", "verify", "ready", "claims"):
        os.makedirs(os.path.join(W, d), exist_ok=True)
    for t in act_rejects:
        if shas[t]:
            with open(os.path.join(W, "lastreject", t + ".lastreject.sha"), "w") as f:
                f.write(shas[t] + "\n")
        for p in (
            os.path.join(W, "verify", t + ".verify.md"),
            os.path.join(W, "gate", t + ".gate.json"),
        ):
            if os.path.exists(p):
                os.makedirs(arch_v, exist_ok=True)
                shutil.move(p, os.path.join(arch_v, os.path.basename(p)))
        for p in (
            os.path.join(W, "ready", t + ".zip"),
            os.path.join(W, "ready", t + ".zip.manifest.json"),
        ):
            if os.path.exists(p):
                os.makedirs(arch_r, exist_ok=True)
                shutil.move(p, os.path.join(arch_r, os.path.basename(p)))
        for p in (
            os.path.join(W, "briefs", t + ".md"),
            os.path.join(W, "verify", t + ".verify.md"),
        ):
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(briefs[t])
        shutil.rmtree(os.path.join(W, "claims", t), ignore_errors=True)
    dec = os.path.join(W, "decide.txt")
    if act_rejects and os.path.isfile(dec):
        keep = [ln for ln in lines_of(dec) if ln and ln not in act_rejects]
        if len(keep) != len([ln for ln in lines_of(dec) if ln]):
            shutil.copy(dec, dec + ".bak." + ts)
            open(dec, "w").write("".join(ln + "\n" for ln in keep))
    q = os.path.join(W, "queue.txt")
    old = lines_of(q)
    comments = [ln for ln in old if ln.startswith("#")]
    rest = [
        ln
        for ln in old
        if ln and not ln.startswith("#") and ln not in act_rejects and ln not in passes
    ]
    new_q = comments + act_rejects + rest
    if new_q != [ln for ln in old if ln]:
        if os.path.isfile(q):
            shutil.copy(q, q + ".bak." + ts)
        open(q, "w").write("\n".join(new_q) + "\n")
    rows = [t for t in sorted(res) if t not in already and t not in live]
    if rows:
        new_ledger = not os.path.isfile(ledger_p)
        with open(ledger_p, "a", encoding="utf-8") as f:
            if new_ledger:
                f.write(
                    "# return_sha256\treturn_name\treturn_path\ttask\tverdict\trecorded_at\n"
                )
            for t in rows:
                f.write(
                    "%s\t%s\t%s\t%s\t%s\t%s\n"
                    % (
                        ret_sha,
                        name,
                        dest if copy_needed else os.path.realpath(a.zip),
                        t,
                        res[t][0],
                        ts,
                    )
                )

    # ---- read back ----
    acc_now = sm.accepted_set(acc_p)
    assert all(t in acc_now for t in passes), "accepted.txt readback failed"
    for t in act_rejects:
        if shas[t]:
            got = (
                open(os.path.join(W, "lastreject", t + ".lastreject.sha"))
                .read()
                .strip()
            )
            assert got == shas[t], "lastreject readback failed for " + t
        assert not os.path.exists(os.path.join(W, "claims", t)), (
            "claim still held: " + t
        )
        assert not os.path.exists(os.path.join(W, "ready", t + ".zip")), (
            "ready zip still live: " + t
        )
        for p in (
            os.path.join(W, "briefs", t + ".md"),
            os.path.join(W, "verify", t + ".verify.md"),
        ):
            txt = open(p, encoding="utf-8").read()
            assert txt == briefs[t] and re.search(r"VERDICT: *NOT-READY", txt, re.I), (
                "brief readback failed: " + p
            )
    qn = [ln for ln in lines_of(q) if ln and not ln.startswith("#")]
    assert qn[: len(act_rejects)] == act_rejects, "queue head readback failed"
    assert not set(act_rejects) & set(lines_of(dec)), "decide.txt readback failed"
    led = {(r[0], r[3]) for r in read_ledger(ledger_p)}
    assert all((ret_sha, t) in led for t in rows), "ledger readback failed"
    print(
        "\nAPPLIED + read back: %d newly frozen, %d requeued at the head of %s, %d briefs in %s"
        % (
            len(new_acc),
            len(act_rejects),
            q,
            len(act_rejects),
            os.path.join(W, "briefs"),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
