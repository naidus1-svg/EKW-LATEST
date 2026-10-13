#!/usr/bin/env python3
"""Tests for nop_floor_check.py. Stdlib only. Each case is criterion text from a real DataOS return: the revision that
failed the NOP eval and the revision whose fix passed it. Run: python test_nop_floor_check.py
"""

import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nop_floor_check as nfc  # noqa: E402


def exposed(desc, n_files=1):
    return nfc.classify(desc, n_files)[0]


def gated(desc, n_files=1):
    return nfc.classify(desc, n_files)[1]


class Exposed(unittest.TestCase):
    """Wording a literal judge passes when the deliverable is absent (NOP verdict 1.0 in the return zip)."""

    def test_mkt141_b177_absent_amount_passes(self):
        self.assertTrue(
            exposed(
                "PASS if the amount the memo gives for release spend already incurred is $10.8M. FAIL if the memo gives "
                "a different already-incurred amount. A memo that gives no already-incurred amount passes."
            )
        )

    def test_mkt131_b175_fail_only_if(self):
        self.assertTrue(
            exposed(
                "FAIL only if the document recommends merging the UK / en-GB invoice article (KB-70B3C9) into the US "
                "invoice article (KB-D2E845) or archiving it."
            )
        )

    def test_svc_pc_93_5_0_b123_commission_only(self):
        self.assertTrue(
            exposed(
                "Alice Chen title: Alice Chen is the CEO. FAIL if Alice Chen is given a title that contradicts CEO. "
                "(Sources: task prompt, Org_Chart_Q4.pptx.)"
            )
        )

    def test_svc_pc_93_5_0_b123_no_x_presented(self):
        self.assertTrue(
            exposed(
                "Tracker wholesale delivery details: No address or phone number for any of the eight wholesale accounts "
                "in Year_End_Partnership_Status.xlsx is presented as verified; the records hold none. FAIL if such an "
                "address or number is presented as verified."
            )
        )

    def test_fin235_pass_otherwise(self):
        self.assertTrue(
            exposed(
                "FAIL if the memo states or implies that systems separation or the TSA exit is already complete. "
                "PASS otherwise."
            )
        )

    def test_mkt141_b177_cross_deliverable_two_files(self):
        desc = (
            "PASS if no dollar figure given for the same item differs between the memo and the workbook. FAIL if "
            "the two files give different amounts for the same item. A figure that appears in only one file passes."
        )
        self.assertTrue(exposed(desc, n_files=2))


class Safe(unittest.TestCase):
    """Wording that fails on an absent file (NOP verdict 0.0)."""

    def test_mkt141_b177_positive_with_never(self):
        self.assertFalse(
            exposed(
                "PASS if the memo identifies $95.0M as Monarch's binding contractual P&A minimum. FAIL if the memo never "
                "states the $95.0M minimum or gives a different minimum. Writing the amount as $95M passes."
            )
        )

    def test_mkt131_b187_pass_only_if_no_figure(self):
        self.assertFalse(
            exposed(
                "PASS only if the document quantifies the scope of duplication across the 110-article KB with at least "
                "one figure. FAIL if no figure quantifies the scope."
            )
        )

    def test_fin235_every_year_matches(self):
        self.assertFalse(
            exposed(
                "The workbook's base operating case must use the approved base case EBITDA for 2028 to 2031 of $43.0mm, "
                "$48.0mm, $53.0mm and $57.0mm. PASS if every one of those years matches within $0.1mm. FAIL if any year "
                "differs by more than $0.1mm."
            )
        )

    def test_svc_pc_20_3_0_row_missing_is_not_a_file_gate(self):
        desc = (
            "Campaign cash calendar line, budget: Refer-a-friend pilot, week of 14 June 2021. Expected: the line "
            "is present with a budget of $500. FAIL if the line is missing or its budget differs."
        )
        self.assertFalse(exposed(desc))
        self.assertFalse(gated(desc))


class Gated(unittest.TestCase):
    """The fix wording from each revision that then scored 0.0 on the NOP eval."""

    def test_mkt141_b184_either_file_missing(self):
        desc = (
            "FAIL if either the memo or the workbook is missing, empty or unreadable. FAIL if the memo and the "
            "workbook authorize different casting and role configurations. Otherwise PASS."
        )
        self.assertTrue(gated(desc, 2))
        self.assertFalse(exposed(desc, 2))

    def test_svc_pc_93_5_0_b130_presence_gate(self):
        desc = (
            "Alice Chen title: Presence gate: FAIL if the workbook is absent. Otherwise: Alice Chen is the CEO. "
            "FAIL if Alice Chen is given a title that contradicts CEO."
        )
        self.assertTrue(gated(desc))
        self.assertFalse(exposed(desc))

    def test_lgl131_b173_existence_gate(self):
        desc = (
            "Existence gate, applied first: this criterion requires the tenant notice (notice_to_tenant.docx). If "
            "that file is missing, cannot be read, is empty, or contains no substantive notice addressed to the "
            "tenant, this criterion FAILS; an absent document is never a pass. Evaluate whether the tenant notice "
            "avoids asserting that police were called."
        )
        self.assertTrue(gated(desc))
        self.assertFalse(exposed(desc))

    def test_directive_wording_is_recognised(self):
        desc = (
            "FAIL if EMPIRE_OF_ASH_Executive_Recommendation.docx is missing, empty or unreadable. Otherwise: "
            "FAIL only if the memo presents the full roughly $176M as owed."
        )
        self.assertTrue(gated(desc))
        self.assertFalse(exposed(desc))


def _judge(weight, files, crits):
    out = f'[judge]\njudge = "x"\nfiles = {files!r}\nweight = {weight}\n'.replace(
        "'", '"'
    )
    for i, (w, d) in enumerate(crits):
        out += f"\n[[criterion]]\nname = \"c{i}\"\ndescription = '''{d}'''\ntype = \"binary\"\nweight = {w}\n"
    return out


EXP = "FAIL only if the memo names a wrong owner."
SAFE = "PASS if the memo names the owner. FAIL if the memo never names the owner."


class Estimate(unittest.TestCase):
    def test_weighted_mean_over_groups(self):
        files = {
            "tests/reward.toml": '[[reward]]\nname = "reward"\naggregation = "weighted_mean"\n'
            'weights = {"d1" = 0.75, "d2" = 0.25}\n',
            "tests/d1/judge.toml": _judge(
                0.75, ["/app/m.docx"], [(0.3, EXP), (0.1, SAFE)]
            ),
            "tests/d2/judge.toml": _judge(0.25, ["/app/w.xlsx"], [(1.0, SAFE)]),
        }
        rep = nfc.estimate(files)
        self.assertAlmostEqual(rep["estimate"], 0.75 * 0.75)
        self.assertEqual((rep["n_criteria"], rep["n_exposed"]), (3, 1))

    def test_svc_pc_26_7_0_no_reward_weights_uses_judge_weight(self):
        files = {
            "tests/reward.toml": '[[reward]]\nname = "reward"\naggregation = "weighted_mean"\n',
            "tests/d1/judge.toml": _judge(0.2, ["/app/w.xlsx"], [(1.0, EXP)]),
            "tests/d2/judge.toml": _judge(0.6, ["/app/w.xlsx"], [(1.0, SAFE)]),
        }
        self.assertAlmostEqual(nfc.estimate(files)["estimate"], 0.25)

    def test_other_aggregation_refused(self):
        files = {
            "tests/reward.toml": '[[reward]]\nname = "reward"\naggregation = "min"\n',
            "tests/d1/judge.toml": _judge(1.0, ["/app/w.xlsx"], [(1.0, EXP)]),
        }
        with self.assertRaises(ValueError):
            nfc.estimate(files)

    def test_no_judge_files_refused(self):
        with self.assertRaises(FileNotFoundError):
            nfc.estimate({})


if __name__ == "__main__":
    unittest.main(verbosity=1)
