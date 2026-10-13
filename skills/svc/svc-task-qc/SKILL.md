---
name: svc-task-qc
description: >-
  Quality-check (QC) a single SVC/Cirrus harbor task locally: Source & Prompt
  QC, Solution QC, and SVC Rubric QC (category-weighted rubric with must-pass
  gates + penalties), plus cross-level DAG checks. Use when asked to QC, review,
  or check an SVC (cirrus-y1-task-*) task, solution, or rubric.
---

# SVC / Cirrus Task QC

Grade **one** SVC harbor task directory (`cirrus-y1-task-*`) and return an
actionable, reviewer-facing verdict. **You are the judge** — you read the task's
files and grade each dimension yourself, applying the severity scale, evidence
policy, and verdict computation from the EKW skill (this skill reuses that
machinery verbatim; see *Shared engine* below).

This skill is the SVC-adapted sibling of `gdpval-task-qc`. It exists because SVC
tasks differ from EKW tasks in three ways that break the EKW tooling
out-of-the-box (see [`../../../docs/svc/QC_APPLICABILITY.md`](../../../docs/svc/QC_APPLICABILITY.md) for the empirical write-up):

1. **Different rubric object** — `tests/rubric.json` with `criteria[]` grouped
   into weighted `categories[]` (sum to **100**), `must_pass` **gates**
   (fail ⇒ reward 0), and negative **penalty** criteria. NOT EKW's flat
   `verifiers[]`. → EKW's `check_verifier.py` false-rejects every SVC task; use
   `gdpval_qc.tools.check_rubric` (pipeline/.venv/bin/python -m …) instead.
2. **A decomposition DAG** — L1 (atomic leaves, 1 criterion) → L2 (mid) → L3
   (apex, 100 criteria) over a shared company corpus. → level-aware grading +
   cross-level checks.
3. **Different layout** — `environment/data/` (sources) + `solution/golden/`
   (golden) + `tests/rubric.json`, not `Source Documents/` + `Expert Solution/`.

## Task directory layout (SVC harbor)

```
cirrus-y1-task-5-<node>/
  instruction.md            # the prompt (verbatim) + environment notes
  task.toml                 # [metadata] level = L1|L2|L3, category, ...
  environment/data/         # SOURCE files (the QC "input files")
  environment/skills/       # vendored doc skills (not QC'd)
  solution/golden/          # GOLDEN deliverables (the "expert solution")
  solution/solve.sh         # oracle: copies graded deliverables to /app/output/
  tests/rubric.json         # the rubric (category-weighted; gates; penalties)
  tests/grader.py           # shared LLM-judge runtime (identical across tasks)
  PROVENANCE.json           # per-file source hashes
```

The prompt IS in the folder here (`instruction.md`) — unlike EKW, you don't need
it pasted. The rubric IS in the folder (`tests/rubric.json`) — likewise.

## Shared engine

**Grading protocol, severity scale, evidence policy, confidence demotion, and
verdict computation** are in one front-agnostic file:
[`../../_shared/QC_FOUNDATION.md`](../../_shared/QC_FOUNDATION.md). Read it and
apply it unchanged. (Same-repo path — both fronts now live in one repo, so this
is no longer the fragile cross-repo reference it used to be when EKW-GDPVal and
SVC were separate project directories.)

**Dimension text reused from EKW `gdpval-task-qc`, verbatim** — read from
[`../../ekw/gdpval-task-qc-with-verifiers/`](../../ekw/gdpval-task-qc-with-verifiers/):

- `source-and-prompt-qc.md` — the 8 Source & Prompt dimensions.
- `solution-qc.md` — the 7 Solution dimensions.
- `verifier-qc.md` — the 6 rubric dims adapted in stage 3b.

**The extractor and both fronts' structural checkers are canonical modules in
the shared pipeline package** (`pipeline/gdpval_qc/tools/`), not per-skill
script copies — invoke them via the pipeline's own venv:

```bash
cd pipeline
.venv/bin/python -m gdpval_qc.tools.extract_task_files <task_dir> \
    --source-dir-names environment/data --solution-dir-names solution/golden
.venv/bin/python -m gdpval_qc.tools.check_rubric <task_dir>/tests/rubric.json --level L1|L2|L3
.venv/bin/python -m gdpval_qc.tools.check_dag <tasks_dir>   # workbook-level, once per batch
```

## Stages

Run in order; each is independently runnable.

### 1. Source & Prompt QC — REUSE, but DAG/level-aware (Change Set 1)

Grade `instruction.md` + `environment/data/` with the EKW Source & Prompt
dimensions. **First read `task.toml` `[metadata] level` (L1/L2/L3).** The EKW dims
assume each task is a *standalone, substantive, professional engagement with no
answer in its inputs*. SVC L1/L2 are decomposition nodes that are intentionally
atomic, minimal, and fed prior correct results — so apply the "standalone
realistic work" family **only at the apex (L3)**, relaxed at L1/L2:

- **`professional_complexity`** — L1 → `applicable=false` (atomic-by-design is not
  a defect) · L2 → advisory only, judged at the *workstream* bar (a workstream may
  be semi-mechanical) · L3 → full blocking as written.
- **`overall_gdpval_fit`** — L1/L2 → do **not** flag "benchmark-shaped"; instead
  judge *"is this a valid decomposition step of the apex?"* (advisory) · L3 → full
  blocking (the apex must read as real delegated work).
- **`input_file_authenticity`** — keep the corpus-realism check at L2/L3 (they read
  the Cirrus corpus). **Suppress the "inputs contain the answer" hard-fail for any
  node whose inputs are upstream golden outputs** (PROVENANCE `source_kind:corpus`
  pointing at a parent golden): each SVC task *assumes a correct prior run*, so
  answer-in-input is by design, **not** a synthetic/leak marker.
- **`input_prompt_leakage`** (if run from the v18.5 superset) — same exemption:
  the prior-run channel is by design. Retain it only for a genuine leak — the
  answer stated in the **prompt text** itself, or a value the **apex is supposed to
  derive** appearing in the apex's own raw inputs.

### 2. Solution QC — REUSE, level-aware (Change Set 1)
Grade `solution/golden/` with the EKW Solution dimensions.
- **`solution_substantiveness`** — L1 → a single correct figure stated explicitly
  **is** fully substantive; do not apply the "skeleton / <2-line section" pattern.
  L2/L3 → full bar.
- **`solution_internal_consistency`** — especially high-value at L3 (memo ↔
  databook ↔ deck must reconcile).

### 3. SVC Rubric QC — REPLACE + ADAPT
The EKW verifier stage does not apply. Instead:

**3a. Programmatic (run, don't eyeball):**
```bash
pipeline/.venv/bin/python -m gdpval_qc.tools.check_rubric <task>/tests/rubric.json
```
Emits 7 findings — `rubric_spec_parseable`, `rubric_category_weights_sum`,
`rubric_criteria_category_valid`, `rubric_gate_present_and_sane`,
`rubric_count_for_level`, `rubric_points_penalty_coherent`,
`rubric_criteria_not_blank` — in the standard finding shape. Fold them
straight into the verdict. Level is inferred from the `task` name; pass
`--level` to force it.

**3b. LLM dims (ADAPT the 6 EKW verifier dims to the SVC schema).** Apply the
concepts of `verifier_rubric_clarity`, `_specificity`, `_construct_validity`,
`_outcome_coverage`, `_missing_critical_dimensions`, `_discriminative_power`
(from EKW `verifier-qc.md`) — but read each criterion's **`description`** +
**`expected_value`** (SVC has no `assertion.rubric.prompt`). Keep the EKW
calibration guardrails (check the golden before flagging an always-fails or
over-strict criterion; a criterion covered across a *combination* is not a gap).
- **`_discriminative_power` — extraction-node exception.** For a node fed its
  parent's golden (answer provided by design), "a competent reader passes" is the
  intent — do **not** flag it as low-discrimination. Grade whether the criterion
  correctly separates a *right* extraction/derivation from a *wrong* one; advisory.

### 4. SVC-native coverage — Change Set 2 (LOW-RISK CUT)

**Design rule (Luiz, risk-minimizing):** QC must *verify what is deterministically
checkable* and *delete flags that are wrong* — but must **not add new LLM-judged
dimensions to the automated verdict**, because each new judgment injects judge noise
(bias, run-to-run inconsistency) — the very failure mode the research documents. So
Change Set 2 is split: **4a is gating (deterministic only); 4b is optional
human-review, never auto-acting.**

#### 4a. Deterministic gates — KEEP (no LLM judgment; reproducible)
- **`check_rubric.py`** (already folds in): weights=100, ≥1 gate present, not
  over-gated, count-for-level, penalty-coherence, criteria→category valid.
- **`check_dag.py`** (workbook, once): **`svc_anchor_consistency`** — a shared anchor
  is byte-identical everywhere it appears (a divergence is an objective
  contradiction); plus the extraction/derivation **construct-map** (data only, no
  verdict).
- **`svc_upstream_golden_correctness` — DETERMINISTIC anchors only.** Recompute
  ledger-derived values from `environment/data/` and check they tie (e.g. start cash
  $2,186,512 = checking $2,036,512 + savings $150,000). This is arithmetic against
  source — it *reduces* uncertainty. **Do NOT gate on modeled/stochastic anchors**
  (L2 projected trough, L3 Monte-Carlo P5/P95): they can't be reproduced exactly, so
  routing them into the verdict would *add* uncertainty. Flag them for a human
  (§4b), do not auto-fail.

#### 4b. Optional human-review prompts — DO NOT add to the automated verdict
These are real concerns, but answering them requires LLM judgment, which would add
noise. Surface them for a human to consider; **never auto-act, never gate.** (If a
future need justifies the risk, promote one at a time with calibration data.)
- `svc_gate_design` — are the `must_pass` gates the *right* criteria? (deterministic
  part — present / not-over-gated / golden-passes — is already in 4a; only the
  "*right?*" judgment lives here.)
- `svc_aggregation_fcp` — could a criterion bank credit while its prerequisite is
  absent (flat-sum False Credit Propagation)?
- `svc_penalty_design` — penalty magnitude & conditional logic sane?
- `svc_category_balance` — any category mis-weighted vs the prompt?
- `svc_construct_labeling` — does a rubric *claim* derivation for a value the inputs
  already provide? (uses the §4a construct-map as its input.)
- `svc_level_appropriateness` — is each node scoped right for its tier?
- `svc_grader_conformance` — does `grader.py` implement gates/penalties/weights + the
  untrusted-data boundary? (mostly code-inspectable; verify once, out of band.)

## Workflow

```
- [ ] 0. Read task.toml -> note the level (L1|L2|L3). Read instruction.md + rubric.json.
- [ ] 1. Source & Prompt QC (EKW dims; DAG/level-aware per Change Set 1)
- [ ] 2. Solution QC (EKW dims; L1 substantiveness relaxed)
- [ ] 3a. Run gdpval_qc.tools.check_rubric; fold findings
- [ ] 3b. Rubric LLM dims (adapted; extraction-node discrimination exception)
- [ ] 4a. Deterministic gates: check_rubric + check_dag anchor-consistency + deterministic-anchor recompute (these count toward the verdict)
- [ ] 4b. Optional human-review prompts (gate/FCP/penalty/balance/construct-labeling/level/grader) — surface, do NOT gate
- [ ] 5. Compute verdict (EKW tiers) from deterministic gates + reused EKW dims only; list 4b items separately as "for human review"
```

Compute the verdict and emit the review using the EKW `SKILL.md` output format.
Title it `# QC review — <task_id> · SVC`.

## Workbook-level pass (run once per workbook)
`gdpval_qc.tools.check_dag <tasks_dir>` (pipeline/.venv/bin/python -m …) — cross-level checks over all 33 nodes: anchor
consistency (`svc_anchor_consistency`), an **extraction/derivation map** for
`svc_construct_labeling` (answer-in-input is expected by design — reported, not
failed), and L1→L2 provenance. Feeds the per-task SVC-native dims above.
