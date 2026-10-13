"""Alarm when the shortfall stops moving, and say for each hole whether anything is alive.

Why this exists, plainly. Two monitors ran all evening and neither caught that three Gemini
runs on SVC-PC-7-3-0 had been dead for hours:

  watch.py     prints only when the number CHANGES. The number sat at 3, so it printed
               nothing. Silence meant stuck and was read as fine.
  leasewatch.py tested for "exactly one object and it is lease.json". Those runs had 21
               objects and exception files, so they counted as alive. It detected the
               previous failure mode and was blind to the next one.

So this does not test for any particular failure. It tests the only thing that always
holds: a hole that is genuinely being worked on gets closed, and one that is not, does not.
If the shortfall has not fallen in STALL_MIN minutes, it says so and names every outstanding
hole with a verdict, regardless of how the underlying run failed.

Scored means EITHER trial_status/status.json has a non-null reward OR verifier/reward.json
does. The default pipeline writes no reward into status.json at all.

Read-only.
"""

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

E = "long-horizon-evals-beta"
LOG = r"C:\evzuild\stallwatch.log"
CYCLE = 180
STALL_MIN = 25.0  # no reduction in this long, on a hole with nothing alive, is an alarm
ALIVE_MIN = 45.0  # a run touched this recently is plausibly still working
EXCLUDE = {"v1", "v3"}
MODELS = [
    "anthropic__claude-opus-5",
    "anthropic__claude-sonnet-5",
    "google__gemini-3.1-pro-preview-customtools",
    "google__gemini-3.7-flash",
    "openai__gpt-5.6-sol",
    "openai__gpt-5.6-terra",
]
GEMINI = ("google__gemini-3.7-flash", "google__gemini-3.1-pro-preview-customtools")

_t = {"v": None, "at": 0}


def tok():
    if _t["v"] is None or time.time() - _t["at"] > 600:
        _t["v"] = os.popen("gcloud auth print-access-token").read().strip()
        _t["at"] = time.time()
    return _t["v"]


def req(u, tries=4):
    for i in range(tries):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(u, headers={"Authorization": "Bearer " + tok()}),
                timeout=300,
            )
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                _t["v"] = None
            if i == tries - 1:
                raise
            time.sleep(3)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3)


def listing(prefix):
    out, page = [], None
    while True:
        u = (
            "https://storage.googleapis.com/storage/v1/b/"
            + E
            + "/o?prefix="
            + urllib.parse.quote(prefix)
            + "&maxResults=1000&fields=items(name,updated),nextPageToken"
        )
        if page:
            u += "&pageToken=" + page
        j = json.load(req(u))
        out.extend(j.get("items", []))
        page = j.get("nextPageToken")
        if not page:
            return out


def cat(n):
    try:
        return json.loads(
            req(
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


def say(m):
    line = "%s  %s" % (
        datetime.datetime.now(datetime.timezone.utc).strftime("%H:%MZ"),
        m,
    )
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def T(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def measure():
    now = datetime.datetime.now(datetime.timezone.utc)
    items = listing("evals/SVC")
    score_files = [
        i["name"]
        for i in items
        if len(i["name"].split("/")) > 5
        and i["name"].split("/")[2] not in EXCLUDE
        and (
            i["name"].endswith("/trial_status/status.json")
            or i["name"].endswith("/verifier/reward.json")
        )
    ]

    def one(n):
        d = cat(n)
        if d is None:
            return None
        p = n.split("/")
        return (p[1], p[4], (p[2], p[3], p[5]), d.get("reward") is not None)

    scored = collections.defaultdict(lambda: collections.defaultdict(set))
    tasks = set()
    with ThreadPoolExecutor(max_workers=24) as ex:
        for r in ex.map(one, score_files):
            if not r:
                continue
            tasks.add(r[0])
            if r[3]:
                scored[r[0]][r[1]].add(r[2])

    # newest write per run, and whether it ever threw
    runs = collections.defaultdict(lambda: {"last": "", "exc": 0})
    for i in items:
        p = i["name"].split("/")
        if len(p) < 6 or p[2] in EXCLUDE:
            continue
        k = (p[1], p[4], (p[2], p[3], p[5]))
        r = runs[k]
        if i["updated"] > r["last"]:
            r["last"] = i["updated"]
        if "exception.txt" in i["name"]:
            r["exc"] += 1

    holes = []
    for t in sorted(tasks):
        for m in MODELS:
            target = 10 if m in GEMINI else 4
            gap = max(0, target - len(scored[t][m]))
            if not gap:
                continue
            alive = 0
            for k, v in runs.items():
                if k[0] != t or k[1] != m or k[2] in scored[t][m]:
                    continue
                if (now - T(v["last"])).total_seconds() / 60.0 < ALIVE_MIN:
                    alive += 1
            holes.append((t, m, gap, alive))
    k4 = sum(max(0, 4 - len(scored[t][m])) for t in tasks for m in MODELS)
    k10 = sum(max(0, 10 - len(scored[t][m])) for t in tasks for m in GEMINI)
    return k4, k10, holes


say("stallwatch up. alarms when the shortfall stops falling, whatever the cause.")
last_total, last_drop = None, time.time()
while True:
    try:
        k4, k10, holes = measure()
    except Exception as e:
        say("measure failed: %s" % str(e)[:90])
        time.sleep(CYCLE)
        continue

    total = k4 + k10
    if total == 0:
        say("COMPLETE. k=4 satisfied and Gemini at k=10.")
        sys.exit(0)

    if last_total is None or total < last_total:
        last_drop = time.time()
        say("k=4 short %d   gemini k=10 short %d" % (k4, k10))
        for t, m, gap, alive in holes:
            say(
                "   %-14s %-34s short %d   alive %d"
                % (t, m.split("__")[-1], gap, alive)
            )
    last_total = total

    stalled = (time.time() - last_drop) / 60.0
    dead = [h for h in holes if h[3] == 0]
    if stalled > STALL_MIN and dead:
        say(
            "STALLED %.0f min with %d hole(s) that have NOTHING running. Refire these:"
            % (stalled, len(dead))
        )
        for t, m, gap, _ in dead:
            say("   REFIRE  %-14s %-34s %d run(s)" % (t, m.split("__")[-1], gap))
        last_drop = time.time()  # re-alarm every STALL_MIN, do not go quiet again
    time.sleep(CYCLE)
