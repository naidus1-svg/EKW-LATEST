# Zero-pass review brief (TFRL QC style)

You are doing the TFRL QC team's manual check ourselves, on tasks they did not sample. Read-only work on local files.
Never modify anything in DataOS, Drive, Sheets or Slack.

## Your input

A DataOS "task with runs" zip per task, at `C:/Users/khiem.doan_turing/Documents/qc_review/<batch>/zips/<TASK>__<ID>.zip`.
Unzip it into your own work folder `C:/Users/khiem.doan_turing/Documents/qc_review/<batch>/work/<TASK>/` (create it).
Inside, under `<TASK>/rev_N__<ID>/`:

- `task_files/instruction.md` (the prompt the agent saw); SVC tasks also have `task_files/tests/task_prompt.txt`
- `task_files/tests/` (the grader): SVC uses `deliverables_*/judge.toml` (criteria, expected values, the `files=` list
  each judge group can see) plus `reward.toml` (weights); EKW uses `verifier.json` (criteria and weights) and a
  vendored `verifier_lib/`. Discover the layout; do not assume.
- `task_files/environment/initial_workspace/` (the source files the agent had) and `task_files/solution/` (gold)
- `evaluations/eval_<id>__attempt_1__<agent>__<model>/eval_files/verifier/reward-details.json` (per-criterion verdict
  and judge reasoning for that run) plus the run's own outputs. Oracle runs are the gold answer graded; ignore them
  when deciding what the agents did.

You are also given, per task, the list of tests that fail in EVERY agent run (0% pass rate). Those are what you judge.
Read xlsx with openpyxl, docx by unzipping `word/document.xml`, pdf with any available tool.

## The question, per 0% test

Is this a TASK DEFECT or a SOLVER MISS?

TASK DEFECT, one of:
1. **Prompt-tests misalignment**: the criterion demands something the prompt does not ask for, or contradicts what the
   prompt says (including format or layout demands the prompt never states).
2. **Prompt ambiguity**: the prompt allows a reasonable reading that the runs took, and the criterion accepts only a
   different reading.
3. **Wrong or contested expected value**: the source files support a different answer than the criterion expects, or
   support both, or the sources conflict and the criterion picks one side without the prompt saying which governs.
4. **Unpassable by construction**: the criterion grades a file the judge group's `files=` list never includes, or the
   expected value cannot be derived from the given sources at all.

SOLVER MISS: the prompt clearly asks for it, the sources clearly support the expected value, and the runs simply did
not deliver it (omitted it, computed it wrong, ignored an instruction).

Check the evidence yourself: open the prompt, the criterion text, the relevant source file, and at least one run's
output or judge reasoning. Quote them. A verdict without a quoted prompt line and a quoted criterion is not done.

**Search ALL the sources before either call (added 2026-09-29).** Before calling a criterion "not asked for",
"unsourced" or "invented", search every file under `environment/` (dossiers, tickets, emails, workbooks, PDFs, not
just the prompt and the one file the change set or brief points at) for the criterion's key terms, ids and figures,
and quote what you found or state that the search returned nothing and which terms you used. Before calling a 0% test a
SOLVER MISS, show the source line (or the recomputation from source data) that supports the expected value. On
TaskID-MKT-188 a Major was marked because the reviewer checked only the prompt and change set; the task's hard-cases
dossier tags "created_at parsed as epoch-ms integer [CHG-0B5A8F, CHG-3B9D77]" and ticket TCK-C5B240 asks to "update the
parser before cutover", which grounds the requirement. A requirement the sources pin is not a defect when the prompt
asks for that kind of output (here, a required developer action per change). It is still a defect when the prompt
never asks for that kind of output at all (QC's own SVC-PC-91-0-0 call below).

## Severity (how QC rated round 1)

- A TASK DEFECT that fails correct or reasonable work is **Major at any weight**. QC marked a 0.9% criterion Major
  ("MAJOR, tiny weight"). False rejection is Major; weight only changes how urgent the fix is.
- **Minor**: coverage gaps (a criterion that never reaches full marks but is not a false rejection), a sub-condition
  the prompt only implies, small wording issues.
- A task with only SOLVER MISS findings is **CLEAN** for this check.

## Calibration: QC's own round 1 calls (batch 1)

Majors (task defects):
- SVC-PC-44-0-0, PTM Major: c-090 (0.9%) failed runs for not describing channel-level MMM credit shifts; the prompt
  says not to report channel-level MMM results the data cannot identify. Runs did what the prompt said.
- SVC-PC-91-0-0, PA Major: r7 (6.7%) needs one per-unit net figure (DTC minus Amazon contribution); the prompt only asks
  to "quantify the cannibalization". Runs quantified it other valid ways.
- SVC-PC-88-4-0, PTM Major: obj-02/03 (28%) accept only $30,100; the member's own enrolment form supports $30,450
  (two effective dates in one form). The rubric picks one side of a source conflict.
- HLT-240, PA Major + PTM Major: v5 treats a normal lab trend as a "source conflict"; v1/v3/v14/v19 fix one clinical
  answer and reject a guideline-concordant alternative the prompt allows.
- FIN-267, PA Major: criteria ban a $0.6M residual shortfall that the lease wording ($3.0M cap, $2.4M estimate) supports
  under the usual ASC 842 reading.
- task_207, PTM Major: v10 demands per-SKU lines although the rubric itself says those SKUs do not change the settlement
  and the prompt says carry forward only material exceptions.

Solver misses (not defects), for contrast: SVC-PC-91-6-0 (five 0% tests), SVC-PC-47-0-0, SVC-PC-57-2-0,
SVC-PC-93-6-0, SVC-PC-37-1-0, SVC-PC-55-0-0, task_FIN-313 (thirteen 0% tests), task_FIN-327, task_FIN-324,
task_FIN-298: the prompt asked, the sources supported the answer, the runs missed it.

## Output, per task

Write `C:/Users/khiem.doan_turing/Documents/qc_review/<batch>/verdicts/<TASK>.json`:

```json
{"task": "...", "dataos_id": "...", "verdict": "MAJOR|MINOR|CLEAN",
 "prompt_ambiguity": "Good|Minor|Major", "prompt_tests_misalignment": "Good|Minor|Major", "test_coverage": "Good|Minor|Major",
 "zero_tests": [{"id": "...", "weight_pct": 0.0, "call": "TASK DEFECT|SOLVER MISS", "category": "PTM|PA|WRONG_VALUE|UNPASSABLE|-",
   "evidence": "prompt: \"...\" | criterion: \"...\" | source <file>: \"...\" | run: \"...\"", "reason": "one sentence"}],
 "feedback": "QC-style paragraph, see below", "confidence": "high|medium|low"}
```

`feedback` uses QC's format, plain text, no em dashes: first line `TASK DEFECT - N tests at 0% pass rate across runs,
X% of total reward.` or `ZERO-PASS - N tests at 0% pass rate across runs, X% of total reward. Solver miss, not a task
defect.`, then one short paragraph per finding: `Prompt-Tests misalignment (MAJOR): <criterion ids> (<weight>%) ...`.
Name the criterion, what it demands, what the prompt or source says, and what the runs did. No speculation beyond
what you quoted.

Set `confidence` to low whenever you could not open a needed source file or the judge reasoning is missing.
When done with all your tasks, reply with one line per task: `<TASK>: <verdict> (<confidence>)`.
