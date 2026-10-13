# Release check, portable folder (version 1)

Written 2026-10-08 (US Eastern), job B12_PORTRC. Copy this whole folder into the team repo. It needs only Python 3.11 or newer (tomllib is used). No sandbox, no pip install, no network. Check 2's second check (the verifier) uses your own `claude` command, only if you ask for it. Nothing under final/releasecheck_v1, final/step2 or final/step3 was changed; this is a new folder.

## The one command

```
python3 run_release.py EXPORT_DIR PKGS_DIRS OUT_DIR --dl DL_DIR [--dl-copies DIR] [--tasks FILE] [--verifier-out DIR | --run-verifier] [--spec 557]
```

It runs the three checks twice (check 1 with at least 2 valid solver attempts, then at least 3) and writes `OUT_DIR/release_table.csv`: one row per task, columns `call` (HOLD, EVIDENCE MISSING or RELEASE) and `call_with_check1_at_3_attempts`, plus the reasons. No cutoff is applied; the manager reads the counts. The meaning of each check is in `README_v1_checks.md` (a copy of final/releasecheck_v1/README.md, unchanged).

To check the folder itself: `python3 tests/run_tests.py` (prints `TESTS run= failures= errors= skipped= passed=`).

## What is vendored (copies, not the originals)

`vendor/step2/` holds copies of the frozen step 2 files that check 2 runs: step2_v11.py, parse_reviews_v11.py, pass_rule_v11.py, v11lib.py, pkg.py, verifier/make_ws_v11.py, verifier/check_out.py, verifier/run_verifier.sh, prompts/VERIFIER_PROMPT_V11.md and its .sha256. `vendor/step3/gate.py` is a copy of the step 3 gate. Each is byte-identical to the file in final/step2 or final/step3 on 2026-10-08 (checked with `cmp`, 11 of 11). Their sha256 are in `VENDORED.sha256`; a test fails if a vendored file is edited. If final/step2 or final/step3 changes later, this folder does not follow: recopy and re-record the hashes.

`release_check.py` is the final/releasecheck_v1 file with one line changed: `FINAL = os.path.join(H, 'vendor')` instead of `os.path.dirname(H)`, so it finds the vendored modules (diff: 1 line). Checks 1, 2 and 3 are otherwise the same code.

Two things to know about the copies. `run_verifier.sh` contains a path to a sandbox helper (`/root/pq/b12/work/others/h/sandbox.sh`); it is reached only when a lane name is given, and release_check always passes `local`, so it never runs. The verifier script calls `claude -p --model opus` (the frozen choice); it uses your own login and plan.

## Files a manager needs

| name | what it is | in the control run |
|---|---|---|
| `EXPORT_DIR` | folder in the "export layout": results.jsonl, runs.csv, nop.csv, map.csv, tasks.csv, newruns/, runs/ | work/trial3a/export |
| `--dl DL_DIR` | the downloader's folder: one subfolder per task id | work/trial3a/dl |
| `--dl-copies` | same, for QC copy task ids | work/trial3a/dl_copies |
| `PKGS_DIRS` | task package folders (instruction.md, task.toml, tests/, solution/, environment/), `:`-joined | /root/pq/b12/pkgs and two more |
| `--verifier-out` | verdicts from an earlier verifier run, or use `--run-verifier` | work/releasecheck/run1/step2/verifier_out |
| `--tasks` | CSV task_id,name,tab | work/trial3a/export/tasks.csv |

**Make EXPORT_DIR from DL_DIR alone:** `python3 build_export.py DL_DIR EXPORT_DIR [--dl-copies DIR --map map.csv] [--tasks tasks.csv]`. map.csv has columns copy_task_id,orig_task_id and is needed only when reviews ran on QC copies. results.jsonl is rebuilt from each task's `verifications/*.json` (finished, not archived, written with the review prompt answer-check-v11, DataOS saved prompt id 557). On the 22 control tasks this rebuild gives the same 88 reviews as the stored results.jsonl on all five fields compared (key, status, targets_runs, targets_tasks, output; 88 of 88) and the same empty-answer rewards (22 of 22).

### Where each file comes from (what the downloader reads)

From `/root/sbdp/pipeline/tools/_scratch_dataos_download_sb.py` (read-only, GET requests only; run it with `--run-level`). The right column is the DataOS API object it reads; I cannot see the DataOS screens from the sandbox, so I name no page or button (Khiem or a manager must confirm which page shows each object; marked "unconfirmed" below).

| file in the folder | DataOS object read | page or button |
|---|---|---|
| `<task>/task.json` (last edit time) | `datasets/tasks/<task>/` | unconfirmed |
| `<task>/runs/<run>.json` (agent, status, reward) | `evaluations/?task=<task>` then `evaluations/<id>/runs/` | unconfirmed |
| `<task>/runs/<run>.reward-details.json` (per-rule results; check 1) | `evaluations/runs/<run>/output-file/?path=verifier/reward-details.json` | unconfirmed (a run's output file) |
| `<task>/verifications/<id>.json` (the reviews; check 2 and the timing columns) | `verifications/?target_type=task&target_id=<task>` and `target_type=evaluationrun&target_id=<run>`, then `verifications/<id>/` | unconfirmed |
| package folders | not read by the downloader | not known from the files I opened: ask Khiem which export produces them |
| `preflight.csv`, `step1.csv`, `review.csv` (check 3 inputs) | made by final/step1 scripts and the run-history export | without them check 3 reads CANT_JUDGE (18 of 22 in the control) |

If a person has no downloader, the same objects have to be saved by hand from DataOS; the sandbox cannot tell which screens offer them. That step is open (see out/PORTRC.md).

## Reading the table

HOLD: at least one check says yes; return the task to the author with the reason columns. EVIDENCE MISSING: no check says yes and one is not computable; `missing_inputs` names it. RELEASE: all three computed, none yes. A RELEASE is not a statement that the task is sound.

## Verifier cost

`--run-verifier` runs one `claude -p` call per task workspace, one after another (about 1.6 per task per final/step2/README.md), resumable. The folder's real-claude path was not run in this job (control used stored verdicts, as in out/TRIAL3A.md).
