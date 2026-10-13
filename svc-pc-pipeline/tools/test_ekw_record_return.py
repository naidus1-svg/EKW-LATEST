#!/usr/bin/env python3
"""Tests for ekw_record_return.py. Stdlib only, temp dirs, no sandbox paths touched. Each case builds a fake
EKW lane work dir and a synthetic DataOS *_with_runs.zip (task roots named by EKW task id, the same
<task>/rev_N__id/{task_files,evaluations,verifications}/ layout real returns have), then runs the tool.

That the pass rule is svc_record_return's is proved read-only on the sandbox against a real return:
  python3 tools/ekw_record_return.py <real return zip> --svc-rule-equivalence
Run: python tools/test_ekw_record_return.py"""

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ekw_record_return as err  # noqa: E402
import svc_record_return as srr  # noqa: E402

# The review prompt itself carries an EXAMPLE verdict JSON; only the LAST one is the reviewer's answer.
EXAMPLE = '{"overall_verdict": "reject", "major_count": 9, "checks": [{"check": "1.1", "severity": "major"}]}'


def review_md(majors, moderates=(), tag=""):
    checks = (
        [
            {
                "check": cid,
                "severity": "major",
                "name": "major %s %s" % (cid, tag),
                "justification": "WHY-%s-%s criterion v3 grades a figure the prompt never asks for"
                % (cid, tag),
                "suggested_fix": "FIX-%s-%s loosen v3" % (cid, tag),
            }
            for cid in majors
        ]
        + [
            {
                "check": cid,
                "severity": "moderate",
                "name": "moderate %s" % cid,
                "justification": "MOD-%s-%s" % (cid, tag),
                "suggested_fix": "",
            }
            for cid in moderates
        ]
        + [
            {
                "check": "1.9",
                "severity": "minor",
                "name": "minor-noise",
                "justification": "MINOR-NOISE",
            }
        ]
    )
    verdict = {
        "overall_verdict": "reject" if majors else "approve",
        "major_count": len(majors),
        "checks": checks,
        "summary": "s",
    }
    return (
        "## status\nPASSED\n\n## prompt\nReturn JSON like %s\n\n## transcript\n...\n%s\n"
        % (EXAMPLE, json.dumps(verdict))
    )


def build_return(path, spec, rev="rev_1__100"):
    """spec: {task: [review .md text, ...]} ; an empty list = a task DataOS never reviewed."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for t, reviews in spec.items():
            r = "%s/%s" % (t, rev)
            z.writestr(r + "/task_files/instruction.md", "do the thing for %s\n" % t)
            z.writestr(
                r + "/task_files/tests/deliverables_01/judge.toml",
                "[criterion]\nid='v1-%s'\n" % t,
            )
            z.writestr(r + "/task_files/tests/test.sh", "#!/bin/sh\n")
            z.writestr(
                r + "/evaluations/eval_1__attempt_1__oracle/verifier/reward.json",
                '{"reward": 1.0}',
            )
            for i, md in enumerate(reviews):
                z.writestr(
                    r
                    + "/verifications/comprehensive_review_%d___codex__gpt-5.6-sol.md"
                    % (900 + i),
                    md,
                )
            z.writestr(
                r + "/verifications/qc_1___codex__gpt-5.6-sol.md",
                review_md(["1.1"], tag="qc-ignored"),
            )
    return path


def add_evals(path, task, rev, evals):
    """Append <task>/<rev>/evaluations/eval_<id>__attempt_1__<agent>/eval_files/verifier/{reward.json,
    test-stdout.txt,runtime.log} entries to an already-built return zip (the real path shape; build_return's
    own stub reward.json is one level shallower and is never read by the marker scan). `evals` is
    [(eval_id, agent, reward, ungraded), ...]; ungraded=True writes the line DataOS's harness writes when
    rewardkit exits 1 and never produces a reward.json, into runtime.log, matching a real 2026-09-29
    DataOS return byte for byte (the marker was never seen in test-stdout.txt in any return checked).
    """
    with zipfile.ZipFile(path, "a", zipfile.ZIP_DEFLATED) as z:
        for eval_id, agent, reward, ungraded in evals:
            base = "%s/%s/evaluations/eval_%s__attempt_1__%s/eval_files/verifier/" % (
                task,
                rev,
                eval_id,
                agent,
            )
            z.writestr(base + "reward.json", json.dumps({"reward": reward}))
            if ungraded:
                z.writestr(
                    base + "test-stdout.txt", "  0%|          | 0/1 [00:00<?, ?it/s]\n"
                )
                z.writestr(
                    base + "runtime.log",
                    "RuntimeError: Reward 'deliverables_01' failed: "
                    "litellm.ServiceUnavailableError: AnthropicException - credential validation "
                    "failed. Handle with `litellm.ServiceUnavailableError`.\n"
                    "rewardkit exited 1 and wrote no reward.json; see runtime.log\n",
                )
            else:
                z.writestr(base + "test-stdout.txt", "ok\n")
                z.writestr(base + "runtime.log", "ok\n")


def snapshot(root):
    out = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = hashlib.sha256(fh.read()).hexdigest()
        if not fs:
            out[os.path.relpath(d, root) + "/"] = "dir"
    return out


class TestRecordReturn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ekwrr_")
        self.work = os.path.join(self.tmp, "_ekw")
        self.rets = os.path.join(self.tmp, "_returns")
        self.dl = os.path.join(self.tmp, "dl")
        for d in ("claims", "ready", "verify", "gate", "briefs"):
            os.makedirs(os.path.join(self.work, d))
        os.makedirs(self.dl)
        self.w(
            "queue.txt",
            "# EKW v1 queue header\nLGL-131\nLGL-140\nSCO-174\nSCO-198\nLGL-200\n",
        )
        self.w("decide.txt", "SCO-198\nLGL-186\n")
        for t in ("LGL-131", "LGL-140", "SCO-198", "LGL-200"):
            os.makedirs(os.path.join(self.work, "claims", t))
        for t in ("LGL-131", "SCO-198"):
            self.w("ready/%s.zip" % t, "zipbytes")
            self.w("ready/%s.zip.manifest.json" % t, "{}")
            self.w(
                "verify/%s.verify.md" % t, "old record\nVERDICT: READY-TO-RESUBMIT\n"
            )
            self.w("gate/%s.gate.json" % t, '{"verdict": "PASS"}')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def w(self, rel, text):
        p = os.path.join(self.work, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8", newline="\n").write(text)

    def r(self, rel):
        return open(os.path.join(self.work, rel), encoding="utf-8").read()

    def run_tool(self, zp, apply=False):
        argv = [zp, "--work", self.work, "--returns-dir", self.rets] + (
            ["--apply"] if apply else []
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = err.main(argv)
        return rc, buf.getvalue()

    def standard_return(self, name="ekw-v1-batch1_with_runs.zip"):
        return build_return(
            os.path.join(self.dl, name),
            {
                "LGL-131": [
                    review_md([]),
                    review_md([], moderates=["1.4"]),
                ],  # PASS 2 of 2
                "SCO-198": [
                    review_md(["1.5"], ["1.4"], tag="r1"),
                    review_md([]),
                ],  # FAIL 1 of 2
                "LGL-140": [],  # never reviewed
            },
        )

    def test_near_miss_goes_ahead_of_zero_of_two(self):
        # 2026-09-26 (owner): a 1-of-2 reject is one seat from passing, so it heads the queue even when a 0-of-2
        # reject sorts first by name (AAA-100 < SCO-198).
        zp = build_return(
            os.path.join(self.dl, "ekw-v1-batch9_with_runs.zip"),
            {
                "AAA-100": [
                    review_md(["1.5"], tag="a"),
                    review_md(["1.4"], tag="b"),
                ],  # 0 of 2
                "SCO-198": [review_md(["1.5"], tag="r1"), review_md([])],  # 1 of 2
            },
        )
        os.makedirs(os.path.join(self.work, "claims", "AAA-100"))
        rc, _ = self.run_tool(zp, apply=True)
        self.assertEqual(rc, 0)
        q = [
            ln
            for ln in self.r("queue.txt").splitlines()
            if ln and not ln.startswith("#")
        ]
        self.assertEqual(q[:2], ["SCO-198", "AAA-100"])

    def test_dry_run_writes_nothing(self):
        zp = self.standard_return()
        before = snapshot(self.tmp)
        rc, out = self.run_tool(zp)
        self.assertEqual(rc, 0)
        self.assertIn("DRY RUN", out)
        self.assertIn("LGL-131    PASS (2 of 2", out)
        self.assertIn("SCO-198    FAIL (1 of 2", out)
        self.assertEqual(snapshot(self.tmp), before)
        self.assertFalse(os.path.exists(self.rets))

    def test_pass_freezes_and_keeps_claim(self):
        rc, _ = self.run_tool(self.standard_return(), apply=True)
        self.assertEqual(rc, 0)
        self.assertIn("LGL-131", self.r("accepted.txt").split())
        self.assertTrue(os.path.isdir(os.path.join(self.work, "claims", "LGL-131")))
        self.assertNotIn("LGL-131", self.r("queue.txt").split())
        self.assertTrue(
            os.path.exists(os.path.join(self.work, "ready", "LGL-131.zip"))
        )  # a pass is not archived
        self.assertFalse(
            os.path.exists(os.path.join(self.work, "briefs", "LGL-131.md"))
        )

    def test_fail_requeues_releases_claim_writes_brief(self):
        zp = self.standard_return()
        rc, _ = self.run_tool(zp, apply=True)
        self.assertEqual(rc, 0)
        W = self.work
        self.assertFalse(os.path.exists(os.path.join(W, "claims", "SCO-198")))
        q = [ln for ln in self.r("queue.txt").splitlines() if ln]
        self.assertEqual(q[0], "# EKW v1 queue header")
        self.assertEqual(q[1], "SCO-198")
        self.assertEqual(q.count("SCO-198"), 1)
        self.assertEqual(q[2:], ["LGL-140", "SCO-174", "LGL-200"])
        self.assertNotIn("SCO-198", self.r("decide.txt").split())
        self.assertIn("LGL-186", self.r("decide.txt").split())
        with zipfile.ZipFile(zp) as z:
            want = srr.tests_hash_from_zip(z, "SCO-198")
        self.assertTrue(want)
        self.assertEqual(self.r("lastreject/SCO-198.lastreject.sha").strip(), want)
        arch = "_pre_ekw-v1-batch1_with_runs"
        self.assertIn("READY-TO-RESUBMIT", self.r("verify/%s/SCO-198.verify.md" % arch))
        self.assertTrue(
            os.path.exists(os.path.join(W, "verify", arch, "SCO-198.gate.json"))
        )
        self.assertFalse(os.path.exists(os.path.join(W, "gate", "SCO-198.gate.json")))
        ra = os.path.join(W, "ready", "_returned_ekw-v1-batch1_with_runs")
        self.assertTrue(os.path.exists(os.path.join(ra, "SCO-198.zip")))
        self.assertTrue(os.path.exists(os.path.join(ra, "SCO-198.zip.manifest.json")))
        self.assertFalse(os.path.exists(os.path.join(W, "ready", "SCO-198.zip")))
        brief = self.r("briefs/SCO-198.md")
        self.assertIn("WHY-1.5-r1 criterion v3", brief)
        self.assertIn("FIX-1.5-r1 loosen v3", brief)
        self.assertIn("MOD-1.4-r1", brief)
        self.assertNotIn("MINOR-NOISE", brief)
        self.assertNotIn("qc-ignored", brief)
        self.assertNotIn(chr(0x2014), brief)  # no em dash
        # the runner seeds fix mode from a verify record that greps VERDICT: *NOT-READY; the brief is that record
        self.assertEqual(self.r("verify/SCO-198.verify.md"), brief)
        self.assertTrue(re.search(r"VERDICT: *NOT-READY", brief, re.I))
        self.assertIn("LGL-140", self.r("needs_regrade.txt").split())
        self.assertTrue(os.path.isdir(os.path.join(W, "claims", "LGL-140")))
        self.assertEqual(
            open(os.path.join(self.rets, os.path.basename(zp)), "rb").read(),
            open(zp, "rb").read(),
        )

    def test_rerun_is_idempotent_and_never_releases_a_new_claim(self):
        zp = self.standard_return()
        self.run_tool(zp, apply=True)
        os.makedirs(
            os.path.join(self.work, "claims", "SCO-198")
        )  # a lane picked the reject up again
        before = snapshot(self.tmp)
        rc, out = self.run_tool(zp, apply=True)
        self.assertEqual(rc, 0)
        self.assertIn("already recorded", out)
        self.assertEqual(snapshot(self.tmp), before)
        # the copy in _returns is the same return: running from it is also a no-op
        self.run_tool(os.path.join(self.rets, os.path.basename(zp)), apply=True)
        self.assertEqual(snapshot(self.tmp), before)

    def test_second_round_brief_carries_both_rounds(self):
        self.run_tool(self.standard_return(), apply=True)
        z2 = build_return(
            os.path.join(self.dl, "ekw-v1-batch2_with_runs.zip"),
            {"SCO-198": [review_md(["1.4"], tag="r2"), review_md(["1.1"], tag="r2b")]},
            rev="rev_2__200",
        )
        rc, _ = self.run_tool(z2, apply=True)
        self.assertEqual(rc, 0)
        b = self.r("briefs/SCO-198.md")
        self.assertIn("WHY-1.5-r1", b)
        self.assertIn("WHY-1.4-r2", b)
        self.assertIn("WHY-1.1-r2b", b)
        self.assertLess(b.index("WHY-1.5-r1"), b.index("WHY-1.4-r2"))
        self.assertIn(
            "SCO-198", self.r("verify/_pre_ekw-v1-batch2_with_runs/SCO-198.verify.md")
        )

    def test_do_not_touch_reject_is_not_requeued(self):
        self.w("do_not_touch.txt", "SCO-198\n")
        self.run_tool(self.standard_return(), apply=True)
        self.assertTrue(os.path.isdir(os.path.join(self.work, "claims", "SCO-198")))
        self.assertFalse(
            os.path.exists(os.path.join(self.work, "briefs", "SCO-198.md"))
        )
        self.assertTrue(os.path.exists(os.path.join(self.work, "ready", "SCO-198.zip")))

    def test_zip_without_ekw_roots_is_refused(self):
        zp = build_return(
            os.path.join(self.dl, "other_with_runs.zip"),
            {"misc-folder": [review_md([])]},
        )
        before = snapshot(self.tmp)
        rc, _ = self.run_tool(zp, apply=True)
        self.assertEqual(rc, 1)
        self.assertEqual(snapshot(self.tmp), before)

    def test_pass_with_ungraded_oracle_prints_warning(self):
        # 2026-09-29: DataOS's judge failed for every evaluation (oracle + 2 agents) on two real returns
        # while the reviews still said PASS 2 of 2; the tool counted the pass and said nothing. This is
        # that shape: reviews pass, but the oracle eval never graded.
        zp = build_return(
            os.path.join(self.dl, "ekw-v1-warntest_with_runs.zip"),
            {"LGL-131": [review_md([]), review_md([])]},  # PASS 2 of 2
        )
        add_evals(
            zp,
            "LGL-131",
            "rev_1__100",
            [
                ("9001", "oracle", 0.0, True),
                ("9002", "terminus-2__gpt-5.6-sol", 1.0, False),
                ("9003", "codex__gpt-5.6-sol", 1.0, False),
            ],
        )
        rc, out = self.run_tool(zp, apply=False)
        self.assertEqual(rc, 0)
        self.assertIn(
            "WARNING LGL-131: PASS on reviews, but 1 of 3 evaluations did not grade",
            out,
        )
        self.assertIn("oracle: did not grade", out)
        self.assertIn("9001", out)
        self.assertIn(
            "Run an oracle-only DataOS evaluation on revision 100 before QC", out
        )

    def test_pass_with_graded_evals_prints_no_warning(self):
        zp = build_return(
            os.path.join(self.dl, "ekw-v1-cleantest_with_runs.zip"),
            {"LGL-131": [review_md([]), review_md([])]},  # PASS 2 of 2
        )
        add_evals(
            zp,
            "LGL-131",
            "rev_1__100",
            [
                ("9001", "oracle", 1.0, False),
                ("9002", "terminus-2__gpt-5.6-sol", 1.0, False),
                ("9003", "codex__gpt-5.6-sol", 1.0, False),
            ],
        )
        rc, out = self.run_tool(zp, apply=False)
        self.assertEqual(rc, 0)
        self.assertNotIn("WARNING", out)
        self.assertNotIn("did not grade", out)

    def test_ungraded_marker_does_not_change_verdict_or_files(self):
        # The warning is print-only: a PASS with an ungraded oracle still freezes and keeps its claim
        # exactly like test_pass_freezes_and_keeps_claim, in both dry-run and --apply.
        zp = build_return(
            os.path.join(self.dl, "ekw-v1-warnapply_with_runs.zip"),
            {"LGL-131": [review_md([]), review_md([])]},  # PASS 2 of 2
        )
        add_evals(
            zp,
            "LGL-131",
            "rev_1__100",
            [
                ("9001", "oracle", 0.0, True),
                ("9002", "terminus-2__gpt-5.6-sol", 1.0, False),
            ],
        )
        rc, out = self.run_tool(zp, apply=False)
        self.assertEqual(rc, 0)
        self.assertIn("WARNING LGL-131", out)
        self.assertIn("LGL-131    PASS (2 of 2", out)  # verdict itself unaffected

        rc, out = self.run_tool(zp, apply=True)
        self.assertEqual(rc, 0)
        self.assertIn("WARNING LGL-131", out)  # printed in --apply too
        self.assertIn("LGL-131", self.r("accepted.txt").split())
        self.assertTrue(os.path.isdir(os.path.join(self.work, "claims", "LGL-131")))
        self.assertTrue(os.path.exists(os.path.join(self.work, "ready", "LGL-131.zip")))
        self.assertFalse(
            os.path.exists(os.path.join(self.work, "briefs", "LGL-131.md"))
        )

    def test_format_ungraded_warning_shape(self):
        ungraded = [
            ("100", "oracle", "9001", "RuntimeError: boom"),
            ("100", "terminus-2__gpt-5.6-sol", "9002", "RuntimeError: boom2"),
        ]
        msg = srr.format_ungraded_warning("LGL-131", 3, ungraded)
        self.assertTrue(
            msg.startswith(
                "WARNING LGL-131: PASS on reviews, but 2 of 3 evaluations did not grade"
            )
        )
        self.assertIn("oracle: did not grade", msg)
        self.assertIn("9001", msg)
        self.assertIn("9002", msg)
        self.assertIn("revision 100", msg)
        self.assertNotIn(chr(0x2014), msg)  # no em dash

    def test_format_ungraded_note_shape(self):
        msg = srr.format_ungraded_note(
            "SCO-198", 2, [("100", "oracle", "9001", "boom")]
        )
        self.assertTrue(
            msg.startswith("note SCO-198: 1 of 2 evaluations did not grade")
        )
        self.assertIn("not PASS", msg)

    def test_ungraded_evals_from_zip_direct(self):
        zp = build_return(
            os.path.join(self.dl, "ekw-v1-directtest_with_runs.zip"),
            {"LGL-131": [review_md([])]},
        )
        add_evals(
            zp,
            "LGL-131",
            "rev_1__555",
            [
                ("1", "oracle", 0.0, True),
                ("2", "terminus-2__gpt-5.6-sol", 1.0, False),
            ],
        )
        with zipfile.ZipFile(zp) as z:
            result = srr.ungraded_evals_from_zip(z, ["LGL-131"])
        total, ungraded = result["LGL-131"]
        self.assertEqual(total, 2)
        self.assertEqual(len(ungraded), 1)
        revid, agent, evalid, cause = ungraded[0]
        self.assertEqual(revid, "555")
        self.assertEqual(agent, "oracle")
        self.assertEqual(evalid, "1")
        self.assertIn("RuntimeError", cause)

    def test_rule_matches_review_summary_edge_cases(self):
        """Any major fails the task, so 2 clean of 3 fails; an unparseable review also fails it."""
        by = {
            "A-1": [
                {"parsed": True, "major_count": 0},
                {"parsed": True, "major_count": 1},
            ],
            "A-2": [{"parsed": True, "major_count": 0}] * 2
            + [{"parsed": True, "major_count": 3}],
            "A-3": [
                {"parsed": True, "major_count": 0},
                {"parsed": False, "major_count": None},
            ],
            "A-4": [],
        }
        self.assertEqual(
            err.verdicts_from_reviews(by),
            {
                "A-1": ("FAIL", 1, 2),
                "A-2": ("FAIL", 2, 3),
                "A-3": ("FAIL", 1, 1),
                "A-4": ("FAIL", 0, 0),
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
