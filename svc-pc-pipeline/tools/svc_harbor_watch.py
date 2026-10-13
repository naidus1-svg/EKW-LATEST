"""Emit one line whenever the shortfall changes, and shout if the run stalls.

Separate from finish.py on purpose. finish.py polls, builds and uploads; if it is
restarted or interrupted the visibility goes with it. This only observes, so it can
run continuously without touching anything.

Reports both targets, because they are different and confusing one for the other has
already cost a day: k=4 across all six models is what the leaderboard needs, and
k=10 for the two Gemini models is the separate Google package Shyam asked for.

Silent while a number is unchanged. Speaks when it moves, when nothing has been
written to the bucket for a while, or when everything is done.

Scored means `reward is not None` in EITHER trial_status/status.json OR
verifier/reward.json. This file read status.json alone until 2026-09-08 and would
report the board as 958 of 960 while it was complete.

This prints a shortfall and no denominator, so a `0` from it does not say how many
tasks it found and cannot be reconciled against another count. That is the right
shape for watching a run in flight and the wrong shape for stating a result. To
state a result run tools/svc_harbor_coverage.py; EVAL_RUNBOOK.md section 10e is the
counting contract.
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
LOG = r"C:\evzuild\watch.log"
CYCLE = 180
STALL_MIN = 40
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


def say(m):
    line = "%s  %s" % (
        datetime.datetime.now(datetime.timezone.utc).strftime("%H:%MZ"),
        m,
    )
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def measure():
    items = listing("evals/SVC")
    # A run is scored when reward is not None in EITHER trial_status/status.json OR
    # verifier/reward.json. This file read status.json alone until 2026-09-08, which is the
    # 958-of-960 bug: the 2026-09-03 repair runs went onto the default pipeline, which writes
    # no reward field into status.json at all and puts the score only in verifier/reward.json.
    # 17 runs live only there, so a status.json-only read reports the board 2 short and the
    # Gemini top-up 3 short when both are complete. Section 10e of EVAL_RUNBOOK.md is the
    # contract; tools/svc_harbor_coverage.py is what states a result.
    st = [
        i["name"]
        for i in items
        if (
            i["name"].endswith("/trial_status/status.json")
            or i["name"].endswith("/verifier/reward.json")
        )
        and len(i["name"].split("/")) > 5
        and i["name"].split("/")[2] not in EXCLUDE
    ]

    def one(n):
        try:
            d = json.loads(
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
        p = n.split("/")
        return (p[1], p[4], (p[2], p[3], p[5]), d.get("reward") is not None)

    runs = collections.defaultdict(lambda: collections.defaultdict(set))
    tasks = set()
    with ThreadPoolExecutor(max_workers=24) as ex:
        for r in ex.map(one, st):
            if not r:
                continue
            tasks.add(r[0])
            if r[3]:
                runs[r[0]][r[1]].add(r[2])
    k4 = sum(max(0, 4 - len(runs[t][m])) for t in tasks for m in MODELS)
    k10 = sum(max(0, 10 - len(runs[t][m])) for t in tasks for m in GEMINI)
    newest = max(i["updated"] for i in items)
    quiet = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.datetime.fromisoformat(newest.replace("Z", "+00:00"))
    ).total_seconds() / 60.0
    return k4, k10, quiet, runs, tasks


say("watch up. reports k=4 across six models and k=10 for the two Gemini models.")
last = None
while True:
    try:
        k4, k10, quiet, runs, tasks = measure()
    except Exception as e:
        say("measure failed: %s" % str(e)[:90])
        time.sleep(CYCLE)
        continue

    if k4 == 0 and k10 == 0:
        say("COMPLETE. k=4 satisfied on all six models, Gemini at k=10.")
        sys.exit(0)

    if quiet > STALL_MIN:
        say(
            "STALLED: nothing written for %.0f min, %d k=4 and %d k=10 still missing"
            % (quiet, k4, k10)
        )
        sys.exit(3)

    now = (k4, k10)
    if now != last:
        short = collections.Counter()
        for t in tasks:
            for m in MODELS:
                short[m] += max(0, 4 - len(runs[t][m]))
        detail = "  ".join(
            "%s %d" % (m.split("__")[-1].replace("-preview-customtools", ""), n)
            for m, n in short.most_common()
            if n
        )
        say("k=4 missing %d   gemini k=10 missing %d   [%s]" % (k4, k10, detail))
        last = now
    time.sleep(CYCLE)
