#!/usr/bin/env python3
"""Tests for ekw_bundle_upload.py. Stdlib only, temp dirs, no sandbox paths touched.

Each case builds a fake EKW world (package, _raw verifier.json, verify record, gate JSON, ready.txt, a ready zip
and the manifest ekw_intake.py package writes), then runs the tool as a subprocess.
Run: python tools/test_ekw_bundle_upload.py"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "ekw_bundle_upload.py")
MV = "v9.9-test"


def sha(b):
    return hashlib.sha256(b).hexdigest()


class World:
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="ekwbundle_")
        self.work = os.path.join(self.root, "work")
        self.pkg_root = os.path.join(self.root, "pkgs")
        self.out = os.path.join(self.root, "bundles")
        self.rules = os.path.join(self.root, "rules.md")
        for d in ("ready", "verify", "gate"):
            os.makedirs(os.path.join(self.work, d))
        os.makedirs(self.pkg_root)
        open(self.rules, "w").write("METHOD_VERSION: %s\nrules\n" % MV)
        open(os.path.join(self.work, "ready.txt"), "w").close()
        open(os.path.join(self.work, "parked.txt"), "w").close()

    def add_task(
        self,
        task,
        extra=None,
        verdict="READY-TO-RESUBMIT",
        no_manifest=False,
        ready_ts="2026-09-25T10:00:00Z",
    ):
        pkg = os.path.join(self.pkg_root, task)
        files = {
            "task.toml": b'schema_version = "1.1"\n',
            "instruction.md": b"Write the memo.\n",
            "tests/reward.toml": b"[reward]\n",
            "tests/test.sh": b"#!/bin/bash\n",
            "tests/task_prompt.txt": b"Write the memo.\n",
            "tests/deliverables_01/judge.toml": b"[judge]\n",
            "solution/solve.sh": b"cp -a /solution/files/. /app/\n",
            "solution/files/memo.docx": b"GOLDEN MEMO " + task.encode(),
            "environment/Dockerfile": b"FROM x\n",
            "environment/initial_workspace/lease.pdf": b"LEASE " + task.encode(),
        }
        files.update(extra or {})
        for rel, data in files.items():
            p = os.path.join(pkg, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(data)
        raw = os.path.join(self.pkg_root, "_raw", task)
        os.makedirs(raw, exist_ok=True)
        open(os.path.join(raw, "verifier.json"), "w").write('{"task_id": "%s"}' % task)
        vrec = os.path.join(self.work, "verify", task + ".verify.md")
        open(vrec, "w").write(
            "checked\nVERDICT: %s\n\nMETHOD_VERSION: ekw-v1/%s\n" % (verdict, MV)
        )
        gj = os.path.join(self.work, "gate", task + ".gate.json")
        json.dump({"task": task, "verdict": "PASS"}, open(gj, "w"))
        zp = os.path.join(self.work, "ready", task + ".zip")
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            for rel, data in sorted(files.items()):
                z.writestr("%s/%s" % (task, rel), data)
        if not no_manifest:
            man = {
                "task": task,
                "zip_sha256": sha(open(zp, "rb").read()),
                "files": {rel: sha(d) for rel, d in files.items()},
                "evidence": {
                    vrec: sha(open(vrec, "rb").read()),
                    gj: sha(open(gj, "rb").read()),
                },
                "raw_verifier_sha256": sha(
                    open(os.path.join(raw, "verifier.json"), "rb").read()
                ),
            }
            json.dump(man, open(zp + ".manifest.json", "w"))
        with open(os.path.join(self.work, "ready.txt"), "a") as f:
            f.write("%s\tz\t%s\tattempts=1\n" % (task, ready_ts))
        return pkg

    def run(self, *args):
        common = [
            "--work",
            self.work,
            "--pkg-root",
            self.pkg_root,
            "--rules",
            self.rules,
            "--out-dir",
            self.out,
        ]
        r = subprocess.run(
            [sys.executable, TOOL] + list(args) + common, capture_output=True, text=True
        )
        return r.returncode, r.stdout + r.stderr

    def bundle(self, name="ekw-v1-batch1", *tasks):
        sel = ["--tasks"] + list(tasks) if tasks else ["--from-ready"]
        return self.run("bundle", "--name", name, *sel)

    def check(self, name="ekw-v1-batch1"):
        return self.run("check", os.path.join(self.out, name + ".zip"))

    def roots(self, name="ekw-v1-batch1"):
        with zipfile.ZipFile(os.path.join(self.out, name + ".zip")) as z:
            return sorted({n.split("/", 1)[0] for n in z.namelist()})


class T(unittest.TestCase):
    def setUp(self):
        self.w = World()

    def tearDown(self):
        shutil.rmtree(self.w.root, ignore_errors=True)

    def test_fresh_passes_bundle_and_check(self):
        self.w.add_task("LGL-001")
        self.w.add_task("SCO-002")
        rc, out = self.w.bundle()
        self.assertEqual(rc, 0, out)
        self.assertIn("2 fresh, 0 refused", out)
        self.assertEqual(self.w.roots(), ["LGL-001", "SCO-002"])
        rc, out = self.w.check()
        self.assertEqual(rc, 0, out)
        self.assertIn("FRESH: every task is byte-identical", out)
        self.assertTrue(
            os.path.isfile(os.path.join(self.w.work, "shipped", "LGL-001.json"))
        )

    def test_stale_package_refused(self):
        self.w.add_task("LGL-001")
        pkg = self.w.add_task("SCO-002")
        open(os.path.join(pkg, "instruction.md"), "wb").write(b"edited after the zip\n")
        rc, out = self.w.bundle()
        self.assertEqual(rc, 0, out)
        self.assertIn("REFUSED SCO-002", out)
        self.assertIn("STALE: package on disk changed", out)
        self.assertEqual(self.w.roots(), ["LGL-001"])

    def test_stale_after_bundle_fails_check(self):
        pkg = self.w.add_task("LGL-001")
        self.assertEqual(self.w.bundle()[0], 0)
        open(os.path.join(pkg, "tests/deliverables_01/judge.toml"), "wb").write(
            b"[judge]\nedited\n"
        )
        rc, out = self.w.check()
        self.assertEqual(rc, 1, out)
        self.assertIn("DO NOT UPLOAD", out)

    def test_missing_manifest_refused(self):
        self.w.add_task("LGL-001", no_manifest=True)
        rc, out = self.w.bundle()
        self.assertEqual(rc, 1, out)
        self.assertIn("no manifest", out)
        self.assertIn("nothing shippable", out)

    def test_golden_in_inputs_refused(self):
        self.w.add_task(
            "LGL-190",
            extra={
                "environment/initial_workspace/memo_copy.docx": b"GOLDEN MEMO LGL-190"
            },
        )
        rc, out = self.w.bundle()
        self.assertEqual(rc, 1, out)
        self.assertIn("golden in inputs", out)

    def test_junk_refused(self):
        self.w.add_task("LGL-001", extra={"tests/_scratch_probe.py": b"print(1)\n"})
        rc, out = self.w.bundle()
        self.assertEqual(rc, 1, out)
        self.assertIn("junk in zip", out)

    def test_answer_key_path_refused(self):
        self.w.add_task(
            "LGL-001",
            extra={"environment/initial_workspace/expert_solution/notes.txt": b"x"},
        )
        rc, out = self.w.bundle()
        self.assertEqual(rc, 1, out)
        self.assertIn("answer-key path", out)

    def test_verdict_as_markdown_heading_is_read(self):
        # 2026-09-25: "## VERDICT: READY-TO-RESUBMIT" was read as no verdict and excluded LGL-185
        import importlib.util, tempfile

        tool = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "ekw_bundle_upload.py"
        )
        spec = importlib.util.spec_from_file_location("ekw_bu_probe", tool)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(
                "| v1 | x |\n\n## VERDICT: READY-TO-RESUBMIT\n\nMETHOD_VERSION: ekw-v1/x\n"
            )
        try:
            self.assertEqual(mod.verify_state(f.name)[0], "READY-TO-RESUBMIT")
        finally:
            os.unlink(f.name)

    def test_verify_not_ready_refused(self):
        self.w.add_task("LGL-001", verdict="NOT-READY")
        rc, out = self.w.bundle()
        self.assertEqual(rc, 1, out)
        self.assertIn("verify verdict is NOT-READY", out)

    def test_parked_after_ready_refused_but_ready_after_park_ok(self):
        self.w.add_task("LGL-001", ready_ts="2026-09-25T10:00:00Z")
        self.w.add_task("LGL-002", ready_ts="2026-09-25T12:00:00Z")
        with open(os.path.join(self.w.work, "parked.txt"), "a") as f:
            f.write("LGL-001\tp\t2026-09-25T11:00:00Z\tstuck\n")
            f.write("LGL-002\tp\t2026-09-25T11:00:00Z\tstuck\n")
        rc, out = self.w.bundle()
        self.assertEqual(rc, 0, out)
        self.assertIn("REFUSED LGL-001", out)
        self.assertEqual(self.w.roots(), ["LGL-002"])

    def test_rebuild_same_name_ok_second_bundle_refused(self):
        self.w.add_task("LGL-001")
        self.assertEqual(self.w.bundle("ekw-v1-batch1")[0], 0)
        rc, out = self.w.bundle("ekw-v1-batch1")
        self.assertEqual(rc, 0, out)
        rc, out = self.w.bundle("ekw-v1-batch2")
        self.assertEqual(rc, 1, out)
        self.assertIn("already in bundle ekw-v1-batch1.zip", out)

    def test_never_graded_same_bytes_reship_ok(self):
        # 2026-09-29 SCO-232: DataOS returned 0 reviews, so the task sits on needs_regrade.txt with unchanged bytes.
        self.w.add_task("LGL-001")
        self.assertEqual(self.w.bundle("ekw-v1-batch1")[0], 0)
        with open(os.path.join(self.w.work, "needs_regrade.txt"), "w") as f:
            f.write("LGL-001\n")
        rc, out = self.w.bundle("ekw-v1-batch2")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.w.check("ekw-v1-batch2")[0], 0)

    def test_size_split(self):
        for t in ("LGL-001", "LGL-002", "LGL-003"):
            self.w.add_task(t)
        rc, out = self.w.run(
            "bundle", "--name", "ekw-v1-batch1", "--from-ready", "--max-mb", "0.0000001"
        )
        self.assertEqual(rc, 0, out)
        for s in "abc":
            self.assertTrue(
                os.path.isfile(os.path.join(self.w.out, "ekw-v1-batch1%s.zip" % s)), out
            )
        self.assertEqual(self.w.check("ekw-v1-batch1b")[0], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
