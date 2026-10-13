# QC Foundation — shared grading protocol, verdict computation, output format

Front-agnostic machinery shared by every single-agent QC skill (EKW's
`gdpval-task-qc*` family and SVC's `svc-task-qc`). None of this mentions a
specific task-directory layout, dimension set, or checker script — each
front's own `SKILL.md` supplies those specifics and points here for
everything else, so a fix made here benefits every front without a
copy-paste re-sync.

**You are the judge.** You read the task's files directly and grade each
dimension yourself, applying the policies below. There is no second model
and no network call.

---

## Grading protocol

Grade **every** dimension listed in the active stage file. Each dimension
produces exactly one **finding** with this shape:

```json
{
  "dimension":      "instruction_authenticity",
  "severity":       0,
  "confidence":     "low | medium | high",
  "applicable":     true,
  "evidence_quote": "verbatim passage from the inputs, or null",
  "headline":       "one sentence (<= 25 words), sample-specific",
  "justification":  "1-3 sentences of reasoning, referencing the evidence",
  "fixability":     "trivial | fixable | structural | n/a"
}
```

Per-dimension rules:

- **severity** — integer 0-3, anchored to the dimension's own severity rubric.
- **applicable** — `false` only when the dimension's `applies_when` precondition
  is not met (e.g. a chart dimension on a chart-free solution). When `false`,
  set `severity=0`, `evidence_quote=null`, `fixability="n/a"`.
- **fixability** — `trivial` (one-line edit), `fixable` (rewrite one
  section/file), `structural` (the sample must be redone or different inputs
  supplied), `n/a` (severity 0).
- When the rubric is ambiguous between two levels, **default to the lower
  severity.** Real professional artifacts are often dryly written and
  structured — structure alone is not a defect.

**Programmatic dimensions.** Most dimensions are LLM-graded (you are the
judge). Each front designates some dimensions as **deterministic**: produce
their findings by running that front's checker script rather than judging by
hand (see the front's own `SKILL.md` for which dimensions and which script).
Deterministic findings use the same finding shape (always `confidence: high`,
`evidence_quote: null`) and fold into the verdict identically.

### Severity scale (global)

| Sev | Meaning |
|---|---|
| 0 | no issue or fully meets criterion |
| 1 | minor concern; does not affect usability of the sample |
| 2 | material concern; sample is usable only after a fix |
| 3 | severe failure; sample cannot be made usable by a fix |

### Evidence policy (the principal anti-overcall guard)

Any finding with **severity ≥ 1 MUST include a verbatim `evidence_quote`** — a
short passage (≈ ≤ 30 words) copied **exactly** (not paraphrased) from the
inputs. **If you cannot quote concrete evidence, set severity to 0.** This rule
is absolute; a sev-≥1 finding without a real quote is invalid and must be
demoted to 0.

### Confidence policy

Assign `confidence` to every finding, then apply demotion:

- **low confidence at severity 1 → demote the finding to severity 0.**
- **low confidence at severity ≥ 2 → keep the severity but flag the task for
  `needs_review`** (do not auto-act on it).

### Single-judge uncertainty rule (replaces multi-judge disagreement)

The batch framework runs two judges and routes a task to `needs_review` when
they disagree by **more than one** severity level (a ≥ 2-level gap — a 1-level
gap counts as agreement) on a **blocking** dimension. As the sole
judge, reproduce that safety valve with honest self-assessment: when you are
**genuinely torn** between two severity levels on a blocking dimension — you
could credibly argue either — mark that finding **uncertain** and route the
task to `needs_review` instead of auto-rejecting on the worse reading.

### Eval-context conventions (do NOT penalise these)

This corpus is an **evaluation dataset**, not in-the-wild work. Several patterns
that would be unusual in a forwarded email are normal eval setup and **must not**
be treated as synthetic/constructed markers. Apply this to every dimension,
especially the authenticity and fit dimensions:

- **Persona / role assignment** — "You are a senior credit analyst at …",
  "Acting as the portfolio manager, …". Sets context; not LLM framing.
- **Output file specifications** — "save your memo as `/workspace/output/memo.docx`",
  "produce a `.xlsx` with sheets named …". The verifier needs to know where to
  look; naming the deliverable / format / location is not "pre-specifying
  structure" in the synthetic sense.
- **Required deliverable list** — "produce two files: a memo and a model" is
  fine, even when enumerated. The synthetic version is an instruction whose
  enumerated requirements read as a verifier rubric copied verbatim.
- **Length / scope cues** — "a one-page memo", "a ~500-word summary" are normal.
  Only flag benchmark-arbitrary limits ("exactly 3 bullet points", "exactly
  200 words").
- **Capability framing** — eval tasks are *designed* to exercise capabilities;
  that is what an eval is. Only flag tasks whose stakes/domain are so paper-thin
  they couldn't represent any real delegated work.
- **Acceptance criteria in the instruction** — real briefs sometimes include
  "the deliverable must address …" lists. Fine.
- **Anonymisation** — redacted/anonymised real documents may carry
  generic-sounding names without being fabricated.

Err toward "the eval needed this" rather than "this is synthetic" when a pattern
could plausibly fall in either bucket.

### Hard-fail patterns are guidance, not auto-bumps

Each dimension lists "Common hard-fail patterns". These are diagnostic guidance,
**not** automatic severity jumps. When a pattern is clearly present, quote the
evidence and decide severity *in context*. A pattern that is borderline,
ambiguous, or has a plausible benign explanation should not be flagged.

---

## Verdict computation

After all findings are in, compute one **verdict** for the task. Only
`applicable` findings count. Each dimension carries a **gate role** (`blocking`,
`advisory`, `informational`) and a **`reject_at_severity`** threshold (default
`3`; some structural dimensions use `2` — see the front's dimension files).
Apply the tiers **in this priority order — first match wins**:

1. **needs_review** — any *blocking* dimension you marked **uncertain** (the
   single-judge rule above). Reason: "uncertainty on blocking dim '<name>'".
2. **needs_review** — any finding with **low confidence at severity ≥ 2**.
   Reason: "low-confidence finding at severity N on dim '<name>'".
3. **reject_structural** — any blocking dimension at `severity ≥ reject_at_severity`
   with `fixability = structural`.
4. **reject_fixable** — any blocking dimension at `severity ≥ reject_at_severity`
   with `fixability ≠ structural`.
5. **needs_review** — borderline: a blocking dimension landing **exactly at
   `reject_at_severity − 1`** (and severity ≥ 1).
6. **accept_with_fixes** — any blocking-or-advisory dimension at severity ≥ 1
   (informational findings do not count here).
7. **accept** — no applicable non-informational findings at severity ≥ 1.

`needs_review` (tiers 1-2) deliberately outranks reject: when the signal to
reject is contested or low-confidence, defer to a human rather than
auto-rejecting.

---

## Output format

Synthesize the findings into the reviewer-facing review. Two derived lists:

- **`top_issues`** — up to **3** MUST-FIX items, ranked by
  `(blocking before advisory, then higher severity, then more structural)`.
  A finding is **must-fix** when it is `severity ≥ 2` on any non-informational
  dimension, **or** `severity == 1` on a *blocking* dimension. A `severity 1`
  finding on an *advisory* dimension is **not** must-fix.
- **`suggested_fixes`** — up to **5** additional items: must-fix overflow beyond
  the 3-item cap, plus minor (advisory severity-1) findings. Never duplicate a
  top issue here.

Every `action` and `suggested_fix` must be **specific enough to act on without
opening raw notes**: name a concrete file, section, rubric, or quote the
`evidence_quote` verbatim. Generic advice ("improve authenticity") is not
acceptable.

Present the review using this template (then offer to save it to
`<task_dir>/qc_review.md` or a path the expert chooses):

```markdown
# QC review — <task_id> · Source File and Prompt

**Verdict:** <accept | accept_with_fixes | needs_review | reject_fixable | reject_structural>
**Summary:** <one sentence, <= 25 words>
<!-- include only when verdict is needs_review: -->
**Review required because:** <reason>

## Top issues (must-fix)
1. **[sev N · <fixability> · <dimension>]** <headline>
   - Action: <specific action>
   - Evidence: "<verbatim evidence_quote>"
<!-- up to 3; omit the section entirely if none -->

## Suggested fixes (minor)
- <specific suggestion>
<!-- up to 5; omit if none -->

## All dimension findings
| dimension | role | sev | conf | fixability | headline |
|---|---|---|---|---|---|
| overall_gdpval_fit | blocking | 0 | high | n/a | no issue |
| ... | ... | ... | ... | ... | ... |
```

Keep the full findings table so the expert sees skipped/clean dimensions too.
For `accept`, both issue lists are empty — say so plainly.
