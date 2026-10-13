# Start here

Last checked: 2026-10-02 against main at `ad9511f`. This repo checks and fixes AI-training tasks (a prompt, source files, a golden answer and a rubric) before and after they go to DataOS, Turing's grading platform. Pick your role and do the steps in its row. Unknown word? See the [glossary](#glossary).

| I am... | Do this first |
|---|---|
| A QC person | 1. Follow the [QC person run sheet](docs/QC-RUNBOOK-qc-person.md): do "Once", then steps 1 to 8 for each task. 2. Open the [SOP](docs/QC-SOP-first-run.md) when a step points to it. |
| A manager who reviews the tasks QC people hand over | 1. Follow the [manager run sheet](docs/QC-RUNBOOK-manager.md); it is your main document. 2. Open the [SOP](docs/QC-SOP-first-run.md) when a step points to it. |
| Writing tasks | 1. Read the [SOP](docs/QC-SOP-first-run.md), the current one ([QC_SOP.docx](docs/QC_SOP.docx) is older). 2. Write the rubric with the [1.4 and 1.5 guideline](docs/rubric-check-1-5-guideline.md). 3. Answer the [failure checklist](docs/task-failure-checklist.md) for every criterion, then run the [gate](docs/QC-SOP-first-run.md#6a-the-gate-every-task-before-any-upload). |
| Reviewing or approving tasks (managers: do this together with the [manager run sheet](docs/QC-RUNBOOK-manager.md), which holds rules A to F) | 1. Read the [review rules v2](docs/task-review-rules-v2.md). 2. Open the task's four Answer Check review results (the four reviews of the pipeline in the SOP, section 6b) and read their findings first. 3. Check what each finding id means in the [review prompt](docs/ekw-svc-comprehensive-review.md) (v2 is in open PR [#75](https://github.com/turing-genai-apps/EKW_QC_pipeline/pull/75), not merged). |
| Fixing a rejected task | 1. Answer the [failure checklist](docs/task-failure-checklist.md) for each finding. 2. Fix with the [1.4 and 1.5 guideline](docs/rubric-check-1-5-guideline.md) and the [fix rules](svc-pc-pipeline/tools/svc_fix_method_rules.md) (v8.2 is in open PR [#78](https://github.com/turing-genai-apps/EKW_QC_pipeline/pull/78)). 3. Re-run the [gate](docs/QC-SOP-first-run.md#6a-the-gate-every-task-before-any-upload). 4. After DataOS returns it, read the four reviews and check each listed problem: SOP sections 6b and 6c. |
| Building or running the auto-fix agent | 1. Read the [quickstart](docs/autofix-agent-quickstart.md). 2. Repeat its verified minimal run (section 5). 3. Read the [pipeline README](svc-pc-pipeline/README.md) for the full loop. |
| Running the pipeline and the batches | 1. Read the [pipeline README](svc-pc-pipeline/README.md). 2. Follow the [return runbook](svc-pc-pipeline/docs/svc-return-runbook.md), the step list at its top. 3. Read the [QC intake process](svc-pc-pipeline/docs/qc-intake-process.md) before sending any batch. |
| On another platform (RL World, CTP canvas), or want to know what every QC script does | 1. Read the plain-English [script registry](docs/QC-SCRIPT-REGISTRY.md): every check in twelve families, with examples. 2. See the [non-check tools](docs/QC-SCRIPT-REGISTRY-TOOLS.md). 3. Read the how-to for your platform: [RL World](docs/QC-HOW-TO-ADD-TO-RL-WORLD.md) or [CTP canvas](docs/QC-HOW-TO-ADD-TO-CTP.md). 4. For how our process differs from yours: [RL World comparison](https://docs.google.com/document/d/1HqiWdx3InG8ytBu57Rh4GJB-iFK_dpweX8hU8_G3mcc/edit) and [CTP canvas comparison](https://docs.google.com/document/d/1rsGB_Yl9pgD8AODKp1b_fJm7KxC5kqFrkfCtYt5VKDE/edit). |
| Looking for an old report or result | Open the [doc index](docs/README.md): every doc, its status, and what replaced it. |

---

## Earlier content (kept as is)

Everything below this line is older. For the current process use the table above and the [SOP](docs/QC-SOP-first-run.md). The task shape described below (`tests/rubric.json`) is the older one; current packages use `tests/deliverables*/judge.toml` (see the [quickstart](docs/autofix-agent-quickstart.md), section 2).

# EKW QC

Quality control for GDPVal-style, document-grounded knowledge-work task
datasets: task/prompt design, source-document authenticity, golden-solution
quality, and rubric/verifier design — graded by a multi-judge LLM ensemble
against a versioned spec, plus single-agent skills for ad-hoc one-task QC.

**One engine, two fronts.** `pipeline/gdpval_qc` and `pipeline/cycle.py` are
shared; each front supplies its own thin spec overlay, its own skills, and
its own day-to-day workflow on top of that shared core.

| | EKW-GDPVal | SVC/Cirrus |
|---|---|---|
| Onboarding | [`docs/ONBOARDING.md`](docs/ONBOARDING.md) | [`docs/svc/ONBOARDING.md`](docs/svc/ONBOARDING.md) (superseded by the [SOP](docs/QC-SOP-first-run.md); see the [doc index](docs/README.md)) |
| Skills | `skills/ekw/` | `skills/svc/` |
| Spec | `pipeline/specs/gdpval_task_quality_v18.md` (the base) | `pipeline/specs/overlays/svc.md` (`extends:` the base) |
| Task structure | independent tasks, tracker-driven intake | a decomposition DAG (L1→L2→L3) over a shared corpus, pre-bundled |
| Entry point | `cycle.py new/fetch/diff/bundle/qc/dataos` | `cycle.py svc-qc <corpus>` |

Not sure which front a task belongs to? Task id looks like
`cirrus-y1-task-*`, has `tests/rubric.json` (not `verifier.json`), and
`environment/data/`+`solution/golden/` (not `environment/`+`solution/golden_outputs/`)
→ SVC. Anything else → EKW.

## Quick start

Older set-up, kept as is. The QC person and manager run sheets use a Claude login (QC person sheet, Once 2), and they do not mention `OPENAI_API_KEY` or `GEMINI_API_KEY`.

```bash
cd pipeline
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # fill in OPENAI_API_KEY + GEMINI_API_KEY (or GOOGLE_API_KEY)

# smoke test against the bundled reference task
gdpval-assess --spec specs/gdpval_task_quality_v18.md \
              --corpus data/sample_corpus --output-dir runs/smoke
```

Then read whichever front's onboarding doc applies to what you're QCing —
they cover setup details (LibreOffice, etc.) and the actual day-to-day
procedure in full.

## Layout

```
gdpval-qc/
├── pipeline/            the shared QC engine — see pipeline/README.md for architecture
│   ├── gdpval_qc/       spec parser (incl. `extends:` overlay composition), judges, verdict, tools/
│   ├── specs/           the base spec + specs/overlays/ (svc.md, svc-noeval.md, no-eval-gates.md)
│   ├── tools/           EKW-only automation (bundle, drive-fetch, dataos-submission, reward-kit convert)
│   ├── templates/harbor/
│   └── cycle.py         the driver — both fronts' entrypoints live here
├── skills/
│   ├── ekw/             single-agent, single-task QC skills for the EKW front
│   ├── svc/             same, for SVC/Cirrus
│   └── _shared/         QC_FOUNDATION.md — grading protocol/verdict computation both fronts share
├── docs/                onboarding + process docs for both fronts (docs/svc/ for SVC-specific)
├── reference/           load-bearing reference material a skill reads at runtime (e.g. the Data-OS click-path recipe)
├── automation/          exportable Claude Code scheduled-task routines
└── cycles/, runs/        gitignored — created locally as you work; never committed (task/eval data)
```

## Why one engine, two fronts (not two separate tools)

The judgment layer — severity scale, evidence policy, verdict computation,
most of the Source/Prompt/Solution dimensions — genuinely transfers between
fronts; only the rubric schema and task structure differ enough to need
their own code. Composing via a spec `extends:` overlay (see
`pipeline/gdpval_qc/v18_spec.py`) instead of forking the whole spec file
means a fix to the shared base propagates to every front automatically,
rather than needing a manual re-fork that silently drifts (which is exactly
what happened before this repo existed — see `docs/svc/QC_APPLICABILITY.md`
for the empirical case study).

## Contributing

- Read the relevant front's onboarding doc before making process changes —
  each documents known gotchas and calibration history that aren't obvious
  from the code alone.
- Changes to `pipeline/gdpval_qc` or the base spec affect both fronts —
  check `pipeline/tests/` still passes, and sanity-check both an EKW and an
  SVC spec resolution before committing.
- Never commit task corpora, eval data, or API keys. `.gitignore` already
  excludes `cycles/`, `runs/`, `dataos_qc_runs/`, and `.env`; the one
  exception is the tiny bundled smoke-test fixture at
  `pipeline/data/sample_corpus/`.


---

## Glossary

- **DataOS**: Turing's grading platform. A task passes when all four of its Answer Check reviews (the four reviews of the pipeline in the SOP, section 6b) report no major finding.
- **Oracle**: a run that scores the golden answer against the rubric. It must score 1.0.
- **Comprehensive Review**: DataOS's AI review of a whole task. The four "Answer Check" reviews of the pipeline are Comprehensive Reviews written with one saved prompt (id 431). Each finding has an id (1.1 to 1.8) and a severity; a major blocks the task.
- **TFRL**: the outside QC team that reviews finished tasks. It rejects or passes the tasks in a QC batch.
- **QC batch**: 50 or more passed tasks sent together to the TFRL QC team (the outside reviewers); see the [QC intake process](svc-pc-pipeline/docs/qc-intake-process.md).
- **Zero-pass**: a test that fails in every model run. We review these ourselves for every batch ([qc_zero_pass](svc-pc-pipeline/tools/qc_zero_pass/README.md)).
- **EQC**: the status column the QC team fills on the consolidated sheet (`EQC ready`, `Skip- duplicate`). The repo never spells out the acronym.
- **NOP**: the empty-answer run. It submits nothing and must score zero (SOP 5a item 2).
- **QCR doc**: the one-page document named QCR_<name>_<date> that is handed to the QC team (see [task-doc](svc-pc-pipeline/skills/task-doc.md)).
- **DataOS ids**: pipeline 141 is "ManualQC automated QC pipeline 4 Reviewers", version 8 is spec 401, and the saved review prompt is 431 (SOP 6b step 2). You do not choose the prompt.
- **Batch owner**: Khiem Doan, who sends cleared tasks to the TFRL QC team in batches of 50 or more (SOP, "What changed" item 1).
- **Lane**: one worker with its own Claude Max login that fixes one task at a time ([doc index](docs/README.md)).
- **Golden**: the reference answer. **Rubric**: the checklist (`judge.toml`) that scores an answer.

To keep this current: run `python docs/check_links.py` (it fails on a broken relative link or a missing "Last checked" line), re-read the docs you changed, then update the "Last checked" line here and in [docs/README.md](docs/README.md).
