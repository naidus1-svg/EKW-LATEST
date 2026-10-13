#!/usr/bin/env python3
"""Tests for formula_provenance_lint.py.

The two named regression fixtures required by the defect list are pinned twice over:
once as a self-contained synthetic package built from the REAL CONFIG block of the task
(so the test runs anywhere), and once against the real corpus when it happens to be
present on this machine (skipped otherwise).

  - task_218: an unanchored 11-day date-serial window (`invar_exp_arrival`, 46251..46262)
    whose own EXEMPT list already contains three values inside it -> unanchored_generic_band.
  - task_390: `live(key, depth=0)` with `if not f or depth > 3` -> hop_limit_too_low, and
    the post-fix `depth > MAX_ECHO_DEPTH` with MAX_ECHO_DEPTH = 8 -> no finding.
"""

from __future__ import annotations

import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from formula_provenance_lint import (  # noqa: E402
    Band,
    analyze_task,
    detect_hop_limit,
    parse_bands,
    replay_config,
    to_number,
)

import ast  # noqa: E402

REAL_CORPUS = Path(
    "/Users/luiz.araujo/Claude/Projects/gdpval-qc/dataos_qc_runs/74-ekw-sprint/"
    "qcr_21092026/incoming"
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

TEMPLATE_BODY = '''
import re
from pathlib import Path

import rewardkit as rk

_SINGLE = re.compile(r"x")
_FUNC = re.compile(r"y")


@rk.criterion(description="live-formula check")
def formula_provenance(workspace: Path) -> bool:
    import openpyxl

    formulas = {}

    def _cached(key):
        return None

    def live(key, depth=0):
        f = formulas.get(key)
        if not f or depth > HOP:
            return False
        refs = _SINGLE.findall(f[1:])
        if len(refs) == 1 and not _FUNC.search(f[1:]):
            a, b = _cached(key), _cached(refs[0])
            if a == b:
                return live(refs[0], depth + 1)
        return True

    typed_hits = []
    for key in formulas:
        typed_hits.append((key, 1, ["lab"]))
    if len(typed_hits) > MAX_UNCACHED_RESTATEMENTS:
        return False
    return True
'''


def write_package(
    tmp: Path,
    *,
    task_id: str = "task_x",
    config: str,
    instruction: str = "Produce a workbook. Every derived figure must be a live formula.",
    body: str = TEMPLATE_BODY,
    inputs: dict[str, list[list]] | None = None,
) -> Path:
    task = tmp / task_id
    (task / "tests" / "deliverables_01").mkdir(parents=True)
    (task / "environment" / "initial_workspace").mkdir(parents=True)
    (task / "solution" / "files").mkdir(parents=True)
    (task / "instruction.md").write_text(instruction, encoding="utf-8")
    (task / "tests" / "deliverables_01" / "check_formula_provenance.py").write_text(
        textwrap.dedent(config) + body, encoding="utf-8"
    )
    if inputs:
        from openpyxl import Workbook

        for name, rows in inputs.items():
            wb = Workbook()
            ws = wb.active
            ws.title = "Sheet1"
            for r in rows:
                ws.append(r)
            wb.save(task / "environment" / "initial_workspace" / name)
    return task


def kinds(result: dict) -> set[str]:
    return {f["kind"] for f in result["findings"]}


# ---------------------------------------------------------------------------
# unit-level: config replay and band parsing
# ---------------------------------------------------------------------------

def test_replay_config_handles_comprehensions_and_concatenation() -> None:
    """task_390's real CONFIG builds BANDS from a comprehension over `_M` and EXEMPT from
    a list concatenation with `list(range(1, 41))`. A literal_eval-only parser cannot read
    either; the restricted replay must."""
    src = textwrap.dedent(
        """
        import re
        _M = [("pbo", 1380.0, 1420.0)]
        BANDS = (
            [(l, lo, hi) for l, lo, hi in _M]
            + [(l, lo * 1e3, hi * 1e3) for l, lo, hi in _M]
            + [("duration", 10.0, 12.0)]
        )
        EXEMPT = [1400.0] + list(range(1, 41))
        _NOT_SAFE = re.compile(r"x")
        MIN_BANDS_HIT = 7
        """
    )
    cfg = replay_config(ast.parse(src))
    assert len(cfg["BANDS"]) == 3
    assert cfg["MIN_BANDS_HIT"] == 7
    assert 1400.0 in cfg["EXEMPT"] and 40 in cfg["EXEMPT"]
    assert "_NOT_SAFE" not in cfg, "re.compile must not be replayed"


def test_replay_config_never_runs_the_criterion() -> None:
    """The replay must not import rewardkit/openpyxl or execute a decorated function."""
    src = textwrap.dedent(
        """
        import rewardkit as rk
        BANDS = [("a", 1.0, 2.0)]

        @rk.criterion(description="x")
        def formula_provenance(workspace):
            raise AssertionError("the criterion body must never run")
        """
    )
    cfg = replay_config(ast.parse(src))
    assert cfg["BANDS"] == [("a", 1.0, 2.0)]
    assert "formula_provenance" not in cfg


def test_parse_bands_reads_three_and_four_tuples() -> None:
    bands = parse_bands([("a", 1, 2), ("b", 3, 4, "PN123"), "junk", ("c",)])
    assert [b.label for b in bands] == ["a", "b"]
    assert bands[1].anchor == "PN123"


def test_to_number_reads_excel_date_serials_and_formatted_strings() -> None:
    import datetime

    assert to_number(datetime.date(2026, 8, 20)) == 46254.0
    assert to_number("4,140") == 4140.0
    assert to_number("(1,200)") == -1200.0
    assert to_number("not a number") is None


# ---------------------------------------------------------------------------
# task_390 regression: hop_limit_too_low
# ---------------------------------------------------------------------------

TASK_390_CONFIG_PREFIX = """
DELIVERABLE = "pension_derisking_model.xlsx"
_M = [
    ("pbo", 1380.0, 1420.0),
    ("funding_liability", 1279.0, 1339.0),
    ("settlement_liability", 1509.0, 1569.0),
]
BANDS = (
    [(l, lo, hi) for l, lo, hi in _M]
    + [(l, lo * 1e3, hi * 1e3) for l, lo, hi in _M]
    + [("buyout_premium", 725.0, 745.0)]
)
ABS_VALUES = True
EXEMPT = [1400.0]
EXEMPT_TOL = 1e-9
MIN_BANDS_HIT = 4
MIN_SUBSTANTIVE = 60
MAX_UNCACHED_RESTATEMENTS = 50
HOP = 3
"""


def test_task_390_three_hop_cap_is_flagged() -> None:
    """The measured defect: a 3-hop follower scored task_390's real 4-hop live chain
    (`=F8 -> =F7 -> ='3_Three_Basis'!D6 -> ='2_Liability_Curve'!G47 -> =SUM(G7:G46)`)
    as a typed constant. 460 live formulas, 0 on a 0.10 check."""
    with tempfile.TemporaryDirectory() as td:
        task = write_package(Path(td), config=TASK_390_CONFIG_PREFIX)
        result = analyze_task(task)
    assert result["status"] == "fail"
    assert "hop_limit_too_low" in kinds(result)
    hop = next(f for f in result["findings"] if f["kind"] == "hop_limit_too_low")
    assert hop["hop_cap"] == 3
    assert hop["severity"] == "fail"


def test_task_390_post_fix_named_depth_constant_is_not_flagged() -> None:
    """The real post-fix package replaced the literal with `depth > MAX_ECHO_DEPTH`; the
    detector must resolve the name through the replayed CONFIG, not report `skip`."""
    body = TEMPLATE_BODY.replace("depth > HOP", "depth > MAX_ECHO_DEPTH")
    cfg = TASK_390_CONFIG_PREFIX + "\nMAX_ECHO_DEPTH = 8\n"
    with tempfile.TemporaryDirectory() as td:
        task = write_package(Path(td), config=cfg, body=body)
        result = analyze_task(task)
    assert "hop_limit_too_low" not in kinds(result)


def test_hop_limit_reads_gte_form() -> None:
    src = textwrap.dedent(
        """
        def live(key, depth=0):
            if depth >= 4:
                return False
            return live(key, depth + 1)
        """
    )
    cap, ev = detect_hop_limit(ast.parse(src), {})
    assert cap == 3
    assert "depth >= 4" in ev


def test_hop_limit_ignores_a_non_recursive_function() -> None:
    src = "def f(depth=0):\n    return depth > 3\n"
    cap, _ = detect_hop_limit(ast.parse(src), {})
    assert cap is None


# ---------------------------------------------------------------------------
# task_218 regression: unanchored generic bands + band_collision
# ---------------------------------------------------------------------------

TASK_218_CONFIG = """
DELIVERABLE = "tooling_material_plan.xlsx"
BANDS = [
    ("invar_net_gap_ft", 13.0, 13.0, "C4B8A0"),
    ("pad_firm_supply_ea", 20.0, 20.0, "E7C302"),
    ("machining_gap_value", 53340.0, 53360.0, None),
    ("invar_std_arrival", 46293.0, 46304.0, None),
    ("invar_exp_arrival", 46251.0, 46262.0, None),
]
ABS_VALUES = True
EXEMPT = [46253.0, 46258.0, 46262.0, 46295.0, 46300.0]
EXEMPT_TOL = 1e-9
MIN_BANDS_HIT = 5
MIN_SUBSTANTIVE = 10
MAX_UNCACHED_RESTATEMENTS = 50
HOP = 3
"""


def test_task_218_unanchored_date_window_is_flagged_and_corroborated() -> None:
    """The measured defect: `invar_exp_arrival` is an 11-day date-serial window with no
    row anchor. An agent's ordinary Action-Plan due dates (2026-08-20/22/23 -> serials
    46254/46256/46257) landed in it; the workbook had 674 live formulas and lost 0.10.
    The checker's own EXEMPT list already carried three serials inside the same window,
    which is the author conceding the collision."""
    with tempfile.TemporaryDirectory() as td:
        task = write_package(Path(td), config=TASK_218_CONFIG)
        result = analyze_task(task)
    assert "unanchored_generic_band" in kinds(result)
    f = next(x for x in result["findings"] if x["kind"] == "unanchored_generic_band")
    labels = {b["band"]["label"] for b in f["bands"]}
    assert {"invar_std_arrival", "invar_exp_arrival"} <= labels
    assert f["n_corroborated"] >= 2, "EXEMPT entries sit inside the flagged windows"
    # anchored small-integer bands must NOT be flagged -- the anchor is the cure
    assert "invar_net_gap_ft" not in labels
    assert "pad_firm_supply_ea" not in labels
    assert f["severity"] == "warn", "report-only, never gates"


def test_band_collision_fires_on_a_real_environment_input() -> None:
    """The task_348/task_462 shape, mechanised: a value the instruction tells the solver
    to transcribe sits inside a band, so typing it is scored as typing a graded answer."""
    cfg = """
    DELIVERABLE = "plan.xlsx"
    BANDS = [("total_extended_cost", 29136.90, 29196.90)]
    ABS_VALUES = True
    EXEMPT = []
    EXEMPT_TOL = 1e-9
    MIN_BANDS_HIT = 1
    MIN_SUBSTANTIVE = 10
    MAX_UNCACHED_RESTATEMENTS = 50
    HOP = 8
    """
    with tempfile.TemporaryDirectory() as td:
        task = write_package(
            Path(td),
            config=cfg,
            inputs={"prices.xlsx": [["SKU", "cost"], ["A-1", 29166.90], ["A-2", 12.0]]},
        )
        result = analyze_task(task)
    assert result["status"] == "fail"
    assert "band_collision" in kinds(result)
    f = next(x for x in result["findings"] if x["kind"] == "band_collision")
    assert f["n_collisions"] == 1
    assert f["collisions"][0]["numeric"] == pytest.approx(29166.90)
    assert f["collisions"][0]["origin"] == "environment"


def test_band_collision_respects_exempt_and_anchors() -> None:
    cfg = """
    DELIVERABLE = "plan.xlsx"
    BANDS = [("gap", 13.0, 13.0, "C4B8A0"), ("cost", 29136.90, 29196.90, None)]
    ABS_VALUES = True
    EXEMPT = [29166.90]
    EXEMPT_TOL = 1e-9
    MIN_BANDS_HIT = 1
    MIN_SUBSTANTIVE = 10
    MAX_UNCACHED_RESTATEMENTS = 50
    HOP = 8
    """
    with tempfile.TemporaryDirectory() as td:
        task = write_package(
            Path(td),
            config=cfg,
            # 13 sits in the anchored band but its row never names the anchor PN
            inputs={"stock.xlsx": [["part", "qty"], ["WIDGET-9", 13], ["x", 29166.90]]},
        )
        result = analyze_task(task)
    assert "band_collision" not in kinds(result)


# ---------------------------------------------------------------------------
# other detectors
# ---------------------------------------------------------------------------

def test_per_cell_violation_counting_is_flagged() -> None:
    """task_574: one legitimately restated figure (4,140) across 75 presentation cells
    read as 75 violations against a cap of 1."""
    cfg = TASK_390_CONFIG_PREFIX.replace(
        "MAX_UNCACHED_RESTATEMENTS = 50", "MAX_UNCACHED_RESTATEMENTS = 1"
    ).replace("HOP = 3", "HOP = 8")
    with tempfile.TemporaryDirectory() as td:
        task = write_package(Path(td), config=cfg)
        result = analyze_task(task)
    assert "per_cell_violation_counting" in kinds(result)
    f = next(x for x in result["findings"] if x["kind"] == "per_cell_violation_counting")
    assert f["severity"] == "warn", "report-only"


def test_disguised_constant_guard_present_is_not_flagged() -> None:
    with tempfile.TemporaryDirectory() as td:
        task = write_package(Path(td), config=TASK_218_CONFIG)
        result = analyze_task(task)
    assert "disguised_constant_unguarded" not in kinds(result)


def test_disguised_constant_guard_absent_is_flagged() -> None:
    """task_388's shape: credit any substantive formula, so `=184627.68*1` passes."""
    body = TEMPLATE_BODY.replace(
        "        refs = _SINGLE.findall(f[1:])\n"
        "        if len(refs) == 1 and not _FUNC.search(f[1:]):\n"
        "            a, b = _cached(key), _cached(refs[0])\n"
        "            if a == b:\n"
        "                return live(refs[0], depth + 1)\n",
        "",
    )
    with tempfile.TemporaryDirectory() as td:
        task = write_package(Path(td), config=TASK_218_CONFIG, body=body)
        result = analyze_task(task)
    assert "disguised_constant_unguarded" in kinds(result)


def test_coverage_floor_too_shallow_on_all_aggregate_labels() -> None:
    """task_348: 4 aggregate-total bands with a floor of 2, so all 22 detail rows may be
    typed provided the totals are live."""
    cfg = """
    DELIVERABLE = "disposition_workbook.xlsx"
    BANDS = [
        ("total_extended_cost", 29136.90, 29196.90),
        ("at_risk_seasonal_total", 21966.80, 21968.80),
        ("halloween_subtotal", 16025.13, 16027.13),
        ("fall_harvest_subtotal", 5940.67, 5942.67),
    ]
    ABS_VALUES = True
    EXEMPT = []
    EXEMPT_TOL = 1e-9
    MIN_BANDS_HIT = 2
    MIN_SUBSTANTIVE = 10
    MAX_UNCACHED_RESTATEMENTS = 50
    HOP = 8
    """
    with tempfile.TemporaryDirectory() as td:
        task = write_package(Path(td), config=cfg)
        result = analyze_task(task)
    assert "coverage_floor_too_shallow" in kinds(result)
    assert result["status"] == "warn", "report-only kinds must never set fail"


def test_requirement_not_in_instruction_on_range_agg() -> None:
    """task_559: `range_agg >= 1` requires a colon-range aggregating function that appears
    nowhere in instruction.md."""
    body = TEMPLATE_BODY.replace(
        "    return True\n",
        "    range_agg = 0\n    return range_agg >= 1\n",
    )
    cfg = TASK_218_CONFIG.replace("HOP = 3", "HOP = 8")
    with tempfile.TemporaryDirectory() as td:
        task = write_package(
            Path(td),
            config=cfg,
            body=body,
            instruction="Produce a schedule of held serials. Use live formulas.",
        )
        result = analyze_task(task)
    assert "requirement_not_in_instruction" in kinds(result)


def test_requirement_anchored_in_instruction_is_not_flagged() -> None:
    body = TEMPLATE_BODY.replace(
        "    return True\n",
        "    range_agg = 0\n    return range_agg >= 1\n",
    )
    cfg = TASK_218_CONFIG.replace("HOP = 3", "HOP = 8")
    with tempfile.TemporaryDirectory() as td:
        task = write_package(
            Path(td),
            config=cfg,
            body=body,
            instruction="Total the column with a SUMIF formula over the cell range.",
        )
        result = analyze_task(task)
    assert "requirement_not_in_instruction" not in kinds(result)


def test_skip_when_no_formula_provenance_checker() -> None:
    with tempfile.TemporaryDirectory() as td:
        task = Path(td) / "task_none"
        (task / "tests").mkdir(parents=True)
        (task / "instruction.md").write_text("do a thing", encoding="utf-8")
        result = analyze_task(task)
    assert result["status"] == "skip"
    assert "ships no formula-provenance checker" in " ".join(result["errors"])


def test_gate_kinds_are_configurable() -> None:
    with tempfile.TemporaryDirectory() as td:
        task = write_package(Path(td), config=TASK_390_CONFIG_PREFIX)
        gated = analyze_task(task)
        ungated = analyze_task(task, gate_kinds=())
    assert gated["status"] == "fail"
    assert ungated["status"] == "warn"


# ---------------------------------------------------------------------------
# real-corpus regressions (skipped when the corpus is not on this machine)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not REAL_CORPUS.is_dir(), reason="real EKW corpus not present")
def test_real_task_218_baseline_is_flagged() -> None:
    result = analyze_task(REAL_CORPUS / "task_218")
    assert result["genre"] == "rewardkit"
    assert "unanchored_generic_band" in kinds(result)
    assert "hop_limit_too_low" in kinds(result)


@pytest.mark.skipif(not REAL_CORPUS.is_dir(), reason="real EKW corpus not present")
def test_real_task_390_baseline_has_a_three_hop_cap() -> None:
    result = analyze_task(REAL_CORPUS / "task_390")
    hop = next(f for f in result["findings"] if f["kind"] == "hop_limit_too_low")
    assert hop["hop_cap"] == 3


@pytest.mark.skipif(not REAL_CORPUS.is_dir(), reason="real EKW corpus not present")
def test_real_nine_known_bad_baselines_all_report_findings() -> None:
    known_bad = [
        "task_218", "task_559", "task_462", "task_470", "task_574",
        "task_390", "task_388", "task_348", "task_145",
    ]
    for tid in known_bad:
        r = analyze_task(REAL_CORPUS / tid)
        assert r["status"] in {"fail", "warn"}, f"{tid} reported {r['status']}"
        assert r["findings"], f"{tid} produced no findings"
