# Doc index

Last checked: 2026-10-02 against main at `ad9511f`. Start page: [README](../README.md). Auto-fix loop: [autofix quickstart](autofix-agent-quickstart.md).

Every doc in the repo, grouped by what you want to do. Dates are the last commit to that file on main.

**Status key.** CURRENT: read it, it matches main today. STALE: older than the current process, contradicts it, or has broken links; the note says why. SUPERSEDED: a newer doc replaces it, named in the note. "Not read in full" means the status comes from the file's date and links, not a full read. Sub-files of a skill (the gate prompts and checklists next to each `SKILL.md`) share that skill's status.

**Open PRs change some of these** (none merged): [#72](https://github.com/turing-genai-apps/EKW_QC_pipeline/pull/72) and [#74](https://github.com/turing-genai-apps/EKW_QC_pipeline/pull/74) lane and gate fixes (a lane is one worker with its own Claude Max login that fixes one task at a time; see the [autofix quickstart](autofix-agent-quickstart.md)), new approval-review prompt; [#75](https://github.com/turing-genai-apps/EKW_QC_pipeline/pull/75) review prompt v2; [#78](https://github.com/turing-genai-apps/EKW_QC_pipeline/pull/78) fix rules v8.2 and a task-author page; [#80](https://github.com/turing-genai-apps/EKW_QC_pipeline/pull/80) faster re-grade; [#81](https://github.com/turing-genai-apps/EKW_QC_pipeline/pull/81) EKW intake checks; [#82](https://github.com/turing-genai-apps/EKW_QC_pipeline/pull/82) converter fixes; [#85](https://github.com/turing-genai-apps/EKW_QC_pipeline/pull/85) golden-criterion review.

## The auto-fix process

| Doc | What it is | Status |
|---|---|---|
| [autofix-agent-quickstart.md](autofix-agent-quickstart.md) | The loop, inputs, prompts, verification commands, a verified minimal run | CURRENT (new) |
| [svc_fix_method_rules.md](../svc-pc-pipeline/tools/svc_fix_method_rules.md) | The fix and verify rules R1 to R7; every prompt embeds it (2026-09-22) | CURRENT; v8.2 in open PR #78 |
| [svc-pc-pipeline/README.md](../svc-pc-pipeline/README.md) | The pipeline step by step: lanes, gates, bundler, return intake (2026-09-25) | CURRENT; runner changes in open PRs #72, #74, #78, #80, #81 |
| [svc-return-runbook.md](../svc-pc-pipeline/docs/svc-return-runbook.md) | The step list for a DataOS return (2026-09-25) | CURRENT for the top "CURRENT SEQUENCE"; step 5 says not to share the dataset with `TFRL_QC`, the same as the [SOP](QC-SOP-first-run.md) (section 7). The sections below the sequence are history. 2 broken links |
| [plan-v6-dataos-as-gate.md](../svc-pc-pipeline/docs/plan-v6-dataos-as-gate.md) | Dated state log, newest first; the "why" behind each rule (2026-09-25) | STALE as a how-to, useful as history. 15 broken links to files that are not in this repo |
| [svc-pc-plain-guide.md](../svc-pc-pipeline/docs/svc-pc-plain-guide.md) | Plain-language method (2026-09-23) | SUPERSEDED by the [quickstart](autofix-agent-quickstart.md) and the pipeline README. Describes the 2026-09-22 state; 2 broken links |
| [svc-pc-one-shot-fix-guide.md](../svc-pc-pipeline/docs/svc-pc-one-shot-fix-guide.md) | How to fix one task by hand (2026-09-23) | STALE: its pass rule is "2 of 3 reviews accept"; the [SOP](QC-SOP-first-run.md) (6b step 3) now says a task passes only when all four Answer Check reviews have no major. 2 broken links |
| [pipeline-hardening-20260922.md](pipeline-hardening-20260922.md) | A proposal to wire existing checks into the fix flow (2026-09-22) | STALE: a proposal; not checked against later commits. Not read in full |
| [fix-task-from-review/SKILL.md](../skills/ekw/fix-task-from-review/SKILL.md) | Skill: fix one rejected task end to end (2026-09-22) | CURRENT |
| [safe-xlsx-golden-edit/SKILL.md](../skills/ekw/safe-xlsx-golden-edit/SKILL.md) | Skill: edit a golden workbook without breaking formula caches (2026-09-16) | CURRENT. Not read in full |
| [tp-fp-classification/SKILL.md](../automation/tp-fp-classification/SKILL.md) | Skill: turn QC feedback into one classified workbook per task; defines the defect classes (2026-09-02) | CURRENT |
| [batch-scan-gates.md](../automation/tp-fp-classification/batch-scan-gates.md) and [gate-mining/SKILL.md](../automation/tp-fp-classification/gate-mining/SKILL.md) | Follow-on to the TP/FP skill (2026-09-02) | CURRENT. Not read in full |
| [judge_emulate.README.md](../svc-pc-pipeline/tools/judge_emulate.README.md) | How the oracle computes a reward (2026-09-23) | CURRENT |

## Task authors

| Doc | What it is | Status |
|---|---|---|
| [QC-SOP-first-run.md](QC-SOP-first-run.md) | The SOP: pick a task, run checks, fix, the gate (6a), DataOS (6b), hand off (2026-09-28) | CURRENT. Points to the review rules v2 (top box and section 7) but has no pointer to the auto-fix quickstart |
| [QC-SCRIPT-REGISTRY.md](QC-SCRIPT-REGISTRY.md) | Every QC check explained in plain English, in twelve families, for readers outside our team (2026-10-06) | CURRENT |
| [QC-SCRIPT-REGISTRY-TOOLS.md](QC-SCRIPT-REGISTRY-TOOLS.md) | The scripts that are not checks (build, upload, returns, regrade, reporting), grouped by stage (2026-10-06) | CURRENT |
| [QC-HOW-TO-ADD-TO-RL-WORLD.md](QC-HOW-TO-ADD-TO-RL-WORLD.md) | For the RL World team: how to add four of our ideas to their platform (2026-10-06) | CURRENT, written against their commit eb16a55 |
| [QC-HOW-TO-ADD-TO-CTP.md](QC-HOW-TO-ADD-TO-CTP.md) | For the CTP canvas team: how to add six of our ideas to their platform (2026-10-06) | CURRENT, written against their commit 578e40e |
| [task-failure-checklist.md](task-failure-checklist.md) | Questions Q1 to Q5 to answer for every criterion before upload (2026-09-28) | CURRENT |
| [rubric-check-1-5-guideline.md](rubric-check-1-5-guideline.md) | How to write rubrics that clear checks 1.4 and 1.5, with real good and bad examples (2026-10-02) | CURRENT |
| [ctp-task-guide.md](ctp-task-guide.md) | Making a task in the CTP canvas that passes DataOS (2026-09-28) | CURRENT; changed in open PRs #72, #74 |
| [harbor-task-rubric.md](harbor-task-rubric.md) | The 15 platform QC checks and the gate for each (2026-09-18) | CURRENT. Cites a folder (`dataos_qc_runs/`) that is not in the repo |
| [docs/ONBOARDING.md](ONBOARDING.md) | EKW front onboarding: `pipeline/cycle.py` workflow (2026-09-18) | CURRENT for the EKW cycle only; does not cover the lane pipeline or the 2026-09-24 intake change. Not read in full |
| [docs/svc/ONBOARDING.md](svc/ONBOARDING.md) | SVC front onboarding (2026-08-06) | SUPERSEDED by the [SOP](QC-SOP-first-run.md). Written for the older `tests/rubric.json` task shape. 1 broken link |
| [docs/svc/](svc/): [BUILDER_PREFLIGHT](svc/BUILDER_PREFLIGHT.md), [KNOWN_CALIBRATIONS](svc/KNOWN_CALIBRATIONS.md), [QC_APPLICABILITY](svc/QC_APPLICABILITY.md), [QC_DIMENSIONS_FOR_CREATORS](svc/QC_DIMENSIONS_FOR_CREATORS.md), [RUN_FULL_QC](svc/RUN_FULL_QC.md), [TASK_CREATION_CLAUDE](svc/TASK_CREATION_CLAUDE.md), [TASK_CREATION_USAGE](svc/TASK_CREATION_USAGE.md) | Cirrus-era task creation and QC notes (2026-08-05 to 2026-08-28) | STALE: oldest docs in the repo, older `tests/rubric.json` shape. Not read in full. 8 broken links (7 in TASK_CREATION_CLAUDE, 1 in KNOWN_CALIBRATIONS) |
| [docs/CLAUDE.md](CLAUDE.md) | One person's working conventions for the EKW front (2026-09-18) | STALE: personal conventions, not a repo guide. 4 broken links |
| [task-creation-self-qc](../skills/svc/task-creation-self-qc/SKILL.md), [svc-task-qc](../skills/svc/svc-task-qc/SKILL.md), [authenticity-and-substance-review](../skills/svc/authenticity-and-substance-review/SKILL.md), [rubric-structure-check](../skills/svc/rubric-structure-check/SKILL.md), [source-file-reference-check](../skills/svc/source-file-reference-check/SKILL.md), [synthetic-marker-scan](../skills/svc/synthetic-marker-scan/SKILL.md) | Six SVC single-task QC skills (all 2026-08-05) | STALE: Cirrus `rubric.json` era, 7 broken links. Not read in full |
| [harbor-task-intake](../skills/ekw/harbor-task-intake/SKILL.md), [ekw-to-dataos-harbor](../skills/ekw/ekw-to-dataos-harbor/SKILL.md), [harbor-rewardkit-convert](../skills/ekw/harbor-rewardkit-convert/SKILL.md) | EKW skills: intake interview, convert to the DataOS package, convert to reward-kit (2026-08-27 to 2026-09-18) | CURRENT. Not read in full; converter changes in open PR #82 |
| [gdpval-task-qc](../skills/ekw/gdpval-task-qc/SKILL.md), [gdpval-task-qc-with-verifiers](../skills/ekw/gdpval-task-qc-with-verifiers/SKILL.md), [gdpval-prompt-input-qc](../skills/ekw/gdpval-prompt-input-qc/SKILL.md), [gdpval-golden-qc](../skills/ekw/gdpval-golden-qc/SKILL.md), [gdpval-verifier-qc](../skills/ekw/gdpval-verifier-qc/SKILL.md), [QC_FOUNDATION](../skills/_shared/QC_FOUNDATION.md) | Single-task EKW QC skills and their shared grading rules (all 2026-08-05) | STALE: not checked against the current gate. Not read in full. 3 broken links in gdpval-task-qc-with-verifiers |

## Reviewers and managers

| Doc | What it is | Status |
|---|---|---|
| [task-review-rules-v2.md](task-review-rules-v2.md) | Rules for approving, holding or sending back a task (2026-10-02) | CURRENT; replaces the nine DENY rules of 2026-09-30 |
| [manager-task-review-guide-v1.md](manager-task-review-guide-v1.md) | The old manager guide with the nine DENY rules and a Slack reply format | SUPERSEDED by [task-review-rules-v2.md](task-review-rules-v2.md) and the [manager run sheet](QC-RUNBOOK-manager.md); the file says so in its first lines |
| [approval-review-prompt.md](approval-review-prompt.md) | The pasteable prompt with the nine DENY rules (2026-09-29) | SUPERSEDED by [task-review-rules-v2.md](task-review-rules-v2.md); the file says so in its second paragraph |
| [WORDING-AUDIT-2026-10-11.md](WORDING-AUDIT-2026-10-11.md) | Names and numbers a new person cannot understand: what was fixed on 2026-10-11 and what still needs an owner | CURRENT |
| [ekw-svc-comprehensive-review.md](ekw-svc-comprehensive-review.md) | The prompt DataOS runs for the Comprehensive Review (2026-09-18) | CURRENT; changed in open PRs #75 (v2) and #85 |
| [qc_zero_pass/README.md](../svc-pc-pipeline/tools/qc_zero_pass/README.md), with [REVIEW_BRIEF](../svc-pc-pipeline/tools/qc_zero_pass/REVIEW_BRIEF.md) and [VERIFY_BRIEF](../svc-pc-pipeline/tools/qc_zero_pass/VERIFY_BRIEF.md) | Internal review of tasks whose tests pass 0% of runs, run on every batch (2026-09-28) | CURRENT; changed in open PR #85. The two briefs not read in full |

## QC intake and batches

| Doc | What it is | Status |
|---|---|---|
| [qc-intake-process.md](../svc-pc-pipeline/docs/qc-intake-process.md) | How batches of 50 or more go to the TFRL QC team, since 2026-09-24 (updated 2026-09-28) | CURRENT; changed in open PRs #72, #74 |
| [dataos-batch-watch/SKILL.md](../skills/ekw/dataos-batch-watch/SKILL.md) | Skill: watch a running DataOS batch, download each finished task, fix it per task (2026-09-16) | CURRENT. Not read in full |
| [dataos-qc-run/SKILL.md](../skills/ekw/dataos-qc-run/SKILL.md) | Skill: run the DataOS QC pass for a dataset (2026-08-05) | STALE: predates the current DataOS pipeline and pass rule. 2 broken links |
| [task-doc.md](../svc-pc-pipeline/skills/task-doc.md) | Skill: the QCR submission doc plus both tracker updates (2026-09-23) | CURRENT. Not read in full; written before the 2026-09-24 intake change |

## SOPs

| Doc | What it is | Status |
|---|---|---|
| [QC-RUNBOOK-qc-person.md](QC-RUNBOOK-qc-person.md) | Run sheet for QC people: numbered steps with the `qc.py` commands, signing in with a Claude Max login or the team GLM key (new, 2026-10-09) | CURRENT. Start here; the SOP below has the detail behind each step |
| [QC-RUNBOOK-manager.md](QC-RUNBOOK-manager.md) | Run sheet for managers: `qc.py release` and `qc.py manage`, rules A to F, approve or send back (new, 2026-10-09) | CURRENT. Start here; the SOP below has the detail behind each step |
| [QC-SOP-first-run.md](QC-SOP-first-run.md) | The SOP for task authors, SVC and EKW (2026-09-28, 17 commits; its own text carries later updates dated 2026-10-05 and 2026-10-09) | CURRENT. The detail behind each step of the run sheets; start with your run sheet |
| [QC_SOP.docx](QC_SOP.docx) | EKW-GDPVal QC SOP v1.3 by Luiz, the two-phase internal and external QC cycle (2026-09-14). GitHub does not show .docx; download it | SUPERSEDED for authors by the Markdown SOP above. It is still the SOP that the TP/FP skill cites, and whether that two-phase cycle is still run is not verified |

## Reference and results

| Doc | What it is | Status |
|---|---|---|
| [pipeline/README.md](../pipeline/README.md) | Architecture of the shared QC engine (2026-08-27) | CURRENT. Not read in full |
| [pipeline/specs/](../pipeline/specs/gdpval_task_quality_v18.md): [base spec v18](../pipeline/specs/gdpval_task_quality_v18.md), [solution visual-only](../pipeline/specs/gdpval_solution_visual_only.md), overlays [svc](../pipeline/specs/overlays/svc.md), [svc-noeval](../pipeline/specs/overlays/svc-noeval.md), [no-eval-gates](../pipeline/specs/overlays/no-eval-gates.md); [svc_fullcorpus_dvc/README](../pipeline/templates/svc_fullcorpus_dvc/README.md) | The grading specs the shared engine reads, and a corpus template | CURRENT as engine inputs. Not read in full |
| [deterministic-checks/README.md](../deterministic-checks/README.md) | The checks, how to run them, `run_all.py` (2026-09-28) | CURRENT |
| [OVERVIEW](../deterministic-checks/OVERVIEW.md), [BUILD-CONTRACT](../deterministic-checks/BUILD-CONTRACT.md), [CHANGELOG](../deterministic-checks/CHANGELOG.md), [CLAUDE](../deterministic-checks/CLAUDE.md), [ekw/README](../deterministic-checks/ekw/README.md) | Overview, package shape, change log, working notes, EKW runner (2026-09-14 to 2026-09-28) | CURRENT. Not read in full |
| [COVERAGE-MATRIX](../deterministic-checks/COVERAGE-MATRIX.md), [GAP-ANALYSIS](../deterministic-checks/GAP-ANALYSIS.md), [PERPLEXITY-QC-FINDINGS](../deterministic-checks/PERPLEXITY-QC-FINDINGS.md), [QC-REVIEW-8x-COVERAGE](../deterministic-checks/QC-REVIEW-8x-COVERAGE.md), [semantic-consistency-design](../deterministic-checks/semantic-consistency-design-2026-09-14.md) | Point-in-time analyses (2026-09-14 and 09-15) | STALE: snapshots; check counts will have moved. Not read in full |
| [content-audit](../deterministic-checks/content-audit/SKILL.md), [structural-audit](../deterministic-checks/structural-audit/SKILL.md), [v0-checks/golden-reproducibility](../deterministic-checks/v0-checks/golden-reproducibility/SKILL.md) | LLM checklists for content and structure; an unvalidated check (2026-09-14) | CURRENT, except v0-checks, which the checks README calls unvalidated. Not read in full |
| [reference/harbor_evals_quick_guide.md](../reference/harbor_evals_quick_guide.md) and [dataos_recipe/RECIPE.md](../reference/dataos_recipe/RECIPE.md) | Operator guide for Harbor evals (2026-08-07); a DataOS click-path recipe (2026-08-27) | STALE: DataOS screens may have changed since. Not read in full |
| [automation/README.md](../automation/README.md) and [ekw-qc-cycle/SKILL.md](../automation/ekw-qc-cycle/SKILL.md) | A scheduled routine for the EKW cycle, steps 1 to 3 (2026-08-05) | STALE: predates the lane pipeline. Not read in full |
| [pipeline/NEW_QC_GATES_PLAN.md](../pipeline/NEW_QC_GATES_PLAN.md) | A 2026-08-05 implementation plan for new gates | STALE: a plan from the first week of the repo |
| [19-0-0 fix](../deliverables/svc-pc-19-0-0-corpus-fix-2026-09-17/README.md), [32-task completeness fix](../deliverables/svc-pc-32-task-corpus-completeness-fix-2026-09-17/README.md) and its [audit](../deliverables/svc-pc-32-task-corpus-completeness-fix-2026-09-17/CORPUS-COMPLETENESS-AUDIT.md) | Two delivered corpus fixes (2026-09-17) | CURRENT as records |
| [SUMMARY.md](../SUMMARY.md) | "Round 53" checker bug fixes (2026-09-16) | STALE: a one-off report |
| ROUND62 reports: [row 16](../ROUND62-ROW16-REPORT.md), [rows 28-29](../ROUND62-ROW28-29-REPORT.md), [rows 28-29 fix](../ROUND62-ROW28-29-FIX-REPORT.md), [row 31](../ROUND62-ROW31-REPORT.md), [row 32](../ROUND62-ROW32-REPORT.md), [row 34 fix](../ROUND62-ROW34-FPFIX-REPORT.md), [row 35](../ROUND62-ROW35-REPORT.md) | One report per checker row, all 2026-09-17 | STALE: one-off reports; the checks they describe are in [deterministic-checks/](../deterministic-checks/README.md) |

## Cleanup candidates (nothing is deleted or moved in this PR)

For a later PR, your call:
- Seven `ROUND62-*.md` reports, `SUMMARY.md`, `_full_svcpc_results.json` (283 KB, 2026-09-17) and `_prompt.txt` (a past agent prompt) in the repo root: one-off outputs.
- [`docs/svc/`](svc/) (7 older docs), [`docs/CLAUDE.md`](CLAUDE.md), [`pipeline/NEW_QC_GATES_PLAN.md`](../pipeline/NEW_QC_GATES_PLAN.md): older than the current process.
- [`svc-pc-plain-guide.md`](../svc-pc-pipeline/docs/svc-pc-plain-guide.md) and [`svc-pc-one-shot-fix-guide.md`](../svc-pc-pipeline/docs/svc-pc-one-shot-fix-guide.md): superseded or stale as shown above.
- [`QC_SOP.docx`](QC_SOP.docx), once someone confirms the two-phase cycle it describes is retired.
- In `svc-pc-pipeline/`: the `patch_*`, `v3digest_*` and `*_pilot.sh` scripts that its README calls superseded, the one-off `_*.sh` and `recover*.sh` scripts in `sandbox_root/`, [`svc_fullsweep_brief.md`](../svc-pc-pipeline/tools/svc_fullsweep_brief.md), and the two review notes [`judge_emulate_REVIEW.md`](../svc-pc-pipeline/tools/judge_emulate_REVIEW.md) and [`judge_emulate.arithmetic-review.md`](../svc-pc-pipeline/tools/judge_emulate.arithmetic-review.md).
- The runner exists twice on main (`tools/` and `sandbox_root/`) with different contents; open PR #78 makes them the same.
