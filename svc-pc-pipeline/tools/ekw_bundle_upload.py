#!/usr/bin/env python3
"""The ONLY sanctioned way to assemble a multi-task EKW DataOS upload bundle, and to re-check one before it is
uploaded. The EKW twin of svc_bundle_upload.py. Stdlib only. Runs on the sandbox, where the EKW packages, the
lane work dir and the per-task ready zips live.

Why: the SVC stale-zip hole (2026-09-22). Four zips built at ~04:00Z shipped at 13:34Z after a later fix pass had
re-edited their packages; all four were rejected. A zip on disk is never trusted as current. For every task this
tool re-derives, from disk, everything the lane runner (ekw_v1_lane_runner.sh step 9, ekw_intake.py package)
recorded in <TASK>.zip.manifest.json and refuses the task on any difference:

  1. the zip still hashes to manifest.zip_sha256, and every member hashes to manifest.files
  2. the package on disk ($EKW_ROOT/<TASK>, walked with ekw_intake.package's own junk filter) still hashes to
     manifest.files, file for file (nothing edited it since the zip was built)
  3. the verify record and gate JSON are byte-identical to the ones the build used; the verify's last VERDICT line
     is READY-TO-RESUBMIT and its METHOD_VERSION is the CURRENT ekw-v1/<svc_fix_method_rules.md version>; the gate
     verdict is PASS
  4. the raw verifier.json ($EKW_ROOT/_raw/<TASK>) still hashes to manifest.raw_verifier_sha256
  5. the task is READY (latest ready.txt line is newer than any parked.txt line), not on accepted.txt or
     do_not_touch.txt, and no lane runner process is working on it right now
  6. zip audit: exactly one root named <TASK>, required files present, no junk (lease.json, __pycache__,
     _scratch_*, *.preedit, *.orig, *.bak, *.pyc, *.tmp, tamper scripts, .DS_Store), no answer-key path under
     environment/, and no environment/ file byte-identical to a solution/ file (LGL-190 had its goldens in inputs)
  7. these exact package bytes were not already put in a different bundle

Subcommands:
  bundle  - build <out-dir>/<name>.zip + <name>.zip.manifest.json from fresh tasks only; refused tasks are printed
            with every reason and left out. Records each bundled task in <work>/shipped/<TASK>.json. Rebuilding the
            SAME --name is allowed (it replaces that bundle); putting the same bytes in a second bundle is refused.
            A bundle whose summed task zips exceed --max-mb (default 450) is split into <name>a, <name>b, ...
  check   - re-run every check above for an existing bundle against the CURRENT disk state, plus the bundle's own
            hash and roots. Run it immediately before the upload. Exit 0 = OK to upload; exit 1 = do not upload.

Usage (sandbox):
  python3 /root/qc/tools/ekw_bundle_upload.py bundle --name ekw-v1-batch1 --from-ready
  python3 /root/qc/tools/ekw_bundle_upload.py bundle --name ekw-v1-batch2 --tasks LGL-131 SCO-198
  python3 /root/qc/tools/ekw_bundle_upload.py check /root/qc/_bundles/ekw-v1-batch1.zip
Exit: 0 ok, 1 refused/stale (check) or nothing shippable (bundle), 2 usage.
Nothing here uploads, writes to Drive/Sheets, or sends messages."""

import argparse
import datetime
import fnmatch
import glob
import hashlib
import json
import os
import re
import string
import sys
import zipfile

QC = "/root/qc"
WORK = QC + "/_ekw"
PKG_ROOT = os.environ.get("EKW_ROOT", "/root/ekwqc/pipeline/data/ekw_qc")
RULES = QC + "/tools/svc_fix_method_rules.md"
OUT_DIR = QC + "/_bundles"
TASK_RE = re.compile(r"^[A-Z]{3}-\d+$")

# ekw_intake.package's own filter, mirrored exactly so a fresh package re-hashes to its manifest.
INTAKE_JUNK_SUFFIX = (".orig", ".bak", ".pyc", ".tmp")
INTAKE_JUNK_NAMES = {
    "lease.json",
    ".ds_store",
    "thumbs.db",
    "__pycache__",
    "_incidents.md",
}
# What may never be inside a shipped zip (svc_ship_manifest.JUNK_GLOBS plus the intake list).
JUNK_GLOBS = (
    "_scratch_*",
    "*tamper*",
    "*.preedit",
    "*.orig",
    "*.bak",
    "*.pyc",
    "*.tmp",
    "lease.json",
    ".DS_Store",
    "Thumbs.db",
    "_incidents.md",
)
REQUIRED = (
    "task.toml",
    "instruction.md",
    "tests/reward.toml",
    "tests/test.sh",
    "solution/solve.sh",
)
# Grader or golden material that must never sit in the solver's environment/.
ANSWER_KEY_NAMES = {
    "verifier.json",
    "judge.toml",
    "reward.toml",
    "checks.py",
    "solve.sh",
    "task.toml",
}
ANSWER_KEY_PART = re.compile(
    r"(^|[\s_.-])(solution|solutions|expert[\s_-]?solution|golden|goldens|answer[\s_-]?key|rubric|grading)"
    r"([\s_.-]|$)",
    re.I,
)


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def file_sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pkg_hash(files):
    """One hash for a {relpath: sha} map: identifies 'these exact package bytes'."""
    return sha_bytes(json.dumps(sorted(files.items())).encode())


def is_junk(path):
    parts = path.replace("\\", "/").split("/")
    return "__pycache__" in parts or any(
        fnmatch.fnmatch(parts[-1], g) for g in JUNK_GLOBS
    )


def answer_key_path(rel):
    """rel is relative to the task root. True if an environment/ path looks like grader/golden material."""
    if not rel.startswith("environment/"):
        return False
    parts = rel.split("/")[1:]
    if parts and parts[-1].lower() in ANSWER_KEY_NAMES:
        return True
    return any(
        ANSWER_KEY_PART.search(os.path.splitext(p)[0] if i == len(parts) - 1 else p)
        for i, p in enumerate(parts)
    )


def method_version(rules):
    with open(rules, encoding="utf-8") as f:
        m = re.match(r"METHOD_VERSION:\s*(\S+)", f.readline().strip())
    if not m:
        raise RuntimeError("no METHOD_VERSION on line 1 of %s" % rules)
    return "ekw-v1/" + m.group(1)


def disk_pkg_files(pkg):
    out = {}
    for dirpath, dirnames, filenames in os.walk(pkg):
        dirnames.sort()
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, pkg).replace("\\", "/")
            if any(
                p.lower() in INTAKE_JUNK_NAMES for p in rel.split("/")
            ) or fn.lower().endswith(INTAKE_JUNK_SUFFIX):
                continue
            out[rel] = file_sha(full)
    return out


def zip_task_files(z, task):
    """{relpath under task root: sha} for every file member of zipfile z under <task>/."""
    out = {}
    for n in z.namelist():
        if n.endswith("/") or not n.startswith(task + "/"):
            continue
        out[n[len(task) + 1 :]] = sha_bytes(z.read(n))
    return out


def audit_members(task, names, files):
    """Content audit of one task's members. names: every name in the zip; files: {rel: sha} under task/."""
    why = []
    roots = sorted({n.split("/", 1)[0] for n in names})
    if roots != [task]:
        why.append("zip roots %s != [%s]" % (roots, task))
    junk = sorted(n for n in names if is_junk(n))
    if junk:
        why.append("junk in zip: %s" % ", ".join(junk[:5]))
    for need in REQUIRED:
        if need not in files:
            why.append("missing %s" % need)
    if not any(r.startswith("solution/files/") for r in files):
        why.append("solution/files/ is empty")
    if not any(
        r.startswith("tests/deliverables") and r.endswith("/judge.toml") for r in files
    ):
        why.append("no tests/deliverables*/judge.toml")
    if not any(r.startswith("environment/initial_workspace/") for r in files):
        why.append("environment/initial_workspace/ is empty")
    ak = sorted(r for r in files if answer_key_path(r))
    if ak:
        why.append("answer-key path(s) in environment/: %s" % ", ".join(ak[:5]))
    empty = sha_bytes(b"")
    gold = {}
    for r, h in files.items():
        if r.startswith("solution/") and h != empty:
            gold.setdefault(h, r)
    dup = sorted(
        "%s == %s" % (r, gold[h])
        for r, h in files.items()
        if r.startswith("environment/") and h in gold
    )
    if dup:
        why.append(
            "golden in inputs: environment file byte-identical to a solution file: %s"
            % "; ".join(dup[:5])
        )
    return why


def read_tsv_latest(path, task):
    """Latest ISO timestamp (col 3) for task in a TSV list like ready.txt / parked.txt, or None."""
    best = None
    if not os.path.isfile(path):
        return None
    for ln in open(path, encoding="utf-8", errors="replace"):
        cols = ln.rstrip("\n").split("\t")
        if cols and cols[0].strip() == task:
            ts = cols[2].strip() if len(cols) > 2 else ""
            best = max(best or "", ts)
    return best


def listed(path, task):
    if not os.path.isfile(path):
        return False
    return any(
        ln.split("\t")[0].strip() == task
        for ln in open(path, encoding="utf-8", errors="replace")
    )


def live_runner(task):
    """True if an ekw_v1_lane_runner.sh process is running this task now. Reads argv tokens from /proc, so it
    never matches its own command line. On a machine without /proc (tests on Windows) it returns False.
    """
    if not os.path.isdir("/proc"):
        return False
    me = os.getpid()
    for p in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            if int(p.split("/")[2]) == me:
                continue
            argv = open(p, "rb").read().split(b"\0")
        except (OSError, ValueError):
            continue
        for i, tok in enumerate(argv[:-1]):
            if (
                tok.endswith(b"ekw_v1_lane_runner.sh")
                and argv[i + 1].decode(errors="replace") == task
            ):
                return True
    return False


def verify_state(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    # 2026-09-25: the verify can write the verdict as a markdown heading ("## VERDICT: READY-TO-RESUBMIT"); the
    # anchored pattern missed it and wrongly excluded LGL-185. Same tolerance as the runner's own grep.
    verdicts = re.findall(r"^\s*#*\s*\**VERDICT\**\s*:\s*\**\s*([A-Z-]+)", txt, re.M)
    mvs = re.findall(r"^METHOD_VERSION:\s*(\S+)", txt, re.M)
    return (verdicts[-1] if verdicts else None), (mvs[-1] if mvs else None)


def diff_summary(want, got):
    changed = sorted(k for k in want if k in got and want[k] != got[k])
    gone = sorted(k for k in want if k not in got)
    new = sorted(k for k in got if k not in want)
    bits = []
    for lab, xs in (("changed", changed), ("missing", gone), ("added", new)):
        if xs:
            bits.append("%s %d: %s" % (lab, len(xs), ", ".join(xs[:3])))
    return "; ".join(bits) or "no file-level difference"


def check_task(task, zip_path, a):
    """Return (manifest or None, [reasons]). An empty list is the only 'fresh'."""
    why = []
    if not TASK_RE.match(task):
        return None, ["task id %r is not like LGL-131" % task]
    mp = zip_path + ".manifest.json"
    if not os.path.isfile(zip_path):
        return None, ["no ready zip %s" % zip_path]
    if not os.path.isfile(mp):
        return None, [
            "no manifest %s (zip was not built by the lane runner's package step)" % mp
        ]
    try:
        m = json.load(open(mp, encoding="utf-8"))
    except ValueError as e:
        return None, ["manifest unreadable: %s" % e]
    if m.get("task") != task:
        why.append("manifest names %s, not %s" % (m.get("task"), task))
    mfiles = m.get("files") or {}
    if not mfiles:
        why.append("manifest has no file hashes")
    # 1. the zip itself
    if file_sha(zip_path) != m.get("zip_sha256"):
        why.append("zip bytes changed since the manifest was written")
    try:
        with zipfile.ZipFile(zip_path) as z:
            if z.testzip() is not None:
                why.append("zip has a corrupt member")
            names = z.namelist()
            zfiles = zip_task_files(z, task)
    except zipfile.BadZipFile as e:
        return m, why + ["not a zip: %s" % e]
    if zfiles != mfiles:
        why.append(
            "zip members differ from the manifest (%s)" % diff_summary(mfiles, zfiles)
        )
    # 2. the package on disk
    pkg = os.path.join(a.pkg_root, task)
    if not os.path.isdir(pkg):
        why.append("no package on disk at %s" % pkg)
    else:
        dfiles = disk_pkg_files(pkg)
        if dfiles != mfiles:
            why.append(
                "STALE: package on disk changed since the zip was built (%s)"
                % diff_summary(mfiles, dfiles)
            )
    # 3. verify record + gate JSON
    ev = m.get("evidence") or {}
    vrec = [p for p in ev if os.path.basename(p) == task + ".verify.md"]
    gj = [p for p in ev if os.path.basename(p) == task + ".gate.json"]
    if not vrec:
        why.append("manifest records no verify record")
    if not gj:
        why.append("manifest records no gate JSON")
    for p, h in ev.items():
        if h is None:
            why.append(
                "evidence %s was missing when the zip was built" % os.path.basename(p)
            )
        elif not os.path.isfile(p):
            why.append("evidence %s is gone" % os.path.basename(p))
        elif file_sha(p) != h:
            why.append(
                "STALE: %s changed since the zip was built" % os.path.basename(p)
            )
    for p in vrec:
        if os.path.isfile(p):
            verdict, mv = verify_state(p)
            if verdict != "READY-TO-RESUBMIT":
                why.append("verify verdict is %s, not READY-TO-RESUBMIT" % verdict)
            cur = method_version(a.rules)
            if mv != cur:
                why.append(
                    "verify METHOD_VERSION %s is not the current %s (re-verify)"
                    % (mv, cur)
                )
    for p in gj:
        if os.path.isfile(p):
            try:
                gv = json.load(open(p, encoding="utf-8")).get("verdict")
            except ValueError:
                gv = "unreadable"
            if gv != "PASS":
                why.append("gate verdict is %s, not PASS" % gv)
    # 4. raw verifier.json
    raw = os.path.join(a.pkg_root, "_raw", task, "verifier.json")
    cur_raw = file_sha(raw) if os.path.isfile(raw) else None
    if cur_raw != m.get("raw_verifier_sha256"):
        why.append("STALE: _raw verifier.json changed since the zip was built")
    # 5. lifecycle state
    r_ts = read_tsv_latest(os.path.join(a.work, "ready.txt"), task)
    p_ts = read_tsv_latest(os.path.join(a.work, "parked.txt"), task)
    if not r_ts:
        why.append("not in ready.txt")
    elif p_ts and p_ts >= r_ts:
        why.append("parked at %s, after its last READY at %s" % (p_ts, r_ts))
    if listed(os.path.join(a.work, "accepted.txt"), task):
        why.append("on the EKW accepted list (never re-shipped)")
    if listed(os.path.join(a.work, "do_not_touch.txt"), task):
        why.append("on the EKW do-not-touch list")
    if live_runner(task):
        why.append("a lane runner is working on it right now")
    # 6. content audit of the zip bytes
    why += audit_members(task, names, zfiles)
    return m, why


def shipped_elsewhere(task, m, bundle_names, a):
    """Refuse a task whose exact bytes already went into a bundle other than the one(s) being (re)built now."""
    p = os.path.join(a.work, "shipped", task + ".json")
    if not os.path.isfile(p) or not m:
        return None
    prev = json.load(open(p, encoding="utf-8"))
    if (
        prev.get("pkg_hash") == pkg_hash(m.get("files") or {})
        and prev.get("bundle") not in bundle_names
    ):
        # 2026-09-29: a task DataOS never graded (0 reviews, a DataOS exception) sits on needs_regrade.txt, off the
        # queue, with its bytes unchanged by design. This refusal then stranded SCO-232 from ekw-v1-batch14
        # (2026-09-26) with no path back to a grade. Re-shipping the same bytes is exactly what a first grade
        # needs; a pass stays blocked by accepted.txt in check_task, and ekw_record_return.py takes the task off
        # needs_regrade.txt once a return grades it.
        if listed(os.path.join(a.work, "needs_regrade.txt"), task):
            return None
        return "these exact bytes are already in bundle %s" % prev.get("bundle")
    return None


def split_parts(name, ok, a):
    """[(bundle name, entries)]: --size N splits by count; otherwise split by summed zip size over --max-mb."""
    if a.size:
        chunks = [ok[i : i + a.size] for i in range(0, len(ok), a.size)]
    else:
        cap = a.max_mb * 1e6
        chunks, cur, tot = [], [], 0
        for e in ok:
            s = os.path.getsize(e[1])
            if cur and tot + s > cap:
                chunks.append(cur)
                cur, tot = [], 0
            cur.append(e)
            tot += s
        if cur:
            chunks.append(cur)
    if len(chunks) == 1:
        return [(name, chunks[0])]
    return [(name + string.ascii_lowercase[i], c) for i, c in enumerate(chunks)]


def possible_names(name, a):
    return {name + ".zip"} | {name + c + ".zip" for c in string.ascii_lowercase}


def write_bundle(name, entries, a):
    os.makedirs(a.out_dir, exist_ok=True)
    out = os.path.join(a.out_dir, name + ".zip")
    for p in (out, out + ".manifest.json"):
        if os.path.exists(p):
            os.remove(p)
    tmp = out + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for t, zp, _ in entries:
            with zipfile.ZipFile(zp) as zi:
                for n in zi.namelist():
                    if not n.endswith("/"):
                        zo.writestr(n, zi.read(n))
    # cold audit of the finished file: integrity, exactly the task roots we meant, every task byte-identical to
    # its manifest, and the per-task content audit again on the bundle bytes
    problems = []
    with zipfile.ZipFile(tmp) as z:
        if z.testzip() is not None:
            problems.append("corrupt member")
        names = z.namelist()
        roots = sorted({n.split("/", 1)[0] for n in names})
        want = sorted(t for t, _, _ in entries)
        if roots != want:
            problems.append("roots %d != tasks %d" % (len(roots), len(want)))
        for t, _, m in entries:
            tf = zip_task_files(z, t)
            if tf != m["files"]:
                problems.append("%s bytes differ from its manifest" % t)
            problems += [
                "%s: %s" % (t, w)
                for w in audit_members(
                    t, [n for n in names if n.startswith(t + "/")], tf
                )
            ]
    if problems:
        os.remove(tmp)
        sys.exit("REFUSED: bundle cold audit failed: %s" % "; ".join(problems[:10]))
    os.replace(tmp, out)
    man = {
        "bundle": os.path.basename(out),
        "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "method_version": method_version(a.rules),
        "bundle_sha": file_sha(out),
        "tasks": {t: {"zip": zp, "manifest": m} for t, zp, m in entries},
    }
    json.dump(man, open(out + ".manifest.json", "w", encoding="utf-8"), indent=1)
    sd = os.path.join(a.work, "shipped")
    os.makedirs(sd, exist_ok=True)
    for t, _, m in entries:
        json.dump(
            {
                "bundle": os.path.basename(out),
                "pkg_hash": pkg_hash(m["files"]),
                "at": man["built_at"],
            },
            open(os.path.join(sd, t + ".json"), "w", encoding="utf-8"),
        )
    print(
        "BUNDLE %s: %d tasks, %d bytes (%.1f MB), cold audit OK"
        % (out, len(entries), os.path.getsize(out), os.path.getsize(out) / 1e6)
    )
    print("  sha256:", man["bundle_sha"])
    print("  tasks:", " ".join(want))
    print("  manifest:", out + ".manifest.json")
    return out


def cmd_bundle(a):
    if a.tasks:
        tasks = a.tasks
    else:
        tasks = sorted(
            os.path.basename(p)[:-4]
            for p in glob.glob(os.path.join(a.work, "ready", "*.zip"))
            if TASK_RE.match(os.path.basename(p)[:-4])
        )
    mine = possible_names(a.name, a)
    ok, refused = [], []
    for t in tasks:
        zp = os.path.join(a.work, "ready", t + ".zip")
        m, why = check_task(t, zp, a)
        dup = shipped_elsewhere(t, m, mine, a)
        if dup:
            why.append(dup)
        if why:
            refused.append((t, why))
        else:
            ok.append((t, zp, m))
    print(
        "=== EKW freshness check: %d candidates, %d fresh, %d refused (method %s) ==="
        % (len(tasks), len(ok), len(refused), method_version(a.rules))
    )
    for t, why in refused:
        print("  REFUSED %s: %s" % (t, "; ".join(why)))
    if not ok:
        print("nothing shippable")
        sys.exit(1)
    for bname, part in split_parts(a.name, ok, a):
        write_bundle(bname, part, a)
    if refused:
        print("\n%d task(s) were EXCLUDED; they are not in any bundle." % len(refused))


def cmd_check(a):
    mp = a.bundle + ".manifest.json"
    if not os.path.isfile(a.bundle):
        print("STALE: no bundle at %s" % a.bundle)
        sys.exit(1)
    if not os.path.isfile(mp):
        print(
            "STALE: no bundle manifest %s - not built by ekw_bundle_upload.py. Do not upload."
            % mp
        )
        sys.exit(1)
    man = json.load(open(mp, encoding="utf-8"))
    bad = []
    if file_sha(a.bundle) != man.get("bundle_sha"):
        bad.append(("<bundle>", ["bundle zip bytes changed since it was built"]))
    with zipfile.ZipFile(a.bundle) as z:
        names = z.namelist()
        roots = sorted({n.split("/", 1)[0] for n in names})
        if roots != sorted(man["tasks"]):
            bad.append(("<bundle>", ["bundle roots differ from its manifest"]))
        for t, e in sorted(man["tasks"].items()):
            if zip_task_files(z, t) != (e.get("manifest") or {}).get("files"):
                bad.append((t, ["bundle bytes differ from the task manifest"]))
    for t, e in sorted(man["tasks"].items()):
        _, why = check_task(t, e["zip"], a)
        if why:
            bad.append((t, why))
    print(
        "=== pre-upload check %s: %d tasks, method now %s ==="
        % (os.path.basename(a.bundle), len(man["tasks"]), method_version(a.rules))
    )
    for t, why in bad:
        print("  STALE %s: %s" % (t, "; ".join(why)))
    if bad:
        print(
            "DO NOT UPLOAD. Rebuild the bundle (stale tasks are excluded automatically)."
        )
        sys.exit(1)
    print("FRESH: every task is byte-identical to what was verified. OK to upload.")


def parse(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bundle")
    b.add_argument("--name", required=True, help="bundle basename, e.g. ekw-v1-batch1")
    g = b.add_mutually_exclusive_group(required=True)
    g.add_argument("--tasks", nargs="+")
    g.add_argument(
        "--from-ready",
        action="store_true",
        help="every <TASK>.zip currently in <work>/ready/",
    )
    b.add_argument(
        "--size",
        type=int,
        default=0,
        help="split into parts of N tasks (overrides --max-mb)",
    )
    b.add_argument(
        "--max-mb",
        type=float,
        default=450.0,
        help="split so each part's task zips sum under this",
    )
    c = sub.add_parser("check")
    c.add_argument("bundle")
    for p in (b, c):
        p.add_argument("--work", default=WORK)
        p.add_argument("--pkg-root", default=PKG_ROOT)
        p.add_argument("--rules", default=RULES)
        p.add_argument("--out-dir", default=OUT_DIR)
    return ap.parse_args(argv)


def main(argv=None):
    a = parse(argv)
    if a.cmd == "bundle" and not re.match(r"^[A-Za-z0-9._-]+$", a.name):
        sys.exit(2)
    {"bundle": cmd_bundle, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    main()
