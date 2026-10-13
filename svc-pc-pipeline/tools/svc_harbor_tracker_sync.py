"""Sync the Work Tracker `Evals` tab to the coverage contract in EVAL_RUNBOOK.md section 10e.

Two jobs. It corrects per-model cells that were hand-counted from `status.json` alone, and it
appends the provenance columns R to Y that state each population with its own denominator, so
a reader no longer has to know which model answers to which k.

Why it is needed. On 2026-09-08 the tab held `3` for SVC-PC-6-1-0 opus, `3` for SVC-PC-6-5-0
terra and `7` for SVC-PC-7-3-0 gemini-3.7-flash. Those three numbers are exactly the
`status.json`-only read; the repair runs for those cells wrote their reward only to
`verifier/reward.json`. A session read the tab, reported 958 of 960, and was correctly
reporting a tracker that was wrong.

Safety. The base check and the write live in the same conditional. On 2026-09-01 a size check
printed MISMATCH and the push ran anyway because the two sat in separate blocks. Nothing is
written unless every cell this script intends to change still holds the value it was built
against, and the result is read back and compared.

Dry run by default. Pass --apply to write.

    python tools/svc_harbor_coverage.py --task-csv bytask.csv --csv cells.csv
    python tools/svc_harbor_tracker_sync.py --task-csv bytask.csv --cell-csv cells.csv
    python tools/svc_harbor_tracker_sync.py --task-csv bytask.csv --cell-csv cells.csv --apply
"""

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

SHEET = "19nP1_WyfGqR-q5MMUGrKeIE-JELZPazkgoHWt3qVU1A"
TAB = "Evals"
API = "https://sheets.googleapis.com/v4/spreadsheets"

# Sheet column -> (model slug, cap). The cap is that model's own k, and it differs by column:
# the two Gemini columns hold the k=10 top-up figure, the rest hold the k=4 board figure.
# This asymmetry is the tab's existing convention and section 10e now documents it.
MODEL_COLS = {
    "H": ("anthropic__claude-opus-5", 4),
    "I": ("openai__gpt-5.6-sol", 4),
    "J": ("openai__gpt-5.6-terra", 4),
    "K": ("google__gemini-3.1-pro-preview-customtools", 10),
    "M": ("google__gemini-3.7-flash", 10),
    "N": ("anthropic__claude-sonnet-5", 4),
}

PROV_HEADERS = [
    ("R", "Board k=4 scored (of 24)"),
    ("S", "Board k=4 complete"),
    ("T", "Gemini k=10 scored (of 20)"),
    ("U", "Gemini k=10 complete"),
    ("V", "Runs scored only in verifier/reward.json"),
    ("W", "Revisions counted"),
    ("X", "Counted as of (UTC)"),
    ("Y", "Counted by"),
]

GEMINI_HEADER_FIX = {
    "K": "Gemini 3.1 Pro (k=10 top-up)",
    "M": "Gemini 3.7 Flash (k=10 top-up)",
}


def tok():
    t = os.popen("gcloud auth print-access-token").read().strip()
    if len(t) < 40:
        sys.exit("no access token; run: gcloud.cmd auth login --enable-gdrive-access")
    return t


def call(method, path, body=None):
    u = API + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(u, data=data, method=method)
    r.add_header("Authorization", "Bearer " + tok())
    r.add_header("Content-Type", "application/json")
    try:
        return json.load(urllib.request.urlopen(r, timeout=300))
    except urllib.error.HTTPError as e:
        sys.exit("HTTP %s on %s: %s" % (e.code, path, e.read()[:400]))


def get_values(rng):
    return call(
        "GET",
        "/%s/values/%s?majorDimension=ROWS" % (SHEET, urllib.parse.quote(rng)),
    ).get("values", [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-csv", required=True)
    ap.add_argument("--cell-csv", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    bytask = {r["task"]: r for r in csv.DictReader(open(args.task_csv))}
    cells = {}
    for r in csv.DictReader(open(args.cell_csv)):
        cells[(r["task"], r["model"])] = int(r["scored_runs"])

    rows = get_values("%s!A1:AF200" % TAB)
    if not rows:
        sys.exit("Evals tab read returned nothing")
    header = rows[0]

    # rownum is 1-based in A1 notation; rows[0] is sheet row 1
    svc_rows = {}
    for idx, r in enumerate(rows[1:], start=2):
        if r and r[0].startswith("SVC-PC-"):
            svc_rows[r[0]] = (idx, r)

    print("Evals tab: %d rows read, %d SVC rows found" % (len(rows), len(svc_rows)))
    missing = sorted(set(bytask) - set(svc_rows))
    extra = sorted(set(svc_rows) - set(bytask))
    if missing:
        print("  in coverage but not on the tab: %s" % ", ".join(missing))
    if extra:
        print("  on the tab but not in coverage: %s" % ", ".join(extra))

    def cell(rowlist, colletter):
        i = ord(colletter) - ord("A")
        return rowlist[i] if i < len(rowlist) else ""

    # ---- build the intended changes, and the base each one was built against ----------
    updates = []  # (range, new_value, old_value, label)

    for col, want in GEMINI_HEADER_FIX.items():
        old = cell(header, col)
        if old != want:
            updates.append(("%s!%s1" % (TAB, col), want, old, "header %s" % col))

    for col, text in PROV_HEADERS:
        old = cell(header, col)
        if old != text:
            updates.append(("%s!%s1" % (TAB, col), text, old, "header %s" % col))

    model_fixes = 0
    for task in sorted(bytask):
        if task not in svc_rows:
            continue
        rownum, rowlist = svc_rows[task]
        t = bytask[task]

        for col, (slug, cap) in MODEL_COLS.items():
            have = cells.get((task, slug))
            if have is None:
                continue
            want = str(min(have, cap))
            old = cell(rowlist, col)
            if old != want:
                model_fixes += 1
                updates.append(
                    (
                        "%s!%s%d" % (TAB, col, rownum),
                        want,
                        old,
                        "%s %s" % (task, slug.split("__")[-1]),
                    )
                )

        prov = {
            "R": "%s" % t["board_k4_scored"],
            "S": t["board_complete"],
            "T": "%s" % t["topup_k10_scored"],
            "U": t["topup_complete"],
            "V": t["reward_json_only_runs"],
            "W": t["revisions_counted"],
            "X": t["counted_as_of_utc"],
            "Y": t["counted_by"],
        }
        for col, want in prov.items():
            old = cell(rowlist, col)
            if old != want:
                updates.append(
                    (
                        "%s!%s%d" % (TAB, col, rownum),
                        want,
                        old,
                        "%s prov %s" % (task, col),
                    )
                )

    print()
    print("=== intended changes: %d cell(s) ===" % len(updates))
    print("  per-model corrections: %d" % model_fixes)
    for rng, new, old, label in updates:
        if "prov" in label or label.startswith("header"):
            continue
        print("  %-22s %-40s %r -> %r" % (rng, label, old, new))
    print("  (plus %d provenance/header cells)" % (len(updates) - model_fixes))

    if not updates:
        print("nothing to change")
        return 0

    if not args.apply:
        print()
        print("DRY RUN. nothing written. re-run with --apply")
        return 0

    # ---- base check and write, in one conditional -------------------------------------
    # Re-read immediately before writing and confirm every target cell still holds the
    # value this diff was computed against. If any moved, another writer got there first.
    fresh = get_values("%s!A1:AF200" % TAB)
    fresh_idx = {}
    for idx, r in enumerate(fresh, start=1):
        fresh_idx[idx] = r

    def fresh_cell(rng):
        col = rng.split("!")[1][0]
        rownum = int(rng.split("!")[1][1:])
        r = fresh_idx.get(rownum, [])
        i = ord(col) - ord("A")
        return r[i] if i < len(r) else ""

    drift = [
        (rng, old, fresh_cell(rng))
        for rng, new, old, label in updates
        if fresh_cell(rng) != old
    ]
    if drift:
        print()
        print("BASE CHECK FAILED, nothing written. %d cell(s) moved:" % len(drift))
        for rng, expected, actual in drift[:20]:
            print("  %s expected %r, found %r" % (rng, expected, actual))
        return 1

    body = {
        "valueInputOption": "RAW",
        "data": [{"range": rng, "values": [[new]]} for rng, new, old, label in updates],
    }
    res = call("POST", "/%s/values:batchUpdate" % SHEET, body)
    print()
    print(
        "wrote %s cell(s) across %s range(s)"
        % (res.get("totalUpdatedCells"), res.get("totalUpdatedRanges"))
    )

    # ---- read back ---------------------------------------------------------------------
    after = get_values("%s!A1:AF200" % TAB)
    after_idx = {idx: r for idx, r in enumerate(after, start=1)}

    def after_cell(rng):
        col = rng.split("!")[1][0]
        rownum = int(rng.split("!")[1][1:])
        r = after_idx.get(rownum, [])
        i = ord(col) - ord("A")
        return r[i] if i < len(r) else ""

    bad = [
        (rng, new, after_cell(rng))
        for rng, new, old, label in updates
        if after_cell(rng) != new
    ]
    if bad:
        print("READ-BACK MISMATCH on %d cell(s):" % len(bad))
        for rng, want, got in bad[:20]:
            print("  %s wanted %r, got %r" % (rng, want, got))
        return 1
    print("read-back matches on all %d cell(s)" % len(updates))
    return 0


if __name__ == "__main__":
    sys.exit(main())
