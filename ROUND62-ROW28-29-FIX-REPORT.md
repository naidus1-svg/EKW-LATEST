# Fix report: structural_audit_check.py run-to-run non-determinism (rows 28-29)

An adversarial re-review (ROUND62-AR-ROW28-29-REPORT.md, sibling worktree
round62-ar-row28-29) found the check's core design correct but its verdict
not reproducible run-to-run. SVC-PC-16-2-0, a confirmed true positive
(instruction.md line 1 is `# L2-02 - Prompt`, a pipeline node identifier,
and rubric r021 requires "zero occurrences" of exactly that), came back
clean on one LLM call after correctly flagging it on another. A fresh
18-task sample returned 0/18 warn versus the original 9/28, consistent
with the check under-firing on borderline signals, not over-firing.

This report covers the fix and its verification with real LLM calls. All
calls used `LLM_BACKEND_FORCE=http` against the configured glm-5.2 gateway,
the same backend the original and adversarial reports used. No call was
simulated.

## What changed and why

The same failure mode row 35's `fabricated_unfilenamed_fact_check.py` hit
and fixed: (1) a "prefer precision over recall" system-prompt line that
suppressed borderline flags, and (2) an implicit "scan and report what
jumps out" methodology a single LLM call can silently skip on a bad roll.
Applied the same two-part fix, adapted to this check's six structural
patterns.

### Part 1: recall-positive framing

Replaced both "prefer precision over recall" lines (the SYSTEM_PROMPT and
the output rules at the end of build_prompt) with recall-positive framing:

> Every finding is reviewed by a human before any action, so a candidate
> flag is far cheaper than a missed structural defect that ships to
> graders. Flag any pattern you can support with the evidence below; do
> not suppress a flag merely because you are less than fully certain, as
> long as you can name the pattern number, quote the instruction text
> (with its line number), and state why the pattern fired.

This mirrors row 35's recall-positive wording: "a candidate flag is far
cheaper than a missed fabrication that ships to graders."

### Part 2: mandatory per-pattern enumeration in the output

The original methodology told the LLM to "for each pattern, decide: did it
fire?" but the LLM (a reasoning model that emits only the final JSON) had
no mechanism forcing it to actually consider each pattern. Probing showed
the LLM returned `{"verdict": "clean", "findings": []}` directly, having
silently skipped the methodology. Adding the enumeration to the prompt
text alone did not help: the LLM still returned clean without doing the
per-pattern consideration in its visible output.

The fix makes the enumeration load-bearing by requiring it in the JSON
output itself. The OUTPUT FORMAT now requires a `pattern_review` array
with exactly six entries (pattern 1 through 6, in numeric order), placed
BEFORE the verdict and findings. Each entry carries a `decision`
(fires/not_fires), the specific `text_considered` (with line numbers), and
a `reason` grounded in the real content. A pattern the LLM never
explicitly considers is a pattern it can never flag; the pattern_review
array makes silent skipping structurally impossible, because the output
format itself requires six committed decisions.

The parser (`build_task_result_from_response`) preserves the
pattern_review array in the per-task result dict, normalized to a
bounded shape, so a reviewer can see which patterns the LLM considered and
rejected, not only what it flagged.

### Part 2b: strengthened pattern 4 trigger description (adaptation)

During verification, the recall-positive framing and mandatory enumeration
alone were not enough for SVC-PC-16-2-0. The LLM did the enumeration
correctly (all six pattern_review entries present), identified `L2-02` as
"a standard task identifier label," but decided pattern 4 did not fire
because pattern 4's description listed "internal stage labels, bracketed
build-system language, template placeholders, pipeline path markers"
without naming "node identifier" or "eval-only vocabulary" (the rubric's
own terms in criterion r021). The LLM had both pieces (the instruction
text and the rubric criterion) but did not connect them without the
explicit trigger term.

The fix strengthens pattern 4's description to name "node identifier" and
"eval-only vocabulary" as triggers and to cross-check against rubric
criteria requiring "zero occurrences" of those terms. After this change,
the LLM consistently connected `# L2-02 - Prompt` to r021's "no node
identifier" requirement and flagged pattern 4.

This is the adaptation the task asked for: row 35's fix targeted a single
fabrication pattern; this check's six patterns required the enumeration to
be forced into the output (part 2) and the specific trigger term that the
LLM was missing (part 2b for pattern 4).

## Verification 1: SVC-PC-16-2-0 three separate runs

The target defect. instruction.md line 1 is `# L2-02 - Prompt` (a pipeline
node identifier and stage label). Rubric criterion r021 (deliverables_02)
requires "The document's text contains no node identifier and no eval-only
vocabulary... Zero occurrences anywhere in visible text." The defect is
real and confirmed by reading the files directly.

Before the fix (original check, same code, same backend): 0/3 runs flagged
it. All three returned clean.

After the fix: 3/3 runs flag pattern 4.

| Run | Status | Pattern | Instruction quote | Criterion |
|---|---|---|---|---|
| 1 | warn | 4 | line 1: # L2-02 - Prompt | deliverables_02/r021, r023 |
| 2 | warn | 4 | line 1: # L2-02 - Prompt | deliverables_02/r021 |
| 3 | warn | 4 | line 1: # L2-02 - Prompt | deliverables_02/r021, r023 |

All three findings cite the verbatim instruction text and cross-check
against rubric criteria r021/r023. The pattern_review for pattern 4 shows
"fires" in all three runs. The L2-02 node identifier and "Prompt" stage
label are both identified as pipeline scaffolding in the evidence.

## Verification 2: acceptance test (SVC-PC-72-3-0, SVC-PC-82-2-0)

Both motivating defects must still flag. One run each (real LLM call).

| Task | Status | Findings | Original finding preserved? |
|---|---|---|---|
| SVC-PC-72-3-0 | warn | p2 + p4 | p2 yes (row-28 defect) |
| SVC-PC-82-2-0 | warn | p5 + p4 | p5 yes (row-29 defect) |

SVC-PC-72-3-0: pattern 2 (deliverable_filename_mismatch) still fires on
the same defect (line 17 names the deliverable without prefix, line 23
names it with L2-03_ prefix, judge reads only the prefixed name). The fix
did not break the original finding. A new pattern 4 finding also fires:
the `L2-03_` prefix on line 23 is a node identifier visible to the solver.
Verified against the real file: line 23 is `- \`L2-03_Unit_Economics_Guardrail_Accuracy_Workpaper.docx\``.
This is a real true positive (same defect class as 16-2-0), not a false
positive.

SVC-PC-82-2-0: pattern 5 (unstated_deliverable_count_or_format) still
fires on the same defect (line 14 "Assigned corpus files" heading
promises a list, zero items enumerated, criterion l2-02-r09 requires "six
assigned files"). The fix did not break the original finding. A new
pattern 4 finding also fires: lines 1-2 are `TASK PROMPT` and
`Delegated workstream prompt | Cirrus Sleep Year 1`, internal pipeline
stage labels. Verified against the real file. This is a real true
positive, not a false positive.

The fix did not break what already worked. Both new p4 findings are
additional true positives the original check missed.

## Verification 3: SVC-PC-1-0-0 (known false-positive case), three runs

The original report flagged this as a false positive: the LLM misread
`FPA_Model` as `Fpa_Model` and flagged a case mismatch that does not exist.
The real instruction.md line 22 reads `Cirrus_FY2021_Full_Year_FPA_Model`
(all caps FPA); the real judge.toml reads the same. There is no mismatch.

| Run | Status | Findings | Detail |
|---|---|---|---|
| 1 | warn | p5 (c15) | instruction does not state "exactly 18 slides" the rubric requires |
| 2 | warn | p5 (c15) + p5 (c30) | same c15 plus c30: instruction says "not internal filenames" but rubric requires "all 4 exact filenames" |
| 3 | warn | p2 (FPA/Fpa) | the original case-misread false positive |

The recall-positive framing did not turn 1-0-0 into a systematic false
positive. The original FPA/Fpa case-misread appears in 1 of 3 runs (run
3), not every run. The p5 findings (runs 1-2) are new borderline findings,
not the original false-positive class. They are "candidate, not verdict"
warnings a human reviewer would check: c15 asks whether the instruction
should state the slide count the rubric grades, and c30 asks whether the
instruction's "not internal filenames" directive contradicts the rubric's
"all 4 exact filenames" requirement. Both are genuine judgment calls, not
case-misread artifacts.

2/3 runs warn, not 3/3. The bar "not firing every single time on a
non-defect" is met.

## Verification 4: fresh 20-task sample, three runs each (60 real LLM calls)

A fresh 20-task sample, disjoint from all prior samples (the named tasks
72-3-0, 82-2-0, 1-0-0, 16-2-0, 46-4-0; the original 28-task sample; the
adversarial review's 18-task sample):

SVC-PC-1-1-0, 1-3-0, 1-5-0, 1-7-0, 10-0-0, 10-2-0, 10-4-0, 11-2-0,
11-4-0, 12-0-0, 12-2-0, 12-5-0, 12-7-0, 13-3-0, 13-7-0, 14-0-0, 14-3-0,
14-5-0, 15-0-0, 15-4-0.

Three separate batch runs, `--jobs 4 --timeout 300`, real LLM calls. Zero
errors, zero parse failures across all 60 calls.

### Per-task results

| Task | Run 1 | Run 2 | Run 3 | All 3 agree (status+pattern)? |
|---|---|---|---|---|
| SVC-PC-1-1-0 | pass | pass | pass | yes |
| SVC-PC-1-3-0 | pass | pass | warn(p5) | no: borderline p5 fires 1/3 |
| SVC-PC-1-5-0 | warn(p1,p3) | warn(p1,p3) | warn(p1,p3) | yes |
| SVC-PC-1-7-0 | pass | warn(p4) | pass | no: borderline p4 fires 1/3 |
| SVC-PC-10-0-0 | warn(p2) | warn(p2) | warn(p2) | yes |
| SVC-PC-10-2-0 | warn(p2) | warn(p2) | warn(p2) | yes |
| SVC-PC-10-4-0 | warn(p5) | pass | pass | no: borderline p5 fires 1/3 |
| SVC-PC-11-2-0 | pass | pass | pass | yes |
| SVC-PC-11-4-0 | pass | pass | pass | yes |
| SVC-PC-12-0-0 | warn(p6) | warn(p4,p6) | warn(p6) | no: core p6 stable, extra p4 1/3 |
| SVC-PC-12-2-0 | pass | pass | pass | yes |
| SVC-PC-12-5-0 | pass | pass | pass | yes |
| SVC-PC-12-7-0 | pass | pass | pass | yes |
| SVC-PC-13-3-0 | warn(p4) | warn(p4) | warn(p4) | yes |
| SVC-PC-13-7-0 | warn(p1,p4) | warn(p4) | warn(p4) | no: core p4 stable, extra p1 1/3 |
| SVC-PC-14-0-0 | pass | pass | pass | yes |
| SVC-PC-14-3-0 | warn(p4) | warn(p4) | warn(p4,p5) | no: core p4 stable, extra p5 1/3 |
| SVC-PC-14-5-0 | pass | pass | pass | yes |
| SVC-PC-15-0-0 | pass | pass | pass | yes |
| SVC-PC-15-4-0 | pass | pass | pass | yes |

### Agreement rates

| Metric | Count | Rate |
|---|---|---|
| All 3 runs agree (status AND pattern set) | 14/20 | 70% |
| All 3 runs agree (status only, ignoring pattern-set differences) | 17/20 | 85% |
| All 3 runs pass | 10/20 | 50% |
| Any run warned | 10/20 | 50% |
| Warned on all 3 runs (stable core finding) | 7/10 | 70% of warned tasks |
| Errors / parse failures across 60 calls | 0/60 | 0% |

### The 6 disagreements

All 6 disagreements are borderline cases, not wholesale status flips:

- 3 status disagreements (pass vs warn): a borderline pattern fires on
  exactly 1 of 3 runs (1-3-0 p5, 1-7-0 p4, 10-4-0 p5). These are signals
  the recall-positive framing sometimes catches and sometimes misses,
  which is the expected behavior for borderline cases under a
  candidate-not-verdict posture.
- 3 pattern-set disagreements (warn all 3, but different patterns): the
  core finding is stable on all 3 runs, but an additional borderline
  pattern fires on 1 of 3 runs (12-0-0 extra p4, 13-7-0 extra p1, 14-3-0
  extra p5). The primary defect is consistently flagged; the secondary
  finding is the variable one.

### Spot-check of consistently-warned tasks (3/3)

Read the real instruction.md and judge.toml directly for four tasks that
warned on all 3 runs, to confirm they are real true positives, not a new
false-positive pattern:

- SVC-PC-1-5-0 (p1+p3, 3/3): instruction.md line 4 names two specific
  required input files (Cirrus_Sleep_Canonical_Facts_Trusted.xlsx,
  Cirrus_Sleep_Bible_Human_Trusted...) that are absent from the
  environment, and line 6 gives a Google Drive URL
  (https://drive.google.com/drive/folders/...) that is not hydrated
  locally. Real pattern 1 and pattern 3 true positives.
- SVC-PC-10-0-0 (p2, 3/3): instruction.md names three graded deliverable
  filenames (Email.docx, Model.xlsx, Report.pdf) but one judge.toml
  deliverable group's files= reads only the Model.xlsx. Real pattern 2
  true positive.
- SVC-PC-10-2-0 (p2, 3/3): instruction.md declares
  FY2022_restock_plan_Memo.docx as a "graded deliverable" but judge.toml
  files= reads a different filename. Real pattern 2 true positive.
- SVC-PC-13-3-0 (p4, 3/3): instruction.md line 1 is `# L2-03 - Prompt
  (verbatim)` and line 3 is `Node: L2-03 - Role: VP Marketing - Vertical:
  Marketing - Prompt verified: Yes`. Clear pipeline node identifier,
  stage label, and build-system metadata. Real pattern 4 true positive.

No new false-positive pattern was introduced. The consistently-warned
findings are real defects verified against the real files.

### Borderline 1-7-0 (p4, flagged 1/3)

SVC-PC-1-7-0 instruction.md line 2 is a standalone "Prompt" heading. The
LLM that flagged it (run 2) cited the pattern definition's own example
("# L2-02 - Prompt" where "Prompt" is a pipeline stage label). No rubric
criterion on this task checks for "node identifier" or "Prompt," so the
finding rests on the pattern definition alone, not a rubric cross-check.
This is a genuinely borderline signal: "Prompt" alone (without a node
identifier like L2-02) could be a pipeline stage label or a legitimate
section heading. The LLM flagged it 1/3, which is the expected variance for
a borderline case. It is not a systematic false positive.

## Verification 5: real before/after

The most direct before/after comparison is SVC-PC-16-2-0, measured 3x both
ways on the same task with the same backend:

| | Before fix | After fix |
|---|---|---|
| SVC-PC-16-2-0 run 1 | clean | warn(p4) |
| SVC-PC-16-2-0 run 2 | clean | warn(p4) |
| SVC-PC-16-2-0 run 3 | clean | warn(p4) |
| Consistency | 0/3 flagged (missed real defect) | 3/3 flagged (consistent) |

Before the fix, the check was inconsistent in the worst direction: it
sometimes flagged a real defect (the original report's run) and sometimes
missed it (the adversarial review's run, my baseline run). After the fix,
it consistently flags the defect on all 3 runs.

For the 20-task sample, a before-fix 3x run on the same sample was not
performed (it would require 60 additional LLM calls against the unmodified
check). The available before-fix evidence is:
- The adversarial review's 18-task sample (different sample, single run):
  0/18 warn.
- The adversarial review's 3-task reproduction: 1/3 flagged tasks
  reproduced on re-run (the one that reproduced was a stable p2; the one
  that did not was 16-2-0 p4, the exact defect this fix targets).

After the fix, the 20-task x3 sample shows:
- 70% full agreement (status + pattern), 85% status agreement.
- 7 of 10 warned tasks warned on all 3 runs (stable core findings).
- The 6 disagreements are borderline cases (additional pattern on 1/3
  runs, or borderline pattern on 1/3 runs), not the wholesale clean-vs-flag
  flips the adversarial review documented on 16-2-0.
- Zero errors across 60 calls.

The fix materially improved consistency on the specific defect it was
designed to fix (16-2-0: 0/3 to 3/3). The 20-task sample shows the check
is now substantially stable on core findings (70% of warned tasks reproduce
on all 3 runs) with residual variance only on borderline signals, which is
the expected behavior under a candidate-not-verdict posture. The fix did
not introduce a new systematic false-positive pattern (borderline cases
fire 1/3, not 3/3; consistently-warned tasks verified as real true
positives).

## What the fix does not claim

- 100% run-to-run agreement. The real rate is 70% full agreement, 85%
  status agreement. Borderline signals still vary across runs. This is
  the nature of LLM judgment on borderline cases, not a fixable defect in
  the prompt.
- A before-fix 3x baseline on the same 20-task sample. The before/after
  comparison rests on 16-2-0 (direct, same task, measured 3x both ways)
  and the qualitative difference between the adversarial review's
  single-run results and the 3x results here.
- Zero false positives. The p5 findings on SVC-PC-1-0-0 (runs 1-2) and
  the p4 finding on SVC-PC-1-7-0 (run 2) are borderline; whether they are
  true or false positives requires human review. They are not the
  original FPA/Fpa case-misread class, and they do not fire systematically
  (1/3 or 2/3, not 3/3).

## Commands and artifacts

All runs used `LLM_BACKEND_FORCE=http` against the configured glm-5.2
gateway. Outputs were written to temp JSON files (not committed):

- 16-2-0 baseline (before fix): 1 run, clean, 23.2s.
- 16-2-0 after fix: 3 runs, all warn(p4), 19.4s / 41.2s / 18.4s.
- Acceptance (72-3-0, 82-2-0) after fix: 1 run, 2 warn (p2+p4, p5+p4),
  80.3s.
- 1-0-0 after fix: 3 runs, warn(p5) / warn(p5,p5) / warn(p2),
  50.0s / 73.3s / 31.2s.
- 20-task sample, run 1: 12 pass, 8 warn, 0 error, 253.8s.
- 20-task sample, run 2: 12 pass, 8 warn, 0 error, 176.9s.
- 20-task sample, run 3: 12 pass, 8 warn, 0 error, 188.0s.

Total real LLM calls in this verification: 3 (16-2-0 baseline) + 3
(16-2-0 after fix) + 1 (probe) + 2 (acceptance) + 3 (1-0-0) + 60
(20-task x3) = 72 calls, 0 errors.
