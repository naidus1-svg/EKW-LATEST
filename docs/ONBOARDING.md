# GDPVal QC — Onboarding

This repo QCs task/rubric quality for **two fronts** — EKW-GDPVal and
SVC/Cirrus — that share one engine (`pipeline/gdpval_qc`) but differ in
task layout, rubric schema, and day-to-day workflow. This file is the
EKW front's onboarding doc (workflow + mental model, most of what follows).
If you're QCing SVC/Cirrus tasks, read [`svc/ONBOARDING.md`](svc/ONBOARDING.md)
instead — the engine internals (§6 below, and `pipeline/README.md`) are
shared, but the day-to-day procedure differs enough that it's its own doc.

## Which front is this?

- Task id looks like `cirrus-y1-task-*`, or the task has `tests/rubric.json`
  (not `tests/verifier.json`) and an `environment/data/` + `solution/golden/`
  layout → **SVC/Cirrus**. Go to [`svc/ONBOARDING.md`](svc/ONBOARDING.md).
- Anything else (task ids that are short numeric/tracker ids, `tests/verifier.json`,
  `environment/` + `solution/golden_outputs/`) → **EKW-GDPVal**. Continue below.

**Read order (EKW front):** this file first (workflow + mental model), then
the [SOP](QC-SOP-first-run.md) (the current step-by-step procedure; the
[doc index](README.md) marks `QC_SOP.docx` SUPERSEDED by it and `CLAUDE.md`
STALE, so do not treat either as the spec), then
[`../pipeline/README.md`](../pipeline/README.md) (the QC engine's own
architecture doc) if you need to touch the Python internals.

## 0. The SOP — start here for the actual day-to-day procedure

> **Status note.** The current day-to-day procedure is [`QC-SOP-first-run.md`](QC-SOP-first-run.md) and the run sheets named in the [top README](../README.md). The [doc index](README.md) marks `QC_SOP.docx` SUPERSEDED by it and says it is not verified whether the two-phase cycle described below is still run. Read this section as background.

[`QC_SOP.docx`](QC_SOP.docx) is the operational walkthrough this onboarding
doc summarizes: the two-phase QC process for a batch of tasks, in the order
you'd actually run it (restructured 2026-08-13 from a three-phase process —
Internal QC and External QC (Automated) are now one continuous pass).

- **Phase 1 — Internal QC + External QC (Automated)**: fetch (from any of
  three trackers) → bundle once for both harbor and Data-OS reward-kit
  format → create the Data-OS dataset and upload (manual) → run the full
  automated eval + trajectory-verification pass (the `dataos-qc-run` skill,
  browser-automated) → import those same artifacts into `03_evals/` →
  run `cycle.py qc` (now eval-grounded, no separate local trial needed) →
  merge Internal QC's own findings with Data-OS's flagged checks into one
  joint packet → adjudicate true_positive/false_positive **once** per batch
  against that joint packet (the same deep-analysis prompt template that
  used to run twice, once per phase) → publish feedback (Drive + tracker) →
  route: approved tasks proceed to Phase 2, rejected tasks go back to
  intake. `cycle.py` covers everything except the Data-OS dataset
  create/upload and the deep-analysis prompt itself.
- **Before Phase 1 — author checklist (step 0)**: authors answer the six questions in [`author-pre-submission-checklist.md`](author-pre-submission-checklist.md) for every heavy rule before submitting a task.
- **Phase 2 - External QC (Manual)**: the current SOP replaces the weekly
  shared dataset that was described here. Khiem (the batch owner) collects
  cleared tasks from the consolidated sheet into batches of 50 or more and
  sends them to the TFRL QC team; you never send anything to TFRL yourself
  (SOP, "What changed" items 1 and 6). The same deep-analysis pass applies
  to the feedback that comes back.

Every batch goes through both phases before it's QC-complete. This
ONBOARDING.md file covers the same ground as Phase 1's `cycle.py` portion in
more system-level detail (why each step exists, what breaks if you skip
it); the SOP is the literal procedure, including the parts of Phase 1 (the
Data-OS click-path and the deep-analysis prompt) and all of Phase 2 that
happen outside `cycle.py` entirely.

---

## 1. What this is, in one paragraph

EKW-GDPVal is a benchmark of long-horizon, document-grounded knowledge-work
tasks (~7–10 hours of expert effort each, across 9 economic domains) used to
train and evaluate LLMs. Each task = a prompt + 3+ source documents + an
expert "golden" solution + a rubric ("verifier") that an LLM judge grades a
model's attempt against. **Our job is Quality Control**: catching tasks that
are too easy, too vague, internally inconsistent, or graded by a broken
rubric — before they're accepted into the RL-usable set. We don't write the
tasks; we gatekeep them and hand back actionable feedback to the people who
do (the "experts team").

## 2. The four things you'll actually do

1. **Fetch** tasks that are ready for QC from a shared tracker + shared drive.
2. **Request evals** (get one or more models to attempt the task) — only for
   the Data-OS-internal QC track; the external eval handoff is a manual
   send/receive, not something we trigger.
3. **Run QC** — an automated multi-judge LLM pipeline that grades the task
   design and the rubric design against a fixed spec, and (for the sampling
   track) grades actual model attempts.
4. **Send feedback** — a report of what's broken, handed to the experts team
   so they can fix the task or rubric.

Everything below maps these four things onto exact commands.

## 3. Mental model: one QC track, one engine

`pipeline/cycle.py qc <date>` runs the full design QC spec
(`specs/gdpval_task_quality_v18.md`, currently v18.6, 36 dims) against every
ready task, 2×/week. Most dims grade task/source/solution/verifier *design*,
not live model attempts, and don't need `03_evals/` populated — but 4
verifier-quality dims (construct validity, outcome coverage, missing
critical dimensions, discriminative power) DO read `03_evals/` trial data
when present (via `verifier_assertion_summary`), which is why the unified
Phase 1 flow (§0) imports Data-OS's automated-pass artifacts into
`03_evals/` before this step runs — those 4 dims are ungrounded, not simply
skipped, without it.

(There used to be a second track here — a 20%-acceptance-sample pass,
`cycle.py redflags`, graded on real model trials via a slim spec. It was
deprecated and removed 2026-08-06: its slim/final spec variants and the
run-based headroom/capability-inversion callbacks they used are gone. If you
find an old note mentioning "full-qc vs sample-qc" or `cycle.py redflags`,
it's stale — there's just `cycle.py qc` now.)

There's also a separate, Turing-internal-only step, **Data-OS submission**
(`cycle.py dataos`), which is how accepted tasks get formally handed off —
see §7.

Default assumption: if someone just says "run QC", they mean `cycle.py qc`.

## 4. Setup (one-time)

This setup is for the `cycle.py` workflow in section 5, which uses the OpenAI and Gemini keys below. The QC person run sheet uses `qc.py` and a `claude` login instead (its "Once" section) and does not mention these keys.

```bash
cd pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# LibreOffice — only needed if the corpus has .docx/.doc/.pptx/.ppt/.xls
# files that must be converted to PDF for judging (it almost always does).
brew install --cask libreoffice          # macOS
# sudo apt-get install -y libreoffice-core libreoffice-writer   # Linux

cp .env.example .env
# edit .env: fill in OPENAI_API_KEY and GEMINI_API_KEY (or GOOGLE_API_KEY)
```

Smoke test:

```bash
gdpval-assess --spec specs/gdpval_task_quality_v18.md \
              --corpus data/sample_corpus --output-dir runs/smoke
```

**Always run `cycle.py` and `gdpval-assess` from inside `pipeline/`.** This
is the single source of truth — there may be other copies floating around
(an internal `platform/` mirror, old `archive/` snapshots); never run QC
from those. If you're not sure which copy is canonical, check
`pipeline/VERSION`.

## 5. The 2×/week cycle, step by step

Everything happens under a dated directory, `cycles/<date>/`, moving through
fixed stages: `00_fetched → 01_diff → 02_bundle → 03_evals → 04_qc →
05_report`.

```bash
cd pipeline

# 0. Scaffold today's cycle dir
python3 cycle.py new
```

### Step 1 — Fetch
The tracker (a spreadsheet of every task + its status) is **policy-blocked
from automated reading** — you must export it by hand. As of the
2026-08-13 restructure there are three trackers, front-tagged (`ekw`, `svc`,
`intake` — see `pipeline/fetch.config.json`'s `fronts` registry and
CLAUDE.md's "QC Cycle Workflow" §1 for the full per-front detail); the
walkthrough below shows the single-tracker case, still valid as `tracker.csv`
(front=ekw by default).

1. Open the tracker ("Omega - Task Tracker - Tasks" tab), export as CSV,
   save it to `cycles/<date>/tracker.csv`.
2. `python3 cycle.py fetch <date>` — reads the CSV, lists every task whose
   Status matches `ready_values` in `pipeline/fetch.config.json`
   (**only** `"ready for eval"` — a separate status, "Ready for Re-review",
   is a different track and is intentionally *not* picked up here). Writes
   one `00_fetched/<id>/` per ready task (with `_source.txt` = the Drive
   link, `_row.json` = the full tracker row) and a `_TO_FETCH.md` checklist.
3. **Download the actual files by hand** from the Shared Drive into
   `00_fetched/` — the Drive's sharing is org-locked, so `gdown` / connector
   tools can't bulk-pull it. This is the one genuinely manual, unavoidable
   step in the whole pipeline.
4. `python3 cycle.py normalize <date>` — flattens bulk-download folder names
   (`Task NNN`) down to `00_fetched/<id>/`.
5. `python3 cycle.py check <date>` — confirms every ready task actually has
   files on disk before you move on.

Drop any task you want to skip this cycle (e.g. known duplicate, out of
scope) into `cycles/<date>/_exclude.txt`, one id per line.

### Step 2 — Diff
```bash
python3 cycle.py diff <date>
```
Hashes each task's actual **content** (source docs + solution files +
Prompt + Rubric text) against `cycles/latest` and writes
`01_diff/changes.md` — new / changed / unchanged. This is a real content
diff, not a status/date check, so a task that got re-uploaded with identical
files shows as unchanged.

### Step 3 — Bundle
```bash
python3 cycle.py bundle <date>
# or, to fix/re-bundle just a few tasks:
python3 cycle.py bundle <date> --only 97,160 --out 02_bundle_fixed
```
Assembles each `00_fetched/<id>/` into a **runnable harbor task package**
at `02_bundle/task_<id>/` — see §8 for the exact layout. Also writes
`02_bundle/_INCIDENTS.md`: every intercurrence worth flagging to the
experts team (empty/malformed rubric JSON, missing source or solution
files, verifier sanity issues — fewer than 6 verifiers, weights not
summing to 1.0, numbering gaps, outcome-weight < process-weight).

**Send `02_bundle/` to the evaluator.** This handoff is manual — there's no
API for it.

### Step 3b — (Data-OS track only) Submission
See §7 — a separate, Turing-internal-only entry point for that track.

### Step 3c — Request the k=1 eval (Harbor-beta, automated)
Added 2026-08-07 — this used to mean asking an external run owner to hand-run
`reference/harbor_evals_quick_guide.md`'s PowerShell steps. `cycle.py` now
does it directly:

```bash
python3 cycle.py evals-package <date> --batch-prefix PREFIX   # repackage 02_bundle/ for upload, solution/ stripped
python3 cycle.py evals-upload  <date>                          # gcloud storage cp to GCS + ready markers (asks to confirm the guide's pre-flight checklist first)
python3 cycle.py evals-enqueue <date> --base-url URL --k N --models-file PATH   # dry-run always; add --live to actually spend
python3 cycle.py evals-status  <date> --batch-prefix PREFIX --expected-trials N --wait   # poll until done
python3 cycle.py evals-fetch   <date>                           # download into 03_evals_raw/, ready for Step 4
```

`evals-package` runs the guide's sanitization checklist as hard gates
(`/workspace/output` referenced, `storage_mb<=10240`, non-empty
`environment/data/`, non-empty `tests/test.sh`, UTF-8 text) and writes
`03_evals_package/_INCIDENTS.md` for anything it rejects. `evals-enqueue`
only spends real money with an explicit `--live` flag — it fetches the
internal secret fresh via `gcloud secrets versions access` each time and
never writes it to disk. See `reference/harbor_evals_quick_guide.md` for the
underlying manual procedure and its full cautions (never touch provider
keys, never delete pending markers/purge queues/kill pods — ask an engineer
when a check fails), and `pipeline/tools/harbor_evals.py` for the
implementation.

### Step 4 — Evals come back
Whoever runs the evals — the `evals-*` commands above, or (still supported)
a human/automated fleet handing you a raw drop directly — gets their trial
outputs into `03_evals/`. Nothing to do here except wait / collect.

### Step 5 — QC
```bash
python3 cycle.py qc <date>          # full design QC (the only QC track; "run QC" means this)
```
This runs the actual multi-judge LLM assessment (see §6) and writes
`04_qc/` — `batch_review.json`, `reviewer_queue.csv`, `batch_summary.md`.

Run QC **once** per change and read the findings + severities, not just the
top-line verdict — LLM-judge noise is real, and a single run is the right
cost/speed tradeoff for iteration. Reserve a 3-run consistency pass for
final verification of something consequential (e.g. right before a formal
acceptance decision).

### Step 6 — Report, ledger, close
```bash
python3 cycle.py report <date>   # collects everything into 05_report/ for sharing
python3 cycle.py ledger <date>   # updates the cross-cycle task_ledger (novelty + repeat-feedback tracking)
python3 cycle.py close <date>    # advances cycles/latest, so the *next* cycle diffs against this one
python3 cycle.py status          # all cycles + how far each got
```

**`close` is the one command with lasting effect** — it moves the diff
baseline forward. Don't run it until you're actually done with the cycle.

## 6. What "running QC" is actually doing

`gdpval-assess` (invoked internally by `cycle.py qc`) is a multi-judge LLM
ensemble graded against a versioned spec (currently v18.6, canonical file:
`pipeline/specs/gdpval_task_quality_v18.md`):

- Each of ~21 LLM-graded quality dimensions is judged independently by
  **two models** (GPT-5.5 + Gemini-3.1-pro by default) at high reasoning
  effort; 4 more dimensions are deterministic Python callbacks.
- Findings are aggregated (evidence-quote requirements, low-confidence
  demotion, disagreement handling) into one verdict per task:
  `accept` / `accept_with_fixes` / `needs_review` / `reject_fixable` /
  `reject_structural`.
- A synthesizer LLM turns raw findings into a human-readable top-issues
  list per task.
- The framework never edits your data — it only grades and queues. Fixing
  is on the experts team (or you, if you're empowered to hand-repair, e.g.
  a malformed rubric).

Full architecture + the exact dimension list live in
[`../pipeline/README.md`](../pipeline/README.md).

## 7. Data-OS submission (Turing-internal track)

As of the 2026-08-13 restructure, `cycle.py bundle` already runs this
automatically for every bundled task (§5 step 3) — you only need the
command below directly for a standalone re-run (e.g. converting a subset
after fixing an incident, or a bundle sitting outside any cycle folder via
`cycle.py dataos-standalone <bundle_dir> <out_dir>`).

```bash
python3 cycle.py dataos <date> [--only ids] [--name NAME] [--deadline DD/MM/YYYY]
```
Converts every bundled task to reward-kit format (EKW's `tests/verifier.json`
and SVC's `tests/rubric.json` are both supported) and drafts the two
hand-off artifacts a Turing-internal QC request needs: a one-pager
(`QCR_<name>_<date>.docx`) and the `#TFRL_QC` Slack message (TFRL is the QC team that reviews finished tasks), into
`cycles/<date>/dataos/`, plus `SUBMISSION.md` (convert status per task +
the remaining manual checklist).

**Everything past this point is manual, by design** (per project
convention, DataOS-facing steps are never automated): Data-OS upload,
oracle-pass confirmation, freezing the dataset. Do not share anything with
the TFRL QC team and do not post in `#tfrl_qc` yourself (SOP section 7).

Gotcha: a task whose golden output is a single un-extracted `.zip` archive
converts to a *silently empty* `solution/files/` — the converter detects
this and excludes the task with an explicit reason rather than reporting a
false "converted." Don't assume every task in a batch actually converted;
check `SUBMISSION.md`.

If you want the eval + verification runs *inside* Data-OS run for you
rather than by hand, see the `dataos-qc-run` skill in `../skills/ekw/dataos-qc-run/` — it drives
the live Data-OS UI via browser automation for a whole dataset at once.
Read `../reference/dataos_recipe/RECIPE.md` once before first use; it has the
exact click-path, selectors, and gotchas. Scope is fixed (3 evals + 2
Agent Trajectory QC runs per task, no Loss Pattern / Comprehensive Review)
— don't expand it without checking with whoever owns the process at the
time. That scope belongs to the old skill: the [doc index](README.md) marks
the skill and the recipe STALE. The current DataOS pipeline is in SOP 6b:
five evaluation runs, then four "Answer Check" reviews.

## 8. The harbor task format (what "bundle" produces)

Every bundled task is a **runnable** package, not just a rubric — upload
validators enforce this:

```
task_<id>/
├── instruction.md
├── task.toml                    # metadata; benchmark_type deliberately omitted (see below)
├── environment/
│   ├── Dockerfile
│   └── data/                    # source documents
├── solution/
│   ├── solve.sh                 # oracle: copies ONLY the graded deliverables into /workspace/output/
│   └── golden_outputs/          # ONLY the graded deliverables solve.sh copies (no Reasoning.docx / expert-only files)
└── tests/
    ├── test.sh                  # generic entrypoint, copied verbatim from templates/harbor/
    ├── verifier_runtime.py      # generic runner, copied verbatim
    ├── verifier_lib/            # generic verifier library, copied verbatim
    └── verifier.json            # the rubric — the only task-specific file in tests/
```

Rules worth internalizing:
- **`solve.sh` copies only what the verifier grades.** A deliverable is a
  golden file the verifier reads back as `output/<name>`. Never copy
  expert-only files (e.g. a `Reasoning.docx`) into output — a
  side-effect-aware verifier will penalize the unsolicited file.
- **`test.sh` / `verifier_runtime.py` / `verifier_lib/` are shipped
  verbatim** from `pipeline/templates/harbor/` — never hand-edit per task.
- **`benchmark_type` is deliberately absent** from `task.toml` — the
  platform's enum only covers code/SWE benchmarks, none of which fit
  document-grounded knowledge work, and it's a warning, not a hard error.
  Don't "fix" this by mislabeling the task.
- The canonical reference task (what a correct bundle looks like) is
  `pipeline/data/sample_corpus/task_11/`.

## 9. Task & verifier quality bar (what you're actually judging)

Full detail is in [`CLAUDE.md`](CLAUDE.md) — read it, don't just skim this
summary. The short version:

**A good task** is rooted in real practitioner work, requires genuine
domain depth (a generalist would miss the key considerations), resists
shortcuts (right answer hinges on exceptions/tradeoffs a naive model
glosses over), and has headroom (a weak model can get partial credit, a
strong model is genuinely rewarded for expertise). Prompts describe *what*
to determine, never *how* (no method names, formulas, or column
references that leak the answer). Source documents (3+) must
cross-reference each other so the task is unsolvable from any single file,
match format to genre (.xlsx for tabular, .docx for memos, .pdf for
signed/final docs), and contain zero leaked answers.

**A good verifier (rubric)** has 6+ atomic, self-contained, independently
gradeable checks in `tests/verifier.json`, weights summing to exactly 1.0,
core/secondary classification (core = "if this alone failed, would an
expert still call it solved? No → core"), and at least one check that
penalizes unsolicited additions (extra files/sections/claims not asked
for). Delete verifiers that only check file existence, only check a
filename, or substantially overlap another verifier on the same artifact.

## 10. Sending feedback

The feedback loop back to the experts team happens through two documents,
both produced automatically:

- **`02_bundle/_INCIDENTS.md`** — structural problems found while
  *assembling* the task (broken/empty rubric JSON, missing files,
  verifier-sanity issues). Send this every cycle, even if short.
- **`04_qc/reviewer_queue.csv` + `batch_summary.md`** — the actual QC
  verdict per task: top-3 must-fix issues, minor "extras", severity,
  fixability, and an evidence quote per finding. This is what you hand back
  after a QC run — it's built to be actionable without extra editorializing
  from you.

`cycle.py report <date>` bundles both plus the cycle's other artifacts into
`05_report/` as the single thing to actually share (Slack, email, whatever
your team's channel is).

## 11. Skills (EKW front)

Drop `../skills/ekw/` (and `../skills/_shared/QC_FOUNDATION.md`, which they
all depend on) into wherever your Claude Code / agent tool loads skills
from, and these become invokable:

| Skill | Use for |
|---|---|
| `gdpval-verifier-qc` | QC just the rubric of one task (2 LLM gates + 3 programmatic checks) |
| `gdpval-golden-qc` | QC the golden/expert solution of one task |
| `gdpval-prompt-input-qc` | QC the prompt + source documents of one task |
| `gdpval-task-qc` | Full single-task QC (prompt/input + solution, no verifier) |
| `gdpval-task-qc-with-verifiers` | Full single-task QC including the verifier |
| `harbor-rewardkit-convert` | Convert a bundled harbor task to reward-kit format |
| `dataos-qc-run` | Browser-automate the Data-OS eval+QC click-path across a whole dataset |

These are for **single-task, ad-hoc** QC (e.g. "check just this one task's
rubric"). The **cycle-level** workflow in §5 is what you use for the
regular 2×/week batch — it doesn't require invoking skills at all, just
`cycle.py`. (SVC's equivalent skills live in `../skills/svc/` — see
[`svc/ONBOARDING.md`](svc/ONBOARDING.md).)

## 12. Known rough edges (don't rediscover these the hard way)

- **`how_justification` fields** in many existing tasks were
  auto-converted and read generic/confusing — flag and improve when you
  see them.
- **`output_variables.json`** in golden solutions isn't used by
  verification — safe to ignore/remove if you see it.
- **Trials without skills enabled** (some Gemini runs) — note this when
  judging trajectory quality; it's a known confound, not a task defect.
- **A few tasks have no verifier headroom** — expert and model attempts
  both score near 1.0. Not a bug in your QC; the rubric genuinely has
  nothing left to discriminate on.
- **Verifier-gate calibration is settled** (2026-07-09) — before flagging
  an "always-fails" or "0%-pass" rubric as broken, or an "over-strict"
  rubric, check whether the *golden* solution passes it. If the golden
  passes, the rubric is hard/demanding, not broken. A soft quantifier
  ("several", "most") is fine if backed by an enumerated set elsewhere. A
  criterion covered by a *combination* of rubrics isn't a gap. A missing
  side-effect/output-dir check is polish (sev 1), not a gating defect.

## 13. Project layout reference

This repo QCs two fronts sharing one engine — see the root
[`../README.md`](../README.md) for the full picture. The EKW-relevant parts:

```
gdpval-qc/
├── pipeline/            THE QC tool — single source of truth, run from here
│   ├── gdpval_qc/       the assessment engine (spec, judges, aggregation, emitters)
│   │   └── tools/       check_verifier.py, check_rubric.py, check_dag.py, extract_task_files.py
│   │                    — canonical checker/extractor modules, run as `-m gdpval_qc.tools.<name>`
│   ├── specs/
│   │   ├── gdpval_task_quality_v18.md   the base spec (single source of truth; currently v18.6)
│   │   └── overlays/    front-specific deltas via `extends:` — svc.md, svc-noeval.md, no-eval-gates.md
│   ├── tools/           EKW-only automation: bundle.py, drive_fetch.py, dataos_submission.py, to_rewardkit.py, ...
│   ├── templates/harbor/   the runtime (test.sh + verifier_runtime.py + verifier_lib) shipped verbatim into every bundled task
│   └── cycle.py         the cycle driver (new|fetch|diff|bundle|qc|dataos|svc-qc|evals-package|evals-upload|evals-enqueue|evals-status|evals-fetch|report|ledger|close|status)
├── cycles/              dated cycle directories (EKW-specific; gitignored — created locally as you work); cycles/latest -> diff baseline
├── skills/
│   ├── ekw/             the 7 skills listed in §11
│   ├── svc/             SVC's equivalent skills — see svc/ONBOARDING.md
│   └── _shared/QC_FOUNDATION.md   grading protocol both fronts' skills depend on
├── docs/                you are here — CLAUDE.md, QC_SOP.docx, and svc/ (SVC's onboarding pair)
├── reference/           dataos_recipe/RECIPE.md (load-bearing — the dataos-qc-run skill reads it)
└── automation/          exportable Claude Code scheduled-task routines (e.g. ekw-qc-cycle)
```
