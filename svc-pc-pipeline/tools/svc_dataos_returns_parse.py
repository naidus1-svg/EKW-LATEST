#!/usr/bin/env python3
"""Parse a DataOS "batch_N_SVC_with_runs.zip" return: per task, the oracle and solver rewards (evaluations/*/verifier/reward.json)
and the comprehensive-review verdicts (verifications/comprehensive_review_*.md, whose transcript ends with the reviewer's JSON),
then apply Khiem's pass rule (2026-09-20 00:55Z): a review with no MAJOR check is a pass (needs_revision counts as a pass), and
a task passes only when it has at least 2 reviews and EVERY review was read and has no major (pipeline version 8: one major,
or one unreadable review, fails the task).

The review .md carries the whole prompt, which itself contains an EXAMPLE verdict JSON ("overall_verdict": "reject"); only the
LAST JSON object with an overall_verdict key is the reviewer's own answer.

Usage: python tools/svc_dataos_returns_parse.py ZIP [--out returns.json] [--extract-reviews DIR]
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import zipfile


def review_items(d: dict) -> list:
    """The reviewer's list of checks: `checks` in the older format, `findings` in the Answer Check format."""
    for key in ("checks", "findings"):
        if isinstance(d.get(key), list):
            return d[key]
    return []


def last_verdict_json(text: str) -> dict | None:
    """Return the last JSON object in text that has an overall_verdict key."""
    idx = [m.start() for m in re.finditer(r'"overall_verdict"', text)]
    for pos in reversed(idx):
        start = text.rfind("{", 0, pos)
        # walk forward to the matching close brace
        depth = 0
        for i in range(start, len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    chunk = text[start : i + 1]
                    try:
                        d = json.loads(chunk)
                        if (
                            isinstance(d, dict)
                            and "overall_verdict" in d
                            and (
                                isinstance(d.get("checks"), list)
                                or isinstance(d.get("findings"), list)
                            )
                        ):
                            return d
                    except Exception:  # noqa: BLE001
                        pass
                    break
    return None


def review_summary(md: str) -> dict:
    status = re.search(r"^## status\s*\n(\S+)", md, re.M)
    d = last_verdict_json(md)
    if not d:
        return {
            "job_status": status.group(1) if status else None,
            "verdict": None,
            "major_count": None,
            "majors": [],
            "minors": [],
            "parsed": False,
        }
    majors, minors = [], []
    for c in review_items(d):
        sev = str(c.get("severity", "")).lower()
        cid = str(
            c.get("check")
            or c.get("id")
            or c.get("check_id")
            or c.get("name")
            or c.get("type")
            or "?"
        )
        if sev == "major":
            majors.append(cid)
        elif sev == "minor":
            minors.append(cid)
    return {
        "job_status": status.group(1) if status else None,
        "verdict": str(d.get("overall_verdict", "")).lower(),
        "major_count": len(majors),
        "declared_major_count": d.get("major_count"),
        "majors": majors,
        "minors": minors,
        "summary": str(d.get("summary", ""))[:400],
        "parsed": True,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("zip")
    ap.add_argument("--out")
    ap.add_argument(
        "--extract-reviews",
        help="directory to write each review's verdict JSON as <task>__<file>.json",
    )
    a = ap.parse_args()
    z = zipfile.ZipFile(a.zip)
    names = z.namelist()
    tasks = sorted({n.split("/")[0] for n in names if n.startswith("SVC-PC-")})
    out = {}
    for t in tasks:
        rec = {"evals": collections.OrderedDict(), "reviews": [], "qc": []}
        for n in names:
            if (
                n.startswith(t + "/")
                and "/evaluations/" in n
                and n.endswith("verifier/reward.json")
            ):
                kind = re.sub(r"eval_\d+__attempt_\d+__", "", n.split("/")[3])
                try:
                    d = json.loads(z.read(n).decode("utf-8", "replace"))
                    rec["evals"].setdefault(kind, []).append(d.get("reward"))
                except Exception as e:  # noqa: BLE001
                    rec["evals"].setdefault(kind, []).append(f"err:{e}")
        for n in names:
            if n.startswith(t + "/") and "/verifications/" in n and n.endswith(".md"):
                md = z.read(n).decode("utf-8", "replace")
                s = review_summary(md)
                s["file"] = n.split("/")[-1]
                m = re.search(r"___(.+)\.md$", s["file"])
                s["reviewer"] = m.group(1) if m else "?"
                (rec["qc"] if s["file"].startswith("qc_") else rec["reviews"]).append(s)
                if a.extract_reviews and s["parsed"]:
                    os.makedirs(a.extract_reviews, exist_ok=True)
                    d = last_verdict_json(md)
                    with open(
                        os.path.join(a.extract_reviews, f"{t}__{s['file'][:-3]}.json"),
                        "w",
                        encoding="utf-8",
                    ) as f:
                        json.dump(d, f, indent=1)
        out[t] = rec

    print(
        f"\n{'task':14} {'oracle':>10} {'gpt-sol':>8} {'t2-opus':>8} {'cc-opus':>8}  reviews: verdict/majors (reviewer)  -> rule"
    )
    for t, rec in out.items():
        ev = rec["evals"]

        def r(k):
            v = ev.get(k, [])
            return (
                ",".join(
                    (
                        "-"
                        if x is None
                        else (f"{x:.2f}" if isinstance(x, (int, float)) else str(x)[:6])
                    )
                    for x in v
                )
                if v
                else "-"
            )

        revs = rec["reviews"]
        passes = sum(1 for s in revs if s["parsed"] and s["major_count"] == 0)
        unparsed = sum(1 for s in revs if not s["parsed"])
        verdicts = " | ".join(
            f"{(s['verdict'] or 'UNPARSED')[:14]}/{s['major_count'] if s['parsed'] else '?'} ({s['reviewer'][:20]})"
            for s in revs
        )
        rule = "PASS" if len(revs) >= 2 and passes == len(revs) else "FAIL"
        if unparsed:
            rule += f" ({unparsed} review(s) unparsed)"
        qc = ",".join((s["verdict"] or "?") for s in rec["qc"]) or "-"
        print(
            f"{t:14} {r('oracle'):>10} {r('terminus-2__gpt-5.6-sol'):>8} {r('terminus-2__claude-opus-5'):>8} {r('claude-code__claude-opus-5'):>8}  {verdicts}  qc={qc} -> {rule} ({passes} of {len(revs)} with 0 majors)"
        )
        for s in revs:
            if s["majors"]:
                print(f"      majors from {s['reviewer']}: {s['majors']}")
    if a.out:
        json.dump(out, open(a.out, "w", encoding="utf-8"), indent=1)
        print("wrote", a.out)


if __name__ == "__main__":
    main()
