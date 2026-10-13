# Verifier: test each reviewer finding against the task package

You are an expert checking whether specific claims about a benchmark task are true. A benchmark task
is a work assignment for an AI: an instruction, input files, a reference answer (the "golden") and a
grader (the "rubric": weighted pass/fail or scored criteria that an AI judge applies to the AI's answer).

Your working directory holds one task package:

- `instruction.md`: the instruction exactly as the AI sees it.
- `inputs/`: the input files the AI receives (may be empty).
- `rubric/criteria.json`: every criterion as a list of {id, w, text}; `w` is the criterion's effective
  weight in the final reward (all weights sum to 1). `rubric/raw/` holds the original rubric files.
- `golden/`: the reference answer files and solve script.
- `evidence.json`: stored run evidence where available (for example the reward an empty or no-op
  answer earned in a stored run). It may be empty.
- `findings.json`: a list of findings {id, text}. Each is a claim, written by some reviewer, that the
  task has a defect. Reviewers are often wrong. Do not assume a finding is true.

Use python3 (openpyxl, python-docx, pdfplumber or pypdf if installed; fall back to unzip or strings) to
read inputs and golden files when you need them. Read the instruction, the criteria and the relevant
inputs before deciding anything.

## The test (fixed; apply it to every finding)

For each finding, identify the criterion or criteria it concerns (by id from criteria.json; if the
finding concerns the task as a whole, pick the criteria it affects most). Then apply these four tests:

(a) FALSE REJECTION: can you write, in a few lines, an answer that follows the instruction as written
    and that a careful expert in the field would accept, which still loses this criterion's credit?
    If yes, write that answer sketch and quote the criterion text it fails and the instruction text it
    follows.
(b) FALSE CREDIT: does an empty, wrong or no-op answer earn this criterion's credit? Use the stored
    empty-answer reward in evidence.json if present; otherwise reason about a trivially wrong answer
    against the criterion text (for example, a criterion that passes when something is absent).
(c) CONTRADICTION: do two criteria, or a criterion and the instruction, require opposite things?
    Quote both sides.
(d) MISSING INPUT: does the criterion depend on a fact, figure or file that is not in the inputs and
    cannot be derived from them or from ordinary professional knowledge? Name the fact and say where
    you looked.

Verdict per finding:
- `VERIFIED` only if at least one of (a) to (d) holds and you can quote the evidence from the files.
  A defect that is real but different from what the finding claims still counts only if it concerns
  the same criterion; say so in `note`.
- `NOT_A_DEFECT` if none holds; quote the instruction sentence or input text that supports the
  criterion as written.
- `UNCLEAR` if you cannot decide from the files (say what is missing).

Be strict about evidence, not about style. Wording you would have written differently, a criterion
that is hard, or a criterion with low weight is NOT by itself a defect. A finding that only says a
criterion is "redundant", "compound" or "low weight" is VERIFIED only if it also meets (a), (b), (c)
or (d).

## Output

Write `verdicts.json` in the working directory, exactly this shape, one entry per finding id in
findings.json (no missing ids, no extra ids):

```json
{"verdicts": [
  {"id": "F1",
   "criteria": ["<criterion id>", "..."],
   "verdict": "VERIFIED | NOT_A_DEFECT | UNCLEAR",
   "tests_met": ["a", "b", "c", "d"],
   "answer_sketch": "<for test a: the few-line acceptable answer that loses credit; else empty>",
   "evidence": ["<short quote with file name>", "<short quote with file name>"],
   "note": "<one or two sentences>"}
]}
```

`tests_met` lists only the tests that hold (empty for NOT_A_DEFECT and UNCLEAR). Keep each quote under
40 words. Do not edit any other file. When verdicts.json is written, stop.
