"""The EKW wrapper builds its own package, so the two converter fixes have to reach it separately (2026-10-01).

  PHR-118 batch148 (EKW): the golden's judge folders p4 and p5 timed out at rewardkit's 300 s default. The wrapper writes
      its own judge.toml, so the converter's `timeout = 900` never reached an EKW package until the wrapper wrote it too.
  FIN-155 (EKW): DataOS reviewers raised a 1.5 because a copy of the golden with every formula replaced by its cached
      value grades identically to the golden. The fix is a code check in <raw>/checks_deterministic/*.py, and the wrapper
      has to carry it into tests/checks_deterministic/ because the lane regenerates the package from <raw> every attempt.
  The wrapper renders trk.TEST_SH itself. The guard in the new template takes its deliverables from the placeholder
      __DELIVERABLE_NAMES_PY__; a wrapper that only filled __DELIVERABLE_NAMES__ shipped a test.sh whose guard raised a
      NameError at grade time. Both tests build a one-criterion raw task through convert() and read what it wrote.

Usage: python3 test_ekw_raw_to_rewardkit_render.py   (needs openpyxl; run from svc-pc-pipeline/tools with the repo's
pipeline/tools/to_rewardkit.py two directories up, as the wrapper itself expects)
"""

import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

if importlib.util.find_spec("openpyxl") is None:
    raise unittest.SkipTest("openpyxl not installed")
import openpyxl  # noqa: E402

wrapper = importlib.import_module("ekw_raw_to_rewardkit")
TMP = tempfile.mkdtemp(prefix="ekw_wrapper_render_test_")


def make_raw(name, checks=None):
    raw = os.path.join(TMP, name)
    os.makedirs(os.path.join(raw, "expert_solution"))
    for rel, body in (checks or {}).items():
        path = os.path.join(raw, "checks_deterministic", *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").write(body)
    open(os.path.join(raw, "prompt.txt"), "w", encoding="utf-8").write(
        "Build the quarterly model. " * 12
    )
    wb = openpyxl.Workbook()
    wb.active.append(["a", 1])
    wb.save(os.path.join(raw, "expert_solution", "Quarterly_Model.xlsx"))
    verifier = {
        "task_id": name,
        "verifiers": [
            {
                "name": "C1",
                "assertion": {
                    "type": "rubric",
                    "expected": True,
                    "rubric": {"prompt": "The quarterly model exists."},
                },
                "source": {
                    "file": {"arguments": {"path": "output/Quarterly_Model.xlsx"}}
                },
                "metadata": {"weight": 1.0, "tag": "t1"},
            }
        ],
    }
    open(os.path.join(raw, "verifier.json"), "w", encoding="utf-8").write(
        json.dumps(verifier)
    )
    return raw


def build(name, checks=None):
    out = os.path.join(TMP, "out_" + name)
    wrapper.convert(make_raw(name, checks), out, fix_formulas=False)
    return os.path.join(out, name)


class WrapperRendersTheConverterFixes(unittest.TestCase):
    def test_PHR_118_every_judge_toml_carries_the_judge_timeout(self):
        pkg = build("render-timeout")
        tomls = sorted(
            os.path.join(pkg, "tests", d, "judge.toml")
            for d in os.listdir(os.path.join(pkg, "tests"))
            if d.startswith("deliverables")
        )
        self.assertTrue(tomls)
        for t in tomls:
            self.assertRegex(open(t, encoding="utf-8").read(), r"(?m)^timeout = 900$")

    def test_test_sh_has_no_unreplaced_placeholder_and_names_the_deliverables(self):
        pkg = build("render-placeholder")
        text = open(os.path.join(pkg, "tests", "test.sh"), encoding="utf-8").read()
        self.assertNotIn("__DELIVERABLE_NAMES_PY__", text)
        self.assertNotIn("__DELIVERABLE_NAMES__", text)
        self.assertIn('DELIVERABLES = ["Quarterly_Model.xlsx"]', text)

    def test_the_rendered_guard_compiles(self):
        pkg = build("render-compile")
        text = open(os.path.join(pkg, "tests", "test.sh"), encoding="utf-8").read()
        blocks = re.findall(r"python3 - <<'PYEOF'\n(.*?)\nPYEOF", text, re.S)
        self.assertEqual(len(blocks), 2)
        for i, b in enumerate(blocks):
            compile(b, "heredoc%d" % i, "exec")

    def test_the_rendered_test_sh_passes_bash_syntax_check(self):
        probe = subprocess.run(["bash", "-c", "echo ok"], capture_output=True, text=True)
        if probe.returncode != 0 or "ok" not in probe.stdout:
            self.skipTest("no usable bash here (a Windows WSL stub is not one)")
        pkg = build("render-bash")
        path = os.path.join(pkg, "tests", "test.sh")
        r = subprocess.run(
            ["bash", "-n", path.replace(os.sep, "/")], capture_output=True, text=True
        )
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_FIN_155_checks_deterministic_ships_byte_for_byte_and_stays_out_of_the_weights_table(self):
        body = b'DELIVERABLE = "Quarterly_Model.xlsx"\n# a check\r\nx = 1\n'
        pkg = build("render-checks", {"formula_checks.py": body})
        shipped = os.path.join(pkg, "tests", "checks_deterministic", "formula_checks.py")
        self.assertEqual(open(shipped, "rb").read(), body)
        text = open(os.path.join(pkg, "tests", "reward.toml"), encoding="utf-8").read()
        self.assertIn("judges 50% / deterministic checks 50%", text)
        import tomllib

        reward = tomllib.loads(text)["reward"][0]
        self.assertTrue(reward["weights"])
        self.assertNotIn("checks_deterministic", reward["weights"])
        for dim in reward["weights"]:
            self.assertTrue(os.path.isfile(os.path.join(pkg, "tests", dim, "judge.toml")), dim)

    def test_a_task_without_checks_deterministic_gets_no_folder_and_the_old_reward_toml(self):
        pkg = build("render-no-checks")
        self.assertFalse(os.path.exists(os.path.join(pkg, "tests", "checks_deterministic")))
        text = open(os.path.join(pkg, "tests", "reward.toml"), encoding="utf-8").read()
        self.assertTrue(text.startswith("[[reward]]"))

    def test_only_py_files_directly_in_the_folder_are_copied(self):
        pkg = build(
            "render-checks-filter",
            {
                "formula_checks.py": b"x = 1\n",
                "notes.txt": b"not code\n",
                "__pycache__/formula_checks.cpython-313.pyc": b"\0\0",
                "nested/other.py": b"y = 2\n",
            },
        )
        shipped = sorted(os.listdir(os.path.join(pkg, "tests", "checks_deterministic")))
        self.assertEqual(shipped, ["formula_checks.py"])

    def test_an_empty_checks_deterministic_folder_adds_nothing(self):
        raw = make_raw("render-checks-empty")
        os.makedirs(os.path.join(raw, "checks_deterministic"))
        out = os.path.join(TMP, "out_render-checks-empty2")
        wrapper.convert(raw, out, fix_formulas=False)
        pkg = os.path.join(out, "render-checks-empty")
        self.assertFalse(os.path.exists(os.path.join(pkg, "tests", "checks_deterministic")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
