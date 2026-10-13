# SVC-PC builder preflight

Status: stale. This is one of the oldest docs in the repo and was written for the older `tests/rubric.json` task shape. See the [doc index](../README.md).

Run this before building any SVC task. It does not create outputs, touch
Drive files, call a model, or submit anything to DataOS.

The builder needs three local inputs:

1. A staged task directory. Each task must be under `00_fetched/<task-id>/`
   and include one Prompt file, one Grading Rubric `.xlsx`, and the Golden
   deliverable. Normalize the Golden folder name to `Golden Solution` before
   running the builder.
2. A local copy of the Cirrus Sleep Full Y1 corpus. Hydration uses it to add
   the real input files named by each task.
3. The project virtual environment with the dependencies from
   `pipeline/pyproject.toml` installed.

From `C:\ekwqc\svc-builder-windows\pipeline` in PowerShell:

```powershell
$env:SVC_PC_INPUT_ROOT = 'C:\path\to\00_fetched'
$env:SVC_PC_OUTPUT_ROOT = 'C:\path\to\svc_pc_output'
$env:SVC_PC_CORPUS_ROOT = 'C:\path\to\Cirrus Sleep Full Y1 (FINAL VERSION)'
$env:SVC_PC_SCRATCH_ROOT = 'C:\path\to\svc_pc_scratch'
$env:SVC_PC_PYTHON = (Resolve-Path '.\.venv\Scripts\python.exe')

& .\.venv\Scripts\python.exe .\tools\svc_pc_batch_convert.py --preflight
```

Expected result: the three path checks say `ok` and the staged task-folder count
matches the intended batch. The preflight does not validate individual rubric
contents or build a package.

Do not run the builder until the source-file changes are complete and the
preflight passes.

## Build one task safely

Start with one task. This normal command does not delete an existing package
or an earlier report. If the task already has a ready or messy output, it is
skipped and the command explains how to choose a separate output root or
intentionally replace it.

```powershell
& .\.venv\Scripts\python.exe .\tools\svc_pc_batch_convert.py `
  --only 'SVC-PC-2-3-0'
```

`--only` accepts a comma-separated list when a small, known set is ready.

## Build a full-corpus task

Use this path only when the prompt requires the complete Cirrus corpus rather
than named inputs. Create an empty `_FULLCORPUS` marker directly in the staged
`00_fetched/<task-id>/` folder, then run the same one-task command with
`--only`. The builder passes `--dvc-fullcorpus` to `assemble_task.py` instead
of `--source-dir`; the resulting package contains the checked-in DVC pointer,
not a copied corpus.

```powershell
New-Item -ItemType File 'C:\path\to\00_fetched\SVC-PC-2-3-0\_FULLCORPUS'
& .\.venv\Scripts\python.exe .\tools\svc_pc_batch_convert.py `
  --only 'SVC-PC-2-3-0'
```

Use a separate output root for the first full-corpus pilot. A later execution
environment needs the configured DVC remote and its permitted credentials to
materialize the corpus. The current builder still requires a local corpus root
because preflight validates and indexes it before processing any task. Review
each marker as an explicit task-wide data-scope decision. Do not use `--reset`
unless replacing that selected task package is intentional.

## Replace a selected task output

Use this only after confirming that the staged source for that task is the
correct version. It removes `03_dataos_ready/<task-id>` and
`03_dataos_messy/<task-id>` for the selected task, then rebuilds that task.
It does not remove outputs for other tasks.

```powershell
& .\.venv\Scripts\python.exe .\tools\svc_pc_batch_convert.py `
  --only 'SVC-PC-2-3-0' `
  --reset
```

Passing `--reset` without `--only` intentionally clears the complete ready
and messy output directories. Do not use that form for the first pilot.
