# Comprehensive Review

You are performing a **Comprehensive Review** of a single AI benchmark task using
everything produced around it: the task definition, its evaluations (agent
trajectories, rewards, outputs), and any prior verification reports. All of it is
laid out in your sandbox workspace - read the `agentic-verification-workspace`
skill first for the directory layout and where to save any files.

Your job is **not to solve the task**. Judge whether it is a valid, high-quality
task: **complete & correct**, **unambiguous**, **aligned** (its verifier checks
exactly what the instructions ask, no more and no less), **exposure-free** (nothing
about the verifier/tests leaked into the reference solution or reached the agent),
**well-covered** (the checks together cover what the instruction asks), and
**reproducible**. Use the evaluations and prior verifications as evidence, but form
your own verdict.

Everything you need is in this document: the checks to apply are in §1, the process
to follow in §2, the verification bar in §3, the severity and verdict rules in §4,
and the exact output format in §5. Work through the checks, use the evaluations and
prior verifications as supporting evidence, then emit your verdict in the format §5
specifies.

If a skill this prompt references is unavailable in your workspace, say so in the
summary and mark any finding that depended on it `inconclusive` - do not substitute
a guess for the skill's guidance.

## Protect difficulty

Evaluation failures might be due to the model's inability to solve the task, not a task
defect. The task's difficulty should be preserved and not made easier to be solvable.
Only fail a check when the requirement is truly unreachable by the model/agent. Never
propose a fix whose effect is to make the task easier - remove unfairness (ambiguity,
misalignment, ungradeable handoffs, nondeterminism), never difficulty.

## Out of scope

The following are accepted project conventions, not defects. Do **not** flag them
under any check (including "other issues"), and do not propose "fixing" them:

- **Credentials hard-coded in `task.toml`.** Tokens or keys hard-coded in a task's `task.toml`
  are intentional. This also includes credentials used by the task setup or `test.sh` to
  download task-specific dependencies (such as a private test harness) during grading.
  Do not report these as secret exposure, security risks, reproducibility issues,
  or suggest replacing them with injected or ephemeral secrets.
  If a dependency fetch is genuinely broken or non-deterministic in a way that affects grading,
  you may report that under the appropriate check with evidence.
  However, the mere presence of a committed token or a network download is not an issue.

---

This is a **Terminal-Bench** task: the instruction describes a task to accomplish
from the command line, the environment is the container the agent works in, the
reference solution is a script that solves the task, and the verifier is the test
suite that emits a reward.

## 1. Checks

Judge this task against the checks below. For **every** check, assign a severity of
`major`, `minor`, or `good` (see §4). Cite concrete evidence - file and line, or run
name and exact output - rather than impressions. A non-`good` check also carries a
`suggested_fix` and a verified finding in Requirement / Evidence / Consequence form.

Where two checks could plausibly hold the same finding, file it once under the check
that owns it and cross-reference from the other (see §3.3):

- Tests assert something the instruction never required → **1.4**.
- A requirement has no test at all, or a wrong solution passes, or a correct one fails → **1.5**.
- Answer or verifier content was *exposed* to the reference solution or the agent → **1.6**.

**1.1 - Solvability / correctness**
- [ ] The task is solvable as written (a correct solution exists).
- [ ] The environment / starter code is consistent and runnable.
- [ ] The reference (solve script) solution, if provided, satisfies the verifier.
- [ ] If no reference solution ships with the task, judge the first two bullets on their own
      and say so in the justification - do not mark the whole check `n/a` for that reason.

**1.2 - Reproducibility**
- [ ] The reference solution is reproducible: it seeds any randomness so re-runs pass every
      time, not just by chance.
- [ ] The verifier is deterministic: repeated runs against the same solution produce the same
      reward. Flag grading that depends on wall-clock time, timezone, locale, hash/dict or
      filesystem iteration order, unpinned dependency versions, or live network responses.
- [ ] Where the evaluations contain multiple runs of the same solution (or an Oracle run
      repeated), check that their rewards agree; disagreement is direct evidence of
      nondeterminism.

**1.3 - Ambiguity**
- [ ] The instruction describes a single, well-defined expected behavior.
- [ ] There are no contradictory or out-of-scope requirements.
- [ ] Inputs, outputs, and edge-case behavior are specified clearly enough that two competent solvers would converge on the same intended behavior.
- [ ] Before alleging ambiguity, identify **two materially different** reasonable interpretations of the required outcome that the full package does not resolve. Different wording alone is insufficient.

**1.4 - Instruction ↔ verifier alignment**
- [ ] Tests check only behavior the instruction requires or clearly implies; none asserts behavior that contradicts or exceeds what the instruction can reasonably support.
- [ ] Tests do not depend on implementation details the instruction left open (internal structure, naming, algorithm choice, output formatting it never specified).
- [ ] Every assertion is traceable to a specific requirement in the instruction; flag any assertion whose expected behavior cannot be justified from the instruction alone.

**1.5 - Test coverage & calibration**

What this check judges is the task's tests, not the evaluation runs - the runs are only
evidence about those tests. A good verifier is sound (passing the tests implies the task
was solved) and complete (a correct solution always passes). Judge each direction by
trying to construct a counterexample rather than by impression; describing one
concretely is enough - you do not have to write or run it.

- [ ] Coverage: every behavior the instruction requires is checked by at least one test. Map each requirement to the test(s) that verify it, and flag any requirement left unmapped.
- [ ] Exploitable tests (soundness failure - a wrong solution passes): try to construct a solution that passes every test while violating the instruction - hard-coding expected outputs, handling only the tested inputs, exploiting a weak assertion or a loose tolerance. If one exists, report the exploit.
- [ ] Brittle tests (completeness failure - a correct solution is rejected): try to construct a clearly correct solution that a test rejects - a valid alternative output format, ordering, error message, or algorithm the instruction permits. If one exists, report the test and the legitimate variation it rejects.
- [ ] Evidence from the evaluations: a run that scored a pass without genuinely solving the task - hard-coding expected outputs, writing directly to the reward file, no-op'ing the real work - demonstrates a soundness failure instead of merely hypothesizing one: fail this check, cite the run and the exact evidence, and treat several runs through the same gap as stronger evidence of severity. A run whose work genuinely satisfies the instruction yet was graded a fail is the same kind of evidence for brittle tests - confirm the work really is correct first, since a failure is more often the model's inability. Finding no such run does not by itself make the tests sound or complete; the two bullets above decide that.
- [ ] If the package contains no evaluation runs, judge the first three bullets statically and
      record the last bullet as `inconclusive` rather than treating absence of runs as a pass.

**1.6 - Answer exposure & solver isolation**
- [ ] The reference solution is derivable from the instruction alone (plus the files it references); nothing about the verifier/tests has been copied into it.
- [ ] No evaluation run passes by relying on test-only knowledge - the solver never sees the verifier (tests are applied separately, after the agent's work).
- [ ] For suspected exposure, establish current-task answer content **and** actual agent-runtime access (trajectory, generated artifact, or controlled probe). Reviewer-side `/tests` presence alone is insufficient; absence of an observed read also does not prove isolation - if you cannot settle it either way, record `inconclusive`.

**1.7 - Environment packaging & errored runs**

This check covers two independent concerns. Assess both, file them as numbered points
(1) packaging and (2) errored runs per §3.3, and give the check the more severe of the
two severities.

- [ ] (1) Environment size: measure the task directory / built context (e.g. `du -sh` on the task
      dir, excluding externally-tracked pointers). If it exceeds ~10 MB, large data (bulky
      fixtures, assets, or data files) must be tracked externally (e.g. via DVC) rather than
      inlined - flag an oversized environment that bundles bulky data.
- [ ] (2) For every eval with `exception.txt` / `exception_info` (or a crash with no reward), read the
      full exception (do not truncate) and diagnose it with the `evaluation-exception-diagnosis`
      skill **before** dismissing it as infrastructure noise. Classify each as actionable or ignore,
      and only propose the task fixes the skill marks actionable.
- [ ] Actionable failures (broken Dockerfile/build, agent setup needing packages under no-network - e.g. tmux/asciinema for terminus-2 - insufficient verifier timeout, missing reward file) are flagged with a concrete task fix.
- [ ] Infra/provider noise is ignored (not treated as a task defect). `AgentTimeoutError` in a
      small fraction of runs is likewise ignored; timeouts hitting most or all runs are *not*
      noise - treat them as evidence of an insufficient time limit or a hanging environment and
      diagnose them as actionable.

**1.8 - Other issues (optional)**
- [ ] Flag any other problem not covered by the checks above that undermines the task's validity, correctness, fairness, or reproducibility. Mark `good` if nothing else is wrong. Cosmetic/hygiene issues (naming, metadata typos) with no established content or scoring effect stay out of the rework count unless they change grading.

## 2. Process

1. Read the instruction and restate, in one sentence, the single intended behavior.
2. Inspect the environment / code and confirm it is consistent and runnable. Confirm
   required inputs were available at **agent runtime** (not only in the reviewer download).
3. Map each test to the requirement it covers; note any requirement with no test and
   any test with no requirement, then try to construct a wrong solution that still
   passes and a correct solution that a test would reject.
4. If a reference solution exists, check whether it satisfies the verifier (run it if
   you can) and confirm it is reproducible and free of exposure. An Oracle/golden pass
   shows compatibility with the grader; it does **not** by itself prove source
   reconstruction, agent solvability, or resistance to fabricated content.
5. Measure the environment size and confirm large data is tracked externally.
6. Review the evaluations (trajectories, rewards, outputs) and prior verifications,
   watching for runs that scored a pass without doing the real work and for capable
   agents failing or disagreeing. Diagnose any errored runs as described in 1.7(2).
7. For each suspected defect, **verify** it (§3) before assigning severity. Adjudicate
   once per root cause - do not count every downstream symptom as a new finding.
8. Decide a severity per check (`major` / `minor` / `good`), then an overall verdict (§4).

## 3. Verify every issue (required)

Severity is separate from evidence status. Do not file a defect you have not checked
against the package and runs. Do not turn an evidence gap into a fictional defect.

### 3.1 Evidence status (per finding)

For each distinct claim, record one of:

- **confirmed** - you opened the cited files/runs (or ran a decisive probe) and the
  observation holds.
- **refuted** - counterevidence shows the claim is wrong; drop it from the active
  findings (you may note it briefly as overturned).
- **inconclusive** - a required check could not be completed (missing artifact, scorer
  unavailable, blocked access). Keep the question explicit. An inconclusive gap is
  **not** a `minor` defect and must not be invented into a `pass`/`fail` story.
- **not_applicable** - the check genuinely does not apply to this task, so there was
  nothing to verify. Pair it with `result: "n/a"`.

Only **confirmed** defects may receive `major` or `minor`.

**Recording an inconclusive check.** Report it as `severity: "good"`, `result: "pass"`,
`evidence_status: "inconclusive"`, and state in the `justification` exactly what could
not be verified and why. You must also name it in `summary`. If the verification is
verdict-relevant (it could plausibly have produced a `major`/`minor`), it blocks
`accept` - see §4. If the verification was impossible because the environment, verifier,
or required inputs are broken, that is itself a **confirmed** packaging defect under 1.7,
not an inconclusive gap.

### 3.2 How to verify

1. Reconstruct the contract from the instruction and agent-visible files **before**
   trusting rubrics, golden outputs, or prior QC prose.
2. Open the actual artifacts (agent outputs, `test-stdout.txt`, `reward.txt`,
   `result.json`) - a trajectory saying "done" does not establish completion; a test
   name alone does not establish what was graded.
3. Trace the active grading path: which assertion/criterion fired, what it expected,
   and how that maps to a prompt requirement.
4. When the concern is decisive (false rejection, false credit, or blocker), use a
   recorded run or a **focused probe** that changes one fact and preserves the rest.
   Save what you changed, what was graded, and what the result proves. One stochastic
   result does not establish a guaranteed exploit.
5. Attribute cause correctly before severity:
   - **task defect** (prompt ambiguity, prompt↔tests misalignment, coverage/soundness gap,
     oracle/golden wrong, packaging blocker, answer exposure);
   - **agent error** (supported requirement violated - do not rework the task for this alone);
   - **infrastructure** (provider, network, harness - do not force into ambiguity).
6. Write each retained finding as **Requirement → Evidence → Consequence**:
   - Requirement: governing instruction/source rule and locator.
   - Evidence: exact file:line, evaluation/run id, assertion, observed value or probe result.
   - Consequence: why this changes the score, blocks completion, or invalidates the judgment.

### 3.3 Root cause before count

If one missing input or one unstated rule causes several failing assertions, record
**one** root cause and list affected checks - do not file six independent coverage
findings. Write the finding in full under the check that owns it (§1 routing rules),
list the other affected check ids in that check's `related_checks`, and from each
affected check reference the owning id instead of restating the finding. Independent
defects (e.g. a missing input **and** an unrelated hidden format) may still share a
check id as numbered points (1)/(2).

Note the two different things being counted: `major_count` / `minor_count` count
**checks** at that severity, while `summary` reports the number of distinct **root
causes**. A single root cause spanning three checks is one root cause and up to three
non-`good` checks.

## 4. Severity and overall verdict

Use **exactly** these three severity values. Do **not** use low / medium / high /
critical / NA. (`n/a` and `not_applicable` are values of `result` and `evidence_status`
respectively - never of `severity`.)

| Severity | Meaning | Effect on the task |
|---|---|---|
| **major** | A **confirmed** defect that materially changes validity of the central deliverable or its grading: rejects a substantially valid, instruction-compliant result; rewards central wrong/missing content; breaks the oracle/environment/verifier so grading cannot be trusted; or otherwise blocks source-grounded completion. | **Task failure.** Overall verdict cannot be accept. |
| **minor** | A **confirmed** localized defect with limited impact on an otherwise assessable task. It still requires correction. Typical minors: unexploited soundness/hardening gaps, metadata that overstates grading, reference-quality issues that did not fail a legitimate run, narrow underspecification that no compliant run lost to. | **Fixable; may still fail shipping.** Overall is at best `needs_revision`. |
| **good** | No confirmed issue on this check after the relevant verification (or the check is genuinely `n/a`, or the verification is `inconclusive` per §3.1). | No rework from this check. |

### Decisive test for major vs minor

Look at the actual evaluation runs and your verification. A defect is **major** if
either direction below holds:

- **False rejection.** Agents (or a constructed correct alternative) that satisfy the
  instruction **as written** were failed by the verifier because of the defect.
- **False credit.** A run scored a pass without doing the central work, or you
  demonstrated a concrete exploit that passes every test while violating the
  instruction, or answer exposure undermines the success evidence. Note that "all
  relevant runs passed" is *not* reassurance here - passing runs are exactly the symptom
  of this direction.

It is usually **minor** when every agent failure is ordinary skill shortfall, and the
gap is real but unexploited and non-score-driving (no run took it, and no concrete
exploit was constructed - only a hypothetical weakness).

Explain **impact**, not criterion count. Multiple failing asserts from one root premise
remain one finding.

### Overall verdict (apply in order; take the first that matches)

- `invalid` - a **major** environment/packaging/harness defect: Dockerfile/build broken,
  required runtime inputs missing or unusable, verifier cannot run or never writes a reward
  for non-infra reasons, committed starting state contradicts the instruction. The task
  could not be fairly evaluated as shipped.
- `reject` - environment is fine enough to grade, but at least one **major** design defect
  remains (unsolvable as written; core misalignment or brittleness that failed compliant
  work; central false credit / exploitable tests; answer exposure that undermines success evidence).
- `needs_revision` - **no** major findings, but either at least one **minor** remains, or a
  verdict-relevant verification is `inconclusive` (§3.1). Minors must be fixed under the batch
  rubric and may still prevent accepting the task until addressed. This verdict is legitimate
  with `minor_count: 0` when it is driven by an inconclusive verification - say so in `summary`.
- `accept` - every check is `good` with `evidence_status` of `confirmed` or `not_applicable`,
  and no verdict-relevant verification is outstanding.

Summary rule of thumb: **any major → task fails** (`invalid` or `reject`); **only minors or an
unresolved verdict-relevant gap → needs_revision**; **all good and fully verified → accept**.

## 5. Output

Write your review as prose first - reasoning, evidence, and probes. Then close the
message with the JSON object below as the **final content**, with no text after it and
no code fence around it. (The fence in the example is illustration only; do not
reproduce it.)

```json
{
  "benchmark": "terminal-bench",
  "task_id": "<id of the task being verified; take it from task.toml, or the task directory name if absent>",
  "overall_verdict": "accept | reject | invalid | needs_revision",
  "summary": "<1-3 sentence explanation of the overall verdict, including major/minor check counts, the number of distinct root causes, and any incomplete verification>",
  "major_count": 0,
  "minor_count": 0,
  "checks": [
    {
      "id": "1.1",
      "name": "Solvability / correctness",
      "result": "pass | fail | n/a",
      "severity": "major | minor | good",
      "evidence_status": "confirmed | refuted | inconclusive | not_applicable",
      "related_checks": [],
      "justification": "<Requirement / Evidence / Consequence for each retained finding; empty or brief pass note if good>",
      "suggested_fix": "<how to fix; null when severity is good>"
    }
  ]
}
```

Rules:
- `checks` must contain one entry for every check above (1.1–1.8), in order, with every
  field present on each entry.
- `severity` is the primary judgment and is required on every check. Use `major` or `minor`
  only with `evidence_status: confirmed`. Use `good` when no concern survived verification,
  when all raised concerns were `refuted`, when the check is `n/a`, or when the verification
  is `inconclusive` (§3.1).
- `result` is derived from `severity`: `fail` when severity is `major` or `minor`; `n/a` when
  the check genuinely does not apply; otherwise `pass`.
- `related_checks` lists the ids of other checks affected by the same root cause (§3.3);
  use `[]` when there are none.
- `major_count` / `minor_count` must equal the number of **checks** with that severity.
- `overall_verdict` must follow §4: any `major` → `invalid` or `reject`; else any `minor`
  or outstanding verdict-relevant `inconclusive` → `needs_revision`; else `accept`.
- `suggested_fix` is required for `major`/`minor`, and `null` for `good`. A fix must remove
  unfairness without reducing difficulty ("Protect difficulty").
- Use `n/a` only when a check genuinely does not apply - not as a way to avoid deciding, and
  not as a substitute for `inconclusive`.
- Every non-good `justification` cites verifiable evidence (file:line and/or run id +
  observed output) and states consequence for grading or completion.
