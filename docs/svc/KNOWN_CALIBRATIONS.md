# Known calibrations

Status: stale. This is one of the oldest docs in the repo and was written for the older `tests/rubric.json` task shape. See the [doc index](../README.md).

Single source of truth for QC findings that were ruled a false positive or
an accepted convention, rather than a real defect. Both
[`QC_DIMENSIONS_FOR_CREATORS.md`](QC_DIMENSIONS_FOR_CREATORS.md) and
[`CLAUDE.md`](CLAUDE.md) link here instead of restating the ruling, so a
future change to either doesn't leave the other stale.

**Every entry needs a "last re-confirmed" date before you rely on it for a
new task.** These rulings were made against specific delivered task sets,
at a specific point in time. They may not hold for tasks created after this
document was written. If you haven't personally re-checked one of these for
the task in front of you, treat it as open, not settled.

---

## `solution_format_match`

**What was flagged:** the LLM judge reports the golden deliverable "not
saved under the exact required output path" on nearly every task in the
sets checked so far. Goldens are saved under build-convention names (e.g.
`L1-01-01_Golden.xlsx`) rather than the literal path the instruction's
"Save your deliverable(s) to..." block specifies, and no `solve.sh` maps
one to the other.

**Ruling made:** this is a build convention, not a defect. Missing
`solve.sh` is fine; the exact-path mismatch was calibrated out of the
verdict for the sets it was checked against.

**When/where:** `qc_runs/2026-07-17_task1-task3_FIXED_RERUN.md` (task-1,
task-3); cross-referenced in `QC_APPLICABILITY.md`'s harbor task format
section.

**Re-confirm before relying on this — last re-confirmed:** ________________

---

## `metadata_completeness`

**What was flagged:** `task.toml` doesn't carry the `category` field the
dimension checks for.

**Ruling made:** schema difference, not a defect. This task family's
`task.toml` uses `vertical`/`role` fields instead of the `category`/`domain`
fields the dimension expects. The dimension is informational-only regardless
(it never gates a verdict on its own), so this ruling mainly affects how
much attention the finding deserves, not whether a task can ship.

**When/where:** `qc_runs/2026-07-17_task1-task3_FINDINGS.md`.

**Re-confirm before relying on this — last re-confirmed:** ________________

---

## Adding a new entry

If you find a new recurring finding worth calibrating out, add it here with
the same four fields: what was flagged, what ruling was made, when/where
(cite the specific `qc_runs/` run or `QC_APPLICABILITY.md` section), and a
blank re-confirm date. Don't fold a new ruling directly into
`QC_DIMENSIONS_FOR_CREATORS.md` or `CLAUDE.md`; add it here first and link
to it, so there's one place to update if the ruling ever changes.
