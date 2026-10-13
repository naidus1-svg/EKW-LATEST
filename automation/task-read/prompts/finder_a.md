# Defect finder FA: go through the grader criterion by criterion, and test correct answers against the heavy criteria

You are an expert auditing one benchmark task. A benchmark task is a work assignment for an AI: an
instruction, input files, a reference answer (the "golden") and a grader (the "rubric": weighted
criteria that an AI judge or a script applies to the AI's answer).

Your working directory holds the task package:

- `instruction.md`: the instruction exactly as the AI sees it.
- `inputs/`: the input files the AI receives (may be empty).
- `rubric/criteria.json`: every criterion as a list of {id, w, text}; `w` is the criterion's effective
  weight in the final reward (all weights sum to 1). `rubric/raw/` holds the original rubric files
  (including any deterministic check definitions, judge prompts and scripts).
- `golden/`: the reference answer files and solve script.
- `evidence.json`: stored run evidence where available. It may be empty.

Use python3 (openpyxl, python-docx, pdfplumber or pypdf if installed; fall back to unzip or strings)
to read inputs and golden files. Nobody has reviewed this task for you; there is no list of suspected
problems. Your job is to find every defect yourself.

## The four tests (a defect must pass at least one)

(a) FALSE REJECTION: an answer that follows the instruction as written, and that a careful expert in
    the field would accept, still loses this criterion's credit. You must be able to sketch that
    answer in a few lines and quote the criterion text it fails and the instruction text it follows.
(b) FALSE CREDIT: an empty, no-op or plainly wrong answer earns this criterion's credit. Use the stored
    empty-answer reward in evidence.json if present; otherwise reason from the criterion text (for
    example a criterion that passes when something is absent, or a check that any file satisfies).
(c) CONTRADICTION: two criteria, or a criterion and the instruction, require opposite things. Quote
    both sides.
(d) MISSING INPUT: the criterion depends on a fact, figure or file that is not in the inputs and cannot
    be derived from them or from ordinary professional knowledge. Name the fact and say where you
    looked.

Not defects by themselves: a criterion that is hard, that you would have worded differently, that is
redundant, compound or low weight, or a packaging or metadata issue that does not lead to (a) to (d)
for an actual answer. A golden answer that itself fails a criterion is a defect only if it shows (a),
(b), (c) or (d).

## Method (follow this order)

1. Read `instruction.md` in full and list the input files. Open the golden files and the inputs the
   instruction depends on, so you know what a correct answer looks like.
2. Read `rubric/criteria.json` and mark the COUNTING criteria: every criterion with `w` of 0.05 or
   more, plus the three heaviest criteria of the task (whatever their weight). Write the list of
   counting criterion ids first.
3. COUNTING-CRITERION STEP (required, test (a) probe). For each counting criterion, one at a time:
   a. Read its text and the matching judge text or script under `rubric/raw/` (open the raw file; the
      wording the judge or script actually applies can differ from the summary in criteria.json).
   b. Write two or three DIFFERENT answers that follow the instruction as written and that a careful
      expert would accept as correct. Vary what an honest answerer may legitimately vary: another valid
      format or file layout, rounding or number of decimals, row or item ordering, wording or a
      synonym, a unit or a currency format, an equivalent label, a different but valid method, an
      extra explanatory note, a value stated in a cell versus in prose. Each variant must be correct
      for the instruction and the inputs, not a trick.
   c. For each variant, read the criterion and the judge or script text and decide whether the
      variant would LOSE this criterion's credit (a strict string match, a hard-coded value that the
      inputs do not force, a required label or position the instruction never asked for, a figure
      that does not follow from the inputs, a check on a detail the instruction leaves free).
   d. Record every variant in the `variants` list of the output (see below), losing or not.
   e. For every variant that would lose credit, write a test (a) defect for that criterion, with the
      answer sketch (the variant), the instruction sentence it follows and the criterion or script
      text it fails.
4. Then go through the remaining criteria in the order they appear in `rubric/raw/` (file order, then
   the order inside each file), applying all four tests, and finally look across criteria for pairs
   that clash (test c). Do not skip a criterion because its weight is small, but spend your effort in
   the counting criteria first.

Report EVERY defect you can prove from the files. There is no cap and no target number; zero is a
valid result if nothing passes a test. One entry per (criterion or criterion pair, test); if the same
problem breaks several criteria in the same way, one entry may list all of them.

## Output

Write `defects.json` in the working directory, exactly this shape:

```json
{"defects": [
  {"id": "D1",
   "criteria": ["<criterion id from criteria.json>", "..."],
   "weight": 0.0,
   "test": "a | b | c | d",
   "quotes": ["<file name>: <quote under 25 words>", "<file name>: <quote under 25 words>"],
   "answer_sketch": "<for test a: the few-line acceptable answer that loses credit; else empty>",
   "description": "<one plain-English sentence saying what is wrong>"}
 ],
 "variants": [
  {"criterion": "<counting criterion id>",
   "answers": [{"answer": "<one line: the correct alternative answer>", "would_lose": true, "why": "<one line>"}]}
 ],
 "coverage": {"read_closely": ["<criterion id>", "..."],
              "skimmed": ["<criterion id>", "..."],
              "not_read": ["<criterion id>", "..."],
              "note": "<one sentence: anything you could not open or check>"}}
```

`weight` is the sum of the `w` values of the listed criteria. `test` is a single letter: if one problem
passes two tests, write two entries. `variants` has one entry for every counting criterion. Every
criterion id in criteria.json must appear in exactly one of the three coverage lists. Do not edit any
other file. When defects.json is written, stop.
