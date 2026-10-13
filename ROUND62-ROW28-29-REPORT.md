# Round 62, rows 28-29: automated structural-audit LLM-judge check

Builds an automated LLM-judge check (`structural_audit_check.py`) that applies the
six structural-defect patterns from the manual "structural audit" methodology
(`deterministic-checks/structural-audit/SKILL.md`), and wires it into both
orchestrators so it runs automatically in the normal process, not only when a
human remembers to do a manual pass.

The two motivating defects (rows 28-29) passed every existing deterministic +
LLM check with zero fail/error. This check flags both, for real, with real LLM
calls against the real corpus.

## What was built

### `deterministic-checks/structural_audit_check.py` (new)

Modeled on `rubric_overspecification_check.py` and `golden_groundedness_check.py`
(the two existing LLM-judge checks in this folder). Reuses the same shared
helpers those checks use, so the inputs it sends to the LLM are byte-identical
to what every other calibrated check already reads:

- `tools/llm_backend.call_llm()` (the shared backend; carries the
  `LLM_API_MAX_TOKENS=32000` setdefault fix for the row-15 reasoning-model
  starvation bug)
- `answer_key_rubric_leak_check.load_criteria_for_task` (format-dispatching
  criteria loader: SVC-PC `judge.toml` + EKW `verifier.json`)
- `answer_key_rubric_leak_check.find_golden_files`, `extract_file_text`
- `deliverable_filename_check.load_deliverable_files` (format-dispatching
  `files=` loader) plus `basename`, `_load_solution_files`,
  `_is_readscope_source` (splits each `files=` entry into a solver-produced
  deliverable vs a judge read-scope source)
- `answer_key_content_leak_check.find_environment_files` (format-dispatching:
  SVC-PC `environment/initial_workspace/`, EKW `environment/data/`)

Per task, the LLM receives:

1. `instruction.md` full text, with 1-based line numbers (so it can cite the
   two disagreeing sections by line, the row-28 case)
2. the `judge.toml` `files=` list, split into DELIVERABLES the solver must
   produce vs READ-SCOPE sources the judge reads as context (pattern 2 only
   compares against deliverables, not read-scope context files)
3. the `judge.toml` criteria (name + description), for pattern 5 cross-check
   (a criterion that expects a specific count/format the instruction never
   states)
4. an environment file manifest: directly-staged files, corpus-subtree
   subfolder summary, a flat searchable basename list, and placeholder-marker
   detection (for patterns 1 and 3)

The LLM applies the six patterns and returns strict JSON: a `verdict` plus a
`findings` list, each carrying a `pattern` (1-6), a verbatim
`instruction_quote` (with line number), a `judge_quote` if relevant, an
`environment_note` if relevant, and a short `evidence` sentence. Severity is
always `warn` (the "candidate, not verdict" posture every LLM check in this
project uses); a finding never hard-gates a task.

### The six patterns (as encoded in the prompt)

1. `placeholder_env_vs_named_files`: environment is a placeholder/generic
   description while instruction.md names specific required files that are not
   present anywhere.
2. `deliverable_filename_mismatch`: instruction.md names a deliverable filename
   that does not match what `judge.toml` `files=` reads. Two shapes: (a)
   instruction says X, judge reads Y; (b) the narrower row-28 case where
   instruction.md names the SAME deliverable two different ways in two
   different sections (e.g. with vs without an `L2-03_` prefix) and
   `judge.toml` reads only one of the two names.
3. `unhydrated_drive_dependency`: instruction.md points to a live cloud-storage
   URL that is never staged into the solver-visible environment.
4. `golden_or_pipeline_leak_in_prompt`: GOLDEN / internal-pipeline text
   leaked into the solver-facing instruction.md (a `GOLDEN` filename the
   solver is told to produce, or raw build-system / node-identifier text).
5. `unstated_deliverable_count_or_format`: instruction.md promises or implies a
   count/format but never actually gives it, while a judge criterion requires
   a specific count/format. The row-29 case: an "Assigned corpus files"
   heading promises a list, jumps to the next section with zero items given,
   while a must-pass criterion requires "six assigned files".
6. `internal_contradiction_in_instruction`: instruction.md contradicts itself
   on a requirement, filename, count, scope, or deliverable shape.

### Orchestrator registration

Registered under **letter C** in both `deterministic-checks/svc_run_checks.py`
(`CHECKS["structural_audit"]`, `LETTERS = ("C","D","E")`) and
`deterministic-checks/ekw/ekw_run_checks.py` (`CHECKS["structural_audit"]`,
`LETTERS = ("B","C","D","E")`). Letter legends in both header docstrings updated.

**Letter choice: C, not A.** The brief said "under the LLM-judge group (check
A)" but also said "do not assume A is correct without checking." Checking
settles it: `LETTERS` on the SVC runner is `("C","D","E")` and registering
"A" would `KeyError` in `merge()`'s `by_letter = {L: [] for L in LETTERS}` on
the first task processed (confirmed by reading `merge()` directly, svc_run_checks
line 1279 / ekw_run_checks line 1188, not assumed). The letter tracks the defect
class, not the method: `rubric_overspecification` is LLM-based but sits at D
(mechanical/rubric class); `golden_groundedness` is LLM-based but sits at E
(formula health). These six patterns are structural defects (instruction.md
vs the real `judge.toml` `files=` vs the real environment listing), the same
defect class as the deterministic C checks (`environment_input`,
`deliverable_count`, `answer_key_leakage`). Letter C is the correct fit; this
is the LLM-judge analog of those deterministic structural checks.
`content-audit/SKILL.md` is the pipeline's "Check A" by tracker column but has
no CLI and no `CHECKS` entry (documented in svc_run_checks.py lines 73-77);
this check ships the CLI the structural patterns need to run automatically.

## Verification: acceptance test (two known defects), real LLM calls

Command (real calls, not dry-run, against the live SVC-PC corpus at
`C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready`):

```
LLM_BACKEND_FORCE=http python structural_audit_check.py \
  SVC-PC-72-3-0 SVC-PC-82-2-0 \
  --root C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready \
  --jobs 2 --timeout 300 --out acceptance.json
```

Real output:

```
  WARN  SVC-PC-72-3-0      1 finding(s): p2/deliverable_filename_mismatch
  WARN  SVC-PC-82-2-0      1 finding(s): p5/unstated_deliverable_count_or_format

2 tasks in 34.8s: 0 pass, 2 warn, 0 skip, 0 error
```

Both flagged with the correct pattern and real evidence citing the exact text:

**SVC-PC-72-3-0 (row 28) -> pattern 2 (deliverable_filename_mismatch):**
- instruction_quote: `line 17: Unit_Economics_Guardrail_Accuracy_Workpaper.docx`
- judge_quote: `/app/L2-03_Unit_Economics_Guardrail_Accuracy_Workpaper.docx`
- evidence: "instruction.md names the same deliverable two different ways:
  line 17 names it 'Unit_Economics_Guardrail_Accuracy_Workpaper.docx' (without
  the L2-03_ prefix) while line 23 names it
  'L2-03_Unit_Economics_Guardrail_Accuracy_Workpaper.docx' (with the prefix).
  judge.toml files= reads only the prefixed name; an agent following line 17's
  Deliverable section would produce the unprefixed file and score 0 silently."

**SVC-PC-82-2-0 (row 29) -> pattern 5 (unstated_deliverable_count_or_format):**
- instruction_quote: `line 14: Assigned corpus files` / `line 15: Use only these
  files from the current Cirrus corpus...`
- judge_quote: `[deliverables/l2-02-r09] States that the package uses only the
  assigned six corpus files... Expected: Six assigned files only.`
- evidence: "The 'Assigned corpus files' section promises a list but provides
  zero items before 'Boundaries' begins at line 17. Rubric criterion r09 expects
  the solver to state 'six assigned files,' a specific count the instruction
  never enumerates."

Both acceptance cases pass: the check flags the real defect, on the right
pattern, with a verbatim quote of the real text.

## Verification: broader real sample (28 tasks)

A spread of 28 tasks (the 2 known defects plus 26 sampled every ~23rd from the
600-task corpus), real LLM calls, 4 parallel workers:

```
LLM_BACKEND_FORCE=http python structural_audit_check.py <28 ids> \
  --root C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready \
  --jobs 4 --timeout 300 --out sample28.json
```

Real output:

```
28 tasks in 145.7s: 19 pass, 9 warn, 0 skip, 0 error
```

Task-id list (28): SVC-PC-72-3-0, SVC-PC-82-2-0, SVC-PC-1-0-0, SVC-PC-12-6-0,
SVC-PC-16-2-0, SVC-PC-19-5-0, SVC-PC-21-3-0, SVC-PC-25-5-0, SVC-PC-29-6-0,
SVC-PC-33-4-0, SVC-PC-37-5-0, SVC-PC-40-4-0, SVC-PC-43-3-0, SVC-PC-46-4-0,
SVC-PC-49-5-0, SVC-PC-51-3-0, SVC-PC-54-2-0, SVC-PC-57-3-0, SVC-PC-6-2-0,
SVC-PC-62-3-0, SVC-PC-66-4-0, SVC-PC-69-5-0, SVC-PC-71-3-0, SVC-PC-76-0-0,
SVC-PC-78-8-0, SVC-PC-81-1-0, SVC-PC-9-3-0, SVC-PC-93-0-0.

9 warnings (pattern / task):

| task | pattern | pattern_name |
|---|---|---|
| SVC-PC-72-3-0 | 2 | deliverable_filename_mismatch (known, row 28) |
| SVC-PC-82-2-0 | 5 | unstated_deliverable_count_or_format (known, row 29) |
| SVC-PC-1-0-0 | 2 | deliverable_filename_mismatch |
| SVC-PC-16-2-0 | 4 | golden_or_pipeline_leak_in_prompt |
| SVC-PC-19-5-0 | 2 | deliverable_filename_mismatch |
| SVC-PC-33-4-0 | 1 | placeholder_env_vs_named_files |
| SVC-PC-46-4-0 | 2 | deliverable_filename_mismatch |
| SVC-PC-49-5-0 | 5 | unstated_deliverable_count_or_format |
| SVC-PC-6-2-0 | 5 | unstated_deliverable_count_or_format |

### False-positive spot-check (all 7 new flags checked against the real files)

Each new flag was checked against the real instruction.md / judge.toml /
environment files:

| task | flag | spot-check verdict | evidence |
|---|---|---|---|
| SVC-PC-1-0-0 | p2 | FALSE POSITIVE | LLM claimed instruction.md line 22 says `Fpa_Model` (title-case) while judge reads `FPA_Model`. Real instruction.md says `FPA_Model` (all-caps); real judge.toml also reads `FPA_Model`. Both agree; the LLM misread the case. |
| SVC-PC-16-2-0 | p4 | TRUE POSITIVE | instruction.md line 1 is literally `# L2-02 - Prompt` (a node identifier + pipeline stage label). Rubric r021 confirms node identifiers are eval-only vocabulary. Real pipeline-scaffolding leak into the solver-facing prompt. |
| SVC-PC-19-5-0 | p2 | TRUE POSITIVE | instruction.md line 16 commands `Processor_Economics_Settlement_Memo.docx`; criterion f01 (must-pass) expects it present. But the top-level `[judge].files` in all four deliverables groups lists only the `.xlsx` Reconciliation_Map, never the `.docx` memo. The grader's read-scope omits a commanded deliverable. |
| SVC-PC-33-4-0 | p1 | TRUE POSITIVE | instruction.md says "We hold customer records in three places. Shopify, HubSpot... Go to all three." A recursive `find` for `*hubspot*` and `contacts_export` under the environment returns nothing; the corpus subtree has `System Exports - 2021Q4__shopify` but no hubspot folder. Rubric criteria expect HubSpot figures; the HubSpot data is genuinely not staged. |
| SVC-PC-46-4-0 | p2 | TRUE POSITIVE | instruction.md line 3 (Prompt body) says "Produce Engineering_Ownership_and_Handoff_Analysis.xlsx" (no prefix); the "Graded deliverable filenames" section says `L2-04_Engineering_Ownership_and_Handoff_Analysis.xlsx` (with prefix); judge reads only the prefixed form. Same defect class as row 28. |
| SVC-PC-49-5-0 | p5 | TRUE POSITIVE | `grep -i src` in instruction.md returns nothing; must-pass criterion c-035 requires source inputs on `SRC_`-prefixed tabs. The instruction never states the tab-naming convention a must-pass criterion requires. |
| SVC-PC-6-2-0 | p5 | TRUE POSITIVE | instruction.md line 9 says "Work from the data-room files listed under Inputs" but no Inputs section or file list appears anywhere; criterion r50b requires "four named data-room files," a specific count the instruction never enumerates. Same defect class as row 29. |

Tally on the flagged set: 8 true positives, 1 false positive out of 9 flags.
The one false positive (SVC-PC-1-0-0) is an LLM case-misread (`FPA` read as
`Fpa`), a known LLM weakness on case sensitivity. This is a disclosed,
reproducible false-positive class, not a structural flaw in the check's
design: the prompt explicitly asks for verbatim quotes, and a reviewer
spot-checking the quote against the real file (as the CLAUDE.md hard rule
requires for every check's findings) catches it in seconds.

The 19 "clean" tasks were not individually re-audited by hand, so a
false-negative rate on the clean set is not measured here (no labeled
ground-truth set exists for the 600-task corpus). The acceptance bar was
"flag both known defects + spot-check new flags for false-positive rate";
that bar is met.

## Verification: EKW format (real, not untested)

The brief said to write the EKW registration and mark it EKW-UNTESTED if no EKW
corpus was reachable. A real EKW corpus IS reachable at
`C:/ekwqc/_merged274/files` (task_1, task_15, ...) with the
`instruction.md` + `environment/data/` + `tests/verifier.json` shape. The
check's helpers are format-dispatching, so it runs on EKW directly:

```
LLM_BACKEND_FORCE=http python structural_audit_check.py task_1 task_15 \
  --root C:/ekwqc/_merged274/files --jobs 2 --timeout 300 --out ekw2.json
```

Real output:

```
  OK    task_1             clean
  OK    task_15            clean

2 tasks in 23.5s: 2 pass, 0 warn, 0 skip, 0 error
```

- task_1: fmt=ekw, 20 criteria, 20 deliverables, 0 read-scope, 8 env files, clean
- task_15: fmt=ekw, 23 criteria, 23 deliverables, 0 read-scope, 3 env files, clean

The format-agnostic path is live (real LLM verdict on real EKW verifier.json),
not assumed. The motivating row-28/29 defects are SVC-PC tasks; no EKW-specific
structural defect was verified against this check yet (the two EKW tasks
sampled came back clean), so an EKW-side false-positive rate is not measured.

## Verification: orchestrator end-to-end wiring

Ran the SVC orchestrator itself (not the check standalone) against the two
acceptance tasks, scoped to the new check:

```
LLM_BACKEND_FORCE=http python svc_run_checks.py \
  SVC-PC-72-3-0 SVC-PC-82-2-0 \
  --root C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready \
  --out-dir <out> --checks structural_audit
```

Real output:

```
  structural_audit                 shard 00 (  1 tasks) rc=0    16.0s json ok
  structural_audit                 shard 01 (  1 tasks) rc=0    30.8s json ok
  structural_audit                 merged 2/2 shards, cpu 46.8s, json ok

2 tasks in 30.9s -> <out>/summary.csv
  C: fail=0  error=0  warn=2  pass=0  skip=0
  D: fail=0  error=0  warn=0  pass=0  skip=2
  E: fail=0  error=0  warn=0  pass=0  skip=2
    structural_audit                 warn=2
```

`summary.csv` confirms the rollup: both tasks show `C=warn`,
`structural_audit=warn`. The check is wired into the normal process users
actually run.

## LLM backend

The configured HTTP backend (glm-5.2 via an OpenAI-compatible gateway) was used
for every real call in this report (`LLM_BACKEND_FORCE=http`). No call was
simulated. A trivial probe (`Reply with exactly the single word: READY`)
returned `READY` before any task run. The Claude Code CLI is not on PATH in
this environment; the HTTP backend served every call.

## Files changed

- `deterministic-checks/structural_audit_check.py` (new, the check)
- `deterministic-checks/svc_run_checks.py` (registered under letter C + legend)
- `deterministic-checks/ekw/ekw_run_checks.py` (registered under letter C + legend)

## Known limitations

- One false-positive class observed: LLM case-misread of filenames (the
  SVC-PC-1-0-0 `FPA`/`Fpa` case). Mitigated by the verbatim-quote requirement
  + the project's existing hard rule that a reviewer checks every finding
  against the real file before acting. Not auto-suppressed, because
  suppressing case-only differences would also suppress a real
  case-sensitivity defect on a case-sensitive filesystem (a genuine row-28
  shape).
- False-negative rate not measured (no labeled ground-truth set for the
  600-task corpus; the 19 clean tasks in the sample were not hand-audited).
- EKW false-positive rate not measured (2 EKW tasks sampled, both clean; no
  EKW-specific structural defect verified against this check yet).
- One real LLM call per task (~5-15s observed on the configured backend);
  expensive on a bare `--all` over 600 tasks. Scope with `--checks` to exclude
  it from a fast sweep, same discipline the other two LLM checks carry.
