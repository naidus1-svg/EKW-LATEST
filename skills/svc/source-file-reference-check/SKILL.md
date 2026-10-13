---
name: source-file-reference-check
description: >-
  Check that every file an SVC/Cirrus task's instruction.md references by
  name actually exists in environment/data/, and flag environment/data/
  files the instruction never mentions. Use when drafting or finishing an
  instruction.md for an SVC/Cirrus task, or before marking one ready for
  delivery.
---

# Source-file reference check

Referenced files missing from `environment/data/` is the single most common
real defect found across delivered SVC/Cirrus task sets so far — an
instruction names a specific file ("the KPI report", "the governed
revenue-adjustment bridge", a named `.xlsx`/`.csv`) that was never bundled
into the data room, making the task unsolvable as written. This mirrors the
mechanical half of two post-hoc QC dimensions,
[`instruction_input_consistency` and `self_containedness`](../../QC_DIMENSIONS_FOR_CREATORS.md).

## Run it

```bash
python scripts/check_references.py <task_dir>
```

`task_dir` must contain `instruction.md` and `environment/data/`. Emits
three findings in the standard shape (dimension/role/severity/evidence/fixability):

- `source_file_reference_missing` (blocking, sev 2) — a filename the
  instruction names by extension (`.xlsx`, `.docx`, `.pdf`, `.csv`, etc.) does
  not resolve to any file under `environment/data/`. Fix by bundling the file
  or removing the reference.
- `source_file_reference_unreferenced` (advisory, sev 1) — a file under
  `environment/data/` that `instruction.md` never names. **Not automatically
  wrong** — some tasks (confirmed this round on two delivered sets)
  deliberately hand a node the entire shared company data room and expect the
  solving agent to search it, so an "orphan" file may be the intended design.
  Use this as a prompt to double-check, not a hard requirement.
- `source_data_dir_pointer_only` (blocking, sev 2) — `environment/data/`
  contains zero real files, only a `SOURCES.md` pointer (or nothing at all).
  Added after a calibration miss: an instruction referenced files only by
  category ("the four OpEx handoff files"), never by literal filename, so
  the name-matching check above passed vacuously while the folder was
  functionally empty. Catches that failure mode regardless of how the
  instruction phrases its references.

## What it does not do

This only checks that a named file *exists* — it cannot tell whether that
file's *content* actually matches what the instruction asks for (e.g. an
instruction says "reconcile against the KPI report" and a file named
accordingly exists, but is actually empty or off-topic). That semantic half
stays with the
[`authenticity-and-substance-review`](../authenticity-and-substance-review/SKILL.md)
checklist — don't over-trust a clean run here as "the task is solvable,"
only as "nothing named is missing."

## Reading the output

Missing references are the higher-priority signal — fix these before
delivery. The unreferenced-file list is worth a quick scan but only worth
acting on if you didn't intend a full-data-room design for this node.
