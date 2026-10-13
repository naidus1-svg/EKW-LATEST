#!/usr/bin/env python3
"""Judge file-scope breadth check (taxonomy class A39): does the judge's own configured file
scope -- `judge.toml`'s `[judge].files=[...]` list (SVC-PC) or a verifier's own `source.file`
list (EKW) -- exclude source material the task's own prompt tells the solver to ground the
response in?

Why this exists, and why it is NOT extraction_groundedness_check.py's territory: that script
answers "within a file the judge IS configured to read, can the configured extraction command
see the property a criterion asks about" -- a DEPTH question. Its own module docstring names
the question this script answers as explicitly out of scope: "a criterion whose required
property lives in a file that is not in the judge's files=[...] / verifier file list at all --
that is a judge FILE-SCOPE problem (breadth: which files are in scope), not an extraction-
command problem." This script closes exactly that named gap (taxonomy entry A39: "judge.files=
[...] itself excludes files a criterion needs real context from").

Real, confirmed positive control: SVC-PC-92-0-0 (both C:/ekwqc/repo/pipeline/data/svc_pc_qc/
03_dataos_ready/SVC-PC-92-0-0 and the separately reconciled C:/b/_stage_0914_reconciled56/
SVC-PC-92-0-0 copy). instruction.md has a "Named corpus sources" section listing 16 exact local
files ("Local: Inventory_Policy.docx", "Local: Fulfillment_SOP.docx", ... all the way to
"Local: All_Hands_Week_52.docx") and states outright: "Use only the named local corpus files."
All 16 exist under environment/initial_workspace/. tests/deliverables/judge.toml's own
`[judge].files` is `["/app/Critical_Policy_Procedure_Lifecycle_Controls_Response.docx"]` --
the response document only. None of the 16 named source files are anywhere in that list, and
none of them exist under any other judge group either (there is only one group). Every one of
the task's 10 criteria (r01-r10, weights summing to 1.0) asks about facts that can only be
confirmed against that named source corpus -- "trial-window... conflicts," "stale dual-3PL SOP,"
"ten-SKU FAQ," "critical guidance population" -- and the judge never opens a single one of those
16 files. It only ever reads the response docx, so it can check whether the response'S OWN TEXT
is internally well-formed and cites plausible-sounding filenames, never whether those citations
are actually true. This is the manual-QC finding this script mechanizes: "judge can't see
sources, so fabrication can pass."

What it checks, per task, per judge group (SVC-PC: one group per tests/deliverables*/judge.toml,
since each such file carries its own independent `[judge].files` scope; EKW: one group per
verifier, since ekw_verifier_json.py's own docstring confirms EKW has no judge.toml-style shared
grouping -- each verifier already carries its own file list, so the per-verifier check IS the
per-criterion check for EKW, a finer grain than SVC-PC gets for free):

  1. Extracts every filename-shaped token (reusing criterion_groundedness_check.py's own
     FILENAME_RE rather than reinventing it -- same reuse convention that script's own docstring
     used against answer_key_content_leak_check.py) from instruction.md, EXCLUDING (a) anything
     inside a "## Graded deliverable filenames" section or a "Submit the graded deliverable(s)
     using..." sentence (the solver's own OUTPUT, not a source to ground against -- same
     directive-language convention deliverable_filename_check.py's REVERSE direction already
     recognizes), and (b) anything sitting within ~40 characters after an explicit negation cue
     ("do not use", "must not use", "excluding", ...) -- a task can legitimately name a file it
     tells the solver NOT to use (SVC-PC-92-0-0 itself does this for "System Exports... other
     task Goldens... responses, rubrics"), and that is the opposite of a required source.
  2. Keeps only the filenames that ALSO exist as real files under this task's own
     environment/initial_workspace/ (SVC-PC) or environment/data/ (EKW) -- reusing
     criterion_groundedness_check.py's own environment_signals() basename set. A filename named
     in prose that does NOT exist in the environment is a different, already-covered defect
     (environment_input_check.py's territory), not this script's.
  3. For each judge group, computes that group's own file scope as a lowercased basename set
     (SVC-PC: [judge].files, path-stripped; EKW: the verifier's own `files` list, already
     basename-relative per ekw_verifier_json.py). Two findings, in order of confidence:

     a. `judge_scope_zero_source_visibility` (HARD, gates the exit code) -- fires when this
        task names at least one real environment source file (step 1-2) AND this group's own
        scope contains ZERO overlap with the task's FULL environment file set (not just the
        specifically named ones -- checked against every environment file, so a group that
        legitimately sees some OTHER pre-existing source, e.g. a fill-in-place template sharing
        a name with an environment file, is not swept in as a false positive). This is the
        SVC-PC-92-0-0 shape: the judge sees only solver-produced output, nothing that pre-
        existed in the task's own corpus.
     b. `possible_judge_scope_excludes_named_sources` (SOFT, never gates) -- fires when this
        group's scope DOES overlap the environment (so (a) did not fire) but still excludes
        every one of the SPECIFICALLY named source files. Kept low-confidence and non-gating
        because a group seeing some other pre-existing file (a companion template, an earlier-
        stage draft) is a plausible legitimate reason the named list doesn't match verbatim, and
        this script cannot tell that apart from a genuine narrower-but-still-real breadth gap.
     c. `criterion_cites_out_of_scope_file` (HARD, gates the exit code) -- a different, sharper
        per-criterion signal, independent of (a)/(b): a criterion's OWN description text
        (not the whole prompt) names a filename (FILENAME_RE again) that exists in the
        environment corpus but is absent from THAT criterion's own group's scope. Higher
        confidence than (a)/(b) because the criterion itself, not just the task prompt, is
        making the citation -- there is no "maybe some other file covers it" ambiguity. Did NOT
        fire on SVC-PC-92-0-0's own r01-r10 (none of them cite a filename literally -- they are
        abstract fact descriptions, "stale dual-3PL SOP" not "per Fulfillment_SOP.docx"), so this
        is a genuinely complementary signal, not a restatement of (a); see Validation below for
        where it does fire on the real corpus.

  4. Reports, per group with a hard finding, `reward_at_risk_upper_bound`: the sum of that
     group's own criterion weights (SVC-PC: judge.toml's own `weight` field, re-parsed directly
     via tomllib rather than rubric_text_lint.load_judge_files, which drops weight entirely --
     see Provenance; EKW: metadata.weight, already surfaced by load_ekw_criteria). Named
     "upper bound" and not "confirmed reward earnable from filenames alone" deliberately: this
     script has no way to confirm every criterion in a zero-visibility group is actually
     source-dependent (some could legitimately grade only the response's own internal
     coherence, which a blind judge CAN assess honestly) -- it is the total weight that COULD be
     gamed by an unfaithful response in that group, not a claim that it WILL be. On
     SVC-PC-92-0-0 this number comes out to 1.0000 (all 10 criteria, one group, full task
     weight) -- consistent with, though not independently identical to, the "~0.80 of reward
     earnable from filenames alone" figure the taxonomy entry cites from a human manual-QC read
     (VM Gap 6), which is a narrower judgment call about which SPECIFIC criteria are gameable,
     not a claim this script reproduces criterion-by-criterion.

Provenance: dual-format pattern matches extraction_groundedness_check.py exactly (ekw_verifier_
json.py's load_ekw_criteria()/has_ekw_config() for EKW; tomllib + tests/deliverables*/judge.toml
for SVC-PC). SVC-PC parsing is NOT done via rubric_text_lint.load_judge_files (though that
function returns the right shape for files/criteria) because it drops each criterion's `weight`
field entirely, which this script needs for reward_at_risk_upper_bound -- re-parsing directly
with tomllib, mirroring criterion_groundedness_check.py's own check_task(), was simpler and more
honest than adding a weight-carrying side channel to a shared loader used by scripts that don't
need it. FILENAME_RE and environment_signals() ARE reused directly (imported from
criterion_groundedness_check.py), per that script's own "reused rather than reinvented"
convention.

Exit 0 clean (zero HARD findings across every task), 1 findings, 2 bad usage.

    python judge_file_scope_breadth_check.py <package_root> [--task TASK-ID] [--json out.json]

Known limits, disclosed rather than silently dropped -- READ THIS BEFORE TRUSTING A "clean"
RESULT, matching this folder's own precedent (answer_key_content_leak_check.py):
    - This is a NAMED-FILENAME-LITERAL check, not a semantic one. A task that tells the solver
      "assess the current guidance environment" and separately lists its source files by name
      (SVC-PC-92-0-0's actual shape) is caught. A task that describes its required source
      material only in prose with NO literal filename anywhere in instruction.md ("read the
      attached policy documents") is invisible to this check -- it has nothing to extract, so it
      reports zero named_source_files and makes no claim either way. This is a real, disclosed
      coverage gap, not a hidden one; it is why every result also reports named_source_files so
      a human can see when the check had nothing to work with, distinct from a genuine clean
      pass.
    - `judge_scope_zero_source_visibility` is checked against the task's FULL environment file
      set, not just the named subset, specifically to avoid one false-positive shape (a group
      legitimately reading a pre-existing companion/template file that happens not to be in the
      literal named list). It cannot rule out a SECOND false-positive shape this design does not
      defend against: a group whose in-scope file is a pre-existing environment file that is
      NOT actually the relevant source for that group's own criteria (e.g. one stray boilerplate
      template shared across many unrelated tasks) -- this would wrongly suppress a real finding
      by looking like "some overlap exists," not wrongly create one. Disclosed as an
      under-flagging risk, not an over-flagging one.
    - The negation guard (a named file preceded by "do not use" etc. within 40 characters) is a
      fixed phrase list, not a parse of the sentence's actual grammar -- a differently-worded
      exclusion this script's phrase list doesn't recognize would wrongly count an explicitly
      forbidden file as a required source, which would only ever make a finding's severity read
      as somewhat larger than it is (the file is still absent from scope either way), never
      fabricate a finding that wouldn't otherwise exist.
    - `criterion_cites_out_of_scope_file` matches a filename against the CRITERION'S OWN group
      scope only. For SVC-PC, a multi-group task where criterion X's own group doesn't carry a
      file that a DIFFERENT group in the same task does, is correctly flagged (that group's own
      judge genuinely cannot open it) -- this is not a false positive, even though "some judge
      somewhere in the task sees it" might read as close enough at a glance.
    - reward_at_risk_upper_bound sums weights straight from judge.toml/verifier.json without
      re-validating that they actually sum to 1.0 across the whole task (rubric_schema_check.py's
      job, not this script's) -- a task with a malformed weight sum would produce a
      correspondingly malformed upper bound, not a crash.
    - Like every text-pattern check in this folder, this reads instruction.md and the config
      files only; it does not open the deliverable itself to see whether a real response for
      this task actually exploited the gap. It answers "can this be gamed," not "was it."

Validation against real data (2026-09-14/15 session; nothing under either path was modified --
this script only reads):

  Positive control: SVC-PC-92-0-0, read from BOTH copies present on disk tonight --
  C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready/SVC-PC-92-0-0 (the full 609-task corpus)
  and C:/b/_stage_0914_reconciled56/SVC-PC-92-0-0 (a separately reconciled 56-task population) --
  both flagged `judge_scope_zero_source_visibility` on its one judge group, 16/16 named source
  files excluded, reward_at_risk_upper_bound 1.0000. See this script's own CLI output (run
  directly against each path) for the exact per-run numbers; not hardcoded here so this
  docstring can't go stale against a corpus that gets re-staged under the same names.

  Corpus-wide false-positive counts (SVC-PC: all 609 tasks under 03_dataos_ready; EKW: all 274
  tasks under C:/ekwqc/_merged274/files) are deliberately NOT hardcoded in this docstring either
  -- see this script's own accompanying report for the actual run, so the numbers can't drift out
  of sync with the code that produced them.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from criterion_groundedness_check import FILENAME_RE, environment_signals
from ekw_verifier_json import has_ekw_config, load_ekw_criteria

# ---------------------------------------------------------------------------
# instruction.md: named-source-filename extraction
# ---------------------------------------------------------------------------

# A "## Graded deliverable filenames" heading (deliverable_filename_check.py's own confirmed
# real convention on this corpus) or a "Submit the graded deliverable(s) using..." directive
# sentence with no heading at all -- both mark the start of the OUTPUT-naming section, not
# source material. Everything from the first match to the end of instruction.md is excluded
# from source-filename extraction.
DELIVERABLE_MARKER_RE = re.compile(
    r"##?\s*Graded deliverable filenames|Submit the graded deliverables?\s+using",
    re.IGNORECASE,
)

# A filename immediately preceded (within NEGATION_WINDOW chars) by one of these phrases is
# named as something the solver must NOT use, not a required source -- SVC-PC-92-0-0's own
# instruction.md does exactly this ("Do not use System Exports, other task Goldens, responses,
# rubrics, unsupported inputs, or unnamed sibling files"). A fixed phrase list, not a grammar
# parse -- see module docstring's Known limits for the direction of error this can produce.
NEGATION_CUE_RE = re.compile(
    r"\b(?:do not use|must not use|never use|excluding|not use|do not read|"
    r"forbidden|off[- ]?limits|do not reference)\b",
    re.IGNORECASE,
)
NEGATION_WINDOW = 40


def _split_deliverable_section(text: str) -> str:
    """instruction.md text with everything from the first 'Graded deliverable filenames'-style
    marker onward stripped off -- filenames named only in that trailing section are the
    solver's own required OUTPUT, not source material to check judge-scope breadth against.
    """
    m = DELIVERABLE_MARKER_RE.search(text)
    return text if not m else text[: m.start()]


def _instruction_named_filenames(instr_text: str) -> set[str]:
    """Every filename-shaped token (FILENAME_RE) in instruction.md's source-facing body
    (deliverable-naming section stripped, negated mentions excluded), lowercased. Does NOT
    check existence against the environment -- callers intersect with environment_signals()'s
    basenames separately, matching criterion_groundedness_check.py's own two-step convention
    (extract text-shaped facts first, confirm environment presence second)."""
    body = _split_deliverable_section(instr_text)
    out: set[str] = set()
    for m in FILENAME_RE.finditer(body):
        window = body[max(0, m.start() - NEGATION_WINDOW) : m.start()]
        if NEGATION_CUE_RE.search(window):
            continue
        out.add(m.group(0).lower())
    return out


def _basename(p) -> str:
    return Path(str(p).replace("\\", "/")).name.lower()


def _load_instruction(task_dir: Path) -> str | None:
    p = task_dir / "instruction.md"
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# SVC-PC: judge.toml, parsed directly (weight-preserving -- see module docstring Provenance)
# ---------------------------------------------------------------------------


def _load_svc_pc_groups(task_dir: Path):
    """Every tests/deliverables*/judge.toml under a task dir, parsed directly via tomllib.
    Returns a list of {path, files, criteria: [{name, description, weight}], parse_error}.
    Deliberately NOT rubric_text_lint.load_judge_files -- see module docstring Provenance for
    why this script needs its own copy (weight preservation)."""
    out = []
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return out
    for jt in sorted(tests_dir.glob("deliverables*/judge.toml")):
        rel = str(jt.relative_to(task_dir)).replace("\\", "/")
        try:
            data = tomllib.loads(jt.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 -- never let one bad file kill the batch
            out.append(
                {"path": rel, "files": [], "criteria": [], "parse_error": str(e)}
            )
            continue
        judge = data.get("judge") or {}
        files = judge.get("files") or []
        criteria = [
            {
                "name": c.get("name"),
                "description": c.get("description") or "",
                "weight": c.get("weight"),
            }
            for c in data.get("criterion") or []
        ]
        out.append(
            {"path": rel, "files": files, "criteria": criteria, "parse_error": None}
        )
    return out


def _has_svc_pc_config(task_dir: Path) -> bool:
    tests_dir = task_dir / "tests"
    return tests_dir.is_dir() and any(tests_dir.glob("deliverables*/judge.toml"))


# ---------------------------------------------------------------------------
# shared per-group analysis (both formats funnel through this one function, so SVC-PC and EKW
# can never silently apply different rules -- same convention extraction_groundedness_check.py's
# _find_blind_matches() uses)
# ---------------------------------------------------------------------------


def _weight_sum(criteria) -> float:
    total = 0.0
    for c in criteria:
        w = c.get("weight")
        if isinstance(w, (int, float)):
            total += w
    return round(total, 4)


def _analyze_group(
    res, group_label, group_files, criteria, env_basenames, named_sources
):
    scope = {_basename(f) for f in group_files if f}
    scope_env_overlap = scope & env_basenames
    scope_named_overlap = scope & named_sources

    if named_sources and not scope_env_overlap:
        res["findings"].append(
            {
                "kind": "judge_scope_zero_source_visibility",
                "group": group_label,
                "judge_files": sorted(scope),
                "named_source_files_excluded": sorted(named_sources),
                "n_criteria_in_group": len(criteria),
                "reward_at_risk_upper_bound": _weight_sum(criteria),
                "reason": (
                    f"instruction.md names {len(named_sources)} source file(s) confirmed to "
                    "exist under this task's environment corpus, but every file in this judge "
                    "group's own files=[...] scope is solver-produced output -- zero overlap "
                    "with ANY pre-existing environment file, not just the named ones. This "
                    "judge can never read a single source file; it can only check the "
                    "response's own internal claims."
                ),
            }
        )
    elif named_sources and scope_env_overlap and not scope_named_overlap:
        res["possible_findings"].append(
            {
                "kind": "possible_judge_scope_excludes_named_sources",
                "group": group_label,
                "judge_files": sorted(scope),
                "named_source_files_excluded": sorted(named_sources),
                "reason": (
                    "this judge group's files=[...] includes at least one pre-existing "
                    "environment file, but none of the SPECIFIC file(s) instruction.md names "
                    "as the source set -- possible narrower breadth gap, not hard-flagged: the "
                    "file(s) actually in scope may legitimately be the relevant ones despite "
                    "not matching the named list verbatim (e.g. a companion template)."
                ),
            }
        )

    for c in criteria:
        desc = c.get("description") or ""
        cited = {m.group(0).lower() for m in FILENAME_RE.finditer(desc)}
        missing = (cited & env_basenames) - scope
        for fn in sorted(missing):
            res["findings"].append(
                {
                    "kind": "criterion_cites_out_of_scope_file",
                    "group": group_label,
                    "criterion": c.get("name"),
                    "file": fn,
                    "reason": (
                        f"criterion '{c.get('name')}' names '{fn}' directly in its own "
                        "description; that file exists in this task's environment corpus, but "
                        "is absent from this judge group's own files=[...] scope -- the judge "
                        "cannot open the exact file the criterion is asking about."
                    ),
                }
            )


def _base_result(task_dir: Path, fmt: str) -> dict:
    return {
        "task": task_dir.name,
        "format": fmt,
        "groups_checked": 0,
        "named_source_files": [],
        "findings": [],
        "possible_findings": [],
        "parse_errors": [],
        "ok": False,
    }


def check_task_svc_pc(task_dir: Path) -> dict:
    res = _base_result(task_dir, "svc_pc")
    instr_text = _load_instruction(task_dir)
    if instr_text is None:
        res["parse_errors"].append("no instruction.md")
        return res

    _floats, _blob, env_basenames, _instr_text = environment_signals(
        task_dir, ekw=False
    )
    named_sources = _instruction_named_filenames(instr_text) & env_basenames
    res["named_source_files"] = sorted(named_sources)

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
        _analyze_group(
            res, g["path"], g["files"], g["criteria"], env_basenames, named_sources
        )

    res["ok"] = not res["findings"] and not res["parse_errors"]
    return res


def check_task_ekw(task_dir: Path) -> dict:
    """EKW: each verifier is its own group (no judge.toml-style shared scope exists --
    ekw_verifier_json.py's own docstring confirms this), so the per-group check above IS the
    per-criterion check here, one call per verifier."""
    res = _base_result(task_dir, "ekw")
    instr_text = _load_instruction(task_dir)
    if instr_text is None:
        res["parse_errors"].append("no instruction.md")
        return res

    _floats, _blob, env_basenames, _instr_text = environment_signals(task_dir, ekw=True)
    named_sources = _instruction_named_filenames(instr_text) & env_basenames
    res["named_source_files"] = sorted(named_sources)

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
        _analyze_group(
            res, c["group"], c.get("files") or [], [c], env_basenames, named_sources
        )

    res["ok"] = not res["findings"] and not res["parse_errors"]
    return res


def check_task_dispatch(task_dir: Path) -> dict:
    """SVC-PC takes precedence when both configs exist, matching every other dual-format check
    in this folder."""
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
# CLI -- same shape as criterion_groundedness_check.py's main()
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
    n_possible_only = sum(1 for r in results if r["ok"] and r["possible_findings"])
    n_named_source_tasks = sum(1 for r in results if r["named_source_files"])
    total_reward_at_risk = sum(
        f["reward_at_risk_upper_bound"]
        for r in results
        for f in r["findings"]
        if f["kind"] == "judge_scope_zero_source_visibility"
    )

    for r in results:
        flag = "OK  " if r["ok"] else "FAIL"
        print(
            f"{flag} {r['task']:<20} [{r['format']:<6}] "
            f"{r['groups_checked']:>3} group(s)  "
            f"{len(r['named_source_files']):>2} named-source(s)  "
            f"{len(r['findings']):>2} findings  {len(r['possible_findings']):>2} possible"
        )
        for w in r["parse_errors"]:
            print(f"       parse: {w}")
        for f in r["findings"]:
            if f["kind"] == "judge_scope_zero_source_visibility":
                print(
                    f"       ZERO_VISIBILITY [{f['group']}]: judge sees only "
                    f"{f['judge_files']}, excludes {len(f['named_source_files_excluded'])} "
                    f"named source(s), reward_at_risk_upper_bound={f['reward_at_risk_upper_bound']}"
                )
            else:
                print(
                    f"       OUT_OF_SCOPE [{f['group']}/{f['criterion']}]: cites {f['file']!r}"
                )
        for f in r["possible_findings"]:
            print(
                f"       possible [{f['group']}]: excludes "
                f"{f['named_source_files_excluded']} (partial overlap, not hard-flagged)"
            )

    print(
        f"\n{len(results) - len(bad)}/{len(results)} clean "
        f"({n_possible_only} of those carry only possible findings, non-blocking), "
        f"{len(bad)} FAIL  |  {n_named_source_tasks}/{len(results)} tasks had >=1 named source "
        f"file to check against  |  total reward_at_risk_upper_bound across all "
        f"zero-visibility findings: {round(total_reward_at_risk, 4)}"
    )
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
