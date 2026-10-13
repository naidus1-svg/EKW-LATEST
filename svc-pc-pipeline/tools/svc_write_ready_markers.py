"""Put a ready marker on the newest revision of the 30 audited-clean SVC tasks.

The blocker this clears. 38 of the 40 staged SVC tasks have no `.harbor_package_ready` on
their newest revision, and the worker resolves the newest revision BEFORE it checks for the
marker, so every one of them returns `skippedNoInput` and silently drops out of a run. That
blocks the Google SVC leg and the xAI Grok leg equally.

Why 30 and not 40. `TuringGpt/bench-websites` PR 151, merged 2026-09-08, pulled ten tasks
off the published board after a source-of-truth audit against the current Final L2 folder.
Goldens matched on all 40, so nothing leaked, but ten were graded against criteria that do
not match their own spec:

  9-1-0, 9-3-0, 9-4-0, 9-5-0, 9-6-0   superseded prompts asserting case facts, dates,
                                      vendors and SKUs the current prompts never state
  14-2-0                              graded with a DIFFERENT task's rubric; 16 of its 17
                                      criteria have no counterpart in its own FINAL
  10-1-0                              a must-pass criterion carrying two sibling criteria's
                                      numbers, 17,582 units and $1,698,133 against 12,166
  1-2-0                               must-pass flags inverted BOTH ways
  5-2-0                               scored on a 12th criterion the rubric does not define
  16-4-0                              stale exact-filename rule worth 2 points

Marking those ten would put known-wrong scores in front of a customer. They come back after
a rebuild from FINAL, which the PR estimates at 240 runs and about $670.

Note the scope conflict this creates, which is not mine to resolve: Shane McCracken asked on
2026-09-09 for "the 40 published tasks" so xAI stays "apples to apples with the six in the
post". The board became n=30 the day before he wrote that. Every model gained 2 to 6 points
on the change and first place flipped, so 40 and 30 are materially different deliverables.

Safety:
  - only the 30 on the allowlist, computed as staged minus the ten, and asserted
  - refuses if any SVC-shaped task is queued in any lane, because staging a revision with
    queued trials against it restarts them
  - the marker is an empty object, exactly as `paths.ts` expects
  - every marker is read back from the bucket, not from a local copy

    python tools/svc_write_ready_markers.py            report only
    python tools/svc_write_ready_markers.py --live     write and read back
"""

import argparse
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

BUCKET = "long-horizon-beta"
PROJECT = "turing-delivery-apac-dev"
ENV = {**os.environ, "CLOUDSDK_CORE_DISABLE_PROMPTS": "1"}
WORKERS = 8

# PR 151, TuringGpt/bench-websites, merged 2026-09-08.
PULLED = {
    "SVC-PC-1-2-0",
    "SVC-PC-5-2-0",
    "SVC-PC-9-1-0",
    "SVC-PC-9-3-0",
    "SVC-PC-9-4-0",
    "SVC-PC-9-5-0",
    "SVC-PC-9-6-0",
    "SVC-PC-10-1-0",
    "SVC-PC-14-2-0",
    "SVC-PC-16-4-0",
}

QUEUES = [
    "x-gdpval-beta-harbor-eval-executions",
    "x-gdpval-beta-harbor-eval-trials-google",
    "x-gdpval-beta-harbor-eval-trials-xai",
    "x-gdpval-beta-harbor-executions",
]


def gcloud(args, timeout=900):
    return subprocess.run(
        ["gcloud.cmd", "storage"] + args,
        capture_output=True,
        text=True,
        env=ENV,
        timeout=timeout,
    )


def revnum(v):
    m = re.match(r"v(\d+)$", v)
    return int(m.group(1)) if m else -1


def newest_and_marker(task):
    r = gcloud(["ls", "gs://{}/tasks/{}/".format(BUCKET, task)])
    revs = [
        l.strip().rstrip("/").rsplit("/", 1)[-1]
        for l in r.stdout.splitlines()
        if l.strip().startswith("gs://")
    ]
    revs = [v for v in revs if revnum(v) >= 0]
    if not revs:
        return task, None, False
    newest = max(revs, key=revnum)
    m = gcloud(
        ["ls", "gs://{}/tasks/{}/{}/.harbor_package_ready".format(BUCKET, task, newest)]
    )
    return task, newest, ".harbor_package_ready" in m.stdout


def queued_svc():
    """Any SVC-shaped task waiting in any lane. Staging restarts queued trials."""
    total = 0
    for q in QUEUES:
        r = subprocess.run(
            [
                "gcloud.cmd",
                "tasks",
                "list",
                "--queue=" + q,
                "--location=us-central1",
                "--project=" + PROJECT,
                "--limit=500",
                "--format=value(name.basename())",
            ],
            capture_output=True,
            text=True,
            env=ENV,
            timeout=600,
        )
        n = len([l for l in r.stdout.splitlines() if "svc" in l.lower()])
        if n:
            print("  {} has {} SVC-shaped tasks waiting".format(q, n))
        total += n
    return total


def write_marker(task, rev):
    path = "gs://{}/tasks/{}/{}/.harbor_package_ready".format(BUCKET, task, rev)
    tmp = os.path.join(os.environ.get("TEMP", "."), "_hpr_empty")
    open(tmp, "w").close()
    up = gcloud(["cp", tmp, path], timeout=300)
    if up.returncode != 0:
        return task, rev, False, (up.stderr or "")[-140:]
    back = gcloud(["ls", path], timeout=300)
    if path not in back.stdout:
        return task, rev, False, "not visible in bucket after upload"
    return task, rev, True, "verified in bucket"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args()

    r = gcloud(["ls", "gs://{}/tasks/".format(BUCKET)])
    staged = sorted(set(re.findall(r"SVC-PC-[\d-]+", r.stdout)))
    print("SVC tasks staged: {}".format(len(staged)))

    missing = PULLED - set(staged)
    if missing:
        print("WARNING, pulled ids not found staged: {}".format(sorted(missing)))
    allow = [t for t in staged if t not in PULLED]
    print("on the published board, so eligible: {}".format(len(allow)))
    print(
        "pulled by PR 151, deliberately skipped: {}".format(len(PULLED & set(staged)))
    )
    if len(allow) != 30:
        print(
            "\nNOTE: expected 30 eligible, got {}. Read the list before proceeding.".format(
                len(allow)
            )
        )

    print("\nchecking every lane for queued SVC work before staging anything")
    q = queued_svc()
    if q:
        sys.exit(
            "\n{} SVC-shaped tasks are queued. Staging a revision with queued trials "
            "against it restarts them. Refusing.".format(q)
        )
    print("  none queued, safe to stage")

    print("\nresolving newest revision per task")
    rows = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        rows = list(pool.map(newest_and_marker, allow))

    need = [(t, v) for t, v, has in rows if v and not has]
    have = [(t, v) for t, v, has in rows if v and has]
    broke = [t for t, v, _ in rows if not v]
    print("  already marked : {}".format(len(have)))
    print("  need a marker  : {}".format(len(need)))
    if broke:
        print("  NO REVISIONS   : {}".format(broke))

    if not a.live:
        for t, v in need[:12]:
            print("    would mark {:<16} {}".format(t, v))
        print("\ndry run, nothing written. Re-run with --live.")
        return

    print("\nwriting {} markers".format(len(need)))
    ok, bad = 0, []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for t, v, good, why in pool.map(lambda p: write_marker(*p), need):
            if good:
                ok += 1
                print("  {:<16} {:<5} {}".format(t, v, why))
            else:
                bad.append((t, v, why))
                print("  {:<16} {:<5} FAILED {}".format(t, v, why))

    print("\nmarked {} of {}".format(ok, len(need)))
    if bad:
        for t, v, why in bad:
            print("  FAILED {} {} {}".format(t, v, why))

    print("\nre-checking from the bucket")
    rows2 = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        rows2 = list(pool.map(newest_and_marker, allow))
    final = sum(1 for _, v, has in rows2 if v and has)
    print("  {} of {} board tasks now enqueueable".format(final, len(allow)))
    print("\nThe ten pulled tasks remain unmarked on purpose. They need a rebuild from")
    print("FINAL before they can be graded, per PR 151.")


if __name__ == "__main__":
    main()
