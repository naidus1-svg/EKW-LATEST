# Run the QC on the full SVC task dataset

Status: stale. This is one of the oldest docs in the repo and was written for the older `tests/rubric.json` task shape. See the [doc index](../README.md).

The SVC spec variant is ready: **`pipeline/specs/overlays/svc.md`**.
(Migrated 2026-08-05 from the old full-file fork `gdpval_svc_qc.md` — now a thin
`extends: ../gdpval_task_quality_v18.md` overlay containing only SVC's real deltas,
so base-spec fixes now propagate automatically instead of requiring a manual
re-fork. `gdpval_svc_noeval_qc.md` similarly became `overlays/svc-noeval.md`,
`extends: svc.md`.)

## What it changes vs the base spec
1. **Path remap** — inputs `environment/data`, golden `solution/golden` (SVC layout).
2. **Verifier dims: LLM on, programmatic off.** `verifier_spec_json`→`tests/rubric.json` and
   `verifier_assertion_summary`→evals digest are bound, so the **6 LLM verifier dims run and read
   the rubric + the eval trials** (esp. `verifier_discriminative_power`, which uses the per-model
   reward spread for headroom/discrimination). The **3 programmatic verifier checks are re-gated to
   `task_has_rubric_verifier`** (False on SVC's no-`verifiers[]` rubric) so they skip — no schema
   misfire. NOTE: the LLM verifier dims are EKW-worded ("verifiers"), so treat their findings on
   SVC's `criteria[]` rubric as approximate. Structural rubric QC still via `check_rubric.py`.
   **Requires `<task>/evals/<model>/trial_*/` present** (all 33 integrated: 198 trials).
3. **L1 false-positive dims level-gated** — `overall_gdpval_fit`, `professional_complexity`,
   `input_prompt_leakage` now carry `applies_when: task_is_substantive`, a new deterministic
   precondition (`gdpval_qc/precondition.py`) that reads `[metadata].level` and returns False for
   L1 (skip) and True for L2/L3 (run). Non-SVC corpora are unaffected (no `level` ⇒ True).

## Command (whole dataset, 33 tasks)

**Preferred — via `cycle.py svc-qc`** (added 2026-08-05): wraps the exact
invocation below, defaults `--spec`/`--skip-calibration`/`--no-conversion`/
`--sample-parallelism 3` for you, and — unlike `cycle.py qc` — always tees its
own run to `<out-dir>/_run.log`, so the run gets a timing/audit trail without
you having to redirect it by hand:

```bash
cd pipeline
OPENAI_API_KEY=... GEMINI_API_KEY=... \
.venv/bin/python cycle.py svc-qc \
  /path/to/your/SVC/tasks \
  --out-dir runs/svc_full
```
Pass `--only <id1,id2,...>` to restrict to specific tasks, `--with-conversion` to
re-enable libreoffice extraction (checking a flagged blank-xlsx finding), or
`--spec specs/overlays/svc-noeval.md` when `evals/<model>/trial_*/` isn't
populated yet (re-gates the 4 eval-trial-dependent verifier-quality dims off
instead of running them ungrounded). `-- <extra args>` passes anything else
straight through to `gdpval-assess`.

**Manual invocation** (what `svc-qc` wraps, for reference or if you need a flag
it doesn't expose):
```bash
cd pipeline
OPENAI_API_KEY=... GEMINI_API_KEY=... \
.venv/bin/python -m gdpval_qc.cli \
  --spec specs/overlays/svc.md \
  --corpus /path/to/your/SVC/tasks \
  --output-dir runs/svc_full \
  --skip-calibration --no-conversion \
  --heartbeat-only --sample-parallelism 3
```
Artifacts land in `runs/svc_full/`: `batch_review.json`, `reviewer_queue.csv`, `batch_summary.md`.

## Flags — why
- `--skip-calibration` — the spec's calibration goldens are EKW's, not SVC's.
- `--no-conversion` — text-only judging; reliable (no libreoffice/pandoc dependency). Trade-off:
  formula-driven xlsx sheets extract as blank, so `solution_layout_professionalism` may emit
  false "unfinished/blank" findings (advisory, non-gating). Re-run a node with conversion to confirm.
- `--sample-parallelism 3` — grade 3 tasks at once (raise/lower per API rate limits). Sequential
  (=1) would take ~30–60 min for 33 tasks.

## What to expect
- **L1 leaves no longer false-reject** on gdpval-fit / complexity / prompt-leakage (difficulty
  dims skip L1; prompt-leakage recognizes the by-design prior-run channel).
- **Cross-reference / provenance markers are recognized as legitimate**, not flagged. The
  markers (`transcribe the verified L3 engine`, `ties to the L3-05B golden`, `Golden databook`,
  `(canon)`, …) are intended upstream→downstream data-flow references the tasks rely on — the
  `input_file_authenticity` and `overall_gdpval_fit` gates now carry an SVC exception for them.
  **Do NOT scrub them from the task data.**
- **L2/L3 grade fully** (verifier dims skipped). Watch the real findings surfaced on the slice:
  L3 readout is a multi-slide deck vs the requested one-page; L2 golden may be a summary not the full
  monthly model; L2 headroom-vs-year-end inconsistency.

## Keys
Pass via env (as above) or a `.env` in `pipeline/`. **Rotate the keys shared in chat** —
treat them as compromised.

## Rough cost
**Updated 2026-08-05** after the base spec grew from 27 to 36 dims (the "shift-left
deterministic checks" work) — the estimate below is stale by ~5-10x and kept only
as a historical data point. A real 3-task slice (1 L1 + 1 L2 + 1 L3) on the
current v18.6-based `svc.md` cost **$9.98** (n=141 judge calls) — figure roughly
**$3-4/task average**, so a full 33-task batch is closer to **$100-130**, not
$1-3. Start with `--only <id1,id2>` on a couple of tasks if you want a fresh
cost check before running the whole batch.
