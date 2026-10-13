---
name: tp-fp-classification
description: >-
  Adjudicate flagged QC complaints against a task's own ground-truth
  artifacts and emit one strictly-schematized, consolidated issue-tracker
  .xlsx per task — the "External QC Feedback Classification Loop" /
  "TP/FP Skill". Accepts any combination of the three feedback sources the
  SOP produces: Internal QC's reviewer_queue.csv rows, DataOS's automated
  trajectory-verification (verifications_results.json + evals.zip), and
  Turing's manual human-review feedback (QCR_<name>_<date> results file).
  Same prompt, same output schema, for both SOP Phase 1 (Internal QC +
  DataOS automated) and Phase 2 (Turing manual) — whichever source(s)
  apply to this round. Use whenever a QC complaint needs a true_positive /
  false_positive / inconclusive verdict grounded in the task's actual
  files, not the complaint text alone. Verdict is tagged with a Defect
  Class (format/convention vs content/substance vs pipeline/packaging vs
  design-intent vs dataos-format-artifact vs agent-capability), a Fix
  Owner (task author vs pipeline engineer vs grading-model reliability —
  a confirmed true_positive is not automatically expert work; plenty turn
  out to be a verifier bug or a single grading run misapplying an
  already-correct rule), and split Scoring Impact / Authoring Effort
  ratings, so triage doesn't conflate "this zeroed real trials" with
  "this needs a rubric rewrite" — a one-line filename fix and a
  leaked-answer pipeline bug can carry the same severity and look
  identical otherwise. Screens out noise that's
  narrowly, verifiably about the harbor-to-DataOS submission-format
  conversion rather than the task — without waving off pipeline-traced
  defects (leaked inputs, malformed goldens) that happen to look similar
  but actually spoil the task; and writes fix guidance as a
  self-contained, jargon-explained mini-brief a non-ML expert can hand
  straight to an LLM to execute.
---

# External QC Feedback Classification Loop (the "TP/FP Skill")

This is the single canonical source of truth for the TP/FP classification
prompt referenced by `docs/QC_SOP.docx` Phase 1 Step I and Phase 2 §2.5. The
SOP links here rather than embedding the prompt text — that duplication is
exactly what caused stale copies to drift in the past (a full 3-phase-era
copy of the SOP itself was found sitting untouched in `docs/` after the
2-phase rewrite). Edit this file when the methodology changes; the SOP
should only ever need to reference it.

Paste this whole file as your first message in a fresh Claude Code session
to kick off a round of this workflow. It is self-contained — the new
session has no memory of prior conversations.

## What this is

Tasks in this QC pipeline accumulate complaints from up to three independent
sources, at different points in the SOP:

1. **`internal_qc`** — Internal QC's own engine (`cycle.py qc`), which
   writes one row per issue to `reviewer_queue.csv`. Columns and meaning
   (from `pipeline/gdpval_qc/v18_emitter.py`):
   - `sample_id` / `verdict` (`needs_review | reject_structural |
     reject_fixable | accept_with_fixes | accept`) / `one_line` /
     `review_reason` — sample-level summary, repeated on every issue row
     for that sample.
   - `issue_rank`, `classification` (`blocking | cosmetic`, empty for a
     no-issue sample), `dimension`, `severity`, `fixability`, `headline`,
     `action` (the synthesizer's suggested fix for blocking issues),
     `classification_reason` (why blocking vs. cosmetic).
   - `evidence_quote`, `detail` — already-extracted supporting text; treat
     as a lead to verify, not as settled fact.
   - `judges_agreed` (`Y`/`N` — flag `N` rows as lower-confidence),
     `judge_trace_path`, `data_quality_warnings` (set when the file judged
     was from degraded text — e.g. a failed docx→pdf conversion).
2. **`dataos_automated`** — Data-OS's (also written DataOS: the platform that runs the evaluation runs on a submitted task) automated external judge (GPT 5.6
   Sol), producing `task_<id>_verifications_results.json` (meta-QC checks
   on the task's own verifier/rubric: `task_clarity`, `test_accuracy`,
   `false_positive_risk`, `environment_adequacy`, `requirement_coverage`,
   `trajectory_integrity`, `test_failure_attribution`,
   `error_message_actionability`, each with `outcome` pass/fail/n-a +
   `explanation`) plus `task_<id>_evals.zip` (the agent trajectories,
   deliverables, and per-criterion `reward-details.json` that produced
   those checks).
3. **`turing_manual`** — Turing's QC team, returning a
   `QCR_<name>_<date>` results file after human review of the batch. This
   file's exact column layout is whatever Turing's reviewers actually
   ship — read it directly rather than assuming it mirrors either of the
   two schemas above; treat each row as one flagged issue with whatever
   comment/rationale field it carries.

**None of these three sources is reliable on its own.** `internal_qc` and
`dataos_automated` are both LLM-judge output — sometimes a real defect,
sometimes the judge misread the source docs. `turing_manual` is a human,
which is not the same as "always correct" — a reviewer can also
misunderstand a rubric or miss a source document. **Your job every round:
for each flagged issue, from whichever source(s) apply, go read the actual
task artifacts and settle whether the complaint is real.** Never take a
source's own explanation at face value — verify it against
`instruction.md`, `tests/verifier.json`, the source documents, the golden
solution, and the actual submitted deliverables.

## Which sources apply to which SOP phase

- **Phase 1** (Internal QC + External QC Automated, unified): both
  `internal_qc` and `dataos_automated` apply together, merged by
  `cycle.py joint-feedback` into `cycles/<date>/joint_feedback/task_<id>_packet.json`
  — one adjudication round per task, not one round per source.
- **Phase 2** (External QC Manual): `turing_manual` applies. If any
  `internal_qc` or `dataos_automated` issues on this task are still open
  (rare — Phase 1 only advances tasks with zero confirmed
  `true_positive` rows), re-attach them too so this round's sheet is the
  complete picture, not just the newest complaint.

A round may legitimately have just one source (a Phase-2-only round with
no open Phase-1 issues) or more than one — the methodology and output
below are identical either way.

## Inputs you'll be given

Per task, whichever of these apply to this round:
- `internal_qc`: the task's row(s) in `reviewer_queue.csv` (or the joint
  packet's `internal_qc_issues` field, copied verbatim from it — the
  packet is a convenience index, not a substitute for the raw file).
- `dataos_automated`: `task_<id>_verifications_results.json` (also
  indexed into the packet's `external_qc_automated_flags`, but check the
  raw file too — the packet only extracts FAILED checks, not every
  field) plus `task_<id>_evals.zip`, unzipped. It contains subfolders per
  trial (`claude-code_...`, `codex_...`, sometimes `oracle_...`; the first
  two are real solver trials, `oracle_...` is the oracle run, which submits
  the reference answer), each with:
  - `artifacts/app/` — the actual deliverable files that trial produced
  - `verifier/reward-details.json` — per-criterion judge verdict +
    reasoning for that trial (richer ground truth than the
    verifications_results.json summary — read this directly)
  - `verifier/runtime.log`, `verifier/reward.json` — raw judge call logs
    (check for infra failures, e.g. Anthropic "compiled grammar is too
    large" 400 errors — a known recurring failure mode that zeroes
    reward regardless of quality; confirm by checking if the **oracle**
    run also got 0.0, which proves it's infra not content)
  - `agent/trajectory.json` or `agent/*.txt` — the agent's own work log
- `turing_manual`: the `QCR_<name>_<date>` results file itself.
- **Always required**: the task's ground-truth materials from the harbor
  bundle —
  ```
  cycles/<batch>/02_bundle/task_<id>/
    instruction.md              # the task prompt
    tests/verifier.json         # the rubric — "verifiers" list, each with rubric.prompt + metadata.weight/importance/grading_role
    environment/data/           # source documents given to the agent
    solution/golden_outputs/    # expert reference solution
  ```
  If a task isn't in that bundle yet, bundle it first via `pipeline/cycle.py bundle` — see `docs/QC_SOP.docx` and `docs/CLAUDE.md`, or ask the user where this batch's source materials are.

## Format-artifact gate — screen these out before deep verification

Our ship format is the harbor bundle (the task folder layout shown above) `cycle.py`'s step 2 produces
(`instruction.md` / `environment/data/` / `solution/golden_outputs/` /
`tests/verifier.json`). Submitting to DataOS requires a second, lossy
conversion (`pipeline/tools/to_rewardkit.py`) that reshapes this into
reward-kit's schema — splitting large rubrics across multiple
`judge.toml` files, renormalizing weights, dropping fields DataOS doesn't
recognize. Some automated-judge complaints are really about artifacts of
that *second* conversion, not about the task as an expert authored it —
fixing those means changing the conversion script (or just ignoring the
noise), never the task's own prompt/rubric/environment. Check every
flagged complaint against these two confirmed patterns before running the
Methodology below on it:

1. **"Weights in this criterion group don't sum to 1 (or 100)" / missing
   or mis-set cross-chunk `[judge].weight`.** Once a rubric has more than
   `max_criteria_per_judge` criteria (12 by default), `to_rewardkit.py`
   splits it across `tests/deliverables_NN/judge.toml` files — a
   chunking scheme that exists solely to satisfy DataOS's per-judge
   criteria-count limit and has no counterpart in the task's own
   originally-authored rubric (the source rubric never had "chunks" —
   that concept is introduced entirely by this conversion step). By
   design, each chunk's own weights only need to sum to that chunk's own
   share, not to 1.0 in isolation (`pipeline/tools/to_rewardkit.py:17-29`);
   cross-chunk balance is supposed to be handled via `[judge].weight` on
   each chunk, which `reward.toml`'s `weighted_mean` uses to recombine
   them. **Always tag `dataos_format_artifact`/`false_positive` here,
   whether or not `[judge].weight` is actually present or correctly set
   on every chunk.** This is purely a side effect of the conversion's own
   chunking mechanism — never a defect in the task's own authored
   rubric, prompt, or environment — so it must never be classified
   `true_positive` (with either `content_substance` or
   `pipeline_packaging`), and never routed to a task author *or* held
   open as a pipeline-engineer action item on this task's own record.
   Still cite the actual `[judge].weight` values you found for the audit
   trail (`Evidence Excerpt`/`Evidence Reference`), but the verdict stays
   `false_positive`/`dataos_format_artifact`, `Scoring Impact: None`,
   `Authoring Effort: N/A` regardless of what those values are. (If this
   pattern recurs often enough to be worth fixing at the source, that is
   a standing improvement to `to_rewardkit.py` itself, tracked separately
   from any single task's adjudication — it is not this task's finding to
   carry.)
2. **"Input file not found" / `environment_adequacy: fail`** on an SVC
   task (SVC and EKW are the two task kinds). Many SVC prompts point at a shared corpus (finance/ops/etc. via
   named connectors like quickbooks/shopify/GDrive) rather than naming
   every file directly, and a real trial sometimes fails to find a file
   it actually had, then blames the environment in its own trajectory —
   which the automated judge then repeats uncritically. **Verify against
   this specific task's actually-shipped `environment/data/` (or the
   packaged `initial_workspace/`) — not the master corpus on disk, which
   is a different thing and proves nothing about what this task shipped.**
   Also check the failing trial's `agent/trajectory.json` for whether it
   searched thoroughly (multiple terms/locations) before concluding a
   file was missing. If the file is genuinely present in what was shipped
   to that trial and the trajectory shows it gave up early or barely
   looked, tag `agent_capability` — not a task defect. If the file
   genuinely is absent from the packaged environment, that's real: trace
   whether it should have been hydrated in (Methodology step 6) and
   classify accordingly — don't default to disregarding every "file not
   found" complaint just because this pattern exists.
   - **DVC-pointer environments specifically**: if this task's
     `environment/initial_workspace/` in the bundle you're reviewing is
     only a `data.dvc` pointer file (not the hydrated tree — check before
     concluding anything), you are not looking at the real environment a
     trial actually runs against. The task's own `Dockerfile` resolves
     that pointer into the real, much larger shared corpus via `dvc pull`
     at container-build time — a named file absent from the *unhydrated
     pointer bundle* proves nothing, since named files in these prompts
     routinely live inside that larger corpus, not the static snapshot
     you can see. **Default this specific shape of complaint —
     `environment/initial_workspace` ships as an unhydrated `data.dvc`
     pointer, and the named file cannot be located in what you can
     actually inspect — to `false_positive`/`dataos_format_artifact`,
     not `true_positive`, and not `inconclusive`.** Only escalate to
     `true_positive` when you have positive evidence the file is absent
     even from the *hydrated* environment specifically — e.g. a real
     trial's own `agent/trajectory.json` shows it actually running inside
     the built container, searching thoroughly, and still not finding the
     file (this is different from checking an older, separately-built
     snapshot of the same task, which is its own unhydrated/differently-
     packaged bundle and proves nothing about this task's real corpus
     either).
   - **"Prompt names one file as the only permitted input, but the
     shipped environment is a full multi-department company corpus" — this
     is the expected SVC-PC shape, not a defect.** A prompt sentence like
     "do not use any other materials: `<one named file>`" paired with an
     actually-shipped environment structured as a browsable corpus (e.g. a
     `Company Shared Drive/` tree with `Finance/`, `HR/`, `Legal/`,
     `Marketing/`, `Operations/`, `Vendors/` subfolders, or similar) is not
     a contradiction to flag — the named file is a starting/reference
     point, and the wider corpus being genuinely present and searchable is
     the intended, by-design environment for these tasks. Default to
     `false_positive` for both of this shape's common framings: (a) "two
     readings disagree on whether the wider corpus is in play or
     off-limits" (ambiguity) and (b) "the only permitted input path
     doesn't exist, so solvers must work outside the only source the
     prompt permits" (misalignment) — these are two descriptions of the
     same non-issue, not two separate defects. Only escalate to
     `true_positive` if the environment genuinely ships nothing usable at
     all (not merely "more than the one named file") — e.g. an empty or
     near-empty environment, or a corpus that doesn't contain the
     information the task actually requires. **This also covers the
     narrower "files are nested under a subdirectory, not flat at `/app/`
     as the prompt states" friction** — a real trial having to `find`/`cd`
     one level deeper than the prompt's literal wording promises, inside
     an environment that is otherwise genuinely searchable and does
     contain the named files, is the same small-scale version of this
     non-issue, not a separate content defect worth a `task_author` row —
     default to `false_positive` here too, even when a real trial's own
     trajectory shows it had to search before finding the file.
3. **"Must-pass gate carries no more weight than any other criterion" /
   "criteria called must-pass gates do not gate anything."** Every SVC
   criterion whose source rubric marks it a must-pass gate gets converted
   to an ordinary weighted `[[criterion]]` with a bracketed disclosure in
   its own description text — literally: `[must-pass gate in the source
   rubric: SVC scoring zeroes the whole reward on failure; reward-kit's
   weighted_mean has no native gate concept, so this is approximated here
   as a heavily-weighted criterion only]`. This is not a task-authoring
   gap — the task's own rubric correctly marks these criteria must-pass;
   `reward-kit`/DataOS's aggregation format has no hard-gate primitive at
   all, on any task, so there is no per-task fix available in this task's
   own `judge.toml` or `instruction.md` that would change this. **Always
   tag `dataos_format_artifact`/`false_positive` here, regardless of how
   large the scoring gap looks** (e.g. "failing every gate still scores
   ~0.7-0.85") — same treatment as pattern 1's chunk-weight gap, for the
   same reason: this is DataOS/reward-kit's own aggregation-rule
   limitation, with zero task-authored counterpart, so it is never
   `true_positive`, never routed to a task author, and never held open as
   a per-task pipeline-engineer action item on this task's own record.
   (If reward-kit ever gains a real gate primitive, migrating every
   converted task to use it is a standing improvement to
   `pipeline/tools/to_rewardkit.py`, tracked separately from any single
   task's adjudication.)
4. **"The graded deliverable is one exact filename `instruction.md` never
   states" / "prompt names no filename, format, or path" — including when
   real trials scored 0 for file-not-found.** Confirmed real, recurring
   noise: this is categorically `false_positive`/`dataos_format_artifact`,
   never `true_positive`, regardless of the answer to any of the questions
   that used to gate this call — whether `instruction.md` states the
   filename inline, whether it carries the `to_rewardkit.py` auto-append
   boilerplate, whether sibling tasks in the same batch happen to have
   that boilerplate and this one doesn't, or whether real trials in the
   reviewed eval bundle actually scored 0 with "file not found" in
   `reward-details.json`. None of those distinctions changes the verdict.
   Do not classify this `pipeline_packaging`/`pipeline_engineer` either —
   it is not a per-task pipeline defect to route anywhere; it is expected,
   accepted noise from the harbor→DataOS conversion, the same category
   `docs/svc/KNOWN_CALIBRATIONS.md`'s `solution_format_match` entry
   already established for the sibling "golden saved under a different
   build-convention name" shape of this same underlying non-issue.

**This gate is narrow, and a pipeline/packaging root cause is not, by
itself, a reason to disregard anything.** The four patterns above are
the only ones pre-cleared by this gate — patterns 1, 3, and 4
categorically (none of these mechanisms has any task-authored
counterpart, regardless of the instance-level weight values, DVC-
hydration state, or observed scoring impact), pattern 2 only after you
verify the specific trial's trajectory (or the hydrated
environment) each time. **If the root cause is pipeline-related, the
Auto-Verdict is `false_positive`** — that is now the default reading for
any complaint traced to a build/hydration/conversion/scoring-mechanics
tool, not the exception. The one thing that does NOT get waved off this
way: a pipeline-run tool that corrupts the task's own shipped *content*
(not just its conversion/scoring mechanics) badly enough to spoil
real-trial validity. The cautionary example from this project: a task's
downstream sub-task golden-answer files ended up copied into its own
environment by a hydration script with no exclusion filter for them. The
instinct to wave that off as a "format/packaging artifact" was wrong —
the leaked files let real trials pass the actual rubric by lookup instead
of analysis; the environment and the verifiers run against it were both
real, and both were spoiled. That stays `true_positive`/
`content_substance` (the task's *environment* is now genuinely broken —
tag it by what's broken, not by which tool broke it) — never
`pipeline_packaging`, which is reserved for cases where the task's own
authored content is untouched and only the conversion/scoring mechanics
around it are broken. The fix there was as simple as removing the leaked
files from that task's shipped input (a separate, optional question is
whether the hydration script also needs patching so it doesn't recur on
other tasks). **Before keeping anything `true_positive` on a
pipeline-traced complaint, you must be able to point to the specific
task content that is actually corrupted, not merely a conversion/
scoring-mechanics tool that behaved imperfectly** — patterns 1-4 above
plus this section's default now cover the ordinary case.

Rows resolved by this gate (`dataos_format_artifact` or
`agent_capability`) still get recorded — same audit-trail convention as
any other `false_positive` — with `Scoring Impact: None`,
`Authoring Effort: N/A`, and Actionable Fix Guidance limited to naming
which pattern applied and why. They are never escalated to experts as
work to do.

## Methodology (per flagged issue)

The job here is to adjudicate what was flagged, not to go looking for
new issues nobody raised — every row in the output traces back to a
complaint from `internal_qc`, `dataos_automated`, or `turing_manual`.
That said, some complaint shapes are easy to reflexively wave off as
"just a format/packaging thing" when they're actually a real,
task-spoiling defect — oracle runs that don't score cleanly, a golden
solution that's malformed or doesn't match what the verifier expects, an
environment file that leaks the answer — treat any complaint along these
lines with extra scrutiny before defaulting to a disregard-class verdict;
see the Format-artifact gate's cautionary example above.

1. Identify the distinct underlying claim in each flagged issue — two
   sources (or two trials within `dataos_automated`) often flag the same
   problem from different angles — dedupe to one row per real issue, not
   one row per raw check/comment field. If two-plus sources co-flag the
   same issue, list all of them in the row's `Source` value (see below)
   rather than picking one arbitrarily. Screen every issue against the
   Format-artifact gate above before spending time on steps 2-5 below —
   if it matches a named pattern there, resolve it there and move on.
2. Read the exact rubric text (`tests/verifier.json`, quote the
   `rubric.prompt` for the relevant criterion) and the exact prompt
   language (`instruction.md`) — most disputes hinge on precise wording.
   **Before concluding "the judge has nothing to check the submission
   against," check whether the criterion's own description already embeds
   the reference — an `Expected: <value>` clause written directly into
   `judge.toml`'s criterion text functions as the reference for that
   objective check, even when `[judge].files` lists only the agent's own
   submission path.** Not handing the judge the full golden file
   separately is often intentional (it would leak unrelated golden
   content/figures the criterion isn't checking), not a gap — don't
   conflate "no separate reference *file*" with "no reference at all."
3. Check the actual source documents and golden solution directly — many
   "the rubric requires something not in the prompt" complaints turn out
   to be grounded once you check whether the *golden solution*
   independently does the same thing, or whether a source document
   supports it. **When the golden (or a sibling criterion) already
   demonstrates the missing convention, default to treating this as a
   disclosure gap, not an open design question** — e.g. if the golden
   workbook is heavily formula-driven but `instruction.md` never says
   formulas are required, the fix is "write down the convention the
   golden already follows" (Fix Owner `task_author`, Authoring Effort
   `Trivial`), not "ask the task author to decide whether formulas
   should be required." Only escalate it as a genuine open decision (see
   Fix Owner below) when the golden's own choice looks discretionary
   rather than intentional — i.e. nothing forces that specific choice and
   a differently-reasoned answer would be equally defensible (this is the
   same signal that drives a `design_intent` tag on step 6).
   - **Distinguish "undisclosed convention" from "the criterion is testing
     whether the agent reasons its way to the right method."** Not every
     "the prompt never says to use method X" complaint is a disclosure
     gap — some professional-judgment tasks are deliberately open-ended on
     *how* to solve the underlying problem precisely because choosing and
     justifying the right method (not just producing a plausible-looking
     number) is the expertise being graded. If the criterion is checking
     that the agent arrived at (and can defend) the technically correct
     approach to a genuine analytical question — not an arbitrary
     convention the golden happens to follow — that is fair grading of
     professional judgment, not a prompt/rubric misalignment, even when a
     differently-reasoned, less-rigorous method could produce a
     similar-looking number. This is a genuine expert call, not a bright
     line — when uncertain whether a specific method requirement is
     "testing judgment" versus "an arbitrary undisclosed convention",
     default to `inconclusive` rather than forcing a verdict either way,
     and say so explicitly in the reasoning.
4. Check the actual submitted deliverable/workbook when the complaint is
   about what a run's submission does or doesn't contain — don't trust a
   source's paraphrase, open the file (docx/xlsx/pdf skills, or python
   openpyxl/python-docx/pdfplumber).
5. For xlsx claims about "blank"/"NaN" cells: check both
   `data_only=True` and `data_only=False` — a workbook saved without
   recalculation will show `None` under `data_only=True` even when
   formulas are correct; this is a known verifier-extraction gap, not
   necessarily a content defect.
6. **Classify what kind of defect this is before deciding severity or fix
   guidance — don't let "how badly did this hurt scoring" stand in for
   "where does the fix actually belong":**
   - Apply the litmus test: if you changed *only* a filename/path/wording
     string, leaving all substantive content untouched, does the
     complaint fully resolve? If yes, this is a **format/convention**
     issue no matter how severely it scored — the fix is cosmetic and
     says nothing about rubric/environment quality.
   - If the complaint is about content the source documents, rubric, or
     golden solution are missing/wrong/self-contradictory as authored,
     and no renaming fixes it, this is **content/substance**.
   - **For any complaint about a file's presence, absence, or content
     inside `environment/`** — an input "leaks" the answer, is missing,
     or sits at the wrong path — trace the actual mechanism before
     finalizing verdict or fix guidance. Check whether the pattern
     already exists in the pre-conversion source materials (the original
     QC request zip, the expert's raw deliverable) or only appears after
     a specific harbor-pipeline tool ran (e.g. `hydrate_environment.py`,
     `assemble_task.py`, `to_rewardkit.py`, or the batch's equivalent).
     Read that tool's actual logic — grep for the relevant hydration/
     conversion log if one exists — rather than inferring cause from the
     packaged output alone. A complaint that looks like "the task author
     leaked the answer" is often really "a hydration/assembly script has
     no exclusion filter for X," which is a **pipeline/packaging** defect
     with a completely different fix location (patch the script) than
     the same-looking symptom caused by an author's own mistake.
   - Use the oracle-vs-real-trial score split as a cheap first signal: if
     the oracle passes cleanly and a real trial fails purely on a
     path/filename/wording mismatch with otherwise-correct substance,
     that's evidence for `format_convention`. If the oracle *itself*
     cannot cleanly pass without relying on something not shipped to real
     agents, that's `content_substance` almost by definition — even the
     reference answer can't be honestly earned from what's shipped.
   - If the flagged pattern is a deliberate adversarial/trap element
     (injected decoy controls, mislabeled distractor source docs), confirm
     by checking the golden solution's own internal documentation/tabs
     and by checking whether an oracle run resolves it cleanly — tag this
     **design_intent** rather than leaving it looking like a plain
     non-issue, since a reader skimming Auto-Verdict alone can't tell
     "never a real complaint" apart from "intentionally adversarial, and
     depends on a fix elsewhere" (see Practical notes on dependencies
     between rows).
   - **A `true_positive` verdict does not automatically mean the task
     author has work to do — decide Fix Owner separately from Defect
     Class, right now, before writing guidance:**
     - `task_author`: the fix is an edit to `instruction.md`, the
       rubric's own criterion text, a source document, or the golden
       solution. Write the Actionable Fix Guidance for this task's own
       domain expert (see the guidance rules below).
     - `pipeline_engineer`: the fix belongs in a build/hydration/
       conversion/verifier-extraction tool, not this task's own files.
       **If the root cause is pipeline-related, the Auto-Verdict is
       `false_positive`** — this Fix Owner value now essentially only
       shows up on `false_positive`/`dataos_format_artifact` rows recorded
       for audit-trail purposes (see the Format-artifact gate). If a
       pipeline-run tool corrupted the task's own shipped content badly
       enough to spoil real-trial validity (e.g. leaked an answer key into
       the environment), that's `content_substance`/`task_author` instead
       — the environment itself is broken, which is a different thing
       from the conversion/scoring mechanics being broken.
     - **Concrete named check — missing "Save your deliverable(s)..."
       filename boilerplate: `false_positive`/`dataos_format_artifact`,
       full stop — see Format-artifact gate pattern 4.** (An earlier
       version of this skill classified this `true_positive`/
       `pipeline_engineer`/`Blocking` when real trials scored 0 on
       "file not found" — corrected: real scoring impact in a reviewed
       eval bundle does not, by itself, make this a task- or even
       pipeline-owned finding, the same lesson already established for
       patterns 1 and 3. Don't re-introduce that framing.)
     - `grading_reliability`: **new category — check for this before
       concluding the criterion text itself is wrong.** Some flagged
       complaints turn out to be a specific grading run misapplying a
       criterion that is *already correct as written* — the judge's own
       recorded reasoning identifies the exact fact the criterion asks
       for, then scores the opposite (e.g. "the workbook has zero
       formula cells" recorded as reasoning, immediately followed by a
       PASS on a criterion that says "FAIL if no material formula
       linkage"); or two sibling criteria checking the identical fact on
       the identical submission return contradictory verdicts in the
       same run; or the recorded reasoning describes text that does not
       actually appear anywhere in the submission. **The test:** if you
       rewrote the criterion text, would it change anything? If the
       criterion is already unambiguous and a compliant answer would
       pass it, this is a grading-engine reliability issue, not a task
       defect — there is no content for the task author to change. Keep
       `Auto-Verdict: true_positive` (the flagged run genuinely scored
       wrong) but set `Fix Owner: grading_reliability`, `Authoring
       Effort: N/A`, and write the Actionable Fix Guidance as a note for
       whoever maintains the grading model/harness, not the task author
       — do not put rubric-jargon "fixes" in front of a domain expert for
       something they have no content lever to pull on.
7. Decide: is the complaint **true_positive** (real defect — confirmed by
   direct evidence), **false_positive** (complaint is wrong — rubric/task
   is actually fine, confirmed by direct evidence), or **inconclusive**
   (genuinely a judgment call / not resolvable from available materials,
   e.g. a subjective config choice like a verifier timeout value). Assign
   the Defect Class from step 6 alongside it.

## Output: one consolidated spreadsheet per task

For each task, produce a standalone `.xlsx` (one sheet, "QC Issues") with
one row per distinct issue and these exact columns:

**Task ID · Source · Issue Description · Auto-Verdict · Defect Class · Fix Owner · Verdict Reasoning · Evidence Excerpt · Evidence Reference (path) · Scoring Impact · Authoring Effort · Fix Title · Actionable Fix Guidance · Expert Verdict (fill in) · Expert Proposed Fix (fill in) · Last Run**

Column conventions:
- **Source**: `internal_qc` | `dataos_automated` | `turing_manual`, or a
  `+`-joined combination (e.g. `internal_qc+dataos_automated`) when
  multiple sources independently flagged the same underlying issue
  (dedupe per Methodology step 1 — one row, not one per source). Every
  row traces back to at least one of these three — this workflow
  adjudicates flagged complaints, it doesn't originate new ones.
- **Auto-Verdict**: `true_positive` | `false_positive` | `inconclusive`
  (lowercase, underscore).
- **Defect Class**: `format_convention` | `content_substance` |
  `pipeline_packaging` | `design_intent` | `dataos_format_artifact` |
  `agent_capability` (lowercase, underscore — assign per Methodology step
  6 and the Format-artifact gate). Orthogonal to Auto-Verdict, not a
  restatement of it — e.g. a `false_positive` can be `design_intent` (a
  confirmed deliberate trap) rather than a plain non-issue. Definitions:
  - `format_convention`: path/filename/wording mismatch between prompt
    and verifier; fixing the string alone (no content change) resolves
    it. Trivially fixable, no reflection on rubric/environment quality.
  - `content_substance`: the source documents, rubric, or golden are
    actually wrong/missing/contradictory as authored. No renaming fixes
    it.
  - `pipeline_packaging`: a build/hydration/assembly/scoring-mechanics
    tool in the conversion chain is broken — the task's own authored files
    (prompt, rubric, environment as an expert built it) are fine. **Pairs
    with `false_positive`, not `true_positive`** — confirmed repeatedly
    this round (chunk-weight normalization, must-pass-gate-as-weight
    approximation, missing deliverable-filename boilerplate, DVC-unhydrated
    missing-file claims, corpus-vs-single-file scope, nested-vs-flat path
    friction all resolved this way, regardless of real scoring impact
    observed in a reviewed eval bundle). **If a pipeline-run tool actually
    corrupts the task's own shipped content** in a way that spoils
    real-trial validity — the cautionary example that used to justify a
    `pipeline_packaging`/`true_positive` pairing: a hydration script
    copying a downstream sub-task's answer key into this task's own
    environment — that is a `content_substance` defect (the task's
    *environment*, not just its conversion, is now genuinely broken), not
    `pipeline_packaging`. Note the pipeline mechanism that caused it in
    the reasoning/evidence for context, but the Defect Class and
    Auto-Verdict follow from what's actually broken (the shipped
    environment), not from which tool broke it.
  - `design_intent`: a confirmed deliberate adversarial/trap element
    (injected decoy controls, mislabeled distractor docs) — verify
    against the golden's own internal documentation, not just plausibility.
  - `dataos_format_artifact`: the complaint exists only because of the
    harbor→DataOS format conversion itself, verified to have zero effect
    on real trial scoring (see Format-artifact gate — only the two named,
    pre-verified patterns there qualify). Always pairs with
    `false_positive`.
  - `agent_capability`: the complaint is really about what a specific
    agent run did or didn't do (didn't search hard enough, gave up early)
    rather than any property of the task. Always pairs with
    `false_positive`.
  Leave blank only when Auto-Verdict is `false_positive` *and* the
  complaint was simply wrong with no interesting reason beyond that (i.e.
  none of the above apply).
- **Fix Owner**: `task_author` | `pipeline_engineer` | `grading_reliability`
  | blank (`false_positive` rows with no interesting mechanism). Assign
  per Methodology step 6. This is the single most important field for
  routing — it determines whether this row should ever reach a task's
  domain expert at all:
  - `task_author`: a real content edit belongs in `instruction.md`, the
    rubric's own criterion text, a source document, or the golden
    solution. These are the only rows that should be handed to the
    task's own subject-matter expert.
  - `pipeline_engineer`: the fix is in a build/hydration/conversion/
    verifier-extraction tool. Route to whoever maintains that tool, not
    the task author — they have no lever to pull on a broken script.
    A missing "Save your deliverable(s)..." filename sentence is NOT this
    category — it's `false_positive`/`dataos_format_artifact` per
    Format-artifact gate pattern 4, not a per-task pipeline finding.
  - `grading_reliability`: the criterion text is already correct; a
    specific grading run misapplied it (self-contradicted its own
    recorded reasoning, gave opposite verdicts to two sibling criteria
    checking the same fact, or hallucinated reasoning describing content
    absent from the submission). Route to whoever owns the grading
    model/harness. **Never surface a `grading_reliability` row to a
    domain expert as something for them to fix — there is no content
    change that would prevent it, since the content was already right.**
    A task whose *only* `true_positive` rows are `grading_reliability`
    has nothing for its author to review at all (see "Approved"
    definition in Practical notes).
- **Evidence Excerpt**: a short, concrete quote/figure from the actual
  materials (rubric text, source doc line, submitted file content) — not
  a paraphrase.
- **Evidence Reference (path)**: the specific file(s) you actually
  checked, e.g. `task_298/tests/verifier.json (v17)` or
  `task_284/environment/data/03_benchmark_and_market_data.pdf (p.2)` —
  always cite real paths, never generic placeholders. For
  `pipeline_packaging` rows, also cite the tool/script and line (e.g.
  `pipeline/tools/hydrate_environment.py:187-191`), not just the affected
  task file — the reader needs to know which layer to patch.
- **Scoring Impact**: how badly this hurts real trials *today*,
  independent of how hard the fix is — `Blocking` (zeroes or
  near-zeroes real trial reward), `Major` (significant partial-credit
  loss), `Minor` (small point loss or judge-confidence issue only),
  `None` (`false_positive` / no measurable impact).
- **Authoring Effort**: what it actually takes to fix, independent of
  urgency — `Trivial` (one line in `instruction.md` or a `judge.toml`
  criterion, e.g. state a filename), `Moderate` (rewrite a handful of
  rubric criteria, add a missing source file), `Major` (rebuild the
  golden solution, environment, or rubric from scratch), `Pipeline-Fix`
  (Fix Owner `pipeline_engineer` — the fix belongs in a build/hydration/
  assembly script, not in this task's own files — name the exact tool in
  Actionable Fix Guidance), `N/A` (`false_positive`, or Fix Owner
  `grading_reliability` — there is no task-side authoring effort because
  nothing in the task's own files needs to change). A row can
  legitimately be `Scoring Impact: Blocking` + `Authoring Effort:
  Trivial` (a missing filename that zeroed both real trials) — that
  combination is exactly the signal this split exists to surface,
  distinct from `Blocking` + `Major` (the task itself needs rebuilding)
  or `Blocking` + `Pipeline-Fix` (a script leaked the answer; the task's
  own files are fine).
- **Fix Title**: a short (3–8 word) specific title, e.g. "Tighten FAIL
  condition to match PASS target".
- **Actionable Fix Guidance**: for `Fix Owner: task_author` rows, written
  for that task's own domain expert (a finance analyst, an apparel
  merchandiser, a clinician — whoever actually wrote this task), who does
  **not** know rubric-as-code or LLM/RL terminology, and who will likely
  paste this cell alone into an LLM to actually make the change — so it
  must be self-contained. **Before finalizing the row, reread every
  sentence and ask: would this task's own domain expert, who has never
  opened a `judge.toml` file, understand it without translation?** Banned
  words for these rows: `criterion`, `judge.toml`, `PASS`/`FAIL` (as
  literal terms), `files=[]`, `rubric` (say "the grading rules" or name
  the actual requirement instead). Say what's wrong and what to change in
  the task's own subject-matter vocabulary — e.g. "the check for
  store-eligibility is missing" instead of "add a criterion checking
  StoreEligibility against the Style Master's files list." For `Fix
  Owner: pipeline_engineer` or `grading_reliability` rows, write for that
  audience instead — file paths, tool names, and rubric-as-code
  references are appropriate there since a domain expert will never see
  these rows in the first place (see Practical notes on splitting
  output by Fix Owner). Every `true_positive`/`inconclusive` row with
  `Fix Owner: task_author` follows this shape (skip straight to "no fix
  needed + why" for `false_positive`, `dataos_format_artifact`, and
  `agent_capability` rows, and for `grading_reliability`/
  `pipeline_engineer` rows write a short technical note instead of the
  5-part structure below, which is expert-audience-specific):
  1. **What's wrong** — one plain-language sentence, no jargon.
  2. **Why it matters for grading** — one or two sentences connecting the
     defect to what actually happens when a real agent run is scored. If
     a technical term is unavoidable (must-pass gate, judge model,
     reward, weighted_mean, sandbox, hydration, oracle run), define it in
     a short parenthetical the first time it appears in *this row* — do
     not assume the reader already knows it or will look it up elsewhere.
  3. **Exactly what to change** — the exact file, field, or cell, quoted
     verbatim, never paraphrased.
  4. **A concrete example of the fix** — actual replacement text/value,
     phrased as "for example: '...' — or an equivalent in your own words
     that keeps the same meaning." Never leave the reader to invent the
     shape of the fix from an abstract instruction alone.
  5. **How to confirm it worked** — one sentence naming an observable
     check (e.g. "re-run the two failing trials — `reward-details.json`
     should no longer say 'File not found' for these criteria").
  Direct and concrete, no hedging, no buzzwords — but not so terse it
  can't be acted on without context this row doesn't provide. Worked
  example (a real one from this pipeline):
  > *Bad (too vague):* "Add the filename to the prompt."
  > *Bad (unexplained jargon):* "The judge's grammar-size ceiling forced a
  > chunked deliverables split, so the gate's weighted_mean approximation
  > disproportionately inflates the reward."
  > *Good:* "The prompt never states where or under what filename to save
  > the three deliverables, but the grading script (the part that reads
  > the agent's submitted files and checks them against the answer key)
  > only looks for one exact file:
  > `/app/L2-01_Golden_Response_Locked_FY2021_Close_LOCAL_UPDATED_Workbook.xlsx`.
  > Since that filename never appears anywhere in the prompt, an agent has
  > no way to guess it — both real trials wrote correct content to
  > differently-named files and scored 0 on all 59 criteria as a result.
  > Fix: add one sentence to `instruction.md`, for example: 'Save all
  > three deliverables as tabs in a single Excel workbook at
  > `/app/L2-01_Golden_Response_Locked_FY2021_Close_LOCAL_UPDATED_Workbook.xlsx`.'
  > (Any wording that states that exact path works — the filename just
  > has to appear in the prompt.) To confirm: re-run a trial and check
  > that `reward-details.json` no longer reports 'File not found' for any
  > criterion."
  For `design_intent` rows, also state explicitly if the verdict is
  contingent on another row's fix (see Practical notes).
- **Expert Verdict (fill in)** / **Expert Proposed Fix (fill in)**: leave
  blank — a human fills these in later.
- **Last Run**: today's date, ISO format (`YYYY-MM-DD`).

If this task already has an `<task_id>_qc_validation.xlsx` from an earlier
round (e.g. a Phase 2 `turing_manual` round arriving after Phase 1 already
produced one), **append** this round's rows to the same sheet rather than
starting a new file — one consolidated, running sheet per task across its
whole QC lifecycle, not one file per round. Re-upload the combined file
under the same name.

Style bar: dense, evidence-first, no hedging without a stated reason.
Every claim should be traceable to a file you actually opened this
session — quote it. False positives are recorded too (`Auto-Verdict =
false_positive`) but don't get a fix-guidance row beyond "no fix needed" —
they're kept for audit/drift tracking, not sent to experts. This includes
`dataos_format_artifact` and `agent_capability` rows (Format-artifact
gate) — they exist so the same noise doesn't get re-litigated next round,
not because an expert needs to act on them. Exception: `design_intent`
false positives still get real Actionable Fix Guidance text if they're
contingent on another row's fix (see Practical notes) — "no fix needed"
would be misleading there.

Save each file as `<task_id>_qc_validation.xlsx` and upload it to today's
dated subfolder under the shared Drive folder (see `docs/QC_SOP.docx` §1.4
Step I for the current link — do not hardcode it here, it has moved
before). Create the `YYYY-MM-DD` subfolder if it doesn't exist yet; use
the Google Drive MCP `create_file` tool with `base64Content` +
`disableConversionToGoogleType: true` to preserve native xlsx formatting.

## Also produce: one batch-level summary

A round almost never covers a single task — the per-task files above are
the audit trail, but nobody starts by reading 70 separate spreadsheets.
Before (or alongside) the per-task files, produce one consolidated view
across every task in this round:

- One row per task: `Task ID`, `Approved?` (zero `true_positive` rows of
  *any* Fix Owner — see the "Approved" definition in Practical notes),
  `Needs task-author review?` (zero `true_positive` rows with `Fix
  Owner: task_author` specifically — a task can be `Approved: No` yet
  have nothing for its author to act on, if every `true_positive` row is
  `pipeline_engineer`/`grading_reliability`; don't let those two
  collapse into one column), worst `Scoring Impact` among its
  `task_author` rows, and a one-line summary.
- Split the `task_author` rows out into their own review list (only these
  ever go in front of a domain expert), and keep `pipeline_engineer` /
  `grading_reliability` rows in a clearly separate section so they don't
  get triaged as content work by mistake — a task whose only issues are
  pipeline/grading-reliability rows is "approved" from the task author's
  point of view even though it is not "fully clean" for whoever owns the
  verifier or grading model.
- Scale this to what the round needs: for a handful of tasks, a plain
  table is enough; for dozens, build it as a filterable view (by verdict,
  by Fix Owner, by Scoring Impact) rather than a flat list nobody will
  scroll through.

## Also update: `QC Task Tracker` tab

Tracks task-level pipeline status only (`Internal QC (automated) →
Peer Review → External QC (automated) → this classification step →
External QC (manual)`) — it does **not** hold issue-level detail; that
lives in the per-task Drive file above. Columns as of the current reorg:
`Task, Delivery Team, Batch, Status, Internal QC (automated), Feedback,
Peer Review, External QC (automated), Feedback 2, Feedback Link, Passed
External QC (automated), External QC (manual), Feedback 3`.

For each `task_id` you find an existing row for (match on column A), once
you've classified all its issues for this round:
- **Phase 1 round** (source includes `internal_qc` and/or
  `dataos_automated`): write `Feedback Link` (Drive `viewUrl`, as an
  actual hyperlink) and `Passed External QC (automated)` = `Yes` if the
  task has zero `true_positive` rows across the *whole* consolidated
  sheet, else `No`. This is the *fully clean* tier (see "Approved"
  definition in Practical notes) — a task with an open
  `pipeline_engineer` or `grading_reliability` row is still `No` here
  even though its author has nothing to fix, since the pipeline gate
  cares whether real trials score correctly, not who owns the fix.
- **Phase 2 round** (source is `turing_manual`): by the same pairing
  pattern, write `Feedback 3` (the Drive `viewUrl`, as a hyperlink) and
  `External QC (manual)` = `Yes`/`No` on the same zero-`true_positive`
  basis. This pairing is inferred from the existing
  `Feedback 2` ↔ `External QC (automated)` pattern — confirm with the
  user once if this is the first Phase 2 round run through this skill.
- **Do not touch** any other column unless the user explicitly asks —
  those are set by other steps in the pipeline, not this classification
  pass.
- If no row exists yet for a `task_id`, ask the user before creating
  one — don't guess `Batch`/`Delivery Team` values.
- Also create/update the issue tracker spreadsheet's row on the QC
  tracker's "QC Task Overview" tab for other teams (see `docs/QC_SOP.docx`
  for the current link).

## Practical notes from running this before

- **Scale via parallel Agent dispatch**, not the Workflow tool (unless
  the user explicitly says "use a workflow"/"ultracode"). Batch ~3-5
  tasks per agent, each doing its own deep artifact verification and
  returning structured findings directly. **Every batch agent will be
  tempted to spawn its own per-task sub-agents instead of doing the work
  itself — this happens even when explicitly told not to, reliably,
  across most batches in a round, not as a rare edge case.** Tell each
  batch agent explicitly, in these words or close to them: "do not call
  the Agent/Task tool at all — read the files yourself and return the
  full structured result directly." If a batch agent still comes back
  with a stalling message ("standing by for my sub-agents") instead of
  actual findings, don't wait it out — resume it immediately with a
  correction telling it to do the work itself right now, or to collect
  and relay whatever its children already returned. A resumed parent
  agent loses track of children it isn't actively awaiting and will
  report "still waiting" even after its children finished, so don't
  assume it will self-correct. If an agent must fan out further, have
  the *top-level* orchestrator (you) collect all child results directly
  rather than trusting an intermediate agent to relay them after being
  resumed. Smaller batches (3, not 5) reduce how tempting it is for an
  agent to delegate rather than just doing 3 tasks itself.
- **Bash tool classifier flakiness**: transient "claude-sonnet-5 is
  temporarily unavailable" errors on Bash are common and usually resolve
  on immediate retry — don't treat one failure as a real blocker.
- **zsh gotcha**: this environment's Bash runs zsh, which does NOT
  word-split unquoted `"$VAR"` containing multiple space-separated tokens
  by default (unlike bash/sh). Use `${=VAR}` for zsh word-splitting, or
  avoid multi-token string variables in `for` loops — iterate over
  literal args or use arrays.
- **Verifying Drive uploads**: don't trust an agent's own "upload failed"
  self-report if it was interrupted mid-retry — always do a final, fresh
  (non-cached) `search_files` query against the target folder before
  concluding anything failed or needs re-uploading. Compare
  `createdTime`/file `id` against what you expect, not just file count.
- **"Approved" definition — two tiers, don't collapse them**: a task is
  *fully clean* only if it has zero `true_positive` rows of any Fix
  Owner in its consolidated sheet. But **"approved for the task
  author"** is a different, narrower question: zero `true_positive` rows
  with `Fix Owner: task_author` specifically. A task can legitimately be
  "not fully clean" (it has a real `pipeline_engineer` or
  `grading_reliability` true_positive) while having *nothing* for its
  domain expert to review — don't report that task as "needs expert
  review" just because it has an open `true_positive` row; check which
  Fix Owner that row actually has before routing it. This distinction is
  the main thing to get right in the batch summary (see "Also produce:
  one batch-level summary" above) — reporting it as one binary
  approved/not-approved number hides which tasks genuinely need a
  human's domain judgment versus which just need an infra ticket. A task
  with only `inconclusive` + `false_positive` rows is "approved" in the
  sense of no confirmed defect, but should still be called out distinctly
  from a task where a source raised zero complaints in the first place
  (for `dataos_automated`, check the original verification's top-level
  `"status"` field per trial — `PASSED`/`PASSED` on both trials means no
  complaint was ever raised; anything else means complaints were raised
  and resolved away).
- **Don't over-escalate a disclosure gap into a `task_author` open
  question**: it's tempting to tag anything without an explicit line in
  `instruction.md` as "needs the expert to decide." Check the golden
  solution first — if it already does the thing consistently (heavy
  formula use, a specific section, a specific tab), that's not an open
  question, it's an undisclosed convention that just needs writing down
  (see Methodology step 3). Reserve genuine `task_author` decisions for
  cases where nothing anywhere — not the golden, not a sibling
  criterion, not a source document — actually settles what the right
  answer is.
- **Contingent `design_intent` verdicts**: a `false_positive`/
  `design_intent` row (e.g. "the prompt's numbers are a deliberate
  injected trap the agent should reject") can depend on a *different*
  row's fix to actually be fair in practice (e.g. the canonical source an
  agent needs to detect the trap isn't shipped — a separate
  `true_positive`/`content_substance` row). Say this explicitly in both
  rows' Verdict Reasoning/Actionable Fix Guidance rather than letting the
  `false_positive` row read as fully resolved on its own — a reader who
  only skims Auto-Verdict should still learn that this "non-issue" is
  presently unfair until the companion row ships.
- **Don't let a plausible-sounding cause stand in for the traced one**:
  a `content_substance`-flavored complaint can turn out to actually be
  `pipeline_packaging` once you read the actual hydration/assembly script
  and its log, rather than inferring cause from the packaged output alone
  (see Methodology step 6). This changes *where the fix goes* (a script's
  exclusion filter vs. hand-editing the task's rubric/environment) — it
  does not, by itself, change the Auto-Verdict, and it is never a license
  to relabel a real defect as disregardable noise (see the Format-artifact
  gate's cautionary example).
- **Concrete tells for `grading_reliability`** (see Methodology step 6):
  read the specific run's recorded per-criterion reasoning, not just its
  score, for every flagged row before writing guidance. Three patterns
  that showed up repeatedly in one round: (1) the reasoning states the
  exact fact the criterion's own FAIL condition names, then the recorded
  score is PASS anyway (the model found the defect and didn't act on it);
  (2) two criteria checking the same underlying fact on the same
  submission in the same run return opposite verdicts, and neither
  criterion's *text* is actually ambiguous when you read them side by
  side; (3) the reasoning cites specific wording ("the memo references
  X") that a direct text search of the actual submission does not
  contain anywhere. Any of these means rewriting the criterion would not
  have changed the outcome — there's nothing for a task author to fix.
  Don't write task-author-facing guidance for these; log them for
  whoever maintains the grading model instead.

## What runs after this

Once a round's per-task files and batch summary exist, run
`automation/tp-fp-classification/gate-mining/SKILL.md` — it distills this
round's confirmed `task_author` `true_positive` rows into standing gates
(`automation/tp-fp-classification/batch-scan-gates.md`) that pre-screen
the *next* round's tasks before a full manual adjudication. It reads the
`Fix Owner` field to know which rows are even candidates —
`pipeline_engineer`/`grading_reliability` rows never become gates, since
there's no rubric-text pattern for a gate to scan for.

## Reference

Full project context (pipeline layout, cycle workflow, verifier-gate
calibration history) is in `docs/CLAUDE.md` — read it if anything here is
ambiguous or if this is a new batch that hasn't been bundled yet. Full SOP
narrative (when this skill runs, what feeds `cycle.py joint-feedback`,
tracker links) is in `docs/QC_SOP.docx` Phase 1 Step I and Phase 2 §2.5.
