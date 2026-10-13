"""Name the exact slots still short, and say whether anything is running for them.

The shortfall number alone does not tell you what to do. Four missing runs with four
live trials in flight means wait; four missing with nothing running means fire. This
prints both, per (task, model), plus how long each in-flight trial has been going so a
hung one is visible against the model's median.

Read-only. Lists the bucket and reads status.json; writes nothing.
"""

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

E = "long-horizon-evals-beta"
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
MEDIAN = {
    "anthropic__claude-opus-5": 39.4,
    "anthropic__claude-sonnet-5": 40.5,
    "openai__gpt-5.6-sol": 24.8,
    "openai__gpt-5.6-terra": 24.4,
    "google__gemini-3.7-flash": 23.6,
    "google__gemini-3.1-pro-preview-customtools": 8.0,
}

_t = {"v": None, "at": 0}
_lock = threading.Lock()


def tok():
    with _lock:
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
                with _lock:
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


now = datetime.datetime.now(datetime.timezone.utc)
items = listing("evals/SVC")
by_name = {i["name"]: i["updated"] for i in items}
st = [
    n
    for n in by_name
    if n.endswith("/trial_status/status.json")
    and len(n.split("/")) > 5
    and n.split("/")[2] not in EXCLUDE
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
    return (p[1], p[4], (p[2], p[3], p[5]), d.get("reward") is not None, n)


# A run counts as scored if EITHER trial_status/status.json carries a non-null reward OR
# verifier/reward.json exists with one. Camus moved the 2026-09-03 repair runs onto the
# default pipeline, which writes status.json with no reward field at all and puts the score
# only in verifier/reward.json. Reading status.json alone reported 7 finished runs as
# failures and left k=4 looking 2 short when it was already complete at 960 of 960.
rewards = [
    i["name"]
    for i in items
    if i["name"].endswith("/verifier/reward.json")
    and len(i["name"].split("/")) > 5
    and i["name"].split("/")[2] not in EXCLUDE
]

scored = collections.defaultdict(lambda: collections.defaultdict(set))
tasks = set()
with ThreadPoolExecutor(max_workers=24) as ex:
    for r in ex.map(one, st):
        if not r:
            continue
        tasks.add(r[0])
        if r[3]:
            scored[r[0]][r[1]].add(r[2])
    for r in ex.map(one, rewards):
        if not r:
            continue
        tasks.add(r[0])
        if r[3]:
            scored[r[0]][r[1]].add(r[2])

# A slot is in flight when the run prefix exists in the bucket but has no scored
# status.json. Age is measured from the newest object written under that run.
runs = collections.defaultdict(lambda: [None, False])
for i in items:
    p = i["name"].split("/")
    if len(p) < 6 or p[2] in EXCLUDE:
        continue
    k = (p[1], p[4], p[2], p[3], p[5])
    if runs[k][0] is None or i["updated"] > runs[k][0]:
        runs[k][0] = i["updated"]
for n in st:
    p = n.split("/")
    runs[(p[1], p[4], p[2], p[3], p[5])][1] = True

live = collections.defaultdict(list)
for (task, model, rev, exe, trial), (upd, has_status) in runs.items():
    if (rev, exe, trial) in scored[task][model]:
        continue
    age = (
        now - datetime.datetime.fromisoformat(upd.replace("Z", "+00:00"))
    ).total_seconds() / 60.0
    live[(task, model)].append((rev, exe, trial, age, has_status))

print("=== k=4 holes, all six models ===")
tot = 0
for task in sorted(tasks):
    for m in MODELS:
        gap = max(0, 4 - len(scored[task][m]))
        if not gap:
            continue
        tot += gap
        inf = sorted(live.get((task, m), []), key=lambda x: x[3])
        tag = ", ".join(
            "%s/%s/%s %.0fm%s" % (r, e, t, a, " dead" if h else "")
            for r, e, t, a, h in inf[:6]
        )
        print(
            "  %-16s %-42s short %d   in flight %d  %s"
            % (task, m.split("__")[-1], gap, len(inf), tag or "NOTHING RUNNING")
        )
print("k=4 total short: %d" % tot)

print()
print("=== Gemini k=10 holes ===")
g = 0
for task in sorted(tasks):
    for m in GEMINI:
        gap = max(0, 10 - len(scored[task][m]))
        if not gap:
            continue
        g += gap
        inf = live.get((task, m), [])
        print(
            "  %-16s %-42s short %d   in flight %d"
            % (task, m.split("__")[-1], gap, len(inf))
        )
print("gemini k=10 total short: %d" % g)
