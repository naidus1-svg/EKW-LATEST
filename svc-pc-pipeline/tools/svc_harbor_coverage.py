"""Print the SVC eval coverage matrix with its denominator, its populations and its sources.

Why this exists. On 2026-09-08 two sessions reported the same run as complete and as two
runs short, and neither was checkable, because every tool we had printed only a shortfall.
`holes.py` prints "k=4 total short: 0" whether it found 40 tasks or 38, so a zero could mean
finished or could mean the enumeration missed a task and nobody would see the difference.
`stallwatch.py` has the same shape. A number with no denominator cannot be reconciled against
another number with no denominator.

So this prints the denominator first and the shortfall last. Four things it states outright
that the older tools left implicit, each of which produced a real wrong answer:

1. **The set and its size.** Every task id found, counted. A missing task shows up as a
   smaller denominator instead of as silence.

2. **Two populations, never summed.** The k=4 board is six models on every task. The Gemini
   k=10 top-up is two models on every task, and it is a SEPARATE deliverable, not part of the
   board. On 2026-09-08 a session put Gemini's k=10 figure (400) in a table whose other rows
   were k=4 (160) and totalled the mixed column against 960. Its own note admits the cause:
   "I'd been scoring Gemini against the k=10 Google top-up rather than the k=4 board."

3. **Which file the score came from.** A run is scored when `reward is not None` in EITHER
   `trial_status/status.json` OR `verifier/reward.json`. Camus moved the 2026-09-03 repair runs
   onto the default pipeline, which writes no reward field into status.json at all and puts the
   score only in verifier/reward.json. Reading status.json alone reported 7 finished runs as
   failures and left k=4 looking 2 short when it was already complete. This prints the split, so
   a tool reading one source shows up as a discrepancy rather than as a deficit.

4. **Every revision seen.** Revisions run past v30. A hardcoded allowlist of revision ids
   truncates the count silently: on 2026-09-08 a session filtered to 17 collected revision
   numbers and reported a Sonnet gap that did not exist, because Sonnet's run sat at v24.
   This uses a denylist of known-dead revisions, prints it, and prints the full census of what
   it actually found so a truncation is visible.

Read-only. Lists the bucket, reads status.json and reward.json, writes only local files.

Usage:
    python tools/svc_harbor_coverage.py                 # matrix to stdout
    python tools/svc_harbor_coverage.py --csv out.csv    # plus a per-cell CSV for the tracker
"""

import argparse
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

BUCKET = "long-horizon-evals-beta"
PREFIX = "evals/SVC"

# Revisions whose runs are dead and must not count. v1 holds the 545 trials from the stopped
# run that fail at 0 seconds; v3 was staged without its ready marker. This is a DENYLIST on
# purpose: an allowlist of "the revisions I saw" silently drops every revision staged later.
EXCLUDE_REVISIONS = {"v1", "v3"}

BOARD_MODELS = [
    "anthropic__claude-opus-5",
    "anthropic__claude-sonnet-5",
    "google__gemini-3.1-pro-preview-customtools",
    "google__gemini-3.7-flash",
    "openai__gpt-5.6-sol",
    "openai__gpt-5.6-terra",
]
# The k=10 top-up Google asked for. These two models appear in BOTH populations, at different
# k. That overlap is why a single per-model tracker cell cannot express the state.
TOPUP_MODELS = [
    "google__gemini-3.1-pro-preview-customtools",
    "google__gemini-3.7-flash",
]
BOARD_K = 4
TOPUP_K = 10

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
            + BUCKET
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


def cat(name):
    try:
        return json.loads(
            req(
                "https://storage.googleapis.com/storage/v1/b/"
                + BUCKET
                + "/o/"
                + urllib.parse.quote(name, safe="")
                + "?alt=media"
            )
            .read()
            .decode("utf-8", "replace")
        )
    except Exception:
        return None


# Object layout: evals/{task}/{revision}/{execution}/{model}/{trial}/{status|verifier}/file
# A run is identified by (task, model, revision, execution, trial).
def parse(name):
    p = name.split("/")
    if len(p) < 7:
        return None
    return {"task": p[1], "rev": p[2], "exe": p[3], "model": p[4], "trial": p[5]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="write a per-cell CSV here")
    ap.add_argument(
        "--task-csv",
        help="write a per-task CSV here, shaped for the Work Tracker Evals tab",
    )
    args = ap.parse_args()

    now = datetime.datetime.now(datetime.timezone.utc)
    items = listing(PREFIX)

    # Census of every revision present, before any filtering, so a denylist that is too
    # broad or an allowlist someone reintroduces is visible in the output.
    rev_census = collections.Counter()
    for i in items:
        d = parse(i["name"])
        if d:
            rev_census[d["rev"]] += 1

    score_files = []
    for i in items:
        n = i["name"]
        if not (
            n.endswith("/trial_status/status.json")
            or n.endswith("/verifier/reward.json")
        ):
            continue
        d = parse(n)
        if not d or d["rev"] in EXCLUDE_REVISIONS:
            continue
        score_files.append(n)

    def one(n):
        d = cat(n)
        if d is None:
            return None
        p = parse(n)
        src = (
            "status.json" if n.endswith("/trial_status/status.json") else "reward.json"
        )
        return (
            p["task"],
            p["model"],
            (p["rev"], p["exe"], p["trial"]),
            d.get("reward") is not None,
            src,
        )

    # scored[task][model] -> {run_key: set of sources that carried a reward for it}
    scored = collections.defaultdict(lambda: collections.defaultdict(dict))
    tasks = set()
    models_seen = set()
    with ThreadPoolExecutor(max_workers=24) as ex:
        for r in ex.map(one, score_files):
            if not r:
                continue
            task, model, key, ok, src = r
            tasks.add(task)
            models_seen.add(model)
            if ok:
                scored[task][model].setdefault(key, set()).add(src)

    tasks = sorted(tasks)

    print("=== SVC harbor eval coverage, %s ===" % now.strftime("%Y-%m-%d %H:%MZ"))
    print()
    print("Denominator, stated before any shortfall:")
    print("  tasks found in gs://%s/%s : %d" % (BUCKET, PREFIX, len(tasks)))
    print(
        "  revisions excluded as dead     : %s" % ", ".join(sorted(EXCLUDE_REVISIONS))
    )
    print(
        "  revisions actually present     : %s"
        % ", ".join(
            "%s(%d obj)" % (r, c)
            for r, c in sorted(rev_census.items(), key=lambda x: x[0])
        )
    )
    print("  model slugs present in bucket  : %d" % len(models_seen))
    for m in sorted(models_seen):
        mark = ""
        if m not in BOARD_MODELS:
            mark = "   <-- NOT on the board, excluded from both targets"
        print("     %s%s" % (m, mark))
    print()

    # --- population 1, the k=4 board -------------------------------------------------
    print(
        "--- POPULATION 1: the k=4 board. %d models x %d tasks x k=%d = %d runs ---"
        % (
            len(BOARD_MODELS),
            len(tasks),
            BOARD_K,
            len(BOARD_MODELS) * len(tasks) * BOARD_K,
        )
    )
    board_target = len(BOARD_MODELS) * len(tasks) * BOARD_K
    board_done = 0
    board_short = []
    for t in tasks:
        for m in BOARD_MODELS:
            have = len(scored[t][m])
            counted = min(have, BOARD_K)
            board_done += counted
            if have < BOARD_K:
                board_short.append((t, m, BOARD_K - have, have))
    print("  scored: %d of %d" % (board_done, board_target))
    if board_short:
        print("  cells below k=%d:" % BOARD_K)
        for t, m, gap, have in board_short:
            print(
                "    %-16s %-44s have %d, short %d" % (t, m.split("__")[-1], have, gap)
            )
    else:
        print("  cells below k=%d: none" % BOARD_K)
    print()

    # --- population 2, the Gemini k=10 top-up ---------------------------------------
    print(
        "--- POPULATION 2: the Gemini k=10 top-up. %d models x %d tasks x k=%d = %d runs ---"
        % (
            len(TOPUP_MODELS),
            len(tasks),
            TOPUP_K,
            len(TOPUP_MODELS) * len(tasks) * TOPUP_K,
        )
    )
    print(
        "  This is a separate deliverable. It is NOT part of population 1 and the two"
    )
    print("  totals are never added together.")
    topup_target = len(TOPUP_MODELS) * len(tasks) * TOPUP_K
    topup_done = 0
    topup_short = []
    for t in tasks:
        for m in TOPUP_MODELS:
            have = len(scored[t][m])
            counted = min(have, TOPUP_K)
            topup_done += counted
            if have < TOPUP_K:
                topup_short.append((t, m, TOPUP_K - have, have))
    print("  scored: %d of %d" % (topup_done, topup_target))
    if topup_short:
        print("  cells below k=%d:" % TOPUP_K)
        for t, m, gap, have in topup_short:
            print(
                "    %-16s %-44s have %d, short %d" % (t, m.split("__")[-1], have, gap)
            )
    else:
        print("  cells below k=%d: none" % TOPUP_K)
    print()

    # --- where the scores came from --------------------------------------------------
    only_status = only_reward = both = 0
    reward_only_runs = []
    for t in tasks:
        for m in sorted(models_seen):
            for key, srcs in scored[t][m].items():
                if srcs == {"status.json"}:
                    only_status += 1
                elif srcs == {"reward.json"}:
                    only_reward += 1
                    reward_only_runs.append((t, m, key))
                else:
                    both += 1
    total_runs = only_status + only_reward + both
    print(
        "--- Where each score came from, across %d distinct scored runs ---"
        % total_runs
    )
    print("  in status.json only  : %d" % only_status)
    print("  in reward.json only  : %d" % only_reward)
    print("  in both              : %d" % both)
    print(
        "  A tool reading status.json alone would report %d of these %d runs as unscored."
        % (only_reward, total_runs)
    )
    if reward_only_runs:
        print("  The reward.json-only runs, which are real and must be counted:")
        for t, m, key in sorted(reward_only_runs):
            print("    %-16s %-44s %s" % (t, m.split("__")[-1], "/".join(key)))
    print()

    print("=== VERDICT ===")
    print(
        "  k=4 board       : %s  (%d of %d, %d cell(s) short)"
        % (
            "COMPLETE" if not board_short else "INCOMPLETE",
            board_done,
            board_target,
            len(board_short),
        )
    )
    print(
        "  Gemini k=10     : %s  (%d of %d, %d cell(s) short)"
        % (
            "COMPLETE" if not topup_short else "INCOMPLETE",
            topup_done,
            topup_target,
            len(topup_short),
        )
    )
    print("  Never report a single combined figure. Two populations, two numbers.")

    if args.csv:
        rows = [
            "task,model,scored_runs,board_target,topup_target,from_status_only,from_reward_only,from_both"
        ]
        for t in tasks:
            for m in sorted(models_seen):
                cell = scored[t][m]
                s_only = sum(1 for v in cell.values() if v == {"status.json"})
                r_only = sum(1 for v in cell.values() if v == {"reward.json"})
                b = sum(1 for v in cell.values() if len(v) > 1)
                rows.append(
                    "%s,%s,%d,%s,%s,%d,%d,%d"
                    % (
                        t,
                        m,
                        len(cell),
                        BOARD_K if m in BOARD_MODELS else "",
                        TOPUP_K if m in TOPUP_MODELS else "",
                        s_only,
                        r_only,
                        b,
                    )
                )
        with open(args.csv, "w", encoding="utf-8") as fh:
            fh.write("\n".join(rows) + "\n")
        print()
        print("wrote %s, %d data rows" % (args.csv, len(rows) - 1))

    if args.task_csv:
        # One row per task, in the shape the Work Tracker Evals tab needs: each population
        # stated separately with its own denominator, plus the provenance that makes a stale
        # or single-source count visible instead of silent.
        stamp = now.strftime("%Y-%m-%d %H:%MZ")
        rows = [
            "task,board_k4_scored,board_k4_target,board_complete,"
            "topup_k10_scored,topup_k10_target,topup_complete,"
            "reward_json_only_runs,revisions_counted,counted_as_of_utc,counted_by"
        ]
        for t in tasks:
            b = sum(min(len(scored[t][m]), BOARD_K) for m in BOARD_MODELS)
            bt = len(BOARD_MODELS) * BOARD_K
            u = sum(min(len(scored[t][m]), TOPUP_K) for m in TOPUP_MODELS)
            ut = len(TOPUP_MODELS) * TOPUP_K
            ro = sum(
                1
                for m in models_seen
                for v in scored[t][m].values()
                if v == {"reward.json"}
            )
            revs = sorted(
                {k[0] for m in models_seen for k in scored[t][m]},
                key=lambda s: int(s[1:]) if s[1:].isdigit() else 0,
            )
            rows.append(
                "%s,%d,%d,%s,%d,%d,%s,%d,%s,%s,%s"
                % (
                    t,
                    b,
                    bt,
                    "Yes" if b == bt else "No",
                    u,
                    ut,
                    "Yes" if u == ut else "No",
                    ro,
                    " ".join(revs),
                    stamp,
                    "tools/svc_harbor_coverage.py",
                )
            )
        with open(args.task_csv, "w", encoding="utf-8") as fh:
            fh.write("\n".join(rows) + "\n")
        print("wrote %s, %d data rows" % (args.task_csv, len(rows) - 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
