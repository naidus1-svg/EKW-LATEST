# Task-creation self-QC — running checklist

Copy this into your own session and check items off as you go. One line per
dimension; see `QC_DIMENSIONS_FOR_CREATORS.md` for the full explanation and
before/after examples behind each one.

## 1. Framing the task
- [ ] `overall_gdpval_fit` (skip L1) — reads as real professional work, not exercise-shaped
- [ ] `role_and_deliverable_clarity` — role and required artifact are both unambiguous
- [ ] `professional_complexity` (skip L1) — requires real judgment, not template-filling
- [ ] `feasibility_and_clarity` — doable in scope; two professionals would interpret it the same way

## 2. Writing the instruction
- [ ] `instruction_input_consistency` — every referenced file/section actually exists and matches
- [ ] `input_prompt_leakage` — no answer or completed-solution artifact leaked into the input folder
- [ ] `self_containedness` — solvable from instruction + bundled files alone
- [ ] `instruction_authenticity` — the brief reads as human-written, not LLM-shaped

## 3. Assembling `environment/data/`
- [ ] Run `source-file-reference-check` — zero missing references
- [ ] Run `synthetic-marker-scan` — zero marker/template-leak hits; date-outlier candidates checked by hand
- [ ] `input_file_authenticity` — no internal contradictions, impossible values, or wrong-source content
- [ ] `metadata_completeness` — confirmed current status in `KNOWN_CALIBRATIONS.md`, not assumed

## 4. Building the golden solution
- [ ] `solution_format_match` — confirmed current status in `KNOWN_CALIBRATIONS.md`, not assumed
- [ ] `solution_substantiveness` — real analysis, not a skeleton (except L1's single-fact exception)
- [ ] `solution_instruction_alignment` — every explicit requirement actually addressed
- [ ] `solution_internal_consistency` — deliverables agree with each other and with themselves
- [ ] `solution_layout_professionalism` — client-ready presentation
- [ ] `solution_chart_quality` / `solution_visual_insight_surfacing` (skip if no charts) — labeled, and surfaces the actual insight

## 5. Writing the rubric
- [ ] Run `rubric-structure-check` — all severities zero (gate present, not over-gated, count fits the level, no blank criteria)
- [ ] `verifier_rubric_clarity` — no undefined subjective language used as a pass condition
- [ ] `verifier_rubric_specificity` — every criterion points at something observable

## Before delivery
- [ ] Full pass through `authenticity-and-substance-review/CHECKLIST.md`
- [ ] Every severity-2 finding resolved or consciously accepted with a written reason
