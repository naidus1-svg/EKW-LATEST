---
name: dataos-qc-run
description: >-
  Automate the DataOS-side QC pass for an EKW dataset: for every task in a
  Data-OS dataset, run evaluations (Claude Code, Codex, Oracle), run QC
  (Agent Trajectory / GPT 5.6 Sol) against the model-based evals, then
  download every task's outputs+results and organize them on disk. Spawns
  a small fleet of parallel subagents, each driving its own Chrome tab over
  a disjoint slice of the dataset's tasks. Use when asked to "run DataOS
  QC", "run evals+QC on this dataset", or to automate step 3b/4 of the QC
  cycle workflow for a Data-OS dataset link.
---

# DataOS QC run — parallel browser-automation fleet

Runs the full click-path a human takes in Data-OS to get QC signal on every
task in a dataset, then collects the resulting artifacts. This skill drives
the live Data-OS UI via the `claude-in-chrome` connector — it is **not** a
read-only research task; it launches real (billed) evaluation and
verification runs against the workspace's shared credit balance.

The full click-by-click recipe this skill implements — captured live with
Luiz on 2026-08-04 — lives at
[reference/dataos_recipe/RECIPE.md](../../reference/dataos_recipe/RECIPE.md).
Read it once before the first run of this skill in a session; it has exact
selectors, modal field names, gotchas (dropdown-closes-on-blur, stale effort
selection, async run timing) and the confirmed downloaded-file layout. This
SKILL.md is the orchestration wrapper around that recipe — if the two ever
disagree, RECIPE.md is the source of truth for "what to click"; this file
governs "how the fleet is organized."

## Scope (confirmed by Luiz — do not expand without asking)

- **In scope, per task:** `Run evaluation` × 3 (Claude Code / Claude Opus 4.8
  / high; Codex / GPT 5.6 Sol / high; Oracle) → `Agent Trajectory` QC × 2
  (against the Claude Code and Codex evals only, never Oracle; model
  GPT 5.6 Sol / medium effort) → bulk-download evaluations + verifications.
- **Out of scope:** `Loss Pattern`, `Comprehensive Review`. Do not click
  these even if convenient — Luiz confirmed the above is the minimal set
  that gives sufficient QC signal.
- **The `benchmark_type` missing-metadata warning is always benign** for
  EKW tasks (deliberate, per the project's Strict Harbor Task Format) —
  never treat it as a blocker or something to fix.

## Required inputs — confirm BEFORE starting

| Input | How supplied | If missing |
|---|---|---|
| **Dataset URL** | e.g. `https://data-os.turing.com/datasets/273` | Ask & wait — never guess a dataset id |
| **Fleet size** | number of parallel agents | Default to 4–6 (Luiz's stated preference); ask only if the task count makes the default clearly wrong (e.g. <10 tasks → fewer agents) |
| **Task scope** | all tasks in the dataset, or a named subset | Default to all tasks currently listed on the dataset page |

## Orchestrator workflow

```
- [ ] 1. Load claude-in-chrome tools; open the dataset URL in a tab
- [ ] 2. Read dataset name, total task count, task label list, current credit balance
- [ ] 3. Create the output directory dataos_qc_runs/<dataset_name>/
- [ ] 4. Partition task labels into N contiguous slices (N = fleet size)
- [ ] 5. Spawn N subagents in parallel (single message, N Agent calls), one per slice
- [ ] 6. Each subagent runs Phase A -> Phase B -> Phase C on its slice and returns a status report
- [ ] 7. Collect all N reports; write dataos_qc_runs/<dataset_name>/RUN_REPORT.md
- [ ] 8. Report to the user: tasks completed, tasks blocked/skipped, credit status, file locations
```

### Step 1–2 — Coordinator: survey the dataset

Open the dataset URL yourself first (don't delegate this part — you need
the full picture before deciding how to split work). Load the browser tools:

```
ToolSearch: select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__get_page_text,mcp__claude-in-chrome__find
```

Navigate to the dataset URL, then `get_page_text` to read:
- **Dataset name** (page header, e.g. `QCR_EKW_Luiz`) — this becomes the
  output folder name verbatim.
- **Task count and labels** — expand `Tasks (N)`; if the list is
  paginated/virtualized, scroll and re-read until all N labels are
  collected. Every task label matters — a silently-dropped task is a
  silent coverage gap.
- **Credit balance** — sidebar `Credits: US$ X used / Y total`. Record the
  starting `remaining = Y - X`. This is the number every subagent's budget
  check is measured against (see Step 4 in RECIPE.md's cost data: a
  Claude Code eval run cost ~$2.13, Codex ~$1.66, Oracle ~$0.003, each QC
  run ~$0.20 — i.e. roughly **$4** of model cost per task for the full
  loop, plus DataOS runtime overhead). Do a sanity check: if
  `remaining < 4 * task_count`, warn the user up front that the budget
  likely won't cover the full run before spawning anything.

### Step 3 — Output directory

Create `dataos_qc_runs/<dataset_name>/` in the project root (sanitize the
dataset name for the filesystem — replace spaces/slashes with `_`). Each
task's artifacts land in a subfolder: `dataos_qc_runs/<dataset_name>/task_<label>/`.

This directory is scoped to the dataset, not the QC cycle date — a re-run
against the same dataset reuses the same folder; a new dataset name always
gets a fresh folder.

### Step 4 — Partition and spawn the fleet

Split the task label list into N roughly-equal contiguous slices (N =
fleet size, default 4–6). Spawn **one Agent call per slice, all in a single
message** so they run concurrently. Use `subagent_type: general-purpose`
(needs Bash for file moves + the full browser toolset).

Each subagent prompt must be fully self-contained — it has no memory of
this conversation. Use this template, substituting `{DATASET_URL}`,
`{DATASET_NAME}`, `{OUTPUT_DIR}`, `{TASK_LABELS}` (this agent's slice, as a
list), and `{STARTING_REMAINING_CREDITS}`:

```
You are one worker in a fleet automating a DataOS QC run. You drive your
own Chrome tab against a live production tool (Data-OS) — every click you
make launches real, billed work against a shared credit balance. Read
carefully and follow the recipe exactly; do not improvise UI interactions.

## Setup

1. Load browser tools:
   ToolSearch: select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__read_page,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__get_page_text,mcp__claude-in-chrome__find
2. Call tabs_create_mcp to get your OWN tab — do not reuse a tab another
   worker might be using. Track your tabId and pass it explicitly to every
   browser tool call from now on.
3. Read the full click-by-click recipe before doing anything else:
   Read {REPO_ROOT}/reference/dataos_recipe/RECIPE.md
   Pay special attention to Steps 0-17 and the gotchas called out inline
   (dropdown closes on alt-tab/blur — never switch focus mid-selection;
   effort-selector can retain a stale value from a prior model — always
   explicitly click the required effort; evaluations AND verifications
   are asynchronous — never wait/poll, launch and move on).
4. Navigate your tab to {DATASET_URL}, expand Tasks, and confirm you can
   see every task label in your assigned slice: {TASK_LABELS}

## Your assigned tasks
{TASK_LABELS}

## Output directory
{OUTPUT_DIR}  (create dataos_qc_runs/{DATASET_NAME}/task_<label>/ per task)

## Credit budget protocol (hard stop — do not skip this)

Starting workspace-wide remaining credits when you were spawned:
{STARTING_REMAINING_CREDITS}. Other workers are spending from the SAME
pool concurrently, so treat this number as a rough ceiling, not a precise
per-worker allowance. Before EVERY `Run evaluation` or `Run trajectory`
click:
  - Re-read the sidebar Credits value on your current page.
  - If remaining credits look too low to safely cover the next run
    (rule of thumb: assume ~$2-2.50 per eval launch, ~$0.20-0.25 per QC
    launch), or if a Launch/Run action itself errors out due to
    insufficient credits, STOP immediately. Do not retry, do not degrade
    to a cheaper model as a workaround.
  - On stopping for this reason, record exactly which of your assigned
    tasks/phases were completed vs not yet reached, and say so plainly in
    your final report — this must be surfaced to the user as "ran out of
    credits, need more to continue," not buried.

## The pipeline (3 phases, run in this order, across YOUR ENTIRE slice
## before moving to the next phase — do not interleave)

### Phase A — Launch evaluations (no waiting)
For each task in your slice, in order:
  1. Open the task page (navigate via the dataset's Tasks list — task
     detail page URLs use an internal numeric id you can only get by
     clicking the task's row, not by guessing).
  2. Click `Run evaluation`. Select agent `Claude Code`, model
     `Claude Opus 4.8`, effort `high`, internet access ON. **Before
     clicking Launch, check for and deselect any OTHER highlighted effort
     pill** (effort pills are ADDITIVE TOGGLES, not single-select — a
     stale prior selection does not get replaced by clicking a new one,
     it adds to it). **Read the Launch button's own label — it must say
     `Launch` singular, never `Launch 2 evaluations` — before clicking.**
     Then click `Launch`.
  3. Go back to the task page (breadcrumb). Click `Run evaluation` again.
     Select agent `Codex`, model `GPT 5.6 Sol`, effort `high`. Do NOT
     assume the modal pre-filled correctly from the prior task/agent — it
     usually resets to blank, but even when it doesn't, apply the same
     additive-toggle check above (deselect any stale effort, confirm the
     Launch button reads singular) before clicking `Launch`.
  4. Go back. Click `Run evaluation` again. Select agent `Oracle`,
     internet ON, `Launch`. (No model/effort fields for Oracle.)
  5. Do NOT wait for any of these to finish. Move to the next task in your
     slice via the dataset page's task list.
Do this for every task in your slice before starting Phase B.

**Safety-critical, repeat for emphasis: never click Launch/Run trajectory
without first reading that button's own label to confirm it says the
singular form. If it says "2" of anything, you have a doubled selection —
deselect the stale pill before proceeding. This has been observed to
silently double a run's billed cost.**

### Phase B — Launch QC (no waiting)
For each task in your slice, in order:
  1. Open the task page. Confirm the Claude Code and Codex evaluations
     have progressed enough to be clickable (they don't need to be
     finished, per the recipe — but must exist as rows). If clicking an
     eval's row silently does nothing (observed once while the run was
     still RUNNING), fall back to navigating directly to
     `https://data-os.turing.com/evaluations/{eval_id}` using the id from
     that run's `#NNNNNN` label.
  2. Click into the Claude Code eval run's row. Click `Agent Trajectory`.
     In the modal, ATTEMPT stays as pre-selected. Set MODEL to
     `GPT 5.6 Sol`, effort `medium`. **Same additive-toggle danger as
     Phase A: check for and deselect any other highlighted effort pill,
     and confirm the Run button reads `Run trajectory` singular (not a
     count) before clicking.**
  3. Go back to the task page via the breadcrumb. Click into the Codex
     eval run's row. Repeat the same Agent Trajectory / GPT 5.6 Sol /
     medium / Run trajectory sequence, with the same pre-click safety
     check.
  4. Skip Oracle entirely — no QC is run against it.
  5. If any evaluation row shows an EXCEPTION status rather than a normal
     PASS/FAIL, skip QC for that one run, note it in your report, and move
     on — do not block your slice on one broken run.
  6. Do NOT wait for verification runs to finish. Move to the next task.
Do this for every task in your slice before starting Phase C.

### Phase C — Collect artifacts
For each task in your slice, in order:
  1. Open the task page.
  2. In the `Evaluations` section, click `Select all`, then click
     `Download outputs (N)`.
  3. In the `Verifications` section, click `Select all`, then click
     `Download results (N)`.
  4. The files land in ~/Downloads as `task_<label>_evals.zip` and
     `task_<label>_verifications_results.json` (Chrome may append
     ` (1)`/etc. if a name collides — check for that before moving).
  5. Move both files into {OUTPUT_DIR}/task_<label>/ immediately (use
     Bash `mv`) so they don't collide with another worker's downloads of
     a same-shaped filename, and so ~/Downloads doesn't accumulate stale
     copies.
  6. If any evaluation/verification run never left RUNNING/PENDING by the
     time you reach this phase, note it in your report as "not ready for
     download" rather than downloading a partial/empty result.

## Your final report (return this as your last message)

Return, as plain structured text:
- Tasks fully completed (evals + QC + both downloads collected)
- Tasks partially completed, and exactly which phase/step they stopped at
- Any exceptions encountered (task label + which run + what status)
- Whether you stopped early due to the credit budget protocol above
- File paths of everything you saved under {OUTPUT_DIR}
```

### Step 6-7 — Collect and synthesize

Wait for all N subagents to return (they run in parallel; this is a
barrier — you need every worker's status before writing the final
report). Merge their reports into
`dataos_qc_runs/<dataset_name>/RUN_REPORT.md`:

```markdown
# DataOS QC run — <dataset_name>
Run on <date>. Fleet size: N. Tasks in scope: <total>.

## Summary
- Completed: X/<total>
- Partially completed: Y (see below)
- Blocked by credit exhaustion: <yes/no — which workers, at what point>
- Exceptions encountered: <count, list>

## Per-worker detail
### Worker 1 (tasks <label>..<label>)
<verbatim status from that subagent>
...

## Artifacts
All downloaded under dataos_qc_runs/<dataset_name>/task_<label>/
{evals.zip, verifications_results.json}
```

### Step 8 — Report to the user

Summarize the run in the chat: how many tasks got full QC signal, any
exceptions, and — most importantly — **whether the fleet ran out of
credits partway through**. If it did, say explicitly how many
tasks/phases are incomplete and that more credits need to be added to the
workspace before finishing the remainder. Do not imply completion if any
worker stopped early.

## Notes for future runs

- This skill only automates *launching* evals/QC and *collecting* the raw
  artifacts. Parsing `reward-details.json` / `*_verifications_results.json`
  for actual insights ("what verifier defects did this surface") is a
  separate follow-on step, not part of this skill.
- If Data-OS's UI changes (button labels, modal fields, URL patterns),
  update [RECIPE.md](../../reference/dataos_recipe/RECIPE.md) first, then
  re-check this file's Phase A/B/C descriptions still match it.
