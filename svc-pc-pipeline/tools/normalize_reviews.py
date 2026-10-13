#!/usr/bin/env python3
"""normalize_reviews.py - recover reviewer verdicts that were discarded only for their shape.

fix_from_reviews.sh's canon_ok() accepts a reviewer file only when it has "overall_verdict" and "checks" as a LIST. The Sonnet
reviewer (and occasionally GLM) often writes a complete verdict with "checks" as an object keyed by check id, or "verdict" in place of
"overall_verdict". The dispatcher quarantines such a file as CR.<r>.round<N>.bad.<stamp>.json and re-runs the whole review (about 4M
cache-read and 85K output tokens each), and the re-run often ends as a fragment instead (the response hits max_tokens and the extractor
keeps only the continuation message), so tasks sat at "one reviewer done" for hours: 11-2-0, 24-4-0, 53-6-0 and about ten others.

  normalize_reviews.py scan    report what would be recovered
  normalize_reviews.py apply   write the recovered files (the dispatcher's own quarantine is left alone)

A file is recovered only when: overall verdict text present ("overall_verdict" or "verdict"); "checks" is a list, or an object whose
values are objects, with at least 8 entries; every check has a severity in {major, minor, good, info}; a given major_count equals the
number of severity-major checks (when absent it is computed); the file is at least as new as the newest shipped file of the task
(a review of older bytes is not recovered); and no review of that task and reviewer is running. Candidates are the canonical file
itself (kept aside as .rawshape.<stamp>.json) and the newest .bad. file when the canonical file is missing or not canonical.
"""

import glob
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, "/root/qc/tools")
import oracle_refresh as orf  # noqa: E402  (newest_staged)

Q = "/root/qc"
SP = f"{Q}/stream-pipe"
SEV = {"major", "minor", "good", "info"}
apply = len(sys.argv) > 1 and sys.argv[1] == "apply"


def canon(d):
    return (
        isinstance(d, dict)
        and "overall_verdict" in d
        and isinstance(d.get("checks"), list)
    )


def normalize(d):
    """(canonical dict, note) or (None, reason)."""
    if not isinstance(d, dict):
        return None, "not an object"
    verdict = d.get("overall_verdict") or d.get("verdict")
    if not isinstance(verdict, str) or not verdict:
        return None, "no verdict text"
    checks = d.get("checks")
    if isinstance(checks, dict):
        items = []
        for k, v in checks.items():
            if not isinstance(v, dict):
                return None, "a checks value is not an object"
            m = re.match(r"(\d+\.\d+)", str(k))
            it = dict(v)
            it.setdefault("id", m.group(1) if m else str(k))
            items.append(it)
        checks = items
    if not isinstance(checks, list) or len(checks) < 8:
        return None, "checks missing or shorter than 8"
    for c in checks:
        if not isinstance(c, dict) or "id" not in c:
            return None, "a check has no id"
        if str(c.get("severity", "")).lower() not in SEV:
            return None, f"unknown severity {c.get('severity')!r}"
    majors = sum(1 for c in checks if str(c.get("severity")).lower() == "major")
    minors = sum(1 for c in checks if str(c.get("severity")).lower() == "minor")
    out = dict(d)
    out["overall_verdict"] = verdict
    out["checks"] = checks
    mc = d.get("major_count")
    if isinstance(mc, int) and not isinstance(mc, bool):
        if mc != majors:
            return None, f"major_count {mc} disagrees with {majors} major checks"
    else:
        out["major_count"] = majors
    if not isinstance(d.get("minor_count"), int) or isinstance(
        d.get("minor_count"), bool
    ):
        out["minor_count"] = minors
    out["_normalized_by"] = "normalize_reviews.py"
    return out, f"{len(checks)} checks, {majors} major"


def live(task, reviewer):
    ps = subprocess.run(
        ["ps", "-eo", "args", "--no-headers"], capture_output=True, text=True
    ).stdout
    return (
        re.search(
            rf"run_workspace_review\.py --task {task} .*--reviewer {reviewer}\b", ps
        )
        is not None
    )


def load(f):
    try:
        return json.load(open(f))
    except Exception:
        return None


def rounds_present(d, r):
    """Round numbers that have a canonical-named file or a quarantined .bad. file for reviewer r (archived .pre-reopen- files do not count)."""
    out = set()
    for f in glob.glob(f"{d}/CR.{r}.round*.json"):
        m = re.search(r"round(\d+)(?:\.bad\.[^/]*)?\.json$", f)
        if m:
            out.add(int(m.group(1)))
    return sorted(out)


stamp = int(time.time())
n = 0
for d in sorted(glob.glob(f"{SP}/SVC-PC-*")):
    t = os.path.basename(d)
    if not re.fullmatch(r"SVC-PC-\d+-\d+-\d+", t):
        continue
    for r in ("glm", "sonnet"):
        for rnd in rounds_present(d, r):
            cf = f"{d}/CR.{r}.round{rnd}.json"
            cur = load(cf) if os.path.exists(cf) else None
            if canon(cur):
                continue
            cands = []
            if cur is not None:
                cands.append((cf, "in place"))
            for b in sorted(
                glob.glob(f"{d}/CR.{r}.round{rnd}.bad.*.json"),
                key=os.path.getmtime,
                reverse=True,
            ):
                cands.append((b, "quarantined"))
            for path, kind in cands:
                got, note = normalize(load(path))
                if got is None:
                    continue
                newest, rel = orf.newest_staged(t)
                if os.path.getmtime(path) + 5 < newest:
                    print(
                        f"{t} {r}: {os.path.basename(path)} is older than {rel}; not recovered"
                    )
                    continue
                if live(t, r):
                    print(f"{t} {r}: a {r} review is running; not touching it")
                    break
                n += 1
                print(
                    f"{t} {r} round{rnd}: recover {kind} {os.path.basename(path)} ({note}, verdict {got['overall_verdict']})"
                )
                if apply:
                    if kind == "in place":
                        os.replace(cf, f"{d}/CR.{r}.round{rnd}.rawshape.{stamp}.json")
                    with open(cf + ".tmp", "w") as f:
                        json.dump(got, f, indent=2)
                    os.replace(cf + ".tmp", cf)
                break
print(f"{n} reviewer file(s) {'recovered' if apply else 'recoverable'}")
