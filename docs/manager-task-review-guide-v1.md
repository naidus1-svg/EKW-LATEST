# OLD, DO NOT USE: How to review a task: approve or deny, and what to reply

Status: stale. Task review rules v2 and the manager run sheet replace it. Do not follow its commands.

Older status line, kept: the nine DENY rules in this guide are replaced by [Task review rules v2](task-review-rules-v2.md); read that file first.

This is the full method for deciding APPROVE / DENY / CAN'T JUDGE YET on a task, and for writing the reply to the author in the same style every time. Follow it step by step. You do not need anyone else to make the call.

## 0. The one-minute version

1. Find the live task (not an archived version) and read its **eval runs** and **both Comprehensive Reviews**.
2. Check the three gates: 2 Oracle runs at 1.0, model runs exist, two Comprehensive Reviews exist and the task is shared with you.
3. Look at every issue the reviews list, **including minors**. Run each against the 9 DENY rules (section 3).
4. If any rule fires, it is a DENY, even when the review calls it minor.
5. If only the allowed issues are left (section 4), it is an APPROVE.
6. Reply in the author's thread in the format in section 6.

## 1. What you need before you can judge

You need all four. If one is missing, the answer is CAN'T JUDGE YET and you say which one.

| Needed | Where | If missing |
|---|---|---|
| The task is shared with you (you can open it) | DataOS task page | "share it with me as admin, i can't open it" |
| At least 2 Oracle runs at 1.0 | Evaluations list on the task | "run oracle once more and repost once you have two at 1.0" |
| Model runs (Codex and Terminus) | Evaluations list | ask for the model runs |
| Both Comprehensive Reviews, run on the current version | Verifications list | "rerun the reviews" |

Check which version is live. A dataset holds many versions of the same task and most are archived. Always judge the one that is not archived. If the author linked an archived task, tell them: "that's an archived version, the live one is X, repost the current link."

Check the dates. If the reviews are older than the latest model or Oracle runs, or the task id is the same one that was already denied and nothing changed, the author has not fixed anything. Say so.

## 2. How to read the results

For each task look at:

- **Oracle runs**: every one should be 1.0. Fewer than 2 means CAN'T JUDGE YET.
- **Model runs** (Codex, Terminus): note the scores. If every model scored 100%, always say so in the reply, because that means the task is too easy.
- **A model run at 0.0**: find out why before you blame the task. Usually it is the model's own error (a broken formula, a missing file) or the judge hit an API usage limit. Both are not task defects. If it is a usage limit, ask for a rerun.
- **Both Comprehensive Reviews**: for each one read the verdict, the major and minor counts, and the text of every failed check. The check ids look like 1.1 to 1.9. The ones that matter most:
  - 1.1 solvability / golden answer correct
  - 1.3 ambiguity
  - 1.4 criteria require only what the instruction asks for
  - 1.5 rubric coverage and calibration (bundling, duplicates, coverage gaps)
  - 1.7 golden prose and tables match their own numbers and the sources
  - 1.9 metadata

Two reviews can disagree. Use the stricter one on facts, not on opinion. If one review says accept and the other lists a real defect, the defect counts.

### Fast way to pull everything (optional)

Open any DataOS page while signed in, open the browser console, and paste this. It only reads (GET requests) with your own signed-in session. Replace the task id.

```js
const dos = async p => { const t = sessionStorage.getItem('data-os.access-token'); const tok = t.startsWith('"') ? JSON.parse(t) : t;
  const r = await fetch(p.startsWith('http') ? p : 'https://api.data-os.turing.com/api/' + p, { headers: { Authorization: 'Bearer ' + tok } }); return r.json(); };
const all = async p => { let out = [], u = p; while (u) { const j = await dos(u); out = out.concat(j.results || []); u = j.next; } return out; };
const id = 123456; // <- task id
const task = await dos(`datasets/tasks/${id}/`);
const evals = await all(`evaluations/?task=${id}&page=1&archived=false`);
const vers = await all(`verifications/?target_type=task&target_id=${id}&page=1&level__gte=2&archived=false`);
console.log(task.name, task.status);
evals.forEach(e => console.log(e.agent?.display_name, e.model?.display_name || '', e.latest_run_summary?.aggregate_reward));
for (const v of vers) { const d = await dos(`verifications/${v.id}/`); console.log('REVIEW', v.id, v.created_at, d.turns?.at(-1)?.output?.response?.slice(0, 3000)); }
```

If it does not work, do the same by hand: open the task, read the Evaluations list, then open each Comprehensive Review and read its failed checks.

## 3. The 9 DENY rules

DENY if any of these is true, **even if the review calls it minor**.

1. **One check grades many separate facts at once**, so one small miss fails the whole check.
2. **The same fact is graded twice** (in two checks or two deliverables), so one mistake costs twice.
3. **Graders gave different results on the same answer** (pass, fail, pass).
4. **The answer key (golden) has a factual error or contradicts the source files or itself.**
5. **A check requires something the prompt never asks for.** Search the instruction and every source file before deciding this.
6. **A judge must check facts against source files it isn't given.**
7. **The grading script can crash and give no score.**
8. **A major issue that is not fixed and not explained as a false positive in writing.**
9. **Exact file-path or wording matching** that fails a correct answer written differently.

### What these look like in practice

- Rule 1: "all 52 starting rents in one criterion", "April, May, June and the quarter total in one pass/fail", "ceilings, prices and the subtotal in one check", a check that says "checked for every case" over a table.
- Rule 2: the same figure appears in 5 to 14 checks, or one fact is graded in the brief and again in the workbook.
- Rule 3: the review says the judges disagreed on an identical answer. A common cause is the literal text `None` in a cell being read as blank.
- Rule 4: the golden memo says one thing and its own workbook says another, a ranked table that contradicts its own labels, a date in the summary that the schedule disproves, a total that does not add up.
- Rule 5: required formula counts ("at least 40 cross-sheet formulas"), a prescribed outcome when the prompt allows judgment ("must decline", "must recommend X" when grant or decline is allowed), required wording ("must say write-down"), a required section the prompt never asked for, an unstated word-count band instead of the page count that was asked for, requiring a source for a number that the cited source does not contain.
- Rule 9: only one narrow list of acceptable answers, or only exact labels accepted when equivalent labels are allowed.

### A false-positive claim from the author

Authors often write "the minor is a false positive". That alone does not clear anything. It clears only if the author explains it in writing and the explanation is correct. "Having multiple grades per one check is not a false positive." If the claim is wrong, say why in one sentence and name the check.

## 4. What is allowed (APPROVE)

If the only remaining issues are these, APPROVE:

- Checks that are **too easy to pass**: a coverage gap, a wrong answer that could still pass, a decoy formula or hard-coded value that could pass, blank cells that could pass.
- Oversized files or environments.
- Missing or incomplete metadata (domain, occupation, sector, subdomain, task_type).
- Small single-fact checks.
- Wording the rubric accepts either way.
- Formatting or layout polish on the golden that does not change a fact.

Note the difference. "A wrong answer can pass" is allowed (too easy). "A correct answer fails" is a deny (rules 1, 5, 9).

## 5. Quick decision table

| Situation | Verdict |
|---|---|
| Not shared with you | CAN'T JUDGE YET |
| Fewer than 2 Oracle runs at 1.0 | CAN'T JUDGE YET |
| No model runs, or only one real review, or reviews older than the latest changes | CAN'T JUDGE YET |
| Any of rules 1 to 9 fires | DENY |
| Only allowed issues remain | APPROVE |
| Same task id as a prior denial and nothing changed | DENY, say nothing changed |
| Archived link posted | tell them the live link |

Always add one line when **every model scored 100%**: "both models scored 100%, so it's on the easy side." It does not block an approval. Add "raise difficulty if you can" only on a deny.

## 6. How to reply

Work out the verdict in this shape (for yourself or an assistant):

```
Verdict: APPROVE / DENY / CAN'T JUDGE YET
Why: 1 to 2 plain sentences, no jargon.
Fix: numbered list, each naming the check id and exactly what to change.
Slack reply: 2 to 3 lowercase sentences to paste to the author.
```

Then send **only the Slack reply** to the author, in their thread, with their @tag at the front.

### Where to post it

Reply **in the thread under the author's own post**, not as a new message in the channel and not in a DM, unless they DM'd you. Tag them. If the post has already been answered by another manager, do not answer again.

Before replying, check the thread for an answer already given. Do not approve something another manager already denied without telling them.

### Voice

Short, direct, lowercase, specific. Name the check id and what to change. No hedging, no apologies, no thanks, no emojis, no long explanations. State the verdict first.

Approve:

```
@author hlt-190 approved, submit as per sop.
@author fin-314 approved, submit as per sop. both models scored 100%, so it's on the easy side.
```

Deny (name the rule's problem and the fix):

```
@author gtm-129 denied for now. each account check needs all six fields right to pass and the all-account presence check re-grades what the account checks already cover. split them into separate checks with the same total weight and drop the presence check.
```

```
@author task_376_v3 denied for now. each monthly-trend check grades april, may and june in one pass/fail, so one wrong month fails the whole check, and we fix that even when it's marked minor. split them into separate month checks with the same total weight.
```

Deny where the golden is wrong:

```
@author fin-310 denied for now. the golden contradicts itself: the memo and the workbook rank f5 at 7 as "routine - no action" and f6 at 8 as "priority - verify response". fix the order or the labels, then rerun and repost.
```

Deny where a check asks for something the prompt never asks for:

```
@author sco-272 denied for now. v10b requires the memo to say write-down or dead money but the prompt only asks for a depth rationale. accept any depth rationale, rerun and repost.
```

Deny where the author claims false positive:

```
@author sco-254 denied, those aren't false positives. the same hours agreement is graded in both deliverables_02 and deliverables_07, so one miss costs twice. merge the duplicates, rerun and repost.
```

Nothing changed since the last denial:

```
@author fin-462 denied. nothing has changed on the task since it was rejected (same runs and reviews). fix the flagged checks, rerun and repost.
```

Can't judge yet:

```
@author fin_136 can't be approved yet, it only has one oracle run. run oracle once more and repost once you have two at 1.0.
@author 194222 can't be judged yet, share it with me as admin since i can't open it.
@author fin-219 can't be judged yet. the model runs are new but both reviews are from before them, so rerun the comprehensive reviews and repost.
```

Wrong link:

```
@author 185224 is an archived version so i can't review it. the live task in that dataset is 189934, repost the current link.
```

When you reply to several tasks from one author in one message, put each task on its own line with its verdict.

### Rules for the reply text

- Name the exact check id (v37a, v10b, deliverables_02 lines 79-80) so the author can find it.
- State the fix, not only the problem. The fix usually keeps the total weight the same.
- Say it once. Do not list five issues when two are enough to deny. List all of them if the author keeps resubmitting with partial fixes.
- Never paste expected values, tolerances or the golden's numbers into a reply. The authors are not the graded party but the reply may be copied around. Name the check, not the answer.
- Do not promise a date or a "next review". Just give the verdict.

## 7. Process rules that always apply

1. **Oracle needs 2 runs at 1.0.** One run is not enough.
2. **Do not treat "minor" as safe.** Rules 1 to 5 deny on minors.
3. **"The reviews pass" is not the test.** Two clean reviews can still miss a bundled check or a golden error. If a review shows a real defect, it counts.
4. **Judge what is live.** Use the non-archived task. If the id is the same as one already denied, confirm something actually changed (new version, new reviews).
5. **Do not change a task yourself.** You only judge and reply. The author fixes and reposts.
6. **Credits and access are separate requests.** If someone asks for DataOS credits, that is not a review. Do not mix it into a verdict.
7. **Do not name colleagues' mistakes in public threads.** Name the task and the check.
8. **If a task is in the consolidated sheet:** a fixed task gets a new row with the new link and is marked as an EQC revision (EQC is explained in the [glossary](../README.md#glossary)). Do not overwrite the old row.

## 8. When you are not sure

- If you cannot tell whether a check really is outside the prompt (rule 5), open the instruction and the source files and search. If it is not asked for anywhere, it is a deny.
- If the only issue is a coverage gap and you are unsure whether it counts as too easy, it does: approve.
- If two reviews disagree about a fact, check the fact in the source file yourself.
- If it is a customer-facing or high-stakes call and you still cannot decide, reply CAN'T JUDGE YET with the exact question for the author and escalate to the team lead in the managers channel. Do not guess.

## 9. Prompt to use with Claude (copy and paste)

Use this when you want an assistant to do the analysis. Paste the DataOS task link, the eval results (Oracle and model rewards), and both Comprehensive Review JSONs. If you have the task files (instruction.md, judge.toml, source files), paste those too.

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

An assistant reading only the review text can miss things. Before you send a deny, make sure the check it names really exists in the review or the judge file.
