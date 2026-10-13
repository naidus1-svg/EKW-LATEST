#!/usr/bin/env python3
"""Reproduce exactly what the Data-OS judge receives, without Data-OS.

Data-OS's judge has been returning HTTP 401 from api.anthropic.com since roughly
04:28 UTC on 2026-09-01, so every oracle batch writes `{"reward": 0.0}` with no
criteria graded. Verified from a run artifact's own `verifier/runtime.log`, not
inferred:

    litellm.AuthenticationError: AnthropicException -
    {"type":"error","error":{"type":"authentication_error",
     "message":"API key is invalid."}}

That credential is inside their Modal container and we cannot set it. What we can
do is reconstruct the judge's INPUT locally, because every part of it is in our
own package: `judge.toml` carries each criterion's text and the `files` list, and
the extraction is plain MarkItDown.

This writes, per task, the exact prompt material a judge would see. Feed that to a
reviewer to get a per-criterion read while the credential is dead. The result is
NOT an oracle score and must never be reported as one; it is a pre-screen that
says which criteria would obviously fail, so fixes can be iterated blind-free.

Mirrors `rewardkit/judges.py::_read_file_blocks`: a 1 MiB per-file ceiling above
which the judge is handed a skip notice rather than content, the same document
extension allowlist, and the same `--- {label} ---` block header. Anything outside
the allowlist is read as raw text, which is what rewardkit does and is why a
binary golden once produced a UnicodeDecodeError instead of a grade.

    python tools/svc_prescreen_extract.py <03_dataos_ready_root> --out DIR [--task ID]
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

# Both mirror rewardkit/judges.py as installed (harbor-rewardkit 0.2.0).
MAX_FILE_SIZE = 1024 * 1024
DOCUMENT_EXTENSIONS = frozenset(
    {".pdf", ".docx", ".pptx", ".xlsx", ".xls", ".msg", ".epub", ".html", ".htm"}
)


def extract(path: Path) -> str:
    """What the judge is handed for one deliverable."""
    if not path.is_file():
        return "[missing: the judge would receive nothing for this file]"
    if path.stat().st_size > MAX_FILE_SIZE:
        return f"[skipped: file too large, {path.stat().st_size:,} bytes over the {MAX_FILE_SIZE:,} ceiling]"
    if path.suffix.lower() in DOCUMENT_EXTENSIONS:
        from markitdown import MarkItDown

        return MarkItDown().convert(str(path)).text_content
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "[unreadable: not valid UTF-8, the judge would fail on this]"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--out", required=True)
    ap.add_argument("--task", action="append", dest="tasks")
    args = ap.parse_args()

    root, out = Path(args.root), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    wanted = set(args.tasks or [])

    index, n_tasks, n_crit = [], 0, 0
    for task_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if wanted and task_dir.name not in wanted:
            continue
        bundles = []
        for jt in sorted(task_dir.rglob("judge.toml")):
            data = tomllib.loads(jt.read_text(encoding="utf-8"))
            judge = data.get("judge", {})
            crits = data.get("criterion", [])
            n_crit += len(crits)
            blocks = []
            for f in judge.get("files", []):
                local = task_dir / "solution" / "files" / Path(f).name
                blocks.append(f"--- {f} ---\n{extract(local)}")
            bundles.append(
                {
                    "deliverable": jt.parent.name,
                    "judge_model": judge.get("judge"),
                    "weight": judge.get("weight"),
                    "files": judge.get("files", []),
                    "extracted": "\n\n".join(blocks),
                    "criteria": [
                        {
                            "name": c.get("name"),
                            "weight": c.get("weight"),
                            "description": c.get("description", ""),
                        }
                        for c in crits
                    ],
                }
            )
        payload = {"task": task_dir.name, "bundles": bundles}
        dest = out / f"{task_dir.name}.json"
        dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        n_tasks += 1
        chars = sum(len(b["extracted"]) for b in bundles)
        ncrit = sum(len(b["criteria"]) for b in bundles)
        index.append(
            {
                "task": task_dir.name,
                "bundles": len(bundles),
                "criteria": ncrit,
                "extracted_chars": chars,
                "path": str(dest),
            }
        )
        print(
            f"{task_dir.name}: {len(bundles)} bundle(s), {ncrit} criteria, {chars:,} chars of extracted text"
        )

    (out / "_index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"\n{n_tasks} tasks, {n_crit} criteria written to {out}")
    empty = [i["task"] for i in index if i["extracted_chars"] == 0]
    if empty:
        print(f"tasks where the judge would receive NO text at all: {', '.join(empty)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
