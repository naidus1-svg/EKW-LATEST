#!/usr/bin/env python3
"""EKW QC runner: Check B plus every shared deterministic check, one command, one table.

What it does
------------
1. Runs `ekw_check_b.py` in-process over the EKW harbor tree at `--root`: verifies each build
   and stages a BUILD-CONTRACT-shaped copy under `--stage` (see ekw_check_b.py's docstring).
2. Runs each shared check in `deterministic-checks/` as a subprocess against the staged tree
   (or against `--root` directly with `--native`, once the shared checks read verifier.json
   themselves), writing each check's own JSON to `--out-dir/<check>.json` untouched.
3. Merges everything into `--out-dir/summary.json` and `--out-dir/summary.csv`: one row per
   task, one column per check with a normalised verdict (pass / warn / fail / skip / error),
   plus B / C / D / E roll-ups in the letters the QC trackers use.

Only four of the sixteen shared checks return a non-zero exit code on findings; the other
twelve always exit 0. The runner therefore never trusts an exit code: every verdict comes
from the check's JSON. A check that crashed, timed out, or wrote no JSON shows `error` for
every task, with the stderr tail in `runs.json`, rather than a silent column of blanks.

Letters (the grouping docs/QC-SOP-first-run.md section 3 gives the trackers)
  B  ekw_check_b (build verified, package staged)
  C  structural: environment_input, answer_key_leakage, deliverable_count,
     answer_key_content_leak, environment_size_budget, answer_key_rubric_leak,
     metadata_leak (2026-09-16: reads xlsx/docx/pptx file METADATA -- cell comments, defined
     names, sheet titles, docx comments/tracked-changes/headers-footers, pptx speaker notes --
     none of the other answer_key_* checks above ever open; see its own module docstring),
     structural_audit (2026-09-17: LLM-judge six-pattern structural audit, rows 28-29)
  D  mechanical/rubric: deliverable_filename, rubric_schema, rubric_text_lint,
     judge_criterion_name_duplicate, tab_naming, deliverable_integrity,
     judge_determinism_config_lint, compound_criterion, undisclosed_terminology,
     extraction_groundedness, unrequested_deliverable_source, dependency_pin,
     weight_application, duplicate_criterion_content, same_file_requirement_duplicate,
     cell_address_pinned (this line has other pre-existing gaps against the full
     CHECKS dict below, not fixed here -- only the two checks this 2026-09-16
     change touches were added, plus cell_address_pinned added 2026-09-17)
  E  formula_health, formula_health_extraction_loss, verifier_executability,
     source_truncation, golden_arithmetic

  F  six questions (docs/author-pre-submission-checklist.md), one column per question:
     F1 sixq_f1 (a rule fails a correct answer in another valid form), F2 sixq_f2 (a rule asks
     for what the instruction never requested), F3 sixq_f3 (second reading of an instruction
     sentence), F4 sixq_f4 (a wrong or empty answer can still earn weight), F5 sixq_f5 (weights,
     output location or inputs), F6 sixq_f6 (a number pinned in a rule is not in the golden).
     F1 to F3 call `claude -p --model sonnet` once per task (skip if no claude login, or use
     --checks to leave them out); see README_sixq.md.

Roll-up rule per letter: any fail -> fail; else any error -> error; else any warn -> warn;
else any pass -> pass; else skip. `warn` is a disclosure the checks themselves do not treat
as a defect (a candidate leak, a lint hit, a Check B warning); it never blocks on its own.

Usage
-----
    python ekw_run_checks.py --all --root C:\\ekwqc\\_merged274\\files --stage C:\\ekwqc\\_ekw274_stage --out-dir C:\\ekwqc\\_ekw274_qc
    python ekw_run_checks.py task_142 task_15 --root ... --stage ... --out-dir ...
    python ekw_run_checks.py --all --root ... --stage ... --out-dir ... --checks check_b,rubric_schema,formula_health
    python ekw_run_checks.py --all --root ... --stage ... --out-dir ... --skip-stage   # reuse an existing stage

Exit 0 when no task has a fail or error in any letter, 1 otherwise, 2 on bad usage.
Stdlib only for the runner itself; the shared checks pull openpyxl / formulas on first run.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):  # unicode task names on a cp1252 console
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

HERE = Path(__file__).resolve().parent
CHECKS_DIR = HERE.parent
sys.path.insert(0, str(HERE))
import ekw_check_b  # noqa: E402

VERDICTS = ("fail", "error", "warn", "pass", "skip")


def _first_text(items) -> str:
    """A one-line quote of the first finding, whatever shape the check used."""
    if not items:
        return ""
    x = items[0]
    if isinstance(x, str):
        return x[:200]
    if isinstance(x, dict):
        for key in (
            "message",
            "reason",
            "detail",
            "description",
            "error",
            "kind",
            "filename",
            "file",
            "text",
            "url",
            "normalized_name",
            "path",
        ):
            if x.get(key):
                s = str(x[key])
                extra = ""
                for k2 in (
                    "sheet",
                    "cell",
                    "criterion",
                    "criterion_name",
                    "environment_file",
                    "value",
                ):
                    if x.get(k2):
                        extra += f" {k2}={x[k2]}"
                return (s + extra)[:200]
        return json.dumps(x, ensure_ascii=False)[:200]
    return str(x)[:200]


def _std_status(map_: dict, key: str = "status"):
    def f(r):
        return map_.get(r.get(key), "error")

    return f


def _findings_from(*paths):
    """paths: dotted keys; each resolves to a list (or a dict with a list) to concatenate."""

    def f(r):
        out = []
        for p in paths:
            cur = r
            for part in p.split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
                if cur is None:
                    break
            if isinstance(cur, list):
                out.extend(cur)
            elif isinstance(cur, dict) and cur.get("fired"):
                out.append(cur)
        return out

    return f


PF = {"pass": "pass", "fail": "fail", "skip": "skip"}

# name -> (script, letter, cli_style, task_key, verdict_fn, findings_fn)
CHECKS: dict[str, dict] = {
    "check_b": dict(
        script=None,
        letter="B",
        style="inproc",
        task_key="task_id",
        verdict=_std_status(PF),
        findings=lambda r: sorted(
            (f for f in r.get("findings", []) if f["severity"] in ("fail", "warn")),
            key=lambda f: f["severity"] != "fail",
        ),
    ),
    "deliverable_filename": dict(
        script="deliverable_filename_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status(PF, "combined_status"),
        findings=_findings_from("missing", "commanded_but_not_graded"),
    ),
    "deliverable_count": dict(
        script="deliverable_count_check.py",
        letter="C",
        style="std",
        task_key="task_id",
        verdict=_std_status(PF),
        findings=_findings_from("errors"),
    ),
    "environment_input": dict(
        script="environment_input_check.py",
        letter="C",
        style="std",
        task_key="task_id",
        verdict=_std_status(PF),
        findings=_findings_from("pattern1.missing", "pattern3.hits", "pattern5"),
    ),
    # GLM round 27/28 coverage synthesis "Class 6: oversized inlined environment, no
    # package-size budget". Same script as svc_run_checks.py's registration (see that
    # runner's comment, and this check's own module docstring "Calibration" /
    # "Duplicate-file severity", for the full derivation): environment/initial_workspace/ for
    # SVC-PC, environment/data/ for EKW, same WORKSPACE_DIRNAME_BY_FORMAT split
    # environment_input_check.py already established, so this needs no EKW-specific
    # translation layer despite check_b existing for other EKW-only shape differences. Letter
    # C (structural), matching environment_input above. Threshold (35MB) and the
    # duplicate-file severity default (warn, not fail -- see the check's own docstring for the
    # full-corpus data behind that) were calibrated against the SVC-PC corpus specifically;
    # applied here without a separate EKW-side calibration run, disclosed in the check's own
    # "Known limits".
    "environment_size_budget": dict(
        script="environment_size_budget_check.py",
        letter="C",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {
                "pass": "pass",
                "warn": "warn",
                "fail": "fail",
                "skip": "skip",
                "error": "error",
            }
        ),
        findings=_findings_from("findings"),
    ),
    "answer_key_leakage": dict(
        script="answer_key_leakage_check.py",
        letter="C",
        style="std",
        task_key="task_id",
        verdict=_std_status(PF),
        findings=_findings_from(
            "instruction_filename_leaks", "environment_filename_leaks", "bracket_leaks"
        ),
    ),
    "answer_key_content_leak": dict(
        script="answer_key_content_leak_check.py",
        letter="C",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {"clean": "pass", "candidate": "warn", "flagged": "fail", "error": "error"}
        ),
        findings=_findings_from("high_findings", "candidate_findings"),
    ),
    # answer_key_rubric_leak: Andrew Ma pattern 6 (rubric copies golden answer
    # wording, 7/19 tasks, zero coverage before this check). Distinct from
    # answer_key_leakage (golden filenames in the prompt) and
    # answer_key_content_leak (rubric values in solver-visible files): this one
    # is TEXT overlap between rubric prose and golden solution content. "skip"
    # is a real status here (no solution/ to compare against), mapped to "skip"
    # not "error": a task with no golden is a coverage gap, not a crash.
    "answer_key_rubric_leak": dict(
        script="answer_key_rubric_leak_check.py",
        letter="C",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {
                "clean": "pass",
                "candidate": "warn",
                "flagged": "fail",
                "error": "error",
                "skip": "skip",
            }
        ),
        findings=_findings_from("flagged_findings", "candidate_findings"),
    ),
    # metadata_leak: the three answer_key_* checks above only ever read VISIBLE cell/paragraph/
    # run text (confirmed by reading their own extraction code, not assumed) -- none opens an
    # xlsx cell comment, a defined name, a docx comment/tracked-change/header-footer, or a pptx
    # speaker note. This check reads exactly those six metadata fields, on BOTH golden (solution/)
    # and solver-visible (environment/) files, reusing answer_key_content_leak_check.py's own
    # expected-value matcher and answer_key_leakage_check.py's own filename-tell scan rather than
    # reinventing "does this look like a leak" -- see the script's own module docstring for two
    # confirmed real golden-side instances (SVC-PC-7-6-0, SVC-PC-7-4-0) and the full-corpus
    # verification. Same letter C as the three checks above: this is the same leak-surface
    # family, just a metadata-shaped sub-case none of them can see.
    "metadata_leak": dict(
        script="metadata_leak_check.py",
        letter="C",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {
                "pass": "pass",
                "warn": "warn",
                "fail": "fail",
                "skip": "skip",
                "error": "error",
            }
        ),
        findings=_findings_from(
            "environment_high_findings",
            "environment_candidate_findings",
            "golden_high_findings",
            "golden_candidate_findings",
        ),
    ),
    "deliverable_integrity": dict(
        script="deliverable_integrity_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status(PF),
        findings=lambda r: [
            f
            for f in r.get("files", [])
            if isinstance(f, dict) and f.get("checked") and not f.get("ok")
        ],
    ),
    "rubric_schema": dict(
        script="rubric_schema_check.py",
        letter="D",
        style="rubric_schema",
        task_key="task",
        verdict=lambda r: "pass" if r.get("ok") else "fail",
        findings=_findings_from(
            "parse_errors",
            "blank_desc",
            "bare_tier",
            "placeholder_expected",
            "file_weight_mismatch",
        ),
    ),
    "judge_criterion_name_duplicate": dict(
        script="judge_criterion_name_duplicate_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status(PF),
        findings=_findings_from("per_file_collisions", "cross_file_collisions"),
    ),
    "rubric_text_lint": dict(
        script="rubric_text_lint.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=lambda r: (
            "pass"
            if not (r.get("summary") or {}).get("n_findings") and not r.get("findings")
            else "warn"
        ),
        findings=_findings_from("findings"),
    ),
    "tab_naming": dict(
        script="tab_naming_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status(PF),
        findings=_findings_from("findings"),
    ),
    # sibling_criterion_asymmetry_check.py / brittle_construction_ordering_check.py: two
    # real, hand-confirmed defect classes from the EKW fix-and-reverify pipeline's own
    # history (task_48, task_28; 2026-09-16 -- see
    # skills/ekw/dataos-batch-watch/SKILL.md's "recurring defect classes" section and
    # skills/ekw/fix-task-from-review/SKILL.md step 1). Both need an LLM call (judging
    # whether two criteria grade "the same underlying fact," or whether an alternate
    # calculation ordering is "equivalent," is not a structural/AST check) and neither is
    # corpus-calibrated yet (one hand-confirmed real incident each) -- same posture as
    # answer_key_content_leak_check.py and judge_determinism_config_lint.py: always
    # surfaced, never gating. "flagged" maps to "warn", not "fail", until real-corpus
    # false-positive-rate data justifies a stricter mapping.
    "sibling_criterion_asymmetry": dict(
        script="sibling_criterion_asymmetry_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {"clean": "pass", "flagged": "warn", "skip": "skip", "error": "error"}
        ),
        findings=_findings_from("findings"),
    ),
    "brittle_construction_ordering": dict(
        script="brittle_construction_ordering_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {"clean": "pass", "flagged": "warn", "skip": "skip", "error": "error"}
        ),
        findings=_findings_from("findings"),
    ),
    "judge_determinism_config_lint": dict(
        script="judge_determinism_config_lint.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {
                "flag": "fail",
                "mitigated": "pass",
                # deterministic_confirmed: every non-error config file explicitly pins
                # temperature to zero (greedy/deterministic decoding). This IS a pass -- the
                # config confirms determinism, unlike not_exposed where the config format
                # cannot express a temperature field at all (determinism unknown). Added
                # 2026-09-15 round 17: the check's task-level rollup was splitting these two
                # into the same not_exposed bucket, conflating "confirmed deterministic"
                # (EKW regular tasks, temperature=0.0) with "unknown" (SVC-PC, no field).
                "deterministic_confirmed": "pass",
                # not_exposed: the config format does not expose a temperature/panel field
                # anywhere. This is a disclosed blind spot (determinism unknown), not a
                # confirmed-safe result. Map to warn, same as svc_run_checks.py, NOT pass --
                # the prior pass mapping here was the same bug class the SVC orchestrator's
                # not_exposed->warn fix already corrected (tracker backlog item 25, fixed on
                # the SVC side but the EKW side drifted). Confirmed zero real-world impact
                # before landing: the full 274-task EKW corpus is all deterministic_confirmed
                # or flag, zero tasks hit not_exposed either way.
                "not_exposed": "warn",
                "parse_error": "warn",
                "no_config_found": "warn",
                "no_tests_dir": "fail",
            }
        ),
        findings=_findings_from("flagged_configs"),
    ),
    # harness_fragility_check.py: Andrew pattern 9 (harness fragile/irreproducible).
    # Detects unpinned judge model, infra-failure-scores-zero, no grading-config
    # preflight from judge.toml/verifier.json and test.sh. Same "std" CLI shape as
    # judge_determinism_config_lint.py. All findings are warn-level, exit 0, never
    # gates. On the 14-task EKW sample: 2 findings/task (unpinned judge +
    # infra-failure-scores-zero), no_grading_config_preflight does NOT fire (EKW
    # test.sh has the verifier.json preflight). Registered in both orchestrators.
    "harness_fragility": dict(
        script="harness_fragility_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status({"warn": "warn", "pass": "pass", "skip": "skip"}),
        findings=_findings_from("findings"),
    ),
    # dependency_pin_check.py: GLM round 27/28 coverage synthesis Class 3.
    # Same shared script as svc_run_checks.py's registration - see that file
    # for the full rationale.
    "dependency_pin": dict(
        script="dependency_pin_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status({"warn": "warn", "pass": "pass", "skip": "skip"}),
        findings=_findings_from("findings"),
    ),
    # verifier_requirements_pin_mismatch_check.py (2026-09-17): a real, distinct gap from
    # dependency_pin above -- confirmed by reading dependency_pin_check.py's own source, not
    # just its docstring, that it only reads tests/test.sh pip-install lines and has no
    # concept of two DIFFERENT requirements files disagreeing with each other.
    # environment/verifier-requirements.txt and tests/__verifier_lib/requirements.txt pin
    # different exact versions of the same package (pypdf, litellm confirmed on multiple real
    # tasks), defeating a pre-warmed-venv hash-check. Same "std" CLI shape as dependency_pin.
    "verifier_requirements_pin_mismatch": dict(
        script="verifier_requirements_pin_mismatch_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status({"fail": "fail", "warn": "warn", "pass": "pass", "skip": "skip"}),
        findings=_findings_from("findings"),
    ),
    # weight_application_check.py: GLM round 27/28 coverage synthesis Class 5. Same shared
    # script as svc_run_checks.py's registration - see that file for the full rationale
    # (narrowed to a static, package-only precondition check after weight_aggregation_check.py
    # and certification_gate_check.py turned out to already cover the run-dependent halves of
    # this finding, more strongly, which is exactly why this runner does not register either of
    # those two either). On EKW's own verifier.json shape this check only evaluates must-pass
    # presence (info/warn tier) -- EKW has no judge.toml-style subdirectory grouping for a
    # cross-group weighting bug to exist in, per weight_aggregation_check.py's own EKW sample
    # (0/22 pairs flagged).
    "weight_application": dict(
        script="weight_application_check.py",
        letter="D",
        style="rubric_schema",
        task_key="task",
        verdict=lambda r: (
            "fail"
            if r.get("weight_gate_unusable")
            else (
                "error"
                if r.get("parse_errors")
                else "warn" if r.get("possible_findings") else "pass"
            )
        ),
        findings=_findings_from("weight_gate_unusable", "possible_findings"),
    ),
    # compound_criterion / undisclosed_terminology share rubric_schema_check.py's exact CLI
    # and output shape (`<root> [--task ID ...] [--json out.json]`, a bare JSON list keyed by
    # "task"), so they reuse style="rubric_schema" rather than "std". Both separate their own
    # severities in the JSON (compound_fail/compound_warn/tiered_warn; findings/parse_errors),
    # so each gets a verdict lambda instead of _std_status(PF): a real confirmed defect ranks
    # above a parse/config problem (mapped to "error", matching the runner's own "no result"
    # convention) above a heuristic warn above clean.
    "compound_criterion": dict(
        script="compound_criterion_check.py",
        letter="D",
        style="rubric_schema",
        task_key="task",
        verdict=lambda r: (
            "fail"
            if r.get("compound_fail")
            else (
                "error"
                if r.get("parse_errors")
                else (
                    "warn"
                    if (r.get("compound_warn") or r.get("tiered_warn"))
                    else "pass"
                )
            )
        ),
        findings=_findings_from("compound_fail", "compound_warn", "tiered_warn"),
    ),
    "undisclosed_terminology": dict(
        script="undisclosed_terminology_check.py",
        letter="D",
        style="rubric_schema",
        task_key="task",
        verdict=lambda r: (
            "fail"
            if r.get("findings")
            else "error" if r.get("parse_errors") else "pass"
        ),
        findings=_findings_from("findings"),
    ),
    # extraction_groundedness_check.py's CLI/output matches the "std" checks exactly
    # (`<task_ids...|--all> --root DIR --out FILE.json`, {"results": [...]}), but its per-task
    # record has no "status" field to key _std_status() on -- only "summary.by_kind" and
    # "errors" -- so this also gets a custom verdict: only the "_confirmed" finding kind (the
    # command-aware, cross-checked-against-real-code claim; see the script's own docstring) is
    # a fail, "_not_flagged" kept for audit visibility is not, and a missing-config/parse
    # problem is "error" rather than silently "pass".
    "extraction_groundedness": dict(
        script="extraction_groundedness_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=lambda r: (
            "fail"
            if (r.get("summary") or {})
            .get("by_kind", {})
            .get("extraction_blind_confirmed")
            else "error" if r.get("errors") else "pass"
        ),
        findings=_findings_from("findings"),
    ),
    "formula_health": dict(
        script="formula_health_check.py",
        letter="E",
        style="std",
        task_key="task_id",
        verdict=_std_status(PF),
        findings=lambda r: [
            f for f in r.get("findings", []) if f.get("actionable", True)
        ],
    ),
    # Three real gaps, not disclosed exclusions -- confirmed by direct search 2026-09-15 that
    # none of these were ever wired into this orchestrator despite being confirmed dual-format
    # and already run against real EKW data tonight (judge_file_scope_breadth: 26/274 EKW hits;
    # test_coverage_absence: 459/5264 EKW sections; criterion_groundedness: this check's own
    # docstring documents EKW rubric-prompt extraction as first-class, not an afterthought).
    # Found only when asked directly "will every check we built actually fire" -- same CLI
    # shape as compound_criterion/undisclosed_terminology (style="rubric_schema"), verdict
    # logic copied exactly from svc_run_checks.py's own registry for the same three checks.
    # cross_deliverable_consistency_check.py (2026-09-17): confirmed genuine gap, distinct from
    # judge_file_scope_breadth below -- that check asks whether the judge's file scope excludes
    # EXTERNAL source material named in instruction.md; this asks whether ANY criterion's own
    # source spans 2+ of the TASK'S OWN 2+ declared deliverables, i.e. whether anything could
    # ever cross-check the deliverables against each other. Running judge_file_scope_breadth
    # directly against task_78/task_100/task_130 (real confirmed-affected tasks) came back
    # clean on all three -- confirms it does not incidentally cover this. Same "rubric_schema"
    # CLI/output shape as compound_criterion/judge_file_scope_breadth (`<root> [--task ID ...]
    # [--json out.json]`, bare JSON list keyed by "task").
    "cross_deliverable_consistency": dict(
        script="cross_deliverable_consistency_check.py",
        letter="D",
        style="rubric_schema",
        task_key="task",
        verdict=lambda r: (
            "error"
            if r.get("status") == "error"
            else "warn" if r.get("status") == "warn" else (r.get("status") or "error")
        ),
        findings=lambda r: (
            [{"kind": "no_cross_deliverable_check", "deliverable_files": r.get("deliverable_files")}]
            if r.get("status") == "warn"
            else []
        ),
    ),
    "judge_file_scope_breadth": dict(
        script="judge_file_scope_breadth_check.py",
        letter="D",
        style="rubric_schema",
        task_key="task",
        verdict=lambda r: (
            "fail"
            if any(
                f.get("kind")
                in (
                    "judge_scope_zero_source_visibility",
                    "criterion_cites_out_of_scope_file",
                )
                for f in r.get("findings", [])
            )
            else (
                "error"
                if r.get("parse_errors")
                else "warn" if r.get("findings") else "pass"
            )
        ),
        findings=_findings_from("findings"),
    ),
    "test_coverage_absence": dict(
        script="test_coverage_absence_check.py",
        letter="D",
        style="rubric_schema",
        task_key="task",
        verdict=lambda r: (
            "error"
            if r.get("errors")
            else "warn" if r.get("untested_section") else "pass"
        ),
        findings=_findings_from("untested_section"),
    ),
    # instruction_requirement_coverage_check.py: NON-BLOCKING warn-tier candidate
    # tool for Andrew Ma pattern 5 (explicit requirements go ungraded). Same
    # registration rationale as in svc_run_checks.py: deterministic noun-overlap
    # heuristic, warn never fail, surfaces the candidate set for human/LLM review.
    # See the script's own docstring for the measured false-positive rate. Dual-format
    # via ekw_verifier_json so it reads EKW's verifier.json natively; "std" CLI.
    "instruction_requirement_coverage": dict(
        script="instruction_requirement_coverage_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=lambda r: {
            "pass": "pass",
            "warn": "warn",
            "skip": "skip",
        }.get(r.get("status"), "error"),
        findings=_findings_from("findings"),
    ),
    "criterion_groundedness": dict(
        script="criterion_groundedness_check.py",
        letter="D",
        style="rubric_schema",
        task_key="task",
        verdict=lambda r: (
            "fail"
            if r.get("unreachable_criterion")
            else (
                "error"
                if r.get("parse_errors")
                else "warn" if r.get("possible_unreachable") else "pass"
            )
        ),
        findings=_findings_from("unreachable_criterion", "possible_unreachable"),
    ),
    # Same two real gaps as svc_run_checks.py's registry, same reasons - see that file's
    # comment for full context. Confirmed both run against real EKW task data before wiring
    # (task_1): pinned_value_prescreen clean; spelling_grammar found real, UNTUNED false
    # positives on EKW specifically ("mm" -> "my", a currency-scale abbreviation; a likely
    # real proper noun flagged as a typo) - round 8's exclusion-list tuning (338 FPs -> 1) was
    # SVC-PC-only, never validated against EKW's own vocabulary. Warn-only here is not just
    # cautious by convention, it's confirmed necessary by this real evidence.
    "pinned_value_prescreen": dict(
        script="pinned_value_prescreen_check.py",
        letter="D",
        style="rubric_schema",
        task_key="task",
        verdict=lambda r: (
            "error"
            if r.get("parse_errors")
            else "warn" if r.get("findings") else "pass"
        ),
        findings=_findings_from("findings"),
    ),
    "spelling_grammar": dict(
        script="spelling_grammar_check.py",
        letter="D",
        style="rubric_schema",
        task_key="task",
        verdict=lambda r: "warn" if r.get("findings") else "pass",
        findings=_findings_from("findings"),
    ),
    # Pre-delivery gold-replay gate (turing-context-09, 2026-09-15): does tests/test.sh parse
    # under a real (non-Cygwin) bash, and does the task's own gold reach reward 1.0 against its
    # own verifier under an approving judge. Both are hard pass/fail gates, not heuristics - a
    # failure here means the task is ungradable regardless of submission quality. Full 274-task
    # EKW corpus: 110 pass / 164 fail (60%). Dual-format (EKW gold-replay, SVC-PC
    # rewardkit.discover() config-validity + referenced-file-existence). These EKW numbers are
    # unaffected by the 2026-09-16 SVC-PC fix below - the two format branches share this script
    # but not this code path.
    #
    # 2026-09-16 fix (SVC-PC branch only, see svc_run_checks.py's own registration comment for
    # the full story): the referenced-file-existence half only checked solution/files/, so any
    # judge.toml file that ships in environment/initial_workspace/ instead (the far more common
    # case per BUILD-CONTRACT.md - /app/ starts pre-seeded with the environment, solve.sh only
    # overlays solution/files/ on top) read as "missing". Confirmed as the sole cause of 71/202
    # (35%) SVC-PC fails in Khiem's 2026-09-16 Step 2 run (908/908 missing-file entries traced to
    # environment/initial_workspace/, 0 genuinely absent). Now checks both directories; see
    # `_environment_basenames` in verifier_executability_check.py.
    "verifier_executability": dict(
        script="verifier_executability_check.py",
        letter="E",
        style="std",
        task_key="task_id",
        verdict=_std_status(PF),
        findings=lambda r: [
            {"kind": "verifier_not_executable", "detail": e}
            for e in r.get("errors", [])
        ],
    ),
    # S-6 (Pietro Carra / turing-context-09, 2026-09-15): flags a verifier source whose
    # gold-replay extracted text lands exactly at max_content_chars (90000) - the tell for
    # SourceRegistry's silent, unmarked truncation. Every finding is a candidate for human
    # review, not a confirmed defect (exact-boundary match is strong evidence, not proof the cut
    # lost material content) - warn, never fail, same posture as pinned_value_prescreen and
    # judge_file_scope_breadth's non-definitive kinds above.
    "source_truncation": dict(
        script="source_truncation_check.py",
        letter="E",
        style="std",
        task_key="task_id",
        verdict=lambda r: (
            "warn"
            if r.get("status") == "candidates_found"
            else (
                "skip"
                if r.get("status") == "not_applicable"
                else "error" if r.get("status") == "error" else "pass"
            )
        ),
        findings=_findings_from(
            "ekw_truncation.candidates", "svc_pc_oversized_file_marked_skip.files"
        ),
    ),
    # S-10 (Pietro Carra / turing-context-09, 2026-09-15): for every file a task's grading
    # config actually reads as a source, checks whether that filename is ever named in
    # instruction.md - solve.sh copies every golden file into the graded directory, so an
    # unrequested file can ride along as a real, gradable source. Candidate, not confirmed (a
    # file could be named by description rather than exact filename) - warn, not fail. Real
    # overlap with deliverable_filename_check.py disclosed by the builder, not hidden; worth a
    # human call on whether these merge, not resolved by registering it separately here.
    "unrequested_deliverable_source": dict(
        script="unrequested_deliverable_source_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=lambda r: (
            "warn"
            if r.get("status") == "candidate"
            else (
                "skip"
                if r.get("status") == "skip"
                else "error" if r.get("status") == "error" else "pass"
            )
        ),
        findings=_findings_from("findings"),
    ),
    # S-3 (Pietro Carra / turing-context-09, 2026-09-15): does the verifier's OWN extraction
    # path (load_workbook(data_only=True)) see the same content a fresh recalculation would -
    # a formula cell with no cached value arrives as "" to the real grader regardless of whether
    # recomputation would fix it. Distinct mode of formula_health_check.py itself (own registry
    # entry, not folded into "formula_health" above, since it's a genuinely separate report
    # shape triggered by --check-extraction-loss, not an additional field on the default mode).
    "formula_health_extraction_loss": dict(
        script="formula_health_check.py",
        letter="E",
        style="std",
        task_key="task_id",
        extra_args=["--check-extraction-loss"],
        verdict=lambda r: (
            "skip" if r.get("status") == "not_applicable" else _std_status(PF)(r)
        ),
        findings=_findings_from("findings"),
    ),
    # golden_arithmetic_check.py: GLM round 27/28 coverage synthesis Class 2 (golden-value
    # arithmetic correctness -- the golden's own stated number is computed WRONG from real
    # source data that DOES exist). A third, distinct defect class from formula_health (recomputes
    # a live Excel FORMULA against its own cache; these goldens are literal typed-in values, zero
    # formulas) and criterion_groundedness (checks whether a fact exists anywhere in environment/,
    # never whether a SUM of it is arithmetically correct). Same "std" CLI shape as
    # formula_health_check.py; the scan itself is format-agnostic (only looks under solution/ and
    # environment/, regardless of judge.toml vs. verifier.json), but was built and validated
    # against the SVC-PC corpus specifically -- see the script's own docstring Known limits. Ported
    # into this registry for parity with svc_run_checks.py (same convention as
    # verifier_executability/source_truncation/formula_health_extraction_loss being ported the
    # other direction, commits 80a7698/027957a), not because it has been separately validated
    # against a real EKW task yet.
    "golden_arithmetic": dict(
        script="golden_arithmetic_check.py",
        letter="E",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {"pass": "pass", "warn": "warn", "fail": "fail", "skip": "skip"}
        ),
        findings=_findings_from("findings"),
    ),
    # golden_groundedness_check.py: same script as svc_run_checks.py's registration (see that
    # runner's comment for the full real-verification detail -- ported 2026-09-16 for tracker
    # row 13, real adaptation for this repo's structurally different golden_arithmetic_check.py,
    # retrieval rebuilt and verified against the real SVC-PC-5-3-0 task, row-15 token-budget fix
    # applied). SVC-PC-only in practice for the same reason rubric_overspecification_check.py is:
    # not separately validated against a real EKW task, ported for parity only. Warn-only,
    # EXPENSIVE (one real LLM call per task, 39-111s observed) -- give it a generous --timeout.
    "golden_groundedness": dict(
        script="golden_groundedness_check.py",
        letter="E",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {"pass": "pass", "warn": "warn", "skip": "skip", "error": "error"}
        ),
        findings=_findings_from("findings"),
    ),
    # duplicate_criterion_content_check.py: coverage-synthesis gap class -- near-duplicate
    # Expected-clause/description (SVC-PC) or full rubric-prompt (EKW) text across
    # DIFFERENTLY-NAMED criteria (TF-IDF cosine, threshold 0.42, min 3 shared content tokens).
    # Distinct from duplicate_criterion_check.py (pre-conversion xlsx ID collision, excluded on
    # the SVC-PC side for a different reason) and judge_criterion_name_duplicate_check.py (same
    # NAME, not content). Dual-format via ekw_verifier_json, same "std" CLI shape. Verified
    # against the real SVC-PC corpus before registering (this script's comparison text and
    # threshold were calibrated on SVC-PC; no separate EKW-side real-defect calibration sample
    # was available). Updated 2026-09-16 after porting GLM round 33's Jaccard-distance
    # value-divergence gate (independently re-verified against the real 600-task SVC-PC corpus):
    # SVC-PC-29-2-0 now 9 clusters / 27.19% excess (was 10/33.73%), SVC-PC-33-8-0 now 8 clusters
    # / 49.5% (was 9/50.5%) -- both still correctly flag; SVC-PC-21-4-0 still clean (0 clusters).
    # Full SVC-PC corpus: fail=230/warn=170/pass=200 (pre-fix) -> warn=355/pass=245/fail=0
    # (post-fix) -- the "fail" tier was removed entirely (a real, disclosed-in-code severity
    # downgrade bundled into the same round, not just the similarity-gate fix), so this check is
    # now warn-only on both formats.
    "duplicate_criterion_content": dict(
        script="duplicate_criterion_content_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {
                "pass": "pass",
                "warn": "warn",
                "fail": "fail",
                "skip": "skip",
                "error": "error",
            }
        ),
        findings=_findings_from("clusters"),
    ),
    # same_file_requirement_duplicate_check.py: narrower SIBLING of duplicate_criterion_content
    # above, added 2026-09-16. Same script as svc_run_checks.py's registration (see that
    # runner's comment for the full real-corpus verification: fail=10/pass=590 on the real
    # 600-task SVC-PC corpus, all 15 findings hand-confirmed genuine). SVC-PC-only in practice --
    # EKW has no "Expected:" label convention (see the check's own module docstring "Known
    # limits"), so the EKW branch is format-completeness/never-crash, not separately calibrated.
    "same_file_requirement_duplicate": dict(
        script="same_file_requirement_duplicate_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {"pass": "pass", "fail": "fail", "skip": "skip", "error": "error"}
        ),
        findings=_findings_from("findings"),
    ),
    # task_metadata_completeness_check.py: task.toml's [metadata] domain/occupation/sector/
    # subdomain/task_type fields. Warn-only by design -- no scoring effect, cataloguing/
    # discoverability only -- never fails a task. Same "std" CLI shape. Verified against the
    # real SVC-PC calibration tasks (29-2-0, 33-8-0, 21-4-0): 5 findings/task (one per absent
    # field), matching the documented real empty-metadata SVC-PC shape; the check's own
    # docstring separately confirms a real complete-metadata EKW sample (task_175) produces 0
    # findings, so both formats were checked, not just SVC-PC's.
    "task_metadata_completeness": dict(
        script="task_metadata_completeness_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status({"pass": "pass", "warn": "warn", "skip": "skip"}),
        findings=_findings_from("findings"),
    ),
    # source_citation_existence_check.py: golden CELL CONTENT citing a file-path-shaped string
    # absent from environment/ (sub-case A, mechanical) and instruction.md naming a file by
    # CATEGORY with no plausibly matching environment basename (sub-case B, a disclosed
    # heuristic that cannot distinguish "no file at all" from "a file exists but is the wrong
    # type"). Distinct from criterion_groundedness_check.py (criterion text, not golden cell
    # text) and content-audit/SKILL.md pattern 3 (LLM-judged prose, not a filesystem check).
    # Warn-only, never fails. Same "std" CLI shape. Verified against the real SVC-PC corpus:
    # SVC-PC-37-3-0 reproduces its named real defect exactly (golden cites
    # ".../MSA_SwiftShip_2021.pdf", absent from environment/) plus one further same-pattern
    # finding (MSA_Apex_2021.pdf, also absent); SVC-PC-41-4-0 correctly does not fire, per this
    # check's own disclosed "wrong file type" limitation (environment/ carries
    # SwiftShip_Evaluation.docx and three Apex_*.docx/.pdf files, but no Apex/SwiftShip rate
    # card -- confirmed by direct listing, not assumed). Updated 2026-09-16 after porting GLM
    # round 33's precision pass (17% cut to sub-case A extraction-artifact false positives;
    # sub-case B's COMMON_CAPITALIZED_WORDS exclusion cut its false-positive rate from ~98% to
    # 5/600 real tasks) -- independently re-verified against the real 600-task SVC-PC corpus:
    # warn=297/pass=303 (pre-fix) -> warn=255/pass=345 (post-fix). Still warn-only.
    "source_citation_existence": dict(
        script="source_citation_existence_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {"pass": "pass", "warn": "warn", "skip": "skip", "error": "error"}
        ),
        findings=_findings_from("findings"),
    ),
    # rubric_overspecification_check.py: the inverse of instruction_requirement_coverage_check.py
    # above (that one asks "does every instruction requirement have a covering criterion"; this
    # one asks "does every criterion's pinned value/count/name/format have instruction-level
    # support, or did the rubric narrow what the instruction left open") -- structural mirror
    # images, so same letter D as that check, NOT letter A. content-audit/SKILL.md, the only
    # "Check A" this pipeline names anywhere, has no CLI and no CHECKS entry in either
    # orchestrator, and LETTERS here is ("B","C","D","E") -- registering letter "A" would
    # KeyError in merge()'s `by_letter = {L: [] for L in LETTERS}` on the first task processed,
    # confirmed by reading merge() directly rather than assumed. This is LLM-judgment territory
    # like content-audit, but unlike content-audit it ships a real CLI (task_ids + --root +
    # --out, same "std" shape) that reuses tools/llm_backend.call_llm() -- Claude Code CLI first
    # (free under a Max plan) then a caller-configured HTTP backend, never a hardcoded
    # credential. UNLIKE every other entry in this dict, one run of this check makes one LLM
    # call PER TASK -- 50-100s, not milliseconds -- and a real cost/time commitment when the CLI
    # backend is unavailable and a paid HTTP backend is configured instead. A bare `--all` with
    # no `--checks` filter now attempts this for every task in the corpus; scope with `--checks`
    # to exclude it from a fast sweep. Verified before registering (against the real SVC-PC
    # corpus; this check's prompt/extraction path is dual-format but was not separately
    # calibrated against a real EKW over-specification example): unit tests (16/16,
    # fixture-only, no real call); --dry-run confirms prompt construction surfaces all three
    # named real over-specification cases in SVC-PC-33-8-0 (5-vs-4 checks, the 4-name roster,
    # the deferred tolerance).
    #
    # Root-caused a real reliability failure found during this verification (2026-09-16,
    # tracker row 15), not just disclosed it: the first 8 real calls against the configured HTTP
    # backend (an OpenAI-compatible endpoint serving a reasoning model, glm-5.2) returned usable
    # content on only 1 of 8. Diagnosed with instrumented raw-HTTP calls (status/headers/usage,
    # bypassing call_llm() only far enough to see them) rather than guessing: every failure was a
    # clean 200 with `finish_reason: "length"` and `completion_tokens` sitting EXACTLY at
    # max_tokens (4096, the tools/llm_backend.py library default) -- the model's hidden reasoning
    # was consuming the entire generation budget before emitting any visible answer, not rate
    # limiting (no 429s, no rate-limit headers, `x-litellm-key-spend` far under
    # `x-litellm-key-max-budget` throughout) and not auth or malformed-request flakiness (status
    # 200 every time). This check's own module docstring already named "roughly 32000" as the
    # working number and claimed it "was already fixed in tools/llm_backend.py itself" -- that
    # claim was false (call_llm() exposed no override point that reached this far) -- so the fix
    # is `os.environ.setdefault("LLM_API_MAX_TOKENS", "32000")` near this script's own imports,
    # not a change to the shared library's generic default. Verified at real sample size, not 1-2
    # lucky calls: 9 of 9 real calls at 32000 succeeded (`finish_reason: "stop"`, natural
    # completion, 12,948-24,084 completion tokens observed -- comfortably under the ceiling) after
    # 10 of 10 real calls at 4096 failed the same way, across this check's own prompt (6 calls)
    # and content_audit_check.py's (3 calls, run from the mirror for comparison, confirming this
    # is backend-wide, not specific to one check's prompt). A 32000-token completion also needs
    # more wall time (52-99s observed vs the 18-24s a failed 4096 call took) -- give this check a
    # generous `--timeout`, at least 180s, when running for real.
    "rubric_overspecification": dict(
        script="rubric_overspecification_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {"pass": "pass", "warn": "warn", "skip": "skip", "error": "error"}
        ),
        findings=_findings_from("findings"),
    ),
    # cell_address_pinned_check.py: same script as svc_run_checks.py's
    # registration (see that runner's comment for the full rationale and
    # validation). Deterministic regex for the 5th over-specification category
    # (numeric value + spreadsheet cell address pinned together). Dual-format
    # via ekw_verifier_json, style="rubric_schema", warn-only. EKW-TESTED
    # against the real 274-task corpus: 0 sheet-qualified findings (EKW
    # verifier.json rubric prompts are free-text descriptions that don't
    # typically use the Sheet!Cell form), 5 bare findings (all false positives --
    # part/identifier codes like CNC12, K2207, M4410, D771 that match the bare
    # cell-ref shape but are not spreadsheet cell references). The check runs
    # correctly on EKW data (reads verifier.json, parses criteria, produces
    # findings) -- the 0 sheet-qualified count is a real signal that this
    # defect shape does not appear in the EKW corpus, not a parsing failure.
    # word_ban_false_trigger_check.py: same script as svc_run_checks.py's registration
    # (see that runner's comment for the full negation-proximity fix and the 10-task
    # before/after verification). Never wired into this orchestrator on the SVC-side
    # 2026-09-17 fix, even though the script has always dual-supported EKW natively
    # (check_task_ekw / has_ekw_config / load_ekw_criteria, ekw=True path). Verified
    # here against a real EKW task before registering: `python
    # word_ban_false_trigger_check.py C:\ekwqc\_merged274\files --task task_1` returns
    # a real, non-crashing result (format=ekw, 20 criteria, 0 word-ban, ok=true), not
    # a guess.
    "word_ban_false_trigger": dict(
        script="word_ban_false_trigger_check.py",
        letter="D",
        style="rubric_schema",
        task_key="task",
        verdict=lambda r: (
            "fail"
            if not r.get("ok")
            else "warn" if r.get("possible_findings") else "pass"
        ),
        findings=_findings_from("findings", "possible_findings"),
    ),
    "cell_address_pinned": dict(
        script="cell_address_pinned_check.py",
        letter="D",
        style="rubric_schema",
        task_key="task",
        verdict=lambda r: (
            "error"
            if r.get("parse_errors")
            else "warn" if r.get("findings") else "pass"
        ),
        findings=_findings_from("findings"),
    ),
    # structural_audit_check.py: closes tracker rows 28-29 (the two real SVC-PC
    # defects every existing check missed) by automating the six-pattern manual
    # "structural audit" methodology (structural-audit/SKILL.md) as a real
    # LLM-judge check. Feeds the LLM the real instruction.md (with line numbers),
    # the real verifier.json source files (split into solver-produced
    # deliverables vs judge read-scope sources via deliverable_filename_check.py's
    # format-dispatching loader), the real verifier criteria, and a real
    # environment file manifest, then asks it to apply the six structural
    # patterns and report per-pattern pass/fail/warn with a verbatim quote.
    #
    # LETTER CHOICE - letter C, NOT letter A. The brief said "under the LLM-judge
    # group (check A)" but also said "do not assume A is correct without
    # checking"; checking settles it: LETTERS on this runner is ("B","C","D","E")
    # and registering "A" would KeyError in merge()'s
    # `by_letter = {L: [] for L in LETTERS}` on the first task processed
    # (confirmed by reading merge() directly, line 1188, not assumed). The
    # letter tracks the DEFECT CLASS, not the method: these six patterns are
    # STRUCTURAL defects (instruction.md vs the real verifier source files vs
    # the real environment listing), the same defect class as the deterministic
    # C checks (environment_input, deliverable_count, answer_key_leakage).
    # Letter C is the correct fit. content-audit/SKILL.md is the pipeline's
    # "Check A" by tracker column but has no CLI and no CHECKS entry; this check
    # ships the CLI the structural patterns need to run automatically in the
    # normal process.
    #
    # Same "std" CLI shape and warn-only "candidate, not verdict" posture as
    # golden_groundedness and rubric_overspecification. EXPENSIVE: one real LLM
    # call per task; give it a generous --timeout and scope with --checks to
    # exclude it from a fast sweep.
    #
    # EKW-TESTED (not untested): ran two real EKW tasks (task_1, task_15) at
    # C:/ekwqc/_merged274/files via the format-dispatching helpers
    # (load_criteria_for_task -> load_ekw_criteria_list, find_environment_files
    # -> environment/data/, load_deliverable_files -> load_ekw_files); both
    # returned a real LLM verdict (clean, 20 and 23 criteria respectively), so
    # the format-agnostic path is live, not assumed. The motivating row-28/29
    # defects are SVC-PC tasks; no EKW-specific structural defect was verified
    # against this check yet (the two EKW tasks sampled came back clean), so an
    # EKW-side false-positive rate has not been measured. See
    # ROUND62-ROW28-29-REPORT.md.
    "structural_audit": dict(
        script="structural_audit_check.py",
        letter="C",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {"pass": "pass", "warn": "warn", "skip": "skip", "error": "error"}
        ),
        findings=_findings_from("findings"),
    ),
    # judge_scope_under_inclusion_check.py: LLM-judge check for tracker row 32 (judge files=
    # too NARROW -- the OPPOSITE end of the axis judge_scope_over_inclusion closes). Same
    # script as svc_run_checks.py's registration (see that runner's comment for the full
    # rationale and the four-task real verification against the live SVC-PC corpus). Letter
    # D, style "std", task_key "task_id", warn-only -- same posture and CLI shape as
    # rubric_overspecification / golden_groundedness above.
    #
    # EKW-UNTESTED: the check's design is format-agnostic (dual-format dispatch reuses
    # judge_file_scope_breadth_check.py's SVC-PC group loader and ekw_verifier_json.py's
    # load_ekw_criteria for EKW, same convention judge_scope_over_inclusion follows), so it
    # reads EKW verifier.json natively. But no real EKW under-inclusion defect example was
    # available to validate against this session -- EKW verifiers typically carry only the
    # deliverable path in source.file (judge_scope_over_inclusion's own docstring notes the
    # over-inclusion shape "almost never fires on EKW" for the same reason), so the narrow
    # end is expected to be rare on EKW too. Registered for parity with the SVC orchestrator
    # (an orchestrator silently missing a real check is the exact failure class this whole
    # effort closes), marked EKW-UNTESTED pending real EKW data access. Like the other LLM
    # checks, one run makes one real LLM call per task -- scope with --checks to exclude it
    # from a fast sweep.
    "judge_scope_under_inclusion": dict(
        script="judge_scope_under_inclusion_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {"pass": "pass", "warn": "warn", "skip": "skip", "error": "error"}
        ),
        findings=_findings_from("findings"),
    ),
    # 2026-09-17 QCR tracer (append-only; do not rebase onto the pin-mismatch /
    # cross-deliverable registrations above). Warn-only until corpus FP rates exist.
    # Post-run Oracle/CR gates live in pre_submit_gate.py, not --all.
    "accepted_alternative_compatibility": dict(
        script="accepted_alternative_compatibility_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {"pass": "pass", "warn": "warn", "skip": "skip", "error": "error"}
        ),
        findings=_findings_from("findings"),
    ),
    # fabricated_unfilenamed_fact_check.py: tracker row 35 (round 62). The automated
    # LLM-judge "check A" (content audit) this pipeline's tracker mapping had always
    # left as "not scripted, needs a human/LLM read". See svc_run_checks.py's own
    # registration for the full design and the real 4-task acceptance-test record
    # (3 true positives flag, 1 true negative clears, stable across two runs). This
    # entry is the EKW-side parity registration: same script, same "std" CLI shape,
    # same warn-only posture.
    #
    # Format-agnostic by construction: _task_format dispatches to environment/data/
    # (raw EKW) or environment/initial_workspace/ (staged EKW after check_b), and to
    # solution/golden_outputs/ or solution/files/ for the golden. Verified via
    # --dry-run on a real raw EKW task (task_15 in C:\\ekwqc\\_ekw119_harbor: fmt=ekw,
    # 3 golden, 5 env, 35707-char prompt) and a real staged EKW task (task_1 in
    # C:\\ekwqc\\_ekw274_stage: fmt=svc_pc, 2 golden, 8 env, 23203-char prompt). Both
    # built a real prompt with golden text + the recursive environment file listing.
    # EKW-UNTESTED at the real-LLM-call level: the 4-task acceptance test ran against
    # SVC-PC tasks only (the three confirmed instances and the one true negative are
    # all SVC-PC); no real EKW true-positive/negative pair was available to calibrate
    # against, so this registration is format-completeness, not a separately
    # validated EKW defect detector. The check will not crash on EKW (the format
    # dispatch and env walk are verified), but its precision/recall on EKW goldens
    # (which are memos/workbooks with different prose conventions) is unmeasured. A
    # follow-up adversarial review also found the 4-task acceptance split does NOT
    # reliably hold past 2 runs; treat a single clean verdict as advisory only.
    #
    # Letter D, not a new "A" slot: this project's own letter legend has no "A" - the only
    # thing "check A" names anywhere in this codebase is `content-audit/SKILL.md`, explicitly
    # logged as NOT registered in this file because it is "0% script, 100% judgment... cannot
    # be wired into this subprocess harness tonight or ever, on its current design." This
    # check is the opposite (a real, runnable, automated LLM check), so it was never a fit for
    # that slot. D is where this project already keeps groundedness/citation-shaped checks:
    # source_citation_existence, criterion_groundedness, judge_scope_over_inclusion,
    # judge_scope_under_inclusion - this is a direct sibling of all four, not a new category.
    # (Corrected 2026-09-17 from an earlier commit that added a real "A" slot to LETTERS;
    # reverted alongside this change - no LETTERS edit needed, D already exists. Two
    # independent adversarial reviews confirmed the "A" slot would have silently broken
    # ekw_tracker_writeback.py, which is hardcoded to B-E.)
    #
    # EXPENSIVE: one real LLM call per task (70-280s observed against glm-5.2). Give
    # it a generous --timeout and scope with --checks for a fast sweep.
    "fabricated_unfilenamed_fact": dict(
        script="fabricated_unfilenamed_fact_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {"pass": "pass", "warn": "warn", "skip": "skip", "error": "error"}
        ),
        findings=_findings_from("findings"),
    ),
    # judge_file_size_cliff_check.py (row 31): same script as svc_run_checks.py's
    # registration (see that runner's comment for the full design rationale, the
    # golden-complexity investigation that proved non-predictive, and the
    # threshold calibration against the real 202-task SVC-PC subset). Format-
    # agnostic: walks environment/data/ for EKW (vs environment/initial_workspace/
    # for SVC-PC) and globs solution/ recursively for goldens, so the same script
    # runs on both formats with zero changes.
    #
    # EKW-UNTESTED: the check was calibrated against the SVC-PC xlsx-embedding
    # bloat mechanism (one real incident, SVC-PC-66-2-0). A 3-task EKW smoke test
    # (task_1, task_10, task_100) ran clean: EKW environment/data/ carries .md
    # SEC-filing files, not the csv/json/xlsx data exports that drive SVC-PC
    # bloat. The .md extension is not in the check's DATA_EXTS, so no EKW task
    # is flagged today. This is honest: EKW's bloat mechanism (if any) is a
    # different shape, not calibrated against any real incident. Registered for
    # parity (same convention as golden_arithmetic/golden_groundedness above,
    # which are also SVC-PC-calibrated and EKW-untested) so the check runs and
    # reports 0 findings rather than being silently absent.
    #
    # CLI: <root> [--task ID] [--json OUT], style="rubric_schema". WARN never gates.
    "judge_file_size_cliff": dict(
        script="judge_file_size_cliff_check.py",
        letter="D",
        style="rubric_schema",
        task_key="task",
        verdict=lambda r: "warn" if r.get("findings") else "pass",
        findings=_findings_from("findings"),
    ),
    # --- letter F: the six pre-submission questions (sixq_checks.py; see README_sixq.md) ---
    # Same "std" CLI shape; warn-only, uncalibrated candidates. F1 to F3 make one claude call
    # per task and report skip (not error) when no claude login is present.
    "sixq_f1": dict(
        script="ekw/sixq_checks.py",
        letter="F",
        style="std",
        task_key="task_id",
        extra_args=["--question", "1"],
        verdict=_std_status({"pass": "pass", "warn": "warn", "skip": "skip", "error": "error"}),
        findings=_findings_from("findings"),
    ),
    "sixq_f2": dict(
        script="ekw/sixq_checks.py",
        letter="F",
        style="std",
        task_key="task_id",
        extra_args=["--question", "2"],
        verdict=_std_status({"pass": "pass", "warn": "warn", "skip": "skip", "error": "error"}),
        findings=_findings_from("findings"),
    ),
    "sixq_f3": dict(
        script="ekw/sixq_checks.py",
        letter="F",
        style="std",
        task_key="task_id",
        extra_args=["--question", "3"],
        verdict=_std_status({"pass": "pass", "warn": "warn", "skip": "skip", "error": "error"}),
        findings=_findings_from("findings"),
    ),
    "sixq_f4": dict(
        script="ekw/sixq_checks.py",
        letter="F",
        style="std",
        task_key="task_id",
        extra_args=["--question", "4"],
        verdict=_std_status({"pass": "pass", "warn": "warn", "skip": "skip", "error": "error"}),
        findings=_findings_from("findings"),
    ),
    "sixq_f5": dict(
        script="ekw/sixq_checks.py",
        letter="F",
        style="std",
        task_key="task_id",
        extra_args=["--question", "5"],
        verdict=_std_status({"pass": "pass", "warn": "warn", "skip": "skip", "error": "error"}),
        findings=_findings_from("findings"),
    ),
    "sixq_f6": dict(
        script="ekw/sixq_checks.py",
        letter="F",
        style="std",
        task_key="task_id",
        extra_args=["--question", "6"],
        verdict=_std_status({"pass": "pass", "warn": "warn", "skip": "skip", "error": "error"}),
        findings=_findings_from("findings"),
    ),
    "xlsx_extraction_budget": dict(
        script="xlsx_extraction_budget_check.py",
        letter="E",
        style="std",
        task_key="task_id",
        verdict=_std_status(
            {
                "pass": "pass",
                "warn": "warn",
                "fail": "fail",
                "skip": "skip",
                "error": "error",
            }
        ),
        findings=_findings_from("findings"),
    ),
}
LETTERS = ("B", "C", "D", "E", "F")
SIXQ = ("sixq_f1", "sixq_f2", "sixq_f3", "sixq_f4", "sixq_f5", "sixq_f6")
# Longest-running checks first when scheduling shards (formula recomputation dominates).
HEAVY = (
    "formula_health",
    "deliverable_integrity",
    "answer_key_content_leak",
    "tab_naming",
)


def rollup(verdicts: list[str]) -> str:
    for v in ("fail", "error", "warn", "pass"):
        if v in verdicts:
            return v
    return "skip"


def run_shared_check(
    name: str,
    spec: dict,
    target: Path,
    out_dir: Path,
    task_ids,
    shard: int,
    timeout: int,
) -> dict:
    """One shard of one shared check: the check's own script over an explicit list of task
    ids, writing <out_dir>/_shards/<name>.<shard>.json. Every shared check walks its tasks
    serially, and formula_health_check.py alone takes about 17 s per task, so one process per
    check is an 80-minute run on 274 tasks; sharded across the cores it is a few minutes.
    """
    shard_dir = out_dir / "_shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    out_json = shard_dir / f"{name}.{shard:02d}.json"
    if out_json.exists():
        out_json.unlink()
    script = CHECKS_DIR / spec["script"]
    if spec["style"] == "rubric_schema":
        cmd = [sys.executable, str(script), str(target), "--json", str(out_json)]
        for t in task_ids:
            cmd += ["--task", t]
    else:
        cmd = [
            sys.executable,
            str(script),
            *task_ids,
            "--root",
            str(target),
            "--out",
            str(out_json),
        ]
        # A check can share its script file with another registry entry but run a distinct mode
        # via a static flag (e.g. formula_health_extraction_loss reuses formula_health_check.py
        # itself with --check-extraction-loss) - spec["extra_args"] carries that flag through.
        # Empty/absent for every check that doesn't need one, so this is a no-op for the rest.
        cmd += spec.get("extra_args", [])
        # formula_health_check.py, verifier_executability_check.py, source_truncation_check.py
        # and unrequested_deliverable_source_check.py are the checks in this folder that run
        # their own internal ProcessPoolExecutor (all default to cpu_count-1 workers when --jobs
        # is unspecified, confirmed in their own source - formula_health_extraction_loss shares
        # formula_health_check.py's own pool under its --check-extraction-loss mode, same
        # mechanism). Without this, each of THIS runner's own outer shards spawns a full inner
        # pool independently, multiplying real concurrency by the shard count on top of whatever
        # --jobs/--shards was requested here - confirmed as the real mechanism behind a
        # BrokenProcessPool crash on a genuine full-274-task run (2026-09-15) for
        # formula_health_check.py, not resource contention in the abstract; the other three have
        # the identical shape (their own ProcessPoolExecutor(max_workers=args.jobs), same
        # default), so they get the same treatment on registration rather than waiting to
        # reproduce the same crash. The outer sharding already IS each check's parallelism;
        # forcing its own inner pool to 1 makes total concurrency match what --jobs actually
        # asked for instead of silently multiplying it.
        if name in (
            "formula_health",
            "formula_health_extraction_loss",
            "verifier_executability",
            "source_truncation",
            "unrequested_deliverable_source",
        ):
            cmd += ["--jobs", "1"]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    t0 = time.time()
    rec = {
        "check": name,
        "shard": shard,
        "n_tasks": len(task_ids),
        "task_ids": list(task_ids),
        "cmd": (
            cmd[:3] + ["<%d task ids>" % len(task_ids)] + cmd[3 + len(task_ids) :]
            if spec["style"] != "rubric_schema"
            else cmd[:4] + ["<%d --task pairs>" % len(task_ids)]
        ),
        "returncode": None,
        "seconds": None,
        "stderr_tail": "",
        "json": str(out_json),
        "ok": False,
    }
    try:
        p = subprocess.run(
            cmd,
            cwd=str(CHECKS_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        rec["returncode"] = p.returncode
        rec["stderr_tail"] = ((p.stderr or "") + (p.stdout or ""))[-2000:]
    except subprocess.TimeoutExpired:
        rec["stderr_tail"] = f"timed out after {timeout}s"
    rec["seconds"] = round(time.time() - t0, 1)
    rec["ok"] = out_json.is_file()
    print(
        f"  {name:<32} shard {shard:02d} ({len(task_ids):>3} tasks) rc={rec['returncode']} {rec['seconds']:>7}s {'json ok' if rec['ok'] else 'NO JSON'}",
        file=sys.stderr,
    )
    return rec


def merge_shards(name: str, spec: dict, out_dir: Path, shard_recs: list[dict]) -> dict:
    """Combine a check's shard JSONs into <out_dir>/<name>.json with the check's own top-level
    shape: `results` (or the bare list rubric_schema writes) concatenated in shard order,
    integer `n_*` counters and integer-valued count dicts summed, everything else taken from
    the first shard. Returns a run record for runs.json."""
    out_json = out_dir / f"{name}.json"
    merged = None
    ok_shards = [r for r in sorted(shard_recs, key=lambda r: r["shard"]) if r["ok"]]
    for r in ok_shards:
        data = json.loads(Path(r["json"]).read_text(encoding="utf-8"))
        if merged is None:
            merged = data
            continue
        if isinstance(data, list):
            merged.extend(data)
            continue
        for k, v in data.items():
            if k == "results":
                merged.setdefault("results", []).extend(v)
            elif isinstance(v, bool):
                continue
            elif isinstance(v, int) and (k.startswith("n_") or k.startswith("total_")):
                merged[k] = merged.get(k, 0) + v
            elif (
                isinstance(v, dict)
                and v
                and all(isinstance(x, int) for x in v.values())
            ):
                base = merged.setdefault(k, {})
                for kk, vv in v.items():
                    base[kk] = base.get(kk, 0) + vv
    if merged is not None:
        out_json.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    rc = (
        max(
            (r["returncode"] if r["returncode"] is not None else 99) for r in shard_recs
        )
        if shard_recs
        else None
    )
    failed_shards = [r for r in shard_recs if not r["ok"]]
    # Every task_id that lived in a shard that never produced JSON - not a per-task failure,
    # the check simply never ran on these tasks this pass. Kept separate from "genuinely no
    # result" so merge() can report it accurately instead of a misleading "check crashed or
    # skipped it" on every task in the run.
    missing_task_ids = sorted(
        {tid for r in failed_shards for tid in r.get("task_ids", [])}
    )
    rec = {
        "check": name,
        "shards": len(shard_recs),
        "shards_ok": len(ok_shards),
        "returncode": rc,
        "seconds": round(sum(r["seconds"] or 0 for r in shard_recs), 1),
        "wall_seconds_max_shard": (
            max((r["seconds"] or 0) for r in shard_recs) if shard_recs else 0
        ),
        "stderr_tail": "\n".join(
            f"[shard {r['shard']:02d}] " + (r["stderr_tail"] or "")[-600:]
            for r in shard_recs
            if not r["ok"] or (r["returncode"] not in (0, 1))
        ),
        "json": str(out_json),
        # "ok": every shard succeeded, no gaps at all - the strong, original meaning, kept for
        # any caller that only wants a fully-clean run.
        "ok": merged is not None and len(ok_shards) == len(shard_recs),
        # "partial_ok": at least one shard produced real data, worth merging and reporting
        # rather than discarding wholesale - this is what a caller should actually gate on to
        # avoid throwing away 7/8 shards' worth of real results over 1 shard dying.
        "partial_ok": merged is not None,
        "failed_shards": [r["shard"] for r in failed_shards],
        "missing_task_ids": missing_task_ids,
    }
    print(
        f"  {name:<32} merged {len(ok_shards)}/{len(shard_recs)} shards, cpu {rec['seconds']}s, "
        f"{'json ok' if rec['ok'] else (f'PARTIAL - {len(missing_task_ids)} tasks missing' if rec['partial_ok'] else 'INCOMPLETE - no shards produced data')}",
        file=sys.stderr,
    )
    return rec


def load_results(name: str, spec: dict, out_json: Path) -> dict[str, dict]:
    if not out_json.is_file():
        return {}
    data = json.loads(out_json.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("results", [])
    return {str(r.get(spec["task_key"])): r for r in rows if isinstance(r, dict)}


def _reconcile_environment_input(r: dict, graded: list[str]) -> tuple[str | None, str]:
    """EKW prompts name the DELIVERABLES ("Produce the following deliverables in `/app/`: -
    `x.xlsx`, ...") and describe inputs by content, never by filename. The unported
    environment_input_check.py reads those deliverable names as inputs the solver was promised
    and reports every one of them missing from initial_workspace/ (pattern 1), a false
    positive on every EKW task. When every pattern-1 hit is a graded deliverable (compared as
    a name suffix, because the check's filename regex truncates names carrying spaces or
    dashes) and patterns 3 and 5 are quiet, the verdict becomes pass with the reason recorded
    and `reconciled: true` on the cell. Anything else keeps the check's own verdict."""
    if r.get("status") != "fail":
        return None, ""
    missing = [
        m.get("filename", "") for m in ((r.get("pattern1") or {}).get("missing") or [])
    ]
    p3 = (r.get("pattern3") or {}).get("hits") or []
    p5 = (r.get("pattern5") or {}).get("fired")
    if not missing or p3 or p5:
        return None, ""
    gl = [g.casefold() for g in graded]
    if all(any(g.endswith(m.casefold()) for g in gl) for m in missing):
        return "pass", (
            f"pattern-1 hits are all graded deliverables ({', '.join(missing)}); "
            "EKW prompts name outputs, not inputs"
        )
    return None, ""


def _reconcile_answer_key_leakage(r: dict) -> tuple[str | None, str]:
    """answer_key_leakage_check.py's `_REFERENCE` tell was calibrated on SVC-PC, where a file
    named *_REFERENCE* that the solver is told to PRODUCE was a golden reference answer. EKW
    ships reference material as INPUTS (`pdpm_classification_reference_card.pdf`,
    `03_Trading_Options_Reference.pdf`): seven tasks in the 274 drop, every one a file that
    exists under environment/ or is named in the prompt as something to read. When the only
    tells are `_REFERENCE` and there is no bracketed pipeline text, the verdict becomes warn
    with the reason recorded and `reconciled: true`; a GOLDEN/SOLUTION/ANSWER/KEY tell, or any
    bracket leak, keeps the fail."""
    if r.get("status") != "fail":
        return None, ""
    if r.get("bracket_leaks"):
        return None, ""
    leaks = list(r.get("instruction_filename_leaks") or []) + list(
        r.get("environment_filename_leaks") or []
    )
    if not leaks:
        return None, ""
    tells = {t for x in leaks for t in (x.get("tells") or [])}
    if tells and tells <= {"_REFERENCE"}:
        names = [
            x.get("filename") or os.path.basename(x.get("path", "")) for x in leaks
        ]
        return (
            "warn",
            f"only the _REFERENCE tell fired, on reference-material file(s) {', '.join(names)}; on EKW these are inputs, not goldens",
        )
    return None, ""


def merge(
    task_ids: list[str],
    per_check: dict[str, dict[str, dict]],
    ran: set[str],
    genres: dict[str, str],
    missing_by_check: dict[str, set[str]] | None = None,
) -> list[dict]:
    missing_by_check = missing_by_check or {}
    rows = []
    for tid in task_ids:
        row = {"task_id": tid, "genre": genres.get(tid), "checks": {}}
        by_letter: dict[str, list[str]] = {L: [] for L in LETTERS}
        graded = (per_check.get("check_b", {}).get(tid) or {}).get("graded_files") or []
        for name, spec in CHECKS.items():
            if name not in ran:
                continue
            r = per_check.get(name, {}).get(tid)
            if r is None:
                if tid in missing_by_check.get(name, ()):
                    # A real gap, but a run-infrastructure one, not a per-task failure - the
                    # check's own shard for this task died (crash/timeout/OOM) while the rest
                    # of the run succeeded. "warn," not "error": this task's own content was
                    # never actually evaluated by this check, distinct from the check running
                    # and finding nothing wrong.
                    cell = {
                        "verdict": "warn",
                        "native": None,
                        "n_findings": 0,
                        "first": (
                            f"OPEN ITEM: {name}'s shard covering this task did not complete "
                            "(crash/timeout/OOM) - this task was never evaluated by this check "
                            "this run, rerun it specifically to get a real verdict"
                        ),
                    }
                else:
                    cell = {
                        "verdict": "error",
                        "native": None,
                        "n_findings": 0,
                        "first": "no result for this task (check crashed or skipped it)",
                    }
            else:
                try:
                    verdict = spec["verdict"](r)
                except Exception as e:  # a check's JSON shape moved under us
                    verdict = "error"
                    r = {"_merge_error": f"{type(e).__name__}: {e}"}
                try:
                    finds = spec["findings"](r) if verdict != "error" else []
                except Exception:
                    finds = []
                native = (
                    r.get("combined_status")
                    if name == "deliverable_filename"
                    else (r.get("ok") if name == "rubric_schema" else r.get("status"))
                )
                cell = {
                    "verdict": verdict,
                    "native": native,
                    "n_findings": len(finds),
                    "first": _first_text(finds),
                }
                if name == "answer_key_leakage":
                    new_verdict, why = _reconcile_answer_key_leakage(r)
                    if new_verdict:
                        cell.update(
                            {"verdict": new_verdict, "first": why, "reconciled": True}
                        )
                if name == "environment_input" and graded:
                    new_verdict, why = _reconcile_environment_input(r, graded)
                    if new_verdict:
                        cell.update(
                            {"verdict": new_verdict, "first": why, "reconciled": True}
                        )
            row["checks"][name] = cell
            by_letter[spec["letter"]].append(cell["verdict"])
        for L in LETTERS:
            row[L] = rollup(by_letter[L]) if by_letter[L] else "skip"
        for i, nm in enumerate(SIXQ, 1):
            row[f"F{i}"] = (row["checks"].get(nm) or {}).get("verdict", "skip")
        rows.append(row)
    return rows


def write_csv(rows: list[dict], ran: list[str], path: Path) -> None:
    cols = ["task_id", "genre", *LETTERS, *[f"F{i}" for i in range(1, 7)]]
    for name in ran:
        cols += [name, f"{name}_n", f"{name}_first"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            flat = {
                "task_id": r["task_id"],
                "genre": r["genre"],
                **{L: r[L] for L in LETTERS},
                **{f"F{i}": r.get(f"F{i}", "skip") for i in range(1, 7)},
            }
            for name in ran:
                c = r["checks"].get(name) or {}
                flat[name] = c.get("verdict", "")
                flat[f"{name}_n"] = c.get("n_findings", "")
                flat[f"{name}_first"] = c.get("first", "")
            w.writerow(flat)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("task_ids", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument(
        "--root", required=True, help="EKW harbor tree, one task directory per task"
    )
    ap.add_argument(
        "--stage", help="BUILD-CONTRACT-shaped staging tree (required unless --native)"
    )
    ap.add_argument("--out-dir", required=True)
    ap.add_argument(
        "--merge-only",
        action="store_true",
        help="run nothing; re-merge the per-check JSON already in --out-dir",
    )
    ap.add_argument("--id-prefix", default="")
    ap.add_argument("--checks", help="comma-separated subset of: " + ",".join(CHECKS))
    ap.add_argument(
        "--skip-stage",
        action="store_true",
        help="do not re-stage; run the shared checks on the existing --stage tree",
    )
    ap.add_argument(
        "--native",
        action="store_true",
        help="run the shared checks on --root directly (only once they read verifier.json natively)",
    )
    ap.add_argument(
        "--rewardkit-out",
        help="also run the real rewardkit converter per task (Check B build proof)",
    )
    ap.add_argument(
        "--jobs",
        type=int,
        default=os.cpu_count() or 4,
        help="concurrent processes for the shared checks and threads for Check B (default: one per CPU)",
    )
    ap.add_argument(
        "--shards",
        type=int,
        default=os.cpu_count() or 4,
        help="split each shared check's task list into this many processes (default: one per CPU)",
    )
    ap.add_argument(
        "--timeout", type=int, default=7200, help="seconds per shared-check shard"
    )
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2
    if not args.all and not args.task_ids:
        sys.stderr.write("give task ids or --all\n")
        return 2
    if not args.native and not args.stage:
        sys.stderr.write("--stage is required unless --native\n")
        return 2
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    selected = (
        [c.strip() for c in args.checks.split(",")] if args.checks else list(CHECKS)
    )
    bad = [c for c in selected if c not in CHECKS]
    if bad:
        sys.stderr.write(f"unknown checks: {bad}\n")
        return 2
    task_ids = args.task_ids or None
    stage = Path(args.stage) if args.stage else None
    target = root if args.native else stage

    t_all = time.time()
    per_check: dict[str, dict[str, dict]] = {}
    genres: dict[str, str] = {}
    runs = []
    ordered_ids: list[str] = []

    if args.merge_only:
        for name in selected:
            per_check[name] = load_results(name, CHECKS[name], out_dir / f"{name}.json")
        if "check_b" in per_check and per_check["check_b"]:
            ordered_ids = list(per_check["check_b"])
            genres = {tid: r.get("genre") for tid, r in per_check["check_b"].items()}
        else:
            ordered_ids = sorted({tid for res in per_check.values() for tid in res})
        # Keep every selected check, present or not: a check whose JSON is missing must show
        # `error` in its column, not vanish from the table (a re-merge after a partial rerun
        # or a disk cleanup would otherwise erase a real fail; found by the merge verifier).
        missing = [c for c in selected if not per_check.get(c)]
        if missing:
            print(
                f"no JSON for: {missing} (their columns will read error)",
                file=sys.stderr,
            )
        rows = merge(ordered_ids, per_check, set(selected), genres)
        (out_dir / "summary.json").write_text(
            json.dumps(
                {
                    "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "merge_only": True,
                    "checks_run": selected,
                    "n_tasks": len(rows),
                    "results": rows,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        write_csv(rows, selected, out_dir / "summary.csv")
        print(f"re-merged {len(rows)} tasks from {out_dir}", file=sys.stderr)
        return 0

    # 1. Check B (in-process), staging unless told not to
    if "check_b" in selected:
        print("check_b ...", file=sys.stderr)
        t0 = time.time()
        report = ekw_check_b.run(
            root,
            task_ids,
            args.id_prefix,
            None if args.skip_stage else stage,
            Path(args.rewardkit_out) if args.rewardkit_out else None,
            quiet=True,
            jobs=args.jobs,
        )
        (out_dir / "check_b.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        per_check["check_b"] = {r["task_id"]: r for r in report["results"]}
        genres = {r["task_id"]: r.get("genre") for r in report["results"]}
        ordered_ids = [r["task_id"] for r in report["results"]]
        runs.append(
            {
                "check": "check_b",
                "seconds": round(time.time() - t0, 1),
                "ok": True,
                "n_pass": report["n_pass"],
                "n_fail": report["n_fail"],
            }
        )
        print(
            f"  check_b: {report['n_pass']}/{report['n_tasks']} pass, {report['n_fail']} fail, genres {report['genre_counts']}",
            file=sys.stderr,
        )
    if not ordered_ids:
        ordered_ids = [
            p.name for p in ekw_check_b.find_task_dirs(root, task_ids, args.id_prefix)
        ]

    # 2. shared checks, concurrently
    shared = [c for c in selected if c != "check_b"]
    if shared and not target.is_dir():
        sys.stderr.write(f"shared-check target does not exist: {target}\n")
        return 2
    n_shards = max(1, min(args.shards, len(ordered_ids)))
    chunks = [ordered_ids[i::n_shards] for i in range(n_shards)]
    chunks = [c for c in chunks if c]
    # Heaviest checks first so the pool never ends on one long tail.
    heavy_first = sorted(
        shared, key=lambda n: HEAVY.index(n) if n in HEAVY else len(HEAVY)
    )
    print(
        f"shared checks ({len(shared)}) on {target}: {len(chunks)} shards each, {args.jobs} concurrent processes ...",
        file=sys.stderr,
    )
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        futs = [
            (
                name,
                ex.submit(
                    run_shared_check,
                    name,
                    CHECKS[name],
                    target,
                    out_dir,
                    chunk,
                    si,
                    args.timeout,
                ),
            )
            for name in heavy_first
            for si, chunk in enumerate(chunks)
        ]
        shard_recs: dict[str, list[dict]] = {}
        for name, fut in futs:
            shard_recs.setdefault(name, []).append(fut.result())
    missing_by_check: dict[str, set[str]] = {}
    for name in shared:
        rec = merge_shards(name, CHECKS[name], out_dir, shard_recs.get(name, []))
        runs.append(rec)
        # Load whatever shards actually succeeded - a check with 7/8 shards ok still has real
        # results for those tasks, and discarding them wholesale over 1 dead shard was masking
        # a partial run as every task "error"ing (found 2026-09-15, real data loss, not a
        # display bug). missing_by_check carries the gap forward so merge() can report it
        # honestly instead of the misleading "check crashed or skipped it" on tasks the check
        # never even attempted this pass.
        per_check[name] = (
            load_results(name, CHECKS[name], Path(rec["json"]))
            if rec["partial_ok"]
            else {}
        )
        if rec["missing_task_ids"]:
            missing_by_check[name] = set(rec["missing_task_ids"])

    # 3. merge
    ran = [c for c in selected]
    rows = merge(ordered_ids, per_check, set(ran), genres, missing_by_check)
    summary = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "root": str(root),
        "stage": str(stage) if stage else None,
        "target": str(target),
        "native": args.native,
        "checks_run": ran,
        "n_tasks": len(rows),
        "letter_counts": {
            L: {v: sum(r[L] == v for r in rows) for v in VERDICTS} for L in LETTERS
        },
        "check_counts": {
            name: {
                v: sum((r["checks"].get(name) or {}).get("verdict") == v for r in rows)
                for v in VERDICTS
            }
            for name in ran
        },
        "seconds": round(time.time() - t_all, 1),
        "results": rows,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "runs.json").write_text(
        json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_csv(rows, ran, out_dir / "summary.csv")

    print(
        f"\n{len(rows)} tasks in {summary['seconds']}s -> {out_dir / 'summary.csv'}",
        file=sys.stderr,
    )
    for L in LETTERS:
        c = summary["letter_counts"][L]
        print(f"  {L}: " + "  ".join(f"{v}={c[v]}" for v in VERDICTS), file=sys.stderr)
    for name in ran:
        c = summary["check_counts"][name]
        print(
            f"    {name:<32} " + "  ".join(f"{v}={c[v]}" for v in VERDICTS if c[v]),
            file=sys.stderr,
        )
    blocked = sum(any(r[L] in ("fail", "error") for L in LETTERS) for r in rows)
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
