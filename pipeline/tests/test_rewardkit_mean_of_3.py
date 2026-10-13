"""rewardkit_mean_of_3: three byte-identical judge samples per chunk, judge weight split, reversible."""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("rewardkit_mean_of_3", REPO / "pipeline" / "tools" / "rewardkit_mean_of_3.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

JUDGE = '[judge]\njudge = "anthropic/claude-sonnet-4-6"\nweight = 0.7\n\n[[criterion]]\nname = "c1"\ndescription = "d"\nweight = 1.0\n'
REWARD = '[[reward]]\naggregation = "weighted_mean"\n# judge = prose mentioning judge = 0.9 must not be touched? (comment)\nweights = { judge = 0.64, "$checks" = 0.36 }\n'


def _package(tmp_path: Path) -> Path:
    for name, reward in (("deliverables_01", None), ("deliverables_02", REWARD)):
        d = tmp_path / "tests" / name
        d.mkdir(parents=True)
        (d / "judge.toml").write_text(JUDGE)
        if reward:
            (d / "reward.toml").write_text(reward)
    return tmp_path


def test_apply_is_idempotent_splits_weight_and_undo_restores(tmp_path: Path) -> None:
    pkg = _package(tmp_path)
    before = {p: p.read_bytes() for p in pkg.rglob("*.toml")}
    assert tool.check(pkg)                                   # not in mean-of-3 form yet
    tool.apply(pkg)
    tool.apply(pkg)                                          # second run changes nothing
    assert tool.check(pkg) == []
    for d in tool.chunk_dirs(pkg):
        assert (d / "judge_s2.toml").read_bytes() == (d / "judge_s3.toml").read_bytes() == (d / "judge.toml").read_bytes()
    w = tomllib.loads((pkg / "tests" / "deliverables_02" / "reward.toml").read_text())["reward"][0]["weights"]
    assert w["$checks"] == 0.36
    assert w["judge"] == w["judge_s2"] == w["judge_s3"] and abs(w["judge"] * 3 - 0.64) < 1e-5
    (pkg / "tests" / "deliverables_01" / "judge.toml").write_text(JUDGE.replace('"d"', '"edited"'))
    assert any("differs" in p for p in tool.check(pkg))      # stale samples are caught
    (pkg / "tests" / "deliverables_01" / "judge.toml").write_text(JUDGE)
    tool.undo(pkg)
    assert {p: p.read_bytes() for p in pkg.rglob("*.toml")} == before
