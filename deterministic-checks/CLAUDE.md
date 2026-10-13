# EKW Sprint — Working With This Pipeline

Context for Claude (and for any human reading over its shoulder) when the working directory is
this folder, or a task corpus being run against it. Sprint goal: 200 EKW tasks accepted in
DataOS by tomorrow, 1000 within two weeks. "Accepted" means passed DataOS's Manual QC /
Comprehensive Review — everything in this file is in service of getting a task there by the
fastest reliable path, not of running every script for its own sake.

Read `README.md` in this folder for what each check actually does. This file is about how to
use them on this sprint, not a repeat of that catalog.

## Setup

This pipeline lives on `feature/deterministic-checks-external-review-coverage`, not `main` yet.

```bash
git fetch origin
git checkout feature/deterministic-checks-external-review-coverage
cd deterministic-checks
```

Requires **Python 3.11+** — `rubric_schema_check.py`, `judge_panel_size_check.py`,
`criterion_condition_count_check.py`, `invention_detection_input_check.py`,
`golden_dependency_reachability_check.py`, and `run_all.py` itself all import `tomllib`
(stdlib-only from 3.11 on) and print a clear error and exit if run under an older interpreter —
if you hit that, switch to `python3.11`/`python3.12` or the repo's `pipeline/.venv`, don't try to
patch around it.

## The one command to run

```bash
python3.11 run_all.py --all --root <path to your claimed task folders> --out-dir results/
```

or with an explicit list instead of `--all`. This drives every applicable check in this folder
in one pass and writes `results/summary.json` + one raw report per check. Don't invoke the
individual check scripts by hand unless you're debugging one specific finding — `run_all.py`
already knows each script's CLI quirks (some take `--all`/task ids, `rubric_schema_check.py`
takes a positional root instead, `duplicate_criterion_check.py` has no per-task concept at all)
so you don't have to.

**Autofix before you read anything.** Most of what blocks a task is a stale/blank spreadsheet
formula cache, and there's a verified, safe autofixer for exactly that:

```bash
python3.11 formula_cache_autofix.py <task-id> --root <path> --dry-run --out report.json   # see what it WOULD do
python3.11 formula_cache_autofix.py <task-id> --root <path> --out report.json             # apply (backs up to <file>.orig first)
```

Run this, then re-run `run_all.py`, before triaging findings by hand. It only ever writes a
cell's own freshly-recomputed value into its own cache — never touches formula logic, never
invents a number.

## Hard rules for any fix, automated or not

These are non-negotiable, not style preferences:

- **Never invent a fact, number, or filename.** If closing a finding requires data that isn't
  already derivable from the task's own files, that's a `needs_source_data` escalation, not a
  guess. Putting an invented value in front of a grader is a rule violation, not a shortcut.
- **Mechanical fix vs. policy decision are different lanes.** A stale formula cache is
  mechanical — fix it. Deciding which additional judge model to add to a panel, or how to
  reweight a split rubric criterion, is a policy/authoring call — escalate it, don't guess at it.
- **Verify a finding against the actual task files before acting on it.** Every check here is
  either brand-new (v1, uncalibrated — see the file list below) or has already shown real
  false-positive classes on this exact corpus (see "Known false positives" below). Reading the
  check's own JSON report is not the same as reading the task.
- **If a finding looks wrong, don't silently work around it in one task.** Fix the check (or
  flag it in the team channel so someone does) so the same false positive doesn't cost the next
  30 people the same investigation. Three false-positive classes have already been fixed this
  week this exact way — see below.
- **Commit as you go**, one task/one fix per commit, with a message that says what was wrong and
  why the fix is correct — not "fix task_X". Someone else will need to understand your commit
  without re-deriving your reasoning.

## The four "systemic" findings are per-task work (reversed 2026-09-18)

Until 2026-09-18 this section told you to skip `judge_determinism_config_lint`, `judge_panel_size_check`,
`criterion_condition_count_check` and `invention_detection_input_check` as corpus-level policy. The expert
reward-signal review of QCR_EKW_16092026 (48 findings, 12/12 tasks) showed that **three of its top mechanisms
are exactly these four**: a fabrication/traceability criterion graded from one file cannot be decided (false
fails on correct work, false passes on fabrication); a single judge sample flips verdicts on identical bytes;
a compound criterion zeroes a correct answer over a decorative sub-clause. Policy now:

- **Judge samples:** `config.models` lists the judge model **three times** (majority of 3). Per task, in
  `verifier.json`. `reward_signal_gate.py` G9 fails otherwise.
- **Single-file source on a fidelity/traceability/consistency/status criterion:** re-source with
  `filesystem.extract_many` over the deliverable plus the named source file(s), or narrow the prompt to what
  one file can show. G1 fails otherwise (or on an undispositioned candidate).
- **Compound criteria:** split so the decisive fact carries the weight; G7 candidates need a disposition.
- `judge_determinism_config_lint` (temperature) stays a corpus decision — temperature 1.0 is required by the
  judge model; the majority-of-3 is the determinism fix.

All four are enforced by `reward_signal_gate.py` (wired into `pre_submit_gate.py`); see its docstring for the
disposition format in `reports/<task>_TRACE.json`.

## Format note: this corpus is `verifier.json`, not `judge.toml`

Several checks here were built against SVC-PC's `judge.toml` rubric format and correctly report
`not_applicable` / "no rubric files found" on EKW's `verifier.json`-shaped tasks:
`rubric_schema_check.py`, `judge_criterion_name_duplicate_check.py`, `rubric_text_lint.py`,
`duplicate_criterion_check.py` (xlsx-rubric only). **That's expected, not a bug** — don't log it
as a task defect, and don't mark those columns "failed" in the tracker.

## Known false positives already fixed on this corpus — don't rediscover these

- `environment_input_check.py` / `answer_key_content_leak_check.py` used to look for
  `environment/initial_workspace/`; this corpus ships `environment/data/`. Fixed — both now try
  both names plus a single-subdirectory fallback.
- `answer_key_leakage_check.py` used to flag any `*_reference.*` filename as a leaked answer key.
  A `_REFERENCE` lookup table (e.g. a denial-code crosswalk the solver is required to consult)
  is legitimate; only `_REFERENCE` compounded with ANSWER/SOLUTION/GOLDEN/KEY is a real tell now.
- `golden_dependency_reachability_check.py` used to parse plain-English "a.m."/"p.m." time
  phrases as unreachable `.m` (MATLAB) script references. Fixed with a narrow exclusion.

If you hit a NEW false-positive class, follow the same pattern: reproduce it, find the root
cause by reading the code, fix with the smallest correct change, re-verify against the task that
exposed it AND at least one other already-passing task (no regression), commit with a message
that names the false-positive class.

## Tracker mapping (Check A–H columns)

| Column | Source |
|---|---|
| A – Content audit | Not scripted — needs a human/LLM read. Leave as-is unless told otherwise. |
| B – Build success | Trivial pass if the package is already downloaded/intact. |
| C – Structural audit | `environment_input_check.py`, `answer_key_leakage_check.py`, `deliverable_count_check.py` |
| D – Mechanical sub-check | `deliverable_filename_check.py`, `deliverable_integrity_check.py`, `tab_naming_check.py`, `answer_key_content_leak_check.py`, `judge_panel_size_check.py`, `criterion_condition_count_check.py`, `invention_detection_input_check.py`, `golden_dependency_reachability_check.py` |
| E – Formula health | `formula_health_check.py` + `formula_cache_autofix.py` |
| F – Oracle | DataOS-side, not local |
| G – Manual QC / Comprehensive Review | DataOS-side, not local — this is the actual finish line |
| H – Tracker write-back | Confirm the row actually saved |

## Workflow discipline

1. Claim task(s) in the tracker before touching them — don't duplicate someone else's work.
2. `run_all.py --all` on your claimed batch.
3. `formula_cache_autofix.py` (dry-run, then apply) before reading findings by hand.
4. `run_all.py` again to confirm the clean-up landed.
5. Triage what's left: the four formerly-"systemic" findings are per-task work now (see above) —
   resolve them like any other; verify everything against the real task files, escalate anything needing source data or a policy call instead of guessing.
6. Update the tracker's per-check columns and Note.
7. Push the task into DataOS. Local-clean is not the finish line — passing Comprehensive Review is.

## Further reading

- `README.md` — full capability table, what each check catches, honest maturity labels.
- `QC-REVIEW-8x-COVERAGE.md` — the external-review remediation list this batch of checks came
  from, and which items are pipeline fixes vs. task-authoring fixes vs. out of scope.
- `GAP-ANALYSIS.md` — what a comprehensive pre-grading framework is still missing.
- `BUILD-CONTRACT.md` — the package shape every check assumes.
