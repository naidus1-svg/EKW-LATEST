---
name: synthetic-marker-scan
description: >-
  Scan an SVC/Cirrus task's instruction.md and environment/data/ for leaked
  synthetic-pipeline markers, unrendered template syntax, and anachronistic
  dates before delivery. Use before marking any SVC/Cirrus task ready, or
  right after assembling environment/data/.
---

# Synthetic-marker scan

This is the single highest-value, cheapest script to run — right before
delivery, once `environment/data/` is assembled. These are the most
embarrassing, 100%-avoidable defects found across delivered task sets: a
generation script's own scaffolding leaking directly into what the solving
agent sees. Mirrors the post-hoc pipeline's `synthetic_marker_scan`
dimension, extended with two pattern classes found by hand this round — see
[`QC_DIMENSIONS_FOR_CREATORS.md`](../../QC_DIMENSIONS_FOR_CREATORS.md) for
the full rationale.

## Run it

```bash
python scripts/check_synthetic_markers.py <task_dir>
```

`task_dir` must contain `instruction.md` and `environment/data/`. Reads
plain-text formats directly and extracts `.xlsx`/`.docx`/`.doc`/`.pdf`
best-effort (missing libraries degrade to a reported skip, never a crash —
check the `SKIPPED COVERAGE` line in the output). Emits three findings:

- **`synthetic_pipeline_marker`** (blocking, sev 2) — a bracket-style tag
  (`[TIE]`, `[SYNTHETIC]`, `[AI-GENERATED]`, `[FABRICATED]`, `[GENERATED]`,
  `[OMEGA]`) or a prose fourth-wall break ("this document is a fabricated
  artifact created for a training case study"). One confirmed hit is
  unambiguous — there is no count threshold, and it should never happen.
- **`unrendered_template_leak`** (blocking, sev 2) — a generation script
  computed a value but never substituted it into the final text, e.g. a
  literal `$(T20.inYear)` (Qlik/QlikView-style) left in a document's
  narrative. Found verbatim in two different delivered task sets sharing the
  same corpus file — fixing it once at the source clears it everywhere that
  file gets reused.
- **`anachronistic_date`** (advisory, sev 1) — a year that appears rarely
  against an otherwise-dominant year elsewhere in the task's data (e.g. one
  or two "2026" dates among a corpus that's otherwise consistently "2021").
  **Not an automatic defect** — the script can't know a task's intended
  in-universe year, and legitimate forward-looking references ("the FY2023
  plan") look the same to a pure frequency count. It surfaces a candidate;
  a human confirms. This is the exact shape of a real defect found this
  round: a shipment record correctly showing "2021" in its ID but a "2026"
  arrival date — month and day were right, only the year was wrong, almost
  certainly the generation script stamping the real wall-clock year instead
  of the task's fictional one.

## What it does not do

It does not read scanned/image-only PDFs (no OCR), and a missing
`openpyxl`/`python-docx`/`pypdf` install will show up as skipped coverage
rather than a silent miss — install the missing library to close the gap
rather than assuming a clean run covered every file.
