# Can the EKW QC pipeline QC the SVC (Cirrus) tasks?

Status: stale. This is one of the oldest docs in the repo and was written for the older `tests/rubric.json` task shape. See the [doc index](../README.md).

Severity levels (sev-2, sev-3) come from the shared grading rules in [QC_FOUNDATION](../../skills/_shared/QC_FOUNDATION.md).

**Question (Luiz):** figure out whether the existing EKW-GDPVal QC pipeline transfers to the
new SVC tasks, which have new domains — and if not, what has to change.

**Verdict:** The **judgment layer transfers well (~70%)**; the **programmatic verifier layer
and the file extractor break out-of-the-box** on SVC's schema; and SVC's **structure — a
leveled DAG, category weights, must-pass gates, negative penalties, exact numeric anchors, and
a shared company corpus — needs a net-new coverage module the EKW pipeline has no analog for.**
So: **reuse the skill's dimension engine, replace the verifier module, add a DAG/anchor module.
Do not run `cycle.py` or `check_verifier.py` against SVC as-is** — they misfire.

Evidence below is from a real run of the actual EKW tooling against a vertical slice of the DAG
(`cirrus-y1-task-5-l1-01-01`, `-l2-01`, `-l3`).

---

## 1. What is structurally new in SVC vs EKW

| | EKW-GDPVal | SVC (Cirrus) |
|---|---|---|
| **Rubric object** | `verifier.json` — flat list of ~6–20 atomic `verifiers[]`, each `assertion.rubric.prompt`, `metadata.classification core/secondary`, weights **sum to 1.0**, soft-min severity | `rubric.json` — `criteria[]` grouped into weighted **categories** (sum to **100**), `must_pass` **gates** (fail ⇒ reward 0), negative **penalty** criteria, `tier: objective/…`, `expected_value` per criterion |
| **Grader** | shared `verifier_runtime.py`, copied verbatim | `grader.py` (LLM judge, claude-sonnet-4-5) — **identical md5 across all 33 tasks**; task-specificity lives entirely in `rubric.json` |
| **Task set** | independent tasks, each own source docs | one **decomposition DAG** over a shared 49 MB single-virtual-company corpus: **L1** (26 atomic leaves, 1 criterion) → **L2** (6 mid, ~14 criteria, 3 cats, 2 gates) → **L3** (1 apex, 100 criteria, 7 cats, 3 gates, 2 penalties) |
| **Folder layout** | `Source Documents/`, `Expert Solution/` | `environment/data/`, `solution/golden/`, `tests/rubric.json`, `PROVENANCE.json` |
| **Answer anchoring** | value-verifiers exist but QC deliberately does *not* re-check the value | rubrics assert **exact computed values** ($2,186,512 start cash; October $1,142,381 trough; P95 peak-to-trough drawdown) that only recomputation can confirm |
| **Data flow** | flat | **cross-level**: L1-01-01 reads `L2-01_Baseline_Cash_Databook.xlsx` — i.e. the *golden output of L2-01*, not raw corpus |

---

## 2. Empirical probes (what actually happened)

- **`check_verifier.py` vs every SVC `rubric.json`** → **false blocking sev-2 auto-reject.**
  It reads `data["verifiers"]`; SVC has `criteria`, so `verifier_spec_parseable` reports
  *"missing `verifiers` list"* (blocking, `reject_at_severity 2`) and the other two checks
  refuse to run. Fires on L1, L2, and L3 alike — a pure schema mismatch, not a quality signal.
- **`extract_task_files.py` vs SVC task dir** → **"nothing to QC."** It resolves only
  `Source Documents/` + `Expert Solution/`; SVC uses `environment/data/` + `solution/golden/`,
  so the extractor prints *"no 'Source Documents/' folder found — nothing to QC."*
- **`cycle.py` (fetch/diff/bundle)** — not applicable. It exists to pull an AI-locked tracker
  CSV + Shared-Drive downloads and *assemble* harbor tasks. SVC tasks arrive **pre-bundled** in
  (a variant of) harbor format, so the whole fetch→normalize→bundle front end has no input.

---

## 3. Component-by-component transfer classification

Legend: **REUSE** (works as-is or one-line path fix) · **ADAPT** (concept transfers, must
re-point to SVC schema) · **REPLACE** (breaks structurally, needs SVC logic) · **ADD** (no
EKW analog) · **DROP** (not needed for SVC).

### Source & Prompt QC — 8 dims → mostly REUSE
| Dimension | Class | Note |
|---|---|---|
| overall_gdpval_fit | REUSE | Cirrus tasks are clearly real finance work |
| instruction_input_consistency | ADAPT | valid, but "inputs" = `environment/data/` at `/app/data/`; path map only |
| self_containedness | REUSE | corpus supplied in-env |
| role_and_deliverable_clarity | REUSE | SVC states role + exact filenames |
| **professional_complexity** | **ADAPT (level-aware)** | **misfires on L1**: atomic single-fact leaves ("which month is the low point?") read as sev-2/3 "mechanical" — but that is the DAG design, not a defect. Needs a level-aware exception |
| feasibility_and_clarity | REUSE | |
| instruction_authenticity | REUSE | Cirrus prompts are human-voiced emails ("From: VP Risk. To: FP&A/Treasury") |
| input_file_authenticity | ADAPT | more important here (shared corpus, leakage); see §4.6 |

### Solution QC — 7 dims → REUSE (domain-agnostic)
format_match · substantiveness · instruction_alignment · **internal_consistency** (high-value
for L3: memo/databook/deck must reconcile) · layout_professionalism · chart_quality ·
visual_insight_surfacing. Only change: extractor path (`solution/golden/`). **Gap:** none of
these verify the golden is *numerically correct vs the corpus* — only that it is internally
consistent and substantive (see §4.4).

### Verifier QC — BREAKS structurally; concepts partly transfer
| Component | Class | Note |
|---|---|---|
| 6 LLM dims (clarity, specificity, construct_validity, outcome_coverage, missing_critical, discriminative_power) | **ADAPT** | concepts apply to any rubric, but they read `assertion.rubric.prompt` / `how_justification`; SVC has `description` + `expected_value`. Re-point required |
| `verifier_spec_parseable` | **REPLACE** | re-point to `criteria` list |
| `verifier_count_in_range` [6,20] | **REPLACE** | wrong for a DAG: legitimate counts span 1 (L1) → 100 (L3). Needs **per-level** expectations, not a fixed band |
| `verifier_outcome_grader_present` | **REPLACE** | looks for `classification==core`/`grading_role==outcome`; SVC uses `tier`/`must_pass`. Different taxonomy |

### Plumbing
| Component | Class |
|---|---|
| `extract_task_files.py` folder names | ADAPT (add `environment/data`, `solution/golden`) |
| `cycle.py` fetch/normalize/bundle + tracker + Shared-Drive | DROP (SVC pre-bundled) |
| harbor-conformance checks (`verifier_runtime.py`, `golden_outputs/`) | ADAPT (SVC uses `grader.py`, `golden/`) |

---

## 4. New coverage SVC needs (no EKW analog) — the high-leverage gaps

1. **Category-weight sanity** — do category weights sum to 100? Any category mis-weighted vs
   its importance (e.g. "Firewall" at 3 vs "Trough/LaR" at 24)?
2. **Gate design** — are `must_pass` gates (G01/B10/W01) the *right* criteria? A gate on a
   non-essential check needlessly zeroes reward; a missing gate lets a fatal flaw score high.
   Highest-leverage single knob in the SVC scoring model; **entirely absent in EKW.**
3. **Penalty design** — the negative criteria (C08b/C08c firewall): magnitude sane? the
   "C08c scored only if C08b does not fire" logic coherent? **Absent in EKW.**
4. **Anchor / `expected_value` groundedness** — recompute the asserted values from
   `environment/data/` (or at least confirm the golden hits them and they agree across levels).
   EKW *deliberately exempts* value-verifiers from scrutiny; for SVC this is the crux and is a
   genuine gap.
5. **Cross-level DAG consistency** — the start-cash anchor ($2,186,512) must be identical
   across L1/L2/L3; L1 leaves must tie to the L2 databook they consume; no contradictions.
6. **Answer leakage (DAG + filenames)** — the L1 deliverable filename
   `L1-01-01_October_Trough_Databook.xlsx` **literally states the answer** ("October Trough").
   Lower-level goldens in the shared corpus can also leak higher-level answers. EKW's
   input-authenticity dim covers this only partially.
7. **`grader.py` conformance** — confirm the shared grader actually implements the rubric's
   scoring/gates/penalties as described (must_pass ⇒ 0, penalties subtract, category weights).
   EKW ships a verbatim runtime, so this was never needed.
8. **Level-appropriateness** — is each node correctly scoped for its tier (atomic L1, mid L2,
   apex L3)? Pairs with the professional_complexity exception in §3.

---

## 5. Recommended QC recipe for SVC

- **Keep** the single-agent skill's dimension engine, severity scale, evidence policy, verdict
  computation, and **all of Source&Prompt + Solution QC** (fix the extractor path; add the
  level-aware complexity exception).
- **Swap** the verifier module: re-point the 6 LLM dims to `criteria[].description/expected_value`;
  **replace** the 3 programmatic checks with an SVC structural checker (criteria parseable;
  category weights sum to 100; ≥1 sane must-pass gate; penalty logic; per-level count sanity).
- **Add** a new SVC module: gate-design, penalty-design, anchor-recompute-from-corpus,
  cross-level DAG consistency + leakage, grader.py conformance.
- **Drop** the `cycle.py` tracker/Shared-Drive/bundle front end.

---

## 6. Proposed ablation to validate the recipe across all 33 tasks

Treat each module above as a togglable component and measure marginal defect-catch:

| Axis | Ablate between |
|---|---|
| A. Stage set | prompt/source · solution · rubric — which earn their cost per level? |
| B. Verifier spec | EKW as-is (baseline: shows the false-reject) → re-pointed → +SVC structural |
| C. Domain priming | generalist judge → finance/treasury-primed |
| D. Grounding | trust `expected_value` → recompute anchors from `environment/data/` |
| E. Scope | per-task isolation → DAG-aware (leakage + cross-level reconciliation) |
| F. Judge | sonnet vs opus; effort tiers |

Slice first (this vertical cut: L1-01-01 + L2-01 + L3), then fan out to the 26 L1 / 6 L2 / 1 L3.

---

## 7. Status
- ✅ Packaged skill `skills/svc-task-qc/` (SKILL.md wiring the §5 recipe; references EKW
  `gdpval-task-qc-with-verifiers/` in place per Luiz's ruling).
- ✅ `scripts/check_rubric.py` — SVC structural checker (replaces the broken EKW
  `check_verifier.py`): 0 false rejects on all 33, catches seeded defects.
- ✅ `scripts/check_dag.py` — cross-level workbook checks (answer/filename leakage,
  anchor consistency). Findings in `WORKBOOK_FINDINGS.md`.
- ✅ End-to-end judge run on `l1-01-01` (`.../qc_review.md`) — surfaced the systemic
  answer-in-input leakage that `check_dag.py` then confirmed workbook-wide.
- ⏳ **Next:** end-to-end judge run on **L3** (exercises must-pass gates, penalties, and
  the L2/L3 anchor *recompute* — the only recipe modules not yet run live), then the §6
  ablation matrix across the slice → fan out to all 33.
