#!/usr/bin/env python3
"""End-to-end tests for the stale-zip gate: svc_build_upload_zip.py + svc_bundle_upload.py (+ the shared
svc_ship_manifest.py). Stdlib only; builds a throwaway corpus in a temp dir, so it runs on the laptop or the
sandbox. Every case is a way stale or unverified bytes have reached, or could reach, DataOS.

Run: python tools/test_svc_bundle_upload.py     (exit 0 = all pass)
"""

import json, os, shutil, subprocess, sys, tempfile, time, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "svc_build_upload_zip.py")
BUNDLE = os.path.join(HERE, "svc_bundle_upload.py")
sys.path.insert(0, HERE)
import svc_ship_manifest as sm  # noqa: E402

MV = sm.method_version()
T = tempfile.mkdtemp(prefix="svc_bundle_test_")
CORPUS, DF, READY, OUT, SHIP, RET = (
    os.path.join(T, d)
    for d in ("corpus", "deepfix", "ready", "bundles", "shipped", "returns")
)
for d in (CORPUS, DF, READY, OUT, SHIP, RET):
    os.makedirs(d)
ACC = os.path.join(T, "accepted.txt")
open(ACC, "w").write("SVC-PC-99-9-0\n")
PREFILTER = os.path.join(T, "prefilter_ok.py")
open(PREFILTER, "w").write("print('prefilter: clean')\n")
COMMON = [
    "--pkg-root",
    CORPUS,
    "--accepted-list",
    ACC,
    "--returns-dir",
    RET,
    "--verify-dir",
    DF,
    "--prefilter",
    PREFILTER,
]


def make_task(t, verdict="READY-TO-RESUBMIT", mv=MV, regrade="PASS"):
    p = os.path.join(CORPUS, t)
    for sub in ("tests/deliverables", "solution", "environment/initial_workspace"):
        os.makedirs(os.path.join(p, sub), exist_ok=True)
    open(os.path.join(p, "instruction.md"), "w").write("Do the thing.\n")
    open(os.path.join(p, "tests/deliverables/judge.toml"), "w").write(
        '[[criterion]]\nid="c1"\n'
    )
    open(os.path.join(p, "solution/answer.md"), "w").write("golden\n")
    time.sleep(0.02)
    if verdict:
        open(os.path.join(DF, t + ".verify.md"), "w").write(
            "audit table " * 30
            + "\nVERDICT: %s\n\nMETHOD_VERSION: %s\n" % (verdict, mv)
        )
    if regrade:
        json.dump(
            {"verdict": regrade, "why": "test"},
            open(os.path.join(DF, t + ".regrade.json"), "w"),
        )
    return p


def build(t, *extra):
    r = subprocess.run(
        [
            sys.executable,
            BUILD,
            t,
            "--regrade-dir",
            DF,
            "--out",
            os.path.join(READY, t + ".zip"),
        ]
        + COMMON
        + list(extra),
        capture_output=True,
        text=True,
    )
    return r.returncode, r.stdout


def bundle(name, *tasks, first_grade=False):
    cmd = (
        [sys.executable, BUNDLE, "bundle", "--name", name, "--tasks"]
        + list(tasks)
        + COMMON
        + ["--ready-dir", READY, "--out-dir", OUT, "--shipped-dir", SHIP]
    )
    if first_grade:
        cmd.append("--first-grade")
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout


def check(path):
    r = subprocess.run(
        [sys.executable, BUNDLE, "check", path]
        + COMMON
        + ["--ready-dir", READY, "--out-dir", OUT, "--shipped-dir", SHIP],
        capture_output=True,
        text=True,
    )
    return r.returncode, r.stdout


results = []


def case(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(
        ("PASS" if cond else "FAIL"),
        "::",
        name,
        ("" if cond else "\n      " + detail.replace("\n", "\n      ")[:900]),
    )


# builder gates
make_task("SVC-PC-1-0-0")
rc, out = build("SVC-PC-1-0-0")
case(
    "builder builds a READY, current-method, regrade-PASS task and writes a manifest",
    rc == 0 and os.path.isfile(os.path.join(READY, "SVC-PC-1-0-0.zip.manifest.json")),
    out,
)

make_task("SVC-PC-2-0-0", verdict="NOT-READY")
rc, out = build("SVC-PC-2-0-0")
case(
    "builder refuses a NOT-READY verify record (Gate 2 used to check only that the file existed)",
    rc == 4,
    out,
)

make_task("SVC-PC-3-0-0", mv="v7-old")
rc, out = build("SVC-PC-3-0-0")
case("builder refuses a verify record made under an older METHOD_VERSION", rc == 4, out)

make_task("SVC-PC-4-0-0")
time.sleep(0.05)
open(os.path.join(CORPUS, "SVC-PC-4-0-0/solution/answer.md"), "w").write(
    "edited after verify\n"
)
rc, out = build("SVC-PC-4-0-0")
case("builder refuses a verify record older than the last package edit", rc == 4, out)

# bundler: fresh vs stale
rc, out = bundle("b-fresh", "SVC-PC-1-0-0")
bpath = os.path.join(OUT, "b-fresh.zip")
case("bundler bundles a fresh task", rc == 0 and os.path.isfile(bpath), out)
if os.path.isfile(bpath):
    with zipfile.ZipFile(bpath) as z:
        roots = sorted({n.split("/")[0] for n in z.namelist()})
    case("bundle holds exactly the task root", roots == ["SVC-PC-1-0-0"], str(roots))
rc, out = check(bpath)
case("check passes while nothing changed", rc == 0 and "FRESH" in out, out)

make_task("SVC-PC-5-0-0")
build("SVC-PC-5-0-0")
time.sleep(0.05)
open(os.path.join(CORPUS, "SVC-PC-5-0-0/tests/deliverables/judge.toml"), "w").write(
    '[[criterion]]\nid="c1-edited"\n'
)
rc, out = bundle("b-stale", "SVC-PC-5-0-0")
case(
    "THE STALE-ZIP HOLE: corpus edited after the zip was built -> excluded, nothing bundled",
    rc == 1
    and "EDITED since this zip was built" in out
    and not os.path.isfile(os.path.join(OUT, "b-stale.zip")),
    out,
)

make_task("SVC-PC-6-0-0")
build("SVC-PC-6-0-0")
open(os.path.join(DF, "SVC-PC-6-0-0.verify.md"), "a").write("\nVERDICT: NOT-READY\n")
rc, out = bundle("b-reverified", "SVC-PC-6-0-0")
case(
    "re-verified NOT-READY after zipping (the batch1 case) -> excluded",
    rc == 1 and "NOT-READY" in out,
    out,
)

make_task("SVC-PC-7-0-0")
build("SVC-PC-7-0-0")
rc, out = bundle("b-mixed", "SVC-PC-7-0-0", "SVC-PC-5-0-0")
with zipfile.ZipFile(os.path.join(OUT, "b-mixed.zip")) as z:
    roots = sorted({n.split("/")[0] for n in z.namelist()})
case(
    "mixed batch: fresh task ships, stale task is excluded and named",
    rc == 0 and roots == ["SVC-PC-7-0-0"] and "REFUSED SVC-PC-5-0-0" in out,
    out,
)

rc, out = bundle("b-again", "SVC-PC-7-0-0")
case(
    "the same bytes are never bundled twice", rc == 1 and "already shipped" in out, out
)

# check catches staleness between bundle and upload
open(os.path.join(CORPUS, "SVC-PC-1-0-0/instruction.md"), "w").write(
    "changed after bundling\n"
)
rc, out = check(bpath)
case(
    "check catches a task edited AFTER bundling (last-moment pre-upload check)",
    rc == 1 and "STALE SVC-PC-1-0-0" in out,
    out,
)

# a zip without a manifest (built the old way) is refused
make_task("SVC-PC-8-0-0")
with zipfile.ZipFile(os.path.join(READY, "SVC-PC-8-0-0.zip"), "w") as z:
    z.writestr("SVC-PC-8-0-0/instruction.md", "x")
rc, out = bundle("b-nomanifest", "SVC-PC-8-0-0")
case(
    "a ready zip with no manifest (pre-gate or hand-built) is refused",
    rc == 1 and "no manifest" in out,
    out,
)

# accepted freeze
make_task("SVC-PC-99-9-0")
rc, out = build("SVC-PC-99-9-0")
case("builder refuses an accepted (frozen) task", rc == 7, out)

# team do-not-touch list (svc_build_freeze.py output) is honoured like accepted.txt
open(os.path.join(T, "do_not_touch.txt"), "w").write("SVC-PC-14-0-0\n")
make_task("SVC-PC-14-0-0")
rc, out = build("SVC-PC-14-0-0")
case(
    "builder refuses a task on the team do-not-touch list (owned or already submitted by someone)",
    rc == 7,
    out,
)


# verify-cap pilot (2026-09-23): a NOT-READY verify ships only via --fast-track + --verify-capped, with a 1.0
# oracle on the current bytes; every other gate (regrade PASS here) still holds.
def oracle(t, rew):
    p = os.path.join(DF, t + ".oracle_confirm.json")
    time.sleep(0.02)
    json.dump({"total_reward": rew}, open(p, "w"))
    return p


CAPR = "verify-capped L2 pilot (test)"
make_task("SVC-PC-20-0-0", verdict="NOT-READY")
rc, out = build(
    "SVC-PC-20-0-0",
    "--fast-track",
    CAPR,
    "--oracle-json",
    oracle("SVC-PC-20-0-0", 1.0),
    "--verify-capped",
)
man = {}
mp = os.path.join(READY, "SVC-PC-20-0-0.zip.manifest.json")
if os.path.isfile(mp):
    man = json.load(open(mp))
case(
    "verify-capped builds a NOT-READY task with a 1.0 oracle and tags the manifest with the verify record hash",
    rc == 0 and man.get("verify_capped") is True and man.get("capped_verify_sha"),
    out,
)
rc, out = bundle("b-capped", "SVC-PC-20-0-0")
case("a verify-capped zip bundles and passes the manifest re-check", rc == 0, out)

make_task("SVC-PC-21-0-0", verdict="NOT-READY")
rc, out = build("SVC-PC-21-0-0", "--verify-capped")
case("--verify-capped without --fast-track is refused", rc == 2, out)

make_task("SVC-PC-22-0-0", verdict="NOT-READY")
rc, out = build(
    "SVC-PC-22-0-0",
    "--fast-track",
    CAPR,
    "--oracle-json",
    oracle("SVC-PC-22-0-0", 0.9),
    "--verify-capped",
)
case("verify-capped refuses an oracle below 1.0", rc == 4, out)

make_task("SVC-PC-23-0-0", verdict="NOT-READY", regrade="FAIL")
rc, out = build(
    "SVC-PC-23-0-0",
    "--fast-track",
    CAPR,
    "--oracle-json",
    oracle("SVC-PC-23-0-0", 1.0),
    "--verify-capped",
)
case("verify-capped still refuses a regrade that is not PASS", rc == 6, out)

# first-grade
make_task("SVC-PC-10-0-0", verdict=None, regrade=None)
rc, out = bundle("b-harvest", "SVC-PC-10-0-0", first_grade=True)
case(
    "first-grade bundles a never-graded task with no verify/regrade record",
    rc == 0,
    out,
)
make_task("SVC-PC-11-0-0", verdict=None, regrade=None)
with zipfile.ZipFile(os.path.join(RET, "batch_x_with_runs.zip"), "w") as z:
    z.writestr("SVC-PC-11-0-0/rev_1__1/task_files/instruction.md", "x")
    z.writestr(
        "SVC-PC-11-0-0/rev_1__1/verifications/comprehensive_review_1___codex__gpt.md",
        "x",
    )
    # a task that came back with evaluations but NO review (DataOS exception) was never graded
    z.writestr("SVC-PC-15-0-0/rev_1__2/task_files/instruction.md", "x")
rc, out = bundle("b-harvest2", "SVC-PC-11-0-0", first_grade=True)
case(
    "first-grade refuses a task DataOS already graded (proved from the return zips)",
    rc == 1 and "already graded" in out,
    out,
)
make_task("SVC-PC-15-0-0", verdict=None, regrade=None)
rc, out = bundle("b-harvest3", "SVC-PC-15-0-0", first_grade=True)
case(
    "first-grade allows re-grading a task whose return held no review (DataOS exception, 5-1-0)",
    rc == 0,
    out,
)

# legacy check: a pre-gate bundle (no manifest) is compared byte-for-byte to the corpus
make_task("SVC-PC-13-0-0", verdict=None, regrade=None)
LEG = os.path.join(OUT, "legacy.zip")
with zipfile.ZipFile(LEG, "w") as z:
    for full in sm._walk(os.path.join(CORPUS, "SVC-PC-13-0-0")):
        z.write(
            full,
            "SVC-PC-13-0-0/"
            + os.path.relpath(full, os.path.join(CORPUS, "SVC-PC-13-0-0")).replace(
                "\\", "/"
            ),
        )


def legacy():
    r = subprocess.run(
        [sys.executable, BUNDLE, "check", LEG, "--legacy"]
        + COMMON
        + ["--ready-dir", READY, "--out-dir", OUT, "--shipped-dir", SHIP],
        capture_output=True,
        text=True,
    )
    return r.returncode, r.stdout


rc, out = legacy()
case(
    "legacy check: a manifest-less bundle that matches the corpus passes",
    rc == 0 and "MATCHES CORPUS" in out,
    out,
)
open(os.path.join(CORPUS, "SVC-PC-13-0-0/instruction.md"), "w").write(
    "edited after the legacy bundle\n"
)
rc, out = legacy()
case(
    "legacy check: corpus edited after a manifest-less bundle -> STALE",
    rc == 1 and "STALE SVC-PC-13-0-0" in out,
    out,
)

# sweep: stale ready zips go back to the queue, fresh ones stay
Q = os.path.join(T, "queue.txt")
CL = os.path.join(T, "claims")
os.makedirs(os.path.join(CL, "SVC-PC-5-0-0"))
open(Q, "w").write("SVC-PC-50-0-0\n")
make_task("SVC-PC-12-0-0")
build("SVC-PC-12-0-0")
r = subprocess.run(
    [sys.executable, BUNDLE, "sweep", "--apply", "--queue", Q, "--claims-dir", CL]
    + COMMON
    + ["--ready-dir", READY, "--out-dir", OUT, "--shipped-dir", SHIP],
    capture_output=True,
    text=True,
)
q = open(Q).read().split()
case(
    "sweep requeues stale zips (edited corpus, no manifest) and keeps a fresh one",
    r.returncode == 0
    and "SVC-PC-5-0-0" in q
    and "SVC-PC-8-0-0" in q
    and "SVC-PC-12-0-0" not in q
    and os.path.isfile(os.path.join(READY, "SVC-PC-12-0-0.zip"))
    and not os.path.isfile(os.path.join(READY, "SVC-PC-5-0-0.zip"))
    and not os.path.isdir(os.path.join(CL, "SVC-PC-5-0-0")),
    r.stdout + r.stderr,
)

shutil.rmtree(T, ignore_errors=True)
n_ok = sum(ok for _, ok in results)
print("\n%d/%d passed" % (n_ok, len(results)))
sys.exit(0 if n_ok == len(results) else 1)
