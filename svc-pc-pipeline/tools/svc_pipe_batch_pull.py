#!/usr/bin/env python3
"""Pull gate-v2 pipeline zips off the sandbox and stage one DataOS batch.

The scripted pipeline (/root/qc/tools/pipe_batch.sh) writes one zip per task to
/root/qc/out/pipe/<task>.zip. This tool turns the next N of them into a DataOS
upload: scp each zip, testzip it, sha256 it, combine into one archive, and print
(or with --apply, append) the ledger section for ekw/vm-batches/DATAOS-SUBMISSIONS.md
plus the ids for /root/qc/SUBMITTED.txt.

Dry-run by default: nothing is written to the ledger or SUBMITTED.txt without --apply.
Zips are always copied and hashed, that part is read-only against the sandbox.

Usage:
  python tools/svc_pipe_batch_pull.py --batch 4                 # next 10 unsubmitted pipe zips, dry run
  python tools/svc_pipe_batch_pull.py --batch 4 --limit 5 --apply

A task already in SUBMITTED.txt is a resubmit: its round number is prior rounds + 1 and
its ledger row says so. A task already pulled into an earlier pipe batch (present in the
ledger under a "pipe" batch header) is skipped unless --include-pulled.
"""

import argparse
import datetime as dt
import hashlib
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LEDGER = REPO / "ekw" / "vm-batches" / "DATAOS-SUBMISSIONS.md"
SSH = [
    "ssh",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=20",
    "-i",
    os.path.expanduser("~/.ssh/kiem_sandbox"),
    "-p",
    "2222",
    "kiem-sandbox",
]
SCP_BASE = [
    "scp",
    "-o",
    "BatchMode=yes",
    "-i",
    os.path.expanduser("~/.ssh/kiem_sandbox"),
    "-P",
    "2222",
]
REMOTE = "kiem-sandbox"
PIPE_OUT = "/root/qc/out/pipe"
SUBMITTED = "/root/qc/SUBMITTED.txt"
DEST_ROOT = Path(r"C:\wt\_dataos_upload")


def ssh(cmd: str) -> str:
    r = subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        sys.exit(f"ssh failed ({r.returncode}): {cmd}\n{r.stderr}")
    return r.stdout


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ledger_rounds() -> dict:
    """task -> number of DataOS rounds: rows under a `## Batch` header that was uploaded. Rows under any other section (the
    returns tables, the plan-status table) or under a batch marked NOT UPLOADED / NOT YET UPLOADED are not rounds; counting
    them labelled 9-5-0 "round 4" on 2026-09-19 when DataOS had seen it twice."""
    rounds = {}
    if LEDGER.exists():
        counting = False
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                counting = line.startswith("## Batch") and not re.search(
                    r"NOT (YET )?UPLOADED", line
                )
                continue
            if not counting:
                continue
            m = re.match(r"^\|\s*(SVC-PC-\d+-\d+-\d+)\s*\|", line)
            if m:
                rounds[m.group(1)] = rounds.get(m.group(1), 0) + 1
    return rounds


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--batch", type=int, required=True, help="batch number for the ledger header"
    )
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument(
        "--apply", action="store_true", help="append to the ledger and to SUBMITTED.txt"
    )
    ap.add_argument(
        "--include-pulled",
        action="store_true",
        help="re-pull tasks already in a pipe batch",
    )
    ap.add_argument(
        "--since",
        default="2026-09-19T01:53:00Z",
        help="ignore sandbox zips built before this UTC time. Zips older than the 01:53Z "
        "workspace-mode rule were made under the single-shot review and must never be uploaded; "
        "without this filter the oldest-first pick would take them first",
    )
    ap.add_argument(
        "--tasks",
        default="",
        help="comma-separated task ids (with or without the SVC-PC- prefix) to pull, and nothing else. "
        "Pass the exact uploaded set to --apply: zips that finish between the dry run and --apply otherwise "
        "join the batch and the ledger stops matching the archive that was uploaded",
    )
    args = ap.parse_args()

    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%H:%M")

    listing = ssh(f"ls -l --time-style=+%FT%TZ {PIPE_OUT}/*.zip 2>/dev/null || true")
    remote = []
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) < 7:
            continue
        size, mtime, path = int(parts[4]), parts[5], parts[6]
        task = Path(path).stem
        if re.fullmatch(r"SVC-PC-\d+-\d+-\d+", task):
            remote.append((mtime, task, size, path))
    remote.sort()
    remote = [r for r in remote if r[0] >= args.since]
    if args.tasks:
        want = {
            t if t.startswith("SVC-PC-") else f"SVC-PC-{t}"
            for t in args.tasks.replace(" ", "").split(",")
            if t
        }
        remote = [r for r in remote if r[1] in want]
        missing = want - {r[1] for r in remote}
        if missing:
            sys.exit(f"--tasks: no zip on the sandbox for {sorted(missing)}")
    if not remote:
        print(f"no zips in {PIPE_OUT} yet")
        return 0

    submitted = set(ssh(f"cat {SUBMITTED}").split())
    rounds = ledger_rounds()
    pulled_in_pipe = set()
    if LEDGER.exists():
        txt = LEDGER.read_text(encoding="utf-8")
        for sec in re.split(r"^## ", txt, flags=re.M):
            if (
                sec.lower().startswith("batch")
                and "pipe" in sec.split("\n", 1)[0].lower()
            ):
                pulled_in_pipe.update(
                    re.findall(r"^\|\s*(SVC-PC-\d+-\d+-\d+)\s*\|", sec, re.M)
                )

    picked = []
    for mtime, task, size, path in remote:
        if task in pulled_in_pipe and not args.include_pulled:
            continue
        picked.append((mtime, task, size, path))
        if len(picked) >= args.limit:
            break
    print(
        f"{len(remote)} pipe zips on sandbox, {len(pulled_in_pipe)} already pulled, taking {len(picked)}"
    )
    if not picked:
        return 0

    dest = DEST_ROOT / f"{today}-pipe{args.batch}"
    dest.mkdir(parents=True, exist_ok=True)
    rows = []
    for mtime, task, size, path in picked:
        local = dest / f"{task}.zip"
        if not local.exists() or local.stat().st_size != size:
            r = subprocess.run(
                SCP_BASE + [f"{REMOTE}:{path}", str(local)],
                capture_output=True,
                text=True,
                timeout=900,
            )
            if r.returncode != 0:
                sys.exit(f"scp failed for {task}: {r.stderr}")
        if local.stat().st_size != size:
            sys.exit(
                f"{task}: local {local.stat().st_size} bytes != remote {size}; truncated copy"
            )
        bad = zipfile.ZipFile(local).testzip()
        if bad is not None:
            sys.exit(f"{task}: testzip failed on {bad}")
        names = zipfile.ZipFile(local).namelist()
        if any(n.endswith("lease.json") for n in names):
            sys.exit(f"{task}: lease.json inside zip")
        rnd = rounds.get(task, 0) + 1
        rows.append((task, size, sha256(local), rnd, task in submitted, mtime))
        print(
            f"  {task:16} {size:>12,} round {rnd}{'  (resubmit)' if task in submitted else ''}  built {mtime}"
        )

    combined = dest / f"svc-pc-pipe-batch{args.batch}-{len(rows)}-tasks-{today}.zip"

    # DataOS wants the task folders at the archive root (batch 1 layout), not a zip of zips:
    # the 22:04 UTC build nested the five per-task zips and DataOS answered
    # "No task directories found in the uploaded archive".
    # Member names are copied as the raw bytes the per-task zip holds. Info-ZIP writes non-ASCII names as raw UTF-8
    # without the UTF-8 flag; Python decodes those as cp437 ("ΓÇö" for an em dash) and writestr() then re-encodes the
    # decoded text as UTF-8 with the flag set, which changes the bytes of every non-ASCII file name (21 of 204 names
    # in 2-7-0). RawZipInfo writes the original bytes and flags back unchanged.
    class RawZipInfo(zipfile.ZipInfo):
        def _encodeFilenameFlags(self):
            return self._raw_name, self.flag_bits

    with zipfile.ZipFile(combined, "w", zipfile.ZIP_DEFLATED) as z:
        for task in [r[0] for r in rows]:
            inner = zipfile.ZipFile(dest / f"{task}.zip")
            for info in inner.infolist():
                if info.filename.endswith("/"):
                    continue
                ni = RawZipInfo(info.filename, info.date_time)
                ni._raw_name = (
                    info.filename.encode("utf-8")
                    if info.flag_bits & 0x800
                    else info.filename.encode("cp437")
                )
                ni.compress_type = zipfile.ZIP_DEFLATED
                ni.external_attr = info.external_attr
                ni.create_system = info.create_system
                ni.flag_bits = info.flag_bits & 0x800
                ni.extra = info.extra
                z.writestr(ni, inner.read(info.filename))
    csize, csha = combined.stat().st_size, sha256(combined)
    print(f"\ncombined: {combined}  {csize:,} bytes  sha256 {csha}")

    resub = [t for t, *_r in rows if _r[3]]
    section = [
        "",
        f"## Batch {args.batch} (pipe): `{combined.name}` ({csize:,} bytes, sha256 `{csha}`), "
        f"built {today} {stamp} UTC by svc_pipe_batch_pull.py, NOT YET UPLOADED",
        "",
        f"Source: {len(rows)} zips from the scripted gate-v2 pipeline (`/root/qc/out/pipe/`, since 2026-09-19 01:53Z: workspace-mode "
        f"Comprehensive Review by GLM and Sonnet on the exact staged bytes with the canon prompt, Opus fix rounds from the reviewers' majors and the "
        f"deterministic gate cells, oracle probe at 1.0 on the current files, `stage_and_zip.sh` actuator). Not part of that bar: the per-task "
        f"solver-run grading and adjudication of the older `gate_task.sh` flow. "
        + (
            f"{len(resub)} are resubmits, seen by DataOS in an earlier uploaded batch: {' '.join(resub)}. "
            if resub
            else ""
        )
        + "Each zip passed testzip and its remote byte size on the laptop; sha256 is of the per-task zip inside the combined archive. "
        "Change this header to 'uploaded by Khiem <time> UTC' after the upload, and record verdict JSONs under "
        f"`/root/qc/in/dataos-cr-batch{args.batch}-returns/`.",
        "",
        "| Task | per-task zip bytes | sha256 | DataOS round |",
        "|---|---|---|---|",
    ]
    for task, size, h, rnd, _s, _m in rows:
        section.append(f"| {task} | {size:,} | `{h}` | {rnd} |")
    section_txt = "\n".join(section) + "\n"
    print("\n--- ledger section ---\n" + section_txt)

    new_ids = [t for t, *_r in rows if not _r[3]]
    if args.apply:
        with open(LEDGER, "a", encoding="utf-8", newline="\n") as f:
            f.write(section_txt)
        if new_ids:
            ssh("printf '%s\\n' " + " ".join(new_ids) + f" >> {SUBMITTED}")
        n = int(ssh(f"wc -l < {SUBMITTED}").strip())
        print(
            f"APPLIED: ledger appended, SUBMITTED.txt now {n} ids (+{len(new_ids)} new)"
        )
    else:
        print(
            f"dry run: would append {len(new_ids)} new ids to SUBMITTED.txt ({' '.join(new_ids)}); re-run with --apply"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
