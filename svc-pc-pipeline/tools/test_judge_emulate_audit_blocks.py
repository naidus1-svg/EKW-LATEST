#!/usr/bin/env python3
"""Tests _run_formula_audit_block in judge_emulate.py: it must run the heredoc INSIDE each audit block, whatever
its delimiter or version, and never the next section's block.

2026-09-25: SVC-PC-20-8-0 / 20-4-0 / 22-2-0 wrap FORMULA-AUTHENTICITY in <<'FAEOF' (22-2-0 as -V2). The runner
matched only -V1 and <<'PYEOF', so it ran the following SVCPC-RENDER-V1 PYEOF block instead and the report four
criteria grade was never written (golden stuck at 0.97 through 10 attempts). Run: python tools/test_judge_emulate_audit_blocks.py
"""

import os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judge_emulate as je

PRE = (
    "#!/bin/bash\npython3 - <<'PYEOF'\nopen('/app/pre_marker','w').write('x')\nPYEOF\n"
)
RENDER = (
    "# --- SVCPC-RENDER-V1: render ---\npython3 - <<'PYEOF'\n"
    "open('/app/render_marker','w').write('x')\nPYEOF\n# --- END SVCPC-RENDER-V1 ---\n"
)


def auth(version, delim):
    return (
        "# --- SVCPC-FORMULA-AUTHENTICITY-%s ---\n# comment mentioning PYEOF\n"
        "python3 - <<'%s'\nopen('/app/_formula_authenticity_report.md','w').write('ok')\n%s\n"
        "# --- END SVCPC-FORMULA-AUTHENTICITY-%s ---\n"
        % (version, delim, delim, version)
    )


class T(unittest.TestCase):
    def run_block(self, test_sh):
        with tempfile.TemporaryDirectory() as d:
            task, app = Path(d, "task"), Path(d, "app")
            (task / "tests").mkdir(parents=True)
            app.mkdir()
            (task / "tests" / "test.sh").write_text(test_sh, encoding="utf-8")
            je._run_formula_audit_block(task, app)
            return sorted(p.name for p in app.iterdir())

    def test_faeof_v1_runs_own_block_not_render(self):
        out = self.run_block(PRE + auth("V1", "FAEOF") + RENDER)
        self.assertIn("_formula_authenticity_report.md", out)
        self.assertNotIn("render_marker", out)
        self.assertNotIn("pre_marker", out)

    def test_faeof_v2_is_recognised(self):
        out = self.run_block(PRE + auth("V2", "FAEOF") + RENDER)
        self.assertIn("_formula_authenticity_report.md", out)
        self.assertNotIn("render_marker", out)

    def test_pyeof_v1_still_works(self):
        out = self.run_block(PRE + auth("V1", "PYEOF") + RENDER)
        self.assertEqual(out, ["_formula_authenticity_report.md"])

    def test_no_audit_header_runs_nothing(self):
        self.assertEqual(self.run_block(PRE + RENDER), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
