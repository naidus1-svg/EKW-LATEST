# QC person pre-check, grouped by what TFRL rejects (same checks as SOP section 5a)

The QC person (the person fixing the task, not the task author) answers these six questions for every weighted grading rule worth 0.05 or more of the score (a heavy rule), before the task goes to the DataOS pipeline. Write down the file and line that proves each answer. A question counts as answered only when you can point at that line.

These are the six kinds of serious problem (Major) that the external QC team (TFRL) wrote most often on rejected tasks, most frequent first. Unclear instruction is the most frequent kind in the newest batches. This checklist turns those complaints into checks you can run yourself. It has not been measured on authors yet, so it is a reading aid and a place to catch problems early, not a gate.

Most of this list is the same as steps 2 to 10 of section 5a of docs/QC-SOP-first-run.md, regrouped by the kind of Major TFRL writes. Two things here are not in the 5a steps: question 3 (a second way to read an instruction sentence) and the weights part of question 5. The checks that can be run by script are being added to the first-run check runner (deterministic-checks/ekw/ekw_run_checks.py).

## First, three quick runs

1. Run the oracle (the reference solution) twice. It must score 100 percent both times.
2. Run the empty answer. It must score 0. If it scores above 0, find the rule that credits nothing and fix it.
3. Check that every file the instruction or a rule names is in the package.

## The six questions

### 1. Does a rule fail an answer that is correct?
List the accepted forms of the answer: rounding, units, ordering, file or sheet naming, spelling, a different but valid method. Picture a careful expert's correct answer in each form. If any form would lose the rule, widen the rule so it grades the meaning, not the wording.

### 2. Does a rule ask for something the instruction never requested?
Next to each weighted rule, paste the sentence of the instruction that asks for it. If there is no sentence, add one to the instruction or remove the requirement from the rule. Watch for extras that sneak in: a word limit, a count of fields, a layout, a threshold, an extra scenario.

### 3. Can a careful reader take an instruction sentence another way, so that a rule would then fail a correct answer?
For each heavy rule, write the other reading a careful expert could take (period, scope, definition, which file, which rounding). Ask: would an answer that follows that reading still earn the rule? If not, settle the point in the instruction, or widen the rule to accept both readings.

### 4. Do the rules check enough that a wrong or empty answer earns nothing?
Read every rule as if the answer file were empty. Does any rule pass because something is absent ("no errors", "does not include X")? Does any rule only check that a file or section exists? Write a vague answer that restates the instruction without doing the work and list the rules it would still pass; that list should be close to empty. For every requirement in the instruction and every trap you planted in the inputs, write the rule that tests it.

### 5. Are the weights, the output location or the inputs wrong?
Does each rule's weight follow the priorities the instruction states? Is the deliverable in the place the grader reads? Can the judge see every file each rule needs? Does any rule ask for the opposite of another rule or of the instruction?

### 6. Is a number or the reference answer wrong?
Recompute every expected value yourself from the input files. Write how a careful solver gets it from the instruction and the inputs alone. If it rests on an assumption the instruction does not state, state it or change the key.

## Notes

- Questions 1 to 3 cover the largest share of what TFRL rejects. Do them first if you are short of time.
- Some of these problems only show up in solver runs. If your task has solver runs, read the rules where the runs disagree or all lose while the reference answer passes.
- Source and counts: the 478 serious items on the 219 tasks TFRL rejected (pipeline quality analysis, 2026-10-08). Send corrections to the QC lead.
