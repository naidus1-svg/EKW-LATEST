Status: stale. Task review rules v2 and the manager run sheet replace it. Do not follow its commands.

# Approval review prompt

For reviewers (Khiem, Jaya, Luiz, Sanskar, Salman). Paste the prompt below into Claude, then paste the task's review data under it. It returns APPROVE, DENY or CAN'T JUDGE YET, the fixes, and a Slack reply for the author.

These are the rules used for every approval and denial on 2026-09-29. See also `task-failure-checklist.md` in this folder. Oracle and Comprehensive Review are explained in the [glossary](../README.md#glossary). The nine DENY rules in the prompt below are the ones that [task review rules v2](task-review-rules-v2.md) replaces.

```
You are reviewing a task submission. Decide APPROVE, DENY, or CAN'T JUDGE YET.

I will paste the DataOS task link, the eval results (Oracle and model rewards), and both Comprehensive Review JSONs (verdict, major/minor counts, failed checks). If I also paste task files (instruction.md, judge.toml, source files), use them.

CAN'T JUDGE YET if: there are no model runs, fewer than 2 Oracle runs at 1.0, no Comprehensive Reviews, or the dataset isn't shared with me.

DENY if any of these is true, even if the review calls it "minor":
1. One check grades many separate facts at once, so one small miss fails the whole check.
2. The same fact is graded twice, so one mistake costs twice.
3. Graders gave different results on the same answer (pass, fail, pass).
4. The answer key has a factual error or contradicts the source files.
5. A check requires something the prompt never asks for. Search every source file before deciding this.
6. A judge must check facts against source files it isn't given.
7. The grading script can crash and give no score.
8. A major issue that isn't fixed and isn't explained as a false positive in writing.
9. Exact file-path or wording matching that fails a correct answer written differently.

APPROVE if the only issues are: checks that are too easy to pass, oversized files, missing metadata, small single-fact checks, or wording the rubric accepts either way.

Always say if every model scored 100%, because that means the task is too easy.

Reply with:
Verdict: APPROVE / DENY / CAN'T JUDGE YET
Why: 1 to 2 plain sentences, no jargon.
Fix: numbered list, each naming the check id and exactly what to change.
Slack reply: 2 to 3 lowercase sentences I can paste to the author.
```
