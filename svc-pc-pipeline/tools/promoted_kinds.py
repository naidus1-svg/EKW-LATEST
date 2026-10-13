#!/usr/bin/env python3
"""
promoted_kinds.py - C1 refinement (laptop, 18:55Z 2026-09-19), Fable's severity mapping
(_prompts/fable-severity/README.md, mapping-96.csv): 79 of 96 DataOS majors on 22 tasks already
had a deterministic signal, but every one is either in stage_and_zip.sh's ADVISORY set or a
verdict-only scan, so no fixer ever saw it. Promoting the WHOLE cell/scan to blocking is unsafe:
SVC-PC-2-7-0 (the one task DataOS accepted, zero majors) fires seven of the same families
(compound_criterion, duplicate_criterion_content, rubric_overspecification, undisclosed_terminology,
structural_audit, answer_preexposure_scan, cross_group_duplicate_scan) - a family-level gate would
have blocked the accepted task. This module promotes by finding KIND instead: for each of the 10
kinds below, only the specific sub-case Fable's row-level analysis found separates the 96 majors
from the accepted control.

Shared by build_review_union.py (folds matches into the union as findings) and
promoted_kinds_gate.py (a read-only CLI: exit 5 if anything fires, 0 otherwise - the coordinator
wires this into stage_and_zip.sh once it passes acceptance).

READ-ONLY: reads checks/*.csv, the newest available recheck summary.csv (live checks/recheck/, an
archived checks/recheck.expired-*/, or the newest review_workspace*/*/prior_verifications/
recheck_summary.csv - same freshness fallback build_review_union.py already uses) and that
directory's per-cell <cell>.json files. Never modifies anything.

Verified discrepancy against Fable's own README (recorded here, not silently "fixed" by guessing):
structural_audit pattern 1 ("placeholder_env_vs_named_files") DOES fire on SVC-PC-2-7-0 in the
current cell_details data (Board_Resolutions_2021.pdf, decision="fires"), contradicting the
README's claim that this kind does not fire on the control. Direct read of
work/cell_details.jsonl confirms it. structural_audit/pattern-1 is therefore NOT included in
PROMOTED_KINDS below (excluded from both the union fold-in and the blocking gate) pending the
coordinator's own review of this discrepancy - see fixes-1720-report.md's C1 section.
"""
from __future__ import annotations

import csv
import glob
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _qc_common import DEFAULT_CORPUS_ROOT, extract_filename_tokens

PIPE_ROOT = Path("/root/qc/stream-pipe")
FRESH_SLACK = 5

# answer_preexposure_scan.py's own FAIL_OVERLAP constant (fail severity at overlap >= this).
# Duplicated here rather than imported: that module is a corpus-wide scan script, not a library,
# and importing it would pull in its argparse/markitdown-heavy module-load path unnecessarily.
_ANSWER_PREEXPOSURE_FAIL_OVERLAP = 0.6

# Extended document-noun suffix set for the fabricated_unfilenamed_fact heuristic below: a "record"
# is a named FILE or a document-titled phrase, not a bare entity/vendor name. _qc_common's own
# _DOC_SUFFIXES doesn't include "minutes" (needed for the 39-3-0 "Q4 Board Minutes" example).
_RECORD_TITLE_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9]*(?:\s+[A-Za-z0-9]+){0,4}\s+"
    r"(?:Minutes|Report|Register|Ledger|Statement|Statements|Memo|Letter|Package|Model|Plan|"
    r"Reconciliation|Journal|Workpaper|Summary|Agreement|Schedule)\b"
)


def newest_recheck_dir(task: str) -> Path | None:
    """Same freshness-fallback chain as build_review_union.py's blocking_gate_cells resolution,
    plus the top-level /root/qc/_recheck/<task>/ location (Fable's README: for exactly 5-4-0,
    9-5-0, 11-4-0, 25-7-0 and 39-3-0, only /root/qc/_recheck/ exists - stream-pipe's own
    checks/recheck/ is expired on every task): a live checks/recheck/ dir, else the
    numerically-newest checks/recheck.expired-<N>/, else /root/qc/_recheck/<task>/, else the
    mtime-newest review_workspace*/*/prior_verifications/ (which holds recheck_summary.csv + the
    per-cell context needed alongside it) - whichever of these carries the newest summary.csv."""
    pipe = PIPE_ROOT / task
    checks = pipe / "checks"
    live = checks / "recheck"
    if (live / "summary.csv").is_file():
        return live
    cands = []
    for d in glob.glob(str(checks / "recheck.expired-*")):
        m = re.search(r"recheck\.expired-(\d+)$", d)
        if m and (Path(d) / "summary.csv").is_file():
            cands.append((int(m.group(1)), Path(d)))
    best_local = max(cands)[1] if cands else None

    top_level = Path("/root/qc/_recheck") / task
    best_top = top_level if (top_level / "summary.csv").is_file() else None

    pv_cands = []
    for p in glob.glob(str(Path("/root/qc") / "review_workspace*" / task / "prior_verifications")):
        pp = Path(p)
        if (pp / "recheck_summary.csv").is_file():
            pv_cands.append((pp.stat().st_mtime, pp))
    best_pv = max(pv_cands)[1] if pv_cands else None

    def _mtime(d: Path | None) -> float:
        if d is None:
            return -1.0
        f = d / "summary.csv"
        if not f.is_file():
            f = d / "recheck_summary.csv"
        return os.path.getmtime(f) if f.is_file() else -1.0

    candidates = [c for c in (best_local, best_top, best_pv) if c is not None]
    if not candidates:
        return None
    return max(candidates, key=_mtime)


def _load_cell_json(recheck_dir: Path, cell: str) -> dict:
    p = recheck_dir / f"{cell}.json"
    if not p.is_file():
        return {}
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if isinstance(d, list):
        d = {"results": d}
    items = d.get("results") if isinstance(d.get("results"), list) else [d]
    return items[0] if items else {}


def _scan_rows(task: str, scan: str) -> list[dict]:
    p = PIPE_ROOT / task / "checks" / f"{scan}.csv"
    if not p.is_file():
        return []
    try:
        with open(p, newline="") as f:
            return list(csv.DictReader(f))
    except Exception:  # noqa: BLE001
        return []


def _is_named_record(text: str) -> str | None:
    """A filename-shaped token or a capitalized document-title phrase in `text`, or None. This is
    what separates 'naming a record absent from the environment' (39-3-0's 'Q4 Board Minutes',
    67-3-0's 'Cap_Table_2021_v2.xlsx') from a bare entity/vendor claim (2-7-0's 'NovaTex', which
    names no file or document title at all)."""
    files = extract_filename_tokens(text)
    if files:
        return next(iter(files))
    m = _RECORD_TITLE_RE.search(text)
    return m.group(0) if m else None


def promoted_findings(task: str) -> list[dict]:
    """One entry per promoted-kind hit: {promoted_kind, cell_or_scan, detail, evidence}."""
    out: list[dict] = []
    recheck_dir = newest_recheck_dir(task)

    # 1. source_citation_existence / kind == golden_cites_absent_file (sub_case A)
    if recheck_dir is not None:
        item = _load_cell_json(recheck_dir, "source_citation_existence")
        for f in item.get("findings", []) or []:
            if f.get("kind") == "golden_cites_absent_file":
                out.append(
                    {
                        "promoted_kind": "source_citation_existence/golden_cites_absent_file",
                        "cell_or_scan": "source_citation_existence",
                        "detail": f"{f.get('citation')} at {f.get('location')}",
                        "evidence": f.get("evidence", ""),
                    }
                )

    # 2. golden_citation_scan / found_where == MISSING
    for r in _scan_rows(task, "golden_citation_scan"):
        if r.get("found_where") == "MISSING":
            out.append(
                {
                    "promoted_kind": "golden_citation_scan/MISSING",
                    "cell_or_scan": "golden_citation_scan",
                    "detail": r.get("cited_name", ""),
                    "evidence": f"checks/golden_citation_scan.csv: {r}",
                }
            )

    # 3. structural_audit / pattern == 1, decision == fires -- EXCLUDED, see module docstring
    #    (verified to fire on SVC-PC-2-7-0's current bytes, contradicting the README).

    # 4. fabricated_unfilenamed_fact naming a record absent from the environment (not a bare entity claim)
    if recheck_dir is not None:
        item = _load_cell_json(recheck_dir, "fabricated_unfilenamed_fact")
        for f in item.get("findings", []) or []:
            if f.get("kind") != "fabricated_unfilenamed_fact":
                continue
            # `claim` alone (not claim_context, which carries surrounding, legitimately-sourced
            # text too): the record must be named IN the fabricated assertion itself, or a
            # co-occurring real filename elsewhere in context produces a false match (verified:
            # 2-7-0's NovaTex claim_context happens to mention Q4_CSAT_Report.xlsx nearby for
            # unrelated, correctly-sourced reasons - that is not what's being fabricated).
            record = _is_named_record(f.get("claim", ""))
            if record:
                out.append(
                    {
                        "promoted_kind": "fabricated_unfilenamed_fact/absent_record",
                        "cell_or_scan": "fabricated_unfilenamed_fact",
                        "detail": f"names absent record {record!r}: {f.get('claim', '')[:200]}",
                        "evidence": f.get("evidence", "")[:400],
                    }
                )

    # 5. rubric_consistency_scan / kind in {band_text_binary, unsourced_expected_token}
    for r in _scan_rows(task, "rubric_consistency_scan"):
        if r.get("kind") in ("band_text_binary", "unsourced_expected_token"):
            out.append(
                {
                    "promoted_kind": f"rubric_consistency_scan/{r.get('kind')}",
                    "cell_or_scan": "rubric_consistency_scan",
                    "detail": f"{r.get('criterion_ids', '')}: {r.get('detail', '')}",
                    "evidence": f"checks/rubric_consistency_scan.csv: {r}",
                }
            )

    # 6. criterion_groundedness / hard == unreachable_criterion list
    if recheck_dir is not None:
        item = _load_cell_json(recheck_dir, "criterion_groundedness")
        for f in item.get("unreachable_criterion", []) or []:
            out.append(
                {
                    "promoted_kind": "criterion_groundedness/unreachable_criterion",
                    "cell_or_scan": "criterion_groundedness",
                    "detail": f"{f.get('criterion')}: token {f.get('token')!r} ({f.get('kind')})",
                    "evidence": f.get("reason", ""),
                }
            )

    # 7. rubric_overspecification / overspec_type in {count_pinned, name_pinned}
    if recheck_dir is not None:
        item = _load_cell_json(recheck_dir, "rubric_overspecification")
        for f in item.get("findings", []) or []:
            if f.get("overspec_type") in ("count_pinned", "name_pinned"):
                out.append(
                    {
                        "promoted_kind": f"rubric_overspecification/{f.get('overspec_type')}",
                        "cell_or_scan": "rubric_overspecification",
                        "detail": f"{f.get('criterion')}: {f.get('pinned_value', '')}",
                        "evidence": f.get("quote", "")[:400],
                    }
                )

    # 8. escape_hatch_scan / where == golden
    for r in _scan_rows(task, "escape_hatch_scan"):
        if r.get("where") == "golden":
            out.append(
                {
                    "promoted_kind": "escape_hatch_scan/where=golden",
                    "cell_or_scan": "escape_hatch_scan",
                    "detail": f"{r.get('id_or_loc', '')}: {r.get('token_or_path', '')}",
                    "evidence": f"checks/escape_hatch_scan.csv: {r}",
                }
            )

    # 9. answer_preexposure_scan / source_file contains "(final)" AND overlap >= the scan's own
    #    fail threshold (0.6, answer_preexposure_scan.py FAIL_OVERLAP). Tightened 19:15Z: filename
    #    alone false-fires on a "(final)" source file that is genuinely unrelated to the golden
    #    sentence it happened to pair with (a low-overlap row); 17-7-0's real leak is >= 0.6.
    for r in _scan_rows(task, "answer_preexposure_scan"):
        if "(final)" not in (r.get("source_file") or "").lower():
            continue
        try:
            overlap = float(r.get("overlap", 0) or 0)
        except (TypeError, ValueError):
            continue
        if overlap < _ANSWER_PREEXPOSURE_FAIL_OVERLAP:
            continue
        out.append(
            {
                "promoted_kind": "answer_preexposure_scan/final_document",
                "cell_or_scan": "answer_preexposure_scan",
                "detail": f"{r.get('source_file', '')} (overlap={overlap})",
                "evidence": f"golden_sentence: {r.get('golden_sentence', '')[:200]}",
            }
        )

    # 10. judge_scope_under_inclusion (any finding - no further sub-condition given)
    if recheck_dir is not None:
        item = _load_cell_json(recheck_dir, "judge_scope_under_inclusion")
        for f in item.get("findings", []) or []:
            out.append(
                {
                    "promoted_kind": "judge_scope_under_inclusion",
                    "cell_or_scan": "judge_scope_under_inclusion",
                    "detail": f"{f.get('group', '')}/{f.get('criterion', '')}: {f.get('quote', '')[:200]}",
                    "evidence": f.get("implied_source", ""),
                }
            )

    return out


PROMOTED_KIND_NAMES = [
    "source_citation_existence/golden_cites_absent_file",
    "golden_citation_scan/MISSING",
    "fabricated_unfilenamed_fact/absent_record",
    "rubric_consistency_scan/band_text_binary",
    "rubric_consistency_scan/unsourced_expected_token",
    "criterion_groundedness/unreachable_criterion",
    "rubric_overspecification/count_pinned",
    "rubric_overspecification/name_pinned",
    "escape_hatch_scan/where=golden",
    "answer_preexposure_scan/final_document",
    "judge_scope_under_inclusion",
]

# Verified empirically against SVC-PC-2-7-0's CURRENT bytes (not just Fable's frozen snapshot):
# these 2 (of the 11) DO fire on the accepted control, contradicting the README's claim that they
# separate cleanly. structural_audit/pattern-1 is excluded earlier (never added to
# PROMOTED_KIND_NAMES at all - same discrepancy, see module docstring). All 3 discrepancies are
# reported in fixes-1720-report.md's C1 section for the coordinator's own review; they stay in
# PROMOTED_KIND_NAMES (so build_review_union.py still surfaces them to the fixer as advisory
# findings - a real, likely-genuine defect on the 22 tasks either way) but are excluded from the
# BLOCKING gate below, since a false major-block on the one accepted task is the one thing the
# acceptance test forbids outright.
#
# 19:15Z precision check (10-task sample, outside the 22, seed 20260919): a subagent read each
# sampled criterion + its judge.toml files= and judged true/false positive by hand.
# judge_scope_under_inclusion scored 2/10 true positives (SVC-PC-2-4-0, SVC-PC-79-1-0), well below
# the coordinator's 8/10 bar - removed from BLOCKING_SAFE_KIND_NAMES (stays in PROMOTED_KIND_NAMES,
# still surfaced to the fixer as advisory). Dominant false-positive pattern the sample found: a
# criterion phrased "Expected: <exact number/fact>" bakes the ground truth into the rubric text
# itself, so the judge grades the deliverable's own stated claim against that given value and never
# actually needs to open the "implied_source" file the detector guessed at - the detector has no way
# to tell a self-contained Expected clause from a genuinely source-dependent one.
BLOCKING_SAFE_KIND_NAMES = [
    k
    for k in PROMOTED_KIND_NAMES
    if k
    not in (
        "criterion_groundedness/unreachable_criterion",
        "rubric_overspecification/name_pinned",
        # also verified empirically: 2-7-0's deliverables_03/d6 pins "Exactly 5 asks, lettered A-E"
        # - a count_pinned hit, but the count IS explicitly stated in instruction.md line 10
        # ("five lettered asks, A through E"), so the pin is legitimate, not overspecification.
        # count_pinned's own finding schema carries no field distinguishing "pinned to an
        # instruction-stated count" from "pinned to an invented one" - would need to grep
        # instruction.md for the pinned value to separate them, which this module does not do.
        "rubric_overspecification/count_pinned",
        # 2/10 true positives on the 19:15Z precision sample - see comment block above.
        "judge_scope_under_inclusion",
    )
]
