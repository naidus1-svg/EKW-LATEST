#!/usr/bin/env python3
"""Formula-provenance checker lint: static defects in a task's OWN per-task
`tests/deliverables_*/check_formula_provenance.py` (rewardkit genre) or in the
whole-workbook `formula_authenticity` assertions of its `tests/verifier.json`
(native genre).

Why this exists (measured, not hypothesised). In the 30-task fix session of 2026-09-22,
9 of 30 tasks had a defect in their per-task copy of the band-anchored formula-provenance
template. The template is copy-pasted per task and its per-task CONFIG block (BANDS,
EXEMPT, MIN_BANDS_HIT, hop limits, restatement caps) is hand-written each time and never
linted or unit-tested. All 9 defects cost real reward on a 0.03-0.10 weight criterion:

    task_218  unanchored 11-day date-serial bands; an agent's ordinary Action-Plan due
              dates (2026-08-20/22/23) landed inside `invar_exp_arrival`. 674 live
              formulas, full 0.10 lost.
    task_559  required `range_agg >= 1` (a colon-range aggregating function) -- a
              construct that appears nowhere in instruction.md.
    task_462  banded raw filing figures the instruction TELLS the solver to type and cite,
              in both $000 and $m form, with an EXEMPT list of 2 numbers. 3 runs failed.
    task_470  banded the trial-volatility levels of a breakeven-vol grid -- scenario
              inputs, not typed answers.
    task_574  counted typed CELLS, not distinct typed FIGURES, against a cap of 1: one
              legitimately restated figure across 75 presentation cells read as 75.
    task_390  echo-chain follower capped at 3 hops; a real 4-hop live roll-forward chain
              scored as a typed constant. 460 live formulas, scored 0.
    task_388  gate satisfiable by `=184627.68*1` disguised constants.
    task_348  bands only 4 aggregate totals, floor 2 -- all 22 detail rows may be typed.
    task_145  (native genre) formula share measured whole-workbook with a 50-example cap:
              ~300 decoy formulas + 10 cross-sheet links passes.

What this check DOES. It is a STATIC lint. It never imports, execs or otherwise runs the
task's checker as a checker. It `ast`-parses the file, replays ONLY the module-level
constant assignments of the CONFIG block in a restricted namespace (no imports, no
function/class defs, no calls except a small builtin allowlist -- so `BANDS` built by a
list comprehension over `_M`, or `EXEMPT = _SPOTS + list(range(1, 41))`, still resolve),
and reasons over that plus the AST of the criterion body.

Detectors, with their honest confidence:

  band_collision                  EXACT on the value scan, heuristic on intent.
      A numeric/date value that actually exists in the task's own `environment/` inputs,
      or is a TYPED (non-formula) constant in the golden deliverable, falls inside one of
      the checker's bands and is not on its EXEMPT list (respecting ABS_VALUES,
      INTEGER_ONLY and per-band row anchors). The value scan is exact -- the value is
      genuinely there and genuinely in band. What is heuristic is whether that value is
      "the figure the band is meant to pin": a value the golden computes with a live
      formula is assumed intended, a typed one is not. This is the mechanised form of the
      by-hand sweep task_348's own fix report records ("all 169 distinct input values
      scanned, none in band").
  unanchored_generic_band         HEURISTIC (the task_218 class).
      A band with no exclusionary row anchor whose range is generic enough that ordinary
      deliverable content lands in it: a date-serial window (values in 40000..60000) more
      than 2 days wide, or a small-integer band (|hi| <= 100). Corroborated -- and
      escalated in the report -- when the checker's own EXEMPT list already contains
      values inside that same band, which is the author conceding collisions happen there.
  hop_limit_too_low               EXACT.
      The reference/echo-chain follower's recursion cap, read straight off the AST
      (`depth > N` / `depth >= N` in a function that recurses with `depth + 1`, or a
      `MAX_HOPS`/`MAX_DEPTH`-shaped constant), is below `--min-hops` (default 8).
  per_cell_violation_counting     HEURISTIC.
      A violation list that is `.append`-ed one entry per CELL inside the cell scan is
      compared by `len(...)` against a small cap, with no de-duplication of the underlying
      (value, band) figure anywhere in the function.
  disguised_constant_unguarded    HEURISTIC.
      The checker credits any "substantive" formula without a guard for identity wrappers
      (`=184627.68*1`, `=B7+0`, `=IF(TRUE,<literal>,...)`). Detected by absence of the
      template's own guard shape: a single-reference formula whose cached value is
      compared for equality against its referent's cached value, or an explicit literal-
      operand test.
  requirement_not_in_instruction  HEURISTIC.
      The checker requires a construct (a colon-range aggregate, a verdict literal, a
      minimum live-formula count) whose whole vocabulary is absent from the task's own
      `instruction.md`. Vocabulary sets are listed in REQUIREMENT_VOCAB below.
  coverage_floor_too_shallow      HEURISTIC.
      `MIN_BANDS_HIT` is below `--min-coverage-ratio` (default 0.5) of the distinct band
      LABELS defined, or every band label reads as an aggregate ("total", "subtotal",
      "sum", "grand") so a workbook may type every detail row and still pass. Native
      genre: a `formula_authenticity`-tagged assertion on `$.formula_share_all` or
      `$.n_formula_with_refs` whose source carries no `sheet_name_contains` scoping, i.e.
      measured across the whole workbook with an unbounded denominator.

What this check does NOT do, stated plainly:
  - It does not run the task's checker, so it cannot tell you whether the golden or any
    real agent workbook actually passes or fails. Only `formula_health_check.py` and a
    real grading run do that.
  - It cannot see collisions that arise only in an agent's own output (task_218's actual
    losing cells were in the AGENT's workbook, not in the environment or the golden).
    `unanchored_generic_band` is the static proxy for that class, and it is a proxy.
  - It has no opinion on whether a band's numeric range is CORRECT for the rubric figure
    it claims to pin; it reads the band as given.
  - Native genre coverage is thin: only the whole-workbook-scope signal, because the
    50-example `hardcoded_cells` cap that task_145 actually lost on lives in the frozen
    `__verifier_lib/sources/xlsx.py`, not in any per-task file this lint reads.

Calibration status (2026-09-22), measured -- every number below is from a real run, not
an estimate.

  Pre-fix baselines, `qcr_21092026/incoming/` (the 9 tasks above, as submitted and as
  scored): 9/9 reported findings; 8/9 fail on a gate-ready kind, task_145 warns.
  8 of the 9 are flagged by the detector matching their OWN measured mechanism --
  task_218 `unanchored_generic_band` (both date windows, 3 EXEMPT serials corroborating
  inside them), task_559 `requirement_not_in_instruction` (range_agg) AND
  `band_collision` (inspection-log counts 41/42/43/69/71), task_462 `band_collision`
  (filing figures in $m bands), task_470 `unanchored_generic_band` (the n_d1 unit-interval
  band [0.683, 0.701] and the option-value band [17.6, 19.7] that swallow an agent's typed
  trial-vol grid levels 0.685-0.700 and 18/19), task_574 `per_cell_violation_counting`,
  task_390 `hop_limit_too_low` (cap 3), task_348 `coverage_floor_too_shallow`,
  task_145 `coverage_floor_too_shallow` (native whole-workbook share).
  The 9th, task_388, is flagged (hop cap + unanchored bands) but NOT by the mechanism its
  fix report names: reading its real source, task_388 DOES carry the identity-wrapper
  guard, so `disguised_constant_unguarded` correctly stays silent on it. Stated here
  rather than tuned into a false catch.

  Post-fix packages, `qcr_21092026/ready/*_fixed.zip` + `qcr_20092026_rework/ready/*.zip`
  (30 tasks): every detector that fired on a task's own measured mechanism goes quiet
  after that task's fix -- task_390 `hop_limit_too_low` (the fix names the cap
  `MAX_ECHO_DEPTH = 8`, which this lint resolves through the CONFIG replay), task_574
  `per_cell_violation_counting`, task_559 `requirement_not_in_instruction`, task_348's
  `unanchored_generic_band`. What remains post-fix is latent, not spurious: 6 packages
  still carry the template's `depth > 3` cap because only task_390's fix touched it, and
  task_574's residual `band_collision` is the documented known-FP class (the golden's own
  typed '4,140' presentation restatements, which the fixed checker forgives at run time
  through logic a static lint cannot replay).

  False-positive sweep, `ready_to_upload_v7/submitted/` (79 tasks, the shipped v7 batch):
  0 gate-ready findings. 4 pass, 33 skip (no formula-provenance checker at all), 42 warn
  -- every warn is `coverage_floor_too_shallow` on a native-genre whole-workbook
  formula-share/count assertion. Second sweep, `ready_to_upload_v4/submitted/` (51 tasks,
  7 of them rewardkit-genre): 7 pass, 44 skip, 0 findings of any kind.
  Honest limit on that number: only 9 of those 130 shipped tasks are rewardkit-genre, so
  "0 gate false positives" is measured on a thin rewardkit denominator. The broad
  denominator for the gate-ready kinds is the 30-package post-fix set above.

GATE-READY (default `--gate` set): `band_collision`, `hop_limit_too_low`. Both have an
exact core (a real value really in a real band; a recursion cap read off the AST) and
zero false positives across both shipped sweeps.
REPORT-ONLY (never sets `fail`, surfaced as `warn`): `unanchored_generic_band`,
`per_cell_violation_counting`, `disguised_constant_unguarded`,
`requirement_not_in_instruction`, `coverage_floor_too_shallow`. These fire on enough
legitimately-authored tasks that gating on them would block correct work
(`coverage_floor_too_shallow` alone fires on 42 of the 46 non-skip tasks of the shipped
v7 batch) -- `answer_key_content_leak_check.py` is the precedent for shipping a useful,
honest, non-gating signal rather than pretending to a precision the calibration does not
support. Move one into `--gate` only after calibrating it on your own corpus.

Known false-positive classes, disclosed:
  - band_collision: a band deliberately drawn to pin a figure the golden also SHOWS as a
    typed presentation restatement on a summary tab (the checker may forgive it at run
    time via its own live-bands logic, which this static lint cannot replay).
  - band_collision: an environment input whose value coincides with a derived figure by
    arithmetic accident (a subtotal equal to one of its own line items).
  - unanchored_generic_band: a task whose graded figures genuinely ARE small integers and
    whose deliverable schema has no free-text row that could collide.
  - requirement_not_in_instruction: an instruction that expresses the requirement in
    domain words this lint's vocabulary sets do not contain ("roll the balance forward"
    for a range aggregate).
  - coverage_floor_too_shallow: a task with exactly one graded headline figure, where
    MIN_BANDS_HIT=1 over 2 unit-variant bands is correct.

Statuses:
    "fail"  -- at least one GATE-READY finding.
    "warn"  -- report-only findings only.
    "pass"  -- a formula-provenance checker (or native formula_authenticity block) was
               found and parsed, and nothing fired.
    "skip"  -- the task genuinely ships no formula-provenance checker and no
               formula_authenticity assertion; the reason says which was looked for.
    "error" -- a checker exists but could not be parsed or its config could not be read.

Exit code: 0 always (disclosure tool; `pre_submit_gate.py` decides policy).

Python 3.11+, stdlib + openpyxl only.

Usage:
    python formula_provenance_lint.py <TASK-ID> [<TASK-ID> ...] --root <path> [--out report.json]
    python formula_provenance_lint.py --all --root <path> [--id-prefix task_] [--out report.json]
    python formula_provenance_lint.py --all --root <path> --gate band_collision,hop_limit_too_low
"""

from __future__ import annotations

import argparse
import ast
import csv
import datetime as _dt
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# tunables / policy
# ---------------------------------------------------------------------------

DEFAULT_MIN_HOPS = 8
DEFAULT_MIN_COVERAGE_RATIO = 0.5
DEFAULT_GATE_KINDS = ("band_collision", "hop_limit_too_low")

ALL_KINDS = (
    "band_collision",
    "unanchored_generic_band",
    "hop_limit_too_low",
    "per_cell_violation_counting",
    "disguised_constant_unguarded",
    "requirement_not_in_instruction",
    "coverage_floor_too_shallow",
)

# Excel date-serial plausibility window: 2009-09-26 .. 2064-04-06. A band lying wholly
# inside it is treated as a date window for `unanchored_generic_band` purposes.
DATE_SERIAL_LO = 40000.0
DATE_SERIAL_HI = 60000.0

# A `requirement_not_in_instruction` rule: (config/AST marker, human name, vocabulary that
# would have to appear SOMEWHERE in instruction.md for the requirement to be anchored).
REQUIREMENT_VOCAB: dict[str, tuple[str, tuple[str, ...]]] = {
    # Deliberately NARROW: the requirement is a colon-RANGE aggregating FUNCTION, so the
    # instruction has to name such a function (or the idea of a range/column aggregate) for
    # the requirement to be anchored. A bare "count" or "total" in prose does not tell a
    # solver to write `=SUM(A1:A20)` -- that widening is exactly what let task_559's
    # `range_agg >= 1` look anchored when it was not.
    "range_agg": (
        "a colon-range aggregating function (SUM/AVERAGE/COUNTIF over a cell range)",
        ("sum(", "=sum", "sumif", "sumproduct", "subtotal(", "average(", "countif",
         "counta", "aggregate function", "cell range", "range aggregate", "roll up",
         "rollup", "formula over the range", "aggregating formula"),
    ),
    "verdicts": (
        "logic formulas returning a PASS/FAIL-style verdict literal",
        ("verdict", "pass", "fail", "tie-out", "tie out", "flag", "status", "ok",
         "compliant", "exception", "decision"),
    ),
    "cross_sheet": (
        "formulas that reference another worksheet",
        ("sheet", "tab", "worksheet", "reference", "link", "cross-sheet"),
    ),
}

# Config names whose value is a minimum-count floor on live formulas. A high floor with no
# instruction support is the task_145/task_559 shape.
FORMULA_COUNT_FLOOR_NAMES = ("MIN_SUBSTANTIVE", "MIN_FORMULAS", "MIN_LIVE", "MIN_FUNCTIONAL")

AGGREGATE_LABEL_WORDS = ("total", "subtotal", "sum", "grand", "aggregate", "rollup", "roll_up")

# Builtins the restricted config replay is allowed to call. Deliberately tiny: everything
# real CONFIG blocks in this corpus use, and nothing with a side effect.
SAFE_BUILTINS = {
    "abs": abs, "bool": bool, "dict": dict, "enumerate": enumerate, "float": float,
    "frozenset": frozenset, "int": int, "len": len, "list": list, "max": max, "min": min,
    "range": range, "round": round, "set": set, "sorted": sorted, "str": str, "sum": sum,
    "tuple": tuple, "zip": zip, "True": True, "False": False, "None": None,
}

_EPOCH = _dt.datetime(1899, 12, 30)

CHECKER_GLOB = "check_formula_provenance*.py"
# Some tasks name the same template differently; both spellings are real in this corpus.
CHECKER_EXTRA_GLOBS = ("check_live_formula*.py", "check_formula_*.py")


# ---------------------------------------------------------------------------
# package layout resolution
# ---------------------------------------------------------------------------

def resolve_package_root(task_dir: Path) -> Path | None:
    """Find the directory that holds `tests/` for this task.

    Real layouts in this corpus:
        <root>/<task>/                                   (ready_to_upload_v7/submitted)
        <root>/<task>/<task>/rev_*/task_files/           (qcr_*/incoming)
        <root>/<task>/task_files/                        (unzipped *_fixed.zip)
    Picks the deepest-but-first match by a bounded breadth walk, preferring the highest
    revision when several `rev_*` directories exist.
    """
    if (task_dir / "tests").is_dir():
        return task_dir
    candidates: list[Path] = []
    for depth_dir in (task_dir, *(p for p in task_dir.iterdir() if p.is_dir())) if task_dir.is_dir() else ():
        if (depth_dir / "tests").is_dir():
            return depth_dir
        if not depth_dir.is_dir():
            continue
        for sub in depth_dir.iterdir():
            if not sub.is_dir():
                continue
            if (sub / "tests").is_dir():
                candidates.append(sub)
            elif (sub / "task_files" / "tests").is_dir():
                candidates.append(sub / "task_files")
    if not candidates:
        return None

    def _rev_key(p: Path) -> tuple[int, str]:
        m = re.search(r"rev_(\d+)", str(p))
        return (int(m.group(1)) if m else 0, str(p))

    return sorted(candidates, key=_rev_key)[-1]


def find_checkers(pkg: Path) -> list[Path]:
    tests = pkg / "tests"
    if not tests.is_dir():
        return []
    found: dict[Path, None] = {}
    for pat in (CHECKER_GLOB, *CHECKER_EXTRA_GLOBS):
        for p in sorted(tests.rglob(pat)):
            if "__verifier_lib" in p.parts:
                continue
            found[p] = None
    return list(found)


def find_environment_inputs(pkg: Path) -> list[Path]:
    for rel in ("environment/initial_workspace", "environment/data", "environment"):
        d = pkg / rel
        if d.is_dir():
            files = [
                p for p in sorted(d.rglob("*"))
                if p.is_file() and p.suffix.lower() in {
                    ".xlsx", ".xlsm", ".csv", ".docx", ".txt", ".md", ".json", ".pdf"
                }
            ]
            if files:
                return files
    return []


def find_golden_workbooks(pkg: Path, deliverable: str | None) -> list[Path]:
    out: list[Path] = []
    for rel in ("solution/files", "solution/golden_outputs", "solution", "tests/golden"):
        d = pkg / rel
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file() and p.suffix.lower() in {".xlsx", ".xlsm"}:
                if deliverable and p.name != deliverable:
                    continue
                out.append(p)
        if out:
            break
    return out


# ---------------------------------------------------------------------------
# restricted CONFIG replay (NOT an execution of the checker)
# ---------------------------------------------------------------------------

class _UnsafeConfig(Exception):
    pass


def _expr_is_safe(node: ast.AST, known: set[str]) -> bool:
    """True if `node` is a pure constant expression over SAFE_BUILTINS and already-bound
    config names. Any attribute access (`re.compile`, `datetime.date`), any name we have
    not bound ourselves, any lambda/comprehension over unknown names -> unsafe."""
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Attribute, ast.Await, ast.Yield, ast.YieldFrom, ast.Lambda)):
            return False
        if isinstance(sub, ast.Call):
            if not isinstance(sub.func, ast.Name) or sub.func.id not in SAFE_BUILTINS:
                return False
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            if sub.id in SAFE_BUILTINS or sub.id in known:
                continue
            # comprehension-local targets are bound inside the expression itself
            if any(
                sub.id in _comp_targets(c)
                for c in ast.walk(node)
                if isinstance(c, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))
            ):
                continue
            return False
    return True


def _comp_targets(comp: ast.AST) -> set[str]:
    names: set[str] = set()
    for gen in getattr(comp, "generators", []):
        for n in ast.walk(gen.target):
            if isinstance(n, ast.Name):
                names.add(n.id)
    return names


def replay_config(tree: ast.Module) -> dict:
    """Replay the module-level constant assignments only, in a restricted namespace.

    This is deliberately NOT `import`ing or exec'ing the checker: function defs, imports,
    decorators and every expression touching an attribute or a non-allowlisted call are
    dropped, so the criterion body never runs and `rewardkit`/`openpyxl` are never needed.
    """
    ns: dict = {"__builtins__": dict(SAFE_BUILTINS)}
    known: set[str] = set()
    for stmt in tree.body:
        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            continue
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        if not all(isinstance(t, ast.Name) for t in targets):
            continue
        value = stmt.value
        if value is None or not _expr_is_safe(value, known):
            continue
        mod = ast.Module(body=[stmt], type_ignores=[])
        ast.fix_missing_locations(mod)
        try:
            exec(compile(mod, "<config>", "exec"), ns)  # noqa: S102 - restricted namespace
        except Exception:
            continue
        for t in targets:
            known.add(t.id)  # type: ignore[union-attr]
    ns.pop("__builtins__", None)
    return ns


# ---------------------------------------------------------------------------
# band model
# ---------------------------------------------------------------------------

class Band:
    __slots__ = ("label", "lo", "hi", "anchor")

    def __init__(self, label: str, lo: float, hi: float, anchor: str | None) -> None:
        self.label, self.lo, self.hi, self.anchor = label, float(lo), float(hi), anchor

    @property
    def width(self) -> float:
        return self.hi - self.lo

    @property
    def is_date_window(self) -> bool:
        return DATE_SERIAL_LO <= self.lo <= DATE_SERIAL_HI and DATE_SERIAL_LO <= self.hi <= DATE_SERIAL_HI

    def contains(self, y: float) -> bool:
        return self.lo <= y <= self.hi

    def as_dict(self) -> dict:
        return {"label": self.label, "lo": self.lo, "hi": self.hi, "anchor": self.anchor}


def _band_contains_integer(b: Band) -> bool:
    """True if some whole number lies inside [lo, hi] -- i.e. an ordinary typed quantity,
    row ordinal or grid level can land in the band."""
    import math

    return math.floor(b.hi) >= math.ceil(b.lo)


def parse_bands(raw) -> list[Band]:
    bands: list[Band] = []
    if not isinstance(raw, (list, tuple)):
        return bands
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        label, lo, hi = item[0], item[1], item[2]
        anchor = item[3] if len(item) > 3 else None
        if not isinstance(label, str):
            continue
        try:
            lo_f, hi_f = float(lo), float(hi)
        except (TypeError, ValueError):
            continue
        if not isinstance(anchor, str):
            anchor = None
        bands.append(Band(label, min(lo_f, hi_f), max(lo_f, hi_f), anchor))
    return bands


def to_number(x) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, _dt.datetime):
        return (x - _EPOCH).total_seconds() / 86400.0
    if isinstance(x, _dt.date):
        return float((x - _EPOCH.date()).days)
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip().replace(",", "").replace("$", "")
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        if s.endswith("%"):
            s = s[:-1]
        try:
            return float(s)
        except ValueError:
            return None
    return None


def band_hits(value, bands: list[Band], *, abs_values: bool, integer_only: bool,
              exempt: list[float], exempt_tol: float, rowtext: str | None) -> list[Band]:
    y = to_number(value)
    if y is None:
        return []
    if abs_values:
        y = abs(y)
    if integer_only and abs(y - round(y)) > 1e-9:
        return []
    for e in exempt:
        ey = to_number(e)
        if ey is None:
            continue
        if abs(abs(y) - abs(ey)) <= exempt_tol * max(1.0, abs(ey)):
            return []
    out = []
    for b in bands:
        if not b.contains(y):
            continue
        if b.anchor is not None and rowtext is not None and b.anchor.upper() not in rowtext:
            continue
        out.append(b)
    return out


# ---------------------------------------------------------------------------
# data scans
# ---------------------------------------------------------------------------

_MONTHS = (
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST",
    "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
    "JAN", "FEB", "MAR", "APR", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)


def _date_context_noise(value, rowtext: str) -> bool:
    """Suppress one measured noise class in the TEXT-derived (pdf/docx/txt) scan only.

    A calendar day-of-month picked out of prose ("December 31, 2024" -> 31) is not a
    figure any solver types into a workbook as a result, but a band like [31.0, 31.0]
    still matches it. Applies ONLY to loose text, never to a real xlsx/csv cell -- a 31
    sitting in a spreadsheet cell is a genuine candidate for transcription.
    """
    y = to_number(value)
    if y is None or abs(y) > 31 or abs(y - round(y)) > 1e-9:
        return False
    return any(m in rowtext for m in _MONTHS)


def _xlsx_values(path: Path, *, with_formulas: bool):
    """Yield (sheet, coord, value, rowtext, is_formula). `value` is the CACHED value."""
    import openpyxl

    try:
        wbv = openpyxl.load_workbook(str(path), data_only=True, read_only=False)
    except Exception as e:  # pragma: no cover - corrupt fixture
        raise RuntimeError(f"{path.name}: {e}") from e
    wbf = None
    if with_formulas:
        try:
            wbf = openpyxl.load_workbook(str(path), data_only=False, read_only=False)
        except Exception:
            wbf = None
    try:
        for ws in wbv.worksheets:
            wsf = wbf[ws.title] if wbf is not None and ws.title in wbf.sheetnames else None
            rowtext: dict[int, str] = {}
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and not c.value.startswith("="):
                        rowtext[c.row] = rowtext.get(c.row, "") + " " + c.value.upper()
            if wsf is not None:
                for row in wsf.iter_rows():
                    for c in row:
                        if isinstance(c.value, str) and not c.value.startswith("="):
                            rowtext[c.row] = rowtext.get(c.row, "") + " " + c.value.upper()
            for row in ws.iter_rows():
                for c in row:
                    if c.value is None:
                        continue
                    is_formula = False
                    if wsf is not None:
                        raw = wsf[c.coordinate].value
                        is_formula = isinstance(raw, str) and raw.startswith("=")
                        if not is_formula and getattr(raw, "text", None) is not None:
                            is_formula = True
                    yield ws.title, c.coordinate, c.value, rowtext.get(c.row, ""), is_formula
    finally:
        wbv.close()
        if wbf is not None:
            wbf.close()


_DOCX_NUM = re.compile(r"-?\$?\d[\d,]*(?:\.\d+)?%?")

_PDF_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
_PDF_SHOW = re.compile(rb"\((?:\\.|[^\\()])*\)")
_PDF_ESCAPE = re.compile(rb"\\([nrtbf()\\]|[0-7]{1,3})")


def _pdf_text(path: Path, *, max_bytes: int = 25_000_000) -> str:
    """Stdlib-only, best-effort PDF text extraction.

    Inflates every FlateDecode content stream with `zlib` and pulls the literal strings
    out of the text-showing operators. Deliberately cheap: no font/encoding tables, no
    CID maps, no layout. That is enough for this check, whose only consumer is a numeric
    band scan over figures that a solver could transcribe -- but it means a PDF whose
    fonts use a custom encoding, or one that is a scanned image, contributes NOTHING, and
    a band_collision this lint does not report is therefore not proof of no collision.
    Disclosed here rather than silently assumed away.
    """
    import zlib

    try:
        raw = path.read_bytes()
    except Exception:
        return ""
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
    chunks: list[str] = []
    for m in _PDF_STREAM.finditer(raw):
        blob = m.group(1)
        for candidate in (blob, blob.strip()):
            try:
                data = zlib.decompress(candidate)
                break
            except Exception:
                data = None
        if data is None:
            data = blob if b"Tj" in blob or b"TJ" in blob else None
        if data is None:
            continue
        parts: list[str] = []
        for s in _PDF_SHOW.finditer(data):
            body = s.group(0)[1:-1]
            body = _PDF_ESCAPE.sub(
                lambda mm: (
                    bytes([int(mm.group(1), 8)])
                    if mm.group(1).isdigit()
                    else {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b",
                          b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}[mm.group(1)]
                ),
                body,
            )
            parts.append(body.decode("latin-1", errors="replace"))
        if parts:
            chunks.append(" ".join(parts))
    return "\n".join(chunks)


def _text_numbers(path: Path):
    """Yield (locator, value, rowtext) for csv/docx/txt sources. Cheap, text-only."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        try:
            with open(path, newline="", encoding="utf-8", errors="replace") as fh:
                for i, row in enumerate(csv.reader(fh), 1):
                    line = " ".join(row).upper()
                    for j, cell in enumerate(row):
                        v = to_number(cell)
                        if v is not None:
                            yield f"row{i}col{j + 1}", v, line
        except Exception:
            return
    elif suffix == ".docx":
        try:
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist() if n.startswith("word/") and n.endswith(".xml")]
                text = " ".join(
                    re.sub(r"<[^>]+>", " ", z.read(n).decode("utf-8", errors="replace"))
                    for n in names
                )
        except Exception:
            return
        for m in _DOCX_NUM.finditer(text):
            v = to_number(m.group(0))
            if v is not None:
                yield f"offset{m.start()}", v, text[max(0, m.start() - 120): m.start() + 120].upper()
    elif suffix == ".pdf":
        text = _pdf_text(path)
        if not text:
            return
        for m in _DOCX_NUM.finditer(text):
            v = to_number(m.group(0))
            if v is not None:
                yield f"offset{m.start()}", v, text[max(0, m.start() - 120): m.start() + 120].upper()
    elif suffix in {".txt", ".md", ".json"}:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return
        for m in _DOCX_NUM.finditer(text):
            v = to_number(m.group(0))
            if v is not None:
                yield f"offset{m.start()}", v, text[max(0, m.start() - 120): m.start() + 120].upper()


# ---------------------------------------------------------------------------
# AST-level detectors
# ---------------------------------------------------------------------------

def detect_hop_limit(tree: ast.Module, config: dict) -> tuple[int | None, str]:
    """Return (hop_cap, evidence). Exact: reads the recursion guard off the AST."""
    for name in ("MAX_HOPS", "MAX_DEPTH", "HOP_LIMIT", "DEPTH_LIMIT", "MAX_ECHO_HOPS",
                 "MAX_ECHO_DEPTH", "MAX_CHAIN_DEPTH", "MAX_FOLLOW_DEPTH"):
        if isinstance(config.get(name), int):
            return int(config[name]), f"{name} = {config[name]}"

    best: tuple[int, str] | None = None
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arg_names = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
        depth_args = {a for a in arg_names if "depth" in a or "hop" in a}
        if not depth_args:
            continue
        recurses = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == fn.name
            for n in ast.walk(fn)
        )
        if not recurses:
            continue
        for cmp_node in ast.walk(fn):
            if not isinstance(cmp_node, ast.Compare) or len(cmp_node.ops) != 1:
                continue
            left, op, right = cmp_node.left, cmp_node.ops[0], cmp_node.comparators[0]
            if not (isinstance(left, ast.Name) and left.id in depth_args):
                continue
            if isinstance(right, ast.Constant) and isinstance(right.value, int):
                n = right.value
            elif isinstance(right, ast.Name) and isinstance(config.get(right.id), int):
                # `depth > MAX_ECHO_DEPTH` -- resolve through the replayed CONFIG block
                n = int(config[right.id])
            else:
                continue
            if isinstance(op, ast.Gt):        # depth > 3  -> 3 extra hops after the first
                cap = n
            elif isinstance(op, ast.GtE):     # depth >= 4 -> 3
                cap = n - 1
            else:
                continue
            src_txt = right.id if isinstance(right, ast.Name) else n
            ev = f"{fn.name}(): `{left.id} {'>' if isinstance(op, ast.Gt) else '>='} {src_txt}` (= {n})"
            if best is None or cap < best[0]:
                best = (cap, ev)
    if best:
        return best
    return None, ""


def _appended_lists(fn: ast.AST) -> dict[str, list[ast.Call]]:
    out: dict[str, list[ast.Call]] = {}
    for n in ast.walk(fn):
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "append"
            and isinstance(n.func.value, ast.Name)
        ):
            out.setdefault(n.func.value.id, []).append(n)
    return out


def detect_per_cell_counting(tree: ast.Module) -> list[dict]:
    """HEURISTIC: `len(<per-cell violation list>) > <small cap>` with no figure-level dedup."""
    findings: list[dict] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        appended = _appended_lists(fn)
        if not appended:
            continue
        # figure-level dedup anywhere in the function suppresses this finding
        src_names = {
            n.func.id for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {"set", "frozenset"}
        }
        for cmp_node in ast.walk(fn):
            if not isinstance(cmp_node, ast.Compare) or len(cmp_node.ops) != 1:
                continue
            left = cmp_node.left
            if not (
                isinstance(left, ast.Call)
                and isinstance(left.func, ast.Name)
                and left.func.id == "len"
                and left.args
                and isinstance(left.args[0], ast.Name)
            ):
                continue
            lname = left.args[0].id
            if lname not in appended:
                continue
            right = cmp_node.comparators[0]
            cap = None
            if isinstance(right, ast.Constant) and isinstance(right.value, int):
                cap = right.value
            elif isinstance(right, ast.Name):
                cap = right.id
            if cap is None:
                continue
            # does the appended element look like a per-CELL record (carries a key/coord)?
            per_cell = False
            for call in appended[lname]:
                for a in ast.walk(call):
                    if isinstance(a, ast.Name) and a.id in {"key", "c", "cell", "coord", "coordinate"}:
                        per_cell = True
                    if isinstance(a, ast.Attribute) and a.attr in {"coordinate", "coord"}:
                        per_cell = True
            if not per_cell:
                continue
            if "set" in src_names and isinstance(cap, str):
                # e.g. dedups into a set before comparing -- weak evidence of figure counting
                pass
            findings.append(
                {
                    "function": fn.name,
                    "list": lname,
                    "cap": cap,
                    "evidence": f"{fn.name}(): `len({lname}) {type(cmp_node.ops[0]).__name__} {cap}`",
                }
            )
    return findings


_IDENTITY_GUARD_MARKERS = ("*1", "+0", "disguised", "identity")


def detect_disguised_constant_guard(tree: ast.Module, source: str) -> bool:
    """True if the checker HAS an identity-wrapper guard.

    The template's guard shape: inside the chain follower, a single-reference formula's own
    cached value is compared for equality with its referent's cached value (so `=X*1` is
    followed rather than credited). Detected structurally, with a textual fallback.
    """
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        has_single_ref = any(
            isinstance(n, ast.Attribute) and n.attr in {"findall", "fullmatch", "match"}
            and isinstance(n.value, ast.Name) and "SINGLE" in n.value.id.upper()
            for n in ast.walk(fn)
        )
        has_len_one = any(
            isinstance(n, ast.Compare)
            and isinstance(n.left, ast.Call)
            and isinstance(n.left.func, ast.Name)
            and n.left.func.id == "len"
            and any(isinstance(c, ast.Constant) and c.value == 1 for c in n.comparators)
            for n in ast.walk(fn)
        )
        if has_single_ref and has_len_one:
            return True
    lowered = source.lower()
    return any(m in lowered for m in _IDENTITY_GUARD_MARKERS if m not in {"*1", "+0"}) or (
        "=x*1" in lowered.replace(" ", "") or "=b7+0" in lowered.replace(" ", "")
    )


def detect_requirements(tree: ast.Module, config: dict, source: str) -> list[dict]:
    """Required constructs the checker enforces, for the instruction-anchor test."""
    reqs: list[dict] = []
    # `range_agg >= N`, `verdicts < MIN_VERDICT`, etc. -- any comparison of a counter whose
    # name matches a REQUIREMENT_VOCAB key against a threshold.
    for cmp_node in ast.walk(tree):
        if not isinstance(cmp_node, ast.Compare) or len(cmp_node.ops) != 1:
            continue
        for side in (cmp_node.left, cmp_node.comparators[0]):
            if isinstance(side, ast.Name) and side.id in REQUIREMENT_VOCAB:
                other = cmp_node.comparators[0] if side is cmp_node.left else cmp_node.left
                thr = other.value if isinstance(other, ast.Constant) else (
                    config.get(other.id) if isinstance(other, ast.Name) else None
                )
                reqs.append({"marker": side.id, "threshold": thr})
    for name in ("MIN_VERDICT", "MIN_VERDICTS"):
        if isinstance(config.get(name), int) and config[name] > 0:
            reqs.append({"marker": "verdicts", "threshold": config[name]})
    # de-duplicate by marker, keeping the strictest threshold
    best: dict[str, dict] = {}
    for r in reqs:
        cur = best.get(r["marker"])
        if cur is None or (isinstance(r["threshold"], int) and isinstance(cur["threshold"], int)
                           and r["threshold"] > cur["threshold"]):
            best[r["marker"]] = r
    return list(best.values())


# ---------------------------------------------------------------------------
# native genre (verifier.json)
# ---------------------------------------------------------------------------

WHOLE_WORKBOOK_PATHS = ("$.formula_share_all", "$.n_formula_with_refs", "$.n_cross_sheet_formula")


def analyze_native(pkg: Path) -> tuple[list[dict], bool]:
    vj = pkg / "tests" / "verifier.json"
    if not vj.is_file():
        return [], False
    try:
        data = json.loads(vj.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return [], False
    findings: list[dict] = []
    seen_any = False
    for v in data.get("verifiers", []) or []:
        meta = v.get("metadata") or {}
        tag = str(meta.get("tag", ""))
        src = ((v.get("source") or {}).get("file") or {})
        cmd = str(src.get("command", ""))
        if "formula" not in tag and "formula" not in cmd:
            continue
        seen_any = True
        assertion = v.get("assertion") or {}
        det = assertion.get("deterministic") or {}
        jpath = str(det.get("path", ""))
        args = src.get("arguments") or {}
        if jpath in WHOLE_WORKBOOK_PATHS and not args.get("sheet_name_contains"):
            findings.append(
                {
                    "verifier": v.get("name"),
                    "json_path": jpath,
                    "expected": assertion.get("expected"),
                    "weight": meta.get("weight"),
                    "detail": (
                        f"`{v.get('name')}` measures {jpath} over the WHOLE workbook "
                        f"(source command `{cmd}` carries no `sheet_name_contains` scoping), "
                        "so the denominator is unbounded: decoy formulas on an ungraded tab "
                        "raise the number and legitimate typed source data lowers it. This is "
                        "the task_145 shape."
                    ),
                }
            )
    return findings, seen_any


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------

def analyze_checker(
    checker: Path,
    pkg: Path,
    *,
    min_hops: int,
    min_coverage_ratio: float,
    max_collisions_reported: int,
    scan_inputs: bool,
) -> dict:
    out: dict = {
        "checker": str(checker.relative_to(pkg)) if checker.is_relative_to(pkg) else str(checker),
        "deliverable": None,
        "n_bands": 0,
        "n_band_labels": 0,
        "min_bands_hit": None,
        "hop_cap": None,
        "findings": [],
        "errors": [],
    }
    source = checker.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source)
    config = replay_config(tree)

    bands = parse_bands(config.get("BANDS"))
    labels = sorted({b.label for b in bands})
    out["n_bands"] = len(bands)
    out["n_band_labels"] = len(labels)
    deliverable = config.get("DELIVERABLE")
    out["deliverable"] = deliverable if isinstance(deliverable, str) else None
    abs_values = bool(config.get("ABS_VALUES", False))
    integer_only = bool(config.get("INTEGER_ONLY", False))
    exempt_raw = config.get("EXEMPT", []) or []
    exempt = [float(e) for e in exempt_raw if isinstance(e, (int, float)) and not isinstance(e, bool)]
    exempt_tol = float(config.get("EXEMPT_TOL", 1e-9) or 1e-9)
    min_bands_hit = config.get("MIN_BANDS_HIT")
    out["min_bands_hit"] = min_bands_hit if isinstance(min_bands_hit, int) else None

    # ---- 2. hop_limit_too_low (exact) -------------------------------------
    hop_cap, hop_ev = detect_hop_limit(tree, config)
    out["hop_cap"] = hop_cap
    if hop_cap is not None and hop_cap < min_hops:
        out["findings"].append(
            {
                "kind": "hop_limit_too_low",
                "severity": "fail",
                "detail": (
                    f"The reference/echo-chain follower stops after {hop_cap} hop(s) "
                    f"({hop_ev}), below the {min_hops}-hop floor. A live chain longer than "
                    f"{hop_cap} hops (task_390's real 4-hop roll-forward: "
                    "`=F8 -> =F7 -> ='3_Three_Basis'!D6 -> ='2_Liability_Curve'!G47 -> "
                    "=SUM(G7:G46)`) is scored as a typed constant, failing a correct model."
                ),
                "hop_cap": hop_cap,
                "evidence": hop_ev,
            }
        )

    # ---- 4. disguised_constant_unguarded (heuristic) -----------------------
    if bands and not detect_disguised_constant_guard(tree, source):
        out["findings"].append(
            {
                "kind": "disguised_constant_unguarded",
                "severity": "warn",
                "detail": (
                    "No identity-wrapper guard found: the checker credits any 'substantive' "
                    "formula, so a typed constant dressed as `=184627.68*1`, `=B7+0` or "
                    "`=IF(TRUE,<literal>,...)` satisfies the live-formula gate (task_388's "
                    "real defect). The template's guard follows a single-reference formula "
                    "whose cached value equals its referent's instead of crediting it."
                ),
            }
        )

    # ---- 3. per_cell_violation_counting (heuristic) ------------------------
    for pc in detect_per_cell_counting(tree):
        cap_val = config.get(pc["cap"]) if isinstance(pc["cap"], str) else pc["cap"]
        if isinstance(cap_val, int) and cap_val > 5:
            continue
        out["findings"].append(
            {
                "kind": "per_cell_violation_counting",
                "severity": "warn",
                "detail": (
                    f"`{pc['list']}` is appended once per CELL inside the cell scan and then "
                    f"compared by length against a cap of {cap_val!r} ({pc['evidence']}), with "
                    "no de-duplication by distinct (value, band) figure. One legitimately "
                    "restated figure spread across a presentation table reads as many "
                    "violations -- task_574 lost on one figure (4,140) restated in 75 cells."
                ),
                "evidence": pc["evidence"],
            }
        )

    # ---- 5. requirement_not_in_instruction (heuristic) ----------------------
    instruction = pkg / "instruction.md"
    instr_text = instruction.read_text(encoding="utf-8", errors="replace").lower() if instruction.is_file() else None
    if instr_text is None:
        out["errors"].append("instruction.md not found; requirement_not_in_instruction not evaluated")
    else:
        for req in detect_requirements(tree, config, source):
            human, vocab = REQUIREMENT_VOCAB[req["marker"]]
            if any(w in instr_text for w in vocab):
                continue
            out["findings"].append(
                {
                    "kind": "requirement_not_in_instruction",
                    "severity": "warn",
                    "detail": (
                        f"The checker requires {human} (marker `{req['marker']}`, threshold "
                        f"{req['threshold']!r}), but none of its vocabulary "
                        f"({', '.join(vocab)}) appears anywhere in instruction.md. A solver "
                        "cannot know to build a construct the prompt never asks for -- "
                        "task_559's `range_agg >= 1` is the measured instance."
                    ),
                    "marker": req["marker"],
                    "threshold": req["threshold"],
                }
            )
        for name in FORMULA_COUNT_FLOOR_NAMES:
            floor = config.get(name)
            if isinstance(floor, int) and floor >= 25 and not re.search(
                r"\b(formula|formulas|formulae|live cell|computed cell|calculated cell)", instr_text
            ):
                out["findings"].append(
                    {
                        "kind": "requirement_not_in_instruction",
                        "severity": "warn",
                        "detail": (
                            f"`{name} = {floor}` imposes a minimum live-formula count, but "
                            "instruction.md never uses the word 'formula' (or 'live cell' / "
                            "'computed cell'), so the solver is graded on a construct the "
                            "prompt does not ask for."
                        ),
                        "marker": name,
                        "threshold": floor,
                    }
                )

    # ---- 6. coverage_floor_too_shallow (heuristic) -------------------------
    if bands and isinstance(min_bands_hit, int) and labels:
        ratio = min_bands_hit / len(labels)
        if ratio < min_coverage_ratio:
            out["findings"].append(
                {
                    "kind": "coverage_floor_too_shallow",
                    "severity": "warn",
                    "detail": (
                        f"MIN_BANDS_HIT = {min_bands_hit} over {len(labels)} distinct band "
                        f"label(s) is {ratio:.0%} coverage, below the "
                        f"{min_coverage_ratio:.0%} floor: most graded figures may be typed "
                        "and the check still passes."
                    ),
                    "min_bands_hit": min_bands_hit,
                    "n_labels": len(labels),
                    "ratio": round(ratio, 3),
                }
            )
    if bands and labels and all(
        any(w in lab.lower() for w in AGGREGATE_LABEL_WORDS) for lab in labels
    ):
        out["findings"].append(
            {
                "kind": "coverage_floor_too_shallow",
                "severity": "warn",
                "detail": (
                    f"Every band label ({', '.join(labels)}) names an aggregate. Only totals "
                    "are graded for liveness, so a workbook whose entire detail grid is typed "
                    "passes provided the totals are formulas -- task_348's real defect "
                    "(4 aggregate bands, floor 2, 22 typed rows)."
                ),
                "labels": labels,
            }
        )

    # ---- 1b. unanchored_generic_band (heuristic) ---------------------------
    generic: list[dict] = []
    for b in bands:
        if b.anchor is not None:
            continue
        exempt_inside = [e for e in exempt if b.contains(abs(e) if abs_values else e)]
        if b.is_date_window and b.width > 2:
            generic.append(
                {
                    "band": b.as_dict(),
                    "why": f"date-serial window {b.width:.0f} days wide with no row anchor",
                    "exempt_inside": exempt_inside,
                }
            )
            continue
        lo_a, hi_a = abs(b.lo), abs(b.hi)
        contains_int = _band_contains_integer(b)
        if hi_a <= 100 and contains_int:
            # task_218 (13 / 11 / 20 / 30 quantities) and task_470 (an option-value band
            # [17.6, 19.7] that swallows an agent's typed trial-grid levels 18 and 19).
            generic.append(
                {
                    "band": b.as_dict(),
                    "why": f"small-magnitude band [{b.lo:g}, {b.hi:g}] spanning a whole "
                           "number, with no row anchor",
                    "exempt_inside": exempt_inside,
                }
            )
        elif 0.0 <= b.lo and hi_a <= 1.0:
            # task_470's n_d1 band [0.683, 0.701] -- the unit interval is where every ratio,
            # probability, percentage-as-decimal and volatility level in a model lives.
            generic.append(
                {
                    "band": b.as_dict(),
                    "why": f"unit-interval band [{b.lo:g}, {b.hi:g}] (ratios, probabilities "
                           "and decimal percentages all live here) with no row anchor",
                    "exempt_inside": exempt_inside,
                }
            )
    if generic:
        corroborated = [g for g in generic if g["exempt_inside"]]
        out["findings"].append(
            {
                "kind": "unanchored_generic_band",
                "severity": "warn",
                "detail": (
                    f"{len(generic)} band(s) have no exclusionary row anchor and a range "
                    "generic enough for ordinary deliverable content to land in: "
                    + "; ".join(f"{g['band']['label']} ({g['why']})" for g in generic[:6])
                    + (
                        f". {len(corroborated)} of them already carry EXEMPT entries INSIDE "
                        "the band, which is the author conceding that unrelated values do "
                        "collide there -- exactly task_218, where an agent's Action-Plan due "
                        "dates 2026-08-20/22/23 fell in an 11-day unanchored date window and "
                        "cost the full 0.10 on a workbook with 674 live formulas."
                        if corroborated else ""
                    )
                ),
                "bands": generic[:20],
                "n_generic_bands": len(generic),
                "n_corroborated": len(corroborated),
            }
        )

    # ---- 1a. band_collision (exact value scan) -----------------------------
    if bands and scan_inputs:
        collisions: list[dict] = []
        scanned_values = 0

        def _record(origin: str, locator: str, value, hits: list[Band], typed: bool) -> None:
            collisions.append(
                {
                    "origin": origin,
                    "where": locator,
                    "value": value if isinstance(value, (int, float, str)) else str(value),
                    "numeric": to_number(value),
                    "bands": [b.label for b in hits],
                    "typed": typed,
                }
            )

        for src in find_environment_inputs(pkg):
            if src.suffix.lower() in {".xlsx", ".xlsm"}:
                try:
                    for sheet, coord, value, rowtext, _isf in _xlsx_values(src, with_formulas=False):
                        scanned_values += 1
                        hits = band_hits(value, bands, abs_values=abs_values,
                                         integer_only=integer_only, exempt=exempt,
                                         exempt_tol=exempt_tol, rowtext=rowtext)
                        if hits:
                            _record("environment", f"{src.name}!{sheet}!{coord}", value, hits, True)
                except Exception as e:
                    out["errors"].append(f"could not scan input {src.name}: {e}")
            else:
                try:
                    for locator, value, rowtext in _text_numbers(src):
                        scanned_values += 1
                        hits = band_hits(value, bands, abs_values=abs_values,
                                         integer_only=integer_only, exempt=exempt,
                                         exempt_tol=exempt_tol, rowtext=rowtext)
                        if hits and not _date_context_noise(value, rowtext):
                            _record("environment", f"{src.name}:{locator}", value, hits, True)
                except Exception as e:
                    out["errors"].append(f"could not scan input {src.name}: {e}")

        for golden in find_golden_workbooks(pkg, out["deliverable"]):
            try:
                for sheet, coord, value, rowtext, is_formula in _xlsx_values(golden, with_formulas=True):
                    scanned_values += 1
                    if is_formula:
                        continue  # the golden's own live derivations are the intended hits
                    hits = band_hits(value, bands, abs_values=abs_values,
                                     integer_only=integer_only, exempt=exempt,
                                     exempt_tol=exempt_tol, rowtext=rowtext)
                    if hits:
                        _record("golden", f"{golden.name}!{sheet}!{coord}", value, hits, True)
            except Exception as e:
                out["errors"].append(f"could not scan golden {golden.name}: {e}")

        out["n_values_scanned"] = scanned_values
        if collisions:
            by_band: dict[str, int] = {}
            for c in collisions:
                for lab in c["bands"]:
                    by_band[lab] = by_band.get(lab, 0) + 1
            examples = "; ".join(
                f"{c['where']} = {c['value']!r} -> band {'/'.join(c['bands'])} [{c['origin']}]"
                for c in collisions[:max_collisions_reported]
            )
            out["findings"].append(
                {
                    "kind": "band_collision",
                    "severity": "fail",
                    "detail": (
                        f"{len(collisions)} value(s) that genuinely exist in this task's own "
                        "inputs or are TYPED constants in its golden deliverable fall inside a "
                        "band and are not EXEMPT: "
                        + examples
                        + (f" (+{len(collisions) - max_collisions_reported} more)"
                           if len(collisions) > max_collisions_reported else "")
                        + ". A solver that transcribes or restates any of these -- which for an "
                        "environment input the instruction usually TELLS them to do (task_462) "
                        "-- is scored as having typed a graded answer. Either anchor the band, "
                        "add the value to EXEMPT, or narrow the range."
                    ),
                    "n_collisions": len(collisions),
                    "by_band": by_band,
                    "collisions": collisions[:max_collisions_reported],
                }
            )

    return out


def analyze_task(
    task_dir: Path,
    *,
    min_hops: int = DEFAULT_MIN_HOPS,
    min_coverage_ratio: float = DEFAULT_MIN_COVERAGE_RATIO,
    gate_kinds: tuple[str, ...] = DEFAULT_GATE_KINDS,
    max_collisions_reported: int = 25,
    scan_inputs: bool = True,
) -> dict:
    """One result dict for one task. Never raises."""
    result: dict = {
        "task_id": task_dir.name,
        "package_root": None,
        "genre": None,
        "checkers": [],
        "findings": [],
        "n_findings": 0,
        "status": None,
        "errors": [],
    }
    pkg = resolve_package_root(task_dir)
    if pkg is None:
        result["status"] = "skip"
        result["errors"].append(
            f"no `tests/` directory found under {task_dir} (not a task package layout this "
            "check recognises), so there is no formula-provenance checker to lint"
        )
        return result
    result["package_root"] = str(pkg)

    checkers = find_checkers(pkg)
    native_findings, native_seen = analyze_native(pkg)

    if not checkers and not native_seen:
        result["status"] = "skip"
        result["errors"].append(
            "this task ships no formula-provenance checker: no "
            "`tests/deliverables_*/check_formula_provenance*.py` and no "
            "`formula_authenticity`-tagged assertion in tests/verifier.json"
        )
        return result

    result["genre"] = "rewardkit" if checkers else "native"

    for checker in checkers:
        try:
            info = analyze_checker(
                checker, pkg,
                min_hops=min_hops,
                min_coverage_ratio=min_coverage_ratio,
                max_collisions_reported=max_collisions_reported,
                scan_inputs=scan_inputs,
            )
        except SyntaxError as e:
            result["errors"].append(f"{checker.name}: could not parse: {e}")
            continue
        except Exception as e:
            result["errors"].append(f"{checker.name}: unhandled error: {e}")
            continue
        result["checkers"].append(info)
        for f in info["findings"]:
            f = dict(f)
            f["checker"] = info["checker"]
            result["findings"].append(f)
        result["errors"].extend(f"{checker.name}: {m}" for m in info["errors"])

    for nf in native_findings:
        result["findings"].append(
            {
                "kind": "coverage_floor_too_shallow",
                "severity": "warn",
                "checker": "tests/verifier.json",
                "detail": nf["detail"],
                "verifier": nf["verifier"],
                "json_path": nf["json_path"],
                "expected": nf["expected"],
                "weight": nf["weight"],
            }
        )

    result["n_findings"] = len(result["findings"])
    if result["errors"] and not result["checkers"] and not native_findings:
        result["status"] = "error"
        return result
    if any(f["kind"] in gate_kinds for f in result["findings"]):
        result["status"] = "fail"
    elif result["findings"]:
        result["status"] = "warn"
    else:
        result["status"] = "pass"
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

HOW_TO_READ_THIS_REPORT = {
    "purpose": (
        "Static lint of a task's OWN per-task formula-provenance checker "
        "(tests/deliverables_*/check_formula_provenance.py) or its native "
        "formula_authenticity assertions. Built from 9 measured defects in a 30-task fix "
        "session on 2026-09-22. It never runs the checker."
    ),
    "task_status": {
        "fail": "At least one GATE-READY finding (band_collision, hop_limit_too_low).",
        "warn": "Report-only findings only -- read them, do not treat them as a verdict.",
        "pass": "A formula-provenance checker was found and parsed; nothing fired.",
        "skip": "The task genuinely ships no formula-provenance checker.",
        "error": "A checker exists but could not be parsed.",
    },
    "gate_ready_kinds": list(DEFAULT_GATE_KINDS),
    "report_only_kinds": [k for k in ALL_KINDS if k not in DEFAULT_GATE_KINDS],
    "finding_kinds": {
        "band_collision": (
            "EXACT value scan: a value in the task's own environment inputs, or a typed "
            "constant in its golden deliverable, falls inside a band and is not EXEMPT."
        ),
        "unanchored_generic_band": (
            "HEURISTIC: an unanchored date-serial window >2 days wide, or an unanchored "
            "small-integer band -- the task_218 class, corroborated when EXEMPT already "
            "lists values inside the same band."
        ),
        "hop_limit_too_low": (
            "EXACT: the echo/reference-chain follower's recursion cap read off the AST is "
            "below --min-hops (default 8). task_390 lost 0.10 to a 3-hop cap."
        ),
        "per_cell_violation_counting": (
            "HEURISTIC: a per-cell violation list compared by len() against a small cap "
            "with no de-duplication by distinct figure."
        ),
        "disguised_constant_unguarded": (
            "HEURISTIC: no guard for `=<literal>*1` / `=<literal>+0` identity wrappers."
        ),
        "requirement_not_in_instruction": (
            "HEURISTIC: the checker requires a construct whose whole vocabulary is absent "
            "from instruction.md."
        ),
        "coverage_floor_too_shallow": (
            "HEURISTIC: MIN_BANDS_HIT below --min-coverage-ratio of the distinct band "
            "labels, all-aggregate band labels, or (native genre) a whole-workbook "
            "formula-share/count assertion with no sheet scoping."
        ),
    },
    "the_one_thing_this_check_cannot_see": (
        "Whether the golden or any real agent workbook actually passes the checker. This "
        "is a static lint; it never executes the task's checker, so a band collision that "
        "arises only in an agent's own output (task_218's real losing cells) is visible to "
        "it only through the `unanchored_generic_band` proxy."
    ),
}


def find_task_dirs(root: Path, task_ids=None, id_prefix: str = "") -> list[Path]:
    if task_ids:
        dirs = []
        for tid in task_ids:
            p = root / tid
            if not p.is_dir():
                print(f"WARNING: task dir not found, skipping: {p}", file=sys.stderr)
                continue
            dirs.append(p)
        return dirs
    return sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith(id_prefix))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Formula-provenance checker lint: static defects in a task's own "
            "check_formula_provenance.py (band collisions, hop-limit caps, per-cell "
            "violation counting, unguarded disguised constants, unanchored requirements, "
            "shallow coverage floors)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("task_ids", nargs="*", help="one or more task ids")
    ap.add_argument("--all", action="store_true", help="run every task under --root")
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--id-prefix", default="")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--min-hops", type=int, default=DEFAULT_MIN_HOPS)
    ap.add_argument("--min-coverage-ratio", type=float, default=DEFAULT_MIN_COVERAGE_RATIO)
    ap.add_argument(
        "--gate",
        default=",".join(DEFAULT_GATE_KINDS),
        help="comma-separated finding kinds that set status=fail (default: the two "
             "gate-ready kinds). Pass an empty string to make the whole check report-only.",
    )
    ap.add_argument("--no-scan-inputs", action="store_true",
                    help="skip the band_collision value scan (fast AST-only mode)")
    args = ap.parse_args()

    if args.root is None:
        ap.error("--root is required")
    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")
    if not args.root.is_dir():
        print(f"--root does not exist or is not a directory: {args.root}", file=sys.stderr)
        return 2

    gate_kinds = tuple(k.strip() for k in args.gate.split(",") if k.strip())
    task_dirs = find_task_dirs(args.root, None if args.all else args.task_ids, id_prefix=args.id_prefix)
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        return 2

    results = []
    for i, task_dir in enumerate(task_dirs, 1):
        print(f"[{i}/{len(task_dirs)}] {task_dir.name} ...", file=sys.stderr)
        try:
            r = analyze_task(
                task_dir,
                min_hops=args.min_hops,
                min_coverage_ratio=args.min_coverage_ratio,
                gate_kinds=gate_kinds,
                scan_inputs=not args.no_scan_inputs,
            )
        except Exception as e:
            r = {
                "task_id": task_dir.name, "status": "error",
                "errors": [f"unhandled exception: {e}"], "package_root": None,
                "genre": None, "checkers": [], "findings": [], "n_findings": 0,
            }
        results.append(r)
        kinds = sorted({f["kind"] for f in r.get("findings", [])})
        print(f"    -> {r['status']}" + (f": {', '.join(kinds)}" if kinds else ""), file=sys.stderr)

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    finding_counts: dict[str, int] = {}
    for r in results:
        for f in r.get("findings", []):
            finding_counts[f["kind"]] = finding_counts.get(f["kind"], 0) + 1

    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "id_prefix": args.id_prefix,
        "gate_kinds": list(gate_kinds),
        "min_hops": args.min_hops,
        "min_coverage_ratio": args.min_coverage_ratio,
        "n_tasks": len(results),
        "status_counts": counts,
        "finding_counts": finding_counts,
        "how_to_read_this_report": HOW_TO_READ_THIS_REPORT,
        "results": results,
    }

    width = max((len(r["task_id"]) for r in results), default=8)
    print(f"\n{'task':<{width}}  {'status':<6}  findings")
    print(f"{'-' * width}  {'-' * 6}  {'-' * 40}")
    for r in results:
        kinds = sorted({f["kind"] for f in r.get("findings", [])})
        print(f"{r['task_id']:<{width}}  {r['status']:<6}  {', '.join(kinds) or '-'}")
    print(f"\n{len(results)} task(s) checked.")
    print("status counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if finding_counts:
        print("finding counts: " + ", ".join(f"{k}={v}" for k, v in sorted(finding_counts.items())))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, default=str)
        print(f"\nWrote {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
