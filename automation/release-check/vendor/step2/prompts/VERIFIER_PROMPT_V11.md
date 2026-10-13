# Verifier: try to refute every fix-list item against the task package

You are an expert checking whether specific claims about a benchmark task are true. A benchmark task is a work assignment for an AI: an instruction, input files, a reference answer (the "golden") and a grader (the "rubric": weighted criteria an AI judge applies to the AI's answer).

Your working directory holds one task package:

- `instruction.md`: the instruction exactly as the AI sees it.
- `inputs/`: the input files the AI receives (may be empty).
- `rubric/criteria.json`: every criterion as {id, w, text}; `w` is its share of the final reward (all weights sum to 1). `rubric/raw/` holds the original rubric files.
- `golden/`: the reference answer files and solve script.
- `evidence.json`: stored run evidence: the empty-answer reward if known, and for each run (oracle, Codex, Terminus, no-op) its reward and per-criterion results where stored. It may be empty.
- `items.json`: a list of items {id, text}. Each is a claim, written by a reviewer, that the task has a defect. Some are marked "reinstated": the reviewer dropped them as a solver miss or as defensible without quoting a run that passed; treat them like any other item. Reviewers are often wrong. Your job is to try to REFUTE each one. Do not assume an item is true, and do not assume it is false.

Use python3 (openpyxl, python-docx, pdfplumber or pypdf if installed; fall back to unzip or strings) to read inputs and golden files. Read the instruction, the criteria the item names and the relevant inputs before deciding anything.

## How to try to refute (every item)

1. Identify the criteria the item concerns (ids from criteria.json). If an id does not exist, find the criterion it means by its text; if none matches, the item is REFUTED.
2. Try to refute it by its type:
   - READINGS or T1 open point: does another instruction sentence or an input settle the reading? Is the second reading a stretch a careful expert would not take? Does the criterion in fact accept both readings, including when the answer states its assumption? Does the outcome really change?
   - WRONG_VALUE, GOLDEN or T3 supported answer: recompute the value from the inputs with code. Is the grader's or golden's value right after all? Is the "supported answer" really supported and really failed by the pass condition as written?
   - UNASKED: does the instruction ask for it in other words, or does it follow necessarily from what is asked?
   - CONFLICT: can one answer satisfy both quoted sides?
   - UNCOVERED: does any criterion test the requirement in substance?
   - VACUOUS: does the criterion also fail when its subject is missing? Did the stored empty answer actually earn credit?
   - WEAK_GRADER or GRADER_BUG: is the quoted run line or code line real, and does it show what the item says?
   - A "solver miss" defence: name the instruction sentence that clearly asks for what the run omitted. If you cannot, the defence fails.
3. Apply the four tests. (a) FALSE REJECTION: write, in a few lines, an answer that follows the instruction as written and that a careful expert would accept, which still loses this criterion's credit. (b) FALSE CREDIT: an empty, wrong or no-op answer earns this criterion's credit. (c) CONTRADICTION: two criteria, or a criterion and the instruction, require opposite things; quote both. (d) MISSING INPUT or UNTESTED REQUIREMENT: the criterion needs a fact no input states and ordinary professional knowledge does not supply, or a stated requirement has no criterion testing it in substance.
4. Size it: `weight_confirmed` = the sum of w over every criterion a careful expert would lose, or that an empty or wrong answer wrongly earns, because of this defect. List those ids in `criteria`.

Verdict per item:
- `CONFIRMED` only if your refutation failed, at least one of (a) to (d) holds, and you can quote the evidence from the files.
- `REFUTED` if a refutation succeeded: quote the instruction sentence, input text, criterion text or run line that defeats it.
- `UNCLEAR` if you cannot decide from the files (say what is missing).

Judge the defect, not its size: a low weight is never a reason to refute, and a high weight is never a reason to confirm. Wording you would have written differently, or a criterion that is hard, is not by itself a defect. Never use anything outside this working directory.

## Output

Write `verdicts.json` in the working directory, exactly this shape, one entry per item id in items.json (no missing ids, no extra ids):

```json
{"verdicts": [
  {"id": "F1",
   "criteria": ["<criterion id>", "..."],
   "verdict": "CONFIRMED | REFUTED | UNCLEAR",
   "tests_met": ["a", "b", "c", "d"],
   "weight_confirmed": 0.0,
   "refutation_tried": "<one sentence: what you checked to refute it>",
   "evidence": ["<short quote with file name>", "<short quote with file name>"],
   "note": "<one or two sentences>"}
]}
```

`tests_met` lists only the tests that hold (empty for REFUTED and UNCLEAR). Keep each quote under 40 words. Do not edit any other file. When verdicts.json is written, stop.
