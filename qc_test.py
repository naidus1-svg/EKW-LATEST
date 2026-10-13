"""Tests for qc.py: self-update behaviour in a throwaway clone, and argument handling. Standard library only."""

import csv
import hashlib
import io
import json
import importlib.abc
import importlib.machinery
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import warnings
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import qc  # noqa: E402


def git(cwd, *a):
    return subprocess.run(
        ["git", "-C", str(cwd), *a], capture_output=True, text=True, check=True
    )


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.remote = self.d / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        self.src = self.d / "src"
        subprocess.run(
            ["git", "clone", "-q", str(self.remote), str(self.src)],
            check=True,
            capture_output=True,
        )
        git(self.src, "config", "user.email", "t@t")
        git(self.src, "config", "user.name", "t")
        (self.src / "a.txt").write_text("one")
        git(self.src, "add", "-A")
        git(self.src, "commit", "-q", "-m", "first")
        git(self.src, "push", "-q", "origin", "HEAD")
        self.clone = self.d / "clone"
        subprocess.run(
            ["git", "clone", "-q", str(self.remote), str(self.clone)],
            check=True,
            capture_output=True,
        )
        self._saved = (qc.REPO, qc.SKILL_SRC, qc.SKILL_DST)
        qc.REPO = self.clone
        qc.SKILL_SRC = self.clone / "none" / "SKILL.md"
        qc.SKILL_DST = self.d / "skill" / "SKILL.md"

    def tearDown(self):
        qc.REPO, qc.SKILL_SRC, qc.SKILL_DST = self._saved
        shutil.rmtree(self.d, ignore_errors=True)

    def push_change(self, text, msg):
        (self.src / "a.txt").write_text(text)
        git(self.src, "commit", "-q", "-am", msg)
        git(self.src, "push", "-q", "origin", "HEAD")

    def test_pulls_new_commit_and_says_what_changed(self):
        self.push_change("two", "second change for QC people")
        buf = io.StringIO()
        with redirect_stdout(buf):
            ok = qc.update()
        self.assertTrue(ok)
        self.assertEqual((self.clone / "a.txt").read_text(), "two")
        self.assertIn("second change for QC people", buf.getvalue())

    def test_already_current(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertTrue(qc.update())
        self.assertIn("already up to date", buf.getvalue())

    def test_local_edit_blocks_pull_and_keeps_the_edit(self):
        self.push_change("two", "remote edit")
        (self.clone / "a.txt").write_text("my local edit")
        buf = io.StringIO()
        with redirect_stdout(buf):
            ok = qc.update()
        self.assertFalse(ok)
        self.assertEqual((self.clone / "a.txt").read_text(), "my local edit")
        self.assertIn("nothing was overwritten", buf.getvalue())

    def test_not_a_git_clone(self):
        qc.REPO = self.d / "src" / "nothere"
        qc.REPO.mkdir(parents=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertFalse(qc.update())
        self.assertIn("not a git clone", buf.getvalue())

    def test_skill_refresh_copies_when_different(self):
        s = self.clone / "none"
        s.mkdir()
        (s / "SKILL.md").write_text("v1")
        with redirect_stdout(io.StringIO()):
            qc.refresh_skill()
        self.assertEqual(qc.SKILL_DST.read_text(), "v1")
        (s / "SKILL.md").write_text("v2")
        with redirect_stdout(io.StringIO()):
            qc.refresh_skill()
        self.assertEqual(qc.SKILL_DST.read_text(), "v2")


class ArgTests(unittest.TestCase):
    def test_review_missing_files(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = qc.main(["--no-update", "review", "nope_dir", "nope.md"])
        self.assertEqual(rc, 2)
        self.assertIn("not found", buf.getvalue())

    def test_doc_names_all_four_commands(self):
        for word in ("update", "checks", "review", "release", "read", "manage", "proof"):
            self.assertIn(word, qc.__doc__)


    def test_read_runs_task_read_with_arguments(self):
        calls = []

        def fake_run(cmd, cwd=None):
            calls.append([str(c) for c in cmd])
            return 1

        saved = qc.run
        qc.run = fake_run
        try:
            with redirect_stdout(io.StringIO()):
                rc = qc.main(["--no-update", "read", "some/task", "--out", "rep"])
        finally:
            qc.run = saved
        self.assertEqual(rc, 1)
        self.assertTrue(calls[0][1].endswith(os.path.join("automation", "task-read", "task_read.py")))
        self.assertEqual(calls[0][-2:], ["--out", "rep"])

    def read_times(self, codes, *extra, times="3"):
        """qc.py read --times N with a stand-in for the reader: (exit code, the commands it ran, what it printed)."""
        calls, seq = [], iter(codes)

        def fake_read(cmd, tag):
            calls.append([str(c) for c in cmd])
            return next(seq)

        saved = qc.run_read
        qc.run_read = fake_read
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                rc = qc.main(["--no-update", "read", "some/task", "--times", times, *extra])
        finally:
            qc.run_read = saved
        return rc, calls, buf.getvalue()

    def test_read_times_all_clean(self):
        rc, calls, out = self.read_times([0, 0, 0])
        self.assertEqual((rc, len(calls)), (0, 3))
        base = Path("some").resolve() / "read_task"
        self.assertEqual([Path(c[c.index("--out") + 1]) for c in calls], [base / "read1", base / "read2", base / "read3"])
        self.assertEqual(out.strip().splitlines()[-1], f"NOT FLAGGED - report: {base / 'read1' / 'task_read_report.md'}")

    def test_read_times_stops_at_the_first_flag(self):
        rc, calls, out = self.read_times([0, 1, 0])
        self.assertEqual((rc, len(calls)), (1, 2))
        base = Path("some").resolve() / "read_task"
        self.assertEqual(out.strip().splitlines()[-1], f"FLAGGED - report: {base / 'read2' / 'task_read_report.md'}")
        self.assertEqual([x for x in out.splitlines() if x.startswith(("FLAGGED", "NOT FLAGGED"))], [out.strip().splitlines()[-1]])

    def test_read_times_stops_when_a_read_cannot_run(self):
        rc, calls, out = self.read_times([0, 2, 0])
        self.assertEqual((rc, len(calls)), (2, 2))
        self.assertNotIn("FLAGGED - report", out)

    def test_read_times_uses_out_as_the_base_folder_and_passes_the_tab(self):
        rc, calls, out = self.read_times([0, 0, 0], "--out", "rep", "--tab", "EKW")
        self.assertEqual(rc, 0)
        self.assertEqual([c[c.index("--out") + 1] for c in calls], [str(Path("rep") / f"read{k}") for k in (1, 2, 3)])
        self.assertTrue(all(c[-2:] == ["--tab", "EKW"] for c in calls))

    def test_read_times_is_clamped_to_five(self):
        rc, calls, out = self.read_times([0] * 5, times="9")
        self.assertEqual((rc, len(calls)), (0, 5))
        self.assertIn("--times must be between 1 and 5", out)

    def test_read_times_one_is_the_single_read_and_passes_the_exit_code_through(self):
        calls = []

        def fake_run(cmd, cwd=None):
            calls.append([str(c) for c in cmd])
            return 1

        saved = qc.run
        qc.run = fake_run
        try:
            with redirect_stdout(io.StringIO()):
                rc = qc.main(["--no-update", "read", "some/task", "--times", "1", "--out", "rep"])
        finally:
            qc.run = saved
        self.assertEqual((rc, len(calls)), (1, 1))
        self.assertEqual(calls[0][-2:], ["--out", "rep"])


class ManageTests(unittest.TestCase):
    def make_export(self, root):
        for name, revs in (("task-a", (1, 2)), ("task-b", (1,))):
            for r in revs:
                tid = {"task-a": 11, "task-b": 12}[name] + 100 * (r - 1)
                (Path(root) / name / f"rev_{r}__{tid}" / "task_files").mkdir(parents=True)

    def run_manage(self, rcs, extra=()):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        self.make_export(d / "dl")
        calls = []

        def fake_run(cmd, cwd=None):
            calls.append([str(c) for c in cmd])
            return rcs[len(calls) - 1]

        saved = qc.run
        qc.run = fake_run
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                rc = qc.main(["--no-update", "manage", str(d / "dl"), "--out", str(d / "out"), *extra])
        finally:
            qc.run = saved
        return rc, calls, buf.getvalue(), d

    def test_one_call_per_task_newest_revision_only(self):
        rc, calls, text, d = self.run_manage([1, 0])
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 2)  # task-a rev 2 and task-b rev 1; rev 1 of task-a is skipped
        self.assertTrue(calls[0][1].endswith(os.path.join("automation", "manager-read", "manager_read.py")))
        self.assertIn("rev_2__111", calls[0][2])
        self.assertEqual(calls[0][-2], "--out")
        self.assertIn("items on 1 of 2", text)
        self.assertIn("needs a written answer", text)
        rows = (d / "out" / "manager_summary.csv").read_text().splitlines()
        self.assertEqual(len(rows), 3)

    def test_could_not_run_gives_exit_two(self):
        rc, _, text, _ = self.run_manage([2, 0])
        self.assertEqual(rc, 2)
        self.assertIn("could not run on 1", text)

    def test_tab_is_passed_on(self):
        _, calls, _, _ = self.run_manage([0, 0], ("--tab", "EKW"))
        self.assertEqual(calls[0][-2:], ["--tab", "EKW"])

    def test_zip_input_is_unpacked(self):
        import zipfile

        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        z = d / "dl.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("task-a/rev_1__11/task_files/instruction.md", "x")
        calls = []
        saved = qc.run
        qc.run = lambda cmd, cwd=None: calls.append([str(c) for c in cmd]) or 0
        try:
            with redirect_stdout(io.StringIO()):
                rc = qc.main(["--no-update", "manage", str(z), "--out", str(d / "out")])
        finally:
            qc.run = saved
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        self.assertTrue(Path(calls[0][2], "task_files", "instruction.md").exists())

    def test_empty_folder(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(qc.main(["--no-update", "manage", str(d), "--out", str(d / "o")]), 2)


INSTRUCTION = (
    "Write a memo for the board. State the total headcount cost for 2027 and name the three biggest drivers of the change, "
    "as the board's finance lead asked."
)
QUOTE = "State the total headcount cost for 2027 and name the three biggest drivers of the change"
WHY = "Any memo that states the same total in a different layout or currency format would also pass this test."


def crit(name, value, error=None, weight=0.25):
    return {"name": name, "value": value, "weight": weight, "description": f"Pass if the memo handles {name}.", "error": error}


def attempt(total, drivers, title, late=(0, None)):
    """One AI attempt's reward-details in the three real shapes: judge passes in a list (d1), a group (d2), a dict (d3)."""
    d1 = lambda i: {"criteria": [crit("total", total), crit("drivers", drivers[i])]}
    group = {"kind": "group", "components": [{"name": "judge", "weight": 0.45, "detail": {"criteria": [crit("late", *late)]}}]}
    return {"d1": [d1(0), d1(1)], "d2": group, "d3": {"criteria": [crit("title", title)]}}


# total and drivers fail in every AI attempt, title passes in one, late was graded in one; oracle and nop must not count
RUNS = {
    "eval_1__attempt_1__codex__m": attempt(0, (0, 0), 0),
    "eval_2__attempt_1__terminus-2__m": attempt(0, (0, 0), 1, (0, "judge timed out after 300s")),
    "eval_3__attempt_1__oracle": attempt(1, (1, 1), 1, (1, None)),
    "eval_4__attempt_1__nop": attempt(0, (0, 0), 0),
}


def row(cid, quote=QUOTE, where="golden memo, section 2", other=WHY):
    return [cid, "", "0.25", quote, where, other]


def weighted(spec):
    """Two AI attempts that give every test the value in spec ({name: (value, weight)}), in one plain deliverable."""
    run = {"d1": {"criteria": [crit(n, v, weight=w) for n, (v, w) in spec.items()]}}
    return {"eval_1__attempt_1__codex__m": run, "eval_2__attempt_1__terminus-2__m": run}


class ProofTests(unittest.TestCase):
    def make(self, runs=RUNS, parent="task"):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        rev = d / parent / "rev_1__11"
        (rev / "task_files").mkdir(parents=True)
        (rev / "task_files" / "instruction.md").write_text(INSTRUCTION, encoding="utf-8")
        for name, details in runs.items():
            v = rev / "evaluations" / name / "eval_files" / "verifier"
            v.mkdir(parents=True)
            (v / "reward-details.json").write_text(json.dumps(details), encoding="utf-8")
        return rev

    def go(self, action, rev):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = qc.main(["--no-update", "proof", action, str(rev), "--no-blame"])
        return rc, buf.getvalue()

    def write(self, rev, *rows):
        with open(rev / qc.PROOF_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([qc.PROOF_COLS, *rows])

    def line(self, out, cid):
        return next(x for x in out.splitlines() if x.endswith(": " + cid))

    def test_lists_the_tests_every_scored_ai_attempt_failed(self):
        tests, scored, ai, total = qc.zero_pass_criteria(self.make())
        # title passed once, late was graded once, and the oracle and nop runs do not count
        self.assertEqual([t[0] for t in tests], ["d1/drivers", "d1/total"])
        self.assertEqual((scored, ai, total), (2, 2, 1.0))
        self.assertEqual(tests[0][1:], ("Pass if the memo handles drivers.", 0.25, 0.25))

    def test_one_passing_judge_pass_or_a_run_with_an_exception_changes_the_list(self):
        runs = {**RUNS, "eval_1__attempt_1__codex__m": attempt(0, (0, 1), 0), "eval_5__attempt_1__codex__m": attempt(1, (1, 1), 1)}
        rev = self.make(runs)
        exc = {"exception_info": {"exception_type": "AgentTimeoutError", "exception_message": "x"}}
        (rev / "evaluations" / "eval_5__attempt_1__codex__m" / "eval_files" / "result.json").write_text(json.dumps(exc))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)  # the reused read_json leaves result.json open
            tests, scored, ai, _ = qc.zero_pass_criteria(rev)
        self.assertEqual([t[0] for t in tests], ["d1/total"])  # drivers passed in one judge pass; the run that passed all crashed
        self.assertEqual((scored, ai), (2, 3))

    def test_folder_name_with_brackets(self):
        self.assertEqual(len(qc.zero_pass_criteria(self.make(parent="task [v2]"))[0]), 2)

    def test_init_writes_the_file_next_to_evaluations_and_never_overwrites_it(self):
        rev = self.make()
        rc, out = self.go("init", rev / "task_files")  # the task_files folder of the same revision works too
        self.assertEqual(rc, 0)
        self.assertFalse((rev / "task_files" / qc.PROOF_FILE).exists())
        with open(rev / qc.PROOF_FILE, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0], qc.PROOF_COLS)
        self.assertEqual([r[0] for r in rows[1:]], ["d1/drivers", "d1/total"])
        self.assertEqual(rows[1][1:], ["Pass if the memo handles drivers.", "0.25", "", "", ""])
        self.assertIn("2 heavy tests failed in all 2 scored AI attempts", out)
        self.assertIn("lighter zero-pass tests left out (they need no proof): 0", out)
        (rev / qc.PROOF_FILE).write_text("my work")
        rc, out = self.go("init", rev)
        self.assertEqual(rc, 2)
        self.assertIn("already exists", out)
        self.assertEqual((rev / qc.PROOF_FILE).read_text(), "my work")

    def test_nothing_to_prove(self):
        passing = attempt(1, (1, 1), 1, (1, None))
        all_pass = {**RUNS, "eval_1__attempt_1__codex__m": passing, "eval_2__attempt_1__terminus-2__m": passing}
        rev = self.make(all_pass)
        rc, out = self.go("init", rev)
        self.assertEqual(rc, 0)
        self.assertIn("no proof required: no test failed in all 2", out)
        rc, out = self.go("check", rev)
        self.assertEqual((rc, out.strip().splitlines()[-1]), (0, "PROOF: COMPLETE"))
        self.assertFalse((rev / qc.PROOF_FILE).exists())

    def test_too_few_scored_attempts_is_a_hold_never_complete(self):
        one_attempt = {k: v for k, v in RUNS.items() if "terminus" not in k}
        rev = self.make(one_attempt)
        rc, out = self.go("init", rev)
        self.assertEqual(rc, 1)
        self.assertIn("only 1 of 1 AI attempts could be scored", out)
        rc, out = self.go("check", rev)
        self.assertEqual((rc, out.strip().splitlines()[-1]), (1, "PROOF: HOLD (only 1 of 1 AI attempts could be scored)"))
        self.assertFalse((rev / qc.PROOF_FILE).exists())

    def test_check_holds_without_a_file_or_a_row(self):
        rev = self.make()
        rc, out = self.go("check", rev)  # no file at all
        self.assertEqual((rc, out.count("MISSING ROW"), out.strip().splitlines()[-1]), (1, 2, "PROOF: HOLD (2 open)"))
        self.write(rev, row("d1/drivers"))  # one row only
        rc, out = self.go("check", rev)
        self.assertEqual((rc, out.strip().splitlines()[-1]), (1, "PROOF: HOLD (1 open)"))
        self.assertIn("OK: d1/drivers", out)
        self.assertIn("MISSING ROW: d1/total", out)

    def test_check_names_each_problem(self):
        rev = self.make()
        self.write(
            rev,
            row("d1/drivers", quote="State the total headcount cost", where=" ", other="Because it is."),
            row("d1/total", quote="Name the five smallest drivers of the change in headcount cost"),
        )
        rc, out = self.go("check", rev)
        self.assertEqual(rc, 1)
        for part in ("QUOTE TOO SHORT", "EMPTY FIELD golden_location", "EMPTY FIELD other_valid_answer"):
            self.assertIn(part, self.line(out, "d1/drivers"))
        self.assertTrue(self.line(out, "d1/total").startswith("QUOTE NOT FOUND"))
        self.assertEqual(out.strip().splitlines()[-1], "PROOF: HOLD (2 open)")

    def test_check_complete_ignores_case_spacing_and_curly_quotes(self):
        rev = self.make()
        q = "  NAME the three biggest drivers of the change,   as the board" + chr(0x2019) + "s finance lead asked "
        self.write(rev, row("d1/drivers", quote=q), row("d1/total"))
        rc, out = self.go("check", rev)
        self.assertEqual((rc, out.strip().splitlines()[-1]), (0, "PROOF: COMPLETE"))

    def test_check_reads_a_file_saved_by_excel_as_plain_csv(self):
        rev = self.make()
        q = "name the three biggest drivers of the change, as the board" + chr(0x2019) + "s finance lead asked"
        self.write(rev, row("d1/drivers", quote=q), row("d1/total"))
        path = rev / qc.PROOF_FILE
        path.write_bytes(path.read_text(encoding="utf-8").encode("cp1252"))
        self.assertEqual(self.go("check", rev)[0], 0)

    def test_cannot_run_without_run_data_or_with_a_file_missing_columns(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        rc, out = self.go("check", d)
        self.assertEqual(rc, 2)
        self.assertIn("cannot run", out)
        rev = self.make()
        (rev / qc.PROOF_FILE).write_text("criterion_id,weight\nd1/total,0.25\n")
        rc, out = self.go("check", rev)
        self.assertEqual(rc, 2)
        self.assertIn("lacks the column", out)

    def test_only_heavy_tests_need_a_proof(self):
        # big is 40 percent of the total weight; s1 to s3 are 2 percent each and failed in every attempt too
        rev = self.make(weighted({"big": (0, 0.40), "s1": (0, 0.02), "s2": (0, 0.02), "s3": (0, 0.02), "fine": (1, 0.54)}))
        tests, _, _, total = qc.zero_pass_criteria(rev)
        self.assertEqual((len(tests), round(total, 6)), (4, 1.0))
        rc, out = self.go("init", rev)
        self.assertEqual(rc, 0)
        self.assertIn("1 heavy test failed in all 2 scored AI attempts", out)
        self.assertIn("lighter zero-pass tests left out (they need no proof): 3", out)
        with open(rev / qc.PROOF_FILE, newline="", encoding="utf-8-sig") as f:
            self.assertEqual([r[0] for r in list(csv.reader(f))[1:]], ["d1/big"])
        rc, out = self.go("check", rev)  # one open row, and the light tests are not looked at
        self.assertEqual((rc, out.strip().splitlines()[-1]), (1, "PROOF: HOLD (1 open)"))
        self.assertNotIn("d1/s1", out)
        self.write(rev, row("d1/big"), row("d1/s1", quote="", where="", other=""))  # a half-empty row for a light test is ignored
        rc, out = self.go("check", rev)
        self.assertEqual((rc, out.strip().splitlines()[-1]), (0, "PROOF: COMPLETE"))

    def test_heavy_is_a_share_of_the_total_weight_not_a_raw_weight(self):
        # the weights add up to 10: big is 20 percent, edge exactly 5 percent (heavy), lite 4 percent (light, raw weight 0.4)
        rev = self.make(weighted({"big": (0, 2.0), "edge": (0, 0.5), "lite": (0, 0.4), "fine": (1, 7.1)}))
        tests, _, _, total = qc.zero_pass_criteria(rev)
        self.assertEqual({t[0]: round(t[3], 4) for t in tests}, {"d1/big": 0.2, "d1/edge": 0.05, "d1/lite": 0.04})
        rc, out = self.go("init", rev)
        self.assertEqual(rc, 0)
        self.assertIn("here a weight of 0.5 or more", out)
        with open(rev / qc.PROOF_FILE, newline="", encoding="utf-8-sig") as f:
            self.assertEqual([r[0] for r in list(csv.reader(f))[1:]], ["d1/big", "d1/edge"])

    def test_only_light_zero_pass_tests_need_no_proof(self):
        rev = self.make(weighted({"l1": (0, 0.02), "l2": (0, 0.03), "fine": (1, 0.95)}))
        for action in ("init", "check"):
            rc, out = self.go(action, rev)
            self.assertEqual(rc, 0)
            self.assertIn("no proof required: no heavy test failed in all 2 scored AI attempts (2 lighter zero-pass tests left out", out)
        self.assertEqual(out.strip().splitlines()[-1], "PROOF: COMPLETE")  # check still ends with the line the manager looks for
        self.assertFalse((rev / qc.PROOF_FILE).exists())


# ---- the golden-answer reader inside the proof step (EKW tasks); a fake claude stands in for the model -------------

# answers the reader's calls from a scenario file: a test is called "the test is the problem" when its text holds a marker.
# gold[i] lists the markers for golden pass i, base the markers for the pass without the golden, skip the item keys to leave out.
FAKE_CLAUDE = r'''import json, os, re, sys
sc = json.load(open(os.environ["FAKE_SCENARIO"], encoding="utf-8"))
rule = sys.argv[-1]
text = sys.stdin.read()
log = os.environ["FAKE_LOG"]
role = "gold" if rule.startswith("You are a QC reviewer. The batch is on standard input.") else "base"
calls = open(log, encoding="utf-8").read().split() if os.path.exists(log) else []
with open(log, "a", encoding="utf-8") as f:
    f.write(role + "\n")
if sc.get("exit"):
    sys.stderr.write("simulated failure")
    sys.exit(sc["exit"])
markers = sc["gold"][min(calls.count("gold"), len(sc["gold"]) - 1)] if role == "gold" else sc["base"]
parts = re.split(r"(?:-----CRITERION ITEM|=====ITEM) (k\d+)(?:-----|=====)", text)
out = {}
for key, body in zip(parts[1::2], parts[2::2]):
    if key in sc.get("skip", []):
        continue
    defect = any(m in body for m in markers)
    out[key] = {"verdict": "criterion_defect" if defect else "solver_miss", "why": "the golden asks for it" if defect else "fair", "confidence": 3}
print(json.dumps(out))
'''


class FakeMarkItDown:
    def convert(self, path):
        return types.SimpleNamespace(text_content=Path(path).read_text(encoding="utf-8"))


# name, description (the marker is what the fake claude looks for), weight, value in every AI attempt
CRITERIA = [
    ("big", "PASS if the memo states the total headcount cost for 2027 (BIGMARK).", 0.40, 0.0),
    ("pinned", "PASS if the memo uses the 40 percent split (PINNED).", 0.03, 0.0),
    ("fair", "PASS if the memo has a title (FAIR).", 0.02, 0.0),
    ("ok", "PASS if the memo is addressed to the board (OKMARK).", 0.55, 1.0),
]
GOLD_TEXT = "The total is 100. The split is 40 percent."


def judge_toml(skip=()):
    body = "[judge]\nweight = 1.0\n"
    for name, desc, w, _v in CRITERIA:
        if name not in skip:
            body += f'\n[[criterion]]\nname = "{name}"\ndescription = "{desc}"\nweight = {w}\n'
    return body


def verifier_json():
    """The harbor grader: criteria called v1, v2 ... (the criterion inside a run file carries another name)."""
    verifiers = [
        {"name": f"v{i}", "assertion": {"rubric": {"prompt": desc}}, "metadata": {"weight": w}}
        for i, (_n, desc, w, _v) in enumerate(CRITERIA, 1)
    ]
    return json.dumps({"verifiers": verifiers})


def details(shape="dict", oracle=False, layout="judge"):
    def crit(n, d, w, v):
        return {"name": n, "value": 1.0 if oracle else v, "raw": v, "weight": w, "description": d, "reasoning": "met" if oracle or v else "the run missed it"}

    if layout == "native":  # harbor: one entry per verifier, keyed v1, v2 ...
        return {f"v{i}": {"score": 0.0, "kind": "outcome", "criteria": [crit(*c)]} for i, c in enumerate(CRITERIA, 1)}
    crits = [crit(*c) for c in CRITERIA]
    if shape == "list":  # judge passes in a list
        return {"deliverables_01": [{"criteria": crits}, {"criteria": crits}]}
    if shape == "group":  # a group whose component holds the criteria
        return {"deliverables_01": {"kind": "group", "components": [{"name": "judge", "weight": 0.45, "detail": {"criteria": crits}}]}}
    return {"deliverables_01": {"score": 0.0, "kind": "llm", "criteria": crits}}


class GoldenProofTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        fake = self.d / "fake_claude.py"
        fake.write_text(FAKE_CLAUDE, encoding="utf-8")
        self.log = self.d / "claude_calls.log"
        self.scenario({"gold": [["PINNED"], ["PINNED"], []], "base": ["PINNED"]})  # golden 2 of 3 and the no-golden pass: HOLD
        env = {"GCR_CLAUDE": f'"{sys.executable}" "{fake}"', "FAKE_SCENARIO": str(self.d / "scenario.json"), "FAKE_LOG": str(self.log)}
        for patch in (
            mock.patch.dict(os.environ, env),
            mock.patch.dict(sys.modules, {"markitdown": types.SimpleNamespace(MarkItDown=FakeMarkItDown)}),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def scenario(self, scenario):
        (self.d / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")

    def calls(self):
        return len(self.log.read_text().split()) if self.log.exists() else 0

    def make(self, category="EKW", reward_toml=False, shape="dict", golden=GOLD_TEXT, attempts=2, grader=True, layout="judge", judge_skip=()):
        rev = self.d / "EKW-123" / "rev_3__171383"
        tf = rev / "task_files"
        native = layout == "native"  # harbor shape: tests/verifier.json and solution/golden_outputs
        (tf / "tests" / "deliverables_01").mkdir(parents=True)
        gold_dir = tf / "solution" / ("golden_outputs" if native else "files")
        gold_dir.mkdir(parents=True)
        (tf / "instruction.md").write_text(INSTRUCTION, encoding="utf-8")
        if category:
            (tf / "task.toml").write_text(f'[metadata]\ncategory = "{category}"\n', encoding="utf-8")
        if grader and native:
            (tf / "tests" / "verifier.json").write_text(verifier_json(), encoding="utf-8")
        elif grader:
            (tf / "tests" / "deliverables_01" / "judge.toml").write_text(judge_toml(judge_skip), encoding="utf-8")
        if reward_toml:
            (tf / "tests" / "reward.toml").write_text("[[reward]]\n", encoding="utf-8")
        if golden is not None:
            (gold_dir / "gold.md").write_text(golden, encoding="utf-8")
        runs = [(f"eval_{i}__attempt_1__codex__m", False) for i in range(1, attempts + 1)] + [("eval_9__attempt_1__oracle", True)]
        for name, oracle in runs:
            v = rev / "evaluations" / name / "eval_files" / "verifier"
            v.mkdir(parents=True)
            (v / "reward-details.json").write_text(json.dumps(details(shape, oracle, layout)), encoding="utf-8")
        return rev

    def go(self, action, rev, *extra):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = qc.main(["--no-update", "proof", action, str(rev), "--no-blame", *extra])
        return rc, buf.getvalue()

    def last(self, out):
        return out.strip().splitlines()[-1]

    def sheet(self, rev):
        with open(rev / qc.PROOF_FILE, newline="", encoding="utf-8-sig") as f:
            return list(csv.reader(f))

    def fill(self, rev, *ids):
        table = self.sheet(rev)
        for r in table[1:]:
            if r[0] in ids:
                r[3], r[4], r[5] = QUOTE, "golden memo, section 2", WHY
        with open(rev / qc.PROOF_FILE, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows(table)

    def saved(self, rev):
        return json.loads((rev / qc.GOLDEN_FILE).read_text(encoding="utf-8"))

    def stopped(self, rev, out, reason):
        self.assertEqual(self.last(out), "PROOF: HOLD (the golden-answer reader could not run)")
        self.assertIn(reason, out)
        self.assertIn("Send your lead the task name EKW-123, the folder name rev_3__171383", out)
        self.assertFalse((rev / qc.PROOF_FILE).exists() or (rev / qc.GOLDEN_FILE).exists())  # nothing half written

    def test_init_asks_the_reader_once_and_adds_a_row_for_each_flagged_test(self):
        rev = self.make()
        rc, out = self.go("init", rev)
        self.assertEqual(rc, 0, out)
        self.assertIn("asking the golden-answer reader about 3 tests (4 AI calls, about 2 minutes)", out)
        self.assertIn("flagged 1 of the 3 tests that every AI attempt failed (HOLD)", out)
        self.assertIn("deliverables_01/pinned: the golden asks for it", out)
        self.assertIn("1 heavy test failed in all 2 scored AI attempts", out)
        self.assertIn("and the golden-answer reader flagged 1 more test", out)
        self.assertIn("lighter zero-pass tests left out (they need no proof): 1", out)
        table = self.sheet(rev)
        self.assertEqual(table[0], qc.PROOF_COLS)  # the sheet people know: same six columns
        self.assertEqual([(r[0], r[2]) for r in table[1:]], [("deliverables_01/big", "0.4"), ("deliverables_01/pinned", "0.03")])
        self.assertEqual(self.calls(), 4)  # three passes with the golden, one without
        self.assertEqual([h["id"] for h in self.saved(rev)["hold"]], ["deliverables_01/pinned"])
        rc, out = self.go("check", rev)  # rows still empty
        self.assertEqual((rc, self.last(out)), (1, "PROOF: HOLD (2 open)"))
        self.assertIn("flagged 1 of the 3 tests that every AI attempt failed (HOLD): deliverables_01/pinned", out)
        self.fill(rev, "deliverables_01/big", "deliverables_01/pinned")
        rc, out = self.go("check", rev)
        self.assertEqual((rc, self.last(out)), (0, "PROOF: COMPLETE"))
        self.assertIn("OK: deliverables_01/pinned", out)

    def test_check_never_calls_the_model(self):
        rev = self.make()
        self.go("init", rev)
        self.fill(rev, "deliverables_01/big", "deliverables_01/pinned")
        before = self.calls()
        with mock.patch.dict(os.environ, {"GCR_CLAUDE": '"%s"' % (self.d / "no_such_claude")}):
            with mock.patch.dict(sys.modules, {"markitdown": None}):  # the manager has neither claude nor markitdown
                rc, out = self.go("check", rev)
        self.assertEqual((rc, self.last(out), self.calls()), (0, "PROOF: COMPLETE", before))

    def test_a_flagged_heavy_test_gets_one_row(self):
        self.scenario({"gold": [["BIGMARK"], ["BIGMARK"], []], "base": ["BIGMARK"]})
        rev = self.make()
        self.assertEqual(self.go("init", rev)[0], 0)
        self.assertEqual([r[0] for r in self.sheet(rev)[1:]], ["deliverables_01/big"])
        self.assertEqual([h["id"] for h in self.saved(rev)["hold"]], ["deliverables_01/big"])

    def test_nothing_flagged_leaves_only_the_heavy_rows(self):
        self.scenario({"gold": [[]], "base": []})
        rev = self.make()
        rc, out = self.go("init", rev)
        self.assertEqual(rc, 0)
        self.assertIn("flagged none of the 3 tests that every AI attempt failed", out)
        self.assertEqual([r[0] for r in self.sheet(rev)[1:]], ["deliverables_01/big"])
        self.fill(rev, "deliverables_01/big")
        self.assertEqual(self.go("check", rev)[1].strip().splitlines()[-1], "PROOF: COMPLETE")

    def test_read_first_is_advice_and_gets_no_row(self):
        self.scenario({"gold": [["PINNED"]], "base": []})  # golden 3 of 3 but the pass without the golden disagrees: READ_FIRST
        rev = self.make()
        rc, out = self.go("init", rev)
        self.assertEqual(rc, 0)
        self.assertIn("flagged none of the 3 tests", out)
        self.assertIn("also marked 1 more as read first (no row needed): pinned", out)
        self.assertEqual([r[0] for r in self.sheet(rev)[1:]], ["deliverables_01/big"])

    def test_only_a_reader_flag_can_create_the_sheet(self):
        # no heavy test at all: the one zero-pass test is light, and the reader flags it
        self.scenario({"gold": [["PINNED"]], "base": ["PINNED"]})
        rev = self.make()
        with mock.patch.object(qc, "HEAVY_SHARE", 0.9):
            rc, out = self.go("init", rev)
        self.assertEqual(rc, 0, out)
        self.assertEqual([r[0] for r in self.sheet(rev)[1:]], ["deliverables_01/pinned"])  # no heavy test; the reader flagged pinned
        self.assertIn("0 heavy tests failed in all 2 scored AI attempts", out)
        self.assertIn("lighter zero-pass tests left out (they need no proof): 2", out)

    def test_svc_task_prints_the_skip_line_and_nothing_else_changes(self):
        rev = self.make(category="SVC-PC")
        rc, out = self.go("init", rev)
        self.assertEqual(rc, 0)
        self.assertIn("golden-answer reader: skipped, this is an SVC task (the task.toml category word). The reader block is for EKW tasks only.", out)
        self.assertEqual([r[0] for r in self.sheet(rev)[1:]], ["deliverables_01/big"])
        self.assertEqual((self.calls(), (rev / qc.GOLDEN_FILE).exists()), (0, False))
        self.fill(rev, "deliverables_01/big")
        rc, out = self.go("check", rev)
        self.assertEqual((rc, self.last(out)), (0, "PROOF: COMPLETE"))

    def test_tab_flag_beats_the_files_both_ways(self):
        rc, out = self.go("init", self.make(category="SVC-PC"), "--tab", "EKW")
        self.assertEqual(rc, 0)
        self.assertEqual(self.calls(), 4)
        shutil.rmtree(self.d / "EKW-123")
        self.log.unlink()
        rc, out = self.go("init", self.make(category="EKW"), "--tab", "svc")
        self.assertEqual(rc, 0)
        self.assertIn("skipped, this is an SVC task (you gave --tab)", out)
        self.assertEqual(self.calls(), 0)

    def test_files_that_do_not_say_the_kind_count_as_ekw(self):
        rev = self.make(category=None, reward_toml=True)
        rc, out = self.go("init", rev)
        self.assertEqual(rc, 0, out)
        self.assertIn("do not say whether this is an EKW or an SVC task, so I treat it as EKW", out)
        self.assertIn("If it is an SVC task, add --tab SVC", out)
        self.assertEqual(self.calls(), 4)

    def test_a_package_with_no_grader_file_skips_the_reader_with_a_notice(self):
        rev = self.make(category=None, grader=False)
        rc, out = self.go("init", rev)
        self.assertEqual(rc, 0)
        self.assertIn("skipped, the task files have no grader file", out)
        self.assertEqual(self.calls(), 0)

    def test_nothing_to_read_when_no_test_failed_everywhere(self):
        rev = self.make()
        for name in ("eval_1__attempt_1__codex__m", "eval_2__attempt_1__codex__m"):
            p = rev / "evaluations" / name / "eval_files" / "verifier" / "reward-details.json"
            p.write_text(json.dumps(details("dict", oracle=True)), encoding="utf-8")
        rc, out = self.go("check", rev)
        self.assertEqual((rc, self.last(out), self.calls()), (0, "PROOF: COMPLETE", 0))
        self.assertIn("golden-answer reader: nothing to read", out)

    def test_too_few_scored_attempts_never_reaches_the_reader(self):
        rev = self.make(attempts=1)
        rc, out = self.go("init", rev)
        self.assertEqual(rc, 1)
        self.assertIn("only 1 of 1 AI attempts could be scored", out)
        self.assertEqual(self.calls(), 0)

    def test_reader_that_cannot_run_stops_an_ekw_task_and_says_what_to_send_the_lead(self):
        rev = self.make()
        with mock.patch.dict(os.environ, {"GCR_CLAUDE": '"%s"' % (self.d / "no_such_claude")}):
            rc, out = self.go("init", rev)
        self.assertEqual(rc, 2)
        self.stopped(rev, out, "the claude command was not found")
        with mock.patch.dict(sys.modules, {"markitdown": None}):
            rc, out = self.go("init", rev)
        self.stopped(rev, out, 'the Python package markitdown is not installed; run once: python -m pip install "markitdown[docx,xlsx,pdf,pptx]"')
        self.scenario({"gold": [[]], "base": [], "exit": 3})
        rc, out = self.go("init", rev)
        self.stopped(rev, out, "an AI call failed (RuntimeError: claude exited 3: simulated failure)")
        self.scenario({"gold": [["PINNED"]], "base": ["PINNED"], "skip": ["k001"]})
        rc, out = self.go("init", rev)
        self.stopped(rev, out, "the reader's answers skipped 1 test (")

    def test_a_markitdown_that_will_not_load_and_any_other_surprise_also_stop_the_task(self):
        class WontLoad(importlib.abc.Loader):
            def create_module(self, spec):
                return None

            def exec_module(self, module):
                raise OSError("dll load failed")

        class Finder(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                return importlib.machinery.ModuleSpec(name, WontLoad()) if name == "markitdown" else None

        rev = self.make()
        finder = Finder()
        with mock.patch.dict(sys.modules):
            sys.modules.pop("markitdown", None)
            sys.meta_path.insert(0, finder)
            try:
                rc, out = self.go("init", rev)
            finally:
                sys.meta_path.remove(finder)
        self.assertEqual(rc, 2)
        self.stopped(rev, out, "the Python package markitdown does not load (OSError: dll load failed)")
        with mock.patch.object(qc, "golden_ask", side_effect=KeyError("surprise")):
            rc, out = self.go("init", rev)
        self.assertEqual(rc, 2)
        self.stopped(rev, out, "unexpected error KeyError: 'surprise'")

    def test_no_golden_text_stops_before_any_ai_call(self):
        rev = self.make(golden=None)
        rc, out = self.go("init", rev)
        self.assertEqual(rc, 2)
        self.stopped(rev, out, "the reader found no golden answer text")
        self.assertEqual(self.calls(), 0)

    def test_a_test_the_reader_cannot_see_is_never_passed_in_silence(self):
        rev = self.make(judge_skip=("pinned",))  # the grader file does not list a test that the run files grade
        self.assertEqual(len(qc.zero_pass_criteria(rev)[0]), 3)
        rc, out = self.go("init", rev)
        self.assertEqual(rc, 2)
        self.stopped(rev, out, "the reader cannot see 1 of the tests that every AI attempt failed (pinned)")
        self.assertEqual(self.calls(), 0)

    def test_run_files_in_a_list_or_a_group_are_read_too(self):
        for shape in ("list", "group"):
            shutil.rmtree(self.d / "EKW-123", ignore_errors=True)
            self.log.unlink(missing_ok=True)
            rev = self.make(shape=shape)
            rc, out = self.go("init", rev)
            self.assertEqual(rc, 0, (shape, out))
            self.assertEqual(([r[0] for r in self.sheet(rev)[1:]], self.calls()), (["deliverables_01/big", "deliverables_01/pinned"], 4), shape)

    def test_a_harbor_task_with_verifier_json_and_golden_outputs_is_read(self):
        rev = self.make(category=None, layout="native")  # no task.toml: tests/verifier.json says EKW
        rc, out = self.go("init", rev)
        self.assertEqual(rc, 0, out)
        self.assertNotIn("treat it as EKW", out)  # the files said so
        self.assertEqual(([r[0] for r in self.sheet(rev)[1:]], self.calls()), (["v1/big", "v2/pinned"], 4))
        self.assertEqual([h["id"] for h in self.saved(rev)["hold"]], ["v2/pinned"])
        self.fill(rev, "v1/big", "v2/pinned")
        rc, out = self.go("check", rev)
        self.assertEqual((rc, self.last(out)), (0, "PROOF: COMPLETE"))
        shutil.rmtree(self.d / "EKW-123")
        rc, out = self.go("init", self.make(category=None, layout="native", golden=None))
        self.assertEqual(rc, 2)
        self.assertIn("the reader found no golden answer text", out)

    def test_second_init_never_asks_the_reader_again(self):
        rev = self.make()
        self.go("init", rev)
        self.assertEqual(self.calls(), 4)
        self.scenario({"gold": [[]], "base": []})  # a new roll of the reader would flag nothing
        rc, out = self.go("init", rev)
        self.assertEqual(rc, 2)
        self.assertIn("already exists, so I stopped and changed nothing", out)
        (rev / qc.PROOF_FILE).unlink()
        rc, out = self.go("init", rev)  # the sheet is rebuilt from the saved answer
        self.assertEqual(rc, 0)
        self.assertEqual(([r[0] for r in self.sheet(rev)[1:]], self.calls()), (["deliverables_01/big", "deliverables_01/pinned"], 4))

    def test_check_without_a_saved_answer_is_hold_and_init_adds_the_rows_to_an_old_sheet(self):
        rev = self.make()
        with mock.patch.object(qc, "task_kind", return_value=("SVC", "flag")):  # a sheet made before this change: heavy rows only
            self.go("init", rev)
        self.fill(rev, "deliverables_01/big")
        before = self.sheet(rev)
        rc, out = self.go("check", rev)
        self.assertEqual((rc, self.last(out)), (1, "PROOF: HOLD (the golden-answer reader has not run on this download)"))
        self.assertIn("python qc.py proof init <the same folder>", out)
        rc, out = self.go("init", rev)
        self.assertEqual(rc, 0, out)
        self.assertIn("added 1 row to the end of", out)
        after = self.sheet(rev)
        self.assertEqual(after[: len(before)], before)  # the rows people had are untouched
        self.assertEqual([r[0] for r in after[len(before):]], ["deliverables_01/pinned"])
        rc, out = self.go("check", rev)
        self.assertEqual((rc, self.last(out)), (1, "PROOF: HOLD (1 open)"))
        self.fill(rev, "deliverables_01/pinned")
        self.assertEqual(self.go("check", rev)[1].strip().splitlines()[-1], "PROOF: COMPLETE")

    def test_an_old_sheet_saved_by_excel_keeps_its_words_when_rows_are_added(self):
        rev = self.make()
        with mock.patch.object(qc, "task_kind", return_value=("SVC", "flag")):
            self.go("init", rev)
        q = "name the three biggest drivers of the change, as the board" + chr(0x2019) + "s finance lead asked"
        self.fill(rev, "deliverables_01/big")
        table = self.sheet(rev)
        table[1][3] = q
        path = rev / qc.PROOF_FILE
        with open(path, "w", newline="", encoding="cp1252") as f:
            csv.writer(f).writerows(table)
        self.assertEqual(self.go("init", rev)[0], 0)
        self.assertEqual(self.sheet(rev)[1][3], q)

    def test_a_saved_answer_for_other_files_is_hold_and_is_not_replaced(self):
        rev = self.make()
        self.go("init", rev)
        self.fill(rev, "deliverables_01/big", "deliverables_01/pinned")
        (rev / "task_files" / "instruction.md").write_text(INSTRUCTION + " Also state the 2028 figure.", encoding="utf-8")
        rc, out = self.go("check", rev)
        self.assertEqual((rc, self.last(out)), (1, "PROOF: HOLD (golden_reader.json does not fit this download)"))
        self.assertIn("instruction.md has changed", out)
        calls = self.calls()
        rc, out = self.go("init", rev)
        self.assertEqual((rc, self.last(out)), (2, "PROOF: HOLD (golden_reader.json does not fit this download)"))
        self.assertEqual(self.calls(), calls)

    def test_a_different_set_of_attempts_is_other_files_too(self):
        rev = self.make()
        self.go("init", rev)
        extra = rev / "evaluations" / "eval_5__attempt_1__codex__m" / "eval_files" / "verifier"
        extra.mkdir(parents=True)
        (extra / "reward-details.json").write_text(json.dumps(details()), encoding="utf-8")
        rc, out = self.go("check", rev)
        self.assertEqual(rc, 1)
        self.assertIn("the AI attempts in this download are not the ones it looked at", out)

    def test_the_saved_answer_cannot_be_hand_edited_into_nonsense(self):
        rev = self.make()
        self.go("init", rev)
        (rev / qc.GOLDEN_FILE).write_text("{not json", encoding="utf-8")
        rc, out = self.go("check", rev)
        self.assertEqual(rc, 1)
        self.assertIn("cannot be read (do not edit it by hand)", out)


# test name -> (weight, the grader's reason in each AI attempt); every test fails in both attempts
BLAME_TESTS = {
    "t_heavy": (0.40, "The memo names no currency, and the test wanted dollars written out in words."),
    "t_mid": (0.30, "The memo lacks the three drivers that the instruction asked for."),
    "t_light": (0.05, "The title is missing from the memo."),
}
BLAME_REPLY = {
    "t_heavy": {"blame": "CRITERION", "unfair_runs": 2, "reason": "The test asks for dollars in words, the instruction does not.",
                "instruction_quote": "State the total headcount cost for 2027", "grader_quote": "the test wanted dollars written out in words"},
    "t_mid": {"blame": "SOLVER", "unfair_runs": 0, "reason": "The instruction asks for three drivers.",
              "instruction_quote": "name the three biggest drivers of the change", "grader_quote": "lacks the three drivers"},
    "t_light": {"blame": "MIXED", "unfair_runs": 1, "reason": "Only some runs missed a title.",
                "instruction_quote": "words that are not in the instruction at all", "grader_quote": "words that are not in the reason either"},
}
REAL_BLAME_MODEL = qc.blame_model
SMALL = {
    "t_big": (0.90, "The memo names no currency, and the test wanted dollars written out in words."),
    "t_small": (0.01, "The memo is missing the dollars in words that the test wanted."),
}
BLAME_REPLY["t_big"] = BLAME_REPLY["t_mid"]
BLAME_REPLY["t_small"] = BLAME_REPLY["t_heavy"]
BLAME_TESTS_ALL = {**BLAME_TESTS, **SMALL}


class BlameTests(unittest.TestCase):
    """The blame reader, with a stub in place of the model: no network and no claude command."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        self.asked = []
        self.replies = dict(BLAME_REPLY)
        patch = mock.patch.object(qc, "blame_model", self.model)
        patch.start()
        self.addCleanup(patch.stop)

    def model(self, rule, text):
        name = next(n for n in BLAME_TESTS_ALL if f"({n})" in text)
        self.asked.append(name)
        reply = self.replies[name]
        return reply if isinstance(reply, str) else json.dumps(reply)

    def make(self, tests=BLAME_TESTS, where="task"):
        """A rev folder with two AI attempts that failed every test in tests; the criterion text names the test as (name)."""
        rev = self.d / where / "rev_1__11"
        (rev / "task_files").mkdir(parents=True)
        (rev / "task_files" / "instruction.md").write_text(INSTRUCTION, encoding="utf-8")
        crits = [
            {"name": n, "value": 0, "weight": w, "description": f"Pass if the memo handles it ({n}).", "reasoning": why}
            for n, (w, why) in tests.items()
        ]
        for i in (1, 2):
            v = rev / "evaluations" / f"eval_{i}__attempt_1__codex__m" / "eval_files" / "verifier"
            v.mkdir(parents=True)
            (v / "reward-details.json").write_text(json.dumps({"d1": {"criteria": crits}}), encoding="utf-8")
        return rev

    def go(self, rev, *extra, action="init"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = qc.main(["--no-update", "proof", action, str(rev), *extra])
        return rc, buf.getvalue()

    def saved(self, rev):
        return json.loads((rev / qc.BLAME_FILE).read_text(encoding="utf-8"))["answers"]

    def block(self, out):
        """The lines of the blame block."""
        lines = out.splitlines()
        start = next(i for i, x in enumerate(lines) if "blame reader: " in x)
        return [x for x in lines[start:] if x.startswith("[qc]  ") or "blame reader: " in x or "zero-pass test" in x][: 12]

    def test_parse_reads_json_inside_other_words_and_ignores_the_rest(self):
        text = 'Here is my answer: {"blame":"criterion","reason":"x"} and {"other":1}'
        self.assertEqual(qc.blame_object(text)["reason"], "x")
        self.assertIsNone(qc.blame_object('{"blame":"MAYBE"}'))
        self.assertIsNone(qc.blame_object("no json at all"))

    def test_quote_check_downgrades_only_when_neither_quote_is_found(self):
        ins, why = "Write a memo for the board.", ["The memo has no title page."]
        ans = {"blame": "CRITERION", "reason": "r", "instruction_quote": "write a  MEMO for the board.", "grader_quote": "invented words here"}
        got = qc.blame_check(ans, ins, why)
        self.assertEqual((got["blame"], got["grader_quote"], got["downgraded"]), ("CRITERION", "", False))  # one found: kept, the made-up quote dropped
        self.assertEqual(got["instruction_quote"], "write a  MEMO for the board.")
        got = qc.blame_check({**ans, "instruction_quote": "not in the text at all", "blame": "mixed"}, ins, why)
        self.assertEqual((got["blame"], got["downgraded"]), ("UNCLEAR", True))
        got = qc.blame_check({**ans, "instruction_quote": "short", "grader_quote": ""}, ins, why)  # under 12 characters never counts
        self.assertEqual(got["blame"], "UNCLEAR")
        got = qc.blame_check({"blame": "SOLVER", "instruction_quote": "", "grader_quote": ""}, ins, why)
        self.assertEqual(got["blame"], "SOLVER")  # only CRITERION and MIXED need a quote

    def test_quote_check_ignores_markdown_marks_dash_lengths_and_no_break_spaces(self):
        ins = "Write a **memo** for the board \u2013 no more than `two` pages.\u00a0Keep it plain."
        why = ["The memo runs to three pages."]
        quote = "Write a memo for the board - no more than two pages. Keep it plain."
        got = qc.blame_check({"blame": "CRITERION", "reason": "r", "instruction_quote": quote, "grader_quote": ""}, ins, why)
        self.assertEqual((got["blame"], got["instruction_quote"], got["downgraded"]), ("CRITERION", quote, False))
        wrong = {"blame": "CRITERION", "reason": "r", "instruction_quote": "Write a memo for the board - no more than three pages.", "grader_quote": ""}
        self.assertEqual(qc.blame_check(wrong, ins, why)["blame"], "UNCLEAR")  # the tolerance is about marks, never about words

    def oracle_run(self, rev, graded):
        """Add a reference-solution (ORACLE) attempt that graded the tests in graded (name -> value)."""
        v = rev / "evaluations" / "eval_9__attempt_1__oracle__m" / "eval_files" / "verifier"
        v.mkdir(parents=True)
        crits = [{"name": n, "value": val, "weight": 0.1, "description": f"Pass if the memo handles it ({n}).", "reasoning": "oracle"} for n, val in graded.items()]
        (v / "reward-details.json").write_text(json.dumps({"d1": {"criteria": crits}}), encoding="utf-8")

    def test_a_test_the_reference_solution_failed_too_is_left_out(self):
        rev = self.make()
        self.oracle_run(rev, {"t_heavy": 0, "t_mid": 1})  # t_light was not graded by the oracle run, so it stays in
        _, out = self.go(rev)
        self.assertEqual(self.asked, ["t_mid", "t_light"])
        self.assertIn("blame reader: 1 zero-pass test left out because the reference solution failed it too", out)

    def test_when_the_reference_solution_failed_every_zero_pass_test_check_does_not_hold_for_the_blame_reader(self):
        rev = self.make()
        self.oracle_run(rev, dict.fromkeys(BLAME_TESTS, 0))
        self.go(rev)
        self.assertEqual(self.asked, [])
        _, out = self.go(rev, action="check")
        self.assertNotIn("the blame reader has not run", out)

    def test_init_flags_the_task_and_prints_the_block_before_the_proof_text(self):
        rev = self.make()
        rc, out = self.go(rev)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.asked, ["t_heavy", "t_mid", "t_light"])  # heaviest first
        self.assertIn("These zero-pass tests may be the test's fault, not the answer's (1):", out)
        self.assertIn("d1/t_heavy (weight 0.4, the test): The test asks for dollars in words", out)
        self.assertIn('instruction says: "State the total headcount cost for 2027"', out)
        self.assertIn("d1/t_mid (weight 0.3): the test looks fair", out)
        self.assertNotIn("d1/t_light (weight 0.05, ", out)  # MIXED with two invented quotes became UNCLEAR, so it is not flagged
        self.assertIn("the reader could not decide: d1/t_light", out)
        self.assertLess(out.index("blame reader: "), out.index("Wrote "))
        self.assertEqual(sorted(a["blame"] for a in self.saved(rev).values()), ["CRITERION", "SOLVER", "UNCLEAR"])

    def test_flagged_criteria_are_listed_heaviest_first(self):
        self.replies = {n: BLAME_REPLY["t_heavy"] for n in BLAME_TESTS}
        _, out = self.go(self.make())
        order = [out.index(f"d1/{n} (weight") for n in ("t_heavy", "t_mid", "t_light")]
        self.assertEqual(order, sorted(order))
        self.assertIn("(3):", out)

    def test_loose_rule_flags_on_mixed_alone(self):
        self.replies = {n: BLAME_REPLY["t_mid"] for n in BLAME_TESTS}
        self.replies["t_light"] = {**BLAME_REPLY["t_heavy"], "blame": "MIXED"}
        _, out = self.go(self.make())
        self.assertIn("(1):", out)
        self.assertIn("d1/t_light (weight 0.05, the test and the answers)", out)

    def test_nothing_flagged_says_so(self):
        self.replies = {n: BLAME_REPLY["t_mid"] for n in BLAME_TESTS}
        _, out = self.go(self.make())
        self.assertIn("No zero-pass test looks like the test's fault.", out)
        self.assertNotIn("may be the test's fault", out)

    def test_saved_answers_are_reused_and_a_changed_reason_asks_again(self):
        rev = self.make()
        _, first = self.go(rev)
        self.assertEqual(len(self.asked), 3)
        self.asked.clear()
        self.replies = {n: BLAME_REPLY["t_mid"] for n in BLAME_TESTS}  # a new roll would say something else
        rev.joinpath("zero_pass_proof.csv").unlink()
        _, again = self.go(rev)
        self.assertEqual(self.asked, [])
        self.assertNotIn("asking the blame reader", again)
        self.assertEqual(self.block(first), self.block(again))  # the same answer as before
        self.assertIn("(1):", again)
        for f in rev.glob("evaluations/*/eval_files/verifier/reward-details.json"):  # the graders' reasons change in this download
            f.write_text(f.read_text(encoding="utf-8").replace("lacks the three drivers", "A different reason from the grader"), encoding="utf-8")
        self.go(rev)
        self.assertEqual(self.asked, ["t_mid"])  # only the test whose reasons changed

    def test_check_reads_saved_answers_and_never_calls_the_model(self):
        rev = self.make()
        self.go(rev)
        self.asked.clear()
        _, out = self.go(rev, action="check")
        self.assertEqual(self.asked, [])
        self.assertIn("(1):", out)

    def test_check_without_blame_reader_json_holds_and_says_so(self):
        rev = self.make()
        self.go(rev)
        (rev / qc.BLAME_FILE).unlink()
        self.asked.clear()
        rc, out = self.go(rev, action="check")
        self.assertEqual((rc, self.asked), (1, []))
        self.assertIn("the blame reader has not run for this task", out)
        self.assertIn("python qc.py proof init <the same folder>", out)
        self.assertEqual(out.strip().splitlines()[-1], "PROOF: HOLD (the blame reader has not run on this task)")

    def test_check_with_some_answers_missing_holds(self):
        rev = self.make()
        self.go(rev)
        answers = self.saved(rev)
        qc.blame_write(rev, dict(list(answers.items())[:1]))
        rc, out = self.go(rev, action="check")
        self.assertEqual(rc, 1)
        self.assertEqual(out.strip().splitlines()[-1], "PROOF: HOLD (the blame reader has not run on this task)")

    def test_cap_asks_the_heaviest_and_says_what_was_left_out(self):
        _, out = self.go(self.make(), "--blame-max", "2")
        self.assertEqual(self.asked, ["t_heavy", "t_mid"])
        self.assertIn("1 lighter test left out, the cap is 2 per task", out)
        self.assertEqual(qc.BLAME_MAX, 40)
        self.asked.clear()
        many = {f"t{i:02d}": (0.01 * (i + 1), "The memo is missing a part.") for i in range(43)}
        with mock.patch.object(qc, "blame_model", lambda rule, text: self.asked.append(1) or json.dumps(BLAME_REPLY["t_mid"])):
            _, out = self.go(self.make(many, "task2"))
        self.assertEqual(len(self.asked), 40)
        self.assertIn("3 lighter tests left out, the cap is 40 per task", out)

    def test_a_task_asked_at_the_old_cap_holds_until_proof_init_asks_about_the_rest(self):
        many = {f"t{i:02d}": (0.01 * (i + 1), "The memo is missing a part.") for i in range(17)}
        rev = self.make(many, "task3")
        with mock.patch.object(qc, "blame_model", lambda rule, text: self.asked.append(1) or json.dumps(BLAME_REPLY["t_mid"])):
            self.go(rev, "--blame-max", "15")  # what proof init did while the cap was 15
            self.assertEqual(len(self.asked), 15)
            _, out = self.go(rev, action="check")
            self.assertIn("the blame reader has not run for every zero-pass test", out)
            self.asked.clear()
            self.go(rev)  # the default cap is 40 now: only the 2 tests with no saved answer are asked
            self.assertEqual(len(self.asked), 2)
            _, out = self.go(rev, action="check")
            self.assertNotIn("the blame reader has not run", out)

    def test_a_model_failure_says_no_blame_check_holds_and_keeps_saved_answers(self):
        rev = self.make()
        calls = []

        def broken(rule, text):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("claude exited 3: simulated stderr")
            return json.dumps(BLAME_REPLY["t_heavy"])

        with mock.patch.object(qc, "blame_model", broken):
            rc, out = self.go(rev)
        self.assertIn("blame reader: stopped, this task has no blame check. Reason: an AI call failed (RuntimeError: claude exited 3: simulated stderr", out)
        self.assertEqual(rc, 1)  # not a silent pass
        self.assertTrue(out.strip().splitlines()[-1].startswith("PROOF: HOLD (the blame reader did not run on this task"))
        self.assertTrue((rev / qc.PROOF_FILE).is_file())  # the sheet is still written
        self.assertEqual(len(self.saved(rev)), 1)  # the first answer is kept
        rc, out = self.go(rev, action="check")  # and check holds the same way as a missing file
        self.assertEqual((rc, out.strip().splitlines()[-1]), (1, "PROOF: HOLD (the blame reader has not run on this task)"))
        (rev / qc.PROOF_FILE).unlink()
        self.go(rev)
        self.assertEqual(len(self.asked), 2)  # only the two unanswered ones

    def test_a_reply_with_no_answer_is_asked_twice_then_holds_and_is_not_saved(self):
        self.replies["t_mid"] = "I think the test is fine but I will not use JSON."
        rev = self.make()
        rc, out = self.go(rev)
        self.assertEqual(self.asked.count("t_mid"), 2)
        self.assertIn("no answer in the reply for d1/t_mid. Its output was: I think the test is fine", out)
        self.assertIn("the reader could not decide: d1/t_mid, d1/t_light", out)
        self.assertEqual(len(self.saved(rev)), 2)
        self.assertEqual(rc, 1)
        self.assertTrue(out.strip().splitlines()[-1].startswith("PROOF: HOLD (the blame reader did not run"))

    def test_the_real_model_helper_runs_through_the_claude_command(self):
        fake = self.d / "fake_claude.py"
        fake.write_text("import sys,json\nsys.stdin.read()\nprint('Sure. ' + json.dumps({'blame':'SOLVER','reason':'ok','instruction_quote':'','grader_quote':''}))\n", encoding="utf-8")
        rev = self.make({"t_mid": BLAME_TESTS["t_mid"]})
        with mock.patch.object(qc, "blame_model", REAL_BLAME_MODEL), mock.patch.dict(os.environ, {"GCR_CLAUDE": f'"{sys.executable}" "{fake}"'}):
            _, out = self.go(rev)
        self.assertIn("d1/t_mid (weight 0.3): the test looks fair", out)  # the reply had words around its JSON

    def test_default_is_on_and_no_blame_gives_the_old_results_exactly(self):
        on, off = self.make(SMALL, "on"), self.make(SMALL, "off")
        rc_on, out_on = self.go(on)
        self.assertEqual(self.asked, ["t_big", "t_small"])  # on by default, no option given
        self.assertTrue((on / qc.BLAME_FILE).is_file())
        self.asked.clear()
        rc_off, out_off = self.go(off, "--no-blame")
        self.assertEqual(self.asked, [])
        self.assertFalse((off / qc.BLAME_FILE).exists())
        self.assertIn("blame reader: skipped (--no-blame), so this task has no blame check.", out_off)
        sheet = (off / qc.PROOF_FILE).read_text(encoding="utf-8-sig")
        self.assertEqual(sheet.count("\n"), 2)  # header and the one heavy test, as before the reader existed
        self.assertNotIn("BLAME READER", sheet)
        rc, out = self.go(off, "--no-blame", action="check")
        self.assertEqual((rc, out.strip().splitlines()[-1]), (1, "PROOF: HOLD (1 open)"))
        self.assertNotIn("not run", out)
        self.assertEqual(rc_off, 0)

    def test_old_blame_option_on_proof_init_is_a_harmless_alias(self):
        rc, out = self.go(self.make(SMALL), "--blame")
        self.assertEqual((rc, self.asked), (0, ["t_big", "t_small"]))

    def test_a_flagged_light_test_adds_a_row_and_holds_until_it_is_filled(self):
        rev = self.make(SMALL)
        rc, out = self.go(rev)
        self.assertEqual(rc, 0)
        self.assertIn("the blame reader flagged 1 more test", out)
        sheet = (rev / qc.PROOF_FILE).read_text(encoding="utf-8-sig")
        self.assertIn("d1/t_small", sheet)
        self.assertIn("BLAME READER FLAGGED THIS TEST", sheet)
        self.assertIn("The test asks for dollars in words", sheet)  # the reader's sentence
        self.assertIn("State the total headcount cost for 2027", sheet)  # a short quote
        rc, out = self.go(rev, action="check")
        self.assertEqual((rc, out.strip().splitlines()[-1]), (1, "PROOF: HOLD (2 open)"))
        rows = list(csv.reader(io.StringIO(sheet)))
        for r in rows[1:]:
            r[3:6] = [QUOTE, "the memo, second paragraph", WHY]
        with open(rev / qc.PROOF_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
        rc, out = self.go(rev, action="check")
        self.assertEqual((rc, out.strip().splitlines()[-1]), (0, "PROOF: COMPLETE"))
        self.assertEqual(self.asked.count("t_big"), 1)  # check asked nothing more

    def test_an_unflagged_task_has_the_same_sheet_and_result_as_without_the_reader(self):
        self.replies = {n: BLAME_REPLY["t_mid"] for n in BLAME_TESTS}
        self.replies.update({n: BLAME_REPLY["t_mid"] for n in SMALL})
        on, off = self.make(SMALL, "on"), self.make(SMALL, "off")
        rc_on, out_on = self.go(on)
        rc_off, _ = self.go(off, "--no-blame")
        self.assertEqual(rc_on, rc_off)
        self.assertEqual((on / qc.PROOF_FILE).read_text(encoding="utf-8-sig"), (off / qc.PROOF_FILE).read_text(encoding="utf-8-sig"))
        self.assertEqual(self.go(on, action="check")[1].strip().splitlines()[-1], self.go(off, "--no-blame", action="check")[1].strip().splitlines()[-1])

    def test_a_task_with_no_zero_pass_test_or_one_scored_attempt_is_unaffected(self):
        rev = self.make(SMALL, "two")
        for f in list(rev.glob("evaluations/*attempt_1*"))[1:]:
            shutil.rmtree(f)  # one scored AI attempt left
        rc, out = self.go(rev, action="check")
        self.assertEqual(rc, 1)
        self.assertIn("only 1 of", out)
        self.assertEqual(self.asked, [])
        self.assertNotIn("blame", out)
        rev = self.d / "pass" / "rev_1__11"  # every test passes in both attempts
        (rev / "task_files").mkdir(parents=True)
        (rev / "task_files" / "instruction.md").write_text(INSTRUCTION, encoding="utf-8")
        for i in (1, 2):
            v = rev / "evaluations" / f"eval_{i}__attempt_1__codex__m" / "eval_files" / "verifier"
            v.mkdir(parents=True)
            crit = {"name": "t_ok", "value": 1, "weight": 1.0, "description": "d", "reasoning": "fine"}
            (v / "reward-details.json").write_text(json.dumps({"d1": {"criteria": [crit]}}), encoding="utf-8")
        rc, out = self.go(rev, action="check")
        self.assertEqual((rc, out.strip().splitlines()[-1]), (0, "PROOF: COMPLETE"))
        self.assertEqual(self.asked, [])
        self.assertNotIn("blame", out)
        self.assertFalse((rev / qc.BLAME_FILE).exists())

    def test_no_blame_asks_nothing_and_writes_no_file(self):
        rev = self.make()
        _, out = self.go(rev, "--no-blame")
        self.assertNotIn("asking the blame reader", out)
        self.assertFalse((rev / qc.BLAME_FILE).exists())
        self.assertEqual(self.asked, [])

    def test_manage_reads_the_saved_answers_without_the_model_and_shows_the_hold(self):
        root, out_dir = self.d / "dl", self.d / "out"
        rev = self.make(SMALL, "dl/task-a")

        def manage(*extra):
            buf = io.StringIO()
            with mock.patch.object(qc, "run", lambda cmd, cwd=None: 1), redirect_stdout(buf):
                rc = qc.main(["--no-update", "manage", str(root), "--out", str(out_dir), *extra])
            return rc, buf.getvalue(), (out_dir / "manager_summary.csv").read_text()

        rc, out, table = manage()  # nothing saved yet
        self.assertEqual(self.asked, [])
        self.assertTrue(table.splitlines()[0].endswith(",blame"))
        self.assertTrue(table.splitlines()[1].endswith("HOLD (blame reader has not run)"))
        self.go(rev)  # proof init saves blame_reader.json
        self.asked.clear()
        rc, out, table = manage()
        self.assertEqual(self.asked, [])
        self.assertTrue(table.splitlines()[1].endswith("HOLD (1 flagged open)"), table)
        self.assertIn("blame reader: HOLD on 1 of 1 tasks", out)
        rows = list(csv.reader(io.StringIO((rev / qc.PROOF_FILE).read_text(encoding="utf-8-sig"))))
        for r in rows[1:]:
            r[3:6] = [QUOTE, "the memo, second paragraph", WHY]
        with open(rev / qc.PROOF_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
        self.assertTrue(manage()[2].splitlines()[1].endswith("1 flagged (all answered)"))
        rc, out, table = manage("--no-blame")
        self.assertEqual(table.splitlines()[0], "task_id,task_name,rev,result,report")  # the old table
        self.assertEqual(rc, 0)

    def test_manage_blame_asks_the_model_only_when_told_to(self):
        root, out_dir = self.d / "dl", self.d / "out"
        rev = self.make(SMALL, "dl/task-a")
        buf = io.StringIO()
        with mock.patch.object(qc, "run", lambda cmd, cwd=None: 1), redirect_stdout(buf):
            qc.main(["--no-update", "manage", str(root), "--out", str(out_dir), "--blame"])
        self.assertEqual(self.asked, ["t_big", "t_small"])
        self.assertTrue((out_dir / "manager" / "11" / "blame_reader_report.md").is_file())
        self.assertTrue((rev / qc.BLAME_FILE).is_file())

    # ---- the look-first pointer: no AI call, never blocks ----

    def write_flags(self, rows, name="flags.csv", header=("task_id", "tab", "best_reader_flag", "opus_replay_flag")):
        p = self.d / name
        with open(p, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: the lane file may carry a byte order mark
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        return p

    def look(self, rev, flags, *extra):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = qc.main(["--no-update", "look-first", str(rev), "--replay-flags", str(flags), *extra])
        return rc, buf.getvalue()

    def test_look_label_table(self):
        L = qc.look_label
        self.assertEqual(L("flagged", "flagged"), "both flagged")
        self.assertEqual(L("not flagged", "not flagged"), "neither flagged")
        self.assertEqual(L("flagged", "not flagged"), "one flagged")
        self.assertEqual(L("not flagged", "flagged"), "one flagged")
        self.assertEqual(L("not run", "flagged"), "no pointer (blame reader not run)")
        self.assertEqual(L("flagged", "no answer"), "no pointer (no TFRL review read)")

    def test_look_wording_says_pointer_not_rule_and_keeps_the_measured_counts(self):
        both = "\n".join(qc.look_lines("flagged", "flagged", "UNKNOWN"))
        self.assertIn("LOOK FIRST", both)
        self.assertIn("25 of 40 (62 percent)", both)
        self.assertIn("4 of 23 (17 percent)", both)
        self.assertIn("It does not send the task back and it does not pass it.", both)
        ekw = "\n".join(qc.look_lines("flagged", "flagged", "EKW"))
        self.assertIn("15 of 16", ekw)
        self.assertIn("not confirmed yet", ekw)
        svc = "\n".join(qc.look_lines("flagged", "flagged", "SVC"))
        self.assertIn("approved 14 of the 24", svc)
        self.assertIn("Do not send an SVC task back for this line alone.", svc)
        neither = "\n".join(qc.look_lines("not flagged", "not flagged", "EKW"))
        self.assertIn("4 of 23 (17 percent)", neither)
        self.assertIn("not a pass", neither)
        one = "\n".join(qc.look_lines("flagged", "not flagged", "SVC"))
        self.assertIn("did not sort tasks", one)
        self.assertIn("13 of 31 (42 percent)", one)
        self.assertIn("5 of 11 (45 percent)", one)
        for text in (both, ekw, svc, neither, one):
            self.assertNotIn("—", text)

    def test_look_flags_file_words_and_errors(self):
        p = self.write_flags([["11", "EKW", "1", "1"], ["12", "SVC", "0", "0"], ["13", "SVC", "1", "NA"], ["14", "EKW", "", ""], ["15", "EKW", "", " True "]])
        got = qc.look_flags_read(p)
        self.assertEqual(got, {"11": "flagged", "12": "not flagged", "13": "no answer", "14": "no answer", "15": "flagged"})
        bad = self.write_flags([["11", "EKW"]], "bad.csv", header=("task_id", "tab"))
        with self.assertRaises(ValueError):
            qc.look_flags_read(bad)
        with self.assertRaises(ValueError):
            qc.look_flags_read(self.d / "nothing.csv")

    def test_look_first_command_on_a_task_with_saved_blame_answers(self):
        rev = self.make()
        self.go(rev)  # proof init saves blame_reader.json (t_heavy is flagged)
        self.asked.clear()
        both = self.write_flags([["11", "EKW", "1", "1"]])
        rc, out = self.look(rev, both, "--tab", "EKW")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.asked, [])  # no AI call
        self.assertIn("LOOK FIRST: both checks flagged this task", out)
        self.assertIn("On EKW tasks it was 15 of 16 against 3 of 13", out)
        self.assertEqual(out.strip().splitlines()[-1], "LOOK: both flagged (task 11; the blame reader flagged, the TFRL review read flagged)")
        one = self.write_flags([["11", "EKW", "1", "0"]], "one.csv")
        rc, out = self.look(rev, one)
        self.assertEqual(rc, 0)  # it never blocks
        self.assertEqual(out.strip().splitlines()[-1], "LOOK: one flagged (task 11; the blame reader flagged, the TFRL review read not flagged)")
        self.assertIn("did not sort tasks", out)
        absent = self.write_flags([["99", "EKW", "1", "1"]], "absent.csv")
        rc, out = self.look(rev, absent)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip().splitlines()[-1], "LOOK: no pointer (no TFRL review read) (task 11; the blame reader flagged, the TFRL review read no answer)")
        na = self.write_flags([["11", "EKW", "1", "NA"]], "na.csv")
        self.assertIn("no pointer (no TFRL review read)", self.look(rev, na)[1])
        self.assertEqual(self.asked, [])

    def test_look_first_says_neither_when_the_blame_reader_found_nothing_and_the_read_did_not_either(self):
        self.replies = {n: BLAME_REPLY["t_mid"] for n in BLAME_TESTS_ALL}
        rev = self.make()
        self.go(rev)
        self.asked.clear()
        rc, out = self.look(rev, self.write_flags([["11", "SVC", "0", "0"]]), "--tab", "SVC")
        self.assertEqual(rc, 0)
        self.assertIn("neither check flagged this task", out)
        self.assertEqual(out.strip().splitlines()[-1], "LOOK: neither flagged (task 11; the blame reader not flagged, the TFRL review read not flagged)")

    def test_look_first_gives_no_pointer_and_asks_nothing_when_the_blame_reader_has_not_run(self):
        rev = self.make()  # nothing saved
        rc, out = self.look(rev, self.write_flags([["11", "EKW", "1", "1"]]))
        self.assertEqual(rc, 0)
        self.assertEqual(self.asked, [])
        self.assertIn("The blame reader has not run on this task: python qc.py proof init", out)
        self.assertEqual(out.strip().splitlines()[-1], "LOOK: no pointer (blame reader not run) (task 11; the blame reader not run, the TFRL review read flagged)")

    def test_look_first_stops_on_a_bad_flags_file_or_folder(self):
        rev = self.make()
        rc, out = self.look(rev, self.write_flags([["11", "EKW"]], "bad.csv", header=("task_id", "tab")))
        self.assertEqual(rc, 2)
        self.assertIn("has no task_id and opus_replay_flag columns", out)
        rc, out = self.look(self.d / "not-a-rev-folder", self.write_flags([["11", "EKW", "1", "1"]]))
        self.assertEqual(rc, 2)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = qc.main(["--no-update", "look-first", str(rev)])  # no flags file and no saved TFRL read
        self.assertEqual(rc, 0)
        self.assertIn("LOOK: no pointer", buf.getvalue())  # no flags file, no saved TFRL read, blame reader not run: a pointer line, exit 0

    def test_manage_adds_the_look_first_column_only_when_the_flags_file_is_given(self):
        root, out_dir = self.d / "dl", self.d / "out"
        rev = self.make(SMALL, "dl/task-a")
        self.go(rev)
        self.asked.clear()
        flags = self.write_flags([["11", "EKW", "1", "1"]])

        def manage(*extra):
            buf = io.StringIO()
            with mock.patch.object(qc, "run", lambda cmd, cwd=None: 0), redirect_stdout(buf):
                rc = qc.main(["--no-update", "manage", str(root), "--out", str(out_dir), *extra])
            return rc, buf.getvalue(), (out_dir / "manager_summary.csv").read_text().splitlines()

        rc, out, table = manage("--replay-flags", str(flags))
        self.assertEqual(rc, 0)
        self.assertEqual(self.asked, [])
        self.assertTrue(table[0].endswith(",blame,look_first"), table)
        self.assertTrue(table[1].endswith("both flagged"), table)
        self.assertIn("both checks flagged 1 of 1 tasks: 11 (", out)
        self.assertIn("sends no task back and passes none", out)
        rc, out, table = manage()
        self.assertTrue(table[0].endswith(",blame"), table)  # no flags file, no new column, no new line
        self.assertNotIn("look first", out)
        rc, out, table = manage("--replay-flags", str(self.d / "missing.csv"))
        self.assertEqual(rc, 2)
        self.assertIn("manage stopped:", out)

    # ---- tfrl-read: TFRL's own review prompt, one Opus call, saved in the rev folder ----

    def stub_replay(self, severities=None, text=None, boom=None):
        """Replace the Opus call. The fake writes the review the way the real call would, into <cwd>/out/review.md, and records what it was given."""
        seen = []

        def fake(cwd, prompt):
            cwd = Path(cwd)
            seen.append({"prompt": prompt, "pkg": sorted(p.name for p in (cwd / "pkg").iterdir()), "runs": sorted(p.name for p in (cwd / "runs").iterdir())})
            if boom:
                raise boom
            body = text
            if body is None:
                checks = [{"id": k, "severity": v} for k, v in severities.items()]
                body = "My review.\n" + json.dumps({"benchmark": "x", "checks": checks, "overall_verdict": "reject"})
            (cwd / "out" / "review.md").write_text(body, encoding="utf-8")
            return 0, "done"

        patch = mock.patch.object(qc, "replay_ask", fake)
        patch.start()
        self.addCleanup(patch.stop)
        return seen

    def tfrl(self, rev, *extra):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = qc.main(["--no-update", "tfrl-read", str(rev), *extra])
        return rc, buf.getvalue()

    def tree_hash(self, folder):
        h = hashlib.sha256()
        for p in sorted(Path(folder).rglob("*")):
            if p.is_file():
                h.update(str(p.relative_to(folder)).encode() + p.read_bytes())
        return h.hexdigest()

    MAJOR = {"1.3": "good", "1.4": "major", "1.5": "minor"}
    CLEAN = {"1.3": "good", "1.4": "minor", "1.5": "good"}

    def test_tfrl_read_flags_a_major_saves_it_and_never_touches_the_task(self):
        rev = self.make()
        (rev / qc.BLAME_FILE).write_text("{}", encoding="utf-8")  # an earlier review output that must not reach the reader
        seen = self.stub_replay(self.MAJOR)
        before = self.tree_hash(rev / "task_files")
        rc, out = self.tfrl(rev)
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.strip().splitlines()[-1], "TFRL READ: flagged (major on 1.4)")
        self.assertIn("check 1.4 (the prompt and the tests do not match)", out)
        data = json.loads((rev / qc.REPLAY_FILE).read_text(encoding="utf-8"))
        self.assertEqual((data["flag"], data["model"], data["severities"]["1.4"]), ("1", "opus", "major"))
        self.assertTrue((rev / qc.REPLAY_REPORT).read_text(encoding="utf-8").startswith("My review."))
        self.assertEqual(len(seen), 1)
        self.assertIn("# Comprehensive Review", seen[0]["prompt"])  # TFRL's prompt, unchanged
        self.assertIn("review.md", seen[0]["prompt"])
        self.assertIn("instruction.md", seen[0]["pkg"])
        self.assertTrue(all(n.startswith("eval_") for n in seen[0]["runs"]) and seen[0]["runs"])
        self.assertNotIn(qc.BLAME_FILE, seen[0]["pkg"])
        self.assertEqual(self.tree_hash(rev / "task_files"), before)  # the task folder is never changed

    def test_tfrl_read_not_flagged_when_no_check_is_major(self):
        rev = self.make()
        self.stub_replay(self.CLEAN)
        rc, out = self.tfrl(rev)
        self.assertEqual((rc, out.strip().splitlines()[-1]), (0, "TFRL READ: not flagged"))
        self.assertEqual(json.loads((rev / qc.REPLAY_FILE).read_text(encoding="utf-8"))["flag"], "0")

    def test_tfrl_read_reuses_the_saved_answer_until_the_instruction_changes_or_again(self):
        rev = self.make()
        seen = self.stub_replay(self.MAJOR)
        self.tfrl(rev)
        rc, out = self.tfrl(rev)
        self.assertEqual((len(seen), rc), (1, 0))  # no second call
        self.assertIn("saved answer for this task, no AI call", out)
        self.tfrl(rev, "--again")
        self.assertEqual(len(seen), 2)
        (rev / "task_files" / "instruction.md").write_text(INSTRUCTION + " One more sentence.", encoding="utf-8")
        self.tfrl(rev)
        self.assertEqual(len(seen), 3)

    def test_tfrl_read_without_a_usable_answer_saves_nothing_and_exits_two(self):
        rev = self.make()
        self.stub_replay(text="I could not decide, no JSON here.")
        rc, out = self.tfrl(rev)
        self.assertEqual(rc, 2)
        self.assertTrue(out.strip().splitlines()[-1].startswith("TFRL READ: could not run"))
        self.assertFalse((rev / qc.REPLAY_FILE).exists())
        self.assertEqual(qc.replay_state(rev), "no answer")

    def test_tfrl_read_missing_check_or_timeout_is_could_not_run(self):
        rev = self.make()
        self.stub_replay({"1.3": "good", "1.4": "major"})  # 1.5 missing
        self.assertEqual(self.tfrl(rev)[0], 2)
        self.stub_replay(boom=subprocess.TimeoutExpired("claude", 5))
        rc, out = self.tfrl(rev, "--again")
        self.assertEqual(rc, 2)
        self.assertIn("could not run (timed out)", out)

    def test_tfrl_read_json_is_found_after_prose_and_braces(self):
        text = 'Notes {not json} and {"x": 1}.\n{"benchmark": "b", "checks": [{"id": "1.3", "severity": "Good"}, {"id": "1.4", "severity": "MAJOR"}, {"id": "1.5", "severity": "good"}]}'
        self.assertEqual(qc.replay_severities(qc.replay_json(text)), {"1.3": "good", "1.4": "major", "1.5": "good"})
        self.assertIsNone(qc.replay_json("no object at all"))

    def test_look_first_uses_the_saved_tfrl_read_without_a_flags_file(self):
        rev = self.make()
        self.go(rev)  # blame answers saved (t_heavy flagged)
        self.asked.clear()
        self.stub_replay(self.MAJOR)
        self.tfrl(rev)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = qc.main(["--no-update", "look-first", str(rev)])
        self.assertEqual(rc, 0)
        self.assertEqual(self.asked, [])
        self.assertEqual(buf.getvalue().strip().splitlines()[-1], "LOOK: both flagged (task 11; the blame reader flagged, the TFRL review read flagged)")
        # a flags file still wins when it is given
        out = self.look(rev, self.write_flags([["11", "EKW", "1", "0"]], "over.csv"))[1]
        self.assertEqual(out.strip().splitlines()[-1], "LOOK: one flagged (task 11; the blame reader flagged, the TFRL review read not flagged)")

    def test_look_first_with_no_tfrl_read_says_how_to_make_one(self):
        rev = self.make()
        self.go(rev)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = qc.main(["--no-update", "look-first", str(rev)])
        self.assertEqual(rc, 0)
        self.assertIn("python qc.py tfrl-read", buf.getvalue())
        self.assertIn("LOOK: no pointer (no TFRL review read)", buf.getvalue())

    def test_manage_adds_look_first_from_saved_tfrl_reads_without_a_flags_file(self):
        root, out_dir = self.d / "dl", self.d / "out"
        rev = self.make(SMALL, "dl/task-a")
        self.go(rev)
        self.stub_replay(self.MAJOR)
        self.tfrl(rev)
        self.asked.clear()
        buf = io.StringIO()
        with mock.patch.object(qc, "run", lambda cmd, cwd=None: 0), redirect_stdout(buf):
            rc = qc.main(["--no-update", "manage", str(root), "--out", str(out_dir)])
        table = (out_dir / "manager_summary.csv").read_text().splitlines()
        self.assertEqual(rc, 0)
        self.assertTrue(table[0].endswith(",blame,look_first"), table)
        self.assertTrue(table[1].endswith("both flagged"), table)
        self.assertEqual(self.asked, [])


class FixTests(unittest.TestCase):
    """qc.py fix, with a stand-in for the model: no claude command, no network."""

    CRIT = '[judge]\nweight = 1.0\n\n[[criterion]]\nname = "a"\ndescription = "Old rule A."\ntype = "binary"\nweight = 0.6\n\n[[criterion]]\nname = "b"\ndescription = "Rule B."\ntype = "binary"\nweight = 0.4\n'

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.pkg = self.d / "task-1"
        for rel, body in {
            "instruction.md": "Write the memo. Use the Q3 figures. Keep it short.\n",
            "environment/data.csv": "x,y\n1,2\n",
            "solution/answer.txt": "42\n",
            "tests/reward.toml": '[[reward]]\nname = "reward"\n[reward.weights]\ndeliverables_01 = 1.0\n',
            "tests/deliverables_01/judge.toml": self.CRIT,
        }.items():
            (self.pkg / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.pkg / rel).write_text(body, encoding="utf-8")
        self.findings = self.d / "FINDINGS.md"
        self.findings.write_text("Criterion a demands something the instruction does not ask for.\n", encoding="utf-8")
        self.calls = []
        self.script = []  # one entry per model call: a function(cwd) -> reply text, or a reply string
        self.patches = [
            mock.patch.object(qc, "fx_claude", lambda: "/fake/claude"),
            mock.patch.object(qc, "fx_ask", self.fake_ask),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.d, ignore_errors=True)

    def fake_ask(self, cwd, prompt):
        self.calls.append((Path(cwd), prompt))
        step = self.script[len(self.calls) - 1]
        reply = step(Path(cwd)) if callable(step) else step
        return 0, reply

    @staticmethod
    def good(cwd):
        j = cwd / "tests/deliverables_01/judge.toml"
        j.write_text(j.read_text(encoding="utf-8").replace("Old rule A.", "New rule A, with the wording the instruction uses."), encoding="utf-8")
        (cwd / "instruction.md").write_text("Write the memo. Use the Q3 figures. Keep it under one page.\n", encoding="utf-8")
        (cwd / "fix_log.md").write_text("a: reworded.\nFILES CHANGED: tests/deliverables_01/judge.toml, instruction.md\n", encoding="utf-8")
        return "done"

    @staticmethod
    def bad(cwd):  # weights no longer add up to what they did
        j = cwd / "tests/deliverables_01/judge.toml"
        j.write_text(j.read_text(encoding="utf-8").replace("weight = 0.6", "weight = 0.9"), encoding="utf-8")
        (cwd / "fix_log.md").write_text("changed weight.\n", encoding="utf-8")
        return "done"

    def fix(self, *extra):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = qc.main(["--no-update", "fix", str(self.pkg), str(self.findings), *extra])
        return rc, buf.getvalue()

    def hashes(self):
        return {str(p.relative_to(self.pkg)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(self.pkg.rglob("*")) if p.is_file()}

    def out(self):
        return self.d / "fix_task-1"

    def test_parser_knows_the_command(self):
        a = qc.build_parser().parse_args(["fix", "T", "F.md", "--out", "O", "--no-ask"])
        self.assertEqual((a.cmd, a.task_dir, a.findings, a.out, a.no_ask), ("fix", "T", "F.md", "O", True))
        self.assertIs(qc.build_parser().parse_args(["fix", "T", "F.md"]).no_ask, False)

    def test_accepted_fix(self):
        self.script = [self.good]
        rc, out = self.fix()
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.strip().splitlines()[-1], "FIX: ACCEPTED BY CHECKER (2 files changed; 0 criteria made looser)")
        self.assertEqual(len(self.calls), 1)
        for name in ("fix_diff.md", "fix_log.md", "fixed/FIX_FINDINGS.md"):
            self.assertTrue((self.out() / name).is_file(), name)
        self.assertIn("something the instruction does not ask for", (self.out() / "fixed/FIX_FINDINGS.md").read_text(encoding="utf-8"))
        self.assertIn("FILES CHANGED", (self.out() / "fix_log.md").read_text(encoding="utf-8"))

    def add_copies(self):
        """judge_s2.toml and judge_s3.toml beside judge.toml, as pipeline/tools/rewardkit_mean_of_3.py writes them."""
        j = self.pkg / "tests/deliverables_01/judge.toml"
        for s in ("judge_s2.toml", "judge_s3.toml"):
            (j.parent / s).write_bytes(j.read_bytes())

    def test_sample_copies_are_not_duplicates(self):
        self.add_copies()
        crit, sums, groups, broken, dups = qc.fx_criteria(self.pkg)
        self.assertEqual(dups, [])
        self.assertEqual(sorted(crit), ["deliverables_01/a", "deliverables_01/b"])
        self.assertEqual(sorted(sums), ["deliverables_01/judge.toml", "deliverables_01/judge_s2.toml", "deliverables_01/judge_s3.toml"])
        self.assertEqual(broken, [])

    def test_a_real_duplicate_is_still_a_duplicate(self):
        j = self.pkg / "tests/deliverables_01/judge.toml"
        j.write_text(j.read_text(encoding="utf-8") + '\n[[criterion]]\nname = "a"\ndescription = "Again."\ntype = "binary"\nweight = 0.0\n', encoding="utf-8")
        self.add_copies()
        self.assertEqual(qc.fx_criteria(self.pkg)[4], ["deliverables_01/a"])

    def test_a_judge_s2_without_a_judge_is_an_ordinary_grader_file(self):
        d = self.pkg / "tests/deliverables_02"
        d.mkdir()
        (d / "judge_s2.toml").write_text(self.CRIT, encoding="utf-8")
        crit, _sums, _groups, _broken, dups = qc.fx_criteria(self.pkg)
        self.assertIn("deliverables_02/a", crit)
        self.assertEqual(dups, [])

    def crit(self, w, text):
        return {"w": w, "text": text, "file": "x"}

    def test_looser_weight_down(self):
        got = qc.fx_looser({"d/a": self.crit(0.2, "Report the total.")}, {"d/a": self.crit(0.1, "Report the total.")})
        self.assertEqual([(g["id"], g["old_w"], g["new_w"]) for g in got], [("d/a", 0.2, 0.1)])
        self.assertIn("weight went down", got[0]["why"])

    def test_looser_text_shorter_by_a_fifth(self):
        old = "The answer states the total revenue for the year and names the region that grew fastest."
        got = qc.fx_looser({"d/a": self.crit(1, old)}, {"d/a": self.crit(1, "The answer states the total revenue for the year.")})
        self.assertEqual(len(got), 1)
        self.assertIn("shorter", got[0]["why"])

    def test_looser_floor_lowered_and_raised(self):
        det = lambda e: json.dumps({"type": "deterministic", "expected": e, "deterministic": {"comparison": "greater_than_equal", "path": "$.n"}})
        got = qc.fx_looser({"a": self.crit(1, det(150)), "b": self.crit(1, det(10))}, {"a": self.crit(1, det(60)), "b": self.crit(1, det(40))})
        self.assertEqual([g["id"] for g in got], ["a"])
        self.assertIn("floor lowered 150 -> 60", got[0]["why"])

    def test_looser_quoted_phrase_removed_and_criterion_removed(self):
        got = qc.fx_looser({"a": self.crit(1, 'Names the "net book value" line as below par in the sheet.'), "b": self.crit(1, "Something else entirely here.")},
                           {"a": self.crit(1, "Names the line as below par in the sheet.")})
        self.assertEqual([g["id"] for g in got], ["a", "b"])
        self.assertIn("required phrase", got[0]["why"])
        self.assertEqual(got[1]["why"], "criterion removed")

    def test_looser_wording_that_accepts_more(self):
        got = qc.fx_looser({"a": self.crit(1, "The answer states a margin of 12 percent for August.")}, {"a": self.crit(1, "The answer states a margin of about 12 percent, or any figure between 11 and 13 percent, for August.")})
        self.assertEqual(len(got), 1)
        self.assertIn("accepts more", got[0]["why"])

    def test_looser_no_change_and_tighter_are_not_listed(self):
        same = {"a": self.crit(0.5, "Report the total revenue for the year.")}
        self.assertEqual(qc.fx_looser(same, dict(same)), [])
        tighter = {"a": self.crit(0.7, "Report the total revenue for the year and the growth rate against the plan for each region.")}
        self.assertEqual(qc.fx_looser(same, tighter), [])

    def test_the_diff_has_a_made_looser_section(self):
        self.script = [self.good]
        rc, out = self.fix()
        text = (self.out() / "fix_diff.md").read_text(encoding="utf-8")
        self.assertIn("## Made looser (read these first)", text)
        self.assertLess(text.index("## Made looser"), text.index("## Weights"))

    def test_a_task_with_sample_copies_is_fixed_not_refused(self):
        self.add_copies()
        self.script = [self.good]
        rc, out = self.fix()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("same name", out)

    def test_accepted_fix_refreshes_the_sample_copies(self):
        self.add_copies()
        self.script = [self.good]
        rc, out = self.fix()
        self.assertEqual(out.strip().splitlines()[-1], "FIX: ACCEPTED BY CHECKER (2 files changed; 2 copies of judge.toml refreshed; 0 criteria made looser)")
        fixed = self.out() / "fixed/tests/deliverables_01"
        new = (fixed / "judge.toml").read_bytes()
        self.assertIn(b"New rule A", new)
        self.assertEqual((fixed / "judge_s2.toml").read_bytes(), new)
        self.assertEqual((fixed / "judge_s3.toml").read_bytes(), new)
        diff = (self.out() / "fix_diff.md").read_text(encoding="utf-8")
        self.assertIn("Files changed: 2 (plus 2 copies of judge.toml).", diff)
        self.assertEqual(diff.count("New text:"), 1)  # the criterion change is listed once, not three times
        self.assertIn("## tests/deliverables_01/judge_s2.toml (copy of judge.toml)", diff)
        self.assertEqual(self.calls[0][1].count("byte copy of it"), 1)  # the fixer is told
        self.assertEqual(len(list(self.pkg.rglob("judge_s2.toml"))), 1)  # the task folder itself was not touched
        self.assertNotIn(b"New rule A", (self.pkg / "tests/deliverables_01/judge_s2.toml").read_bytes())

    def test_a_copy_that_differed_on_purpose_is_left_alone(self):
        self.add_copies()
        s2 = self.pkg / "tests/deliverables_01/judge_s2.toml"
        s2.write_text(s2.read_text(encoding="utf-8").replace("Rule B.", "Rule B, different on purpose."), encoding="utf-8")
        before = s2.read_bytes()
        self.script = [self.good]
        rc, out = self.fix()
        self.assertEqual(rc, 0, out)
        fixed = self.out() / "fixed/tests/deliverables_01"
        self.assertEqual((fixed / "judge_s2.toml").read_bytes(), before)
        self.assertEqual((fixed / "judge_s3.toml").read_bytes(), (fixed / "judge.toml").read_bytes())
        self.assertEqual(out.strip().splitlines()[-1], "FIX: ACCEPTED BY CHECKER (2 files changed; 1 copy of judge.toml refreshed; 0 criteria made looser)")

    def test_printed_result_of_read_opens_the_report(self):
        rep = self.d / "read" / "task_read_report.md"
        rep.parent.mkdir()
        rep.write_text("# Task read report\n## FLAGGED\n### 1. Verified finding\n- Criterion: a\n", encoding="utf-8")
        self.findings.write_text(f"[qc] running: python task_read.py X\nFLAGGED - report: {rep}\n", encoding="utf-8")
        self.script = [self.good]
        rc, out = self.fix()
        self.assertEqual(rc, 0, out)
        text = (self.out() / "fixed/FIX_FINDINGS.md").read_text(encoding="utf-8")
        self.assertIn("### 1. Verified finding", text)
        self.assertNotIn("FLAGGED - report", text)

    def test_printed_result_of_a_several_read_run_uses_the_last_result_line(self):
        rep = self.d / "read_x" / "read2" / "task_read_report.md"
        rep.parent.mkdir(parents=True)
        rep.write_text("# Task read report\n## FLAGGED\n### 1. Verified finding\n- Criterion: a\n", encoding="utf-8")
        other = self.d / "read_x" / "read1" / "task_read_report.md"
        lines = [
            "[qc] read 1 of 3: read_x/read1",
            "[qc] running: python task_read.py X --out read_x/read1",
            f"[qc] read 1 of 3: NOT FLAGGED - report: {other}",
            "[qc] read 2 of 3: read_x/read2",
            "[qc] running: python task_read.py X --out read_x/read2",
            f"[qc] read 2 of 3: FLAGGED - report: {rep}",
            "[qc] read 2 of 3 flagged the task. Any flag counts, so the other reads are not run.",
            f"FLAGGED - report: {rep}",
        ]
        self.findings.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.script = [self.good]
        rc, out = self.fix()
        self.assertEqual(rc, 0, out)
        self.assertIn("### 1. Verified finding", (self.out() / "fixed/FIX_FINDINGS.md").read_text(encoding="utf-8"))

    def test_printed_result_of_a_several_read_run_that_is_all_clean_is_not_run(self):
        rep = self.d / "read_x" / "read1" / "task_read_report.md"
        lines = ["[qc] read 1 of 3: read_x/read1", f"[qc] read 1 of 3: NOT FLAGGED - report: {rep}", "[qc] all 3 reads of the task are clean (that does not prove the task is good).", f"NOT FLAGGED - report: {rep}"]
        self.findings.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rc, out = self.fix()
        self.assertEqual(rc, 2)
        self.assertIn("NOT FLAGGED", out)
        self.assertEqual(self.calls, [])

    def test_printed_result_found_next_to_the_findings_file(self):  # the report was copied along with the findings file, the path inside is another computer's
        (self.d / "task_read_report.md").write_text("# Task read report\n## FLAGGED\n- Criterion: b\n", encoding="utf-8")
        self.findings.write_text("FLAGGED - report: /root/elsewhere/reports/1/read/task_read_report.md\n", encoding="utf-8")
        self.script = [self.good]
        rc, out = self.fix()
        self.assertEqual(rc, 0, out)
        self.assertIn("- Criterion: b", (self.out() / "fixed/FIX_FINDINGS.md").read_text(encoding="utf-8"))

    def test_printed_result_that_says_not_flagged_is_not_run(self):
        self.findings.write_text(f"NOT FLAGGED - report: {self.d / 'r.md'}\n", encoding="utf-8")
        rc, out = self.fix()
        self.assertEqual(rc, 2)
        self.assertIn("FIX: NOT RUN (", out)
        self.assertIn("NOT FLAGGED", out)
        self.assertEqual(self.calls, [])

    def test_printed_result_with_a_missing_report_is_not_run(self):
        self.findings.write_text(f"FLAGGED - report: {self.d / 'gone' / 'task_read_report.md'}\n", encoding="utf-8")
        rc, out = self.fix()
        self.assertEqual(rc, 2)
        self.assertIn("is not at", out)
        self.assertEqual(self.calls, [])

    def test_printed_result_naming_a_file_that_is_not_a_report_is_not_run(self):
        secret = self.d / "notes.txt"
        secret.write_text("private\n", encoding="utf-8")
        self.findings.write_text(f"FLAGGED - report: {secret}\n", encoding="utf-8")
        rc, out = self.fix()
        self.assertEqual(rc, 2)
        self.assertIn("not a .md report", out)
        self.assertEqual(self.calls, [])

    def test_a_long_findings_file_is_never_followed(self):
        body = "Criterion a: an empty answer passes.\n" * 4 + f"FLAGGED - report: {self.d / 'x.md'}\n" + "More text.\n" * 3
        self.findings.write_text(body, encoding="utf-8")
        self.script = [self.good]
        rc, out = self.fix()
        self.assertEqual(rc, 0, out)
        self.assertIn("FLAGGED - report", (self.out() / "fixed/FIX_FINDINGS.md").read_text(encoding="utf-8"))

    def test_rejected_then_accepted_on_the_retry(self):
        self.script = [self.bad, self.good]
        rc, out = self.fix()
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.calls), 2)
        self.assertIn("rejected by the checker", self.calls[1][1])
        self.assertIn("weight total", self.calls[1][1])
        self.assertFalse((self.out() / "rejected_try1").exists())  # an accepted run leaves no rejected first try behind
        self.assertEqual(out.strip().splitlines()[-1], "FIX: ACCEPTED BY CHECKER (2 files changed; 0 criteria made looser)")

    def test_rejected_twice(self):
        self.script = [self.bad, self.bad]
        rc, out = self.fix()
        self.assertEqual(rc, 1, out)
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(out.strip().splitlines()[-1].startswith("FIX: REJECTED (weight total of tests/deliverables_01/judge.toml moved 1 -> 1.3"), out)
        self.assertTrue((self.out() / "fixed").is_dir())  # kept for reading
        self.assertIn("REJECTED", (self.out() / "fix_diff.md").read_text(encoding="utf-8"))

    def test_missing_fix_log_is_a_rejection(self):
        self.script = [lambda cwd: "I looked at the task and thought about it. " * 10] * 2
        rc, out = self.fix()
        self.assertEqual(rc, 1)
        self.assertIn("fix_log.md missing", out)

    def test_usage_limit_is_not_a_rejection(self):
        self.script = ["Claude AI usage limit reached|1760000000"]
        rc, out = self.fix()
        self.assertEqual(rc, 2, out)
        self.assertEqual(len(self.calls), 1)  # no retry
        last = out.strip().splitlines()[-1]
        self.assertTrue(last.startswith("FIX: NOT RUN"), last)
        self.assertNotIn("REJECTED", out)
        self.assertFalse((self.out() / "fix_diff.md").exists())

    def test_limit_words_in_a_finished_fix_are_not_a_limit(self):
        def fixed(cwd):
            self.good(cwd)
            return "I also looked at the rate limit section of the task."

        self.script = [fixed]
        self.assertEqual(self.fix()[0], 0)

    def test_task_folder_unchanged_byte_for_byte(self):
        before = self.hashes()
        for script in ([self.good], [self.bad, self.bad], ["usage limit reached"]):
            self.calls, self.script = [], script
            self.fix()
            self.assertEqual(self.hashes(), before)
        self.assertFalse((self.pkg / "fix_log.md").exists())
        self.assertFalse((self.pkg / "FIX_FINDINGS.md").exists())

    def test_a_fixer_that_writes_into_the_task_folder_is_caught(self):
        def sneaky(cwd):
            self.good(cwd)
            (self.pkg / "instruction.md").write_text("changed behind the back\n")
            return "done"

        self.script = [sneaky]
        rc, out = self.fix()
        self.assertEqual(rc, 2)
        self.assertIn("changed while the fixer ran", out)

    def test_diff_lists_the_changed_criterion_with_old_and_new_text(self):
        self.script = [self.good]
        self.fix()
        diff = (self.out() / "fix_diff.md").read_text(encoding="utf-8")
        self.assertIn("## tests/deliverables_01/judge.toml (changed)", diff)
        self.assertIn("Criterion deliverables_01/a: text changed.", diff)
        self.assertIn("Old text: Old rule A.", diff)
        self.assertIn("New text: New rule A, with the wording the instruction uses.", diff)
        self.assertNotIn("Criterion deliverables_01/b", diff)
        self.assertIn("Old sentence: Keep it short.", diff)
        self.assertIn("New sentence: Keep it under one page.", diff)
        self.assertIn("copy the ones you accept into the task by hand", diff)
        self.assertNotIn(chr(0x2014), diff)

    def test_diff_of_a_long_criterion_shows_the_changed_end(self):
        long_rule = ("Every figure is correct. " * 60).strip()
        j = self.pkg / "tests/deliverables_01/judge.toml"
        j.write_text(j.read_text(encoding="utf-8").replace("Old rule A.", long_rule), encoding="utf-8")

        def append(cwd):
            f = cwd / "tests/deliverables_01/judge.toml"
            f.write_text(f.read_text(encoding="utf-8").replace(long_rule, long_rule + " Also FAIL if the answer is empty."), encoding="utf-8")
            (cwd / "fix_log.md").write_text("x\n", encoding="utf-8")
            return ""

        self.script = [append]
        self.assertEqual(self.fix()[0], 0)
        diff = (self.out() / "fix_diff.md").read_text(encoding="utf-8")
        old_part = diff.split("Old text:")[1].split("New text:")[0]
        new_part = diff.split("New text:")[1]
        self.assertIn("only the part around the change is shown", diff)
        self.assertIn("Also FAIL if the answer is empty.", new_part)
        self.assertNotIn("Also FAIL if the answer is empty.", old_part)

    def test_diff_shows_weight_changes(self):
        def reweigh(cwd):
            j = cwd / "tests/deliverables_01/judge.toml"
            j.write_text(j.read_text(encoding="utf-8").replace("weight = 0.6", "weight = 0.5").replace("weight = 0.4", "weight = 0.5"), encoding="utf-8")
            (cwd / "fix_log.md").write_text("x\n", encoding="utf-8")
            return ""

        self.script = [reweigh]
        self.assertEqual(self.fix()[0], 0)
        diff = (self.out() / "fix_diff.md").read_text(encoding="utf-8")
        self.assertIn("Criterion deliverables_01/a: weight 0.6 -> 0.5.", diff)
        self.assertIn("Criterion deliverables_01/b: weight 0.4 -> 0.5.", diff)

    def test_two_criteria_removed_is_rejected(self):
        def drop(cwd):
            (cwd / "tests/deliverables_01/judge.toml").write_text('[judge]\nweight = 1.0\n\n[[criterion]]\nname = "x"\ndescription = "n"\nweight = 1.0\n', encoding="utf-8")
            (cwd / "fix_log.md").write_text("x\n", encoding="utf-8")
            return ""

        self.script = [drop, drop]
        rc, out = self.fix()
        self.assertEqual(rc, 1)
        self.assertIn("2 criteria removed", out)

    def test_broken_grader_file_is_rejected(self):
        def wreck(cwd):
            (cwd / "tests/deliverables_01/judge.toml").write_text("[[criterion\n", encoding="utf-8")
            (cwd / "fix_log.md").write_text("x\n", encoding="utf-8")
            return ""

        self.script = [wreck, wreck]
        rc, out = self.fix()
        self.assertEqual(rc, 1)
        self.assertIn("is no longer valid", out)

    def test_no_ask_reuses_saved_output(self):
        self.script = [self.good]
        self.assertEqual(self.fix()[0], 0)
        (self.out() / "fix_diff.md").unlink()
        rc, out = self.fix("--no-ask")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.calls), 1)  # no second model call
        self.assertTrue((self.out() / "fix_diff.md").is_file())
        self.assertEqual(out.strip().splitlines()[-1], "FIX: ACCEPTED BY CHECKER (2 files changed; 0 criteria made looser)")

    def test_no_ask_with_nothing_saved_is_a_tool_failure(self):
        rc, out = self.fix("--no-ask")
        self.assertEqual(rc, 2)
        self.assertEqual(self.calls, [])

    def test_no_claude_command_is_a_tool_failure(self):
        with mock.patch.object(qc, "fx_claude", lambda: None):
            rc, out = self.fix()
        self.assertEqual(rc, 2)
        self.assertIn("claude command was not found", out)
        self.assertFalse(self.out().exists())

    def test_no_package_found(self):
        empty = self.d / "empty"
        empty.mkdir()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = qc.main(["--no-update", "fix", str(empty), str(self.findings)])
        self.assertEqual(rc, 2)
        self.assertIn("no task package found", buf.getvalue())

    def test_task_files_layout_and_out_option(self):
        rev = self.d / "rev_1__77"
        shutil.copytree(self.pkg, rev / "task_files")
        self.script = [self.good]
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = qc.main(["--no-update", "fix", str(rev), str(self.findings), "--out", str(self.d / "o")])
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertTrue((self.d / "o" / "fixed" / "instruction.md").is_file())

    def test_out_inside_the_task_folder_is_refused(self):
        rc, out = self.fix("--out", str(self.pkg / "o"))
        self.assertEqual(rc, 2)
        self.assertEqual(self.calls, [])

    def test_runs_the_claude_command_with_the_agreed_tools(self):
        for p in self.patches:
            p.stop()
        self.patches = [mock.patch.object(qc, "fx_claude", lambda: "/fake/claude")]
        self.patches[0].start()
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"], seen["cwd"], seen["input"] = cmd, kw.get("cwd"), kw.get("input")
            self.good(Path(kw["cwd"]))
            return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

        with mock.patch.object(qc.subprocess, "run", fake_run):
            rc, out = self.fix()
        self.assertEqual(rc, 0, out)
        cmd = seen["cmd"]
        self.assertEqual(cmd[:4], ["/fake/claude", "-p", "--model", "sonnet"])
        self.assertEqual(cmd[cmd.index("--tools") + 1], "Read,Glob,Grep,Write,Edit")  # exactly these tools, no shell
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "user")  # package settings and hooks are not read
        self.assertNotIn("--allowedTools", cmd)  # a bare allowed tool name would let the AI write on every path
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "acceptEdits")
        self.assertEqual(seen["input"], qc.FIX_PROMPT)  # the long prompt goes on stdin, not in the argument list
        self.assertTrue(all(len(c) < 100 for c in cmd))
        self.assertEqual(Path(seen["cwd"]).resolve(), (self.out() / "fixed").resolve())

    # ---- the audit's fixes (FIXCMD2) ----

    def noop(self, reply="x"):
        def f(cwd):
            return reply
        return f

    def test_settings_files_are_deleted_from_the_copy_before_the_call(self):
        for rel in ("CLAUDE.md", ".mcp.json", ".claude/settings.json", "environment/sub/claude.md", "environment/.claude/x.json"):
            (self.pkg / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.pkg / rel).write_text("{}", encoding="utf-8")
        seen = {}

        def look(cwd):
            seen["left"] = sorted(p.relative_to(cwd).as_posix() for p in cwd.rglob("*") if p.name.lower() in qc.FIX_STRIP)
            return self.good(cwd)

        self.script = [look]
        rc, out = self.fix()
        self.assertEqual(rc, 0, out)
        self.assertEqual(seen["left"], [])
        self.assertTrue((self.pkg / ".claude/settings.json").is_file())  # the original keeps them
        diff = (self.out() / "fix_diff.md").read_text(encoding="utf-8")
        self.assertIn("Settings files removed from the copy", diff)
        self.assertIn("Files changed: 2.", diff)  # the deleted settings files are not counted as the AI's changes

    def test_a_symbolic_link_in_the_package_stops_the_run(self):
        (self.d / "outside.txt").write_text("keep", encoding="utf-8")
        (self.d / "outdir").mkdir()
        for kind, target in (("file", self.d / "outside.txt"), ("folder", self.d / "outdir")):
            link = self.pkg / "environment" / f"link_{kind}"
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                self.skipTest("no symbolic links here")
            self.calls, self.script = [], [self.good]
            rc, out = self.fix()
            self.assertEqual(rc, 2, kind)
            self.assertIn("symbolic link", out)
            self.assertEqual(self.calls, [])
            link.unlink()

    def test_a_change_beside_the_package_inside_the_task_folder_is_caught_and_named(self):
        rev = self.d / "rev_1__77"
        shutil.copytree(self.pkg, rev / "task_files")
        (rev / "notes.txt").write_text("keep", encoding="utf-8")

        def sneaky(cwd):
            self.good(cwd)
            (rev / "notes.txt").write_text("changed", encoding="utf-8")
            return "done"

        self.script = [sneaky]
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = qc.main(["--no-update", "fix", str(rev), str(self.findings), "--out", str(self.d / "o")])
        self.assertEqual(rc, 2)
        self.assertIn("changed while the fixer ran", buf.getvalue())
        self.assertIn("notes.txt", buf.getvalue())

    def test_default_output_folder_inside_the_task_folder_is_not_counted_as_a_change(self):
        rev = self.d / "rev_1__77"
        shutil.copytree(self.pkg, rev / "task_files")
        self.script = [self.good]
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = qc.main(["--no-update", "fix", str(rev), str(self.findings)])
        self.assertEqual(rc, 0, buf.getvalue())

    def test_a_change_to_the_findings_file_is_caught(self):
        def sneaky(cwd):
            self.good(cwd)
            self.findings.write_text("rewritten", encoding="utf-8")
            return "done"

        self.script = [sneaky]
        rc, out = self.fix()
        self.assertEqual(rc, 2)
        self.assertIn("findings file", out)

    def test_an_old_fix_log_in_the_package_does_not_count_as_the_fixers_log(self):
        (self.pkg / "fix_log.md").write_text("an old log from somebody else\n", encoding="utf-8")
        (self.pkg / "FIX_FINDINGS.md").write_text("old findings\n", encoding="utf-8")
        seen = {}

        def idle(cwd):
            seen["log"], seen["findings"] = (cwd / "fix_log.md").exists(), (cwd / "FIX_FINDINGS.md").read_text(encoding="utf-8")
            return "Claude AI usage limit reached|1760000000"

        self.script = [idle]
        rc, out = self.fix()
        self.assertFalse(seen["log"])
        self.assertIn("Problems found in this task", seen["findings"])
        self.assertEqual(rc, 2, out)
        self.assertTrue(out.strip().splitlines()[-1].startswith("FIX: NOT RUN"), out)

    def test_a_changed_file_named_fix_log_deeper_in_the_tree_shows_in_the_diff(self):
        (self.pkg / "environment" / "fix_log.md").write_text("old\n", encoding="utf-8")

        def edit(cwd):
            self.good(cwd)
            (cwd / "environment" / "fix_log.md").write_text("new\n", encoding="utf-8")
            return ""

        self.script = [edit]
        self.assertEqual(self.fix()[0], 0)
        self.assertIn("## environment/fix_log.md (changed)", (self.out() / "fix_diff.md").read_text(encoding="utf-8"))

    def test_a_change_far_into_a_long_instruction_sentence_is_shown(self):
        long_s = "Write the memo and " + "include every figure from the data " * 40 + "and stop."
        (self.pkg / "instruction.md").write_text(long_s + "\n", encoding="utf-8")

        def edit(cwd):
            self.good(cwd)
            (cwd / "instruction.md").write_text(long_s.replace("and stop.", "and name the regional lead, then stop.") + "\n", encoding="utf-8")
            return ""

        self.script = [edit]
        self.assertEqual(self.fix()[0], 0)
        diff = (self.out() / "fix_diff.md").read_text(encoding="utf-8")
        old_part = diff.split("Old sentence:")[1].split("New sentence:")[0]
        new_part = diff.split("New sentence:")[1]
        self.assertIn("name the regional lead", new_part)
        self.assertNotIn("name the regional lead", old_part)
        self.assertIn("only the part around the change", diff)

    def test_more_usage_limit_wordings_are_not_a_rejection(self):
        for text in ("You've hit your weekly limit", "You've reached your weekly limit", "API Error: 429 Too Many Requests",
                     '{"type":"rate_limit_error"}', "529 overloaded_error", "Credit balance is too low", "5-hour limit reached ∙ resets 2am"):
            self.calls, self.script = [], [text]
            rc, out = self.fix()
            self.assertEqual(rc, 2, text)
            self.assertEqual(len(self.calls), 1, text)
            self.assertIn("usage limit", out, text)

    def test_exit_zero_with_no_fix_log_and_a_short_reply_is_not_run(self):
        self.script = ["ok"]
        rc, out = self.fix()
        self.assertEqual(rc, 2, out)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(out.strip().splitlines()[-1].startswith("FIX: NOT RUN"), out)
        self.assertNotIn("REJECTED", out)

    def test_a_grader_file_with_a_byte_order_mark_is_read(self):
        j = self.pkg / "tests/deliverables_01/judge.toml"
        j.write_bytes(b"\xef\xbb\xbf" + self.CRIT.encode("utf-8"))
        crit, sums, _, broken, _ = qc.fx_criteria(self.pkg)
        self.assertEqual((broken, len(crit)), ([], 2))
        self.script = [self.good]
        self.assertEqual(self.fix()[0], 0)

    def test_a_grader_file_that_does_not_parse_before_the_fix_stops_the_run(self):
        (self.pkg / "tests/deliverables_01/judge.toml").write_text("[[criterion\n", encoding="utf-8")
        self.script = [self.good]
        rc, out = self.fix()
        self.assertEqual(rc, 2)
        self.assertIn("does not parse", out)
        self.assertIn("deliverables_01/judge.toml", out)
        self.assertEqual(self.calls, [])

    def test_duplicate_criterion_names_stop_the_run_with_a_plain_message(self):
        j = self.pkg / "tests/deliverables_01/judge.toml"
        j.write_text(j.read_text(encoding="utf-8").replace('name = "b"', 'name = "a"'), encoding="utf-8")
        rc, out = self.fix()
        self.assertEqual(rc, 2)
        self.assertIn("same name", out)
        self.assertEqual(self.calls, [])

    def test_a_utf16_findings_file_is_decoded(self):
        self.findings.write_bytes("Criterion a demands more than asked.\n".encode("utf-16"))
        self.script = [self.good]
        rc, out = self.fix()
        self.assertEqual(rc, 0, out)
        self.assertIn("Criterion a demands more than asked.", (self.out() / "fixed/FIX_FINDINGS.md").read_text(encoding="utf-8"))

    def test_findings_with_nul_bytes_and_no_mark_stop_the_run(self):
        self.findings.write_bytes("Criterion a is wrong\n".encode("utf-16-le"))
        rc, out = self.fix()
        self.assertEqual(rc, 2)
        self.assertIn("UTF-8", out)
        self.assertEqual(self.calls, [])

    def test_a_path_that_cannot_be_copied_gives_a_plain_message(self):
        def boom(*a, **k):
            raise OSError(206, "The filename or extension is too long")

        with mock.patch.object(qc.shutil, "copytree", boom):
            rc, out = self.fix()
        self.assertEqual(rc, 2)
        self.assertIn("could not copy the task", out)
        self.assertIn("--out", out)
        self.assertEqual(self.calls, [])

    def test_the_prompt_forbids_writing_the_answer_into_the_instruction(self):
        self.assertIn("Do not write the expected conclusion, number or verdict that a grader checks into the instruction", qc.FIX_PROMPT)

    LEAK_RUBRIC = '[judge]\nweight = 1.0\n\n[[criterion]]\nname = "a"\ndescription = "The memo states Churn Risk Band 7 and a total of $48,250 or 12.5%."\ntype = "binary"\nweight = 1.0\n'

    def edit_instruction(self, sentence):
        def f(cwd):
            self.good(cwd)
            (cwd / "instruction.md").write_text("Write the memo. Use the Q3 figures. " + sentence + "\n", encoding="utf-8")
            return ""
        return f

    def test_a_sentence_that_writes_the_graders_answer_is_flagged(self):
        (self.pkg / "tests/deliverables_01/judge.toml").write_text(self.LEAK_RUBRIC, encoding="utf-8")
        self.script = [self.edit_instruction("State that the total is $48,250 and that the account is in the Churn Risk Band.")]
        self.assertEqual(self.fix()[0], 0)
        diff = (self.out() / "fix_diff.md").read_text(encoding="utf-8")
        self.assertIn("Possible answer leaks flagged: 1", diff)
        line = [x for x in diff.splitlines() if "POSSIBLE ANSWER LEAK:" in x]
        self.assertEqual(len(line), 1)
        self.assertIn("$48,250", line[0])
        self.assertIn('"Churn Risk Band"', line[0])
        self.assertLess(diff.index("Possible answer leaks flagged"), diff.index("New sentence"))

    def test_a_requirement_only_sentence_is_not_flagged(self):
        (self.pkg / "tests/deliverables_01/judge.toml").write_text(self.LEAK_RUBRIC, encoding="utf-8")
        self.script = [self.edit_instruction("Give the total as one dollar figure and name the risk band in a sentence.")]
        self.assertEqual(self.fix()[0], 0)
        diff = (self.out() / "fix_diff.md").read_text(encoding="utf-8")
        self.assertIn("Possible answer leaks flagged: 0", diff)
        self.assertNotIn("POSSIBLE ANSWER LEAK", diff)

    def test_a_number_already_in_the_old_instruction_is_not_flagged(self):
        (self.pkg / "tests/deliverables_01/judge.toml").write_text(self.LEAK_RUBRIC, encoding="utf-8")
        (self.pkg / "instruction.md").write_text("Write the memo. Use the Q3 figures. The cap is 12.5% of revenue.\n", encoding="utf-8")
        self.script = [self.edit_instruction("Show the cap of 12.5% as a column.")]
        self.assertEqual(self.fix()[0], 0)
        self.assertIn("Possible answer leaks flagged: 0", (self.out() / "fix_diff.md").read_text(encoding="utf-8"))

    def test_a_leak_is_found_from_the_golden_answer_files_too(self):
        (self.pkg / "solution/answer.txt").write_text("Regional Lead: Dana Whitfield, 4,210 units\n", encoding="utf-8")
        self.script = [self.edit_instruction("Name Dana Whitfield and report 4,210 units.")]
        self.assertEqual(self.fix()[0], 0)
        diff = (self.out() / "fix_diff.md").read_text(encoding="utf-8")
        self.assertIn("Possible answer leaks flagged: 1", diff)
        self.assertIn("4,210", diff)
        self.assertIn('"Dana Whitfield"', diff)

    def test_quota_in_an_ordinary_reply_is_not_a_usage_limit(self):
        self.script = ["I read the sales quota attainment criterion and it is fine as written. " * 6] * 2
        rc, out = self.fix()
        self.assertEqual(rc, 1, out)  # the fixer forgot its log: a rejection, as for any fixer that forgot its log
        self.assertNotIn("usage limit", out)
        self.assertIn("fix_log.md missing", out)

    def test_a_limit_message_with_a_nonzero_exit_is_a_limit_even_after_a_log(self):
        def ask(cwd, prompt):
            self.calls.append((Path(cwd), prompt))
            self.good(Path(cwd))
            return 1, "Claude AI usage limit reached|1760000000"

        with mock.patch.object(qc, "fx_ask", ask):
            rc, out = self.fix()
        self.assertEqual(rc, 2, out)
        self.assertIn("usage limit", out.strip().splitlines()[-1])
        self.assertEqual(len(self.calls), 1)

    def test_a_nonzero_exit_is_not_accepted_even_when_a_log_was_written(self):
        def ask(cwd, prompt):
            self.calls.append((Path(cwd), prompt))
            self.good(Path(cwd))
            return 1, "Segmentation fault"

        with mock.patch.object(qc, "fx_ask", ask):
            rc, out = self.fix()
        self.assertEqual(rc, 2, out)
        last = out.strip().splitlines()[-1]
        self.assertTrue(last.startswith("FIX: NOT RUN (the claude command failed (exit 1)"), last)
        self.assertNotIn("ACCEPTED", out)
        self.assertEqual(len(self.calls), 1)
        self.assertFalse((self.out() / "fix_diff.md").exists())

    def test_a_rerun_into_the_fixed_copy_cannot_delete_the_task_it_names(self):
        self.script = [self.good]
        self.assertEqual(self.fix()[0], 0)
        fixed = self.out() / "fixed"
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = qc.main(["--no-update", "fix", str(fixed), str(self.findings), "--out", str(self.out())])
        self.assertEqual(rc, 2, buf.getvalue())
        self.assertIn("would overwrite the task folder", buf.getvalue())
        self.assertTrue((fixed / "instruction.md").is_file())  # the folder named as the task is still there
        self.assertEqual(len(self.calls), 1)  # no second AI call

    def test_an_empty_folder_added_to_the_task_folder_stops_the_run(self):
        def stray(cwd):
            self.good(cwd)
            (self.pkg / "stray_empty_folder").mkdir()
            return "done"

        self.script = [stray]
        rc, out = self.fix()
        self.assertEqual(rc, 2, out)
        self.assertIn("stray_empty_folder", out)
        self.assertIn("changed while the fixer ran", out)

    @unittest.skipIf(os.name == "nt", "permission bits mean little on Windows")
    def test_a_permission_change_in_the_task_folder_stops_the_run(self):
        def chmod(cwd):
            self.good(cwd)
            os.chmod(self.pkg / "instruction.md", 0o755)
            return "done"

        self.script = [chmod]
        rc, out = self.fix()
        self.assertEqual(rc, 2, out)
        self.assertIn("instruction.md", out)

    def test_a_fixer_that_changed_nothing_is_not_called_accepted(self):
        def nothing(cwd):
            (cwd / "fix_log.md").write_text("a: no change, the criterion is fine.\nFILES CHANGED: none\n", encoding="utf-8")
            return "done"

        self.script = [nothing]
        rc, out = self.fix()
        self.assertEqual(rc, 0, out)
        last = out.strip().splitlines()[-1]
        self.assertTrue(last.startswith("FIX: NO CHANGE MADE"), last)
        self.assertNotIn("ACCEPTED", out)
        self.assertIn("The fixer changed no file", (self.out() / "fix_diff.md").read_text(encoding="utf-8"))

    def test_findings_saved_in_the_windows_ansi_code_page_are_read(self):
        self.findings.write_bytes("Criterion a says \u201cquoted\u201d text.\n".encode("cp1252"))
        self.script = [self.good]
        rc, out = self.fix()
        self.assertEqual(rc, 0, out)
        self.assertIn("\u201cquoted\u201d", (self.out() / "fixed/FIX_FINDINGS.md").read_text(encoding="utf-8"))

    SHARED_RUBRIC = '[judge]\nweight = 1.0\n\n[[criterion]]\nname = "a"\ndescription = "PASS if the memo concludes that net revenue retention fell below the plan."\ntype = "binary"\nweight = 1.0\n'

    def test_wording_shared_with_a_grader_is_shown_when_no_number_or_name_matches(self):
        (self.pkg / "tests/deliverables_01/judge.toml").write_text(self.SHARED_RUBRIC, encoding="utf-8")
        self.script = [self.edit_instruction("Conclude that net revenue retention fell below the plan.")]
        self.assertEqual(self.fix()[0], 0)
        diff = (self.out() / "fix_diff.md").read_text(encoding="utf-8")
        self.assertIn("Possible answer leaks flagged: 1", diff)
        self.assertIn("SHARED WORDING WITH A GRADER", diff)
        self.assertNotIn("POSSIBLE ANSWER LEAK:", diff)


class FixLeakMatchTests(unittest.TestCase):
    """The match behind the answer-leak flag: number formats, case and quotes do not hide a match; shared wording is found."""

    G = 'PASS if the total is 1,234, growth is 12%, the term is "Net Book Value" and the memo concludes that net revenue retention fell below the plan.'

    def test_thousands_percent_case_and_curly_quotes_do_not_hide_a_match(self):
        self.assertEqual(qc.fx_leaks("State that the total is 1234.", "", self.G), ["1234"])
        self.assertEqual(qc.fx_leaks("State that growth is 12 percent.", "", self.G), ["12 percent"])
        self.assertEqual(qc.fx_leaks('Cite "net book value" as below par.', "", self.G), ['"net book value"'])
        self.assertEqual(qc.fx_leaks("Say that \u201cnet book value\u201d is low.", "", self.G), ['"net book value"'])

    def test_a_number_the_instruction_already_gave_in_another_format_is_not_flagged(self):
        self.assertEqual(qc.fx_leaks("Show a total of 1234.", "The ledger lists 1,234.", self.G), [])

    def test_shared_wording_finds_a_conclusion_in_plain_words(self):
        run = qc.fx_shared("Conclude that net revenue retention fell below the plan.", "", self.G)
        self.assertEqual(len(run.split()), qc.FIX_SHARED_RUN)

    def test_shared_wording_ignores_wording_the_instruction_already_had(self):
        s = "Conclude that net revenue retention fell below the plan."
        self.assertEqual(qc.fx_shared(s, s, self.G), "")

    def test_shared_wording_is_off_at_zero(self):
        with mock.patch.object(qc, "FIX_SHARED_RUN", 0):
            self.assertEqual(qc.fx_shared("Conclude that net revenue retention fell below the plan.", "", self.G), "")

    def test_a_short_shared_phrase_is_not_shown(self):
        self.assertEqual(qc.fx_shared("State the net revenue retention.", "", self.G), "")

SIB_INSTRUCTION = "Write a memo that sorts the findings into act-now and confirm-first items, with an owner for each."
SIB_VERIFIER = {"verifiers": [
    {"name": f"t{i}", "metadata": {"weight": w}, "assertion": {"type": "rubric", "rubric": {"prompt": f"Pass if the memo handles item {i}. " + "x" * 600}}}
    for i, w in enumerate([0.4, 0.3, 0.2, 0.1], 1)
]}
SIB_PROBLEMS = (
    "P1. The test t1 passes any memo that lists owners. It also affects t2 here.\nWeight 0.4.\n\n"
    "P2. Test `t3` accepts a blank answer; the suggested change is to match t1 exactly.\n"
)


class SiblingTests(unittest.TestCase):
    """The sibling reader, with a stand-in for the model: no network and no claude command."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        (self.d / "task" / "tests").mkdir(parents=True)
        (self.d / "task" / "instruction.md").write_text(SIB_INSTRUCTION, encoding="utf-8")
        (self.d / "task" / "tests" / "verifier.json").write_text(json.dumps(SIB_VERIFIER), encoding="utf-8")
        self.problems = self.d / "problems.md"
        self.problems.write_text(SIB_PROBLEMS, encoding="utf-8")
        self.stdins = []
        self.reply = '{"siblings": [{"id": "t4", "reason": "same gap"}, {"id": "t1", "reason": "named already"}, {"id": "nope", "reason": "x"}]}'
        patch = mock.patch.object(qc, "sib_model", self.model)
        patch.start()
        self.addCleanup(patch.stop)

    def model(self, prompt, stdin):
        self.stdins.append(stdin)
        return self.reply

    def go(self, *extra):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = qc.main(["--no-update", "siblings", str(self.d / "task"), str(self.problems), *extra])
        return rc, buf.getvalue()

    def pkg_tests(self):
        return qc.sib_tests(self.d / "task")[1]

    def test_ids_a_problem_block_names(self):
        ids = [t[0] for t in self.pkg_tests()]
        blocks = dict(qc.sib_blocks(SIB_PROBLEMS))
        self.assertEqual(list(blocks), ["P1", "P2"])
        self.assertEqual(qc.sib_named(blocks["P1"], ids), ["t1", "t2"])
        self.assertEqual(qc.sib_named(blocks["P2"], ids), ["t3", "t1"])
        self.assertEqual(qc.sib_named("the test t10 and xt1 and t1x", ids), [])  # whole tokens only
        self.assertEqual(qc.sib_named("an owner is needed", ["owner"]), [])  # a plain word counts only when marked as an id
        self.assertEqual(qc.sib_named("the criterion owner is vague, `owner`", ["owner"]), ["owner"])

    def test_other_named_ids_become_the_placeholder(self):
        text = qc.sib_blocks(SIB_PROBLEMS)[0][1]
        out = qc.sib_redact(text, ["t2"])
        self.assertIn("t1", out)
        self.assertNotIn("t2", out)
        self.assertIn("[another test]", out)
        self.go()
        first = self.stdins[0]  # the call for t1 in P1: t2, t3 hidden, t1 kept
        self.assertIn("CRITERION A: [t1]", first)
        reviewer = first.split("THE REVIEWER'S WORDS ABOUT THE DEFECT IN A:\n")[1]
        self.assertNotIn("t2", reviewer)
        self.assertIn("[another test]", reviewer)

    def test_input_follows_the_measured_layout(self):
        ins, tests = qc.sib_tests(self.d / "task")
        stdin = qc.sib_stdin(ins * 2000, tests, "t1", "words")
        self.assertTrue(stdin.startswith("TASK INSTRUCTION:\n"))
        self.assertIn("CRITERIA OF THE TASK (4):\n[t1] weight 0.4000: Pass if", stdin)
        self.assertEqual(max(len(ln) for ln in stdin.splitlines() if ln.startswith("[t2]")), len("[t2] weight 0.3000: ") + 400)
        self.assertEqual(len(stdin.split("\n\nCRITERIA OF THE TASK")[0]), len("TASK INSTRUCTION:\n") + 12000)

    def test_a_test_already_named_is_dropped(self):
        rc, out = self.go()
        self.assertEqual(rc, 0)
        md = (self.d / "siblings.md").read_text(encoding="utf-8")
        self.assertIn(qc.SIB_HEADING, md)
        self.assertIn("- `t4`", md)
        self.assertNotIn("- `t1`", md)  # named in problems.md already
        self.assertNotIn("nope", md)    # not a test of the task
        self.assertEqual(md.count("- `t4`"), 2)

    def test_parsing_a_good_a_malformed_and_an_empty_answer(self):
        valid = {"t1", "t2", "t3", "t4"}
        good = qc.sib_parse('Sure:\n{"siblings": [{"id": "[t2]", "reason": "  a   b "}, {"id": "t2", "reason": "dup"}, {"id": "t1", "reason": "A itself"}]}', valid, "t1")
        self.assertEqual(good, [{"id": "t2", "reason": "a b"}])
        self.assertEqual(len(qc.sib_parse(json.dumps({"siblings": [{"id": i, "reason": ""} for i in sorted(valid)]}), valid, "t9")), 3)
        self.assertIsNone(qc.sib_parse('{"siblings": [{"id": "t2"', valid, "t1"))
        self.assertIsNone(qc.sib_parse('{"siblings": "t2"}', valid, "t1"))
        self.assertIsNone(qc.sib_parse("", valid, "t1"))
        self.assertEqual(qc.sib_parse('{"siblings": []}', valid, "t1"), [])  # none named is an answer

    def test_a_rerun_reads_the_cache_and_asks_nothing(self):
        self.go()
        calls = len(self.stdins)
        self.assertEqual(calls, 4)  # t1, t2 (P1), t3, t1 (P2): four different inputs
        first = (self.d / "siblings.md").read_text(encoding="utf-8")
        (self.d / "siblings.md").unlink()
        rc, out = self.go()
        self.assertEqual((rc, len(self.stdins)), (0, calls))
        self.assertEqual((self.d / "siblings.md").read_text(encoding="utf-8"), first)
        self.assertIn("0 asked now, 4 from the saved file", out)

    def test_no_ask_uses_saved_answers_only(self):
        rc, out = self.go("--no-ask")
        self.assertEqual((rc, self.stdins), (0, []))
        self.assertIn("4 answers not saved yet", out)
        self.assertIn("No answer saved yet", (self.d / "siblings.md").read_text(encoding="utf-8"))

    def test_a_retry_after_a_malformed_reply_and_a_clear_stop_when_both_fail(self):
        replies = iter(["not json", self.reply] + [self.reply] * 10)
        with mock.patch.object(qc, "sib_model", lambda p, s: next(replies)):
            self.assertEqual(self.go()[0], 0)
        (self.d / qc.SIB_CACHE).unlink()
        with mock.patch.object(qc, "sib_model", lambda p, s: "nothing useful"):
            rc, out = self.go()
        self.assertEqual(rc, 2)
        self.assertIn("siblings: stopped.", out)
        self.assertNotIn("Traceback", out)
        with mock.patch.object(qc, "sib_model", side_effect=qc.SibStop("the claude command was not found")):
            rc, out = self.go()
        self.assertEqual((rc, out.count("\n")), (2, 2))  # one line to say it asks, one to say it stopped

    def test_console_summary(self):
        rc, out = self.go()
        self.assertEqual(rc, 0)
        self.assertIn("[qc] siblings: 4 reader answers needed, 4 asked now, 0 from the saved file.", out)
        self.assertIn("siblings: 2 problem blocks, 2 tests suggested in all", out)
        self.assertIn("siblings: P1: named t1, t2; suggested t4", out)
        self.assertIn("siblings: P2: named t3, t1; suggested t4", out)

    def test_parser_and_help_know_the_command(self):
        a = qc.build_parser().parse_args(["siblings", "task", "p.md", "--no-ask"])
        self.assertEqual((a.cmd, a.no_ask), ("siblings", True))
        self.assertIn("python qc.py siblings", qc.__doc__)

    def answer_rows(self):
        text = (self.d / qc.SIB_ANS).read_bytes().decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text, newline="")))

    def write_answers(self, rows):
        with open(self.d / qc.SIB_ANS, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=qc.SIB_COLS)
            w.writeheader()
            w.writerows(rows)

    def test_the_answers_file_has_one_row_per_suggested_test(self):
        rc, out = self.go()
        self.assertEqual(rc, 0)
        rows = self.answer_rows()
        self.assertEqual([(r["problem"], r["test_id"]) for r in rows], [("P1", "t4"), ("P2", "t4")])
        self.assertEqual({(r["answer"], r["note"]) for r in rows}, {("", "")})
        self.assertIn(qc.SIB_ANS, out)
        self.assertIn("--check", out)

    def test_check_holds_until_every_row_has_an_answer_and_a_note(self):
        self.go()
        calls = len(self.stdins)
        rc, out = self.go("--check")
        self.assertEqual(rc, 1)
        self.assertIn("SIBLINGS: HOLD (2 open)", out)
        self.assertEqual(len(self.stdins), calls)  # --check makes no AI call
        rows = self.answer_rows()
        rows[0].update(answer="yes", note="changed the test to match the instruction")
        rows[1].update(answer="maybe", note="not sure about this one")
        self.write_answers(rows)
        rc, out = self.go("--check")
        self.assertEqual(rc, 1)
        self.assertIn("SIBLINGS: HOLD (1 open)", out)
        self.assertIn("answer must be yes or no: P2 t4", out)
        rows[1].update(answer="No", note="read it and the test is fair")
        self.write_answers(rows)
        rc, out = self.go("--check")
        self.assertEqual(rc, 0)
        self.assertTrue(out.rstrip().endswith("SIBLINGS: COMPLETE"))

    def test_a_short_note_keeps_the_row_open(self):
        self.go()
        rows = self.answer_rows()
        for r in rows:
            r.update(answer="no", note="fine")
        self.write_answers(rows)
        rc, out = self.go("--check")
        self.assertEqual(rc, 1)
        self.assertIn("SIBLINGS: HOLD (2 open)", out)
        self.assertIn("note needs 4 words or more", out)

    def test_check_holds_when_the_reader_has_not_run(self):
        rc, out = self.go("--check")
        self.assertEqual((rc, self.stdins), (1, []))
        self.assertIn("the reader has not run on 4 named tests", out)
        self.assertIn("SIBLINGS: HOLD (1 open)", out)
        self.assertFalse((self.d / qc.SIB_ANS).exists())

    def test_check_holds_when_the_problems_name_no_test(self):
        self.problems.write_text("P1. The prompt is vague about the format.\n", encoding="utf-8")
        rc, out = self.go("--check")
        self.assertEqual(rc, 1)
        self.assertIn("names no test id", out)
        self.assertIn("SIBLINGS: HOLD", out)

    def test_check_is_complete_when_the_reader_names_nothing(self):
        self.reply = '{"siblings": []}'
        self.go()
        self.assertEqual(self.answer_rows(), [])
        rc, out = self.go("--check")
        self.assertEqual(rc, 0)
        self.assertTrue(out.rstrip().endswith("SIBLINGS: COMPLETE"))

    def test_a_rerun_keeps_the_answers_already_written(self):
        self.go()
        rows = self.answer_rows()
        rows[0].update(answer="yes", note="changed the test to match the instruction")
        self.write_answers(rows)
        self.go()
        kept = self.answer_rows()
        self.assertEqual((kept[0]["answer"], kept[0]["note"]), ("yes", "changed the test to match the instruction"))
        self.assertEqual(kept[1]["answer"], "")

    def test_a_written_answer_survives_when_its_problem_is_edited_out(self):
        self.go()
        rows = self.answer_rows()
        rows[1].update(answer="no", note="read it and the test is fair")
        self.write_answers(rows)
        self.problems.write_text(SIB_PROBLEMS.split("\n\nP2.")[0] + "\n", encoding="utf-8")
        self.go()
        got = {(r["problem"], r["test_id"]): r for r in self.answer_rows()}
        self.assertIn(("P1", "t4"), got)
        self.assertEqual(got[("P2", "t4")]["answer"], "no")
        self.assertTrue(got[("P2", "t4")]["reason"].startswith("(no longer suggested)"))
        self.go()  # a second rerun must not stack the prefix
        again = {(r["problem"], r["test_id"]): r for r in self.answer_rows()}
        self.assertEqual(again[("P2", "t4")]["reason"].count("(no longer suggested)"), 1)

    def test_an_unreadable_answers_file_stops_without_overwriting_it(self):
        self.go()
        (self.d / qc.SIB_ANS).write_bytes(b"\xff\xfe\x00bad")
        before = (self.d / qc.SIB_ANS).read_bytes()
        rc, out = self.go()
        self.assertEqual(rc, 2)
        self.assertIn("siblings: stopped.", out)
        self.assertEqual((self.d / qc.SIB_ANS).read_bytes(), before)

    def test_check_flag_is_in_the_parser(self):
        a = qc.build_parser().parse_args(["siblings", "task", "p.md", "--check"])
        self.assertTrue(a.check)
        self.assertFalse(qc.build_parser().parse_args(["siblings", "task", "p.md"]).check)

    def test_toml_layout_weights_are_shares_of_the_task(self):
        pkg = self.d / "toml"
        (pkg / "tests" / "g1").mkdir(parents=True)
        (pkg / "tests" / "g2").mkdir()
        (pkg / "instruction.md").write_text("x", encoding="utf-8")
        (pkg / "tests" / "g1" / "judge.toml").write_text('[judge]\nweight = 0.75\n[[criterion]]\nname = "a"\ndescription = "da"\nweight = 1\n[[criterion]]\nname = "b"\ndescription = "db"\nweight = 3\n', encoding="utf-8")
        (pkg / "tests" / "g2" / "judge.toml").write_text('[judge]\nweight = 0.25\n[[criterion]]\nname = "c"\ndescription = "dc"\n', encoding="utf-8")
        got = qc.sib_tests(pkg)[1]
        self.assertEqual([(i, round(w, 4)) for i, w, _ in got], [("a", 0.1875), ("b", 0.5625), ("c", 0.25)])


class SmallFixTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        (self.d / "tasks").mkdir()

    def run_checks(self, runner_body, out=None):
        fake = self.d / "fake_runner.py"
        fake.write_text(runner_body, encoding="utf-8")
        a = qc.build_parser().parse_args(["--no-update", "checks", str(self.d / "tasks"), str(self.d / "stage"), str(out or self.d / "out")])
        buf, err = io.StringIO(), io.StringIO()
        with mock.patch.object(qc, "RUNNER", fake), redirect_stdout(buf), mock.patch("sys.stderr", err):
            rc = qc.cmd_checks(a)
        return rc, buf.getvalue()

    def test_checks_prints_no_table_line_when_no_table_was_written(self):
        rc, out = self.run_checks("import sys\nprint('shared-check target does not exist: x', file=sys.stderr)\nsys.exit(2)\n")
        self.assertEqual(rc, 2)
        self.assertNotIn("table:", out)
        self.assertIn("checks stopped: no table was written.", out)
        self.assertIn("does not exist", out)

    def test_checks_prints_table_line_when_the_table_exists(self):
        body = "import sys, pathlib\no = sys.argv[sys.argv.index('--out-dir') + 1]\npathlib.Path(o, 'summary.csv').write_text('a')\n"
        rc, out = self.run_checks(body)
        self.assertEqual(rc, 0)
        self.assertIn("table: ", out)

    def test_checks_permission_error_is_one_plain_line(self):
        with mock.patch.object(Path, "mkdir", side_effect=PermissionError(13, "Permission denied")):
            rc, out = self.run_checks("raise SystemExit(0)\n")
        self.assertEqual(rc, 2)
        self.assertIn("checks stopped: cannot write to", out)
        self.assertNotIn("Traceback", out)

    def load_svc_runner(self):
        import importlib.util
        path = HERE / "deterministic-checks" / "svc_run_checks.py"
        spec = importlib.util.spec_from_file_location("svc_run_checks_t", path)
        m = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(path.parent))
        spec.loader.exec_module(m)
        return m

    def run_svc(self, patch_csv):
        (self.d / "tasks" / "T1").mkdir()
        (self.d / "tasks" / "T1" / "instruction.md").write_text("hi", encoding="utf-8")
        m = self.load_svc_runner()
        err = io.StringIO()
        old = os.getcwd()
        os.chdir(self.d)
        try:
            with mock.patch("sys.argv", ["x", "--all", "--root", "tasks", "--out-dir", "out", "--checks", "formula_health"]), mock.patch("sys.stderr", err):
                if patch_csv:
                    with mock.patch.object(m, "write_csv", lambda *a, **k: None):
                        m.main()
                else:
                    m.main()
        finally:
            os.chdir(old)
        return err.getvalue()

    def test_svc_run_checks_prints_absolute_summary_path(self):
        text = self.run_svc(False)
        line = [x for x in text.splitlines() if "-> " in x and "summary.csv" in x][0]
        self.assertTrue(Path(line.split("-> ", 1)[1]).is_absolute(), line)

    def test_svc_run_checks_prints_summary_line_only_when_csv_exists(self):
        text = self.run_svc(True)
        self.assertNotIn("-> ", text.split("tasks in")[1] if "tasks in" in text else "")
        self.assertNotIn("tasks in", text)

    def test_qc_test_runner_exits_1_on_failure(self):
        t = self.d / "t_bad.py"
        src = (HERE / "qc_test.py").read_text(encoding="utf-8").rsplit("if __name__ == " + chr(34) + "__main__" + chr(34) + ":", 1)[1]
        t.write_text("import sys, unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.fail('x')\nif __name__ == '__main__':" + src, encoding="utf-8")
        res = subprocess.run([sys.executable, str(t)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 1)
        self.assertIn("TESTS 0/1 passed", res.stdout)

    def read_with_rc(self, rc):
        a = qc.build_parser().parse_args(["--no-update", "read", str(self.d / "tasks")])
        buf = io.StringIO()
        with mock.patch.object(qc, "run", return_value=rc), mock.patch.object(Path, "exists", return_value=True), redirect_stdout(buf):
            got = qc.cmd_read(a)
        return got, buf.getvalue()

    def test_read_not_flagged_adds_the_rerun_line(self):
        got, out = self.read_with_rc(0)
        self.assertEqual(got, 0)
        self.assertIn("One read can miss. If you run it again and any run flags the task, treat it as flagged.", out)
        self.assertIn("To have qc.py repeat the read for you, add --times 3.", out)

    def test_read_flagged_and_could_not_run_add_no_rerun_line(self):
        for rc in (1, 2):
            got, out = self.read_with_rc(rc)
            self.assertEqual(got, rc)
            self.assertNotIn("One read can miss", out)
            self.assertNotIn("--times 3", out)

    def test_no_update_is_accepted_after_the_command_word(self):
        p = qc.build_parser()
        self.assertTrue(p.parse_args(["read", "x", "--no-update"]).no_update)
        self.assertTrue(p.parse_args(["--no-update", "read", "x"]).no_update)
        self.assertFalse(p.parse_args(["read", "x"]).no_update)


if __name__ == "__main__":
    r = unittest.main(exit=False, verbosity=0)
    n = r.result.testsRun
    bad = len(r.result.failures) + len(r.result.errors)
    print(f"TESTS {n - bad}/{n} passed")
    sys.exit(1 if bad else 0)
