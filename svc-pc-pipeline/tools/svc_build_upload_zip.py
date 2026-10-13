#!/usr/bin/env python3
"""The ONLY sanctioned way to build a per-task SVC-PC DataOS upload zip. Hard-gates every v8 pre-upload check
so a zip physically cannot exist without them (enforce_svc_fix_method.py blocks raw zip/tar of an SVC-PC
package to force this path). Multi-task upload bundles are built ONLY by svc_bundle_upload.py, from zips this
tool built, after re-checking each one is still fresh. Both read state from disk, so a compaction that wipes
the model's memory cannot loosen them.

Gate 1 - deterministic pre-screen (svc_prefilter.py): REFUSE on any HARD defect (grammar bomb >15 criteria/dir,
         a files= path missing from the package, an answer-key leak, lease.json). WARNs do not block.
Gate 2 - adversarial verify record: REFUSE unless <verify-dir>/<task>.verify.md exists, its LAST verdict is
         READY-TO-RESUBMIT, it carries the CURRENT METHOD_VERSION from svc_fix_method_rules.md, and it is
         NEWER than the last edit anywhere in the package. (Until 2026-09-22 this gate only checked that the
         file existed, so a NOT-READY record, or one from before a later edit, passed it.)
Gate 3 - EVAL-REGRADE (the load-bearing check): REFUSE unless <regrade-dir>/<task>.regrade.json exists, its
         verdict is PASS, and it is NEWER than the newest file under tests/ (proof it was re-run AFTER the last
         edit). PASS means the real answer DataOS saved - the one it called compliant-but-failed - now passes
         the fixed rubric (direction A), and any 1.5 coverage hole is closed by a criterion a hollow answer
         fails (direction B).
Gate 4 - accepted-task freeze: REFUSE if the task is on <accepted-list> (a task DataOS already passed is never
         re-touched; re-editing passes caused 4 of 5 regressions).
Gate 5 - identical-resubmit guard: REFUSE if tests/ is byte-identical to the last-rejected snapshot recorded
         at <regrade-dir>/<task>.lastreject.sha (15% of past rounds shipped unchanged bytes). The return
         intake (svc_record_return.py) writes that file for every rejected task.
Then: build the zip excluding junk, cold-audit it (testzip OK, exactly one SVC-PC-* root, no junk), and write
<zip>.manifest.json (package hash, zip hash, verify + regrade record hashes and verdicts, METHOD_VERSION).
svc_bundle_upload.py re-derives every manifest field from disk at bundle time and refuses any task whose
corpus, zip, verify or regrade changed since. That closes the stale-zip hole (see svc_ship_manifest.py).

--first-grade: a task DataOS has NEVER graded (harvest). Gates 3 and 5 need a prior grade and are N/A; the
builder PROVES the task is absent from every return zip in --returns-dir instead of taking it on trust, and a
verify record is optional (used and checked if present). Gates 1, 4 and the cold audit still apply. This
replaces building harvest zips under [skip-svc-fix-method].

Usage (on the sandbox, where packages live):
  python3 tools/svc_build_upload_zip.py SVC-PC-16-1-0 [--first-grade] \
     [--pkg-root /root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready] \
     [--verify-dir /root/qc/_deepfix] [--regrade-dir /root/qc/_deepfix] \
     [--accepted-list /root/qc/_v7/accepted.txt] [--returns-dir /root/qc/_returns] [--out /tmp/<task>.zip]
Exit: 0 built, 3 pre-screen HARD, 4 verify record missing/NOT-READY/old-method/stale, 5 zip audit failed,
      6 eval-regrade missing/not-PASS/stale (or first-grade task already graded), 7 accepted-task frozen,
      8 identical resubmit, 9 usage/paths."""

import argparse, os, sys, subprocess, zipfile, datetime, glob, json, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import svc_ship_manifest as sm  # noqa: E402

is_junk = sm.is_junk


def tests_files(pkg):
    tdir = os.path.join(pkg, "tests")
    for dp, dirs, fs in os.walk(tdir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in fs:
            if not is_junk(f):
                yield os.path.join(dp, f)


def tests_mtime(pkg):
    return max((os.path.getmtime(f) for f in tests_files(pkg)), default=0)


def tests_hash(pkg):
    """Gate 5 fingerprint. Kept byte-compatible with every .lastreject.sha already on disk."""
    h = hashlib.sha256()
    for f in sorted(tests_files(pkg)):
        h.update(os.path.relpath(f, pkg).replace("\\", "/").encode())
        with open(f, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()


if __name__ != "__main__":
    # imported for tests_hash / tests_files only (svc_record_return.py); do not run the gates
    pass
else:
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument(
        "--pkg-root", default="/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready"
    )
    ap.add_argument("--verify-dir", default="/root/qc/_deepfix")
    ap.add_argument("--regrade-dir", default="/root/qc/_deepfix")
    ap.add_argument("--accepted-list", default="/root/qc/_v7/accepted.txt")
    ap.add_argument("--returns-dir", default="/root/qc/_returns")
    ap.add_argument("--rules", default=sm.RULES)
    ap.add_argument(
        "--first-grade",
        action="store_true",
        help="never-graded harvest task: Gates 3/5 N/A, proven absent from every return zip",
    )
    ap.add_argument("--out", default="")
    ap.add_argument("--prefilter", default=os.path.join(HERE, "svc_prefilter.py"))
    ap.add_argument(
        "--fast-track",
        default="",
        metavar="REASON",
        help="owner-authorised: skip ONLY Gate 2's READY-verdict requirement (the local reviewer), recorded in the "
        "manifest. Every other gate still runs, and the golden must score 1.0 on its current bytes (--oracle-json).",
    )
    ap.add_argument(
        "--oracle-json",
        default="",
        help="with --fast-track: the oracle result for the CURRENT package bytes; total_reward must be 1.0 and the "
        "file must be newer than the last package edit",
    )
    ap.add_argument(
        "--verify-capped",
        action="store_true",
        help="with --fast-track: the L2 verify-cap pilot (owner-authorised 2026-09-23). The runner shipped after the "
        "verify loop-back cap with every deterministic gate green; tags the manifest so this cohort's DataOS pass "
        "rate is measured separately, and records the unresolved verify record's hash.",
    )
    a = ap.parse_args()
    if a.verify_capped and not a.fast_track:
        print("ERROR: --verify-capped requires --fast-track REASON and --oracle-json")
        sys.exit(2)
    # Absolute, or the manifest records a path only valid from this cwd and every later check reads it as missing
    # (46-0-0 fast-track on 2026-09-23: bundle check from /root reported the oracle record "changed or missing").
    if a.oracle_json:
        a.oracle_json = os.path.abspath(a.oracle_json)

    pkg = os.path.join(a.pkg_root, a.task)
    if not os.path.isdir(pkg):
        print("ERROR: package not found:", pkg)
        sys.exit(9)
    cur_mv = sm.method_version(a.rules)

    # Gate 1: deterministic pre-screen
    print("=== Gate 1: pre-screen (svc_prefilter.py) ===")
    r = subprocess.run(
        [sys.executable, a.prefilter, pkg], capture_output=True, text=True
    )
    print(r.stdout.strip())
    if r.returncode != 0:
        print(
            "\nREFUSED: pre-screen found a HARD defect. Fix it and re-run. (WARNs do not block.)"
        )
        sys.exit(3)

    # Gate 1b: DataOS's own loader. rewardkit 0.1.7 discover() must accept tests/, or DataOS drops the task at
    # upload with only "Has 1 error" (72-1-0 and 94-7-0 on 2026-09-22: judge = [panel list] loads in 0.2.0,
    # crashes in 0.1.7). Skipped with a loud note only where the pinned venv does not exist (laptop).
    v017 = os.environ.get("SVC_REWARDKIT017_PY", "/root/venv017/bin/python3")
    if os.path.exists(v017):
        print("\n=== Gate 1b: rewardkit 0.1.7 discover() (the loader DataOS runs) ===")
        r = subprocess.run(
            [v017, os.path.join(HERE, "svc_discover017_check.py"), pkg],
            capture_output=True,
            text=True,
        )
        print(r.stdout.strip())
        if r.returncode != 0:
            print(
                "\nREFUSED: DataOS's pinned rewardkit cannot load tests/. Fix judge.toml (e.g. judge must be one string)."
            )
            sys.exit(3)
    else:
        print("\nNOTE: Gate 1b skipped - no rewardkit 0.1.7 interpreter at %s" % v017)

    # Gate 2: verify record READY, under the current method, newer than every package edit
    vrec = os.path.join(a.verify_dir, a.task + ".verify.md")
    pkg_mtime = max((os.path.getmtime(f) for f in sm._walk(pkg)), default=0)
    print("\n=== Gate 2: adversarial verify record (method %s) ===" % cur_mv)
    if a.fast_track:
        # Owner-authorised 2026-09-23 for the L3 deadline: the local reviewer is a weak predictor of DataOS (about 21%
        # of its READYs pass) while the golden-1.0 and regrade gates are objective. Replace the verdict requirement
        # with a proof that the golden scores 1.0 on THESE bytes.
        oj = a.oracle_json
        if not (oj and os.path.isfile(oj)):
            print(
                "REFUSED: --fast-track needs --oracle-json for the current package bytes."
            )
            sys.exit(4)
        if os.path.getmtime(oj) < pkg_mtime:
            print(
                "REFUSED: the oracle result is OLDER than the last package edit - it scored different bytes."
            )
            sys.exit(4)
        rew = json.load(open(oj)).get("total_reward")
        if rew != 1.0:
            print("REFUSED: fast-track oracle total_reward is %r, not 1.0." % rew)
            sys.exit(4)
        print(
            "FAST-TRACK (owner-authorised): reviewer verdict NOT required. Reason: %s"
            % a.fast_track
        )
        print("oracle on current bytes: total_reward=1.0 (%s)" % oj)
        capped_vrec = vrec if (a.verify_capped and os.path.isfile(vrec)) else None
        vrec = None
    elif a.first_grade and not os.path.isfile(vrec):
        print(
            "first-grade: no verify record (not required before a task's first DataOS grade)"
        )
        vrec = None
    else:
        if not (os.path.isfile(vrec) and os.path.getsize(vrec) > 200):
            print(
                "REFUSED: no adversarial-verify record at", vrec, "(need >200 bytes)."
            )
            sys.exit(4)
        vv, vmv = sm.verify_verdict(vrec)
        if vv != "READY":
            print(
                "REFUSED: the verify record's last verdict is %s, not READY-TO-RESUBMIT."
                % vv
            )
            sys.exit(4)
        if vmv != cur_mv:
            print(
                "REFUSED: verify record was made under method %s; current is %s. Re-verify."
                % (vmv, cur_mv)
            )
            sys.exit(4)
        if os.path.getmtime(vrec) < pkg_mtime:
            print(
                "REFUSED: verify record is OLDER than the last package edit - it audited different bytes."
            )
            sys.exit(4)
        print("found:", vrec, "(%d bytes, READY, %s)" % (os.path.getsize(vrec), vmv))

    # Gate 3: eval-regrade PASS and fresh (graded), or proof of never-graded (first-grade)
    print("\n=== Gate 3: eval-regrade (real answer now passes the fixed rubric) ===")
    rg = os.path.join(a.regrade_dir, a.task + ".regrade.json")
    if a.first_grade:
        zips = sorted(glob.glob(os.path.join(a.returns_dir, "*_with_runs*.zip")))
        graded_in = []
        for z in zips:
            try:
                # A return counts as a grade only if it holds a comprehensive review for the task. A task
                # that hit a DataOS exception comes back with no review (5-1-0, 2026-09-22): there are no
                # findings to fix from, so it is re-graded as-is via --first-grade, not sent to a lane.
                if any(
                    n.startswith(a.task + "/")
                    and "/verifications/comprehensive_review" in n
                    for n in zipfile.ZipFile(z).namelist()
                ):
                    graded_in.append(os.path.basename(z))
            except zipfile.BadZipFile:
                print(
                    "REFUSED: unreadable return zip",
                    z,
                    "- cannot prove the task was never graded.",
                )
                sys.exit(6)
        if graded_in:
            print(
                "REFUSED: --first-grade, but DataOS already graded %s in %s. Use the graded path."
                % (a.task, graded_in)
            )
            sys.exit(6)
        print(
            "first-grade: absent from all %d return zips in %s; Gates 3 and 5 N/A"
            % (len(zips), a.returns_dir)
        )
        rg = None
    else:
        if not os.path.isfile(rg):
            print(
                "REFUSED: no eval-regrade record at",
                rg,
                "- run svc_eval_regrade.py regrade first.",
            )
            sys.exit(6)
        try:
            rec = json.load(open(rg))
        except Exception as e:
            print("REFUSED: eval-regrade record unreadable:", e)
            sys.exit(6)
        if rec.get("verdict") != "PASS":
            print(
                "REFUSED: eval-regrade verdict is %r, not PASS: %s"
                % (rec.get("verdict"), rec.get("why"))
            )
            sys.exit(6)
        if os.path.getmtime(rg) < tests_mtime(pkg):
            print(
                "REFUSED: eval-regrade record is STALE (older than the last tests/ edit). Re-run the regrade."
            )
            sys.exit(6)
        print("PASS:", str(rec.get("why", ""))[:160])

    # Gate 4: never re-touch a task DataOS already accepted
    if a.task in sm.accepted_set(a.accepted_list):
        print(
            "\nREFUSED: %s is on the accepted freeze list (%s). Passed tasks are never re-touched."
            % (a.task, a.accepted_list)
        )
        sys.exit(7)

    # Gate 5: refuse a byte-identical resubmit
    lastreject = os.path.join(a.regrade_dir, a.task + ".lastreject.sha")
    if not a.first_grade and os.path.isfile(lastreject):
        if open(lastreject).read().strip() == tests_hash(pkg):
            print(
                "\nREFUSED: tests/ is byte-identical to the last-rejected snapshot - resubmitting would waste a round."
            )
            sys.exit(8)

    # Build the zip (top-level = <task>/), excluding junk
    out = a.out or os.path.join(
        "/tmp", "%s-%s.zip" % (a.task, datetime.date.today().isoformat())
    )
    for p in (out, sm.manifest_path(out)):
        if os.path.exists(p):
            os.remove(p)
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for full in sm._walk(pkg):
            z.write(
                full,
                os.path.join(a.task, os.path.relpath(full, pkg)).replace("\\", "/"),
            )
            n += 1
    print("\n=== built:", out, "(%d files) ===" % n)

    # Cold audit
    z = zipfile.ZipFile(out)
    bad = z.testzip()
    tops = sorted({e.split("/")[0] for e in z.namelist()})
    junk = [e for e in z.namelist() if is_junk(e)]
    z.close()
    ok = bad is None and tops == [a.task] and not junk
    print(
        "audit: testzip=%s roots=%s junk=%d"
        % ("OK" if bad is None else "CORRUPT:" + str(bad), tops, len(junk))
    )
    if not ok:
        print("REFUSED: zip audit failed.")
        os.remove(out)
        sys.exit(5)

    # Freshness manifest: what svc_bundle_upload.py re-checks before this zip may go into any upload bundle
    man = sm.build_manifest(a.task, pkg, out, vrec, rg, graded=not a.first_grade)
    man.update(
        {
            "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "method_current": cur_mv,
            "tests_hash": tests_hash(pkg),
        }
    )
    if a.fast_track:
        man.update(
            {
                "fast_track": a.fast_track,
                "oracle_json": a.oracle_json,
                "oracle_sha": sm.file_sha(a.oracle_json),
            }
        )
        if a.verify_capped:
            man.update(
                {
                    "verify_capped": True,
                    "capped_verify_path": capped_vrec,
                    "capped_verify_sha": sm.file_sha(capped_vrec) if capped_vrec else None,
                }
            )
    with open(sm.manifest_path(out), "w") as f:
        json.dump(man, f, indent=1)
    print("manifest:", sm.manifest_path(out))
    print("\nOK. Upload-ready:", out)
