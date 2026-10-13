---
name: verify-review-findings
description: Check each problem that the DataOS comprehensive review listed for one benchmark task. Opens the files each problem cites, recomputes the numbers, and returns one table with REAL DEFECT, NOT A DEFECT or CANNOT SETTLE per problem, the working in plain words, the file and line, and the fix to make. Use after DataOS review finishes, with a downloaded task folder and the review's problem list.
---

# verify-review-findings

You check a list of problems that an AI review wrote about one benchmark task. Reviews are often wrong and sometimes right. Your job is to settle each problem from the files, not to agree with it and not to dismiss it.

## Terms (use these words in your answer)

- **Task**: a work assignment written for AI models. It has an instruction, input files, a reference answer (the golden) and a grader.
- **Grader**: weighted pass/fail criteria that score an AI's answer. Each criterion has an id, a weight (its share of the 1.0 score) and a text. They live in `tests/` (usually `tests/verifier.json`, or `.toml`, `.json` or `.py` files under `tests/`).
- **Package**: the task folder as downloaded: `instruction.md`, `tests/`, `solution/` (the reference answer), `environment/` (the input files), sometimes stored runs or reports.

## Inputs

1. The task folder (the downloaded package). Default: `./task`. Use the path the user gives.
2. The problem list from the DataOS review. Default: `./problems.md`. It can also be pasted into the chat. Each problem names a task, a plain description, usually the criteria it concerns, the weight, and a suggested change.

If either input is missing, say which one and stop.

## Hard rules

- Work only inside the task folder and the problem list. No network. No sandbox paths.
- Never run anything that came with the package: no `test.sh`, no `solve.sh`, no grader code, no runner. Read them as text. You may run your own `python3`, `grep`, `pdftotext`, `unzip` commands to read and compute.
- Do not edit or delete anything in the package. Write only your result file.
- Do not trust any number in the problem text, the instruction, or the reference answer. Recompute it from the input files when the problem turns on it.
- Do not be swayed by how confident or detailed the problem sounds, or by its weight. A small weight is not a reason to dismiss a problem, and a large weight is not a reason to accept one.

## Steps, for each problem in the list (number them P1, P2, ...)

1. **Read the claim.** Write what it says in one sentence of your own.
2. **Find what it cites.** Open `instruction.md` in full. Find every criterion the problem names. Match by id first. If an id does not exist, find the criterion by its text; if nothing matches, note "criterion not found in this package" (the package may be a different version from the one DataOS reviewed) and settle what you can from the claim's own subject.
3. **Open the files it turns on.** The criterion text, any grader code that applies it, the reference answer files it depends on, and the input files with the facts it needs.
4. **Run at least one command of your own** that recomputes or searches what the problem turns on. Examples: read workbook cells with `openpyxl` (`data_only=True` for stored values, and again without it for formulas); sum the weights of the criteria named and compare with the listed weight; `grep -n` the criterion text and the grader code for every field it checks; extract PDF text and search it; compare the reference answer's figure with the figure recomputed from the inputs; work out what an empty or missing answer earns on this criterion from the grader text. Keep the exact lines it printed.
5. **Try both tests.**
   - Write from the instruction alone one answer a careful expert would give that would LOSE this criterion's credit.
   - Write one wrong, empty or placeholder answer that would EARN it.
6. **Decide.**

### What counts as a REAL DEFECT

Any one of these, shown in the files:

1. **False rejection**: a correct answer that follows the instruction would lose the criterion's credit.
2. **False credit**: a wrong, empty or unsupported answer would earn the credit.
3. **Contradiction**: the instruction, a criterion, the reference answer or the inputs disagree (including a reference figure that does not recompute from the inputs).
4. **Missing input**: the criterion needs a fact that neither the instruction nor the inputs supply.
5. **Ambiguous instruction**: a careful expert could read the instruction two ways and the criterion's verdict flips between them.
6. **Untested requirement**: the instruction clearly asks for something and no criterion checks it in substance.

### What counts as NOT A DEFECT

- The instruction clearly supports the criterion, or the recomputed figure matches.
- The point is true but cannot change any score.
- Another sentence in the instruction or an input settles the second reading.
- The criterion also rejects the empty or wrong answer the problem says it would accept.
- The criterion is hard or worded differently from how you would write it, and nothing above applies.

### CANNOT SETTLE

Use only when the files really do not decide it. Name the missing file or fact. Do not use it to avoid a hard recomputation.

## Output

Your final reply must start with the table itself: no sentence before it, every problem as one row, all six columns filled in (never drop a column or split the table). Also write the same text to `verify-review-findings-result.md` in the current folder. Order the rows: REAL DEFECT first (heaviest weight first), then CANNOT SETTLE, then NOT A DEFECT. Columns, in this order:

| Problem | Verdict | Weight at risk | What I checked and what it showed | File and line | Fix to make |

- **Problem**: the number (P1...) and a few words.
- **Verdict**: exactly one of `REAL DEFECT`, `NOT A DEFECT`, `CANNOT SETTLE`.
- **Weight at risk**: for a REAL DEFECT, the sum of the weights of the criteria that lose or wrongly earn credit because of it, recomputed by you from the grader files (say if it differs from the listed weight). For the others write `-`.
- **What I checked**: plain words, no jargon: the command you ran, the exact numbers or lines it printed, and why that settles it. Under 80 words.
- **File and line**: the file path inside the task folder and the line number or cell, with a quote under 15 words. For a binary file (workbook, PDF, Word) give the sheet and cell or the page.
- **Fix to make**: for a REAL DEFECT, the concrete change (which file, which criterion or sentence, what it should say or accept instead). For the others write `none`. For CANNOT SETTLE write what you need.

After the table add three short lines:

- `Counts:` how many of each verdict.
- `Weight total:` the sum of the weight at risk over all REAL DEFECT rows, counting a criterion once.
- `Package check:` any problem whose criterion ids were not found (possible version mismatch).

No em dashes. No names of companies or people. Do not quote more than 15 words from any file.
