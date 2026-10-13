"""The oracle's error path must score a failing criterion 0, never crash.
A criterion with description=None (or missing) used to raise a pydantic ValidationError inside
_synthetic_error_scores, so a task whose programmatic reward raised was parked as "oracle CRASHED".
Usage: python test_judge_emulate_error_scores.py [path/to/judge_emulate.py]"""

import importlib.util, sys, types

path = sys.argv[1] if len(sys.argv) > 1 else "tools/judge_emulate.py"
spec = importlib.util.spec_from_file_location("je", path)
je = importlib.util.module_from_spec(spec)
spec.loader.exec_module(je)

cases = {
    "description None": types.SimpleNamespace(
        name="c1", description=None, id="c1", negate=False, optional=False
    ),
    "no attributes": types.SimpleNamespace(),
    "negate None": types.SimpleNamespace(
        name="c3", description="d", negate=None, optional=None
    ),
}
fail = 0
for label, c in cases.items():
    try:
        s = je._synthetic_error_scores([c], [0.5], "programmatic reward raised X")[0]
        ok = s.value == 0.0 and s.weight == 0.5 and s.error.startswith("programmatic")
        print("PASS" if ok else "FAIL", label, "->", s.name, s.value)
        fail += not ok
    except Exception as e:
        print("FAIL", label, "->", type(e).__name__)
        fail += 1
print("ALL PASS" if not fail else "%d FAIL" % fail)
sys.exit(1 if fail else 0)
