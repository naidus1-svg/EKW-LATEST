#!/usr/bin/env python3
"""Judge file-scope OVER-INCLUSION check (failure-mode tracker row 33): does the judge's own
configured file scope -- judge.toml's [judge].files=[...] list (SVC-PC) or a verifier's own
source.file list (EKW) -- include BOTH the graded deliverable AND pre-existing environment
source files, undifferentiated, so the judge can conflate source-document content with the
solver's own output?

Why this exists, and why it is NOT judge_file_scope_breadth_check.py's territory: that script
(its own module docstring names this explicitly) answers "which FILES are in scope" and flags
the zero-overlap end -- judge_scope_zero_source_visibility, where files=[...] contains only the
deliverable and excludes every named source (the judge can never read a source file, so
fabrication passes). This script closes the OPPOSITE end of the same axis: files=[...] contains
the deliverable AND one or more pre-existing source files in one undifferentiated list. The
rewardkit judge harness (harbor_rewardkit's judges.py:202 _build_user_content) concatenates
every file in files=[...] into undifferentiated "--- <path> ---" text blocks under a generic
system prompt ("You are an evaluation judge. Evaluate the provided file contents against the
following criteria.") that never labels which file is the submission. So the judge can (and,
on the confirmed cases, does) credit source-document content as if the deliverable itself
contained it -- a demonstrated, reproducible cheat, not a soundness gap.

Real, confirmed positive controls: SVC-PC-76-2-0 and SVC-PC-76-4-0 (both reviewer passes,
GPT-5.6-Sol and Claude Opus 5, independently confirmed). judge.toml's [judge].files lists 8
paths: the deliverable (L2-02_Retention_and_Deletion_Execution.docx / L2-04_Data_Locations_
and_Provider_Handoffs.docx) PLUS 7 pre-existing source documents (Backup_Recovery_Plan.docx,
Data_Retention_Policy_v2.docx, Merchant_Agreement_Stripe.pdf, Privacy_Policy_v2.docx,
Service_Agreement_CloudHost.pdf, Terms_of_Service_v2.docx, Vendor_Agreement_Shopify.pdf for
76-2-0; a different 7-file set for 76-4-0). Probe results from the Comprehensive Review:
  SVC-PC-76-2-0: a rubric-restating boilerplate memo with ZERO source content scored reward
    1.0, 12/12 criteria yes (reproduced 3/3); a workspace with NO deliverable at all still
    scored 0.52 (6/12 criteria pass on source content alone).
  SVC-PC-76-4-0: a "Content to be drafted." placeholder scored 0.84/1.00 (8/10 yes) graded
    against files=[deliverable + 7 sources], vs 0.00/1.00 (0/10) graded against the deliverable
    alone. Both reviewers independently confirmed the fix: narrow files= to the deliverable only.
Source: ekw/svc-comprehensive-review-results-2026-09-16/SVC-PC-76-{2,4}-0_verif*.json and
ekw/svc-dataos-failure-mode-tracker-CONSOLIDATED-2026-09-16.md row 33.

What it checks, per task, per judge group (SVC-PC: one group per tests/deliverables*/judge.toml;
EKW: one group per verifier, since ekw_verifier_json.py confirms EKW has no judge.toml-style
shared grouping -- each verifier carries its own file list):

  1. Extracts the DELIVERABLE filename(s) from instruction.md's deliverable-naming section --
     the text from the first DELIVERABLE_MARKER_RE match ("## Graded deliverable filenames" or
     "Submit the graded deliverables using") onward, using FILENAME_RE -- the SAME regex the
     breadth check uses for source extraction, applied to the OPPOSITE section. This is the
     solver's required OUTPUT, not source material. For EKW, an additional heading ("Produce
     the following deliverables in <path>:") is recognized as a fallback, matching
     deliverable_filename_check.py's own EKW port convention.
  2. Extracts the ENVIRONMENT file basename set: every file under environment/initial_workspace/
     (SVC-PC) or environment/data/ (EKW), recursive, lowercased -- mirroring environment_signals()'s
     own basename-extraction logic without the expensive text/content extraction this check does
     not need. Falls back to file_listing.txt (the flattened mirror's file manifest) when the
     environment directory is absent, so this check runs against both the real corpus and the
     flattened mirror.
  3. For each judge group, computes that group's own file scope as a lowercased basename set.
     One finding, in order of confidence:

     a. judge_scope_over_inclusion (HARD, gates the exit code) -- fires when this group's scope
        contains BOTH at least one deliverable file (step 1, confirmed by basename match against
        the deliverable set) AND at least one pre-existing source file (a file in scope that
        exists in the environment basename set AND is not the deliverable). This is the SVC-PC-
        76-2-0/76-4-0 shape: the judge sees the deliverable and the sources in one undifferentiated
        list, so source-document content can be credited as if the deliverable contained it.

  4. Reports, per group with a hard finding, reward_at_risk_upper_bound: the sum of that group's
     own criterion weights (SVC-PC: judge.toml's weight field, re-parsed directly via tomllib,
     same as the breadth check; EKW: metadata.weight, already surfaced by load_ekw_criteria).
     Named "upper bound" for the same reason as the breadth check: this script has no way to
     confirm every criterion in an over-inclusion group is actually conflation-exploitable
     (some could grade only the response's internal coherence, which is honest even with sources
     in view) -- it is the total weight that COULD be gamed by source/deliverable conflation, not
     a claim that it WILL be.

Provenance: dual-format dispatch and helper reuse match judge_file_scope_breadth_check.py
exactly. _load_svc_pc_groups(), _has_svc_pc_config(), _load_instruction(), _basename(),
_weight_sum(), and DELIVERABLE_MARKER_RE are imported directly from that script (the
assignment names them as the source of the helpers). FILENAME_RE is imported from
criterion_groundedness_check.py (same reuse convention). has_ekw_config()/load_ekw_criteria()
from ekw_verifier_json.py. The only new code is the over-inclusion predicate itself and the
deliverable-section extractor (the breadth check's _split_deliverable_section strips that
section; this script takes it instead).

Exit 0 clean (zero HARD findings across every task), 1 findings, 2 bad usage.

    python round55-judge_scope_over_inclusion_check.py <package_root> [--task TASK-ID] [--json out.json]

Known limits, disclosed rather than silently dropped -- READ THIS BEFORE TRUSTING A "clean"
RESULT, matching judge_file_scope_breadth_check.py's own precedent:
    - This is a STRUCTURAL SHAPE check, not a semantic one. It flags the SHAPE (deliverable +
      source both in scope, undifferentiated) that MAKES source/deliverable conflation possible.
      It does NOT confirm the conflation was actually exploited -- that requires a probe (the
      kind both reviewers ran on 76-2-0/76-4-0). A "clean" result means the shape is absent, not
      that the task is defect-free; a flagged result means the shape is present, not that every
      criterion is conflation-exploitable. See reward_at_risk_upper_bound's own caveat above.
    - A task whose criteria genuinely REQUIRE source verification (the judge SHOULD see sources
      to check the deliverable's claims against them) will ALSO fire this check, because the
      undifferentiated files=[...] list is the same shape regardless of intent. On such a task
      the fix is NOT "narrow to deliverable only" (that would recreate the zero-visibility
      defect the breadth check flags) but "add role-labeling so the judge can tell submission
      from source" -- which harbor-rewardkit's current harness does not support, so the
      practical resolution is a task-design decision this script cannot make. Disclosed as a
      known over-flagging risk on source-verification task designs, not as a false positive in
      the narrower sense (the structural risk is real on every task that fires; whether it is
      the PRIMARY defect depends on the task's own criteria).
    - Deliverable extraction depends on instruction.md carrying a "## Graded deliverable
      filenames" heading (SVC-PC) or a "Produce the following deliverables in <path>:" heading
      (EKW). An instruction.md that names its deliverable only in prose body text with no heading
      is invisible to this check -- deliverable_files comes back empty, so the over-inclusion
      predicate never fires (nothing to match against), and the result reads as clean. This is
      a real, disclosed coverage gap, not a hidden one; every result also reports
      deliverable_files so a human can see when the check had no deliverable to work with,
      distinct from a genuine clean pass. solution/files/ (the solver's own produce set) is a
      more reliable deliverable signal that deliverable_filename_check.py already uses, but is
      deliberately NOT consumed here: the assignment names DELIVERABLE_MARKER_RE (instruction.md-
      based) as the deliverable signal, and adding a second path would diverge from the template
      for no confirmed gain on the two real cases (both carry the heading).
    - The environment basename set is built from a directory listing (rglob), not from file
      content. A judge.toml files=[...] entry whose basename matches an environment file is
      counted as a source even if the environment copy is a judge-side derived artifact
      (*_judge_extract.csv, *.extracted.md) rather than the original source. This is correct for
      this check's purpose (a judge artifact IS pre-existing source-derived content the judge
      sees alongside the deliverable, undifferentiated), but it means a group whose only non-
      deliverable scope entry is a judge artifact will fire, where a human might argue the
      artifact is a grading-pipeline convenience rather than a source the solver was given.
    - EKW verifiers typically carry only the deliverable path (under output/) in their
      source.file list, not source files, so this check will almost never fire on EKW. That is
      correct behavior, not a gap: the over-inclusion shape is an SVC-PC pattern (one shared
      judge.toml files=[...] list per group). If an EKW verifier ever does carry both a
      deliverable and an environment source file, this check will flag it the same way.
    - Like every text-pattern check in the sibling folder, this reads instruction.md and the
      config files only; it does not open the deliverable itself to see whether a real response
      for this task actually exploited the conflation. It answers "can this be gamed," not
      "was it."

Validation against real data (2026-09-16 session; nothing under either path was modified --
this script only reads):

  Positive controls: SVC-PC-76-2-0 and SVC-PC-76-4-0, read from the flattened mirror at
  ekw/pipeline-mirror/khiem-202-data/full-202-text-and-listings/<TASK-ID>/ (instruction.md +
  tests__deliverables__judge.toml + file_listing.txt), staged into the real layout this script's
  reused helpers expect. Both flagged judge_scope_over_inclusion on their one judge group:
  1 deliverable + 7 sources in scope, reward_at_risk_upper_bound 1.0000. See this script's own
  CLI output (and the companion note committed alongside it) for the exact per-run numbers.

  Corpus-wide false-positive counts across the 202-task flattened mirror are deliberately NOT
  hardcoded in this docstring -- see the companion note for the actual run, so the numbers
  cannot drift out of sync with the code that produced them.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Reuse the template's own helpers directly rather than reinventing them. The breadth check
# lives in deterministic-checks/; this script lives in design-proposals/ (a sibling), so we
# add that directory to sys.path before importing.
_DETERMINISTIC_CHECKS = Path(__file__).resolve().parent.parent / "deterministic-checks"
if str(_DETERMINISTIC_CHECKS) not in sys.path:
    sys.path.insert(0, str(_DETERMINISTIC_CHECKS))

from judge_file_scope_breadth_check import (  # noqa: E402
    _load_svc_pc_groups,
    _has_svc_pc_config,
    _load_instruction,
    _basename,
    _weight_sum,
    DELIVERABLE_MARKER_RE,
)
from criterion_groundedness_check import FILENAME_RE  # noqa: E402
from ekw_verifier_json import has_ekw_config, load_ekw_criteria  # noqa: E402

# ---------------------------------------------------------------------------
# instruction.md: deliverable-filename extraction (the breadth check strips this
# section; this check takes it instead -- the OPPOSITE direction)
# ---------------------------------------------------------------------------

# EKW's own tier-1-equivalent deliverable heading, matching deliverable_filename_check.py's
# PRODUCE_DELIVERABLES_HEADING_RE. SVC-PC's "## Graded deliverable filenames" is already covered
# by the reused DELIVERABLE_MARKER_RE; this extends the same extraction to EKW.
_EKW_DELIVERABLE_HEADING_RE = re.compile(
    r"produce the following deliverables in [^\n:]*:",
    re.IGNORECASE | re.MULTILINE,
)


def _deliverable_section(instr_text: str) -> str:
    """instruction.md text from the first deliverable-naming marker onward -- the solver's own
    OUTPUT-naming section. This is the OPPOSITE of the breadth check's _split_deliverable_section,
    which returns the text BEFORE the marker (the source-facing body). SVC-PC's
    DELIVERABLE_MARKER_RE is tried first; EKW's _EKW_DELIVERABLE_HEADING_RE is the fallback."""
    m = DELIVERABLE_MARKER_RE.search(instr_text)
    if not m:
        m = _EKW_DELIVERABLE_HEADING_RE.search(instr_text)
    return instr_text[m.start():] if m else ""


def _instruction_deliverable_filenames(instr_text: str) -> set[str]:
    """Every filename-shaped token (FILENAME_RE) in instruction.md's deliverable-naming section,
    lowercased. This is the set the solver is told to PRODUCE, not source material to check
    judge-scope breadth against. Mirrors the breadth check's _instruction_named_filenames
    (source extraction from the body) in the reverse direction: same regex, opposite section."""
    section = _deliverable_section(instr_text)
    return {m.group(0).lower() for m in FILENAME_RE.finditer(section)}


# ---------------------------------------------------------------------------
# environment basename set -- mirrors environment_signals()'s basename branch without the
# expensive text/content extraction this check does not need
# ---------------------------------------------------------------------------


def _env_basenames(task_dir: Path, ekw: bool) -> set[str]:
    """Set of lowercased basenames of every file under environment/initial_workspace/ (SVC-PC)
    or environment/data/ (EKW), recursive. Mirrors environment_signals()'s own basename
    collection but skips the text/cell extraction (openpyxl/docx/pypdf) this check does not
    need, so it runs fast and has no optional-dependency requirements.

    Falls back to file_listing.txt when the environment directory is absent. The flattened
    mirror (ekw/pipeline-mirror/khiem-202-data/full-202-text-and-listings/<TASK-ID>/) ships
    instruction.md + flattened judge.toml + file_listing.txt but NOT the actual environment/
    directory; file_listing.txt is a tab-separated manifest of every file in the task package
    (size, relative path), so the env basenames are recoverable from it without the real files.
    """
    env_subdir = "data" if ekw else "initial_workspace"
    env_dir = task_dir / "environment" / env_subdir
    out: set[str] = set()
    if env_dir.is_dir():
        for p in env_dir.rglob("*"):
            if p.is_file():
                out.add(p.name.lower())
    if not out:
        listing = task_dir / "file_listing.txt"
        if listing.is_file():
            prefix = f"environment/{env_subdir}/"
            for line in listing.read_text(encoding="utf-8", errors="replace").splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    rel = parts[1].replace("\\", "/")
                    if rel.startswith(prefix):
                        out.add(Path(rel).name.lower())
    return out


# ---------------------------------------------------------------------------
# shared per-group analysis (both formats funnel through this one function, so SVC-PC and
# EKW can never silently apply different rules -- same convention the breadth check uses)
# ---------------------------------------------------------------------------


def _analyze_over_inclusion(
    res, group_label, group_files, criteria, deliverable_basenames, env_basenames
):
    scope = {_basename(f) for f in group_files if f}
    deliverable_in_scope = scope & deliverable_basenames
    # A pre-existing source: a file in this group's scope that exists in the environment AND is
    # not the deliverable. Excluding deliverable_basenames prevents the deliverable itself (if
    # it also happens to exist in the environment as a template) from being counted as a source.
    source_in_scope = (scope & env_basenames) - deliverable_basenames

    if deliverable_in_scope and source_in_scope:
        res["findings"].append(
            {
                "kind": "judge_scope_over_inclusion",
                "group": group_label,
                "deliverable_files_in_scope": sorted(deliverable_in_scope),
                "source_files_in_scope": sorted(source_in_scope),
                "n_criteria_in_group": len(criteria),
                "reward_at_risk_upper_bound": _weight_sum(criteria),
                "reason": (
                    f"this judge group's files=[...] includes {len(deliverable_in_scope)} "
                    f"deliverable file(s) AND {len(source_in_scope)} pre-existing environment "
                    f"source file(s), undifferentiated. harbor-rewardkit's judge harness "
                    f"concatenates every file in files=[...] into one undifferentiated text "
                    f"block with a generic system prompt that never labels which file is the "
                    f"submission, so the judge can credit source-document content as if the "
                    f"deliverable itself contained it (probe-confirmed on SVC-PC-76-2-0/76-4-0; "
                    f"see the Comprehensive Review verification JSONs and tracker row 33)."
                ),
            }
        )


def _base_result(task_dir: Path, fmt: str) -> dict:
    return {
        "task": task_dir.name,
        "format": fmt,
        "groups_checked": 0,
        "deliverable_files": [],
        "env_file_count": 0,
        "findings": [],
        "parse_errors": [],
        "ok": False,
    }


def check_task_svc_pc(task_dir: Path) -> dict:
    res = _base_result(task_dir, "svc_pc")
    instr_text = _load_instruction(task_dir)
    if instr_text is None:
        res["parse_errors"].append("no instruction.md")
        return res

    deliverable_basenames = _instruction_deliverable_filenames(instr_text)
    res["deliverable_files"] = sorted(deliverable_basenames)
    env = _env_basenames(task_dir, ekw=False)
    res["env_file_count"] = len(env)

    groups = _load_svc_pc_groups(task_dir)
    if not groups:
        res["parse_errors"].append(
            "no tests/deliverables*/judge.toml found for this task"
        )
        return res

    for g in groups:
        if g["parse_error"]:
            res["parse_errors"].append(
                f"{g['path']}: judge.toml failed to parse: {g['parse_error']}"
            )
            continue
        res["groups_checked"] += 1
        _analyze_over_inclusion(
            res, g["path"], g["files"], g["criteria"],
            deliverable_basenames, env,
        )

    res["ok"] = not res["findings"] and not res["parse_errors"]
    return res


def check_task_ekw(task_dir: Path) -> dict:
    """EKW: each verifier is its own group (no judge.toml-style shared scope exists --
    ekw_verifier_json.py's own docstring confirms this), so the per-group check above IS the
    per-criterion check here, one call per verifier. EKW verifiers typically carry only the
    deliverable path (under output/) in their source.file list, so the over-inclusion shape
    is not expected to fire on EKW -- but if a verifier ever does carry both a deliverable and
    an environment source file, this check flags it identically to SVC-PC."""
    res = _base_result(task_dir, "ekw")
    instr_text = _load_instruction(task_dir)
    if instr_text is None:
        res["parse_errors"].append("no instruction.md")
        return res

    deliverable_basenames = _instruction_deliverable_filenames(instr_text)
    res["deliverable_files"] = sorted(deliverable_basenames)
    env = _env_basenames(task_dir, ekw=True)
    res["env_file_count"] = len(env)

    criteria = load_ekw_criteria(task_dir)
    parse_error_entries = [c for c in criteria if c["name"] == "__parse_error__"]
    if parse_error_entries:
        for c in parse_error_entries:
            res["parse_errors"].append(c["description"])
        return res
    if not criteria:
        res["parse_errors"].append("tests/verifier.json has zero verifiers")
        return res

    for c in criteria:
        res["groups_checked"] += 1
        _analyze_over_inclusion(
            res, c["group"], c.get("files") or [], [c],
            deliverable_basenames, env,
        )

    res["ok"] = not res["findings"] and not res["parse_errors"]
    return res


def check_task_dispatch(task_dir: Path) -> dict:
    """SVC-PC takes precedence when both configs exist, matching every other dual-format check
    in the sibling folder."""
    if _has_svc_pc_config(task_dir):
        return check_task_svc_pc(task_dir)
    if has_ekw_config(task_dir):
        return check_task_ekw(task_dir)
    res = _base_result(task_dir, "unknown")
    res["parse_errors"].append(
        "no tests/deliverables*/judge.toml or tests/verifier.json found"
    )
    return res


# ---------------------------------------------------------------------------
# CLI -- same shape as judge_file_scope_breadth_check.py's main()
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "root",
        help="a directory containing one subdirectory per task, or a single task directory",
    )
    ap.add_argument(
        "--task",
        action="append",
        default=[],
        help="limit to these task ids (repeatable)",
    )
    ap.add_argument("--json", help="also write the full result set here")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2

    if (root / "tests").is_dir():
        task_dirs = [root]
    else:
        task_dirs = sorted(d for d in root.iterdir() if d.is_dir())
    if args.task:
        want = set(args.task)
        task_dirs = [d for d in task_dirs if d.name in want]
    if not task_dirs:
        sys.stderr.write(f"no task directories matched under {root}\n")
        return 2

    results = []
    for i, d in enumerate(task_dirs, 1):
        if len(task_dirs) > 20:
            print(f"[{i}/{len(task_dirs)}] {d.name} ...", file=sys.stderr)
        results.append(check_task_dispatch(d))

    bad = [r for r in results if not r["ok"]]
    n_no_deliverable = sum(
        1 for r in results if not r["deliverable_files"] and not r["parse_errors"]
    )
    total_reward_at_risk = sum(
        f["reward_at_risk_upper_bound"]
        for r in results
        for f in r["findings"]
        if f["kind"] == "judge_scope_over_inclusion"
    )

    for r in results:
        flag = "OK  " if r["ok"] else "FAIL"
        print(
            f"{flag} {r['task']:<20} [{r['format']:<6}] "
            f"{r['groups_checked']:>3} group(s)  "
            f"{len(r['deliverable_files']):>2} deliverable(s)  "
            f"{r['env_file_count']:>3} env-file(s)  "
            f"{len(r['findings']):>2} findings"
        )
        for w in r["parse_errors"]:
            print(f"       parse: {w}")
        for f in r["findings"]:
            if f["kind"] == "judge_scope_over_inclusion":
                print(
                    f"       OVER_INCLUSION [{f['group']}]: deliverable(s) "
                    f"{f['deliverable_files_in_scope']} + source(s) "
                    f"{f['source_files_in_scope']} undifferentiated, "
                    f"reward_at_risk_upper_bound={f['reward_at_risk_upper_bound']}"
                )

    print(
        f"\n{len(results) - len(bad)}/{len(results)} clean "
        f"({n_no_deliverable} of those had no extractable deliverable, so the check had "
        f"nothing to match against -- distinct from a genuine clean pass), "
        f"{len(bad)} FAIL  |  total reward_at_risk_upper_bound across all over-inclusion "
        f"findings: {round(total_reward_at_risk, 4)}"
    )
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
