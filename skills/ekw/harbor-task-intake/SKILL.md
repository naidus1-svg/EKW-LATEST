---
name: harbor-task-intake
description: >-
  Walk a non-technical subject-matter expert through submitting a brand-new
  task — interviewing them for the prompt, source documents, expert (golden)
  solution, and grading rubric — then assemble those loose pieces into an
  internal-harbor task folder (`assemble_task.py`) and, from that, a
  dataos-harbor task folder (`to_dataos_harbor.py`) ready for DataOS upload.
  Use when an expert wants to "submit a task", "build a harbor task from
  scratch", "get my task ready for DataOS", or "I have a prompt/docs/rubric,
  what do I do with them" — i.e. task INTAKE, starting from loose files, not
  reformatting a task that's already in harbor shape (for that, see
  `harbor-rewardkit-convert`).
---

# Harbor task intake

Turns four loose pieces an expert already has sitting on their machine —
a prompt, some source documents, their own solution, and a grading rubric —
into two ready-to-use task folders:

1. **internal-harbor** — the format `gdpval-assess` and the Harbor-beta
   eval-request path (`harbor_evals.py`) consume directly.
2. **dataos-harbor** — the same task, patched so DataOS's own upload
   validator (`rewardkit.discover()`) doesn't choke on it.

You are running an **interview + pipeline**, not writing new conversion
logic. The scripts below already exist and are the canonical source of
truth — your job is to collect clean inputs, catch problems before the
scripts do, and run them in order.

If the expert already has a task fully in harbor shape (has `task.toml`,
`instruction.md`, `environment/`, `tests/verifier.json` already) and just
wants the strict reward-kit format DataOS grades against, that's a
*different* skill: [`harbor-rewardkit-convert`](../harbor-rewardkit-convert/SKILL.md).
This skill is for the step *before* that exists — raw pieces, no folder
structure yet.

## What "done" looks like

"Done" means a task that actually **runs**, not just one that's correctly
shaped — a full `task.toml` (verifier/agent/environment sections included,
not just `[metadata]`), a real grading harness, and an oracle solver, so
`bash tests/test.sh` against a `solve.sh`-populated workspace grades for
real without a second manual pass:

```
<out>/<task_id>/                    # internal-harbor
├── instruction.md
├── task.toml                       # full: [verifier]/[agent]/[environment]/[metadata]
├── environment/
│   ├── Dockerfile                  # build recipe, copied verbatim (always added, automatic)
│   ├── data/                       # expert's source docs (if supplied)
│   ├── data.dvc                    # shared-corpus DVC pointer (always added, automatic)
│   └── .dvc/config
├── solution/
│   ├── golden_outputs/             # expert's solution files (if supplied)
│   └── solve.sh                    # oracle solver (only if a golden solution was supplied)
└── tests/
    ├── verifier.json
    ├── test.sh                     # generic harbor runtime, copied verbatim
    ├── verifier_runtime.py
    └── verifier_lib/

<out>/<task_id>_dataos_harbor/      # dataos-harbor (same task, upload-safe)
└── ... same tree, tests/ patched (test.sh, verifier_runtime.pyrun, __verifier_lib/)
```

Both are real script outputs — [`assemble_task.py`](../../../pipeline/tools/assemble_task.py)
for the first, [`to_dataos_harbor.py`](../../../pipeline/tools/to_dataos_harbor.py)
for the second. Don't hand-edit either tree; if something's wrong, fix the
loose input and re-run.

## Workflow

Track this checklist as you go:

```
- [ ] 1. Collect task_id and category
- [ ] 2. Collect and sanity-check the prompt
- [ ] 3. Collect source documents (optional but typical)
- [ ] 4. Collect the expert (golden) solution (optional, recommended)
- [ ] 5. Collect or build the grading rubric (verifier.json) — required
- [ ] 6. Cross-check the four pieces against each other
- [ ] 7. Run assemble_task.py -> internal-harbor
- [ ] 8. Smoke-test the internal-harbor task for real (solve.sh + test.sh)
- [ ] 9. Run to_dataos_harbor.py -> dataos-harbor
- [ ] 10. Verify both outputs and report next steps
```

Don't silently assume defaults for anything the expert hasn't told you —
ask. But don't ask everything up front either: work through the checklist
in order, since later answers (e.g. deliverable filenames) depend on
earlier ones (the prompt).

### Step 1 — task_id and category

Ask for:
- **task_id** — short, filesystem-safe (letters/digits/`-`/`_`). If they
  don't have one yet, propose a slug from the prompt's subject and confirm
  it with them rather than guessing silently.
- **category** — the front/track this task belongs to (e.g. `EKW`,
  `SVC-PC`). Goes straight into `task.toml`'s `[metadata].category`.
- **subdomain** / **task_type** (optional, but ask) — finer-grained
  classification if the expert's tracker/intake sheet has it (e.g. sector +
  task-type columns). Leave blank if it doesn't apply; don't invent a value.

You do not need to ask about resource limits (agent/verifier timeouts,
container memory/storage) unless the expert flags something unusual (a huge
spreadsheet, a task that needs more than 4 hours of agent time) — Step 7
applies the same production defaults `cycle.py` uses for every other task,
and only needs overriding for genuine outliers.

### Step 2 — the prompt

Ask the expert to paste the prompt text, or point you at a file. This
becomes `instruction.md` verbatim (a later stage, not this skill, rewrites
its output paths for the strict platform format — see
`harbor-rewardkit-convert`). It must already tell the agent to write
deliverables under `/workspace/output/` — if it doesn't say that anywhere,
flag it now; don't assume assemble_task.py or anything downstream will fix
missing output-path guidance.

Sanity-check before moving on (ask, don't silently pass/fail):
- Does it name every deliverable file the agent must produce, with a
  filename and format (e.g. "produce `output/valuation_model.xlsx`")?
  You'll need this exact list in Step 4 and Step 5.
- Does it describe *what* to determine, not *how* (no formulas, method
  names, or column references that hand the agent the answer)? The deliverable's
  **schema block** (sheets / required columns / granularity — the output contract, see
  `docs/harbor-task-rubric.md`) is required and is not a method hint.
- Is it solvable only by using the source documents you're about to
  collect in Step 3 — not from general knowledge alone?

### Step 3 — source documents

Ask for a folder of source/input files (or "none" — some tasks ship with
only the shared corpus). For each file, or the folder as a whole, check:

- Is every file actually referenced by name or clear description in the
  prompt? A file nobody's prompt sends the agent to read is dead weight
  and should either be cut or the prompt updated to point to it.
- Any single `.docx` over ~1 MB? Flag it — DataOS's judge has a 1 MB
  attachment cutoff per file; large embedded images/fonts are the usual
  cause. Ask the expert to trim it now rather than after upload fails.
- Do the files cross-reference each other realistically (shared IDs,
  consistent dates/names/totals) rather than each being solvable in
  isolation? This isn't something you can verify by eye alone — ask the
  expert to confirm, since they know the intended solve path.

If everything checks out, note the folder path — it becomes `--source-dir`.
If there's no source-dir, that's fine; `assemble_task.py` still ships the
task with the shared full-corpus DVC pointer automatically (see script
docstring) as a safety net, so nothing else needs to happen here.

### Step 4 — expert (golden) solution

Ask whether they have their own completed solution to the task (strongly
recommended — Solution QC and reward-kit's grading baseline both depend on
it, but it's not a hard requirement here).

If yes, ask for the folder and check:
- **Every deliverable named in the prompt (Step 2) is present**, in the
  exact format named there (don't accept a `.csv` when the prompt asked
  for `.xlsx`, or a `.pdf` when it asked for `.docx`).
- **Only graded deliverables are in this folder** — not reasoning notes,
  scratch files, or a "how I solved this" writeup. Those belong in a
  separate location the expert keeps for themselves; if they hand you a
  mixed folder, ask them to split it rather than including everything.
- `.xlsm` files are fine here — downstream conversion (not this skill)
  strips macros and converts to `.xlsx` automatically when needed for
  reward-kit; internal-harbor keeps the file as-is.

If no golden solution exists yet, say so explicitly in your final report —
Solution QC is simply skipped downstream, this isn't a blocker.

### Step 5 — the grading rubric (verifier.json)

This is the highest-stakes input — a bad rubric produces a task that grades
wrong no matter how good the prompt and solution are. Figure out which shape
the expert has:

**(a) They already have a `verifier.json`.** Validate it yourself before
running anything:
- Valid JSON, parses cleanly.
- At least 6 criteria (`verifiers[]`); no fixed upper limit.
- Every `verifiers[].name` matches `^[a-zA-Z0-9_-]{1,64}$` and is unique —
  an oversized or duplicate name silently crashes the verifier at runtime
  much later, so catch it here.
- `metadata.weight` across all criteria sums to ~1.0 (±0.01).
- Every criterion has `metadata.how_justification` and
  `why_justification` filled in (not boilerplate/empty).
- At least one criterion is marked as checking a real outcome, not just
  structure/formatting (look at `metadata.importance` /
  `metadata.grading_role` if present, or ask the expert directly which
  criteria are "must-have to be correct" vs "nice-to-have polish").
- Every `source.file.arguments.path` referenced actually corresponds to a
  deliverable the prompt (Step 2) and solution (Step 4) agree on.
- **A `source.file` list (multiple files in one criterion) is fine for
  `to_rewardkit.py`'s reward-kit conversion — the primary DataOS path — but
  breaks this skill's own dataos-harbor output.** `to_rewardkit.py`'s
  judge.toml shares one `files=[...]` list across every criterion in a
  chunk, so a "the two deliverables must agree" criterion reading both files
  works natively there. But this skill's Step 9 (`to_dataos_harbor.py`)
  ships the *internal* harbor `test.sh`/`verifier_runtime.py` runtime
  verbatim, and that runtime's `Source` schema (`verifier_lib/models.py`)
  types `file` as a single object, never a list — a multi-file criterion
  makes the *entire* verifier.json fail schema validation there, zeroing
  every other criterion's score too, not just the offending one (confirmed
  live on a real Oracle run against a `to_dataos_harbor.py` package,
  2026-09-09). If this task is only ever going through `to_rewardkit.py`,
  leave a multi-file criterion as-is. If it's also meant to run via this
  skill's own dataos-harbor output or `harbor_evals.py`, split it into two
  single-file verifiers, or redesign it as a single-file check (e.g. require
  one deliverable to self-declare a tie-out to the other, as in
  `pipeline/data/sample_corpus/task_11`-style rubrics). Step 7
  (`assemble_task.py`) now warns (not errors) on this, precisely because it's
  only conditionally a problem.
- `config.models` names the judge model(s) you actually want — Step 7
  derives `task.toml`'s `[verifier.env]` credential variable directly from
  this list (`openai/...` → `OPENAI_API_KEY`, `anthropic/...` →
  `ANTHROPIC_API_KEY`), so a wrong or missing provider here means the wrong
  credentials get provisioned at grade time, not a cosmetic detail.

**(b) They have a rubric spreadsheet (xlsx), not JSON.** If the folder
matches the SVC-PC shape — exactly one "Grading Rubric" xlsx plus exactly
one golden-solution deliverable file, all under one folder — run the
existing converter instead of hand-transcribing:

```bash
python3 pipeline/tools/rubric_xlsx_to_verifier.py <task_dir> --out verifier.json
```

It raises `ConversionError` (not a silent guess) if the shape doesn't
match — e.g. more than one candidate rubric or deliverable file. If it
raises, don't try to force it; fall back to (c) instead.

**(c) They only have criteria in their head / a plain-language list.**
Interview them criterion by criterion and draft `verifier.json` yourself,
using `pipeline/data/sample_corpus/task_11/tests/verifier.json` as the
structural template (one `verifiers[]` entry per criterion: `name`,
`metadata.{how_justification, why_justification, importance, weight}`,
`source.file.{type, command: "extract_text", arguments.path}`,
`assertion.{type: "rubric", expected: true, rubric.prompt}`). For each
criterion, before locking it in, check with the expert:
- Does this test *one* thing, or is it secretly two criteria bundled
  together? Split it if the latter.
- Is every number/threshold/name it depends on written inline in the
  criterion text — never "as required by the prompt"? A grading model
  only ever sees this text plus the deliverable, not the prompt.
- Could someone pass this by keyword-stuffing the deliverable without
  actually solving the task? If so, tighten it.
- Does it assume another criterion already passed? Rubric criteria must
  be gradeable independently.

Once you have a draft, show the full `verifier.json` back to the expert
(or run [`gdpval-verifier-qc`](../gdpval-verifier-qc/SKILL.md) against it
if they want a second, structured opinion) before treating it as final —
don't silently ship your own first draft.

Regardless of path (a)/(b)/(c), confirm weights sum to 1.0 before moving
on; nudge the largest or vaguest criterion up/down to close small gaps
rather than distributing the remainder evenly across all of them.

### Step 6 — cross-check everything

Before running any script, walk the four pieces together one more time and
confirm out loud to the expert:
- Every deliverable filename in the prompt appears in the golden solution
  (if supplied) **and** in at least one rubric criterion's `source.file`.
- Every source document is named in the prompt.
- task_id and category are both settled.

If anything doesn't line up, go back to the relevant step — don't paper
over a mismatch by editing the script output later.

### Step 7 — assemble the internal-harbor task

```bash
python3 pipeline/tools/assemble_task.py \
  --task-id "<task_id>" \
  --prompt "<path to prompt file, or - to pipe stdin>" \
  --source-dir "<source docs folder>" \
  --solution-dir "<golden solution folder>" \
  --verifier "<verifier.json path>" \
  --out "<out dir, e.g. intake/<task_id>_harbor_intake>" \
  --category "<category>" \
  --subdomain "<subdomain, if any>" \
  --task-type "<task type, if any>"
```

Omit `--source-dir` / `--solution-dir` entirely if the expert has none —
don't pass an empty folder. The script:
- writes a **complete** `task.toml` ([verifier]/[agent]/[environment] with
  production defaults, not just `[metadata]`) and derives `[verifier.env]`
  from the rubric's own `config.models`;
- fails fast (`exit 2`, clear message) if `--verifier` isn't valid JSON, has
  no criteria, or has duplicate criterion names — don't hand-wave past this;
- copies in the full harbor grading runtime (`tests/test.sh` +
  `verifier_runtime.py` + `verifier_lib/`) so the task can actually be run,
  not just loaded;
- generates `solution/solve.sh` (the oracle solver) whenever a golden
  solution was supplied, by cross-referencing the verifier's own
  `output/<file>` paths against what's actually in the golden-outputs
  folder — this is also a second, independent check that your rubric's
  deliverable paths and the golden solution's filenames actually agree;

and prints a one-line summary (char counts, file counts, chosen judge env
var). Read it and confirm the counts match what you collected — a
`0 source file(s)` when the expert gave you five, or a `judge env` you
didn't expect, means something's wrong; don't treat the summary as a
formality.

If it exits non-zero, don't route around the error by hand-editing the
output tree — fix the underlying `--verifier` file and re-run.

### Step 8 — smoke-test the internal-harbor task for real

Structural correctness (Step 7 exiting 0) isn't the same as "this task
actually grades." Prove it, using the real oracle solver and the real
grading harness — only possible when a golden solution was supplied
(Step 4):

```bash
TASK="<out dir>/<task_id>"
WORKSPACE=$(mktemp -d)

# 1. Run the oracle solver — same thing an agent's output stands in for.
WORKSPACE_DIR="$WORKSPACE" SOLUTION_DIR="$TASK/solution" bash "$TASK/solution/solve.sh"
find "$WORKSPACE/output" -type f   # expect every deliverable named in the prompt

# 2. Run the real grading harness against that workspace.
VERIFIER_DIR=$(mktemp -d)
TESTS_DIR="$TASK/tests" VERIFIER_DIR="$VERIFIER_DIR" WORKSPACE_DIR="$WORKSPACE" \
  bash "$TASK/tests/test.sh"
cat "$VERIFIER_DIR/reward.json"    # expect a real score close to 1.0 — it's grading the golden solution
```

This actually installs the verifier's Python dependencies into a throwaway
venv and calls the judge model named in `config.models` for every rubric
criterion — it needs real network access and a valid credential for
whichever env var Step 7 reported (e.g. `OPENAI_API_KEY`). Tell the expert
this step costs a small amount of judge-model spend and takes a few
minutes; skip it only if neither is available, and say so explicitly in
your final report rather than silently skipping.

A near-1.0 score confirms the whole chain — rubric, deliverable paths,
runtime, credentials — actually works end to end. A low or partial score
here means the rubric doesn't actually match the golden solution; go back
to Step 5, don't ship it hoping a real agent will somehow score better than
the reference solution did.

If no golden solution exists (Step 4 was skipped), you can still confirm
the harness *starts* correctly — same command, but skip step 1 and instead
place whatever files you have under `$WORKSPACE/output/` by hand. Say
explicitly in your final report that this task has never been graded
end-to-end.

### Step 9 — convert to dataos-harbor

```bash
python3 pipeline/tools/to_dataos_harbor.py \
  "<out dir>/<task_id>" \
  "<out dir>/<task_id>_dataos_harbor"
```

This only patches `tests/` (renames `verifier_lib/` → `__verifier_lib/`,
`verifier_runtime.py` → `.pyrun`, swaps in the patched `test.sh`) — it
will refuse to run if `tests/verifier.json` is missing from the source,
which would mean Step 7 didn't actually complete.

### Step 10 — verify and report

Confirm both trees exist and look right:

```bash
find "<out dir>/<task_id>" -type f | sort
find "<out dir>/<task_id>_dataos_harbor" -type f | sort
```

Explicitly check `environment/Dockerfile` is present in **both** trees
(`ls "<out dir>/<task_id>_dataos_harbor/environment/"`) before telling the
expert to upload — a task missing it fails DataOS's own upload validator
with a blocking `Missing environment/Dockerfile` error (confirmed live,
2026-09-09). This should always be there since `assemble_task.py` copies it
in unconditionally (same as the DVC pointer); if it's ever missing, that's a
sign `assemble_task.py` itself regressed, not something to patch by hand
here — fix the script, don't hand-copy a Dockerfile into the output tree.

Report to the expert, in plain language:
- Where both folders live (a path they can actually open — never leave
  the only copy in a sandbox/scratch location they can't reach).
- What was included vs. skipped (e.g. "no golden solution was supplied,
  so Solution QC and the Step 8 grading smoke test were both skipped").
- The Step 8 smoke-test result — the actual reward score, or an explicit
  note that it wasn't run and why.
- Any warnings you raised along the way (oversized file, criterion you
  tightened, weight rebalance) and what you did about them.
- Next steps: this dataos-harbor folder is what gets uploaded to DataOS
  directly. If they instead need the strict reward-kit format (separate
  `task.toml` schema, `judge.toml`, `reward.toml` — used when DataOS
  *grades* the task rather than just accepting the upload), point them at
  [`harbor-rewardkit-convert`](../harbor-rewardkit-convert/SKILL.md) using
  the internal-harbor folder from Step 7 as its input.

## Canonical source — don't fork this logic

`pipeline/tools/assemble_task.py` and `pipeline/tools/to_dataos_harbor.py`
are the project's canonical converters; this skill is an interview layered
on top of them, not a reimplementation. `assemble_task.py` also owns
generating the full `task.toml`, installing the harbor runtime, and writing
`solution/solve.sh` — mirroring `cycle.py`'s own `_task_toml()` /
`_install_harbor_runtime()` / `_solve_sh()` — so this skill's output has the
same completeness as a task built through the full cycle pipeline. If the
four-piece shape or either script's CLI changes, update this file's Step
7/9 commands to match — don't let them drift.
