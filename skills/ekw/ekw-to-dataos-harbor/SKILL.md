---
name: ekw-to-dataos-harbor
description: >-
  Converts an EKW harbor task (internal format) into the correct DataOS-uploadable
  package. EKW tasks come in two build genres that need two different converters --
  this skill auto-detects which genre a task is and dispatches to the right one,
  rather than assuming one converter fits every task. Use whenever you need to
  prepare one or more EKW tasks for DataOS upload, or you hit a DataOS sandbox-creation
  error like "Path does not exist: .../environment/initial_workspace/" (a strong
  signal a task was converted with the wrong converter for its genre).
---

# EKW → DataOS harbor conversion

## Why this exists

EKW's 274-task corpus ships in two structurally different build genres that look
similar (same top-level layout: `instruction.md`, `task.toml`, `environment/`,
`solution/`, `tests/`) but need different treatment to become DataOS-uploadable:

| Genre | Signature | Converter |
|---|---|---|
| **native-harbor** | `task.toml` has `artifacts =`; `solution/solve.sh` copies `golden_outputs/`; `tests/verifier_runtime.py` present; Dockerfile installs `verifier-requirements.txt` / copies skills | `scripts/to_dataos_harbor.py` |
| **rewardkit-hybrid** | `task.toml` has `schema_version = "1.1"`; `solve.sh` copies `/solution/files/` to `/app/`; no `verifier_runtime.py`; Dockerfile does `COPY initial_workspace/ /app/` | `scripts/to_rewardkit.py` |

Running the wrong converter on a task produces a package that looks structurally
fine on disk but fails at DataOS's Daytona sandbox-creation step with:

```
DaytonaError: Failed to create sandbox: Path does not exist:
.../environment/initial_workspace/
```

This happens because a rewardkit-hybrid task's Dockerfile expects
`environment/initial_workspace/` to exist (populated from `environment/data/`),
but only `to_rewardkit.py` ever produces that directory — `to_dataos_harbor.py`
(built for native-harbor tasks) never does, and the raw task directory never ships
it either. This is a real defect class, confirmed live on DataOS (2026-09-15,
converting an entire 74-task batch uniformly through `to_dataos_harbor.py` without
checking genre first shipped 4 broken tasks this exact way).

**If you see that error, don't guess — run `scripts/detect_genre.py` on the task
first.** If it comes back `rewardkit-hybrid`, the task needs `to_rewardkit.py`,
not `to_dataos_harbor.py`.

## Requirements

Python 3.11+ (stdlib only — `tomllib` is used by `to_rewardkit.py`). No pip
packages needed to run the conversion itself; the *generated* `tests/test.sh` for
rewardkit-hybrid tasks installs its own dependencies (`harbor-rewardkit`,
`openpyxl`) inside the DataOS container at grading time, not here.

## Usage

**One task, genre auto-detected:**
```bash
python scripts/convert.py <task_dir> <out_dir>
```

**A whole corpus at once** (prints a per-task genre + outcome table, then totals):
```bash
python scripts/convert.py --all <root_dir_of_task_* dirs> --out-dir <out_root>
```
Each task lands at `<out_root>/<task_id>/`. Nothing is silently skipped — a task
whose genre signals are absent, tied, or conflicting comes back `skipped` with the
reason and the raw per-file signal votes, never forced through either converter.

**Just check genre, no conversion** (useful for auditing a corpus before converting):
```bash
python scripts/detect_genre.py <task_dir>            # one task, JSON output
python scripts/detect_genre.py --all <root_dir>      # every task_* dir, table + totals
```

**Optional flags** (rewardkit-hybrid tasks only, ignored for native-harbor):
- `--prefix <name>` — task-name prefix for the generated rewardkit task name (default `ekw`)
- `--max-criteria-per-judge <N>` — once a task's rubric has more than N criteria, the
  judge is split across multiple `deliverables_NN/judge.toml` chunks (default 12,
  matches Anthropic's strict-tool schema-size limit that motivated this default)

## What each converter actually does

**`to_dataos_harbor.py`** (native-harbor): copies the task tree verbatim, then
replaces `tests/{test.sh,verifier_runtime.py,verifier_lib/}` with patched versions
from `templates/dataos_harbor/` — `verifier_runtime.py` becomes
`verifier_runtime.pyrun` and `verifier_lib/` becomes `__verifier_lib/`, so DataOS's
own upload-time `rewardkit.discover()` scan doesn't try to import anything under
`tests/` at all (previously it did, which — even when the import succeeded — wrote
real `__pycache__/*.pyc` files that DataOS's own validator then flagged right back
as "files that may not be relevant"). Needs `templates/dataos_harbor/` to sit
alongside it (two directories up from the script, same relative layout as this
skill package) — don't move one without the other.

**`to_rewardkit.py`** (rewardkit-hybrid): produces a fully independent, self-contained
reward-kit-native package — `environment/initial_workspace/` (populated from
`environment/data/`), `solution/files/` (deliverable copies, `.xlsm` pre-converted
to `.xlsx`), `tests/deliverables_NN/judge.toml` (one or more judge chunks, Claude-only
per a locked policy — a non-Anthropic judge model named in the source `verifier.json`
gets silently forced to `anthropic/claude-sonnet-4-6`), `tests/reward.toml`, and a
generated `tests/test.sh` that installs `harbor-rewardkit` itself at grading time.
No shared template dependency, no `verifier_lib` — it's a completely different
package shape from `to_dataos_harbor.py`'s output, which is exactly why it must
never go through `to_dataos_harbor.py` afterward.

## Verifying a conversion before uploading

A quick, zero-cost sanity check that catches the exact defect class this skill
exists to prevent:
```bash
# native-harbor output should have tests/__verifier_lib/ (not tests/verifier_lib/)
test -d <out_dir>/tests/__verifier_lib && echo OK

# rewardkit-hybrid output should have environment/initial_workspace/ populated
# with the same file count as the source task's environment/data/
diff <(ls <src_task_dir>/environment/data) <(ls <out_dir>/environment/initial_workspace) && echo OK
```
If either check fails, the wrong converter likely ran — re-check genre with
`detect_genre.py` before re-converting.
