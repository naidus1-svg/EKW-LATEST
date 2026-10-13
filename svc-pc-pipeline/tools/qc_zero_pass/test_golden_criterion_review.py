"""Tests for golden_criterion_review.py. stdlib unittest, no model call: a synthetic bundle plus replayed replies."""

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import golden_criterion_review as g

# a stand-in for the claude command: logs its standard input, answers one item, can be told to fail
FAKE_CLAUDE = """import json, os, sys
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as f:
    f.write(sys.stdin.read() + "\\n---\\n")
if os.environ.get("FAKE_FAIL"):
    sys.stderr.write("simulated failure")
    sys.exit(3)
print(json.dumps({"k000": {"verdict": "criterion_defect", "why": "w", "confidence": 3}}))
"""

JUDGE_TOML = """[judge]
weight = 1.0

[[criterion]]
name = "c1_pinned"
description = "PASS if the memo names the 40 percent split."
weight = 0.5

[[criterion]]
name = "c2_fair"
description = "PASS if the memo states the total."
weight = 0.5

[[criterion]]
name = "c3_passes"
description = "PASS if the memo has a title."
weight = 0.0
"""


def details(c1, c2, c3):
    crit = lambda n, v, r: {
        "name": n,
        "value": v,
        "raw": v == 1.0,
        "weight": 0.5,
        "description": "d",
        "reasoning": r,
    }
    return {
        "deliverables_01": {
            "score": 0.0,
            "kind": "llm",
            "criteria": [
                crit("c1_pinned", c1[0], c1[1]),
                crit("c2_fair", c2[0], c2[1]),
                crit("c3_passes", c3[0], c3[1]),
            ],
        }
    }


def make_bundle(root):
    tf = Path(root) / "t" / "rev_1__1" / "task_files"
    (tf / "tests" / "d1").mkdir(parents=True)
    (tf / "solution" / "files").mkdir(parents=True)
    (tf / "instruction.md").write_text(
        "Write a memo giving the total.", encoding="utf-8"
    )
    (tf / "tests" / "d1" / "judge.toml").write_text(JUDGE_TOML, encoding="utf-8")
    (tf / "solution" / "files" / "gold.md").write_text(
        "The total is 100. The split is 40 percent.", encoding="utf-8"
    )
    for i, run in enumerate(("a", "b")):
        ev = (
            Path(root)
            / "t"
            / "rev_1__1"
            / "evaluations"
            / ("eval_%d__attempt_1__x__%s" % (i, run))
            / "eval_files"
            / "verifier"
        )
        ev.mkdir(parents=True)
        (ev / "reward-details.json").write_text(
            json.dumps(
                details(
                    (0.0, "run %s left out the split" % run),
                    (0.0, "run %s missed the total" % run),
                    (1.0, "ok"),
                )
            ),
            encoding="utf-8",
        )
    oracle = (
        Path(root)
        / "t"
        / "rev_1__1"
        / "evaluations"
        / "eval_9__attempt_1__oracle"
        / "eval_files"
        / "verifier"
    )
    oracle.mkdir(parents=True)
    (oracle / "reward-details.json").write_text(
        json.dumps(details((1.0, "o"), (1.0, "o"), (1.0, "o"))), encoding="utf-8"
    )


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        make_bundle(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_zero_pass_skips_oracle_and_passing_criteria(self):
        b = g.load_bundle(self.tmp.name)
        names = [n for n, _f in g.zero_pass(b)]
        self.assertEqual(sorted(names), ["c1_pinned", "c2_fair"])

    def test_inputs_carry_golden_only_in_the_golden_pass(self):
        b = g.load_bundle(self.tmp.name)
        zp = g.zero_pass(b)
        keys = ["k000", "k001"]
        self.assertIn("The split is 40 percent", g.build_gold_input(b, zp, keys))
        self.assertNotIn("The split is 40 percent", g.build_base_input(b, zp, keys))
        self.assertIn("-----CRITERION ITEM k000-----", g.build_gold_input(b, zp, keys))
        self.assertIn("=====ITEM k001=====", g.build_base_input(b, zp, keys))

    def test_tiers(self):
        d = lambda v: {"verdict": v, "why": "w", "confidence": 2}
        gold = [
            {"k000": d("criterion_defect"), "k001": d("solver_miss")},
            {"k000": d("criterion_defect"), "k001": d("criterion_defect")},
            {"k000": d("solver_miss"), "k001": d("solver_miss")},
        ]
        base = {"k000": d("criterion_defect"), "k001": d("criterion_defect")}
        t = {
            i["criterion"]: i["tier"]
            for i in g.tier(gold, base, ["k000", "k001"], ["c1_pinned", "c2_fair"])
        }
        self.assertEqual(t["c1_pinned"], "HOLD_AI")
        self.assertIsNone(t["c2_fair"])  # only 1 golden vote
        base2 = {"k000": d("solver_miss"), "k001": d("solver_miss")}
        t2 = {
            i["criterion"]: i["tier"]
            for i in g.tier(gold, base2, ["k000", "k001"], ["c1_pinned", "c2_fair"])
        }
        self.assertEqual(t2["c1_pinned"], "READ_FIRST")

    def test_replay_end_to_end_and_no_zero_pass(self):
        rd = Path(self.tmp.name) / "replay"
        rd.mkdir()
        d = lambda v: {"verdict": v, "why": "pinned to the golden", "confidence": 3}
        for i in (1, 2, 3):
            (rd / ("gold%d.json" % i)).write_text(
                json.dumps({"k000": d("criterion_defect"), "k001": d("solver_miss")}),
                encoding="utf-8",
            )
        (rd / "base.json").write_text(
            json.dumps({"k000": d("criterion_defect"), "k001": d("solver_miss")}),
            encoding="utf-8",
        )
        res = g.review(self.tmp.name, replay_dir=str(rd))
        self.assertEqual(res["hold_ai"], ["c1_pinned"])
        self.assertEqual(res["read_first"], [])
        self.assertEqual(
            g.review(self.tmp.name, dry_run=True)["note"], "dry run: nothing sent"
        )

    def test_staleness_gate_drops_changed_flags(self):
        cur = Path(self.tmp.name) / "current"
        make_bundle(str(cur))
        cp = cur / "t" / "rev_1__1" / "task_files" / "tests" / "d1" / "judge.toml"
        cp.write_text(
            JUDGE_TOML.replace(
                "PASS if the memo names the 40 percent split.",
                "PASS if the memo names any split.",
            ),
            encoding="utf-8",
        )
        d = lambda v: {"verdict": v, "why": "w", "confidence": 3}
        rd = Path(self.tmp.name) / "replay2"
        rd.mkdir()
        both = {"k000": d("criterion_defect"), "k001": d("criterion_defect")}
        for i in (1, 2, 3):
            (rd / ("gold%d.json" % i)).write_text(json.dumps(both), encoding="utf-8")
        (rd / "base.json").write_text(json.dumps(both), encoding="utf-8")
        res = g.review(self.tmp.name, replay_dir=str(rd), current=str(cur))
        self.assertEqual(
            res["stale"], ["c1_pinned"]
        )  # its text changed in the current version
        self.assertEqual(res["hold_ai"], ["c2_fair"])  # unchanged text stays flagged
        tiers = {i["criterion"]: i["tier"] for i in res["items"]}
        self.assertEqual(tiers["c1_pinned"], "STALE")

    def test_parse_reply_strips_code_fence(self):
        self.assertEqual(
            g.parse_reply('```json\n{"k000": {"verdict": "solver_miss"}}\n```'),
            {"k000": {"verdict": "solver_miss"}},
        )

    def fake_command(self):
        """Write the fake claude and return the GCR_CLAUDE value that runs it."""
        fake = Path(self.tmp.name) / "fake_claude.py"
        fake.write_text(FAKE_CLAUDE, encoding="utf-8")
        return '"%s" "%s"' % (sys.executable, fake)

    def test_claude_argv_uses_the_override_or_the_claude_on_path(self):
        with mock.patch.dict(os.environ, {"GCR_CLAUDE": self.fake_command()}):
            argv = g.claude_argv()
        self.assertEqual(argv[0], sys.executable)
        self.assertTrue(argv[1].endswith("fake_claude.py"))
        env = {k: v for k, v in os.environ.items() if k != "GCR_CLAUDE"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(g.shutil, "which", return_value="C:/x/claude.cmd"):
                self.assertEqual(g.claude_argv(), ["C:/x/claude.cmd"])
            with mock.patch.object(g.shutil, "which", return_value=None):
                self.assertEqual(g.claude_argv(), ["claude"])

    def test_run_claude_runs_the_override_command_with_the_text_on_stdin(self):
        log = Path(self.tmp.name) / "stdin.log"
        env = {"GCR_CLAUDE": self.fake_command(), "FAKE_LOG": str(log)}
        with mock.patch.dict(os.environ, env):
            reply = g.run_claude("RULE", "the batch text")
        self.assertEqual(reply["k000"]["verdict"], "criterion_defect")
        self.assertIn("the batch text", log.read_text(encoding="utf-8"))
        with mock.patch.dict(os.environ, {**env, "FAKE_FAIL": "1"}):
            with self.assertRaises(RuntimeError) as cm:
                g.run_claude("RULE", "the batch text")
        self.assertIn("simulated failure", str(cm.exception))

    def test_golden_outputs_folder_is_the_golden_too(self):
        tf = Path(self.tmp.name) / "t" / "rev_1__1" / "task_files" / "solution"
        (tf / "files" / "gold.md").unlink()
        (tf / "golden_outputs").mkdir()
        (tf / "golden_outputs" / "gold.md").write_text(
            "The harbor golden says 40 percent.", encoding="utf-8"
        )
        fake = types.SimpleNamespace(
            MarkItDown=lambda: types.SimpleNamespace(
                convert=lambda p: types.SimpleNamespace(
                    text_content=Path(p).read_text(encoding="utf-8")
                )
            )
        )
        with mock.patch.dict(sys.modules, {"markitdown": fake}):
            golden = g.load_bundle(self.tmp.name)["golden"]
        self.assertIn("The harbor golden says 40 percent.", golden)

    def test_harbor_verifier_names_and_every_reward_details_shape_are_read(self):
        root = Path(self.tmp.name) / "h" / "rev_1__1"
        (root / "task_files" / "tests").mkdir(parents=True)
        (root / "task_files" / "instruction.md").write_text("Do it.", encoding="utf-8")
        verifiers = [
            {"name": n, "assertion": {"rubric": {"prompt": "rubric " + n}}}
            for n in ("v1", "v2", "v3")
        ]
        (root / "task_files" / "tests" / "verifier.json").write_text(
            json.dumps({"verifiers": verifiers}), encoding="utf-8"
        )
        crit = lambda n: {"name": n, "value": 0.0, "reasoning": "missed " + n}
        shapes = {  # a criterion called v1, v2, v3 in the grader, and another name inside each run file
            "v1": {"criteria": [crit("slug-one")]},  # plain
            "v2": [{"criteria": [crit("slug-two")]}],  # judge passes in a list
            "v3": {"components": [{"detail": {"criteria": [crit("slug-three")]}}]},
            "other": {"judge": {"model": "m"}, "score": 0.0},  # nothing to read here
        }
        for run in ("a", "b"):
            ev = root / "evaluations" / ("eval_1__attempt_1__x__%s" % run)
            (ev / "eval_files" / "verifier").mkdir(parents=True)
            (ev / "eval_files" / "verifier" / "reward-details.json").write_text(
                json.dumps(shapes), encoding="utf-8"
            )
        b = g.load_bundle(str(root), golden=False)
        self.assertEqual(sorted(n for n, _f in g.zero_pass(b)), ["v1", "v2", "v3"])
        self.assertEqual(len(b["runs"]["v2"]), 2)  # one entry per run

    def test_a_rev_folder_as_the_root_sees_the_runs(self):
        rev = Path(self.tmp.name) / "t" / "rev_1__1"
        for root in (self.tmp.name, str(rev)):
            b = g.load_bundle(root, golden=False)
            self.assertEqual(
                sorted(n for n, _f in g.zero_pass(b)), ["c1_pinned", "c2_fair"], root
            )

    def test_review_bundle_is_review_and_lists_the_criteria_a_reply_skipped(self):
        rd = Path(self.tmp.name) / "replay"
        rd.mkdir()
        d = lambda v: {"verdict": v, "why": "w", "confidence": 3}
        both = {"k000": d("criterion_defect"), "k001": d("solver_miss")}
        for i in (1, 2, 3):
            (rd / ("gold%d.json" % i)).write_text(json.dumps(both), encoding="utf-8")
        (rd / "base.json").write_text(json.dumps(both), encoding="utf-8")
        whole = g.review(self.tmp.name, replay_dir=str(rd))
        again = g.review_bundle(g.load_bundle(self.tmp.name), replay_dir=str(rd))
        self.assertEqual(whole, again)
        self.assertEqual(whole["unanswered"], [])
        # the third golden reply forgets k001: it must show up, not count as "not a defect"
        (rd / "gold3.json").write_text(
            json.dumps({"k000": d("criterion_defect")}), encoding="utf-8"
        )
        self.assertEqual(
            g.review(self.tmp.name, replay_dir=str(rd))["unanswered"], ["c2_fair"]
        )


if __name__ == "__main__":
    unittest.main()
