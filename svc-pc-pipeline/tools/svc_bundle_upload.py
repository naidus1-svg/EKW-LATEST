#!/usr/bin/env python3
"""The ONLY sanctioned way to assemble a multi-task SVC-PC DataOS upload bundle, and to re-check one before
it is uploaded. Stdlib only. Runs on the sandbox, where the corpus and the per-task zips live.

Why (2026-09-22, the stale-zip hole, second time): batch1 was bundled at 13:34Z by an ad-hoc script that
unzipped every _v7/ready/<task>.zip whose regrade said PASS. Four of those zips were built at ~04:00Z; a later
fix pass re-edited the four packages and its own verify said NOT-READY; the bundle shipped the 04:00Z bytes
anyway and all four were rejected. The bundler trusted "a zip exists" as "the zip is current". This tool
trusts nothing it cannot re-derive: for every task it recomputes the corpus package hash, the zip hash, and
the verify/regrade record hashes and verdicts, and compares them to the manifest the builder wrote. Any
difference EXCLUDES the task from the bundle and prints why. A stale task cannot ride along.

  bundle  - build a bundle from per-task zips (graded tasks, from _v7/ready/) or, with --first-grade, build
            each never-graded task's zip through svc_build_upload_zip.py --first-grade first. Writes
            <bundle>.zip + <bundle>.manifest.json (one entry per task, the per-task manifests embedded) and
            records each shipped task in <shipped-dir>/<task>.json so the same bytes are never sent twice.
  check   - re-run every freshness check for an existing bundle against the CURRENT disk state. Run it
            immediately before the upload (and before copying a bundle off the sandbox). Exit 0 = every task
            in the bundle is still exactly what was verified; exit 1 = at least one is stale, do not upload.

  sweep   - find every zip in ready/ that is no longer fresh (corpus edited, re-verified, old METHOD_VERSION,
            no manifest) and send it back through the loop: retire the zip, release the claim, requeue at the
            head. Run after every METHOD_VERSION bump and after any pool run that overlapped a rules change.

Usage:
  python3 tools/svc_bundle_upload.py sweep [--apply]
  python3 tools/svc_bundle_upload.py bundle --name svc-v8-batch2 [--tasks T1 T2 ... | --from-ready] \
      [--first-grade] [--size 25]
  python3 tools/svc_bundle_upload.py check /root/qc/_bundles/svc-v8-batch2.zip
Exit: 0 ok, 1 stale/refused tasks present (check) or nothing shippable (bundle), 2 usage."""

import argparse, datetime, glob, json, os, shutil, subprocess, sys, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import svc_ship_manifest as sm  # noqa: E402

CORPUS = "/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready"
QC = "/root/qc"


def args():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bundle")
    b.add_argument("--name", required=True, help="bundle basename, e.g. svc-v8-batch2")
    g = b.add_mutually_exclusive_group(required=True)
    g.add_argument("--tasks", nargs="+")
    g.add_argument(
        "--from-ready", action="store_true", help="every zip currently in --ready-dir"
    )
    b.add_argument(
        "--first-grade",
        action="store_true",
        help="never-graded harvest tasks (builds each zip)",
    )
    b.add_argument(
        "--size",
        type=int,
        default=0,
        help="split into parts of N tasks (0 = one bundle)",
    )
    c = sub.add_parser("check")
    c.add_argument("bundle")
    c.add_argument(
        "--legacy",
        action="store_true",
        help="bundle built before the gate (no manifest): compare each task folder to the corpus",
    )
    s = sub.add_parser("sweep")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--claims-dir", default=QC + "/_v7/claims")
    s.add_argument("--queue", default=QC + "/_v7/queue.txt")
    for p in (b, c, s):
        p.add_argument("--pkg-root", default=CORPUS)
        p.add_argument("--ready-dir", default=QC + "/_v7/ready")
        p.add_argument("--accepted-list", default=QC + "/_v7/accepted.txt")
        p.add_argument("--out-dir", default=QC + "/_bundles")
        p.add_argument("--shipped-dir", default=QC + "/_v7/shipped")
        p.add_argument("--rules", default=sm.RULES)
        p.add_argument("--returns-dir", default=QC + "/_returns")
        p.add_argument("--verify-dir", default=QC + "/_deepfix")
        p.add_argument("--prefilter", default=os.path.join(HERE, "svc_prefilter.py"))
    return ap.parse_args()


def check_one(task, zip_path, a):
    m, why = sm.check_task_zip(
        zip_path, os.path.join(a.pkg_root, task), a.accepted_list, a.rules
    )
    if m and m.get("task") != task:
        why.append("manifest names %s, not %s" % (m.get("task"), task))
    return m, why


def already_shipped(task, m, a):
    p = os.path.join(a.shipped_dir, task + ".json")
    if not os.path.isfile(p) or not m:
        return None
    prev = json.load(open(p))
    if prev.get("pkg_hash") == m.get("pkg_hash"):
        return "these exact bytes already shipped in %s" % prev.get("bundle")
    return None


def write_bundle(name, entries, a):
    os.makedirs(a.out_dir, exist_ok=True)
    out = os.path.join(a.out_dir, name + ".zip")
    for p in (out, out + ".manifest.json"):
        if os.path.exists(p):
            os.remove(p)
    stage = tempfile.mkdtemp()
    try:
        for t, zp, _ in entries:
            with zipfile.ZipFile(zp) as z:
                z.extractall(stage)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for t, _, _ in entries:
                root = os.path.join(stage, t)
                for full in sm._walk(root):
                    z.write(
                        full,
                        os.path.join(t, os.path.relpath(full, root)).replace("\\", "/"),
                    )
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    # cold audit: integrity, exactly the task roots we meant, no junk
    with zipfile.ZipFile(out) as z:
        bad = z.testzip()
        roots = sorted({n.split("/", 1)[0] for n in z.namelist()})
        junk = [n for n in z.namelist() if sm.is_junk(n)]
    want = sorted(t for t, _, _ in entries)
    if bad is not None or roots != want or junk:
        os.remove(out)
        sys.exit(
            "REFUSED: bundle audit failed (testzip=%s roots=%d/%d junk=%d)"
            % (bad, len(roots), len(want), len(junk))
        )
    man = {
        "bundle": os.path.basename(out),
        "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "method_version": sm.method_version(a.rules),
        "bundle_sha": sm.file_sha(out),
        "tasks": {t: {"zip": zp, "manifest": m} for t, zp, m in entries},
    }
    json.dump(man, open(out + ".manifest.json", "w"), indent=1)
    os.makedirs(a.shipped_dir, exist_ok=True)
    for t, zp, m in entries:
        json.dump(
            {
                "bundle": os.path.basename(out),
                "pkg_hash": m.get("pkg_hash"),
                "at": man["built_at"],
            },
            open(os.path.join(a.shipped_dir, t + ".json"), "w"),
        )
    print(
        "BUNDLE %s: %d tasks, %.1f MB, audit OK"
        % (out, len(entries), os.path.getsize(out) / 1e6)
    )
    print("  tasks:", " ".join(want))
    print("  manifest:", out + ".manifest.json")
    return out


def cmd_bundle(a):
    if a.first_grade:
        tasks = a.tasks or []
        if not tasks:
            sys.exit("--first-grade needs --tasks")
        fg_dir = os.path.join(a.out_dir, "_first_grade_zips")
        os.makedirs(fg_dir, exist_ok=True)
    else:
        tasks = a.tasks or sorted(
            os.path.basename(p)[:-4]
            for p in glob.glob(os.path.join(a.ready_dir, "SVC-PC-*.zip"))
        )
    ok, refused = [], []
    for t in tasks:
        if a.first_grade:
            zp = os.path.join(fg_dir, t + ".zip")
            r = subprocess.run(
                [
                    sys.executable,
                    os.path.join(HERE, "svc_build_upload_zip.py"),
                    t,
                    "--first-grade",
                    "--pkg-root",
                    a.pkg_root,
                    "--accepted-list",
                    a.accepted_list,
                    "--returns-dir",
                    a.returns_dir,
                    "--verify-dir",
                    a.verify_dir,
                    "--rules",
                    a.rules,
                    "--prefilter",
                    a.prefilter,
                    "--out",
                    zp,
                ],
                capture_output=True,
                text=True,
            )
            if r.returncode != 0:
                refused.append(
                    (
                        t,
                        [
                            "builder refused (exit %d): %s"
                            % (r.returncode, r.stdout.strip().splitlines()[-1:])
                        ],
                    )
                )
                continue
        else:
            zp = os.path.join(a.ready_dir, t + ".zip")
        m, why = check_one(t, zp, a)
        dup = already_shipped(t, m, a)
        if dup:
            why.append(dup)
        (refused if why else ok).append((t, why) if why else (t, zp, m))
    print(
        "=== freshness check: %d fresh, %d refused (method %s) ==="
        % (len(ok), len(refused), sm.method_version(a.rules))
    )
    for t, why in refused:
        print("  REFUSED %s: %s" % (t, "; ".join(why)))
    if not ok:
        print("nothing shippable")
        sys.exit(1)
    parts = (
        [ok] if not a.size else [ok[i : i + a.size] for i in range(0, len(ok), a.size)]
    )
    for i, part in enumerate(parts, 1):
        write_bundle(a.name if len(parts) == 1 else "%s-p%d" % (a.name, i), part, a)
    if refused:
        print(
            "\n%d task(s) were EXCLUDED as stale or unshippable; they are not in any bundle."
            % len(refused)
        )


def cmd_check(a):
    mp = a.bundle + ".manifest.json"
    if not os.path.isfile(mp) and a.legacy:
        # A bundle built before this gate existed has no manifest. The strongest check left: every task folder
        # in the zip must be byte-identical to the current corpus package, and not on the freeze list.
        hashes = sm.zip_tree_hashes(a.bundle)
        acc = sm.accepted_set(a.accepted_list)
        bad = []
        for t, h in sorted(hashes.items()):
            pkg = os.path.join(a.pkg_root, t)
            if t in acc:
                bad.append((t, "on the accepted freeze list"))
            elif not os.path.isdir(pkg):
                bad.append((t, "no corpus package"))
            elif sm.pkg_hash(pkg) != h:
                bad.append((t, "zip content differs from the current corpus package"))
        print(
            "=== legacy check %s: %d tasks (no manifest: content vs corpus only; verify/regrade not provable) ==="
            % (os.path.basename(a.bundle), len(hashes))
        )
        for t, why in bad:
            print("  STALE %s: %s" % (t, why))
        if bad:
            print(
                "DO NOT UPLOAD as-is. Rebuild with svc_bundle_upload.py bundle (stale tasks are excluded)."
            )
            sys.exit(1)
        print(
            "MATCHES CORPUS: every task folder is byte-identical to the current package."
        )
        return
    if not os.path.isfile(mp):
        print(
            "STALE: no bundle manifest %s - this bundle was not built by svc_bundle_upload.py. Do not upload."
            % mp
        )
        sys.exit(1)
    man = json.load(open(mp))
    bad = []
    if sm.file_sha(a.bundle) != man.get("bundle_sha"):
        bad.append(("<bundle>", ["bundle zip bytes changed since it was built"]))
    with zipfile.ZipFile(a.bundle) as z:
        roots = sorted({n.split("/", 1)[0] for n in z.namelist()})
    if roots != sorted(man["tasks"]):
        bad.append(("<bundle>", ["bundle roots differ from its manifest"]))
    for t, e in sorted(man["tasks"].items()):
        _, why = check_one(t, e["zip"], a)
        if why:
            bad.append((t, why))
    print(
        "=== pre-upload check %s: %d tasks, method now %s ==="
        % (os.path.basename(a.bundle), len(man["tasks"]), sm.method_version(a.rules))
    )
    for t, why in bad:
        print("  STALE %s: %s" % (t, "; ".join(why)))
    if bad:
        print(
            "DO NOT UPLOAD. Rebuild the bundle (stale tasks are excluded automatically)."
        )
        sys.exit(1)
    print("FRESH: every task is byte-identical to what was verified. OK to upload.")


def cmd_sweep(a):
    """Every zip in ready/ that is not fresh goes back through the loop: retire the zip, release the claim,
    put the task at the head of the queue. Needed whenever METHOD_VERSION changes (every old-method zip is
    stale by definition) and after any pool run that overlapped a rules change."""
    import time

    zips = sorted(glob.glob(os.path.join(a.ready_dir, "SVC-PC-*.zip")))
    acc = sm.accepted_set(a.accepted_list)
    stale = []
    for zp in zips:
        t = os.path.basename(zp)[:-4]
        if t in acc:
            continue  # a passed task's zip is history, never requeued
        _, why = check_one(t, zp, a)
        if why:
            stale.append((t, zp, why))
    print(
        "=== sweep %s: %d zips, %d stale (method %s) ==="
        % (a.ready_dir, len(zips), len(stale), sm.method_version(a.rules))
    )
    for t, _, why in stale:
        print("  STALE %s: %s" % (t, "; ".join(why)))
    if not a.apply or not stale:
        print("DRY RUN." if stale and not a.apply else "nothing to requeue.")
        return
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    sup = os.path.join(a.ready_dir, "_superseded")
    os.makedirs(sup, exist_ok=True)
    for t, zp, _ in stale:
        for p in (zp, sm.manifest_path(zp)):
            if os.path.exists(p):
                shutil.move(p, os.path.join(sup, os.path.basename(p) + "." + stamp))
        shutil.rmtree(os.path.join(a.claims_dir, t), ignore_errors=True)
    q = a.queue
    if os.path.isfile(q):
        shutil.copy(q, q + ".bak." + stamp)
        rest = [ln.strip() for ln in open(q) if ln.strip()]
    else:
        rest = []
    names = [t for t, _, _ in stale]
    head = [ln for ln in rest if ln not in names]
    # keep tasks already at the head (e.g. a return's rejects) first, then the swept tasks, then the rest
    open(q, "w").write("\n".join(names + head) + "\n")
    print(
        "requeued %d at the head of %s; their zips moved to %s" % (len(names), q, sup)
    )


if __name__ == "__main__":
    a = args()
    {"bundle": cmd_bundle, "check": cmd_check, "sweep": cmd_sweep}[a.cmd](a)
