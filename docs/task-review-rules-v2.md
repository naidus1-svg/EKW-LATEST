# Task review rules, version 2

For: managers who approve, hold, or send back submitted tasks.
Status: proposal. Not yet shown to work on new tasks. Use it as a reading order, not as a pass bar. The pipeline steps below apply to the "ManualQC automated QC pipeline 4 Reviewers" pipeline (DataOS pipeline 141), version 8. Its four "Answer Check" reviews use the review prompt saved in DataOS as 431, named "Comprehensive_v3_pipeline_quality_re-derive_cascade_NOP_2026-10-03"; you do not run that prompt yourself.
Replaces: the nine DENY rules (reviewer prompt of 2026-09-30).
Words: Oracle run, Comprehensive Review and TFRL are in the [glossary](../README.md#glossary). Answer Check review is in the glossary of the [manager run sheet](QC-RUNBOOK-manager.md#glossary).
Use it with the manager run sheet: from the next batch the manager also applies rules B to E of [`QC-RUNBOOK-manager.md`](QC-RUNBOOK-manager.md) and approves a task only when every rule holds. For the reader items (rule D) a missing or unbelievable answer is enough to send a task back ([SOP 7](QC-SOP-first-run.md#7-package-and-hand-off)). You record the verdict in the review sheet with rule F of that run sheet.

## Why this changes

The nine rules were applied to the rubric text alone. The reviewer did not read the two Comprehensive Review results on the task page, and could not read the source files (PDFs and spreadsheets). Three of the nine rules depend on those sources:

- Rule 4, the answer key has a factual error.
- Rule 5, a check asks for something the prompt never asks for.
- Rule 6, a judge must check facts it is not given the files for.

A reviewer without the sources can only guess on those three. The Comprehensive Review does read them: it recomputes the figures from the source files, checks that the answer key does not leak into them, and reads the model outputs. On task_311 the review confirmed that both models lost points because they omitted realized-gain tax, which is a real model error. A rubric-only reading had called that same check unfair.

So a rubric-only DENY on rules 4, 5 or 6 is unproven. Every verdict given under the old rules is treated as unverified until it is re-checked under these rules.

## What the reviewer must read first

1. All four Answer Check review results (task page, then Verifications, then Comprehensive Review). For each, write down the id, the time it ran, the overall verdict, the major and minor counts, and every failed check with its suggested fix. Confirm they ran on the Oracle and model evaluations that are on the task page now.
2. The Oracle and model results: evaluation ids, rewards, and the per-test pass table.
3. instruction.md and every criterion in the rubric, in full.

If a review is missing, or ran on older evaluations, the answer is CAN'T JUDGE YET.

## How to use the pipeline result

The pipeline result tells you which task to open and which review to read. The pipeline fails a task when any of the four Answer Check reviews reports a major.

- Pipeline fails: send the task back to the author with the failed checks.
- Pipeline passes: the task can go in the next TFRL batch (TFRL is the outside QC team that reviews finished tasks; Khiem Doan builds the batches and sends them, you never send a task to TFRL yourself, see [SOP 7](QC-SOP-first-run.md#7-package-and-hand-off)), unless your own read finds a Major you can show (item 7 of "What to read, in order of what finds the most", and the Tier A rules). A Major you can show means a correct answer that follows the instruction would lose credit because of it, or a wrong or empty answer would earn credit because of it. If you find one, send the task back with the check id and the reason.
- The four reviews can disagree, and a major in any one of them fails the pipeline. Tell the author which review to read and to fix what is a real problem.

A pipeline pass means the pipeline rule was met. It does not replace your read, and it is not a TFRL approval.

The nine deny rules (guide v1) are retired. This document and any later version of the manager steps are proposals that have not been shown to work on new tasks. Use them as a reading order. Write down what you read and what you did not. When you disagree with a review, say which one and why.

Do not quote a catch rate or a false-flag rate from earlier analyses. The figures that circulated were measured on the set the prompts were tuned on and did not hold on new tasks. Any rate added to a document must be labelled early and unaudited, with its denominator and date.

## What to read, in order of what finds the most

Most Major issues are found by comparing the rubric with the instruction and the sources, not by reading failed tests.

1. For each criterion: does the instruction ask for it, and can the expected value be worked out from what is shipped?
2. For each instruction requirement and each planted trap: which criterion tests it, and how tightly?
3. What does an empty answer score, and what does a vague answer score?
4. Can each judge see its inputs in full (no cut-off deliverable, no missing file, no value read only from a cached cell)?
5. Do any criteria contradict the prompt, the sources or each other?
6. Only then read the failed tests: does a criterion fail in every run for a task reason or a solver reason? TFRL samples tests that fail in every run first, so expect them; the question is the cause.
7. Call it Major only if a prompt-following answer loses credit because of the defect, or a wrong or empty answer gains credit because of it. Everything else is Minor.

## Verdicts

APPROVE, DENY, or CAN'T JUDGE YET.

CAN'T JUDGE YET when there are no model runs, fewer than 2 Oracle runs at 1.0 (1 is enough on the manager's own tasks), no Comprehensive Review on the current evaluations, or the task cannot be read.

## Tier A: correctness and fairness. These can DENY.

- A1. The answer key has a factual error, or contradicts the source files, or contradicts itself across checks. Applied only when a review or a reading of the extracted source text shows it.
- A2. A check requires something that neither the prompt nor the sources ask for. The sources include notes the prompt names, such as a CIO engagement note.
- A3. A judge must check facts against files it is not given, and the check text does not carry the values it needs.
- A4. The grading script can crash and give no score.
- A5. Graders gave different results on the same answer in the runs (pass, fail, pass).
- A6. A major issue in any of the reviews that is not fixed and is not explained in writing as a false positive. The send-back decision follows "How to use the pipeline result" above: a major in any of the four reviews fails the pipeline.
- A7. A correct answer written differently fails: an exact filename or exact wording is required, or a band excludes a valid alternative the prompt leaves open.

A Tier A rule that needs the source files is applied only after the source text has been read, or a review confirms it. Otherwise the reviewer says so and does not deny on it.

## Tier B: rubric hygiene. Reported, not a DENY by default.

- B1. One check grades many separate facts at once.
- B2. The same fact is graded in two checks with no note saying which one owns it.
- B3. Wording a judge could read two ways.

Tier B findings go to the author as optional fixes, with check ids. The manager can decide for a given batch that Tier B findings also hold a task. Default: they do not.

## Always say

- If every model scored 100%, the task is too easy. This never blocks an approval.
- Whether the finding agrees or disagrees with a Comprehensive Review. When it disagrees, say which one and why, with the check id. A review that read the sources outranks a finding made from rubric text alone.
- A check "wrongly fails a correct answer" only when the model output was seen, or a review says so.

## Verdict line format

```
Verdict: APPROVE / DENY / CAN'T JUDGE YET
Why: 1 to 2 plain sentences.
Tier A findings: check id, rule, one line each.
Tier B findings (optional fixes): check id, rule, one line each.
Disagrees with review: yes or no, and where.
Coverage: criteria read x of y; reviews read; sources read or not.
Fix: numbered list, each naming the check id and exactly what to change.
```

For the sheet, one line per task: `task | tab | APPROVE / DENY (correctness) / APPROVE + hygiene | reason`.

## Known limits of this process

- The reviewer reads the source text only where the file API serves text. PDFs and spreadsheets are read through the Comprehensive Review, not directly.
- The four Answer Check reviews on one task can disagree. All four are read, and a disagreement is reported rather than resolved silently.
- The review itself is a model output and can be wrong. It is the best available evidence on the sources, not a final authority.

## What happens to earlier verdicts

Every task that received a DENY, KEEP_HELD, FAIL, or WIP-fix-needed verdict under the old rules is re-graded under these rules, in this order: tasks already sent back to authors or held out of a submission, then the WIP rows, then the rest. Until a task is re-graded, its old verdict is not used to message an author.
