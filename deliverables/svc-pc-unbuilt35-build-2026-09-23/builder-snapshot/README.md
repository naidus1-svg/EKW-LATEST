# Builder snapshot used for the 2026-09-23 build

These five files are the exact build chain that produced the 17 packages on the
`svc-unbuilt35-2026-09-23` release. They are a snapshot, not a proposed change to
`pipeline/tools/`: the builder that produced the 2026-09-14 full corpus lives on the
unmerged branch `qc/rubric-converter-failloud` (base commit `a74f6df`) plus uncommitted
edits in one working copy, so `main`'s `svc_pc_batch_convert.py` does not reproduce the
released packages. On `main`, `assemble_task.py` adds a `dvc pull` of the whole corpus to
every SVC Dockerfile, which DataOS cannot reach and `svc_prefilter.py` hard-fails. This
builder ships the needed corpus files in `environment/initial_workspace/` instead
(flat files, or `_corpus_subtree/` folders chosen by relevance scoring).

| File | Role |
|---|---|
| `svc_pc_batch_convert.py` | driver: per task, rubric -> verifier.json -> assemble -> rewardkit |
| `rubric_xlsx_to_verifier.py` | rubric workbook to verifier.json (fail-loud on unmapped columns) |
| `hydrate_environment.py` | picks the corpus files each task needs |
| `assemble_task.py` | Harbor task layout, no `dvc pull` |
| `to_rewardkit.py` | Harbor to DataOS rewardkit layout (`tests/deliverables_NN/judge.toml`) |

One change was made on top of that branch for this build, in
`rubric_xlsx_to_verifier.py`: two exact-match header aliases in `FIELD_HEADER_EXACT`,
`"src"` to `src_refs` and `"lens"` to `category`. Without them the fail-loud check routes
SVC-PC-13-1-0, 13-2-0, 13-5-0, 13-8-0 (a `Src` source-reference column) and 60-1-0 (a
`Lens` column) to messy over informational columns. Exact match means neither alias can
claim a longer header in another rubric family.

## Rebuild one task

Stage the task's Final L2 / Final L3 Tasks folder (see `../source-inventory.csv`) as
`00_fetched/<TASK>/` with subfolders `Prompt/`, `Golden Solution/` (the Drive folder is
named `Golden`; rename it) and `Rubric/`, then:

```
python svc_pc_batch_convert.py --input-root 00_fetched --output-root out \
  --corpus-root "<extracted Cirrus Sleep Full Y1 (FINAL VERSION)>" \
  --scratch-root scratch --only <TASK>
```

The corpus is `Cirrus-Sleep-Full-Y1-corpus.zip` on the same release (1,182 files; the
same zip is committed at `deliverables/svc-pc-40-corpus-fix-2026-09-15/` on branch
`qc/rubric-converter-failloud`, not on `main`). Every one of its 1,182 files is
md5-identical to the corpus this build used. Two tasks also needed a hand hydration step after the build, recorded in
`../hydration-fixes.json`:

- SVC-PC-60-1-0 names its 12 permitted inputs on the rubric's `Input Manifest` sheet,
  which the hydrator does not read. Those 12 exact paths were copied to
  `_corpus_subtree/<path>` and the `_no_input_files_required.txt` placeholder removed.
- SVC-PC-4-4-0 resolved only one named file while its prompt also cites the monthly
  P&Ls, the Q1 dashboard, launch results and the year-1 retrospective. It ships the full
  corpus under `_corpus_subtree/`, the same as its released sibling SVC-PC-4-2-0.

SVC-PC-60-1-0's two rubric files are named `Rubric_Grading.xlsx` and
`Rubric_Response_Criteria.xlsx` on Drive; they were renamed to
`SVC-PC-60-1-0_Grading_Rubric.xlsx` / `_Response_Criteria.xlsx` before the build so the
converter can tell them apart. Content unchanged.
