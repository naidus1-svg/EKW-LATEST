# Safe edits to a golden `.xlsx`

Use this whenever a fix touches a golden output workbook — a numeric
correction, a formula fix, or even a single-cell text/citation change. The
danger is in the **save mechanism**, not the semantic size of the edit: a
one-character text fix and a full recalculation carry the identical risk if
done the wrong way.

## The failure mode

`tests/__verifier_lib/sources/xlsx.py` (or the SVC-PC equivalent) extracts
spreadsheet content with `openpyxl.load_workbook(path, data_only=True,
read_only=True)`. That call reads the **cached result** each formula cell
stored the last time a real spreadsheet engine (Excel, LibreOffice, Google
Sheets) computed it — `data_only=True` never evaluates formulas itself. If a
workbook is loaded and re-saved through plain `openpyxl` (`load_workbook()`
… `.save()`), openpyxl faithfully preserves the formula *text* but does not
compute new cached values, and drops the ones that were already there. The
saved file opens fine, looks identical in Excel (which recalculates on open),
and passes a casual "does it load" check — but the grading harness's
`data_only=True` read now returns `None` for every affected cell.

**Confirmed incident (2026-09-16, task_28 round 4):** a Comprehensive Review
flagged a stale filename citation in one workbook cell. The fix was framed
as "quick, low-risk cleanup" and applied via `openpyxl.load_workbook().save()`.
That single re-save silently stripped 552 of 883 cached cells (63%) —
concentrated in exactly the tabs that ~77% of the rubric's weight grades. The
Oracle's own golden would have failed most of the rubric had this shipped;
a follow-up Comprehensive Review caught it before it went out. The same
failure class (formula-cache loss from a well-intentioned re-save) has
independently bitten fix attempts on other tasks in this corpus (flagged
during task_34's and task_54's fix rounds) — it is a recurring trap, not a
one-off.

A file-size check is a useful smoke alarm (the corrupted workbook was ~40%
smaller in bytes) but not the decisive test — the decisive test is a cached-
cell count through the real extraction path.

## The rule

1. **Never** call `openpyxl.load_workbook(...).save(...)` on a file that is
   or will become part of `solution/golden_outputs/`, for *any* edit size.
2. Edit the underlying XML directly instead: an `.xlsx` is a zip archive of
   XML parts. Extract the archive, edit only the text you intend to change
   inside the relevant XML file, then rebuild the zip, copying every other
   entry byte-for-byte unchanged.
3. After every edit — even one you're confident is "just text" — run the
   verifier's own extraction function against the file before and after, and
   confirm the non-`None` cached-cell count is unchanged (except for cells
   you deliberately changed). Do this even for edits that don't touch a
   formula cell at all; it is the only way to catch an accidental full
   re-save.

## How to do the surgery

Most golden-cell text lives in `xl/sharedStrings.xml` as a shared string
table entry (`<si><t>...</t></si>`), referenced by index from cells with
`t="s"`. A few cells store text inline instead
(`<c t="inlineStr"><is><t>...</t></is></c>`). Locate which form applies
before editing:

```python
import zipfile

path = "market_sizing_model.xlsx"
with zipfile.ZipFile(path) as z:
    shared = z.read("xl/sharedStrings.xml").decode("utf-8")

old_text = "Data is sourced from Modelling - TAM Analysis - Supporting Information - Assumption Dataset"
assert shared.count(old_text) == 1, "expected exactly one occurrence"
```

Then rebuild the zip, replacing only the one member you edited and copying
every other entry (including compression type) unchanged:

```python
new_text = "Data is sourced from Modelling - Assumption Dataset.xlsx"
new_shared = shared.replace(old_text, new_text)

with zipfile.ZipFile(path) as zin:
    items = zin.infolist()
    with zipfile.ZipFile(path + ".tmp", "w", zipfile.ZIP_DEFLATED) as zout:
        for item in items:
            data = zin.read(item.filename)
            if item.filename == "xl/sharedStrings.xml":
                data = new_shared.encode("utf-8")
            zout.writestr(item, data)

import os
os.replace(path + ".tmp", path)
```

(A shell-based alternative — `unzip` the one file out, edit it with `sed`
or a script, then `zip` it back into the archive with `zip <file>.xlsx
xl/sharedStrings.xml` — works too, as long as you never round-trip the
whole workbook through a spreadsheet library's writer.)

If the target cell is an inline string instead of a shared-string reference,
apply the same extract → string-replace → selective-rewrite approach to the
relevant `xl/worksheets/sheetN.xml` part instead.

## The mandatory before/after check

Run this against the file before your edit (record the baseline) and again
after (confirm it matches, aside from cells you meant to change):

```python
import openpyxl

def cached_cell_count(path):
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    total = 0
    per_sheet = {}
    for ws in wb.worksheets:
        n = sum(1 for row in ws.iter_rows() for c in row if c.value is not None)
        per_sheet[ws.title] = n
        total += n
    return total, per_sheet

before_total, before_sheets = cached_cell_count("market_sizing_model.xlsx.bak")
after_total, after_sheets = cached_cell_count("market_sizing_model.xlsx")
assert before_total == after_total, f"cache loss: {before_total} -> {after_total}"
assert before_sheets == after_sheets, "cache loss concentrated in a specific sheet"
```

Keep a pre-edit copy (`.bak` or a round-numbered snapshot, per this corpus's
existing snapshot convention) specifically so this comparison has a real
baseline to check against — don't rely on memory of what the count "should"
be.

For a formula or numeric-value fix (not just a citation/text fix), also spot-
check that the specific load-bearing rows still extract as real numbers
(e.g. the TAM/SAM/SOM totals a rubric criterion reads), not just that the
aggregate count matches — a corruption that swaps two cells' worth of content
could in principle preserve the total count while still breaking grading.

## When this skill applies

Any task where a rubric criterion reads a `.xlsx` deliverable via
`data_only=True` extraction — this is the default for both EKW native-harbor
tasks (`tests/__verifier_lib/sources/xlsx.py`) and SVC-PC rewardkit tasks
using an equivalent xlsx source type. It applies equally to:

- A golden-content fix (correcting a wrong number or formula).
- A "purely cosmetic" fix (a stale citation, a mislabeled sheet name, a typo).
- A metadata-adjacent fix that happens to touch the same file as a content
  fix in the same round.

It does **not** apply to `.docx` edits (python-docx round-trips text safely;
there is no formula-cache equivalent) or to `verifier.json`/`judge.toml`
edits (plain JSON/TOML, no binary-format risk).

## Cross-reference

Called out as a standing rule in
[`dataos-batch-watch/SKILL.md`](../dataos-batch-watch/SKILL.md)'s fix-subagent
mandate — that skill's golden-edit caution and this skill's procedure are the
same rule; this file is the actionable how-to.
