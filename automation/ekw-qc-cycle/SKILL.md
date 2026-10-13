---
name: ekw-qc-cycle
description: EKW-GDPVal QC cycle steps 1–3 (new→fetch→diff→bundle), Mon & Thu 4pm; stops before evals.
---

Run the EKW-GDPVal QC cycle — steps 1–3 only. The eval handoff is manual, so STOP after bundling. Do NOT run the qc or report steps (those wait for evals to come back).

Working directory: <path to your clone of this repo> — e.g. `/Users/<you>/Projects/gdpval-qc`. Edit this line to your actual clone path before registering the routine.

Steps:
1. Run `python3 pipeline/cycle.py new` and note the new cycle date (today, YYYY-MM-DD).
2. The task list comes from a CSV export of the tracker's "ready for review" tab, which must be placed at `cycles/<date>/tracker.csv` (the tracker itself is policy-blocked from automated reading). Check whether that file exists. If it does NOT exist, message the owner: "Drop the tracker CSV export at cycles/<date>/tracker.csv, then re-run the cycle" — and end the run.
3. If tracker.csv exists, run `python3 pipeline/cycle.py fetch <date>`. This parses the CSV, creates one folder per ready-for-review task under `cycles/<date>/00_fetched/`, and downloads each task's files when the Drive links are open (otherwise it writes `_source.txt` with the link for manual pull). If many tasks show "need manual file pull", note that in your report.
4. Run `python3 pipeline/cycle.py diff <date>` and read `cycles/<date>/01_diff/changes.md`.
5. If there are NEW or CHANGED tasks, harbor-bundle only those into `cycles/<date>/02_bundle/` (run `python3 pipeline/cycle.py bundle <date>`; the helper is at pipeline/tools/bundle.py). If nothing is new or changed, skip bundling.
6. Report to the owner: the cycle date, counts (new / changed / unchanged / removed), how many tasks needed manual file pull, where the bundle is, and whether it is ready to send to the evaluator. If nothing changed, say so plainly.

Conventions are in this repo's onboarding docs (`docs/ONBOARDING.md`, `docs/CLAUDE.md` — "Project Layout" + "QC Cycle Workflow"). Column mapping for the tracker CSV is in `pipeline/fetch.config.json`. Always run the pipeline from `pipeline/`. Do not advance `cycles/latest`; that happens at `python3 pipeline/cycle.py close <date>` after the full cycle completes, which is not part of this routine.
