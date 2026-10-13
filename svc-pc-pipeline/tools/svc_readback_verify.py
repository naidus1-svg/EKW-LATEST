#!/usr/bin/env python3
"""Independently re-download every written file and md5-compare against local source.

`drive.py put` already reads back after writing. This is the SECOND, separate check,
because on 08-29 two files reached Drive in a state the write log did not reflect: the
record showed the first write's fingerprint while a later corrected write was the live
one. A tool checking its own work is one source.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("C:/b/_fetched_all32")
DRIVE = Path.home() / ".claude" / "drive.py"


def md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


results = json.loads((ROOT / "_writeback_results.json").read_text(encoding="utf-8"))
written = [r for r in results if r.get("put_exit") == 0]
print(f"re-downloading {len(written)} files written to Drive\n")

rows, mismatches = [], []
with tempfile.TemporaryDirectory() as td:
    for w in written:
        local = ROOT / w["task"] / w["rel"]
        dest = Path(td) / f"{w['task']}__{Path(w['rel']).name}"
        r = subprocess.run(
            [sys.executable, str(DRIVE), "get", w["id"], "-o", str(dest)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if r.returncode != 0 or not dest.exists():
            verdict, drive_md5, drive_bytes = "DOWNLOAD FAILED", "", 0
            mismatches.append(w)
        else:
            drive_md5, drive_bytes = md5(dest), dest.stat().st_size
            local_md5 = md5(local)
            if drive_md5 == local_md5:
                verdict = "MATCH"
            else:
                verdict = "MISMATCH"
                mismatches.append(w)
        rows.append(
            {
                "task": w["task"],
                "rel": w["rel"],
                "id": w["id"],
                "md5_before_edit": w["md5_before"],
                "md5_local_after_edit": w["md5_after"],
                "md5_redownloaded_from_drive": drive_md5,
                "bytes_before": w["bytes_before"],
                "bytes_after": w["bytes_after"],
                "bytes_on_drive": drive_bytes,
                "verdict": verdict,
            }
        )
        print(f"{verdict:<16} {w['task']:<16} {w['rel'][:48]}")

out = ROOT / "_readback_verify.json"
out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
print(f"\n{len(rows) - len(mismatches)}/{len(rows)} matched on independent re-download")
if mismatches:
    print("MISMATCHES, these files are NOT confirmed on Drive:")
    for m in mismatches:
        print(f"  {m['task']} :: {m['rel']}")
print(f"wrote {out}")
raise SystemExit(1 if mismatches else 0)
