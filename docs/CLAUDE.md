# EKW-GDPVal Project — QC Guidelines

> This is the **EKW front's** process doc within the two-front `gdpval-qc`
> repo (see the root [`../../README.md`](../../README.md)) — it carries
> Luiz's personal working conventions for that front specifically, not a
> repo-wide contributor guide. The SVC/Cirrus front's equivalent is
> [`../svc/ONBOARDING.md`](../svc/ONBOARDING.md) and its companions in
> `docs/svc/`.

- Always begin every message by addressing the user by name: "Luiz".

Rules extracted from **Project Omega Guide V2** for use in any generation or review work on this project.

---

## What This Project Is

EKW-GDPVal is a benchmark dataset of long-horizon, document-grounded knowledge-work tasks used to evaluate and RL-fine-tune LLMs. Each task represents ~7–10 hours of expert effort across 9 economic domains (government, finance, professional services, health care, manufacturing, retail, information, real estate, and one more).

**My role:** Quality Control — reviewing tasks and verifier outputs for the 19 RL-usable tasks, and contributing to ongoing task/verifier quality improvement.

---

## Task Quality Rules

### A good task must be:
- **Rooted in real work** — something a practitioner actually does, not a hypothetical
- **Dependent on domain depth** — correct completion requires specialized knowledge a generalist would miss
- **Resistant to shortcuts** — the right answer hinges on exceptions, tradeoffs, or context that naive reasoning glosses over
- **Designed for headroom** — floor is reachable by weak models; ceiling rewards genuine expertise

### Prompt writing rules:
- Describe **what** to determine, never **how** (no method names, formulas, domain jargon, or column references)
- State constraints a model might miss or violate (sources to trust, what not to use, how to resolve conflicts)
- Every prompt needs 2+ deliverable artifacts (`.docx`, `.xlsx`, `.pdf`, or `.pptx`) under `/workspace/output/`
- Target productive middle ground: not over-constrained, not excessively vague
- **Platform form (Harbor rubric, see `docs/harbor-task-rubric.md`):** no roleplay/persona opener; every
  input named by absolute path (`/workspace/data/<file>`); every deliverable by absolute path; a **schema
  block** for each structured deliverable (sheets / required columns / granularity / live formulas — the output
  contract, not the method); canary line. "What not how" still governs the *method*; the schema block is the
  *output contract* and is required, not a hint.

### Headroom techniques:
- Multi-layered scenarios requiring integration of several domain considerations
- Trade-off decisions (competing priorities, real tensions)
- Real-world complexity (incomplete data, conflicting inputs, genuine uncertainty)
- Open-ended deliverables where quality of reasoning can vary

---

## Source Document Rules

Each task must have **3+ source documents**. They must:

- **Cross-reference each other** — shared entity IDs, joinable keys; task should be unsolvable from any single file
- **Match format to genre** — `.xlsx` for tabular data, `.docx` for memos/policies, `.pdf` for signed/finalized docs
- **Contain NO leaked answers** — no column or label that directly states what the task asks to determine
- **Be internally consistent** — dates, totals, names, IDs agree across all files
- **Be realistic** — no sequential IDs (INV-0001), no round numbers, no perfectly regular timestamps
- **Not include unreferenced files** — every file must be referenced in the prompt

---

## Verifier / Rubric Rules

### Structure:
Each task needs a **minimum of 6 verifiers** in `tests/verifier.json` — **no upper limit** (a thorough rubric with many checks is not a defect). Use:
- `openai/gpt-5.4` as judge model listed **three times** in `config.models` (the runtime takes a majority over
  the list — one sample flipped identical golden bytes between 0.915 and 0.985), `temperature: 1.0`,
  `reasoning_effort: "xhigh"`
- Classification: `"core"` or `"secondary"` (not both on same concept)
- Weights must sum to exactly **1.0**
- Mean weight of `outcome` verifiers ≥ mean weight of `process` verifiers

### Core vs Secondary:
- **Core** — non-negotiable requirements; a solution failing this is not solved. Failed core rubric = minimum severity-2 in reward computation.
- **Secondary** — distinguishes stronger from weaker correct solutions (formatting, completeness polish, organization)
- Ask: "If only this verifier failed, would an expert still call the task solved?" Yes → secondary. No → core.
- Be deliberate: too many core verifiers lets judging noise sink valid solutions

### Each rubric must be:
1. **ATOMIC** — tests exactly one tightly coupled concept
2. **OBJECTIVELY TESTABLE** — concrete pass and fail anchors; two judges should converge
3. **SELF-CONTAINED** — inline every required value, threshold, column, entity, section, comparison target. Never write "as required by the prompt" or "per the instructions"
4. **GROUNDED** — anchored in the task prompt, source documents, golden solution, or clearly implied success conditions
5. **NON-OVERLAPPING** — no two rubrics grade the same concept against the same artifact
6. **INDEPENDENT** — gradeable without assuming another verifier passed; no cascading language
7. **CONSTRUCT-VALID** — tests the real quality, not a proxy concept
8. **ANTI-HACK** — cannot be passed by keyword stuffing or superficial structure
9. **SIDE-EFFECT AWARE** — at least one verifier penalizes materially unsolicited additions (unrequested files, tabs, sections, claims)

### Delete verifiers that:
- Only check file existence (this is implicit when the source extraction runs)
- Only check filename without evaluating task quality
- Simply restate deliverable format without meaningful quality check
- Substantially overlap with another verifier on the same artifact

### Add expert-created verifiers for:
- Domain-specific tradeoffs an expert would naturally weigh
- Implicit constraints obvious to practitioners but not spelled out in the prompt
- Known failure modes in the field
- Nuanced judgment calls where a generic answer sounds plausible but is materially wrong

### Mechanical-proxy checklist — ask this before writing or accepting ANY criterion

**Before a criterion becomes an LLM-judged rubric prompt, ask: is there a
deterministic, code-level check that verifies this fact instead — zero judge
variance, nothing to talk a judge out of?** A criterion whose PASS condition
can be fully captured by a JSONPath assertion against structured
source-command output isn't real LLM-judgment territory; grading it with a
judge anyway is strictly worse (variance, cost, gameable by wording) for zero
benefit. This is the single highest-leverage lever available for making a
task simultaneously **harder** (a mechanical check can't be talked around
the way a text-only judge sometimes can) and **more confidently gradeable**
(deterministic output, not a per-run judgment call) — see
`docs/ekw-svc-comprehensive-review.md` §0 for the review-side mirror of this
same discipline (auditing whether an *existing* criterion's source command
can even see what it claims to check).

Established mechanical proxies already available in this corpus's source-
command library — check whether one of these fits before defaulting to an
LLM-judged prompt for the underlying fact:

| If the criterion needs to check... | Use this source command instead of trusting `extract_text` | Because |
|---|---|---|
| A chart/visual actually exists in a workbook | `xlsx.has_chart` (`chart_count`, `max_series_count`; reads the `xl/charts/chartN.xml` parts directly) | `extract_text`'s `read_only=True` load never loads chart objects at all — deleting every chart is invisible to a text-only judge |
| A slide's visual content (images, fills) | **No template command exists yet** — `pptx.py` ships `extract_text` only. Two tasks carry their own `extract_visual_structure` (task_130, task_120); port one into `pipeline/templates/dataos_harbor/` (then `sync_templates.py --write`) before referencing it | Slide text extraction can't see whether a required image/graphic is actually present |
| A value is genuinely computed, not typed in | `xlsx.formula_summary` asserting `$.n_formula_with_refs >= N` **and** `xlsx.formula_authenticity_scan` asserting `$.formula_share_all >= S` (both layout-independent; floors derived from a minimal compliant model, together ≥ 0.10 of weight). **Do not use the pinned `xlsx.formula_authenticity_check`** unless the instruction fixes the sheet and range: it raises on a sheet name the solver did not use | A hardcoded literal and a live formula's cached result read back identically once extracted to text — even when numerically identical to the "right" answer |
| Text sits inside a Word structured-document-tag / content control | `docx.extract_text` (canonical template version — fixed in place, not a new command) | Confirmed 2026-09-17 (task_122): both python-docx's high-level paragraph/table API and its own run-level `.text` skip anything wrapped in `<w:sdt>`/`<w:sdtContent>` — a Google-Docs-suggestion artifact hid a golden's own 18%-hurdle sentence from the judge entirely. Older per-task copies of `docx.py` predate this fix; re-copy from the canonical template rather than patching in place |
| Two `verifier-requirements.txt` files disagree on a pinned version, silently defeating the pre-warmed venv | `deterministic-checks/verifier_requirements_pin_mismatch_check.py` (registered as `verifier_requirements_pin_mismatch`) | Confirmed on 35/54 tasks in one batch (2026-09-17): `environment/verifier-requirements.txt` and `tests/__verifier_lib/requirements.txt` pin different exact versions of the same package (pypdf, litellm) — `dependency_pin_check.py` only catches *unpinned* installs, not two pinned files disagreeing with each other. Also check a task's Dockerfile directly if it pins a package inline instead of via `environment/verifier-requirements.txt` — the check reports `skip` there, not a false clean |
| A multi-deliverable task has no criterion cross-checking the deliverables against each other | `deterministic-checks/cross_deliverable_consistency_check.py` (registered as `cross_deliverable_consistency`) | Confirmed on 50/54 tasks (2026-09-17): every criterion sources exactly one deliverable file, so a memo and a workbook could contradict each other and both still pass. Static proxy only (flags "no criterion touches 2+ files"), not a semantic check — a task that comes back "pass" may still be doing this badly for the *specific* facts that matter, so treat a pass as "not obviously absent," not "definitely sufficient" |
| Multiple files' evidence without truncation bias toward one document | `filesystem.extract_many` (asymmetric budget — the primary/submission file gets the larger share) | An even per-file budget split can silently truncate the very document under scrutiny while reference files get full space |
| A sheet/table too large to fit any extraction budget | A dimensions/row-count check (e.g. `sheet.max_row`) rather than a judge reading truncated text | No text budget can hold a 17,000-row sheet; a text-based criterion on it can never pass by design |
| Weight sums, duplicate/compound criteria, judge panel size, determinism config | The `deterministic-checks/` suite (see its `README.md`) — `compound_criterion_check.py` alone flagged 284 fail + 489 warn across 1,140 criteria in one 54-task batch (2026-09-17), 0/54 tasks clean | Already built, already calibrated on this corpus — don't re-invent as a judge prompt. **Gotcha**: these scripts expect a flat `task_X/{tests,environment,instruction.md,...}` layout; a downloaded review batch is often nested as `task_X/rev_N__NNNNN/task_files/...` instead — build a symlink-only staging tree (`stage/task_X -> task_X/rev_N__NNNNN/task_files`) before invoking, don't assume "0 criteria found" means the check doesn't apply |

**General heuristic for spotting a new candidate**: if a criterion's PASS
text names a concrete artifact type (chart/image/table/formula), a count or
existence fact, or a numeric value directly derivable from the source data,
try the mechanical-proxy question first. Reserve actual LLM judgment for
what a machine genuinely can't assess: reasoning soundness, whether an
explanation is convincing, whether tone/framing suits the audience,
consistency across a long narrative. If no existing source command covers a
new mechanical-proxy candidate, that's a real, worthwhile addition to build
— see `xlsx.formula_summary` / `xlsx.formula_authenticity_scan` for the template to follow (a small,
adversarially-tested source command added to the canonical template
`pipeline/templates/dataos_harbor/__verifier_lib/` and mirrored with
`pipeline/tools/sync_templates.py --write` — never a one-off hack in a single task, and never edited in a copy).

---

## Reward System (reference)

| Severity | Band | Interpretation |
|----------|------|----------------|
| 0 | [0.90, 1.00] | All core rubrics passed cleanly |
| 1 | [0.75, 0.89] | Minor core issues |
| 2 | [0.40, 0.74] | Moderate core failure |
| 3 | [0.00, 0.39] | Severe core failure |
| 4 | [0.00, 0.00] | Fatal error during verification |

- Final reward = quality linearly remapped into severity band
- Core reward uses **weighted soft-min** (τ=0.10) — dominated by the weakest rubric
- A failed core rubric is automatically tagged severity ≥ 2 even if judges report severity 0
- Secondary rubrics only influence reward at severity 0 or 1 (w_sec = 0.10 or 0.03)

---

## RL Signal Classification (current 19 tasks)

| Filter | Count | Signal type |
|--------|-------|-------------|
| Bandgap (max/min trials ≥ 2 tiers apart) | 7 tasks | Clear win/loss labels; policy sharpening |
| Productive-band (≥2 trials in sev-1∪sev-2) | 13 tasks | Dense rubric-level gradient; early exploration |
| Overlap | 1 task (GO-35907bf4) | Both |

---

## Known Issues to Check During QC

1. **`how_justification` quality** — many were auto-converted and are generic/confusing; flag and improve
2. **`output_variables.json` / `Reasoning.docx` / `*.round*` in golden solutions** — must be removed; the platform's `no_extraneous_files` check fails the task (enforced by `deterministic-checks/harbor_rubric_gate.py`)
3. **Skills directory** — Gemini trials ran without skills enabled; note when reviewing trajectory quality
4. **Verifier ceiling tasks** — 3 tasks where expert + Gemini both score near 1.0 (no headroom)
5. **Severe failure tasks** — 20 tasks where Gemini fails on every trial; candidates for stronger model eval (Opus 4.8, GPT 5.5)
6. **Candidate-surfacer overridability** — the "advisory candidate, judge confirms or dismisses" pattern (`consistency_ledger.py` → `instruction_input_consistency` / `solution_internal_consistency`; `verifier_source_verifiable` hint → `verifier_construct_validity`) may share the same failure mode fixed for `input_file_authenticity` / `verifier_rubric_clarity` in iteration 5 (see `calibration-iteration4-decomposition-n4` memory) — a downstream LLM subtask can freely override a correct candidate back to "no issue." Not yet confirmed broken; audit before assuming it needs the same authoritative-floor treatment.

---

## Project Layout

This doc covers the **EKW front** in detail — see the repo root
[`../../README.md`](../../README.md) for the two-front picture (this repo
also QCs the SVC/Cirrus front; its process doc is
[`../svc/ONBOARDING.md`](../svc/ONBOARDING.md)). The EKW-relevant layout:

```
gdpval-qc/
├── pipeline/        THE QC tool — single source of truth. Do not run any other copy.
│   ├── gdpval_qc/   the package; gdpval_qc/tools/ holds the canonical checker/extractor modules
│   ├── specs/       the base spec (currently v18.6) + specs/overlays/ (front-specific `extends:` deltas)
│   ├── .venv/       invoke as: pipeline/.venv/bin/python -m gdpval_qc.cli ...
│   ├── tools/       EKW-only helper scripts (bundle, drive-fetch, dataos-submission, reward-kit convert, harbor_evals — the Harbor-beta eval-request automation)
│   ├── templates/   harbor runtime template (harbor/: test.sh + verifier_runtime.py + verifier_lib/) shipped verbatim into every bundled task
│   ├── cycle.py     the cycle driver (new|fetch|diff|bundle|qc|dataos|svc-qc|evals-package|evals-upload|evals-enqueue|evals-status|evals-fetch|report|ledger|close|status)
│   └── VERSION      pinned version + reconciliation note
├── cycles/          gitignored, created locally as you work — cycles/latest -> diff baseline; cycles/INDEX.md catalogs cycles
│   └── <YYYY-MM-DD>/    full design QC (whole batch) — 00_fetched 01_diff 02_bundle 03_evals_package 03_evals_raw 03_evals 04_qc 05_report MANIFEST.md
├── skills/ekw/      all EKW QC skills (verifier / golden / prompt-input / task); skills/svc/ + skills/_shared/ are the other front's
├── reference/       stable docs a skill reads at runtime (e.g. dataos_recipe/RECIPE.md, harbor_evals_quick_guide.md — the source runbook cycle.py evals-* automates)
└── automation/      exportable Claude Code scheduled-task routines (e.g. ekw-qc-cycle)
```

## QC Cycle Workflow (2x/week)

Always run the pipeline from `pipeline/` in this repo — never an older EKW-GDPVal working-tree copy.

Restructured 2026-08-13: Internal QC and External QC (Automated) are now one continuous pass —
see `docs/QC_SOP.docx` Phase 1 for the full human-facing procedure (Steps A–L). This section is
the code-facing summary; the SOP is authoritative for exact click-paths/prompts.

1. **Fetch**: export whichever tracker(s) this batch's tasks come from as CSV to
   `cycles/<date>/tracker_<front>.csv` (or the legacy single-tracker `cycles/<date>/tracker.csv`,
   front=ekw by default) — every tracker is policy-blocked from automated reading. Fronts today:
   `ekw` (EKW OTS Experts Project), `svc` (SVC Project), `intake` (the newer Intake form) — see
   `pipeline/fetch.config.json`'s `fronts` registry for per-front column mapping + `ready_values`
   (currently "ready for eval" for all three; svc/intake column headers not yet confirmed, so
   fetch falls back to fuzzy id/status/link detection for those two until a real export is seen).
   `cycle.py fetch <date> [--front ekw|svc|intake]` reads every tracker CSV present and writes one
   `00_fetched/<id>/` per ready task, tagged `_row.json["front"]`, plus a combined `_TO_FETCH.md`
   grouped by front. Per-cycle drops go in `cycles/<date>/_exclude.txt` (one id per line). Files
   are downloaded **manually** from the Shared Drive for ekw/intake-front tasks (links are
   org-locked; gdown/connector can't bulk-pull) — svc-front tasks arrive pre-bundled instead (see
   the "QC for the SVC task family" section of the SOP), nothing to download there. After dropping
   a bulk download, run `cycle.py normalize <date>` (flattens `Task NNN` → `00_fetched/<id>/`)
   then `cycle.py check <date>` (verifies all ready tasks have files).
2. **Diff** vs previous cycle → `cycle.py diff <date>` writes `01_diff/changes.md` (new/changed/unchanged).
3. **Bundle (harbor + Data-OS, in one step)**: `cycle.py bundle <date>` assembles harbor tasks in
   `02_bundle/task_<id>/` from each `00_fetched/<id>/` for ekw/intake-front tasks (instruction.md
   from `_row.json` Prompt, environment/data + Dockerfile, solution/golden_outputs, **solution/solve.sh**
   oracle, the shared harbor runtime copied verbatim from `pipeline/templates/harbor/`, task.toml,
   tests/verifier.json from a shipped `00_fetched/<id>/verifier.json` or the `Rubric` cell); for
   svc-front tasks (which arrive pre-bundled) it registers the already-complete package verbatim
   instead of re-assembling it, flagging `svc-not-prebundled` if one arrives incomplete. Trailing-junk
   rubrics auto-recover; malformed/empty rubrics are flagged distinctly. Every run writes
   `02_bundle/_INCIDENTS.md` for the experts team. `bundle --only <ids> --out <dir>` produces a
   targeted sub-bundle. **In the same run**, bundle also reward-kit-converts every assembled task
   (what used to require a separate `cycle.py dataos` call) via `pipeline/tools/to_rewardkit.py`
   — which now supports SVC's `tests/rubric.json` shape (flat `criteria[]`/`points`/`must_pass`,
   no folded-in `categories[]` weight — see the function-level comment in `to_rewardkit.py` for
   why) alongside EKW's `tests/verifier.json` — drafting the one-pager (`QCR_<name>_<DDMMYYYY>.docx`),
   `#TFRL_QC` Slack message (TFRL is the human QC team), and `SUBMISSION.md` into `cycles/<date>/dataos/`. A task whose golden
   dir holds a single un-extracted archive converts to a *silently empty* `solution/files/` —
   detected and excluded with an explicit reason rather than a false "converted". `cycle.py
   dataos-standalone <bundle_dir> <out_dir>` runs this same conversion for a bundle outside any
   cycle folder (single task or a dir of `task_<id>/` dirs) — useful since the phases aren't
   necessarily run by the same person.
3b. **Create the Data-OS dataset + upload** (manual, per batch — Data-OS uploads are never
    automated by this pipeline): create/reuse a Data-OS dataset and upload every task under
    `cycles/<date>/dataos/rewardkit/` into it. This must happen **before** 3c, not after, despite
    the natural reading order — it's what populates the dataset 3c runs its evaluations against.
3c. **Run the full External QC (Automated) pass**: per task, `Run evaluation` × 3 (Claude Code /
    Claude Opus 4.8 / high; Codex / GPT 5.6 Sol / high; Oracle) then `Agent Trajectory` QC × 2
    (Claude Code + Codex runs only, never Oracle; GPT 5.6 Sol / medium), then bulk-download each
    task's Evaluations outputs + Verifications results. Already automated via the `dataos-qc-run`
    skill (`skills/ekw/dataos-qc-run/SKILL.md`, drives a parallel Chrome-automation fleet per
    `reference/dataos_recipe/RECIPE.md`), writing `dataos_qc_runs/<dataset_name>/task_<label>/{task_<label>_evals.zip,
    task_<label>_verifications_results.json}`.
3d. **Import the Data-OS artifacts**: `cycle.py dataos-evals-import <date> <dataos_qc_runs_dir>`
    (implementation: `pipeline/tools/dataos_evals_import.py`) unzips each `_evals.zip`, remaps its
    `claude-code_*`/`codex_*` trial folders into `03_evals/task_<id>/evals/<model>/trial_1/`
    (`oracle_*` kept alongside under `oracle/`, excluded from reward stats), and copies
    `verifications_results.json` alongside — the same artifacts that used to feed only a separate
    deep-analysis pass now also ground Internal QC's own eval-dependent dims in step 4, via the
    existing `build_verifier_assertion_summary()` (no engine change needed — it already reads any
    `evals/<name>/trial_*/verifier/reward.json`, no special naming convention required).
4. **QC**: `cycle.py qc <date>` runs the full base spec (currently v18.6, 36 gates across task /
   solution / verifier design) against `03_evals/` — now real eval-grounded thanks to 3d, so the
   4 eval-dependent verifier-quality dims (construct validity, outcome coverage, missing critical
   dimensions, discriminative power) are graded on real signal instead of skipped ungrounded; the
   old separate local k=1 trial ask is gone. Writes `batch_review.json`, `reviewer_queue.csv`,
   `batch_summary.md` to `04_qc/`. Run it **once** per change when iterating (LLM-judge noise is
   real — read the findings and their severities, not just the verdict label); reserve a 3-run
   consistency pass for final verification of a consequential change.
4b. **Joint feedback**: `cycle.py joint-feedback <date>` merges `04_qc/reviewer_queue.csv`'s own
    issue rows (both blocking and cosmetic — the literal file a reviewer opens, not a
    re-derivation from `batch_review.json`) per task with each task's
    `03_evals/task_<id>/verifications_results.json` FAILED checks into one combined
    candidate-complaint list per task, written to
    `cycles/<date>/joint_feedback/task_<id>_packet.json` (which also names the 4 required source
    locations — reviewer_queue.csv rows, verifications_results.json, task artifacts under
    `02_bundle/task_<id>/`, and eval trajectories under `03_evals/task_<id>/evals/`) — no
    auto-dedup across the two sources, both listed side by side for the (human-run) TP/FP (true positive / false positive) +
    actionable-guidance session-starter prompt in the SOP to adjudicate **once** per batch against
    all 4 required inputs, instead of once per source. Upload target
    and tracker link are documented in the SOP's embedded prompt, not here (they're prompt
    content, not pipeline config).
5. **Report**: `cycle.py report <date>` collects artifacts into `05_report/`; study + share.
6. **Close**: `cycle.py close <date>` advances `cycles/latest` so the next run diffs against it.

Steps 1–3 are what the 2x/week Claude Cowork routine runs, then it stops (everything from 3b on is manual/skill-driven).

- **Alternate: direct Harbor-beta eval request** (added 2026-08-07, automates
  `reference/harbor_evals_quick_guide.md` — no more asking an external run owner to hand-run it).
  This is a separate mechanism from 3b–3d above — useful for an ad-hoc/standalone eval request
  outside the main 2x/week cycle (e.g. a one-off batch handed over directly), not part of the
  main cycle's eval-grounding path, which now runs through Data-OS (3b–3d) instead.
  `cycle.py evals-package <date> --batch-prefix PREFIX` repackages `02_bundle/task_<id>/` into the
  Harbor-beta upload layout (`<prefix>-task_<id>/v1/harbor_task/`, `solution/` stripped — the
  agent under eval must never see the golden — plus the guide's sanitization checklist as hard
  gates: `/workspace/output` referenced, `storage_mb<=10240`, non-empty `environment/data/`,
  non-empty `tests/test.sh`, UTF-8 text with no NUL bytes) into `03_evals_package/`.
  `cycle.py evals-upload <date>` then `gcloud storage cp`s it to `gs://long-horizon-beta/tasks/`
  and writes `.harbor_package_ready` markers (prints the guide's pre-flight checklist and asks for
  typed confirmation first). `cycle.py evals-enqueue <date> --base-url URL --k N --models-file PATH`
  always dry-runs first; add `--live` only once the dry run is clean to actually spend — it fetches
  `gdpval_INTERNAL_WORKER_SECRET` fresh via `gcloud secrets versions access` (never written to
  disk/logged), POSTs the real enqueue, saves `_eval-runs.csv`, and removes the ready markers
  immediately after. `cycle.py evals-status <date> --batch-prefix PREFIX --expected-trials N [--wait]`
  polls GCS until every trial is done. `cycle.py evals-fetch <date>` downloads the finished trials
  straight into the exact layout `cycle.py evals` already expects. Implementation: `pipeline/tools/harbor_evals.py`.

- Task interface: https://bench.turing.com/ekw/ · datasets on Google Drive (Slack links).
- Task structure: `task_<id>/{task.toml, instruction.md, tests/, environment/, evals/}`.
- To update the pipeline: bump `pipeline/VERSION`. (The original EKW-GDPVal project reconciled `pipeline/` against a separate `platform/scripts/gdpval_qc` mirror — that mirror isn't part of this repo; if that reconciliation process still applies to your workflow, do it against the source working tree, not here.)
- **Verifier-gate calibration (2026-07-09, settled):** the verifier gates in the base spec (applied at the time to v18.5 + the now-removed slim/final_qc/eval_gates_only variants of the deprecated sample-qc track) carry calibration from the expert Approved-Task re-review. False-positive exceptions: check the golden before flagging an always-fails / 0%-pass rubric OR an over-strict rubric (golden passes ⇒ hard/demanding, not broken); a soft quantifier is fine when backed by an enumerated set; a criterion covered across a combination of rubrics is not a gap; a missing side-effect / output-dir check is sev1 polish, not gating. Hard-fails added: extract_text can't verify formula/no-hardcoding claims; advisory wording ("should/preferably/such as"); aggregate-only passing when per-item detail is required; guardrail-only rubrics that never grade positive quality. Specs backup in `pipeline/specs.backup-*/`. Full rationale in memory `expert-calibration-verifier-gates`. task_48/116 (requiring a memo to restate derived counts) remain a known judgment-boundary case that flickers into needs_review — route to a human, do not tune away.

---

## File Format Conventions

All output deliverables go in `/workspace/output/`. Source paths in verifier.json are workspace-relative (strip `/workspace/` prefix). Valid source types: `xlsx`, `docx`, `pdf`, `pptx`, `csv`, `md`, `text` — all with `extract_text` command.

---

## Harbor Task Format (strict) — the standard for ALL QC fronts (EKW + DermOTS)

Every task we ship must be a **runnable** harbor package, not just a rubric. Upload validators enforce this. A conforming `task_<id>/` (or DermOTS case task) has:

```
task_<id>/
├── instruction.md
├── task.toml                    # [metadata]; benchmark_type is intentionally omitted (see below)
├── environment/
│   ├── Dockerfile
│   └── data/                    # source docs (EKW) or the built world snapshot (DermOTS)
├── solution/
│   ├── solve.sh                 # Oracle: reproduces ONLY the graded deliverables in /workspace/output/
│   └── golden_outputs/          # ONLY the graded deliverables solve.sh copies — no Reasoning.docx / expert-only files (platform `no_extraneous_files`)
└── tests/
    ├── test.sh                  # generic verifier entrypoint (copied verbatim)
    ├── verifier_runtime.py      # generic runner (copied verbatim) — also emits reward-details.json
    ├── verifier_lib/            # generic verifier library (copied verbatim)
    └── verifier.json            # the rubric (the only task-specific file in tests/)
```

At grade time the runtime writes, to `/logs/verifier/`: `reward.txt` + `reward.json` (the numeric reward harbor grades from) **and `reward-details.json`** — the **reward-kit** per-check breakdown the harbor platform surfaces as the task's "tests". Without `reward-details.json` (and no `ctrf.json`) the platform's verifier panel renders empty and the run reads as "no tests ran" even though grading succeeded. `verifier_runtime.py` translates each verifier into one reward-kit entry (`name -> {kind, score, criteria[], judge}`); a judge auth failure then shows as N errored tests rather than nothing. **The reward number always came from `reward.json`; `reward-details.json` is what makes the checks visible/accepted.**

Rules:
- **`solve.sh` copies only what the verifier grades.** A deliverable = a golden file the verifier reads back as an `output/<name>` source path. Never copy expert-only artifacts (e.g. `Reasoning.docx`) into output/ — a side-effect-aware verifier can penalize the unsolicited file.
- **`test.sh` + `verifier_runtime.py` + `verifier_lib/` are shipped verbatim, never hand-edited per task.** EKW copies them from `pipeline/templates/harbor/`; DermOTS copies them from `convert-to-harbor/task_template/` (both via the bundler/converter — do not paste by hand).
- **`benchmark_type` is deliberately left out.** The platform's enum is all code/SWE benchmarks (`swe-bench`, `program-bench`, …); none fits document-grounded knowledge work, and the field is warning-only (non-blocking). Leaving it out keeps `task.toml` honest. If a target platform ever makes it a hard error, add it as a bundler flag rather than mislabeling.
- The canonical, upload-ready reference task is `pipeline/data/sample_corpus/task_11/`.

Both fronts already emit this from their data-prep step: EKW via `cycle.py bundle`, DermOTS via `pipeline/to_harbor.py`. When touching either converter, preserve this layout.
