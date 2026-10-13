Status: stale. The [QC SOP](../../docs/QC-SOP-first-run.md) (sections 6a to 7) replaces it; there a task fails if any of the four Answer Check reviews has a major. Do not follow its commands.

# SVC-PC one-shot fix guide — pass Comprehensive Review on the first DataOS upload

Written for teammates fixing SVC-PC harbor tasks with Claude Code. It is self-contained: the
acceptance bar, machine and Claude setup, the anatomy of a task, the fix loop, every file template,
the concrete edit recipes (xlsx / pptx / TOML / prompts), the recurring root causes with the fix that
closed each, the packaging script, the exact fixer and reviewer prompts, and the task-doc template.
It was distilled from taking SVC-PC-62-6-0, SVC-PC-68-8-0 and SVC-PC-68-1-0 from `reject` to
zero-major on every independent review.

Companion docs in this repo (the prompts below reference them by path — teammates need the repo):

- [`svc-pc-fix-playbook.md`](svc-pc-fix-playbook.md) — mechanics of a fix (genres, xlsx gotchas §4, corpus conventions §7).
- [`ekw-svc-comprehensive-review.md`](ekw-svc-comprehensive-review.md) — the exact review prompt DataOS runs.

In this guide "the review spec", "review §4" and "review §5" mean that file's numbered sections, and
"1.1" to "1.10" are its check ids.

---

## 0. The bar you are aiming at

| Gate | Requirement | How it is measured |
|---|---|---|
| DataOS pipeline reviews | A task is sent back if **any** of the four Answer Check reviews (the reviews of the DataOS pipeline "ManualQC automated QC pipeline 4 Reviewers", version 8) reports a major; it passes only when all four are clean | A review verdict of `reject` or `invalid` means that review found a major; `accept` or `needs_revision` means it found none. Read each review with a major and fix it if it is real. The manager denies only for correctness or fairness; hygiene findings are optional fixes. See [`task-review-rules-v2.md`](../../docs/task-review-rules-v2.md) and [QC SOP, section 6b](../../docs/QC-SOP-first-run.md#6b-the-dataos-pipeline). |
| Oracle runs | **All** pass | Golden copied by `solve.sh` into `/app`, graded by `tests/test.sh`, reward ≈ 1.0, no infra error. |

The local loop in section 3 asks for three clean local reviews, which is stricter than the pipeline rule on
purpose: local reviewers tend to rate as minor what DataOS rates as major.

A **major** (review §4) is: the golden fails a criterion it should pass (**false rejection**), a wrong
answer passes a criterion (**false credit**), a rubric pins a value the sources contradict, an
infrastructure defect breaks the run, or answers leak into the workspace. Everything else is minor —
but minors keep the verdict at `needs_revision` forever, so **we fix them all**.

Why a real review is strict: DataOS reviewers **recompute your numbers from the source files**, grep
every filename you cite, run your test harness, and build exploit workbooks against your programmatic
checks. Your local review must do the same or it predicts nothing.

DataOS UI note: the "N Passed" tile counts **top-level reward groups** (`deliverables_01`,
`deliverables_02`), not criteria. Two groups → "2 Passed".

---

## 1. One-time setup (≈ 20 min)

### 1.1 Machine

```bash
git clone https://github.com/turing-genai-apps/EKW_QC_pipeline.git
cd EKW_QC_pipeline
python -m venv .venv && .venv/Scripts/activate          # Python 3.11+ (3.14 in use here)
pip install openpyxl==3.1.5 python-docx python-pptx pdfplumber pandas \
            'formulas==1.3.4' 'schedula==1.6.15' markitdown
# the exact grader the tasks pin — keep its source next to you for probing
pip download 'harbor-rewardkit==0.2.0' --no-deps -d /tmp/rk && mkdir -p /tmp/rk/extracted \
  && unzip -q /tmp/rk/harbor_rewardkit-0.2.0-*.whl -d /tmp/rk/extracted
# you will import: /tmp/rk/extracted/rewardkit/{runner.py, reward.py, judges.py}
```

Windows-specific, non-negotiable:

- `export PYTHONUTF8=1` in every shell (PowerShell: `$env:PYTHONUTF8=1`). Without it any script
  that prints an em-dash, emoji or `Δ` dies with `UnicodeEncodeError` under cp1252.
- **Never write task text files in text mode.** `open(p,'w')` rewrites `\n` → `\r\n`. A `\r` inside
  `tests/test.sh` makes harbor write `reward.json` to `/logs/verifier\r/` and **every** oracle run
  dies with `RewardFileNotFoundError`. Use `open(p,'w',newline='\n')` or binary writes, and assert no
  `\r` before packaging (§7).
- LibreOffice and pandoc are usually absent. Read `.docx`/`.pptx` with python-docx/python-pptx, not
  `pandoc`; skip visual renders; never report "conversion failed" banners as task defects.

### 1.2 Claude Code

`.claude/settings.json` in the repo already whitelists the Python invocations the workflow uses
(`Bash(PYTHONUTF8=1 python -c ' *)` and venv equivalents). Add for your own paths when prompted;
never blanket-allow `rm -rf`.

Put this in your **project CLAUDE.md** so it applies to every session:

```markdown
## SVC-PC fixing rules
- Acceptance: the DataOS pipeline rule is met (none of the four Answer Check reviews reports a major) AND all oracle runs pass. Locally, fix every major AND minor.
- Never trust the fixer's self-review. After every fix round, run 3 independent cold-start reviews
  (general-purpose subagents, background, in parallel) against a FRESH extraction of the zip, using
  docs/ekw-svc-comprehensive-review.md verbatim. Loop until 3/3 report 0 majors and no residual minors.
- instruction.md and tests/task_prompt.txt ship byte-identical; edit both; assert sha256 equal.
- Windows: PYTHONUTF8=1 always; write files with newline='\n'; assert b'\r' not in any .sh/.toml/.md/.txt/.py.
- xlsx: wb.save() wipes formula caches -> re-inject <v> or patch sheet XML inside the zip. Verify
  data_only=True shows 0 empty caches before packaging.
- Every number typed into a golden or a criterion must be recomputed from environment/initial_workspace.
- Corpus conventions NOT to "fix": task.toml domain/occupation/sector/subdomain/task_type absent;
  15-20 MB environment size; private Docker base image.
- Pinned grader: harbor-rewardkit==0.2.0, source at <your /tmp/rk/extracted/rewardkit>.
```

If you use Claude's auto-memory, copy the seeds in Appendix C into
`~/.claude/projects/<project>/memory/` (one file each, plus a line in `MEMORY.md`).

### 1.3 Anatomy of a rewardkit-hybrid task (what every file is, and which you may touch)

```
SVC-PC-68-1-0/
├── task.toml                      # name, [metadata] category+tags(+description, difficulty), timeouts, env
├── instruction.md                 # the prompt (human/review-facing copy)      ← edit together with ↓
├── environment/
│   ├── Dockerfile                 # FROM private base image; pip pins; COPY initial_workspace/ /app/  (don't touch)
│   └── initial_workspace/         # the evidence room the agent sees at /app (~290 files, 15-20 MB)  (never edit)
├── solution/
│   ├── solve.sh                   # cp -a /solution/files/. /app/        (oracle = this + tests/)
│   └── files/<Deliverable>.xlsx   # the golden                          ← edit with the recipes in §5
└── tests/
    ├── task_prompt.txt            # the prompt the AGENT receives; byte-identical to instruction.md ← edit together
    ├── test.sh                    # pip install harbor-rewardkit==0.2.0; pre-steps; rewardkit /tests
    ├── reward.toml                # [[reward]] aggregation + [reward.weights] per group
    ├── recalc_xlsx.py             # optional pre-grade step: fill empty formula caches (xlsx tasks)
    ├── deliverables_01/
    │   ├── judge.toml             # [judge] model/files/weight + [[criterion]] list  (may be split: must_pass.toml + quality.toml)
    │   ├── formula_check.py       # optional programmatic criteria (@criterion)  → "$checks" input
    │   └── reward.toml            # weight of the $checks bucket + [scoring] aggregation
    └── deliverables_02/judge.toml
```

Genre tell (playbook §0): `Dockerfile` ends with `COPY initial_workspace/ /app/`, there is no
`verifier_runtime.py`, and `tests/test.sh` pip-installs `harbor-rewardkit`. Other genres exist; this
guide's recipes are for this one, the loop (§3) applies to all.

---

## 2. Intake (per task, ≈ 5 min)

1. `mkdir staged_<task>_fix/` and extract the task zip into it → `staged_<task>_fix/<TASK-ID>/`.
2. Save the DataOS review JSON beside it. Its shape is a list of reviews, each ending in the review
   spec's §5 object: `overall_verdict`, `summary`, `major_count`, `minor_count`, `checks[]` with
   `id (1.1–1.10)`, `result`, `severity`, `evidence_status`, `justification`, `suggested_fix`.
3. Ask Claude to **table every finding from all reviews** (review#, check id, severity, claim,
   file/cell, suggested fix) **before it touches anything**. Reviews disagree with each other; the
   table is what gets verified in §3A.
4. Read yourself, in this order: `instruction.md` → every `judge.toml` → the golden → `tests/test.sh`
   → root `tests/reward.toml`. You need this to judge the subagents' claims later.
5. Take an inventory the fixer will reuse: deliverable filename(s) and their `/app/...` paths in
   `[judge].files`, criterion ids and weights per group, all filenames the golden cites.

---

## 3. The loop (this is what makes it one-shot)

```
 A. Verify every finding  →  B. Fix (1 fixer subagent,  →  C. 3 independent cold-start reviews
    against real files          plan approved by you)         (parallel, on a FRESH zip extraction)
                 ▲                                                        │
                 └──────────── D. consolidate residuals ◄─────────────────┘
                     until 3/3 → 0 major, 0 unrefuted minor   →   E. package (§7)  →  F. upload
```

Typical convergence: **2–4 rounds**. Budget 2–4 hours wall-clock per task; do not believe "5 minutes".

### A. Verify every finding against the real files

For each finding the fixer produces: file, cell/line, actual value, and `confirmed / refuted /
partial`. Any disputed number is **recomputed from `environment/initial_workspace/` with
openpyxl/csv**, never read from golden prose. Refuted items are dropped **with the evidence written
down** — a later reviewer will raise the same thing.

### B. Fix — one fixer subagent, plan first

Spawn **one** `general-purpose` subagent with the fixer prompt (Appendix A). Require a **plan**
(root cause → fix → proof) before editing; approve or amend; then let it apply. Rules:

- Fix the **root cause**, not the symptom.
- **Never lower difficulty** to make a criterion pass (review "Protect difficulty").
- Every numeric change is recomputed from sources.
- Edit `instruction.md` **and** `tests/task_prompt.txt` identically.
- Prove: golden passes every criterion by hand-grading (§5.6); TOML parses; weights sum; rewardkit
  discovery/scoring probe (§6) shows the intended arithmetic; caches intact; no `\r`.

### C. Three independent cold-start reviews — parallel, on a fresh extraction

The fixer grading its own work is not a review; it knows what it intended.

1. Package the zip (§7), extract it to a **separate** directory `review_check/<TASK-ID>/`. Reviewers
   must see exactly what DataOS sees — not your working tree with `__pycache__`, scratch scripts or a
   half-saved workbook.
2. Launch **three** `general-purpose` subagents, `run_in_background: true`, **in one message**, with
   the reviewer prompt (Appendix B). Same prompt for all three; independence comes from separate
   contexts.
3. Each executes `docs/ekw-svc-comprehensive-review.md` verbatim and ends with the §5 JSON.
4. Tally verdicts, `major_count`, `minor_count`, and **root causes** (two reviewers describing one
   defect differently is one item).

### D. Consolidate and go again

Hand the fixer the union of confirmed residuals with the reviewers' exact evidence. Round-2 fixers
regularly **introduce** defects (cited-but-unregistered file, grader language leaking into the
golden, incomplete terminology sweep after a rename). Loop until a whole round comes back clean.

**Stop condition:** 3/3 reviews with `major_count = 0` and every minor fixed or refuted with evidence.
If you ship with an unfixed minor, write it into the task doc (§8).

---

## 4. File templates (verbatim from shipped, review-passing tasks)

### 4.1 `tests/reward.toml` — cross-group weights (works in rewardkit 0.2.0)

```toml
[[reward]]
name = "reward"
aggregation = "weighted_mean"

[reward.weights]
deliverables_01 = 0.88
deliverables_02 = 0.12
```

Without `[reward.weights]` groups are averaged 1:1 regardless of their declared weights.

### 4.2 `tests/deliverables_XX/judge.toml` — header and criterion pattern

```toml
[judge]
judge = "anthropic/claude-sonnet-4-6"
files = ["/app/FPA_Quality_of_Earnings_and_EBITDA_Bridge_Model.xlsx"]   # what the judge reads; must match solve.sh output
weight = 0.80                                                          # this file's share of the group

[[criterion]]
name = "r003"
description = '''<What it grades, one sentence>. Expected: <exact figure(s) with signs and units,
recomputed from the sources>; also accepted: (a) <alternative treatment> giving <its implied total>,
(b) ... — provided the same treatment is carried through <the other tabs/criteria that depend on it>.
FAIL if <specific, observable failure conditions>. <If the extraction can't see something — formulas,
images, number formats — say so and grade only what is visible.>'''
type = "binary"
weight = 0.07

[scoring]
aggregation = "weighted_mean"
```

Criterion rules that survived review:

- **One fact per criterion.** Two independent facts → split (`r002a`, `r002b`). If a criterion must
  bundle sub-checks, state the partial-credit rule ("3 of 4 passes").
- **Pin numbers only after recomputing them** from `initial_workspace/`, with sign and rounding.
- **Enumerate legitimate alternatives with their implied totals** (e.g. bridge −970,186; or −945,186
  if the BrightMark SOW is added back; or −946,186 without the 8% burden …) and require consistency
  across tabs. Every *other* criterion that pins a dependent number (run-rate, runway, disposition)
  must accept the matching alternative.
- **Never grade what the judge cannot see**: formulas, images, chart XML, number formats, freeze
  panes. Either grade it programmatically (§4.4) or say explicitly it is not graded. Never penalise a
  chart's implementation choice (bitmap vs native) — a real eval rejected a legitimate image chart.
- **No positional requirements** ("near the top") — extractors reorder tables to the end.
- **Weights per group sum exactly** to the group's share; per-deliverable weight should reflect how
  much of the instruction that deliverable carries.
- "Must-pass" **prose has no mechanical effect**. To gate, use `required_pass`:

```toml
# tests/deliverables_01/must_pass.toml  (sibling quality.toml holds the rest with weighted_mean)
[judge]
judge = "anthropic/claude-sonnet-4-6"
files = ["/app/Executive_Normalized_Earnings_Review.pptx", "/app/_corpus_subtree/.../FY2021_Quality_of_Earnings_Report.docx"]
weight = 0.80
[[criterion]]  # ... core criteria r001, r002a, r002b, r003, r004, r005, r011
[scoring]
aggregation = "required_pass"
```

`required_pass` zeroes **only its own group**; the floor is set by sibling weights (0.80 / 0.08 /
0.12 → a core failure caps reward at 0.20). Reweight siblings accordingly.

### 4.3 `tests/deliverables_XX/reward.toml` — programmatic bucket weight

```toml
weight = 0.08            # reward weight of the "$checks" input (all .py criteria in this dir)
[scoring]
aggregation = "weighted_mean"
```

Judge weight 0.80 + checks 0.08 = 0.88 = the group's `[reward.weights]` entry.

### 4.4 `tests/deliverables_XX/<name>_check.py` — programmatic criterion skeleton

```python
from pathlib import Path
from rewardkit import criterion        # rewardkit imports every .py in this dir at discovery time

DELIVERABLE = "FPA_Quality_of_Earnings_and_EBITDA_Bridge_Model.xlsx"

def _score(workspace: Path) -> float:
    import openpyxl                    # import inside: a missing dep must score 0.0, not crash discovery
    path = Path(workspace) / DELIVERABLE
    if not path.is_file():
        return 0.0
    wb = openpyxl.load_workbook(path, data_only=False)
    results = {}                       # name -> bool; locate cells by ROW LABEL regex, never fixed addresses
    ...
    return sum(1.0 for v in results.values() if v) / len(results)

@criterion(description="Load-bearing summary cells are live formulas, not hard-keyed literals")
def formula_authenticity(workspace: Path) -> float:
    try:
        return _score(workspace)
    except Exception as e:             # never let a grading bug zero the whole run
        print(f"check: unexpected error {e!r}; scoring 0.0")
        return 0.0
```

Hardening that the reviewers demanded (see `staged_svc68_1_fix/.../formula_check.py` for the full
implementation): a formula counts as "live" only if it contains a cell reference **and** is not a
bare `=Sheet!A1` pointing (transitively) at a typed literal; PASS/FAIL verdict formulas count only if
at least one referenced cell is itself a live formula; label regexes tolerate layout variants
(`Difference (GL - TB)`); items the instruction doesn't literally require are skipped when absent, not
failed. **Always test**: golden → 1.0; all formulas replaced by cached values → 0.0; every formula
replaced by `=<literal>` → 0.0; every formula replaced by `=Inputs!A{n}` → 0.0; relabelled golden → 1.0.

### 4.5 `tests/test.sh` — the five blocks it must have

```bash
#!/bin/bash
export LITELLM_DROP_PARAMS=true
VERIFIER_DIR="${VERIFIER_DIR:-/logs/verifier}"; mkdir -p "$VERIFIER_DIR"
TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DELIVERABLE="/app/<Deliverable>.xlsx"

write_infra_failure() {            # rewardkit writes NOTHING on failure; harbor needs a numeric reward.json
  echo "$1" >> "$VERIFIER_DIR/runtime.log"
  echo "0.0" > "$VERIFIER_DIR/reward.txt"; echo '{"reward": 0.0}' > "$VERIFIER_DIR/reward.json"
}
# 1. pinned grader
pip install --quiet 'harbor-rewardkit[all]==0.2.0' || { write_infra_failure "pip install failed"; exit 1; }
python3 -c "import openpyxl" 2>/dev/null || pip install --quiet openpyxl
# 2. (xlsx tasks) fill EMPTY formula caches so a solver's openpyxl-written workbook is gradable
if [ -f "$DELIVERABLE" ] && pip install --quiet 'formulas==1.3.4' 'schedula==1.6.15'; then
  timeout 900 python3 "$TESTS_DIR/recalc_xlsx.py" "$DELIVERABLE" 2>&1 | grep -v 'it/s' | tee -a "$VERIFIER_DIR/runtime.log"
fi
# 3. judge skips files > 1 MB silently -> warn
[ -f "$DELIVERABLE" ] && [ "$(wc -c < "$DELIVERABLE" | tr -d ' ')" -gt 1000000 ] && echo "WARN: deliverable > 1 MB; judge will skip it" | tee -a "$VERIFIER_DIR/runtime.log"
# 4. grade
rewardkit /tests --output "$VERIFIER_DIR/reward.json" 2>&1 | tee -a "$VERIFIER_DIR/runtime.log"
RC=${PIPESTATUS[0]}
# 5. never leave harbor without a numeric reward.json
[ -s "$VERIFIER_DIR/reward.json" ] || { write_infra_failure "rewardkit exited $RC, no reward.json"; exit 1; }
exit "$RC"
```

`reward.json` values must be **numeric only** (harbor validates with pydantic); messages go to
`runtime.log`. The full shipped version with comments is `staged_svc68_1_fix/SVC-PC-68-1-0/tests/test.sh`;
`recalc_xlsx.py` next to it is reusable as-is (fills only empty caches, works on a scratch copy, exits
0 on any failure).

### 4.6 `task.toml`

```toml
schema_version = "1.1"

[task]
name = "svc/svc-pc-68-1-0"
description = "<one line: what the solver builds from what>"        # add if missing

[metadata]
category = "SVC-PC"
tags = ["fp&a", "quality-of-earnings", "ebitda-bridge", "financial-modeling", "excel"]
difficulty = "hard"                                                 # add if missing
# domain / occupation / sector / subdomain / task_type: NOT recognised at this schema — leave absent

[agent]
timeout_sec = 14400.0
[verifier]
timeout_sec = 3600.0
[verifier.env]
ANTHROPIC_API_KEY = "${ANTHROPIC_API_KEY}"
[environment]
os = "linux"
cpus = 2
memory_mb = 4096
allow_internet = true
```

### 4.7 `solution/solve.sh` and `environment/Dockerfile` — don't change

```bash
#!/bin/bash
set -euo pipefail
mkdir -p /app
cp -a /solution/files/. /app/
```

The Dockerfile pulls a private base image (`us-central1-docker.pkg.dev/...`), pins pandas / openpyxl
3.1.5 / python-pptx / python-docx / pdfplumber etc., and ends with `COPY initial_workspace/ /app/`.
You cannot build it locally; nothing in the loop requires it.

---

## 5. Edit recipes

### 5.1 Golden xlsx — change text without wiping formula caches

`wb.save()` strips **every** cached `<v>` in the workbook. For text-only edits, patch the XML inside
the zip instead:

```python
import zipfile, shutil, openpyxl
p, old, new = "solution/files/X.xlsx", "Every assumption: basis, ..., management-decision flag.", "Every assumption: value, basis, source file and record, Fact/Computed/Judgment label."
z = zipfile.ZipFile(p); names = z.namelist()
hits = [n for n in names if old.encode() in z.read(n)]          # xl/sharedStrings.xml or xl/worksheets/sheetN.xml
assert len(hits) == 1 and z.read(hits[0]).count(old.encode()) == 1
with zipfile.ZipFile(p + ".tmp", "w", zipfile.ZIP_DEFLATED) as out:
    for n in names:
        d = z.read(n); out.writestr(z.getinfo(n), d.replace(old.encode(), new.encode()) if n in hits else d)
z.close(); shutil.move(p + ".tmp", p)
wf, wv = openpyxl.load_workbook(p), openpyxl.load_workbook(p, data_only=True)
assert not [c.coordinate for ws in wf.worksheets for r in ws.iter_rows() for c in r
            if c.data_type == "f" and wv[ws.title][c.coordinate].value in (None, "")]
```

Escape XML special characters (`&`, `<`, `>`) in `new` if present.

### 5.2 Golden xlsx — structural/formula edits (you must `wb.save()`)

1. Edit with openpyxl and save (caches now empty).
2. Restore caches either with the task's own `tests/recalc_xlsx.py <file>` (formulas engine; verify
   afterwards that every restored value equals your independent recompute), or by injecting values
   you computed in Python into the sheet XML (playbook §4.2 recipe: regex
   `(<c r="C33"[^>]*)(>)(<f>.*?</f>)<v></v></c>` → fill `<v>`; add `t="str"` for text results).
3. After a **row insert/delete**, recompute every subtotal independently — openpyxl does **not**
   shift references in formulas (`=C6+C12` kept pointing at the old row on 68-1-0).
4. Known engine quirk: `formulas` mis-evaluates `--ISERROR(range)`; write `SUMPRODUCT(ISERROR(range)+0)`.
5. Re-verify: `data_only=True` → 0 empty caches, no `#REF!`/`#VALUE!`; `data_only=False` → formulas
   intact; `zipfile.testzip()` None; file < 1 MB.

### 5.3 Golden xlsx — sweeps the reviewers always run (run them first)

```python
import re, openpyxl, os
wb = openpyxl.load_workbook(p)
# a) every cited filename exists and is in the register
cited = {m for ws in wb.worksheets for r in ws.iter_rows() for c in r if isinstance(c.value, str)
         for m in re.findall(r"[\w\-\. &()]+\.(?:xlsx|csv|docx|pptx|pdf|doc|txt)", c.value)}
missing = [f for f in cited if not any(f == n for _, _, fs in os.walk("environment/initial_workspace") for n in fs)]
# b) self-descriptions: tab index vs wb.sheetnames, "N checks" vs check rows, "N files" vs register rows
# c) label consistency: same item -> same Fact/Computed/Judgment label on every tab; stage labels
#    (Reported / Interim / Adjusted EBITDA) never swapped between tabs
# d) grader language: grep golden text for criterion|rubric|judge|must-pass|PASS if|FAIL if
# e) no formula embeds a >=4-digit literal (hidden hard-key): re.search(r"(?<![A-Z$])\d{4,}", f)
```

### 5.4 Golden pptx (deck tasks)

```python
from pptx import Presentation
prs = Presentation(p)
for i, s in enumerate(prs.slides, 1):
    for sh in s.shapes:
        if sh.has_text_frame: ...           # add "Source: <exact filename>" lines beside material figures
        if sh.has_chart:                    # fix chart data (68-8-0: a −31,147 segment had the wrong sign)
            ch = sh.chart; ...              # use chart.replace_data(CategoryChartData) to rewrite values
prs.save(p)                                 # pptx has no cache problem; re-read text to verify
```

Cite exact delivered filenames **on the slides that carry the claims**, not only on a sources slide —
the citation criterion was passing on hallucinated judge reasoning until the slides carried them.

### 5.5 Prompt edits — both files, always

```python
import hashlib
for f in ("instruction.md", "tests/task_prompt.txt"):
    s = open(f, "rb").read().decode(); s = s.replace(OLD, NEW); open(f, "wb").write(s.encode())
assert hashlib.sha256(open("instruction.md","rb").read()).digest() == hashlib.sha256(open("tests/task_prompt.txt","rb").read()).digest()
```

### 5.6 Hand-grading the golden against every criterion

For each `[[criterion]]`: extract the golden the way the judge does (`markitdown` or
`pandas.read_excel(engine="openpyxl")` for every sheet; python-pptx text for decks), then check every
"Expected" figure/label appears **in that extraction** with the stated sign and rounding, and no
"FAIL if" clause fires. Record `criterion → evidence location`. Any criterion the golden fails is a
**major** until fixed. Also grade one **alternative-treatment** variant of the golden through every
criterion that pins a dependent number, to prove the alternatives are accepted consistently.

### 5.7 Weight arithmetic

Per group: criterion weights sum to `[judge].weight`; `[judge].weight + checks weight = [reward.weights]`
entry; entries sum to 1.0. Then probe (§6).

---

## 6. harbor-rewardkit 0.2.0 facts and the probe

- `runner._discover_layout(tests_dir, workspace)` → one group per `tests/deliverables_XX/`; inputs are
  `judge` (each `*.toml` with `[[criterion]]`) and `$checks` (every `.py` exposing `@criterion`
  functions `f(workspace: Path) -> float`). Root-level `.py` files (e.g. `recalc_xlsx.py`) are
  imported harmlessly as long as they register no criteria.
- `reward.aggregate_scores` supports `weighted_mean | all_pass | any_pass | threshold | required_pass`.
- `Criterion.optional` exists; description prose has no scoring semantics.
- Judge reads xlsx/pptx via markitdown → **cached values and text only**, 1 MB cap per file, ~90k chars
  per file (a rubric grading the last sheet of a huge workbook can be starved).

```python
import sys; sys.path.insert(0, "/tmp/rk/extracted")
from pathlib import Path
from rewardkit import runner
lay = runner._discover_layout(Path("tests"), Path("solution/files"))
for g in lay.groups: print(g.name, [(i.kind, i.weight) for i in g.inputs])
# then feed synthetic per-criterion pass/fail into runner._score_layout and confirm:
# all pass -> 1.0 ; d01 pass + d02 fail -> 0.88 ; d01 fail + d02 pass -> 0.12 ; core fail under required_pass -> floor
```

(Attribute names may differ slightly; read `runner.py` once — it is short.)

---

## 7. Packaging checklist — script it, run it every round

```python
import zipfile, os, hashlib, glob, tomllib, openpyxl
T = "SVC-PC-XX-Y-Z"
# 1 prompt files identical
h = lambda f: hashlib.sha256(open(f, "rb").read()).digest()
assert h(f"{T}/instruction.md") == h(f"{T}/tests/task_prompt.txt")
# 2 no CR anywhere it matters
for p in glob.glob(f"{T}/**/*", recursive=True):
    if os.path.isfile(p) and (p.endswith((".sh", ".toml", ".md", ".txt", ".py")) or p.endswith("Dockerfile")) \
       and "initial_workspace" not in p:
        assert b"\r" not in open(p, "rb").read(), p
# 3 TOML parses; weights sum
for f in glob.glob(f"{T}/tests/**/*.toml", recursive=True):
    d = tomllib.load(open(f, "rb")); print(f, round(sum(c["weight"] for c in d.get("criterion", [])), 4))
# 4 xlsx caches complete, size under judge cap
for x in glob.glob(f"{T}/solution/files/*.xlsx"):
    wf, wv = openpyxl.load_workbook(x), openpyxl.load_workbook(x, data_only=True)
    empty = [(ws.title, c.coordinate) for ws in wf.worksheets for r in ws.iter_rows() for c in r
             if c.data_type == "f" and wv[ws.title][c.coordinate].value in (None, "")]
    assert not empty, empty[:5]; assert os.path.getsize(x) < 1_000_000
# 5 zip without junk
out = f"{T}_final.zip"; os.path.exists(out) and os.remove(out)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for dp, dn, fn in os.walk(T):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if not f.endswith((".pyc", ".tmp")): z.write(os.path.join(dp, f))
z = zipfile.ZipFile(out); assert z.testzip() is None; print(len(z.namelist()), "entries OK")
```

Then extract that zip to `review_check/` and point the reviewers at it (§3C). Ship the zip only after
a clean review round on **that** extraction.

---

## 8. After upload, and the task doc

- Re-run the DataOS Comprehensive Review and the oracle. If any review still returns `reject`, pull the
  JSON and restart at §3A — never patch from memory.
- Write the task doc (`scratch/GoogleDoc_<TASK-ID>.docx`, generated with `scratch/docgen/gen.js`,
  `npm install docx` once). Sections, in order:
  1. Title `<TASK-ID> — Dataset Description`; Team; Dataset name; Data OS link.
  2. Purpose and use case (what the solver builds, from what, graded how — groups/criteria/genre).
  3. Scope (1 task; deliverable filename).
  4. Dataset structure and key metadata (`environment/initial_workspace/`, `solution/files/`, `tests/…`
     with criterion counts and weights, pins).
  5. Expected outputs (what a passing deliverable contains).
  6. Known limitations / review notes: golden fixes made, rubric calibration fixes, corpus conventions
     left as-is, verification history (real review verdicts before/after, local review round results,
     "live re-upload is the authoritative confirmation").
  7. Final packaged zip name. 8. Contact person.

---

## 9. Recurring root causes (found in ≥ 1 of the 3 tasks) and the fix that closed each

| # | Symptom in the review | Root cause | Fix that closed it |
|---|---|---|---|
| 1 | Citation criterion passes on hallucinated judge reasoning; golden slides/tabs carry no filenames | Golden lacks exact-filename citations near material claims | Cite exact delivered filenames beside every material figure; register lists **every** file cited anywhere (regex every cell) |
| 2 | "Must-pass" in prose, but a wrong deck still scores ~0.36 | Flat `weighted_mean` ignores the label | `required_pass` group for core criteria **and** reweight siblings (0.80/0.08/0.12 → floor 0.20) |
| 3 | Cross-group reward is an unweighted mean | Root `reward.toml` lacks weights | `[reward.weights]` (§4.1); playbook §7's "not fixable" is out of date |
| 4 | Compound criterion | Two independent facts in one binary | Split (r002 → r002a/r002b); explicit partial-credit rules |
| 5 | Same fact graded twice / gated twice | Clause duplicated into a numeric must-pass | Remove the clause from the numeric criterion |
| 6 | Legitimate alternative treatment rejected | Rubric pins one judgment where sources admit several | Enumerate alternatives **with implied totals**; require cross-tab consistency; make every dependent criterion accept the matching alternative |
| 7 | Chart criterion rejects a bitmap chart (real eval) | Wording required native chart XML | Never penalise implementation choice; only an empty/broken native chart |
| 8 | "Use formulas" ungraded — judge blind to formulas | No programmatic criterion | `formula_check.py` + per-dir `reward.toml` + `recalc_xlsx.py` pre-step (§4.3–4.5) |
| 9 | Formula check bypassed by `=Inputs!A1` → literal | Check only tests "contains a reference" | Resolve precedents; verdict formulas need a live precedent; test 4 exploit variants + relabelled golden |
| 10 | Judge sees blank cells | `wb.save()` wiped caches | §5.1 / §5.2; assert 0 empty caches |
| 11 | Subtotal wrong after row insert | Stale intra-sheet reference | Independent recompute after structural edits |
| 12 | Stale self-descriptions (tab index, "22 checks", "18 files", "every X has Y") | Edited content, didn't re-verify prose | §5.3 (b) sweep |
| 13 | Grader language in the golden | Criterion wording copy-pasted | §5.3 (d) grep |
| 14 | Terminology / label drift across tabs | Rename applied on one tab | §5.3 (c) sweep |
| 15 | Reviewers read the two prompt files as contradicting | Fix applied to one file | §5.5 |
| 16 | Every oracle run `RewardFileNotFoundError` | CRLF in `test.sh` | `newline='\n'`; §7 step 2 |
| 17 | Metadata incomplete | `task.toml` missing `description`/`difficulty` | §4.6; don't add unrecognised fields |
| 18 | Register cites a file that doesn't exist / attributes a fact to the wrong file | Fixer added a citation from memory | §5.3 (a); attribute closing entries etc. to the file that actually holds them |
| 19 | Rubric tolerance band admits the wrong answer | ± band wider than the gap to the known-wrong value | Compute the wrong value; tighten the band or make an unambiguous anchor binding |

---

## Appendix A — Fixer subagent prompt (template)

```
You are fixing one SVC-PC harbor benchmark task so that none of its Comprehensive Reviews
reports a major (verdict accept or needs_revision, never reject) and all oracle runs pass.

Task dir (edit in place): <abs path>/staged_<T>_fix/<TASK-ID>
Reviews to address: <abs path>/verifications.json  (N reviews; findings are claims, not facts)
Playbook: <repo>/docs/svc-pc-fix-playbook.md — follow §1–§6 and every xlsx gotcha in §4.
Review spec the graders use: <repo>/docs/ekw-svc-comprehensive-review.md
Recipes and templates: <repo>/docs/svc-pc-one-shot-fix-guide.md §4–§7
Pinned grader source: <path>/rk/extracted/rewardkit (harbor-rewardkit 0.2.0)

Phase 1 — VERIFY, no edits: for every finding across all reviews, open the real file/cell/line and
record confirmed / refuted / partial with the evidence. Recompute any disputed number from the
sources under environment/initial_workspace/ with openpyxl/csv, never from golden prose.
Phase 2 — PLAN: group confirmed findings by root cause. For each: root cause → fix → how you will
prove it (which probe, which number). Never lower task difficulty. Return the plan and STOP.
Phase 3 (after approval) — APPLY, then prove:
  - golden passes every criterion by hand-grading against the criterion text (guide §5.6)
  - instruction.md == tests/task_prompt.txt (sha256)
  - all TOML parse; criterion weights per group sum as intended; root [reward.weights] set
  - rewardkit _discover_layout / _score_layout show the intended reward for all-pass / d01-only / d02-only
  - every xlsx formula has a non-empty cache (data_only=True); deliverable < 1 MB; no \r in any text file
  - every filename cited anywhere in the golden exists by exact name and is in the source register
  - terminology and Fact/Computed/Judgment labels identical for the same item on every tab
  - no grader/rubric language in the golden; every self-description (counts, index) true
  - any programmatic check: golden 1.0; hard-keyed copy 0.0; =literal copy 0.0; indirection copy 0.0;
    relabelled-layout golden still 1.0
Write text files with newline='\n'. Do not wb.save() a golden without restoring caches.
Report: table of findings → disposition → evidence; list of files changed; probe outputs verbatim.
```

## Appendix B — Independent reviewer prompt (identical for all three; parallel; background)

```
You are performing an independent Comprehensive Review of one SVC-PC harbor benchmark task.
No prior context, no memory of any fix history — a fresh cold-start audit. Don't assume fine or
broken. Open every file yourself.

Task package (read-only — do not edit): <abs path>/review_check/<TASK-ID>
Read <repo>/docs/ekw-svc-comprehensive-review.md — execute that prompt verbatim (§1 checks
1.1–1.10, §2, §3, §4, §5 output format).
No evaluation runs ship with this copy — treat evaluation-dependent bullets per §1.5/§3.1
(inconclusive, not a pass by default).

<one paragraph: genre, deliverable, grading layout, pinned grader source path>

Do the real work with rigor on:
1. Recompute every load-bearing figure from the sources with openpyxl/csv — not from golden prose.
2. Verify every filename cited anywhere in the golden exists by exact name and that the register's
   completeness claim matches what every tab actually cites (regex every cell).
3. Terminology consistency of every stage/item label across ALL tabs vs what the criteria grade.
4. Every formula cell carries a live cached value; no formula embeds ≥4-digit literals.
5. Run any programmatic check yourself against the golden, a hard-keyed copy, an =literal copy,
   and an indirection copy; run the recalc pre-step on a cache-wiped copy; confirm rewardkit
   _discover_layout/_score_layout reward arithmetic (state the expected numbers).
6. Every alternative treatment any criterion endorses is accepted consistently by every criterion
   that pins a number — compute each alternative's implied totals.
7. Map instruction requirements to criteria; construct an exploit and a brittle rejection per §1.5;
   check compound/duplicate criteria; check for grader language leaked into the golden; verify
   every golden self-description against reality.

Write prose first (reasoning, evidence, computed numbers), then close with the exact JSON per §5,
nothing after it, no code fence.
```

## Appendix C — Memory seeds (copy into your Claude's memory or CLAUDE.md)

1. **instruction.md / task_prompt.txt must match** — the prompt ships twice; nothing enforces equality;
   a fix in one file never reaches the agent and reads as a contradiction to reviewers. Assert sha256
   equal in the same script that edits them.
2. **Windows text-mode writes → CRLF test.sh** — `\r` in `VERIFIER_DIR` → `RewardFileNotFoundError`
   on every oracle run. `newline='\n'`; assert no `\r` before zipping.
3. **Formula-authenticity check indirection bypass** — "contains a cell reference" is defeated by
   `=Inputs!A1`; resolve precedents; keep golden at 1.0; test four exploit variants.
4. **required_pass alone doesn't lower the floor** — siblings still average in; reweight with
   `[reward.weights]`.
5. **Fixer self-review is not a review** — always three cold-start reviewers on a fresh extraction.
6. **Corpus conventions not to fix** — task.toml domain/occupation/sector/subdomain/task_type absent;
   15–20 MB environment; private base image. Flag, don't change.
7. **Judge sees cached values only** — formulas, images, chart XML, number formats are invisible →
   grade programmatically or don't grade.
8. **Alternative treatments accepted everywhere or nowhere** — if r003 accepts five bridge variants,
   r004/r005/r008/r010 must accept the matching run-rate/runway/disposition.
9. **Sweep golden self-descriptions after every edit** — counts, tab indexes, "every X has Y", sender.
10. **`wb.save()` wipes every formula cache** — patch XML in the zip for text edits; recalc/inject after
    structural edits; openpyxl doesn't shift formula references on row insert.
11. **PYTHONUTF8=1** in every shell on Windows.

## Appendix D — The three tasks this guide is built on

| Task | Start (real DataOS) | Rounds | Final local reviews | Key fixes |
|---|---|---|---|---|
| SVC-PC-62-6-0 | 2 reject / 1 needs_revision | 2 | 3/3 needs_revision, 0 major, all minors fixed | prompt-file desync, f16 reworded functional, CRLF |
| SVC-PC-68-8-0 | 3 reject → 2 reject / 1 NR after first re-upload | 4 | 3/3 non-reject | slide citations, chart sign, required_pass + weights, r002 split, r005 unbundled, r012 twice, task.toml description/difficulty |
| SVC-PC-68-1-0 | 3 reject | 3 + confirmation | 3/3 needs_revision, 0 major; last minors fixed | formula_check.py + recalc pre-step, weights 0.88/0.12, COGS/bridge recompute, register completeness, label consistency, indirection hardening, r010 single rule |

Final zips: `staged_svc62_fix/SVC-PC-62-6-0_final.zip`, `staged_svc68_fix/SVC-PC-68-8-0_final.zip`,
`staged_svc68_1_fix/SVC-PC-68-1-0_final.zip` — use any of them as a worked example of the end state.
A real DataOS re-upload remains the authoritative confirmation for each.
