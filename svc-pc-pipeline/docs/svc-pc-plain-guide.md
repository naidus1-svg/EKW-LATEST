Status: stale. The [auto-fix quickstart](../../docs/autofix-agent-quickstart.md) and the [pipeline README](../README.md) replace it, and the [QC SOP](../../docs/QC-SOP-first-run.md) is the process for a person. Do not follow its commands.

# SVC-PC QC, in plain words

2026-09-21. The simple version of what our pipeline does and what we changed this round. The jargon-heavy
SOP is [svc-pc-one-shot-fix-guide.md](svc-pc-one-shot-fix-guide.md); the live operating plan is
[../ekw/plan-2026-09-21-v6-dataos-as-gate.md](../ekw/plan-2026-09-21-v6-dataos-as-gate.md). This doc is for
anyone on the team who wants the whole picture in five minutes, no acronyms.

## Update (2026-10-05): the DataOS pipeline and its pass rule changed

This guide was written for an earlier DataOS setup. The pipeline now is "ManualQC automated QC pipeline 4 Reviewers"
(version 8). It runs the five evaluation runs (the oracle runs, the GPT 6 Sol solver runs and the empty-answer NOP
run), then four identical "Answer Check" reviews (Claude Opus 5.5, medium effort; the review prompt is DataOS saved prompt 431,
named "Comprehensive_v3_pipeline_quality_re-derive_cascade_NOP_2026-10-03"). A task fails the pipeline if any of
the four Answer Check reviews reports a major, and passes only when all four are clean (see the
[QC SOP, section 6b](../../docs/QC-SOP-first-run.md#6b-the-dataos-pipeline)). The author reads each review with a
major and fixes what is real. The two "Failed Tests" reviews were removed in version 7. A run costs about 3.15 USD
(approximate: version 7 measured 2.20 USD, and each added review is about 0.47 USD). A
manager then reviews the result: a task that fails goes back to the author with the failed checks, and a task that
passes can go in the next TFRL batch unless the manager's own read finds a Major they can show. A pipeline pass is
not a TFRL QC approval. The "NO CLAUDE" pipeline, the older "ManualQC automated QC pipeline" (version 5 and
earlier), the version 6 pair rule and the "2 of 3 reviews" rule are retired. Where the sections below describe the reviewers, the pass rule
or the grading cost, they describe the earlier setup. The method (full coverage sweep, DataOS as the only verdict)
is unchanged.

## Latest (2026-09-22): what the last batch taught us, and the rules now built in

Our batch of 18 came back with 8 accepted, our best result so far. The 10 that failed failed for three
reasons, and each is now a built-in rule rather than something to remember:

1. **Old files got shipped.** Four tasks were packaged in the morning, then fixed again in the afternoon, and
   the fix found problems. We uploaded the morning package anyway. Now every package carries a fingerprint
   of exactly what was checked. If anything in the task changes afterwards, the package is refused and the
   task goes back into the fixing queue by itself. You cannot bundle packages by hand any more; the only
   way is `tools/svc_bundle_upload.py`, and it re-checks every task right before upload.
2. **We were told not to add rubric items, even when one was missing.** When the grader says "nothing checks
   that the answer includes X", the fix is to add one check for X. Our fixing instructions had forbidden
   that. The rule is now: too strict, loosen or remove it; missing, add one check for the missing fact.
3. **We fixed the one example instead of the whole group, and did not re-check what we rewrote.** If the
   grader says one refund is missing from the tally, check every refund, not just that one. And any section
   we rewrote gets reviewed again as if new, because the grader reads it fresh.

All the fixing rules live in one file, `tools/svc_fix_method_rules.md`. Every automated fixer and reviewer
reads it. If you change a rule there, bump the version number on its first line; every task checked under
the old rules is then re-checked automatically before it can ship.

The step-by-step procedure (what to run when results come back, and how to bundle and upload) is the
"CURRENT SEQUENCE" at the top of [../ekw/svc-return-runbook-2026-09-21.md](../ekw/svc-return-runbook-2026-09-21.md).

## What we are trying to do

Each task is a finance job: a folder of source files (spreadsheets, PDFs), an instruction ("act as the VP of
Marketing and quantify X"), a built-in correct answer (the "golden"), and a rubric (a checklist the grader
uses to score a submission). Our job is to make each task good enough that **DataOS** accepts it. DataOS is
the grader Turing runs. It is the only judge that counts. Our own opinion of a task does not.

## How DataOS grades (the checks and the reviews)

Two stages:

1. **The oracle (automatic).** It runs the task's own golden answer through the scorer. The golden must score
   a perfect **1.0**. If the golden cannot pass its own rubric, the task is broken before anyone looks at it.
2. **The reviewers (AI, picky senior-reviewer style).** In the earlier setup, two or three GPT-5.6-sol reviewers
   read the whole task; in the current pipeline the reviews are four Answer Check
   reviews. Each review returns a verdict: **accept**, **needs revision**, or **reject**, plus a list of any
   problems marked **major**. A problem is filed under one of these labels:
   - **1.1** the golden is wrong (fails its rubric, or its numbers do not come from the source files)
   - **1.3** the instruction is ambiguous
   - **1.4** the rubric grades something the instruction never asked for (too strict)
   - **1.5** the instruction asks for something the rubric never checks (missing coverage) - **this is the one
     that fails us most**
   - **1.6 / 1.7** other rubric or internal-consistency problems
   - **1.8** packaging bombs: too many checklist items in one group, garbled filenames, missing files

**The pass rule (earlier setup, since replaced; see the update at the top):** a task passed if the
reviewers found **0 major problems**, with 2 of 3 agreeing. "Needs revision with 0 majors" counted as a pass. A
single reviewer finding one major failed the task. Under the current rule a major in any one of the four Answer
Check reviews fails the task, and it passes only when all four are clean.

## What all the evidence says (about 45 tasks graded now)

Four batches have come back from DataOS:

| batch | accepted |
|---|---|
| wave 1 | 1 of 8 |
| resubmit round 1 | 1 of 7 |
| resubmit wave 2 | 3 of 7 |
| dual-basis batch | 0 of 11 |

Almost every rejection is **1.4 or 1.5** (alignment and coverage). The hard lesson underneath the numbers:
**our own checks and our own AI reviewers cannot predict what GPT will call a "major."** Our reviewers see
the same problems but grade them "minor," so they wave through tasks GPT then rejects. We call this the
**severity wall**. On one batch our Opus reviewer accepted every task while both GPT reviewers rejected them
all. So we cannot certify "this will pass" by reviewing it ourselves. Only a DataOS return tells us.

## What we CAN catch ourselves, for free

Some defects need no judgment - a script catches them every time, so we fix them before upload and never
waste a paid DataOS grade on them:

- too many checklist items in one rubric group (a "grammar bomb" that crashes the grader) - split the group
- garbled characters in filenames - repair them
- the golden does not score 1.0 - rebuild it until it does
- a rubric line that accepts two different answers ("Expected: X or Y") - delete the wrong alternative

## Why we kept failing the same tasks (the honest post-mortem)

This was our third resubmission of some tasks, and we kept getting rejected on new coverage gaps. The reason:
**rounds 1 and 2 we fixed only the one problem DataOS named, then stopped.** But GPT re-audits the entire
task every time, so each round it finds the NEXT hole we had not fixed. We were playing whack-a-mole against
a reviewer that checks the whole board.

## The change this round (the overhaul)

**Stop point-fixing. Do the full coverage sweep on every task, before upload.** A point fix patches the one
cell DataOS complained about. The full sweep rebuilds the rubric so that passing it *proves* the task was
done right, which is the only thing that survives a fresh reviewer. Plus: fix the free deterministic defects
first, keep DataOS as the only real gate, and use the cheaper grading config (below) so each wave costs less.

### How to do the full coverage sweep (the actual HOW, step by step)

This is the part worth keeping. Do it in order, on the real files:

1. **List every fact the task asks for.** Read the instruction and write down each thing it wants: every
   total, every date, every per-row number, every named deliverable.
2. **Re-derive each fact yourself from the source files.** Open the spreadsheets and PDFs and work out the
   correct value on your own. Do not trust the golden - if the golden disagrees with the sources, the golden
   is wrong, so fix it.
3. **Match each fact to the rubric line that forces it.** Go fact by fact:
   - no line checks this fact? **Add one**, graded against the value you derived.
   - a line only checks part of it (10 of 24 rows, 5 of the employees)? **Extend it to the full set.**
   - a line accepts a wrong alternative? **Delete the wrong one.**
4. **Try to cheat.** Ask: could someone pass every rubric line and still be wrong (a wrong-basis number, an
   accepted alternative, a fact nothing forces)? If yes, tighten the rubric until you cannot.
5. **Re-check the golden still scores 1.0** after your edits.
6. **Repeat 1 to 5** until there is no partial coverage, no way to cheat, every fact is forced, and the golden
   scores 1.0.

The one-line test: **if someone passes the whole rubric, the task must have been solved correctly.** If that
is not true, there is a hole, and a fresh GPT reviewer will find it.

## Where the work runs

We fix tasks on "lanes" - 16 sandbox workers, each an independent Claude session. One task, one lane, one
strong agent (Opus or Fable), directed by that task's COMPLETE list of every DataOS finding it has ever
received (every round, both reviewer seats, majors and moderates, full text - not a summary). As of
2026-09-21 we dropped the 33 tasks already finished by the team (169 real tasks remain). We do NOT run a
generic shared brief across the pool: that batch approach was tried and came back 0 of 17 from DataOS, so it
is retired. DataOS grades only what we upload, and we upload in small measured waves, not all at once -
because the severity wall means a locally clean task is still only a guess until DataOS returns.

## The cheaper grading config

This section describes the grading setup of 2026-09-21, before the 4 Reviewers pipeline. Its seat list and costs do
not describe the current pipeline.

The full grade costs about $18.46 per task (oracle + 2 Opus solvers + 2 GPT reviews + 1 Opus review + a QC
seat). We moved to: **oracle + 2 GPT-5.6-sol solvers + 2 GPT-5.6-sol reviews, nothing else** - about $6 per
task, roughly 68% cheaper. Why it is safe to drop the others: the accept/reject decision hinges on GPT
severity grading, which only GPT-5.6-sol does well, so an Opus review seat added almost nothing. The tradeoff:
with 2 reviews instead of 3 a single reject fails the task, so the bar is slightly stricter.

## Why earlier rounds kept failing, and what we changed (2026-09-21)

We rejected the same tasks 4-5 times. Each round we fixed exactly what GPT complained about, resubmitted, and
GPT rejected on something new. Three reasons, now fixed:

1. **We handed the fixer only a piece of the problem.** Our old notes cut the findings short and kept only the
   latest round. The fixer closed that piece, and GPT rejected on the piece we cut. Now the fixer gets the
   COMPLETE history: every round, both reviewers, full text.
2. **We only fixed what GPT had already named.** But GPT re-reads the WHOLE task every round and finds new
   problems. So even a perfect fix of the named issues fails on a fresh one. Now the fixer audits EVERY rule
   in the rubric against the instruction, not just the flagged ones.
3. **We kept ADDING rules to close gaps, and every added rule became the next rejection.** Now we fix by
   DELETING or loosening rules the instruction does not actually require.

Two cheap helpers on top: a script greps for the common bad-rule shapes (minimum counts, diversity rules,
whitelists) before the expensive rebuild, and an independent reviewer checks the fix is really enough before
we spend a grade. Honest odds: this moves a task's chance of a clean pass from about 6-12% to about 40-50%.
Not a guarantee.

**One deeper problem, corpus-wide:** the solver can see more files than the grader can open (126 vs 33 on one
task). So a solver can cite a file the grader can't check, and the grader either wrongly fails it or lets a
made-up citation through. The clean fix is to trim the task's file set so the solver only sees what the grader
can check (the extra files are personal tax/payroll forms the task says to ignore anyway). That is an
environment change, decided per track.

## What is still unsolved

The hardest 1.4/1.5 calls still depend on GPT's severity, which we cannot run locally, so DataOS stays the
only real verdict. The two levers that reach it: **(a)** get GPT-5.6-sol as our own reviewer (the standing ask
to Shyam), or **(b)** rebuild each task individually with the changes above and let DataOS gate. We are doing
(b) now while (a) is pending.
