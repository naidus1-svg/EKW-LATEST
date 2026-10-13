# SVC-PC return runbook: fire when the resubmit comes back (ARMED 2026-09-21)

## CURRENT SEQUENCE (v8.1, 2026-09-22) - use this; the sections further down are history

Why this exists: [batch18-return-analysis-2026-09-22.md](batch18-return-analysis-2026-09-22.md). Four stale
zips shipped because a hand-written script bundled whatever sat in `_v7/ready/`. Each step below is a
sanctioned tool that re-derives state from disk; the hook `enforce_svc_bundle_gate.py` (a Claude Code hook installed under `~/.claude/hooks`) blocks the
hand-built alternatives. A "lane" is one Claude Max login (`/root/.claude-<letter>`) on the sandbox that runs one
task fix at a time, and the "pool" is the set of workers, one per lane (see the team README, step 2). Sandbox = `ssh -p 2222 -i ~/.ssh/kiem_sandbox root@136.113.78.105`; tools live in
`/root/qc/tools/`, python is `/root/venv/bin/python3`.

### Return intake (the moment a `*_with_runs*.zip` lands)

1. **Copy the return up, verify the bytes:** `scp -P 2222 -i ~/.ssh/kiem_sandbox "<Downloads>/<name>_with_runs.zip"
   root@136.113.78.105:/root/qc/_returns/`, then compare `ls -l` sizes on both sides.
2. **Dry run the intake:** `python3 /root/qc/tools/svc_record_return.py /root/qc/_returns/<name>_with_runs.zip`.
   It prints PASS/FAIL per task and what it will write. **Check that its PASS or FAIL line applies the current
   rule** (a task fails the pipeline if any review in the return reports a major, and passes only when every review
   is clean): a copy of the tool from before 2026-10-05 passes a task when at least two reviews are clean, and it does
   not read Answer Check replies, which carry `findings` instead of `checks` (checked 2026-10-05 by running
   the review parser on synthetic reviews: none of four clean Answer Check replies is read, and four reviews with one
   major still meet the at-least-two-clean count). Read the four reviews against the rule yourself before step 3.
3. **Apply:** same command with `--apply`. Passers go on `_v7/accepted.txt` (frozen). Each reject gets
   `_deepfix/<task>.lastreject.sha` from DataOS's own copy of the graded bytes, its verify/regrade records and
   ready zip archived, its claim released, and it moves to the head of `_v7/queue.txt`. Read-back asserted.
4. **Refresh findings + briefs (laptop):** `python tools/svc_harvest_all_returns.py --briefs`, then
   `python tools/svc_build_directed_briefs.py <each reject>` (each brief embeds `tools/svc_fix_method_rules.md`),
   then scp `_deepbriefs/<task>.md` to `/root/qc/_deepbriefs/` and strip CRLF (`sed -i "s/\r$//"`).
5. **Document the passers:** `/task-doc <passers>` (builds the QCR doc, the one-page document named QCR_<name>_<date> that is handed to the QC team; see
   `../skills/task-doc.md`). Do not share the passers' DataOS dataset with the TFRL QC team and do not post in #tfrl_qc: since 2026-09-24 the batch dataset Khiem builds is the one shared with `TFRL_QC`, and authors never send tasks to the QC team themselves (`docs/qc-intake-process.md`). Per the [QC SOP, section 7](../../docs/QC-SOP-first-run.md#7-package-and-hand-off), log the task in the consolidated sheet as a pass; Khiem collects passing tasks into batches of 50 or more, uploads each batch as one dataset under the tasks' original names, and sends it. The earlier rule here, to share each passer's dataset with `TFRL_QC`, is retired; this runbook does not say whether `Ardeshir_team` still needs access, so ask Khiem. The SOP (section 7) says to share the dataset that holds the task with Khiem as ADMIN and with `Andrew_team` as admin (for EKW, also with Luiz as ADMIN). Check the consolidated tracker for duplicates first.
   **QC-team SOP (doc 1IL2s3ez..., section 7c; applied 2026-09-23):** a task another person already submitted
   and PASSED goes in the MAIN table with EQC Status `Skip- duplicate` (`svc_consolidated_record.py --dup`),
   never under the lower Duplicates heading and never marked for manual QC. A task whose earlier submission is
   under Rejected gets F `EQC Ready Revision` + the `Resubmission change` column note (the tool does both).
   Never move rows. The QCR doc must carry Purpose, Scope, Dataset structure, Expected outputs, Known
   limitations or review notes, and the contact (template in `/task-doc`). Column C is a LINK (`--doc-url`,
   required). Verify links with `python tools/svc_consolidated_links.py`.
   Cohort check on every return: `cd /root/qc && python3 tools/svc_return_cohort.py _returns/<zip>` (pass
   rate for verify_capped vs full READY, plus each pass's rev id for the QCR doc).
6. **Pool:** if it is running, it picks the requeued rejects up on its next claim (workers poll every 2 min
   since 2026-09-23; they no longer exit on an empty queue). If it is stopped, relaunch per "Pool control" below.
   **Dead-ends are AUTOMATIC since 2026-09-24 (owner):** a task that hits the same blocker STUCK_LIMIT times in
   normal mode adds itself to `_v7/decide.txt`, logs AUTO-DECIDE (also in `_v7/auto_decide.txt`), and the pool
   releases it for a decide-mode round (runner exit 30). Only a task that also gets stuck IN decide mode parks.
   A lane usage limit (runner exit 10) never parks a task any more; the pool always releases it. Before this, 3 dead-ends
   sat parked without ever trying decide mode and 6 tasks sat parked as "transient x3" with nothing wrong with them.
   Manual path, still valid for DEFERRED (attempt-cap) tasks: put it on `_v7/decide.txt` and back in the queue via
   `tools/svc_release_launch.sh "" <task>`; add it to
   `_v7/priority.txt` so it runs soon. Its next run is a DECIDE run (see the team README, step 2). Read
   `_deepfix/<task>.decision.json` afterwards: every KEEP overrules a DataOS reviewer and must cite a source record.
   Before any of that, check whether the park was a lane limit: `grep -i "weekly limit" _v7/logs/<task>.log`.
   A weekly-capped lane refuses every call, so the task was never really tried; just release it.
   **A park is never a dead end until its blocker is classified TASK or GATE (owner, 2026-09-24).** Every cycle,
   read `_v7/gate_errors.txt` and, for each new decide-mode park in `_v7/parked.txt`, read the task's
   `_deepfix/<task>.regrade.json` (`verdict`, `why`, `llm_regrade.ran`, `direction_B.proof`) and its
   `decision.json` (`gate_note`). A GATE-ERROR verdict, a re-grade that never ran, or a decision that disputes
   the gate with evidence is a bug in our tools: fix the tool, add a regression test named after the task, then
   release. Never recommend releasing (unclaiming) a task on the park line alone. On 2026-09-24, 7 of 8
   "genuinely stuck" parks were two `svc_eval_regrade.py` bugs (kept-criteria exemption applied after the
   re-grade decision; checks.py criteria invisible to the coverage check), fixed and covered by
   `tools/test_svc_eval_regrade_gate.py`. The runner now parks these as `GATE problem` in `gate_errors.txt`.
   **Ship every READY task each cycle** (owner, 2026-09-23): no minimum bundle size.
   **Restarting one task:** do not kill its runner and relaunch it on the same lane with `svc_release_launch.sh`.
   The pool worker on that lane sees it go free and claims the next queue task in the gap, which put two runners
   on lane t (2026-09-24). Kill the runner, release the task (`svc_release_launch.sh "" <task>`), make sure it is
   at the queue head (priority.txt), and let the pool claim it.

### Bundling and upload (the only path)

7. **Build the bundle on the sandbox:** `python3 /root/qc/tools/svc_bundle_upload.py bundle --name <name> --from-ready`
   (or `--tasks T1 T2 ...`; `--size 10` splits into parts). Stale tasks are EXCLUDED and named; read the
   REFUSED list. Output: `/root/qc/_bundles/<name>.zip` + `.manifest.json`.
8. **Check and pull in ONE command** (the hook blocks a pull without it):
   `ssh ... 'python3 /root/qc/tools/svc_bundle_upload.py check /root/qc/_bundles/<name>.zip' && scp -P 2222 -i ~/.ssh/kiem_sandbox root@136.113.78.105:/root/qc/_bundles/<name>.zip C:/Users/khiem.doan_turing/svc-v8-upload/`
   Then compare the byte size on both sides.
9. **Upload** (delegated to Claude since 2026-09-22 for bundles that passed `check`): DataOS > Datasets > New
   dataset, tag `cirrus sleep`, Create & upload; wait until the dataset's `Tasks (N)` equals the bundle's task
   count (a 300 MB zip takes ~3 min to ingest; the pipeline only runs on tasks READY at launch), then Run
   pipeline > "ManualQC automated QC pipeline 4 Reviewers" (version 8 on 2026-10-05; the "NO CLAUDE" pipeline is
   retired). If more than an hour passed since step 8, re-run the `check` first; a task can be reworked in between.
   **DataOS rejects zips over 500 MB (owner, 2026-09-23).** If a bundle is bigger, split it BEFORE upload:
   `python3 /root/qc/tools/svc_split_bundle.py <name>` (dry run) then `--apply`; it moves the unuploaded
   bundle's shipped records to `_v7/shipped/_not_uploaded/` and rebuilds `<name>a` / `<name>b` through the
   bundler, so every freshness gate runs again. The laptop link is ~0.5 MB/s and resets on long pulls: pull
   with `-o ServerAliveInterval=15` and compare the byte size, retrying on mismatch.
10. **Never-graded (harvest) tasks:** `svc_bundle_upload.py bundle --name <name> --first-grade --tasks ...`. It
    proves each task is absent from every return zip. A bundle built before 2026-09-22 has no manifest; check
    it with `svc_bundle_upload.py check <zip> --legacy` (content vs current corpus).

### After a rules change

11. Edit `tools/svc_fix_method_rules.md`, bump `METHOD_VERSION` on line 1, deploy it to `/root/qc/tools/`, then
    `python3 /root/qc/tools/svc_bundle_upload.py sweep --apply`. Each zip verified under the old version is
    retired and requeued; the runner re-verifies it (mode `reverify`, no edit first).

### Pool control

- **Idle lanes with work stuck (check every cycle, 2026-09-23).** Workers exit when the queue has no unclaimed
  task, and the pool starts a new pass only when every worker (including ones waiting out a capped lane) returns,
  so released tasks can sit for hours. Also watch for `transient x3` parks: the pool stops retrying them though
  nothing is wrong with the task (L3 21-0-0 and 53-0-0 sat idle that way). Probe free lanes, then
  `bash /root/qc/tools/svc_release_launch.sh "<free lanes>" TASK ...` releases each task (claim ->
  `_v7/claims_released/`, retries reset, back in the queue) and launches one runner per free lane.
- Lane time report: `python3 /root/qc/tools/svc_lane_time.py` (last 24h: attempts, wall time per task, time by
  phase, loop-back reasons).

- Stop: `bash /root/qc/svc_v7_stop.sh` (kills pool, runners, lane agents, oracles). Confirm with
  `pgrep -f "[s]vc_v7_lane_runner" | wc -l` = 0 in a SEPARATE ssh call.
- Relaunch, in a separate ssh call, through a login shell:
  `rm -f /root/qc/_v7/daemon.stop; (setsid nohup bash -lc "bash /root/qc/svc_v7_pool.sh" >> /root/qc/_v7/pool.stdout 2>&1 < /dev/null &); exit 0`
  (stdout goes to `pool.stdout`, not `pool.log`: `plog` already writes `pool.log`, so sending stdout there
  doubles every line.)
- Swap the pool controller WITHOUT stopping work (since 2026-09-22 21:50Z): `pkill -TERM -f "[b]ash
  /root/qc/svc_v7_pool.sh"` kills only the pool and its workers; runners keep going. Relaunch as above. The new
  pool starts a worker on EVERY candidate lane; each waits for any running runner on its lane (adopt), then for
  its own window (`wait_ok`, re-probe every 900s, up to 14h), so capped lanes rejoin by themselves instead of
  idling until the pass ends. Caveat: a runner orphaned by the swap that exits 10 (transient) leaves its claim
  dir behind; release it by hand (`rm -rf /root/qc/_v7/claims/<task>`) if the task has no live runner, no
  ready zip, and is not in parked.txt.
- Attempt cap (since 2026-09-23): a runner stops at 10 attempts and DEFERS the task to `_v7/deferred.txt` (claim
  kept, so no lane re-takes it). When the queue has no claimable tasks left, requeue the deferred ones: append
  their ids to `_v7/queue.txt`, remove their `claims/<task>` dirs and `retries/<task>` files, and empty
  `deferred.txt`. Evidence for 10: 41 of 42 converged tasks needed <= 8 attempts.
- Tests to run after any change to these tools: `python tools/test_svc_bundle_upload.py` (21) and
  `python ~/.claude/hooks/test_enforce_svc_bundle_gate.py` (19).

---

> **UPDATED 2026-09-22 - the scale-up is now the v7 GO-triggered daemon, NOT the old overnight script.**
> The lane machinery is already deployed AND ARMED on the sandbox: a `flock`-singleton daemon
> (`/root/qc/svc_scaleup_daemon.sh`, kept alive by a `* * * * *` cron re-arm) is polling for
> `/root/qc/_v7/GO`, with the reject pool pre-staged (`_v7/queue.staged.txt`, 72 tasks), every task's
> COMPLETE brief in `/root/qc/_deepbriefs/`, and the graded baselines in `/root/qc/_returns/`. **The proof
> task is now SVC-PC-16-1-0, not "5 of 7."** When DataOS ACCEPTS 16-1-0 (0 major from the GPT seats), the
> ONLY action - from any terminal, laptop closed - is:
> ```
> ssh -p 2222 -i ~/.ssh/kiem_sandbox root@136.113.78.105 'touch /root/qc/_v7/GO'
> ```
> The daemon then promotes the staged queue to live and launches `svc_v7_pool.sh` detached; it runs one Opus
> per lane (work-stealing, transient-retry, self-heals across 5h window resets), each task going
> brief -> rebuild -> oracle 2x -> growth guard (HARD) -> on-lane adversarial verify -> gated zip into
> `/root/qc/_v7/ready/`. Monitor: `tail /root/qc/_v7/pool.log`. Stop: `bash /root/qc/svc_v7_stop.sh`. The old
> `svc_dataos_overnight.sh`/`svc_dataos_fix.sh` path below (Sonnet-default, laptop-launched) is SUPERSEDED;
> do not run it. Uploading the `ready/` zips is still the user's action (DataOS is browser-gated).


Companion to the live plan [plan-2026-09-21-v6-dataos-as-gate.md](plan-2026-09-21-v6-dataos-as-gate.md).
This is the exact, ordered sequence to run the moment the resubmit `_with_runs` zip lands in `Downloads/`.
It is agnostic to which task ids are in the batch: every tool enumerates the zip. Nothing here uploads;
building and uploading the resubmit zip stays the user's action.

Two things happen on return: (A) document the passers, (B) if the proof gate clears, deploy the lanes
overnight on the full reject pool. Do BOTH; they are independent.


**Ownership gate (2026-09-25):** every cycle runs `python tools/svc_build_freeze.py --push`. It rebuilds the SVC and EKW do-not-touch lists from the trackers: lanes and bundlers touch a task only if it is assigned to us on its Combined tracker and not a live submission on the consolidated sheet (task from column E, EQC Status column H; rows under the Rejected heading never block). Unassigned / "Available - claim me" rows are off-limits until claimed on the tracker. If the push prints "queued tasks now off-limits: [...]", remove those from the queue and stop any runner on them. The pool skips listed tasks at claim time (`tools/test_svc_v7_pool_offlimits.sh`).

## Step 0 - read the live plan in full (hard rule, non-negotiable)

Post-compaction or fresh session: read `ekw/plan-2026-09-21-v6-dataos-as-gate.md` end to end, then probe
the lanes before asserting anything is blocked. A capped lane is ONE account's weekly limit, not the fleet.

## Step 1 - split the return: passers vs still-rejected (laptop, deterministic)

```
ZIP="C:/Users/khiem.doan_turing/Downloads/<the-resubmit>_with_runs.zip"
python tools/svc_dataos_returns_parse.py "$ZIP" --out ekw/_return_split.json | tee ekw/_return_split.txt
grep ' -> PASS' ekw/_return_split.txt | awk '{print $1}' > ekw/_passers.txt
grep ' -> FAIL' ekw/_return_split.txt | awk '{print $1}' > ekw/_round2.txt
```

Pass rule (QC SOP, section 6b, since 2026-10-05): a task fails if any of its four Answer Check reviews reports a
major, and passes only when all four are clean. Check the tool's PASS and FAIL lines against this rule by hand. The real verdict is each review's `overall_verdict` in its answer body, never
the `## status` header (that is job status). Record the count: `passers=N`, `still-rejected=M`, `N+M=7`.

## Step 2 - harvest findings for the still-rejected (laptop, then push to sandbox)

```
python tools/svc_harvest_dataos_findings.py "C:/Users/khiem.doan_turing/Downloads" ekw/dataos-findings.json
scp -P 2222 -i ~/.ssh/kiem_sandbox ekw/dataos-findings.json root@136.113.78.105:/root/qc/_findings.json
```

This re-parses EVERY `_with_runs` zip in Downloads, so the new round's findings land in the repair table the
lane fixer reads. `_findings.json` on the sandbox is what `svc_dataos_fix_brief.py` turns into each task's
brief.

## Step 3 - the proof-gate decision (this is the "comes back ready" test)

- **>= 5 of 7 passed** -> the directed fixer works. GO: run Step 4A (document passers) AND Step 4B (deploy
  lanes overnight on the full reject pool). This is the "immediately deploy and run overnight" trigger.
- **< 5 of 7 passed** -> the ceiling is real. Run Step 4A for whatever passed, then STOP. Do NOT scale.
  Write the ceiling note in the plan and the decision moves to GPT-5.6-sol-as-our-reviewer access or cutting
  tasks (user/Shyam). Round-2 the still-rejected 7 only if their NEW findings look mechanical, not 1.4/1.5.

Whichever branch: the still-rejected tasks (`ekw/_round2.txt`) are eligible for a round-2 fix (cap 3 DataOS
rounds/task total; after 3, cut as irreparable).

## Step 4A - document every passer (the full /task-doc all-steps)

For the passers in `ekw/_passers.txt`, run `/task-doc SVC-PC-a-b-c SVC-PC-d-e-f ...`. The skill now does all
of it: build the QCR Google Doc, share to `qc@turing.com`, mark the SVC QC Tracker A, add to the
consolidated tracker, and log duplicates. If doing it by hand, the steps are:

1. **QCR Google Doc** via the Drive connector `create_file` (contentMimeType `text/markdown`), read back,
   share to `qc@turing.com` as writer. One block per task, QCR format, fields from real data only.
2. **SVC QC Tracker A** (`1JmpP38bcOUDmKlkx_2HndB4GdncPgObC4-_vnQFNaw4`): mark each passer
   `submit for manual QC` and assign to Khiem:
   ```
   python tools/svc_mark_manual_qc.py --tasks $(cat ekw/_passers.txt) --assignee "Khiem Doan"          # dry run
   python tools/svc_mark_manual_qc.py --tasks $(cat ekw/_passers.txt) --assignee "Khiem Doan" --apply  # writes + reads back
   ```
   Dry run first: it prints every `old -> new` for Status and Assigned-to. Overwriting a co-assignee's name
   is per the user's standing "mark my submissions under my name"; if a cell holds someone else, that is
   expected and intended for Khiem's submissions. Needs `gcloud.cmd auth login --enable-gdrive-access`.
3. **Consolidated tracker** (`15Z00RATLJt7QcyT_-Rc6Y0jYS9WmcqUpukKp08GwAZ8`, `SVC` tab): add one row per
   passer to the main list (cols: A=No blank, B `Khiem`, C QCR doc title, D task id, E DataOS link,
   F `EQC ready`, G blank). Base-check the target rows are empty; snapshot; read back. Pattern in
   `_scratch_sheets_write.py`.
4. **Duplicates** (any passer already submitted by someone else): append under the `Duplicates` heading
   (currently row 189; re-read, do not assume) with B `Khiem`, C `Duplicate - already submitted by <who>`,
   D task id, E link. Do NOT re-submit a duplicate for manual QC. Pattern in `_scratch_dups_write.py`.

## Step 4B - deploy the lanes overnight (only on GO from Step 3)

Build the reject-pool list, push the runner, launch detached, then poll. The pool = every rejected task
with a non-deterministic finding, minus the four golden-broken excluded (41-5-0, 20-4-0, 35-0-0, 76-0-0)
and anything already passed.

```
python -c "import json;d=json.load(open('ekw/dataos-findings.json'));ex={'SVC-PC-41-5-0','SVC-PC-20-4-0','SVC-PC-35-0-0','SVC-PC-76-0-0'};print('\n'.join(t for t,v in sorted(d.items()) if t not in ex and any(f.get('bucket')!='deterministic' for f in v.get('findings',[]))))" > ekw/_pool.txt
# drop tasks that already passed this round:
grep -vxF -f ekw/_passers.txt ekw/_pool.txt > ekw/_pool2.txt && mv ekw/_pool2.txt ekw/_pool.txt
wc -l ekw/_pool.txt
```

Push and launch (the fixer + gate live on the sandbox; the overnight wrapper chains them):

```
scp -P 2222 -i ~/.ssh/kiem_sandbox tools/svc_dataos_overnight.sh tools/svc_dataos_fix.sh tools/svc_dataos_fix_brief.py root@136.113.78.105:/root/qc/
scp -P 2222 -i ~/.ssh/kiem_sandbox ekw/_pool.txt root@136.113.78.105:/root/qc/_round.txt
ssh root@136.113.78.105 -p 2222 -i ~/.ssh/kiem_sandbox \
  'chmod +x /root/qc/svc_dataos_overnight.sh /root/qc/svc_dataos_fix.sh; \
   (setsid nohup bash /root/qc/svc_dataos_overnight.sh /root/qc/_round.txt >/root/qc/_overnight.log 2>&1 </dev/null &); exit 0'
```

Poll (re-read, never wrap in an `until ... grep; do sleep; done` loop; the wrapper exits silently on done):

```
ssh root@136.113.78.105 -p 2222 -i ~/.ssh/kiem_sandbox \
  'tail -5 /root/qc/_dataosfix/progress.txt; echo ---VERDICTS---; tail -30 /root/qc/_preship/verdicts.txt'
```

Morning: `progress.txt` shows `OVERNIGHT_DONE ... ready=R tier2=T held=H`. The locally-verified resubmit set
is `/root/qc/_dataosfix/ready.txt` (oracle 1.0 + all deterministic clean). `ready_tier2.txt` is shippable
but the oracle could not run locally (an `/app` path or a capped lane), so it is not proven; ship it only as
a measured tier-2 add, not as verified. Pull `ready.txt`, build the resubmit zip from the corpus
(`testzip` + byte-size verify after transfer), hand it to the user to upload through the MVP config.

## Guardrails (each cost a real incident; do not skip)

- **Lane `t` is capped** (per-account weekly). The fixer excludes it; `svc_preship_gate.sh` still lists it,
  so a `t`-assigned oracle just times out to `oracle-unverified`, not a hang. Probe lanes before claiming
  the fleet is blocked.
- **CRLF:** the overnight wrapper strips `\r`, but if you build a list on Windows and feed another tool,
  a trailing `\r` glues to the id and the task is silently not found. Keep lists LF or `tr -d '\r'`.
- **No paid Anthropic API.** Lanes run on Max-plan compute (`CLAUDE_CONFIG_DIR=/root/.claude-<L>`). Never
  wire an `sk-ant-...` key.
- **The oracle is blind to a factually-wrong golden** that passes a too-weak rubric (1.1-in-narrative,
  19-4-0). `ready.txt` means the golden passes ITS rubric, not that the golden is correct.
- **No em dashes** anywhere the fixer or a doc emits. Hyphens only.
- **Upload is the user's action.** Everything here stops at a verified local `ready.txt`.
