---
name: tp-fp-gate-mining
description: >-
  Distill a just-concluded TP/FP adjudication round's confirmed
  `task_author` defects into reusable, high-precision LLM gates that can
  screen the *next* round's tasks before a full manual adjudication —
  the follow-on step to the `tp-fp-classification` skill. Reads a
  round's per-task `_qc_validation.xlsx` files (or the batch summary),
  clusters recurring `content_substance` / `design_intent` /
  `format_convention` patterns across tasks, checks each candidate
  against the existing gates file for overlap, and only promotes a
  pattern to a new gate when it can be checked against a strict,
  quotable evidence policy — deliberately rejecting patterns that would
  need a subjective severity call, since a noisy gate is worse than no
  gate. Never mines `pipeline_engineer` or `grading_reliability` rows
  (see `tp-fp-classification`'s Fix Owner field) into gates — those
  are tooling/model-reliability bugs, not rubric-text patterns a gate
  can scan for. Use once a TP/FP round's output exists and before the
  next batch's DataOS automated judge results come in, so the
  accumulated gates can pre-screen that batch.
---

# TP/FP Gate Mining (the follow-on step to the TP/FP skill)

This is the step that closes the loop after a `tp-fp-classification` round:
turn *confirmed, recurring* rubric-authoring defects into standing checks
that catch the same pattern automatically on future batches, instead of
re-discovering it by hand every round. The existing gates this project has
already produced from one earlier round live in
`automation/tp-fp-classification/batch-scan-gates.md` — read that file in
full before starting anything here. It is not a template to imitate loosely;
it is the actual schema and precision bar this skill has to match.

The backticked terms below (`Fix Owner`, `task_author`, `Auto-Verdict`,
`true_positive`, `dataos_automated`) are columns and values defined in
`automation/tp-fp-classification/SKILL.md`.

Paste this whole file as your first message in a fresh Claude Code session,
along with the concluded TP/FP round's outputs, to kick off a gate-mining
pass. It is self-contained — the new session has no memory of the
adjudication round that produced the inputs.

## When this runs

After a `tp-fp-classification` round has produced its per-task
`<task_id>_qc_validation.xlsx` files and batch summary (see that skill's
"Also produce: one batch-level summary" section). Run gate mining once per
concluded round, before the next batch's `dataos_automated` results arrive
— the point is for the accumulated gates to pre-screen the *next* round,
not to re-analyze the round that just finished.

## Inputs you'll be given

- The concluded round's per-task `_qc_validation.xlsx` files (or the batch
  summary that indexes them) — specifically every row where
  **`Auto-Verdict: true_positive`** and **`Fix Owner: task_author`**.
  Nothing else in this workflow. `pipeline_engineer` and
  `grading_reliability` rows are out of scope entirely (see "Why Fix Owner
  matters here" below) — do not read them looking for patterns, they will
  not produce a usable gate no matter how it's phrased.
- The current `automation/tp-fp-classification/batch-scan-gates.md` (or
  whatever gates file supersedes it) — the standing set of gates already
  in production. You are extending this file, not starting from scratch.
- If available, this round's gate-hit results from the *previous* round's
  gates (which findings a standing gate correctly flagged, which it
  missed, which it flagged that turned out `false_positive` on manual
  adjudication) — this tells you which existing gates need tightening
  before you go looking for new ones.

## Why Fix Owner matters here

A gate is a standing instruction to an LLM judge: "read this rubric text
and this prompt text, and tell me if this specific pattern is present."
That only works when the defect *is* a pattern in how rubric/prompt text
was written — something a fresh reader with no other context could spot by
comparing quotes. `pipeline_engineer` rows (a broken hydration script,
mis-set reward weights) and `grading_reliability` rows (a specific model
run misapplied an already-correct rule) are not rubric-text patterns —
there is nothing in the rubric or prompt wording for a gate to notice,
because the wording was fine. Mining those into a gate produces a check
that can never fire correctly: either it never triggers (there's no
textual signal to key off), or it triggers on the wrong thing because
you've forced a "does the text look like X" heuristic onto a problem that
was never about the text. Screen every candidate on Fix Owner before
spending time on it.

## Methodology

1. **Pull the candidate pool.** Collect every `task_author` +
   `true_positive` row across the round's task files. For each, note
   `Defect Class`, the one-sentence `Issue Description`, and the
   `Evidence Reference` (path) — you'll need to re-open the actual files
   to generalize the pattern, the row's own text is a pointer, not a
   substitute.
2. **Cluster by pattern shape, not by task.** Group candidates where the
   *underlying mechanism* repeats, independent of the specific numbers,
   domain, or task ID: "a criterion hardcodes one exact answer to a
   decision another criterion calls open" is one shape whether it shows up
   in a fabric-cut plan or a bond valuation. Re-read each cluster member's
   actual rubric/prompt text side by side — a shared `Defect Class` tag
   alone isn't proof of a shared mechanism; `content_substance` covers a
   lot of unrelated failure modes.
3. **Require recurrence before promoting a cluster.** A pattern that
   showed up on exactly one task this round is not yet gate-worthy — it
   might be a genuine one-off (a specific author's specific mistake, not
   a systemic authoring gap). Default threshold: **at least 2-3
   independent tasks**, ideally from different authors/domains, before
   treating it as a standing pattern rather than an anecdote. Keep a
   running list of singleton candidates across rounds — a pattern that
   was a singleton last round and shows up again this round has now met
   the bar; don't discard the memory of near-misses.
4. **Check for overlap with existing gates before drafting anything.**
   Read every gate already in the file (six as of this writing — see
   `batch-scan-gates.md`) and ask, for each cluster: does an existing
   gate's `dimension_name`/description already cover this mechanism? If
   yes, this cluster is corroborating evidence for that gate, not a new
   one — log it in the gate's own "confirmed on" history (add a short
   changelog note; see Output below) rather than duplicating the gate
   under a new name with slightly different wording. Two gates that
   overlap by 80% will disagree with each other on the 20% edge cases and
   erode trust in both.
5. **Apply the precision bar before writing a new gate — this is the
   step most likely to be skipped under time pressure, and skipping it is
   the single fastest way to make this whole exercise counterproductive.**
   For each surviving cluster, ask:
   - **Can I write an evidence policy that requires verbatim quotes, not
     a judgment call?** Every existing gate's Evidence Policy demands 2-3
     specific quotes (the criterion text, the prompt's competing/broader
     text, and often a source or golden excerpt) — if satisfying that
     evidence policy would still leave room for "well, it depends how you
     read it," the pattern isn't ready to be a gate. Reference the two
     patterns `batch-scan-gates.md` explicitly rejected for this exact
     reason (the "criterion names control figures but its FAIL clause
     doesn't require them" pattern, and "required document structure is
     never checked") — both were real, confirmed defects, both got left
     to manual review anyway, because "how loose is too loose" has no
     quotable evidence policy.
   - **Does the pattern generalize across domains, or is it actually
     domain-specific?** "A criterion demands a technical convention the
     golden happens to use but the prompt never states" generalizes.
     "Finance workbooks in this batch tend to omit a required-return
     disclosure" does not generalize past finance tasks — it might still
     be worth a narrower, domain-scoped gate (`applies_when` can key off
     task category), but say so explicitly rather than writing a gate
     that silently never fires outside its origin domain.
   - **Would a false hit on this gate be embarrassing or just a wasted
     minute?** A `reject_at_severity: 2`/`role: blocking` gate that fires
     incorrectly blocks a clean task from advancing — calibrate severity
     rubrics conservatively (see every existing gate's Severity 0-3
     ladder) and bias toward under-flagging (severity 1, "advisory") over
     a confident-sounding false blocking verdict.
6. **Write the gate in the existing schema, verbatim structure.** Every
   gate in `batch-scan-gates.md` has, in this order: a `yaml` header
   (`dimension_name`, `check_kind: llm`, `inputs`, `applies_when`,
   `gate.role`/`reject_at_severity`); a **Guidance (paste into tool,
   ≤5,000 chars)** block — the compressed, self-contained version for the
   tool's actual pass/fail/not_applicable field; then reference-only prose
   (**What this evaluates**, **How to judge**, **Severity rubric**, **Do
   not flag**, **Evidence policy**) that a human reads to understand the
   gate but never pastes into a tool. Match this shape exactly — the
   Subtask prompt template at the end of `batch-scan-gates.md` assumes
   every gate has this structure and is not gate-specific; a gate that
   doesn't fit it breaks that template for no reason.
7. **State explicitly what you rejected and why**, the same way
   `batch-scan-gates.md`'s own intro does ("Deliberately not included:
   ..."). A reader auditing this round's gate-mining pass should be able
   to see every candidate pattern that was considered and either promoted
   or explicitly left to manual review, not just the ones that made the
   cut.

## Output: an updated gates file, with a changelog

Update `automation/tp-fp-classification/batch-scan-gates.md` in place
(or its successor if it has been renamed/versioned — gates accumulate
across rounds, this file should not be treated as belonging to one
specific batch going forward). At the top of the file, above the existing
gate list, maintain a running changelog:

```markdown
## Changelog

- **<round date/batch id>**: added Gate 7 (`<dimension_name>`) — <one
  sentence, the pattern it catches>. Confirmed on <N> tasks this round
  (<task ids>).
- **<round date/batch id>**: Gate 4 confirmed again on <task ids> — no
  wording change needed.
- **<round date/batch id>**: considered a gate for "<pattern>" (seen on
  <task ids>) — rejected, no quotable evidence policy possible (see
  Methodology step 5). Left to manual review.
- **<round date/batch id>**: Gate 2 retired/narrowed — <N> of its last
  <M> hits were overturned as `false_positive` on manual review; <what
  changed in the guidance, or why it was removed>.
```

Then append any newly-promoted gates after the existing ones, numbered
sequentially, using the exact schema from Methodology step 6.

## Also produce: a pre-screen manifest for the next round

Alongside the updated gates file, write a short manifest naming which
gates apply to which task categories this round's `applies_when` clauses
target (e.g. `task_has_verifier`, `task_has_closed_world_instruction`,
`task_has_golden_and_oracle_run`) — this is what the next
`tp-fp-classification` round (or a lightweight pre-screen pass before it)
dispatches against each new task's bundle. Running every gate against
every task regardless of `applies_when` wastes calls on gates that will
always return `not_applicable`.

## Feeding gate hits back into the next TP/FP round

A gate hit is a **candidate**, not a verdict. When the next round's
pre-screen produces a gate finding (`applicable: true`, `severity >= 2`),
hand it to `tp-fp-classification`'s Methodology as a lead — it still goes
through the full verification steps (read the actual rubric/prompt text,
check the golden, check the oracle run, check the real submitted
deliverable) before becoming a row in that task's `_qc_validation.xlsx`.
The gate's own `evidence_quotes` are a head start on Methodology step 2,
not a substitute for it — a gate can still be wrong on a specific task
even when its underlying pattern is real (see "Do not flag" sections on
every existing gate; they exist because generalized patterns have
exceptions). After the round concludes, feed the outcome back:
- Gate hit confirmed `true_positive` on manual review → log it in the
  gate's changelog entry as corroborating evidence, no gate change needed.
- Gate hit turned out `false_positive` → this is the input to Methodology
  step 5's precision check, run retroactively on a live gate: does the
  gate's evidence policy need tightening (an extra required quote, a
  narrower `applies_when`), or was this a one-off misapplication by the
  scanning agent that doesn't indict the gate itself? Only the former
  justifies editing the gate.
- A real defect the gates *missed entirely* (found only through full
  manual adjudication) → this is new gate-mining raw material for the
  next pass, same as any other round's `task_author` true_positive rows.

## Practical notes

- **One subtask per (task, gate) pair, not one subtask per task covering
  every gate** — this is already `batch-scan-gates.md`'s own convention
  (see its Subtask prompt template) and it holds for gate-mining's own
  execution too: when checking a candidate pattern against multiple tasks
  for recurrence (Methodology step 3), or when running the pre-screen
  manifest against a new batch, dispatch narrowly-scoped, isolated
  subtasks in parallel rather than one agent trying to hold every gate
  and every task in context at once — narrow scope is what keeps a gate's
  evidence policy enforceable; a subtask juggling six gates at once will
  drift toward vaguer, unquoted findings.
- **A gate's `applies_when` is doing real work — don't leave it as
  `task_has_verifier` by default.** Every existing gate scopes itself
  tightly (`task_has_closed_world_instruction` for Gate 3,
  `task_has_golden_and_oracle_run` for Gate 5) specifically so it doesn't
  waste calls, or worse, force a strained finding, on tasks where the
  underlying question doesn't even apply. Pick the narrowest
  `applies_when` that's still correct for a new gate, not the broadest
  one that technically includes every candidate task you happened to see
  the pattern on.
- **Don't let the changelog become the only record of a rejected
  pattern.** If the same rejected-as-too-subjective pattern (Methodology
  step 5) shows up on enough tasks across enough rounds, that's a signal
  the underlying authoring process needs a template/checklist fix
  upstream of both TP/FP adjudication and gate mining — not that the
  precision bar for gates should be lowered to let it through. Escalate
  that distinction explicitly rather than quietly relaxing an evidence
  policy to catch it.

## Reference

The gate schema, the six existing gates, and the Subtask prompt template
this skill's output must match live in
`automation/tp-fp-classification/batch-scan-gates.md`. The adjudication
methodology and output schema (including the `Fix Owner` field this skill
filters on) that produces this skill's inputs live in
`automation/tp-fp-classification/SKILL.md`.
