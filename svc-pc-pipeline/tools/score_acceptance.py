#!/usr/bin/env python3
"""score_acceptance.py - GATE-V2 verifier spec (03-acceptance-test.md,
2026-09-19), item 10: score against the fact, not the check id.

DataOS's 8 majors (5 on 8-2-0, 2 on 67-1-0, plus the 54-2-0 ceiling) are
matched against a review's findings by OBJECT NAME (a distinctive filename,
dollar figure, or criterion id unique to that fact) appearing in a MAJOR-
severity check's justification text. This is a mechanical proxy for the
spec's own three-part rule (same object + same mechanism + same consequence,
at severity major) - it is NOT a substitute for a human reading each match,
only for the counting/aggregation. Every match this script claims should be
spot-checked against the review JSON before SCORE.md is treated as final;
this script's own output says so on every row.

Usage:
    python3 score_acceptance.py --results-dir DIR --out SCORE.md
`DIR` holds one JSON per review, named <task>.r<N>.json (03-acceptance-test.md
section 3's own naming), each the canon-schema CR.json (overall_verdict,
major_count, minor_count, checks[]).
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path

# object-name pattern -> (fact id, task, one-line description)
FACTS = [
    (r"Sales_Orders\.xlsx", r"(1\s*Mi?B|1,048,576|_MAX_FILE_SIZE|skipped.{0,20}too large|skipped_too_large)",
     "M67-A", "SVC-PC-67-1-0", "1 MiB skip on Sales_Orders.xlsx"),
    (r"Customer_Master\.xlsx", r"(undifferentiated|pre-existing environment|0\.24|r003.{0,40}r008|duplicate)",
     "M67-B", "SVC-PC-67-1-0", "files= over-inclusion (Customer_Master.xlsx mixed with deliverable)"),
    (r"(1,329,407|1\.3\s*MB|oversized.{0,20}docx|DOCX.{0,20}skipped)", r"(skipped|too large|false rejection)",
     "M8-A", "SVC-PC-8-2-0", "1.33 MB DOCX deliverable skipped (false rejection)"),
    (r"(growth target|150%|\$4-5M|20-22 FTE|28 (year-end )?FTE)", r"(ambiguit|three (materially )?different|unresolved|TBD)",
     "M8-B", "SVC-PC-8-2-0", "growth-target ambiguity (three readings)"),
    (r"(c4|c5|c6|a10|d1\b|e3\b|e2\b)", r"(instruction never (asks|requests|names)|false rejection|golden-author choice)",
     "M8-C", "SVC-PC-8-2-0", "1.4 overreach (c4-c6/a10/d1/e3/e2)"),
    (r"\$8-\$76", r"(\$8-\$99|no pricing matrix|does not exist|conflict)",
     "M8-D", "SVC-PC-8-2-0", "1.5 unsourced $8-$76 rubric value"),
    (r"\(final\)\.doc", r"(leak|shingle|verbatim|copied|answer exposure|1\.6)",
     "M8-E", "SVC-PC-8-2-0", "leaked near-final (final).doc answer document"),
    (r"(\$8-\$99|Supplier Scorecard)", r"(\$8-\$76|conflict|contradict|wrong side)",
     "M8-F", "SVC-PC-8-2-0", "1.7 source conflict ($8-$99 vs $8-$76)"),
]

CODEX_54_2_0_ALLOWED = ["r09", "compound", "r05", "coverage exploit", "r06", "r11", "closure"]


def load_reviews(results_dir: Path) -> dict[str, list[dict]]:
    """{task: [review_json, ...]} from <task>.r<N>.json files."""
    out: dict[str, list[dict]] = {}
    for p in sorted(glob.glob(str(results_dir / "*.r*.json"))):
        if p.endswith(".stats.json") or ".raw.txt" in p:
            continue
        m = re.match(r"(.+)\.r\d+\.json$", Path(p).name)
        if not m:
            continue
        task = m.group(1)
        try:
            d = json.loads(Path(p).read_text())
        except json.JSONDecodeError:
            continue
        d["_source_file"] = p
        out.setdefault(task, []).append(d)
    return out


def major_texts(review: dict) -> str:
    return " ".join(
        f"{c.get('id')} {c.get('name')} {c.get('justification','')}"
        for c in review.get("checks", [])
        if c.get("severity") == "major"
    )


def check_facts(review: dict) -> dict[str, bool]:
    text = major_texts(review)
    return {
        fact_id: bool(re.search(obj_pat, text, re.I) and re.search(mech_pat, text, re.I))
        for obj_pat, mech_pat, fact_id, task, desc in FACTS
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    reviews = load_reviews(args.results_dir)
    lines = ["# SCORE.md - acceptance test result (03-acceptance-test.md)", "",
             "**Mechanical object-name matching only - every claimed match must be spot-checked",
             "against the source review JSON before this is treated as final.**", ""]

    # --- Rule 4.4: deterministic gate (independent of any review) ---
    lines.append("## Rule 4.4: deterministic gate (judge_input_report.py)")
    jir_ok = None
    for task in ("SVC-PC-67-1-0", "SVC-PC-8-2-0"):
        jir_path = args.results_dir / f"{task}.judge_input.json"
        if jir_path.is_file():
            d = json.loads(jir_path.read_text())
            fired = d.get("blocking_major", False)
            lines.append(f"- {task}: blocking_major={fired} ({jir_path})")
            if task == "SVC-PC-67-1-0":
                jir_ok = fired
        else:
            lines.append(f"- {task}: **NOT RUN** ({jir_path} missing)")
            if task == "SVC-PC-67-1-0":
                jir_ok = False
    lines.append("")

    # --- Rules 4.1/4.2: recall + per-review floor ---
    lines.append("## Rules 4.1 (union recall) / 4.2 (per-review floor)")
    fact_ids = [f[2] for f in FACTS]
    union_hit = {fid: False for fid in fact_ids}
    per_review_rows = []
    for task, revs in sorted(reviews.items()):
        if task == "SVC-PC-54-2-0":
            continue
        for i, rev in enumerate(revs, start=1):
            hits = check_facts(rev)
            n_hit = sum(hits.values())
            per_review_rows.append((task, i, rev.get("major_count"), n_hit, hits, rev["_source_file"]))
            for fid, ok in hits.items():
                union_hit[fid] = union_hit[fid] or ok

    lines.append("| task | review | major_count | facts hit (/8) | which |")
    lines.append("|---|---|---|---|---|")
    floor_pass = True
    for task, i, mc, n_hit, hits, src in per_review_rows:
        which = ", ".join(fid for fid, ok in hits.items() if ok) or "-"
        lines.append(f"| {task} | r{i} | {mc} | {n_hit} | {which} |")
        if n_hit < 5:
            floor_pass = False
    n_union = sum(union_hit.values())
    lines.append("")
    lines.append(f"**Union recall: {n_union}/8** ({', '.join(fid for fid, ok in union_hit.items() if ok) or 'none'})")
    lines.append(f"**Per-review floor (>=5/8 every review): {'PASS' if (floor_pass and per_review_rows) else 'FAIL or NO DATA'}**")
    lines.append("")

    # --- Rule 4.3: ceiling on 54-2-0 ---
    lines.append("## Rule 4.3: ceiling on SVC-PC-54-2-0 (major_count <= 1)")
    ceiling_pass = True
    for i, rev in enumerate(reviews.get("SVC-PC-54-2-0", []), start=1):
        mc = rev.get("major_count")
        majors = [c for c in rev.get("checks", []) if c.get("severity") == "major"]
        outside_allowed = [c for c in majors if not any(k in (c.get("justification", "") + c.get("name", "")).lower() for k in CODEX_54_2_0_ALLOWED)]
        ok = (mc or 0) <= 1 and not outside_allowed
        ceiling_pass = ceiling_pass and ok
        lines.append(f"- r{i}: major_count={mc}, majors outside the Codex-allowed set: {len(outside_allowed)} -> {'PASS' if ok else 'FAIL'}")
    if not reviews.get("SVC-PC-54-2-0"):
        ceiling_pass = False
        lines.append("- **NO DATA for SVC-PC-54-2-0**")
    lines.append(f"**Ceiling: {'PASS' if ceiling_pass else 'FAIL or NO DATA'}**")
    lines.append("")

    # --- Rule 4.5: no regression on M8-C/D/E ---
    lines.append("## Rule 4.5: no regression on M8-C, M8-D, M8-E (major, >=2 reviews)")
    regress_pass = True
    n_8_2_0_reviews = len(reviews.get("SVC-PC-8-2-0", []))
    for fid in ("M8-C", "M8-D", "M8-E"):
        n = sum(1 for task, i, mc, n_hit, hits, src in per_review_rows if hits.get(fid))
        ok = n >= 2
        regress_pass = regress_pass and ok
        lines.append(f"- {fid}: hit in {n}/{n_8_2_0_reviews} reviews -> {'PASS' if ok else 'FAIL'}")
    lines.append(f"**No regression: {'PASS' if regress_pass else 'FAIL'}**")
    lines.append("")

    overall = (n_union == 8) and floor_pass and ceiling_pass and bool(jir_ok) and regress_pass and bool(per_review_rows)
    lines.append(f"## Overall: {'PASS - lanes/ZIP_HOLD may come off' if overall else 'FAIL - lanes/ZIP_HOLD stays'}")
    lines.append("")
    lines.append("## Open disagreements (not silently dropped or conceded)")
    lines.append("- M8-B (growth-target ambiguity): DataOS calls it a major; at least one of our reviews has argued it is resolvable. Put to Khiem.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines))
    print(f"wrote {args.out}: union={n_union}/8 floor={floor_pass} ceiling={ceiling_pass} jir={jir_ok} regression={regress_pass} overall={overall}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
