---
name: harbor-golden-reproducibility
description: >-
  Attempts a Harbor-shaped task blind (environment/initial_workspace/ and
  instruction.md only, no solution/, no tests/) with a fresh solver, then
  compares the resulting deliverable against the real golden answer and
  every judge.toml criterion. Catches tasks where the golden reproduces only
  because the golden's author already knew the answer -- an ambiguous or
  underspecified prompt that an independent blind solve cannot pass even
  when the rubric and golden agree with each other perfectly. Run on a
  5-10% random sample of a task population, not exhaustively -- a full
  blind-solve per task is expensive and this check does not need every
  task to be useful. Use once a population has cleared the other QC layers
  and someone wants to know whether the prompt actually stands on its own.
---

# Golden reproducibility for Harbor-shaped task packages

STATUS: v0, UNVALIDATED AS A PROCESS. This has not yet been run against a real task population to see whether it produces a useful, low-noise signal versus mostly reflecting one agent's variable solve quality. Treat results skeptically until calibrated.

## Provenance and status

Written as a new procedure, not extracted from a proven pipeline the way
`structural-audit/SKILL.md` was. It fills a specific gap that no existing
check covers: does the task actually reproduce its own golden answer when
attempted blind, or does it only pass because whoever wrote the rubric
already knew the intended answer. Nobody has run this against a real task
population yet. Treat every claim below about what it "catches" as a
hypothesis this procedure is designed to test, not a result it has already
delivered.

## Why this is different from Oracle

Oracle submits a task's own reference answer to its own grader and checks
that the grader accepts it. That is self-consistency: it proves the rubric
and the golden agree with each other, and nothing else. A task can pass
Oracle on two independent runs and still have a prompt that is ambiguous,
underspecified, or silently relies on context only the golden's author
had -- Oracle cannot see that, because it never asks anyone to solve the
task from the prompt alone.

This check does the opposite: it withholds the golden and the tests, hands
a fresh solver only what a real solver would get (`environment/
initial_workspace/` and `instruction.md`), and asks whether that alone is
enough to independently arrive at something the real rubric would accept.
Where Oracle asks "does the answer key pass its own test," this asks "does
the question, on its own, produce that answer key." A task can pass one and
fail the other for unrelated reasons, which is why this is a fourth,
independent layer alongside structural-audit, Oracle, and a content-only
read of prompt/golden/rubric text -- not a replacement for any of them.

| Layer | Checks | Blind to |
|---|---|---|
| Content audit | prompt/golden/rubric text, no solve involved | Whether the built package matches that text, whether the prompt is actually solvable from what it shows |
| Oracle | rubric vs. golden, run twice | Whether the prompt itself supports reproducing the golden independently |
| Structural audit | built package vs. prompt vs. verifier | Content correctness of the rubric or the golden |
| This skill | blind solve vs. golden vs. every criterion | Whether the rubric's criteria are individually well-formed (that's the content audit's job) |

## Hard requirement: the blind solver sees nothing but a real solver's inputs

The isolated copy handed to the fresh session or person must contain
`environment/initial_workspace/` and `instruction.md` and nothing else --
explicitly no `solution/`, no `tests/`, no rubric, no filename or directory
that hints a golden answer exists nearby. Never put the answer key in front
of the graded party: this applies here even though the "graded party" is a
disposable QC probe, not a real solver, because a probe that can see the
answer produces a result that looks like a pass and means nothing.

Build the isolated copy in a fresh directory outside the task's own build
tree (a temp directory, a scratch clone), copying only the two named paths.
Do not symlink into the original task directory -- a careless `ls ..` or a
curious solver poking one level up must not be able to find `solution/`
sitting next to it.

## Procedure

1. **Stage the blind copy.** From the real built package, copy
   `environment/initial_workspace/` and `instruction.md` only into an
   isolated location (a fresh scratch directory). Verify by listing the
   isolated copy's contents that no `solution/`, `tests/`, `judge.toml`, or
   any file with "golden" or "answer" in its name is present anywhere
   under it, including in parent directories the solver could navigate to.

2. **Attempt the task blind.** Open a fresh Claude session (or hand it to a
   person) pointed only at the isolated copy, with no framing that this is
   a QC check and no hint that a reference answer exists. Give it the same
   instructions a real solver would get: attempt `instruction.md` using
   only what's in `initial_workspace/`. Save whatever the solver produces
   as the blind deliverable.

3. **Compare against the real answer.** Go back to the real task package.
   Diff the blind deliverable against `solution/` -- not just "did it look
   similar" but which specific facts, values, filenames, or structural
   requirements match and which don't.

4. **Score against every judge.toml criterion, one by one.** Read the real
   `tests/judge.toml` (or equivalent verifier config) and, for each
   individual criterion, determine whether the blind deliverable would
   satisfy it. Do this criterion-by-criterion, not as a single holistic
   yes/no -- a blind solve can pass eight of ten criteria and the two
   misses are the actual signal.

5. **Classify every miss.** For each criterion the blind attempt failed,
   decide which of two buckets it falls in:
   - **Prompt defect**: the miss looks like it came from the prompt itself
     being ambiguous, underspecified, or silently assuming information the
     solver had no way to have (a required file never named, a format
     never specified, a term used without definition that the golden
     interprets one specific way among several reasonable ones).
   - **Solve quality**: the miss looks like the blind attempt was simply
     lower-quality or made an avoidable error, not that the prompt failed
     to communicate what was needed -- a real solver with the same prompt
     could plausibly have gotten this right.
   This classification is the actual judgment call this procedure asks
   for, and it will often be genuinely unclear. Say so when it is, rather
   than forcing a bucket.

6. **Report per task**: which criteria passed blind, which failed, and for
   each failure, the prompt-defect-vs-solve-quality call with the reasoning
   behind it. A task where every criterion passes blind is a positive
   signal for that task alone, not proof the population is fine.

## Sampling, not exhaustive coverage

A full blind solve costs a real attempt per task -- a fresh session's full
context and time, or a person's actual working time. Run this on a random
5-10% sample of a task population, not on every task. A random sample
means selected without looking at which tasks seem risky first; picking
only tasks that already look shaky defeats the point of sampling for a
population-level signal.

If the sample turns up a pattern (the same criterion type failing blind
across multiple unrelated tasks, say), that is a reason to widen the
sample for that specific pattern, not to conclude the whole population
shares the defect from a handful of data points. One measurement is not a
finding: a sample-level result needs a second, differently-shaped read
before it becomes a claim about the population, the same way any other
QC number here would.

## What this does not establish

A clean result (blind attempt satisfies every criterion) says the sampled
task's prompt was sufficient for at least one solver on at least one
attempt. It does not say:

- that a different solver, or the same solver on a different attempt,
  would reproduce it again (compound criteria are known to flip between
  runs on identical inputs; a single blind pass is one datapoint, not
  proof of stability)
- anything about tasks outside the sample
- that the rubric's own criteria are individually well-formed (a
  structural or content audit's job, not this one's)
- that the golden itself is correct (Oracle's job, not this one's)

A failed result does not by itself mean the task should be pulled -- see
step 5's classification. A solve-quality miss on one blind attempt is
weak evidence about the task; a prompt-defect miss is the actual signal
this procedure exists to surface, and even then, one occurrence is a
finding to report, not yet a confirmed defect, until someone looks at the
specific prompt language and agrees.

## Cross-reference against the other layers, every time

This skill alone is not a readiness signal, the same way none of
content-audit, Oracle, or structural-audit alone is one. Run it alongside
the others, on the sampled subset, and report its result as one more
independent layer -- never as a substitute for running the other three on
the full population.
