# New QC Gates — Implementation Plan

**Context:** Requested by Mahesh Joshi based on issues found during live demo and batch review:
1. Input folder contamination — files like `Prompt.docx` appearing in `environment/` 
2. Synthetic generation markers — pipeline artifacts like `[TIE] Synthetic` leaking into source docs

**Status:** Planned. Do not implement while a QC run is in progress.

**Terms:** this plan is for the gdpval-qc tool described in `README.md` in this folder. "Dim" means one quality dimension, and `blocking`, `reject_at_severity`, severity 0 to 3 and `needs_review` are explained there. The plan changes the tool's code and spec; it asks nothing of a task author or QC person.

**Branch to create:** `feat/add-synthetic-leak-qc-gates` off `main` in `x-gdpval-enterprise-workflow`.

---

## Overview of changes

| # | Change | Kind | Files |
|---|--------|------|-------|
| 1 | New dim `input_prompt_leakage` | LLM dim | `v18_spec.py`, `specs/gdpval_task_quality_v18.md` |
| 2 | New dim `synthetic_marker_scan` | Deterministic callback | `v18_callbacks.py`, `v18_spec.py`, `specs/gdpval_task_quality_v18.md` |
| 3 | Update `input_file_authenticity` | Prompt edit | `specs/gdpval_task_quality_v18.md` only |

---

## Change 1 — `input_prompt_leakage` (new LLM dimension)

### What it checks

Whether any file in `environment/` is semantically equivalent to the instruction, or is a solution/reasoning artifact that leaked into the input folder. The classic failure mode: a `Prompt.docx` copy of the task instruction sitting next to the source documents the agent is supposed to work from.

### Design decisions

- **Gate:** `blocking`, `reject_at_severity: 2` — a leaked prompt is a structural contamination that cannot be fixed by editing; the file must be removed.
- **Family:** Task Structure (insert after `instruction_input_consistency`, before `self_containedness`)
- **applies_when:** Unconditional — runs on every task regardless of whether a solution or verifier is present.
- **On disagreement:** `review`
- **Inputs:** `instruction`, `input_files`

### Spec YAML block

Insert this block into `specs/gdpval_task_quality_v18.md` in the **Task Structure** section, after the `instruction_input_consistency` section:

```markdown
### input_prompt_leakage

```yaml
dimension_name: "Input Folder Prompt Leakage"
check_kind: llm
inputs: [instruction, input_files]
gate:
  role: blocking
  reject_at_severity: 2
  on_disagreement: review
```

**What this evaluates.** Whether any file in the input folder (`environment/`) is a copy
or near-duplicate of the task instruction, or is a solution/reasoning artifact (e.g. a
`Reasoning.docx`, a completed deliverable, or a grading rubric) that should not be
visible to the agent. This is a contamination check, not a consistency check — it is
asking whether the folder accidentally gives the agent the answer or the prompt itself.

**Severity rubric.**

- **Severity 0** — All input files are genuine source documents. No file is semantically
  equivalent to the instruction or contains information that would constitute a direct
  answer leak. The folder is clean.
- **Severity 1** — One file has minor overlap with the instruction (e.g. shares a
  sentence of boilerplate context) but is clearly a legitimate source document in its
  own right. The overlap does not materially help the agent bypass the task.
- **Severity 2** — One or more input files is a near-duplicate of the instruction, a
  copy of the task prompt, a completed solution deliverable, or a reasoning/justification
  document that reveals how the task should be solved. The contamination materially
  undermines the task's integrity as an evaluation item.
- **Severity 3** — The input folder contains the full prompt verbatim AND one or more
  solution artifacts, making the task entirely transparent to the agent.

**Common hard-fail patterns (sev 2).**

- A file named `Prompt.docx`, `prompt.md`, `instruction.docx`, `task.md`, or any
  filename that explicitly identifies the file as the task instruction.
- A file whose opening paragraph is identical or near-identical to the first paragraph
  of the instruction (copy-paste of the prompt into a Word doc).
- A file named `Reasoning.docx` or `Reasoning.pdf` in the input folder — this is the
  canonical name for the expert's solution reasoning and must only appear under
  `solution/golden_outputs/`.
- A completed deliverable (e.g. a finished memo, a completed financial model with
  specific conclusions) placed in the input folder alongside the raw source data.
- A rubric or scoring guide that lists the verifier criteria, placed in the input folder.

**Anti-overcall guidance.**

- Source documents that reference the same company, transaction, or scenario as the
  instruction are expected and must NOT be flagged — the instruction describes the
  task context, and the source docs naturally share that context.
- Partial thematic overlap (e.g. the instruction mentions "leverage ratio" and a
  source document is a credit agreement that discusses leverage) is not leakage.
- Files named `background.docx`, `context.pdf`, `briefing.md` are only suspicious if
  their *content* mirrors the instruction — the filename alone is not sufficient to flag.
- If a file looks like a legitimate professional document with genuine domain content,
  do not flag it simply because it was named generically.
- Evidence quote is required for any severity ≥ 1 finding. Quote the specific passage
  from the input file that is equivalent to instruction content.
```

### Where to insert in `v18_spec.py`

The spec parser reads dimension sections from the markdown — you do **not** need to touch `v18_spec.py` for LLM dims. The parser discovers dims from `### <dim_name>` headings in the markdown. Confirm by checking `V18Spec.from_markdown()` in `v18_spec.py` — it iterates `###` headings.

However, if you need to adjust dim ordering (the framework runs dims in spec order), insert the markdown section at the right position. The order in `specs/gdpval_task_quality_v18.md` controls execution order.

---

## Change 2 — `synthetic_marker_scan` (new deterministic callback)

### What it checks

Scans the raw text content of all input files for known synthetic pipeline marker patterns — bracket-style metadata tags like `[TIE] Synthetic`, `[SYNTHETIC]`, `[AI-GENERATED]` that indicate the task creation pipeline's labels leaked into the source documents.

### Design decisions

- **Gate:** `blocking`, `reject_at_severity: 2` — a single confirmed marker is egregious enough for a material finding. The tag cannot appear in a real professional document.
- **Family:** Programmatic Checks (alongside `verifier_spec_parseable` etc.)
- **applies_when:** Unconditional — scan inputs regardless of solution/verifier presence.
- **Fixability:** `fixable` — the file needs to be cleaned up, but the task itself is not necessarily broken.
- **Single hit threshold:** Yes. One confirmed marker = sev 2. There is no count threshold because a single `[TIE] Synthetic` in a real-looking source document is already a clear contamination signal.

### Callback implementation

Add this function to `gdpval_qc/v18_callbacks.py`:

```python
import re

# Maintained list of known synthetic pipeline markers.
# Add new patterns here as they are discovered in production.
_SYNTHETIC_MARKER_PATTERNS: list[re.Pattern] = [
    re.compile(r'\[TIE\]', re.IGNORECASE),
    re.compile(r'\[SYNTHETIC\]', re.IGNORECASE),
    re.compile(r'\[AI-GENERATED\]', re.IGNORECASE),
    re.compile(r'\[AI_GENERATED\]', re.IGNORECASE),
    re.compile(r'\[LLM-GENERATED\]', re.IGNORECASE),
    re.compile(r'\[LLM_GENERATED\]', re.IGNORECASE),
    re.compile(r'\[FABRICATED\]', re.IGNORECASE),
    re.compile(r'\[GENERATED\]', re.IGNORECASE),
    re.compile(r'\[OMEGA\]', re.IGNORECASE),
    re.compile(r'\[OMEGA-REBORN\]', re.IGNORECASE),
    # Bracket-style metadata tags with optional content: [TAG: value]
    re.compile(r'\[(?:TIE|SYNTHETIC|AI|LLM|FABRICATED|GENERATED|OMEGA)[^\]]*\]', re.IGNORECASE),
]


def check_synthetic_markers(sample: Sample, dim: V18Dimension) -> DimensionFinding:
    """Sev 2 if any input file contains a known synthetic pipeline marker."""
    input_files = sample.fields.get("input_files")
    if not input_files:
        return _ok(dim, headline="no input files to scan")

    hits: list[tuple[str, str, str]] = []  # (filename, pattern, matched_text)

    for file_obj in input_files:
        # file_obj is a FileContent object; access .text or .content for raw text.
        # The exact attribute depends on the FileContent dataclass in v18_loader.py —
        # check that file for the correct attribute name (likely .text or .content).
        filename = getattr(file_obj, 'filename', getattr(file_obj, 'name', 'unknown'))
        text = getattr(file_obj, 'text', getattr(file_obj, 'content', ''))
        if not text:
            continue
        for pattern in _SYNTHETIC_MARKER_PATTERNS:
            match = pattern.search(text)
            if match:
                hits.append((filename, pattern.pattern, match.group(0)))
                break  # one hit per file is enough

    if not hits:
        return _ok(dim)

    hit_count = len(hits)
    files_affected = ', '.join(h[0] for h in hits)
    first_match = hits[0][2]

    return _fail(
        dim,
        severity=2,
        headline=f"synthetic pipeline marker found in {hit_count} input file(s)",
        detail=(
            f"Found synthetic generation marker(s) in: {files_affected}. "
            f"First match: '{first_match}'. These bracket-style tags are artifacts "
            f"of the task creation pipeline and must not appear in source documents "
            f"presented to the agent. Remove or scrub the markers from the affected files."
        ),
        fixability="fixable",
    )
```

> **Important:** Before finalising, check `v18_loader.py` for the exact `FileContent` dataclass definition to confirm the attribute names for filename and text content. Look for a class or dataclass named `FileContent` or similar. The text attribute is likely `.text` or `.content`; the filename is likely `.name` or `.filename`.

### Registering the callback

Callbacks must be registered in the spec parser. In `v18_spec.py`, find the `CALLBACK_REGISTRY` dict (or equivalent — search for where `check_metadata_completeness` is registered). Add:

```python
"check_synthetic_markers": check_synthetic_markers,
```

Also add the import at the top of `v18_spec.py` or wherever the registry is populated.

### Spec YAML block

Insert this in `specs/gdpval_task_quality_v18.md` under the **Programmatic Checks** section:

```markdown
### synthetic_marker_scan

```yaml
dimension_name: "Synthetic Pipeline Marker Scan"
check_kind: programmatic
callback: check_synthetic_markers
inputs: [input_files]
gate:
  role: blocking
  reject_at_severity: 2
  on_disagreement: review
```

**What this evaluates.** Scans the text content of all input files for known synthetic
pipeline markers — bracket-style annotation tags (e.g. `[TIE] Synthetic`,
`[SYNTHETIC]`, `[AI-GENERATED]`) that indicate the task creation tooling's metadata
leaked into the source documents presented to the agent.

This is a deterministic check. A single confirmed marker in any input file produces a
severity-2 finding. There is no count threshold — any confirmed marker in a real-looking
professional document is an unambiguous contamination signal.

**Pass:** No known synthetic markers found in any input file.

**Severity 2:** One or more input files contain a recognised synthetic pipeline marker.
`fixability: fixable` — the file must be cleaned up (marker removed or file regenerated),
but the task itself may be salvageable.

**Marker pattern list** (maintained in `v18_callbacks.py → _SYNTHETIC_MARKER_PATTERNS`):

- `[TIE]`, `[TIE: ...]`
- `[SYNTHETIC]`
- `[AI-GENERATED]`, `[AI_GENERATED]`
- `[LLM-GENERATED]`, `[LLM_GENERATED]`
- `[FABRICATED]`
- `[GENERATED]`
- `[OMEGA]`, `[OMEGA-REBORN]`
- Any `[TAG: value]` pattern matching the above prefixes

To extend the pattern list as new markers are discovered, add to
`_SYNTHETIC_MARKER_PATTERNS` in `v18_callbacks.py`. No spec file changes needed.
```

---

## Change 3 — Update `input_file_authenticity` prompt

### What to add

The existing `input_file_authenticity` dimension already catches holistic synthetic feel. The prompt update adds explicit guidance for the nuanced cases the deterministic scan cannot catch: partially-scrubbed markers, pipeline metadata embedded in document properties, and automated-tooling artifacts in tracked changes.

### Where

In `specs/gdpval_task_quality_v18.md`, find the `### input_file_authenticity` section. Locate the **Common hard-fail patterns** block and append the following items:

```markdown
- **Partially-scrubbed pipeline markers.** Residual bracket-style tags that were
  imperfectly removed — e.g. a document containing `TIE Synthetic` (brackets stripped)
  or `[TIE]` where only the content was deleted. Quote the residual pattern as evidence.
- **Pipeline metadata in document metadata fields.** Properties like Author = "omega-reborn"
  or Creator = "gdpval-task-generator" visible in document metadata (these may appear in
  extracted text as a header block). Quote the relevant field.
- **Automated-tooling artifacts in tracked changes.** Revision history showing a
  non-human author (e.g. a script name, a bot account) making the initial draft, with
  human edits applied on top. This pattern indicates the document was generated then
  lightly edited, not originally authored.
- **Uniform generation fingerprints across supposedly independent documents.** All
  files in the input folder sharing the same creation timestamp to the second, identical
  document metadata, or identical internal structure despite coming from "different"
  organisations — consistent with batch generation by a single pipeline run.
```

Also add to the **Anti-overcall** block:

```markdown
- Do not flag bracket notation used in legitimate professional documents (e.g.
  `[Exhibit A]`, `[redacted]`, `[sic]`, `[citation needed]`). The synthetic markers
  are specifically LLM-pipeline tags — they appear at the start of paragraphs or as
  standalone labels, not as standard document annotation conventions.
```

---

## Testing plan

### Step 1 — Dry run
```bash
gdpval-assess --spec specs/gdpval_task_quality_v18.md \
  --corpus ~/Claude/Projects/EKW-GDPVal/x-gdpval/corpus/ \
  --dry-run
```
Confirms the spec loads cleanly with the new dims and no parse errors.

### Step 2 — Smoke test on 3 known-clean tasks
```bash
gdpval-assess --spec specs/gdpval_task_quality_v18.md \
  --corpus ~/Claude/Projects/EKW-GDPVal/x-gdpval/corpus/ \
  --tasks task_2,task_7,task_31 \
  --output-dir /tmp/smoke_test/
```
All three should pass `input_prompt_leakage` and `synthetic_marker_scan` at sev 0 since these are clean tasks. If either fires, check for false positives in the prompt or pattern list.

### Step 3 — Validate on known-bad task
If a task with a known `Prompt.docx` or `[TIE]` marker is available in the corpus, run it in isolation and confirm the correct finding fires at sev 2 with a valid evidence quote.

### Step 4 — Full batch
Once smoke test passes, run on the full 60-task corpus and review the new dim findings in `reviewer_queue.csv`.

---

## File change summary

```
specs/gdpval_task_quality_v18.md
  + Add ### input_prompt_leakage section (Task Structure family)
  + Add ### synthetic_marker_scan section (Programmatic Checks family)
  ~ Update ### input_file_authenticity hard-fail patterns + anti-overcall

gdpval_qc/v18_callbacks.py
  + Add _SYNTHETIC_MARKER_PATTERNS list
  + Add check_synthetic_markers() function

gdpval_qc/v18_spec.py
  + Register check_synthetic_markers in CALLBACK_REGISTRY
    (search for check_metadata_completeness to find the right location)
```

No changes needed to: `v18_engine.py`, `v18_judge.py`, `v18_aggregate.py`, `v18_verdict.py`, `v18_loader.py`, `cli.py`.

---

## Open questions (resolve before implementing)

1. **Scope of `synthetic_marker_scan`** — inputs only, or also solution files? Current plan: inputs only. Solution file markers would be a different problem (solution authenticity) and are partially covered by `solution_substantiveness`. Revisit if markers are found in solution files in practice.

2. **`input_prompt_leakage` reject threshold** — currently `reject_at_severity: 2`. If judges prove overcallers on this dim during the smoke test, consider loosening to `reject_at_severity: 3` and keeping `blocking` so it still flows to `accept_with_fixes`.

3. **FileContent attribute names** — verify `.text`/`.content` and `.name`/`.filename` in `v18_loader.py` before finalising callback code.
