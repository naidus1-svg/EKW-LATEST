# SVC/Cirrus QC — Onboarding

Status: superseded for task authors by the [SOP](../QC-SOP-first-run.md). Written for the older `tests/rubric.json` task shape. See the [doc index](../README.md).

This is the SVC front's onboarding doc. If you landed here from
[`../ONBOARDING.md`](../ONBOARDING.md) (the EKW front's doc), good — that's
the right router. Everything here assumes you're QCing SVC/Cirrus tasks:
task ids like `cirrus-y1-task-5-l1-01-01`, a decomposition DAG (L1 → L2 → L3)
over a shared company corpus, `tests/rubric.json` (not `verifier.json`), and
`environment/data/` + `solution/golden/` (not `environment/` +
`solution/golden_outputs/`).

**Read order:** this file (workflow + mental model), then
[`QC_APPLICABILITY.md`](QC_APPLICABILITY.md) (the empirical write-up of
*why* SVC needs its own path through the shared engine — keep reading this
even after onboarding; it's the reasoning behind every rule below, not just
historical record), then [`RUN_FULL_QC.md`](RUN_FULL_QC.md) (the exact
command), then [`KNOWN_CALIBRATIONS.md`](KNOWN_CALIBRATIONS.md) and
[`QC_DIMENSIONS_FOR_CREATORS.md`](QC_DIMENSIONS_FOR_CREATORS.md) if you're
also creating SVC tasks (not just reviewing them).

## 1. What this is, in one paragraph

SVC/Cirrus tasks are a **decomposition DAG** over one shared, ~49MB virtual
company corpus: 26 atomic **L1** leaves (1 criterion each) feed 6 mid-level
**L2** nodes (~14 criteria each), which feed a single apex **L3** node (100
criteria). Each node's rubric (`tests/rubric.json`) is **category-weighted**
(weights sum to 100), carries **must-pass gates** (failing one zeroes the
reward) and **negative penalty criteria** — a fundamentally different
scoring model from EKW's flat, weight-sums-to-1.0 `verifiers[]`. Same QC
engine, same severity scale and verdict computation, genuinely different
rubric mechanics and a DAG structure EKW has no analog for.

## 2. The two things you'll actually do

1. **Run QC** — either the shared multi-judge engine (`cycle.py svc-qc`,
   §4) against the whole batch, or the single-agent `svc-task-qc` skill
   against one task at a time (§6).
2. **Adjudicate + fix** — SVC has no fetch/bundle/tracker step (tasks arrive
   pre-bundled) and, so far, no formal Data-OS/reward-kit submission track
   either — feedback goes straight back to whoever built the task, using the
   same deep-analysis TP/FP (true positive or false positive) discipline as the EKW SOP's Phase 2/3 (see
   [`../QC_SOP.docx`](../QC_SOP.docx) if you need that pattern spelled out;
   it's front-agnostic).

## 3. Why SVC can't just reuse the EKW pipeline as-is

Three structural differences break EKW's tooling out of the box — full
empirical detail (including which programmatic checks false-reject and
why) is in [`QC_APPLICABILITY.md`](QC_APPLICABILITY.md); the short version:

| | EKW | SVC |
|---|---|---|
| Rubric shape | flat `verifiers[]`, weights → 1.0 | `criteria[]` in weighted `categories[]` (→ 100), `must_pass` gates, penalty criteria |
| Task structure | independent tasks | decomposition DAG (L1→L2→L3) over a shared corpus |
| Layout | `environment/` + `solution/golden_outputs/` | `environment/data/` + `solution/golden/` |

This is why `check_verifier.py` auto-rejects every SVC task (it looks for
`verifiers[]` and finds `criteria[]`) and why `cycle.py`'s fetch/bundle
commands don't apply (SVC tasks arrive pre-bundled — no tracker, no Shared
Drive step).

## 4. Running the shared engine — `cycle.py svc-qc`

```bash
cd pipeline
OPENAI_API_KEY=... GEMINI_API_KEY=... \
.venv/bin/python cycle.py svc-qc /path/to/your/SVC/tasks --out-dir runs/svc_full
```

Full flag reference and expected findings: [`RUN_FULL_QC.md`](RUN_FULL_QC.md).
The short version of what makes this front-specific:

- **Spec**: `pipeline/specs/overlays/svc.md` by default — an `extends:`
  overlay on the shared base spec (see `../pipeline/README.md` if you want
  the mechanics), carrying only SVC's real deltas: the path remap, the
  `task_is_substantive` gate that skips 3 dims on atomic L1 leaves, and the
  `task_has_rubric_verifier` re-gate that skips the 3 programmatic verifier
  checks (they'd misfire on `criteria[]`). Swap to
  `specs/overlays/svc-noeval.md` when `evals/<model>/trial_*/` isn't
  populated yet — it re-gates the 4 eval-trial-dependent verifier-quality
  dims off instead of running them ungrounded.
- **Defaults**: `--no-conversion` (text-only; libreoffice isn't required,
  but formula-driven xlsx sheets extract blank — a known false "unfinished"
  risk, re-run with `--with-conversion` to confirm a flagged node),
  `--skip-calibration` (the spec's calibration goldens are EKW's, not SVC's),
  `--sample-parallelism 3`.
- **Always logs its own run** to `<out-dir>/_run.log` — unlike `cycle.py qc`,
  you don't need to redirect it by hand to get a timing/audit trail.
- **No cycle directory** — pass the corpus path directly; there's no
  `cycles/<date>/` staging area to scaffold first (nothing to fetch/diff/bundle).

## 5. Prerequisites

- Same pipeline install as the EKW front — see the root
  [`../pipeline/README.md`](../pipeline/README.md) "Quick start"
  (`pip install -e .`, `.env` with `OPENAI_API_KEY`/`GEMINI_API_KEY`).
  `--no-conversion` is the default for this front, so LibreOffice isn't
  required unless you're re-checking a flagged node with `--with-conversion`.
- The SVC task corpus itself, locally — it's not part of this repo (large,
  business-sensitive; see the root `.gitignore`). Point `cycle.py svc-qc` /
  the skill at wherever you keep your own clone/download of it.
- For single-task QC (§6): the `svc-task-qc` skill and, transitively, the
  shared `_shared/QC_FOUNDATION.md` and the EKW dimension files it reuses —
  all same-repo paths now, no extra setup.

## 6. Single-task QC — the `svc-task-qc` skill

For "check just this one task" work, use `../../skills/svc/svc-task-qc/`
(drop `skills/svc/` — and `skills/_shared/QC_FOUNDATION.md`, and
`skills/ekw/gdpval-task-qc-with-verifiers/` for the dimension text it
reuses — into wherever your agent tool loads skills from). It:

- Reuses EKW's severity scale, evidence policy, and verdict computation
  verbatim from `QC_FOUNDATION.md`.
- Reuses EKW's Source & Prompt / Solution dimension *text*, but applies it
  level-aware (an L1 leaf isn't graded as "standalone professional work" —
  that bar only applies at L3; see the skill's own `SKILL.md` for the exact
  per-dimension L1/L2/L3 rules).
- Replaces the verifier stage entirely: `gdpval_qc.tools.check_rubric`
  (structural checks on the category-weighted rubric — weights sum to 100,
  gates present and sane, per-level count sanity) and `gdpval_qc.tools.check_dag`
  (workbook-level: cross-level anchor consistency, answer-in-filename
  leakage) replace EKW's `check_verifier.py`.
- Adapts the 6 EKW verifier-quality LLM dims to read `description` +
  `expected_value` instead of `assertion.rubric.prompt`.

Run the programmatic checks directly rather than eyeballing:

```bash
cd pipeline
.venv/bin/python -m gdpval_qc.tools.check_rubric <task>/tests/rubric.json
.venv/bin/python -m gdpval_qc.tools.check_dag /path/to/your/SVC/tasks
```

## 7. Known gotchas (don't rediscover these the hard way)

- **Cross-reference / provenance markers are legitimate, not leaks.**
  Phrases like `transcribe the verified L3 engine`, `ties to the L3-05B
  golden`, `Golden databook` are intended upstream→downstream data-flow
  references the DAG relies on — never scrub them or flag them as
  task-pipeline markers. `input_file_authenticity` and `overall_gdpval_fit`
  carry an explicit SVC exception for this.
- **A node fed its parent's golden output is by design, not contamination.**
  Every SVC task assumes a correct prior run — the answer-in-input pattern
  that would be a hard leak in EKW is the intended data flow here. The
  `upstream_deliverable_inputs` field lists exactly which input files ARE an
  upstream golden (by content hash) — never flag a file named there.
- **L1 leaves are atomic-by-design.** `professional_complexity`,
  `overall_gdpval_fit`, and `input_prompt_leakage` skip L1 entirely via
  `task_is_substantive` — don't manually override this by grading L1 as if
  it were standalone work.
- **The 6 LLM verifier dims are EKW-worded** ("verifiers") — treat their
  findings on SVC's `criteria[]` rubric as approximate, not authoritative;
  `gdpval_qc.tools.check_rubric`'s structural findings are the reliable signal.
- **`--no-conversion`'s blank-xlsx risk is real, not hypothetical** — a
  formula-driven sheet with no cached values extracts as empty text, which
  can read as "unfinished" to a judge. Re-run the specific node with
  `--with-conversion` before treating that finding as confirmed.
- **Rotate any API key that's ever been pasted into chat.** Treat it as
  compromised the moment it's shared that way.

## 8. Project layout reference

See the EKW front's [`../ONBOARDING.md`](../ONBOARDING.md) §13 for the full
repo tree. The SVC-specific pieces:

```
gdpval-qc/
├── pipeline/
│   └── specs/overlays/    svc.md, svc-noeval.md — SVC's spec deltas
├── skills/svc/            svc-task-qc + 5 task-creation-qc sub-skills
└── docs/svc/              you are here
    ├── ONBOARDING.md              this file
    ├── QC_APPLICABILITY.md        the transfer analysis (keep reading — not just history)
    ├── RUN_FULL_QC.md             the exact cycle.py svc-qc / gdpval-assess invocation
    ├── KNOWN_CALIBRATIONS.md      calibration notes for creators + reviewers
    ├── QC_DIMENSIONS_FOR_CREATORS.md   the creator-facing counterpart to svc-task-qc
    ├── TASK_CREATION_CLAUDE.md    rules for building SVC tasks that pass QC the first time
    └── TASK_CREATION_USAGE.md     how to invoke the task-creation-qc sub-skills
```
