"""Fire the Gemini runs still short of k=10, with the staging guards spelled out.

Scope is derived live, not hardcoded. The previous fire script stopped counting at v16
and would read v17 through v21 scored runs as holes, so the revision list here is built
from what actually exists in the bucket minus the two that never ran.

Two guards matter more than anything else this does:

1. A revision is staged with its .harbor_package_ready marker, and the marker is read
   back from the bucket before a single enqueue goes out. The worker resolves the newest
   revision BEFORE it checks for the marker, so a markerless higher revision silently
   takes the task out of service. That fault cost 2.5 hours on 2026-09-02.

2. The enqueue carries one k for every model in the call, and pending/<task>/<rev> blocks
   a second call at the same revision. A task short by different amounts per model needs
   one revision per distinct count, so the work is grouped into waves by k and each wave
   gets its own revision.

Only the two Gemini models, only the tasks actually short, and a scored run is one
(revision, execution, trial) whose trial_status/status.json carries a non-null reward.

  python fire_gemini.py           measure and plan
  python fire_gemini.py --live    stage, verify markers, enqueue
"""

import base64
import collections
import datetime
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = r"C:\evt"
T = "long-horizon-beta"
E = "long-horizon-evals-beta"
WORKER = "https://gdpval-worker-beta-pr-658.rd.atlas.turing.com"
PROJECT = "turing-delivery-apac-dev"
TEMPLATE = r"C:\b\_out46final\03_dataos_ready\SVC-PC-1-4-0\environment\Dockerfile"
EXCLUDE_REVS = {"v1", "v3"}
K_TARGET = int(os.environ.get("K", "10"))
START_REV = int(os.environ.get("REV", "22"))
LIVE = "--live" in sys.argv
LOG = r"C:\evzuild\fire-gemini.log"

MODELS = {
    "google__gemini-3.7-flash": {
        "name": "google/gemini-3.7-flash",
        "provider": "google",
        "reasoningEffort": "high",
    },
    "google__gemini-3.1-pro-preview-customtools": {
        "name": "google/gemini-3.1-pro-preview-customtools",
        "provider": "google",
        "reasoningEffort": "high",
    },
}
RATE = {
    "google__gemini-3.7-flash": 0.96,
    "google__gemini-3.1-pro-preview-customtools": 0.23,
    "anthropic__claude-opus-5": 4.30,
    "anthropic__claude-sonnet-5": 7.00,
    "openai__gpt-5.6-sol": 3.00,
    "openai__gpt-5.6-terra": 1.30,
}
ALL = dict(MODELS)
ALL["anthropic__claude-sonnet-5"] = {"name": "anthropic/claude-sonnet-5[1m]", "provider": "claude", "reasoningEffort": "max"}
ALL["anthropic__claude-opus-5"] = {"name": "anthropic/claude-opus-5[1m]", "provider": "claude", "reasoningEffort": "max"}
ALL["openai__gpt-5.6-sol"] = {"name": "openai/gpt-5.6-sol", "provider": "openai", "reasoningEffort": "max"}
ALL["openai__gpt-5.6-terra"] = {"name": "openai/gpt-5.6-terra", "provider": "openai", "reasoningEffort": "max"}
# ONLY_MODELS scopes the fire to named slugs. Empty means the Gemini pair above.
_only = [x for x in os.environ.get("ONLY_MODELS", "").split(",") if x]
if _only:
    MODELS = {k: ALL[k] for k in _only}
ONLY_TASKS = set(x for x in os.environ.get("ONLY_TASKS", "").split(",") if x)

_t = {"v": None, "at": 0}
_lock = threading.Lock()


def say(m):
    line = "%s  %s" % (datetime.datetime.now().strftime("%H:%M:%S"), m)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def tok():
    with _lock:
        if _t["v"] is None or time.time() - _t["at"] > 600:
            _t["v"] = os.popen("gcloud auth print-access-token").read().strip()
            _t["at"] = time.time()
        return _t["v"]


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
                with _lock:
                    _t["v"] = None
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


names = listing(E, "evals/SVC")
revs = sorted(
    {n.split("/")[2] for n in names if len(n.split("/")) > 2} - EXCLUDE_REVS,
    key=lambda r: int(r[1:]),
)
say("revisions counted as done: %s" % revs)

status = [
    n
    for n in names
    if n.endswith("/trial_status/status.json")
    and len(n.split("/")) > 5
    and n.split("/")[2] not in EXCLUDE_REVS
    and n.split("/")[4] in MODELS
]


def scored(n):
    try:
        d = json.loads(
            api(
                "https://storage.googleapis.com/storage/v1/b/"
                + E
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
    return (p[1], p[4], (p[2], p[3], p[5]), d.get("reward") is not None)


have = collections.defaultdict(lambda: collections.defaultdict(set))
tasks = set()
with ThreadPoolExecutor(max_workers=24) as ex:
    for r in ex.map(scored, status):
        if not r:
            continue
        tasks.add(r[0])
        if r[3]:
            have[r[0]][r[1]].add(r[2])

need = collections.defaultdict(dict)
for task in sorted(tasks):
    if ONLY_TASKS and task not in ONLY_TASKS:
        continue
    for slug in MODELS:
        gap = K_TARGET - min(len(have[task][slug]), K_TARGET)
        if gap > 0:
            need[task][slug] = gap

total = sum(sum(v.values()) for v in need.values())
cost = sum(RATE[s] * k for v in need.values() for s, k in v.items())
say("")
say(
    "tasks short: %d   runs to fire: %d   cost if every one lands $%.2f"
    % (len(need), total, cost)
)
for task in sorted(need):
    for s, k in sorted(need[task].items()):
        say("   %-16s %-38s %d" % (task, s.split("__")[-1], k))
waves = max((len(set(v.values())) for v in need.values()), default=0)
say("distinct k per task means %d revision(s), starting at v%d" % (waves, START_REV))

if not LIVE:
    say("plan only. add --live.")
    sys.exit(0)

tpl = open(TEMPLATE, encoding="utf-8").read()


def stage(task, rev):
    """Upload the package, verify the file count, refuse on answer-key paths, then
    write the marker. Returns a message; anything not starting with 'staged' aborts
    the whole run before any enqueue."""
    src = os.path.join(ROOT, task)
    pkg = "tasks/%s/%s/harbor_task/" % (task, rev)
    env_dir = (
        "data"
        if os.path.isdir(os.path.join(src, "environment", "data"))
        else "initial_workspace"
    )
    open(
        os.path.join(src, "environment", "Dockerfile"),
        "w",
        encoding="utf-8",
        newline="\n",
    ).write(tpl.replace("COPY initial_workspace/ /app/", "COPY %s/ /app/" % env_dir))
    local = []
    for dp, dn, fn in os.walk(src):
        rel = os.path.relpath(dp, src).replace("\\", "/")
        top = rel.split("/")[0]
        if top == "solution":
            dn[:] = []
            continue
        for f in fn:
            if rel == "." and f not in ("instruction.md", "task.toml"):
                continue
            if rel != "." and top not in ("environment", "tests"):
                continue
            local.append(f if rel == "." else rel + "/" + f)

    def up(r):
        with open(
            "\\\\?\\" + os.path.abspath(os.path.join(src, r.replace("/", os.sep))), "rb"
        ) as fh:
            d = fh.read()
        api(
            "https://storage.googleapis.com/upload/storage/v1/b/"
            + T
            + "/o?uploadType=media&name="
            + urllib.parse.quote(pkg + r, safe=""),
            method="POST",
            data=d,
            ctype="application/octet-stream",
        )

    with ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(up, local))
    staged = listing(T, pkg)
    if len(staged) != len(local):
        return (task, "MISMATCH %d/%d" % (len(staged), len(local)))
    leak = [n for n in staged if "/solution/" in n or "golden_output" in n.lower()]
    if leak:
        return (task, "ANSWER-KEY LEAK %s" % leak[:2])
    api(
        "https://storage.googleapis.com/upload/storage/v1/b/"
        + T
        + "/o?uploadType=media&name="
        + urllib.parse.quote(
            "tasks/%s/%s/.harbor_package_ready" % (task, rev), safe=""
        ),
        method="POST",
        data=b"",
        ctype="text/plain",
    )
    return (task, "staged %d" % len(staged))


SECRET = (
    base64.b64decode(
        json.load(
            api(
                "https://secretmanager.googleapis.com/v1/projects/"
                + PROJECT
                + "/secrets/gdpval_INTERNAL_WORKER_SECRET/versions/latest:access"
            )
        )["payload"]["data"]
    )
    .decode()
    .strip()
)


def enqueue(task, models, k):
    body = json.dumps(
        {"taskId": task, "models": models, "k": k, "dryRun": False}
    ).encode()
    r = urllib.request.Request(
        WORKER + "/api/internal/harbor-enqueue-eval",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Worker-Secret": SECRET},
    )
    try:
        return json.loads(urllib.request.urlopen(r, timeout=300).read().decode())
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_body": e.read().decode()[:180]}


remaining = {t: dict(v) for t, v in need.items()}
fired = 0
for wave in range(waves):
    rev = "v%d" % (START_REV + wave)
    targets = sorted(t for t in remaining if remaining[t])
    if not targets:
        break
    say("")
    say("=== wave %d at %s, %d task(s) ===" % (wave + 1, rev, len(targets)))
    bad = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for task, msg in ex.map(lambda t: stage(t, rev), targets):
            say("   %-16s %s" % (task, msg))
            if not msg.startswith("staged"):
                bad.append((task, msg))
    if bad:
        sys.exit("staging failed, NOTHING fired: %s" % bad)

    # The marker read-back. Without this the newest revision can be markerless and
    # the task stops dispatching entirely, with HTTP 200 and an empty body.
    back = [
        n
        for n in listing(T, "tasks/SVC")
        if n.endswith("/%s/.harbor_package_ready" % rev)
    ]
    got = {n.split("/")[1] for n in back}
    missing = [t for t in targets if t not in got]
    say(
        "   markers confirmed at %s: %d of %d"
        % (rev, len(got & set(targets)), len(targets))
    )
    if missing:
        sys.exit("marker read-back short for %s, NOTHING fired" % missing)

    for task in targets:
        byk = collections.defaultdict(list)
        for slug, k in remaining[task].items():
            byk[k].append(slug)
        k = max(byk)
        slugs = byk[k]
        d = enqueue(task, [MODELS[s] for s in slugs], k)
        if d.get("enqueued"):
            fired += k * len(slugs)
            for s in slugs:
                remaining[task].pop(s, None)
            say(
                "   %-16s k=%d fired for %s"
                % (task, k, [s.split("__")[-1] for s in slugs])
            )
        else:
            say("   %-16s k=%d NOT fired: %s" % (task, k, json.dumps(d)[:150]))
    say(
        "   running total fired %d, still owed %d"
        % (fired, sum(sum(v.values()) for v in remaining.values()))
    )

say("")
say(
    "dispatched %d runs, %d still owed"
    % (fired, sum(sum(v.values()) for v in remaining.values()))
)
