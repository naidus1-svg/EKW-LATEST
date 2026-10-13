#!/usr/bin/env python3
"""Pull EKW raw task folders from Drive to a local dir. READ-ONLY (Drive files.list + files.get alt=media).

Source of each task: the "prev:" Drive folder written in column E of the 'EKW QC Tracker Combined' tab
(Luiz's TaskID-<ID> folders, created 2026-09-22). Layout on Drive, as authored:
    verifier.json, prompt.txt, expert_solution/..., source_documents/...
Files are written verbatim under <out>/<TASK>/ (duplicate names on Drive: the newest one wins and the
count is recorded in <out>/<TASK>/_pull.json). Normalising the shapes is ekw_intake.py's job on the sandbox.

The Drive MCP connector returned zero children for these folders (2026-09-24) while the Drive API with the
gcloud user token listed all of them, so this uses the API directly.

Usage:
    python tools/ekw_pull_drive.py --tasks-json ekw_rows.json --out C:/ekwqc/_ekw_claimed_raw
    python tools/ekw_pull_drive.py --folder LGL-131=1j6zKJ128Be0PS3y2D-BagACLvEByFGU3 --out ...
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://www.googleapis.com/drive/v3/files"
FOLDER = "application/vnd.google-apps.folder"


def token() -> str:
    p = subprocess.run(
        ["gcloud.cmd", "auth", "print-access-token"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if p.returncode != 0 or not p.stdout.strip():
        sys.exit(
            "gcloud has no token. Run: gcloud.cmd auth login --enable-gdrive-access"
        )
    return p.stdout.strip()


def get(url: str, tok: str) -> bytes:
    last = None
    for i in range(4):
        try:
            req = urllib.request.Request(
                url, headers={"Authorization": "Bearer " + tok}
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:  # transient network / 5xx
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET failed: {url[:120]}: {last}")


def children(fid: str, tok: str) -> list[dict]:
    out, page = [], None
    while True:
        q = {
            "q": f"'{fid}' in parents and trashed=false",
            "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime,md5Checksum)",
            "pageSize": 1000,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page:
            q["pageToken"] = page
        d = json.loads(get(API + "?" + urllib.parse.urlencode(q), tok))
        out += d.get("files", [])
        page = d.get("nextPageToken")
        if not page:
            return out


def pull(task: str, fid: str, out: Path, tok: str) -> dict:
    dest = out / task
    dest.mkdir(parents=True, exist_ok=True)
    rec = {"task": task, "folder": fid, "files": [], "duplicates": 0}
    seen: dict[str, str] = {}

    def walk(folder_id: str, rel: str) -> None:
        kids = sorted(
            children(folder_id, tok), key=lambda f: f["modifiedTime"]
        )  # newest last -> wins
        for f in kids:
            r = f"{rel}{f['name']}"
            if f["mimeType"] == FOLDER:
                walk(f["id"], r + "/")
                continue
            if f["mimeType"].startswith("application/vnd.google-apps"):
                rec["files"].append(
                    {"path": r, "skipped": "google-native file, not exported"}
                )
                continue
            if r in seen:
                rec["duplicates"] += 1
            p = dest / r
            p.parent.mkdir(parents=True, exist_ok=True)
            data = get(f"{API}/{f['id']}?alt=media&supportsAllDrives=true", tok)
            if f.get("size") and len(data) != int(f["size"]):
                raise RuntimeError(f"{task}/{r}: size {len(data)} != Drive {f['size']}")
            p.write_bytes(data)
            seen[r] = f["id"]
            rec["files"].append(
                {
                    "path": r,
                    "id": f["id"],
                    "size": len(data),
                    "md5": f.get("md5Checksum"),
                    "modified": f["modifiedTime"],
                }
            )

    walk(fid, "")
    (dest / "_pull.json").write_text(json.dumps(rec, indent=1))
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--tasks-json",
        help="rows JSON with 'Tasks claimed' and 'c4' (note holding 'prev: <folder url>')",
    )
    ap.add_argument(
        "--folder", action="append", default=[], help="TASK=<folder id>, repeatable"
    )
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    pairs = [tuple(x.split("=", 1)) for x in a.folder]
    if a.tasks_json:
        for r in json.load(open(a.tasks_json, encoding="utf-8"))["rows"]:
            note = r.get("c4", "")
            if "folders/" in note and r.get("Tasks claimed", "").startswith(
                ("LGL-", "SCO-")
            ):
                pairs.append(
                    (
                        r["Tasks claimed"],
                        note.split("folders/")[-1].strip().split("?")[0],
                    )
                )
    if not pairs:
        ap.error("no tasks given")
    tok = token()
    bad = 0
    for task, fid in pairs:
        try:
            rec = pull(task, fid, a.out, tok)
            n = sum(1 for f in rec["files"] if "id" in f)
            print(f"{task}\t{n} files\t{rec['duplicates']} duplicate names")
        except Exception as e:
            bad += 1
            print(f"{task}\tERROR {e}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
