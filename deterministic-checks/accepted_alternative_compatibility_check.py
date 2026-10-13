#!/usr/bin/env python3
"""Flag sibling criteria that revoke an alternative another criterion accepts.

Confirmed 2026-09-17 on task_146: v2 accepts store-eligible as either 32,394 or
32,380, while v1/v5 still require the 14-unit physical-shortfall narrative that
only exists under 32,394. Independently, v10 permits size-run evidence in a
joined tab while v12 fails unless that evidence is in "the table itself."

This is a mechanical, LLM-free proxy: it does not prove two criteria are about
the same fact, only that an explicitly accepted alternative is incompatible
with a sibling's required numbers or presentation. Warn-only until calibrated.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from ekw_verifier_json import load_ekw_criteria  # noqa: E402

NUM_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d{4,})(?!\d)")
EITHER_WINDOW = re.compile(
    r"\beither\b.{0,500}?\bor\b.{0,500}?(?:\.|;|—)",
    re.IGNORECASE | re.DOTALL,
)
TABLE_SELF_RE = re.compile(r"from the table itself", re.IGNORECASE)
JOINED_TAB_RE = re.compile(
    r"\beither\b.{0,300}(?:same table|this same table).{0,300}\bor\b.{0,300}"
    r"(?:separately|separate (?:tab|sheet)|joins? back)",
    re.IGNORECASE | re.DOTALL,
)


def resolve_package_dir(task_dir: Path) -> Path | None:
    """Harbor package, DataOS ``task_files``, or latest ``rev_*/task_files``."""
    if (task_dir / "tests" / "verifier.json").is_file():
        return task_dir
    nested = task_dir / "task_files"
    if (nested / "tests" / "verifier.json").is_file():
        return nested
    revs = sorted(task_dir.glob("rev_*/task_files/tests/verifier.json"))
    if revs:
        return revs[-1].parents[1]
    return None


UNIT_DELTA_RE = re.compile(r"~?\s*(\d{1,3})\s*-unit", re.IGNORECASE)


def _ints(text: str, *, include_unit_deltas: bool = False) -> list[int]:
    numbers = [int(m.replace(",", "")) for m in NUM_RE.findall(text or "")]
    if include_unit_deltas:
        numbers.extend(int(m) for m in UNIT_DELTA_RE.findall(text or ""))
    return numbers


def numeric_alternative_pairs(text: str) -> list[tuple[int, int, str]]:
    pairs: list[tuple[int, int, str]] = []
    for match in EITHER_WINDOW.finditer(text or ""):
        window = match.group()
        seen: list[int] = []
        for number in _ints(window):
            if number >= 100 and number not in seen:
                seen.append(number)
        if len(seen) >= 2:
            pairs.append((seen[0], seen[1], window[:240]))
    return pairs


def check_task(task_dir: Path) -> dict:
    package = resolve_package_dir(task_dir)
    result: dict = {
        "task_id": task_dir.name,
        "status": "skip",
        "findings": [],
        "n_findings": 0,
        "package": str(package) if package else None,
    }
    if package is None:
        result["status"] = "skip"
        return result
    criteria = [
        c
        for c in load_ekw_criteria(package)
        if c.get("name") and c.get("name") != "__parse_error__"
    ]
    if not criteria:
        return result

    findings: list[dict] = []
    for criterion in criteria:
        text = criterion.get("description") or ""
        name = criterion.get("name")
        for left, right, window in numeric_alternative_pairs(text):
            delta = abs(left - right)
            if delta < 1:
                continue
            for sibling in criteria:
                if sibling.get("name") == name:
                    continue
                sibling_text = sibling.get("description") or ""
                sibling_nums = set(_ints(sibling_text, include_unit_deltas=True))
                honors_both = left in sibling_nums and right in sibling_nums
                if honors_both:
                    continue
                if delta in sibling_nums and left not in sibling_nums and right not in sibling_nums:
                    findings.append(
                        {
                            "kind": "accepted_numeric_alternative_revoked",
                            "severity": "warn",
                            "criterion": name,
                            "sibling": sibling.get("name"),
                            "accepted": [left, right],
                            "delta": delta,
                            "evidence": window,
                        }
                    )
        if JOINED_TAB_RE.search(text):
            for sibling in criteria:
                if sibling.get("name") == name:
                    continue
                sibling_text = sibling.get("description") or ""
                if TABLE_SELF_RE.search(sibling_text):
                    findings.append(
                        {
                            "kind": "accepted_presentation_alternative_revoked",
                            "severity": "warn",
                            "criterion": name,
                            "sibling": sibling.get("name"),
                            "evidence": (
                                f"{name} permits a joined/separate tab; "
                                f"{sibling.get('name')} requires evidence "
                                "from the table itself"
                            ),
                        }
                    )

    result["findings"] = findings
    result["n_findings"] = len(findings)
    result["status"] = "warn" if findings else "pass"
    return result


def find_task_dirs(root: Path, task_ids=None, id_prefix: str = "") -> list[Path]:
    if task_ids:
        dirs = []
        for tid in task_ids:
            path = root / tid
            if not path.is_dir():
                print(f"WARNING: task dir not found, skipping: {path}", file=sys.stderr)
                continue
            dirs.append(path)
        return dirs
    return sorted(
        path for path in root.iterdir() if path.is_dir() and path.name.startswith(id_prefix)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_ids", nargs="*")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--id-prefix", default="")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if not args.all and not args.task_ids:
        parser.error("pass one or more task ids, or --all")
    task_dirs = find_task_dirs(
        args.root, None if args.all else args.task_ids, id_prefix=args.id_prefix
    )
    results = [check_task(path) for path in task_dirs]
    report = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root.resolve()),
        "n_tasks": len(results),
        "results": results,
    }
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
