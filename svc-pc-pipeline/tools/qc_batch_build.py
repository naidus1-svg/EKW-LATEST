#!/usr/bin/env python3
"""qc_batch_build.py - plan and record one human-QC batch (SVC and EKW) from the consolidated sheet.

Process: svc-pc-pipeline/docs/qc-intake-process.md (source copy: turing-context ekw/qc-intake-process-2026-09-24.md), section "How we build and send a batch" (Khiem's decision,
2026-09-24).

What it does (dry run by default, nothing is written anywhere but the local --out folder):
  1. Reads the SVC and EKW tabs of the consolidated sheet with the Sheets API. Columns are found
     by header text, never by letter (an "Email Id" column was inserted at C on 2026-09-24). The live queue
     is everything above the "Put your tasks above" row; the "Rejected" and "Duplicates" sections below it
     are ignored.
  2. Picks rows ready for human QC: in the live queue, Task Available Status starts with "EQC ready"
     (includes "EQC Ready - Revision"), EQC Status blank (a value there means the old QC team already
     handled it: Done, Reject, In-progress, Skip - duplicate), the sheet's "Duplicate (auto)" column is
     blank, there is a DataOS task link (or a dataset link, whose task the browser step finds), and the
     "QC batch" column is empty.
  3. Removes duplicates: one row per task_name, keeping the lowest row (latest added). A task already sent
     in an earlier batch is never re-sent; if its row is a revision with EQC Status blank it is listed as a
     FIX for its original batch dataset. The sheet link can point at an archived version; the DataOS copy
     step copies the latest Ready version of each name (TFRL QC guideline 5), see plan.md.
  4. Stops if fewer than --min tasks are left (after the admin-access split, when --access is given).
  5. Splits by DataOS access, from --access (a CSV filled by the DataOS step: ws, task_name, task_id,
     dataset_id, dataset_name, role; start from the access_todo.csv the dry run writes). ADMIN tasks are grouped by source dataset, ready for DataOS "Copy tasks" into
     ONE new batch dataset. Non-admin tasks get one draft Slack ask per author (name + email from the
     sheet) and wait for the next batch. Without --access every task is "access not checked" and the
     tool writes access_todo.csv for the browser step to fill.
  6. Writes to --out: <BATCH>.plan.json (the exact rows, for --apply), <BATCH>.plan.md (readable plan and
     DataOS copy checklist), <BATCH>.gdoc.md (batch Google Doc body), <BATCH>.tfrl_qc_post.txt (draft
     #tfrl_qc request in the standard template), <BATCH>.access_asks.txt (draft author asks).
     Nothing is posted, shared or uploaded. Every outbound text goes through /draft and Khiem's yes.

  --apply --plan <BATCH>.plan.json, run after the batch dataset exists in DataOS:
     writes the batch name into the "QC batch" column (created at the far right if missing, additive
     only) and sets EQC Status to the sheet's "in progress" value, for exactly the plan's rows. Rows are
     re-located by task_name + DataOS link at write time (70 people edit this sheet, rows move), each
     target cell must still be empty/unchanged, old values are snapshotted to <BATCH>.snapshot.json, and
     every cell is read back after the write.

  Step 6 of the process (writing QC feedback into the task rows) is not built: where the QC team returns
  results is still open (process doc, "Open" item 1). See record_feedback() below.

Needs a gcloud token with Drive scope:  gcloud.cmd auth login --enable-gdrive-access

One batch holds both tabs by default (--ws ALL): SVC tasks first, EKW tasks under them, named QC_batch<N>.
--ws SVC or --ws EKW builds a single-tab batch (SVC_batch<N> / EKW_batch<N>). Numbering is shared.

Usage:
  python tools/qc_batch_build.py                               # dry run, both tabs, needs 50
  python tools/qc_batch_build.py --min 1                       # dry run, show the plan whatever the count
  python tools/qc_batch_build.py --access qc_batches/QC_batch1.access_todo.csv
  python tools/qc_batch_build.py --apply --plan qc_batches/QC_batch1.plan.json
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

SHEET = "15Z00RATLJt7QcyT_-Rc6Y0jYS9WmcqUpukKp08GwAZ8"
API = "https://sheets.googleapis.com/v4/spreadsheets"
BATCH_HEADER = "QC batch"
QUEUE_END_MARK = "put your tasks above"
TASK_LINK_RE = re.compile(r"data-os\.turing\.com/tasks/(\d+)")
DATASET_LINK_RE = re.compile(r"data-os\.turing\.com/datasets/(\d+)")
ACCESS_COLS = ["ws", "task_name", "task_id", "dataset_id", "dataset_name", "role"]
TFRL_QC_CHANNEL = "#tfrl_qc (C0BL126LECV)"

# header text (lowercased, stripped) -> matcher. The EKW tab spells it "Submittted By".
COLS = {
    "author": lambda h: h.startswith("submit"),
    "email": lambda h: h.startswith("email"),
    "gdoc": lambda h: h.startswith("google doc"),
    "task": lambda h: h == "task_name",
    "link": lambda h: h.startswith("link in data-os"),
    "avail": lambda h: h.startswith("task available status"),
    "eqc": lambda h: h == "eqc status",
    "batch": lambda h: h == BATCH_HEADER.lower(),
    "dupauto": lambda h: h.startswith(
        "duplicate"
    ),  # the sheet's own formula: "dup, row N counts"
    "resub": lambda h: h.startswith("resubmission"),
    "pa": lambda h: h.startswith("prompt ambiguity"),
    "ptm": lambda h: h.startswith("prompt-tests"),
    "tc": lambda h: h.startswith("test coverage"),
}
REQUIRED = ("author", "task", "link", "avail", "eqc")


# ---------------------------------------------------------------- Sheets API


def token() -> str:
    p = subprocess.run(
        ["gcloud.cmd", "auth", "print-access-token"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if p.returncode != 0 or not p.stdout.strip():
        sys.exit(
            "gcloud has no token. Run: gcloud.cmd auth login --enable-gdrive-access\n"
            + (p.stderr or "")[:400]
        )
    return p.stdout.strip()


def api(method: str, path: str, tok: str, body=None):
    url = f"{API}/{SHEET}{path}"
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {tok}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            sys.exit(
                f"Sheets API {method} {path} failed: {e.code}\n{e.read().decode()[:600]}"
            )
        except Exception as e:  # IncompleteRead, timeout, transient network
            last = e
            time.sleep(1.5 * (attempt + 1))
    sys.exit(f"Sheets API {method} {path} failed after retries: {last}")


def col_letter(idx0: int) -> str:
    s, n = "", idx0 + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def qrange(tab: str, a1: str) -> str:
    return "/values/" + urllib.parse.quote(f"'{tab}'!{a1}")


def read_tab(tab: str, tok: str) -> list[list[str]]:
    rows = api("GET", qrange(tab, "A1:ZZ5000"), tok).get("values", [])
    if not rows:
        sys.exit(f"tab {tab!r} is empty or missing")
    return rows


# ---------------------------------------------------------------- sheet model


def locate(rows: list[list[str]]) -> dict:
    """Column indexes by header text, queue end and section headings by text."""
    hdr = [str(c).strip().lower() for c in rows[0]]
    cols = {}
    for key, match in COLS.items():
        hits = [i for i, h in enumerate(hdr) if match(h)]
        if len(hits) > 1:
            sys.exit(
                f"header {key!r} matches {len(hits)} columns: {[rows[0][i] for i in hits]}"
            )
        if hits:
            cols[key] = hits[0]
    missing = [k for k in REQUIRED if k not in cols]
    if missing:
        sys.exit(f"header row is missing {missing}; header is {rows[0]}")

    def first_row(pred, start=1):
        return next(
            (
                i
                for i in range(start, len(rows))
                if pred([str(c).strip().lower() for c in rows[i]])
            ),
            None,
        )

    end = first_row(lambda r: any(QUEUE_END_MARK in c for c in r))
    rejected = first_row(lambda r: "rejected" in r[:2], (end or 1))
    dups = first_row(lambda r: "duplicates" in r[:2], (end or 1))
    if end is None:
        sys.exit(
            f"no row containing {QUEUE_END_MARK!r}; cannot tell where the live queue ends"
        )
    width = max(len(r) for r in rows)  # first free column is the far right
    return {
        "cols": cols,
        "queue_end": end,
        "rejected": rejected,
        "duplicates": dups,
        "width": width,
    }


def cell(row, i) -> str:
    return str(row[i]).strip() if i is not None and i < len(row) else ""


def live_rows(rows, loc) -> list[dict]:
    c = loc["cols"]
    out = []
    for i in range(1, loc["queue_end"]):
        r = rows[i]
        name = cell(r, c["task"])
        if not name:
            continue
        link = cell(r, c["link"])
        m = TASK_LINK_RE.search(link)
        d = DATASET_LINK_RE.search(link)
        out.append(
            {
                "row": i + 1,
                "task_name": name,
                "author": cell(r, c["author"]),
                "email": cell(r, c.get("email")),
                "gdoc": cell(r, c.get("gdoc")),
                "link": link,
                "task_id": m.group(1) if m else "",
                # some authors linked the dataset, not the task; the browser step finds the task in it
                "link_dataset": d.group(1) if d else "",
                "avail": cell(r, c["avail"]),
                "eqc": cell(r, c["eqc"]),
                "batch": cell(r, c.get("batch")),
                "dupauto": cell(r, c.get("dupauto")),
                "resub": cell(r, c.get("resub")),
                "major": any(
                    "major" in cell(r, c.get(k)).lower() for k in ("pa", "ptm", "tc")
                ),
            }
        )
    return out


def select(live: list[dict]) -> dict:
    """Classify every live row. Returns candidates plus every exclusion, with its reason."""
    batched = {r["task_name"]: r["batch"] for r in live if r["batch"]}
    excluded, fixes, pool = [], [], []
    for r in live:
        is_rev = "revision" in r["avail"].lower()
        if r["batch"] and not r["eqc"] and (r["task_id"] or r["link_dataset"]):
            # batched row whose EQC Status was cleared: the author replaced it in place with a fixed version
            # (FIN-322 and FIN-351, 2026-09-27). Batching writes In-progress, so blank here means a resubmission.
            fixes.append((r, r["batch"]))
        elif (
            r["batch"]
            and r["eqc"].lower().startswith("done")
            and r["major"]
            and r["resub"]
        ):
            # rejected row the author resubmitted in place without clearing it: new link plus a filled
            # "Resubmission changes" cell (SVC-PC-20-7-0 and SVC-PC-65-0-0, 2026-09-27)
            fixes.append((r, r["batch"]))
        elif r["batch"]:
            excluded.append((r, f"already sent in {r['batch']}"))
        elif not r["avail"].lower().startswith("eqc ready"):
            excluded.append((r, f"Task Available Status is {r['avail']!r}"))
        elif r["task_name"] in batched:
            if is_rev and r["eqc"]:
                excluded.append(
                    (r, f"revision already handled (EQC Status {r['eqc']!r})")
                )
            elif is_rev:
                fixes.append((r, batched[r["task_name"]]))
            else:
                excluded.append(
                    (r, f"same task already sent in {batched[r['task_name']]}")
                )
        elif r["eqc"]:
            excluded.append(
                (r, f"EQC Status already {r['eqc']!r} (old QC team handled it)")
            )
        elif r["dupauto"]:
            excluded.append((r, f"Duplicate (auto) column says {r['dupauto']}"))
        elif not r["task_id"] and not r["link_dataset"]:
            excluded.append((r, "no DataOS task or dataset link"))
        else:
            pool.append(r)
    # one row per task_name: keep the lowest row, the latest added
    by_name = defaultdict(list)
    for r in pool:
        by_name[r["task_name"]].append(r)
    cands, dropped = [], []
    for name, rs in by_name.items():
        rs.sort(key=lambda x: x["row"])
        cands.append(rs[-1])
        dropped += [(x, rs[-1]) for x in rs[:-1]]
    # the same DataOS task under two names is also a duplicate
    by_tid = defaultdict(list)
    for r in cands:
        if r["task_id"]:
            by_tid[r["task_id"]].append(r)
    for tid, rs in by_tid.items():
        if len(rs) > 1:
            rs.sort(key=lambda x: x["row"])
            for x in rs[:-1]:
                cands.remove(x)
                dropped.append((x, rs[-1]))
    cands.sort(key=lambda x: x["row"])
    return {
        "candidates": cands,
        "dropped": dropped,
        "excluded": excluded,
        "fixes": fixes,
    }


def next_batch_name(prefix: str, live: list[dict]) -> str:
    # one numbering across both tabs, so QC_batch, SVC_batch and EKW_batch never reuse a number
    nums = [
        int(m.group(1))
        for r in live
        if (m := re.search(r"_batch(\d+)$", r["batch"], re.I))
    ]
    return f"{prefix}_batch{max(nums, default=0) + 1}"


def load_access(path: str | None) -> dict:
    if not path:
        return {}
    out = {}
    # keyed by (tab, task_name): candidates are one row per task_name per tab, and dataset-link rows have
    # no task id until the DataOS step finds it
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = (row.get("task_name") or "").strip()
            if name:
                out[((row.get("ws") or "").strip(), name)] = {
                    k: (row.get(k) or "").strip() for k in ACCESS_COLS[2:]
                }
    return out


def write_access_todo(path: Path, rows: list[dict]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(ACCESS_COLS)
        for r in rows:
            w.writerow(
                [r["ws"], r["task_name"], r["task_id"], r["link_dataset"], "", ""]
            )


# ---------------------------------------------------------------- outputs

ROW_KEYS = ("ws", "row", "task_name", "task_id", "link", "author", "email")


def write_outputs(label, batch, sel, admin, no_admin, unchecked, out: Path, args):
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    plan = {
        "workstreams": label,
        "batch": batch,
        "created": stamp,
        "sheet": SHEET,
        "rows": [
            {k: r[k] for k in ROW_KEYS} | {"access": r.get("access", {})} for r in admin
        ],
        "waiting_for_access": [
            {k: r[k] for k in ROW_KEYS} | {"access": r.get("access", {})}
            for r in no_admin
        ],
        "access_not_checked": [{k: r[k] for k in ROW_KEYS} for r in unchecked],
        "fixes": [
            {
                "ws": r["ws"],
                "row": r["row"],
                "task_name": r["task_name"],
                "original_batch": b,
            }
            for r, b in sel["fixes"]
        ],
    }
    (out / f"{batch}.plan.json").write_text(
        json.dumps(plan, indent=2), encoding="utf-8"
    )
    if unchecked:
        write_access_todo(out / f"{batch}.access_todo.csv", unchecked)

    per_ws = Counter(r["ws"] for r in admin)
    md = [
        f"# {batch} plan ({stamp})",
        "",
        f"Tabs {label}. In the batch: {len(admin)} ({', '.join(f'{w} {n}' for w, n in per_ws.items())}). "
        f"Waiting for admin access: {len(no_admin)}. Access not checked yet: {len(unchecked)}. "
        f"Fixes for earlier batches: {len(sel['fixes'])}.",
        "",
    ]
    if admin:
        md += [
            "## DataOS copy checklist",
            "",
            f"Create one new dataset named `{batch}`. Then for each source dataset below, open it, tick exactly "
            f'these tasks, click "Copy tasks (N)", and copy into `{batch}`. Task names stay as they are.',
            "",
            "Version rule (TFRL QC guideline 5: the latest version in DataOS is the official one). The task id "
            "below is the one the author pasted on the sheet and can be stale: DataOS gives every re-upload a new "
            "id and archives the old one. In each source dataset, search the task NAME and copy its latest Ready "
            "version, not the listed id. After copying, check the batch dataset holds exactly one Ready task per "
            "name, and put the copied ids (not the sheet ids) in the Google Doc.",
            "",
        ]
        by_ds = defaultdict(list)
        for r in admin:
            a = r["access"]
            by_ds[(a.get("dataset_id", ""), a.get("dataset_name", ""))].append(r)
        for (dsid, dsname), rs in sorted(by_ds.items()):
            md.append(
                f"- dataset {dsname or '?'} (https://data-os.turing.com/datasets/{dsid}), {len(rs)} tasks:"
            )
            md += [f"  - [ ] {r['task_name']} (task {r['task_id']})" for r in rs]
        md.append("")
    for title, rs in (
        ("Waiting for admin access", no_admin),
        ("Access not checked yet", unchecked),
    ):
        if rs:
            md += [f"## {title}", ""]
            md += [
                f"- {r['ws']} row {r['row']}: {r['task_name']} (task {r['task_id']}), {r['author']}"
                for r in rs
            ]
            md += [""]
    if sel["fixes"]:
        md += [
            "## Fixes for earlier batches (upload into the ORIGINAL batch dataset, same name)",
            "",
            "Copy the fixed version into the original batch dataset. DataOS then archives the older same-name "
            "copy there on its own (seen 2026-09-25 on QC_batch1), so the batch keeps one Ready version per name. "
            "Update that row's link in the batch Google Doc, and write the batch name and the in-progress value "
            "into the revision row.",
            "",
        ]
        md += [
            f"- {r['ws']} row {r['row']}: {r['task_name']} -> {b}"
            for r, b in sel["fixes"]
        ] + [""]
    if sel["dropped"]:
        md += ["## Duplicates left out", ""]
        md += [
            f"- {x['ws']} row {x['row']}: {x['task_name']} (task {x['task_id']}), kept row {k['row']}"
            for x, k in sel["dropped"]
        ]
        md += [""]
    (out / f"{batch}.plan.md").write_text("\n".join(md), encoding="utf-8")

    # batch Google Doc body (Drive connector create_file, share qc@turing.com as writer). SVC rows come first.
    gdoc = [
        f"# {batch}",
        "",
        f"Tasks: {len(admin)} ({', '.join(f'{w} {n}' for w, n in per_ws.items())}). Dataset: {batch} "
        "(DataOS link to add after creation).",
        "",
        "Every task keeps its permanent name. Fixes after feedback are uploaded into this same dataset under "
        "the same name; the latest version in DataOS is the one to review. Contact: Khiem Doan.",
        "",
        "| # | Workstream | Task | DataOS task | Author |",
        "|---|---|---|---|---|",
    ]
    gdoc += [
        f"| {i} | {r['ws']} | {r['task_name']} | https://data-os.turing.com/tasks/{r['task_id']} | {r['author']} |"
        for i, r in enumerate(admin, 1)
    ]
    (out / f"{batch}.gdoc.md").write_text("\n".join(gdoc) + "\n", encoding="utf-8")

    post = [
        "Thread: QC",
        "Team: Andrew_team",
        f"Dataset: {batch}",
        "Dataset Link: (add after the batch dataset is created and shared with TFRL_QC)",
        "Google Doc Link: (add after the batch Google Doc is created)",
        f"Description: {' + '.join(per_ws)} batch of {len(admin)} tasks "
        f"({', '.join(f'{w} {n}' for w, n in per_ws.items())}), one copy per task, names unchanged, every task "
        "through automated DataOS QC. Fixes after your feedback go into this same dataset under the same task name.",
        f"Requested Deadline: {args.deadline or '(fill in)'}",
        "",
        "cc TFRL QC team: (tag the TFRL QC group here)",
    ]
    (out / f"{batch}.tfrl_qc_post.txt").write_text(
        f"DRAFT for {TFRL_QC_CHANNEL}. Not posted. Run it through /draft; Khiem posts after saying yes.\n\n"
        + "\n".join(post)
        + "\n",
        encoding="utf-8",
    )

    if no_admin:
        by_author = defaultdict(list)
        for r in no_admin:
            by_author[(r["author"], r["email"])].append(r)
        asks = [
            "DRAFTS, not sent. One per author. Run through /draft; Khiem sends after saying yes.",
            "",
        ]
        for (name, email), rs in sorted(by_author.items()):
            ds = sorted(
                {
                    (
                        r["access"].get("dataset_name")
                        or r["access"].get("dataset_id")
                        or "?"
                    )
                    for r in rs
                }
            )
            asks += [
                f"--- to {name} <{email or 'email missing on sheet'}>",
                f"Hi {name.split()[0] if name else 'there'}, I'm putting together the next QC batch. "
                f"Could you give me admin access to {', '.join(ds)} in DataOS? That's where "
                f"{', '.join(r['task_name'] for r in rs)} live{'s' if len(rs) == 1 else ''}, and I need admin "
                f"to copy {'it' if len(rs) == 1 else 'them'} into the batch. Thanks!",
                "",
            ]
        (out / f"{batch}.access_asks.txt").write_text("\n".join(asks), encoding="utf-8")


# ---------------------------------------------------------------- apply


def in_progress_value(rows, eqc_col) -> str:
    """Reuse the sheet's own spelling (the EKW tab says "In-progress")."""
    seen = Counter(
        cell(r, eqc_col)
        for r in rows[1:]
        if re.fullmatch(r"in[\s-]?progress", cell(r, eqc_col), re.I)
    )
    return seen.most_common(1)[0][0] if seen else "In progress"


def plan_tab_writes(ws: str, targets: list[dict], batch: str, tok: str):
    """Cells to write on one tab, or a list of problems if the sheet moved under the plan."""
    rows = read_tab(ws, tok)
    loc = locate(rows)
    c = loc["cols"]
    ipv = in_progress_value(rows, c["eqc"])
    writes, problems = [], []
    batch_col = c.get("batch")
    if batch_col is None:
        batch_col = loc["width"]
        if any(cell(r, batch_col) for r in rows):
            sys.exit(
                f"{ws}: far-right column is not empty; refusing to create the QC batch column"
            )
        writes.append((f"{col_letter(batch_col)}1", "", BATCH_HEADER))
        print(
            f"{ws}: creating column {col_letter(batch_col)} '{BATCH_HEADER}' (far right, additive)"
        )
    live = live_rows(rows, loc)
    for t in targets:
        hits = [
            r
            for r in live
            if r["task_name"] == t["task_name"]
            and r["link"] == t["link"]
            and not r["batch"]
        ]
        if len(hits) > 1:
            # An older row for the same task (already handled by the old QC team, same link, no batch label) can
            # sit above the resubmission; the planned row number decides, and it must still be one of the matches.
            hits = [r for r in hits if r["row"] == t.get("row")]
        if len(hits) != 1:
            problems.append(
                f"{ws} {t['task_name']}: {len(hits)} unsent matching rows now, expected 1"
            )
            continue
        r = hits[0]
        if r["eqc"]:
            problems.append(
                f"{ws} {t['task_name']} row {r['row']}: EQC Status changed to {r['eqc']!r} since the plan"
            )
            continue
        writes.append((f"{col_letter(batch_col)}{r['row']}", r["batch"], batch))
        writes.append((f"{col_letter(c['eqc'])}{r['row']}", r["eqc"], ipv))
    return writes, problems, ipv


def apply_plan(plan_path: Path, tok: str) -> int:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    batch, targets = plan["batch"], plan["rows"]
    if not targets:
        sys.exit("plan has no rows to record")
    by_ws = defaultdict(list)
    for t in targets:
        by_ws[t["ws"]].append(t)

    # check every tab before writing any, so a moved row on EKW cannot leave SVC half-recorded
    all_writes, problems, ipvs = {}, [], {}
    for ws, ts in by_ws.items():
        w, p, ipvs[ws] = plan_tab_writes(ws, ts, batch, tok)
        all_writes[ws] = w
        problems += p
    if problems:
        print("NOT WRITING. The sheet moved under the plan:")
        print("\n".join("  " + p for p in problems))
        return 2

    snap_path = plan_path.with_name(f"{batch}.snapshot.json")
    snap = {
        ws: [{"range": a1, "old": old, "new": new} for a1, old, new in w]
        for ws, w in all_writes.items()
    }
    snap_path.write_text(json.dumps(snap, indent=2), encoding="utf-8")
    print(f"snapshot of {sum(len(v) for v in snap.values())} cells: {snap_path}")

    flat = [(ws, a1, old, new) for ws, w in all_writes.items() for a1, old, new in w]

    def put(ws_writes):
        body = {
            "valueInputOption": "RAW",
            "data": [
                {"range": f"'{ws}'!{a1}", "values": [[new]]}
                for ws, a1, _o, new in ws_writes
            ],
        }
        api("POST", "/values:batchUpdate", tok, body)

    def readback(ws_writes):
        q = "&".join(
            "ranges=" + urllib.parse.quote(f"'{ws}'!{a1}")
            for ws, a1, _o, _n in ws_writes
        )
        got = api("GET", f"/values:batchGet?{q}", tok).get("valueRanges", [])
        vals = [(g.get("values") or [[""]])[0][0] for g in got]
        return [w for w, v in zip(ws_writes, vals) if str(v).strip() != w[3]]

    put(flat)
    bad = readback(flat)
    if bad:
        print(f"{len(bad)} cells did not land; retrying once")
        put(bad)
        bad = readback(bad)
    if bad:
        print(
            f"WARNING: {len(bad)} cells still wrong after retry, the sheet is partly updated: {[b[:2] for b in bad]}"
        )
        print(f"old values are in {snap_path}")
        return 1
    for ws, ts in by_ws.items():
        print(
            f"done: {ws} {len(ts)} rows now carry {batch!r} and EQC Status {ipvs[ws]!r}; every cell read back OK"
        )
    print(
        f"Next, on every batch: /qc-zero-pass-review {batch} (tools/qc_zero_pass/README.md). "
        "It reviews each task with a test at 0% in all runs and marks confirmed defects before TFRL QC samples."
    )
    return 0


def record_feedback(*_a, **_k):
    # TODO(process step 6): write each task's QC result into its row. Blocked on the open question in
    # ekw/qc-intake-process-2026-09-24.md ("Where do QC results come back?"). Once the TFRL QC worksheet
    # link is known: read it, match rows by task_name, write only into the feedback columns, and use the
    # same snapshot / write / read-back pattern as apply_plan().
    raise NotImplementedError(
        "QC feedback write-back is not built yet; see the TODO in record_feedback()"
    )


# ---------------------------------------------------------------- main


def scan_tab(ws: str, tok: str):
    """Read one tab, print what it holds, and classify its rows."""
    rows = read_tab(ws, tok)
    loc = locate(rows)
    c = loc["cols"]
    print(
        f"\n=== tab {ws}: "
        + ", ".join(
            f"{k} = {col_letter(v)} ({rows[0][v].strip()!r})" for k, v in c.items()
        )
    )
    print(
        f"live queue: rows 2-{loc['queue_end']} (ends at the 'Put your tasks above' row {loc['queue_end'] + 1}); "
        f"Rejected heading row {(loc['rejected'] or -1) + 1}, Duplicates heading row "
        f"{(loc['duplicates'] or -1) + 1 if loc['duplicates'] is not None else 'none'}"
    )
    if "batch" not in c:
        print(
            f"'{BATCH_HEADER}' column not there yet; --apply will add it at {col_letter(loc['width'])} (far right)"
        )
    live = live_rows(rows, loc)
    for r in live:
        r["ws"] = ws
    below = {cell(r, c["task"]) for r in rows[loc["queue_end"] :]} - {""}
    print(f"{len(live)} live rows with a task_name")
    print("  Task Available Status x EQC Status:")
    for (a, e), n in Counter(
        (r["avail"] or "(blank)", r["eqc"] or "(blank)") for r in live
    ).most_common():
        print(f"    {n:>4}  {a:24} | {e}")

    sel = select(live)
    reasons = Counter(
        (
            re.sub(r"'.*'", "'...'", why)
            if "already sent" not in why
            else "already sent in a batch"
        )
        for _r, why in sel["excluded"]
    )
    print("left out:")
    for why, n in reasons.most_common():
        if "Duplicate (auto)" in why:
            why = "sheet's Duplicate (auto) column marks it a repeat of another row"
        print(f"  {n:>4}  {why}")
    print(f"  {len(sel['dropped']):>4}  duplicates of another ready row")
    for x, k in sel["dropped"]:
        print(
            f"        row {x['row']}: {x['task_name']} (task {x['task_id']}) duplicate of row {k['row']}"
        )
    if sel["fixes"]:
        print(
            f"{len(sel['fixes'])} FIXES for earlier batches (upload into the ORIGINAL batch dataset, not a new batch):"
        )
        for r, b in sel["fixes"]:
            print(f"  row {r['row']}: {r['task_name']} -> {b}")
    also_below = [r for r in sel["candidates"] if r["task_name"] in below]
    if also_below:
        print(
            "note: these ready tasks ALSO appear in the Rejected/Duplicates sections (kept in; check them):"
        )
        for r in also_below:
            print(f"  row {r['row']}: {r['task_name']}")
    print(f"{len(sel['candidates'])} ready on {ws}")
    return live, sel


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--ws",
        default="ALL",
        choices=["ALL", "SVC", "EKW"],
        help="which tab(s); ALL (default) puts SVC tasks first and EKW under them in one batch",
    )
    ap.add_argument(
        "--min", type=int, default=50, help="minimum tasks for a batch (default 50)"
    )
    ap.add_argument(
        "--access",
        help="CSV from the DataOS step: ws,task_name,task_id,dataset_id,dataset_name,role",
    )
    ap.add_argument(
        "--out", default="qc_batches", help="local output folder (default ./qc_batches)"
    )
    ap.add_argument("--deadline", help="Requested Deadline text for the #tfrl_qc draft")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="record the batch on the sheet (needs --plan)",
    )
    ap.add_argument("--plan", help="the <BATCH>.plan.json to record with --apply")
    args = ap.parse_args()

    tok = token()
    if args.apply:
        if not args.plan:
            sys.exit(
                "--apply needs --plan <BATCH>.plan.json (the plan you built the DataOS dataset from)"
            )
        return apply_plan(Path(args.plan), tok)

    tabs = ["SVC", "EKW"] if args.ws == "ALL" else [args.ws]
    live, sel = [], {"candidates": [], "dropped": [], "excluded": [], "fixes": []}
    for ws in tabs:  # tab order is batch order: SVC first, EKW under
        l, s = scan_tab(ws, tok)
        live += l
        for k in sel:
            sel[k] += s[k]

    cands = sel["candidates"]
    access = load_access(args.access)
    admin, no_admin, unchecked = [], [], []
    for r in cands:
        a = access.get((r["ws"], r["task_name"]))
        if a is None or not a["role"]:
            unchecked.append(r)
        else:
            r["access"] = a
            r["task_id"] = (
                r["task_id"] or a["task_id"]
            )  # dataset-link rows get their id here
            (admin if a["role"].upper() == "ADMIN" else no_admin).append(r)
    ready = len(admin) if access else len(cands)
    print(
        f"\n{len(cands)} tasks ready for human QC and not yet sent"
        + (
            f": {len(admin)} with admin access, {len(no_admin)} without, {len(unchecked)} not checked"
            if access
            else " (admin access not checked yet; pass --access)"
        )
    )
    if ready < args.min:
        print(f"only {ready} ready, need {args.min}. Stopping; nothing built.")
        return 0

    batch = next_batch_name("QC" if len(tabs) > 1 else tabs[0], live)
    # with no access file yet, plan every candidate so the checklist and drafts are complete to review
    planned = admin if access else cands
    for r in planned:
        r.setdefault("access", {})
    out = Path(args.out)
    write_outputs(
        " + ".join(tabs),
        batch,
        sel,
        planned,
        no_admin,
        unchecked if access else [],
        out,
        args,
    )
    if not access:
        # the DataOS step fills this in; the next run with --access splits admin from non-admin
        write_access_todo(out / f"{batch}.access_todo.csv", cands)
    print(f"\nbatch name: {batch}. Files in {out.resolve()}:")
    for p in sorted(out.glob(f"{batch}.*")):
        print(f"  {p.name}")
    print("\nDry run. Nothing written to the sheet, DataOS, Drive or Slack.")
    if not access:
        print(
            f"Next: fill {batch}.access_todo.csv from DataOS (dataset and your role per task), rerun with --access."
        )
    print(
        f"After the batch dataset exists: --apply --plan {out / (batch + '.plan.json')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
