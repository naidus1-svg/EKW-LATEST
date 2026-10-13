"""Tests for triage_review_majors.py. Stdlib only, no model calls: python3 test_triage_review_majors.py"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import triage_review_majors as T  # noqa: E402


def review(checks):
    return {"overall_verdict": "reject", "major_count": 0, "checks": checks}


class Tests(unittest.TestCase):
    def test_load_majors_ignores_minors_and_reads_text_and_fix(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.json"
            p.write_text(
                json.dumps(
                    review(
                        [
                            {
                                "id": "1.5",
                                "severity": "major",
                                "justification": "Rubric lets a wrong answer pass.",
                                "suggested_fix": "Add a check.",
                            },
                            {
                                "id": "1.9",
                                "severity": "minor",
                                "justification": "Naming.",
                            },
                            {
                                "id": "1.1",
                                "severity": "Blocking",
                                "description": "Golden is wrong.",
                            },
                        ]
                    )
                )
            )
            m = T.load_majors(p)
        self.assertEqual([x["check"] for x in m], ["1.5", "1.1"])
        self.assertIn("Add a check.", m[0]["text"])

    def test_not_a_review_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.json"
            p.write_text(json.dumps({"hello": 1}))
            with self.assertRaises(ValueError):
                T.load_majors(p)

    def test_decide_tiers(self):
        v = lambda d, o="no": {"direction": d, "observed_run": o == "yes"}  # noqa: E731
        self.assertEqual(T.decide([v("reference_defect")] * 3)["tier"], "HOLD")
        self.assertEqual(
            T.decide([v("reference_defect"), v("reference_defect"), v("lenient")])[
                "tier"
            ],
            "HOLD",
        )
        self.assertEqual(
            T.decide([v("unfair_to_correct", "yes")] * 3)["tier"], "FIX_NEXT"
        )
        self.assertEqual(T.decide([v("unfair_to_correct")] * 3)["tier"], "FIX_LAST")
        self.assertEqual(T.decide([v("lenient")] * 3)["tier"], "FIX_LAST")
        self.assertEqual(T.decide([v("harness")] * 3)["tier"], "FIX_LAST")
        d = T.decide([v("lenient"), v("harness"), v("reference_defect")])
        self.assertEqual((d["direction"], d["tier"]), ("unresolved", "FIX_NEXT"))

    def test_chunking_keeps_every_major_once(self):
        majors = [{"source": "s", "check": "1.5", "text": "x" * 500} for _ in range(25)]
        chunks = T.build_chunks(majors, cap=3000)
        ids = [i for c in chunks for i, _b in c]
        self.assertEqual(ids, list(range(25)))
        self.assertGreater(len(chunks), 1)

    def test_label_majors_with_a_fake_model(self):
        majors = [
            {"source": "s", "check": "1.1", "text": "golden wrong"},
            {"source": "s", "check": "1.5", "text": "weak answer passes"},
        ]
        calls = []

        def fake(rule, text, model=None, config_dir=None, timeout=0):
            calls.append(config_dir)
            return {
                "m001": {"direction": "reference_defect", "observed_run": "no"},
                "m002": {"direction": "lenient", "observed_run": "no"},
            }

        votes = T.label_majors(majors, runner=fake, lanes=["/a", "/b", "/c"])
        self.assertEqual(sorted(calls), ["/a", "/b", "/c"])
        self.assertEqual([T.decide(v)["tier"] for v in votes], ["HOLD", "FIX_LAST"])

    def test_exit_code_and_report(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.json"
            p.write_text(
                json.dumps(
                    review(
                        [
                            {
                                "id": "1.1",
                                "severity": "major",
                                "justification": "Golden is wrong.",
                            }
                        ]
                    )
                )
            )
            orig = T.label_majors
            T.label_majors = lambda majors, runner=None, lanes=None: [
                [{"direction": "reference_defect", "observed_run": False}] * 3
                for _ in majors
            ]
            try:
                out = Path(d) / "out.md"
                rc = T.main([str(p), "--out", str(out)])
                self.assertEqual(rc, 10)
                self.assertIn("HOLD", out.read_text(encoding="utf-8"))
                self.assertEqual(T.main([]), 0)
            finally:
                T.label_majors = orig


if __name__ == "__main__":
    unittest.main()
