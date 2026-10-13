"""Calibration regression for package_shape_check.py.

Two halves:

  1. Fixture half (always runs): a minimal-but-real package is built in a tmp dir, then each of the
     five known-bad shapes from the 2026-09-22 fix session is reconstructed from it and asserted to
     FIRE the corresponding detector -- a `task_files/` root, bare files at the archive root, a
     package with `reports/` stripped, a package carrying `__pycache__`, a genre-less/mixed package,
     and a zip that drifted from the directory that produced it.
  2. Corpus half (skips when the artifacts are absent): the 29 hand-fixed final zips shipped on
     2026-09-22 must all still pass every always-on detector. That clean sweep is the baseline a
     future change to this check must not break.
"""

from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import package_shape_check as P  # noqa: E402

TASK = "task_999"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _write(root: Path, rel: str, text: str = "x") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def good_pkg(tmp_path: Path) -> Path:
    """A minimal native-harbor package directory named task_999/."""
    pkg = tmp_path / "src" / TASK
    _write(pkg, "instruction.md", "# do the thing\n")
    _write(pkg, "task.toml", 'version = "1.0"\n')
    _write(pkg, "tests/verifier.json", json.dumps({"criteria": []}))
    _write(pkg, "tests/__verifier_lib/judge.py", "# judge\n")
    _write(pkg, "tests/__verifier_lib/requirements.txt", "litellm==1.93.0\n")
    _write(pkg, "solution/solve.sh", "#!/bin/sh\n")
    _write(pkg, "environment/Dockerfile", "FROM python:3.12\n")
    _write(pkg, f"reports/{TASK}_TRACE.json", json.dumps({"criteria": []}))
    _write(pkg, f"reports/{TASK}_DECISIONS.json", json.dumps({"decisions": []}))
    return pkg


def _zip_from(pkg_dir: Path, out: Path, arc_root: str | None) -> Path:
    """Zip pkg_dir's contents under `arc_root/` (or bare at the root when arc_root is None)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w") as z:
        for p in sorted(pkg_dir.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(pkg_dir).as_posix()
            z.write(p, f"{arc_root}/{rel}" if arc_root else rel)
    return out


@pytest.fixture
def good_zip(good_pkg: Path, tmp_path: Path) -> Path:
    return _zip_from(good_pkg, tmp_path / "out" / f"{TASK}_fixed.zip", TASK)


# ---------------------------------------------------------------------------
# the happy path -- a well-formed package of each genre
# ---------------------------------------------------------------------------


def test_good_zip_passes_every_detector(good_zip: Path):
    r = P.check_package(good_zip)
    assert r["status"] == "pass", r["checks"]
    assert r["checks"]["genre_coherence"]["genre"] == "native-harbor"
    assert r["checks"]["drift_vs_source"]["status"] == "skip"


def test_good_directory_package_passes(good_pkg: Path):
    assert P.check_package(good_pkg)["status"] == "pass"


def test_single_underscore_verifier_lib_is_also_native(good_pkg: Path, tmp_path: Path):
    """28 of the 79 shipped v7 tasks use tests/verifier_lib/, not tests/__verifier_lib/."""
    shutil.move(str(good_pkg / "tests" / "__verifier_lib"), str(good_pkg / "tests" / "verifier_lib"))
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", TASK)
    r = P.check_package(z)
    assert r["status"] == "pass", r["checks"]
    assert r["checks"]["genre_coherence"]["genre"] == "native-harbor"


def test_rewardkit_hybrid_genre_passes(good_pkg: Path, tmp_path: Path):
    shutil.rmtree(good_pkg / "tests" / "__verifier_lib")
    (good_pkg / "tests" / "verifier.json").unlink()
    _write(good_pkg, "tests/deliverables_memo/judge.toml", "[[criterion]]\nname='v1'\n")
    _write(good_pkg, "tests/reward.toml", "weight = 1.0\n")
    _write(good_pkg, "environment/initial_workspace/input.csv", "a,b\n")
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", TASK)
    r = P.check_package(z)
    assert r["status"] == "pass", r["checks"]
    assert r["checks"]["genre_coherence"]["genre"] == "rewardkit-hybrid"


# ---------------------------------------------------------------------------
# detector 1: root_shape -- task_470 / task_388 (task_files root), task_462 (bare root)
# ---------------------------------------------------------------------------


def test_task_files_root_fails(good_pkg: Path, tmp_path: Path):
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", "task_files")
    r = P.check_package(z)
    assert "root_shape" in r["failed_checks"], r["checks"]
    assert r["checks"]["required_members"]["status"] == "pass"  # the files are fine, the shape isn't
    assert "task_files/" in r["checks"]["root_shape"]["detail"]
    assert "download with runs" in r["checks"]["root_shape"]["detail"]


def test_bare_files_at_root_fails(good_pkg: Path, tmp_path: Path):
    """task_462's real shape: instruction.md / tests/ / environment/ loose at the zip root."""
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", None)
    r = P.check_package(z)
    assert "root_shape" in r["failed_checks"]
    d = r["checks"]["root_shape"]["detail"]
    assert "top-level entries" in d and "bare FILES" in d
    # With no wrapper there is nothing to look under, so the wrapper-scoped detectors skip
    # rather than emit a second, derivative failure.
    for name in ("ledger_present", "required_members", "genre_coherence"):
        assert r["checks"][name]["status"] == "skip"


def test_wrong_wrapper_name_fails(good_pkg: Path, tmp_path: Path):
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", "task_998")
    r = P.check_package(z)
    assert "root_shape" in r["failed_checks"]
    assert "task_999" in r["checks"]["root_shape"]["detail"]


def test_expect_id_override(good_pkg: Path, tmp_path: Path):
    z = _zip_from(good_pkg, tmp_path / "o" / "whatever.zip", TASK)
    assert P.check_package(z)["checks"]["root_shape"]["status"] == "fail"
    assert P.check_package(z, expect_id=TASK)["checks"]["root_shape"]["status"] == "pass"


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("task_470_fixed.zip", "task_470"),
        ("task_LGL-168_fixed.zip", "task_LGL-168"),
        ("_DO_NOT_UPLOAD_task_LGL-140_fixed.zip", "task_LGL-140"),
        ("task_462.zip", "task_462"),
    ],
)
def test_expected_id_inference(filename: str, expected: str):
    assert P.expected_id_for(Path("/x") / filename) == expected


# ---------------------------------------------------------------------------
# detector 2: ledger_present -- the 11-of-19 defect
# ---------------------------------------------------------------------------


def test_missing_ledger_fails_and_names_g8(good_pkg: Path, tmp_path: Path):
    shutil.rmtree(good_pkg / "reports")
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", TASK)
    r = P.check_package(z)
    assert r["failed_checks"] == ["ledger_present"], r["checks"]
    d = r["checks"]["ledger_present"]["detail"]
    assert "reward_signal_gate.py G8" in d
    assert f"reports/{TASK}_TRACE.json" in d and f"reports/{TASK}_DECISIONS.json" in d


def test_ledger_outside_the_package_is_not_credited(good_pkg: Path, tmp_path: Path):
    """The real 2026-09-22 shape: the ledgers exist next to the package, not inside it."""
    outside = good_pkg.parent / "reports"
    shutil.move(str(good_pkg / "reports"), str(outside))
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", TASK)
    assert outside.is_dir()
    assert "ledger_present" in P.check_package(z)["failed_checks"]


def test_unparseable_ledger_fails(good_pkg: Path, tmp_path: Path):
    _write(good_pkg, f"reports/{TASK}_TRACE.json", "{not json")
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", TASK)
    r = P.check_package(z)
    assert "ledger_present" in r["failed_checks"]
    assert "not valid JSON" in r["checks"]["ledger_present"]["detail"]


# ---------------------------------------------------------------------------
# detector 3: hygiene
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "junk",
    [
        "tests/__verifier_lib/__pycache__/judge.cpython-312.pyc",
        "tests/__verifier_lib/judge.pyc",
        ".DS_Store",
        "tests/verifier.json.round2",
        "tests/verifier.json.bak",
        "solution/notes.tmp",
        "tests/verifier.json.orig",
        "tests/.verifier.json.swp",
        "instruction.md~",
        "environment/nested_bundle.zip",
    ],
)
def test_hygiene_fires_on_each_junk_shape(good_pkg: Path, tmp_path: Path, junk: str):
    _write(good_pkg, junk, "junk")
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", TASK)
    r = P.check_package(z)
    assert "hygiene" in r["failed_checks"], r["checks"]["hygiene"]
    assert Path(junk).name in r["checks"]["hygiene"]["detail"]


def test_hygiene_clean_package_passes(good_zip: Path):
    assert P.check_package(good_zip)["checks"]["hygiene"]["status"] == "pass"


# ---------------------------------------------------------------------------
# detector 4: required_members
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("victim", ["instruction.md", "task.toml", "solution", "environment"])
def test_required_member_missing_fails(good_pkg: Path, tmp_path: Path, victim: str):
    target = good_pkg / victim
    shutil.rmtree(target) if target.is_dir() else target.unlink()
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", TASK)
    r = P.check_package(z)
    assert "required_members" in r["failed_checks"], r["checks"]["required_members"]
    assert victim in r["checks"]["required_members"]["detail"]


# ---------------------------------------------------------------------------
# detector 5: genre_coherence -- never report "unknown" as a pass
# ---------------------------------------------------------------------------


def test_neither_genre_fails_not_skips(good_pkg: Path, tmp_path: Path):
    shutil.rmtree(good_pkg / "tests" / "__verifier_lib")
    (good_pkg / "tests" / "verifier.json").unlink()
    _write(good_pkg, "tests/test.sh", "#!/bin/sh\n")
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", TASK)
    r = P.check_package(z)
    g = r["checks"]["genre_coherence"]
    assert g["status"] == "fail" and g["genre"] == "unknown", g
    assert "NEITHER build genre" in g["detail"]


def test_partial_native_genre_fails(good_pkg: Path, tmp_path: Path):
    """verifier.json with no vendored lib: half a native package, and it cannot grade."""
    shutil.rmtree(good_pkg / "tests" / "__verifier_lib")
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", TASK)
    assert P.check_package(z)["checks"]["genre_coherence"]["genre"] == "unknown"


def test_mixed_genre_fails(good_pkg: Path, tmp_path: Path):
    _write(good_pkg, "tests/deliverables_memo/judge.toml", "[[criterion]]\nname='v1'\n")
    _write(good_pkg, "tests/reward.toml", "weight = 1.0\n")
    _write(good_pkg, "environment/initial_workspace/input.csv", "a,b\n")
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", TASK)
    r = P.check_package(z)
    g = r["checks"]["genre_coherence"]
    assert g["status"] == "fail" and g["genre"] == "mixed", g


# ---------------------------------------------------------------------------
# detector 6: drift_vs_source -- the GAP 5 stale-sibling revert (task_133, task_139)
# ---------------------------------------------------------------------------


def test_drift_detects_stale_zip(good_pkg: Path, tmp_path: Path):
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", TASK)
    # the working directory moves on; the already-built zip does not -- a silent revert
    _write(good_pkg, "tests/verifier.json", json.dumps({"criteria": ["v1 fixed"]}))
    r = P.check_package(z, against=good_pkg)
    d = r["checks"]["drift_vs_source"]
    assert d["status"] == "fail"
    assert d["differs"] == ["tests/verifier.json"], d
    assert "GAP 5" in d["detail"]


def test_drift_detects_file_missing_from_zip(good_pkg: Path, tmp_path: Path):
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", TASK)
    _write(good_pkg, "environment/initial_workspace/late_input.csv", "a,b\n")
    d = P.check_package(z, against=good_pkg)["checks"]["drift_vs_source"]
    assert d["status"] == "fail"
    assert d["only_in_source"] == ["environment/initial_workspace/late_input.csv"], d


def test_drift_passes_on_a_fresh_zip(good_pkg: Path, tmp_path: Path):
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", TASK)
    assert P.check_package(z, against=good_pkg)["checks"]["drift_vs_source"]["status"] == "pass"


def test_drift_accepts_the_parent_directory_too(good_pkg: Path, tmp_path: Path):
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", TASK)
    assert P.check_package(z, against=good_pkg.parent)["checks"]["drift_vs_source"]["status"] == "pass"


def test_drift_ignores_hygiene_junk_on_either_side(good_pkg: Path, tmp_path: Path):
    """A __pycache__ left in the working dir is a hygiene finding, not a drift finding."""
    z = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", TASK)
    _write(good_pkg, "tests/__verifier_lib/__pycache__/judge.cpython-312.pyc", "junk")
    r = P.check_package(z, against=good_pkg)
    assert r["checks"]["drift_vs_source"]["status"] == "pass", r["checks"]["drift_vs_source"]


# ---------------------------------------------------------------------------
# robustness
# ---------------------------------------------------------------------------


def test_corrupt_zip_skips_never_passes(tmp_path: Path):
    bad = tmp_path / f"{TASK}_fixed.zip"
    bad.write_bytes(b"not a zip at all")
    r = P.check_package(bad)
    assert r["status"] == "skip" and r["errors"]


def test_cli_exit_codes(good_pkg: Path, tmp_path: Path, capsys):
    good = _zip_from(good_pkg, tmp_path / "o" / f"{TASK}_fixed.zip", TASK)
    out = tmp_path / "report.json"
    assert P.main([str(good), "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["status_counts"] == {"pass": 1}
    bad = _zip_from(good_pkg, tmp_path / "o2" / f"{TASK}_fixed.zip", "task_files")
    assert P.main([str(bad)]) == 1


def test_root_sweep_finds_zips_and_dirs(good_pkg: Path, good_zip: Path, tmp_path: Path):
    assert P.discover(good_zip.parent) == [good_zip]
    assert P.discover(good_pkg.parent) == [good_pkg]


# ---------------------------------------------------------------------------
# corpus baseline: the 29 hand-fixed zips shipped 2026-09-22 must stay clean
# ---------------------------------------------------------------------------

SPRINT = HERE.parent / "dataos_qc_runs" / "74-ekw-sprint"
SHIPPED = [
    *sorted((SPRINT / "qcr_21092026" / "ready").glob("*.zip")),
    *sorted((SPRINT / "qcr_20092026_rework" / "ready").glob("task_*.zip")),
]


@pytest.mark.skipif(not SHIPPED, reason="shipped 2026-09-22 zips not present")
@pytest.mark.parametrize("z", SHIPPED, ids=lambda p: p.name)
def test_shipped_zips_pass(z: Path):
    r = P.check_package(z)
    assert r["status"] == "pass", r["checks"]
