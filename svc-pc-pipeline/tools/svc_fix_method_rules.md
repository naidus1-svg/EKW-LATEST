METHOD_VERSION: v8.1-2026-09-22-class-fix

# SVC-PC fix + verify rules (single source)

This file is the ONE place the fix and verify rules live. `svc_v7_lane_runner.sh` embeds it verbatim in
every rebuild, targeted-fix and adversarial-verify prompt; `svc_build_directed_briefs.py` embeds it in every
brief; `svc_build_upload_zip.py` and `svc_bundle_upload.py` refuse any task whose verify record was not made
under the METHOD_VERSION on line 1. Change a rule here, bump METHOD_VERSION, and every task verified under
the old rules is automatically refused at ship time until it is re-verified. That is how a prompt change
reaches every task instead of only the ones that happen to run next.

Why each rule exists is the 2026-09-22 batch_of_18 return: 8 of 18 passed; the 10 rejects carried 23 majors,
11 the SAME defect left unfixed, 9 introduced by our own fix, 1 a partial fix, 1 a never-flagged criterion,
1 a seat disagreement. Full analysis: `ekw/batch18-return-analysis-2026-09-22.md`.

## R1. Match the fix to the finding category

- **1.4 over-enforcement** (a criterion fails what the instruction allows, forbids what it permits, pins one
  reading it leaves open): DELETE or LOOSEN the criterion. Shrink.
- **1.5 coverage hole** (an instruction requirement no criterion enforces): ADD one criterion that checks the
  one missing fact against the value you re-derived from `environment/initial_workspace/`. A hollow answer
  must fail it and the golden must pass it. Adding is correct here. The old blanket "never add a criterion"
  rule made every 1.5 hole unfixable and is withdrawn.
- **1.5 compound criterion** (one criterion bundling independently-variable facts): SPLIT into one-fact
  criteria, preserving total weight.
- **1.1 golden wrong**: recompute the value from source and fix the golden. Never loosen a criterion to fit a
  wrong golden.
- **1.3 ambiguity**: edit `instruction.md` AND `tests/task_prompt.txt` identically to state the one required
  reading.
- Never add qualifying text to an existing criterion to patch it; every added qualifier so far became the
  next round's finding.

## R2. Fix the CLASS, not the cited instance

GPT reads the whole task fresh every round. When it cites one missing item (one refund, one holder, one
period, one file), the defect is the criterion FAMILY, not the item. Enumerate every item in that family from
the source files and make the rubric cover all of them. 15-1-0 took a 1.5 in every round since batch15 on a
different missing refund/credit item each time because each fix closed only the cited one.

## R3. Re-audit everything you rewrote

A section you rewrote is new surface, and GPT audits it cold. After any fix, re-audit every criterion,
golden cell and instruction line you changed as if it were never reviewed. 10-4-0 (demand-driver rewrite)
and 2-6-0 (cap-table rewrite) were rejected on findings their own rewrites created.

## R4. Full per-criterion audit every time

Audit EVERY criterion in EVERY judge dir against `instruction.md`, not only the ones a finding named:
over-enforcement, coverage, scope (a clause meant for one tab must say so). Output a per-criterion table:
criterion id | what it grades | instruction line | verdict | action.

## R5. The golden must satisfy every criterion's letter

Open the golden and confirm its own content passes each criterion at strict reading, especially any
criterion demanding a locator (section, page, paragraph), a stored formula value, an exact figure, or a
citation. 16-1-0 r009b: the golden cited a file with no locator its own criterion required.

## R6. Checkable under the pinned grader

DataOS grades with rewardkit 0.1.7 (MarkItDown/Pandas reader). A criterion needing a stored computed value is
uncheckable if the reader extracts a broken formula identically to a live one. Reword or delete it.

## R7. Hard rules (unchanged)

Expected values only in `judge.toml`; at most 15 criteria per judge dir; LF line endings; never lower
difficulty; golden scores 1.0 on 2 oracle runs.
