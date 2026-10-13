"""Catch a trial that claimed a lease and never started, within minutes not hours.

The failure this exists for: a dispatched trial writes trial_status/lease.json, 125
bytes, and then nothing. No container, no logs, no exception. On 2026-09-03 four such
trials sat for 170 minutes while being reported as running, because the test in use was
"does it have an exception file" and a trial that never starts never throws one.

So the test here is the opposite. A live trial writes more than its lease within a few
minutes. One sitting at exactly one object past the grace period is dead and needs
refiring. Nothing else distinguishes the two from outside.

Read-only. Lists the bucket and reads status.json; writes nothing.
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
LOG = r"C:\evzuild\leasewatch.log"
CYCLE = 120
GRACE = 40.0  # minutes a lease may sit alone before it is FLAGGED, not condemned.
# Measured 2026-09-03: enqueue to first object ran 7.2 to 28.7 min, median 15.2.
#
# But a grace period alone is not a death test, and on 2026-09-03 it produced a false
# positive that nearly cost a good run. SVC-PC-6-3-0 sonnet v24 sat lease-only for 27
# minutes, was called dead, and two replacements were fired behind it. It then ran and
# scored 0.42. The cause was a 22-minute stall in which NOTHING anywhere in the bucket
# was written, so the trial was not stuck, the whole queue was.
#
# So a lease-only run is only evidence of a leak when dispatch is otherwise healthy.
# The check below requires both: this run silent past GRACE, AND other runs writing
# recently. If the bucket as a whole has gone quiet, that is a stall and nothing here
# is dead.
DISPATCH_ALIVE_MIN = 10.0  # bucket-wide write within this window means dispatch is up

# WATCH and FRESH are the 2026-09-03 incident's parameters, frozen at the moment this was
# written. Every pair below has since completed and revisions have run past v31, so edit both
# for the situation in front of you rather than trusting them. This is a lease-leak diagnostic
# for named pairs; it is not a completeness tool and cannot answer "is the run done".
# Use tools/svc_harbor_coverage.py for that.
WATCH = {
    ("SVC-PC-6-1-0", "anthropic__claude-opus-5"),
    ("SVC-PC-6-3-0", "anthropic__claude-sonnet-5"),
    ("SVC-PC-6-5-0", "openai__gpt-5.6-terra"),
    ("SVC-PC-12-1-0", "google__gemini-3.7-flash"),
    ("SVC-PC-7-3-0", "google__gemini-3.7-flash"),
}
FRESH = ("v22", "v23", "v24", "v25", "v26", "v27", "v28")

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


def T(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


say("leasewatch up. a run stuck at lease.json past %.0f min is called dead." % GRACE)
last = None
while True:
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        runs = collections.defaultdict(list)
        for o in listing("evals/SVC"):
            p = o["name"].split("/")
            if len(p) < 6 or p[2] not in FRESH:
                continue
            if (p[1], p[4]) not in WATCH:
                continue
            runs[(p[1], p[4], p[2], p[5])].append((o["name"], o["updated"]))

        newest_any = max((u for v in runs.values() for _, u in v), default=None)
        quiet = (now - T(newest_any)).total_seconds() / 60.0 if newest_any else 999.0
        dispatch_up = quiet < DISPATCH_ALIVE_MIN

        dead, alive, scored = [], [], []
        for k, v in runs.items():
            # Either file can carry the reward. status.json alone was the 958-of-960 bug:
            # the default pipeline writes no reward field into it. See EVAL_RUNBOOK 10e.
            st = [
                n
                for n, _ in v
                if n.endswith("/trial_status/status.json")
                or n.endswith("/verifier/reward.json")
            ]
            age = (now - T(min(u for _, u in v))).total_seconds() / 60.0
            if st:
                try:
                    d = json.loads(
                        req(
                            "https://storage.googleapis.com/storage/v1/b/"
                            + E
                            + "/o/"
                            + urllib.parse.quote(st[0], safe="")
                            + "?alt=media"
                        )
                        .read()
                        .decode("utf-8", "replace")
                    )
                except Exception:
                    d = {}
                if d.get("reward") is not None:
                    scored.append(k)
                    continue
            if len(v) == 1 and v[0][0].endswith("lease.json"):
                # dead requires BOTH conditions, see the note on GRACE
                (dead if (age > GRACE and dispatch_up) else alive).append((k, age))
            else:
                alive.append((k, age))

        now_state = (len(scored), len(dead), len(alive))
        if now_state != last:
            say(
                "scored %d   started and running %d   STUCK AT LEASE %d%s"
                % (
                    len(scored),
                    len(alive),
                    len(dead),
                    (
                        ""
                        if dispatch_up
                        else "   [DISPATCH STALLED %.0f min, nothing condemned]" % quiet
                    ),
                )
            )
            for k, age in sorted(dead, key=lambda x: -x[1]):
                say(
                    "   DEAD  %-14s %-22s %-4s %-8s  lease only, %.0f min"
                    % (k[0], k[1].split("__")[-1][:20], k[2], k[3], age)
                )
            for k, age in sorted(scored and [] or []):
                pass
            if scored:
                say(
                    "   scored: %s"
                    % ", ".join(
                        "%s/%s/%s" % (k[0].replace("SVC-PC-", ""), k[2], k[3])
                        for k in sorted(scored)
                    )
                )
            last = now_state
        time.sleep(CYCLE)
    except Exception as e:
        say("check failed: %s" % str(e)[:90])
        time.sleep(CYCLE)
