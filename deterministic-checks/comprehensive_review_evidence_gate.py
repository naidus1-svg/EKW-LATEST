#!/usr/bin/env python3
"""Fail fast on objective evidence that a reviewed task is not ready.

This post-run gate checks three facts that package-only checks cannot know:

1. every Comprehensive Review ends in valid, non-template result JSON;
2. every Oracle/golden run earns full reward; and
3. repeated Oracle runs agree.

It accepts either one downloaded revision directory (containing ``task_files``)
or a batch root containing ``<bundle>/rev_*`` directories.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ALLOWED_VERDICTS = {"accept", "reject", "invalid", "needs_revision"}
EXPECTED_CHECK_IDS = {f"1.{i}" for i in range(1, 11)}
TEMPLATE_VERDICT = "accept | reject | invalid | needs_revision"
JSON_START = re.compile(r"\{\s*\"benchmark\"")


def parse_review(text: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Return the last valid final review object and validation errors."""
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    decode_errors: list[str] = []
    for match in JSON_START.finditer(text):
        try:
            obj, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError as exc:
            decode_errors.append(f"invalid JSON at character {match.start()}: {exc.msg}")
            continue
        if isinstance(obj, dict):
            candidates.append(obj)

    errors: list[str] = []
    for obj in reversed(candidates):
        verdict = obj.get("overall_verdict")
        if verdict == TEMPLATE_VERDICT:
            errors.append("only the prompt's placeholder verdict JSON was emitted")
            continue
        if verdict not in ALLOWED_VERDICTS:
            errors.append(f"invalid overall_verdict: {verdict!r}")
            continue
        checks = obj.get("checks")
        if not isinstance(checks, list):
            errors.append("checks must be a list")
            continue
        ids = {str(c.get("id")) for c in checks if isinstance(c, dict)}
        if ids != EXPECTED_CHECK_IDS or len(checks) != 10:
            errors.append(
                "checks must contain exactly 1.1 through 1.10 "
                f"(found {sorted(ids)})"
            )
            continue
        severities = [
            c.get("severity") for c in checks if isinstance(c, dict)
        ]
        major_count = severities.count("major")
        minor_count = severities.count("minor")
        if obj.get("major_count") != major_count:
            errors.append(
                f"major_count={obj.get('major_count')!r}, expected {major_count}"
            )
            continue
        if obj.get("minor_count") != minor_count:
            errors.append(
                f"minor_count={obj.get('minor_count')!r}, expected {minor_count}"
            )
            continue
        return obj, []

    if not errors:
        errors = decode_errors or ["no final Comprehensive Review JSON object found"]
    return None, errors


def _read_reward(path: Path) -> float | None:
    try:
        if path.name == "reward.txt":
            return float(path.read_text(encoding="utf-8").strip())
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, (int, float)):
            return float(data)
        if isinstance(data, dict):
            for key in ("reward", "score"):
                if isinstance(data.get(key), (int, float)):
                    return float(data[key])
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return None


def _oracle_rewards(revision: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    evaluations = revision / "evaluations"
    if not evaluations.is_dir():
        return rows
    for run in sorted(evaluations.iterdir()):
        if not run.is_dir() or "oracle" not in run.name.lower():
            continue
        candidates = list(run.rglob("reward.txt"))
        if not candidates:
            candidates = list(run.rglob("reward.json"))
        value = next(
            (v for p in candidates if (v := _read_reward(p)) is not None),
            None,
        )
        rows.append(
            {
                "run": run.name,
                "reward": value,
                "reward_path": str(candidates[0]) if candidates else None,
            }
        )
    return rows


def check_submission(revision: Path) -> dict[str, Any]:
    """Check one ``<bundle>/rev_*`` directory."""
    revision = revision.resolve()
    bundle = revision.parent.name if revision.name.startswith("rev_") else revision.name
    findings: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []

    verification_dir = revision / "verifications"
    reports = (
        sorted(verification_dir.glob("comprehensive_review_*.md"))
        if verification_dir.is_dir()
        else []
    )
    if not reports:
        findings.append(
            {
                "kind": "missing_comprehensive_review",
                "severity": "fail",
                "path": str(verification_dir),
                "evidence": "No Comprehensive Review report was found",
            }
        )
    for report in reports:
        try:
            parsed, errors = parse_review(report.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            parsed, errors = None, [str(exc)]
        reviews.append(
            {
                "path": str(report),
                "valid": parsed is not None,
                "overall_verdict": parsed.get("overall_verdict") if parsed else None,
                "errors": errors,
            }
        )
        if parsed is None:
            findings.append(
                {
                    "kind": "malformed_comprehensive_review",
                    "severity": "fail",
                    "path": str(report),
                    "evidence": "; ".join(errors),
                }
            )
        elif (
            parsed["overall_verdict"] != "accept"
            or parsed["major_count"] != 0
            or parsed["minor_count"] > 2
        ):
            findings.append(
                {
                    "kind": "comprehensive_review_not_accepted",
                    "severity": "fail",
                    "path": str(report),
                    "overall_verdict": parsed["overall_verdict"],
                    "major_count": parsed["major_count"],
                    "minor_count": parsed["minor_count"],
                    "evidence": (
                        "Review does not meet the release bar: accept, "
                        "zero major issues, and at most two minor issues"
                    ),
                }
            )

    oracle_runs = _oracle_rewards(revision)
    if not oracle_runs:
        findings.append(
            {
                "kind": "missing_oracle_run",
                "severity": "fail",
                "path": str(revision / "evaluations"),
                "evidence": "No Oracle/golden evaluation run was found",
            }
        )
    for row in oracle_runs:
        reward = row["reward"]
        if reward is None:
            findings.append(
                {
                    "kind": "oracle_reward_unreadable",
                    "severity": "fail",
                    "run": row["run"],
                    "path": row["reward_path"],
                    "evidence": "Oracle run has no readable numeric reward",
                }
            )
        elif reward < 1.0 and not math.isclose(reward, 1.0, abs_tol=1e-9):
            findings.append(
                {
                    "kind": "golden_below_full_reward",
                    "severity": "fail",
                    "run": row["run"],
                    "path": row["reward_path"],
                    "reward": reward,
                    "evidence": f"Oracle/golden reward is {reward:g}, expected 1.0",
                }
            )

    numeric_rewards = [
        float(row["reward"]) for row in oracle_runs if row["reward"] is not None
    ]
    rounded = {round(value, 9) for value in numeric_rewards}
    if len(rounded) > 1:
        findings.append(
            {
                "kind": "oracle_reward_disagreement",
                "severity": "fail",
                "runs": [
                    {"run": row["run"], "reward": row["reward"]}
                    for row in oracle_runs
                    if row["reward"] is not None
                ],
                "evidence": "Repeated Oracle runs of this revision disagree",
            }
        )

    return {
        "bundle": bundle,
        "revision": revision.name,
        "path": str(revision),
        "status": "fail" if findings else "pass",
        "n_reviews": len(reports),
        "n_valid_reviews": sum(row["valid"] for row in reviews),
        "reviews": reviews,
        "oracle_runs": oracle_runs,
        "findings": findings,
    }


def discover_submissions(root: Path) -> list[Path]:
    root = root.resolve()
    if (root / "task_files").is_dir():
        return [root]
    revisions = {
        task_files.parent
        for task_files in root.rglob("task_files")
        if task_files.is_dir()
    }
    return sorted(revisions)


def run(root: Path) -> dict[str, Any]:
    submissions = [check_submission(path) for path in discover_submissions(root)]
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "root": str(root.resolve()),
        "n_submissions": len(submissions),
        "n_pass": sum(row["status"] == "pass" for row in submissions),
        "n_fail": sum(row["status"] == "fail" for row in submissions),
        "finding_counts": {
            kind: sum(
                finding["kind"] == kind
                for row in submissions
                for finding in row["findings"]
            )
            for kind in sorted(
                {
                    finding["kind"]
                    for row in submissions
                    for finding in row["findings"]
                }
            )
        },
        "submissions": submissions,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    report = run(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        f"{report['n_submissions']} submission(s): "
        f"{report['n_pass']} pass, {report['n_fail']} fail"
    )
    for kind, count in report["finding_counts"].items():
        print(f"  {kind}: {count}")
    print(f"wrote {args.out}")
    return 1 if report["n_fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
