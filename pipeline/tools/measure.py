#!/usr/bin/env python3
"""
measure.py — automatic measurement over a gdpval-assess run on GDPval tasks.

Reads a batch_review.json and reports the calibration signal the user asked for:
"run GDPval through the QC and see whether it flags tasks as not good for RL."
Because GDPval is a partially-reliable gold benchmark, a high reject rate means
our gates are too harsh — so this script makes the reject/flag rate and the
per-dimension drivers easy to read, and emits an adjudication worksheet of every
flag for the manual sanity-check step.

Critically, it SEPARATES adapter/convention-driven dims (artifacts of mapping
GDPval into our schema — see build_corpus.py) from GDPval-content dims, so a
converter artifact is never misread as a GDPval quality defect.

Usage:
    python measure.py runs/<run>/batch_review.json
    python measure.py runs/<run>/batch_review.json --worksheet adjudication_10.md
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

# Dims whose result reflects the GDPval->verifier.json adapter or a convention
# mismatch, NOT GDPval task quality. Reported separately; excluded from the
# headline GDPval flag rate.
ADAPTER_DIMS = {
    "verifier_count_in_range",          # GDPval rubrics are 28-69 items vs our [6,20]
    "verifier_outcome_grader_present",  # grading_role is invented by the adapter
    "verifier_spec_parseable",          # we generate the spec -> always parses
    "metadata_completeness",            # we synthesize task.toml -> always complete
}

# Eval-data verifier dims: designed to use per-rubric pass/fail across model
# trials. GDPval has no evals/ data, so these run in degraded/spec-only mode,
# which prior calibration reports flag as unreliable ("never emit a confident
# score on a degraded eval-data gate"). Reported as a separate bucket; excluded
# from the headline content flag rate.
DEGRADED_DIMS = {
    "verifier_rubric_construct_validity",
    "verifier_outcome_coverage",
    "verifier_missing_critical_dimensions",
    "verifier_discriminative_power",
}

NON_CONTENT = ADAPTER_DIMS | DEGRADED_DIMS

FLAG_VERDICTS = {"needs_review", "reject_fixable", "reject_structural"}
REJECT_VERDICTS = {"reject_fixable", "reject_structural"}


def content_findings(sample: dict) -> list[dict]:
    return [f for f in sample["all_findings"]
            if f.get("applicable") and f["dimension"] not in NON_CONTENT]


def adapter_findings(sample: dict) -> list[dict]:
    return [f for f in sample["all_findings"]
            if f.get("applicable") and f["dimension"] in ADAPTER_DIMS]


def degraded_findings(sample: dict) -> list[dict]:
    return [f for f in sample["all_findings"]
            if f.get("applicable") and f["dimension"] in DEGRADED_DIMS]


def content_verdict(sample: dict) -> str:
    """What the verdict would be ignoring adapter dims: did any GDPval-content
    blocking dim hit sev>=2, or any dim sev>=1? Coarse, for the headline only —
    the real verdict still lives in sample['verdict']."""
    cf = content_findings(sample)
    if any(f["severity"] >= 2 and f.get("gate_role") == "blocking" for f in cf):
        return "reject/needs_review (content)"
    if any(f["severity"] >= 1 for f in cf):
        return "accept_with_fixes (content)"
    return "accept (content)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("review", type=Path, help="path to batch_review.json")
    ap.add_argument("--worksheet", type=Path, default=None,
                    help="also write a per-flag adjudication worksheet (markdown)")
    args = ap.parse_args()

    d = json.loads(args.review.read_text())
    samples = d["samples"]
    n = len(samples)

    # ── Headline: verdict mix (as the pipeline reports it) ───────────────────
    verdicts = Counter(s["verdict"] for s in samples)
    flagged = [s for s in samples if s["verdict"] in FLAG_VERDICTS]
    rejected = [s for s in samples if s["verdict"] in REJECT_VERDICTS]

    print(f"\n=== GDPval calibration · N={n} ({d.get('spec_name')} {d.get('spec_version')}) ===\n")
    print("Pipeline verdict mix (as-is):")
    for v, c in verdicts.most_common():
        print(f"  {c:3d}  {100*c/n:5.1f}%  {v}")
    print(f"\n  flag rate   (needs_review|reject*): {len(flagged)}/{n} = {100*len(flagged)/n:.1f}%")
    print(f"  reject rate (reject* only)        : {len(rejected)}/{n} = {100*len(rejected)/n:.1f}%")

    # ── Per-dim sev>=2 drivers, split content / degraded / adapter ───────────
    content_hist, degraded_hist, adapter_hist = Counter(), Counter(), Counter()
    for s in samples:
        for f in s["all_findings"]:
            if f.get("applicable") and f["severity"] >= 2:
                dim = f["dimension"]
                bucket = (adapter_hist if dim in ADAPTER_DIMS
                          else degraded_hist if dim in DEGRADED_DIMS
                          else content_hist)
                bucket[dim] += 1

    print("\nGDPval-content dims firing at sev>=2 (the real calibration signal):")
    for dim, c in content_hist.most_common() or [("(none)", 0)]:
        print(f"  {c:3d}/{n}  {dim}")
    print("\nDegraded eval-data verifier dims at sev>=2 (no eval data on GDPval — low confidence):")
    for dim, c in degraded_hist.most_common() or [("(none)", 0)]:
        print(f"  {c:3d}/{n}  {dim}")
    print("\nAdapter/convention dims at sev>=2 (NOT GDPval quality — expected artifacts):")
    for dim, c in adapter_hist.most_common() or [("(none)", 0)]:
        print(f"  {c:3d}/{n}  {dim}")

    # ── Flag rate attributable to content dims alone ─────────────────────────
    content_flagged = [s for s in samples
                       if any(f["severity"] >= 2 for f in content_findings(s))]
    print(f"\n  tasks with >=1 GDPval-content dim at sev>=2: "
          f"{len(content_flagged)}/{n} = {100*len(content_flagged)/n:.1f}%")

    # ── Content-only verdict view ────────────────────────────────────────────
    cv = Counter(content_verdict(s) for s in samples)
    print("\nContent-only verdict view (adapter dims ignored):")
    for v, c in cv.most_common():
        print(f"  {c:3d}  {100*c/n:5.1f}%  {v}")

    # ── Adjudication worksheet ───────────────────────────────────────────────
    if args.worksheet:
        write_worksheet(args.worksheet, samples)
        print(f"\nadjudication worksheet -> {args.worksheet}")


def write_worksheet(path: Path, samples: list[dict]) -> None:
    """One section per flagged task with every sev>=2 content finding and its
    evidence, plus a verdict column for the human to fill: legit / too-harsh."""
    lines = ["# GDPval calibration — adjudication worksheet",
             "",
             "For each flag: is it a **legit** GDPval defect or **too-harsh** gate over-reach?",
             "Adapter/convention dims are listed separately and should not count as GDPval defects.",
             ""]
    for s in samples:
        if s["verdict"] not in FLAG_VERDICTS:
            continue
        lines.append(f"## {s['sample_id']} — `{s['verdict']}`")
        lines.append(f"_{s.get('one_line','')}_\n")
        cf = [f for f in content_findings(s) if f["severity"] >= 2]
        af = [f for f in adapter_findings(s) if f["severity"] >= 2]
        if cf:
            lines.append("| dim | sev | conf | fixability | headline | evidence | **verdict (legit/too-harsh)** |")
            lines.append("|---|---|---|---|---|---|---|")
            for f in sorted(cf, key=lambda f: -f["severity"]):
                ev = (f.get("evidence_quote") or "").replace("|", "\\|").replace("\n", " ")[:160]
                hl = (f.get("headline") or "").replace("|", "\\|")
                lines.append(f"| {f['dimension']} | {f['severity']} | {f['confidence']} | "
                             f"{f['fixability']} | {hl} | {ev} |  |")
        else:
            lines.append("_No GDPval-content dim at sev>=2 — flag is driven by adapter/convention or sev-1 only._")
        if af:
            lines.append("\n<sub>adapter/convention sev>=2 (not GDPval quality): "
                         + ", ".join(f"{f['dimension']}({f['severity']})" for f in af) + "</sub>")
        lines.append("")
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
