---
name: fix-task-from-review
description: >-
  Given ONE downloaded EKW/SVC-PC task bundle (task_files/ + its
  evaluations/verifications, or just task_files/ plus a review verdict/JSON)
  and real feedback saying it's rejected/needs work, verify the findings,
  fix the task, and confirm the fix through harness execution, adversarial
  verify, and a Comprehensive Review pass — end to end, for a single task.
  Use this directly when you have one task to fix. If you're watching a
  whole in-flight batch run and need to poll for completions and dispatch
  this per newly-finished task, use
  [`dataos-batch-watch`](../dataos-batch-watch/SKILL.md) instead, which
  calls this procedure per task.
---

# Fix a task from real review feedback

This is the fix-and-verify loop for a single task, decoupled from any batch
orchestration. Everything here works from local files — no Data-OS UI
interaction is required except the final manual re-upload.

## The standing bar: zero real-QC major verdicts on a task we called "ready"

**Confirmed 2026-09-16 (task_28, task_48):** both tasks went through a full
fix → adversarial-verify → local Comprehensive-Review-gate cycle, were
called clean or minors-only, and then came back from a *real* Data-OS
review panel with **major** findings — 3/3 reviewers on one task, 2/3 on the
other. Root-causing both showed the failures weren't random: they cluster
into three specific, avoidable process gaps, each now a mandatory check
below (search this file for "GAP" to find each one):

1. **Wording-only re-fixes of the same criterion don't generalize to real
   judges, and we didn't escalate after the first re-failure.** A criterion
   patched twice with cleverer wording was still broken a third time. Hand-
   constructed worked examples validate that *you* find the new wording
   unambiguous — they say nothing about how an independent LLM judge will
   read it. See the escalation rule in Step 1.
2. **A "Comprehensive Review gate" that only re-examines what the round
   touched isn't comprehensive.** Two real major findings were sitting
   untouched since round 1 and survived a dedicated gate pass whose actual
   scope was narrower than its name. See Step 6's full-sweep requirement.
3. **A predicted risk that got reasoned into "legitimate, not a defect"
   was never tested against the review's own severity rule.** We correctly
   anticipated a symptom and then talked ourselves out of it being a
   problem instead of checking it against the actual false-rejection/
   false-credit test. See the mandatory severity-rule check in Step 2.

If you take one thing from this file: **local confidence is not real-judge
confidence.** Every gate below exists to close a specific, previously-
confirmed gap between the two — treat a gate you're tempted to shortcut as
the exact spot the next miss will come from.

## Scope rule: only tasks the review FAILED (added 2026-09-18)

The expert review CSV gives three column verdicts per task (Good | Minor | Major). If **no column is Major,
the task passed — do not run this procedure on it**; ship the reviewed bytes unchanged and log the minors.
Four passed tasks were reworked by mistake on 2026-09-18 and restored. Reworking a passed package only adds
risk and cost.

## What you need before starting

- The task's unzipped bundle. At minimum `task_files/` (`instruction.md`,
  `task.toml`, `tests/`, `solution/`, `environment/`). Ideally also
  `evaluations/` (real agent-run trajectories/rewards) and `verifications/`
  (comprehensive-review reports) from the same download — these are your
  evidence base; without them you're reasoning from the review text alone.
- The actual feedback: a `comprehensive_review_*.md`/JSON verdict, an
  oracle/real-eval reward showing a failure, or a directly-stated defect.
  Confirmed findings only — see step 1 for why you re-derive rather than
  trust this input.
- Know which of the two build genres you're in before touching anything:
  **native-harbor** (`Dockerfile` does `COPY data/ /workspace/data/`, ships
  `tests/__verifier_lib/` + `verifier_runtime.pyrun`) or **rewardkit-hybrid**
  (`Dockerfile` does `COPY initial_workspace/ /app/`, graded via an
  installed `harbor-rewardkit` package, rubric lives in
  `tests/deliverables_*/judge.toml` + `tests/reward.toml`). A file one
  genre needs is correctly absent in the other — don't flag it as missing.

## Model tiering — cheap models only for mechanical, checkable sub-tasks

Dispatching every sub-task on the strongest available model is wasteful when
much of this pipeline's work is mechanical. But the corpus's own history this
sprint (task_121's 5-round mislabeling saga, the recurring "background agent"
hallucination) shows that a weaker model's biggest risk isn't being wrong on
hard judgment calls — it's *claiming completeness on an exhaustive sweep it
didn't actually finish*, and that risk exists at any model tier, so a cheap
model must never be trusted on its own say-so. The rule below exists to get
the cost savings without inheriting that failure mode.

**Allowed on `haiku`** — mechanical, verifiable-by-a-non-LLM-check tasks only:
- Packaging/hygiene checks: `unzip -l`/`unzip -t` output review, hunting for
  `.round*`/`__pycache__`/stray files before a zip ships.
- Mechanical string replacements where the exact old/new pairs (or a fully-
  specified regex) are already decided by a human or a stronger-model plan —
  not "find and fix the mislabeling," only "replace these N exact strings."
- Blank-field population in `task.toml` metadata from an already-known value.
- CRLF/line-ending fixes.
- Step 5b's deterministic-check-registry run itself (invoking the script,
  collecting `summary.csv`/`<check>.json` output) — but not judging whether a
  `fail` finding is real; that's a re-derivation task, see below.
- Status/audit reports: directory listings, zip inventories, counting
  shipped-vs-submitted, watch-state summaries — anything that's really just
  "run these commands and report what they say" with no interpretation.

**Never on `haiku`, always `sonnet`/`opus`** — anything requiring judgment,
exhaustiveness the model itself must vouch for, or domain correctness:
- Step 1 finding verification, and every "proactively check for these
  recurring defect classes" sweep — these require reading and judging, not
  pattern-matching a fixed string.
- Step 2/3 fix planning and authoring — deciding *what* the correct fix is,
  writing new criterion prose, editing golden narrative content.
- Step 5 adversarial verify and Step 6 Comprehensive Review — the entire
  point of both is skepticism a weaker model is less equipped to sustain.
- Judging Step 5b `fail`/`warn` findings, or any exhaustive-sweep claim of the
  form "I checked every X and found none remaining" — this is exactly the
  claim that failed 4 times in a row on task_121, and a weaker model is not
  more trustworthy making it, only cheaper while doing so.

**Guardrails (mandatory whenever `model: "haiku"` is passed to Agent):**
1. **Never accept a haiku agent's own completion claim as verification.**
   Every haiku-tier dispatch must end in a mechanical, independently-run check
   you (the orchestrator) execute yourself — a diff against expected content,
   an occurrence count, `unzip -l`/`-t`, an exit code — never "the agent said
   it did N replacements." If no such independent check is possible for a
   sub-task, it doesn't belong on haiku.
2. **One retry, then promote, never loop on the same tier.** If a haiku
   dispatch fails its independent check, retry once with the specific failure
   quoted verbatim. If it fails again, promote the same sub-task to `sonnet`
   rather than retrying haiku a third time — two failures at the cheap tier is
   itself a signal the sub-task was miscategorized as mechanical.
3. **A haiku agent that reports encountering ambiguity, a judgment call, or
   anything outside its literal instructions must stop and hand back, not
   decide.** Treat any such report as an automatic promotion to `sonnet` for
   that sub-task, not a haiku retry.
4. **Never dispatch Steps 1, 2, 3 (fix authoring), 5, or 6 to haiku, in whole
   or in part**, even under time pressure — these are exactly the steps this
   skill's "GAP 1/2/3" history exists to protect, and every one of those gaps
   was a completeness/judgment failure, the specific thing haiku is weakest
   at.

## Step 1 — Verify every finding against the real files

**Start by running the evidence sweep — do not hand-roll this.** Before reading
a single review document:

    pipeline/.venv/bin/python deterministic-checks/eval_evidence_sweep.py \
      --root <the with_runs bundle> --package-root <the baseline package> --out <workdir>/evidence

It already computes, from the real `reward-details.json`/`verifier-report.json`
artifacts, the four things a fixer otherwise reconstructs by hand: every
criterion the **oracle** scored below 1.0 (the golden failing its own rubric —
definitionally major), every criterion failing ≥75% of real agent runs *with
the judge's own reasoning* (the brittle/unstated-requirement candidates), any
run whose reward came from a **fatal error** rather than a low score (a
`total_verifiers: 0` infrastructure zero is invisible in an aggregate report
and looks like a hard task), and the platform `qc_*.md` / comprehensive-review
verdicts — then marks each flagged criterion UNCHANGED/EDITED/DROPPED against
the package you're about to fix.

**Confirmed 2026-09-22:** across a 30-task session, every fixer re-derived this
by opening `reward-details.json` files one at a time, and the sweep was never
run once. Its output is the evidence base for everything below; read the
reviews *against* it, not before it.

Read every `comprehensive_review_*.md`/verdict available. **A `## status`
header field on these reports is known-unreliable on this corpus's
Data-OS pipeline** (it reads `PASSED` regardless of actual content) — the
real verdict is the embedded `"overall_verdict"` JSON near the end of the
transcript (`accept`/`reject`/`invalid`/`needs_revision`). Grep for the JSON
block containing `"benchmark"`, not the schema-template line near the top of
the file that also contains the literal string `"overall_verdict": "accept |
reject | invalid | needs_revision"` — that's the prompt's own instructions
being echoed, not a real answer.

Then open the actual files each finding references — instruction, task.toml,
tests/, solution/, environment/ — and check whether the finding holds up.
**Treat every finding as a claim to verify, not a fact to inherit**: this
corpus has had confirmed cases of a prior review fabricating a defect that
direct file inspection disproved, and of a real defect being misdiagnosed as
a different one entirely. If a finding doesn't hold up, don't fix it — note
that you rejected it and why.

**When a task gets two independent reviews, don't average their credibility.**
A large-scale adjudication across 54 real tasks (2026-09-17, ~250 findings)
found the two reviewer identities are not equally reliable: one reviewer
("codex"/gpt-5.6-sol) accounted for the large majority of confirmed false
positives, with a specific recurring shape — narrating a plausible-sounding
"brittle rejection" or "unsupported ambiguity" story without checking
whether the actual cited eval run's `verifier-report.json`/`reward-details.json`
failed for that reason at all (several flagship "major" findings collapsed
the moment the real judge output was read). The other reviewer
("claude-code"/claude-opus-5) held up far more consistently. This is not a
license to skip verifying claude-code's findings — it did produce some
false positives too — but a codex-only major, especially one describing a
run's failure reason rather than a static text mismatch, needs its
underlying eval artifacts (not just the review's prose) checked before you
treat it as confirmed. Agreement between both reviewers on the same root
cause is a strong true-positive signal; a codex-only claim is not, by
itself.

**But do not turn reviewer identity into the test either.** Confirmed
2026-09-22 across 30 tasks: codex-only majors were rejected on the evidence in
task_1 (5 of them), task_549, task_574, task_145, task_48 and task_322 — *and*
the claude-code reviewer was independently wrong twice on task_LGL-160, where
codex was right. Neither identity predicts truth well enough to lean on.

**The rule that does hold: a finding is `confirmed` only when you can name the
criterion AND the specific run whose recorded verdict demonstrates it.** Write
both into `reports/<task>_TRACE.json` — the criterion name and the eval
artifact path. A finding you cannot tie to a real verdict is a hypothesis, and
belongs in the report as `refuted-with-evidence` or
`not-a-defect:<reason>`, never as a fix. This is mechanically checkable, it is
what actually separated the true from the false positives in that session, and
it costs nothing once the Step 1 evidence sweep above has already produced the
per-criterion run data.

**Proactively check for these recurring defect classes**, even if nothing
flagged them — each has bitten real tasks in this corpus and none requires a
live judge to catch, only careful reading:

- **Single-source-judge can't verify cross-file claims.** For any criterion
  whose prompt implies checking groundedness against *source* documents
  ("supported by the records," "traceable to the supplied data"), read its
  actual `source` config. If that source is only the deliverable file and
  never the source materials, the judge architecturally cannot verify what
  it claims to grade — it will false-fail correctly-sourced work or
  silently pass anything. This is a structural defect regardless of whether
  a specific run has tripped it yet.
- **Mutually-inconsistent sibling criteria.** Check whether one criterion's
  PASS condition is satisfiable by exactly the approach a *different*
  criterion's FAIL condition targets.
- **Asymmetric carve-out across parallel criteria for the same fact on
  different deliverables.** If a memo-side criterion was patched to accept
  a valid presentation style, check whether the workbook-side twin grading
  the identical fact got the same carve-out.
- **An undisclosed-convention fix on one variable doesn't cover sibling
  variables in the same model.** If you disclose one genuinely-undisclosed
  computational convention (a divide-vs-multiply ambiguity, say), scan the
  model's *other* input parameters for the same class of ambiguity before
  considering the model's ambiguity risk closed.
- **Literal-restatement gating when a sibling criterion already verifies
  the exact figure on a different deliverable.** If a criterion's only
  failure mode on a real run is "said this correctly but didn't restate a
  number verbatim," check whether a sibling criterion elsewhere already
  verifies that number precisely — if so, loosen the prose-side criterion to
  accept a correct paraphrase.
- **A criterion pinning one specific intermediate-calculation ordering as
  the only acceptable construction**, when the instruction never mandates
  that ordering and an alternate ordering is mathematically/logically
  equivalent. The golden trivially satisfies its own convention by
  definition, so re-reading the golden against the rubric can never surface
  this — you have to construct (or use a real submission as) a genuinely
  different valid construction and check the rubric text against *that*.
- **A criterion the golden itself fails.** Check every criterion against
  the golden's own actual content, not just against what the fix note from
  a prior round claims was checked. "Confirmed byte-identical/untouched" in
  a prior round's note is a non-regression check, not a completeness check
  — it tells you a criterion wasn't broken by that round, not that it
  doesn't need fixing.
- **A confirmed finding that was deliberately deferred in a prior round**
  and never got a concrete disposition. Sweep every finding across *every*
  review file this task has ever received — not just the current one — and
  give each an explicit fixed/deferred-with-reason/refuted-with-evidence
  status. A defect visible in review evidence from round 1 that nobody
  actioned by round 3 is exactly the failure mode this sweep catches.

**GAP 1 — escalation rule: a criterion edited 2+ times and still failing
needs a different kind of fix, not another wording tweak.** Before editing
any criterion, check its edit history across all prior rounds' snapshots
(`verifier.json.round1`, `.round2`, …) and the tracker notes. If this is the
**third or later** attempt to fix the *same* criterion's brittleness/false-
rejection (not a new, different criterion — the same one, again), do not
just write a cleverer worked example and re-test it against yourself. Two
prior wording fixes already passed your own self-test and still failed real
judges — a third hand-constructed example proves nothing new. Instead,
either (a) restructure the criterion to remove the ambiguous, presentation-
sensitive language entirely (e.g. stop requiring a specific list *format*
and check only the underlying *facts* it's meant to verify, accepting any
presentation that conveys them), or (b) flag it explicitly in your report as
a criterion that has now resisted two real-judge-driven fix attempts and
recommend it for a from-scratch rewrite or human review rather than a third
local patch. Shipping a third same-pattern wording tweak without one of
these two responses is exactly how this gap recurs.

**GAP 4 — a fix scoped to only the reviewer's/judge's quoted examples doesn't
generalize; sweep the whole defect *pattern*, not just the cited instances.**
Confirmed 2026-09-17 (task_61, task_57): both were fixed after a real oracle
run flagged one instance of a defect (task_61: one stale cached cross-sheet
number; task_57: four fabricated/unsupported narrative figures), verified,
reshipped — and the *next* real oracle run flagged the exact same criterion
failing again, citing **different instances of the identical defect
pattern** that the first fix never touched: task_61 had a second stale
number, this time hardcoded into narrative text rather than a live formula
(the first fix only swept formula cross-references); task_57 had three more
unsupported specific figures in nearby sentences the first fix never read.
In both cases the original fix was correct and complete for exactly what it
targeted — it simply didn't generalize to the defect's full footprint,
because a judge or reviewer reports a *sample* of violations, not an
exhaustive list of every instance. Treating "the quoted examples" as "the
complete list of instances" is the same class of mistake as GAP 2 (a review
that quotes 2 examples is not proof there are only 2) — this is that same
lesson applied one level down, *within* a single criterion/section rather
than across criteria.

**Mandatory practice for every fix touching a staleness- or fabrication-class
defect, not only when a reviewer happens to quote multiple instances:**
identify the general *pattern* behind the flagged instance — not just the
specific cell or sentence — and mechanically sweep the entire affected
deliverable for every other occurrence of that same pattern before
considering the fix done:
- **Stale/inconsistent numeric claims**: don't stop at the one flagged
  mismatch. Grep every occurrence of the semantically-linked value across
  the *whole* workbook/document — every live cross-sheet formula reference
  **and** every hardcoded narrative mention of the same figure (a `$X,XXXK`,
  `X.XX%`, or `X.XXx`-style string) — and cross-check each one against its
  authoritative source (the correct cached/computed value) individually.
  A sweep that only re-runs the same mechanism that caught the original
  instance (e.g. only checking live formulas) will miss a same-value defect
  sitting in narrative prose, and vice versa — check both.
- **Fabricated/unsupported narrative claims**: this generalizes the
  existing "fact-check the whole surrounding section" rule below (task_28)
  — apply it every time, not only when a review happens to flag more than
  one sentence in the same paragraph. Re-read the *entire* surrounding
  section, and treat every other specific number, date, timeframe, rate, or
  named figure in it as an individual claim to verify against the actual
  permitted source files — one at a time — before considering the criterion
  closed, not just the sentence(s) a judge happened to cite this round.
- Before shipping, explicitly ask: *if I only fix what was quoted and stop,
  would a thorough adversarial reread of the whole document still find
  another instance of this exact same pattern?* If you haven't actually
  completed the sweep above, you cannot honestly answer "no" to that
  question — and "I fixed the cited example" is not the same claim as "I
  verified there are no more like it."
- Step 5's adversarial verify pass must independently perform this same
  pattern-sweep itself (not just confirm the cited instance is gone) — this
  is the single highest-leverage way to cut the number of oracle-run
  iterations needed before a task passes cleanly, since a fresh-eyes sweep
  now costs far less than another full round-trip through a real oracle run
  next.

## Step 2 — Plan a fix that resolves the defect without reducing difficulty

Only fix ambiguity, misalignment, leaked answers, or nondeterminism — never
remove genuine difficulty. Dense-but-parseable source language is difficulty,
not ambiguity; leave it alone. If a "fix" would make the task easier or more
solvable than intended, it's the wrong fix.

**Default to fixing the verifier (`verifier.json`/`judge.toml`/`reward.toml`)
over editing the golden.** These are plain text/JSON — safe to edit, easy to
diff. Golden output files (`.xlsx`/`.docx`) are the highest-risk edit
surface in this pipeline. Only edit a golden file when the defect is
factually IN the golden (a wrong number, an invented claim, a stale
reference) — a rubric being unfair or miscalibrated against a *correct*
golden is a verifier problem, even if patching the golden would also make
the symptom go away.

**Before rewording any criterion's LLM-judged prompt text as the fix, check
`docs/CLAUDE.md`'s "Mechanical-proxy checklist" first.** If the defect is
that a criterion can't reliably tell real content from absent/faked content
(a chart, a live formula vs. a typed-in number, visual structure, a
too-large sheet), a mechanical source-command check is very likely the
correct fix, not a cleverer wording of the same LLM-judged prompt — a
wording tweak on this class of defect is exactly the GAP 1 pattern (a
criterion edited 2+ times for brittleness that keeps failing) and the v17
chart-blindness fix earlier this session. Build or reuse a deterministic
source command instead of iterating on judge-facing prose when the
underlying gap is "the extraction never had access to the fact in the first
place."

**If any confirmed finding challenges the golden's factual/technical
correctness in a specialized domain** (clinical, legal, financial-
regulatory — anywhere getting it wrong has real-world safety/compliance
stakes) — **research the primary source before escalating, then escalate only
what the research leaves genuinely open.**

"Flag it for a human" is the right *terminal* state, but it is the wrong
*first* move: confirmed 2026-09-22, three tasks were escalated as "needs legal
input" and two of them resolved in minutes against authoritative primary text:

- task_LGL-135's jury-demand conflict dissolved once the two *different*
  subsections were read — Md. CJP § 4-402(d) is a $30,000 District Court
  jurisdictional ceiling, § 4-402(e) is a separate $25,000 jury-demand-removal
  threshold that only applies to actions filed in the District Court. The
  golden was right and the reviewer had conflated them.
- task_LGL-135's standalone implied-covenant count resolved the other way:
  *Mount Vernon Properties, LLC v. Branch Banking & Trust Co.*, 170 Md. App.
  457 (2006) holds Maryland recognizes no independent cause of action for it.
  The reviewer was right, and the fix was a bounded structural edit.

So: **pull the actual statute, regulation, or reported opinion** (not a
summary, not a memory of one), record the citation and the quoted controlling
text in `reports/<task>_DECISIONS.json`, and resolve the finding if the text
decides it. Escalate to a human when the research is genuinely ambiguous, when
the authorities conflict, or when the fix's scope cascades (next rule).

**Scope-cascade test — a correct narrow fix can still be the wrong edit.**
Before changing any load-bearing figure in a golden, enumerate what depends on
it: grep the deliverables for that figure and for every value derived from it,
and check whether it feeds a jurisdictional threshold, a forum choice, a count
structure, a damages total, or a downstream theory. Confirmed 2026-09-22
(task_LGL-140): 29 C.F.R. § 541.602(b)(1) and the employer's own handbook both
plainly permitted five of six salary deductions, so the golden's "no exception
authorized any of them" was simply wrong — but correcting it dropped the true
damages from $3,323.08 to $830.77, which put the case under Maryland's $30,000
District Court ceiling, invalidating the *forum*, the jury demand, and the
loss-of-exemption theory the pleading is built on. **If the fix changes forum,
jurisdiction, count structure, or the document's central theory, it is a
rewrite, not a fix — stop and report that**, rather than shipping a document
that is correct in the edited paragraph and incoherent everywhere else.

**GAP 3 — never dismiss a predicted risk with reasoning; test it against the
actual severity rule.** If you find yourself writing (or thinking) "this
will probably still fail for reason X, but that's a legitimate/unrelated
failure, not a defect" — stop, and explicitly answer the review's own
decisive test before deciding anything: *would a materially correct,
instruction-compliant submission be rejected by this criterion for reason
X?* If yes, that is a false rejection by definition, which the review's own
rules classify as **major**, regardless of how reasonable the criterion
*sounds* in isolation. "The instruction never mandated this specific
presentation/format/structure, so a correct submission that did it
differently shouldn't fail" is the single most common shape of this
mistake. Confirmed 2026-09-16 (task_28): a fix round predicted "2 of 3 real
submissions will likely still fail v18 for a legitimate, unrelated reason —
not a sign the fix failed," and the next real review panel correctly called
this a textbook brittle-criterion false rejection. Predicting a symptom is
not the same as clearing it — a predicted-and-dismissed risk must still get
a disposition of fixed/genuinely-not-a-defect-per-the-severity-rule, never
just "predicted, so it's fine."

## Step 3 — Apply the fix

Work on a copy, never the original bundle. **Before editing anything, snapshot
it** (`verifier.json.round1`, `verifier.json.round2`, etc., alongside the
original) — without this, a later verify pass can't tell "did this round
touch something a prior round already fixed" from "did this round regress
it," since it has nothing to diff against but the original pre-any-fix
download.

**If you're touching a golden `.xlsx`, for any reason — including a
single-cell text/citation fix that looks purely cosmetic — stop and read
[`safe-xlsx-golden-edit`](../safe-xlsx-golden-edit/SKILL.md) first.** A
plain `openpyxl` load-and-save on a workbook silently strips its cached
formula values even when the edit itself is trivial; this has caused a real,
serious regression in this corpus (a "quick cleanup" pass once stripped 63%
of a workbook's cached cells, which would have failed the Oracle's own
golden on ~77% of the rubric's weight). `.docx`/JSON/TOML edits don't carry
this risk.

**When fixing an unsupported/incorrect claim inside a golden's narrative
prose (a memo's analysis section, a "Key Sensitivities" paragraph, a
reasoning doc), fact-check the whole surrounding section against source and
against the model's own numbers — not just the one sentence a review
flagged.** Confirmed 2026-09-16 (task_28): two separate rounds each fixed
one flagged sentence in the same "Key Sensitivities" paragraph block, and
each time left *other* unsupported claims in the same block untouched (a
wrong-direction sensitivity claim, a mis-stated dollar-per-point figure, and
a fabricated benchmarking source were three distinct defects in one
paragraph, found only when someone finally read the whole section fresh).
An edit scoped to exactly the flagged sentence is a strong signal to widen
the read, not proof the surrounding prose is clean. See **GAP 4** above (end
of Step 1) for the mandatory, generalized version of this rule — it applies
to every staleness/fabrication-class fix, not only narrative prose, and is
not optional even when the current review only quoted one instance.

**Always establish your baseline from the actual most-recently-shipped zip,
never a loose `task_files/` directory on disk, even one that looks right.**
A loose directory can silently diverge from what was actually zipped and
shipped in a prior round. If they differ, the zip is authoritative — always.
Confirmed failure mode: a fix agent once diffed against a stale loose
directory, never noticed, and shipped a fix that silently deleted two
unrelated criteria and reverted five others — a worse regression than the
single defect it was sent to fix.

## Step 4 — Harness-execution gate (mandatory, not optional)

A fix can be textually and logically sound — every finding independently
re-derived, no scope creep — and still be broken, because logical review
never executes anything. This step is not satisfied by "solve.sh runs
locally" alone.

1. Actually execute the task's own grading path against the fixed golden —
   `test.sh` (native-harbor) or the rewardkit runner (rewardkit-hybrid).
2. Confirm it produces a `reward.txt`/`reward.json` at all — a missing
   reward file means the verifier itself crashed, not that the score was
   low.
3. **Explicitly confirm the golden actually PASSES its own fixed verifier —
   not merely that the harness ran without crashing.** These are different
   claims.
   - If a real judge call is available (a live re-upload, or local
     credentials): confirm the fixed golden's real reward is at or near
     1.0 (or the pre-fix baseline) on every criterion you touched, not just
     in aggregate.
   - If no live judge call is available locally (the common case): say so
     explicitly, then read each touched criterion's new prompt text against
     the actual final golden content and reason through, criterion by
     criterion, whether a reasonable judge would score it pass. Report
     which criteria you could confirm this way and which remain genuinely
     unconfirmed pending a real re-upload — don't round "I reasoned through
     it" up to "confirmed passing."
   - A real re-upload can still reject a fix even when the golden now
     passes cleanly, because *other*, untouched criteria still false-reject
     compliant model runs. Passing-golden and accept-verdict are different
     bars — confirm both.
4. If rewardkit-hybrid genre: never re-zip a raw `task_files/` download
   as-is — `environment/initial_workspace/` must exist in what you ship,
   built via the conversion step
   ([`harbor-rewardkit-convert`](../harbor-rewardkit-convert/SKILL.md)).
   Shipping without it produces a Daytona sandbox-creation failure before
   the container even starts.
5. If this step can't be run at all, say so explicitly — "not
   harness-verified" is a materially different claim than "verified."
5b. **Run the whole check registry, not just the named gates (added
   2026-09-22).**

       pipeline/.venv/bin/python deterministic-checks/run_all.py \
         --root <parent dir holding task_<id>/> --out-dir <workdir>/checks

   `deterministic-checks/` holds ~90 checks. Before this rule the skill named
   three, and a 30-task session ran only those three — so defects that a
   purpose-built check already covered shipped anyway. The registry is the
   default; the named gates below are the ones that additionally *block*.

   **A `skip` or `not_applicable` is not a pass.** Treat every one as an open
   item until you have read why: a check that could not evaluate the package
   is telling you it does not understand the package, which is exactly how
   task_LGL-168 shipped with drifted `verifier-requirements.txt`, failed its
   dependency install, and scored reward 0.0 on every run — the two checks
   built for that defect both reported "skip"/"pass" because they only
   recognised `tests/__verifier_lib/` and the task ships the single-underscore
   `tests/verifier_lib/` (28 of 79 shipped tasks use that spelling).
6. **Platform rubric gate (added 2026-09-18).** Run
   `pipeline/.venv/bin/python deterministic-checks/harbor_rubric_gate.py --root <package>`
   and clear every `fail`. The platform's own QC reviewer grades the
   15-check Harbor rubric (`docs/harbor-task-rubric.md`), and 12/12 EKW
   tasks failed it on 2026-09-16 *after* passing our own review. The gate
   covers: instruction form (no persona opener, absolute input and
   deliverable paths, canary), `solution/golden_outputs/` holding only
   graded files, a schema block for structured deliverables, ≥1
   deterministic assertion + formula source on formula-driven goldens,
   judge `<data>` guard, and the criterion trace
   (`reports/<task>_TRACE.json` — one `anchor` per criterion, plus
   `uncovered_requirements`). Fixing the instruction is in scope for this
   step: use the template in `docs/harbor-task-rubric.md`, keep every
   constraint, remove every method statement, then re-run the §1.6 leak
   sweep because a schema block must not state a graded value.
7. **Reward-signal gate (added 2026-09-18, the expert-review bar).** Run
   `pipeline/.venv/bin/python deterministic-checks/reward_signal_gate.py --root <package> [--evidence <with_runs>]`
   and clear every `fail`. It encodes the six mechanisms the expert
   reward-signal review of QCR_EKW_16092026 found on 12/12 tasks (see
   `dataos_qc_runs/74-ekw-sprint/feedback_16092026/_expert/EXPERT_FEEDBACK_GAP_ANALYSIS.md`):
   G1 a fidelity/consistency/status/cross-document criterion the judge
   cannot decide from its single source file (re-source via
   `filesystem.extract_many` over deliverable + the named source, or narrow
   the prompt); G2 a required phrase/label/ID the instruction never asked
   for; G3 an exact or cents-level numeric pin, or the same figure pinned in
   two criteria; G4 a FAIL clause that forbids what the instruction requires,
   a source contains, or a sibling PASS rewards; G5 the same fact graded
   twice; G6 the package library cannot recalculate uncached formulas (resync
   `sources/xlsx.py` from the template — a correct openpyxl-written model
   otherwise extracts blank and loses most of its weight); G7 compound
   criteria; G8 the decision ledger + false-accept sweep
   (`reports/<task>_DECISIONS.json`); G9 fewer than three judge samples
   (`config.models` lists the judge model three times). Every G1–G5/G7
   candidate needs a disposition in `reports/<task>_TRACE.json`
   (`split` / `widened` / `re-sourced` / `tolerance-added` / `removed` /
   `not-a-defect:<reason>` / `domain-decision:<who>`). "Edited" is not
   "fixed": the disposition must name how the mechanism can no longer recur.
   **Sweep every criterion for each mechanism, not the first instance**: the
   gate's candidate list is a floor, not the population — a fixer (and the
   Step 5 verifier) must fill a criterion × mechanism matrix (see review doc
   §1b; `review_matrix_check.py` enforces it on the verifier's output).

## Step 5 — Adversarial verify (fresh context, not the fixer grading itself)

Have a **separate, fresh-context pass** (a new subagent, or explicitly
re-derive from scratch yourself, not from memory of the fix you just wrote)
independently re-check the fix:

> **Operational rule (added 2026-09-22): run Steps 5 and 6 synchronously,
> inside your own turn.** If you are a per-task fixer, do not dispatch Step 5
> or Step 6 to a background agent and then wait on it. Confirmed across a
> 30-task session: multiple fixers spawned nested "Step 6 comprehensive
> review" sub-agents, returned **"still waiting on the review"** as if it were
> a completed result, and had to be killed and finished by hand — three
> separate times on one task, while the nested agents kept respawning. A fix
> is not done until its verdict is in your hands. **"Waiting on a background
> job" is never a terminal state, and never a completion report.**

- For each originally-confirmed finding: independently re-derive whether the
  fixed files actually resolve it — don't just check that *something*
  changed near the flagged spot.
- **Mandatory pattern sweep (GAP 4):** for every finding that was a stale/
  inconsistent value or a fabricated/unsupported narrative claim, do not
  stop at re-checking the cited instance. Independently sweep the *entire*
  affected deliverable for other occurrences of the exact same pattern —
  every cross-sheet formula reference *and* every hardcoded narrative
  mention of the same figure for staleness; every other specific number,
  date, rate, or named claim in the *whole* surrounding section for
  fabrication — and verify each one against its actual source yourself.
  Confirmed 2026-09-17 (task_61, task_57): a fix that fully resolved the
  cited instance still shipped with a second, unflagged instance of the
  identical defect pattern elsewhere in the same document, caught only by
  the next real oracle run. Catching that here is strictly cheaper than
  catching it there — this sweep is what actually reduces the number of
  oracle-run iterations a task needs before it ships clean, which is the
  point of this whole step.
- Separately check whether the fix **reduced difficulty**: added
  scaffolding/hints, resolved ambiguity by picking the answer for the solver
  instead of specifying the missing convention, simplified a computation, or
  turned a genuinely open judgment call into a spoon-fed one. A difficulty
  regression is a failure even if the original finding is technically
  resolved.
- Apply the same proactive-defect-class checklist from Step 1 to criteria
  the fix did *not* touch, not just the ones it changed.
- Verdict per finding: `resolved` / `not_resolved` / `resolved_but_eased`.
- If touching an xlsx, independently re-run the
  [`safe-xlsx-golden-edit`](../safe-xlsx-golden-edit/SKILL.md) before/after
  cached-cell check yourself — don't trust the fixer's own run of it.

**If every finding is `resolved` and the harness gate passes**: proceed to
Step 6. **If anything is `not_resolved`/`resolved_but_eased`, or the harness
run fails**: discard the candidate, and re-fix with the verify pass's
specific feedback quoted verbatim (not paraphrased) plus an explicit
instruction not to repeat that exact failure mode. **Cap retries at 2** (3
total fix attempts) — if it still doesn't pass, stop looping and report
`needs_human_review` with the full attempt history, rather than shipping an
unverified fix or looping forever.

## Step 6 — Comprehensive Review gate (final formal check)

Once the fix passes adversarial verify, run the actual Comprehensive Review
prompt against it — the same prompt Data-OS's real reviewers use, at
`docs/ekw-svc-comprehensive-review.md` in this repo. This is a different,
more exhaustive check than Step 5: it works through all 10 checks (
solvability, reproducibility, ambiguity, instruction↔rubric alignment,
rubric coverage/calibration, answer exposure, source consistency,
packaging/errored-runs, metadata, other issues) and emits a formal
`accept`/`reject`/`invalid`/`needs_revision` verdict with major/minor
severity per check.

**GAP 2 — this gate must independently re-audit EVERY criterion and every
golden section fresh, every time, not just the ones this round touched.**
Confirmed 2026-09-16 (task_48): a dedicated gate pass on a round that
touched 2 criteria came back "needs_revision, minors only" — and the very
next real review panel found two different, previously-untouched criteria
with major, judge-exploitable brittleness (one of which the golden itself
also fails, proving it wasn't a one-off harsh read). Those two criteria had
sat unexamined since round 1 across multiple "clean" local gate passes,
because each pass's attention followed that round's diff instead of the
full rubric. Concretely, before returning a verdict from this step:
- Confirm you (or the subagent running this gate) read and evaluated **every
  criterion in the current `verifier.json`/`judge.toml`**, not only the ones
  the round's diff touched — the prompt's own §1.5 already asks you to try
  constructing an exploit/brittle-case for each criterion; do not skip this
  for criteria that "should already be vetted from a prior round." A prior
  round's silence on a criterion is not evidence it's sound.
- For any criterion with prose/format-sensitive language (a required list
  structure, "standalone," "explicitly states," a specific section layout),
  actively try to construct one *differently-formatted but factually
  correct* submission the wording could plausibly reject — this is the
  single defect class most likely to survive a diff-scoped review.
- Run the same "does the golden itself pass" check on the *whole* rubric,
  not just criteria the current round's fix touched — a criterion the
  golden itself fails is definitionally a major (§4's own rule), and it
  will not surface from a diff-scoped read.
- If the task has an xlsx-graded criterion, run the adversarial
  verifier-soundness probe: strip every formula in a scratch copy of the
  golden workbook, replace each with its own last cached constant, re-run
  extraction, and check whether the score changes. If it doesn't, the
  verifier is blind to whether the deliverable is a live model or a
  hardcoded answer sheet — a real, corpus-level soundness gap (`data_only=
  True` extraction cannot itself distinguish these) that's worth flagging
  even though it isn't fixable at the single-task level; note it in your
  report as an escalation rather than silently passing the check. (This
  specific gap now has a real fix available — see `docs/CLAUDE.md`'s
  "Mechanical-proxy checklist" and `xlsx.formula_summary` / `xlsx.formula_authenticity_scan` —
  consider recommending that fix rather than only logging the escalation.)

Two skills it references (`workspace-layout`, `exception-diagnosis`) don't
exist in this repo — note that explicitly in the review and mark any
dependent finding `inconclusive` rather than guessing at their intent.

- **`accept`**: ship.
- **`needs_revision` (minors only) or `reject`/`invalid` (a major)**: treat
  every confirmed finding like a Step 5 `not_resolved` — do not ship, fix,
  and re-run Steps 4-6. Trivial, zero-risk minors (a stray backup file, a
  one-cell text correction not touching an xlsx's formula cache) can be
  fixed directly without a full new subagent round; anything touching an
  xlsx or a rubric criterion still goes through the full gate.
- Real-world evidence beats local reasoning: if a genuinely unexploited,
  zero-scoring-impact minor survives after several rounds of real-upload-
  driven fixes on the same task, it's reasonable to log it as a deferred
  follow-up rather than chase another iteration — see the "protect
  difficulty" and diminishing-returns judgment call in the project's own
  history for when this applies. Don't use this as an excuse to skip the
  gate on a fresh fix, only to avoid infinite polishing of an
  already-working task.

## Step 7 — Rebundle and hand off

**GAP 5 — the bundle you package for upload must be diffed against the fix
round that actually fixed it, not assumed to be current.** Confirmed
2026-09-17 (task_49): a real fix (a new `v17b` criterion using
a chart source command — template: `xlsx.has_chart` — closing a confirmed chart-blindness gap) was
built and validated correctly in a `refix_v2/` working round, but the bundle
that actually got zipped and submitted as `task_49_fixed` silently reverted
to an older, stale copy of `verifier.json`/`xlsx.py` that never had the fix
— and the next real Comprehensive Review re-confirmed the exact same
chart-blindness defect as a live major, because what shipped wasn't what got
fixed. Before zipping, `diff` every file you're about to package against the
most recent working round that actually applied the fix (`refix_vN/`,
`rev_N/`, whichever this task uses) — a silent revert to an older round is
not something a human reviewer of the final zip can catch by inspection
alone, since the stale version still looks complete and plausible on its
own. If the diff shows anything other than exactly the intended fix, stop
and find out why before shipping.

The upload format is the reward-kit layout, not the "with runs" download
shape — check whether the source is already reward-kit-shaped
(`tests/deliverables/judge.toml`) or old-format harbor (`tests/verifier.json`)
and convert if needed before zipping (see
[`harbor-rewardkit-convert`](../harbor-rewardkit-convert/SKILL.md)).

**Then gate the built archive, not the working directory (added 2026-09-22):**

    pipeline/.venv/bin/python deterministic-checks/package_shape_check.py \
      --root <dir holding the built zips> --against <the working round that produced them>

This mechanizes GAP 5 and the packaging rules above. It is not optional
polish: in a 30-task session, **13 of 30 built zips were malformed** and every
one was caught by hand afterwards — 11 shipped without the
`reports/<task>_{TRACE,DECISIONS}.json` ledger *inside* the package (so
`reward_signal_gate.py`'s G8 failed on re-verification even though the fixer
had built the ledger), one shipped with no wrapper folder at all (its files
collided with every sibling when the batch was unpacked together), and two
shipped with a `task_files/` root instead of `task_<id>/`. Always run it
against the actual archive you are about to hand over.

Report, per finding: confirmed or rejected (with reason), fix applied (or
"no fix needed, false positive"), and the path to the final zip ready for
upload. Write this for a human deciding whether to re-upload, not as an
internal log — state plainly what's confirmed vs. reasoned-through, and
name anything still pending a real re-upload to fully confirm.

## Never ship a task whose container cannot build (added 2026-09-21)

Before calling any task fixed, run:

    deterministic-checks/container_build_check.py --root <batch>/packages --task <task_id>

`environment/Dockerfile` and `environment/verifier-requirements.txt` are REQUIRED. A 26-task delivery
errored at DataOS with neither, having passed all seven ship-gate checks — every one of which grades the
rubric, none of which asked whether the sandbox could be built. If you edit `environment/`, re-run this
check. Do not strip `libreoffice` or `VERIFIER_VENV_DIR` from the Dockerfile: both are grading-relevant
(see `skills/ekw/ekw-to-dataos-harbor/SKILL.md`).
