#!/usr/bin/env python3
"""gate_diff.py — compare the QC gates listed on an agents.turing pipeline page
against the *live* gate vocabulary used in the Omega tracker.

Repeatable process (see README block at bottom / the chat write-up):
  1. PAGE side  — paste the pipeline page's Quality Dimensions into a small
     YAML/txt list mapped to canonical snake_case tokens (page_tokens below,
     or pass --page page.txt with one token per line).
  2. DOC side   — export the tracker "Tasks" tab as CSV; this script mines the
     QC-reasoning columns for every snake_case gate token and counts how many
     tasks cite each.
  3. DIFF       — prints three buckets:
       A  on BOTH            (aligned)
       B  PAGE-only          (candidate outdated / low-signal on this page)
       C  DOC-only           (coverage gap on this page)

Usage:
  gate_diff.py --tasks "Omega - Task Tracker - Tasks.csv" [--page page_tokens.txt]
"""
import csv, re, collections, argparse, sys

# Columns in the Tasks tab that carry QC reasoning text (0-indexed).
REASON_COLS = (18, 22, 23)          # QA Feedback / Task Quality / Quality Summary & Reasoning

# Roll-up labels & task-specific artifact names that are NOT atomic gates.
NOISE = {
    'core_success_rate', 'strict_quality', 'output_quality', 'expert_quality',
    'ic_recommendation_memo', 'eyrie_underwriting_model', 'vendor_recommendation_memo',
    'vendor_evaluation_workbook', 'coverage_model', 'ic_memo',
}

# Default: the 20 Quality Dimensions on pipeline page /17 ("Post-QA GDPVal AR Trigger").
# Replace via --page when auditing a different page.
DEFAULT_PAGE = {
    "role_and_deliverable", "instruction_input_consistency", "output_instruction_alignment",
    "output_file_consistency", "metadata_completeness", "self_containedness", "file_format_check",
    "output_file_presence", "output_format_match", "overall_gdpval_fit", "professional_complexity",
    "feasibility_and_clarity", "computer_performability", "output_substantiveness", "output_chart_quality",
    "output_layout_professionalism", "expert_fixed_factual_inconsistencies", "expert_missed_improvements",
    "expert_improvement_delta", "expert_improvement_fidelity",
}

TOKEN_RE = re.compile(r'\b[a-z][a-z0-9]+(?:_[a-z0-9]+)+\b')
SUFFIX_RE = re.compile(r'__(gpt\w*|opus\w*|expert_improved)$')   # strip per-model suffixes


def base(tok):
    return SUFFIX_RE.sub('', tok)


def family(k):
    if k.startswith('verifier_') or k == 'strict_verifier_quality':
        return 'VERIFIER-QC'
    if 'authenticity' in k or k == 'expert_reason_is_human_written':
        return 'AUTHENTICITY'
    return 'OTHER'


def mine_doc(path):
    counts = collections.Counter()
    with open(path, newline='') as fh:
        rows = list(csv.reader(fh))
    for r in rows[1:]:
        txt = ' '.join(r[i] for i in REASON_COLS if len(r) > i)
        found = {base(m) for m in TOKEN_RE.findall(txt)} - NOISE
        for f in found:
            counts[f] += 1
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tasks', required=True, help='Tasks-tab CSV export')
    ap.add_argument('--page', help='txt file, one canonical page token per line')
    args = ap.parse_args()

    page = DEFAULT_PAGE
    if args.page:
        page = {l.strip() for l in open(args.page) if l.strip() and not l.startswith('#')}

    counts = mine_doc(args.tasks)
    doc = set(counts)

    both = sorted(page & doc, key=lambda k: -counts[k])
    page_only = sorted(page - doc)
    doc_only = sorted(doc - page, key=lambda k: -counts[k])

    print(f"\nPAGE gates: {len(page)}   DOC gates: {len(doc)}   aligned: {len(both)}")
    print("\n### B  PAGE-ONLY  (candidate outdated / low-signal on this page)")
    for k in page_only:
        print(f"    {k}")
    print("\n### A  ON BOTH  (aligned)   [n tasks citing]")
    for k in both:
        print(f"    {counts[k]:3}  {k}")
    print("\n### C  DOC-ONLY  (coverage gap on this page)")
    for grp in ('VERIFIER-QC', 'AUTHENTICITY', 'OTHER'):
        rows = [k for k in doc_only if family(k) == grp]
        if rows:
            print(f"  -- {grp} --")
            for k in rows:
                print(f"    {counts[k]:3}  {k}")


if __name__ == '__main__':
    main()
