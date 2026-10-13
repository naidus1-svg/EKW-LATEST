#!/usr/bin/env python3
"""SVC-PC QC runner: every shared deterministic check, one command, one table.

Built 2026-09-14 during the SVC-PC QC crisis: manual QC found real defects in nearly every
SVC-PC task despite them passing every existing check, and the root cause was that SVC-PC's
own checks (`compound_criterion_check.py`, `undisclosed_terminology_check.py`, etc.) had never
been run as a single batch over the corpus -- only one at a time, by hand. `ekw/ekw_run_checks.py`
already solved this for EKW; this is the SVC-PC-native equivalent.

What it does
------------
Runs each shared check in this directory (`deterministic-checks/`) as a subprocess directly
against `--root`, writing each check's own JSON to `--out-dir/<check>.json` untouched, then
merges everything into `--out-dir/summary.json` and `--out-dir/summary.csv`: one row per task,
one column per check with a normalised verdict (pass / warn / fail / skip / error), plus C/D/E
roll-ups in the letters `ekw_run_checks.py` also uses.

Unlike `ekw_run_checks.py`, there is **no staging/translation layer and no Check B here**.
SVC-PC is the benchmark these checks were originally built and calibrated against
(`BUILD-CONTRACT.md`'s package shape -- `instruction.md` + `environment/initial_workspace/` +
`solution/` + `tests/deliverables_NN/judge.toml` -- IS SVC-PC's own on-disk shape at
`03_dataos_ready/<task-id>/`), so every shared check reads `--root` natively. There is
consequently no letter "B" here: SVC-PC's own build pipeline already produced the package tree
this runner points at, and verifying that build is that pipeline's job, not this runner's (same
reasoning `BUILD-CONTRACT.md` gives for why a shared check here never owns benchmark-specific
build verification).

Only four of the twenty-seven registered checks return a non-zero exit code on findings; the
other twenty-three always exit 0. The runner therefore never trusts an exit code: every verdict comes from
the check's own JSON. A check that crashed, timed out, or wrote no JSON shows `error` for every
task, with the stderr tail in `runs.json`, rather than a silent column of blanks.

Letters
  C  structural: deliverable_count, environment_input, answer_key_leakage,
     answer_key_content_leak, environment_size_budget, answer_key_rubric_leak,
     metadata_leak (2026-09-16: reads xlsx/docx/pptx file METADATA -- cell comments, defined
     names, sheet titles, docx comments/tracked-changes/headers-footers, pptx speaker notes --
     none of the other answer_key_* checks above ever open; see its own module docstring),
     structural_audit (2026-09-17: LLM-judge six-pattern structural audit, rows 28-29)
  D  mechanical/rubric: deliverable_filename, rubric_schema, rubric_text_lint,
     judge_criterion_name_duplicate, tab_naming, deliverable_integrity,
     judge_determinism_config_lint, harness_fragility, compound_criterion,
     undisclosed_terminology, extraction_groundedness, judge_file_scope_breadth,
     test_coverage_absence, instruction_requirement_coverage,
     criterion_groundedness, pinned_value_prescreen, spelling_grammar,
     unrequested_deliverable_source, dependency_pin, weight_application,
     duplicate_criterion_content, task_metadata_completeness,
     source_citation_existence, rubric_overspecification,
     same_file_requirement_duplicate, cell_address_pinned,
     judge_file_size_cliff, judge_scope_over_inclusion,
     judge_scope_under_inclusion (this line synced 2026-09-17; the previous
     version was missing these checks that earlier 2026-09-17 rounds added,
     disclosed here rather than silently left stale further)
  E  formula_health, formula_health_extraction_loss, verifier_executability,
     source_truncation, golden_arithmetic

Roll-up rule per letter: any fail -> fail; else any error -> error; else any warn -> warn;
else any pass -> pass; else skip. `warn` is a disclosure the checks themselves do not treat
as a defect; it never blocks on its own.

Forty-one checks registered as of this edit (confirmed by importing THIS file's own CHECKS dict
and counting it directly, `len(m.CHECKS) == 41`, rather than hand-incrementing a prior count
-- the count changed mid-edit, from 29 to 31, because environment_size_budget_check.py landed in
this same file from a separate, concurrent contribution while this edit was in progress; every
prior count in this paragraph's history was stale the same way for the same reason. The count
rose further to 41 as later rounds ported golden_groundedness, golden_arithmetic,
rubric_overspecification, same_file_requirement_duplicate, task_metadata_completeness,
source_citation_existence, duplicate_criterion_content, and judge_scope_under_inclusion (row
32). Read this count as a snapshot that decays, not a durable fact -- re-derive it from the dict
rather than trusting this sentence). Original twenty-three pre-existing, plus verifier_executability,
source_truncation, unrequested_deliverable_source, formula_health_extraction_loss (ported from
ekw_run_checks.py's own registration, commits 80a7698/027957a, so both orchestrators cover the
same checks), plus dependency_pin and weight_application (GLM round 27/28 coverage synthesis
classes 3 and 5), plus environment_size_budget (Class 6) and golden_arithmetic (Class 2).
Four things this session confirmed exist but did NOT register here,
each for a stated reason rather than a silent drop (see `docs/EVAL_RUNBOOK.md` / this repo's
own hard rule against softening a negative finding):

  - `content-audit/SKILL.md` -- NOT a script. It is an LLM/human-read recipe (six text-consistency
    patterns over prompt/golden/rubric), explicitly "0% script, 100% judgment" per this folder's
    own `OVERVIEW.md`. There is no CLI to invoke; running it means a Claude session or a person
    reading three texts per task and applying the six-pattern methodology by hand. Cannot be
    wired into this subprocess harness tonight or ever, on its current design.
  - `duplicate_criterion_check.py` -- targets the pre-conversion SOURCE rubric .xlsx (ID-collision
    detection before it becomes `judge.toml`), not the built task package this runner points at.
    Confirmed by direct inspection: zero rubric-shaped .xlsx files exist anywhere under
    `03_dataos_ready/<task>/` (checked SVC-PC-1-0-0, 10-0-0, 88-0-0, 92-0-0, 93-0-0 directly --
    only environment corpus files and golden deliverables, `tests/` holds only `judge.toml`).
    Pointing `--root` at the built package gives it nothing to find. `ekw_run_checks.py` excludes
    it from its own CHECKS registry for the same reason on the EKW side. Needs someone to name
    where SVC-PC's pre-conversion rubric spreadsheets actually live before it can be wired in.
  - `certification_gate_check.py` -- operates post-hoc against a COMPLETED judge run
    (`<task>/verifier/reward-details.json`) plus DataOS gate-adjudication records, answering "did
    the must-pass criteria actually gate the shipped score" -- a release-time question, not a
    pre-grading package question. `ekw_run_checks.py` also excludes it from its own registry for
    the same reason. No `--run` paths to real grading output were supplied or located as part of
    this build; wiring it in needs those paths, which is a different input shape than everything
    else this runner checks.
  - `formula_cache_autofix.py` -- a MUTATOR (writes patched cell values), not a check. Excluded on
    purpose, same as `ekw_run_checks.py`.
  - `v0-checks/*.py` -- explicitly unvalidated per this folder's own README ("do not trust output
    as a verdict yet"). Excluded, same as `ekw_run_checks.py`.

Usage
-----
    python svc_run_checks.py --all --root C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready --out-dir C:\\ekwqc\\_svc_qc
    python svc_run_checks.py SVC-PC-1-0-0 SVC-PC-88-0-0 --root ... --out-dir ...
    python svc_run_checks.py --all --root ... --out-dir ... --checks compound_criterion,undisclosed_terminology,formula_health
    python svc_run_checks.py --all --root ... --out-dir ... --merge-only   # re-merge existing per-check JSON

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
CHECKS_DIR = HERE  # the shared check scripts are direct siblings of this file

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
# Same 15 shared checks and the same verdict/findings mapping ekw_run_checks.py uses -- these
# describe the checks' OWN native output shape, calibrated originally against SVC-PC (the source
# benchmark), not anything EKW-specific. No `check_b` entry: SVC-PC has no staging step.
CHECKS: dict[str, dict] = {
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
    # package-size budget". Letter C (structural), same letter as environment_input above --
    # this is also purely about what shipped under environment/, no rubric/judge text involved.
    # Two independent findings, calibrated against the real 600-task corpus rather than the
    # brief's own guidance figures (see the check's own module docstring "Calibration" and
    # "Duplicate-file severity"): oversized_environment (total workspace size over a
    # data-derived 35MB threshold -- the brief's cited 10MB would have flagged 62% of the
    # corpus) and duplicate_environment_file (two-plus files sharing MD5 content under
    # different names -- reported at severity=warn by default, not the brief's originally-
    # pitched unconditional fail, because a full-corpus run found 65% of tasks carry one, almost
    # entirely two shared-source files inherited by many tasks rather than N per-task mistakes).
    # "fail" is only reachable via that script's own --fail-on-duplicate flag, never passed by
    # this runner, so this verdict mapping is effectively pass/warn/skip/error on the real
    # corpus today; the explicit "fail" entry is kept so nothing changes here if that flag is
    # ever wired through later. Full 600-task corpus: 37 over budget, 392 with a duplicate.
    # Updated 2026-09-16: OS/tooling metadata files (.DS_Store, Thumbs.db, desktop.ini,
    # .localized, __MACOSX/) are now excluded from duplicate grouping (name-based, not size- or
    # content-based). A GLM mirror check claimed these could false-FAIL via a same-SIZE proxy in
    # its own text-only reconstructed corpus (no real bytes); checked directly against this
    # runner's real 600-task corpus before trusting that: 37 tasks / 629 real .DS_Store files,
    # zero of which actually collide by MD5 today, so the claimed failure mode does not
    # reproduce here. Exclusion added anyway as a safe hardening (name-based, can only remove
    # already-inert files); re-ran the full corpus both with and without --fail-on-duplicate
    # after adding it -- identical status counts and an identical fail-set (392 tasks) either
    # way, zero verdict changes on any real task.
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
                # temperature to zero (greedy/deterministic decoding). This IS a pass -
                # the config confirms determinism. Added 2026-09-15 round 17 alongside
                # the judge_determinism_config_lint.py rollup fix that split this out of
                # not_exposed (previously both were conflated under not_exposed->warn).
                "deterministic_confirmed": "pass",
                # not_exposed is explicitly "NOT A PASS" per this check's own docstring (see
                # judge_determinism_config_lint.py's how_to_read_this_report): the config format
                # exposes no determinism-control field at all, which is a disclosed blind spot,
                # not a confirmed-safe result. Mapping it to "pass" here silently discarded that
                # distinction in the orchestrator's own rollup. Found by the GLM worker's round-3
                # real execution pass 2026-09-15, independently confirmed against both the
                # mapping (this file) and the docstring (judge_determinism_config_lint.py) before
                # this fix landed.
                "not_exposed": "warn",
                # parse_error / no_config_found were "fail" here, contradicting this check's own
                # docstring (Exit code section): "'not_exposed', 'mitigated', 'no_config_found'
                # and 'parse_error' never fail the run by themselves - they are disclosed states,
                # not verdicts." Same bug class as the not_exposed fix above, found 2026-09-15
                # (tracker backlog item 25). Confirmed zero real-world impact before landing: ran
                # directly against the full 600-task SVC-PC and 274-task EKW corpora, both 100%
                # not_exposed, zero tasks hit either status either way. no_tests_dir stays "fail"
                # deliberately: the docstring's own "never fail" list names only these two plus
                # not_exposed/mitigated, not no_tests_dir - a task missing tests/ entirely is a
                # real packaging defect, not a scanning-limitation disclosure like the other two.
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
    # judge_determinism_config_lint.py (positional task_ids + --root + --out). All
    # findings are warn-level (platform-level properties, not per-task defects),
    # exit code is always 0, never gates on its own. Verified against the real
    # 27-task SVC-PC sample (3 findings/task: all three fire) and 14-task EKW
    # sample (2 findings/task: preflight does NOT fire, EKW test.sh has it) before
    # registering.
    "harness_fragility": dict(
        script="harness_fragility_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status({"warn": "warn", "pass": "pass", "skip": "skip"}),
        findings=_findings_from("findings"),
    ),
    # dependency_pin_check.py: GLM round 27/28 coverage synthesis Class 3
    # (unpinned pip installs in test.sh, e.g. harbor-rewardkit[all] with no
    # version pin despite a documented tested version). Same "std" CLI/output
    # shape as harness_fragility_check.py. Universal warn-tier finding on the
    # real corpus (202/202 SVC-PC tasks share the same test.sh template).
    "dependency_pin": dict(
        script="dependency_pin_check.py",
        letter="D",
        style="std",
        task_key="task_id",
        verdict=_std_status({"warn": "warn", "pass": "pass", "skip": "skip"}),
        findings=_findings_from("findings"),
    ),
    # weight_application_check.py: GLM round 27/28 coverage synthesis Class 5 (declared rubric
    # weights not applied at runtime / inert must-pass semantics) -- narrowed after this session
    # found both halves of the original framing already covered, more strongly, by two checks
    # this runner deliberately does NOT register (weight_aggregation_check.py, confirmed against
    # real completed runs; certification_gate_check.py's must-pass replay, same reason). This
    # script is the static, package-only precondition those two can't check pre-run: does
    # reward.toml even carry a weights table that could apply each judge.toml's declared
    # [judge].weight, and does any group with must-pass language use a gating aggregation. Same
    # CLI/output shape as criterion_groundedness (style="rubric_schema"). Real 202-task SVC-PC
    # corpus: 18 pass / 184 fail / 0 warn / 0 error (see the script's own module docstring and
    # this feature's commit message for the full validation, including the SVC-PC-29-2-0
    # calibration case and clean single-group controls).
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
    # compound_criterion / undisclosed_terminology share rubric_schema_check.py's exact CLI and
    # output shape (`<root> [--task ID ...] [--json out.json]`, a bare JSON list keyed by "task"),
    # so they reuse style="rubric_schema" rather than "std".
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
    # extraction_groundedness_check.py's CLI/output matches the "std" checks exactly, but its
    # per-task record has no "status" field -- only "summary.by_kind" and "errors" -- so it gets
    # a custom verdict: only "_confirmed" is a fail, "_not_flagged" (audit visibility) is not, a
    # missing-config/parse problem is "error" rather than silently "pass".
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
    # judge_file_scope_breadth_check.py's CLI is <root> [--task ID] [--json OUT], the same shape
    # compound_criterion/undisclosed_terminology use, so it needs style="rubric_schema" too --
    # NOT "std" (positional task_ids + --root + --out), a real mismatch caught by an actual
    # smoke-test run before committing, not assumed from the docstring alone. Output has no
    # "status" field -- only "findings" and "parse_errors" -- and two of its three finding kinds
    # hard-gate while the third ("possible_judge_scope_excludes_named_sources") never does, per
    # its own docstring.
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
    # Round 55 draft (row 33), independently validated at round 60 against the full 202-task
    # subset (67/202 fail, matches the tracker's original ad-hoc count exactly) and re-derived a
    # third time this session (independent reconstruction, same 67-task list, zero disagreement).
    # Same CLI shape as judge_file_scope_breadth above: <root> [--task ID] [--json OUT],
    # style="rubric_schema". Single finding kind ("judge_scope_over_inclusion") always sets
    # ok=False, so the checker's own ok field is authoritative -- no separate warn tier exists
    # in its current design. Caveat: validated against the in-repo text/solution mirror
    # (reconstructed nested tree), not yet re-run against the live C:\ekwqc\repo corpus, which
    # this session found has drifted from the mirror on other tasks -- treat 67/202 as
    # as-of-mirror-snapshot until a live re-run confirms it.
    "judge_scope_over_inclusion": dict(
        script="judge_scope_over_inclusion_check.py",
        letter="D",
        style="rubric_schema",
        task_key="task",
        verdict=lambda r: "fail" if not r.get("ok") else "pass",
        findings=_findings_from("findings"),
    ),
    # judge_scope_under_inclusion_check.py: the LLM-judge check for tracker row 32 (files=
    # too NARROW -- the OPPOSITE end of the axis judge_scope_over_inclusion above closes).
    # That sibling (row 33) is DETERMINISTIC and flags the WIDE shape (deliverable + sources
    # undifferentiated); this one is LLM-based and flags the NARROW shape: a criterion whose
    # Expected text references a specific fact/document/comparison that none of the listed
    # files= could verify, so the judge grades a self-declared claim (e.g. "Expected: 80 vs
    # 25 unresolved" implying Q2/Q3 product catalogs the judge was never given). judge_file_
    # scope_breadth_check.py catches the NAMED-FILENAME-LITERAL slice of this (a criterion
    # that literally names a file absent from scope); this check catches the SEMANTIC slice a
    # regex cannot, which is why it was deliberately scoped out of the mechanical row-33
    # checker at round 55 and built as an LLM check wired here as an automated check (called
    # on every run), not a manual pass.
    #
    # Letter D, same family as judge_scope_over_inclusion / judge_file_scope_breadth, NOT
    # letter A: LETTERS on this runner is ("C","D","E") and content-audit/SKILL.md (the only
    # "Check A" this pipeline names) has no CLI and no CHECKS entry -- registering "A" would
    # KeyError in merge()'s `by_letter = {L: [] for L in LETTERS}`, confirmed by reading
    # merge() directly. This is LLM-judgment territory like content-audit and the two other
    # LLM checks already registered here (rubric_overspecification letter D,
    # golden_groundedness letter E), so it follows the same "candidate, not verdict" posture:
    # warn, never fail.
    #
    # style="std" (task_ids + --root + --out), task_key="task_id", matching
    # rubric_overspecification / golden_groundedness -- the LLM checks' own run()/audit_task
    # programmatic shape, NOT the rubric_schema CLI shape the deterministic judge-scope
    # siblings use. UNLIKE every deterministic entry, one run makes one real LLM call PER
    # TASK (50-100s, not milliseconds); scope with --checks to exclude it from a fast sweep,
    # same caution rubric_overspecification / golden_groundedness already carry.
    #
    # Verified for real against the four named defect tasks (2026-09-17, real LLM calls
    # against the configured glm-5.2 HTTP backend, NOT dry-run): SVC-PC-82-2-0 flagged
    # l2-02-r08 (Q2/Q3 count conflict 80 vs 25 -> product_catalog_q2/q3 withheld),
    # SVC-PC-82-3-0 flagged l2-03-r09 (same 80 vs 25 -> product catalogs withheld),
    # SVC-PC-52-3-0 flagged a4 (December balance "agrees with the package cash figure"
    # 2,186,512 -> tax_prep_package.xlsx withheld), SVC-PC-46-3-0 flagged 6 criteria
    # (r01/r03/r04/r05/r06/r07 reference specific sprint backlog + incident log evidence
    # withheld from files=). All four acceptance tasks correctly flagged. A 28-task broader
    # real sample is recorded in ROUND62-ROW32-REPORT.md with the real false-positive
    # spot-check this project's hard rule against softening a negative finding requires.
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
    # Round 55 draft (row 34), had a real dependency-drift bug at construction time
    # (_build_visible_text unpacked a 4-tuple from environment_signals(), which now returns a
    # 3-tuple) -- fixed in this same commit (dropped the unused _instr 4th value; it was dead
    # code even before the drift, _build_visible_text calls its own _load_instruction()
    # separately). Validated post-fix, independently, twice: 30/202 tasks carry >=1 word-ban
    # criterion, 1 hard FAIL (SVC-PC-66-2-0 e4), matching both runs exactly. The "possible"
    # (non-blocking) count disagreed between the two validation passes -- 3 named in the first,
    # 15 confirmed by re-deriving from the checker's own possible_findings array in the second --
    # use the checker's own live output as authoritative going forward, not either prior count.
    # Known, disclosed detection-method gap: this is a static environment/instruction scan, so it
    # does NOT reproduce the two real judge-run-observed false triggers (SVC-PC-52-3-0,
    # SVC-PC-52-5-0) that motivated building this checker in the first place -- both carry a
    # WORD_BAN_DETECTED criterion but the finance-context source text (e.g. "benchmark") lives
    # only in real environment files not staged in the validation mirror. Same live-corpus
    # caveat as judge_scope_over_inclusion above.
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
    # Same CLI-shape correction as judge_file_scope_breadth above: <root> [--task ID] [--json
    # OUT], style="rubric_schema" not "std". test_coverage_absence_check.py ships explicitly as
    # a low-confidence candidate-for-review tool, not a gate (see its own docstring) -- every
    # untested_section finding is "warn", never "fail", the same convention
    # answer_key_content_leak_check.py uses for its own "candidate" tier.
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
    # instruction_requirement_coverage_check.py is a NON-BLOCKING warn-tier candidate
    # tool for Andrew Ma's pattern 5 (explicit requirements go ungraded). It flags
    # imperative requirements in instruction.md whose object nouns no criterion
    # mentions. It is deliberately warn-tier, never fail: a deterministic noun-overlap
    # heuristic cannot distinguish "genuinely ungraded" from "covered by consequence
    # with different nouns", and on the 27-task calibration sample it false-flags 7
    # of 22 well-covered tasks (see the script's own docstring for the measured
    # false-positive rate and the LLM-judgment alternative). Registered so the
    # candidate set is surfaced for human/LLM review, the same discipline every other
    # warn-tier check in this folder (test_coverage_absence, answer_key_content_leak's
    # candidate tier) already follows. CLI is "std" (task_ids + --root + --out),
    # matching deliverable_filename / formula_health.
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
    # weight_aggregation_check.py is deliberately NOT registered here, same reason as
    # certification_gate_check.py above: it requires --run pointing at completed judge-run
    # output (reward-details.json), not just a task package -- a post-hoc release-time replay,
    # not a per-package deterministic check this runner's sweep model can drive.
    #
    # criterion_groundedness_check.py: a real gap, not a disclosed exclusion -- confirmed by
    # direct search that this check was never wired into either orchestrator despite carrying
    # most of tonight's fix work (2026-09-15), found only when asked "will every check we
    # built actually fire." Same CLI shape as compound_criterion/undisclosed_terminology
    # (style="rubric_schema"). unreachable_criterion hard-gates (fail); possible_unreachable
    # is non-blocking by the check's own design (warn); parse_errors means the task couldn't
    # be evaluated at all (error), per its own docstring's Known limits section.
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
    # Two more real gaps found the same way (2026-09-15): GLM round 8 built both of these and
    # ran them for real against 56 tasks, but they only ever existed in the mirror repo --
    # never ported to this canonical repo, so never registered anywhere. Both are deliberately
    # warn-only here, matching their own documented maturity: pinned_value_prescreen_check.py's
    # own round-8 report measured a 47-73% false-positive rate and states it "cannot itself
    # decide true/false, needs LLM judgment downstream" -- a triage tool, not a gate.
    # spelling_grammar_check.py found exactly 1 real defect corpus-wide with heavy exclusion-
    # list tuning to get there (338 FPs -> 1) -- real signal, not yet validated enough to
    # hard-fail a task over. Also fixed spelling_grammar_check.py's own `--task` flag during
    # wiring: it only accepted ONE value (`--task X`), but this orchestrator always invokes it
    # with one repeated `--task` per task in a shard -- a real bug that would have silently
    # processed only the last task in every multi-task shard, found by actually running it
    # with 2 tasks before trusting the wiring, not assumed from the CLI's own --help text.
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
    # under a real (non-Cygwin) bash, and (SVC-PC branch) does rewardkit.discover() succeed plus
    # every judge.toml-referenced file exist under solution/files/ OR environment/
    # initial_workspace/ -- the SVC-PC analog of EKW's schema-crash S-1, config-validity only,
    # not a full reward==1.0 replay (see the script's own module docstring for why). Ported from
    # ekw_run_checks.py's identical registration (commit 80a7698) so both orchestrators cover the
    # same checks -- an orchestrator silently missing a real check is the exact failure class
    # this whole effort exists to close.
    #
    # Real corpus numbers have TWO dates because the corpus itself changed in between, not
    # because the check did: b4431ad (2026-09-15 14:34) measured 598 pass / 2 fail on the full
    # 600-task corpus at build time. Step 2's full A:E run (2026-09-16 06:28, ~16h later, this
    # corpus under active rebuild/re-upload the whole time between) measured 71/202 (35%) fail
    # on the SAME unchanged check logic against the SAME 202-task subset -- a real, confirmed
    # regression, not noise: every one of the 71 tasks' combined 908 "missing" file references
    # was independently verified (2026-09-16) to actually exist under
    # environment/initial_workspace/, just not solution/files/, which is the only directory the
    # check looked in. BUILD-CONTRACT.md's own contract ("environment/initial_workspace/ -- every
    # file the solver starts with, actually staged on disk") confirms /app/ was never populated
    # by solution/solve.sh's `cp -a /solution/files/. /app/` alone. Fixed 2026-09-16 by checking
    # both directories (see `_environment_basenames` in the script itself). Re-verified against
    # the current, live corpus, not the stale build-time number: 202/202 pass on the exact
    # original 202-task set, 598/600 pass at full scale with the SAME 2 genuine defects b4431ad
    # originally found (SVC-PC-10-0-0, SVC-PC-19-5-0 -- a real rewardkit judge.mode config error,
    # unrelated to this fix and still correctly caught).
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
    # gold-replay extracted text lands exactly at max_content_chars (90000) -- the tell for
    # SourceRegistry's silent, unmarked truncation. SVC-PC: not_applicable (rewardkit has a
    # disclosed 1MB hard-reject, not a silent truncation -- different defect shape, reported
    # separately as svc_pc_oversized_file_marked_skip). Every finding is a candidate for human
    # review, not a confirmed defect -- warn, never fail. Full 600-task SVC-PC corpus: 0 fail,
    # 1 task flagged (oversized file). Ported from ekw_run_checks.py (commit 027957a).
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
    # instruction.md -- solve.sh copies every golden file into the graded directory, so an
    # unrequested file can ride along as a real, gradable source. Candidate, not confirmed --
    # warn, not fail. Full 600-task SVC-PC corpus: 597 clean / 3 candidate. Ported from
    # ekw_run_checks.py (commit 027957a).
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
    # path (load_workbook(data_only=True)) see the same content a fresh recalculation would -- a
    # formula cell with no cached value arrives as "" to the real grader regardless of whether
    # recomputation would fix it. Own registry entry, not folded into "formula_health" above,
    # since --check-extraction-loss is a genuinely separate report shape. Full 600-task SVC-PC
    # corpus: 568 pass / 32 fail. Ported from ekw_run_checks.py (commit 027957a).
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
    # formula_health_check.py. Verified against the real corpus before registering: fires on
    # SVC-PC-37-3-0 (all 11 Jurisdiction Summary state rows plus the Orders and AOV Basis Trace
    # sheet's own C8 cell, all "fail" tier, each independently row-count-corroborated against the
    # same 12,177-row Sales_Orders.xlsx export), status counts and false-positive rate against a
    # 202-task sample recorded in this check's own commit message. severity "info" (a same-row
    # Status cell explicitly marking the cell a RAW fact, e.g. "Confirmed"/"Actual", with no
    # row-count corroboration) is intentionally excluded from "findings" -- see the script's own
    # docstring for why an uncorroborated miss against a disclosed raw fact is more likely this
    # check's own limitation than a real defect.
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
    # golden_groundedness_check.py: closes tracker row 13 (cross-document narrative-prose
    # arithmetic reconciliation) -- LLM-based (letter E, same as golden_arithmetic_check.py,
    # its structural sibling: that check recomputes in-TABLE aggregations from a column header;
    # this one checks a bare literal figure in golden PROSE against real source documents,
    # which needs semantic judgment a regex cannot do). Ported 2026-09-16 from GLM's mirror
    # (unported until now) with real, necessary adaptation, not a drop-in: the mirror's own
    # import of read_xlsx_all_text_with_values/read_xlsx_label_value_pairs/
    # find_derivation_statements from golden_arithmetic_check.py failed against THIS repo's
    # real golden_arithmetic_check.py, which was independently built with a structurally
    # different (table-cell, not prose-derivation) design -- confirmed by reading it, not
    # assumed. The two xlsx readers are now inlined; derivation-statement filtering is dropped
    # (nothing in the real repo to overlap with; see this check's own module docstring NOTE).
    #
    # Retrieval was also confirmed BROKEN before shipping, not trusted from GLM's synthetic-
    # fixture-only calibration (its own docstring admits neither real motivating task was
    # available when it was built): run directly against the real SVC-PC-5-3-0 task, the
    # original flat single-match proximity search returned an unrelated customer-list table
    # and a coincidental xlsx label match for the $4,390 claim, never either of the two real
    # source documents (Q1_Ops_Summary.docx, Q2_Ops_Summary.docx). Rebuilt as a per-file,
    # IDF-weighted, singular/plural-tolerant relevance search (see find_env_excerpts's own
    # docstring for the full real-example-driven design). Also applied the row-15 LLM_API_MAX_
    # TOKENS=32000 fix (commit f0d1105) -- this check calls the same token-starved backend and
    # was still at the library's broken 4096 default.
    #
    # Real verification, not synthetic: a real LLM call against SVC-PC-5-3-0 (the row-13
    # motivating task) correctly flagged the golden's $4,390 claim, citing both real source
    # figures by name ("Shipping_Rate_Card_2021.xlsx / Q2_Ops_Summary.docx = $2,390 (Q1) +
    # $2,200 (Q2) = $4,590 for H1 alone... already exceeds the golden's claimed full-year
    # figure") -- exactly the reconciliation row 13 asked for, plus two bonus real catches
    # (a Stripe transaction-ID fragment "72490" misread as a dollar figure, found twice).
    # SVC-PC-37-3-0 (GLM's OTHER named case) came back clean -- expected, not a miss: that
    # task's own known defect is an in-table aggregation already owned by
    # golden_arithmetic_check.py (tracker row 2, confirmed fail=1 true positive there), outside
    # this check's bare-literal-claim scope by design.
    #
    # Warn-only, like every LLM-based check in this project ("candidate, not verdict").
    # EXPENSIVE: one real LLM call per TASK (up to MAX_CLAIMS=50 golden claims batched into one
    # prompt, not one call per claim), but each call took 39-111s observed (dry-run vs real), so
    # give this check a generous --timeout (>=180s) and know the cost before running it inside a
    # bare --all with no --checks filter -- same caution rubric_overspecification_check.py's own
    # registration already carries for the other LLM-based check in this file.
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
    # Expected-clause/description text across DIFFERENTLY-NAMED criteria (TF-IDF cosine,
    # threshold 0.42, min 3 shared content tokens). Distinct from duplicate_criterion_check.py
    # (pre-conversion xlsx ID collision, excluded above) and judge_criterion_name_duplicate_check.py
    # (same NAME, not content). Same "std" CLI shape. Verified against the real corpus before
    # registering; updated 2026-09-16 after porting GLM round 33's Jaccard-distance
    # value-divergence gate (independently re-verified against the real 600-task corpus, not
    # just trusted): SVC-PC-29-2-0 now 9 clusters / 27.19% excess (was 10/33.73%), SVC-PC-33-8-0
    # now 8 clusters / 49.5% (was 9/50.5%) -- both still correctly flag, the reduction is the
    # source-naming false-positive class the new gate suppresses; SVC-PC-21-4-0 still clean.
    # Full corpus: fail=230/warn=170/pass=200 (pre-fix) -> warn=355/pass=245/fail=0 (post-fix):
    # 45/600 tasks (7.5%) fully cleared, and the "fail" tier disappeared entirely -- a real,
    # disclosed-in-code severity downgrade (the FAIL_EXCESS_FRACTION branch was removed, not
    # just the similarity gate), changing zero task's cluster CONTENT, only its severity label.
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
    # above, added 2026-09-16 -- coordinator-approved after a random 20-task hand-verification
    # of that check's real pre-fix fail-tier population found the FAIL removal was directionally
    # justified (85-90% benign) but was also silently hiding a real minority of genuine cases,
    # and that a simple higher excess-fraction threshold could not separate them (a confirmed-
    # benign task scored HIGHER post-fix excess than a confirmed-genuine one). This check is the
    # narrower fix that resulted: same judge.toml FILE, EXACT match (not fuzzy) on the
    # requirement clause (the text before "Expected:", not the Expected clause itself). Verified
    # against the real 600-task corpus, not assumed: fail=10/pass=590, and every one of the 10
    # fail tasks' 15 findings individually hand-confirmed genuine against real judge.toml (100%
    # precision on this final version, after one confirmed false positive, SVC-PC-56-1-0's
    # verbatim-quote-check template, motivated the _VERBATIM_QUOTE_RE exclusion in the check's
    # own source). FAIL severity, unlike duplicate_criterion_content's warn-only, because this
    # narrower signal's real precision (not just its small population) earned it -- see that
    # check's own module docstring "Real calibration" and tracker row 4 for the full numbers.
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
    # subdomain/task_type fields, empty in every real SVC-PC task checked (category/tags are
    # platform-emitted, not part of the defect). Warn-only by design -- no scoring effect,
    # cataloguing/discoverability only -- never fails a task. Same "std" CLI shape. Verified: 5
    # findings/task (one per absent field) on all three named calibration tasks (29-2-0, 33-8-0,
    # 21-4-0), matching its own documented real empty-metadata SVC-PC shape.
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
    # Warn-only, never fails. Same "std" CLI shape. Verified: SVC-PC-37-3-0 reproduces its named
    # real defect exactly (golden cites ".../MSA_SwiftShip_2021.pdf", absent from environment/)
    # plus one further same-pattern finding (MSA_Apex_2021.pdf, also absent); SVC-PC-41-4-0
    # correctly does not fire, per this check's own disclosed "wrong file type" limitation
    # (environment/ carries SwiftShip_Evaluation.docx and three Apex_*.docx/.pdf files, but no
    # Apex/SwiftShip rate card -- confirmed by direct listing, not assumed). Updated 2026-09-16
    # after porting GLM round 33's precision pass (17% cut to sub-case A extraction-artifact
    # false positives; sub-case B's COMMON_CAPITALIZED_WORDS exclusion list cut its false-positive
    # rate from ~98% to 5/600 real tasks) -- independently re-verified against the real 600-task
    # corpus: warn=297/pass=303 (pre-fix) -> warn=255/pass=345 (post-fix), 42/600 tasks (7%)
    # cleared; SVC-PC-37-3-0 still fires its 2 named findings, SVC-PC-41-4-0 still correctly
    # clean, SVC-PC-41-3-0 (round 33's named sub-case B true positive, "the NovaTex MSA
    # Schedule") now correctly fires. No severity-tier change (still warn-only).
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
    # images, so same letter D as that check, NOT letter A. content-audit/SKILL.md, this
    # runner's only "Check A", is documented above as having no CLI and no CHECKS entry, and
    # LETTERS on this runner is ("C","D","E") -- registering letter "A" would KeyError in
    # merge()'s `by_letter = {L: [] for L in LETTERS}` on the first task processed, confirmed by
    # reading merge() directly rather than assumed. This is LLM-judgment territory like
    # content-audit, but unlike content-audit it ships a real CLI (task_ids + --root + --out,
    # same "std" shape) that reuses tools/llm_backend.call_llm() -- Claude Code CLI first (free
    # under a Max plan) then a caller-configured HTTP backend, never a hardcoded credential.
    # UNLIKE every other entry in this dict, one run of this check makes one LLM call PER TASK --
    # 50-100s, not milliseconds -- and a real cost/time commitment when the CLI backend is
    # unavailable and a paid HTTP backend is configured instead. A bare `--all` with no
    # `--checks` filter now attempts this for every task in the corpus; scope with `--checks` to
    # exclude it from a fast sweep. Verified before registering: unit tests (16/16, fixture-only,
    # no real call); --dry-run against the real corpus confirms prompt construction surfaces all
    # three named real over-specification cases in SVC-PC-33-8-0 (5-vs-4 checks, the 4-name
    # roster, the deferred tolerance).
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
    # cell_address_pinned_check.py: a 5th over-specification category the LLM
    # check above has no pattern for -- a criterion that pins an exact numeric
    # answer AND the exact source cell address it came from, e.g. "18.33
    # (Cover!B5)". Worse than a plain value-pin because it tells the solver
    # exactly which sheet/cell to read rather than requiring the analysis to
    # be built. Deterministic regex (not LLM), same CLI/output shape as
    # pinned_value_prescreen_check.py (style="rubric_schema"), same letter D
    # as rubric_overspecification above (same defect family). Warn-only, never
    # gates.
    #
    # Architecture choice: standalone script, NOT a new category inside
    # rubric_overspecification_check.py. That script is LLM-based (one call per
    # task); adding a deterministic regex there would mix detection methods.
    # This script mirrors pinned_value_prescreen_check.py's structure instead
    # (deterministic, dual-format, same CLI shape). See the script's own
    # docstring for the full rationale.
    #
    # Validation (full 600-task SVC-PC corpus, 2026-09-17): 8 tasks flagged with
    # 240 findings (239 sheet-qualified, 1 bare). Sheet-qualified pattern: 100%
    # precision on 8 spot-checked findings (0 FP), 100% recall on SVC-PC-41-4-0
    # ground truth (34/34). Bare pattern: 0 true positives, 6 residual false
    # positives after exclusions (1 SVC-PC K12 source citation + 5 EKW part
    # codes). See ROUND62-ROW16-REPORT.md for the full precision/recall and
    # false-positive spot-check. EKW: ran against the real 274-task corpus
    # (0 sheet-qualified findings, 5 bare false positives -- all part/identifier
    # codes like CNC12, K2207, not cell refs).
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
    # structural_audit_check.py: closes tracker rows 28-29 (the two real defects
    # EVERY existing check missed: SVC-PC-72-3-0 names the same deliverable two
    # ways in two sections, judge.toml reads only one; SVC-PC-82-2-0 has an
    # "Assigned corpus files" heading that promises a list then gives zero items,
    # while a must-pass criterion requires "six assigned files"). Automates the
    # six-pattern manual "structural audit" methodology (structural-audit/
    # SKILL.md) as a real LLM-judge check: feeds the LLM the real instruction.md
    # (with line numbers so it can cite the two disagreeing sections), the real
    # judge.toml files= list (split into solver-produced deliverables vs judge
    # read-scope sources via deliverable_filename_check.py's discriminator), the
    # real judge.toml criteria, and a real environment file manifest, then asks
    # it to apply the six patterns and report per-pattern pass/fail/warn with a
    # verbatim quote.
    #
    # LETTER CHOICE - letter C, NOT letter A. The brief said "under the LLM-judge
    # group (check A)" but also said "do not assume A is correct without
    # checking"; checking settles it: LETTERS on this runner is ("C","D","E")
    # and registering "A" would KeyError in merge()'s
    # `by_letter = {L: [] for L in LETTERS}` on the first task processed
    # (confirmed by reading merge() directly, line 1279, not assumed). The
    # letter tracks the DEFECT CLASS, not the method (deterministic vs LLM):
    # rubric_overspecification is LLM-based but sits at D (mechanical/rubric
    # defect class); golden_groundedness is LLM-based but sits at E (formula
    # health). These six patterns are STRUCTURAL defects (instruction.md vs the
    # real judge.toml files= vs the real environment listing - the built
    # package), the same defect class as the deterministic C checks
    # (environment_input, deliverable_count, answer_key_leakage). Letter C is
    # the correct fit; this is the LLM-judge analog of those deterministic
    # structural checks, catching the semantic structural defects a regex
    # cannot. content-audit/SKILL.md is the pipeline's "Check A" by tracker
    # column, but it has no CLI and no CHECKS entry (documented above, line 73);
    # this check ships the CLI the structural patterns need to run
    # automatically in the normal process, not only when a human remembers.
    #
    # Same "std" CLI shape, same verdict/findings mapping, same warn-only
    # "candidate, not verdict" posture as golden_groundedness and
    # rubric_overspecification. EXPENSIVE: one real LLM call per task
    # (~5-15s observed on the configured glm-5.2 backend for the real corpus's
    # audit-sized prompts); give it a generous --timeout and scope with
    # --checks to exclude it from a fast sweep, same as those two checks.
    # Verified 2026-09-17 against the two motivating tasks (real LLM calls, not
    # dry-run): both flagged correctly - SVC-PC-72-3-0 -> pattern 2
    # (deliverable_filename_mismatch, citing line 17 no-prefix vs line 23
    # L2-03_ prefix), SVC-PC-82-2-0 -> pattern 5 (unstated_deliverable_count,
    # citing the empty "Assigned corpus files" list vs criterion r09 "six
    # assigned files"). Broader 28-task real sample: 19 pass, 9 warn, 0 error;
    # 8 of 9 warnings confirmed true positives on file spot-check, 1 false
    # positive (an LLM case-misread: FPA read as Fpa). See
    # ROUND62-ROW28-29-REPORT.md for the full real output.
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
    # fabricated_unfilenamed_fact_check.py: tracker row 35 (round 62). The automated
    # LLM-judge "check A" (content audit) the CLAUDE.md tracker mapping had always left
    # as "not scripted, needs a human/LLM read". A golden can fabricate a specific
    # factual claim (a named vendor/system/bank, a PO/invoice/document number, a named
    # internal process, a specific figure attributed to a named document) as prose with
    # NO filename to key on, which is NARROWER than row 8's source_citation_existence
    # (letter D): that check needs a filename/path-shaped token (sub-case A) or a
    # proper-noun-plus-category-word pair (sub-case B) to extract; when the fabrication
    # is plain prose with no such token, row 8 structurally cannot catch it. This check
    # is the COMPLEMENT: it hands the LLM the golden text plus the REAL recursive
    # environment file listing (all extensions, ground truth not a file_listing.txt
    # hint, which an earlier check found to omit a whole real subdirectory) and asks
    # it to identify specific named claims stated as established fact where NEITHER
    # (a) a corresponding file exists NOR (b) the golden itself flags the claim (or the
    # reading resting on it) as open/unverified anywhere in the golden.
    #
    # LLM-judge, one real call per task (like rubric_overspecification and
    # golden_groundedness). EXPENSIVE: 70-280s observed per task against the configured
    # glm-5.2 HTTP backend (LLM_BACKEND_FORCE=http); give it a generous --timeout
    # (>=300s) and scope with --checks when running a fast sweep. Warn-only, never
    # fail, same "candidate, not verdict" posture as every other LLM check.
    #
    # Verified 2026-09-17 against the real C:\ekwqc\repo corpus, real LLM calls (not
    # dry-run, not fabricated): the 4-task acceptance test produced the required 3-flag
    # / 1-clear split and held it across two consecutive runs. The three true positives
    # flag: SVC-PC-21-0-0 (invents "Mercury" bank, "Close Authority and Review Map"
    # process, "Licence inventory", "INC-2021-014", Bench/Avalara/ProfitWell/Carta),
    # SVC-PC-24-6-0 ("GOTS organic / OEKO-TEX / CertiPUR-US" and "certs on file" under
    # "NovaTex QSA", no cert files), SVC-PC-73-3-0 ("Jan 18 2022 board minutes" for a
    # $4-5M range, no board-minutes file). The true negative clears: SVC-PC-52-5-0
    # ("Processor annual summary" is transparently flagged "Open item / Carried open",
    # and "Merchant agreement" is a generic category reference excluded by the
    # prompt's specificity lever, not a specific fabricated name). See
    # ROUND62-ROW35-REPORT.md at the worktree root for the full validation record
    # including a broader 30-task sample. A follow-up adversarial review found the
    # acceptance split does NOT reliably hold across more than 2 runs (see that
    # review's report); treat a single clean verdict from this check as advisory only.
    #
    # Letter D, not a new "A" slot: this project's own letter legend (top of this file) has
    # no "A" - the only thing "check A" names anywhere in this codebase is
    # `content-audit/SKILL.md`, explicitly logged above as NOT registered here because it is
    # "0% script, 100% judgment... cannot be wired into this subprocess harness tonight or
    # ever, on its current design." This check is the opposite (a real, runnable, automated
    # LLM check), so it was never a fit for that slot. D is where this project already keeps
    # groundedness/citation-shaped checks: source_citation_existence, criterion_groundedness,
    # judge_scope_over_inclusion, judge_scope_under_inclusion - this is a direct sibling of
    # all four, not a new category. (Corrected 2026-09-17 from an earlier commit that added a
    # real "A" slot to LETTERS; reverted alongside this change. Two independent adversarial
    # reviews confirmed the "A" slot would have silently broken ekw_tracker_writeback.py,
    # which is hardcoded to B-E.)
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
    # judge_file_size_cliff_check.py (row 31): WARN-tier advisory for
    # harbor-rewardkit's 1 MiB silent-truncation cliff (_MAX_FILE_SIZE = 1024*1024
    # in rewardkit/judges.py, confirmed by reading both the installed 0.2.0 and the
    # 0.1.7 extraction). A prior round drafted a checker that tested whether GOLDEN
    # files exceed 1 MiB; two validation passes found 0/202 goldens do, because
    # goldens are always small curated reference files. That checker cannot catch
    # anything: the truncation applies to the SOLVER SUBMISSION (the graded file),
    # not the golden.
    #
    # The brief suggested building a size-risk heuristic from the golden's own
    # structural complexity (formula count, sheet count, row/column extent). This
    # was investigated for real against the full 202-task subset (openpyxl parse of
    # every xlsx golden): the incident task's golden (SVC-PC-66-2-0: 7 sheets, 45
    # formulas, 25 max rows, 6 max cols) sits at the MEDIAN of every structural
    # complexity metric (corpus medians: 7 sheets, 42 formulas, 34 rows, 9 cols).
    # Golden complexity cannot distinguish the incident from ~100 others because
    # bloat comes from embedding source DATA, not from the deliverable SHAPE. The
    # golden is always small (curated answer); the bloat fuel is the environment.
    #
    # This check uses the environment's data file sizes instead -- the ACTUAL
    # source of bloat, and part of the task package. It flags tasks where the
    # environment's largest data-shaped file (csv/json/xlsx/xml/tsv/parquet) is
    # >= 256 KiB (262,144 bytes = 1 MiB / 4x xlsx embedding overhead: a NAMED
    # threshold, not arbitrary). The incident confirms: SVC-PC-66-2-0's 4 MiB
    # orders_export_1.csv, with ~7% embedded, produced a 1,112,742-byte submission
    # past the cliff. ONE data point, not a validated ratio.
    #
    # 202-task real run: 74/202 WARN (all xlsx-golden tasks with shared large
    # corpus data), 128/202 clean. Both incident tasks flagged. The WARN
    # population is high (37%) because the SVC-PC corpus has a large shared data
    # universe -- this is the real at-risk population, not a false-positive rate.
    # The REAL fix belongs in harbor-rewardkit (making the truncation LOUD instead
    # of silent); this per-task check is a COMPLEMENTARY advisory.
    #
    # CLI: <root> [--task ID] [--json OUT], style="rubric_schema" (same shape as
    # judge_file_scope_breadth_check.py). WARN never gates the exit code.
    "judge_file_size_cliff": dict(
        script="judge_file_size_cliff_check.py",
        letter="D",
        style="rubric_schema",
        task_key="task",
        verdict=lambda r: "warn" if r.get("findings") else "pass",
        findings=_findings_from("findings"),
    ),
}
LETTERS = ("C", "D", "E")
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


def find_task_dirs(root: Path, task_ids=None, id_prefix: str = "") -> list[Path]:
    if task_ids:
        dirs = []
        for tid in task_ids:
            p = root / tid
            if not p.is_dir():
                print(f"WARNING: task dir not found, skipping: {p}", file=sys.stderr)
                continue
            dirs.append(p)
        return dirs
    return sorted(
        p for p in root.iterdir() if p.is_dir() and p.name.startswith(id_prefix)
    )


def run_shared_check(
    name: str,
    spec: dict,
    target: Path,
    out_dir: Path,
    task_ids,
    shard: int,
    timeout: int,
) -> dict:
    """One shard of one shared check: the check's own script over an explicit list of task ids,
    writing <out_dir>/_shards/<name>.<shard>.json."""
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
        # via a static flag (formula_health_extraction_loss reuses formula_health_check.py with
        # --check-extraction-loss) -- spec["extra_args"] carries that flag through. Empty/absent
        # for every check that doesn't need one, so this is a no-op for the rest. Ported from
        # ekw_run_checks.py's identical mechanism (commit 027957a).
        cmd += spec.get("extra_args", [])
        # formula_health_check.py, verifier_executability_check.py, source_truncation_check.py
        # and unrequested_deliverable_source_check.py all run their own internal
        # ProcessPoolExecutor (default cpu_count-1 workers when --jobs is unspecified, confirmed
        # in their own source; formula_health_extraction_loss shares formula_health_check.py's
        # own pool under --check-extraction-loss, same mechanism). Without this, each of THIS
        # runner's own outer shards spawns a full inner pool independently, multiplying real
        # concurrency by the shard count -- the exact mechanism that caused a real
        # BrokenProcessPool crash on ekw_run_checks.py's full-corpus run (2026-09-15,
        # formula_health_check.py) before that orchestrator's own fix (commits 80a7698,
        # 027957a). svc_run_checks.py never carried this guard at all -- ported here for
        # formula_health too, not just the four newly-registered checks, since the bug was
        # already live and just hadn't been hit yet on this orchestrator. The outer sharding
        # already IS each check's parallelism; forcing the inner pool to 1 makes total
        # concurrency match what --jobs actually asked for instead of silently multiplying it.
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
    """Combine a check's shard JSONs into <out_dir>/<name>.json."""
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
        "ok": merged is not None and len(ok_shards) == len(shard_recs),
    }
    print(
        f"  {name:<32} merged {len(ok_shards)}/{len(shard_recs)} shards, cpu {rec['seconds']}s, {'json ok' if rec['ok'] else 'INCOMPLETE'}",
        file=sys.stderr,
    )
    return rec


def load_results(name: str, spec: dict, out_json: Path) -> dict[str, dict]:
    if not out_json.is_file():
        return {}
    data = json.loads(out_json.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("results", [])
    return {str(r.get(spec["task_key"])): r for r in rows if isinstance(r, dict)}


def merge(
    task_ids: list[str],
    per_check: dict[str, dict[str, dict]],
    ran: set[str],
) -> list[dict]:
    rows = []
    for tid in task_ids:
        row = {"task_id": tid, "checks": {}}
        by_letter: dict[str, list[str]] = {L: [] for L in LETTERS}
        for name, spec in CHECKS.items():
            if name not in ran:
                continue
            r = per_check.get(name, {}).get(tid)
            if r is None:
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
            row["checks"][name] = cell
            by_letter[spec["letter"]].append(cell["verdict"])
        for L in LETTERS:
            row[L] = rollup(by_letter[L]) if by_letter[L] else "skip"
        rows.append(row)
    return rows


def write_csv(rows: list[dict], ran: list[str], path: Path) -> None:
    cols = ["task_id", *LETTERS]
    for name in ran:
        cols += [name, f"{name}_n", f"{name}_first"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            flat = {"task_id": r["task_id"], **{L: r[L] for L in LETTERS}}
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
        "--root",
        required=True,
        help="SVC-PC task package root, one task directory per task (native shape, e.g. 03_dataos_ready)",
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
        "--jobs",
        type=int,
        default=os.cpu_count() or 4,
        help="concurrent processes for the shared checks (default: one per CPU)",
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

    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2
    if not args.all and not args.task_ids:
        sys.stderr.write("give task ids or --all\n")
        return 2
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    selected = (
        [c.strip() for c in args.checks.split(",")] if args.checks else list(CHECKS)
    )
    bad = [c for c in selected if c not in CHECKS]
    if bad:
        sys.stderr.write(f"unknown checks: {bad}\n")
        return 2
    task_ids_arg = args.task_ids or None

    t_all = time.time()
    per_check: dict[str, dict[str, dict]] = {}
    runs = []

    if args.merge_only:
        for name in selected:
            per_check[name] = load_results(name, CHECKS[name], out_dir / f"{name}.json")
        ordered_ids = sorted({tid for res in per_check.values() for tid in res})
        missing = [c for c in selected if not per_check.get(c)]
        if missing:
            print(
                f"no JSON for: {missing} (their columns will read error)",
                file=sys.stderr,
            )
        rows = merge(ordered_ids, per_check, set(selected))
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

    ordered_ids = [p.name for p in find_task_dirs(root, task_ids_arg, args.id_prefix)]
    if not ordered_ids:
        sys.stderr.write(f"no task directories found under {root}\n")
        return 2

    n_shards = max(1, min(args.shards, len(ordered_ids)))
    chunks = [ordered_ids[i::n_shards] for i in range(n_shards)]
    chunks = [c for c in chunks if c]
    # Heaviest checks first so the pool never ends on one long tail.
    heavy_first = sorted(
        selected, key=lambda n: HEAVY.index(n) if n in HEAVY else len(HEAVY)
    )
    print(
        f"shared checks ({len(selected)}) on {root}: {len(chunks)} shards each, {args.jobs} concurrent processes ...",
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
                    root,
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
    for name in selected:
        rec = merge_shards(name, CHECKS[name], out_dir, shard_recs.get(name, []))
        runs.append(rec)
        per_check[name] = (
            load_results(name, CHECKS[name], Path(rec["json"])) if rec["ok"] else {}
        )

    ran = list(selected)
    rows = merge(ordered_ids, per_check, set(ran))
    summary = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "root": str(root),
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

    if (out_dir / "summary.csv").exists():
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
