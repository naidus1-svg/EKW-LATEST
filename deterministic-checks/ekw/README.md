# EKW Check B and runner

EKW's build output is not in the shape `BUILD-CONTRACT.md` describes, so the shared checks in
the parent folder cannot read it directly. This folder is EKW's own Check B (did the build
produce a valid task package?) plus the thin translation layer the contract says a
non-conforming benchmark must own, plus one runner that runs everything and writes one table.
Nothing here modifies a shared check. The letters A to E (Check B here, and the B / C / D / E roll-ups
in the summary table) are defined in `../OVERVIEW.md`.

| File | What it does |
|---|---|
| `ekw_check_b.py` | Check B for an EKW harbor task tree. Verifies the package files, every observed `verifier.json` shape, weights, graded-file-to-golden agreement, and the build genre. With `--stage DIR` it writes a lossless contract-shaped copy so every shared check runs on EKW unchanged. With `--rewardkit-out DIR` it also runs the real `pipeline/tools/rewardkit_convert.py` per task as build proof. |
| `ekw_run_checks.py` | One command: Check B, staging, all 12 shared checks, then `summary.csv` and `summary.json` with one row per task, one column per check, and B / C / D / E roll-ups in the letters the trackers use. |

## Run it

```bash
cd deterministic-checks/ekw
python ekw_run_checks.py --all --root C:\ekwqc\_merged274\files --stage C:\ekwqc\_ekw274_stage --out-dir C:\ekwqc\_ekw274_qc
```

- `--root` is the EKW harbor tree, one `task_*` directory per task. The 274-task drop of
  2026-09-10 is at `C:\ekwqc\_merged274\files` on Khiem's machine. **Real, downloadable
  copy**: the
  [`ekw-corpus-274-2026-09-17` release](https://github.com/turing-genai-apps/EKW_QC_pipeline/releases/tag/ekw-corpus-274-2026-09-17)
  - extract its `files/` folder anywhere else and point `--root` at it. No other copy of
  this corpus was reachable outside that one machine before this release; use it instead
  of asking around.
- `--stage` is a derived checking surface, rebuilt on every run. It is not the upload artifact.
  Keep it outside `--root`, and keep the path short on Windows: the drop has input filenames
  long enough to hit the 260-character limit under a deep root.
- `--out-dir` gets one JSON per check, untouched, plus `summary.csv`, `summary.json`, `runs.json`.
- Add `--rewardkit-out C:\ekwqc\_ekw274_rk` to also run the converter per task. Add
  `--checks check_b,rubric_schema,formula_health` to run a subset, `--skip-stage` to reuse a
  stage, `--merge-only` to re-merge existing JSON without running anything.
- A few tasks: `python ekw_run_checks.py task_142 task_15 --root ... --stage ... --out-dir ...`.

Runtime on the 274 with all checks: under 15 minutes with the defaults (`--jobs`/`--shards`
default to one per CPU, sharding each check's task list across processes). `formula_health_check.py`
recomputing 2,794 graded workbook criteria is still the long pole; everything else finishes in
under 20 seconds. A single unsharded run of `formula_health_check.py` alone over all 274 takes
close to 80 minutes; do not run it that way. A handful of workbooks can also take far longer
than the rest under system load, not because of task count; see "Results, 2026-09-14" below for
what to do about a task that will not finish.

## Read the output

`summary.csv` columns: `task_id`, `genre`, `B`, `C`, `D`, `E`, then per check a verdict, a
finding count, and the first finding quoted. Verdicts are `pass`, `warn`, `fail`, `skip`,
`error`. Letter roll-up: any fail wins, then error, then warn, then pass, else skip. `warn` is a
disclosure the check itself does not call a defect (a candidate leak, a lint hit, a Check B
warning); it never blocks on its own. `error` means the check produced no result for that task;
see `runs.json` for its stderr.

`check_b.json` has the full Check B record per task: findings with kind and severity, the
genre and its signals, the verifier summary, graded files, goldens, the staged groups, and the
converter result. The findings catalogue with severities is in `ekw_check_b.py`'s docstring.

## What Check B knows about EKW that the shared checks do not

**Two build genres share one directory layout.** 180 of the 274 tasks are native-harbor
(`cycle.py bundle` output: `task.toml` has `artifacts`, `solve.sh` copies `golden_outputs/` to
`/workspace/output/`, `tests/verifier_runtime.py` vendored). 94 are rewardkit-hybrid
(`schema_version = "1.1"`, `solve.sh` copies `/solution/files/` to `/app/`, Dockerfile copies
`initial_workspace/`, no runtime file). Neither `solution/files/` nor `initial_workspace/`
exists in a hybrid package, so it runs only after `to_rewardkit.py` regenerates both. All 119
tasks of DataOS dataset 608 (Oracle batch 2313, 112 pass, 7 fail) are hybrids, which is the
evidence that the DataOS path converts first. Check B reports the genre per task and treats a
missing runtime file as a fail only on the native-harbor genre, where `tests/test.sh` execs it.

**Seven `verifier.json` source shapes, one foreign schema.** The common
`{type:file, file:{arguments:{path}}}`; `arguments:{paths:[...]}` for `extract_many`;
`source.file` as a list of specs; `{type:files, files:[...]}`; a spec with `path` at its top
level and no `arguments`; `type:directory command:list_files`; and `task_FIN-177`, which has no
`assertion` block at all (criterion text at top level, paths under `metadata.source`). Weights
live at `metadata.weight`. 5,596 assertions are rubric, 4 are deterministic (`task_15`), whose
descriptions are composed the way `to_rewardkit.py` composes them.

**Graded paths come in four conventions** (`output/`, `/workspace/output/`, `/app/`, bare) and
goldens live under `solution/golden_outputs/`. Matching is by basename, with case-insensitive,
Unicode-normalised and cp437-mojibake fallbacks reported as warnings. `task_653`'s two goldens
carry `ΓÇö` on disk where the verifier has an em dash; the converter copies the names verbatim,
so the converted package grades files that do not exist. That is a fail, and it is the kind of
defect this check exists for.

**The staged copy is lossless and traceable.** Criterion names in the generated `judge.toml`
are the verifier names (`v1`, `v2`, ...), with `tag`, `verifier_index`, `grading_role` and
`importance` carried as extra keys the shared checks ignore. One `deliverables_NN/` group per
distinct graded-file set, `files=` as `/app/<basename>` to match the converted package and the
prompt text, native paths kept in `source_paths`. Every generated file is parsed back and
compared to the source before the task is called staged; a mismatch is a fail. Reasoning
documents move to `<task>/reasoning/`, outside `solution/`, so no shared check mistakes them
for deliverables (six of the drop's `Reasoning.docx` files are Markdown text, which the
integrity check would otherwise report as broken goldens; Check B reports them as
`reasoning_doc_invalid_format` warnings instead). `tests/verifier.json` is copied so
`judge_determinism_config_lint.py` reads the native config.

## Known EKW-specific behaviour of the shared checks, and what the runner does about it

- `environment_input_check.py` pattern 1 fires on every EKW task because EKW prompts name the
  deliverables ("Produce the following deliverables in `/app/`:") and describe inputs by content
  only. The runner records the check's own verdict as `native` and, when every pattern-1 hit is
  a graded deliverable and patterns 3 and 5 are quiet, reports `pass` with `reconciled: true`
  and the reason. Any pattern-3 or pattern-5 hit keeps the fail.
- `answer_key_leakage_check.py`'s `_REFERENCE` filename tell fires on seven EKW tasks whose
  INPUTS are reference material (`pdpm_classification_reference_card.pdf`,
  `03_Trading_Options_Reference.pdf`). The tell was calibrated on goldens the solver is told to
  produce. When `_REFERENCE` is the only tell and there is no bracketed pipeline text, the
  runner reports `warn` with the reason and `reconciled: true`; any GOLDEN/SOLUTION/ANSWER/KEY
  tell or bracket leak keeps the fail.
- `deliverable_filename_check.py` and `deliverable_count_check.py` report `skip` on EKW tasks:
  neither recognises that heading. Coverage returns once the heading form is added to both
  (tracked in the shared-check ports on branch `ekw/check-b`).
- `judge_determinism_config_lint.py` flagged 269 of 274 tasks on the native `verifier.json`
  (temperature 1.0, no panel) when this was first measured. That was the real finding first
  reported in `PERPLEXITY-QC-FINDINGS.md`, not noise. It is now 0 of 274: every flagged task's
  `config.temperature` was forced to 0 directly in the source tree on 2026-09-14, independently
  re-verified (fresh lint pass, a 15-task hand sample, JSON validity, and a diff confirming
  exactly 269 files changed and nothing else). Re-run the check yourself before trusting this
  paragraph if the source tree may have moved since.

## Results, 2026-09-14

Full run against the 274-task drop, all 13 checks (Check B plus the 12 shared checks),
consolidated into one `--merge-only` pass so every check's verdict reflects the same staged
tree and the `environment_input` reconciliation (which needs Check B's graded-file list) is
applied consistently. `--rewardkit-out` was not run this pass; see the `task_653` note below.

| Letter | pass | warn | fail |
|---|---|---|---|
| B (build) | 273 | - | 1 |
| C (structural) | 266 | 7 | 1 |
| D (mechanical/rubric) | 237 | 35 | 2 |
| E (formula health) | 233 | - | 41 |

Every fail traces to a named cause, not noise:

- **B**: `task_FIN-177`, the one task on the foreign verifier schema (no `assertion` block).
- **C**: `task_625`, a genuine `environment_input` pattern-1 finding (the instruction names
  `DASH.pdf`/`Ethics.pdf`/`hypertension.pdf`; the actual files are differently named, e.g.
  `new_dash.pdf`) — a real content mismatch, needs a human or Check A pass, not a script fix.
- **D**: `task_5` and `task_574`, `deliverable_filename_check.py`'s REVERSE direction: their
  goldens include a `Reasoning.docx` the instruction text never names, so the forward check
  reports it as ungraded-but-commanded. Minor, matches the pattern the check exists to catch.
- **E**: 41 tasks where `formula_health_check.py` either found a real recomputation defect or
  could not finish in 90 seconds even in isolation with reduced concurrency (measured twice, at
  6-way/45s and 3-way/90s, with the same 14 tasks failing both times: `task_5`, `task_36`,
  `task_56`, `task_78`, `task_136`, `task_160`, `task_175`, `task_311`, `task_576`, `task_599`,
  `task_612`, `task_627`, `task_642`, `task_671`). `task_111` was confirmed hung in true
  isolation (240s, single task, zero concurrent load) — a real `formulas`-engine defect on that
  workbook, not contention. A workbook that will not finish is itself the check's answer for
  that task; it does not mean the run is stuck. Re-verify any of these 14 solo before treating
  them as fully confirmed, since they were measured under known system load.

**Known gap in this pass**: `task_653`'s real Check B defect (its two golden filenames carry
cp437-mojibake on disk; the converted package would grade files that do not exist) is not
re-flagged here because this pass ran without `--rewardkit-out`. It is real — see "Graded paths"
above — just not exercised by this particular run. Add `--rewardkit-out` to see it again.

**What this run does and does not cover.** It runs the original, unmodified shared checks
against the contract-shaped copy this folder's staging layer produces from EKW's native
`verifier.json`. It is cross-verified against a second, independent `verifier.json` parser
(`ekw_verifier_json.py`, branch `ekw/check-b`) on 271 of 274 tasks with identical output; the
staging translation layer is a checking surface, not the artifact anyone uploads. Check A
(content/judgment: does the prompt, golden and rubric actually agree) is not automated by
design, per `OVERVIEW.md` — a task with B/C/D/E all clean still needs a Check A pass before it
is QC-complete.

## Related fix

`pipeline/tools/rewardkit_convert.py`'s validator only looked for `tests/deliverables/judge.toml`,
while `to_rewardkit.py` chunks into `tests/deliverables_01..NN/` above 12 criteria. Nearly every
EKW task chunks, so the validator reported "missing required file" on successful conversions.
It now reads both layouts and checks names, weights and graded files across all of them. That
is what makes `--rewardkit-out` a meaningful build proof.
