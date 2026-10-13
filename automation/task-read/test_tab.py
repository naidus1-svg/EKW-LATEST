"""Tests for the task kind (EKW or SVC): detection order, the --tab option, and stopping when the files cannot tell."""

import contextlib
import io
import json
import os
import unittest

import task_read as tr
from test_task_read import Base, defect, put


def verifier_pkg(root, category=None):
    """Package with tests/verifier.json only (no reward.toml). Weights 0.5, 0.3, 0.14, 0.06."""
    p = os.path.join(root, "task2")
    os.makedirs(os.path.join(p, "tests"))
    os.makedirs(os.path.join(p, "environment", "data"))
    os.makedirs(os.path.join(p, "solution"))
    put(os.path.join(p, "instruction.md"), "Write a memo.")
    put(os.path.join(p, "environment", "data", "in.txt"), "data")
    put(os.path.join(p, "solution", "solve.sh"), "true")
    if category:
        put(os.path.join(p, "task.toml"), '[metadata]\ncategory = "%s"\n' % category)
    v = [
        dict(
            name=n,
            metadata=dict(weight=w),
            assertion=dict(rubric=dict(prompt="check " + n)),
        )
        for n, w in (("c1", 0.5), ("c2", 0.3), ("c3", 0.14), ("c4", 0.06))
    ]
    put(os.path.join(p, "tests", "verifier.json"), json.dumps(dict(verifiers=v)))
    return p


class TestTab(Base):
    def go(self, pkg, args, scenario, expect_rc):
        sc = os.path.join(self.t, "scenario.json")
        put(sc, json.dumps(scenario))
        os.environ["FAKE_SCENARIO"] = sc
        with contextlib.redirect_stdout(io.StringIO()):
            rc = tr.main([pkg, "--out", self.out, "--claude-cmd", self.fake_cmd] + args)
        self.assertEqual(rc, expect_rc)
        if expect_rc == 2:
            return None
        return tr.jload(os.path.join(self.out, "task_read_result.json"))

    def test_detect_tab_order(self):
        ws = os.path.join(self.t, "ws")
        tr.build_audit_layout(self.pkg, ws)
        self.assertEqual(tr.detect_tab(self.pkg, ws), ("EKW", "task.toml category"))
        self.assertEqual(tr.detect_tab(self.pkg, ws, "svc"), ("SVC", "flag"))

    def test_detect_tab_in_reads_the_package_folder_directly(self):
        tests = os.path.join(self.pkg, "tests")
        self.assertEqual(tr.detect_tab_in(self.pkg, tests), ("EKW", "task.toml category"))
        self.assertEqual(tr.detect_tab_in(self.pkg, tests, "svc"), ("SVC", "flag"))
        ws = os.path.join(self.t, "ws")
        tr.build_audit_layout(self.pkg, ws)  # the same answer as detect_tab gives on the audit layout
        self.assertEqual(tr.detect_tab(self.pkg, ws), tr.detect_tab_in(self.pkg, os.path.join(ws, "rubric", "raw")))
        os.remove(os.path.join(self.pkg, "task.toml"))  # reward.toml and no category word: the old guess, which the callers treat as 'cannot tell'
        self.assertEqual(tr.detect_tab_in(self.pkg, tests), ("EKW", "reward.toml guess"))
        p = verifier_pkg(self.t)  # verifier.json only
        self.assertEqual(tr.detect_tab_in(p, os.path.join(p, "tests")), ("EKW", "verifier.json grader"))
        os.remove(os.path.join(p, "tests", "verifier.json"))  # no grader file at all
        self.assertEqual(tr.detect_tab_in(p, os.path.join(p, "tests")), ("SVC", "reward.toml guess"))

    def test_flag_overrides_the_category_word(self):
        d = defect(["d1/light"])
        sc = self.scenario(a=d, b=d, ids=("d1/light",))
        auto = self.go(self.pkg, [], sc, 0)  # category EKW: weight 0.02 is under 0.05, does not count
        self.assertEqual((auto["tab"], auto["tab_source"]), ("EKW", "task.toml category"))
        forced = self.go(self.pkg, ["--tab", "SVC"], sc, 1)  # SVC rule: the lightest of three criteria counts
        self.assertEqual((forced["tab"], forced["tab_source"]), ("SVC", "flag"))
        self.assertTrue(forced["flagged_by_verifier"])
        self.assertIn("Kind: SVC (from the --tab option)", self.report())

    def test_category_word_decides_without_a_flag(self):
        p = verifier_pkg(self.t, category="SVC-PC")
        d = defect(["c4"])
        sc = self.scenario(a=d, b=d, ids=("c4",))
        r = self.go(p, [], sc, 0)  # SVC rule: 0.06 is not among the three heaviest
        self.assertEqual((r["tab"], r["tab_source"]), ("SVC", "task.toml category"))
        self.assertFalse(r["kept"][0]["counts"])

    def test_verifier_json_only_means_ekw(self):
        p = verifier_pkg(self.t)
        d = defect(["c4"])
        sc = self.scenario(a=d, b=d, ids=("c4",))
        r = self.go(p, [], sc, 1)  # EKW rule: 0.06 is 0.05 or more
        self.assertEqual((r["tab"], r["tab_source"]), ("EKW", "verifier.json grader"))
        self.assertTrue(r["kept"][0]["counts"])

    def test_cannot_tell_stops_and_asks_for_the_flag(self):
        os.remove(os.path.join(self.pkg, "task.toml"))  # reward.toml package, no category word
        d = defect(["d1/light"])
        sc = self.scenario(a=d, b=d, ids=("d1/light",))
        self.go(self.pkg, [], sc, 2)
        self.assertIn("--tab", self.report())
        r = self.go(self.pkg, ["--tab", "EKW"], sc, 0)  # with the flag it runs
        self.assertEqual((r["tab"], r["tab_source"]), ("EKW", "flag"))


if __name__ == "__main__":
    unittest.main()
