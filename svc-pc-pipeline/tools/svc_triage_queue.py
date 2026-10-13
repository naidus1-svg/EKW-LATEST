#!/usr/bin/env python3
"""Order the SVC-PC lane queue by expected effort and mark small-finding tasks for targeted-fix mode.

Why (2026-09-22): 75 graded rejects on 20 lanes. Every task got a 50-minute wholesale Opus rebuild, the
1-major near-passes waited behind 20-major tasks, and a single 1.4 finding (10-5-0) got the same treatment as
five categories at once. Ordering by the latest return's MAJOR count gets finished zips out sooner, and a
task with <= 2 majors starts in targeted-fix mode (the runner reads `_v7/targeted.txt`).

Per task, the latest `*_with_runs*.zip` in /root/qc/_returns holding it is parsed with
svc_dataos_returns_parse.py; the sort key is (total majors across seats, number of categories). Tasks with no
return keep their place at the end. Tasks currently claimed are left in the file untouched (the pool skips
claimed tasks anyway). Dry run by default; --apply writes queue.txt (backup kept) and targeted.txt.

Usage (sandbox): python3 /root/qc/tools/svc_triage_queue.py [--apply] [--max-targeted-majors 2]
"""

import argparse, glob, json, os, shutil, subprocess, sys, time, zipfile

Q = "/root/qc"
W = Q + "/_v7"
HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-targeted-majors", type=int, default=2)
    a = ap.parse_args()
    queue = [l.strip() for l in open(W + "/queue.txt") if l.strip()]
    zips = sorted(
        glob.glob(Q + "/_returns/*_with_runs*.zip"), key=os.path.getmtime, reverse=True
    )
    latest = {}
    for z in zips:
        try:
            for t in {n.split("/")[0] for n in zipfile.ZipFile(z).namelist()}:
                latest.setdefault(t, z)
        except zipfile.BadZipFile:
            continue
    parsed = {}
    for z in {latest[t] for t in queue if t in latest}:
        out = "/tmp/_triage_%d.json" % abs(hash(z))
        subprocess.run(
            [
                sys.executable,
                os.path.join(HERE, "svc_dataos_returns_parse.py"),
                z,
                "--out",
                out,
            ],
            capture_output=True,
            check=True,
        )
        parsed[z] = json.load(open(out))
    # info[t] = (majors, categories, clean seats). Sort key leads with clean seats, most first: a task where one
    # DataOS seat already returned 0 majors is one seat from passing, so it goes ahead of a task with fewer
    # total majors spread across both seats (2026-09-23: 1-of-2 near-misses were queued behind 0-of-2 tasks).
    info = {}
    for t in queue:
        if t not in latest:
            info[t] = (10**6, 99, 0)
            continue
        revs = [
            r
            for r in parsed[latest[t]].get(t, {}).get("reviews", [])
            if r.get("parsed")
        ]
        nmaj = sum(r.get("major_count", 0) for r in revs)
        cats = {str(c).split()[0] for r in revs for c in (r.get("majors") or [])}
        clean = sum(1 for r in revs if r.get("major_count", 0) == 0)
        info[t] = (nmaj, len(cats), clean)
    ordered = sorted(queue, key=lambda t: (-info[t][2], info[t][0], info[t][1]))
    # Pinned priority (_v7/priority.txt, one task per line, in order) always leads the queue, whatever the major
    # count. 2026-09-23: L3 tasks were put at the head for a same-night deadline; the next return's triage would
    # have re-sorted them back into the middle.
    pin_p = W + "/priority.txt"
    pins = (
        [l.strip() for l in open(pin_p) if l.strip()] if os.path.exists(pin_p) else []
    )
    pins = [t for t in pins if t in ordered]
    ordered = pins + [t for t in ordered if t not in pins]
    targeted = [t for t in ordered if info[t][0] <= a.max_targeted_majors]
    for t in ordered:
        print(
            "%-15s clean=%s majors=%-4s categories=%s%s"
            % (
                t,
                info[t][2],
                info[t][0] if info[t][0] < 10**6 else "-",
                info[t][1],
                "  [targeted]" if t in targeted else "",
            )
        )
    print(
        "\n%d tasks; %d targeted (<= %d majors)"
        % (len(ordered), len(targeted), a.max_targeted_majors)
    )
    if not a.apply:
        print("DRY RUN.")
        return
    ts = int(time.time())
    shutil.copy(W + "/queue.txt", W + "/queue.txt.bak.%d" % ts)
    open(W + "/queue.txt", "w").write("\n".join(ordered) + "\n")
    open(W + "/targeted.txt", "w").write("\n".join(targeted) + "\n")
    print(
        "applied: queue.txt reordered (backup .bak.%d), targeted.txt = %d"
        % (ts, len(targeted))
    )


if __name__ == "__main__":
    main()
