#!/usr/bin/env python3
"""Tests for task_read.py. A fake `claude` command stands in for the model: no network, no paid API.

Run: python3 automation/task-read/test_task_read.py
"""

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import task_read as tr  # noqa: E402

FAKE = r"""#!/usr/bin/env python3
import json, os, sys
sc = json.load(open(os.environ["FAKE_SCENARIO"]))
prompt = sys.argv[-1]
if prompt.lstrip().startswith("Layout note"):
    prompt = prompt.split("\n\n", 1)[1]
if prompt.startswith("You are a manager reviewing"):
    role = "reader"
elif prompt.startswith("# Defect finder"):
    # finder A and finder B now use the same prompt; the folder name tells them apart
    role = "finderB" if os.path.basename(os.getcwd()).startswith("finderB") else "finderA"
elif prompt.startswith("# Verifier"):
    role = "verifier"
else:
    role = "unknown"
if sc.get("fail") == role:
    sys.stderr.write("simulated failure of " + role)
    sys.exit(3)
if role == "reader":
    print("done\n```json\n" + json.dumps(sc["reader"]) + "\n```")
elif role in ("finderA", "finderB"):
    json.dump(sc[role], open("defects.json", "w"))
elif role == "verifier":
    fs = json.load(open("findings.json"))
    out = []
    for f in fs:
        crit = sc["verdict_for"]
        out.append({"id": f["id"], "criteria": crit["criteria"], "verdict": crit["verdict"],
                    "tests_met": ["a"], "answer_sketch": "a sketch", "evidence": ["instruction.md: some words"],
                    "note": "the criterion asks for more than the instruction"})
    json.dump({"verdicts": out}, open("verdicts.json", "w"))
"""

APPROVE = {"verdict": "APPROVE", "tier_a": [], "tier_b": []}
DENY_A2 = {
    "verdict": "DENY",
    "tier_a": [
        {
            "rule": "A2",
            "criteria": ["d1/heavy"],
            "weight": 0.4,
            "evidence": "instruction: x | criterion: y",
        }
    ],
    "tier_b": [],
}
EMPTY = {
    "defects": [],
    "coverage": {"read_closely": [], "skimmed": [], "not_read": [], "note": ""},
}


def defect(ids, test="a"):
    return {
        "defects": [
            {
                "id": "D1",
                "criteria": ids,
                "weight": 0.1,
                "test": test,
                "quotes": ["instruction.md: words"],
                "answer_sketch": "s",
                "description": "asks for more",
            }
        ],
        "coverage": {"read_closely": ids, "skimmed": [], "not_read": [], "note": ""},
    }


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read().lower()


def put(path, text):
    with open(path, "w") as f:
        f.write(text)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = self.tmp.name
        self.fake = os.path.join(self.t, "fake_claude.py")
        put(self.fake, FAKE)
        os.chmod(self.fake, os.stat(self.fake).st_mode | stat.S_IXUSR)
        # run the fake through the interpreter so it also works on Windows, where a .py file is not directly executable
        self.fake_cmd = '"%s" "%s"' % (sys.executable, self.fake)
        self.pkg = self.make_pkg()
        self.out = os.path.join(self.t, "out")

    def tearDown(self):
        self.tmp.cleanup()

    def make_pkg(self, heavy=0.4):
        """EKW-style package: two deliverable dirs, criteria weights heavy / small (0.4 and 0.02 of the total)."""
        p = os.path.join(self.t, "task1")
        os.makedirs(os.path.join(p, "tests", "d1"))
        os.makedirs(os.path.join(p, "environment", "initial_workspace"))
        os.makedirs(os.path.join(p, "solution"))
        put(os.path.join(p, "instruction.md"), "Write a memo.")
        put(os.path.join(p, "task.toml"), '[metadata]\ncategory = "EKW"\n')
        put(os.path.join(p, "environment", "initial_workspace", "in.txt"), "data")
        put(os.path.join(p, "solution", "solve.sh"), "true")
        put(
            os.path.join(p, "tests", "reward.toml"),
            "[[reward]]\nweights = {d1 = 1.0}\n",
        )
        put(
            os.path.join(p, "tests", "d1", "judge.toml"),
            '[[criterion]]\nname = "heavy"\nweight = 40\ndescription = "big item"\n'
            '[[criterion]]\nname = "light"\nweight = 2\ndescription = "small item"\n'
            '[[criterion]]\nname = "rest"\nweight = 58\ndescription = "other item"\n',
        )
        return p

    def run_main(self, scenario, expect_rc):
        sc = os.path.join(self.t, "scenario.json")
        put(sc, json.dumps(scenario))
        os.environ["FAKE_SCENARIO"] = sc
        with contextlib.redirect_stdout(io.StringIO()):
            rc = tr.main([self.pkg, "--out", self.out, "--claude-cmd", self.fake_cmd])
        self.assertEqual(rc, expect_rc)
        return self.report()

    def report(self):
        with open(os.path.join(self.out, "task_read_report.md")) as f:
            return f.read()

    def scenario(
        self,
        reader=APPROVE,
        a=EMPTY,
        b=EMPTY,
        ids=("d1/heavy",),
        verdict="VERIFIED",
        fail=None,
    ):
        return dict(
            reader=reader,
            finderA=a,
            finderB=b,
            verdict_for=dict(criteria=list(ids), verdict=verdict),
            fail=fail,
        )


class TestTaskRead(Base):
    def test_weights_from_raw_package(self):
        ws = os.path.join(self.t, "ws")
        tr.build_audit_layout(self.pkg, ws)
        c = {
            x["id"]: x["w"]
            for x in tr.jload(os.path.join(ws, "rubric", "criteria.json"))
        }
        self.assertAlmostEqual(c["d1/heavy"], 0.40, places=3)
        self.assertAlmostEqual(c["d1/light"], 0.02, places=3)
        self.assertAlmostEqual(sum(c.values()), 1.0, places=3)

    def test_flagged_by_reader_only(self):
        rep = self.run_main(self.scenario(reader=DENY_A2), 1)
        self.assertIn("FLAGGED", rep)
        self.assertIn("Reader rule A2", rep)
        res = tr.jload(os.path.join(self.out, "task_read_result.json"))
        self.assertTrue(res["flagged_by_reader"])
        self.assertFalse(res["flagged_by_verifier"])

    def test_flagged_by_verifier_only(self):
        d = defect(["d1/heavy"])
        rep = self.run_main(self.scenario(a=d, b=d, ids=("d1/heavy",)), 1)
        self.assertIn("Verified finding", rep)
        self.assertIn("d1/heavy", rep)
        self.assertIn("instruction.md: some words", rep)
        res = tr.jload(os.path.join(self.out, "task_read_result.json"))
        self.assertTrue(res["flagged_by_verifier"])
        self.assertFalse(res["flagged_by_reader"])

    def test_not_flagged(self):
        rep = self.run_main(self.scenario(), 0)
        self.assertIn("NOT FLAGGED", rep)
        self.assertNotIn("Reader rule", rep)

    def test_reader_rule_outside_a1_a2_a3_a7_does_not_flag(self):
        r = {
            "verdict": "DENY",
            "tier_a": [
                {"rule": "A4", "criteria": ["x"], "weight": 0.3, "evidence": "e"}
            ],
            "tier_b": [],
        }
        self.run_main(self.scenario(reader=r), 0)

    def test_light_criterion_verified_does_not_flag(self):
        d = defect(["d1/light"])
        rep = self.run_main(self.scenario(a=d, b=d, ids=("d1/light",)), 0)
        self.assertIn("NOT FLAGGED", rep)
        self.assertIn("too light to flag", rep)

    def test_unverified_finding_does_not_flag(self):
        d = defect(["d1/heavy"])
        self.run_main(self.scenario(a=d, b=d, verdict="NOT_A_DEFECT"), 0)

    def test_material_rule_ekw_threshold(self):
        w = {"a": 0.5, "b": 0.05, "c": 0.0499}
        self.assertTrue(tr.counts(0.05, w, True))
        self.assertFalse(tr.counts(0.0499, w, True))

    def test_material_rule_svc_three_heaviest(self):
        w = {"a": 0.4, "b": 0.3, "c": 0.2, "d": 0.1}
        self.assertTrue(tr.counts(0.2, w, False))
        self.assertFalse(tr.counts(0.1, w, False))
        self.assertTrue(
            tr.counts(0.05, {"a": 0.05, "b": 0.04}, False)
        )  # fewer than three: lightest counts

    def test_model_call_fails_exit_2(self):
        for role in ("reader", "finderA", "verifier"):
            with self.subTest(role=role):
                d = defect(["d1/heavy"])
                rep = self.run_main(self.scenario(a=d, b=d, fail=role), 2)
                self.assertIn("COULD NOT RUN", rep)
                self.assertIn("claude exit 3", rep)
                self.assertIn("simulated failure", rep)

    def test_missing_claude_command_exit_2(self):
        rc = tr.main(
            [
                self.pkg,
                "--out",
                self.out,
                "--claude-cmd",
                os.path.join(self.t, "no_such_command"),
            ]
        )
        self.assertEqual(rc, 2)
        rep = self.report()
        self.assertIn("installed and on your PATH", rep)

    def test_not_a_task_folder_exit_2(self):
        empty = os.path.join(self.t, "empty")
        os.makedirs(empty)
        rc = tr.main([empty, "--out", self.out, "--claude-cmd", self.fake_cmd])
        self.assertEqual(rc, 2)

    def test_report_contains_limits_note(self):
        for sc, rc in ((self.scenario(), 0), (self.scenario(reader=DENY_A2), 1)):
            rep = self.run_main(sc, rc)
            self.assertIn("No flag does not mean the task is clean", rep)
            self.assertIn("(UNAUDITED, labels are model-built", rep)
            self.assertIn("14 of 46", rep)
            self.assertIn("4 of 49", rep)
            self.assertIn("5 of 22 and 1 of 20", rep)

    def test_failure_report_also_has_limits_note(self):
        rep = self.run_main(self.scenario(fail="reader"), 2)
        self.assertIn("No flag does not mean the task is clean", rep)

    def test_merge_pairs_same_test_and_shared_criterion(self):
        crit = {"x": 0.3, "y": 0.2}
        a = [
            {"criteria": ["x"], "test": "a", "description": "d"},
            {"criteria": ["y"], "test": "b", "description": "e"},
        ]
        b = [{"criteria": ["x", "y"], "test": "a", "description": "f"}]
        m = tr.merge(a, b, crit)
        self.assertEqual(sorted(f["found_by"] for f in m), ["A", "both"])

    @unittest.skipUnless(os.name == "nt", "the 260-character limit is a Windows rule")
    def test_package_with_long_file_names_copies_on_windows(self):
        prefix = chr(92) * 2 + "?" + chr(92)

        def long(p):
            p = os.path.abspath(p)
            return p if p.startswith(prefix) else prefix + p

        td = tempfile.mkdtemp()
        try:
            root = os.path.join(td, "pkg")
            parts = ["d" * 40] * 6
            deep = os.path.join(root, "environment", "initial_workspace", *parts)
            os.makedirs(long(deep))
            name = "f" * 60 + ".doc"
            with open(long(os.path.join(deep, name)), "w") as fh:
                fh.write("x")
            with open(os.path.join(root, "instruction.md"), "w") as fh:
                fh.write("do it")
            os.makedirs(os.path.join(root, "tests"))
            ver = {"verifiers": [{"name": "a", "metadata": {"weight": 1}, "assertion": {"rubric": {"prompt": "p"}}}]}
            with open(os.path.join(root, "tests", "verifier.json"), "w") as fh:
                json.dump(ver, fh)
            ws = os.path.join(td, "audit" + "x" * 30)
            tr.build_audit_layout(root, ws)
            copied = os.path.join(ws, "inputs", *parts, name)
            self.assertGreater(len(copied), 260)
            self.assertTrue(os.path.exists(long(copied)))
        finally:
            import shutil

            shutil.rmtree(long(td), ignore_errors=True)

    def test_a_crash_is_could_not_run_never_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            pkg = os.path.join(td, "pkg")
            os.makedirs(pkg)
            out = os.path.join(td, "out")
            orig = tr.read_task

            def boom(*a, **k):
                raise RuntimeError("boom")

            tr.read_task = boom
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    code = tr.main([pkg, "--out", out])
            finally:
                tr.read_task = orig
            self.assertEqual(code, 2)
            self.assertIn("unexpected error runtimeerror: boom", read(os.path.join(out, "task_read_report.md")))

    def test_tool_list_allows_python_and_powershell_on_windows_only(self):
        if os.name == "nt":
            for rule in ("Bash(python:*)", "PowerShell(python:*)", "PowerShell(Get-ChildItem:*)"):
                self.assertIn(rule, tr.TOOLS_READ)
                self.assertIn(rule, tr.TOOLS_WRITE)
        else:
            self.assertNotIn("PowerShell", tr.TOOLS_READ)
        self.assertIn("Bash(python3:*)", tr.TOOLS_READ)

    def test_runner_limits_the_available_tools(self):
        seen = {}

        class Done:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def fake_run(argv, **kw):
            seen["argv"] = argv
            return Done()

        orig = tr.subprocess.run
        tr.subprocess.run = fake_run
        try:
            tr.Runner("claude")("reader", "prompt text", os.getcwd(), tr.TOOLS_WRITE)
        finally:
            tr.subprocess.run = orig
        argv = seen["argv"]
        names = argv[argv.index("--tools") + 1].split(",")
        self.assertIn("Read", names)
        self.assertIn("Bash", names)
        self.assertNotIn("Agent", names)
        self.assertNotIn("SendMessage", names)
        self.assertTrue(all("(" not in n for n in names))
        self.assertLess(argv.index("--tools"), argv.index("--allowedTools"))
        if os.name == "nt":
            self.assertTrue(argv[-1].endswith(tr.WINDOWS_NOTE))
        else:
            self.assertEqual(argv[-1], "prompt text")

    def test_prompts_and_report_template_have_no_labels_or_expected_values(self):
        banned = (
            "tfrl",
            "truth_v",
            "material_tabrule",
            "defective task",
            "clean task",
            "labels", "ground truth",
        )
        prompts = [os.path.join(tr.PROMPTS, f) for f in sorted(os.listdir(tr.PROMPTS))]
        self.assertEqual(len(prompts), 4)
        texts = {f: read(f) for f in prompts}
        hits = [
            (os.path.basename(f), w) for f in prompts for w in banned if w in texts[f]
        ]
        self.assertEqual(hits, [])
        code = read(os.path.join(HERE, "task_read.py"))
        self.assertNotIn("tfrl", code)
        self.assertNotIn("truth_v", code)

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
            runner = tr.Runner("claude")
            runner.cmd = [sys.executable, fake]
            out = runner("reader", "prompt text", td, tr.TOOLS_WRITE)
        self.assertEqual(out, "ok \u2010 \u0410 \u00d0 done")

    def test_failed_call_shows_stdout_and_stderr(self):
        # claude prints the API error on stdout and a harmless warning on stderr; the report must carry both.
        class Failed:
            returncode = 1
            stdout = "API Error: Claude's response exceeded the 32000 output token maximum."
            stderr = '[claude-code:unrecognized_model] {"model":"glm-5.2"}'

        orig = tr.subprocess.run
        tr.subprocess.run = lambda argv, **kw: Failed()
        try:
            with self.assertRaises(tr.CouldNotRun) as cm:
                tr.Runner("claude")("finder", "prompt text", os.getcwd(), tr.TOOLS_WRITE)
        finally:
            tr.subprocess.run = orig
        self.assertIn("API Error", str(cm.exception))
        self.assertIn("unrecognized_model", str(cm.exception))


if __name__ == "__main__":
    r = unittest.main(exit=False, verbosity=0)
    n = r.result.testsRun
    bad = len(r.result.failures) + len(r.result.errors)
    print(f"TESTS {n - bad}/{n} passed")
    sys.exit(1 if bad else 0)
