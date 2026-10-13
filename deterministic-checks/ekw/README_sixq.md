# The six questions, built into the first-run checks (letter F)

For the QC person. The six questions used to be a written list the task author answered by hand
(docs/author-pre-submission-checklist.md). They now run as checks F1 to F6 inside
`ekw_run_checks.py`. The QC person runs one command and fixes what it flags. The task author
is not asked to run anything.

## The one command

    python ekw_run_checks.py --all --root <harbor tree> --stage <stage dir> --out-dir <out dir>

F1 to F6 run with every other check. Open `<out dir>/summary.csv`: the columns F1 to F6 hold one
verdict per task (pass, warn, skip, error), and column F is the worst of the six. To run only
the six questions on one task:

    python ekw_run_checks.py task_142 --root <harbor tree> --stage <stage dir> --out-dir <out dir> --checks check_b,sixq_f1,sixq_f2,sixq_f3,sixq_f4,sixq_f5,sixq_f6

Each check also writes its own file `<out dir>/sixq_f1.json` to `sixq_f6.json`. Every finding in
it names a rule id, the file and the line of that rule (the line of its `[[criterion]]` entry, or
of its `"name"` entry in `verifier.json`). A finding with no file and line is dropped and counted
in `dropped_no_anchor`; it is never shown.

## What each column means

| Column | One plain sentence | Needs a Claude login |
|---|---|---|
| F1 | A rule would fail an answer that is correct in another valid form (rounding, units, naming, ordering, wording, method). | Part of it: the AI reader names the other form. The script part (strict wording such as "exactly" with a pinned figure and no wording that accepts another form) runs without. |
| F2 | A rule asks for something the instruction never requested. | Part of it: the AI reader looks for the instruction sentence behind each rule. The script part (a count, limit or required name in a rule that instruction.md never states) runs without. |
| F3 | A careful reader could take an instruction sentence another way, and then a rule would fail a correct answer. | Yes, all of it. Without a login F3 reports skip. |
| F4 | A wrong or empty answer can still earn weight: a rule passes on an absence ("no errors", "without") or only checks that something exists. | No. It also prints how much weight sits on those rules. |
| F5 | Weights, output location or inputs do not line up: a rule names a file its judge group cannot see, or the instruction names a priority and the rules on it weigh less than the task median. | No. |
| F6 | A number pinned in a rule appears in no golden file (within the rounding the rule shows), so the rule or the golden is wrong. | No. |

The AI reader makes one call per task per question with `claude -p --model sonnet`. To leave F1
to F3 out of a fast run, drop them with `--checks`.

## What to do with a flag

1. Open the file at the line in the finding. Read the rule next to the instruction.
2. If the flag is right, fix the rule (widen it so it grades the meaning, add the instruction
   sentence, remove the unrequested part, change the weight, name the file, correct the number),
   then rerun the same command and confirm the column turns to pass.
3. If the flag is wrong, write one line in the task notes saying why. Do not delete the finding
   from the JSON.
4. A flag is a candidate, not a verdict. These checks are not yet calibrated: the backtest in
   `out/SIXQ.md` gives how often each flag fell on tasks TFRL rejected and on tasks TFRL approved. TFRL is the
   human QC team that reviews a sample of each batch (see `../../svc-pc-pipeline/docs/qc-intake-process.md`).

## What still needs a person

- F4: the vague-answer test (write an answer that only restates the instruction and list which
  rules it would pass). The empty-answer run in DataOS stays a pipeline step.
- F5: two rules that ask for opposite things; a deliverable placed where the grader does not read.
- F6: a number that is in no golden file and no input must be recomputed by hand from the inputs.
- F1 to F3: the QC person decides whether the other form or reading the AI reader gives is one a
  careful expert could really take.

## Tests

    python sixq_checks_test.py

Prints a `TESTS n/n passed` line. Each check has a flag case, a clean case and a missing-input
case; the AI reader is replaced by a fake, so no login is needed for the tests.
