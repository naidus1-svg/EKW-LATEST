#!/usr/bin/env python3
"""build_review_union.py - fix_from_reviews.sh's mechanical step: build ONE findings file (fix_plan.md's CR.json shape) from
everything that blocks a task: the two workspace reviewers' majors, the deterministic gate cells that block the zip, the golden's
own oracle score, and any adjudication that found a false rejection.

Usage (unchanged):
    python3 build_review_union.py --task TASK --glm CR.glm.roundN.json --sonnet CR.sonnet.roundN.json \
        [--recheck-csv checks/recheck/summary.csv] [--oracle-json probes/oracle.json] --out CR.union.roundN.json
New optional arguments: --corpus-root, --pipe-dir, --adjudicate-json, --no-latest.
Exit 0 always; an input that fails to parse contributes zero findings (logged to stderr) rather than aborting.

Rewritten 2026-09-19 (laptop) after an audit of every hand-off to the fix-plan model. What it now does that it did not:

  1. GATE CELLS carry the cell's own findings (`details`, verbatim from <recheck>/<cell>.json), a written per-cell `playbook`
     (gate_playbooks.py: what the check measures, the exact procedure, what never to do, which op expresses the fix, how it is
     re-checked) and the head of the check module's docstring (`docs`). Before, 66 of 148 findings were one sentence: "fix whatever the
     check name indicates". metadata_leak findings also carry the criterion's own text and EVERY expected value the metadata text
     matches (the check reports only the first).
  2. ORACLE findings carry the criterion's rubric text, weight and the oracle total, beside the judge's verdict_text.
  3. The reviewers' verdicts used are the NEWEST canonical review of each reviewer (by file time, archived pre-reopen files included),
     not the file the dispatcher named. A re-opened task's dispatcher still passes round0, which predates the earlier fixes; the fixer
     was told to fix majors that were already fixed (1-5-0, 8-4-0, 12-5-0). Findings from a review older than the newest file are
     marked possibly_fixed.
  4. A reviewer verdict with major_count > 0 but no check marked major (6 files, e.g. 77-0-0 r1) no longer yields nothing: an
     `unlisted-majors` finding carries the reviewer's summary and matrix. Severity spellings and empty justification fields are handled.
  5. PRIOR ATTEMPTS: plan notes and the APPLIED / NOOP / FAILED outcome lines of every earlier plan for the task, so a later round
     sees what was tried and what did not apply (94 NOOP and 57 FAILED edits were never reported back before).
  6. ADJUDICATE.json (45 files, 347 criteria judged false rejections) was written by the old gate track and read by nothing. A
     false-rejection entry newer than every file of the task is a finding again. An older one is NOT counted (the file is never
     rewritten after a fix, so it would re-list criteria a later round already rewrote and park the task on them); it is listed
     under context.stale_adjudications for the fixer to check while it edits for another reason.
"""

from __future__ import annotations

import argparse
import csv as _csv
import glob
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import gate_playbooks as GP
except Exception as _exc:  # noqa: BLE001
    GP = None
    print(
        f"WARN: gate_playbooks unavailable ({_exc}); gate findings fall back to the generic sentence",
        file=sys.stderr,
    )
try:
    import promoted_kinds as PK
except Exception as _exc:  # noqa: BLE001
    PK = None
    print(f"WARN: promoted_kinds unavailable ({_exc}); promoted-kind findings skipped", file=sys.stderr)

DEFAULT_CORPUS = os.environ.get(
    "CORPUS", "/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready"
)
FRESH_SLACK = 5  # seconds

# Best-effort: catch file paths a reviewer's prose names that gather_files_text.py's fixed set would NOT already include.
_EXT = r"(?:xlsx|xls|docx|pptx|csv|json|pdf|txt|md|toml)"
FILE_PATTERNS = [
    r"environment/initial_workspace/[^\s\"']+?\." + _EXT + r"\b",
    r"solution/files/[^\s\"']+?\." + _EXT + r"\b",
    r"tests/deliverables[\w./-]*/judge\.toml",
    r"tests/deliverables[\w./-]*/judge_inputs/[^\s\"']+?\." + _EXT + r"\b",
    r"tests/task_prompt\.txt",
    r"tests/reward\.toml",
    r"\binstruction\.md\b",
    r"\btask\.toml\b",
    r"\bjudge\.toml\b",
]


def extract_affected_files(text: str) -> list[str]:
    found: list[str] = []
    for pat in FILE_PATTERNS:
        for m in re.findall(pat, text or ""):
            if m not in found:
                found.append(m)
    return found


# ---------------------------------------------------------------------------
# Gate rule, ported from stage_and_zip.sh (that file is owned elsewhere and must not be imported). Keep in sync by hand.
# ---------------------------------------------------------------------------
GATE = {
    "criterion_groundedness",
    "compound_criterion",
    "duplicate_criterion_content",
    "same_file_requirement_duplicate",
    "weight_application",
    "environment_size_budget",
    "task_metadata_completeness",
    "dependency_pin",
    "instruction_requirement_coverage",
    "fabricated_unfilenamed_fact",
    "golden_groundedness",
    "golden_arithmetic",
    "source_citation_existence",
    "cell_address_pinned",
    "rubric_overspecification",
    "environment_input",
    "metadata_leak",
    "answer_key_rubric_leak",
    "spelling_grammar",
}
ADVISORY = {
    "pinned_value_prescreen",
    "environment_size_budget",
    "criterion_groundedness",
    "compound_criterion",
    "duplicate_criterion_content",
    "same_file_requirement_duplicate",
    "instruction_requirement_coverage",
    "fabricated_unfilenamed_fact",
    "golden_groundedness",
    "golden_arithmetic",
    "source_citation_existence",
    "cell_address_pinned",
    "rubric_overspecification",
    "spelling_grammar",
    "judge_file_scope_breadth",
    "task_metadata_completeness",
    "dependency_pin",
    "harness_fragility",
    "judge_determinism_config_lint",
    "test_coverage_absence",
    "unrequested_deliverable_source",
    "structural_audit",
    "undisclosed_terminology",
    "rubric_text_lint",
    "tab_naming",
    "word_ban_false_trigger",
    "deliverable_count",
    "source_truncation",
}
ZSCAN_PREFIXES = (
    "formula_cache",
    "quantifier_scope",
    "escape_hatch",
    "source_reliability",
    "rubric_consistency",
    "answer_preexposure",
    "instruction_input",
    "cross_group_dup",
)

GATE_FIX_DIRECTION_FALLBACK = (
    "Deterministic actuator check '{cell}' blocks shipping (stage_and_zip.sh GATE-V2 3.4/3.6, not in ADVISORY). Read this "
    "finding's `playbook` and `details` first, then the current judge.toml/instruction.md/golden content below."
)

# ---------------------------------------------------------------------------
# C1 (laptop, 18:25Z/18:40Z 2026-09-19): the 11 canonical scans plus 3 C1-addendum scans, and the 4 named
# ADVISORY-set actuator cells. Neither family reached this union before: the 11 scans' own checks/<scan>.csv
# were written every gate_task.sh pass and read by nothing downstream, and the 4 actuator cells sit in the
# ADVISORY set (blocking_gate_cells() above explicitly skips ADVISORY cells - correctly, for the zip gate) but
# that same skip meant the fixer never saw them either. 96 DataOS majors on 22 tasks were filed on exactly
# these two families (evidence: _prompts/verify/dataos-fresh/majors.csv). Emitting them here does not change
# blocking_gate_cells()'s zip-gate behavior at all; it only adds them to the fixer's input.
# ---------------------------------------------------------------------------
SCAN_NAMES = [
    "formula_cache_scan",
    "quantifier_scope_scan",
    "escape_hatch_scan",
    "source_reliability_scan",
    "rubric_consistency_scan",
    "answer_preexposure_scan",
    "instruction_input_scan",
    "cross_group_duplicate_scan",
    "discretion_pin_scan",
    "golden_citation_scan",
    "muststrip_scan",
    "tiered_criterion_scan",
    "citation_unverifiable_scan",
    "asof_date_missing_scan",
    "judge_group_size_scan",
]
# fail always triggers a finding; these two also trigger on warn (per the coordinator's 18:25Z spec).
SCAN_WARN_INCLUDED = {"answer_preexposure_scan", "golden_citation_scan"}
ADVISORY_ACTUATOR_CELLS = [
    "source_citation_existence",
    "golden_arithmetic",
    "criterion_groundedness",
    "golden_groundedness",
]
SCAN_ROW_CAP = 40


def _read_scan_verdict(checks_dir: Path, scan: str) -> str | None:
    vp = checks_dir / f"{scan}.verdict.csv"
    if not vp.is_file():
        return None
    try:
        with open(vp, newline="") as f:
            rows = list(_csv.DictReader(f))
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None
    row = rows[0]
    for k, v in row.items():
        if k != "task_id":
            return v
    return None


def _read_scan_rows(checks_dir: Path, scan: str, cap: int = SCAN_ROW_CAP) -> tuple[list[dict], int]:
    """(rows, n_cut). Rows verbatim from checks/<scan>.csv, capped."""
    p = checks_dir / f"{scan}.csv"
    if not p.is_file():
        return [], 0
    try:
        with open(p, newline="") as f:
            rows = list(_csv.DictReader(f))
    except Exception:  # noqa: BLE001
        return [], 0
    if len(rows) > cap:
        return rows[:cap], len(rows) - cap
    return rows, 0


def blocking_scan_names(task: str, pipe: Path) -> set[str]:
    """C1 severity fix (coordinator, 20:12Z): the set of scan/cell names carrying at least one
    BLOCKING promoted-kind finding for this task, read from checks/promoted_kinds.txt (the gate's
    own last-run output) when present, else a direct computation via promoted_kinds.promoted_findings()
    filtered to BLOCKING_SAFE_KIND_NAMES (the same set the gate CLI itself would mark BLOCKING). Used
    by scan_findings() to decide severity: a failing scan is major only if IT is what the gate
    actually blocks on; otherwise it's minor context, per the four 18:55Z-19:48Z park incidents
    (2-6-0, 11-4-0, 17-7-0, 26-4-0) where a whole uncalibrated scan verdict (40+ rows, answer_preexposure_scan,
    source_reliability_scan, rubric_consistency_scan, instruction_input_scan) parked a task neither
    reviewer flagged."""
    p = pipe / "checks" / "promoted_kinds.txt"
    kinds: set[str] = set()
    if p.is_file():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = _GATE_LINE_RE.match(line)
            if not m:
                continue
            status, line_task, kind, _detail = m.groups()
            if status == "BLOCKING" and line_task == task:
                kinds.add(kind)
    elif PK is not None:
        try:
            hits = PK.promoted_findings(task)
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: promoted_kinds.promoted_findings({task!r}) raised {exc}", file=sys.stderr)
            hits = []
        kinds = {h["promoted_kind"] for h in hits if h["promoted_kind"] in PK.BLOCKING_SAFE_KIND_NAMES}
    return {_PROMOTED_KIND_CELL.get(k, k) for k in kinds}


def scan_findings(checks_dir: Path | None, blocking_scans: set[str] | None = None) -> list[dict]:
    """One finding per scan whose verdict is fail (or warn, for the two warn-included scans).
    severity is "major" only when the scan's own name is in `blocking_scans` (the gate's calibrated
    blocking set for this task, from blocking_scan_names()); every other failing scan is "minor" -
    still a full finding with rows/evidence/playbook (context for the fixer), just excluded from
    the union's major_count/majors_present so it can no longer park a task on its own."""
    if checks_dir is None or not checks_dir.is_dir():
        return []
    blocking_scans = blocking_scans or set()
    out: list[dict] = []
    for scan in SCAN_NAMES:
        verdict = _read_scan_verdict(checks_dir, scan)
        if verdict is None:
            continue
        trigger = verdict == "fail" or (verdict == "warn" and scan in SCAN_WARN_INCLUDED)
        if not trigger:
            continue
        rows, n_cut = _read_scan_rows(checks_dir, scan)
        severity = "major" if scan in blocking_scans else "minor"
        out.append(
            {
                "id": f"scan-{scan}",
                "kind": "scan",
                "class": scan,
                "severity": severity,
                "criterion_ids": [],
                "affected_files": [],
                "description": (
                    f"Deterministic scan '{scan}' = {verdict!r} ({len(rows)}{'+' if n_cut else ''} finding row(s); "
                    f"{n_cut} cut for space). "
                    + (
                        "This scan is in the calibrated promoted-kinds blocking set for this task (checks/promoted_kinds.txt "
                        "or a BLOCKING-safe kind fired directly) - a genuine major."
                        if severity == "major"
                        else "This scan is NOT in the calibrated promoted-kinds blocking set for this task: kept as minor "
                        "context (rows/playbook below), does not count toward major_count and will not park the task on "
                        "its own. DataOS reviewers may still catch what it finds - check reviewer_major findings too."
                    )
                ),
                "evidence": f"{checks_dir / (scan + '.csv')}: verdict={verdict}",
                "fix_direction": f"Read this finding's `playbook`, then every row in `rows` (all {len(rows)} shown, {n_cut} cut).",
                "playbook": GP.playbook_text(scan) if GP else "",
                "rows": rows,
                "rows_cut": n_cut,
            }
        )
    return out


_PROMOTED_KIND_CELL = {
    "source_citation_existence/golden_cites_absent_file": "source_citation_existence",
    "golden_citation_scan/MISSING": "golden_citation_scan",
    "fabricated_unfilenamed_fact/absent_record": "fabricated_unfilenamed_fact",
    "rubric_consistency_scan/band_text_binary": "rubric_consistency_scan",
    "rubric_consistency_scan/unsourced_expected_token": "rubric_consistency_scan",
    "criterion_groundedness/unreachable_criterion": "criterion_groundedness",
    "rubric_overspecification/count_pinned": "rubric_overspecification",
    "rubric_overspecification/name_pinned": "rubric_overspecification",
    "escape_hatch_scan/where=golden": "escape_hatch_scan",
    "answer_preexposure_scan/final_document": "answer_preexposure_scan",
    "judge_scope_under_inclusion": "judge_scope_under_inclusion",
}


def promoted_kind_findings(task: str) -> list[dict]:
    """C1 refinement (18:55Z): fold promoted_kinds.py's row-level matches into the union as their
    own findings - one of Fable's 10 kinds firing on THIS task, with the underlying cell's playbook.
    Distinct from advisory_actuator_findings()/scan_findings() above, which promote a whole
    cell/scan on any warn/fail; these are the specific sub-cases verified not to fire on the one
    DataOS-accepted control task (SVC-PC-2-7-0) - see promoted_kinds.py's module docstring for the
    3 kinds excluded even from this list because they DO fire on the control despite Fable's README
    describing them as safe."""
    if PK is None:
        return []
    try:
        hits = PK.promoted_findings(task)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: promoted_kinds.promoted_findings({task!r}) raised {exc}", file=sys.stderr)
        return []
    # Group by kind so one finding covers ALL instances of that kind (rows capped, cut-count noted)
    # rather than one finding per row: source_citation_existence/golden_cites_absent_file alone can
    # carry thousands of near-duplicate citations of the same absent file on one task (SVC-PC-6-2-0:
    # 4046) - one row per citation would balloon the union past what a fix-plan prompt can use.
    by_kind: dict[str, list[dict]] = {}
    for h in hits:
        by_kind.setdefault(h["promoted_kind"], []).append(h)

    out: list[dict] = []
    for pk, group in by_kind.items():
        cell = _PROMOTED_KIND_CELL.get(pk, group[0].get("cell_or_scan", ""))
        blocking_safe = pk in (PK.BLOCKING_SAFE_KIND_NAMES if PK else [])
        shown, cut = (group[:SCAN_ROW_CAP], len(group) - SCAN_ROW_CAP) if len(group) > SCAN_ROW_CAP else (group, 0)
        out.append(
            {
                "id": f"promoted-{pk}",
                "kind": "promoted_kind",
                "class": pk,
                # 20:12Z: same severity-gating principle as scan_findings() - a kind excluded from
                # the blocking set (fires on the SVC-PC-2-7-0 control, or failed the precision bar)
                # is minor context, not a major, or it can still park a task on an uncalibrated
                # signal exactly like the incident this session's severity fix was meant to close.
                "severity": "major" if blocking_safe else "minor",
                "criterion_ids": [],
                "affected_files": [],
                "description": (
                    f"Promoted kind '{pk}' fired {len(group)} time(s) "
                    f"({'blocking-safe' if blocking_safe else 'EXCLUDED from the blocking gate - fires on the accepted '
                    'control task, see promoted_kinds.py docstring'}). {shown[0].get('detail', '')}"
                ),
                "evidence": [{"detail": h.get("detail", ""), "evidence": h.get("evidence", "")} for h in shown],
                "rows_cut": cut,
                "fix_direction": f"Read this finding's `playbook` (the underlying cell '{cell}'), then every entry in `evidence` (all {len(shown)} shown, {cut} cut).",
                "playbook": GP.playbook_text(cell) if GP else "",
            }
        )
    return out


_GATE_LINE_RE = re.compile(r"^(BLOCKING|EXCLUDED)  (\S+)  (\S+)  (.*)$")


def gate_actuator_findings(task: str, pipe: Path) -> tuple[list[dict], list[dict]]:
    """(findings, excluded_context). C1 refinement (19:15Z): once promoted_kinds_gate.py is wired
    into stage_and_zip.sh, checks/promoted_kinds.txt is the gate's own stdout from its last attempt
    on THIS task - the actual live blocking decision, not a re-derivation. When present, prefer it
    over re-running promoted_kinds.promoted_findings() directly: a BLOCKING line becomes a finding
    (so the round after a gate block fixes exactly what blocked, no drift between what blocked the
    zip and what the fixer is told to fix); an EXCLUDED line is context only (kept for the fixer to
    read, never a finding - these are the kinds verified to false-fire on the DataOS-accepted
    control task, see promoted_kinds.py's module docstring)."""
    p = pipe / "checks" / "promoted_kinds.txt"
    if not p.is_file():
        return [], []
    findings: list[dict] = []
    excluded: list[dict] = []
    by_kind: dict[str, list[str]] = {}
    excluded_by_kind: dict[str, list[str]] = {}
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _GATE_LINE_RE.match(line)
        if not m:
            continue
        status, line_task, kind, detail = m.groups()
        if line_task != task:
            continue
        (by_kind if status == "BLOCKING" else excluded_by_kind).setdefault(kind, []).append(detail)
    for kind, details in by_kind.items():
        cell = _PROMOTED_KIND_CELL.get(kind, kind)
        shown, cut = (details[:SCAN_ROW_CAP], len(details) - SCAN_ROW_CAP) if len(details) > SCAN_ROW_CAP else (details, 0)
        findings.append(
            {
                "id": f"gate-blocking-{kind}",
                "kind": "gate_blocking",
                "class": kind,
                "severity": "major",
                "criterion_ids": [],
                "affected_files": [],
                "description": (
                    f"stage_and_zip.sh's promoted_kinds_gate.py BLOCKED THE ZIP on '{kind}' ({len(details)} finding(s), "
                    f"from {p}): {shown[0]}"
                ),
                "evidence": shown,
                "rows_cut": cut,
                "fix_direction": f"This is what actually blocked shipping on the last attempt. Read this finding's `playbook`, then every entry in `evidence` (all {len(shown)} shown, {cut} cut). Fix exactly this before anything else.",
                "playbook": GP.playbook_text(cell) if GP else "",
            }
        )
    for kind, details in excluded_by_kind.items():
        excluded.append({"kind": kind, "count": len(details), "example": details[0] if details else ""})
    return findings, excluded


def advisory_actuator_findings(recheck_csv: Path | None, blocking_scans: set[str] | None = None) -> list[dict]:
    """One finding per named ADVISORY-set actuator cell (source_citation_existence, golden_arithmetic,
    criterion_groundedness, golden_groundedness) that reads warn or fail. These cells are correctly excluded
    from blocking_gate_cells() (ADVISORY = does not block the zip) but a DataOS reviewer catching one as a
    major was never surfaced to the fixer before this.

    severity (coordinator, 20:27Z, same rule as scan_findings()/promoted_kind_findings()): "major" only
    when this cell's name is in `blocking_scans` (the task's calibrated promoted-kinds blocking set - a
    BLOCKING row whose cell_or_scan is this cell), else "minor" - rows/details/playbook unchanged either
    way. golden_arithmetic and golden_groundedness have no promoted-kind mapping at all today, so under
    this rule they are always minor until a calibrated sub-case for either is added; that is intentional,
    not a gap introduced here - the whole-cell signal for them was never precision-checked the way the 4
    kinds that ARE in BLOCKING_SAFE_KIND_NAMES were."""
    if recheck_csv is None or not Path(recheck_csv).is_file():
        return []
    with open(recheck_csv, newline="") as f:
        rows = [r for r in _csv.DictReader(f) if r.get("task_id")]
    if not rows:
        return []
    row = rows[0]
    recheck_dir = str(Path(recheck_csv).parent)
    blocking_scans = blocking_scans or set()
    out: list[dict] = []
    for cell in ADVISORY_ACTUATOR_CELLS:
        verdict = row.get(cell)
        if verdict not in ("warn", "fail"):
            continue
        n = row.get(f"{cell}_n", "")
        first = row.get(f"{cell}_first", "")
        details = GP.cell_details(recheck_dir, cell) if GP else {}
        severity = "major" if cell in blocking_scans else "minor"
        out.append(
            {
                "id": f"advisory-{cell}",
                "kind": "advisory_actuator",
                "class": cell,
                "severity": severity,
                "criterion_ids": [],
                "affected_files": [],
                "description": (
                    f"ADVISORY actuator cell '{cell}' = {verdict!r} ({n} finding(s)). In stage_and_zip.sh's ADVISORY "
                    "set (does not block the zip on its own). "
                    + (
                        "This cell is in the calibrated promoted-kinds blocking set for this task (checks/promoted_kinds.txt "
                        "or a BLOCKING-safe kind fired directly) - a genuine major."
                        if severity == "major"
                        else "This cell is NOT in the calibrated promoted-kinds blocking set for this task: kept as minor "
                        "context (details/playbook below), does not count toward major_count and will not park the task on "
                        "its own. DataOS reviewers may still catch what it finds - check reviewer_major findings too."
                    )
                    + f" First finding: {first}"
                ),
                "evidence": f"{recheck_csv}: {cell}={verdict} n={n}",
                "fix_direction": f"Read this finding's `playbook`, then `details` (the cell's own findings, verbatim).",
                "playbook": GP.playbook_text(cell) if GP else "",
                "details": details,
            }
        )
    return out


def blocking_gate_cells(recheck_csv: Path, task: str) -> list[tuple[str, str]]:
    """Exact port of stage_and_zip.sh's gate conditional: [(cell, value), ...] for every cell that would block the actuator."""
    if not recheck_csv or not Path(recheck_csv).is_file():
        return []
    with open(recheck_csv, newline="") as f:
        rows = [r for r in _csv.DictReader(f) if r.get("task_id") == task]
    if not rows:
        return []
    row = rows[0]
    nonpass = [
        (k, v)
        for k, v in row.items()
        if k not in ("task_id", "C", "D", "E")
        and not k.endswith("_n")
        and not k.endswith("_first")
        and v not in ("pass", "", None)
    ]
    blocking = []
    for k, v in nonpass:
        if k in ADVISORY:
            continue
        if k == "metadata_leak" and v != "fail":
            continue
        z = any(k.startswith(p) for p in ZSCAN_PREFIXES)
        relevant = (k in GATE) or z
        if v == "fail":
            blocking.append((k, v))
        elif relevant and v in ("warn", "skip", "error"):
            blocking.append((k, v))
    return blocking


# ---------------------------------------------------------------------------
# Task files
# ---------------------------------------------------------------------------
def criterion_lookup(corpus_root: str, task: str) -> dict:
    """{(group_dir, criterion_name): {"description", "weight"}} from every tests/*/judge.toml."""
    out: dict = {}
    try:
        import tomllib
    except ImportError:
        return out
    for jp in glob.glob(os.path.join(corpus_root, task, "tests", "*", "judge.toml")):
        group = os.path.basename(os.path.dirname(jp))
        try:
            d = tomllib.load(open(jp, "rb"))
        except Exception:  # noqa: BLE001
            continue
        for c in d.get("criterion", []) or []:
            out[(group, str(c.get("name")))] = {
                "description": c.get("description", "") or "",
                "weight": c.get("weight"),
            }
    return out


def newest_shipped_mtime(task: str) -> float:
    """mtime of the newest file the zip step would ship (the guard's own rule), 0.0 when it cannot be computed."""
    try:
        sys.path.insert(0, "/root/qc/tools")
        import oracle_refresh as orf

        return float(orf.newest_staged(task)[0])
    except Exception:  # noqa: BLE001
        return 0.0


def _iso(ts: float) -> str:
    import datetime as dt

    return (
        dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if ts
        else ""
    )


# ---------------------------------------------------------------------------
# Reviewer verdicts
# ---------------------------------------------------------------------------
_MAJOR_WORDS = {"major", "blocking", "critical"}
_TEXT_KEYS = (
    "justification",
    "description",
    "detail",
    "details",
    "issue",
    "finding",
    "reason",
    "evidence",
)
_FIX_KEYS = ("suggested_fix", "fix", "recommendation", "remediation")


def _canonical(d) -> bool:
    return (
        isinstance(d, dict)
        and "overall_verdict" in d
        and isinstance(d.get("checks"), list)
    )


def newest_canonical_review(
    pipe: Path, reviewer: str, passed: Path
) -> tuple[Path, bool]:
    """(path, substituted). The newest canonical review file of `reviewer` by mtime, archived pre-reopen files included."""
    cands = []
    for f in glob.glob(str(pipe / f"CR.{reviewer}.round*.json")):
        if not re.search(rf"CR\.{reviewer}\.round\d+(?:\.pre-reopen-\d+)?\.json$", f):
            continue
        try:
            if _canonical(json.load(open(f))):
                cands.append((os.path.getmtime(f), f))
        except Exception:  # noqa: BLE001
            continue
    if not cands:
        return passed, False
    cands.sort()
    best = Path(cands[-1][1])
    return best, best.resolve() != Path(passed).resolve()


def load_checks(path: Path, reviewer: str) -> tuple[list[dict], dict]:
    """(majors, meta). meta carries major_count, summary, matrix and the number of majors actually listed."""
    meta: dict = {}
    try:
        d = json.loads(Path(path).read_text())
    except Exception as exc:  # noqa: BLE001
        print(
            f"WARN: {path} did not parse ({exc}), contributing 0 findings from {reviewer}",
            file=sys.stderr,
        )
        return [], meta
    if "overall_verdict" not in d:
        print(
            f"WARN: {path} has no overall_verdict (not canon-shaped), contributing 0 findings from {reviewer}",
            file=sys.stderr,
        )
        return [], meta
    checks = d.get("checks")
    if not isinstance(checks, list):
        print(
            f"WARN: {path} has no checks[] list, contributing 0 findings from {reviewer}",
            file=sys.stderr,
        )
        return [], meta
    majors = [
        c
        for c in checks
        if isinstance(c, dict)
        and str(c.get("severity", "")).strip().lower() in _MAJOR_WORDS
    ]
    meta = {
        "major_count": d.get("major_count"),
        "summary": d.get("summary"),
        "matrix": d.get("matrix"),
        "listed": len(majors),
        "overall_verdict": d.get("overall_verdict"),
    }
    return majors, meta


def _first_text(c: dict, keys) -> str:
    for k in keys:
        v = c.get(k)
        if isinstance(v, str) and v.strip():
            return v
        if isinstance(v, (list, dict)) and v:
            return json.dumps(v, ensure_ascii=False)[:1500]
    return ""


# ---------------------------------------------------------------------------
# Oracle, adjudication, prior attempts
# ---------------------------------------------------------------------------
def failed_oracle_criteria(oracle_json: Path) -> tuple[list[dict], dict]:
    """(failed criteria, meta). [] when the file is missing, unparseable, scores 1.0, or any criterion carries a transport error."""
    meta: dict = {}
    if not oracle_json or not Path(oracle_json).is_file():
        return [], meta
    try:
        d = json.loads(Path(oracle_json).read_text())
    except Exception:  # noqa: BLE001
        return [], meta
    total = d.get("total_reward")
    meta = {"total_reward": total, "mtime": os.path.getmtime(oracle_json)}
    if total is None or float(total) >= 1.0:
        return [], meta
    groups = d.get("groups")
    if not isinstance(groups, list):
        return [], meta
    failed = []
    for g in groups:
        for c in g.get("criteria", []) or []:
            if not isinstance(c, dict):
                continue
            if c.get("error"):
                return [], meta  # a judge transport error is not a golden defect
            if not c.get("passed"):
                failed.append(
                    {
                        "group": g.get("name", "?"),
                        "name": c.get("name", "?"),
                        "weight": c.get("weight"),
                        "value": c.get("value"),
                        "verdict_text": c.get("verdict_text", "") or "",
                    }
                )
    return failed, meta


def flipping_oracle_criteria(oracle_json: Path) -> tuple[list[dict], dict]:
    """(flips, meta). flips is oracle.json's own `flips` field (verifier spec, 2026-09-19
    18:25Z step B): criteria that passed in one independent oracle run and failed in
    another. [] when the file is missing, unparseable, or carries no `flips` key (a
    --runs 1 probe, or a --runs > 1 probe where nothing flipped)."""
    meta: dict = {}
    if not oracle_json or not Path(oracle_json).is_file():
        return [], meta
    try:
        d = json.loads(Path(oracle_json).read_text())
    except Exception:  # noqa: BLE001
        return [], meta
    meta = {
        "oracle_runs": d.get("oracle_runs"),
        "oracle_run_totals": d.get("oracle_run_totals"),
        "mtime": os.path.getmtime(oracle_json),
    }
    flips = d.get("flips")
    return (flips if isinstance(flips, list) else []), meta


def adjudication_findings(
    path: Path, newest: float, crit: dict | None = None
) -> tuple[list[dict], list[dict]]:
    """(fresh findings, stale summaries). Only an adjudication newer than every file of the task is a finding: ADJUDICATE.json is never
    rewritten after a fix, so an old one would keep re-listing criteria a later round already rewrote and park the task on them. An
    older one goes to context.stale_adjudications, where the fixer can check it while it is editing for another reason.
    """
    if not path or not Path(path).is_file():
        return [], []
    try:
        d = json.loads(Path(path).read_text())
    except Exception:  # noqa: BLE001
        return [], []
    stale = os.path.getmtime(path) + FRESH_SLACK < newest if newest else False
    fresh, old = [], []
    for i, a in enumerate(d.get("adjudications", []) or [], start=1):
        if not isinstance(a, dict) or a.get("verdict") != "false_rejection":
            continue
        if stale:
            old.append(
                {
                    "criterion_id": a.get("criterion_id"),
                    "group": a.get("group"),
                    "reasoning": (a.get("reasoning") or "")[:700],
                    "fix_direction": (a.get("fix_direction") or "")[:500],
                }
            )
            continue
        fresh.append(
            {
                "id": f"adjudication-{a.get('group', '?')}-{a.get('criterion_id', i)}",
                "kind": "adjudication",
                "class": "false_rejection",
                "severity": "major",
                "criterion_ids": [a.get("criterion_id")],
                "affected_files": [],
                "description": (
                    f"Adjudication of the GLM solver runs: criterion {a.get('criterion_id')} (group {a.get('group')}) rejects a "
                    f"compliant reading of the instruction. A false rejection is a major at any weight (DataOS). {a.get('reasoning', '')}"
                ),
                "evidence": json.dumps(a, ensure_ascii=False)[:1800],
                "fix_direction": a.get("fix_direction", "") or "",
                "instruction_quote": a.get("instruction_quote", "") or "",
                "run_glm1": (a.get("run_glm1") or "")[:900],
                "run_glm2": (a.get("run_glm2") or "")[:900],
                "criterion_text": (
                    (crit or {}).get((a.get("group"), str(a.get("criterion_id")))) or {}
                ).get("description", "")[:1500],
                "weight": (
                    (crit or {}).get((a.get("group"), str(a.get("criterion_id")))) or {}
                ).get("weight"),
                "playbook": GP.adjudication_playbook_text() if GP else "",
            }
        )
    return fresh, old


_OUTCOME_RE = re.compile(
    r"edit (\d+) \[([^\]]*)\] (\w+) (\S+): (APPLIED|NOOP|FAILED) - (.*)"
)


def prior_attempts(pipe: Path) -> list[dict]:
    """Earlier plans for this task: edit counts, the model's own notes, and the outcome of every logged edit."""
    out = []
    for name in (
        "PLAN.round1.json",
        "PLAN.round2.json",
        "PLAN.fixreviews.json",
        "PLAN.fixreviews2.json",
    ):
        p = pipe / name
        if not p.is_file():
            continue
        try:
            d = json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            continue
        out.append(
            {
                "plan": name,
                "when": _iso(os.path.getmtime(p)),
                "edits": len(d.get("edits", []) or []),
                "notes": (d.get("notes") or "")[:900],
            }
        )
    log = pipe / "FIX-FROM-REVIEWS.md"
    if log.is_file():
        counts = {"APPLIED": 0, "NOOP": 0, "FAILED": 0}
        bad = []
        for line in log.read_text(errors="replace").splitlines():
            m = _OUTCOME_RE.search(line)
            if not m:
                continue
            counts[m.group(5)] += 1
            if m.group(5) in ("NOOP", "FAILED"):
                bad.append(
                    f"{m.group(5)} {m.group(3)} {m.group(4)}: {m.group(6)[:200]}"
                )
        out.append(
            {
                "edit_log": "FIX-FROM-REVIEWS.md",
                "outcomes": counts,
                "not_applied": bad[-14:],
            }
        )
    parked = pipe / "PARKED.md"
    if parked.is_file():
        out.append({"parked": parked.read_text(errors="replace")[-600:]})
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
HOW_TO_READ = (
    "Each finding has a `kind`. reviewer_major: a major from one of the two workspace reviewers (read description and fix_direction; a finding "
    "marked possibly_fixed comes from a review older than the newest file: confirm it against the CURRENT FILE CONTENT and emit no edit if it is "
    "already fixed). gate_cell: a deterministic check that blocks the zip: read its `playbook`, then `details` (the check's own findings, verbatim), "
    "then `docs`. oracle: a criterion the golden fails on its own rubric: read `playbook`, `verdict_text`, `criterion_text`. adjudication: a criterion "
    "judged to reject a compliant reading of the instruction. advisory_actuator: one of 4 named deterministic cells (source_citation_existence, "
    "golden_arithmetic, criterion_groundedness, golden_groundedness) that does not block the zip on its own (stage_and_zip.sh ADVISORY set) but is "
    "still a real defect reviewers catch: read `playbook`, then `details`. scan: one of the 12 canonical/addendum corpus scans (also not "
    "blocking): read `playbook`, then every row in `rows` verbatim (a row is one finding of that scan; `rows_cut` says how many were cut past the cap). "
    "A scan finding's `severity` is 'major' only when that scan is in this task's calibrated promoted-kinds blocking set (checks/promoted_kinds.txt "
    "or a live BLOCKING-safe kind); otherwise it is 'minor' - still shown in full (rows/playbook) as context, but excluded from `major_count` and "
    "will not park the task on its own (coordinator, 20:12Z: whole uncalibrated scan verdicts had parked tasks neither workspace reviewer flagged). "
    "promoted_kind: one of Fable's 10 row-level kinds (C1 refinement, 18:55Z) that separates a genuine defect from the one DataOS-accepted "
    "control task - read `playbook`; `description` says whether this specific kind is blocking-safe or excluded (still worth fixing either way). "
    "gate_blocking: what promoted_kinds_gate.py's LAST ACTUAL RUN on this task (checks/promoted_kinds.txt, C1 refinement 19:15Z) reported as "
    "BLOCKING - this is what really stopped the zip; fix this before anything else. context.gate_excluded_kinds lists what the same gate run "
    "reported EXCLUDED (context only, not a finding). `context.prior_attempts` lists what earlier rounds tried and which edits did not apply: "
    "do not repeat an edit that already failed the same way."
)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--task", required=True)
    ap.add_argument("--glm", type=Path, required=True)
    ap.add_argument("--sonnet", type=Path, required=True)
    ap.add_argument("--recheck-csv", type=Path, default=None)
    ap.add_argument("--oracle-json", type=Path, default=None)
    ap.add_argument("--adjudicate-json", type=Path, default=None)
    ap.add_argument("--corpus-root", default=DEFAULT_CORPUS)
    ap.add_argument("--pipe-dir", type=Path, default=None)
    ap.add_argument(
        "--no-latest",
        action="store_true",
        help="use exactly the review files named, not the newest canonical ones",
    )
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    pipe = args.pipe_dir or args.glm.parent
    newest = newest_shipped_mtime(args.task)
    crit = criterion_lookup(args.corpus_root, args.task)
    findings: list[dict] = []
    reviews_used: dict = {}

    # ---- reviewer majors ------------------------------------------------------------------------------------------------
    for reviewer, passed in (("glm", args.glm), ("sonnet", args.sonnet)):
        path, substituted = (
            (passed, False)
            if args.no_latest
            else newest_canonical_review(pipe, reviewer, passed)
        )
        if substituted:
            print(
                f"[build_review_union] {args.task}: using newest canonical {path.name} for {reviewer} instead of {Path(passed).name}",
                file=sys.stderr,
            )
        majors, meta = load_checks(path, reviewer)
        mtime = os.path.getmtime(path) if Path(path).is_file() else 0.0
        stale = bool(newest and mtime + FRESH_SLACK < newest)
        reviews_used[reviewer] = {
            "file": Path(path).name,
            "passed_by_dispatcher": Path(passed).name,
            "reviewed_at": _iso(mtime),
            "major_count": meta.get("major_count"),
            "majors_listed": meta.get("listed"),
            "predates_newest_file": stale,
        }
        for c in majors:
            check_id = c.get("id", "?")
            justification = _first_text(c, _TEXT_KEYS)
            suggested_fix = _first_text(c, _FIX_KEYS)
            findings.append(
                {
                    "id": f"{reviewer}-{check_id}",
                    "kind": "reviewer_major",
                    "class": check_id,
                    "severity": "major",
                    "criterion_ids": [],
                    "affected_files": extract_affected_files(
                        justification + "\n" + suggested_fix
                    ),
                    "description": justification
                    or f"(reviewer gave no text for check {check_id}: {c.get('name', '')})",
                    "evidence": (
                        f"reviewer={reviewer} check_id={check_id} name={c.get('name', '')!r} "
                        f"evidence_status={c.get('evidence_status', '')!r} review_file={Path(path).name}"
                    ),
                    "fix_direction": suggested_fix,
                    "possibly_fixed": stale,
                    "reviewer_check": {
                        k: (
                            v
                            if isinstance(v, (int, float, bool)) or v is None
                            else str(v)[:1200]
                        )
                        for k, v in c.items()
                    },
                }
            )
        mc = meta.get("major_count")
        if isinstance(mc, int) and mc > meta.get("listed", 0):
            findings.append(
                {
                    "id": f"{reviewer}-unlisted-majors",
                    "kind": "reviewer_major",
                    "class": "unlisted-majors",
                    "severity": "major",
                    "criterion_ids": [],
                    "affected_files": [],
                    "description": (
                        f"{reviewer} reported major_count={mc} but its checks[] marks {meta.get('listed', 0)} check(s) as major. "
                        f"Its own summary: {str(meta.get('summary'))[:1500]}"
                    ),
                    "evidence": f"matrix: {json.dumps(meta.get('matrix'), ensure_ascii=False, default=str)[:1500]}",
                    "fix_direction": "Work out which check(s) the reviewer means from its summary and matrix, verify against the CURRENT FILE CONTENT, and fix them.",
                    "possibly_fixed": stale,
                }
            )

    # ---- gate cells -------------------------------------------------------------------------------------------------------
    recheck_csv = args.recheck_csv
    recheck_note = ""
    if recheck_csv is None or not Path(recheck_csv).is_file():
        alt = Path("/root/qc/_recheck") / args.task / "summary.csv"
        if alt.is_file() and (
            not newest or os.path.getmtime(alt) + FRESH_SLACK >= newest
        ):
            recheck_csv, recheck_note = (
                alt,
                "using /root/qc/_recheck (fresher than every file)",
            )
    n_gate = 0
    blocking: list[tuple[str, str]] = []
    if recheck_csv is not None:
        blocking = blocking_gate_cells(Path(recheck_csv), args.task)
        recheck_dir = str(Path(recheck_csv).parent)
        values = None
        for cell, value in blocking:
            n_gate += 1
            details = GP.cell_details(recheck_dir, cell) if GP else {}
            if cell == "metadata_leak" and details:
                try:
                    import metadata_verify as MV

                    values = (
                        values
                        if values is not None
                        else MV.load_values(os.path.join(args.corpus_root, args.task))
                    )
                    for key in ("environment_high_findings", "golden_high_findings"):
                        for it in details.get(key, []) or []:
                            if not isinstance(it, dict):
                                continue
                            ct = crit.get(
                                (it.get("judge_group"), str(it.get("criterion")))
                            )
                            if ct:
                                it["criterion_text"] = ct["description"][:700]
                            it["all_collisions"] = MV.collisions(
                                it.get("text", ""), values
                            )
                except Exception as exc:  # noqa: BLE001
                    details["enrichment_error"] = f"{type(exc).__name__}: {exc}"
            # affected_files stays empty on purpose: gather_files_text.py dumps every file named here into the prompt, and the flagged
            # files are environment workbooks / decks (up to 120,000 chars each); the finding's own `details` already carry the exact text.
            aff: list[str] = []
            findings.append(
                {
                    "id": f"gate-{cell}",
                    "kind": "gate_cell",
                    "class": "1.5",
                    "severity": "major",
                    "cell": cell,
                    "cell_value": value,
                    "criterion_ids": [],
                    "affected_files": aff,
                    "description": (
                        f"Deterministic check '{cell}' = {value!r} blocks the zip (stage_and_zip.sh GATE-V2 3.4/3.6, cell not in ADVISORY) even "
                        f"if both workspace reviewers found zero majors."
                    ),
                    "evidence": f"{recheck_csv}: {cell}={value}",
                    "fix_direction": GATE_FIX_DIRECTION_FALLBACK.format(cell=cell),
                    "playbook": GP.playbook_text(cell) if GP else "",
                    "details": details,
                    "docs": (GP.check_docs(cell) if GP else ""),
                }
            )
        if n_gate:
            print(
                f"[build_review_union] {args.task}: {n_gate} blocking gate cell(s) from {recheck_csv} {recheck_note}",
                file=sys.stderr,
            )

    # `blocking_scans`: the task's calibrated promoted-kinds blocking set (cell/scan names carrying
    # >=1 BLOCKING row), computed once and reused by advisory_actuator_findings/scan_findings below
    # for their severity gating (coordinator, 20:12Z/20:27Z).
    blocking_scans = blocking_scan_names(args.task, pipe)

    # ---- advisory actuator cells (C1, 18:25Z; severity gated 20:27Z) ------------------------------------------------------
    # Same recheck_csv as the gate-cell block above (checks/recheck/summary.csv or the newest prior_verifications
    # fallback already resolved into `recheck_csv`); blocking_gate_cells() correctly skips these 4 (ADVISORY), so
    # they need their own read here or the fixer never sees them at all.
    adv = advisory_actuator_findings(recheck_csv, blocking_scans)
    findings.extend(adv)
    if adv:
        print(
            f"[build_review_union] {args.task}: {len(adv)} advisory-actuator finding(s) from {recheck_csv}",
            file=sys.stderr,
        )

    # ---- 12 canonical/addendum scans (C1, 18:25Z/18:40Z/18:55Z) ------------------------------------------------------------
    scans = scan_findings(pipe / "checks", blocking_scans)
    findings.extend(scans)
    if scans:
        print(
            f"[build_review_union] {args.task}: {len(scans)} scan finding(s) from {pipe / 'checks'}",
            file=sys.stderr,
        )

    # ---- promoted kinds (C1 refinement, 18:55Z/19:15Z) ---------------------------------------------------------------------
    # Prefer checks/promoted_kinds.txt (the gate's own stdout from its last actual attempt on this
    # task) when present: it is the authoritative record of what really blocked shipping, so the
    # fixer sees exactly that rather than a fresh re-derivation that could drift from it. Falls back
    # to direct computation (promoted_kind_findings) for a task the gate has not run on yet.
    gate_txt_findings, gate_txt_excluded = gate_actuator_findings(args.task, pipe)
    if gate_txt_findings or gate_txt_excluded:
        findings.extend(gate_txt_findings)
        print(
            f"[build_review_union] {args.task}: {len(gate_txt_findings)} gate-blocking finding(s) from checks/promoted_kinds.txt "
            f"({len(gate_txt_excluded)} excluded kind(s) noted as context only)",
            file=sys.stderr,
        )
    else:
        promoted = promoted_kind_findings(args.task)
        findings.extend(promoted)
        if promoted:
            print(
                f"[build_review_union] {args.task}: {len(promoted)} promoted-kind finding(s) (direct computation, no checks/promoted_kinds.txt yet)",
                file=sys.stderr,
            )
        gate_txt_excluded = []

    # ---- oracle -----------------------------------------------------------------------------------------------------------
    oracle_meta: dict = {}
    if args.oracle_json is not None:
        failed, oracle_meta = failed_oracle_criteria(args.oracle_json)
        probe_stale = bool(
            newest
            and oracle_meta.get("mtime")
            and oracle_meta["mtime"] + FRESH_SLACK < newest
        )
        for c in failed:
            ct = crit.get((c["group"], str(c["name"])))
            findings.append(
                {
                    "id": f"oracle-{c['group']}-{c['name']}",
                    "kind": "oracle",
                    "class": "1.1",
                    "severity": "major",
                    "criterion_ids": [c["name"]],
                    "affected_files": extract_affected_files(c["verdict_text"]),
                    "description": c["verdict_text"]
                    or "(the judge gave no verdict text)",
                    "evidence": f"{args.oracle_json}: group={c['group']} criterion={c['name']} weight={c['weight']} value={c['value']} total_reward={oracle_meta.get('total_reward')}",
                    "criterion_text": (ct or {}).get("description", "")[:1500],
                    "weight": c["weight"],
                    "fix_direction": (
                        "The golden fails this criterion on its own rubric (GATE-V2 3.4, DataOS 1.1/1.5): a golden must score 1.0 on its own rubric "
                        "before shipping. Follow the playbook."
                    ),
                    "playbook": GP.oracle_playbook_text() if GP else "",
                    "possibly_fixed": probe_stale,
                    "note": (
                        "The probe is older than the newest file of the task: confirm this criterion still fails against the CURRENT FILE CONTENT before editing."
                        if probe_stale
                        else ""
                    ),
                }
            )
        if failed:
            print(
                f"[build_review_union] {args.task}: {len(failed)} failed oracle criterion/criteria from {args.oracle_json}",
                file=sys.stderr,
            )

        # ---- oracle flips (verifier spec, 2026-09-19 18:25Z step B) --------------------------------------------------------
        flips, flip_meta = flipping_oracle_criteria(args.oracle_json)
        if flips:
            flip_stale = bool(
                newest and flip_meta.get("mtime") and flip_meta["mtime"] + FRESH_SLACK < newest
            )
            names = ", ".join(f"{f.get('group')}/{f.get('name')}" for f in flips)
            findings.append(
                {
                    "id": "oracle-flip",
                    "kind": "oracle_flip",
                    "class": "1.5",
                    "severity": "major",
                    "criterion_ids": [f.get("name") for f in flips],
                    "affected_files": [],
                    "description": (
                        f"{len(flips)} criterion/criteria are non-deterministic on the golden across "
                        f"{flip_meta.get('oracle_runs')} independent oracle runs (totals: "
                        f"{flip_meta.get('oracle_run_totals')}): {names}. Each passed in at least one run and "
                        "failed in at least one other, on the SAME golden bytes - the wording admits more than "
                        "one reading of the same evidence."
                    ),
                    "evidence": json.dumps(flips, ensure_ascii=False, default=str)[:4000],
                    "fix_direction": (
                        "Rewrite each flipping criterion so only one reading exists: split a compound Expected "
                        "clause into separate criteria with the weight divided, replace judgment words with the "
                        "exact value and tolerance, and name the sheet, cell or section. Never loosen the bar, "
                        "never delete a criterion. Follow the playbook."
                    ),
                    "playbook": GP.oracle_flip_playbook_text() if GP else "",
                    "possibly_fixed": flip_stale,
                    "note": (
                        "This probe is older than the newest file of the task: confirm these criteria still flip "
                        "against the CURRENT FILE CONTENT (re-run with --runs 3) before editing."
                        if flip_stale
                        else ""
                    ),
                }
            )
            print(
                f"[build_review_union] {args.task}: {len(flips)} flipping oracle criterion/criteria from {args.oracle_json}",
                file=sys.stderr,
            )

    # ---- adjudication -----------------------------------------------------------------------------------------------------
    adj_path = args.adjudicate_json or (pipe / "ADJUDICATE.json")
    adj, stale_adj = adjudication_findings(adj_path, newest, crit)
    findings.extend(adj)

    out = {
        "task": args.task,
        "source": (
            "union of the newest canonical workspace reviews (CR.glm / CR.sonnet), the deterministic gate cells that block the zip, "
            "the golden's oracle score and any adjudicated false rejections"
        ),
        "findings": findings,
        "majors_present": any(f.get("severity") == "major" for f in findings),
        "major_count": sum(1 for f in findings if f.get("severity") == "major"),
        "minor_count": sum(1 for f in findings if f.get("severity") == "minor"),
        "context": {
            "how_to_read": HOW_TO_READ,
            "reviews_used": reviews_used,
            "newest_file_time": _iso(newest),
            "oracle": {
                "total_reward": oracle_meta.get("total_reward"),
                "probed_at": _iso(oracle_meta.get("mtime", 0.0)),
            },
            "blocking_gate_cells": [list(x) for x in blocking],
            "adjudication_false_rejections": len(adj),
            "stale_adjudications": stale_adj,
            "gate_excluded_kinds": gate_txt_excluded,
            "prior_attempts": prior_attempts(pipe),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(
        f"[build_review_union] {args.task}: {len(findings)} finding(s) unioned "
        f"({out['major_count']} major, {out['minor_count']} minor), wrote {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
