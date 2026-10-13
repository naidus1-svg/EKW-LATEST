#!/usr/bin/env python3
"""Unit tests for task_metadata_completeness_check.py.

Tests the check against synthetic task directories written to a temp dir, using
the REAL task.toml shapes found in this worktree as fixtures:

  - Empty-metadata shape (SVC-PC real): `category = "SVC-PC"`, `tags = []`, and
    nothing else under [metadata] (confirmed on svc-task-samples-56/SVC-PC-12-6-0
    and three siblings). Should produce 5 metadata_field_missing findings, one
    per absent descriptive field, status=warn.
  - Complete-metadata shape (EKW real): all five fields (domain, occupation,
    sector, subdomain, task_type) present and non-empty (confirmed on
    ekw-task-samples/task_175-full-for-verifier-execution). Should produce 0
    findings, status=pass.

Plus edge cases: partial metadata, empty-string field, whitespace-only field,
missing task.toml, unparseable task.toml, no [metadata] table at all, and a
non-task directory. No real corpus is needed; all fixtures are written into a
temp directory and fed to check_task directly.

Run:
    python deterministic-checks/task_metadata_completeness_check_test.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from task_metadata_completeness_check import (
    REQUIRED_METADATA_FIELDS,
    check_task,
)


# Real EKW complete-metadata task.toml (ekw-task-samples/task_175...).
COMPLETE_TOML = """\
schema_version = "1.1"

[task]
name = "ekw/project-meridian-ipo-pricing"

[metadata]
tags = []
domain = "Financial & Investment"
occupation = "Financial & Investment Analysts"
sector = "Finance and Insurance"
subdomain = "ECM"
task_type = "IPO valuation and pricing recommendation"
"""

# Real SVC-PC empty-metadata task.toml (svc-task-samples-56/SVC-PC-12-6-0).
EMPTY_TOML = """\
schema_version = "1.1"

[task]
name = "svc/svc-pc-12-6-0"

[metadata]
category = "SVC-PC"
tags = []
# Only platform-recognized [metadata] fields emitted (category, tags).
"""

# Partial: domain + occupation present, sector/subdomain/task_type missing.
PARTIAL_TOML = """\
schema_version = "1.1"

[task]
name = "svc/svc-pc-99-9-9"

[metadata]
category = "SVC-PC"
tags = []
domain = "Healthcare"
occupation = "Registered Nurses"
"""

# task.toml with no [metadata] table at all.
NO_METADATA_TABLE_TOML = """\
schema_version = "1.1"

[task]
name = "svc/svc-pc-99-9-8"
"""


def _make_task(tmp: Path, tid: str, toml_text: str | None) -> Path:
    """Create a task dir under tmp. If toml_text is None, write no task.toml but
    drop an instruction.md so the dir is still recognized as a task."""
    d = tmp / tid
    d.mkdir(parents=True, exist_ok=True)
    if toml_text is None:
        (d / "instruction.md").write_text("placeholder instruction", encoding="utf-8")
    else:
        (d / "task.toml").write_text(toml_text, encoding="utf-8")
    return d


def _warn_kinds(res: dict) -> list[str]:
    return [f["field"] for f in res["findings"] if f["severity"] == "warn"]


def test_complete_metadata_no_findings():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_task(Path(tmp), "task_complete", COMPLETE_TOML)
        res = check_task(d)
        assert res["status"] == "pass", f"expected pass, got {res['status']}"
        assert res["n_warn"] == 0, f"expected 0 warn, got {res['n_warn']}: {res['findings']}"
        assert res["findings"] == [], f"expected no findings, got {res['findings']}"
        assert sorted(res["metadata_present_fields"]) == sorted(REQUIRED_METADATA_FIELDS)
        print("  test_complete_metadata_no_findings: PASS (complete -> pass, 0 findings)")


def test_empty_metadata_real_shape_5_findings():
    """The real SVC-PC shape: category + tags only, all 5 descriptive fields
    absent. One finding per missing field, status=warn."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_task(Path(tmp), "task_empty", EMPTY_TOML)
        res = check_task(d)
        assert res["status"] == "warn", f"expected warn, got {res['status']}"
        assert res["n_warn"] == 5, f"expected 5 warn, got {res['n_warn']}: {res['findings']}"
        missing = _warn_kinds(res)
        assert sorted(missing) == sorted(REQUIRED_METADATA_FIELDS), (
            f"expected all 5 fields flagged, got {sorted(missing)}"
        )
        # every finding is the right kind
        for f in res["findings"]:
            assert f["kind"] == "metadata_field_missing", f"wrong kind: {f['kind']}"
            assert f["severity"] == "warn"
        # category and tags are NOT flagged (they are present)
        flagged = {f["field"] for f in res["findings"]}
        assert "category" not in flagged and "tags" not in flagged
        print("  test_empty_metadata_real_shape_5_findings: PASS (empty -> warn, 5 findings, one per field)")


def test_partial_metadata():
    """domain + occupation present, 3 missing -> exactly 3 findings for the
    missing ones, status=warn, and present_fields records the 2 present."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_task(Path(tmp), "task_partial", PARTIAL_TOML)
        res = check_task(d)
        assert res["status"] == "warn"
        assert res["n_warn"] == 3, f"expected 3 warn, got {res['n_warn']}: {res['findings']}"
        missing = sorted(_warn_kinds(res))
        assert missing == ["sector", "subdomain", "task_type"], f"got {missing}"
        assert sorted(res["metadata_present_fields"]) == ["domain", "occupation"]
        print("  test_partial_metadata: PASS (partial -> warn, 3 findings for the 3 missing)")


def test_empty_string_field_flagged():
    """A field present but set to the empty string counts as missing."""
    toml = (
        "schema_version = \"1.1\"\n\n[task]\nname = \"svc/x\"\n\n[metadata]\n"
        "category = \"SVC-PC\"\ntags = []\n"
        "domain = \"\"\noccupation = \"Plumbers\"\nsector = \"\"\n"
        "subdomain = \"\"\ntask_type = \"\"\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_task(Path(tmp), "task_emptystr", toml)
        res = check_task(d)
        assert res["status"] == "warn"
        missing = sorted(_warn_kinds(res))
        assert missing == ["domain", "sector", "subdomain", "task_type"], f"got {missing}"
        assert res["metadata_present_fields"] == ["occupation"]
        print("  test_empty_string_field_flagged: PASS (empty-string fields -> missing)")


def test_whitespace_only_field_flagged():
    """A field set to whitespace-only counts as missing (empty after strip)."""
    toml = (
        "schema_version = \"1.1\"\n\n[task]\nname = \"svc/x\"\n\n[metadata]\n"
        "category = \"SVC-PC\"\ntags = []\n"
        "domain = \"   \"\noccupation = \"Plumbers\"\nsector = \"Construction\"\n"
        "subdomain = \"Piping\"\ntask_type = \"Pipe fitting plan\"\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_task(Path(tmp), "task_ws", toml)
        res = check_task(d)
        assert res["status"] == "warn"
        assert res["n_warn"] == 1, f"expected 1, got {res['n_warn']}: {res['findings']}"
        assert _warn_kinds(res) == ["domain"]
        print("  test_whitespace_only_field_flagged: PASS (whitespace-only -> missing)")


def test_missing_task_toml():
    """task.toml absent (but instruction.md present so it is a task): single
    metadata_block_absent warn, never a fail. Check B owns the fail-tier."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_task(Path(tmp), "task_notoml", None)
        res = check_task(d)
        assert res["status"] == "warn", f"expected warn, got {res['status']}"
        assert res["n_warn"] == 1
        assert res["n_fail"] == 0
        assert res["findings"][0]["kind"] == "metadata_block_absent"
        print("  test_missing_task_toml: PASS (no task.toml -> 1 metadata_block_absent warn)")


def test_unparseable_task_toml():
    """task.toml exists but is broken TOML: single task_toml_unparseable warn."""
    broken = "schema_version = \"1.1\"\n\n[task]\nname = \"svc/x\n[metadata\n"
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_task(Path(tmp), "task_broken", broken)
        res = check_task(d)
        assert res["status"] == "warn"
        assert res["n_warn"] == 1
        assert res["n_fail"] == 0
        assert res["findings"][0]["kind"] == "task_toml_unparseable"
        print("  test_unparseable_task_toml: PASS (broken TOML -> 1 task_toml_unparseable warn)")


def test_no_metadata_table():
    """task.toml parses but has no [metadata] table: all 5 fields absent -> 5
    findings, status=warn (field-level, not a single block finding)."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_task(Path(tmp), "task_nometa", NO_METADATA_TABLE_TOML)
        res = check_task(d)
        assert res["status"] == "warn"
        assert res["n_warn"] == 5, f"expected 5, got {res['n_warn']}"
        missing = sorted(_warn_kinds(res))
        assert missing == sorted(REQUIRED_METADATA_FIELDS)
        print("  test_no_metadata_table: PASS (no [metadata] table -> 5 field findings)")


def test_not_a_task_dir():
    """An empty directory is not a task: status=skip, one info finding."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "empty"
        d.mkdir()
        res = check_task(d)
        assert res["status"] == "skip", f"expected skip, got {res['status']}"
        assert res["n_warn"] == 0
        assert res["n_info"] == 1
        assert res["findings"][0]["kind"] == "not_a_task_dir"
        print("  test_not_a_task_dir: PASS (empty dir -> skip)")


def test_never_fails():
    """A task with every defect path still never sets status=fail: the check is
    warn-only by design (no scoring effect, per coverage-synthesis.md)."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_task(Path(tmp), "task_empty2", EMPTY_TOML)
        res = check_task(d)
        assert res["n_fail"] == 0
        assert res["status"] != "fail"
        print("  test_never_fails: PASS (warn-only, n_fail always 0)")


if __name__ == "__main__":
    tests = [
        test_complete_metadata_no_findings,
        test_empty_metadata_real_shape_5_findings,
        test_partial_metadata,
        test_empty_string_field_flagged,
        test_whitespace_only_field_flagged,
        test_missing_task_toml,
        test_unparseable_task_toml,
        test_no_metadata_table,
        test_not_a_task_dir,
        test_never_fails,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as exc:
            failed += 1
            print(f"  {t.__name__}: FAIL - {type(exc).__name__}: {exc}")
    print(f"\n{passed}/{passed + failed} tests passed")
    sys.exit(1 if failed else 0)
