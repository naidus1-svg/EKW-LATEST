---
name: dataos-batch-watch
description: >-
  Watch a running Data-OS "Pipeline Batch Run" for newly-COMPLETED tasks,
  download each one's "Task with runs" bundle the moment it finishes, and
  dispatch a fix-and-rebundle subagent per download. Drives the live Data-OS
  UI via the claude-in-chrome connector on a recurring interval (use with the
  `loop` skill). Use when asked to "watch this dataset/batch run", "keep an
  eye on this pipeline until it's done", or to babysit an in-flight
  Comprehensive Review batch.
---

# Data-OS batch-run watcher + auto-fix dispatcher

Confirmed live against `74-ekw-sprint` (dataset 1042, batch run
`/pipelines/batch-runs/67`) on 2026-09-15. Two things made this far simpler
than the eval-launching fleet in [dataos-qc-run](../dataos-qc-run/SKILL.md):

1. **Single-page completion signal.** A dataset's in-flight pipeline run has
   its own page at `/pipelines/batch-runs/<run_id>` (linked from the dataset
   page's "Pipeline Batch Runs" section) showing every task's status
   (`RUNNING`/`COMPLETED`/`EXCEPTION`/`CANCELED`) and a `N/total settled`
   counter, with filter tabs per status. One `get_page_text` call after
   clicking the `COMPLETED` filter tab returns the full list of finished task
   labels — no need to open all 67+ task pages individually to poll status.
2. **The "Task with runs" download is self-contained.** Unzipping
   `task_<label>-v<rev>_with_runs.zip` (Download dropdown → "Task with runs",
   on the task's own page) yields:
   ```
   task_<label>/rev_<n>__<internal_id>/
     task_files/          # instruction.md, task.toml, tests/, solution/, environment/
     evaluations/          # per-agent-run trajectories
     verifications/
       comprehensive_review_<id>___<agent>__<model>.md   # one per CR run
       qc_<id>___<model>.md
   ```
   Each `comprehensive_review_*.md` has a plain `## status` field
   (`PASSED`/`FAILED`) and a `## transcript` with the full judge prompt +
   findings — no separate verification-page download or JSON scraping
   needed. `Loss Pattern`/`Comprehensive Review` being "out of scope" in
   dataos-qc-run's SKILL.md is about *launching* those runs, not about
   reading their output once a pipeline already produced it — this skill
   only ever reads, never launches.

**Confirmed 2026-09-15, dataset 1042 batch run 67 — the `## status` header
is NOT reliable and should never be treated as signal.** Across every single
comprehensive_review_*.md downloaded so far (8 tasks, ~22 review runs), `##
status` says `PASSED` 100% of the time while the embedded
`"overall_verdict"` inside the transcript's own JSON output says `"reject"`
or `"invalid"` — never once `"accept"`. This looks like a labeling bug on
the Data-OS/pipeline side (the header field isn't reading the transcript's
actual verdict), not a per-task fluke. **Always grep the transcript body for
`"overall_verdict"` and treat that as the real result — ignore `## status`
entirely.** This also means: do not use `## status == PASSED` as a reason to
skip or lightly review a task's findings; every downloaded task so far has
had a real `reject`/`invalid` verdict underneath regardless of what the
header says.

## Required inputs — confirm BEFORE starting

| Input | How supplied | If missing |
|---|---|---|
| **Dataset URL/ID** | e.g. `https://data-os.turing.com/datasets/1042` | Ask — never guess |
| **Batch run** | usually "the currently RUNNING one" on that dataset's page | If more than one is RUNNING, ask which |
| **Poll cadence** | default 20 min while `Running` count is high, tighten to ~10 min once it drops below ~10 remaining | State the default, let the user override |
| **Stop condition** | default: `Running == 0` (all settled) OR user says stop | — |

## State file

One JSON file per watch, e.g. `dataos_qc_runs/<dataset_name>/watch_state.json`:

```json
{
  "dataset_id": 1042,
  "batch_run_id": 67,
  "downloaded": ["task_81", "task_9", "task_94", "..."],
  "dispatched": ["task_81"],
  "exceptions_flagged": []
}
```

`downloaded` gates re-downloading; `dispatched` gates re-spawning a fix agent
for the same bundle. Never silently drop an `EXCEPTION`/`CANCELED` task from
tracking — add it to `exceptions_flagged` and mention it in the notification;
those need a human look, not a re-queued download.

## Per-cycle procedure

1. **Poll.** Navigate to `/pipelines/batch-runs/<run_id>`, click the
   `COMPLETED` filter tab, `get_page_text`. Parse task labels. Also note the
   `EXCEPTION`/`CANCELED` counts — if either is nonzero and those tasks
   aren't yet in `exceptions_flagged`, record and flag them (do not attempt
   to download or fix them here; that needs human triage).
2. **Diff.** `new = completed_labels - state.downloaded`. If empty, log
   "no new completions" and skip to step 5.
3. **Download, per new task label** (sequential is fine at this scale; only
   parallelize with multiple tabs if the batch is large enough that this step
   is visibly the bottleneck):
   - Navigate to the task's page (`/tasks/<internal_id>` if known from an
     earlier listing, otherwise find it from the dataset's task list).
   - Click `Download` → `Task with runs`. This is server-side bundling — wait
     for the button's loading-spinner state to clear (observed ~5-8s for a
     ~1.3MB bundle) before assuming the download landed.
   - The file lands in `~/Downloads/task_<label>-v<rev>_with_runs.zip`
     (Chrome auto-suffixes `(1)` etc. on a repeat name — move it out
     immediately). `mv` it into
     `dataos_qc_runs/<dataset_name>/task_<label>/`.
   - Add the label to `state.downloaded`.
4. **Dispatch one fix subagent per newly-downloaded bundle** (parallel Agent
   calls in one message — these don't touch the browser, so no tab
   contention). Give each subagent:
   - The path to its unzipped bundle.
   - The mandate below (verify → plan → fix → rebundle).
   - Where to write its output and how to report back (see below).
   Mark the label `dispatched` once spawned.
5. **Adversarially verify each fix before calling it done** (per-task, once
   its fix subagent returns — see "Adversarial verify + retry" below). Do not
   report a fix as final until it survives this step.
6. **Notify.** One message to the user per cycle: what completed this round,
   what's still running (`N/total settled`), any exceptions flagged, and any
   fix results that finished verification (pass along the verified summary —
   don't just say "done", say what was found, fixed, and confirmed).
7. **Reschedule or stop.** If `Running == 0`, do a final poll, report the
   batch as fully settled, and stop the loop. Otherwise schedule the next
   cycle per the cadence above.

## Adversarial verify + retry (per fixed task)

A fix subagent grading its own work is exactly the failure mode this corpus's
Comprehensive Review prompt already warns about ("prior QC passes have been
wrong before") — a fresh, adversarial pass catches what the fixer's own
self-report won't. After a fix subagent returns:

1. Spawn a **separate, fresh-context verify subagent** (not the same one that
   made the fix). Give it: the originally-confirmed findings (from the fix
   subagent's report), the original `task_files/`, the fixed `task_files/`,
   and no access to — or credit given to — the fixer's self-assessment.
2. Its job, adversarial framing (default to "not resolved" / "still too
   easy" if the evidence is ambiguous, mirroring the "refuted=true if
   uncertain" convention used elsewhere in this corpus's verification):
   - For each originally-confirmed finding, independently re-derive whether
     the fixed files actually resolve it — don't just check that *something*
     changed near the flagged spot.
   - Separately, check whether the fix **reduced difficulty**: did it add
     scaffolding/hints that weren't there before, resolve ambiguity by
     picking the answer for the solver instead of specifying the missing
     convention, simplify a computation, or narrow a genuinely open judgment
     call into a spoon-fed one? Difficulty regressions are graded as failures
     even if the original finding is technically "resolved."
   - Verdict per finding: `resolved` / `not_resolved` / `resolved_but_eased`.
   - Also apply the two proactive checks from the fix subagent's mandate
     below (single-source-judge-can't-verify-cross-file-claims,
     mutually-inconsistent sibling criteria) to the criteria the fix
     *didn't* touch, not just the ones it changed — a fix can correctly
     resolve what it targeted while leaving an adjacent, equally-real defect
     of the same class unaddressed nearby.
3. **Before finalizing, run the fixed golden through the actual grading
   harness and confirm it passes cleanly.** Confirmed the hard way
   (2026-09-15): a fix can be textually and logically sound — every finding
   independently re-derived, no easing detected — and still be **broken**,
   because logical review never executes anything. Real re-uploads of 8
   "verified" tasks on this same day produced exceptions on 3 of them (2
   Daytona sandbox-creation failures, 1 verifier crash with no reward file)
   that no amount of reading `verifier.json`/diffing xlsx cells would have
   caught. This step is not optional and is not satisfied by "`solve.sh`
   runs locally" (which every broken fix in that incident also passed):
   - Actually execute the task's own grading path against the fixed golden
     — `test.sh` (native-harbor) or the rewardkit runner (rewardkit-hybrid),
     locally if the toolchain is installable (`pip install harbor-rewardkit`
     and its dependencies), or by staging a clean throwaway re-upload if not.
   - Confirm it produces a `reward.txt`/`reward.json` at all (a missing
     reward file — `RewardFileNotFoundError` — means the verifier itself
     crashed, not that the score was low).
   - Confirm the reward is at or near what the ORIGINAL unfixed golden
     scored before the fix (not necessarily 1.0 — some tasks' own goldens
     don't hit a perfect score — but a fix must not make a previously-clean
     golden fail). If you don't know the pre-fix baseline, get it: run the
     harness against the untouched original bundle first for comparison.
   - **Explicitly confirm the golden actually PASSES its own fixed verifier
     — not merely that the harness ran without crashing.** "No exceptions,
     reward file produced" and "the golden scores well" are different
     claims; this pipeline's core mandate (the original incident that
     started this whole process) was literally "does the golden pass
     verifiers, checked first" — don't let that regress into just an
     exception check. Concretely:
     - If a real judge call is available (a live re-upload, or local
       credentials): confirm the fixed golden's real reward is at or near
       1.0 (or the pre-fix baseline, whichever is the real bar for this
       task) on every criterion the fix touched, not just in aggregate — an
       aggregate near-1.0 score can still hide one still-failing touched
       criterion offset by others.
     - If no live judge call is available locally (the common case, no
       `OPENAI_API_KEY` in this sandbox): say so explicitly, then do the
       next best thing — read each touched criterion's new prompt text
       against the actual golden content it will be judging, and reason
       through, criterion by criterion, whether a reasonable judge would
       score it pass. This is what the fixer already does when writing the
       fix; the gate here is making that reasoning explicit and checked
       against the *final* fixed text, not just the intent. Report which
       criteria you could confirm this way and which remain genuinely
       unconfirmed pending a real re-upload — do not round "I reasoned
       through it" up to "confirmed passing."
     - Confirmed 2026-09-16 (task_48, task_72): a real re-upload can still
       reject a fix even when the golden now passes cleanly (both real
       Oracle runs scored 1.0), because *other*, untouched criteria still
       false-reject compliant model runs. Passing-golden and
       accept-verdict are two different bars — confirm both, and don't
       claim the second from evidence for only the first.
   - If genre is rewardkit-hybrid (Dockerfile references
     `environment/initial_workspace/`, package uses
     `tests/deliverables_NN/judge.toml` + `tests/reward.toml`, no
     `verifier_lib`): **never re-zip the downloaded `task_files/` as-is.**
     The "Task with runs" download reflects pre-build source
     (`environment/data/`), not the built package Data-OS actually needs —
     `environment/initial_workspace/` must exist in what you ship, built via
     `pipeline/tools/to_rewardkit.py` (or by copying/renaming
     `environment/data/` → `environment/initial_workspace/` if that's all
     the converter does for this task — verify against the converter's
     actual behavior, don't assume). Shipping without it produces exactly
     `FileNotFoundError: .../environment/initial_workspace/` at Data-OS's
     Daytona sandbox-creation step — the container never even starts, so no
     local check that stops at "does the zip look structurally complete"
     will catch it.
   - If this step can't be run at all (harness not installable, no spare
     upload slot), say so explicitly in the report rather than silently
     skipping it — "not harness-verified" is a materially different claim
     than "verified."
3.5. **Run the full Comprehensive Review prompt against the fixed package as
   a final, standing gate — added 2026-09-16 after a 3-generation failure
   pattern on task_48/21/28** (all shipped "verified" after adversarial
   verify + harness gate, all rejected on real re-upload, in two cases by a
   defect that had been visible in review evidence the whole time). Neither
   adversarial verify nor the harness-execution gate is a substitute for
   this: they check "did the fix do what it claimed" and "does it execute,"
   not "is this now a valid, high-quality task by the same exhaustive
   standard the real Data-OS reviewers apply." The exact prompt lives at
   `docs/ekw-svc-comprehensive-review.md` — dispatch it verbatim to a fresh
   subagent, pointed at the fixed `task_files/` plus the most recent real
   evaluations/verifications bundle as evidence. Two of its referenced
   skills ("workspace-layout," "exception-diagnosis") don't exist in this
   repo — instruct the agent to say so and mark any dependent finding
   `inconclusive` per the prompt's own fallback rule, not skip the check.
   - If it returns `accept`: proceed to step 4.
   - If it returns `needs_revision` (minors only) or `reject`/`invalid`
     (a major): treat every confirmed finding exactly like an adversarial-
     verify `not_resolved` — do not ship, spawn a new fix-and-reverify round
     with the finding quoted verbatim, same retry cap as below.
   - This step catches what golden-only reasoning structurally cannot: a
     criterion that's brittle to an *alternate* valid construction (the
     golden always satisfies its own convention, so reading the golden
     against the rubric top-to-bottom never surfaces this), and unaddressed
     findings that were sitting in prior review text the whole time but
     never made a fixer's selected scope (see the findings-triage-
     completeness gate below).
4. **If every finding is `resolved`, the harness run passes cleanly, AND the
   Comprehensive Review returns `accept`**: the
   fix stands. Finalize the zip, mark the task `verified` in the state file,
   include it in the next notification.
5. **If any finding is `not_resolved` or `resolved_but_eased`, OR the harness
   run fails/produces no reward file**: this is a dial-back, not a partial
   credit. Discard the candidate `fixed/` output, and spawn a **new fix
   subagent** (same mandate as before) with one addition: the verify
   subagent's specific, per-finding feedback on what was wrong with the
   previous attempt (quote its reasoning, don't paraphrase it away) — plus
   an explicit instruction not to repeat that failure mode. Re-run the
   adversarial verify step (including the harness run) on the new attempt.
6. **Cap retries at 2** (3 total fix attempts). If it still doesn't pass,
   stop looping — report the task as `needs_human_review` with the full
   history of attempts and why each failed, rather than silently shipping an
   unverified fix or looping forever.

## The fix subagent's mandate

Each subagent gets exactly one downloaded bundle. Its job, in order:

1. **Read every `comprehensive_review_*.md` in `verifications/`.** Note the
   `## status` and every failing/major-severity finding in the transcript.
   Multiple CR runs on one task can disagree — don't just take the first
   one's word.
2. **Verify each flagged issue against `task_files/` directly** — open the
   actual instruction, task.toml, tests, solution, environment files the
   finding references. Comprehensive Review prompts in this corpus
   explicitly warn "prior QC passes in this corpus have been wrong before" —
   treat every finding as a claim to check, not a fact to inherit. If a
   finding doesn't hold up against the real files, don't fix it — note in
   your report that you rejected it and why.

   **Proactively check for two recurring defect classes**, even if no review
   flagged them — confirmed 2026-09-16 across task_37/task_69/task_72 and
   others, so treat these as standing checklist items, not one-off findings:
   - **Single-source-judge can't verify cross-file claims.** For every
     criterion whose prompt text implies checking groundedness/support
     against *source* documents ("supported by the records," "traceable to
     the supplied data," etc.), read its `source` config. If that source is
     only the deliverable file (memo/workbook) and never the source
     materials, the judge architecturally cannot verify what the criterion
     claims to grade — it will either false-fail everything (rejecting
     correctly-sourced facts it can't confirm) or silently pass anything
     (nothing to check against). This is a structural defect regardless of
     whether a specific eval run has tripped it yet.
   - **Mutually-inconsistent sibling criteria.** Check whether any
     criterion's PASS condition is satisfiable by exactly the approach a
     *different* criterion's FAIL condition targets. This produces both
     false-credit (a run that takes the forbidden approach passes the
     criterion that doesn't know it's forbidden) and false-rejection (a run
     that takes the intended approach fails a criterion written around the
     other reading) — sometimes on materially identical answers from
     different runs. Don't just read each criterion in isolation; check that
     sibling criteria on the same judgment call agree on what "correct"
     means.
   - **Asymmetric carve-out across parallel criteria for the same fact on
     different deliverables.** Confirmed 2026-09-16 (task_48): when a task
     grades the same underlying fact on two deliverables (e.g. a memo AND a
     workbook both cite which rules apply to an item), check whether one
     side's criterion has an explicit leniency carve-out the other side's
     twin criterion lacks. If the memo-side criterion was already patched to
     accept a real, valid presentation style (e.g. "rule field may cite
     'R-31; R-22'") but the workbook-side criterion for the identical fact
     was never given the same carve-out, every solver who uses that valid
     style consistently across both deliverables gets penalized only on the
     unpatched side — a real, systematic false-rejection, and a strong
     signal that an earlier fix pass touched one criterion but missed its
     untouched twin. When you find and fix one side of this pattern, always
     check for and fix its sibling in the same pass.
   - **An undisclosed-convention fix on one variable doesn't cover sibling
     variables in the same model.** Confirmed 2026-09-16 (task_28): a fix
     correctly disclosed one genuinely-undisclosed computational convention
     (a divide-vs-multiply ambiguity on a dual-income adjustment, resolved
     by adding an instruction sentence + source note stating the golden's
     always-intended-but-never-stated rule). On real re-upload, a
     *different* parameter in the same financial model (an adoption-rate
     stock-vs-flow ambiguity — cumulative penetration vs. new-intake-only)
     turned out to have the identical defect class, untouched by the first
     fix, and cost two independent real runs a large reward swing on an
     equally defensible alternate reading. When you find and fix one
     undisclosed-convention defect in a multi-parameter model, **scan the
     model's other input parameters for the same class of ambiguity**
     (any value/rate/adjustment with no stated formula or direction in
     either the instruction or the source data) before considering the
     model's ambiguity risk closed — fixing the one instance a review
     happened to catch does not imply siblings are clean.
   - **Literal-restatement gating when a sibling criterion already verifies
     the exact figure on a different deliverable.** Confirmed 2026-09-16
     (task_21): a criterion on the memo/prose deliverable required a number
     be stated *verbatim* (e.g. "84% material coverage"), with no allowance
     for a correct paraphrase ("sub-90% coverage," "below the material
     threshold"), while a sibling criterion on the workbook deliverable
     already independently verifies the precise figure. A real run did the
     analysis correctly, paraphrased the number in prose, stated it exactly
     in the workbook, and was penalized anyway — the prose-side criterion
     was grading exact wording, not correctness, and duplicating a check the
     workbook-side criterion already owns. When a criterion's only failure
     mode on a real run is "said this correctly but didn't use these exact
     words/didn't restate a number verbatim," check whether a sibling
     criterion elsewhere already verifies that number precisely — if so,
     loosen the prose-side criterion to accept a correct paraphrase and let
     the sibling own precision, rather than double-gating the same fact once
     loosely and once exactly.
   - **Any edit to a golden `.xlsx` — including a single-cell text change on
     an otherwise "cosmetic, metadata-only" cleanup pass — must use raw XML
     surgery, never `openpyxl.load_workbook().save()`, and must be verified
     by a before/after cached-cell count, every time, no exceptions.** Full
     procedure, code, and the confirmed 2026-09-16 (task_28, round 4)
     incident that motivated this rule (a "quick, low-risk" citation fix
     silently stripped 63% of a workbook's cached formula values, which
     would have failed the Oracle's own golden on ~77% of the rubric's
     weight) now live in their own dedicated skill:
     [`safe-xlsx-golden-edit`](../safe-xlsx-golden-edit/SKILL.md). Read it
     before touching any golden `.xlsx`, for any reason, no matter how
     small the intended change looks.
   - **Always establish your baseline from the actual shipped zip, never a
     loose `task_files/` directory — even one that "looks right."**
     Confirmed 2026-09-16 (task_21, retry attempt 1): a fix agent built its
     round-2 "baseline" snapshot from a stale loose directory that predated
     a later refinement to the same round. It diffed against this wrong
     baseline, never noticed, and shipped a fix that silently deleted two
     unrelated criteria and reverted five others to stricter wording — a
     worse regression than the single defect it was sent to fix. Before
     trusting *any* on-disk `task_files/` directory as a round's true
     output, fresh-unzip the actual `*_fixed.zip` for that round into a
     clean scratch dir and diff the loose directory against it; if they
     differ, the zip is authoritative, always. This is a five-second check
     that would have caught the failure immediately.
   - **A fixer's own most-recent local evidence overrides its narrative
     summary — check the actual last-run numbers, not what the fix note
     claims to have targeted.** Confirmed 2026-09-16 (task_21): a round-2
     "SHIP" note described fixing v1-v4/v15 and said nothing about v14 —
     but that same round's own final oracle run, already sitting on disk,
     showed reward 0.929 with **both** v14 and v15 failing. The shipped
     "golden passes verifiers" claim was contradicted by evidence the fixer
     already had, not evidence that only a live re-upload could reveal.
     Before shipping any round, re-parse the actual `reward.json`/
     `verifier-report.json` from the most recent local or oracle run
     yourself and treat `reward < 1.0` (or below whatever the task's real
     bar is) as a hard blocker regardless of which criteria the fix note
     says it addressed — do not accept a fixer's self-selected scope as
     evidence the rest is clean.
   - **Mechanically self-test any new/edited rubric clause against its own
     worked example before shipping.** Confirmed 2026-09-16 (task_48): a
     fix added a carve-out clause with an illustrative example, but the
     example's own stated logic didn't actually reduce to the target
     ordering it claimed to permit — a self-contradiction invisible to
     re-reading the prose fluently, only caught by literally applying the
     clause's rule to its own example and to the real golden content. This
     is a deterministic, offline, no-judge-needed check: for every new
     clause with an "e.g." or worked example, mechanically compute what the
     clause's own logic produces on that example and on the actual golden,
     and confirm both reduce to a genuine pass — not just plausible-sounding
     prose.
   - **For any criterion grading an intermediate/process value (not just the
     final output), construct one alternate-but-valid solution path and
     confirm the criterion accepts it — re-confirming the golden alone
     proves nothing about ordering/construction brittleness.** Confirmed
     2026-09-16 (task_28), surfaced independently by six separate
     investigations converging on the same mechanism: a criterion pinned
     the golden's specific intermediate-calculation ordering (which filters
     applied before which conversion step) as the only acceptable
     construction. Every real submission used a different, mathematically
     equivalent ordering and was hard-failed. Because the golden trivially
     satisfies its own convention by definition, no amount of re-reading
     the golden against the rubric can surface this — it requires building
     (or reusing an available real submission as) a genuinely different
     valid construction and checking the rubric text against *that*, not
     just the golden.
   - **Before shipping any round, sweep every confirmed finding across
     every review file this task has ever received and give each one an
     explicit disposition — fixed / deferred-with-reason / refuted-with-
     evidence — not just the findings a fixer happened to select as this
     round's scope.** Confirmed 2026-09-16 (task_28): three independent
     round-1 review files had already named the exact defect (an
     intermediate-value ordering brittleness, quoting the same reward-loss
     figure) that went on to survive two "shipped" rounds untouched, purely
     because neither round's fixer's self-selected scope happened to
     include it. "Confirmed byte-identical/untouched" in a fix note is a
     non-regression check, not a completeness check — it tells you a
     criterion wasn't broken by *this* round, not that it doesn't need
     fixing at all. A finding sitting in static review text, available
     locally with no live judge needed, is exactly the kind of evidence
     this triage sweep is meant to catch before it costs another
     generation.
   - **When a real finding is deliberately deferred (lower-confidence,
     out-of-scope-for-this-pass, or "needs a bigger rewrite than a
     conservative fix should attempt"), say so with enough specificity that
     it survives to the next round** — don't let "confirmed real but not
     fixed" quietly become invisible. Confirmed 2026-09-16 (task_48): a
     first-pass fix correctly deferred a criteria-overlap/duplication
     finding as lower-priority; a second real re-upload rejected the task
     specifically because of that deferred issue (plus its previously-
     unnoticed asymmetric-carve-out sibling). The deferred finding wasn't
     wrong to defer — a conservative single-pass fix is the right call when
     multiple real defects compete for attention — but it needs to be
     reported as a concrete, re-actionable to-do (which criteria, why,
     what the fix would look like), not folded into a vague "some overlap
     exists" aside that's easy to lose between rounds.
3. **Plan a fix that resolves confirmed issues without reducing difficulty.**
   This corpus's own review prompt states the rule to apply: only fix
   ambiguity/misalignment/leakage/nondeterminism, never remove genuine
   difficulty; dense-but-parseable source language is difficulty, not
   ambiguity, and should be left alone. If a "fix" would make the task
   easier or more solvable than intended, it is the wrong fix — find the one
   that resolves the defect while preserving (or increasing) rigor.
   [[project_qc-service-automation-design]]
   **Default to fixing the verifier (`verifier.json`/`judge.toml`/`reward.toml`)
   over editing the golden.** Verifier files are plain text/JSON — safe to
   edit, easy to diff, and a rubric bug (wrong weight, unfair bundling, an
   invented requirement) is exactly what these files are for. Golden output
   files (`.xlsx`/`.docx`) are the highest-risk edit surface in this whole
   pipeline: confirmed 2026-09-15, direct XML surgery on golden xlsx/docx
   files (done to preserve cached formula values across an openpyxl-blanking
   bug) produced files that passed every local check — openpyxl reads them
   fine, `solve.sh` reproduces them, structure diffs clean — and then broke
   in the real Data-OS grading harness. Only edit a golden file when the
   defect is factually IN the golden (a wrong number, an invented claim, a
   stale reference) — a rubric being unfair, ambiguous, or miscalibrated
   against a correct golden is a verifier problem, not a golden problem, even
   if patching the golden would also make the symptom go away. Any golden
   edit is what the harness-run gate below exists to catch — don't skip it
   because the edit "looked safe" locally. For any `.xlsx` golden edit
   specifically, follow
   [`safe-xlsx-golden-edit`](../safe-xlsx-golden-edit/SKILL.md)'s procedure
   and mandatory before/after cached-cell check — it exists precisely
   because "looked safe locally" has failed silently here twice.
4. **Apply the fix to a copy of `task_files/`**, not the original bundle.
   **Before making any edit, copy the current `tests/verifier.json` (and any
   other file about to be touched) to a timestamped or round-numbered
   snapshot** (e.g. `verifier.json.round1`, `verifier.json.round2`) alongside
   it. Confirmed 2026-09-16 (task_48, second fix round): without this, a
   later verify pass has no way to byte-diff "did round 2 touch anything
   round 1 already fixed" against round 1's actual output — only against the
   original pre-any-fix download, which can't distinguish a round-1 fix from
   a round-2 regression on the same criterion. This is a few seconds of work
   that a multi-round fix cannot be fully audited without.
5. **Rebundle for resubmission.** The upload format is the reward-kit layout
   ([harbor-rewardkit-convert](../harbor-rewardkit-convert/SKILL.md)), not
   the "with runs" bundle shape — do not just re-zip
   `task_files/` verbatim if it isn't already in that layout. Check whether
   the source is already reward-kit-shaped (has `tests/deliverables/judge.toml`)
   or old-format harbor (has `tests/verifier.json`) and convert if needed
   before zipping.
6. **Report back**: per finding — confirmed or rejected (with reason), fix
   applied (or "no fix needed, false positive"), and the path to the
   rebundled zip ready for the "Upload tasks" button. This report is what
   gets relayed to the user — write it for a human deciding whether to
   actually re-upload, not as an internal log.
7. **If any confirmed finding challenges the golden's factual/technical
   correctness in a specialized domain** (clinical, legal, financial-
   regulatory, or similar — anywhere getting it wrong has real-world
   safety/compliance implications, not just a grading-fairness one) —
   **do not resolve it yourself.** Confirmed 2026-09-16 (task_72): a review
   raised a specific, citation-backed claim that the golden's clinical
   mechanism was pharmacologically invalid (not just unfairly graded) — this
   is exactly the kind of claim a fix subagent is not positioned to
   adjudicate with confidence, unlike a rubric-wording or arithmetic check
   the agent can independently verify. Report it distinctly from ordinary
   rubric/verifier findings, quote the evidence and citations verbatim, and
   flag it for human (ideally domain-expert) review rather than folding it
   into a routine verifier-vs-golden edit-scope decision.

## An infra-only fix can mask rubric/content defects that only surface later

Confirmed 2026-09-16 (task_72): a fix that resolves a pure infrastructure bug
(wrong judge-provider config, missing file, broken script) causing every
evaluation to error or score 0.0 does not just unblock scoring — it removes
the only thing that would have let anyone see whether the *rubric* and the
*golden's content* are actually sound, because a broken pipeline never
produces a real judge signal to check them against. The original
comprehensive reviews on such a task were themselves working blind on
calibration questions, for the same reason.

Practical implications:
- **Don't treat "no prior CR flagged this" as evidence a rubric/content
  issue doesn't exist**, if the prior CRs were reviewing a task whose evals
  were erroring/scoring 0 for infra reasons at the time. Absence of a
  finding under those conditions is not confirmation of soundness.
- **After an infra-only fix (one that didn't touch verifier.json rubric text
  or golden content), expect that a real re-upload may surface genuine,
  previously-invisible rubric-calibration or even golden-content defects on
  its first real grading pass** — this is not a regression caused by the
  fix; it's the fix working (first real signal ever produced) combined with
  a pre-existing defect nobody could have seen before. Say so explicitly in
  the fix report so a human doesn't mistake a "still reject" verdict on
  re-test for the fix having failed.
- When triaging a fresh reject verdict on a re-uploaded task, always check
  first whether the new findings are about the SAME area the original fix
  touched (a real regression, take it seriously) or a DIFFERENT area the
  original fix never went near (almost certainly pre-existing and newly
  visible, not introduced) — the fix report's list of exactly which files/
  criteria were touched is what makes this check possible, so keep that
  list precise.

## Gotchas carried over from dataos-qc-run / RECIPE.md

- Never trust a modal's pre-filled state; this skill doesn't launch runs at
  all, so this mostly doesn't apply — but if a future version adds
  relaunch-on-exception, re-read RECIPE.md's dry-run findings first.
- Downloaded artifacts go in a dataset-named directory
  (`dataos_qc_runs/<dataset_name>/...`), not a `cycles/<date>/` folder — this
  matches the existing artifact-collection convention.
- The `benchmark_type` missing-metadata validation warning is always benign
  for EKW tasks — never treat it as something for a fix subagent to "fix".
