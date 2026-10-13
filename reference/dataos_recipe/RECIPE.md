# DataOS QC-Run Recipe

Captured live by walking through https://data-os.turing.com/datasets/273 (dataset `QCR_EKW_Luiz`, 80 tasks) with Luiz driving and Claude logging.

Goal: codify the exact click-path a human takes to run QC through DataOS for a task, so it can be replayed by N parallel agents — each agent owns a disjoint subset of the dataset's tasks and runs the full pipeline on each of its tasks.

## Fleet model (confirmed by Luiz)

- Step 0 (always, once per dataset): open the dataset page, expand **Tasks (N)**, partition the full task list into disjoint subsets — one subset per agent.
- Each agent then repeats the per-task pipeline (steps below) for every task_id in its subset.

## Per-agent orchestration loop (confirmed by Luiz)

Within an agent's assigned task subset, evaluations are the outer loop and QC/verification is a second pass done only after ALL tasks in the subset have their evals launched:

1. For each task in the agent's subset (in any order): open the task page → launch `Run evaluation` for every required agent (Claude Code, Codex, and Oracle if the project needs 3; Oracle is the run that grades the golden answer itself, see Step 7 and Step 9) → **do not wait** for any of them to finish (they run async and can take a long time) → navigate back to the dataset page → expand `Tasks` dropdown → pick the next task in the subset that hasn't had evals launched yet → repeat.
2. Only once **every** task in the subset has had its evaluations launched does the agent start the second pass: go back to the first task and run `Verifications` (`QC` button, described next).
3. Rationale: evals are the slow/expensive async step: front-load launching all of them across the whole subset first (maximizing parallel run time in the background) rather than blocking on each one before moving to the next task.
4. **The verification/QC pass (second phase) follows the exact same front-load pattern, one level down**, per Luiz: for each task, open its model-based eval runs (Claude Code, Codex — never Oracle) one at a time, click `Agent Trajectory` → configure `GPT 5.6 Sol`/`medium` → `Run trajectory`, then **don't wait** — go back to the dataset page, pick the next task, and launch its QC runs too. Verifications are noted as generally **faster** than evaluations, but still async (Step 13) — so the same "launch everything, then come back and collect" discipline applies. Only after every task's QC has been launched does the agent circle back to read/collect the `Checks (N)` results (Step 12) across all of them.
5. **Full lifecycle per task, summarized:** dataset page → open task → launch eval(s) (Claude Code, Codex, Oracle) → [move to next task, repeat] → ALL evals launched for subset → return to task 1 → open each model-based eval run → launch its QC (`Agent Trajectory` → model/effort → `Run trajectory`) → [move to next task, repeat] → ALL QC launched for subset → return to task 1 → collect `Checks (N)` results per model-based run → [move to next task, repeat] → done with the subset.

## Step log

### Step 0 — Dataset overview page
- URL: `https://data-os.turing.com/datasets/273`
- Screenshot: `screenshots/step0_dataset_overview.jpg`
- Observed elements (top bar): `Edit`, `Share`, `Archive`, `Report` (dropdown), `Download`
- Validation issues panel: lists tasks with warnings (e.g. `task_346: Has 1 warning.`), `Show more (80)` expander — NOTE: every task in this batch currently shows a warning; not yet confirmed whether this blocks the QC run or is informational only.
- Task list section: header `Tasks (80)`, collapsed by default, click to expand. Buttons alongside: `New task`, `Upload tasks`.
- Below tasks: `Evaluation Batch Runs (0)`, `Verification Batch Runs (0)`, `Training Runs (0)` — collapsed sections, currently empty for this dataset.
- **Action to capture next:** expand `Tasks (80)`, click into `task_346`.

### Step 1 — Task detail page (task_346)
- URL pattern: `https://data-os.turing.com/tasks/{internal_task_numeric_id}` — for `task_346` the numeric id was `20960`. **Note:** the URL id is NOT the `task_NNN` label; it's an internal DB id assigned on upload. An agent can't construct this URL from the task label alone — it must navigate via the dataset's task list link, or resolve the mapping some other way (TBD — may need to check if task list rows expose it, or if search works).
- Reached by: expanding `Tasks (80)` on the dataset page, clicking the `task_346` row.
- Screenshot: attempted via `save_to_disk`, but the file is not reachable on the local filesystem via Bash (searched broadly, not found) — the claude-in-chrome screenshot tool appears to store images in a location only visible inline in the chat transcript, not as an addressable path. **Flagging to Luiz**: screenshots will stay in-transcript only for now; the recipe records structural/textual state (elements, labels, warnings) instead. If literal screenshots need to persist in the recipe db, we need a different capture path (e.g. Luiz saves them manually, or we find the real storage location).
- Header: `task_346` `READY` badge; buttons: `History`, `Edit`, `Set benchmark type`, `Archive`, `Download`
- Validation issues panel: `WARNING · Missing [metadata].benchmark_type. Valid choices: cyber-bench, swe-bench, swe-efficiency, slop-code-bench, kernel-bench, inference-bench, terminal-bench, mle-bench, ds-bench, scicode-bench, program-bench` — matches the known EKW convention of deliberately omitting `benchmark_type` (see project CLAUDE.md, "Strict Harbor Task Format") — this warning is expected/benign for EKW tasks, not a defect to fix.
- `Instruction` panel — full task prompt text, collapsed behind `Show more`.
- `Tests (21)` — collapsed section (verifier checks count, presumably).
- `Evaluations` section: button `Run evaluation`; currently "No evaluations yet."
- `Verifications` section: buttons `QC` and `Comprehensive Review` (Comprehensive Review is not used by this recipe, see "Recipe status" below); text "No verifications yet. Try the QC button or ask a custom question."; a free-text `Ask` box.
- `Comments (0)` section with `New comment` input.
- **Answered:** pipeline order is **Evaluations first, then Verifications**. Concretely: `Run evaluation` is step 1 of the per-task pipeline.
- **Pre-check before running:** confirm `Tests (N)` count is > 0 for this task (visible right below the Instruction panel) — a task with 0 tests presumably can't be meaningfully evaluated/verified. An agent should read this count before clicking `Run evaluation` and flag/skip tasks where it's 0.

### Step 2 — "Run evaluation" modal
- Location: `Evaluations` section, button labeled exactly `Run evaluation`. Clicking it opens a modal titled **"Run evaluation"** (dialog, closable via `X` top-right or `Cancel`).
- Modal fields, top to bottom:
  1. **AGENT** — dropdown, single-select. Confirmed values in use for this project: `Claude Code`, `Codex`, `Oracle` (dropdown not yet expanded to confirm full option list/exact labels — TBD next).
  2. **MODELS** — checkbox list, contents depend on the selected agent. For `Claude Code` agent, options observed: `Claude Opus 4.6 (anthropic)`, `Claude Opus 4.7 (anthropic)`, `Claude Opus 4.8 (anthropic)`, `Claude Opus 5 (anthropic)`, `Claude Sonnet 5 (anthropic)`. Multi-select is allowed (footer shows "N model selected") but for this run policy exactly 1 model per run is checked.
     - Under a checked model, a **Reasoning effort** row appears with pill options: `low`, `medium`, `high`, `xhigh`, `max`. Exactly one must be selected (highlighted in blue) — confirmed default/required for this project is **`high`**.
  3. **Allow internet access** — checkbox, ON by default. Leave on (per Luiz).
  4. Footer buttons: `Cancel` / `Launch` (▶ icon).
- **Run policy (per Luiz):** for a given task, run **Evaluations at least twice — once per required agent** (2 by default, sometimes 3 depending on the project): `Claude Code` and `Codex` always; add `Oracle` when the project calls for a 3rd. Default model choice per project convention: "the best OpenAI and the best Anthropic models" — for `Claude Code` that's currently `Claude Opus 4.8` at `high` effort. Each agent gets its own separate `Run evaluation` invocation (modal reopened, agent switched, model+effort reselected, `Launch` clicked again) — this is **not** a multi-agent single launch.
- **Open question:** what is the equivalent model selection for the `Codex` agent (presumably an OpenAI model list appears in MODELS once Codex is selected), and what is `Oracle` exactly (a third distinct agent, or a special no-model verification mode)? Need to see the Codex + Oracle dropdown states next.
- **Automation gotcha (Luiz confirmed):** the AGENT dropdown closes on tab/window blur (alt-tab). Any agent driving this UI must complete a select→click sequence in one continuous flow without switching focus away from the tab while the dropdown is open — can't alt-tab mid-selection to consult notes/screenshots.

### Step 3 — Post-launch: evaluation attempt page
- After `Launch`, the browser redirects to `https://data-os.turing.com/evaluations/{eval_id}` (e.g. `.../evaluations/124746`).
- Breadcrumb: `Datasets > QCR_EKW_Luiz > task_346 > Claude Code / Claude Opus 4.8 #124746` — **the `task_346` breadcrumb segment is a hyperlink back to the task detail page.**
- Page header: `Claude Code / Claude Opus 4.8` `high` tag, `#124746` (eval id), status badge (`RUNNING` here), `Task task_346` link, created timestamp, `Internet enabled` indicator.
- `Attempt` panel: `Attempt 1` `#144458` with its own status badge — **status badges progress independently at run-level and attempt-level**: queue (sometimes) → `PENDING` → `RUNNING` → `PASS`/`FAIL`/`EXCEPTION`.
- `Attempt 1 overview`: `REWARD` (0.00 while running), `MODEL COST` (— while running), `ENVIRONMENT` (— while running).
- `Attempt 1 details` tabs: `Trajectory` (selected, "Empty." while running), `Charts`, `Tests`.
- `Verifications · Attempt 1`: "No verifications yet." (verifications are attached later, per attempt).
- `Comments (0)` section.
- **Confirmed by Luiz: do NOT wait for the run to finish here.** A run takes a while (RUNNING can persist for a long time). Immediately navigate back to the task page via the `task_346` breadcrumb link to launch the next agent's evaluation (Codex, then Oracle if the project needs a 3rd) — evaluations run asynchronously and don't block the next launch.

### Step 4 — Back on task page: Evaluations section now shows filters + run list
- Once ≥1 evaluation exists for the task, the `Evaluations` section header grows two filter dropdowns: `All agents`, `All models` (to filter the run list below by agent/model — not yet exercised, presumably lets you narrow the list when many runs exist).
- Below that: `Select all` checkbox + one row per existing run, e.g. `Claude Code / Claude Opus 4.8` `high` `#124746` `Running` `RUNNING` — each row has its own checkbox (bulk-action target, purpose TBD — maybe bulk re-run/compare/delete).
- `Run evaluation` button still present to launch another run alongside existing ones.

### Step 5 — "Run evaluation" modal for Codex agent
- Selecting `Codex` in the AGENT dropdown swaps the MODELS list to OpenAI models. Observed (scrollable list, partial — scrolled to middle): `GPT-5.5-cyber (openai)`, `GPT 5.5 Pro (openai)`, `GPT 5.6 Luna (openai)`, `GPT 5.6 Sol (openai)`, `GPT 5.6 Terra (openai)` (list scrolls, likely more entries above the visible window — not yet confirmed top of list).
- Project default for Codex: check `GPT 5.6 Sol (openai)`, reasoning effort `high`. Effort pill options for this model: `none`, `low`, `medium`, `high`, `xhigh` (one more option — `none` — than Claude Code's effort set, which was `low/medium/high/xhigh/max`).
- **Gotcha (Luiz flagged):** the effort selector can retain a stale prior selection (e.g. `medium`) when switching models/agents — always explicitly verify/click `high` rather than assuming the default is correct. Same "exactly one box + one effort pill" pattern as Claude Code.
- `Allow internet access` stays checked; same `Cancel`/`Launch` footer.
- Same async pattern applies: after `Launch`, don't wait — return via breadcrumb to launch the next (Oracle, if this project needs 3).

### Step 6 — Task page once evaluations complete: "Test Results Matrix" appears
- Once at least one evaluation run has finished, a new section appears **above** `Instruction`'s neighbor area, right below `Tests (21)`: **Test Results Matrix**, with a `CSV` export button and a sortable table (`↕` on the `TEST` / `Pass rate` header).
- Table layout: one column per completed run (header = `AGENT-NAME` (caps) / model / effort / aggregate pass rate, e.g. `CLAUDE-CODE` / `Claude Opus 4.8` / `high` / `95.2%`), one row per named verifier/test (e.g. `anti-overstatement`, `applies-from-timing`, ... `remittance-pinning`, ... `workbook-scope` — 21 rows matching `Tests (21)`), cell = pass rate % + colored pass/fail icon. Legend at bottom: `Passed` (green check) / `Failed` (red x) / `Skipped`.
- In this run, 20/21 named tests passed at 100% for Claude Code/Opus 4.8; only `remittance-pinning` failed at `0%`. This is the per-verifier breakdown that feeds the run's aggregate `Reward`.
- **This matrix is a key artifact for QC insight-gathering** — it's where per-verifier pass/fail across every launched agent/model run lives, exportable as CSV. The eventual multi-agent skill should scrape/export this per task once all its evaluations complete.

### Step 6b — Evaluations section: completed-run row format
- Once runs finish, `Evaluations` list rows show far more than the earlier `Running` state:
  - Row 1: `Claude Code / Claude Opus 4.8` `high` `#124746` — `Reward 0.95 · 20 Passed · 1 Failed` — `Total cost $2.1261` — `Tokens 1,219,611 in · 42,699 out` — `Steps 27` — `Tools 25` — status badge `FAILED` (top-right of row).
  - Row 2: `Codex / GPT 5.6 Sol` `high` `#124784` (globe icon = internet-enabled indicator) — `Reward 0.97 · 20 Passed · 1 Failed` — `Total cost $1.6640` — `Tokens 913,042 in · 29,452 out` — `Steps 28` — `Tools 22` — status badge `FAILED`.
  - **Note:** a run whose Reward is high (0.95, 0.97) can still show top-level status `FAILED` — this project's convention is any failed named test (here `remittance-pinning`) fails the whole run regardless of aggregate reward. Don't infer pass/fail from the Reward number alone.
  - Filter dropdowns now list actually-used values: `All agents` → includes `Claude Code`, `Codex`; `All models` → `Claude Opus 4.8`, `GPT 5.6 Sol`.
  - Credits ticked up between screenshots (US$251.96 → US$255.75 used) — each evaluation run has a real $ cost against the workspace credit balance, separate from the per-run `Total cost` shown (that's model-inference cost; workspace credits presumably cover the Data-OS runtime overhead too — not yet confirmed, TBD).

### Step 7 — "Run evaluation" modal for Oracle agent (simplest)
- Selecting `Oracle` in AGENT collapses the whole MODELS section — it doesn't appear at all for this agent (Oracle has no model choice).
- Modal reduces to just: `AGENT` dropdown (`Oracle`), `Allow internet access` checkbox (leave checked), `Cancel`/`Launch`. No effort selector either.
- Confirms Luiz's description: "Oracle is simpler as there's no need to select any models, just select oracle and launch."

### Step 8 — Moving to the next task in the subset
- From the dataset page, expand `Tasks` and click the next unprocessed task in the agent's assigned subset. Observed: `task_346` → `task_335`, URL `.../tasks/20960` → `.../tasks/20959` (internal ids happened to be adjacent/descending here; **do not rely on id adjacency** — always navigate via the task list, not by guessing/incrementing the numeric id).
- New task page (`task_335`, `READY`, `Tests (26)`) looks structurally identical to Step 1: same header buttons, same `benchmark_type` warning, `Evaluations`/`Verifications`/`Comments` sections all empty/fresh for this task.
- **Gotcha confirmed:** opening `Run evaluation` on a fresh task **pre-fills the modal with the last-used agent/model/effort from the previous task** (here: `Claude Code` / `Claude Opus 4.8` / `high` already selected, `1 model selected`, internet access still checked) — so for the common case (same agent+model+effort every task) the agent doesn't need to reselect anything, just click `Launch` directly. Only needs to actively change fields when switching agent (e.g. moving on to Codex/Oracle) or when the project's default differs.

### Step 9 — Revisit task_346 after all 3 evals finished
- All 3 runs completed: `Claude Code / Claude Opus 4.8` `#124746` — Reward 0.95, 20 Passed/1 Failed, **FAILED**; `Codex / GPT 5.6 Sol` `#124784` — Reward 0.97, 20 Passed/1 Failed, **FAILED**; `Oracle` `#129009` — Reward 1.00, 21 Passed/0 Failed, **PASSED**, cost only $0.0029 (Oracle is cheap — no model inference, presumably a deterministic/rule-based check).
- **Exception handling (per Luiz):** if any run's status shows an exception (distinct from FAILED/PASSED), flag it and move on without that run — don't block the pipeline on a single erroring run.
- `Evaluations` filter dropdowns now populated: `All agents` → `Claude Code`, `Codex`, `Oracle`; `All models` → `Claude Opus 4.8`, `GPT 5.6 Sol`, `No model` (Oracle has no model, hence this filter value).
- **Important:** `Test Results Matrix` only grew a column for the two model-based runs (`CLAUDE-CODE`/`Claude Opus 4.8`/high/95.2%, `CODEX`/`GPT 5.6 Sol`/high/95.2%) — **Oracle's PASSED run does not appear as a matrix column**, consistent with Luiz's next instruction that QC only consumes model-based evals, not Oracle.
- **Answered:** it's (b) — click into the model-based eval run row itself. Oracle's row is not used for QC (only the model-based agents' runs are — Claude Code and Codex here).

### Step 10 — Inside a model-based eval run page (clicked `Claude Code / Claude Opus 4.8 #124746` row)
- URL: `https://data-os.turing.com/evaluations/124746` (same eval-detail page seen in Step 3, but now fully populated post-completion).
- Header now has two new buttons (absent while RUNNING): **`Agent Trajectory`** and **`Loss Pattern`**, top-right, alongside the existing `FAILED` status badge.
- **`Agent Trajectory` is where QC gets triggered** (per Luiz) — this is the actual next click, not the task-level `QC` button seen in Verifications. `Loss Pattern` is a separate, not-yet-explored button (out of scope for this recipe, see "Recipe status" below; TBD what it does — presumably a diagnostic view of why the run failed).
- `Attempt 1` panel now shows a completed timeline bar: `Environment setup 56.3s` → `Agent setup 15.3s` → `Agent execution 9m 33s` → `Verifier 1m 45s` → `Total 12m 30s`, plus a `Download` button for the attempt.
- `Attempt 1 overview` now fully populated: `REWARD 0.95`, `TESTS 20 P · 1 F`, `STEPS 27`, `TOOL CALLS 25`, `MODEL COST $2.0913`, `ENVIRONMENT DAYTONA`, `ENV COST $0.0348`, `DELIVERABLES 0.95`.
- `Attempt 1 details` tabs: `Trajectory` (selected — full transcript of the agent's tool calls/reasoning/turns, numbered `#1`, `#2`, ... with role `USER`/`AGENT`, timestamps, and a "N tool call" chip per turn), `Charts`, `Tests`. This is the raw trajectory a QC reviewer would read to sanity-check the run before/while running QC.
- `Verifications · Attempt 1`: still "No verifications yet." — confirms QC/verification is scoped per-attempt, triggered from this page via `Agent Trajectory`, not from the task-level page.
- **Awaiting next click:** Luiz to click `Agent Trajectory` to reveal what "QC gets triggered" actually looks like (likely opens the QC config/launch UI in a new context).

### Step 11 — "Run trajectory verification" modal (this IS the QC launch)
- Clicking `Agent Trajectory` opens a modal titled **"Run trajectory verification"**, subtext: *"A predefined agent-trajectory verification will analyze the selected attempt using the chosen model. Results show up in the Verifications panel."* — confirms this modal's output lands in the `Verifications · Attempt 1` section back on the eval page.
- Fields:
  1. **ATTEMPT** — dropdown, pre-selected to the only/most-recent attempt: `Attempt 1 · #144458 · FAILED`. Nothing to change here per Luiz ("there's nothing to change about it") — only relevant if a run has multiple retry attempts.
  2. **MODEL** — dropdown, a second, separate model list from the one used for `Run evaluation`. **Project rule (confirmed by Luiz): always use `GPT 5.6 Sol (openai)` at `medium` reasoning effort for this QC step** — regardless of which agent/model produced the eval being reviewed (i.e. same QC judge model for both the Claude Code run and the Codex run). Effort pills here: `none`, `low`, `medium`, `high`, `xhigh` (no `max` — same reduced set as Codex's eval-time effort options).
     - **Note:** in this instance the modal already showed `GPT 5.6 Sol` / `medium` preselected (state may persist from a prior session/account default) — but per Luiz's instructions, don't assume: "click on the dropdown and scroll down a bit on the list to find the option" — treat it as always needing an explicit select, not a trusted default (unlike the eval-launch modal in Step 8, which explicitly does carry over selection).
  3. Footer: `Cancel` / `Run trajectory` (✨ icon) button — this is the actual QC-launch action.
- After clicking `Run trajectory`, repeat this exact same Step 10→11 sequence for the `Codex / GPT 5.6 Sol #124784` eval run (click into that run's row from the task page, click `Agent Trajectory`, leave ATTEMPT as-is, set MODEL to `GPT 5.6 Sol` / `medium`, click `Run trajectory`). Oracle's run is skipped — QC only runs against the model-based agent evals.

### Step 12 — The QC verification result page (the actual QC output artifact)
- After `Run trajectory` (it appears to run synchronously/fast — no waiting observed), you land on `https://data-os.turing.com/verifications/{verification_id}` (e.g. `.../verifications/12598`).
- Breadcrumb: `Datasets > QCR_EKW_Luiz > task_346 > Claude Code / Claude Opus 4.8 #124746 > Agent Trajectory · GPT 5.6 Sol #12598` — **the `task_346` segment is the hyperlink Luiz uses to jump straight back to the task page** (skips the intermediate eval page).
- Header: `Agent Trajectory · GPT 5.6 Sol` `medium` `#12598` `FAILED` badge; subheader `Level: Evaluation · Context: Task #20960 and Evaluation Run #144458` (both are hyperlinks back to their respective pages); `Created on`, `by`, `Tokens: 34,251 in · 1,199 out`, `Cost: $0.2024`; `Download` button.
- **`Checks (N)` — this is the actual QC deliverable.** For this run: `Checks (8)`, grouped `FAILED 2` / `PASSED 6`. Each check has a fixed name + pass/fail badge + a narrative paragraph explaining the verdict. Fixed check names observed (appear to be a **standard 8-check rubric the platform always runs**, not task-specific): `Test Accuracy`, `Test Failure Attribution`, `Task Clarity`, `False Positive Risk`, `Environment Adequacy`, `Requirement Coverage`, `Trajectory Integrity`, `Error Message Actionability`.
- **This is exactly the kind of insight this whole pipeline exists to surface**: e.g. here `Test Accuracy` and `Test Failure Attribution` both FAILED with the narrative diagnosing that task_346's `remittance-pinning` verifier criterion is **overly rigid** — it required an undocumented tabulation format not actually demanded by the task instruction, so the agent's substantively-correct answer was wrongly marked failed. This is a verifier-quality defect surfaced by the QC step, not an agent competence issue — directly actionable for the "known issues" QC workflow (fix the rubric).
- **The multi-agent skill's artifact-collection step should scrape, per task, per model-based eval run: the verification's `Checks (N)` list (name/verdict/narrative), `FAILED`/`PASSED` counts, cost, and a Download of the full page/report if available** — this is the raw material for "insights and fixes needed."
- Confirmed: clicking the `task_346` breadcrumb segment returns to the task main page — ready to repeat Steps 10–12 for the Codex run.

### Step 13 — Correction: verification runs are async, not instant
- Repeating Steps 10–11 for `Codex / GPT 5.6 Sol #124784`: same `Run trajectory verification` modal, MODEL `GPT 5.6 Sol`/`medium`, `Run trajectory` clicked.
- **Correction to Step 12's assumption:** this time the resulting page (`.../verifications/12605`) showed status `RUNNING` with body text **"Verification is running…"** and a spinner — `Checks` section not present yet. So verification is **not always synchronous**; it can take a noticeable amount of time just like an evaluation run. The Step 12 Claude Code run happened to already be done by the time we viewed it (or was fast that time) — an automated agent must not assume `Checks (N)` will be immediately present after `Run trajectory` and should poll/revisit the verification page rather than treating results as instantly available.
- Same breadcrumb pattern: `Datasets > QCR_EKW_Luiz > task_346 > Codex / GPT 5.6 Sol #124784 > Agent Trajectory · GPT 5.6 Sol #12605`.

### Step 14 — Task page once both QC runs complete: `Verifications` section populated
- Mirrors the `Evaluations` section's evolution (Step 4/9): once verifications exist, `Verifications` gains filters (`All types` → `Agent Trajectory`; `All models` → `GPT 5.6 Sol`) and a `Select all` checkbox + one row per verification run.
- Row format: `Agent Trajectory · GPT 5.6 Sol` `medium` `#{id}` — `On {eval agent/model} {effort} #{eval_id}` (back-reference to the eval it graded) — `Total cost`, `Tokens in/out` — status badge (`FAILED` here, matching both underlying evals' FAILED status — both diagnosed the same `remittance-pinning` rubric defect).
- Both `QC` and `Comprehensive Review` buttons remain available for launching more verification runs (we've only exercised `QC`/`Agent Trajectory` so far — `Comprehensive Review` still unexplored).
- This task (`task_346`) is now fully done: 3 evals + 2 QC verifications, all visible and collected on one page — this is the per-task end state an agent reaches before moving to artifact collection.

### Step 15 — Artifact collection & download (in progress — Luiz explaining the goal)
- Goal stated by Luiz: once every task in the subset has completed the full eval+QC loop, **fetch all relevant artifacts and download them via the DataOS interface** — this is the final phase before handing results off for insight-gathering/fixes.
- Not yet demonstrated: which exact button(s) perform this (task-level `Download` button seen in Step 1's header? bulk-select checkboxes + a bulk download action in `Evaluations`/`Verifications`? dataset-level `Download`/`Report` button seen in Step 0?). **Awaiting Luiz's next click(s) to capture the actual download mechanism and what file(s)/format it produces.**

### Step 16 — Confirmed download mechanism: per-section "select all" + bulk download button
- On the task page, `Evaluations` section: click the `Select all` checkbox next to its column headers — it turns into `Deselect all` · `N selected`, and a **`Download outputs (N)`** button appears in the section's header row (replacing/alongside `Run evaluation`). Here: all 3 evaluation runs selected → `Download outputs (3)`.
- Symmetrically, `Verifications` section: click its own `Select all` → `Deselect all` · `N selected` → a **`Download results (N)`** button appears. Here: both QC runs selected → `Download results (2)`.
- **Two independent checkbox groups, two independent bulk-download buttons** — one per section, each downloading only that section's selected items. Individual per-run checkboxes (seen since Step 4/Step 14) are what feed the "select all" count; a subset of runs can be selected instead of all if only some are wanted.
- Per Luiz's instruction, the artifact-collection procedure per task is: select all evaluations → `Download outputs (N)` → select all verifications → `Download results (N)`. Not yet confirmed: exact downloaded file format/contents (zip? per-run files? naming convention?) or the browser's save-location behavior — next click should trigger the actual download and reveal this.

### Step 17 — Confirmed downloaded artifact contents (this is the payoff — machine-parseable, not just human-readable)
Files landed directly in `~/Downloads/` (standard browser download, no dialog needed):

- **`task_{label}_evals.zip`** (`Download outputs`, from Evaluations) — one top-level folder per eval run, named `{agent}_{model_slug}_eval_{eval_id}_attempt_{n}/` (e.g. `claude-code_claude_opus_4.8_eval_124746_attempt_1/`, `codex_gpt_5.6_sol_eval_124784_attempt_1/`, `oracle_eval_129009_attempt_1/`). Each contains:
  - `agent/` — raw agent transcript/log (`claude-code.txt` or `codex.txt`), full session data (`sessions/` incl. `.jsonl` rollout), and `trajectory.json` (structured version of the Step 10 Trajectory tab).
  - `artifacts/app/` — the actual deliverable files the agent produced (e.g. `Fernbank Management Audit Letter.docx`, `Fernbank Management Audit Workbook.xlsx`), plus `manifest.json`.
  - `verifier/` — `reward.json` (top-level reward float), `reward-details.json` (the full per-verifier breakdown behind the Step 6 Test Results Matrix — this is the structured form of that table), `runtime.log`, `test-stdout.txt`.
  - `config.json`, `lock.json`, `result.json`, `trial.log` at the run-folder root.
  - Oracle's folder is present but sparse (no `agent` transcript content, no model — matches it having no model in the UI).
- **`task_{label}_verifications_results.json`** (`Download results`, from Verifications) — top-level key `"verifications"`, one entry per verification run, each with: `verification_id`, `tasks` (`[{id, name}]` — the internal numeric id + `task_NNN` label pair, resolving Step 1's open question about that mapping), `verification_model`, `status`, `evaluations` (back-reference: `id`, `run_id`, `status`, `agent`, `model` — which eval this verification graded), and `turns[].output.checks` — **a dict keyed by snake_case check id** (`task_clarity`, `test_accuracy`, `false_positive_risk`, `environment_adequacy`, `requirement_coverage`, `trajectory_integrity`, ...) each with `outcome` (`"pass"`/`"fail"`) and `explanation` (the narrative text seen in Step 12's UI). **This is the structured, directly-parseable form of the Step 12 `Checks (N)` cards** — no HTML scraping needed once this file is downloaded.
- **Implication for the skill:** artifact collection doesn't need to scrape the UI at all for the actual insight-gathering step — it only needs to (a) drive the UI through Steps 1–16 to launch/select runs, then (b) download these two files per task and let a downstream script parse `reward-details.json` (per-verifier pass/fail matrix) + `*_verifications_results.json` (`checks{}` dicts with explanations) directly. This is much more reliable than HTML/DOM scraping for the analysis phase.
- **Naming convention to confirm at scale:** with 80 tasks, each agent needs a predictable download filename per task (`task_{label}_evals.zip`, `task_{label}_verifications_results.json`) and should move/rename them out of `~/Downloads` into a per-cycle folder (e.g. `cycles/<date>/dataos_qc_runs/task_{label}/`) immediately after each download, since Chrome will otherwise auto-suffix repeat downloads (`task_346_evals (1).zip`) and collide across tasks/agents sharing one Downloads folder.

## Recipe status: complete end-to-end for one task

Confirmed full loop, Luiz-approved: **dataset page → partition tasks per agent → [launch evals for every task in subset, no waiting] → [launch QC for every task's model-based evals, no waiting] → [revisit each task, download evals.zip + verifications.json] → next task, repeat until subset done.**

Resolved by Luiz (2026-08-04):
1. **`Loss Pattern` and `Comprehensive Review` are out of scope.** `Run evaluation` (3 agents) + `Agent Trajectory`/QC (2 model-based runs) + the two bulk downloads are the complete, minimal set of clicks needed to get enough QC signal. Do not add these extra buttons to the automated loop.
2. **The `benchmark_type` validation warning is universally benign** for every EKW task (expected/deliberate per the Strict Harbor Task Format convention) — the skill should dismiss/ignore it unconditionally, never treat it as a blocker.
3. **Credit budget is a hard stop, not a thing to optimize around.** Each agent must track remaining credits (dataset-page sidebar: `US$ X used / Y total`) and, before launching the next run, check whether it can afford it. If the budget is exhausted (or a launch fails due to insufficient credits), the agent must **stop immediately**, record exactly which tasks/runs it had completed vs. not yet reached, and report to the user that the run halted due to insufficient credits and more are needed to continue — never silently retry or degrade.
4. **Downloaded artifacts go into a dedicated directory named after the dataset**, not a cycle-dated folder — e.g. `dataos_qc_runs/<dataset_name>/task_<label>/{evals.zip, verifications_results.json}`. A new dataset name means a new folder; this is independent of the `cycles/<date>/` convention used elsewhere in the project.

**Recipe frozen — proceeding to build the `dataos-qc-run` skill from Steps 0–17 above.**

## Dry-run correction (2026-08-04) — CRITICAL safety fix

A dry-run subagent (driving programmatically via `form_input`, not mouse
clicks) surfaced a materially more dangerous version of the Step 5/8 "stale
effort selector" gotcha:

- **The reasoning-effort pills are ADDITIVE TOGGLES, not a single-select
  radio group**, contrary to this recipe's earlier assumption ("Exactly
  one must be selected"). Clicking the desired effort (e.g. `high`) when a
  stale prior effort (e.g. `medium`) is still highlighted does **not**
  replace the selection — it adds a second one. The `Launch` button's label
  changes to reflect this (`Launch 2 evaluations` instead of `Launch`),
  and clicking it would launch **two separate billed runs** (one per
  selected effort) instead of one.
- **Corrected procedure for any agent (human or automated) selecting
  effort:** before/after clicking the required effort pill, explicitly
  check for and deselect any other highlighted effort pill. Then, as a
  final safety check before clicking `Launch`/`Run trajectory`, **read the
  button's own label** — it must read the singular form (`Launch`, not
  `Launch N evaluations`) confirming exactly one run will be created.
  Never click Launch/Run without this check.
- Step 8's claim that a fresh task's `Run evaluation` modal pre-fills
  agent/model/effort from the previous task **did not reproduce** in the
  dry run (modal reset to a blank "Select an agent…" placeholder every
  time) — downgrade that claim from "confirmed" to "sometimes observed,
  don't rely on it"; always explicitly (re)select every field.
- Clicking directly into a still-RUNNING evaluation's row from the task
  page silently no-opped once during the dry run; navigating directly to
  `https://data-os.turing.com/evaluations/{id}` worked as a fallback.
- Evaluation runtime observed in the dry run exceeded the ~12.5 min example
  in Step 10 — both Claude Code and Codex runs were still RUNNING after
  15+ minutes. Treat Step 10's timing as a lower bound, not an expectation;
  Phase B (QC launch) may need to be retried/re-checked rather than assumed
  ready immediately after Phase A finishes for the whole slice.
