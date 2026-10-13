#!/usr/bin/env python3
"""Audit Oracle ``reward-details.json`` for criterion-level grading defects.

Package-only checks cannot see these. Confirmed 2026-09-17 QCR classes:

1. Repeated Oracle runs disagree on the same criterion (task_1 v11, task_57 v27).
2. A fail verdict calls a quoted fact fabricated/unsourced when that string is
   already in ``environment/`` (task_145 v18, task_120 v15).

Added 2026-09-28 from the QC batch 1-6 failure analysis (60 failed tasks):

3. F2 ``oracle_reward_below_one`` / ``oracle_grammar_too_large``: an Oracle run's
   ``reward.json`` (or ``reward.txt``) is below 1.0 (a missing reward is F3: timeout or crash), or an Oracle
   verifier log carries "compiled grammar is too large". The golden does not earn
   full marks from its own grader.
4. F3 ``verifier_crash``: ANY run's ``eval_files/verifier/`` output shows a Python
   traceback, ``rewardkit exited 1``, ``Reward '<group>' failed``, or "timed out
   after" (also "Verifier execution timed out" in ``trial.log``). The grader, not
   the answer, produced the score (caught SVC-PC-45-1-0, HLT202, PHR-156).

Warn-only. Does not rewrite criteria. Skip when no evaluations exist.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

FABRICATED_RE = re.compile(
    r"fabricat|unsourced|outside the agreed set|not (?:present )?in (?:the )?(?:source|packet|materials)",
    re.IGNORECASE,
)
QUOTED_RE = re.compile(r"[\"“]([^\"”]{4,80})[\"”]")


def resolve_revision_dir(task_dir: Path) -> Path:
    if task_dir.name == "task_files":
        return task_dir.parent
    if (task_dir / "evaluations").is_dir():
        return task_dir
    revs = sorted(p for p in task_dir.glob("rev_*") if p.is_dir())
    if not revs:
        # DataOS with_runs unzip nests one level deeper: <work>/<task>/<task>/rev_*
        revs = sorted(p for p in task_dir.glob("*/rev_*") if p.is_dir())
    return revs[-1] if revs else task_dir


def resolve_package_dir(task_dir: Path) -> Path | None:
    if (task_dir / "environment").is_dir():
        return task_dir
    if (task_dir / "task_files" / "environment").is_dir():
        return task_dir / "task_files"
    rev = resolve_revision_dir(task_dir)
    nested = rev / "task_files"
    if nested.is_dir():
        return nested
    return None


def _score(block: dict) -> float | None:
    if not isinstance(block, dict):
        return None
    value = block.get("score")
    if isinstance(value, (int, float)):
        return float(value)
    criteria = block.get("criteria")
    if isinstance(criteria, list) and criteria and isinstance(criteria[0], dict):
        inner = criteria[0].get("value")
        if isinstance(inner, (int, float)):
            return float(inner)
    return None


def _reasoning(block: dict) -> str:
    criteria = block.get("criteria") if isinstance(block, dict) else None
    if isinstance(criteria, list) and criteria and isinstance(criteria[0], dict):
        return str(criteria[0].get("reasoning") or "")
    return str(block.get("reasoning") or "") if isinstance(block, dict) else ""


def _oracle_detail_files(revision: Path) -> list[Path]:
    evaluations = revision / "evaluations"
    if not evaluations.is_dir():
        return []
    files: list[Path] = []
    for run in sorted(evaluations.iterdir()):
        if not run.is_dir() or "oracle" not in run.name.lower():
            continue
        files.extend(run.rglob("reward-details.json"))
    return files


def _source_corpus(package: Path) -> str:
    chunks: list[str] = []
    env = package / "environment"
    if not env.is_dir():
        return ""
    for path in env.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".txt", ".csv", ".json"}:
            continue
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="replace")[:200_000])
        except OSError:
            continue
        if sum(len(c) for c in chunks) > 2_000_000:
            break
    return "\n".join(chunks)


CRASH_RE = re.compile(
    r"Traceback \(most recent call last\)|rewardkit exited 1|Reward '([^']+)' failed|timed out after [\d.]+",
)
GRAMMAR_RE = re.compile(r"compiled grammar is too large", re.IGNORECASE)
TRIAL_TIMEOUT_RE = re.compile(r"Verifier execution timed out after [\d.]+")
VERIFIER_TEXT_FILES = ("runtime.log", "test-stdout.txt", "test-stderr.txt", "reward-details.json", "verifier-report.json")
F3_FIX = {
    "grammar": "split the judge group (<=15 criteria per judge dir) so the structured-output grammar compiles, then re-run",
    "timeout": "raise [verifier] timeout_sec / the judge timeout, or cut criteria per group, then re-run",
    "crash": "read the traceback and fix the test/verifier code or the deliverable path it names, then re-run",
}


def _run_dirs(revision: Path) -> list[Path]:
    evaluations = revision / "evaluations"
    if not evaluations.is_dir():
        return []
    return sorted(p for p in evaluations.iterdir() if p.is_dir())


def _run_reward(verifier: Path) -> float | None:
    rj = verifier / "reward.json"
    if rj.is_file():
        try:
            data = json.loads(rj.read_text(encoding="utf-8"))
            value = data.get("reward") if isinstance(data, dict) else data
            if isinstance(value, (int, float)):
                return float(value)
        except (OSError, json.JSONDecodeError):
            pass
    rt = verifier / "reward.txt"
    if rt.is_file():
        try:
            return float(rt.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pass
    return None


def _errored_criteria(details: Path) -> list[str]:
    """``group:criterion (error)`` for every criterion in reward-details.json that carries an ``error``."""
    try:
        payload = json.loads(details.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out: list[str] = []
    if not isinstance(payload, dict):
        return out
    for group, block in payload.items():
        crits = block.get("criteria") if isinstance(block, dict) else None
        for c in crits if isinstance(crits, list) else []:
            if isinstance(c, dict) and c.get("error"):
                out.append(f"{group}:{c.get('name', '?')} ({str(c['error'])[:60]})")
    return out


def _rel_run(run: Path) -> str:
    parts = run.parts
    return "/".join(parts[parts.index("evaluations") - 1:]) if "evaluations" in parts else str(run)


def run_health_findings(revision: Path) -> tuple[list[dict], int]:
    """F2 + F3 over every evaluation under ``revision``. Returns (findings, n_runs_seen)."""
    findings: list[dict] = []
    runs = _run_dirs(revision)
    for run in runs:
        verifier = run / "eval_files" / "verifier"
        if not verifier.is_dir():
            continue
        is_oracle = "oracle" in run.name.lower()
        texts: dict[str, str] = {}
        for name in VERIFIER_TEXT_FILES:
            f = verifier / name
            if f.is_file():
                try:
                    texts[name] = f.read_text(encoding="utf-8", errors="replace")[:5_000_000]
                except OSError:
                    continue
        trial_timeout = None
        trial = run / "eval_files" / "trial.log"
        if trial.is_file():
            try:
                m = TRIAL_TIMEOUT_RE.search(trial.read_text(encoding="utf-8", errors="replace"))
                trial_timeout = m.group(0) if m else None
            except OSError:
                pass
        grammar_files = [n for n, t in texts.items() if GRAMMAR_RE.search(t)]
        if is_oracle:
            reward = _run_reward(verifier)
            if reward is not None and reward < 1.0 - 1e-9:
                shown = reward
                findings.append({
                    "kind": "oracle_reward_below_one",
                    "severity": "warn",
                    "run": run.name,
                    "reward": reward,
                    "evidence": f"{_rel_run(run)}/eval_files/verifier/reward.json: oracle reward {shown} (golden should score 1.0). "
                                "Fix: read reward-details.json for the criteria the golden fails and correct the criterion or the golden",
                })
            if grammar_files:
                findings.append({
                    "kind": "oracle_grammar_too_large",
                    "severity": "warn",
                    "run": run.name,
                    "evidence": f"{_rel_run(run)}/eval_files/verifier/{grammar_files[0]}: 'compiled grammar is too large'. Fix: {F3_FIX['grammar']}",
                })
        signals: list[str] = []
        groups: set[str] = set()
        where: list[str] = []
        for name, text in texts.items():
            hit = False
            for m in CRASH_RE.finditer(text):
                hit = True
                if m.group(1):
                    groups.add(m.group(1))
                sig = m.group(0)[:60]
                if sig not in signals and len(signals) < 4:
                    signals.append(sig)
            if hit:
                where.append(name)
        if trial_timeout:
            signals.append(trial_timeout)
            where.append("../trial.log")
        if not signals:
            continue
        cause = "grammar" if grammar_files else "timeout" if any("timed out" in x for x in signals) else "crash"
        details = verifier / "reward-details.json"
        errored = _errored_criteria(details) if details.is_file() else []
        findings.append({
            "kind": "verifier_crash",
            "severity": "warn",
            "run": run.name,
            "oracle": is_oracle,
            "signals": signals,
            "groups": sorted(groups),
            "criteria": errored[:10],
            "evidence": f"{_rel_run(run)}/eval_files/verifier/{where[0]}: {', '.join(signals[:3])}"
                        + (f" in {', '.join(sorted(groups))}" if groups else "")
                        + (f"; errored criteria {'; '.join(errored[:4])}" if errored else "")
                        + f". Fix: {F3_FIX[cause]}",
        })
    return findings, len(runs)


def check_task(task_dir: Path) -> dict:
    revision = resolve_revision_dir(task_dir)
    package = resolve_package_dir(task_dir)
    result: dict = {
        "task_id": task_dir.name if task_dir.name != "task_files" else revision.parent.name,
        "status": "skip",
        "findings": [],
        "n_findings": 0,
        "revision": str(revision),
    }
    run_findings, n_runs = run_health_findings(revision)
    details_files = _oracle_detail_files(revision)
    if not details_files:
        if n_runs:
            result["findings"] = run_findings
            result["n_findings"] = len(run_findings)
            result["status"] = "warn" if run_findings else "pass"
        return result

    per_criterion: dict[str, list[tuple[str, float, str]]] = {}
    for path in details_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        run = next((part for part in path.parts if part.startswith("eval_")), path.name)
        for name, block in payload.items():
            if not isinstance(block, dict):
                continue
            score = _score(block)
            if score is None:
                continue
            per_criterion.setdefault(str(name), []).append((run, score, _reasoning(block)))

    findings: list[dict] = []
    for name, rows in per_criterion.items():
        rounded = {round(score, 9) for _, score, _ in rows}
        if len(rounded) > 1:
            findings.append(
                {
                    "kind": "oracle_criterion_disagreement",
                    "severity": "warn",
                    "criterion": name,
                    "runs": [{"run": run, "score": score} for run, score, _ in rows],
                }
            )

    corpus = _source_corpus(package) if package else ""
    corpus_cf = corpus.casefold()
    if corpus_cf:
        for name, rows in per_criterion.items():
            for run, score, reasoning in rows:
                if score > 0 and not math.isclose(score, 0.0, abs_tol=1e-9):
                    continue
                if not FABRICATED_RE.search(reasoning):
                    continue
                quotes = [q for q in QUOTED_RE.findall(reasoning) if q.casefold() in corpus_cf]
                if quotes:
                    findings.append(
                        {
                            "kind": "fabricated_claim_present_in_sources",
                            "severity": "warn",
                            "criterion": name,
                            "run": run,
                            "quotes": quotes[:5],
                        }
                    )

    findings.extend(run_findings)
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
