# Automation — exported scheduled routines

This directory holds Claude Code scheduled-task routines used to run parts of
the QC workflow automatically. They're exported here as plain files so anyone
working on this repo can install the same automation for themselves — a
Claude Code scheduled task lives under your own `~/.claude/scheduled-tasks/`,
not inside a project repo, so cloning this repo alone does not register
anything; you install it once, locally, per machine.

## `ekw-qc-cycle` — Internal QC cycle steps 1–3 (fetch → diff → bundle)

Runs twice a week (Mon & Thu, 16:00 local time in the original setup — adjust
to your own timezone/schedule) and does the fully-automatable front half of
an Internal QC cycle: scaffold the cycle, fetch ready tasks from the tracker
CSV, diff against the previous cycle, and bundle anything new/changed into
harbor format. It deliberately **stops before evals/QC** — that handoff is
manual by design (see the QC SOP), so the routine reports what it did and
waits for a human to take it from there.

### Install it for yourself

1. Copy this folder into your own scheduled-tasks directory:
   ```bash
   cp -r automation/ekw-qc-cycle ~/.claude/scheduled-tasks/ekw-qc-cycle
   ```
2. Open `~/.claude/scheduled-tasks/ekw-qc-cycle/SKILL.md` and edit the
   **"Working directory"** line to point at wherever you cloned *this* repo
   (e.g. `/Users/you/Projects/gdpval-qc`) — the routine assumes it's running
   with that as its working directory when it invokes `pipeline/cycle.py`.
3. Register the schedule. Easiest path: in an interactive Claude Code
   session, run `/schedule` and point it at the copied `SKILL.md`, or ask
   Claude to "schedule the ekw-qc-cycle routine for Mondays and Thursdays at
   4pm" — it will call the scheduling tool for you. If you're setting it up
   programmatically instead, the original registration used:
   - **cron expression:** `0 16 * * 1,4` (16:00, Monday and Thursday)
   - **task id:** `ekw-qc-cycle`
   - **path:** the `SKILL.md` you just copied

Once registered, `list_scheduled_tasks` (or `/schedule list` in an
interactive session) should show it as `enabled` with a `nextRunAt` in the
future. The routine will message you (not silently do nothing) if the
tracker CSV for a cycle hasn't been dropped yet — that manual step (exporting
the tracker tab and saving it to `cycles/<date>/tracker.csv`) is the one
piece no automation can do, since the tracker is policy-blocked from
automated reading.

### Why nothing exists yet for the SVC front

SVC tasks arrive pre-bundled (no tracker export, no Shared Drive fetch step),
so there's no fetch/diff/bundle cycle to automate the way EKW's is — the SVC
entrypoint (`cycle.py svc-qc <corpus>`) is a single command already, not a
multi-step cycle. If that changes (e.g. SVC gains its own tracker-driven
intake), a second routine can be exported here the same way.

The other folders here are not scheduled routines and have their own README or SKILL.md: `task-read` (run with
`python qc.py read`), `manager-read` (run with `python qc.py manage`), `release-check` (run with `python qc.py release`) and
`tp-fp-classification`.
