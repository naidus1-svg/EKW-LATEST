#!/usr/bin/env python3
"""Load each SVC-PC task's tests/ with rewardkit 0.1.7's discover(), the loader DataOS runs at upload.

Why (2026-09-22): 72-1-0 and 94-7-0 were silently dropped from harvest batches 3 and 4. DataOS showed only
"Has 1 error"; the task page said `rewardkit.discover() failed: TypeError("unhashable type: 'list'")`.
Cause: `judge = ["m", "m", "m"]` (a judge panel) in judge.toml, which our rewardkit 0.2.0 oracle accepts and
0.1.7 does not. Same local-vs-DataOS engine gap as 16-1-0's r017. A task that fails this load can never be
graded, so it is a HARD pre-upload defect; svc_prefilter.py calls this and blocks on failure.

Needs the pinned venv: /root/venv017/bin/python3 (rewardkit 0.1.7).
Usage: /root/venv017/bin/python3 tools/svc_discover017_check.py <task_pkg_dir> [...]   (exit 1 if any fails)
       ... --corpus /root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready   (scan every SVC-PC-* package)
"""

import os, sys, traceback

try:
    from rewardkit import discover
    import rewardkit
except Exception as e:  # pragma: no cover
    sys.exit(
        "rewardkit not importable in this interpreter (%s); run with /root/venv017/bin/python3"
        % e
    )


def check(pkg):
    tests = os.path.join(pkg, "tests")
    try:
        discover(tests)
        return None
    except Exception as e:
        return "%s: %s" % (type(e).__name__, str(e)[:160])


def main(argv):
    if "--corpus" in argv:
        root = argv[argv.index("--corpus") + 1]
        pkgs = sorted(
            os.path.join(root, d) for d in os.listdir(root) if d.startswith("SVC-PC-")
        )
    else:
        pkgs = [a for a in argv if not a.startswith("--")]
    bad = 0
    for p in pkgs:
        err = check(p)
        if err:
            bad += 1
            print("FAIL %s  %s" % (os.path.basename(p.rstrip("/")), err))
    print(
        "rewardkit %s discover(): %d of %d packages fail"
        % (getattr(rewardkit, "__version__", "?"), bad, len(pkgs))
    )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
