SVC-PC-19-0-0 corpus fix, 2026-09-17
====================================

SVC-PC-19-0-0's live environment was missing the entire `Accounting` category from
the Cirrus Sleep Full Y1 shared corpus. Its `_corpus_subtree` had Customer_Support,
Finance, HR, Operations, and My Drive - alice.chen, but no Accounting folder at all.
The golden (`Liquidity_Facility_Decision_Readiness_Pack.docx`,
`Cash_Conversion_Liquidity_Model.xlsx`, `Treasury_Working_Capital_Policy_Memo.docx`,
`Closing_Decision_Message_CEO_Board.docx`) references bank statements, trial balance,
and AR/AP aging as source records. None of those exist anywhere in this task's
environment without this folder. This is the same defect shape as
`deliverables/svc-pc-40-corpus-fix-2026-09-15/` (missing corpus hydration), a fresh
instance on a task not in that batch's 40.

This is fixed locally (folder copied byte-identical from the shared corpus, 88 files,
0 diffs against source) and already applied to the live `03_dataos_ready` checkout on
this machine. This folder is how anyone else gets the same fix without re-running the
full pipeline build or re-extracting the full 42MB shared corpus zip.

Contents
--------

- `Company-Shared-Drive-Accounting.zip` (1.7MB, 88 files) - the real
  `Company Shared Drive/Accounting/2021/` tree from the Cirrus Sleep Full Y1 corpus
  (`AP_Aging`, `AR_Aging`, `Bank_Statements`, quarterly `Close/*_Trial_Balance.xlsx`,
  `Year_End/*`), copied byte-identical, tested with `zipfile.testzip()`.

How to use
----------

1. Extract `Company-Shared-Drive-Accounting.zip` into
   `pipeline/data/svc_pc_qc/03_dataos_ready/SVC-PC-19-0-0/environment/initial_workspace/_corpus_subtree/`
   (or wherever you keep your working copy). It unpacks to a
   `Company Shared Drive__Accounting/` folder, matching the naming convention the
   other four corpus_subtree folders on this task already use.
2. Confirm the result has 88 files under that folder and includes
   `2021/Bank_Statements/Bank_Statement_2021-01.pdf` through `-12.pdf`,
   `2021/AP_Aging/AP_Aging_2021-01.xlsx` through `-12.xlsx`, `2021/AR_Aging/` (same
   12 months), and `2021/Q1..Q4/Close/Q*_Trial_Balance.xlsx`.

This is the same recipe as `svc-pc-40-corpus-fix-2026-09-15`, scoped to one task and
one missing category instead of a full-environment rebuild, since only Accounting was
absent here.

Not covered
-----------

This fix does not address SVC-PC-19-0-0's other open findings (rubric-instruction
mismatch, 75 irrelevant HR PDFs pushing the environment over 10MB, unpinned
harbor-rewardkit, golden timeline inconsistency, missing task.toml metadata). Those
are separate, real content/config decisions, not a corpus-hydration gap.
