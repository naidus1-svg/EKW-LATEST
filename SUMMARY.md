# Round 53 Checker Bug Fixes: Summary

Three checker bug fixes, each verified by running the check on real task data from
`C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready` before and after.

## Bug 1: deliverable_filename_check.py -- read-scope exemption for FORWARD direction

### What changed

`deterministic-checks/deliverable_filename_check.py`:
- Added `_load_solution_files()` (line 369): returns the set of basenames in
  `solution/files/`, or None if that directory is missing or empty.
- Added `_environment_filenames()` (line 380): returns basenames of all files
  under `environment/initial_workspace/` (recursive).
- Added `_is_readscope_source()` (line 391): route 2 checks `solution/files/`
  membership (absent = read-scope); route 1 fallback checks `/app/_corpus_subtree/`
  prefix or environment existence.
- Modified `analyze_task()` (line 675-720): tracks original paths per basename,
  loads solution/env file sets, and exempts read-scope entries in the FORWARD
  check loop (classified into `excluded_judge_artifacts` with a note, not silently
  dropped).

### Before/after (full 600-task corpus)

Command: `python deliverable_filename_check.py --all --root C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready --out report.json`

- Before: 582 pass / 18 fail
- After: 595 pass / 5 fail
- Delta: +13 pass, -13 fail. Exactly the 13 affected tasks flipped fail to pass;
  0 regressions (no other task changed status). The 5 remaining fails are real
  defects (genuinely missing filenames, not read-scope sources).

### Deviation from report

None. Used route 2 (solution/files/ intersection) as the primary fix, with route 1
(environment/initial_workspace/ + _corpus_subtree/ prefix) as fallback for the rare
task without solution/files/ (9 of 10 sampled tasks have it).

## Bug 2: undisclosed_terminology_check.py -- named-source-origin exemption

### What changed

`deterministic-checks/undisclosed_terminology_check.py`:
- Added `SOURCE_NAMING_DIRECTIVE_RE` (line 389): matches 12 source-naming
  directive phrases found across the 9 affected tasks' instruction.md files
  ("pricing matrix", "cite business-readable", "read the schemas", "named
  source", "source-room", "from your files", etc.).
- Added `IDENTIFIER_SHAPE_RE` (line 404): `^[A-Z]{2,}[-_]?[0-9A-Z]*` for the
  allcaps-prefix + code-suffix identifier pattern.
- Added exemption check in `_scan()` (line 1031-1035): suppresses a finding
  when the cue is "allcaps-prefix" or "wildcard", the term matches the
  identifier shape, and instruction.md contains a source-naming directive.

### Before/after

Command: `python undisclosed_terminology_check.py C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready --task <TID> --json report.json`

Affected 9 tasks (29 false positives):
- Before: SVC-PC-12-2-0 (14), SVC-PC-20-1-0 (1), SVC-PC-25-1-0 (3),
  SVC-PC-25-2-0 (1), SVC-PC-25-6-0 (2), SVC-PC-25-7-0 (4), SVC-PC-28-3-0 (1),
  SVC-PC-80-6-0 (2), SVC-PC-93-0-0 (1) = 29 findings
- After: all 9 tasks clean (0 findings)

Must-stay-flagged regression check:
- SVC-PC-63-4-0: 6 findings before, 6 after (unchanged). Its instruction.md
  mentions "price matrix" in passing but has no source-naming directive, so
  the exemption does not fire.

Full 600-task corpus:
- Before: 527/600 clean. After: 553/600 clean.
- Delta: +26 tasks clean, 0 regressions (no task gained findings). The 17
  additional cleared tasks beyond the 9 in the report are the same false-
  positive class (allcaps-prefix data values with source-naming directives).

### Deviation from report

Used the narrower single-step variant ("if instruction.md contains ANY source-
naming directive AND the flagged token matches the identifier pattern, suppress")
as the report recommends for lower effort. Did not implement the prefix-to-source
cross-reference (step 2 of the two-step variant) because the narrower variant
correctly preserves SVC-PC-63-4-0's 6 confirmed-real findings (its instruction.md
has no source-naming directive), and the full-corpus run confirmed 0 regressions.

## Bug 3: compound_criterion_check.py -- slash-list and comma-list-enum splitters

### What changed

`deterministic-checks/compound_criterion_check.py`:
- Added `_split_slash_list()` (line 948): post-pass that splits a clause
  containing 2+ ` / ` patterns (whitespace-slash-whitespace between letters)
  into N items. Requires 2+ slashes (3+ items) to confirm an enumeration,
  not a single path/citation/ratio.
- Added `_split_comma_list_enum()` (line 977): post-pass for the Expected:
  region that splits a clause containing 3+ comma-separated short noun phrases
  (each <= 4 words, no main verb in items 2+) into N clauses. Strips Oxford
  "and" before the last item. Uses `re.split(r"(?<!\d),(?!\d)", clause)` to
  avoid splitting thousands separators ($300,000).
- Modified `_split_clauses()` (line 944): calls `_split_slash_list()` after
  `_drop_noncheckable()`.
- Modified `count_clauses()` (line 1147): applies `_split_comma_list_enum()` to
  the exp region only (inside the Expected: guard, not the req region).

### Before/after (target criteria)

Command: direct call to `count_clauses()` on the 3 affected criteria.

- SVC-PC-80-6-0/a11: before 1 clause (clean), after 3 clauses (flagged).
  Slash-list: "Shopify customer / HubSpot Record ID / Zendesk requester_id" -> 3.
- SVC-PC-80-6-0/c2: before 1 clause (clean), after 3 clauses (flagged).
  Comma-list enum: "orders, line items, retail price" -> 3.
- SVC-PC-77-8-0/c20: before 1 clause (clean), after 4 clauses (flagged).
  Comma-list enum: "cash preserved, time-to-realize, operational/growth cost, and
  a lowest-to-highest-regret rank" -> 4.

### Before/after (full 600-task corpus)

Command: `python compound_criterion_check.py C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready --json report.json`

- Before: 101 clean / 914 fail / 2592 warn (3506 total findings)
- After: 75 clean / 1202 fail / 3020 warn (4222 total findings)
- Delta: +288 fail, +428 warn = +716 new findings, 0 regressions (no task lost
  total findings). The 716 new findings are latent compound criteria the splitter
  previously missed; spot-checked samples (SVC-PC-19-0-0 f11/c01/c49,
  SVC-PC-59-0-0 c003/c004, SVC-PC-88-0-0 str-07, SVC-PC-93-0-0 r09a,
  SVC-PC-6-1-0 r49) are all genuinely multi-attribute criteria.

Unaffected-task regression check (5 tasks outside the affected list):
- SVC-PC-6-1-0: +1 new (r49, 15 required tab names -- real compound)
- SVC-PC-14-1-0: unchanged
- SVC-PC-88-0-0: +1 new (str-07, 3 excluded content types -- real compound)
- SVC-PC-93-0-0: +7 new (r09a-e, 5 required attributes each -- real compound)
- SVC-PC-25-1-0: +1 new (c33)

### Deviation from report

1. Slash-list requires 2+ ` / ` patterns (3+ items), not every single ` / `.
   The report's suggested regex `r'\s/\s(?=[A-Za-z])'` splits every single
   occurrence, which the first full-corpus run showed causes ~453 over-splitting
   false positives on citation references ("Cash_BalanceSheet / BS_Monthly"),
   ratios, and path-like expressions. The 2+ threshold matches the comma-list
   enum's own 3+ item requirement and correctly handles a11 (2 slashes = 3 items).
2. Comma-list enum uses `re.split(r"(?<!\d),(?!\d)", clause)` instead of
   `clause.split(",")` to avoid splitting thousands separators ($300,000).
   The first full-corpus run found this immediately: c08's "$300,000/yr
   ($150,000 each" was wrongly split into "$300" and "000".
3. Comma-list enum applied to exp region only (inside Expected: guard) as the
   report specifies. Slash-list applied to both regions (general), since the
   report describes it as "a new pass (does not conflict with existing
   comma/conjunction logic)."
