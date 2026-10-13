"""Record the xAI Grok Build run in the Work Tracker.

Shane McCracken asked for the 40 published SVC tasks on Grok Build. This records what
actually ran through Camus's PR 931 preview on 2026-09-10.

Why Grok Build needs its own column

  Column O of the Evals tab is `Grok 4.6` and already holds 18 values from the earlier
  **opencode** run. Grok Build is a different harness, so its numbers do not belong in the
  same column: two harnesses in one column is the same not-comparable-metrics error as
  putting a k=4 board count and a k=10 top-up count on one axis. This writes a separate
  `Grok 4.6 (Grok Build)` column instead.

Why the score must come from verifier/reward.json

  harbor 0.20's post-run validator reads a valid verifier-report.json as empty, so every
  Grok Build trial carries `reward: null` in trial_status/status.json and survives only on a
  verdict-agent accept. A status.json-only reader reports the whole run unscored. Runbook 10e
  already allows either source; this tool reads reward.json and says so in the provenance.

Why the agent is checked per task-execution

  The GCS path is `xai__grok-4.6` and does NOT encode the harness, so a Grok Build trial and
  an opencode trial are indistinguishable by path. The harness is only in the job's
  config.json, as `agent: {"name": "grok-build", ..., "kwargs": {"version": "1.0.25"}}`. This
  reads one config per task-execution and refuses to count anything that does not say
  grok-build.

Safety: base check and write in one conditional, read back after, dry run by default.

    python tools/svc_grok_build_tracker_sync.py
    python tools/svc_grok_build_tracker_sync.py --apply
"""

import argparse
import collections
import csv
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from eval_counting import choose_executions, describe

SHEET = "19nP1_WyfGqR-q5MMUGrKeIE-JELZPazkgoHWt3qVU1A"
EVALS_TAB = "Evals"
EXEC_TAB = "Eval Executions"
API = "https://sheets.googleapis.com/v4/spreadsheets"

BUCKET = "long-horizon-evals-beta"
SLUG = "xai__grok-4.6"
AGENT = "grok-build"
MODEL_DISPLAY = "Grok 4.6 (Grok Build)"
MODEL_COL = "Z"
MODEL_HEADER = "Grok 4.6 (Grok Build) k=4"
K = 4
TEAM = "SVC"
OFFERING = "OTS"
COUNTED_BY = "tools/svc_grok_build_tracker_sync.py"

ENV = {
    **os.environ,
    "CLOUDSDK_CORE_DISABLE_PROMPTS": "1",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
}

TRIAL_RE = re.compile(
    r"/evals/(SVC-PC-[0-9-]+)/(v\d+)/execution_(\d+)/"
    + re.escape(SLUG)
    + r"/trial_(\d+)/"
)


def gcloud(args, timeout=1800):
    return subprocess.run(
        ["gcloud.cmd"] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=ENV,
        timeout=timeout,
    )


def listing():
    r = gcloud(
        ["storage", "ls", "-r", "gs://{}/evals/SVC-PC-*/**/{}/**".format(BUCKET, SLUG)]
    )
    lines = [
        l.strip()
        for l in (r.stdout or "").splitlines()
        if l.strip().startswith("gs://")
    ]
    if r.returncode != 0 and not lines:
        sys.exit(
            "listing failed, exit %s: %s" % (r.returncode, (r.stderr or "")[-300:])
        )
    if len(lines) < 50:
        sys.exit(
            "listing returned only %d lines, which is below any plausible floor for a run "
            "of 112 trials. A partial read is not an absence, see runbook 21d."
            % len(lines)
        )
    return lines


def tok():
    t = gcloud(["auth", "print-access-token"], timeout=180).stdout.strip()
    if len(t) < 40:
        sys.exit("no access token; run: gcloud.cmd auth login --enable-gdrive-access")
    return t


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(API + path, data=data, method=method)
    r.add_header("Authorization", "Bearer " + tok())
    r.add_header("Content-Type", "application/json")
    try:
        return json.load(urllib.request.urlopen(r, timeout=300))
    except urllib.error.HTTPError as e:
        sys.exit("HTTP %s on %s: %s" % (e.code, path, e.read()[:400]))


def get_values(rng):
    return call(
        "GET", "/%s/values/%s?majorDimension=ROWS" % (SHEET, urllib.parse.quote(rng))
    ).get("values", [])


def cell(rows, rownum, col):
    i = rownum - 1
    if i >= len(rows):
        return ""
    j = 0
    for ch in col:
        j = j * 26 + (ord(ch) - 64)
    j -= 1
    row = rows[i]
    return (row[j] if len(row) > j else "").strip()


def colidx(col):
    j = 0
    for ch in col:
        j = j * 26 + (ord(ch) - 64)
    return j - 1


def agent_of(paths):
    """Harness name out of a job config.json, or None."""
    for p in paths:
        r = gcloud(["storage", "cat", p], timeout=180)
        if r.returncode != 0:
            continue
        try:
            d = json.loads(r.stdout)
        except Exception:
            continue
        stack = [d]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                a = o.get("agent")
                if isinstance(a, dict) and a.get("name"):
                    return a["name"], (a.get("kwargs") or {}).get("version")
                stack.extend(o.values())
            elif isinstance(o, list):
                stack.extend(o)
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--csv", default="_scratch_grok_build_tracker.csv")
    ap.add_argument("--skip-executions", action="store_true")
    a = ap.parse_args()

    print("listing %s ..." % BUCKET, flush=True)
    lines = listing()
    print("listing: %d objects" % len(lines))

    scored = collections.defaultdict(dict)  # (task, exec) -> {trial: path}
    configs = collections.defaultdict(list)  # (task, exec) -> [config paths]
    leases = set()
    for l in lines:
        m = TRIAL_RE.search(l)
        if not m:
            continue
        key = (m.group(1), int(m.group(3)))
        trial = int(m.group(4))
        if l.endswith("verifier/reward.json") and "/retry_archive/" not in l:
            scored[key][trial] = l
        if l.endswith("/config.json"):
            configs[key].append(l)
        if l.endswith("trial_status/lease.json"):
            leases.add((key, trial))

    print("task-executions seen : %d" % len(set(list(scored) + list(configs))))
    print("scored trials        : %d" % sum(len(v) for v in scored.values()))
    print("leases in flight     : %d" % len(leases))

    # harness check, one config read per task-execution
    print("\nchecking the harness per task-execution ...", flush=True)
    keep, rejected, versions = {}, {}, collections.Counter()
    for key in sorted(scored):
        name, ver = agent_of(configs.get(key, [])[:2])
        if name == AGENT:
            keep[key] = scored[key]
            versions[ver or "unknown"] += 1
        else:
            rejected[key] = name or "no config readable"
    print("  grok-build  : %d task-execution(s)" % len(keep))
    print("  other/unknown: %d  %s" % (len(rejected), list(rejected.items())[:4]))
    if versions:
        print("  grok-build versions seen: %s" % dict(versions))
    if not keep:
        sys.exit("nothing confirmed as grok-build, refusing to write")

    # fetch rewards
    print("\nreading rewards from verifier/reward.json ...", flush=True)
    per = collections.defaultdict(list)
    for key, trials in sorted(keep.items()):
        for trial, path in sorted(trials.items()):
            r = gcloud(["storage", "cat", path], timeout=180)
            if r.returncode != 0:
                continue
            try:
                rw = json.loads(r.stdout).get("reward")
            except Exception:
                continue
            if rw is not None:
                per[key].append((trial, float(rw)))
    print("  rewards read: %d" % sum(len(v) for v in per.values()))

    stamp = subprocess.run(
        ["date", "-u", "+%Y-%m-%d %H:%MZ"], capture_output=True, text=True
    ).stdout.strip()
    if not stamp:
        import datetime

        stamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%MZ")

    # One row per task. An execution that scored a full k on its own IS the canonical
    # set, so it wins outright. Where no execution reaches k alone, the later partial
    # was fired to add the trials the first never got to, so they combine and cap at k:
    # SVC-PC-1-5-0 ran the pilot in execution_2 and three more in execution_3, and
    # taking only the most complete execution read it as 3 of 4 and dropped the task
    # out of the tracker entirely. Taking every trial from both is not cherry-picking;
    # taking a favourable subset would be.
    by_task = collections.defaultdict(dict)
    for (task, ex), rws in per.items():
        by_task[task][ex] = rws

    # The rule lives in tools/eval_counting.py, pinned by tools/test_eval_counting.py.
    best = {}
    for task, byex in by_task.items():
        reward_of = {(ex, tr): rw for ex, pairs in byex.items() for tr, rw in pairs}
        take, mode, dropped = choose_executions(
            {ex: [tr for tr, _ in pairs] for ex, pairs in byex.items()}, K
        )
        best[task] = (
            describe(mode, take, dropped, K),
            [(tr, reward_of[(ex, tr)]) for ex, tr in take],
        )

    complete = {t: v for t, v in best.items() if len(v[1]) >= K}
    print("\ntasks with a full k=%d : %d of %d" % (K, len(complete), len(best)))

    with io.open(a.csv, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["task", "execution", "scored", "mean_reward", "rewards"])
        for t in sorted(best):
            ex, rws = best[t]
            vals = [r for _, r in rws]
            w.writerow(
                [
                    t,
                    ex,
                    len(vals),
                    round(sum(vals) / len(vals), 4) if vals else "",
                    " ".join("%.4f" % v for v in vals),
                ]
            )
    print("wrote %s" % a.csv)

    # ---- Evals tab ----
    evals_rows = get_values("%s!A1:AJ400" % EVALS_TAB)
    hdr_now = cell(evals_rows, 1, MODEL_COL)
    row_of = {}
    for n, r in enumerate(evals_rows, start=1):
        tid = (r[0] if len(r) > 0 else "").strip()
        if tid:
            row_of.setdefault(tid, n)

    print("\n=== Evals tab ===")
    print("  %s header now  %r, want %r" % (MODEL_COL, hdr_now, MODEL_HEADER))
    updates = []
    missing = []
    for t in sorted(complete):
        if t not in row_of:
            missing.append(t)
            continue
        n = row_of[t]
        want = str(min(len(complete[t][1]), K))
        cur = cell(evals_rows, n, MODEL_COL)
        if cur != want:
            updates.append((n, t, cur, want))
    print("  tasks with a row : %d" % (len(complete) - len(missing)))
    if missing:
        print("  tasks with NO row in the tab: %d  %s" % (len(missing), missing[:6]))
    print("  cells to write   : %d" % len(updates))
    for n, t, cur, want in updates[:5]:
        print("    row %-4d %-14s %s -> %s" % (n, t, cur or "(blank)", want))
    if len(updates) > 5:
        print("    ... %d more" % (len(updates) - 5))

    if hdr_now not in ("", MODEL_HEADER):
        sys.exit(
            "column %s already reads %r. Pick another column rather than overwriting."
            % (MODEL_COL, hdr_now)
        )

    # ---- Eval Executions ----
    exec_append = []
    if not a.skip_executions:
        ex_rows = get_values("%s!A1:F20000" % EXEC_TAB)
        # The execution belongs in the dedup key. Trial numbers repeat across executions
        # once a top-up fires, so (task, model, trial) alone collapses execution_2
        # trial_1 and execution_3 trial_1 into one row and loses a real trial.
        have = {
            (
                (r[0] or "").strip(),
                (r[1] or "").strip(),
                (r[2] or "").strip(),
                (r[3] or "").strip(),
            )
            for r in ex_rows[1:]
            if len(r) > 3
        }
        for (task, ex), rws in sorted(per.items()):
            for trial, _ in sorted(rws):
                keyt = (task, "execution_%d" % ex, MODEL_DISPLAY, "trial_%d" % trial)
                if keyt in have:
                    continue
                gcs = "gs://%s/evals/%s/execution_%d/%s/trial_%d/" % (
                    BUCKET,
                    task,
                    ex,
                    SLUG,
                    trial,
                )
                exec_append.append(
                    [
                        task,
                        "execution_%d" % ex,
                        MODEL_DISPLAY,
                        "trial_%d" % trial,
                        gcs,
                        "",
                    ]
                )
        print("\n=== Eval Executions tab ===")
        print("  rows now       : %d" % (len(ex_rows) - 1))
        print("  rows to append : %d" % len(exec_append))

    if not a.apply:
        print("\nDRY RUN. Nothing written.")
        return

    # ---- base check and write, one conditional ----
    fresh = get_values("%s!A1:AJ400" % EVALS_TAB)
    ok = (
        len(fresh) == len(evals_rows)
        and cell(fresh, 1, MODEL_COL) == hdr_now
        and all(cell(fresh, n, MODEL_COL) == cur for n, t, cur, want in updates)
    )
    if not ok:
        sys.exit(
            "BASE MISMATCH, nothing written. The sheet changed under us; re-run the "
            "dry run."
        )

    if hdr_now != MODEL_HEADER:
        call(
            "PUT",
            "/%s/values/%s?valueInputOption=RAW"
            % (SHEET, urllib.parse.quote("%s!%s1" % (EVALS_TAB, MODEL_COL))),
            {"values": [[MODEL_HEADER]]},
        )
        print("wrote header %s = %r" % (MODEL_COL, MODEL_HEADER))

    data = []
    for n, t, cur, want in updates:
        data.append(
            {"range": "%s!%s%d" % (EVALS_TAB, MODEL_COL, n), "values": [[want]]}
        )
        data.append({"range": "%s!X%d" % (EVALS_TAB, n), "values": [[stamp]]})
        data.append({"range": "%s!Y%d" % (EVALS_TAB, n), "values": [[COUNTED_BY]]})
    if data:
        call(
            "POST",
            "/%s/values:batchUpdate" % SHEET,
            {"valueInputOption": "RAW", "data": data},
        )
        print("wrote %d cell(s) across %d row(s)" % (len(data), len(updates)))

    if exec_append:
        res = call(
            "POST",
            "/%s/values/%s:append?valueInputOption=RAW"
            "&insertDataOption=INSERT_ROWS"
            % (SHEET, urllib.parse.quote("%s!A1" % EXEC_TAB)),
            {"values": exec_append},
        )
        print(
            "appended %s to Eval Executions"
            % res.get("updates", {}).get("updatedRange")
        )

    after = get_values("%s!A1:AJ400" % EVALS_TAB)
    bad = [
        (t, cell(after, n, MODEL_COL), want)
        for n, t, cur, want in updates
        if cell(after, n, MODEL_COL) != want
    ]
    print("\n=== read-back ===")
    print("  header %s reads %r" % (MODEL_COL, cell(after, 1, MODEL_COL)))
    if bad:
        print("  MISMATCH: %s" % bad[:5])
    else:
        print("  read-back matches on all %d row(s)" % len(updates))


if __name__ == "__main__":
    main()
