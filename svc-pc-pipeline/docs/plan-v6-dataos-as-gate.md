# SVC-PC v6: deterministic pre-filter + DataOS-as-gate (LIVE PLAN, keep current)

2026-09-21. Supersedes [v5](plan-2026-09-20-v5-checks-that-block.md). **This is the live operating plan.
Read it in FULL at the start of every session and after every compaction before acting on SVC-PC.** When
state changes, update this doc in the same turn. Sub-docs, each authoritative for its slice:
- [wave1-dataos-results-2026-09-21.md](wave1-dataos-results-2026-09-21.md) - wave 1 returns, the 3 buckets
- [dataos-mvp-cost-2026-09-21.md](dataos-mvp-cost-2026-09-21.md) - the cost-reduced DataOS seat config
- [svc-prefilter-scan-2026-09-21.md](svc-prefilter-scan-2026-09-21.md) - the pre-filter + full corpus scan
- [svc-qc-severity-wall-findings-2026-09-21.md](svc-qc-severity-wall-findings-2026-09-21.md) - the wall evidence
- [svc-batch-ready-tier1/tier2-2026-09-21.txt](svc-batch-ready-tier1-2026-09-21.txt) - the ready pools
- [qc-intake-process-2026-09-24.md](qc-intake-process-2026-09-24.md) - **HUMAN QC INTAKE CHANGED 2026-09-24:** Khiem
  sends tasks to the TFRL QC team in batches of 50+; authors no longer submit themselves; QC team no longer edits
  the consolidated sheet (now Khiem's). Read before any submission or consolidated-sheet work.
- [svc-return-runbook-2026-09-21.md](svc-return-runbook-2026-09-21.md) - the fire sequence when a resubmit returns
- [batch18-return-analysis-2026-09-22.md](batch18-return-analysis-2026-09-22.md) - batch1 return, why 10 failed, the stale-zip gate
- [../tools/svc_fix_method_rules.md](../tools/svc_fix_method_rules.md) - THE fix/verify rules, single source, METHOD_VERSION

## CURRENT DATAOS GATE (2026-10-05, NEWEST - read first)

The dated entries below record the DataOS rule in force on each date, and several of them use rules that are now
retired ("2 of 3 reviews", "both GPT seats at 0 majors", the "NO CLAUDE" pipeline, the version 6 pair rule). The
current rule is:

- The pipeline is "ManualQC automated QC pipeline 4 Reviewers" (pipeline 141), version 8 (spec 401, 2026-10-05). It
  runs the five evaluation runs (the oracle runs, the GPT 6 Sol solver runs and the empty-answer NOP run), then four
  identical Answer Check reviews (Claude Opus 5.5, medium effort, saved prompt 431). The two Failed Tests reviews were
  removed in version 7, and versions 1 to 7 are archived. A run costs about 3.15 USD (approximate: version 7 measured
  2.20 USD, and each added review is about 0.47 USD).
- A task fails the pipeline if any of the four Answer Check reviews reports a major, and passes only when all four are
  clean. The author reads each review with a major and fixes what is real.
- A manager reviews the result (`../../docs/task-review-rules-v2.md`): if the pipeline fails, the task goes back to
  the author with the failed checks; if it passes, the task can go in the next TFRL batch unless the manager's own
  read finds a Major they can show.
- A pipeline pass is not a TFRL QC approval. Authors run the author pre-check before the pipeline
  (`../../docs/QC-SOP-first-run.md`, section 5a), and Khiem builds every batch that goes to TFRL QC.
- `tools/svc_record_return.py` and `tools/ekw_record_return.py` must apply the rule above and read Answer Check
  replies, which carry `findings` instead of `checks`. A copy from before 2026-10-05 passes a task when at least two
  reviews are clean and reads no `findings` replies (checked 2026-10-05 on synthetic reviews). Read the four reviews
  against the rule before `--apply` freezes a task.

## PATTERN-LEVEL FIXES IN THE RUNNER (2026-09-22 ~22:57 PDT, NEWEST - read first)

User asked whether lanes recompute + solve, apply every deterministic rule, and fix the failure PATTERN
rather than the named instance. Honest answer was: only attempt 1 (rebuild) re-derived from source; every
later attempt ran a targeted prompt that said "apply the fixes ... and then STOP", which beat R2/R4. The
regrade's direction B passed on `len(added) > 0`. Nothing checked requirement coverage mechanically.

Lane-time measurement (runner logs, last 24h, 90 tasks): L2 median 9 attempts, mean 8.0h wall; L3 median 6,
4.2h. Time by phase: oracle 38%, fix 23%, regrade 21%, verify 16%. Loop-backs: verify NOT-READY 371, oracle
< 1.0 180, regrade not PASS 117, PARKED 54, READY 53. Script: `_scratch_lane_time.py` (sandbox /root/qc/).

**Deployed to `/root/qc/svc_v7_lane_runner.sh` (atomic swap; running runners finish on the old copy, every
new claim runs the new one). Applies to L2 and L3 lanes alike:**
1. Targeted-fix prompt: 4 printed steps. CLASS (enumerate the family from source, fix all of it), RECOMPUTE
   (every touched/cited value from source), REQUIREMENT WALK (`svc_coverage_trace.py list`, add a criterion
   for any unmapped must-unit), RE-AUDIT (R3/R5). The "then STOP" line is gone. Rebuild prompt gets the walk too.
2. Coverage trace gate (`tools/svc_coverage_trace.py`, new): verify writes `_deepfix/<task>.coverage.tsv`
   (unit -> criteria); after verify READY the check runs. rc 1 (a unit with no criterion and no
   NOT-A-REQUIREMENT note) -> targeted fix. rc 2 (map missing/malformed) logs WARN, does not block. Must-units
   may be exempted only with a note, printed as EXEMPT. Mechanical tests: 5 of 5 cases behave.
3. Oracle: 1 run per loop attempt + 1 confirm run on the final bytes before the zip. Ship condition unchanged
   (two 1.0 runs on the same bytes); a flip on the confirm run feeds a split-the-criterion fix.
4. `svc_eval_regrade.py`: a capped/refused judge (infra_failure) now returns verdict INFRA and prints
   "infra refusal", so the runner cap-exits and releases the lane. Before, it read as "no scores" and
   became a false FAIL plus a wasted fix attempt, in BOTH directions.

**Staged, NOT live: direction-B proof (`--b-proof`).** Re-grades the hollow answers a 1.5 finding names
(158 of 254 task-returns with a 1.5 major name a present answer) and requires a coverage-fix criterion to
take points off one. First precision run was void (lane f weekly-capped; that run is what exposed fix 4).
Rerun on lane s (real grade, 80 criteria scored): 17-5-0's ACCEPTED rubric scores the answer its 1.5 finding named at 1.0, so the proof would have blocked a task DataOS accepted. DROPPED, stays off: a 1.5 finding's named eval is not reliably a hollow answer. Test stopped after that result; 80-6-0 not run.

**VERIFY-CAP PILOT, LIVE ~23:05 PDT (owner-approved: all non-L3 lanes, no fixed pilot size).** After 2 verify
NOT-READY loop-backs, a non-L3 task ships on the deterministic gates alone: oracle 1.0 x2 on the final bytes,
regrade PASS, coverage trace CLEAN (a missing map does not qualify), prefilter + 0.1.7 loader. Built with
`svc_build_upload_zip.py --fast-track <reason> --oracle-json _deepfix/<task>.oracle_confirm.json
--verify-capped`; the manifest carries `verify_capped: true` + the unresolved verify record's sha, and
`ready.txt` rows end in `verify_capped`. MEASURE this cohort's DataOS pass rate separately from READY tasks
before widening or keeping it. L3 tasks are exempt via `/root/qc/_v7/l3.txt` (46, 53, 55, 35, 47, 48, 21 -0-0).
Tests: `test_svc_bundle_upload.py` 26/26 (5 new capped cases), hook suite 19/19.
In-flight L2 runners were moved onto the new runner by `_scratch_restart_l2.sh --apply` (sandbox /root/qc/):
9 stopped at safe points (not in fix phase), claims released (the pool keeps a killed runner's claim), all
re-claimed within seconds. 25-2-0 and 66-2-0 were mid-fix and left to finish; re-run the script later.

**L3 WIP (owner, ~23:10 PDT):** goal for 08:00 PDT Sep 23 is VOLUME of 37 L3 tasks; not-done tasks go in the
WIP SVC dataset, approved ones move to master SVC. Asked session "Fill Data OS masters and build SVC/EKW WIP
datasets" to add 21, 46, 53, 35 (-0-0) to WIP. It replied (~23:13 PDT): WIP is DataOS dataset 1911; the copy
waits for Khiem's approval IN THAT SESSION (its permission check refused a request from another session; we must
not do the copy for it). Copyable now: 46-0-0 = task 141964 in #1934 (the run #390 build). 21-0-0 = 141749 in
#1931, blocked until #388 finishes grading. 53-0-0 and 35-0-0 exist in DataOS only as Sep 22 builds (139079 in
#1856, 138515 in #1825); it proposed those as labelled WIP placeholders, which is Khiem's call there.

**L3 in WIP (done ~23:22 PDT on Khiem's approval, WIP = DataOS dataset 1911):** 46-0-0 = WIP task 143605
(copy of 141964, the run #390 build); 53-0-0 = 143606 and 35-0-0 = 143607 are PLACEHOLDERS (Sep 22 builds
139079 / 138515, not the lane packages); 21-0-0 goes in when #388 finishes grading. Peer count: Master-SVC + WIP
= 36 L3, 37 once 21-0-0 lands. Then on Khiem's "send 37 L3 at min", 48-0-0 = WIP task 143611 (copy of 141735,
#1929, its first-grade build, 8 majors; placeholder) -> 37 L3 now, 38 with 21-0-0. 47-0-0 still out.
**Every cycle:** when a newer 46/53/35/48 build clears our gates
and gets its own DataOS dataset, SendMessage the dataset + task ids to session "Fill Data OS masters and build
SVC/EKW WIP datasets"; it swaps the placeholder out to holding dataset 1941 (never archive) and copies the new
build in. Any DataOS approval moves the task WIP -> Master-SVC (1722); tell that session too.

**TEAM REPO IS THE HOME (owner, ~12:45 PDT, hard stop): turing-context is not accessible to the team.** The
whole SVC-PC pipeline is now PR https://github.com/turing-genai-apps/EKW_QC_pipeline/pull/67 (branch
`svc-pc-pipeline-2026-09-23`, commits 30857aa + 2110907): `svc-pc-pipeline/` = every live sandbox tool (226),
the laptop-side SVC tools, runner/pool scripts, runbook, plain + one-shot guides, this plan, task-doc skill,
README; plus deterministic-checks judge_input_gate.py, scans/judge_input_report.py and the llm_backend OSError
fix. 300 .py compile, .sh pass bash -n, bundle tests 26/26, secret scan clean. Local worktree:
`C:/Users/khiem.doan_turing/Documents/Projects/EKW_svc_pc_pipeline`. From now on every tool change also goes
to that branch/PR (or a follow-up PR once merged). The SOP doc's links to turing-context should be repointed to
the team repo after merge (owner's doc).

**Cycle 2026-09-25 ~09:45 PDT.** batch43 (#606) 3/13 PASS: 10-4-0 (the oracle-crash task, unblocked by the judge_emulate fix), 25-2-0 and 52-5-0 (gate-bug tasks). Gate-bug tally so far: 31-5-0, 41-3-0, 25-2-0, 52-5-0 passed DataOS after the 2026-09-24 fixes. 10 FAIL, briefs built, requeued. QCR docs shared qc@turing.com writer: 10-4-0=161745 (1B6yUXiw...), 25-2-0=161747 (1-rb74v2...), 52-5-0=161750 (1ya1Y8mm...); an Opus builder agent is making tools/ekw_bundle_upload.py (bundle+check, stale-zip gate, golden-in-inputs refusal), no upload. Lanes under-used (7 busy): SVC queue near empty, EKW 37 of 44 READY. **PENDING tracker writes (gcloud reauth): 15 passes.** Credits $7,352 / $8,800.

**Cycle 2026-09-25 ~08:50 PDT.** batch42 (#587) 2/3 PASS: 41-3-0 (gate-bug task, rev 160953, QCR 10Eun4o1...) and 57-1-0 (rev 160957, QCR 1Z4p82mx...), shared qc@turing.com writer; 25-4-0 FAIL, requeued. batch43 (13 tasks incl. 25-1-0, which reached READY on the 5400 s decide limit) FRESH -> #2401/#606 RUNNING. Parks classified: 36-3-0 TASK (golden 0.9689 after 10 decide attempts); LGL-136, LGL-180, SCO-238 author-missing inputs as expected. EKW 34 READY zips, no submission path yet. **PENDING tracker writes (gcloud reauth): 12 passes** (the 10 listed at 04:45 plus 41-3-0=160953, 57-1-0=160957). Credits $7,236 / $8,800.

**Cycle 2026-09-25 ~05:15 PDT.** batch42 (25-4-0, 41-3-0, 57-1-0) FRESH -> #2352/#587 RUNNING (25-4-0 and 41-3-0 are gate-bug tasks). Lanes 17 SVC + 3 EKW; EKW 16 READY. 10 passes still await gcloud reauth for tracker writes.

**Cycle 2026-09-25 ~04:45 PDT.** batch41 (#584) 2/4 PASS: 82-2-0 (rev 160668, QCR 1B_UuGjZ...) and 93-5-0 (rev 160670, QCR 1tbDZgEL...), shared qc@turing.com writer. 40-1-0, 52-5-0 FAIL, briefs built, requeued. 25-1-0 parked again on three 2400 s decide timeouts: that lane started on the pre-fix runner; released so it runs on the 5400 s runner. **PENDING tracker writes (gcloud reauth):** 10 passes: 42-7-0=159089, 46-1-0=159090, 52-3-0=159091, 53-6-0=159092, 75-2-0=159093, 77-8-0=159095, 31-5-0=160269, 91-5-0=160276, 82-2-0=160668, 93-5-0=160670. READY 25-4-0, 57-1-0 (under 2h). Lanes 17 SVC + 2 EKW; EKW 14 READY. Credits $7,211 / $8,800.

**Cycle 2026-09-25 ~04:10 PDT.** batch41 (40-1-0, 52-5-0, 82-2-0, 93-5-0) FRESH -> #2343/#584 RUNNING. Lanes 19 SVC + 0 EKW (SVC queue refilled by returns, SVC first by design); EKW 14 READY zips. gcloud reauth still pending.

**Cycle 2026-09-25 ~03:40 PDT.** batch40 (#582) 0/3: 25-2-0, 35-0-0, 77-0-0 FAIL (each 1 of 2 reviews at 0 majors), briefs built, requeued. Nothing in flight; 82-2-0 and 40-1-0 READY (under 2h). Lanes 16 SVC + 4 EKW; EKW 12 READY zips. gcloud reauth still pending.

**Cycle 2026-09-25 ~03:20 PDT.** batch40 (#582) RUNNING. SVC READY since last: 82-2-0, 40-1-0 (under 2h, ship next cycle). EKW: 11 READY zips, 2 new parks classified per the TASK/GATE rule. LGL-190 = TASK (author): its source_documents/ holds byte-identical copies of the two golden deliverables plus Reasoning.docx, and none of the inputs the prompt names (executed MSA and amendments, order-form register, diligence summary); the converter refused it correctly; needs the author to re-upload the real inputs. LGL-178 = TOOL: the EKW runner's verify stuck signature hashed every criterion id in the record, and the record always carries the full per-criterion table, so it could never change (old 20 ids vs new v1 v8 v9); the lane was fixing different blocking defects each round. Fixed to hash only the criteria in the closing VERDICT paragraph (ekw_v1_lane_runner.sh 83fe7fdfdb769716, test_ekw_v1_runner.sh 7/7); LGL-178 released. gcloud still needs the owner's reauth (8 SVC passes await tracker writes; freeze push skipped).

**Cycle 2026-09-25 ~02:50 PDT.** batch39 (#580) 2/9 PASS: 31-5-0 (one of the 7 gate-bug tasks, rev 160269) and 91-5-0 (rev 160276); QCR docs 11-SWq-Oj... and 1AqAcXvP... shared qc@turing.com writer. 7 FAIL (25-4-0, 41-3-0, 52-5-0, 53-5-0, 55-4-0, 57-1-0, 73-0-0) briefs built, requeued. batch40 (25-2-0, 35-0-0, 77-0-0) FRESH -> #2329/#582. **PENDING tracker writes (gcloud reauth, owner step):** 8 passes now: 42-7-0=159089, 46-1-0=159090, 52-3-0=159091, 53-6-0=159092, 75-2-0=159093, 77-8-0=159095, 31-5-0=160269, 91-5-0=160276 -> svc_mark_manual_qc.py + svc_consolidated_record.py; do-not-touch refresh also waits on gcloud. EKW: 10 READY zips in /root/qc/_ekw/ready, no EKW submission path yet. Lanes 14 SVC + 6 EKW. Credits $7,153 / $8,800.

**Cycle 2026-09-25 ~02:15 PDT.** batch38 (#2299/#576) 6/13 PASS: 42-7-0, 46-1-0, 52-3-0, 53-6-0, 75-2-0, 77-8-0. 7 FAIL (10-4-0, 35-0-0, 36-3-0, 75-8-0, 82-2-0, 88-0-0, 93-5-0), briefs built, requeued. QCR docs created and shared qc@turing.com writer: 42-7-0 1lf5OdPD..., 46-1-0 1tAClkoU..., 52-3-0 1ZrTd0mw..., 53-6-0 1XaLEgC5..., 75-2-0 1PVH2wxI..., 77-8-0 1oW__m6r... (per-employee My Drive folder names collapsed to counts). **PENDING (gcloud reauth, owner step `gcloud.cmd auth login --enable-gdrive-access`):** `svc_mark_manual_qc.py --tasks <the 6> --assignee "Khiem Doan"` then --apply, and `svc_consolidated_record.py` per task (doc title + url + TASK=REV: 159089, 159090, 159091, 159092, 159093, 159095). batch39 (25-4-0, 31-5-0, 41-3-0, 52-5-0 [the gate-bug tasks], 53-5-0, 55-4-0, 57-1-0, 73-0-0, 91-5-0) check FRESH -> #2317/#580 RUNNING (the upload call timed out at 30 min but the dataset and run were created; verified all 9 in run 580 before recording). New parks classified per the TASK/GATE rule: 20-8-0 TASK (golden 0.97 on its own rubric); 25-1-0 TOOL (decide run ended without writing decision.json). Lanes: 9 SVC + 12 EKW. Credits $7,082 / $8,800.

**EKW on the lanes 2026-09-25 ~01:20 PDT (owner: lanes never idle while EKW work exists).** A background agent built the EKW lane path: `tools/ekw_intake.py` + `ekw_pull_drive.py` pulled the 44 claimed tasks read-only from Luiz's `TaskID-<ID>` Drive folders (the connector listed them empty; the Drive API via gcloud listed files in all 44) into `/root/ekwqc/pipeline/data/ekw_qc/`; 36 pass schema after automatic reshaping, 5 (SCO-174, 206, 226, 230, 234) need the rubric rewritten into verifier format by the lane, 3 park at once for a missing author file (LGL-136 no verifier.json; LGL-180, SCO-238 no golden). `/root/qc/ekw_v1_lane_runner.sh` (same exit codes as SVC, releases its own claim on 10/30) edits only `_raw/<TASK>`, rebuilds the package with the team `ekw_raw_to_rewardkit.py` every attempt, gates on `ekw_run_checks.py` + oracle + adversarial verify + oracle confirm + prefilter. Proof: LGL-131 on lane b went raw -> READY zip in 4 attempts (07:21Z-08:11Z); `tools/test_ekw_v1_runner.sh` 7/7. Open item on LGL-131: Maryland notice periods not confirmed against current law, and a golden date conflict. Advisory (non-blocking) EKW checks: `/root/qc/_ekw/advisory_checks.txt`; their false-alarm rate is not measured. **Pool:** `svc_v7_pool.sh` (e7815d236f429cb8) claims SVC first and falls back to the EKW queue when no SVC task is claimable; lane_busy covers EKW runners. `tools/test_svc_v7_pool_ekw_fallback.sh` 2/2 new, fails on the old pool. Restarted 08:15Z: within seconds 12 lanes took EKW tasks; 21 lanes busy (9 SVC, 12 EKW), no lane double-booked, 31 EKW left in the queue. EKW READY zips land in `/root/qc/_ekw/ready/`; they are NOT yet bundled or uploaded (the SVC bundle tool is SVC-only); EKW grading/submission path is the next step.

**Gate bugs fixed 2026-09-24 ~23:55 PDT (owner: "this needs to be stopped structurally").** 8 tasks sat parked as "genuinely stuck"; 7 were our own `svc_eval_regrade.py`, not the task. Bug 1 (94-0-0, 25-2-0, 31-5-0): decide-mode keep exemptions were applied after the LLM re-grade decided whether to run, so the re-grade never ran and the gate failed with "did not confirm loosened criteria: {}". Bug 2 (40-1-0, 52-5-0, 41-3-0, 25-4-0): the coverage (1.5) check compared judge.toml only, so a fix made in checks.py (52-5-0's registered in a loop) read as "no criterion added or rewritten"; decide mode had said so in its gate_note twice. Fixes: exemptions first; `load_checks_criteria` fingerprints every checks.py criterion (registration, function + decorators, same-file helpers and constants it reaches, loop-built names). Deterministic old-vs-new on the 7: B.ok False->True on all 4 bug-2 tasks; 12 previously-PASS tasks unchanged. `tools/test_svc_eval_regrade_gate.py` 9/9 new, 3 FAIL on old. **Structural guards:** the gate emits GATE-ERROR when a required re-grade did not run; the runner parks GATE-ERROR, or a decide round whose decision.json carries a gate_note while the gate still fails, as `GATE problem` in `_v7/gate_errors.txt`, and the runbook step 6 now requires classifying every park TASK or GATE before any release recommendation. Deployed: regrade 3d1a8829c3f5c915, runner 92b606d22a6b13f1. All 8 (the 7 plus 20-8-0, a real golden-at-0.97 case) released and running within 2 min. EKW: a background agent is building the EKW lane runner + queue so lanes move to the 44 claimed EKW tasks when the SVC queue is empty.

**Cycle 2026-09-24 ~22:55 PDT.** batch36 (#566) 0/5: 25-1-0, 55-4-0, 56-1-0, 68-0-0, 73-0-0 FAIL. batch37 (#567) 1/3: 94-6-0 PASS -> `QCR_SVC-PC-94-6-0_25092026` (1Gc9pDXb..., shared qc@turing.com writer), Combined row 16 -> submit for manual QC, consolidated SVC row 495; 26-2-0, 57-1-0 FAIL. 7 briefs built, requeued. batch38 (13 tasks: 10-4-0, 35-0-0, 36-3-0, 42-7-0, 46-1-0, 52-3-0, 53-6-0, 75-2-0, 75-8-0, 77-8-0, 82-2-0, 88-0-0, 93-5-0) check FRESH -> #2299/#576. 10-4-0 reached READY after the judge_emulate fix. 12-7-0 parked: "no complete brief" (it was rejected in manual QC, so there is no DataOS return to build a brief from). Lanes: 15 runners (queue nearly empty), pool alive. Credits $6,976 / $8,800.

**Cycle 2026-09-24 ~19:15 PDT.** batch36 (#566) still RUNNING. batch37 (26-2-0, 57-1-0, 94-6-0) check FRESH -> #2285/#567 RUNNING. **Oracle tool bug fixed:** `judge_emulate.py` `_synthetic_error_scores` passed description=None into rewardkit `Score` (a str field), so when a programmatic reward raised, the error path itself crashed and the task parked as "oracle CRASHED" (10-4-0 twice). Now it scores the criterion 0 with the error text. `tools/test_judge_emulate_error_scores.py` 3/3 on the new file, 3/3 FAIL on the old; sandbox hash f90c94b364423ee3. 10-4-0 released to the head of priority. 41-3-0 parked after a decide round (no progress). Lanes: 47 runners, pool alive. Credits $6,952 / $8,800.

**EKW claim 2026-09-24 ~18:45 PDT.** Owner decision: we take ~45 EKW tasks for the lanes this week. Claimed 44 on 'EKW QC Tracker Combined' (all 17 unclaimed LGL + all 27 unclaimed SCO), B=Khiem Doan, C=In progress, D=24-09-2026, note in E; base-checked and read back 44/44 (`_scratch_ekw_claim.py`). The 48h no-progress rule now applies to these rows: none of them has a package or an EKW runner on the sandbox yet, so the EKW converter / intake is the next blocker and the rows need a dated progress note every day. Owners of the rejected tasks were asked whether they are reworking them.

**Cycle 2026-09-24 ~18:50 PDT.** No returns pending. batch36 (25-1-0, 55-4-0, 56-1-0, 68-0-0, 73-0-0) passed check FRESH -> #2279/#566 RUNNING. Sweep sent 52-3-0 back to the queue (its ready zip had no manifest). Lanes: 43 runners, pool alive; the runner that releases its own claims is live.

**Cycle 2026-09-24 ~18:45 PDT.** batch35 (#2275/#564) returned 0/2: 53-6-0 and 75-8-0 FAIL, briefs built, requeued. Ready and not yet shipped: 56-1-0, 55-4-0 (under 2h old, ship next cycle). **Stuck-claim leak found and fixed:** 7 tasks sat claimed with no lane working them (up to 28h). Cause 1: a pool restart orphans running lanes, and their release exits (10/30) were handled only by the pool, so the claim stayed. Cause 2: the 10-attempt cap "deferred" the task (claim kept) and nothing ever requeued deferred.txt. Fix in `svc_v7_lane_runner.sh` (sandbox hash 8d885e4985064171): the runner releases its own claim on exit 10/30, and a normal-mode task at the cap goes to decide mode (exit 30); a decide-mode task at the cap parks with a parked.txt line. Test `tools/test_svc_v7_runner_release.sh` passes 3/3 on the new runner, fails on the old. Released 14-1-0, 46-1-0, 53-5-0, 82-2-0, 91-5-0 (lane limits) and 75-2-0, 77-0-0 (cap, into decide); 12-7-0 added to the queue (it had never been queued). **Combined tracker:** our 46 open rows now carry a dated progress note (col E) from live sandbox state, readback 46/46; 49-4-0 holder "?" set to its builder per the Sep 21 tabs. Stale-claim audit against the Sep 21 / Sep 22 tracker snapshots done; owners of unchanged claims were asked to update or release them. What this does NOT establish: an unchanged row is not proof nobody worked the task (our own 44 rows looked unchanged while lanes worked them). EKW Combined: 84 unclaimed today (the "102" header was earlier); no EKW packages or EKW runner exist on the sandbox yet.

**Cycle 2026-09-24 ~17:45 PDT.** 5-5-0 regrade (#559) PASS -> `QCR_SVC-PC-5-5-0_24092026`, graded revision 157030 in #2272: the DataOS-copy workaround for exception regrades works. batch35 (53-6-0, 75-8-0) -> #2275/#564, FRESH. Census of real tasks (171; the other 40 census entries are pre-fix backup dirs in the corpus folder): 94 passed to manual QC, 31 others', 17 in lanes, 18 parked, 4 waiting on lane limits, 3 on DataOS, 1 at attempt cap, 1 never started (12-7-0). Credits $6,893 / $8,800.

**Cycle 2026-09-24 ~17:15 PDT.** batch32 0/3, batch33 1/2, batch34 0/1: L3 55-0-0 PASS -> `QCR_SVC-PC-55-0-0_24092026` (shared qc@), Combined row 581, consolidated row 480; WIP-to-Master swap sent to the masters session (needs Khiem's yes there). 5 requeued. L3 21-0-0 swap DONE (Master 1722 id 158141). #559 (5-5-0 regrade) at 4/5. DataOS 1/30 slots, $6,889 / $8,800. No fresh READY zips; lanes working the 17 requeued tasks (33 runner procs).

**Cycle 2026-09-24 ~16:50 PDT (later).** Four returns: batch28 2/6, batch29 1/2, batch30 1/4, batch31 2/4 -> 6 PASS (2-4-0, 92-1-0, 70-4-0, 49-2-0, L3 21-0-0, 21-2-0) -> `QCR_group_24092026_batch28-31` (shared qc@), Combined marked, consolidated rows 474-479. 9 requeued. L3 21-0-0 WIP-to-Master swap sent to the masters session; it waits on Khiem's explicit yes there. 5-5-0 hit a DataOS exception (0 reviews); both bundle paths refuse it (--first-grade: already graded before; normal: same bytes already shipped), a gap in svc_bundle_upload.py for exception regrades. Worked around by DataOS 'Copy tasks' of the same task (156397, #2233) into new dataset svc-v81-regrade2 #2272, pipeline #559; removed from needs_regrade.txt. DataOS now 5/30 slots, $6,859.92 / $8,800.

**Cycle 2026-09-24 ~16:50 PDT.** DataOS moving again: #544 (batch28) 3 of 6 done, rest at 3-4/5; others 1-3/5. Credits $6,703.83 / $8,800. batch34 (24-4-0) -> #2266/#558, FRESH. **The lane queue is effectively drained:** of 61 entries in queue.txt only 1 (73-0-0) is claimable; the rest are in flight on DataOS, parked, accepted or do-not-touch. Idle lanes are idle for lack of work, not caps (c, i, l, m, q capped). Remaining throughput now depends on DataOS returns and their requeued rejects.

**Cycle 2026-09-24 ~16:15 PDT.** No returns: DataOS still 30/30 concurrent runs; all 19 in-flight tasks (#544, #547, #550, #552, #554) at 1/5. Credits total raised to $8,800 ($6,539.84 used). batch33 (L3 55-0-0, 94-6-0) -> #2263/#557, FRESH. Pool alive, 14 runner procs, queue 61.

**Cycle 2026-09-24 ~15:40 PDT. DataOS limits:** the header shows Credits $6,454.72 used / $7,300.00 total (about $845 left, account-level) and Concurrent Runs Agent/Model 30 / 30. All our runs (#544 since 13:29 PDT, #547, #550, #552) sit at 1/5 nodes: their eval nodes are queued behind the 30-slot cap, not failing (run #20085: Oracle PASSED, Terminus and Codex evals RUNNING, both reviews BLOCKED on them). Khiem chose to keep uploading every READY task. batch32 (42-3-0, 57-1-0, 77-8-0) -> #2257/#554, FRESH. Pool alive, 15 runner procs, queue 61; lanes c, l, m, q capped.

**Cycle 2026-09-24 ~15:00 PDT.** No returns; #544 (batch28) has sat at 1/5 nodes for ~90 min, #547 and #550 at 0-1/5. batch31 (L3 21-0-0, 21-2-0, 3-9-0, 93-5-0) -> #2250/#552, FRESH, all 4 in the run. Lanes c, l, m, q capped; pool alive, queue 61. Freeze 564. GLM-in-OpenCode setup added to the team SOP (team repo `105575c`).

**Cycle 2026-09-24 ~14:15 PDT.** #536 (batch26) 1/2: 40-3-0 PASS -> `QCR_SVC-PC-40-3-0_24092026` (shared qc@),
Combined row 561, consolidated row 466. 24-4-0 got 0 of 2 and was requeued. batch30 (26-2-0, 42-7-0, 49-2-0, L3 68-0-0)
-> #2244/#550, FRESH, all 4 in the run. #544 and #547 still running. Pool alive, 39 runner procs, queue 62.
**Human QC intake changed today:** see [qc-intake-process-2026-09-24.md](qc-intake-process-2026-09-24.md).

**Cycle 2026-09-24 ~13:45 PDT.** #539 (batch27) 2/3: 33-8-0 and 67-3-0 PASS -> `QCR_group_24092026_batch27` (shared
qc@ writer), Combined rows 551/587, consolidated rows 464-465 (first write with the new Email Id column; readback OK).
21-2-0 got 1 of 2 and was requeued. batch29 (70-4-0, 75-8-0) -> #2240/#547, FRESH, both in the run. #536 (batch26)
40-3-0 done, 24-4-0 at 3/5; #544 (batch28) 0-1/5. Pool alive, 48 runner procs, queue 64.

**Cycle ~13:40 PDT.** #536 (batch26) and #539 (batch27) still running (1-3 of 5 nodes). batch28 (2-4-0, 31-4-0,
5-5-0, 52-3-0, 53-6-0, 92-1-0) -> #2233/#544, FRESH, all 6 in the run. Consolidated tracker now has an "Email Id"
column at C; `svc_consolidated_record.py` finds columns by header (commit `4144c227`, team `bb525b2`). Side job: EKW
"New Tasks" tab merged into "EKW QC Tracker Combined" (most-progress owner wins, 5 dup rows removed, merge note in
col M); not SVC-PC. Freeze 560. Pool alive, 51 runner procs, queue 64.

**Cycle ~12:45 PDT.** #536 (batch26) running, 0/5 nodes. batch27 (21-2-0, 33-8-0, 67-3-0) -> #2221/#539, FRESH, all
3 READY. The upload and pipeline launch now run as one scripted browser step (setInputFiles on the form's file
input, then reload until the tasks show READY, then Run pipeline). Freeze 560. Pool alive, 51 runner procs, queue 64.
Datasets still needing a TFRL_QC share: #2068, #2071, #2082, #2199, #2208, #2216, #2221 (user action).

**Cycle ~12:15 PDT.** #528 (batch24) 1/3: 53-3-0 PASS -> `QCR_SVC-PC-53-3-0_24092026` (shared qc@ writer), Combined
row 578, consolidated row 462 (the live queue ends at 463 and the Rejected heading is at 464, so the next add must go
through the tool's own layout check). 25-4-0 and 42-7-0 got 0 of 2 and were requeued. #531 (batch25) L3 55-0-0 got
1 of 2 and was requeued. batch26 (24-4-0, 40-3-0) -> #2216/#536, FRESH. Share audit: of the 25 datasets holding
passes, #2068, #2071, #2082, #2199 lack TFRL_QC (user action); Ardeshir_team is on 7 of 25. The DataOS token read
for a scripted audit was blocked by the classifier; the audit read each Share dialog instead. Freeze 559. Pool alive,
48 runner procs, queue 65.

**Cycle ~11:35 PDT.** No returns: #528 (batch24) at 1/5 nodes, #531 (batch25) just launched. Sweep 80 zips, 0 stale;
the 5 fresh ready zips are all already shipped, so no bundle. Freeze 554. Pool alive, 49 runner procs, queue 65; lanes
c, l, q capped. The fake test lanes `/root/.claude-T` and `-U` were back on disk (dated 09-23 15:49 PDT) and the pool,
which takes every `/root/.claude-?` dir as a lane, was probing them as "capped" every 15 min. Moved to `_v7/trash`; the
running pool keeps its startup list, so they drop out at its next restart.

**Cycle ~11:30 PDT: 16 passes to manual QC.** #515 (22a) 6/18 PASS, #517 (22b) 9/22 PASS, #520 67-4-0 PASS. All
16 have a QCR doc (`QCR_group_24092026_batch22a`, `..._batch22b`, `QCR_SVC-PC-67-4-0_24092026`), shared with qc@turing.com
as writer, marked `submit for manual QC` in Combined, and have consolidated rows 445-460. 25 FAILs were requeued with briefs.
L3 21-0-0 was in 22a, not 22b (the ~09:55 entry below had that wrong), and it failed 0 of 2. Two tool fixes: (1)
`svc_record_return.py` compared `abspath`, so the `/root/Downloads` symlink copied onto itself and threw
SameFileError before any write; it now compares `realpath`. (2) Someone rearranged the Combined tab: the header is now
at row 397, with task rows above AND below it. `svc_mark_manual_qc.py` only looked in rows 1-20. It now finds the
exact `Task ID` header anywhere and matches tasks on every row. Uploaded batch24 (25-4-0, 42-7-0, 53-3-0) as #2208/#528
and batch25 (L3 55-0-0) as #2212/#531; both FRESH. Freeze list 553 ids. Pool alive, 23 runners, queue 66; lane c capped.
What this does NOT establish: submitted for manual QC is not approval. EQC can still reject any of the 16.

**Cycle ~10:00 PDT.** `svc_build_freeze.py` was taking tracker doc-title cells as task ids ("SVC-PC-10-1-0 - ANDREW_TEAM -
DATASET DESCRIPTION", "..._DATASET_DESCRIPTION.DOCX"): list 535 -> 616, and a cp1252 dash crashed `sweep`. Fixed: only a
bare `SVC-PC-n-n-n` is accepted, output utf-8. Now 541 ids, 0 junk, sweep OK (100 ready zips, 0 stale). Status mix:
222 Approved, 86 + 53 submitted for manual QC, the rest owned. Team PR `23138eb`. 31-5-0 parked in decide
(identical regrade blocker x2). #515 and #517 running. 14 runners.

**~09:55 PDT: batch22 uploaded.** gcloud re-login done (token + Drive scope verified); freeze list refreshed 535 -> 616
ids, none of batch22's 40 tasks on it. 22a -> #2193/#515 (18), 22b -> #2194/#517 (22, incl. L3 21-0-0; WIP swap sent
to the masters session). Browser upload of a ~270 MB zip takes 5-9 min, then ingest another ~10 min; the dataset page
does not refresh Tasks (N) live, reload it.

**Cycle 2026-09-24 ~09:10 PDT (no cycles ran ~19:30-09:00 PDT).** Overnight the lanes drained the queue: 0 unclaimed
at 16:08 UTC, 2 runners, and ~40 READY zips unshipped. DECIDE MODE RESULT: 8 of the 12 dead-end tasks reached READY
(2-4-0, 5-1-0, 15-1-0, 31-4-0, 52-3-0, 56-1-0, 92-1-0, 94-6-0); 20-8-0 and 52-5-0 parked after 2 identical blockers
in decide; 25-1-0 cleared the regrade (attempt 8) then deferred at the verify cap; 55-0-0 cleared the golden, then
deferred at the regrade cap. #481 (25-4-0) FAIL 1 of 2. batch22 = 40 fresh READY (565 MB) -> split by
svc_split_bundle.py into 22a (18 tasks, 282.5 MB) and 22b (22, 282.6 MB), both check FRESH; includes L3 21-0-0.
Idle lanes put back to work: 25-2-0, 31-5-0, 40-1-0, 94-0-0 (parked on regrade) -> decide.txt; 14-1-0, 24-4-0,
25-1-0, 26-2-0, 53-3-0, 67-4-0, L3 68-0-0, L3 55-0-0 (verify/regrade caps) released for a fresh round. Runners 2 -> 15.
gcloud token EXPIRED: svc_build_freeze.py --push and all tracker writes fail until `gcloud.cmd auth login
--enable-gdrive-access` (owner's step). 8 older ready zips have no manifest (pre-gate builds) and are refused.

**Cycle ~19:15 PDT: DECIDE MODE WORKS.** 2-4-0, 5-1-0 and 52-3-0 cleared the eval-regrade gate on their FIRST decide
attempt (they had failed it 45, 21 and 18 attempts running); 55-0-0's golden now scores 1.0 after its decision.
5-1-0 went on to verify NOT-READY and is in the normal fix loop. 52-5-0 and 94-6-0 hit the regrade attempt cap ->
added to decide.txt + priority, released. #478 PASS: 67-2-0 -> `QCR_SVC-PC-67-2-0_23092026` (1kNNCscd..., shared),
QC tracker 2/2, consolidated row 421, audit 1/1. #480 (batch20) 0/2 (21-2-0 1 of 2 again). #479 L3 21-0-0 FAIL
0 of 2 (third DataOS fail today). batch21 (25-4-0) -> #2089/#481. Day total (09-23): 36 to manual QC.

**Cycle ~18:45 PDT.** #477 (batch18) 0/2 (5-4-0 1 of 2 clean, 70-4-0 0 of 2), briefed + requeued. batch20
(21-2-0, 3-9-0) -> #2086/#480. FIRST DECISION RECORD (55-0-0, 01:32 UTC): c2, c3, c9, e2, e6 = rewrite (each
re-graded 1.0 on the real answers 522182/522183); d6 = KEEP (answer 522182 states an unsourced master-carton
material; evidence Quality_Standards.pdf 7.2). Runner is taking it through oracle and regrade.

**Cycle ~18:15 PDT.** READY: L3 21-0-0 (full verify, 10 attempts) and 67-2-0 -> shipped per A: batch19 (67-2-0)
#2082/#478, L3 21-0-0 #2083/#479 (task 150323; WIP swap sent to the masters session). #477 (batch18) 1/2 done.
L3 68-0-0 DEFERRED at the attempt cap on the verify gate (not a decide-mode blocker type; left for review).
Decide mode: 55-0-0's first run (fixed runner) in progress on lane t; the other 9 queued behind the L3 pins.

**ITEM D LIVE (~18:00 PDT): DECIDE MODE.** Owner: "build it, document, add to plan, and go." `svc_v7_lane_runner.sh`
gives a task on `_v7/decide.txt` a decision prompt (exact failing criteria + the DataOS answers they fail + golden
diagnosis; per criterion REWRITE / DROP / KEEP-with-cited-source / FIX-GOLDEN -> `_deepfix/<task>.decision.json`),
at the start and on every regrade / golden-below-1.0 loop-back; STUCK_LIMIT 2 in decide mode, so it parks with its
decision record instead of spending 10 attempts. `svc_eval_regrade.py --decision` exempts only a KEEP with
evidence + reason and lists it under `kept_by_decision`. Test (5-1-0, deterministic path, /tmp only): no decision
-> FAIL on a15a/a15b/a12; cited keeps -> exempted; empty-evidence keep -> still FAIL. The LLM-regrade exemption
path is the same rule but first runs live. Deployed (hash-matched), team PR #67 `afc613e`, README + runbook
updated. `_v7/decide.txt` = 2-4-0, 5-1-0, 15-1-0, 25-1-0, 52-3-0, 56-1-0, 92-1-0, 20-8-0, 31-4-0, 55-0-0; all
released and pinned after the L3 pins in priority.txt, so they run as lanes free. Weekly limits were already
handled by the current runner (`LIMIT_RE` includes "weekly limit" and the oracle output is checked); 73-0-0 and
77-1-0 were deferred on 09-22 before that. Items done today: A (ship every READY), C (near-miss-first triage),
D (decide mode), pool fix. B (auto DataOS poll) is not possible with a user token.

**Cycle ~17:45 PDT.** #476 (batch17) 1/3 PASS: 91-3-0 -> `QCR_SVC-PC-91-3-0_23092026` (1nUPm2ne..., shared),
QC tracker 2/2, consolidated row 420, audit 1/1. 21-2-0 and 76-0-0 1 of 2 clean, briefed + requeued. batch18
(5-4-0, 70-4-0; shipped at 2 per item A) -> #2079/#477. ITEM C LIVE: `svc_triage_queue.py` sorts by clean DataOS
seats first (desc), then majors, then categories; pinned priority.txt still leads. 25 queued tasks have a clean
seat. Team PR #67 updated. Day total (09-23): 35 to manual QC.

**Cycle ~17:15 PDT.** #475 (batch16) 2/7 PASS: 28-3-0, 49-8-0 -> `QCR_group_v81b16_23092026` (1FJNq1HP...,
shared; a first copy dated 24092026 from the UTC date was trashed before sharing), QC tracker 4/4, consolidated
rows 417-418 (live queue now 2-432), audit 2/2. 5 rejects briefed + requeued (26-3-0, 49-2-0, 52-5-0 were 1 of 2
clean). batch17 (21-2-0, 76-0-0, 91-3-0) -> #2077/#476. Owner approved efficiency items A/C/D; A (ship every
READY) is in effect from this cycle. WEEKLY LIMITS (probed): f resets Sep 24 10:00 PDT, k Sep 24 01:00 PDT,
l Sep 24 17:00 PDT, q Sep 24 22:00 PDT, m Sep 26 14:00 PDT; h healthy. 73-0-0 and 77-1-0 had been DEFERRED
only because their lanes (m, q) were weekly-capped (every oracle call refused): released to the queue.
D diagnosis: 7 of 12 dead-ends (2-4-0, 5-1-0, 15-1-0, 25-1-0, 52-3-0, 56-1-0, 92-1-0) have golden 1.0 and fail
only the eval-regrade: the DataOS-flagged agent answers still score 0 on the rewritten criterion (5-1-0 and
52-3-0 never changed the flagged criterion). 3 goldens fail their own rubric (20-8-0 0.97, 31-4-0 ~0.77,
55-0-0 0.88). Plan: one decision run per task (rewrite / drop / overrule-with-justification). B (auto DataOS
poll) is not possible with a user token: DataOS exposes no API-token UI (docs + account menu checked).
Sandbox claude auto-updated at 00:09 UTC (2.1.281); ~10 runner calls hit the missing binary, treated as infra.
Day total (09-23): 34 to manual QC.

**Cycle ~16:40 PDT.** #475 (batch16) 6/7 done. 76-0-0 READY (1 fresh, held). L3 55-0-0 DEFERRED at the
10-attempt cap: golden oracle stuck at 0.88 (last). 19 tasks in runners.

**Cycle ~16:15 PDT.** #473 (batch14) 2/3 PASS: 79-1-0, 93-0-0 -> `QCR_group_v81b14_23092026` (1mcAHKqq...,
shared; first create hit a Drive connector quota error, the retry succeeded and a title search shows one doc),
QC tracker 4/4, consolidated rows 413-414, audit 2/2. 5-5-0 0 of 2, briefed + requeued. batch16 (7 tasks: 1-5-0,
26-3-0 capped, 28-3-0, 40-1-0, 49-2-0, 49-8-0, 52-5-0; 111 MB) -> #2071/#475. 1-5-0's combined-tracker row still
names Ahmed Fawwad (status "Available - claim me"): check ownership before submitting if it passes. 52-3-0
PARKED (identical blocker x5). Day total (09-23): 32 to manual QC.

**Cycle ~15:45 PDT.** #474 (batch15) 2/3 PASS: 57-2-0, 94-4-0 -> `QCR_group_v81b15_23092026` (1qz_cjxM...,
shared), QC tracker 4/4, consolidated rows 407-408, audit 2/2. 41-3-0 0 of 2, briefed + requeued. #473 (batch14)
2/3 done. 49-2-0 READY (1 fresh, below threshold). 20 tasks in runners; lanes f k l m q v capped (real 5-hour
windows). The old-pool test had created `/root/.claude-T` and `-U`, which the new pool picked up as lanes (probe
fails, logs "capped" every 15 min, harmless); moved to `_v7/trash/`, gone at the next pool restart.
Day total (09-23): 30 to manual QC.

**Cycle ~15:15 PDT: SECOND L3 PASS.** #471: **47-0-0 PASS** (2 of 2 at 0 majors; task 149874) ->
`QCR_SVC-PC-47-0-0_23092026` (1nlWF4nr..., shared), QC tracker row 60 -> submit for manual QC, consolidated row
404, audit 1/1. WIP -> Master-SVC move sent to the masters session. #472 (batch13) 0/3, all full-verify READY
(25-4-0 and 3-9-0 0 of 2 clean, 31-5-0 1 of 2); briefed + requeued. batch15 (41-3-0, 57-2-0, 94-4-0, all full
READY) -> #2068/#474. 56-1-0 PARKED (identical blocker x5). 20 tasks in runners. Day total (09-23): 28 to manual QC.

**Cycle ~14:50 PDT.** POOL FIX LIVE (~14:34 PDT): `svc_v7_pool.sh` workers now persist and poll the queue every
120s (claim before probe; wait while an outside runner holds the lane; stop via `_v7/POOL_STOP`, max 168h).
`tools/test_svc_v7_pool.sh` 4/4 (old pool 0/3 on the requeue case). Team PR #67 `0db69f4`. Incident while
testing: the old script ignores POOL_QC, so its test run hit the real queue on fake lanes T/U and falsely parked
91-8-0, 70-4-0, 67-4-0 (40-1-0 got 2 retries). No package or record file changed (stub claude); parks, claims
and retries reverted. #467 (batch12) 3/10 PASS: 35-6-0 (full), 71-0-0, 91-6-0 (capped) ->
`QCR_group_v81b12_23092026` (1QFQshTZ..., shared), QC tracker 6/6, consolidated rows 401-403, audit 3/3. Capped
2/8, full 1/2. 7 rejects briefed + requeued. batch14 (5-5-0, 79-1-0, 93-0-0, all full READY) -> #2066/#473.
Reclaim check (owner: "reclaim ours that are unclaimed"): all 6 rows released by Khiem on 09-21 are held by
someone now (7-1-0 Ayush, 7-3-0/7-4-0 Joao, 8-2-0 Juan; 2 submitted/approved), 0 to reclaim. Claimed 47-0-0 (row 60,
was "Available - claim me", no holder; on DataOS as our L3). 1-5-0 (Ahmed Fawwad) and 9-3-0 (Usama Rizwan) show
"Available" with a name still set, left alone. 48-0-0 is Farhan's (claimed "24-09-26"); our runner self-parked it.
Day total (09-23): 27 to manual QC.

**Cycle ~14:15 PDT: POOL STARVATION FOUND + census.** Pool (started 09-22 14:50 PDT, 23 lanes) has only 9
lane workers left: `svc_v7_pool.sh` ends a lane's loop the first time `claim_next` finds nothing, so DataOS
rejects requeued later by `svc_record_return.py` never get a worker. 27+ rejects sat unclaimed while 9 lanes idled.
Launched 9 queue-head tasks on i k l m o q v x z via svc_release_launch.sh. Fix pending: worker must poll the
queue (sleep + retry) instead of exiting; same change to the team repo. Census (`_scratch_svc_census.py`, one
bucket per task, 171 real tasks; the other 9 dirs in 03_dataos_ready are backups/coverage files): 54 passed ->
manual QC; 31 owned by others (do-not-touch; includes L3 48-0-0, check why); 14 on DataOS (#467 done, #472,
#471); 16 in lanes; ~45 rejected and waiting for a lane (27 queued, 14 stale parked.txt entries, 3 transient,
1 claimed-no-runner); 5 genuinely stuck (2-4-0, 20-8-0, 25-1-0, 5-1-0, 92-1-0); 5 at the 10-attempt cap;
12-7-0 never started. Plus 35 unbuilt tasks outside the corpus (separate session). #466 21-0-0 FAIL (1 of 2
clean), requeued. batch13 (#2062/#472, 3 full READY) and L3 47-0-0 (#2064/#471) uploaded.

**Cycle ~13:40 PDT.** #466 (21-0-0) and #467 (batch12, 3/10 done) running. 31-5-0 READY (1 fresh zip,
below the bundle threshold). Released 67-1-0, 70-1-0, 79-1-0 (TRANSIENT-parked since ~10-11 AM PDT) onto
lanes e/f/h: 16 tasks in runners. Idle lanes have nothing claimable: the rest of the claimed set is PARKED
(5-1-0, 92-1-0, 20-8-0: identical blocker x5) or at the 10-attempt cap (73-0-0, 77-1-0, 15-1-0, 31-4-0).

**Cycle ~13:18 PDT.** #464 (L3 35-0-0) FAIL, 0 of 2 reviews clean; requeued with a brief. L3 21-0-0 reached
full verify READY (oracle confirm 1.0) -> #2055 / pipeline #466 (task 149756). batch12 (10 L2: 8 verify-capped
from runners launched before the cap was turned off, 2 full READY) -> #2054 / pipeline #467, 179 MB. Bundling
note: `bundle` writes `_v7/shipped/<task>.json` at build time, so a discarded bundle blocks its tasks; the 11
records from a discarded mixed L2+L3 build were moved to `_v7/shipped_discarded/` before rebuilding. The 35
unbuilt tasks are in their own session (started by the owner).

**Cycle ~12:50 PDT: #457 (batch11) 4/23 PASS** (capped 3/18, full 1/5): 24-6-0, 7-6-0, 80-7-0, 94-7-0 ->
`QCR_group_v81b11_23092026` (1oRy0fng..., shared qc@ writer), QC tracker 8/8 cells, consolidated rows 386-389
linked, audit 4/4 OK. 7-6-0's tracker row was "Available - claim me" with assignee Mukund Surendra Mishra, now
ours. 17 requeued with briefs. Day total (09-23): 24 to manual QC. 21-0-0's oracle failure was "Prompt is too
long", not a lane cap: judge_emulate now retries a too-long judge prompt on `sonnet[1m]` (Max-plan alias; never
`claude-sonnet-4-6[1m]`, which needs paid credits) and records `judge_model_substituted`. 21-0-0 relaunched
(lane e), 48-0-0 attempt 1 regrade PASS (lane z), 35-0-0 on #2051/#464. 16 tasks in runners.

**Cycle ~12:10 PDT.** #462 (48-0-0) FAIL, one seat clean, the other 1.2/1.5 on 5 criteria; requeued with a
brief. 21-0-0 had NO runner since 11:14 PDT (a pgrep false match said "already running"; check
`ps -eo pid,etime,args | grep "[s]vc_v7_lane_runner.sh SVC-PC-<t> "`, and the task's log tail). Relaunched
21-0-0 (lane v) and 48-0-0 (lane z) via svc_release_launch.sh. #457 (batch11) 22/23 settled. 16 runners.

**QC-team SOP applied ~12:30 PDT (Google Doc 1IL2s3ezzkoMpQLuGTGEK4ZU9Rjb2c_qkF0x60ye_2Zo, section 7c).**
Duplicates go in the MAIN table with EQC Status `Skip- duplicate` (9-4-0 moved: row 383 written, our stray
Duplicates row 481 cleared); resubmissions get `EQC Ready Revision` + the Resubmission change note; never move
rows. QCR docs need Expected outputs + Known limitations: template updated in `/task-doc`, today's four docs
back-filled via Docs API append (original text verified intact). Runbook CURRENT SEQUENCE updated; helpers
promoted to tools/ (svc_split_bundle, svc_release_launch, svc_return_cohort, svc_lane_time,
svc_consolidated_links). Open: the llm_backend.py OSError fix sits uncommitted in the sandbox's
EKW_QC_pipeline clone; pushing it there needs the owner's go.

**Cycle ~11:50 PDT: #445 (batch10b) 13/29 PASS** (capped 6/18, full READY 6/11). Combined batch10: capped 7/36
(19%), full READY 11/21 (52%): cap stays OFF. 12 passes -> `QCR_group_v81b10b_23092026` (161UgznzM..., shared),
QC tracker 24/24, consolidated rows 371-382 linked, audit 12/12. SVC-PC-9-4-0 passed but Mateeh Ullah already
submitted it -> Duplicates row 460 (tracker row left as is). `svc_consolidated_record.py` --dup was broken
(dup_free undefined, NameError) - fixed. L3 48-0-0 reached full READY -> #2042 / pipeline #462 (task 149328),
ids sent to the masters session. 21-0-0 has hit 6 lane usage-limits, all during its oracle.
Day total so far (09-23): 46-0-0 + 79-2-0 + 6 (#444) + 12 (#445) = 20 to manual QC.

**VERIFY-CAP PILOT RESULT (#444, batch10a, returned ~11:10 PDT): FAILED, cap turned OFF.** verify_capped
1/18 passed DataOS; full verify READY 5/10. The local verify DOES predict DataOS at this stage (the "21%
precise" figure was an older reviewer on unfixed tasks). Runner default is now `VERIFY_CAP=99` (off; set 2 to
re-enable), deployed ~11:20 PDT. Runners started earlier still carry the cap until they finish. batch11
(#2036, 23 tasks: 18 capped + 5 full) was uploaded anyway: a DataOS return gives capped tasks real findings to
fix from, and a second capped sample.
Passes from #444 (6): 10-5-0, 15-5-0, 19-6-0, 66-2-0, 76-4-0 (capped), 92-3-0 -> QCR doc
`QCR_group_v81b10a_23092026` (1UtKZRq5..., shared), QC tracker 12/12 cells, consolidated rows 364-369 with links,
audit 6/6 OK. 22 rejects requeued with briefs.

**Cycle 2026-09-23 ~11:15 PDT.** #444 (batch10a, 28) COMPLETED; return 352 MB downloaded, uploading to sandbox.
#445 (batch10b) still running. batch11 = 23 fresh zips, 316.5 MB (< 500 MB), check + download in progress.
Idle-lane fix again: 10 free lanes had nothing to claim, so released and launched directly 21-0-0 (lane i; lanes s
and r had capped under it), L3 55-0-0 (s) and 47-0-0 (c), and the regrade-stuck 2-4-0, 92-1-0, 5-1-0, 52-3-0,
67-2-0, 25-1-0, 56-1-0 (their regrade failures predate the INFRA and formula-audit fixes); 57-1-0, 91-6-0,
42-9-0 released to the queue. 19 runners. Helper: `_scratch_release_launch.sh "<lanes>" TASK...` (sandbox).
Fixed today: judge_emulate now runs test.sh's formula-audit block (a624fedb); llm_backend.py treats OSError
(claude binary mid-update) as infra.

**Cycle 2026-09-23 ~10:08 PDT: stuck-task release.** Queue had 0 unclaimed tasks, so idle pool workers exited
(the pool starts a new pass only when every worker, including ones waiting out a capped lane up to 14h,
returns). L3 21-0-0 and 53-0-0 were parked "transient x3" (capped lanes, not defects) and nobody was working
them; 79-1-0, 67-1-0, 70-1-0 the same. Released those 5 plus old-runner verify parks 14-1-0 and 1-5-0
(claims -> `_v7/claims_released/`, retries reset); launched directly on free lanes s/o/y/r/c/z (21-0-0 on s);
the pool itself took 53-0-0 (lane u). 17 runners. Lanes capped now: t, l, f, v, m, k, q.
**Watch for this every cycle:** `transient x3` parks on L3 tasks, and exited workers with a non-empty release.

**Cycle 2026-09-23 ~10:05 PDT: FIRST L3 APPROVAL.** #432 returned: **46-0-0 PASS** (0/0 majors; task 148141),
frozen; QCR doc `QCR_SVC-PC-46-0-0_23092026` (104d8rlH..., shared qc@turing.com writer). 48-0-0 FAIL (1.5 only),
requeued. Masters session (16:22 UTC, Khiem's yes): placeholders 143605/143611 moved to 1941; WIP 1911 now has
46-0-0 = 148468, 48-0-0 = 148467, 21-0-0 = 148118; MOVE 148468 WIP -> Master-SVC 1722 waits for Khiem's yes
there. Trackers DONE ~10:15 PDT after Khiem's gcloud re-login: QC tracker row 175 -> submit for manual QC /
Khiem Doan; consolidated row 361 (tool inserted one row above the EQC note, live queue was full), audit OK.
batch10 halves re-downloaded after a connection reset (exact sizes, testzip clean): batch10a -> #2020 (28 tasks,
pipeline #444), batch10b -> #2021 (29 tasks, #445), both RUNNING, 0 ingest errors.

**Cycle 2026-09-23 ~08:15 PDT (no cycles ran ~23:45-07:55 PDT; lanes kept working).** Since 06:45Z: 55 READY
(34 verify_capped, 21 full READY, incl. L3 46-0-0 and 48-0-0); deferred at cap: 47-0-0, 55-0-0, 91-6-0; 18
runners, queue 117. 21-0-0 #388 finished (its Terminus eval had hung ~3h, then scored 0.86): FAIL, both
seats majors (1.1/1.3/1.5/1.6/1.7 on 9 criteria), requeued with a brief. L3 46-0-0 + 48-0-0 -> dataset #2005
(svc-v81-l3r2; tasks 148141 / 148142), pipeline #432 RUNNING; ids sent to the masters session for the WIP
swap. L2: 57 fresh zips bundled as svc-v81-batch10 = 594 MB, over **DataOS's 500 MB zip limit (owner)**;
split via `_scratch_split_bundle.py` (sandbox /root/qc/; moves the unuploaded bundle's shipped records to
`_v7/shipped/_not_uploaded/`, rebuilds halves through svc_bundle_upload.py) into batch10a (28 tasks) and
batch10b (29 tasks), ~297 MB each, both check FRESH, downloading (~0.5 MB/s link). Keep bundles < 500 MB.

Cycle ~23:45 PDT: batch9 (#1946/#396) returned in 27 min: **79-2-0 PASS** (0/0 majors) -> accepted, QCR doc
`QCR_SVC-PC-79-2-0_22092026` (12LRYP3j..., shared qc@turing.com writer), QC tracker row 218, consolidated
row 317 (audit OK). 57-2-0 FAIL (1.4/1.5/1.6 on 8 criteria), 79-1-0 FAIL (one 1.5 on r06c): requeued with
briefs. 21-0-0 #388 still RUNNING 3h+: its Terminus 2 eval #532087 is hung (Codex + oracle 1.00, 33/33);
left alone, cancelling could exception the pipeline. Consolidated SVC tab gained an EQC note row "Put your
tasks above in the table ... Do not move tasks below"; `svc_consolidated_record.py` now ends the live queue
at that row (its first 79-2-0 write targeted row 334, below the note, and did not land). Coverage trace live:
82-2-0 and 92-3-0 clean. 0 verify-capped ships so far. 66-2-0 still on the old runner (mid-fix).

Cycle ~23:12 PDT: svc-v81-batch9 (57-2-0, 79-1-0, 79-2-0; check FRESH, 14,239,765 B) -> dataset #1946,
pipeline run #396 RUNNING; all 3 tasks READY with 1 warning each. 25-2-0 moved onto the new runner (stopped
at a safe point, claim moved to `_v7/claims_released/`); 66-2-0 still mid-fix on the old runner. Datasets
#1946 and earlier still need sharing with TFRL_QC + Ardeshir_team (user action).

Lanes probed 22:50 PDT: f j k l m o weekly-capped (resets Sep 23 10:00 PDT to Sep 26 14:00 PDT); s free.

## v8.1: STALE-ZIP GATE + SINGLE-SOURCE RULES (2026-09-22 EVENING)

**batch_of_18 (svc-v8-batch1) returned 8 of 18 PASS** (both GPT seats 0 majors): 11-2-0, 12-6-0, 2-7-0, 22-3-0,
29-2-0, 3-4-0, 38-1-0, 92-4-0. 12-6-0 and 29-2-0 are duplicates of human submissions (Ezekiel, Salman). The
10 rejects: 11 of 23 majors were the same defect still present, 9 were introduced by our own fix. Full record:
[batch18-return-analysis-2026-09-22.md](batch18-return-analysis-2026-09-22.md). User decision: one more v8 round
for all 10 (they are over the 3-round cap; the cap is waived for this round only).

**Three root causes, each now fixed in code, not in prose:**
1. The runner's verify + fix prompts still said not to add a criterion, so 1.5 holes could not be fixed.
   -> `tools/svc_fix_method_rules.md` is the ONE rules file (R1 category-aware, R2 fix the whole class, R3
   re-audit each rewrite, R4 full per-criterion audit, R5 golden satisfies each criterion's letter, R6
   checkable under rewardkit 0.1.7). The runner embeds it in rebuild, fix and verify prompts; the brief
   builder embeds it in each brief. Line 1 is `METHOD_VERSION`.
2. **The stale-zip hole (third occurrence):** four zips built at 04:00Z shipped at 13:34Z after a later pass
   re-edited their packages and re-verified NOT-READY. -> builder writes a freshness manifest per zip;
   `tools/svc_bundle_upload.py` is the ONLY bundle path and excludes any task whose package, zip, verify or
   regrade changed since the build, or whose verify predates the current METHOD_VERSION; `check` re-runs
   that right before upload; the runner retires a task's ready zip the moment it is reworked; hook
   `enforce_svc_bundle_gate.py` blocks any other archive of SVC-PC material, with no override.
3. Nothing wrote `lastreject.sha`, so Gate 5 (identical resubmit) could not fire. -> `tools/svc_record_return.py`
   is the return intake: freeze passers, fingerprint rejects from DataOS's own copy, archive stale records,
   requeue.

**Changing a rule:** edit `tools/svc_fix_method_rules.md`, bump `METHOD_VERSION`, deploy, then
`svc_bundle_upload.py sweep --apply`. Each zip verified under the old version is refused at ship time and
requeued; the runner re-verifies it without editing first (mode `reverify`).

**Current state 18:40Z:** pool relaunched on runner v8.1. Queue head = 10 swept pre-gate zips (re-verify) then
the 10 batch_of_18 rejects (directed rebuild on briefs carrying all rounds + the rules). `accepted.txt` = 12.
22-2-0 parked (same eval-regrade blocker 5x). Nothing ships except via `svc_bundle_upload.py bundle` + `check`.

**Update 2026-09-22 ~19:50Z (freeze list + harvest returns + triage):**
- **Team do-not-touch list** (`tools/svc_build_freeze.py --push`): built from BOTH trackers (consolidated EQC
  not-Reject = submitted; Combined Approved/Submitted = submitted; assigned to someone other than Khiem =
  human-owned). 431 ids -> `/root/qc/_v7/do_not_touch.txt`; `svc_ship_manifest.accepted_set()` (builder +
  bundler) and the runner (parks at start) honour it. Stopped 6 lane runs on listed tasks (6-2-0 Salman's,
  15-2-0 Jyotsana's, 2-6-0 ours already EQC Done, 17-4-0, 17-7-0, 12-3-0); queue pruned. Re-run it before
  every bundle.
- **Harvest returns pulled straight from DataOS to the sandbox** (Download > Dataset with runs gives a signed
  storage URL; curl it on the sandbox, no laptop hop): batch3 (#1834), batch4 (#1822), batch6 (#1825). 1 of 41
  passed (72-3-0, task-doc'd + both trackers). 37 rejects requeued with fingerprints + briefs; 3 rejects not
  requeued (do-not-touch: 7-1-0, 7-3-0, 20-4-0). 72-1-0 (DataOS validation ERROR) and 94-7-0 were never
  graded; our prefilter finds no HARD defect, cause unknown. b1 (#1857) and batch2 (#1856) uploaded 12:04,
  still grading. **harvest b5 (12 tasks) has no DataOS dataset: not uploaded.**
- **Triage** (`tools/svc_triage_queue.py --apply`): queue ordered by the latest return's major count; tasks
  with <= 2 majors (13) listed in `_v7/targeted.txt` and start in targeted-fix mode.

**Update 2026-09-22 ~20:30Z (all harvest returns except b5 in):**
- b1 (#1857): 3 of 25 pass (22-5-0, 35-1-0, 37-3-0), task-doc'd as `QCR_group_b1_22092026` + both trackers.
  batch2 (#1856): 0 of 25; 5-1-0 hit the DataOS exception with 0 reviews -> `_v7/needs_regrade.txt`
  (re-upload for a first grade, not a lane). b5 uploaded by the user ~20:10Z, grading.
- Harvest tally: 4 pass of 91 graded (72-3-0, 22-5-0, 35-1-0, 37-3-0). Plus 72-1-0 (missing hydrated
  inputs: instruction names Q1-Q3 investor updates, workspace holds only the annual letter) and 94-7-0
  (cause unknown) never graded.
- First v8.1 bundle `svc-v81-batch2.zip` (10-5-0, 12-2-0, 19-4-0, 36-5-0) built by `svc_bundle_upload.py`,
  `check` FRESH, pulled to `svc-v8-upload/` (21,904,407 bytes both sides). Awaiting user upload.
- Queue 116 (all with complete briefs), 21 targeted. 21-2-0 parked after 25 attempts.

**Update 2026-09-22 ~20:45Z (new deterministic gate from the two tasks DataOS dropped):** 72-1-0 and 94-7-0
failed DataOS upload with `rewardkit.discover() failed: TypeError("unhashable type: 'list'")`: `judge = [panel
list]` in judge.toml loads under our rewardkit 0.2.0 and crashes under DataOS's pinned 0.1.7 (same engine gap
as 16-1-0). Corpus scan with `tools/svc_discover017_check.py` (0.1.7 venv): exactly these 2 of 169 fail. Fixed
(identical-model panel -> single judge string); builder Gate 1b now runs the 0.1.7 loader and refuses on
failure. 72-1-0 also had missing inputs (Q1-Q3 investor updates) - hydrated from the corpus (md5 matches two
independent copies). Uploaded by Claude on the user's request: `svc-v81-batch2` -> dataset #1872, pipeline
run #362; `svc-v81-fixdiscover1` (72-1-0, 94-7-0) -> #1875, run #365. Dataset #1873 (`svc-v81-hydrate1`) holds
the pre-fix 72-1-0 in ERROR and can be archived. b5 uploaded by the user as "batch 5 svc v8".

**Update 2026-09-22 ~21:02Z:** b5 (#1863) returned 0 of 12 (11 requeued + briefs, 7-4-0 do-not-touch).
Harvest final: 4 pass of 103 graded. New lane zips 11-4-0, 17-5-0, 53-1-0 -> `svc-v81-batch3` (#1877, run
#367); bundler refused re-shipping the 4 batch2 tasks ("exact bytes already shipped"). In flight on DataOS:
#362 (3/4 done), #365 (1/2), #367. Queue 127, 22 targeted.

**Update 2026-09-22 ~21:50Z (30-min loop running, pool fix):** #1872 returned 2 of 4 (19-4-0, 36-5-0), #1875
1 of 2 (72-1-0); all 3 task-doc'd (`QCR_group_v81b2_22092026`) + both trackers. 5-1-0 re-grade uploaded
(#1884, run #370). Accepted/submitted by us: 12 tasks. **Pool fix:** a capped lane used to bow out and idle
until the whole pass ended (19 lanes healthy, 12 working). `svc_v7_pool.sh` now starts a worker on every
candidate lane; each adopts a running runner, then waits for its own window (re-probe every 900s) and rejoins.
Controller swapped without stopping runners: 19 runners on 19 healthy lanes; d, e, g, k, o re-probe on their
own. In flight: #367 (batch3), #370 (5-1-0). One fresh ready zip (41-5-0) waiting for a bundle of 3. This
records process state only; it does not establish that any queued task will pass.

**Update 2026-09-22 ~22:22Z:** batch3 (#1877) returned 2 of 3 (11-4-0, 53-1-0 pass; 17-5-0 requeued).
Both task-doc'd (`QCR_group_v81b3_22092026`) + both trackers; 11-4-0 was a resubmission, so its existing
consolidated row 315 (prior rev 120557, Reject) was updated in place (`svc_consolidated_record.py` now does
this for Reject rows only, and places new rows after the last filled row, never in a hole inside another
submitter's block). Accepted by us: 14. **5-1-0 re-grade (#1884) failed again: `ImageBuildError`.** Its
Dockerfile is the only one in the corpus that runs `dvc pull` against a private bucket DataOS cannot reach;
the package already holds `data/`, but 1,179 files against the pointer's 1,181, so removing the step needs a
source check for the two missing files first. Held; do not re-grade until fixed. `svc-v81-batch4` (10-4-0,
20-1-0, 41-5-0) -> dataset #1891, run #371. **DataOS credits: $4,722 of $5,200 used** (about 26 task-rounds
left at $18.46). Consolidated SVC tab has 2 empty rows left above the Duplicates heading; the tool aborts
rather than insert rows, so more space is needed before the next batch of 3 or more passers.

**Update 2026-09-22 ~22:45Z:** batch4 (#371) still grading (3 running). **Manual QC (EQC) rejected all three
`QCR_group_b1` tasks: 22-5-0, 35-1-0, 37-3-0** (consolidated rows 261-263, G = Reject), plus earlier EQC rejects
14-1-0, 20-8-0, 6-6-0 and the 12-6-0 duplicate. No reject reason was found in the QCR doc (one tab only; the
row links point at tabs t.1/t.2 that do not exist), the Combined tracker, the DataOS task page, or Slack.
These tasks stay on `accepted.txt`, so lanes will not touch them until the feedback is found; reworking them
blind would be guessing. One fresh unshipped ready zip (52-2-0); below the bundle threshold.

**Update 2026-09-22 ~22:50Z: cause of the b1 EQC rejects found (user).** The DataOS datasets were never shared with
the QC teams, so EQC could not open the tasks. The user shared #1857 with `TFRL_QC` + `Ardeshir_team` (Viewer); the
rejects are expected to clear. Share audit of our datasets: only #1816 (batch of 18) and #1857 were shared. Datasets
holding submitted tasks and still unshared: #1834 (72-3-0), #1872 (19-4-0, 36-5-0: Ardeshir_team added, TFRL_QC
missing), #1875 (72-1-0), #1877 (11-4-0, 53-1-0); plus #1891 (batch4, grading). Claude's share on #1872 was stopped by
the auto-mode classifier as a permission grant, so the remaining shares are the user's. `/task-doc` now carries
step 3b (share the dataset with both teams).

**~22:53Z:** user reset consolidated rows 261-263 (22-5-0, 35-1-0, 37-3-0) to EQC ready and shared the datasets.
Read back via the DataOS shares API: #1816, #1834, #1857, #1872 carry both TFRL_QC and Ardeshir_team (Viewer);
#1875, #1877, #1891 carry TFRL_QC only.

**Update 2026-09-22 ~23:14Z:** batch4 (#371) returned 2 of 3 (20-1-0, 41-5-0 pass; 10-4-0 requeued); both
task-doc'd (`QCR_group_v81b4_22092026`) + both trackers (consolidated rows 324-325, the last free rows above
the Duplicates heading). Accepted by us: 16. `svc-v81-batch5` (1-1-0, 12-2-0, 14-6-0, 15-4-0, 52-2-0) -> dataset
#1899, run #373; needs the TFRL_QC + Ardeshir_team share. Lanes: 19 runners, queue 124.

**Update 2026-09-22 ~23:42Z:** batch5 (#373) returned **4 of 5** (1-1-0, 14-6-0, 15-4-0, 52-2-0 pass; 12-2-0 one
clean seat of two, requeued). Doc `QCR_group_v81b5_22092026` shared; Combined tracker 8/8 cells. **Consolidated
rows NOT written: the SVC tab has no empty rows above the Duplicates heading.** The exact command waits in
`ekw/svc-consolidated-pending.txt`. Accepted by us: 20. Credits $4,777 of $5,200 (batch4+5 cost about $55 for 8
tasks, about $7 a task). Lanes: 18 runners, queue 122. No fresh ready zips this cycle.

**~23:58Z correction (user caught it):** the consolidated SVC main list is split by a **"Rejected" heading**:
rows above it are the live EQC queue, rows below it are EQC rejects. `svc_consolidated_record.py` had appended
53-1-0, 20-1-0, 41-5-0 after the last filled row, i.e. UNDER Rejected, and had edited 11-4-0's old reject row
in place (also under Rejected). Fixed: the three rows cleared and 11-4-0's reject row restored from the
snapshot (`_scratch_consolidated_fix.py`, content-matched and read back); the tool now writes only into the
live queue, inserts rows above Rejected when short (user authorised "add the rows as needed"), and gives a
resubmission a fresh live row that names the prior reject row. All 8 (11-4-0, 53-1-0, 20-1-0, 41-5-0, 1-1-0,
14-6-0, 15-4-0, 52-2-0) now sit in live rows 288-295. `python tools/svc_submission_audit.py <tasks>` checks every
submission in both trackers: 20 of 20 OK. This checks tracker placement only, not EQC outcomes.

**~01:20Z (user asked why nothing landed for 1+ h):** 19 runners were all active but mostly looping. (1) Bug: 73-2-0
joined do_not_touch mid-run; the runner checked only at start and read the zip gate's freeze refusal as a defect,
looping 19 attempts / 6.5 h on lane z. Fixed: `freeze_check` at every attempt; runner stopped. (2) Churn: about 7
lanes are on attempts 9-17. `ready.txt` shows 41 of 42 converged tasks needed <= 8 attempts (1 needed 12), so
tasks past ~10 attempts almost never converge while 118 tasks wait. User chose: cap at 10, defer (not drop).
Deployed ~01:25Z; runners already past 10 stopped and deferred: 19-6-0 (14), 15-5-0 (10), 26-8-0 (18), 79-1-0 (15),
25-2-0 (11), 92-3-0 (10). `_v7/deferred.txt` is requeued once the queue drains (runbook, Pool control).

**~01:55Z: oracle emulator crash on programmatic checks, fixed.** Freed lanes hit TRANSIENT on 41-4-0, 73-0-0, 1-5-0:
`judge_emulate.py` crashed (AttributeError) on dimensions with no LLM judge (tests/**/checks.py,
checks_deterministic/*.py, now added by lane rebuilds on 6 packages), and the runner read the crash as a lane cap.
Emulator now runs them via rewardkit's own `Reward.run()` against the rebuilt /app; dry oracle proves the goldens
pass them (73-0-0 4/4, 41-4-0 14/14, 1-5-0 5/5, 35-1-0 4/4). Runner clears the stale oracle json and parks
"oracle CRASHED" on a traceback. 77-8-0 (parked transient x3 by this bug) unparked. `tools/judge_emulate.py` is now
vendored in this repo; the sandbox copy is the deployed one (md5 63fae5be).

**~02:40Z: the "stuck" tasks were mostly tooling, not content (5 read-only investigators on the 12 hardest).**
(1) Usage limits: 2-4-0, 21-2-0, 21-0-0, 36-3-0 burned up to 27 attempts on session/weekly-limit refusals with content
already fixed; the runner now exits TRANSIENT on a limit line after every Claude step and never lets a refusal
overwrite a verify record. (2) Judge JSON glitches: 25-2-0, 15-5-0, 92-3-0, 19-6-0 lost attempts to one malformed
reply zeroing a group; `judge_emulate.py` now retries 3x. All 10 cleared tasks requeued at the head. Remaining
content notes from the investigators, for the lanes: 21-0-0 drop r014; 25-2-0 loosen c42 (either booked figure);
15-5-0 re-add a still-outstanding criterion (a15); 26-8-0 r5b class-level basis wording; 20-8-0 six over-strict
criteria (D1-D6 in its verify record) plus a stray `_formula_authenticity_report.md` in solution/files.
**Owner decisions still open:** 79-1-0 (deferred): reviewers flag its 17.6 MB corpus (under the 35 MB budget) as a
1.8 packaging defect with no defined remedy. 5-1-0: drop the `dvc pull` block, but the package is 2 files short of
its dvc manifest and no sandbox copy has them; the source corpus on Drive has not been checked yet.

**~02:50Z: L3 PRIORITY (user, mission critical): 4 L3 tasks through DataOS comprehensive review tonight.**
Population comes from the QC tracker tab `SVC QC Tracker A(see combined` column F (59 L3 tasks). Ours with a package:
21-0-0, 53-0-0, 46-0-0, 55-0-0, 35-0-0 (the unclaimed "Available" L3 tasks have no package on the sandbox, so they
would be a from-scratch build). All five put at the queue head and running: 21-0-0 lane b (content already fixed,
only r014 left), 53-0-0 lane r (3 majors last round), 46-0-0 lane x (4), 55-0-0 lane f (4), 35-0-0 lane w (5, backup).
Lanes freed by pre-empting old 25-cap runners past attempt 10 (15-1-0 x, 14-1-0 f, 31-4-0 w: deferred) and 75-2-0
(lane b, requeued); a duplicate 75-4-0 runner on lane r was killed. **Upload the first L3 zips alone, do not wait for
a bundle of 3.** 79-1-0: owner decision = trim the environment to what the task uses (<5 MB), no externalization;
recorded in `ekw/svc-owner-notes/SVC-PC-79-1-0.md`, which the brief builder now appends to the brief as a binding
OWNER DECISION section (`_deepbriefs/_owner_notes/`), so it survives brief rebuilds. Requeued behind the L3 tasks.
5-1-0: resolved (~03:05Z). The dvc pointer lists 1,181 paths but the original `dvc push` sent 1,179 files
(`pipeline/templates/svc_fullcorpus_dvc/README.md`, verified 2026-08-27), exactly what the package ships; nothing in
the task references anything else. Owner decision `ekw/svc-owner-notes/SVC-PC-5-1-0.md`: drop the dvc block (DataOS
never injects the bucket token). The brief builder now writes a brief from an owner note alone (5-1-0 was never
graded, so it had none). Queued behind 79-1-0. It is a never-graded task: bundle it with `--first-grade`.

**~02:50Z cycle:** `svc-v81-batch6` (12-2-0, 17-5-0, 41-4-0, 67-2-0, 79-2-0) -> dataset #1920, run #381; needs the
TFRL_QC + Ardeshir_team share. Credits $4,777 of a raised $5,700. L3 lanes all on attempt 1 (55-0-0 released once by a
lane-f usage cap, re-claimable). **L3 pin:** `_v7/priority.txt` (source `ekw/svc-priority.txt`) lists the L3 tasks and
`svc_triage_queue.py` now keeps them at the head on every re-sort (dry run confirmed).

**~03:45Z:** batch6 (#381) returned 2 of 5 (12-2-0, 17-5-0 pass; 41-4-0, 67-2-0, 79-2-0 requeued with briefs).
Both task-doc'd (`QCR_group_v81b6_23092026`) + both trackers (consolidated live rows 304-305); audit 2/2 OK. Submitted
by us: 22. `svc-v81-batch7` (10-4-0, 79-1-0 trimmed 18 MB -> 540 KB, 80-6-0, 82-2-0) -> dataset #1926, run #385.
L3 loop state: 21-0-0 and 46-0-0 at oracle 1.0 + regrade PASS, verify NOT-READY; 53-0-0 and 55-0-0 regrade FAIL;
35-0-0 golden at oracle 0.9685 (fails one criterion). Datasets #1920 and #1926 need the two QC team shares.

**~03:52Z L3 push:** (a) `svc_prefilter.py` accepted nothing named in files= unless physically in the package, so
35-0-0 (which lists the test.sh-generated `<deliverable>.formula_audit.md`, exactly as DataOS's 1.8 finding asked)
could never zip. Now that one generated suffix is accepted when the deliverable ships and test.sh generates it;
corpus-wide re-run: only 35-0-0 changed (2 HARD -> 0). (b) 53-0-0's "invalid" round was judge timeouts; its
judge.toml already carries timeout = 900. (c) L3 briefs + every fix prompt now carry an owner note pointing at three
tasks DataOS accepted today (19-4-0, 36-5-0, 53-1-0) as rubric-style exemplars; the runner appends owner notes to
every fix/rebuild prompt, not only the seed brief. 35-0-0 and 55-0-0 restarted to pick this up. (d) Resubmit track
record since v8.1: 13 of 22 fixed tasks passed (59%). A corpus-provenance investigator (GitHub vs Drive, mojibake
My Drive paths) reported: the corpus is NOT in GitHub (the pipeline repo holds only a DVC pointer to
gs://colab-bench; `hydrate_environment.py` copies named files, `assemble_task.py` ships the pointer). All five L3
packages have complete corpora for what their prompts and judges name; 35-0-0's My Drive paths are byte-identical
(plain hyphen), so its old 1.8 path finding does not reproduce. 55-0-0 ships the whole 56.7 MB corpus. Mojibake
("ΓÇö") folder names exist in 100 of 170 packages; solver-visible only where a prompt or judge quotes the literal
path (21-0-0's judge uses the on-disk name, so it is consistent). Not checked: the GCS bucket itself.

**~04:25Z L3 fast-track (owner decision, 2026-09-22 ~9:10 PM PT):** "Also build 2 raw L3 tasks" = fast-track 21-0-0 and
46-0-0 AND build two never-graded L3 tasks. (1) `svc_build_upload_zip.py --fast-track REASON --oracle-json <json>` waives
ONLY Gate 2's READY verdict; it requires an oracle result of 1.0 newer than the last package edit, every other gate
runs, and the manifest records `fast_track` + the oracle file's sha (`svc_ship_manifest.check_task_zip` re-checks it).
21-0-0: golden 1.0 (03:55Z) + regrade PASS (04:17Z) on the same bytes, runner stopped during review, no edits after the
oracle -> `svc-v81-l3ft1` dataset #1931, run #388. 46-0-0: the files that passed at 04:09Z were overwritten by attempt 5
before its runner was stopped, so the current files are being re-proven (oracle 2x + regrade on lane x's account; the
sandbox's default Claude account is at its weekly limit). (2) 47-0-0 and 48-0-0 built from 00_fetched with
`svc_pc_batch_convert.py`; `assemble_task.py` adds a `dvc pull` Dockerfile block to every SVC build, which DataOS cannot
run (5-1-0's ImageBuildError): the 48-0-0 builder removed it, 47-0-0's was removed with `_scratch_strip_dvc.py`, and
`svc_prefilter.py` now makes `dvc pull` a HARD defect (corpus scan: only 47-0-0 had it at the time). Both uploaded as a
first grade: `svc-v81-l3first1` dataset #1929, run #386. Their findings feed the lanes for round 2.
Datasets #1929 and #1931 need the TFRL_QC + Ardeshir_team share.

**~04:32Z:** batch7 (#385) returned 1 of 4 (80-6-0 pass; 79-1-0 and 82-2-0 one clean seat each; 10-4-0 fail); 80-6-0
task-doc'd (`QCR_SVC-PC-80-6-0_23092026`) + both trackers, audit OK. Submitted by us: 23. Rejects requeued behind the
L3 pin. Still grading: #386 (47-0-0, 48-0-0), #388 (21-0-0).

**~05:10Z:** 46-0-0 re-proven on its current files (oracle 1.0 on 2 runs + regrade PASS, lane x account) and fast-tracked:
`svc-v81-l3ft2b` dataset #1934, run #390. Two tool fixes on the way: the builder now stores the oracle path absolute (a
relative path read as "missing" from another cwd), and a bundle that fails `check` leaves a ship record that blocks a
rebuild as "already shipped"; that record was moved to `_v7/shipped/_not_uploaded/` (tool change still to do: record
ships only after a passing check). 47-0-0 / 48-0-0 first grade (#386): both rejected (13 and 8 majors), requeued with
briefs + L3 notes. Priority list now 53-0-0, 55-0-0, 35-0-0, 47-0-0, 48-0-0 (21-0-0 and 46-0-0 are on DataOS).
35-0-0 golden now 1.0 (was 0.9685). Still grading: #388 (21-0-0), #390 (46-0-0).

**~05:14Z:** `svc-v81-batch8` (26-8-0, 41-4-0, 5-1-0 with its dvc block removed, 66-2-0) -> dataset #1935, run #391.

**~05:31Z:** 46-0-0 fast-track (#390) came back ONE clean seat of two; the other seat has a single 1.4 major (drop the
mandatory CIR-219/CIR-101 narration; accept a handoff control tied to named findings anywhere). Pinned first in
`priority.txt`; lane n pre-empted from 82-2-0 (requeued) and running it. Standing rule tonight: an L3 task whose
golden is 1.0 and regrade PASS on the same bytes is fast-tracked and uploaded alone. 21-0-0 (#388) still grading
after 65+ minutes.

**~05:41Z:** batch8 (#391) 0 of 4 (66-2-0 one clean seat; 5-1-0 got its first real review after the dvc fix; all four
requeued with briefs). 21-0-0 (#388) at 2/5 pipeline nodes after 75 min (large package), still running.

**Harvest (b1-b6, 105 tasks) is unaffected:** built before this gate from never-graded packages; still with the
user to upload. Future harvests use `svc_bundle_upload.py bundle --first-grade`.

## NEVER-GRADED HARVEST (2026-09-22 LATER, NEWEST - read first)

A SECOND workstream ran alongside the graded-fix loop. The user decided (14-hour window): **run all ~105
never-graded tasks on DataOS now for first feedback; do NOT build the self-solve seeder.** Rationale: the
eval-regrade gate needs a PRIOR grade so it cannot run on never-graded tasks; the seeder only pre-screens
locally (weak signal, ~1 day) and cannot get a task ACCEPTED. DataOS-now is the only path that crosses the
finish line inside the window.

- **Guard = `svc_prefilter.py` Gate 1 + cold audit** (the only guard that applies before a grade exists). The
  exit-gate's eval-regrade check is N/A here, so harvest zips are built with `[skip-svc-fix-method]` (logged,
  documented: first-ever grade). Not a safeguard bypass - the applicable subset.
- **Enumeration:** corpus 169 = 4 accepted + 78 graded/in-pipeline + 33 done-excluded + **105 never-graded**.
  Prefilter: 86 clean, 19 HARD. All 19 resolved, **0 held**:
  - 8 grammar bombs -> `svc_split_grammar_dirs.py --max 15 --apply`, PROVEN weight-preserving against
    rewardkit's normalized `_weighted_mean` (reward.py:33-37); golden stays 1.0.
  - 6 "leak" = FALSE POSITIVES (benign "ignore ... answer keys" anti-contamination phrasing; prefilter leak
    check over-flags - refine later).
  - 7 files= gaps = REAL (judge files= names a companion report the instruction never asks for) -> drop the
    phantom path + remove the criteria that grade it (`_scratch_fix_filesgap.py`). 3-9-0 lost 28 of 66 (now a
    reduced 38-criterion xlsx task - FLAGGED; author the audit doc into the instruction if it was intended).
- **Shipped:** 7 zips in `C:\Users\khiem.doan_turing\svc-v8-upload\` (NOT Downloads), 123 tasks total (105
  harvest + 18 gate-confirmed batch1). Sandbox copies `/root/qc/_harvest/`. Lists in `UPLOAD-MANIFEST.md`.
- **15 corpus packages edited in place** (8 splits + 7 files= fixes); no graded/accepted task touched.
- **OPEN (after verdicts):** the ~15-criteria grammar threshold is unverified locally (harvest is the
  datapoint); 3-9-0 reduced-vs-authored; prefilter leak FP refinement.
- **park-after-3 bug FIXED** in `svc_v7_lane_runner.sh` (now `MAX_FIX_ATTEMPTS=25`, `STUCK_LIMIT=5`; the
  "default 3" text elsewhere in this plan is STALE). Re-run of the ~41 unshipped graded tasks is LIVE.

## PASS-3 FAILURE + REVISED APPROACH (2026-09-22, read after the harvest section)

**SVC-PC-16-1-0 failed pass 3.** After 5+ rounds, a complete-brief directed Opus rebuild, the full
per-criterion audit, the growth guard, and a deep Fable adversarial verify, it came back REJECTED again -
both GPT-5.6-sol seats, one 1.5 major each, BOTH new: r017 (formula stored-value coverage) and r009b (the
golden itself cites a file with no internal locator). The proof gate HELD: we did NOT scale. Return:
`Downloads/SVC-PC-16-1-0_with_runs (1).zip`, rev_1__128263.

**Root cause, honestly (why 5 rounds and every local check passed a task DataOS keeps failing):**
1. **Engine mismatch = false green.** Our oracle runs `harbor-rewardkit 0.2.0`; DataOS pins **0.1.7**
   (confirmed: oracle venv 0.2.0, task `tests/test.sh` pins 0.1.7). The 0.1.7 reader cannot tell a live
   formula from `=1/0` (identical extraction), so the oracle scored the golden 1.0 while DataOS's 0.1.7
   reader fails r017. Our green light and DataOS's are computed by DIFFERENT engines. This is the structural
   bug behind the whole loop.
2. **The oracle is a LENIENT grader.** It passes the golden on things GPT-5.6-sol fails strictly (r009b:
   the golden gives a bare filename, no locator; the oracle passed it, GPT failed it). The oracle cannot
   catch "the golden is too lenient for GPT" because the oracle IS the lenient grader (the severity wall,
   in the golden-grading direction).
3. **Recompute-from-source checks correctness, not citation completeness.** r009b is not a wrong number;
   the fact is right, the golden just omits WHERE in the file. Recompute passes a correct fact with an
   incomplete citation.
4. **No check asked "does the golden's own text strictly satisfy every criterion's letter at GPT
   severity"** until the on-lane verify was upgraded 2026-09-22 to do exactly that (golden-satisfies-every-
   criterion). Even so, an Opus verify may be as lenient as the oracle - the reliable fixes are #1 and
   measuring against DataOS itself.

**GPT-5.6-sol as OUR reviewer is OFF the table (we do not have it). Do not propose it again.**

**The two pass-3 findings, exactly (this is HOW every local check passed a task DataOS failed):**
- **r017 (1.5, formula stored-value) is an UNCHECKABLE criterion, not a wrong golden.** The DataOS reviewer
  proved it: it injected `=1/0` into the golden's `Roster Reference!G32` and the judge's extraction of that
  cell was **byte-for-byte identical (same SHA-256, 25,414 chars) to the good golden's**. The pinned reader
  (rewardkit 0.1.7 -> MarkItDown/Pandas) renders a formula cell as its displayed value and cannot see whether
  the formula underneath is live or `=1/0`. So a criterion demanding "every formula has a stored computed
  value" is one the grader physically cannot enforce - a broken answer and the golden look identical to it.
  Our oracle scored 1.0 because the golden looks fine to the same blind reader; recompute verified the numbers
  are right (they are). Neither check asked "can the judge tell a broken cell from a good one?"
- **r009b (1.5, citation locator) is the golden failing its OWN criterion.** r009b requires every off-ranking
  company fact to cite a source file AND an internal locator (section/¶/page). The golden's `Year 2 - What To
  Avoid!D7` names `Employee_Handbook_2021.docx` with no locator; `Roster Reference!A2` cites two files with no
  internal location for the Sarah Kim founder claim. Our oracle passed it because our judge (Claude) is
  lenient and accepted "names a source"; GPT-5.6-sol enforced the "AND locator" clause. Recompute checks the
  fact is correct, never whether the citation is complete.
- **Synthesis:** our oracle + recompute prove the golden's numbers are RIGHT. They never checked (a) whether a
  criterion is physically checkable under DataOS's blind reader, or (b) whether the golden's own text strictly
  satisfies every criterion's letter at GPT severity. Those two gaps ARE r017 and r009b.

**Revised approach (decided with the user 2026-09-22):**
- **The oracle pin to rewardkit 0.1.7 is an orchestration REWRITE, not a version swap (verified 2026-09-22).**
  `judge_emulate` is built on 0.2.0's `_discover_layout` -> `layout.groups` -> `_score_layout` model; 0.1.7
  has none of those (it returns a flat `list[Reward]` with different aggregation internals). Every OTHER
  function it uses is present in 0.1.7 with identical signatures - crucially the extraction path
  (`_read_file_blocks`/`_build_user_content`), which is where the r017 false green lives. So the targeted fix
  is NOT rewriting the aggregation spine: it is a **verifiability probe** (do what the DataOS reviewer did -
  mutate the golden's graded formula cell, confirm the pinned-reader extraction CHANGES; if identical, the
  criterion is uncheckable -> delete/reword). Deterministic, version-specific, catches the whole r017 class.
  Built as an advisory (measured before it blocks) and PR'd into `svc_prefilter.py`.
- **Verify upgrade (done):** the on-lane verify now audits the GOLDEN against every criterion + flags
  formula/extraction criteria unverifiable under the pinned reader (catches the r017/r009b classes at verify).
- **Test round, not one-task obsession:** fire ONE task per lane (~20) through the FULL v7 cycle, submit to
  DataOS in batches (5/7/10), and MEASURE the real miss rate. Rare miss -> the method works, scale. Near-100%
  miss -> the method does not clear DataOS and we stop and rethink, not iterate. This is the actual test.
- **Do NOT scale until the test round shows a real DataOS pass rate.**
- **16-1-0 is past the 3-round cut cap** - CUT (done 2026-09-22: proof gate retired, not in the test round).

**TEST ROUND LAUNCHED 2026-09-22 03:16Z.** GO fired -> daemon promoted 20 -> pool running (pid 2383630) on
~24 lanes (b-z minus s-dup), work-stealing. State: 16 tasks actively rebuilding, 4 replacements queued (claim
as lanes free), 4 original picks (`12-8-0 21-4-0 70-6-0 77-7-0`) were `_done_excluded` (a human owns them) and
the runner CORRECTLY parked them - the zero-overlap-with-humans guard working. Queue: `_v7/queue.txt`.
**Scale-up queue cleaned 72 -> 59** (`_v7/queue.staged.clean.txt`): dropped 13 `_done_excluded` tasks that
would have wasted lane-runs and touched human-owned tasks at scale. When the round produces ready zips they
land in `_v7/ready/`; run `svc_v7_batch_precheck.sh` then hand the user batches of 5/7/10 to upload. The user
uploads (the graded submission is theirs), the pool never uploads.

**FIX LOOP added to the runner 2026-09-22 (park was under-building the plan).** The first test round produced
8 ready and PARKED the rest after a SINGLE failed gate: 3 on golden < 1.0, 9 on one adversarial-verify
NOT-READY. That is the plan's step 7b/9 (feed the finding back, iterate, never ship or abandon an under-fixed
task) NOT implemented - the runner parked instead of looping. `svc_v7_lane_runner.sh` is rewritten into an
internal fix loop: rebuild -> oracle -> growth guard -> adversarial verify, and on ANY gate failure it feeds
the SPECIFIC finding (the verify record, the oracle's failing criteria, the grown criterion, the prefilter
HARD defect) back into another TARGETED fix attempt, up to `MAX_FIX_ATTEMPTS` (default 3). It parks ONLY after
it genuinely cannot converge, and the park names the residual defect - never a silent "verify failed, sit on
it". A NOT-READY verify record already on disk seeds the loop straight into targeted-fix mode. The 9
verify-refusals were high-quality real 1.4 defects (spot-checked: q04/q09/q27/q31 in 5-4-0 pin a monthly step
q34 accepts; 14-6-0 c06b asserts a methodology absent that the policy PDF provides; 11-4-0 r036c lists the
correct premium as a FAIL), so the loop is fixing real over-enforcement, not fighting a too-strict verify.
**Fix pass on the 12 parked tasks is LIVE** (deployed, syntax-checked, one per lane); convergence being
measured before the loop is called proven. Batch 1 (the 8 ready incl. 73-2-0) is the first DataOS measurement.

## PROCESS CORRECTION 2026-09-21 (batch is DISPROVEN; careful Opus directed rebuild is the method)

Read this FIRST. It supersedes any "full-sweep pool" / "oracle-in-worker" guidance below as the fix method.

**Evidence that the batch approach fails.** Waves 1 (10) + 2 (7), produced by a 15-lane Sonnet batch pool
running generic/short (25-min) full-sweep briefs, came back **0/17** from DataOS, all on 1.4/1.5. Tracing
multi-round tasks: 2-6-0 got the SAME 1.4+1.5 majors three rounds running; 11-4-0 got worse. The batch,
Sonnet, generic-brief, 25-min approach does not converge and does not clear the wall. It is disproven. Do
not run it again.

**The only thing that ever produced a pass** was a CAREFUL INDIVIDUAL rebuild: one task, on **Opus**, with a
brief naming the EXACT DataOS finding, a substantive re-derivation and rubric rebuild, hand-verified (13-3-0
golden 24-SKU re-derive, 20-3-0; both reached needs_revision/0-major). That is the working part. Scale THAT,
not the batch.

**The oracle is NOT a sufficient done-signal.** `judge_emulate` only checks the golden passes its own rubric
(catches 1.1). It is blind to 1.4 (rubric grades what the instruction doesn't require) and 1.5 (instruction
requires what the rubric doesn't check) - the exact failures. "golden 1.0" is necessary, never sufficient.

**MANDATED fix method (do not deviate):**
1. ONE task (or a few, one per lane), never a wide batch.
2. **Opus**, never Sonnet, for the rebuild - this is judgment work.
3. A sharp, hand-checked brief naming that task's EXACT DataOS finding (from
   `ekw/dataos-findings-allrounds-2026-09-21.json`) AND the specific rubric change it demands.
4. Re-derive every graded figure from source; rebuild the rubric so passing it PROVES correctness; close the
   named loophole (e.g. citation-checkability, coverage-to-full-set, dual-basis).
5. Verify: golden 1.0 on 2 oracle runs AND the named structural gap is actually closed (re-read the edited
   criteria). Long time budget (>= 45 min), not a 25-min slot.
6. Resubmit only that task; DataOS is the truth. If it flips to pass, THAT is the repeatable unit to scale
   (a few Opus directed rebuilds at a time). If a careful Opus rebuild with the exact finding still fails,
   the wall is real and the answer is GPT-5.6-sol-as-our-reviewer access, not more local fixing.

**In flight (2026-09-21, current):** SVC-PC-16-1-0 ONLY, as the single proof task. The 14-wide Opus round that
was here is KILLED - it was the same batch mistake with the model flag changed (partial briefs, no proof gate
before scaling). Do NOT scale to other tasks until 16-1-0 gets a DataOS ACCEPT. Proof marker
`~/.claude/svc_proof_pending.flag` + the rewritten hook enforce this. 16-1-0 history and current pass2 status:
`ekw/dataos-16-1-0-result-2026-09-21.md`.

### v7 per-task pipeline (end to end - THE codified process, do not deviate)

Every task that needs fixing goes through exactly this. It is per-task, individual, Opus. There is no batch
path.

1. **Graded first.** A task is never fixed blind. If it has no DataOS finding yet, its ONLY first step is to
   be uploaded once to GET graded (a harvest pass, expected to fail). Findings live in
   `ekw/dataos-findings-allrounds-*.json` + the `_deepbriefs/<task>.md` sharp brief built from them.
2. **One COMPLETE directed brief per task** = EVERY round x BOTH reviewer seats x majors+moderates at FULL
   text, no truncation. Generated by `tools/svc_build_directed_briefs.py` (NOT the old `_scratch_gen_deepbriefs.py`,
   which truncated to latest-round majors - that fragment is why GPT rejected on the part we cut). Never a
   generic shared brief on a graded task.
2b. **Cheap pre-screen FIRST** (`python tools/svc_prefilter.py <pkg>`): flags grammar bombs, files= gaps,
   leaks, mojibake, AND the mechanical 1.4 over-enforcement patterns (cardinality minima, diversity mandates,
   whitelists, self-contradiction, exact-reproduction). Catches ~60% of what GPT names from reading at
   zero LLM cost, so the Opus pass only spends effort on the semantic/corpus checks a grep cannot do.
3. **One task -> one lane -> one Opus (or Fable) agent.** Never Sonnet, never a wide batch, never a shared
   brief across lanes. Time budget >= 45-60 min (`timeout 3600`). While the proof gate is set, ONE task only.
4. **Recompute from source.** The agent reads instruction.md + golden + every judge.toml + EVERY source file
   under environment/initial_workspace/, and re-derives every graded fact itself. The golden is not trusted.
5. **Close the exact finding at the root:** 1.5 coverage -> force every instruction requirement with a
   criterion against the re-derived value, extend subset criteria to the full set, uncheckable claims must
   fail; 1.4 -> remove/repair criteria grading what the instruction doesn't require; 1.1 -> fix the golden;
   1.3 -> edit instruction.md AND task_prompt.txt identically; 1.8 -> <=15 criteria/dir, filenames, files.
5b. **FULL PER-CRITERION AUDIT (the step that actually passes the task).** The finding ledger is only what GPT
   flagged SO FAR; GPT re-audits the WHOLE task each round and rejects on defects it never named (16-1-0's
   round-5 reject was r003, a pre-existing over-enforcement never raised in 3 prior rounds). So audit EVERY
   criterion against the instruction: over-enforcement (fails/forbids what the instruction allows), coverage
   holes (a requirement no criterion enforces), and scope (a clause meant for one tab that catches correct
   behaviour elsewhere). Output a per-criterion audit table. **DIRECTION: fix by DELETING/LOOSENING
   over-constraints, never by adding qualifying text** - this task's every prior round added a rule that
   became the next round's finding.
6. **Adversarial:** build a passing-but-wrong answer; tighten until impossible. Passing the rubric must prove
   the task was solved.
7. **Two verify gates, BOTH required:** (a) golden scores 1.0 on **2** oracle runs; (b) the named structural
   gap is re-read and confirmed closed (a wrong/uncheckable answer now fails). Oracle-1.0 alone is NOT
   sufficient - it is blind to 1.4/1.5.
7b. **Adversarial verify BEFORE spending a DataOS grade.** A Fable (or independent) verifier does its OWN
   per-criterion audit and hunts for defects the rebuild missed. If it finds additional over-enforcements,
   feed them back to step 5b and re-run - do NOT resubmit an under-fixed task. On 16-1-0 this caught that
   fixing r003 alone was ~20-30% and the full fix ~40-50%, before any grade was spent. This is the gate that
   stops the whack-a-mole of resubmitting fragments.
8. **Resubmit that task** to DataOS (the only truth). The zip is built ONLY by
   `python3 tools/svc_build_upload_zip.py <task>` - it hard-gates both pre-upload checks (Gate 1 = the
   deterministic `svc_prefilter.py` pre-screen must have no HARD defect; Gate 2 = an adversarial-verify record
   `<verify-dir>/<task>.verify.md` must exist), excludes junk, and cold-audits the zip. Raw `zip`/`tar` of an
   SVC-PC package is hook-blocked (`enforce_svc_fix_method.py` rule 5), so the builder cannot be bypassed. Cap
   **3** DataOS rounds/task; after 3 with no convergence, cut the task or escalate to GPT-5.6-sol-reviewer
   access - do not loop forever.

**The deterministic-check order (what runs first, and how it relates to the A-E taxonomy).** Pre-upload,
deterministic, in order: (1) `svc_prefilter.py` - grammar bomb (>15 criteria/dir), files= gaps, answer-key
leaks, lease.json, mojibake [HARD, block the zip]; plus the 1.4 over-enforcement grep pre-screen [WARN,
triage]. (2) oracle golden 1.0 x2. These are PRE-UPLOAD checks. The **A-E failure-mode taxonomy** (20 modes,
`ekw/failure-labels-2026-08-27/`, custodian Jakub) is a different artifact: it LABELS a trial's failure AFTER
grading at the earliest broken stage (E = grader/rubric error). The grep pre-screen is the preventive
deterministic detector for the same rubric defect Stage E's "Rubric Conflicts with Task or Benchmark" labels
after the fact - same failure family, opposite ends of the lifecycle.
9. **Feed the return back** to step 2; track per-task round count and whether findings SHRINK (converging) or
   RECUR (not). Recurring same-category majors across rounds = the method isn't closing it -> escalate.

**Forbidden (hook-enforced by `enforce_svc_fix_method.py`):** the batch full-sweep pool
(`svc_fullsweep_pool.sh`), Sonnet for a rubric rebuild, a generic non-directed brief on a graded task, and
calling oracle-1.0 "shippable". Override `[skip-svc-fix-method]` with a reason, logged.

**Honest boundary (updated by the 2026-09-21 Fable audit of 16-1-0):** individual recompute reliably closes
1.1, 1.3, 1.8. The Fable audit changed the read on 1.4/1.5: the residual is **NOT primarily the severity
wall**. Both GPT-5.6-sol seats converged on the SAME enumerable list of over-enforcements, i.e. these defects
are findable by careful reading, not unpredictable severity calls. The real reasons 5 rounds failed were (1)
we handed the fixer a truncated fragment, (2) we only fixed what GPT already named while GPT re-audits the
whole task, (3) each round ADDED constraints that became the next finding. v7 attacks all three (complete
brief + full audit + delete-direction + pre-screen + adversarial-verify). Realistic effect: observed 0-major
rate ~6-12% -> ~40-50% per task after the full fix (needs_revision/0-major IS a pass, so the compound-binary
1.5 minor does not block us). NOT certainty: an occasional missed defect and genuinely ambiguous instructions
remain, and some tasks will still be cut or need an instruction edit / the workspace trim (see below).

### Why 5 rounds failed and what v7 changes (the systematic account)

**The pattern.** Every round we fixed exactly what GPT complained about, resubmitted, and GPT rejected on
something new. Three root causes:

| # | Root cause | v7 change | Status |
|---|---|---|---|
| 1 | The fixer got a TRUNCATED fragment of the findings (latest round, majors only, `[:700]`/`[:400]`), so it closed part of the problem and GPT rejected on the cut part | COMPLETE brief: every round x both seats x majors+moderates, full text (`tools/svc_build_directed_briefs.py`) | committed 6711dbda |
| 2 | We only fixed what GPT ALREADY named; GPT re-audits the whole task each round and finds new defects (16-1-0 round-5 = r003, never raised in 3 prior rounds) | FULL per-criterion audit: check EVERY criterion vs the instruction, not just the flagged ones (METHOD step 5b) | committed 5377183c |
| 3 | Each round ADDED a rule to close a gap, and every added rule became the next round's finding (the r030 6->11 coverage fix added the holder list whose cross-training clause became r003) | Fix by DELETING/LOOSENING over-constraints, never adding qualifying text | in the brief + addendum |

**Force multipliers from the Fable audit:** a cheap grep pre-screen (`tools/svc_prefilter.py`) catches ~60%
of the mechanical 1.4 defects at zero LLM cost (9 of 15 on 16-1-0) before the Opus pass; and an adversarial
verifier proves sufficiency BEFORE a DataOS grade is spent (it caught that r003-alone was ~20-30%).

### The workspace-trim root cause (corpus-wide, not just 16-1-0)

**The mismatch.** The solver sees `environment/initial_workspace/` (16-1-0: 126 files). The grader can only
open the files in each criterion's `files=` list (16-1-0: 33 distinct). So a solver can cite a file the grader
cannot open, and the grader is stuck: FAIL it (false rejection, 1.4 - the "whitelist" defect) or SKIP it
(a fabricated citation to an unseen file passes, a 1.5 soundness hole). You cannot write a correct
citation-checking rubric when grader-visible != solver-visible.

**Two fixes, different depth:**
- **In-rubric (patch, used for 16-1-0 this pass):** "a claim citing a file I can't open is neither passed nor
  failed." Stops the false rejection; leaves the fabrication hole; must be applied in all 3 places the
  whitelist lives (r027a, r027b tail, r024b). Hides the cause.
- **Workspace trim (root fix):** remove the files the grader can't use from `initial_workspace/` so solver =
  grader (33 files). Strict citation checking becomes possible AND correct - the mismatch is gone. Fable
  confirmed 16-1-0's 93 removable files are personal tax/payroll forms (I-9, W-4, offer letters, option
  grants, payroll register) that instruction.md line 29 already excludes ("leave the money to Jessica"), so
  removing them does not change the task. Cost: a Dockerfile/`initial_workspace` change + rerun
  `svc-structural-audit` + reconfirm the golden cites no removed file.

**DECISION 2026-09-21: NOT doing the trim. Staying in-rubric.** The user said "do the trim if you are 100%
sure it will help us." We are not, for five specific reasons, so per that instruction it is held:
1. It changes the customer's TASK ENVIRONMENT, not our grading. Every other v7 change fixes the rubric/golden
   (how we grade). Removing files the customer put in `initial_workspace/` may be OUT OF SCOPE for QC (we
   correct the grading, not redefine the task's inputs). If DataOS/the customer treats a shrunk environment as
   an improper task modification, the trim HURTS us. Whether it is an allowed QC action is not resolvable from
   the code - it is a call for the user or Shyam. THIS is the real gate.
2. Not all "93 removable" files are money. Fable listed `Org_Chart_Q1.png` among them; org structure is
   directly relevant to a key-person-risk ranking, so "leave the money to Jessica" (instruction.md:29) does
   not cover it. The "all 93 safely removable" claim is not airtight.
3. We have not INDEPENDENTLY verified the golden + both graded solves cite none of the 93 (Fable said so; a
   destructive env change needs our own confirmation from the golden dump + reward-details, not a subagent's).
4. It needs an `svc-structural-audit` rerun (not yet scoped) and re-establishes the whole task's validity,
   because it changes what solvers run against - not a self-contained rubric edit.
5. The in-rubric fix already handles the CURRENT blocker: 16-1-0 was rejected on the 1.4 (r003), not the
   citation whitelist. "Uncheckable claim is neither passed nor failed" stops the 1.4 false-rejection; the
   trim's extra benefit is closing a lower-severity 1.5 soundness nit, which is not what is failing us now.

**Gate to revisit:** (a) user/Shyam confirms trimming the environment is an accepted QC action, not a task
redefinition [the real gate]; AND (b) we verify ourselves that the golden and both graded solves cite zero of
the 93, and re-check each of the 93 is genuinely non-usable (not just the org chart). (b) we can do; (a) is
the user's. Until both clear, stay in-rubric.

### Extrapolation to the other 75 (gated on 16-1-0 passing)

Run `svc_prefilter.py` (grep pre-screen) across all 75 first - cheap triage of the mechanical 1.4 patterns.
Then one Opus directed rebuild per task on the complete brief + full audit, adversarially verified. Expect
0-major to move toward ~30-40% on clean-golden tasks; `accept` (0 major AND 0 minor) stays low corpus-wide
until the compound-binary format is handled by a standard one-item-per-criterion directory split under the
15-criteria cap. Each added judge directory is another judge call with the full file list - budget it.

## LATEST STATE 2026-09-21 (team reassignment + oracle-in-worker + waves out)

Newest first; supersedes the older 2026-09-21 update below on anything current.

**Team reassignment (the duplication fix).** Both Team A and Team B tabs held all 635 tasks (full overlap =
the duplication). Built a de-duplicated first tab **"SVC QC Tracker Combined"** in the main tracker
(`1JmpP38...`, sheetId 973351887): one owner per task, headroom-first active pool on top, **"Submitted for
Manual QC" (~210) at the bottom**. Rules: Khiem keeps all his; top-12 producers by submission count kept;
non-protected claims released to headroom only if STALE (no status change across 4 daily snapshots
Sep18->19->20->21, IDs `1NwMd`/`1MbK`/`17Du`/live); tie-break more-subs then progress. Progress protection
verified (298 Team-A tasks changed status; non-protected progress-makers kept). Then rebalanced: 5 of
Salman's no-progress -> Jonas; Khiem -30 no-progress -> headroom; Vinicius/Shaheer/Brijmohan capped at 2x
their submissions on no-progress tasks. Headroom = ~99 claimable. Builder `_scratch_build_combined.py`.

**Our lanes vs humans - zero overlap (permanent).** Our automated pool must never work a task a human is
assigned/claiming. `_fill.txt` reduced 165 -> **63, all Khiem-owned**; removed 30 given-back (headroom) + 87
already-submitted/submitting; 15 tasks that were both claimable AND in our waves were pulled out of headroom
(marked "Khiem (ours) - not claimable"). Old `_fill.txt` backed up on the sandbox.

**Oracle-in-worker (throughput switch, 2026-09-21).** `tools/svc_fullsweep_pool.sh` now runs the REAL oracle
(`judge_emulate`, per-lane) as each worker's final step: a task is marked `done/` ONLY if the golden scores
1.0. ~~This retires the separate serial preship gate as the ship path - **done now means shippable**~~
**SUPERSEDED 2026-09-21 (read the v7 section at top):** oracle-1.0 is NECESSARY-NOT-SUFFICIENT and blind to
1.4/1.5 (the golden passes a flawed rubric perfectly). `done/` = golden 1.0 is NOT shippable. Shippable =
golden 1.0 on 2 runs AND that task's named DataOS finding closed by a directed Opus rebuild. `unverified/` =
locally unverifiable (/app path); HELD = golden<1.0. Fast deterministic static/mojibake stay a check at zip time.

**Waves.** Wave 1 (10) + Wave 2 (7), oracle-1.0 + byte-verified, uploaded by the user via the cheap config
(`Downloads/dataos-wave-fillfix-2026-09-21.zip`, `dataos-wave2-2026-09-21.zip`). Wave 3 = 66 done tasks,
oracle-gated in the background (the LAST separate gate run; future waves come straight from the pool `done/`).

## The finding that anchors everything (severity wall)

Local pipeline PASS is **21% precise** vs DataOS, confirmed a THIRD time by wave 1 (1 of 8 accepted). DataOS
grades with **2x GPT-5.6-sol reviews + 1x Opus-5 review + a GPT-5.6-sol QC**, plus solver evals + an oracle.
The failures that dominate (1.3 ambiguity, 1.4 alignment, 1.5 coverage) require grading a defect's SEVERITY
the way GPT-5.6-sol does, and our Opus/Fable/GLM cannot: on wave 1 our Opus review seat found **0 majors on
all 7 judgment-defect tasks** while both GPT seats rejected them. Detection is fine; severity grading is the
wall. No local reviewer change reaches ~90% on 1.3/1.4/1.5. Do not re-chase local reviewer calibration.

## What is deterministically catchable (this is our lever)

Severity does not matter for FIXING or for DETERMINISTIC checks, only for LLM gating. So we catch, for $0,
the defect classes that do not need severity judgment, and keep them out of DataOS entirely:

- **1.8 grammar bomb: a judge dir with > 15 criteria** overflows Anthropic's structured-output grammar at
  grade time (`"compiled grammar is too large"` -> HTTP 400 -> reward 0.0 on every run incl the golden).
  Our CLI-backend oracle FALSE-PASSES these; DataOS errors. **62 of 202 corpus tasks (31%) had this.**
- **1.8 mojibake** in file/dir names + the judge.toml paths that reference them (an em-dash mis-decoded
  through CP437).
- **golden-broken (1.1):** oracle golden `total_reward < 1.0` (golden fails its own rubric). Note the oracle
  is BLIND to a golden that is factually wrong while passing a too-weak rubric (wave-1 19-4-0).
- **missing-file (1.8):** a `/app/_corpus_subtree` path that resolves to not_found.
- **1.4/1.5 dual-basis loophole (NEW 2026-09-21):** a criterion whose `Expected:` accepts two different
  values/bases joined by "or" (`tools/svc_rubric_loophole_check.py`, DUAL_BASIS flag). It lets a solver
  report the wrong value and still pass. Got 1-2-0 rejected twice, and a grammar split COPIES it into every
  child (1-2-0: 26 -> 32 dual-basis criteria across its split). Found in **18 of 202 corpus tasks**. ADVISORY
  (precision 1/1 on the wave-1 set only, not corpus-calibrated), review-only until measured on the must-pass set.

CORRECTION (2026-09-21): "only DataOS/GPT finds 1.5/1.3/1.4" was too strong. What is GPT-only is using our
review VOTE as a GATE (predicting GPT's severity on an un-graded task). FIXING a task DataOS already graded is
LOCAL: we have the finding, and Claude on the real bytes can re-derive the correct answer from source, build a
passing-but-wrong exploit, and tighten the rubric until it fails. The dual-basis check makes part of it
deterministic. DataOS stays the only verdict; we cannot locally certify a GPT accept.

## Round 2 (2026-09-21): adversarial fixer + codified loophole checks (PROPOSAL, in flight)

The round-1 resubmit went 1/7 (proof gate failed). Trajectory analysis (round-1 finding -> our fix -> round-2
finding, per task) showed our round-1 fixes were MECHANICAL: split for grammar, add the one named criterion,
never re-audit what the split/add left behind. 19-4-0 (the only pass) had a substantive fix. Taxonomy:
[svc-round2-patterns-2026-09-21.md](svc-round2-patterns-2026-09-21.md); results
[resubmit-wave1-results-2026-09-21.md](resubmit-wave1-results-2026-09-21.md).

Proposal, now executing on the lanes:
1. **Adversarial fixer method** (baked into `tools/svc_dataos_fix_brief.py`): re-derive the answer from source,
   build a passing-but-wrong exploit and tighten until it fails, check coverage, keep the golden 1.0 - not a
   literal suggested_fix copy. Judgment rounds run on opus.
2. **Targeted round-2** (7 opus lanes, in flight): the 6 fails + 19-4-0 (confirm-don't-break). Per-task briefs
   name the specific defect (11-3-0 too-strict band, 1-2-0 dual-basis, 13-3-0/20-3-0 golden rebuilds, etc.).
3. **Dual-basis fix queued across the corpus** (`tools/svc_dataos_queue_and_zip.sh`): the 17 other flagged
   tasks, self-sequenced after round-2, not just 1-2-0.
4. **Auto-zip**: the queue builds a DataOS resubmit zip from each round's oracle-1.0 ready set; UPLOAD stays
   the user's action.

Runners: `svc_dataos_overnight.sh` (fix + verify), `svc_dataos_queue_and_zip.sh` (sequence + zip),
`svc_rubric_loophole_check.py` (dual-basis scan). Scale the dual-basis fix corpus-wide only if the round-2
resubmit shows it clears the wall - DataOS is still the only verdict.

## Operating procedure (per wave)

1. **Pick candidates** = static-clean, mojibake-clean, never-DataOS-graded tasks. Pool lists committed.
2. **Deterministic pre-filter** (`tools/svc_preship_gate.sh`, fail-fast order), all must pass:
   - static (`svc_rubric_static_check.py`): <=15 criteria/judge-dir + every dim has a grader. HARD.
   - mojibake (`svc_mojibake_check.py --judge-only`).
   - missing-file (`judge_input_gate.py`, _corpus_subtree not_found).
   - oracle (`judge_emulate.py`): golden >= 1.0. None/ERR = locally unverifiable (/app path or a capped
     lane), flagged not blocked; only a numeric < 1.0 hard-blocks.
3. **Fix the deterministic blockers** (all mechanical, snapshotted, verified on a copy first):
   - grammar: `svc_split_grammar_dirs.py` (share-preserving split, golden stays 1.0).
   - mojibake: `svc_fix_mojibake_names.py` (restore the char in names + refs).
   - golden-broken / coverage: needs authoring; route to a fix agent or DataOS-as-gate.
4. **Build the wave zip** from the corpus, testzip-verify, byte-size-verify after transfer (a dropped scp
   truncates silently; split into ~40 MB parts if the link is flaky). Upload is the user's action.
5. **DataOS grades** with the cost-reduced config below. Pull the `_with_runs` zip. The real verdict is each
   review's `overall_verdict` in its answer body, NOT the `## status` header (that is job status).
6. **Feed every return back** into `_gt_labeled_57.json`; re-measure the gates + fixers before the next wave.

## Cost-reduced DataOS config (the MVP - keep GPT-5.6-sol everywhere, no other model)

Full round is 8 model runs = $18.46/task (measured, 9 rounds / 185 opus-solver samples). The MVP:
**oracle + 2 GPT-5.6-sol solvers + 2 GPT-5.6-sol comprehensive reviews. No Opus, no QC, no Gemini/Flash.**

- **Reviewer = GPT-5.6-sol ONLY.** Accept/reject hinges on 1.4/1.5 severity, a GPT-5.6-sol-specific
  capability. Any other reviewer (Opus, Fable, GLM, Gemini Flash) detects but grades minor = ~0 recall =
  a wasted vote. A Flash reviewer repeats the Opus failure that gave wave 1 its 1/8.
- **Solvers stay GPT-capable.** A solver's only gate-job is false-rejection evidence (a capable alternate
  answer the golden wrongly fails = the 1.3/1.4 signal). A weaker solver (Flash) fails on capability = noise.
- **Biggest $ line = the 2 Opus solvers at $7.34/task = 40% of the round** (also the cost tail, one hit $24).
  Dropping them (keep 1-2 GPT solvers) is the core saving. Confirmed by re-grading 13-3-0/20-3-0 recall.
- Cost ladder: current $18.46 -> removes-claude (drop opus review + 2 opus solvers) $8.54 -> MVP (also drop
  QC) ~$6/task (-68%). Cheaper still: drop to 1 GPT solver. Higher recall: add a 3rd GPT-5.6-sol review, not
  a different model. Confirm the review/QC $ against the user's 7 cost views (evals are measured, reviews
  derived from the $18.46 aggregate).

## The DataOS Feedback Fixer (PRIMARY track, lane-executed, do not drop)

The point of DataOS-as-gate is NOT to pre-qualify (the wall makes that impossible). It is to use DataOS's
own per-criterion findings - it returns a `suggested_fix` for every `checks[]` finding - as a directed
repair manual, fix exactly what it named, and resubmit. Every prior attempt failed by (a) chasing local
prediction instead, (b) fixing what OUR blind models saw instead of DataOS's findings, or (c) a resubmit
pipeline that row-mis-joined findings and silently skipped. This track fixes that. The laptop session ONLY
writes and launches; the LANES do every fix and every verify.

### Step 1 - Harvest (deterministic Python, no model, laptop; re-run on every new return)
`tools/svc_harvest_dataos_findings.py` parses every `Downloads/*_with_runs*.zip`. For each task, each
`comprehensive_review` answer-body JSON: pull `overall_verdict` + every `checks[]` finding as a row
{task, seat, check_id, name, result, severity, criterion_named, justification, suggested_fix}. Output
`ekw/dataos-findings.json` (committed) and push to sandbox `/root/qc/_findings.json`. Bucket each finding:
over_enforcement (1.4), missing_coverage (1.5), ambiguity (1.3), deterministic (1.1/1.8 - already handled by
the pre-filter). The parse rule that bites: the real verdict is in the model's answer after the `\nA:`
marker, under key `checks` (NOT `findings`), and `## status` is job status not verdict.

### Step 2 - Directed fix (LANES, Opus, one agent per rejected task)
**CORRECTED 2026-09-21: Opus, never Sonnet. The Sonnet batch is DISPROVEN (waves 1+2 = 0/17). See the v7
section at top.** Per task, one agent on one lane:
- **Model: `claude -p --model opus`** (or Fable) on a working lane (probe first, skip capped; least-loaded
  assign). This is judgment work: authoring a coverage criterion with the golden's REAL expected value on
  customer corpus needs the strongest model on the real bytes. Sonnet was tried at batch scale and did not
  clear the wall; do NOT use it here.
- **Brief = that task's COMPLETE finding ledger** (`_deepbriefs/<task>.md` from `svc_build_directed_briefs.py`:
  every round, both seats, majors + moderates, full text, no truncation), plus the locked rules: keep the golden scoring
  1.0; for missing_coverage ADD a criterion checking the named fact using the golden's real value; for
  over_enforcement NARROW or remove the named criterion; for ambiguity edit instruction.md AND
  tests/task_prompt.txt IDENTICALLY to state the one required reading; never lower difficulty; never put an
  expected value anywhere the solver/graded party can read it.
- Snapshot `tests/` before editing (`/root/qc/_fixsnap/<task>`).
- **Local escalation:** Opus round 1 -> if oracle < 1.0, Opus round 2 fed the oracle failure -> if
  still < 1.0, flag `hard` and stop (do not ship a golden-broken task).

### Step 3 - Verify (LANES + deterministic; NO local severity re-review)
Per fixed task, all must pass, none use a local LLM reviewer (the severity wall makes local re-review
worthless):
- **oracle** (`judge_emulate.py`, judge = rubric's claude-sonnet-4-6, on a lane): golden `total_reward` =
  1.0. This is the gate that a fix did not break the golden.
- **static + mojibake + missing-file** (deterministic scripts): no new grammar/packaging defect introduced.
- **softening guard** (deterministic): a missing_coverage fix must NOT reduce the task's criterion count
  (that would mean the agent "fixed" by deleting). Over_enforcement fixes may reduce it.
A task is locally-verified = oracle 1.0 + all deterministic clean.

### Step 4 - Resubmit (DataOS, the only real verdict)
Build a resubmit zip of locally-verified tasks; user uploads through the cost-reduced MVP config (oracle +
2 GPT-5.6-sol solvers + 2 GPT-5.6-sol reviews). DataOS returns -> re-run Step 1 harvest -> still-rejected
tasks feed their NEW findings back to Step 2 (DataOS round 2). **Cap 3 DataOS rounds per task; after 3,
cut the task as irreparable.** Log each task's round count.

### Proof gate (run BEFORE scaling)
Run the full loop on the 7 wave-1 rejects first (findings already harvested). Scale to all graded rejects
ONLY if >= 5 of 7 pass resubmit. If they do not, the ceiling is real and the decision becomes GPT-5.6-sol
access or cutting tasks - not more local fixing.

### Model roles (LOCKED - do not re-decide next session)
**CORRECTED 2026-09-21 (v7):** Harvest = Python, no model. Directed fix = **Opus (or Fable), one agent per
task on a lane, never Sonnet, never a wide batch**. Oracle judge = claude-sonnet-4-6 (never Opus). No GLM in
this loop. Orchestration = laptop writes + launches detached lane runners and polls; lanes execute every fix
and every oracle. (The prior "Sonnet on lanes, Opus only for round 3" is the disproven method - see v7 at top.)

## Update 2026-09-21 (post wave-2 + dual-basis return, this session)

- **Pass rule confirmed by the user:** needs_revision with 0 majors IS a pass when 2 of 3 reviewers agree.
  Under the 2-GPT MVP that means both GPT seats at 0 majors. GPT-5.6-sol's ceiling verdict here is
  needs_revision (it does not emit `accept`), so 0-major-from-both-GPT is the operative accept-to-QC bar.
- **4th DataOS return - `dual_basis_clean` batch: 0 of 11 accepted.** All 11 rejected by both GPT seats
  (MVP config). Dominant majors 1.4 (21) and 1.5 (20); 93-1-0 came back `invalid` (packaging-broken, 1.8).
  Removing the dual-basis loophole did NOT clear the severity wall - these tasks still fail 1.4/1.5. The
  dual-basis check stays ADVISORY. These 11 now have real DataOS findings, so they route to the DIRECTED
  fixer (their exact findings), not the blind full-sweep. Detail: `_scratch_dualbasis_check.py`.
- **Aggregate across all 4 returns: 5 accepts / 33 grading events (~15%, double-counts 13-3-0/20-3-0 across
  rounds).** Reinforces the wall; does not move it. The tasks that passed got substantive full rebuilds, not
  narrow fixes - which is why the fill (below) runs the full coverage sweep.
- **Wave-2 passers task-doc'd:** 13-3-0 + 20-3-0 -> one QCR Google Doc (id 15DC84ykehb...), shared to
  qc@turing.com, marked submit-for-manual-QC (SVC QC Tracker A), and added to consolidated main list (rows
  192, 178) with the doc + DataOS link. 1-2-0 logged under Duplicates (row 213, done by Brijmohan Tiwari).
  CAUTION on 13-3-0: Ezekiel abandoned an earlier rev (111594) as rewrite-class (golden figures untraceable
  to the 16 sources); our resubmit rev (124642) passed 2-GPT 0-major after a golden rebuild. The QCR doc
  asks the reviewer to confirm golden->source traceability; recommend that check before QC treats it clean.
- **Done-overlap excluded from the pipeline:** 33 corpus tasks were EQC-Done in consolidated (117 done
  total). Physically moved out of `03_dataos_ready/` to `_done_excluded/` (manifest kept). **Corpus now 169.**
- ~~**Idle lanes put to work (full coverage sweep):** `svc_fullsweep_fill.sh` runs one Sonnet agent per
  ungraded task from a shared full-sweep brief~~ **SUPERSEDED / DISPROVEN 2026-09-21:** the shared-brief
  Sonnet full-sweep is exactly the batch that came back 0/17. It is retired and hook-blocked. Idle lanes run
  the v7 method instead: ONE Opus agent per task, directed by that task's COMPLETE `_deepbriefs/<task>.md`
  ledger. No shared/generic brief on a graded task.
- **Round-3 (12-2-0 + 19-4-0 only):** the other two round-3 candidates (10-2-0, 11-3-0) were done-overlap
  and their agents were killed. 19-4-0 flipped pass (wave-1 resubmit, both GPT 0-major) -> fail (wave-2, one
  GPT reject) - the known cross-run instability, so even a single 0-major pass is not proof.
- **Plain-language team guide added:** `docs/svc-pc-plain-guide.md` (no jargon, the full-sweep how-to).
- **ALL DataOS returns harvested + durable (feedback systematically applied):** we have **13 `*_with_runs`
  return zips** (in Downloads), **70 distinct graded tasks**, ~14 passes / ~131 graded instances (~11% -
  the wall, measured across everything, not a slice). Durable artifacts, regenerable with
  `python tools/svc_harvest_all_returns.py --briefs`:
  - `ekw/dataos-returns-ledger-2026-09-21.md` - one row per zip (tasks, pass/fail/invalid) + the 70-task list.
  - `ekw/dataos-findings-allrounds-2026-09-21.json` - per task, every MAJOR finding across ALL rounds, deduped.
  - `_targeted_briefs/<task>.md` - directed fix brief (accumulated findings + full sweep) for each of the
    **54 graded tasks still in the pipeline**; pushed to sandbox `/root/qc/_targeted/`.
  The fill pool (`tools/svc_fullsweep_pool.sh`, work-stealing, 15 lanes, 25-min/task timeout) now PREFERS
  the directed brief when one exists (graded task -> findings+sweep) and falls back to the generic sweep
  (ungraded task). So every graded task gets ALL its prior DataOS feedback applied, not just the latest round.
  When a new return zip lands: drop it in Downloads, re-run the harvester with `--briefs`, re-push
  `_targeted/`, and the next pool pass picks it up.

## Current state (2026-09-21, post wave-1)

- **Resubmit (wave-1 rejects, round 2): 1/7 accepted -> PROOF GATE FAILED** (needed >=5/7). Only 19-4-0
  passed, and it is the flagged factually-wrong golden (1.1-in-narrative) both oracle and panel miss, so it
  is NOT a clean pass: hold it out of manual QC pending a golden factual check. All 6 fails carry a 1.5
  missing-coverage major from a GPT seat (13-3-0, 20-3-0 regressed to 1.1 too); the directed fixer kept
  goldens at oracle 1.0 but did not clear the coverage/severity wall. Graded with 2x gpt-5.6-sol + 1x opus
  review (not the MVP). **Decision forced: ceiling is real - escalate to GPT-5.6-sol-as-our-reviewer access
  or cut; do NOT scale local fixing.** Detail: [resubmit-wave1-results-2026-09-21.md](resubmit-wave1-results-2026-09-21.md).
  The overnight lane deploy was NOT fired (gate did not clear).
- **Wave 1: 1/8 accepted** (14-1-0). Uploaded. 3 buckets: 1.5 coverage blind spot, 1.3/1.4 source
  ambiguity, deterministic blind spots (grammar false-pass, golden-wrong-in-narrative). Full: wave1 doc.
- **Corpus scan (202):** 62 grammar-blocked, 140 static-clean, 106 fresh, 98 fresh+mojibake-clean.
- **Fixes applied (parallel, snapshotted, committed):** 62 grammar-split -> all static-clean, golden 1.0
  preserved (verified 1-2-0, 26-7-0). 7 of 8 mojibake fixed; 26-3-0 excluded (TOML-escaped mojibake edge).
  Snapshots `/root/qc/_grammar_snap`, `/root/qc/_mojibake_snap`.
- **Batch-ready pool:** 67 tier-1 (static+mojibake+oracle-1.0), 20 tier-2 (oracle-unverifiable), 4
  golden-broken EXCLUDED (41-5-0, 20-4-0, 35-0-0, 76-0-0). The 62 grammar-split + 7 mojibake-fixed tasks are
  deterministically clean and oracle-verifying now (sweep on 15 working lanes).
- **Batch 2 = 15 tier-1 tasks**, `Downloads/dataos-batch2-2026-09-21.zip` (208 MB, byte-verified). Uploaded
  through the user's cost-reduced pipeline.
- **Return handling ARMED** ([runbook](svc-return-runbook-2026-09-21.md)) for the 7-resubmit proof gate.
  When a resubmit `_with_runs` zip lands: split passers/rejects (`svc_dataos_returns_parse.py`), document
  every passer via `/task-doc` all-steps (QCR doc + share + both trackers), then the proof-gate decision -
  **>= 5 of 7 pass -> deploy the lanes overnight on the full reject pool** (`svc_dataos_overnight.sh`, fix +
  deterministic verify, launched detached), **< 5 of 7 -> stop scaling** (ceiling is real; escalate to
  GPT-5.6-sol access or cut). New tools this session, ready to fire: `svc_dataos_overnight.sh` (fix+verify
  overnight wrapper, emits `ready.txt`), `svc_mark_manual_qc.py --tasks/--assignee` (parametrized tracker
  write, was hardcoded to 8 tasks). Overnight run stops at a local `ready.txt`; the zip + upload is the
  user's action.

## Sandbox + lanes (probe, never assume)

- Sandbox: `root@136.113.78.105 -p 2222 -i ~/.ssh/kiem_sandbox`. Corpus
  `/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready`. rewardkit venv `/root/venv/bin/python3` +
  `QC_REWARDKIT_SITE_PACKAGES=/root/venv/lib/python3.13/site-packages`.
- Lanes `/root/.claude-{q,r,m,v,w,c,e,f,g,i,j,k,l,p,t,u}` (16). **A lane being capped is a per-account
  weekly limit on ONE lane, not the fleet.** 2026-09-21: 15 of 16 working, only `t` capped. NEVER claim the
  fleet is blocked from a handful of log lines - probe each lane (`CLAUDE_CONFIG_DIR=/root/.claude-<L>
  claude -p "say ok"`) before asserting a block. This is the [[svc-lanes-reservations-and-idle-lanes]] rule
  and it was violated this session.
- SSH drops under load; launch detached `(setsid nohup bash x >log 2>&1 </dev/null &); exit 0` and poll.
  `pgrep -f "[x]pattern"` or a bare pgrep self-matches and inflates counts (cost cycles this session).

## Tools (all committed under tools/)

`svc_rubric_static_check.py` (grammar/empty-dim static gate), `svc_split_grammar_dirs.py` (grammar fix),
`svc_fix_mojibake_names.py` (mojibake fix), `svc_mojibake_check.py` (detector), `svc_preship_gate.sh`
(chained gate), `judge_emulate.py` (oracle, CLI backend), `judge_input_gate.py` (missing-file, team-repo).
Sweep runners `_oracle_sweep_param.sh` (arg1 list, arg2 outdir), assembler `_assemble_ready_wave.sh`.

## What is NOT solved, do not pretend otherwise

- 1.5 missing-coverage + 1.3/1.4 defects are DETECTABLE and FIXABLE locally on the real bytes: read the
  source, re-derive the correct answer, and adversarially check the rubric forces it (detection and authoring
  were never the wall). What is NOT local is CONFIRMING a GPT accept - our review VOTE grades severity
  differently, so it cannot GATE (predict GPT on an un-graded task). For a task DataOS already graded we HAVE
  the severity signal in the finding, so the wall does not block FIXING it, only predicting new ones. The
  fixer therefore acts like the GPT reviewer (re-derive + adversarial rubric test), encoded in
  `svc_dataos_fix_brief.py` RULES 2026-09-21; it does not copy the suggested_fix verbatim.
- The oracle misses a factually-wrong golden that passes a too-weak rubric (1.1-in-narrative, 19-4-0).
- Local PASS is a weak signal. Only a returned DataOS accept, or deterministic-clean + a shipped-and-graded
  return, counts as DataOS-ready.
- GPT-5.6-sol as OUR reviewer is the org ask (user/Shyam); it is the only lever that reaches ~90% locally.
