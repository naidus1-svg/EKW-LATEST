# gdpval-qc — GDPVal Task Quality Assessment

Automated quality assessment of **GDPVal-style** knowledge-work task datasets:
instruction + input files + golden solution + rubric verifiers. Drives a
multi-judge LLM ensemble over a versioned, code-encoded quality spec and
emits actionable reviewer artifacts.

This is the **v18.5** standalone distribution.

---

## What it does

Given a corpus of tasks laid out like:

```
corpus/
  task_1/
    task.toml                       # metadata (domain, sector, ...)
    instruction.md                  # the agent-facing prompt
    environment/                    # files the agent receives as input
    solution/golden_outputs/        # the gold-standard output
    tests/verifier.json             # rubric assertions (LLM- or code-checked)
    evals/<model>/trial_*/...       # (optional) verifier-report.json runs
  task_2/ ...
```

it runs **25 quality dimensions** over each task — 21 graded by LLM judges,
4 by deterministic Python callbacks — and writes:

- `batch_review.json` — full machine-readable verdict + every dim finding +
  every issue + every judge attempt (for audit/replay)
- `reviewer_queue.csv` — one row per sample with **top 3 must-fix issues** and
  up to 5 minor "extras" suggestions, each with severity / fixability /
  headline / action / evidence quote / detail / judge agreement
- `batch_summary.md` — human-readable verdict mix + failure-mode histogram
- `raw/sample_<id>.json` — per-sample LLM transcripts (one file per sample)

Each sample is bucketed into one of five **verdict tiers**:

| Tier | Meaning |
|---|---|
| `accept` | All judges happy, no findings above informational. |
| `accept_with_fixes` | Minor advisory issues only; ship it, address in next pass. |
| `needs_review` | Judges disagree, or low confidence at sev 2+. **Human triage.** |
| `reject_fixable` | Material issues; the task isn't shippable but is salvageable. |
| `reject_structural` | A blocking dim hit `reject_at_severity` with structural fixability. |

The framework **does not** modify your data — it grades, classifies, and
queues. Action is yours.

---

## Quick start

```bash
# 1. Make a virtualenv (Python 3.11+).
python3 -m venv .venv
source .venv/bin/activate

# 2. Install in editable mode.
pip install -e .

# 3. (Optional) LibreOffice — required only if your corpus contains .docx /
# .doc / .pptx / .ppt / .xls files that need conversion to PDF for judging.
# Skip if your corpus is xlsx + pdf + plain text only.
brew install --cask libreoffice                                # macOS
sudo apt-get install -y libreoffice-core libreoffice-writer    # Linux

# 4. Configure judge API keys. Edit .env (gitignored):
cat > .env <<'EOF'
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...          # or GOOGLE_API_KEY
# ANTHROPIC_API_KEY=...     # only if you re-wire judges to Claude
EOF

# 5. Smoke test on the bundled single-task sample (data/sample_corpus/task_11).
gdpval-assess \
    --spec specs/gdpval_task_quality_v18.md \
    --corpus data/sample_corpus \
    --output-dir runs/smoke

# 6. Run on your own corpus.
gdpval-assess \
    --spec specs/gdpval_task_quality_v18.md \
    --corpus /path/to/your/corpus \
    --output-dir runs/full
```

`pip install -e .` drops the `gdpval-assess` script on your `$PATH`. If you
prefer module-form invocation, `python -m gdpval_qc.cli ...` is identical.

Expect roughly **~43 LLM calls per task** (~21 LLM dims × 2 judges + 1
synthesizer). Costs scale linearly with task count and judge model.

---

## Architecture

8-stage pipeline; each stage is a separate module:

```
┌───────────────┐    ┌──────────────────┐    ┌───────────────────┐
│ TaskCorpus    │ →  │ Preconditions    │ →  │ Judge ensemble    │
│ Loader        │    │ (applies_when)   │    │ (LLM + programmatic)│
└───────────────┘    └──────────────────┘    └─────────┬─────────┘
                                                       │
                                                       ▼
┌──────────────┐    ┌──────────────┐    ┌────────────────────────┐
│  Emitters    │ ←  │  Synthesizer │ ←  │  Verdict + Aggregation │
│ (json/csv/md)│    │ (LLM)        │    │  (deterministic)       │
└──────────────┘    └──────────────┘    └────────────────────────┘
```

| Stage | Module | Concern |
|---|---|---|
| Spec | `gdpval_qc/v18_spec.py` | Parse the markdown + YAML spec. Versioned, hashable. |
| Loader | `gdpval_qc/v18_loader.py` | Walk the task dir, populate `Sample.fields`. |
| Preconditions | `gdpval_qc/precondition.py` | Decide which dims apply per sample (e.g. skip chart-quality on a no-chart solution). |
| Judging | `gdpval_qc/v18_judge.py` | Build prompts, call each judge model, parse JSON. |
| Aggregation | `gdpval_qc/v18_aggregate.py` | Combine judge attempts into a single `DimensionFinding`; resolve disagreement. |
| Callbacks | `gdpval_qc/v18_callbacks.py`<br>`gdpval_qc/v18_verifier_summary.py` | Deterministic programmatic checks + verifier-report synthesis. |
| Verdict | `gdpval_qc/v18_verdict.py` | Apply gate roles to land on one of 5 tiers. |
| Synthesizer | `gdpval_qc/v18_synthesizer.py` | LLM-summarize the findings into top issues + minor suggestions. |
| Emitter | `gdpval_qc/v18_emitter.py` | Write `batch_review.json`, `reviewer_queue.csv`, `batch_summary.md`. |
| Engine | `gdpval_qc/v18_engine.py` | Orchestrate all of the above; three-tier parallelism. |
| Calibration | `gdpval_qc/v18_calibration.py` | (Optional) compare verdicts against a hand-labeled golden set. |

### Multi-judge ensemble

Default judges (configured in the spec):

```yaml
models:
  - model: "gpt-5.5"
    reasoning_effort: high
  - model: "gemini-3.1-pro-preview"
    reasoning_effort: high
```

Each LLM-graded dimension is judged by **both** models. The aggregator
applies:

- `require_evidence_quote=true` — any sev ≥ 1 finding without a `≥`30-char
  exact-quote evidence is demoted.
- `confidence_demotion.low_at_sev1=demote_to_0` — sev-1 findings flagged
  `confidence: low` get demoted to no-issue.
- `confidence_demotion.low_at_sev2_or_higher=route_to_review` — sev-2+ at
  `confidence: low` forces the verdict to `needs_review` instead of reject.
- **Disagreement override**: if the two judges differ by ≥1 severity level
  on a blocking dim, the sample is routed to `needs_review` even when the
  worst severity would normally trigger reject.

### Multimodal transport

Office files in `solution/golden_outputs/` and `environment/` are converted
to **PDF** before being sent to judges that accept document blocks
(`gpt-5.5`, `gemini-3.1-pro-preview`):

| Source | Sent as |
|---|---|
| `.pdf` | passthrough (`application/pdf`) |
| `.docx` / `.doc` / `.pptx` / `.ppt` | LibreOffice → PDF |
| `.xlsx` with chart objects | LibreOffice → PDF (preserves visuals) |
| `.xlsx` without charts | text extract (cheaper, equivalent for formula-only models) |
| `.xls` | LibreOffice → PDF |
| plain text | inline text block |

Each judge sees the original extension (`.docx`) alongside the converted
artifact, so format-match dims grade the **source** extension, not the
PDF wrapper.

### Caching

Two layers:

1. **Document conversion cache** at `~/.cache/gdpval-qc/converted/` (override
   with `--cache-dir`) — content-hash keyed
   (`<stem>_<sha256[:16]>.pdf` / `.txt`). LibreOffice conversions are
   expensive (~2-5s per file); the cache eliminates re-conversion on
   re-runs.
2. **Verifier-report summary** is built per-sample at load time (cheap;
   not cached; runs in a few ms per task).

Both run automatically; you do not need to configure either. The cache
auto-invalidates when the source file's bytes change.

### Parallelism

Three tiers, controlled via `V18Engine(...)` or `v18_assess.py` flags:

| Tier | Default | What it parallelizes |
|---|---|---|
| `sample_parallelism` | 1 | Process N samples concurrently. |
| `dim_parallelism` | 4 | Per sample, judge N dimensions concurrently. |
| `judge_parallelism` | 2 (implicit) | The 2-judge ensemble runs concurrently per dim. |

For a 20-task corpus: sample_parallelism=4 × dim_parallelism=4 = 16
in-flight judge calls. With the default OpenAI tpm limit of 20M and Gemini
2M, this stays well under throttle.

---

## The quality spec (v18.5)

The spec at `specs/gdpval_task_quality_v18.md` defines **25 dimensions**.
Each dim has:

- A YAML config (gate role, reject threshold, inputs, applies_when)
- Prose rubric text describing the severity-0/1/2/3 patterns
- (For LLM dims) — auto-built into the judge prompt
- (For programmatic dims) — references a Python callback name

### 6 structural-reject dims (`reject_at_severity: 2`)

If any of these hits sev 2, the sample is **rejected** unless judges
disagree (→ NEEDS_REVIEW):

1. `overall_gdpval_fit` — task fits the GDPVal scope (knowledge work,
   not coding-only, not toy)
2. `instruction_input_consistency` — instruction references files that
   actually exist in `environment/`
3. `professional_complexity` — task takes ≥30 min of expert work
4. `instruction_authenticity` — sounds like a real workplace ask
5. `input_file_authenticity` — input files look like real artifacts, not
   synthetic templates
6. `verifier_spec_parseable` — `verifier.json` parses cleanly

### 4 programmatic dims (deterministic, no LLM)

| Dim | What it checks |
|---|---|
| `metadata_completeness` | `task.toml` has the required keys. |
| `verifier_spec_parseable` | `verifier.json` is valid JSON with the expected shape. |
| `verifier_count_in_range` | Verifier count within `[3, 20]`. |
| `verifier_outcome_grader_present` | At least one verifier is `metadata.classification == "core"` OR `metadata.grading_role == "outcome"`. |

### 15 other LLM dims

Cover task-structure (`self_containedness`, `clear_success_criteria`,
`time_bounded`), solution-quality (`solution_format_match`,
`solution_completeness`, `solution_chart_quality`), and verifier-quality
(`verifier_rubric_clarity`, `verifier_specificity`, etc.).

### Anti-overcall guards

Built into the spec (not configurable per dim):

- `require_evidence_quote: true` — sev ≥ 1 must include a real ≥30-char
  quote from the inputs.
- `confidence_demotion: { low_at_sev1: demote_to_0, low_at_sev2_or_higher: route_to_review }`
- `top_issues_cap: 3` (must-fix only) + `suggested_fixes_cap: 5` (minor
  advisory extras)

Tuning these requires editing the spec markdown — see the YAML frontmatter
and per-dim `gate:` blocks.

---

## Customization

### Write a new spec

Copy `specs/gdpval_task_quality_v18.md` to a new file and edit. The parser
enforces structure (E1-E12 hard errors, W1-W5 warnings). See
`gdpval_qc/v18_spec.py` for the full validation rules.

The version field must start with `18.` (the parser rejects v17 and below).

### Add a precondition

Edit `gdpval_qc/precondition.py` and add a `Sample → bool` function. Then
register it:

```python
from gdpval_qc.precondition import BUILTINS
BUILTINS["my_precondition"] = my_check_function
```

Reference it from the spec:

```yaml
applies_when:
  builtin: my_precondition
```

### Add a programmatic callback

Edit `gdpval_qc/v18_callbacks.py`:

```python
def check_my_dim(sample: Sample, dim: V18Dimension) -> DimensionFinding:
    # ... your logic ...
    return DimensionFinding(
        dimension=dim.name,
        dimension_name=dim.dimension_name,
        severity=2,
        confidence="high",
        applicable=True,
        headline="brief failure summary",
        justification="...",
        fixability="structural",
    )

BUILTIN_CALLBACKS["check_my_dim"] = check_my_dim
```

Reference it from the spec:

```yaml
check_kind: programmatic
callback: check_my_dim
```

### Use a different LLM

The default judges are GPT-5.5 + Gemini-3.1-Pro. To use Anthropic, edit
the spec's `models:` block:

```yaml
models:
  - model: "claude-opus-4-7"
    reasoning_effort: high
```

And ensure `ANTHROPIC_API_KEY` is set. The client adapter is already
wired (`gdpval_qc/llm_client.py:AnthropicClientAdapter`).

---

## CLI reference

```
gdpval-assess [OPTIONS]
# equivalent: python -m gdpval_qc.cli [OPTIONS]

Required:
  --spec PATH               v18 spec markdown file
  --corpus PATH             root directory containing task_*/ subdirs
  --output-dir PATH         where to write artifacts

Selection (optional):
  --limit N                 process only first N tasks
  --tasks task_1,task_3     process only these specific task IDs

Parallelism (optional):
  --sample-parallelism N    default: 1
  --dim-parallelism N       default: 4

Behavior (optional):
  --dry-run                 validate spec + load samples + preconditions only;
                            no API calls, no costs
  --skip-calibration        skip the calibration drift check at start-of-run
  --no-multimodal           force text-only judging (no PDF document blocks)
  --no-conversion           skip LibreOffice conversion entirely; only the
                            files that natively pass through (.pdf, .txt) are
                            sent to judges. Useful if LibreOffice is unavailable.
  --cache-dir PATH          override the default `~/.cache/gdpval-qc/` location

Progress output (optional):
  --quiet                   suppress per-dim progress lines
  --heartbeat-only          one heartbeat line every N seconds instead of per-call
  --heartbeat-seconds N     heartbeat interval (default: 10)
```

---

## Environment

| Variable | Required? | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | yes (for default spec) | gpt-5.5 judge + synthesizer |
| `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | yes (for default spec) | gemini-3.1-pro-preview judge |
| `ANTHROPIC_API_KEY` | only if you wire Claude in | claude judge |

Loaded from `.env` if present (via `python-dotenv`).

---

## Bundled sample data

`data/sample_corpus/task_11/` (~23 MB) — one real omega task. Run the
quick-start command above and you should see a `batch_review.json` with
`task_11` and (in most cases) a verdict of `accept` or
`accept_with_fixes`.

This is intentionally one task — enough to verify your setup end-to-end
without massive disk overhead. Point `--corpus` at your own data for real
runs.

---

## Tests

```bash
# Against the bundled single-task sample (137 tests pass, 6 skip):
pip install -e ".[test]"
pytest tests/ -q

# Against your full corpus (all tests run):
GDPVAL_TEST_CORPUS=/path/to/full/corpus pytest tests/ -q
```

The skipped tests are integration tests that assume a multi-task corpus
(e.g. asserting batch counts ≥ 3 or referencing specific task IDs).

---

## Project layout

```
gdpval_qc/                       # repo root
├── gdpval_qc/                   # Python package
│   ├── __init__.py              # public API
│   ├── finding.py               # DimensionFinding, Issue, JudgeAttempt
│   ├── review.py                # BatchReview, SampleReview, Verdict
│   ├── llm_client.py            # LLMClient protocol, content blocks
│   ├── openai_client.py         # GPT adapter (rate-limited at 20M tpm)
│   ├── gemini_client.py         # Gemini adapter (rate-limited at 2M tpm)
│   ├── mock_llm.py              # MockLLMClient for tests
│   ├── converters.py            # DocumentConverter (LibreOffice → PDF)
│   ├── precondition.py          # applies_when built-ins
│   ├── v18_spec.py              # spec parser + validator
│   ├── v18_loader.py            # corpus loader, default field bindings
│   ├── v18_judge.py             # prompt building, JSON parsing, ensemble
│   ├── v18_aggregate.py         # judge-attempt aggregation
│   ├── v18_callbacks.py         # 4 built-in programmatic checks
│   ├── v18_verifier_summary.py  # verifier_assertion_summary builder
│   ├── v18_verdict.py           # 5-tier verdict computation
│   ├── v18_synthesizer.py       # LLM-driven issue synthesis
│   ├── v18_emitter.py           # JSON / CSV / Markdown emitters
│   ├── v18_engine.py            # pipeline orchestrator
│   └── v18_calibration.py       # golden-set drift checking
│   └── cli.py                   # CLI entry point (`gdpval-assess`)
├── specs/
│   └── gdpval_task_quality_v18.md
├── data/
│   └── sample_corpus/task_11/   # bundled single-task sample (~23 MB)
├── tests/                       # pytest suite (137 tests)
├── runs/                        # gitignored — output directory target
├── pyproject.toml
└── README.md
```

---

## Versioning

The spec carries its own version (`18.5`) and a `cache_bust` integer.
Bump `cache_bust` whenever you edit the spec to force re-judging of
previously-cached samples. The framework version (this package) tracks
the spec major version.

---

## License

Proprietary — Turing internal use only. See `LICENSE`.
