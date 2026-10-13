"""Tests for golden_review_batch.py: stdlib unittest, no model call (a fake review function)."""

import json
import tempfile
import unittest
from pathlib import Path

import golden_review_batch as b


def fake_review(path, config_dir=None, dry_run=False, current=None):
    name = Path(path).stem
    if "boom" in name:
        raise RuntimeError("model unavailable")
    if "hold" in name:
        return {"zero_pass_criteria": 3, "hold_ai": ["c1"], "read_first": ["c2"]}
    if "wide" in name:
        return {
            "zero_pass_criteria": 12,
            "hold_ai": ["c%d" % i for i in range(5)],
            "read_first": ["d%d" % i for i in range(5)],
        }
    if "read" in name:
        return {"zero_pass_criteria": 2, "hold_ai": [], "read_first": ["c9"]}
    return {"zero_pass_criteria": 0, "hold_ai": [], "read_first": []}


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bundles = Path(self.tmp.name) / "zips"
        self.bundles.mkdir()
        for n in ("hold1__11", "read1__12", "clean1__13", "boom1__14", "intrej__15"):
            (self.bundles / (n + ".zip")).write_bytes(b"x")
        self.verd = Path(self.tmp.name) / "verdicts"
        self.verd.mkdir()
        (self.verd / "intrej.json").write_text(
            json.dumps({"verdict": "MAJOR"}), encoding="utf-8"
        )
        (self.verd / "intrej.verify.json").write_text(
            json.dumps({"overall": "CONFIRMED_MAJOR"}), encoding="utf-8"
        )
        (self.verd / "clean1.json").write_text(
            json.dumps({"verdict": "MAJOR"}), encoding="utf-8"
        )
        (self.verd / "clean1.verify.json").write_text(
            json.dumps({"overall": "DOWNGRADED"}), encoding="utf-8"
        )
        self.out = Path(self.tmp.name) / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def tiers(self):
        rows = b.run(
            str(self.bundles),
            ["/root/.claude-a", "/root/.claude-b"],
            str(self.out),
            str(self.verd),
            review=fake_review,
        )
        return {r["task"]: r for r in rows}

    def test_tiers_merge_internal_and_ai(self):
        t = self.tiers()
        self.assertEqual(t["hold1"]["tier"], "HOLD")
        self.assertEqual(t["read1"]["tier"], "READ_FIRST")
        self.assertEqual(
            t["clean1"]["tier"], "CLEAN"
        )  # internal MAJOR was downgraded by the verify pass
        self.assertEqual(t["clean1"]["internal"], "passed")
        self.assertEqual(t["intrej"]["tier"], "HOLD")  # internal rejection alone holds
        self.assertIn("internal review rejected", t["intrej"]["why"])
        self.assertEqual(t["boom1"]["tier"], "ERROR")

    def test_wide_net_tier_unless_internal_rejected(self):
        (self.bundles / "wide1__16.zip").write_bytes(b"x")
        (self.bundles / "wideint__17.zip").write_bytes(b"x")
        (self.verd / "wideint.json").write_text(
            json.dumps({"verdict": "MAJOR"}), encoding="utf-8"
        )
        (self.verd / "wideint.verify.json").write_text(
            json.dumps({"overall": "CONFIRMED_MAJOR"}), encoding="utf-8"
        )
        t = self.tiers()
        self.assertEqual(t["wide1"]["tier"], "WIDE_NET")
        self.assertEqual(
            t["wideint"]["tier"], "HOLD"
        )  # an internal rejection keeps the hold

    def test_resume_skips_finished_bundles(self):
        self.tiers()
        calls = []

        def counting(path, config_dir=None, dry_run=False, current=None):
            calls.append(path)
            return fake_review(path, config_dir, dry_run)

        rows = b.run(
            str(self.bundles),
            ["/root/.claude-a"],
            str(self.out),
            str(self.verd),
            review=counting,
        )
        self.assertEqual(
            len(calls), 0
        )  # all five outputs already exist (the error one too)
        self.assertTrue(all(r["how"] == "resumed" for r in rows))

    def test_report_orders_hold_first_and_counts(self):
        rows = b.run(
            str(self.bundles), [], str(self.out), str(self.verd), review=fake_review
        )
        count = b.write_report(rows, str(self.out))
        self.assertEqual(
            count, {"HOLD": 2, "READ_FIRST": 1, "WIDE_NET": 0, "ERROR": 1, "CLEAN": 1}
        )
        text = (self.out / "report.md").read_text(encoding="utf-8")
        self.assertLess(text.index("## HOLD"), text.index("## READ_FIRST"))
        self.assertEqual(rows[0]["tier"], "HOLD")

    def test_lanes_are_round_robin(self):
        seen = []

        def spy(path, config_dir=None, dry_run=False, current=None):
            seen.append(config_dir)
            return fake_review(path, config_dir, dry_run)

        b.run(str(self.bundles), ["A", "B"], str(self.out), None, workers=1, review=spy)
        self.assertEqual(sorted(set(seen)), ["A", "B"])


if __name__ == "__main__":
    unittest.main()
