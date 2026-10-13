#!/usr/bin/env python3
"""Intake one DataOS `*_with_runs*.zip` return on the sandbox: the steps that were done by hand on 2026-09-22
and must never depend on someone remembering them. Stdlib only. Dry run by default; --apply to write.

For every task in the return (pass rule = svc_dataos_returns_parse.py's: a review with 0 MAJOR checks passes,
a task passes only when it has >= 2 reviews and EVERY review (read or not) is read at 0 majors):
  PASS   -> append to _v7/accepted.txt (the freeze list: never re-touched, never re-shipped).
  REJECT -> 1. write _deepfix/<task>.lastreject.sha = the tests/ fingerprint of the bytes DataOS actually
               graded, read from the return's own task_files/ (so Gate 5 refuses resubmitting them unchanged;
               until 2026-09-22 nothing wrote this file and Gate 5 could never fire);
            2. archive the task's verify/regrade records and its _v7/ready zip + manifest (a READY/PASS made
               before the return must not carry into the next round - the stale-zip hole);
            3. release its pool claim and put it at the head of _v7/queue.txt for the next v8 round.
Also copies the return zip into _returns/ (the runner's eval-regrade baseline) if it is not already there,
and verifies the copy byte-for-byte.

After this, on the laptop: `python tools/svc_harvest_all_returns.py --briefs` then
`python tools/svc_build_directed_briefs.py <rejects>` and push _deepbriefs/ (the runner needs the new round's
findings in the brief). Runbook: ekw/svc-return-runbook-2026-09-21.md, section "Return intake".

Usage: python3 tools/svc_record_return.py /root/qc/_returns/<name>_with_runs.zip [--apply]
"""

import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile, time, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import svc_ship_manifest as sm  # noqa: E402

QC = "/root/qc"
W = QC + "/_v7"
DF = QC + "/_deepfix"


def tests_hash_from_zip(z, task):
    """Same fingerprint as svc_build_upload_zip.tests_hash, computed over the graded task_files/tests/."""
    prefix = None
    for n in z.namelist():
        if n.startswith(task + "/") and "/task_files/tests/" in n:
            prefix = n[: n.index("/task_files/") + len("/task_files/")]
            break
    if prefix is None:
        return None
    files = sorted(
        n
        for n in z.namelist()
        if n.startswith(prefix + "tests/")
        and not n.endswith("/")
        and not sm.is_junk(os.path.basename(n))
        and "__pycache__" not in n
    )
    h = hashlib.sha256()
    for n in files:
        h.update(n[len(prefix) :].encode())
        h.update(z.read(n))
    return h.hexdigest()


# DataOS's harness writes this line when rewardkit exits 1 and never produces a reward.json, so the
# reward the return ships (0.0) is a fallback, not a grade. Seen in every real return checked so far
# only in runtime.log, never in test-stdout.txt, but both are read: rewardkit also exits 1 on a real
# task defect (for example "compiled grammar is too large"), so this marker is reported, never used to
# tell an infrastructure failure apart from a task one -- the cause line is printed instead of a label.
UNGRADED_MARKER = "wrote no reward.json"

EVAL_DIR_RE = re.compile(r"^eval_(\d+)__attempt_\d+__(.+)$")
REV_DIR_RE = re.compile(r"^rev_\d+__(.+)$")


def _last_error_line(text, maxlen=160):
    """Last non-blank line matching Error/Exception in `text`, trimmed. This is the cause DataOS's
    judge failed with; it is printed as-is, never classified as infra vs task defect."""
    for ln in reversed([ln for ln in text.splitlines() if ln.strip()]):
        if re.search(r"Error|Exception", ln):
            return ln.strip()[:maxlen]
    return None


def ungraded_evals_from_zip(z, tasks):
    """{task: (total_evals, [(revid, agent, evalid, cause), ...])} for every task in `tasks` that has
    at least one evaluations/eval_*/eval_files/verifier/ dir in the zip. The list holds only the
    evaluations that carry UNGRADED_MARKER (did not grade); a task present with an empty list graded
    every evaluation found. Revisions are pooled the same way reviews already are elsewhere in this
    file, so `total_evals` counts every evaluation for the task across every revision in the zip.
    """
    names = z.namelist()
    task_set = set(tasks)
    per_task = {}
    for n in names:
        top, sep, rest = n.partition("/")
        if not sep or top not in task_set:
            continue
        parts = rest.split("/")
        if (
            len(parts) != 6
            or parts[1] != "evaluations"
            or parts[3] != "eval_files"
            or parts[4] != "verifier"
            or parts[5] not in ("test-stdout.txt", "runtime.log")
        ):
            continue
        eval_m = EVAL_DIR_RE.match(parts[2])
        if not eval_m:
            continue
        rev_m = REV_DIR_RE.match(parts[0])
        revid = rev_m.group(1) if rev_m else parts[0]
        evalid, agent = eval_m.group(1), eval_m.group(2)
        per_task.setdefault(top, {}).setdefault((revid, evalid, agent), {})[
            parts[5]
        ] = n
    out = {}
    for t, evals in per_task.items():
        ungraded = []
        for (revid, evalid, agent), files in sorted(evals.items()):
            texts = {
                fn: z.read(entry).decode("utf-8", "replace")
                for fn, entry in files.items()
            }
            marked_in = next(
                (
                    fn
                    for fn in ("runtime.log", "test-stdout.txt")
                    if UNGRADED_MARKER in texts.get(fn, "")
                ),
                None,
            )
            if marked_in is None:
                continue
            cause = (
                _last_error_line(texts[marked_in]) or "(no Error/Exception line found)"
            )
            ungraded.append((revid, agent, evalid, cause))
        out[t] = (len(evals), ungraded)
    return out


def format_ungraded_warning(task, total, ungraded):
    """One loud line for a task whose reviews say PASS but not every evaluation graded. `ungraded` is
    the per-task list ungraded_evals_from_zip returns: (revid, agent, evalid, cause) tuples.
    """
    revids = sorted({revid for revid, _, _, _ in ungraded})
    oracle_first = (
        "oracle: did not grade; "
        if any(agent == "oracle" for _, agent, _, _ in ungraded)
        else ""
    )
    eval_ids = ", ".join(sorted({evalid for _, _, evalid, _ in ungraded}))
    causes = " | ".join(sorted({cause for _, _, _, cause in ungraded}))
    return (
        "WARNING %s: PASS on reviews, but %d of %d evaluations did not grade (%seval ids %s): %s. "
        "Run an oracle-only DataOS evaluation on revision %s before QC."
        % (task, len(ungraded), total, oracle_first, eval_ids, causes, "/".join(revids))
    )


def format_ungraded_note(task, total, ungraded):
    """Shorter one-line note for a non-PASS task with ungraded evaluations: informational only, since
    the verdict already reflects the reviews DataOS actually ran."""
    return (
        "note %s: %d of %d evaluations did not grade (task is not PASS; not blocking)"
        % (
            task,
            len(ungraded),
            total,
        )
    )


def verdicts(zip_path):
    out = tempfile.mktemp(suffix=".json")
    subprocess.run(
        [
            sys.executable,
            os.path.join(HERE, "svc_dataos_returns_parse.py"),
            zip_path,
            "--out",
            out,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    d = json.load(open(out))
    os.remove(out)
    res = {}
    for t, v in d.items():
        allrevs = v.get("reviews", [])
        revs = [r for r in allrevs if r.get("parsed")]
        passes = sum(1 for r in revs if r.get("major_count") == 0)
        ok = len(allrevs) >= 2 and passes == len(allrevs)
        res[t] = ("PASS" if ok else "FAIL", passes, len(revs))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("zip")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    name = os.path.basename(a.zip)
    base = name.replace(".zip", "")

    dest = os.path.join(QC, "_returns", name)
    if os.path.realpath(a.zip) != os.path.realpath(
        dest
    ):  # symlinked Downloads copy is the same file
        print("copy return ->", dest)
        if a.apply:
            shutil.copy2(a.zip, dest)
            assert sm.file_sha(dest) == sm.file_sha(a.zip), "copy mismatch"
    with zipfile.ZipFile(a.zip) as z:
        assert z.testzip() is None, "return zip is corrupt"
        res = verdicts(a.zip)
        shas = {t: tests_hash_from_zip(z, t) for t in res}
        ungraded = ungraded_evals_from_zip(z, res)

    accepted = sm.accepted_set(
        W + "/accepted.txt"
    )  # includes the team do-not-touch list
    passes = sorted(t for t, r in res.items() if r[0] == "PASS")
    all_rejects = sorted(t for t, r in res.items() if r[0] != "PASS")
    # A reject that is on the do-not-touch list (someone else owns it, or it is already submitted/finished)
    # is recorded but NOT requeued: fixing it would be work on another person's task.
    # A task with ZERO parsed reviews was never actually graded (DataOS exception): no findings, no fingerprint;
    # it goes to _v7/needs_regrade.txt for an as-is re-upload (svc_bundle_upload.py bundle --first-grade).
    unreviewed = [t for t in all_rejects if res[t][2] == 0 and t not in accepted]
    rejects = [t for t in all_rejects if t not in accepted and t not in unreviewed]
    skipped = [t for t in all_rejects if t in accepted]
    if unreviewed:
        print(
            "NO REVIEWS (DataOS exception) -> needs_regrade.txt, not requeued: %s"
            % unreviewed
        )
    if skipped:
        print("rejects NOT requeued (do-not-touch / frozen): %s" % skipped)
    print(
        "%s: %d tasks, %d PASS, %d FAIL (%d requeued, %d do-not-touch)"
        % (name, len(res), len(passes), len(all_rejects), len(rejects), len(skipped))
    )
    for t in sorted(res):
        print(
            "  %-16s %s (%d of %d reviews at 0 majors)"
            % (t, res[t][0], res[t][1], res[t][2])
        )
    for t in passes:
        total, u = ungraded.get(t, (0, []))
        if u:
            print(format_ungraded_warning(t, total, u))
    for t in all_rejects:
        total, u = ungraded.get(t, (0, []))
        if u:
            print(format_ungraded_note(t, total, u))

    new_acc = [t for t in passes if t not in accepted]
    print("\naccepted.txt += %s" % (new_acc or "nothing new"))
    arch_df = os.path.join(DF, "_pre_" + base)
    arch_rd = os.path.join(W, "ready", "_returned_" + base)
    for t in rejects:
        print(
            "reject %s: lastreject.sha=%s, archive records + ready zip, release claim, requeue"
            % (t, (shas[t] or "NONE")[:12])
        )
    if not a.apply:
        print("\nDRY RUN. Re-run with --apply to write.")
        return

    if new_acc:
        shutil.copy(W + "/accepted.txt", W + "/accepted.txt.bak." + ts)
        with open(W + "/accepted.txt", "a") as f:
            f.write("".join(t + "\n" for t in new_acc))
    os.makedirs(arch_df, exist_ok=True)
    os.makedirs(arch_rd, exist_ok=True)
    if unreviewed:
        nr = W + "/needs_regrade.txt"
        have = set(open(nr).read().split()) if os.path.exists(nr) else set()
        with open(nr, "a") as f:
            f.write("".join(t + "\n" for t in unreviewed if t not in have))
    for t in rejects:
        if shas[t]:
            open(os.path.join(DF, t + ".lastreject.sha"), "w").write(shas[t] + "\n")
        for ext in (".verify.md", ".regrade.json"):
            p = os.path.join(DF, t + ext)
            if os.path.exists(p):
                shutil.move(p, os.path.join(arch_df, t + ext))
        for p in (
            os.path.join(W, "ready", t + ".zip"),
            os.path.join(W, "ready", t + ".zip.manifest.json"),
        ):
            if os.path.exists(p):
                shutil.move(p, os.path.join(arch_rd, os.path.basename(p)))
        shutil.rmtree(os.path.join(W, "claims", t), ignore_errors=True)
    q = W + "/queue.txt"
    shutil.copy(q, q + ".bak." + ts)
    rest = [
        ln.strip()
        for ln in open(q)
        if ln.strip() and ln.strip() not in rejects and ln.strip() not in passes
    ]
    open(q, "w").write("\n".join(rejects + rest) + "\n")
    # read back
    acc_now = sm.accepted_set(W + "/accepted.txt")
    assert all(t in acc_now for t in passes), "accepted.txt readback failed"
    assert all(
        os.path.isfile(os.path.join(DF, t + ".lastreject.sha"))
        for t in rejects
        if shas[t]
    ), "lastreject readback failed"
    print(
        "\nAPPLIED + read back: %d frozen, %d requeued at the head of %s"
        % (len(passes), len(rejects), q)
    )


if __name__ == "__main__":
    main()
