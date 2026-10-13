#!/usr/bin/env python3
"""oracle_refresh.py - re-run the golden-vs-own-rubric oracle probe for tasks whose staged bytes changed after the probe.

zip_when_ready.sh runs the oracle only when probes/oracle.json is missing or infra-tainted, so a task fixed after its
probe ships on the pre-fix result. 15-2-0 on 2026-09-19: probe written 2026-09-18 21:54, golden .docx rewritten 04:30,
zipped 06:09 as "oracle=1.0". This script is the freshness check.

  oracle_refresh.py scan            list unsubmitted zipped or clean-pair tasks whose staged files are newer than their probe
  oracle_refresh.py scan-json       the same as JSON, for guard_rt.py
  oracle_refresh.py run T [T ...]   re-probe those tasks (WORKERS at a time, currently 16 -
                                    the docstring said 4 for a while after the code moved to
                                    16, corrected 2026-09-19); the new probe replaces
                                    oracle.json only when it is a real score (not
                                    infra-tainted) and no staged file changed while it ran.
                                    Step B (2026-09-19 18:25Z): each probe is now --runs 3
                                    (total_reward = the min across runs, flips written to
                                    oracle.runs.json), and each worker defers its own probe
                                    launch (not the pool) while load1 > 64.
Tasks are given as SVC-PC-<n>-<n>-<n> or without the prefix. The old probe is kept as probes/oracle.pre-<epoch>.json.
"""

import concurrent.futures as cf
import glob
import json
import os
import re
import subprocess
import sys
import time

Q = "/root/qc"
SP = f"{Q}/stream-pipe"
C = "/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready"
LANES = [
    "/root/.claude-e", "/root/.claude-f", "/root/.claude-c", "/root/.claude-b", "/root/.claude-d", "/root/.claude", "/root/.claude-g", "/root/.claude-i",
    "/root/.claude-j", "/root/.claude-k", "/root/.claude-l", "/root/.claude-q", "/root/.claude-r",
]
WORKERS = 16
EXCL_DIRS = {"_prior", "_runs", "_scratch"}
EXCL_NAMES = re.compile(
    r"^(FIX-LOG.*\.md|REFUTER.*\.md|CR-REFUTER\.md|COMPREHENSIVE-REVIEW\.md|GATE\.md|.*\.round1.*)$"
)


def norm(t):
    return t if t.startswith("SVC-PC-") else f"SVC-PC-{t}"


def newest_staged(t):
    """(mtime, relative path) of the newest shipped file. tests/test.sh is skipped: the emulator never reads it."""
    root = f"{C}/{t}"
    best = (0.0, "")
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in EXCL_DIRS]
        for f in fn:
            if EXCL_NAMES.match(f):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if rel == "tests/test.sh":
                continue
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if m > best[0]:
                best = (m, rel)
    return best


def has_error(groups):
    for g in groups or []:
        for c in g.get("criteria") or []:
            if c.get("error"):
                return True
        if has_error(g.get("children")):
            return True
    return False


def real_score(path):
    """total_reward if the probe file is a real (non-infra) result, else None."""
    try:
        d = json.load(open(path))
    except Exception:
        return None
    if (
        d.get("total_reward") is None
        or d.get("infra_failure")
        or has_error(d.get("groups"))
    ):
        return None
    # 2026-09-19 18:50Z (step B validation): the blanket LANE_RE.search(json.dumps(d)) that
    # used to sit here is redundant with has_error() above (a pre-fix judge_emulate.py
    # always wrote its lane-refused text into a criterion's own "error" field via
    # _synthetic_error_scores, which has_error() already catches) and actively wrong: it
    # scans the WHOLE json blob, including every judge verdict_text, so a golden that
    # legitimately discusses a "Shopify API rate-limit event" as a business fact (SVC-PC-
    # 26-8-0, SVC-PC-92-4-0) got misclassified as an infra refusal and a real total_reward
    # =1.0 was discarded. Removed; has_error()/infra_failure/total_reward is None already
    # cover every real case this was meant to catch, with no false positives on content.
    return d["total_reward"]


def submitted():
    try:
        return set(open(f"{Q}/SUBMITTED.txt").read().split())
    except Exception:
        return set()


def latest_major(t, r):
    fs = [
        f
        for f in glob.glob(f"{SP}/{t}/CR.{r}.round*.json")
        if re.search(r"round\d+\.json$", f)
    ]
    if not fs:
        return None
    f = max(fs, key=lambda x: int(re.search(r"round(\d+)\.json$", x).group(1)))
    try:
        j = json.load(open(f))
        return (
            j["major_count"]
            if isinstance(j.get("major_count"), int) and "checks" in j
            else None
        )
    except Exception:
        return None


def live_park(t):
    try:
        pk = open(f"{SP}/{t}/PARKED.md").read()
    except Exception:
        return False
    return not re.search(
        r"majors still present after|failed, rc=10|check-fix: still blocked", pk
    )


def prompt_too_long(task_dir):
    for name in ("oracle.log", "oracle.refresh.log"):
        try:
            with open(f"{task_dir}/probes/{name}", "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 8000))
                if b"Prompt is too long" in f.read():
                    return True
        except Exception:
            pass
    return False


def stale_tasks():
    """Unsubmitted tasks that have a zip, or a clean latest verdict pair and no live park, and whose oracle probe is
    missing, infra-tainted, or older than their shipped files."""
    sub = submitted()
    try:
        rejected = set(open(f"{Q}/lanes/DATAOS_REJECTED").read().split())
    except Exception:
        rejected = set()
    zips = {os.path.basename(z)[:-4] for z in glob.glob(f"{Q}/out/pipe/SVC-PC-*.zip")}
    out = []
    for d in sorted(glob.glob(f"{SP}/SVC-PC-*")):
        t = os.path.basename(d)
        if not re.fullmatch(r"SVC-PC-\d+-\d+-\d+", t) or t in sub:
            continue
        has_zip = t in zips
        if not has_zip:
            if live_park(t):
                continue
            if t in rejected and not os.path.exists(f"{d}/DATAOS_MAJORS_RESOLVED"):
                continue
            if latest_major(t, "glm") != 0 or latest_major(t, "sonnet") != 0:
                continue
        o = f"{d}/probes/oracle.json"
        if not os.path.exists(o) or real_score(o) is None:
            # no usable probe yet: run it here, ahead of the zip step, which otherwise spends ~3 of its ~4 minutes per
            # task on it (an attempt with a probe already on disk takes about a minute). A task whose judge prompt
            # exceeds the emulator's window fails the same way every time, so it is left to the alert.
            if prompt_too_long(d):
                continue
            out.append((t, has_zip, 0, "no usable probe"))
            continue
        m, rel = newest_staged(t)
        if m > os.path.getmtime(o) + 1:
            out.append((t, has_zip, m - os.path.getmtime(o), rel))
    return out


def load1():
    try:
        with open("/proc/loadavg") as f:
            return float(f.read().split()[0])
    except Exception:
        return 0.0


def wait_for_load(lg, max_wait_s=300, poll_s=15, threshold=64):
    """Defer a new oracle probe launch while load1 is above threshold (step B, verifier
    2026-09-19 18:25Z: --runs 3 triples probe cost). Bounded, not indefinite - a thread in
    this pool that waited forever would shrink the effective worker count under sustained
    load, which is the opposite of the point; after max_wait_s it proceeds anyway and says
    so in the log."""
    waited = 0
    while load1() > threshold and waited < max_wait_s:
        lg.write(
            f"{time.strftime('%FT%TZ', time.gmtime())} load1={load1()} > {threshold}, "
            f"deferring launch ({waited}s waited)\n"
        )
        lg.flush()
        time.sleep(poll_s)
        waited += poll_s
    if waited >= max_wait_s and load1() > threshold:
        lg.write(
            f"{time.strftime('%FT%TZ', time.gmtime())} load1={load1()} still > {threshold} "
            f"after {waited}s, proceeding anyway\n"
        )
        lg.flush()


def probe(t, lane):
    d = f"{SP}/{t}/probes"
    os.makedirs(d, exist_ok=True)
    new = f"{d}/oracle.new.json"
    if os.path.exists(new):
        os.remove(new)
    with open(f"{d}/oracle.refresh.log", "a") as lg:
        wait_for_load(lg)
        started = time.time()
        lg.write(
            f"\n=== {time.strftime('%FT%TZ', time.gmtime())} refresh on {os.path.basename(lane)}\n"
        )
        lg.flush()
        env = dict(os.environ, CLAUDE_CONFIG_DIR=lane)
        subprocess.run(
            [
                "timeout",
                "3600",  # step B: --runs 3 triples this call's wall-clock cost
                "python3",
                f"{Q}/tools/judge_emulate.py",
                "oracle",
                t,
                "--runs",
                "3",
                "--corpus-root",
                C,
                "--out",
                new,
            ],
            cwd=Q,
            env=env,
            stdout=lg,
            stderr=subprocess.STDOUT,
        )
    old = real_score(f"{d}/oracle.json")
    new_score = real_score(new)
    if new_score is None:
        return (t, old, None, "probe tainted or missing; old probe left in place")
    m, rel = newest_staged(t)
    if m > started:
        return (
            t,
            old,
            new_score,
            f"staged file {rel} changed during the probe; discarded",
        )
    (
        os.replace(f"{d}/oracle.json", f"{d}/oracle.pre-{int(started)}.json")
        if os.path.exists(f"{d}/oracle.json")
        else None
    )
    os.replace(new, f"{d}/oracle.json")
    return (t, old, new_score, "swapped in")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("scan", "scan-json", "run"):
        sys.exit(__doc__)
    if sys.argv[1] in ("scan", "scan-json"):
        rows = stale_tasks()
        if sys.argv[1] == "scan-json":
            print(
                json.dumps(
                    [
                        {"task": t, "zip": z, "newer_s": int(age), "file": rel}
                        for t, z, age, rel in rows
                    ]
                )
            )
            return
        for t, z, age, rel in rows:
            print(f"{t}  {'zip' if z else 'clean pair'}  ({int(age)}s newer: {rel})")
        print(f"{len(rows)} unsubmitted tasks with a probe older than their files")
        return
    tasks = [norm(t) for t in sys.argv[2:]]
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        futs = [ex.submit(probe, t, LANES[i % len(LANES)]) for i, t in enumerate(tasks)]
        for f in cf.as_completed(futs):
            t, old, new, note = f.result()
            print(f"{t}  old={old}  new={new}  {note}", flush=True)


if __name__ == "__main__":
    main()
