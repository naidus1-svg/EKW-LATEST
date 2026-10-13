---
name: gdpval-task-qc
description: >-
  Quality-check (QC) a single GDPVal/omega task locally: Source File & Prompt
  QC, then optional Solution QC and Verifier QC. Use when asked to QC, review,
  or check a task, solution, or verifier/rubric.
---

# GDPVal / Omega Task QC

Grade **one** task directory against a curated quality spec and return an
actionable, reviewer-facing verdict. This skill runs locally as a single agent
over one task — applying the quality spec, severity scale, and anti-overcall
guards directly, with no API keys and no orchestrator.

**You are the judge.** You read the task's files directly and grade each
dimension yourself, applying the global policies below. There is no second
model and no network call.

## Scope: what to QC

Three stages, each **independently runnable**:

1. **Source File and Prompt QC** — grades the prompt + source/input files
   (`Source Documents/`). See [source-and-prompt-qc.md](source-and-prompt-qc.md).
2. **Solution QC** — grades the `Expert Solution/`. See [solution-qc.md](solution-qc.md).
3. **Verifier QC** — grades the verifier (the task's "Rubric", pasted by the
   expert). See [verifier-qc.md](verifier-qc.md).

### Two ways to run

- **Full task QC (default).** Source File and Prompt QC runs first — it is the
  early-QC stage to pass *before* investing in a solution. When it finishes,
  tell the expert which later stages are available (Solution QC if
  `Expert Solution/` exists; Verifier QC if they have a Rubric to paste) and ask
  whether to run them. Do **not** run them unprompted.

- **Standalone stage (run only what the expert asks for).** When the expert says
  they have **already QC'd the source/prompt** and want **only** Solution QC or
  **only** Verifier QC (e.g. "QC only the verifier — source & prompt already
  done"), run just that stage and **skip Source File and Prompt QC entirely** —
  this avoids re-grading and re-reading work already done.

### Required inputs — confirm BEFORE grading

**Before grading any stage, verify you have that stage's required inputs. If any
required input is missing, ask the expert for it and _wait_ — do NOT start QC
with a required input missing.** For a *recommended* input that's missing, say
what it would add and let the expert choose to provide it or proceed without.

| Stage | Required — ask & wait if missing | Recommended — note if missing |
|---|---|---|
| Source File & Prompt QC | the **prompt** (pasted) · non-empty `Source Documents/` | `Expert Solution/` (strengthens overall-fit & complexity; optional at early QC) |
| Solution QC | the **prompt** (pasted) · non-empty `Expert Solution/` | — |
| Verifier QC | the **verifier JSON** (pasted) · the **prompt** (pasted) | `Expert Solution/` (strengthens 4 of 6 dims) |

- The prompt is needed as *context* by most Solution/Verifier dims (alignment,
  format, coverage, clarity); pasting it is cheap and is **not** re-graded.
- The Solution and Verifier dimensions **never read the source/input files**, so
  those stages do **not** need `Source Documents/` — don't ask for it when
  running them standalone.
- **How to ask:** name exactly what's missing and how to supply it — "paste the
  prompt between `<task_prompt>` tags", "upload a zip containing an
  `Expert Solution/` folder", "paste the verifier JSON (its Rubric) between
  `<verifier>` tags". Batch everything missing into one request, then wait.
- **Prompt-missing fallback:** only if the expert says they genuinely can't
  supply the prompt for Solution/Verifier QC, offer the reduced subset that
  doesn't need it (solution: substantiveness, internal consistency, layout,
  charts; verifier: the three programmatic checks + discriminative power) and
  proceed only if they confirm.

## Task directory layout

Tasks follow the expert "Shared Drive" layout (e.g. `data/Task 86`):

```
<task>/                           # e.g. "Task 86"
  Source Documents/               # source/input files referenced by the prompt
  Seed Documents/                 # material used to generate inputs   (not QC'd)
  Expert Solution/                # the expert's golden solution & reasoning (optional at early QC)
  Claude Output/                  # a model's attempt                  (not QC'd)
```

The **prompt is not stored in the folder** — the expert pastes it into the
conversation (or passes it via `--prompt-file`). The **verifier (the task's
"Rubric") is likewise not in the folder** — the expert pastes it for the
optional Verifier QC stage. Folder names may have odd casing or trailing spaces
(e.g. `"Source Documents "`); the extractor matches them tolerantly.

## Workflow

**Step 0 — Pick the mode.** Read what the expert asked for. If they request a
single stage and/or say the source/prompt is already QC'd ("QC only the
solution", "just the verifier — prompt's already done"), run **standalone**: you
will run only that stage and **not** grade or read the source/prompt. Otherwise
run the **full** flow below.

Full-flow checklist (copy and track progress):

```
- [ ] 1. Confirm required inputs (prompt + Source Documents/); ask for anything missing and WAIT before grading
- [ ] 2. Read the prompt and every source file (use the extractor, then Read for visuals)
- [ ] 3. Grade each Source File and Prompt dimension → one finding per dimension
- [ ] 4. Compute the verdict, then synthesize top issues + suggested fixes
- [ ] 5. Present the review; offer to save it
- [ ] 6. Offer Solution QC if Expert Solution/ is present
- [ ] 7. Offer Verifier QC if the expert has a verifier/Rubric to paste
```

**Step 1 — Resolve the task & confirm required inputs (pre-flight gate).** Find
the task directory the expert uploaded/pointed to, then **check every _required_
input for the stage(s) you're about to run** against
[Required inputs](#required-inputs--confirm-before-grading). Detect presence
concretely:

- **prompt** — pasted in the conversation (e.g. between `<task_prompt>` tags)?
- **`Source Documents/` / `Expert Solution/`** — present and non-empty in the
  uploaded directory? The extractor's overview header lists which folders it
  found (trailing spaces tolerated).
- **verifier** — pasted JSON (e.g. between `<verifier>` tags)?

**If any required input is missing, ask the expert for all of it in one message
and WAIT — do not start grading.** For a missing *recommended* input, note what
it would add and let the expert decide. In **full** mode, a missing
`Source Documents/` means there's nothing to QC — say so and stop. Only once the
required inputs are in hand do you proceed; for a standalone stage, go straight
to that stage's file and run its dimensions + the verdict computation.

**Step 2 — Read everything.** Get the text of all source files in one pass with
the extractor, which handles `.docx` / `.xlsx` / `.pdf` / text and skips
infrastructure files (`Dockerfile`, lockfiles, etc.). Run it via the shared
pipeline venv (it's now `pipeline/gdpval_qc/tools/extract_task_files.py`, invoked
as a module so it's the same canonical copy every skill uses):

```bash
cd pipeline
.venv/bin/python -m gdpval_qc.tools.extract_task_files <task_dir>                    # source files
.venv/bin/python -m gdpval_qc.tools.extract_task_files <task_dir> --prompt-file p.md # + the prompt (if saved as a file)
.venv/bin/python -m gdpval_qc.tools.extract_task_files <task_dir> --solution         # + the Expert Solution
```

It needs `python-docx`, `openpyxl`, and `pypdf` only for Office files
(`pip install python-docx openpyxl pypdf`); text/PDF still extract without them.
**Also** open any PDF or image source file with the Read tool directly when a
dimension needs the *visual* artifact (layout, charts), not just its text.

**Step 3-5 — Grade, decide, report.** Apply the [grading protocol](#grading-protocol)
and [verdict computation](#verdict-computation) below, then emit the review in
the [output format](#output-format).

**Step 6 — Offer Solution QC.** Once Source File and Prompt QC is reported, tell
the expert whether `Expert Solution/` is present and ask if they want Solution
QC. Read [solution-qc.md](solution-qc.md) only when they say yes.

**Step 7 — Offer Verifier QC.** Also ask whether the expert has a verifier (the
task's "Rubric") to QC. Because it is not in the folder, prompt them to paste
the verifier JSON into the conversation. Read [verifier-qc.md](verifier-qc.md)
only when they provide one.

---

## Grading protocol, verdict computation, output format

Shared with every other single-agent QC skill (front-agnostic — no EKW-specific
folder names or dimension names) — see
[`../../_shared/QC_FOUNDATION.md`](../../_shared/QC_FOUNDATION.md) for the finding
shape, severity scale, evidence policy, confidence policy, single-judge
uncertainty rule, eval-context conventions, verdict computation, and the
output-format template. Apply it unchanged.

**This front's deterministic dimensions.** The three Verifier QC checks
(`verifier_spec_parseable`, `verifier_count_in_range`,
`verifier_outcome_grader_present`) are deterministic: produce them by running
`.venv/bin/python -m gdpval_qc.tools.check_verifier` (from `pipeline/`) rather
than judging by hand. See [verifier-qc.md](verifier-qc.md).

## Dimension reference

- [source-and-prompt-qc.md](source-and-prompt-qc.md) — **required.** Task
  Structure + Authenticity dimensions.
- [solution-qc.md](solution-qc.md) — offered. Solution Quality dimensions.
- [verifier-qc.md](verifier-qc.md) — offered. Verifier Quality dimensions +
  the three programmatic checks (run via
  `.venv/bin/python -m gdpval_qc.tools.check_verifier`).
