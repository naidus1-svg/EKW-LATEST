"""Fire Gemini 3.8 Flash on the 40 published SVC tasks (the same 40 used for Grok Build).

This is a new eval on an existing task set, not a backfill. `svc_harbor_fire_gemini.py`
already does live task discovery and staging for SVC but targets gemini-3.7-flash and
gemini-3.1-pro-preview-customtools (the six-model leaderboard work). `ekw_harbor_fire_gemini38.py`
fires the right model but is hardcoded to EKW's `ekw0909-` prefix and EKW's ready-list.
Neither fires 3.8 Flash on these 40 SVC tasks, so this script exists.

Scope is the 40 task IDs pulled from `_scratch_upload_grok_zips.state.json` (the Grok
Build upload record — authoritative for "which 40 tasks", per that file's own role in
this project). `ekw/eval-run-plan-2026-09-09.md` Priority 3 independently confirms these
are the 40 SVC tasks that have been graded on any model and are all L2 — the QC-passed
set Shyam's approval condition ("run evals on tasks passing QC") requires.

Same two guards as both parent scripts, because both were paid for in real incidents:

1. **The ready marker is read back from the bucket before a single enqueue goes out.**
   The worker resolves the newest revision BEFORE it checks for the marker, so a
   markerless higher revision silently takes a task out of service. Cost 2.5 hours on
   2026-09-02. Camus's own instruction after the Grok fire was to remove each task's
   harbor_ready_marker post-trigger, so assume these 40 need a FRESH marker at a NEW
   revision, not a reused one from the Grok run.

2. **Existing coverage is computed live from the bucket, not assumed zero.** Even though
   this is "a new eval," checking first costs one listing call and prevents a duplicate
   fire if someone already ran a smoke test on gemini-3.8-flash against this task set.

**Environment is not yet confirmed and this script will not guess.** The 40 tasks were
staged for Grok Build in the `beta` env (`long-horizon-beta` / `long-horizon-evals-beta`,
per the delivered run's bucket in the pre-compact recovery doc). This script defaults to
beta on that basis, but the worker URL Camus most recently gave (`pr-931`, 2026-09-10) was
for grok-build specifically — whether it also serves Gemini traffic, or whether Gemini
needs the earlier `pr-658` url, or QA, is UNCONFIRMED. Phase 0 (measure-only, the default)
does not depend on the worker URL at all, only on bucket listings, so it is safe to run
before that's settled. Do not add --live until the worker URL is confirmed with Camus.

  python tools/svc_harbor_fire_gemini38.py                 measure only, no spend, no worker call
  python tools/svc_harbor_fire_gemini38.py --smoke          one task at k=1, about $1.80, still needs WORKER confirmed
  python tools/svc_harbor_fire_gemini38.py --live           all 40 at k=10, about $720, still needs WORKER confirmed
"""

import argparse
import base64
import collections
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

TASKS = [
    "SVC-PC-1-1-0",
    "SVC-PC-1-2-0",
    "SVC-PC-1-5-0",
    "SVC-PC-3-1-0",
    "SVC-PC-3-2-0",
    "SVC-PC-3-4-0",
    "SVC-PC-5-2-0",
    "SVC-PC-5-4-0",
    "SVC-PC-5-5-0",
    "SVC-PC-5-6-0",
    "SVC-PC-6-1-0",
    "SVC-PC-6-2-0",
    "SVC-PC-6-3-0",
    "SVC-PC-6-5-0",
    "SVC-PC-7-1-0",
    "SVC-PC-7-2-0",
    "SVC-PC-7-3-0",
    "SVC-PC-7-4-0",
    "SVC-PC-7-5-0",
    "SVC-PC-7-6-0",
    "SVC-PC-9-1-0",
    "SVC-PC-9-3-0",
    "SVC-PC-9-4-0",
    "SVC-PC-9-5-0",
    "SVC-PC-9-6-0",
    "SVC-PC-10-1-0",
    "SVC-PC-11-2-0",
    "SVC-PC-11-3-0",
    "SVC-PC-11-4-0",
    "SVC-PC-12-1-0",
    "SVC-PC-12-2-0",
    "SVC-PC-13-3-0",
    "SVC-PC-13-6-0",
    "SVC-PC-13-7-0",
    "SVC-PC-14-1-0",
    "SVC-PC-14-2-0",
    "SVC-PC-14-3-0",
    "SVC-PC-14-6-0",
    "SVC-PC-16-1-0",
    "SVC-PC-16-4-0",
]
assert len(TASKS) == 40, "expected exactly 40 tasks, got %d" % len(TASKS)

# Environment is switchable, same pattern as ekw_harbor_fire_gemini38.py, so an unset
# variable cannot silently pick the wrong one. Default is beta, see docstring above.
_ENVNAME = os.environ.get("HARBOR_ENV", "beta").strip().lower()
if _ENVNAME not in ("beta", "qa"):
    raise SystemExit("HARBOR_ENV must be beta or qa, got {!r}".format(_ENVNAME))
if _ENVNAME == "qa":
    BUCKET = "long-horizon-qa"
    EVALS = "long-horizon-evals-qa"
    WORKER = os.environ.get("WORKER_URL", "")
else:
    BUCKET = "long-horizon-beta"
    EVALS = "long-horizon-evals-beta"
    WORKER = os.environ.get("WORKER_URL", "")

PROJECT = "turing-delivery-apac-dev"
REV = os.environ.get(
    "REV", "v2"
)  # v1 was the Grok Build revision; this is a fresh stage
K_TARGET = int(os.environ.get("K", "10"))
RATE = 1.80  # Gemini 3.8 Flash, per docs/PRE_COMPACT_RECOVERY.md section 8
MODEL = {
    "name": "google/gemini-3.8-flash",
    "provider": "google",
    "reasoningEffort": "high",
}
SLUG = "google__gemini-3.8-flash"

SMOKE = "--smoke" in sys.argv
LIVE = "--live" in sys.argv
ONLY_TASKS = set(x for x in os.environ.get("ONLY_TASKS", "").split(",") if x) or set(
    TASKS
)

ENV = {**os.environ, "CLOUDSDK_CORE_DISABLE_PROMPTS": "1"}
_tok = {"v": None, "at": 0}


def say(m):
    print("%s  %s" % (datetime.datetime.now().strftime("%H:%M:%S"), m), flush=True)


def tok():
    if _tok["v"] is None or time.time() - _tok["at"] > 600:
        import subprocess

        p = subprocess.run(
            ["gcloud.cmd", "auth", "print-access-token"],
            capture_output=True,
            text=True,
            env=ENV,
            timeout=180,
        )
        t = (p.stdout or "").strip()
        if not t:
            sys.exit(
                "no access token. run: gcloud.cmd auth login --enable-gdrive-access"
            )
        _tok["v"], _tok["at"] = t, time.time()
    return _tok["v"]


def api(u, method="GET", data=None, ctype=None, tries=4):
    for i in range(tries):
        try:
            h = {"Authorization": "Bearer " + tok()}
            if ctype:
                h["Content-Type"] = ctype
            return urllib.request.urlopen(
                urllib.request.Request(u, data=data, method=method, headers=h),
                timeout=300,
            )
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (401, 403):
                _tok["v"] = None
            if i == tries - 1:
                raise
            time.sleep(2)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2)


def listing(bucket, prefix):
    out, page = [], None
    while True:
        u = (
            "https://storage.googleapis.com/storage/v1/b/"
            + bucket
            + "/o?prefix="
            + urllib.parse.quote(prefix)
            + "&maxResults=1000&fields=items(name),nextPageToken"
        )
        if page:
            u += "&pageToken=" + page
        j = json.load(api(u))
        out.extend(i["name"] for i in j.get("items", []))
        page = j.get("nextPageToken")
        if not page:
            return out


def scored(n):
    try:
        d = json.loads(
            api(
                "https://storage.googleapis.com/storage/v1/b/"
                + EVALS
                + "/o/"
                + urllib.parse.quote(n, safe="")
                + "?alt=media"
            )
            .read()
            .decode("utf-8", "replace")
        )
    except Exception:
        return None
    p = n.split("/")
    return (p[1], (p[2], p[3], p[5]), d.get("reward") is not None)


# --- Phase 0: measure what already exists for these 40 tasks on this model, live. ---
say(
    "=== Phase 0: measuring existing %s coverage on the 40 SVC tasks, env=%s ==="
    % (SLUG, _ENVNAME)
)
names = listing(EVALS, "evals/SVC")
status = [
    n
    for n in names
    if n.endswith("/trial_status/status.json")
    and len(n.split("/")) > 5
    and n.split("/")[1] in ONLY_TASKS
    and n.split("/")[4] == SLUG
]
have = collections.defaultdict(set)
with ThreadPoolExecutor(max_workers=24) as ex:
    for r in ex.map(scored, status):
        if r and r[2]:
            have[r[0]].add(r[1])

need = {t: K_TARGET - min(len(have.get(t, ())), K_TARGET) for t in sorted(ONLY_TASKS)}
missing_from_bucket = sorted(
    t for t in ONLY_TASKS if t not in {n.split("/")[1] for n in names}
)
say(
    "tasks with existing %s trials found: %d of %d" % (SLUG, len(have), len(ONLY_TASKS))
)
for t in sorted(ONLY_TASKS):
    say("   %-16s have=%d  need=%d" % (t, len(have.get(t, ())), need[t]))
total_trials = sum(v for v in need.values() if v > 0)
say("")
say(
    "trials to fire: %d   cost if every one lands $%.2f   (rate $%.2f/trial)"
    % (total_trials, total_trials * RATE, RATE)
)
if missing_from_bucket:
    say(
        "WARNING: %d task(s) have NO objects at all under evals/SVC in bucket %s: %s"
        % (len(missing_from_bucket), EVALS, missing_from_bucket)
    )
    say(
        "This likely means the task packages are not staged in THIS environment (%s)."
        % _ENVNAME
    )
    say(
        "Before firing, confirm with Camus which env (beta or qa) actually holds these 40 packages now."
    )

if not LIVE and not SMOKE:
    say("")
    say("plan only. add --smoke for a single $1.80 trial, or --live for the full run.")
    sys.exit(0)

if not WORKER:
    sys.exit(
        "WORKER_URL is not set. Confirm the current worker URL with Camus before --smoke or --live "
        "(pr-658 and pr-931 are both mentioned in Slack history for different purposes; do not guess)."
    )

say("")
say(
    "Refusing to actually enqueue: this script's staging/enqueue phase is intentionally not wired up yet."
)
say(
    "Phase 0 (measurement) is the only thing that has run. Build the stage()/enqueue() phase, following"
)
say(
    "svc_harbor_fire_gemini.py's marker-read-back pattern, once the environment and worker URL are confirmed."
)
sys.exit(0)
