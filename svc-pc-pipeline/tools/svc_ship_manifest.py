#!/usr/bin/env python3
"""Shared freshness rules for anything that ships an SVC-PC task to DataOS. Stdlib only.

Why this exists (2026-09-22, the stale-zip hole, second occurrence): 10-4-0, 10-5-0, 12-2-0 and 53-1-0 were
zipped into _v7/ready/ at ~04:00Z, a later fix pass re-edited their corpus packages and its adversarial
verify said NOT-READY at 08:15-09:22Z, and batch1 was bundled at 13:34Z from the 04:00Z zips anyway. All
four were rejected. The first occurrence is memory `cached-probe-result-must-match-final-bytes` (a zip
step reused an oracle score from before the fix rounds). Both times a file on disk was trusted as current
because it existed, not because anything proved it matched the bytes being shipped.

The rule this module encodes: a per-task zip is shippable ONLY while
  1. the corpus package still hashes to what the zip was built from (nothing edited it since), AND
  2. the zip file itself still hashes to what the builder wrote (nobody replaced it), AND
  3. the verify record is byte-identical to the one the build used, says READY-TO-RESUBMIT, and carries the
     CURRENT METHOD_VERSION from svc_fix_method_rules.md (a rules change forces re-verification), AND
  4. for a graded task, the eval-regrade record is byte-identical to the build's and says PASS, AND
  5. the task is not on the accepted freeze list.
The builder writes a manifest next to every zip (`<zip>.manifest.json`); `check_task_zip` re-derives every
field from disk and returns the list of reasons it is stale. An empty list is the only "fresh".
"""

import fnmatch, hashlib, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, "svc_fix_method_rules.md")

JUNK_GLOBS = (
    "_scratch_*",
    "*tamper*",
    "*.preedit",
    "*.orig",
    "*.bak",
    "lease.json",
    "*.pyc",
    ".DS_Store",
)


def is_junk(path):
    b = os.path.basename(path)
    return any(
        fnmatch.fnmatch(b, g) for g in JUNK_GLOBS
    ) or "__pycache__" in path.replace("\\", "/")


def method_version(rules_path=RULES):
    """The METHOD_VERSION on line 1 of the rules file. Raises if absent: shipping without it is not allowed."""
    with open(rules_path, encoding="utf-8") as f:
        first = f.readline().strip()
    m = re.match(r"METHOD_VERSION:\s*(\S+)", first)
    if not m:
        raise RuntimeError("no METHOD_VERSION on line 1 of %s" % rules_path)
    return m.group(1)


def _walk(root):
    for dp, dirs, fs in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__" and not is_junk(d))
        for f in sorted(fs):
            full = os.path.join(dp, f)
            if not is_junk(full):
                yield full


def tree_hash(root):
    """sha256 over (relative path, bytes) of every non-junk file under root, in sorted order."""
    h = hashlib.sha256()
    for f in sorted(_walk(root)):
        h.update(os.path.relpath(f, root).replace("\\", "/").encode())
        h.update(b"\0")
        with open(f, "rb") as fh:
            h.update(fh.read())
        h.update(b"\0")
    return h.hexdigest()


def zip_tree_hashes(zip_path):
    """{task: tree_hash} computed over each top-level task folder INSIDE a zip, same algorithm as tree_hash.
    Lets a bundle built without a manifest be compared byte-for-byte against the current corpus.
    """
    import zipfile

    per = {}
    with zipfile.ZipFile(zip_path) as z:
        for zi in z.infolist():
            n = zi.filename
            if n.endswith("/"):
                continue
            # Info-ZIP `zip` stores non-ASCII names without the UTF-8 flag (bit 11); Python then decodes them as
            # CP437 and a name like "Cirrus Sleep <em dash> ..." reads as mojibake. Recover the real UTF-8 name
            # so the hash compares like with like (found 2026-09-22: 6 harvest bundles falsely read as stale).
            name = n
            if not zi.flag_bits & 0x800:
                try:
                    name = n.encode("cp437").decode("utf-8")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    name = n
            task, _, rel = name.partition("/")
            if not rel or is_junk(name):
                continue
            per.setdefault(task, []).append((rel, n))
        out = {}
        for task, files in per.items():
            h = hashlib.sha256()
            for rel, n in sorted(files):
                h.update(rel.encode())
                h.update(b"\0")
                h.update(z.read(n))
                h.update(b"\0")
            out[task] = h.hexdigest()
    return out


def pkg_hash(pkg):
    """Hash of the WHOLE package (instruction, environment, tests, solution): what actually ships."""
    return tree_hash(pkg)


def file_sha(path):
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_verdict(path):
    """(verdict, method_version) from a verify record. verdict is READY / NOT-READY / None."""
    if not os.path.isfile(path):
        return None, None
    text = open(path, encoding="utf-8", errors="replace").read()
    v = re.findall(r"VERDICT:\s*\**\s*(READY-TO-RESUBMIT|NOT-READY)", text)
    mv = re.findall(r"^METHOD_VERSION:\s*(\S+)\s*$", text, flags=re.M)
    return (
        ("READY" if v[-1] == "READY-TO-RESUBMIT" else "NOT-READY") if v else None
    ), (mv[-1] if mv else None)


def regrade_verdict(path):
    try:
        return json.load(open(path)).get("verdict")
    except Exception:
        return None


def accepted_set(path):
    """Tasks that must never be reworked or shipped: our DataOS passes (accepted.txt) PLUS the team-wide
    do-not-touch list that tools/svc_build_freeze.py builds from both trackers (do_not_touch.txt in the same
    directory: submitted/finished by anyone, or owned by another person)."""
    out = set()
    for p in (path, os.path.join(os.path.dirname(path), "do_not_touch.txt")):
        if os.path.isfile(p):
            out |= {
                ln.strip() for ln in open(p) if ln.strip() and not ln.startswith("#")
            }
    return out


def manifest_path(zip_path):
    return zip_path + ".manifest.json"


def build_manifest(task, pkg, zip_path, verify_path, regrade_path, graded):
    vv, vmv = verify_verdict(verify_path) if verify_path else (None, None)
    return {
        "task": task,
        "graded": bool(graded),
        "pkg_hash": pkg_hash(pkg),
        "zip_sha": file_sha(zip_path),
        "verify_path": verify_path,
        "verify_sha": file_sha(verify_path) if verify_path else None,
        "verify_verdict": vv,
        "method_version": vmv,
        "regrade_path": regrade_path,
        "regrade_sha": file_sha(regrade_path) if regrade_path else None,
        "regrade_verdict": regrade_verdict(regrade_path) if regrade_path else None,
    }


def check_task_zip(zip_path, pkg, accepted_path, rules_path=RULES):
    """Return (manifest, [reasons stale]). Empty list = fresh and shippable."""
    why = []
    mp = manifest_path(zip_path)
    if not os.path.isfile(zip_path):
        return None, ["no zip at %s" % zip_path]
    if not os.path.isfile(mp):
        return None, [
            "no manifest %s (built before the freshness gate, or not by svc_build_upload_zip.py)"
            % mp
        ]
    m = json.load(open(mp))
    task = m.get("task")
    if task in accepted_set(accepted_path):
        why.append("on the accepted freeze list (never re-ship a pass)")
    if file_sha(zip_path) != m.get("zip_sha"):
        why.append("zip bytes changed since the builder wrote them")
    if not os.path.isdir(pkg):
        why.append("corpus package missing: %s" % pkg)
    elif pkg_hash(pkg) != m.get("pkg_hash"):
        why.append(
            "corpus package EDITED since this zip was built (the stale-zip hole)"
        )
    cur_mv = method_version(rules_path)
    if m.get("fast_track"):
        # Owner-authorised fast-track: the reviewer verdict is waived, the oracle proof must still hold byte-for-byte.
        op = m.get("oracle_json")
        if not op or file_sha(op) != m.get("oracle_sha"):
            why.append("fast-track oracle record changed or missing since the build")
    elif m.get("graded", True) or m.get("verify_path"):
        vp = m.get("verify_path")
        if not vp or file_sha(vp) != m.get("verify_sha"):
            why.append(
                "verify record changed or missing since the build (re-verified after zipping)"
            )
        vv, vmv = verify_verdict(vp) if vp else (None, None)
        if vv != "READY":
            why.append("verify verdict is %s, not READY-TO-RESUBMIT" % vv)
        if vmv != cur_mv:
            why.append(
                "verified under method %s, current is %s (re-verify under the current rules)"
                % (vmv, cur_mv)
            )
    if m.get("graded", True):
        rp = m.get("regrade_path")
        if not rp or file_sha(rp) != m.get("regrade_sha"):
            why.append("eval-regrade record changed or missing since the build")
        if regrade_verdict(rp) != "PASS":
            why.append("eval-regrade verdict is %s, not PASS" % regrade_verdict(rp))
    return m, why
