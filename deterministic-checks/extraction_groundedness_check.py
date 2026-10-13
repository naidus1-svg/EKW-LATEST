#!/usr/bin/env python3
"""Extraction groundedness check: does a criterion's required property match what the
extraction path actually configured for its file(s) can see, or is it unpassable by
construction because the judge never receives that property at all.

Why this is a different check from rubric_text_lint.py's extraction_blind sub-check, not a
duplicate of it: that check is a flat keyword lint -- it flags a description matching a
blind-property phrase (formula-driven, tab color, hidden row, etc.) regardless of which
extraction command actually reads that criterion's file. Its own docstring already names the
resulting gap on EKW: 7 of 11 raw extraction_blind hits on the real 274-task corpus were false
positives, because those criteria's files were read via extract_formulas/extract_xlsx (which DO
expose live formulas and number-formatted display text), not extract_text -- and the lint had no
way to know that, since (at the time) nothing fed source.file.command into it. This script closes
exactly that gap by making the same property-vs-extraction question command-aware, per criterion,
for both benchmarks.

What "formula-aware" means, and how each format's answer was obtained -- confirmed directly
against real code and real judge output this session, not assumed from either benchmark's docs:

  EKW: `ekw_verifier_json.load_ekw_criteria()` already surfaces each criterion's own
  `commands` list (added for exactly this purpose -- see that module's `_extract_commands()`).
  `rl_world_verifiers/sources/xlsx.py` confirms `extract_text` loads a workbook with
  `data_only=True` / `values_only=True` (no formula text, no number formatting, no protection,
  no tab color, no hidden-row/sheet flags reach the judge under that command); `extract_formulas`
  and `extract_xlsx` are the two commands that do expose that state. A criterion whose file(s)
  are read through at least one formula-aware command is not blind; one read only through
  extract_text (or an unrecognized/absent command) is.

  SVC-PC: judge.toml carries NO per-criterion extraction-command field at all -- confirmed by
  reading every `[[criterion]]`/`[judge]` key SVC-PC's own to_rewardkit.py ever writes
  (`to_rewardkit.py:1140-1150`: only name/description/type/weight, nothing else) and the
  consuming schema in the extracted harbor_rewardkit package (`rewardkit/models.py:83-92,
  178-187`: Criterion/LLMJudge have no command/extraction field). The *intermediate*
  verifier.json rubric_xlsx_to_verifier.py builds does have a source.file.command slot
  (`build_source()`, ~line 976-985) mirroring EKW's shape, but it is hardcoded to the literal
  "extract_text" for every criterion, never varied by that generator, and is dropped entirely
  once to_rewardkit.py writes judge.toml. The real judge path
  (`rewardkit/judges.py:147-193`) routes any document extension (.xlsx/.xls/.docx/.pptx/.pdf/...)
  unconditionally to `_convert_with_markitdown()`, keyed only on file suffix, never on criterion
  content -- to_rewardkit.py:96-103 states this directly ("the judge only ever reads cell/formula
  text via markitdown, never executes macros"). A formula-capable path does exist
  (to_rewardkit.py:628-655) but only fires when `assertion.type == "deterministic"`
  (`_is_all_deterministic`, ~line 702-705); rubric_xlsx_to_verifier.py unconditionally stamps
  every SVC-PC criterion `"assertion": {"type": "rubric", ...}` (~line 1580-1584), never
  "deterministic" -- so that path is architecturally unreachable for SVC-PC today. Confirmed
  against two real named criteria: SVC-PC-1-1-0's `str-01` ("all roll-ups are live formula
  links... Fail if roll-up cells are hardcoded") and SVC-PC-7-3-0's `st5` ("Board-ready number
  formatting... Currency $#,##0...") -- both grade a real .xlsx through the identical
  MarkItDown-only path, so both are confirmed blind to the exact property they ask about,
  independent of the deliverable's actual quality. SVC-PC therefore has no override to check for:
  every criterion is graded as if its only recorded command were `extract_text`, unconditionally
  -- see SVC_PC_FIXED_COMMANDS below, which exists so both formats run through one shared
  blindness test rather than two independently-maintained ones.

This means a finding here on SVC-PC is a stronger claim than a finding from rubric_text_lint.py:
not "this phrase is suspicious," but "this exact property is confirmed unreachable by the actual
grading pipeline, verified against the real extraction code path, not the criterion text alone."
On EKW it is the same lint rubric_text_lint.py already runs, minus the false positives that
script's own docstring already discloses it cannot avoid.

What this script deliberately does NOT cover (recorded, not silently absorbed): a criterion whose
required property lives in a file that is not in the judge's files=[...] / verifier file list at
all -- that is a judge FILE-SCOPE problem (breadth: which files are in scope), not an extraction-
command problem (depth: what's visible once a file is in scope). Conflating the two would make
this script's verdicts uninterpretable. See SVC-PC-92-0-0's L2-1 finding (judge sees only the
response docx, never the source corpus) for a real, confirmed instance of the file-scope defect
this script does not and should not catch -- it needs its own check.

Status: v1, new 2026-09-14. Imports rubric_text_lint.py's EXTRACTION_BLIND_PATTERNS as a base
(so the two scripts never silently disagree on the patterns they DO share) and supplements it
with EXTRA_BLIND_PATTERNS below -- calibrated against the two real criteria this script exists
to catch (SVC-PC-1-1-0 str-01, SVC-PC-7-3-0 st5), neither of which the base list alone matches.
See EXTRA_BLIND_PATTERNS' own comment for the exact text and why each addition is narrow rather
than a broad word like "format" that would false-positive widely.

Usage:
    python extraction_groundedness_check.py <TASK-ID> [<TASK-ID> ...] --root <path> --out report.json
    python extraction_groundedness_check.py --all --root <path> --out report.json
    python extraction_groundedness_check.py --all --root <path> --id-prefix MYBENCH- --out report.json

Known limits, disclosed rather than silently dropped:
    - An unrecognized or absent extraction command is treated as blind, not as "unknown" -- see
      _is_extraction_blind()'s own docstring for why that direction of error was chosen.
    - Like rubric_text_lint.py, this is still a text-pattern match against the description for
      WHICH property a criterion asks about; it does not open the deliverable file itself to
      confirm the property is really there. It answers "if this property exists, can the
      configured extraction path see it," not "does this property exist."
    - Judge file-scope adequacy (is the right FILE even in scope) is out of scope by design --
      see the module docstring section above.
"""

import argparse
import json
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from ekw_verifier_json import has_ekw_config, load_ekw_criteria
from rubric_text_lint import EXTRACTION_BLIND_PATTERNS, load_judge_files

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Confirmed (ekw_verifier_json.py's own docstring, cross-checked against
# rl_world_verifiers/sources/xlsx.py) to actually expose live formulas and number-formatted
# display text to the judge, rather than rendered/cached plain text only. Anything NOT in this
# set -- including "extract_text", "read_file", "list_files", or no recorded command at all --
# is treated as blind. Deliberately conservative: an unrecognized command is not evidence of
# visibility, and the failure mode of a false "still blind" call (a human reads one extra
# flagged criterion) is far cheaper than a false "not blind" call (a criterion ships
# unpassable-by-construction and nothing ever catches it).
FORMULA_AWARE_COMMANDS = {"extract_formulas", "extract_xlsx"}

# SVC-PC's real judge path (rewardkit/judges.py) has no per-criterion command override --
# confirmed by reading every code path that could vary it (see module docstring). Every
# SVC-PC criterion is graded as if its only recorded command were extract_text, unconditionally.
# Modeled as a constant tuple, not a special-cased "always blind" branch, so both formats run
# through the exact same _is_extraction_blind() test rather than two independently-maintained
# ones that could silently drift apart.
SVC_PC_FIXED_COMMANDS = ("extract_text",)

# rubric_text_lint.py's EXTRACTION_BLIND_PATTERNS, read verbatim against the two real criteria
# that motivated this script (SVC-PC-1-1-0 str-01, SVC-PC-7-3-0 st5 -- both confirmed graded
# through the blind MarkItDown-only path, see module docstring), do NOT match either one's
# actual text. Confirmed by running this script before adding these patterns and reading the
# real judge.toml: importing the base list alone produced 0 findings on both known-blind
# criteria -- a check that can't catch the two examples it was built to catch is not a check,
# so this supplements rather than trusts the import at face value.
#
#   str-01's real text: "all roll-ups are live formula links... contain '=' references to
#   P&L Monthly (not hardcoded literals). Fail if roll-up cells are hardcoded." -- asks whether
#   cells hold live formula references or hardcoded values, a property MarkItDown's
#   data_only=True read cannot distinguish (both render as their cached numeric value).
#   st5's real text: "Board-ready number formatting throughout. Expected: Currency $#,##0;
#   percentages 0.0%; ... zeros render as '-'..." -- asks about cell.number_format display
#   codes, dropped entirely by a values-only read.
EXTRA_BLIND_PATTERNS = [
    r"live formula link",
    r"hardcoded literal",
    r"cells?\s+(?:are|is)\s+hardcoded",
    r"number formatting throughout",
    r"format artifacts",
]

# $#,##0 and 0.0% are Excel format-code syntax, not natural language, so they're a highly
# specific signal WHEN they're actually naming a display-format requirement. But a full
# 600-task SVC-PC run (2026-09-14) found the bare tokens also collide with two real, unrelated
# phrasings: a fixed grading-tolerance idiom ("Tolerance: within 0.0% only when population,
# period, unit, and basis all match" -- boilerplate seen on many criteria, e.g.
# SVC-PC-59-1-0's c01/c02/c07/c11/c18/c22/c23, none about formatting at all) and a literal
# business VALUE that happens to be a round percentage (SVC-PC-38-0-0 c5: "the expected
# dividend yield is 0.0%," a content fact MarkItDown reads just fine). Both patterns are
# therefore gated on FORMAT_CONTEXT_RE appearing within CONTEXT_WINDOW characters before the
# match -- every confirmed true positive in the same corpus run (SVC-PC-3-1-0 r055 "Currency
# cells formatted $#,##0"; SVC-PC-58-1-0 c17 and SVC-PC-71-1-0 c18 "currency cells carry a
# $#,##0 ... display format"; SVC-PC-71-6-0 c20 "Currency cells carry a $#,##0 Excel number
# format") has a formatting word sitting immediately before the token; neither false-positive
# shape does.
CONTEXT_GATED_PATTERNS = [r"\$#,##0", r"\b0\.0%"]
FORMAT_CONTEXT_RE = re.compile(r"format|carr(?:y|ies)|display", re.IGNORECASE)
CONTEXT_WINDOW = 60

# A criterion can correctly pre-empt this entire check by disclaiming, in its own text, that
# display-formatting isn't gradable from the evidence the judge receives. Real, well-authored
# example confirmed on the same corpus run: SVC-PC-58-6-0 c13 -- "That extraction always
# strips Excel's cell-level display format... raw-decimal appearance... is NEVER valid evidence
# that display formatting is missing, and must not be cited as a reason to fail. Score the
# formatting half of this criterion as satisfied by default." Flagging a criterion that has
# ALREADY correctly disclaimed its own extraction-blindness would be exactly backwards -- it is
# the one shape of criterion in this corpus that is provably NOT a defect, and the model this
# check exists to encourage more of, not flag. Mirrors rubric_text_lint.py's own NEGATION_RE
# convention (its meta_rubric_knowledge guard) for the same underlying reason: a keyword match
# preceded by an explicit disclaimer is the opposite of a defect. Applied at the whole-criterion
# level -- a criterion that disclaims the concern once shouldn't still be flagged on some other
# blind-property phrase elsewhere in the same description.
BLINDNESS_DISCLAIMED_RE = re.compile(
    r"not gradable|must not be (?:used|cited)(?: as a reason)? to fail|"
    r"scored? as satisfied by default",
    re.IGNORECASE,
)


def _find_blind_matches(desc):
    """Every (pattern, matched_text) hit in desc across the base + extra + context-gated
    pattern sets, or [] if the criterion has disclaimed extraction-blindness itself (see
    BLINDNESS_DISCLAIMED_RE) -- the one shared classifier both check_task_svc_pc() and
    check_task_ekw() call, so the two formats can never silently apply different rules.
    """
    if BLINDNESS_DISCLAIMED_RE.search(desc):
        return []
    hits = []
    for pat in ALL_BLIND_PATTERNS:
        m = re.search(pat, desc, re.IGNORECASE)
        if m:
            hits.append(m.group(0))
    for pat in CONTEXT_GATED_PATTERNS:
        # One finding per (criterion, pattern), matching how the base patterns above behave
        # via re.search -- stop at the first context-gated hit rather than reporting every
        # repeated occurrence of the same literal token in one description (e.g. a criterion
        # naming "$#,##0" twice, once for currency and once for a per-unit variant).
        for m in re.finditer(pat, desc, re.IGNORECASE):
            window = desc[max(0, m.start() - CONTEXT_WINDOW) : m.start()]
            if FORMAT_CONTEXT_RE.search(window):
                hits.append(m.group(0))
                break
    return hits


ALL_BLIND_PATTERNS = list(EXTRACTION_BLIND_PATTERNS) + EXTRA_BLIND_PATTERNS


def _is_extraction_blind(commands):
    """True if NONE of the given extraction commands can see live formulas or number-formatted
    display text -- i.e. every path the judge might read this criterion's file(s) through is
    confirmed blind to that state. See FORMULA_AWARE_COMMANDS for why an empty or unrecognized
    command list also counts as blind rather than "unknown"."""
    return not any(cmd in FORMULA_AWARE_COMMANDS for cmd in commands)


def _new_result(task_id):
    return {
        "task_id": task_id,
        "files_scanned": [],
        "findings": [],
        "errors": [],
    }


def _finalize(result):
    by_kind = {}
    for f in result["findings"]:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
    result["summary"] = {"n_findings": len(result["findings"]), "by_kind": by_kind}
    return result


def check_task_svc_pc(task_dir):
    """SVC-PC: tests/deliverables*/judge.toml. Every criterion is checked against
    SVC_PC_FIXED_COMMANDS -- see module docstring for why that's a confirmed constant, not an
    assumption -- so any blind-property match is reported as extraction_blind_confirmed: not
    "this phrase looks suspicious" but "this exact property is unreachable by the real grading
    pipeline, verified against the actual extraction code path.\" """
    task_id = task_dir.name
    result = _new_result(task_id)
    judge_files = load_judge_files(task_dir)

    if not judge_files:
        result["errors"].append(
            "no tests/deliverables*/judge.toml found for this task -- nothing for this "
            "check to run"
        )
        return _finalize(result)

    blind = _is_extraction_blind(SVC_PC_FIXED_COMMANDS)
    for jf in judge_files:
        if jf["parse_error"]:
            result["errors"].append(
                f"{jf['path']}: judge.toml failed to parse: {jf['parse_error']}"
            )
            continue
        result["files_scanned"].append(jf["path"])
        for c in jf["criteria"]:
            desc = c["description"]
            for matched in _find_blind_matches(desc):
                if blind:
                    result["findings"].append(
                        {
                            "kind": "extraction_blind_confirmed",
                            "file": jf["path"],
                            "criterion": c["name"],
                            "matched": matched,
                            "description": desc,
                            "commands": list(SVC_PC_FIXED_COMMANDS),
                        }
                    )
    return _finalize(result)


def check_task_ekw(task_dir):
    """EKW: tests/verifier.json via ekw_verifier_json.load_ekw_criteria(), which already
    carries each criterion's own `commands` list. Only flags a blind-property match when NONE
    of that specific criterion's recorded commands are formula-aware -- this is the exact
    command-awareness rubric_text_lint.py's own EKW port docstring names as missing (its 7/11
    false-positive measurement on this same corpus)."""
    task_id = task_dir.name
    result = _new_result(task_id)
    criteria = load_ekw_criteria(task_dir)

    parse_error_entries = [c for c in criteria if c["name"] == "__parse_error__"]
    if parse_error_entries:
        for c in parse_error_entries:
            result["errors"].append(c["description"])
        return _finalize(result)

    if not criteria:
        result["errors"].append(
            "tests/verifier.json has zero verifiers -- nothing for this check to run"
        )
        return _finalize(result)

    result["files_scanned"] = ["tests/verifier.json"]
    for c in criteria:
        desc = c.get("description") or ""
        commands = c.get("commands") or []
        blind = _is_extraction_blind(commands)
        for matched in _find_blind_matches(desc):
            if blind:
                result["findings"].append(
                    {
                        "kind": "extraction_blind_confirmed",
                        "file": "tests/verifier.json",
                        "criterion": f"{c['group']}/{c['name']}",
                        "matched": matched,
                        "description": desc,
                        "commands": commands,
                    }
                )
            else:
                result["findings"].append(
                    {
                        "kind": "extraction_blind_not_flagged",
                        "file": "tests/verifier.json",
                        "criterion": f"{c['group']}/{c['name']}",
                        "matched": matched,
                        "description": desc,
                        "commands": commands,
                        "note": (
                            "phrase matched a blind-property pattern, but at least one "
                            "recorded command for this criterion is formula-aware -- not "
                            "flagged as a defect, kept for audit visibility"
                        ),
                    }
                )
    return _finalize(result)


def _has_svc_pc_config(task_dir):
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return False
    return any(tests_dir.glob("deliverables*/judge.toml"))


def analyze_task(task_dir):
    """Format-dispatching wrapper, same precedence convention as every other dual-format check
    in this folder (rubric_schema_check.py's check_task_dispatch(), rubric_text_lint.py's
    analyze_task()): SVC-PC's judge.toml takes precedence whenever it exists."""
    if _has_svc_pc_config(task_dir):
        return check_task_svc_pc(task_dir)
    if has_ekw_config(task_dir):
        return check_task_ekw(task_dir)
    result = _new_result(task_dir.name)
    result["errors"].append(
        "no tests/deliverables*/judge.toml or tests/verifier.json found for this task"
    )
    return _finalize(result)


def find_task_dirs(root, task_ids=None, id_prefix=""):
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


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "task_ids",
        nargs="*",
        help="one or more task ids (directory names under --root)",
    )
    ap.add_argument(
        "--all", action="store_true", help="run every task directory found under --root"
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=None,
        required=False,
        help="root directory containing one subdirectory per task (REQUIRED -- no default)",
    )
    ap.add_argument(
        "--id-prefix",
        default="",
        help="when using --all, only treat subdirectories starting with this prefix as tasks",
    )
    ap.add_argument(
        "--out", type=Path, default=None, help="write the aggregate JSON report here"
    )
    args = ap.parse_args()

    if args.root is None:
        ap.error(
            "--root is required (point it at the directory containing your task folders)"
        )
    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")

    task_dirs = find_task_dirs(
        args.root, None if args.all else args.task_ids, id_prefix=args.id_prefix
    )
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        sys.exit(1)

    results = []
    for i, task_dir in enumerate(task_dirs, 1):
        print(f"[{i}/{len(task_dirs)}] {task_dir.name} ...", file=sys.stderr)
        try:
            r = analyze_task(task_dir)
        except Exception as e:  # never let one task's crash kill the whole batch
            r = _finalize(
                {
                    "task_id": task_dir.name,
                    "files_scanned": [],
                    "findings": [],
                    "errors": [f"unhandled exception analyzing this task: {e}"],
                }
            )
        results.append(r)
        confirmed = r["summary"]["by_kind"].get("extraction_blind_confirmed", 0)
        print(
            f"    -> {confirmed} confirmed finding(s)  ({len(r['errors'])} errors)",
            file=sys.stderr,
        )

    n_confirmed_total = sum(
        r["summary"]["by_kind"].get("extraction_blind_confirmed", 0) for r in results
    )
    n_clean = sum(
        1
        for r in results
        if r["summary"]["by_kind"].get("extraction_blind_confirmed", 0) == 0
    )
    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "n_tasks": len(results),
        "results": results,
    }

    print(
        f"\n{n_clean}/{len(results)} task(s) clean, {n_confirmed_total} confirmed finding(s)"
    )
    for r in results:
        kinds = ", ".join(
            f"{k}={v}" for k, v in r.get("summary", {}).get("by_kind", {}).items()
        )
        confirmed = r["summary"]["by_kind"].get("extraction_blind_confirmed", 0)
        status = "clean" if confirmed == 0 else "flagged"
        print(f"  {r['task_id']}: {status}" + (f"  [{kinds}]" if kinds else ""))
        for e in r.get("errors", []):
            print(f"      ! {e}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2)
        print(f"\nWrote {args.out}")

    return 1 if n_confirmed_total else 0


if __name__ == "__main__":
    raise SystemExit(main())
