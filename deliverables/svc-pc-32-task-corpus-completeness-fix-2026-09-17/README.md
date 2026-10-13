SVC-PC 32-task corpus-completeness fix, 2026-09-17
===================================================

A systemic audit of all 600 SVC-PC tasks in `03_dataos_ready` (see
`CORPUS-COMPLETENESS-AUDIT.md` in this folder) found 32 tasks missing an entire
top-level Company Shared Drive category that the task's own judge.toml, golden,
or instruction.md text cites specific files from. Same defect shape as
`svc-pc-19-0-0-corpus-fix-2026-09-17/` (a fresh instance found while
investigating a QC blocker), generalized to the whole corpus so no one else
hits the same missing-source-data problem.

All 40 missing-category instances across the 32 tasks are fixed locally
(byte-identical copies from the shared corpus, verified with a recursive diff
against source: 0 mismatches). This folder is the record of what was found and
fixed; no new corpus zip ships here because the source is already published in
`deliverables/svc-pc-40-corpus-fix-2026-09-15/Cirrus-Sleep-Full-Y1-corpus.zip`.

Contents
--------

- `CORPUS-COMPLETENESS-AUDIT.md` - the full audit: method, the 10 real
  Company Shared Drive categories, the 40 confirmed gaps with exact cited
  files and real corpus paths, rejected candidates (looked like gaps, were
  not), and the two different-shaped populations not covered here (2 tasks
  with no Company Shared Drive at all; 138 tasks that hydrate via a flat-file
  model instead of `_corpus_subtree`).
- `fixed-pairs.csv` - the 40 (task, category) pairs actually applied, one row
  each.

The 32 tasks (40 gaps): SVC-PC-14-2-0 (HR, Operations, Vendors), 19-0-0
(Vendors), 19-2-0 (Vendors), 19-5-0 (Accounting, Vendors), 19-6-0
(Accounting), 19-7-0 (Vendors), 2-3-0 (Operations, Vendors), 2-5-0 (Finance),
24-4-0 (Vendors), 26-0-0 (Accounting, HR, Vendors), 26-3-0 (Vendors), 3-5-0
(Vendors), 33-5-0 (Finance), 33-7-0 (Finance), 35-0-0 (Vendors), 42-0-0
(Vendors), 42-5-0 (Vendors), 42-7-0 (Vendors), 53-2-0 (Accounting, HR,
Operations), 58-0-0 (Vendors), 58-3-0 (Accounting), 58-5-0 (Accounting),
58-8-0 (Vendors), 59-0-0 (Vendors), 62-4-0 (Vendors), 62-5-0 (Vendors), 62-6-0
(Customer_Support), 8-4-0 (Operations), 8-5-0 (Finance), 81-3-0 (Finance),
93-2-0 (Vendors), 93-5-0 (Vendors).

By category: Vendors 21, Accounting 6, Finance 5, Operations 4, HR 3,
Customer_Support 1.

How to use
----------

1. Extract `deliverables/svc-pc-40-corpus-fix-2026-09-15/Cirrus-Sleep-Full-Y1-corpus.zip`
   once, anywhere (it is the same shared corpus root, `Company Shared Drive/<Category>/...`).
2. For each row in `fixed-pairs.csv`, copy that category's folder from the
   extracted corpus into
   `<task_id>/environment/initial_workspace/_corpus_subtree/Company Shared Drive__<Category>/`,
   matching the naming convention every other category folder on that task
   already uses.
3. Confirm the copied file count matches the `files` column in
   `fixed-pairs.csv` for each pair.

Not covered
-----------

- SVC-PC-10-5-0 and SVC-PC-73-1-0 have no Company Shared Drive folder at all
  in their corpus subtree (a different, more severe shape). Separate triage.
- 138 tasks hydrate via flat files directly under `environment/initial_workspace/`
  instead of a `_corpus_subtree`. Whether those working sets are complete is a
  separate audit this pass did not perform.
- A second tier of 174 task-category pairs had a concept-level term match
  (e.g. "payroll", "trial balance") but no specific absent filename; these
  were deliberately not treated as confirmed gaps because the cited concept
  usually lives in a present category or in `System Exports - 2021Q4`, not the
  absent Company Shared Drive folder. See audit section 8 for the reasoning
  and the borderline cases flagged for manual review.
