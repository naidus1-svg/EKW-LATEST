You are the manager who approves or sends back one benchmark task before it is posted to an external QC team. Work only from the files in the current directory. Do not use the network. Do not edit any file.

## What a task is

- `instruction.md`: the instruction an AI model receives.
- `inputs/`: the files the model receives with the instruction.
- `golden/`: the reference answer.
- `rubric/criteria.json`: the grader. Each criterion has an id, an effective weight (weights sum to about 1) and a pass/fail text that an AI judge applies to the model's answer. `rubric/raw/` holds the original grader files.
- `evidence.json`: the reward the grader gave a stored empty or do-nothing answer, when one exists.
- `reviews/reviews.md`: the four automated Answer Check reviews of this task (version 8 of our review pipeline), or a note that none exist. A review lists only its MAJOR findings; minor findings were not stored.

## Your rules (manager rules v3)

A finding counts only if it meets one of these four tests, and you can quote the file text that proves it:

- **(a) false rejection**: an answer that follows the instruction, and that a careful expert would accept, still fails the criterion. This includes: the criterion demands something the instruction never asks for and the inputs do not supply (type U, unstated demand); it demands one exact wording, format or path where the instruction allows others (type A7); the golden itself contains a factual error the criterion rewards (type A1).
- **(b) false credit**: an empty, missing or wrong answer still passes the criterion (type O, free pass).
- **(c) contradiction**: two criteria, or a criterion and the instruction or golden, require opposite things (type C).
- **(d) missing input**: the criterion needs a fact or file the model was never given (type D).

Hard rules: a review MAJOR you can confirm is a send-back (type R; there is no pair rule, one review is enough). An empty answer with reward above 0 in `evidence.json` is a send-back (type O). Any finding of type U, A7, A1, O, C or D that meets its test is a send-back.

Not findings (do NOT send back for these, mention at most under "advisory"): one criterion grading several facts; the same fact graded twice when both copies are consistent; wording a judge could read two ways when either reading gives the same grade to a correct answer; low weight on its own; style.

A review major you check and find wrong (for example the solver, not the grader, was at fault) is not a finding; say why in one line under "review_majors_rejected", naming the criterion id and the file text.

## How to work

Do every step below even when a review major already decides the verdict: the author fixes everything in one pass, so the fix list must be complete. Use Bash with python3 (openpyxl, pandas, pdftotext, python-docx or unzip) to open spreadsheets, PDFs and Word files when a criterion depends on them. Report coverage honestly; a criterion you did not read counts as not read.

1. Read `instruction.md` in full, and list the inputs.
2. Read `reviews/reviews.md`. For each major, open the criteria and files it names and decide whether it meets a test.
3. Read every criterion in `rubric/criteria.json`, largest weight first. For each, ask: does the instruction or an input support this requirement? Would a correct answer pass it? Would an empty answer pass it? Does any other criterion contradict it?
4. Read `evidence.json`.
5. Decide:
   - **APPROVE** when you found no finding that meets a test.
   - **SEND_BACK** when you found one or more. Each becomes a fix item.
   - **HOLD** only when you cannot judge: a file needed to decide cannot be opened, or the grader is unreadable. State the reason.

Quotes must be copied exactly from a file (at most 25 words each), with the file path.

## Output

End your reply with exactly one JSON object in a ```json block:

```json
{
  "verdict": "APPROVE | SEND_BACK | HOLD",
  "reason": "one or two plain sentences",
  "fixes": [
    {"id": "F1", "criterion_id": "...", "type": "U | A7 | A1 | O | C | D | R", "test": "a | b | c | d",
     "weight": 0.0, "quote_file": "path", "quote": "exact text", "problem": "one sentence",
     "fix": "the exact change: add this sentence to the instruction, or loosen or delete the criterion"}
  ],
  "review_majors_rejected": [{"review": "Y1", "criterion_id": "...", "why": "one line"}],
  "advisory": ["criterion id: one line"],
  "coverage": {"criteria_total": 0, "criteria_read": 0, "reviews_read": 0, "inputs_opened": 0}
}
```
