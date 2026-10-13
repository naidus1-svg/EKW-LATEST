#!/usr/bin/env python3
"""Unit tests for duplicate_criterion_content_check.py. Tests synthetic cases (identical
Expected text under different names, near-identical with minor wording variance, genuinely
distinct criteria sharing vocabulary, single-token coincidental overlap) plus real cases
from the staged SVC-PC-29-2-0, SVC-PC-33-8-0, and SVC-PC-21-4-0 judge.toml text (the real
calibration corpus). Does NOT make any LLM call; all fixtures are real or hand-written
criterion descriptions fed through analyze_task.

Run:
    python deterministic-checks/duplicate_criterion_content_check_test.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from duplicate_criterion_content_check import analyze_task

STAGED = HERE.parent / "khiem-202-data" / "comprehensive-review-9-real-defects"


# ---------------------------------------------------------------------------
# helpers: build temp task dirs with tests/deliverables_NN/judge.toml
# ---------------------------------------------------------------------------


def _write_judge_toml(path: Path, criteria: list[tuple[str, str, float]],
                      judge_weight: float = 1.0) -> None:
    """Write a judge.toml with the given (name, description, weight) criteria."""
    lines = [
        '[judge]',
        'judge = "test"',
        'files = ["test.xlsx"]',
        f'weight = {judge_weight}',
        '',
    ]
    for cname, desc, weight in criteria:
        lines.append('[[criterion]]')
        lines.append(f'name = "{cname}"')
        lines.append(f"description = '''{desc}'''")
        lines.append('type = "binary"')
        lines.append(f'weight = {weight}')
        lines.append('')
    lines.append('[scoring]')
    lines.append('aggregation = "weighted_mean"')
    path.write_text("\n".join(lines), encoding="utf-8")


def _make_synthetic_task(root: Path, name: str,
                         files: dict[str, list[tuple[str, str, float]]]) -> Path:
    """Build a temp task dir with tests/deliverables_NN/judge.toml files."""
    task = root / name
    tests = task / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    for deliv_name, criteria in files.items():
        d = tests / deliv_name
        d.mkdir(exist_ok=True)
        _write_judge_toml(d / "judge.toml", criteria)
    return task


def _build_real_task(staged_task_name: str, dest_root: Path) -> Path:
    """Copy the flat staged deliverables_NN__judge.toml files into the proper
    tests/deliverables_NN/judge.toml layout so analyze_task can read them."""
    staged = STAGED / staged_task_name
    task = dest_root / staged_task_name
    tests = task / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    for f in sorted(staged.iterdir()):
        if f.name.endswith("__judge.toml"):
            deliv_name = f.name.rsplit("__judge.toml", 1)[0]
            d = tests / deliv_name
            d.mkdir(exist_ok=True)
            shutil.copy(f, d / "judge.toml")
    return task


def _cluster_ids(result: dict) -> set[str]:
    """Flatten all cluster member IDs into a set for easy assertions."""
    ids = set()
    for c in result.get("clusters", []):
        ids.update(c["criteria"])
    return ids


def _has_cluster_with(result: dict, *must_contain: str) -> bool:
    """True if any cluster contains ALL of the named criterion IDs."""
    for c in result.get("clusters", []):
        if all(cid in c["criteria"] for cid in must_contain):
            return True
    return False


# ---------------------------------------------------------------------------
# synthetic tests
# ---------------------------------------------------------------------------


def test_identical_expected_flags():
    """Two criteria with identical Expected text under different names must flag."""
    with tempfile.TemporaryDirectory(prefix="_dup_test_") as tmp:
        root = Path(tmp)
        task = _make_synthetic_task(root, "SYN-IDENTICAL", {
            "deliverables_01": [
                ("r001", "Reports the leave export cannot show who covered for whom Expected: The leave export cannot show who covered for whom.", 0.5),
                ("r002", "States the leave file is too thin to support coverage attribution Expected: The leave export cannot show who covered for whom.", 0.5),
            ],
        })
        r = analyze_task(task)
        assert r["status"] in ("warn", "fail"), f"expected warn/fail, got {r['status']}"
        assert r["n_clusters"] >= 1, f"expected >=1 cluster, got {r['n_clusters']}"
        assert _has_cluster_with(r, "deliverables_01/r001", "deliverables_01/r002"), \
            "r001 and r002 should be in the same cluster"
        print("  test_identical_expected_flags: PASS (identical Expected -> 1 cluster)")


def test_near_identical_flags():
    """Near-identical Expected text with minor wording variance should flag."""
    with tempfile.TemporaryDirectory(prefix="_dup_test_") as tmp:
        root = Path(tmp)
        task = _make_synthetic_task(root, "SYN-NEAR", {
            "deliverables_01": [
                ("c01", "Names the store-to-books check tolerance as None Expected: Tolerance is None or explicitly references the governing reconciliation control, not a number invented in the routine.", 0.5),
                ("c02", "Sets the store-to-books check tolerance to None Expected: Tolerance is None or explicitly references the governing reconciliation control, not a self-assigned number.", 0.5),
            ],
        })
        r = analyze_task(task)
        assert r["status"] in ("warn", "fail"), f"expected warn/fail, got {r['status']}"
        assert r["n_clusters"] >= 1, f"expected >=1 cluster, got {r['n_clusters']}"
        print("  test_near_identical_flags: PASS (near-identical -> 1 cluster)")


def test_distinct_does_not_flag():
    """Genuinely distinct criteria (different facts, no shared template) must NOT flag, AT THIS
    fixture's corpus size (n=2). Real regression, r31-adv1 Finding 3 (2026-09-15): an earlier
    version of this test used a "Names X as the source" pair from two DIFFERENT sources as its
    "distinct" example. That pair is this module's own disclosed source-naming false-positive
    class (see module docstring's "Known false-positive class" paragraph): it correctly stays
    quiet at n=2 here, but the identical pair TYPE flags at 0.688 cosine in the real 50-criterion
    SVC-PC-33-8-0 task (see test_real_33_8_0_named_clusters). The old test's premise ("distinct
    criteria never flag") did not generalize; it passed only because n=2 happened to suppress the
    cosine, which is exactly the false-confidence failure mode this project's own duplicate
    _criterion_content false-positive story (described in the module docstring) is about. Fixed
    by using a pair with no shared template at all, and by not claiming N-invariance: TF-IDF
    cosine over a per-task corpus is corpus-relative, not an absolute property of a pair (see
    the module docstring's "Value-divergence gate ceiling" and corpus-composition-sensitivity
    known limits)."""
    with tempfile.TemporaryDirectory(prefix="_dup_test_") as tmp:
        root = Path(tmp)
        task = _make_synthetic_task(root, "SYN-DISTINCT", {
            "deliverables_02": [
                ("r003", "Reports the leave export as covering 3 days Expected: 3.", 0.25),
                ("r004", "Reports mean tenure as 7.3 months Expected: 7.3.", 0.25),
            ],
        })
        r = analyze_task(task)
        assert r["status"] == "pass", f"expected pass (distinct), got {r['status']}"
        assert r["n_clusters"] == 0, f"expected 0 clusters, got {r['n_clusters']}"
        print("  test_distinct_does_not_flag: PASS (distinct criteria -> 0 clusters, at n=2)")


def test_single_token_overlap_does_not_flag():
    """A pair whose cosine clears SIMILARITY_THRESHOLD but shares FEWER than
    MIN_SHARED_CONTENT_TOKENS non-zero-IDF tokens must NOT flag: the shared-token gate, not
    the cosine threshold, is what suppresses it. Real regression, r31-adv1 Finding 3
    (2026-09-15): the earlier fixture ("leave export"/"mean tenure", both padded with
    "matching the ... sum/mean") actually shared 6 tokens and passed because its cosine
    (0.378) was already below SIMILARITY_THRESHOLD on its own -- the shared-token gate was
    never exercised. This fixture is verified (via a standalone diagnostic against this
    module's real _cosine()/_compute_tfidf()) to have cosine 0.5031 (clears 0.42) with exactly
    2 shared content tokens (below the 3 required), so the gate itself is what has to fire for
    this test to pass. Verified at this fixture's n=2; see test_distinct_does_not_flag's
    docstring for why this project does not claim N-invariance for TF-IDF cosine."""
    with tempfile.TemporaryDirectory(prefix="_dup_test_") as tmp:
        root = Path(tmp)
        task = _make_synthetic_task(root, "SYN-1TOK", {
            "deliverables_01": [
                ("r001", "X equals 42.", 0.5),
                ("r002", "Y equals 42.", 0.5),
            ],
        })
        r = analyze_task(task)
        assert r["status"] == "pass", f"expected pass (1-token overlap), got {r['status']}"
        assert r["n_clusters"] == 0, f"expected 0 clusters, got {r['n_clusters']}"
        print("  test_single_token_overlap_does_not_flag: PASS (cosine 0.50 clears threshold, "
              "shared-token gate correctly suppresses on only 2 shared tokens)")


def test_cross_file_cluster():
    """A duplicate cluster spanning multiple deliverables_NN files must flag (the named
    29-2-0 cluster spans deliverables_02/03/04)."""
    with tempfile.TemporaryDirectory(prefix="_dup_test_") as tmp:
        root = Path(tmp)
        task = _make_synthetic_task(root, "SYN-CROSS", {
            "deliverables_01": [
                ("a01", "Reports total workers Expected: 15.", 0.3),
                ("a02", "Reports distinct titles Expected: 13.", 0.3),
            ],
            "deliverables_02": [
                ("b01", "States the leave export cannot show who covered for whom Expected: The leave export cannot show who covered for whom.", 0.2),
            ],
            "deliverables_03": [
                ("c01", "States in as many words that the leave export is too thin Expected: The leave export cannot show who covered for whom.", 0.2),
            ],
        })
        r = analyze_task(task)
        assert _has_cluster_with(r, "deliverables_02/b01", "deliverables_03/c01"), \
            "cross-file duplicate pair should form one cluster"
        print("  test_cross_file_cluster: PASS (cross-file pair -> 1 cluster)")


def test_no_judge_files_skip():
    """A task with no judge.toml returns skip."""
    with tempfile.TemporaryDirectory(prefix="_dup_test_") as tmp:
        root = Path(tmp)
        task = root / "SYN-EMPTY"
        (task / "tests").mkdir(parents=True)
        r = analyze_task(task)
        assert r["status"] == "skip", f"expected skip, got {r['status']}"
        print("  test_no_judge_files_skip: PASS (no judge.toml -> skip)")


def test_single_criterion_pass():
    """A task with only 1 criterion returns pass (nothing to compare)."""
    with tempfile.TemporaryDirectory(prefix="_dup_test_") as tmp:
        root = Path(tmp)
        task = _make_synthetic_task(root, "SYN-ONE", {
            "deliverables_01": [
                ("r001", "Reports total workers Expected: 15.", 1.0),
            ],
        })
        r = analyze_task(task)
        assert r["status"] == "pass", f"expected pass, got {r['status']}"
        assert r["n_clusters"] == 0
        print("  test_single_criterion_pass: PASS (1 criterion -> pass)")


def test_excess_weight_fraction():
    """A cluster's excess_weight_fraction = (cluster_weight - max_weight) / total_weight."""
    with tempfile.TemporaryDirectory(prefix="_dup_test_") as tmp:
        root = Path(tmp)
        task = _make_synthetic_task(root, "SYN-WEIGHT", {
            "deliverables_01": [
                ("r001", "Reports the leave export cannot show who covered for whom Expected: The leave export cannot show who covered for whom.", 0.06),
                ("r002", "States the leave export is too thin Expected: The leave export cannot show who covered for whom.", 0.04),
                ("r003", "Reports total workers Expected: 15.", 0.90),
            ],
        })
        r = analyze_task(task)
        assert r["n_clusters"] == 1
        c = r["clusters"][0]
        assert abs(c["cluster_weight"] - 0.10) < 0.001, f"cluster_weight={c['cluster_weight']}"
        assert abs(c["excess_weight"] - 0.04) < 0.001, f"excess_weight={c['excess_weight']}"
        assert abs(c["excess_weight_fraction"] - 0.04) < 0.001, \
            f"excess_weight_fraction={c['excess_weight_fraction']}"
        print("  test_excess_weight_fraction: PASS (excess = cluster - max = 0.04)")


# ---------------------------------------------------------------------------
# real-data tests (from the staged calibration corpus)
# ---------------------------------------------------------------------------


def test_real_29_2_0_named_cluster():
    """SVC-PC-29-2-0: the named r015/r024/r034/r044 cluster must flag. These 4 criteria
    all grade 'the leave export cannot show who covered for whom' across deliverables_02/03/04.
    The cluster may include additional members via transitive closure; this test asserts the
    4 named criteria are all in ONE cluster, not the exact cluster membership."""
    if not STAGED.is_dir():
        print("  test_real_29_2_0_named_cluster: SKIP (staged corpus not found)")
        return
    with tempfile.TemporaryDirectory(prefix="_dup_real_") as tmp:
        task = _build_real_task("SVC-PC-29-2-0", Path(tmp))
        r = analyze_task(task)
        assert r["status"] == "warn", f"expected warn, got {r['status']}"
        assert _has_cluster_with(r,
            "deliverables_02/r015", "deliverables_02/r024",
            "deliverables_03/r034", "deliverables_04/r044"), \
            "r015/r024/r034/r044 must all be in one cluster"
        print(f"  test_real_29_2_0_named_cluster: PASS (r015/r024/r034/r044 in one cluster, "
              f"excess={r['total_excess_fraction']})")


def test_real_33_8_0_named_clusters():
    """SVC-PC-33-8-0: the named tolerance, no-per-order-key, and owner clusters must all flag.
    tolerance=None across r010/r017/r022/r031/r042 (weight 0.100),
    no-per-order-key across r009/r023/r034 (0.065),
    owner whitelist across r013/r029/r045 (0.060)."""
    if not STAGED.is_dir():
        print("  test_real_33_8_0_named_clusters: SKIP (staged corpus not found)")
        return
    with tempfile.TemporaryDirectory(prefix="_dup_real_") as tmp:
        task = _build_real_task("SVC-PC-33-8-0", Path(tmp))
        r = analyze_task(task)
        assert r["status"] == "warn", f"expected warn, got {r['status']}"
        # tolerance cluster
        assert _has_cluster_with(r,
            "deliverables_01/r010", "deliverables_02/r017", "deliverables_02/r022",
            "deliverables_03/r031", "deliverables_04/r042"), \
            "tolerance cluster r010/r017/r022/r031/r042 must all be in one cluster"
        # no-per-order-key cluster
        assert _has_cluster_with(r,
            "deliverables_01/r009", "deliverables_02/r023", "deliverables_03/r034"), \
            "no-per-order-key cluster r009/r023/r034 must all be in one cluster"
        # owner whitelist cluster
        assert _has_cluster_with(r,
            "deliverables_02/r013", "deliverables_03/r029", "deliverables_04/r045"), \
            "owner cluster r013/r029/r045 must all be in one cluster"
        # verify cluster weights match the coverage report
        for c in r["clusters"]:
            ids = set(c["criteria"])
            if {"deliverables_01/r010", "deliverables_02/r017", "deliverables_02/r022",
                "deliverables_03/r031", "deliverables_04/r042"} <= ids:
                assert abs(c["cluster_weight"] - 0.100) < 0.002, \
                    f"tolerance cluster_weight={c['cluster_weight']}, expected ~0.100"
            if {"deliverables_01/r009", "deliverables_02/r023", "deliverables_03/r034"} <= ids:
                assert abs(c["cluster_weight"] - 0.065) < 0.002, \
                    f"no-per-order-key cluster_weight={c['cluster_weight']}, expected ~0.065"
            if {"deliverables_02/r013", "deliverables_03/r029", "deliverables_04/r045"} <= ids:
                assert abs(c["cluster_weight"] - 0.060) < 0.002, \
                    f"owner cluster_weight={c['cluster_weight']}, expected ~0.060"
        print(f"  test_real_33_8_0_named_clusters: PASS (tolerance+no-per-order+owner, "
              f"excess={r['total_excess_fraction']})")


def test_real_21_4_0_negative():
    """SVC-PC-21-4-0 (negative calibration): mostly-distinct criteria must NOT flag.
    The task should pass with 0 clusters."""
    if not STAGED.is_dir():
        print("  test_real_21_4_0_negative: SKIP (staged corpus not found)")
        return
    with tempfile.TemporaryDirectory(prefix="_dup_real_") as tmp:
        task = _build_real_task("SVC-PC-21-4-0", Path(tmp))
        r = analyze_task(task)
        assert r["status"] == "pass", f"expected pass, got {r['status']}"
        assert r["n_clusters"] == 0, f"expected 0 clusters, got {r['n_clusters']}"
        print(f"  test_real_21_4_0_negative: PASS (22 criteria, 0 clusters, "
              f"max pair below threshold)")


def test_shared_boilerplate_value_does_not_defeat_gate():
    """Real regression, SVC-PC-1-1-0: genuinely distinct criteria (5 different account
    balances) that ALSO share a boilerplate value ("$0" from "exact, $0 variance", present in
    every one of them) must NOT flag, even though an exact-disjointness value check would see
    the shared "$0" and fail to suppress. This is the case that forced the Expected-only,
    exact-disjointness gate (2026-09-15 v1) to be replaced with the full-text,
    Jaccard-distance gate (2026-09-15 v2, see _full_text_value_tokens() in the module under
    test) after re-verifying the v1 fix against the real 202-task corpus found it barely
    moved the false-positive rate."""
    with tempfile.TemporaryDirectory(prefix="_dup_test_") as tmp:
        root = Path(tmp)
        task = _make_synthetic_task(root, "SYN-BOILERPLATE-VALUE", {
            "deliverables_01": [
                ("obj-01", "FY gross revenue equals the approved figure. Expected: $1,204,900 (exact, $0 variance).. This is a must-pass criterion.", 0.2),
                ("obj-06", "FY net loss equals the approved figure (tied out, not assumed). Expected: $(665,333) (exact, $0 var). Approved Company Facts workbook - Net loss FY.. This is a must-pass criterion.", 0.2),
                ("obj-07", "Dec-31 ending cash equals the approved figure. Expected: $2,186,512 (exact, $0 var). Approved Company Facts workbook - Ending cash.. This is a must-pass criterion.", 0.2),
                ("obj-16", "Dec-31 returns reserve equals the approved balance. Expected: $2,000 (exact, $0 var)..", 0.2),
                ("obj-17", "Dec-31 inventory equals the approved balance. Expected: $200,000 (exact, $0 var)..", 0.2),
            ],
        })
        r = analyze_task(task)
        assert not _has_cluster_with(r, "deliverables_01/obj-01", "deliverables_01/obj-06"), \
            "obj-01 and obj-06 have different dollar figures and must not cluster on shared '$0' boilerplate alone"
        print("  test_shared_boilerplate_value_does_not_defeat_gate: PASS "
              "(shared '$0'/'31' boilerplate does not defeat the value-divergence gate)")


if __name__ == "__main__":
    tests = [
        test_identical_expected_flags,
        test_near_identical_flags,
        test_distinct_does_not_flag,
        test_single_token_overlap_does_not_flag,
        test_cross_file_cluster,
        test_no_judge_files_skip,
        test_single_criterion_pass,
        test_excess_weight_fraction,
        test_real_29_2_0_named_cluster,
        test_real_33_8_0_named_clusters,
        test_real_21_4_0_negative,
        test_shared_boilerplate_value_does_not_defeat_gate,
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
