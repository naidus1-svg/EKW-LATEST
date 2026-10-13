# SVC-PC: build of the 35 tasks that had no package, 2026-09-23

The QC SOP (step 3) listed 35 SVC-PC tasks with no built package anywhere. This folder
records what happened to each of them. The packages themselves are on the
[`svc-unbuilt35-2026-09-23` release](https://github.com/turing-genai-apps/EKW_QC_pipeline/releases/tag/svc-unbuilt35-2026-09-23).

| Outcome | Count | Tasks |
|---|---|---|
| Built and published, one zip per task | 6 | 11-5-0, 13-5-0, 45-6-0, 49-0-0, 65-0-0, 95-0-0 |
| Built, held: assigned to someone in the SVC QC Tracker at build time | 11 | 4-1-0, 4-3-0, 4-4-0, 4-5-0, 11-1-0, 12-4-0, 13-1-0, 13-2-0, 13-8-0, 60-1-0, 90-0-0 |
| Not buildable from any source that exists | 18 | 23-0-0, 27-0-0, 74-0-0, 83-0-0, 84-0-0, 85-0-0, 86-0-0, 87-0-0, 89-0-0, 92-2-0, 97-0-0, 98-0-0, 99-0-0, 100-0-0, 101-0-0, 102-0-0, 103-0-0, 104-0-0 |

All IDs are `SVC-PC-` prefixed. `SVC-PC-88-8-0` (the retired wrong-company slot) was not built.

## Files

- `task-index.csv`: one row per task (all 35). Status, release asset name, size and
  sha256, the tracker's owner/status at build time, and every gate result. Also attached
  to the release.
- `source-inventory.csv`: where each task's source came from, its L1 row, and for the 18
  not buildable, the reason.
- `source-files.csv`: every source file fetched (82 across 18 tasks), with Drive id, md5
  and modified time. All 82 downloads matched Drive's own md5.
- `hydration-fixes.json`: the two tasks whose corpus inputs were added by hand after the
  build (60-1-0, 4-4-0). See `builder-snapshot/README.md`.
- `builder-snapshot/`: the exact five build-chain files used, and how to rebuild a task.

## How the sources were checked

For each of the 35: the L1 tracker row (`SVC_Y1_Pilot_Evals_Expert`, L2 Tasks / L3 Tasks),
the task's folder under Final L2 Tasks or Final L3 Tasks, and a Drive search by task id.

- **L1 is current where it has links.** On all 17 tasks whose L1 row links a prompt,
  golden and rubric, every linked file is byte-identical (md5) to the copy in the Final
  folder. The Final folders are a superset: they also hold the Response Criteria workbook
  and extra golden deliverables the L1 row omits. The build used the Final folders.
- **95-0-0** has an empty L1 row but a complete Final L3 folder, so it was built.
- **16 tasks** have no prompt, golden or rubric link on L1, no Final folder, and a Drive
  search by id returns only tracker sheets.
- **23-0-0** has a prompt link, but its golden and rubric cells link to
  `https://drive.google/`, a truncated URL with no file id.
- **92-2-0** has files, but the rubric is not in the grading template (no points or
  weights; its criteria sheet compares "Claude response" with "Both responses").
  Building it means authoring the rubric, which is the author's call.

## Gates (per task results in `task-index.csv`)

1. `svc_prefilter.py`: all 17 builds pass (no HARD). WARNs are listed per task:
   source CSVs with CRLF line endings as authored, 1.4 cardinality candidates, and on
   13-1-0 and 65-0-0 a figure the prompt itself gives as input (reviewed, not a leak).
2. `svc_discover017_check.py` under rewardkit 0.1.7 (DataOS's loader): 0 of 17 fail.
3. `judge_emulate.py oracle --runs 2` (golden scored against its own rubric): run on the
   6 published tasks, plus 11-1-0, 12-4-0 and 13-1-0, which finished before the held
   decision. The other 8 held tasks were not run. Of the 6 published, only 11-5-0 and
   95-0-0 scored 1.0 on both runs; 13-5-0, 45-6-0, 49-0-0 and 65-0-0 scored between 0.86
   and 0.98, so their golden fails part of its own rubric. They are published anyway,
   labelled, per the rule that a gate failure is visible rather than hidden.

What these gates do not establish: the oracle runs on the CLI judge backend, which skips
the structured-output grammar DataOS compiles, so a 1.0 here is not proof DataOS's grader
can grade the task (the prefilter's 15-criteria-per-judge-dir check covers the known
grammar failure). None of these tasks has had the content audit (check A), a DataOS
pipeline or eval run, or manual QC. "Published" means built and gated as above, not
QC-passed.

## Packaging

Each zip was built by `svc_build_upload_zip.py --first-grade` through
`svc_bundle_upload.py bundle` (prefilter gate, loader gate, proof the task was never
graded, cold audit), then passed `svc_bundle_upload.py check` before it was copied off the
sandbox. The same builder refused the 11 held tasks because they are on the team-wide
do-not-touch list built from the trackers; that refusal is why they are held.
