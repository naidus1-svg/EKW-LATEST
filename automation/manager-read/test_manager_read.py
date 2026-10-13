#!/usr/bin/env python3
"""Tests for manager_read.py. A fake `claude` command stands in for the model: no network, no paid API.

Run: python3 automation/manager-read/test_manager_read.py
"""

import contextlib
import hashlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import manager_read as mr  # noqa: E402

FAKE = r"""#!/usr/bin/env python3
import json, os, sys
sc = json.load(open(os.environ["FAKE_SCENARIO"]))
prompt = sys.argv[-1]
with open(sc["log"], "a") as f:
    f.write(json.dumps({"cwd": os.getcwd(), "has_prompt": prompt.startswith("You are the manager who approves"),
                        "reviews": open("reviews/reviews.md").read() if os.path.exists("reviews/reviews.md") else None,
                        "evidence": open("evidence.json").read() if os.path.exists("evidence.json") else None}) + "\n")
if sc.get("fail"):
    sys.stderr.write("simulated failure")
    sys.exit(3)
if sc.get("garbage"):
    print("I could not produce JSON")
    sys.exit(0)
print("done\n```json\n" + json.dumps(sc["answer"]) + "\n```")
"""

APPROVE = {"verdict": "APPROVE", "reason": "nothing", "fixes": [], "advisory": ["d1/x: low weight"], "coverage": {"criteria_total": 2}}
SEND = {
    "verdict": "SEND_BACK",
    "reason": "one criterion demands an exact wording",
    "fixes": [
        {
            "id": "F1",
            "criterion_id": "d1/heavy",
            "type": "A7",
            "test": "a",
            "weight": 0.4,
            "quote_file": "instruction.md",
            "quote": "Write a memo.",
            "problem": "demands one exact wording",
            "fix": "accept equivalent wording",
        },
        {
            "id": "F2",
            "criterion_id": "d1/light",
            "type": "U",
            "test": "a",
            "weight": 0.02,
            "quote_file": "instruction.md",
            "quote": "words that are not in the file",
            "problem": "p",
            "fix": "f",
        },
    ],
    "review_majors_rejected": [{"review": "Y2", "criterion_id": "d1/heavy", "why": "solver fault"}],
    "advisory": [],
    "coverage": {"criteria_total": 2},
}


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def review_md(rid, findings, major_count=None):
    ans = json.dumps(
        {
            "overall_verdict": "reject" if findings else "valid",
            "major_count": len([f for f in findings if f["severity"] == "major"]) if major_count is None else major_count,
            "findings": findings,
        }
    )
    return (
        "## type\nCOMPREHENSIVE_REVIEW\n\n## status\nPASSED\n\n## transcript\nQ: review it\n\nA: some prose\n\n```json\n"
        + ans
        + "\n```\n"
    )


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = self.tmp.name
        self.fake = os.path.join(self.t, "fake_claude.py")
        put(self.fake, FAKE)
        os.chmod(self.fake, os.stat(self.fake).st_mode | stat.S_IXUSR)
        # run through the interpreter so it also works on Windows
        self.fake_cmd = '"%s" "%s"' % (sys.executable, self.fake)
        self.log = os.path.join(self.t, "calls.jsonl")
        self.scn = os.path.join(self.t, "scenario.json")
        os.environ["FAKE_SCENARIO"] = self.scn
        self.out = os.path.join(self.t, "out")
        self.rev = self.make_rev()

    def tearDown(self):
        self.tmp.cleanup()

    def scenario(self, **kw):
        put(self.scn, json.dumps(dict(log=self.log, **kw)))

    def make_rev(self, n_reviews=4, name="rev_1__999"):
        """A rev_<n>__<id> folder as a Dataset with runs download holds it: task_files, verifications, evaluations."""
        r = os.path.join(self.t, name)
        tf = os.path.join(r, "task_files")
        put(os.path.join(tf, "instruction.md"), "Write a memo.")
        put(os.path.join(tf, "task.toml"), '[metadata]\ncategory = "ekw-test"\n')
        put(os.path.join(tf, "environment", "initial_workspace", "in.txt"), "data")
        put(os.path.join(tf, "solution", "sol.txt"), "answer")
        put(
            os.path.join(tf, "tests", "reward.toml"),
            '[[reward]]\nweights = {d1 = 1.0}\n',
        )
        put(
            os.path.join(tf, "tests", "d1", "judge.toml"),
            '[[criterion]]\nname = "heavy"\nweight = 0.9\ndescription = "uses the exact word"\n'
            '[[criterion]]\nname = "light"\nweight = 0.1\ndescription = "mentions a date"\n',
        )
        major = {"type": "GRADER_BUG", "severity": "major", "criteria": ["heavy"], "evidence": "x"}
        minor = {"type": "STYLE", "severity": "minor", "criteria": ["light"], "evidence": "y"}
        for i in range(n_reviews):
            put(
                os.path.join(r, "verifications", f"comprehensive_review_{100 + i}___claude-code__m.md"),
                review_md(100 + i, [major, minor] if i == 1 else [minor]),
            )
        for name, rew in (("eval_1__attempt_1__nop", 0.0), ("eval_2__attempt_1__oracle", 1.0)):
            put(
                os.path.join(r, "evaluations", name, "eval_files", "result.json"),
                json.dumps({"verifier_result": {"rewards": {"reward": rew}}}),
            )
        return r

    def run_main(self, src=None, extra=()):
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            rc = mr.main([src or self.rev, "--out", self.out, "--claude-cmd", self.fake_cmd, *extra])
        return rc, buf.getvalue(), err.getvalue()

    def report(self):
        with open(os.path.join(self.out, "manager_read_report.md"), encoding="utf-8") as f:
            return f.read()

    def calls(self):
        with open(self.log) as f:
            return [json.loads(x) for x in f if x.strip()]


class ExitCodes(Base):
    def test_approve_is_zero_and_one_call(self):
        self.scenario(answer=APPROVE)
        rc, out, _ = self.run_main()
        self.assertEqual(rc, 0)
        self.assertIn("NO ITEMS", out)
        self.assertEqual(len(self.calls()), 1)
        self.assertIn("not a clean bill of health", self.report())

    def test_send_back_is_one_with_items(self):
        self.scenario(answer=SEND)
        rc, out, _ = self.run_main()
        self.assertEqual(rc, 1)
        self.assertIn("2 ITEM", out)
        rep = self.report()
        for needle in ("d1/heavy", "instruction.md", "Write a memo.", "accept equivalent wording", "needs a written answer"):
            self.assertIn(needle, rep)
        self.assertIn("quote found in that file", rep)
        self.assertIn("quote NOT found", rep)
        self.assertIn("(UNAUDITED", rep)
        self.assertTrue(os.path.exists(os.path.join(self.out, "manager_read_result.json")))

    def test_send_back_without_items_still_one(self):
        self.scenario(answer=dict(SEND, fixes=[]))
        rc, _, _ = self.run_main()
        self.assertEqual(rc, 1)

    def test_claude_failure_is_two(self):
        self.scenario(fail=True)
        rc, _, err = self.run_main()
        self.assertEqual(rc, 2)
        self.assertIn("could not run", err)
        self.assertIn("COULD NOT RUN", self.report())

    def test_garbage_twice_is_two(self):
        self.scenario(garbage=True)
        rc, _, _ = self.run_main()
        self.assertEqual(rc, 2)
        self.assertEqual(len(self.calls()), 2)

    def test_hold_is_two(self):
        self.scenario(answer={"verdict": "HOLD", "reason": "file unreadable", "fixes": []})
        rc, _, _ = self.run_main()
        self.assertEqual(rc, 2)
        self.assertIn("COULD NOT JUDGE", self.report())

    def test_missing_claude_is_two(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = mr.main([self.rev, "--out", self.out, "--claude-cmd", os.path.join(self.t, "no_such_claude")])
        self.assertEqual(rc, 2)

    def test_not_a_folder_is_two(self):
        self.scenario(answer=APPROVE)
        rc, _, _ = self.run_main(os.path.join(self.t, "nope"))
        self.assertEqual(rc, 2)


class Inputs(Base):
    def test_reviews_and_evidence_reach_the_reader(self):
        self.scenario(answer=APPROVE)
        self.run_main()
        c = self.calls()[0]
        self.assertTrue(c["has_prompt"])
        self.assertIn("Four reviews ran (Y1 to Y4)", c["reviews"])
        self.assertIn("## Review Y2: reports a major", c["reviews"])
        self.assertIn("## Review Y1: no major reported", c["reviews"])
        self.assertIn("Major 1", c["reviews"])
        self.assertNotIn("STYLE", c["reviews"])  # minor findings are not stored
        self.assertIn('"max_reward": 0.0', c["evidence"])

    def test_fewer_than_four_reviews_gives_the_note(self):
        rev = self.make_rev(n_reviews=3, name="rev_1__998")
        self.scenario(answer=APPROVE)
        self.run_main(rev)
        self.assertIn("No complete version 8 review run is available", self.calls()[0]["reviews"])

    def test_reader_runs_in_a_copy_and_original_is_untouched(self):
        self.scenario(answer=APPROVE)
        before = sorted(os.listdir(os.path.join(self.rev, "task_files")))
        self.run_main()
        self.assertEqual(before, sorted(os.listdir(os.path.join(self.rev, "task_files"))))
        self.assertNotEqual(os.path.dirname(self.calls()[0]["cwd"]), self.rev)
        self.assertFalse(os.path.exists(self.calls()[0]["cwd"]))  # throwaway removed

    def test_plain_package_folder_has_no_reviews(self):
        self.scenario(answer=APPROVE)
        rc, _, _ = self.run_main(os.path.join(self.rev, "task_files"))
        self.assertEqual(rc, 0)
        self.assertIn("No complete version 8 review run", self.calls()[0]["reviews"])

    def test_reviews_option(self):
        self.scenario(answer=APPROVE)
        rc, _, _ = self.run_main(
            os.path.join(self.rev, "task_files"), ("--reviews", os.path.join(self.rev, "verifications"))
        )
        self.assertEqual(rc, 0)
        self.assertIn("Four reviews ran", self.calls()[0]["reviews"])

    def test_tab_option_labels_report(self):
        self.scenario(answer=APPROVE)
        self.run_main(extra=("--tab", "svc"))
        self.assertIn("Kind: SVC", self.report())


class BadGrader(Base):
    def test_grader_without_weights_is_exit_two_not_a_traceback(self):
        self.scenario(answer=APPROVE)
        put(os.path.join(self.rev, "task_files", "tests", "reward.toml"), "")
        os.remove(os.path.join(self.rev, "task_files", "tests", "d1", "judge.toml"))
        os.remove(os.path.join(self.rev, "task_files", "tests", "reward.toml"))
        put(
            os.path.join(self.rev, "task_files", "tests", "verifier.json"),
            json.dumps({"verifiers": [{"name": "a", "metadata": {"importance": "core"}}]}),
        )
        rc, _, err = self.run_main()
        self.assertEqual(rc, 2)
        self.assertIn("cannot read the grader files", err)


class Prompt(Base):
    def test_prompt_hash_matches_record(self):
        with open(mr.PROMPT_FILE, "rb") as f:
            raw = f.read()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), mr.PROMPT_SHA256)

    def test_changed_prompt_stops_the_run(self):
        self.scenario(answer=APPROVE)
        saved = mr.PROMPT_SHA256
        mr.PROMPT_SHA256 = "0" * 64
        try:
            rc, _, err = self.run_main()
        finally:
            mr.PROMPT_SHA256 = saved
        self.assertEqual(rc, 2)
        self.assertIn("sha256", err)
        self.assertEqual(self.calls() if os.path.exists(self.log) else [], [])

    def test_prompt_has_no_labels_or_expected_values(self):
        with open(mr.PROMPT_FILE, encoding="utf-8") as f:
            t = f.read().lower()
        for bad in ("tfrl", "material_tabrule", "truth_v5", "audit-defective"):
            self.assertNotIn(bad, t)

    def test_a_crash_is_could_not_run_never_a_finding(self):
        import contextlib
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            pkg = os.path.join(td, "pkg")
            os.makedirs(pkg)
            out = os.path.join(td, "out")
            orig = mr.read_task

            def boom(*a, **k):
                raise RuntimeError("boom")

            mr.read_task = boom
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    code = mr.main([pkg, "--out", out])
            finally:
                mr.read_task = orig
            self.assertEqual(code, 2)
            with open(os.path.join(out, "manager_read_report.md"), encoding="utf-8") as fh:
                self.assertIn("unexpected error", fh.read().lower())

    def test_tool_list_allows_python_and_powershell_on_windows_only(self):
        if os.name == "nt":
            for rule in ("Bash(python:*)", "PowerShell(python:*)", "PowerShell(Get-ChildItem:*)"):
                self.assertIn(rule, mr.TOOLS)
        else:
            self.assertNotIn("PowerShell", mr.TOOLS)
        self.assertIn("Bash(python3:*)", mr.TOOLS)

    def test_runner_limits_the_available_tools(self):
        seen = {}

        class Done:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def fake_run(argv, **kw):
            seen["argv"] = argv
            return Done()

        orig = mr.subprocess.run
        mr.subprocess.run = fake_run
        try:
            mr.Runner("claude")("reader", "prompt text", os.getcwd(), mr.TOOLS)
        finally:
            mr.subprocess.run = orig
        argv = seen["argv"]
        names = argv[argv.index("--tools") + 1].split(",")
        self.assertIn("Read", names)
        self.assertIn("Bash", names)
        self.assertNotIn("Agent", names)
        self.assertNotIn("SendMessage", names)
        self.assertTrue(all("(" not in n for n in names))
        self.assertLess(argv.index("--tools"), argv.index("--allowedTools"))
        if os.name == "nt":
            self.assertTrue(argv[-1].endswith(mr.WINDOWS_NOTE))
        else:
            self.assertEqual(argv[-1], "prompt text")

    def test_runner_decodes_model_output_as_utf8(self):
        # Windows decodes captured text as cp1252 unless told otherwise, and cp1252 has no byte 0x90
        # (it sits inside U+2010, a Cyrillic A and an eth), so a read stopped with exit 2.
        with tempfile.TemporaryDirectory() as td:
            fake = os.path.join(td, "fake_claude.py")
            with open(fake, "w", encoding="utf-8") as f:
                f.write(
                    "import sys\n"
                    "sys.stdout.buffer.write(b'ok \\xe2\\x80\\x90 \\xd0\\x90 \\xc3\\x90 done')\n"
                )
            runner = mr.Runner("claude")
            runner.cmd = [sys.executable, fake]
            out = runner("reader", "prompt text", td, mr.TOOLS)
        self.assertEqual(out, "ok \u2010 \u0410 \u00d0 done")

    def test_failed_call_shows_stdout_and_stderr(self):
        # claude prints the API error on stdout and a harmless warning on stderr; the report must carry both.
        class Failed:
            returncode = 1
            stdout = "API Error: Claude's response exceeded the 32000 output token maximum."
            stderr = '[claude-code:unrecognized_model] {"model":"glm-5.2"}'

        orig = mr.subprocess.run
        mr.subprocess.run = lambda argv, **kw: Failed()
        try:
            with self.assertRaises(mr.CouldNotRun) as cm:
                mr.Runner("claude")("finder", "prompt text", os.getcwd(), mr.TOOLS)
        finally:
            mr.subprocess.run = orig
        self.assertIn("API Error", str(cm.exception))
        self.assertIn("unrecognized_model", str(cm.exception))


if __name__ == "__main__":
    r = unittest.main(exit=False, verbosity=0)
    n = r.result.testsRun
    bad = len(r.result.failures) + len(r.result.errors)
    print(f"TESTS {n - bad}/{n} passed")
    sys.exit(1 if bad else 0)
