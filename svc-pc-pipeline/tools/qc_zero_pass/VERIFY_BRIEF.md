# Adversarial verification brief (second pass on first-pass MAJORs)

A first reviewer called these tasks MAJOR (task defect). Marking a task failed sends it back to its author, so a
false fail costs someone a day. Your job is to try to REFUTE each TASK DEFECT finding using the task files, the same
way a skeptical TFRL QC reviewer would. Read `C:/Users/khiem.doan_turing/Documents/qc_review/REVIEW_BRIEF.md` first
for the categories, severity rules and QC's round 1 calibration. Read-only local work; never touch DataOS, Drive,
Sheets or Slack.

## Inputs per task

- The first-pass verdict: `<batch>/verdicts/<TASK>.json`
- The zip: `<batch>/zips/<TASK>__<ID>.zip`; the first reviewer may have unzipped it to `<batch>/work/<TASK>/`
  (you may reuse that folder, but read the files yourself; do not trust the first reviewer's quotes)

## For each finding the first pass called TASK DEFECT

Independently re-derive it:
1. Open the prompt (instruction.md or tests/task_prompt.txt) and find every line relevant to the criterion. Does the
   prompt, read fairly and in full (including general instructions like "cite sources", "flag conflicts", required
   sections and deliverable lists), actually ask for what the criterion demands? A criterion that checks a clearly
   requested item is NOT a defect even if the wording differs.
2. Open the criterion (judge.toml / verifier.json) and its expected value.
3. Open the source file(s) the expected value comes from. Do they support it? Is there a genuine conflict?
   Then search EVERY file under `environment/` (dossiers, tickets, emails, workbooks, PDFs), not only the files the
   first pass quoted, for the criterion's key terms, ids and figures. The first pass's framing is not your search
   scope: on TaskID-MKT-188 both passes checked only the prompt and change set and missed a dossier line tagging the
   required parser update to the exact change id. Report the terms you searched and every hit. If the sources pin the
   required item and the prompt asks for that kind of output, REFUTE.
4. Open at least one agent run's actual output and the judge reasoning in reward-details.json. Did the runs do
   something the prompt allows and get marked down (defect), or did they miss or botch a requested item (solver miss)?

Call each finding CONFIRMED (the defect is real and it fails correct or reasonable work), REFUTED (the prompt or
sources do support the criterion; runs missed it), or UNSURE (evidence genuinely balanced or a file could not be read).

## Output

Write `<batch>/verdicts/<TASK>.verify.json`:

```json
{"task": "...", "findings": [{"id": "...", "first_call": "TASK DEFECT", "verify_call": "CONFIRMED|REFUTED|UNSURE",
   "evidence": "prompt: \"...\" | criterion: \"...\" | source <file>: \"...\" | run: \"...\"", "reason": "one sentence"}],
 "overall": "CONFIRMED_MAJOR|DOWNGRADE_MINOR|CLEAN|UNSURE",
 "ratings": {"prompt_ambiguity": "Good|Minor|Major", "prompt_tests_misalignment": "Good|Minor|Major", "test_coverage": "Good|Minor|Major"},
 "feedback": "QC-style paragraph covering only CONFIRMED findings, same format as the brief, no em dashes"}
```

`overall` is CONFIRMED_MAJOR only if at least one finding is CONFIRMED and severity is Major under the brief's rules.
If every finding is REFUTED, use CLEAN (or DOWNGRADE_MINOR when a Minor issue remains). Use UNSURE when the deciding
finding is UNSURE. Reply with one line per task: `<TASK>: <overall>`.
