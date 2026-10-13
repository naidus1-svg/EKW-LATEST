#!/usr/bin/env python3
"""Aggregate N repeated QC runs of the same spec+corpus to measure judge-noise
stability. LLM judges are stochastic; a single run's severities and verdicts
carry noise. This reports, per task and per dimension, how much the outcome moves
across runs, so you can tell a stable signal from a flapping one before trusting
(or promoting) a dimension.

Reuses the batch_review.json shape (d["samples"][i] -> {sample_id, verdict,
all_findings:[{dimension, severity, applicable, gate_role}]}).

Usage:
  consistency.py runA/batch_review.json runB/... runC/... [--out f.md]
                 [--expected <corpus_dir>] [--focus dimA,dimB]
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ABSENT = None


def load(path: Path) -> dict[str, dict]:
    d = json.loads(path.read_text(encoding="utf-8"))
    return {s["sample_id"]: s for s in d.get("samples", [])}


def sev_of(sample: dict, dim: str) -> int | None:
    """Severity of an applicable finding for dim in this run, else None (absent/skipped)."""
    for f in sample.get("all_findings", []):
        if f["dimension"] == dim and f.get("applicable"):
            return f["severity"]
    return None


def role_of(runs: list[dict[str, dict]], dim: str) -> str:
    for run in runs:
        for s in run.values():
            for f in s.get("all_findings", []):
                if f["dimension"] == dim:
                    return f.get("gate_role", "?")
    return "?"


def read_expected(corpus: Path | None) -> dict[str, str]:
    if not corpus:
        return {}
    return {p.parent.name: p.read_text(encoding="utf-8").strip()
            for p in sorted(corpus.glob("*/expected_verdict.txt"))}


def _spread_flag(sevs: list[int]) -> str:
    if not sevs:
        return "—"
    rng = max(sevs) - min(sevs)
    if rng == 0:
        return "stable"
    if rng == 1:
        return "±1"
    return "NOISY"          # varies by >=2 across runs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", type=Path, help="2+ batch_review.json paths")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--expected", type=Path)
    ap.add_argument("--focus", default="",
                    help="comma-separated dims to highlight first (e.g. the new/amended ones)")
    args = ap.parse_args()
    if len(args.runs) < 2:
        ap.error("need at least 2 runs")

    runs = [load(p) for p in args.runs]
    n = len(runs)
    expected = read_expected(args.expected)
    focus = [x.strip() for x in args.focus.split(",") if x.strip()]
    tasks = sorted(set().union(*[set(r) for r in runs]))
    dims = sorted({f["dimension"] for r in runs for s in r.values()
                   for f in s.get("all_findings", [])})
    ordered_dims = focus + [d for d in dims if d not in focus]

    L: list[str] = []
    L.append(f"# QC consistency across {n} runs")
    L.append("")
    L.append("Runs: " + ", ".join(str(p.parent.name) for p in args.runs))
    L.append("")

    # 1. Verdict stability per task
    L.append("## Verdict stability")
    L.append("| task | expected | verdicts across runs | stable? |")
    L.append("|---|---|---|---|")
    for t in tasks:
        vs = [runs[i].get(t, {}).get("verdict", "(absent)") for i in range(n)]
        stable = "yes" if len(set(vs)) == 1 else f"**FLAPS** ({len(set(vs))})"
        exp = expected.get(t, "—")
        L.append(f"| {t} | {exp} | {' · '.join(vs)} | {stable} |")
    L.append("")

    # 2. Per-dimension severity stability (focus dims first)
    L.append("## Dimension severity stability (per task)")
    L.append("Severity across runs; `–` = not applicable/skipped that run.")
    L.append("")
    L.append("| dimension | role | task | severities | spread | mean |")
    L.append("|---|---|---|---|---|---|")
    for dim in ordered_dims:
        role = role_of(runs, dim)
        star = " ⭐" if dim in focus else ""
        for t in tasks:
            sevs_raw = [sev_of(runs[i].get(t, {}), dim) for i in range(n)]
            present = [x for x in sevs_raw if x is not None]
            cells = "·".join("–" if x is None else str(x) for x in sevs_raw)
            spread = _spread_flag(present)
            mean = f"{statistics.mean(present):.1f}" if present else "—"
            L.append(f"| {dim}{star} | {role} | {t} | {cells} | {spread} | {mean} |")
    L.append("")

    # 3. Noise summary — which dims flap by >=2 anywhere
    L.append("## Noise summary")
    noisy = []
    for dim in ordered_dims:
        for t in tasks:
            present = [x for x in (sev_of(runs[i].get(t, {}), dim) for i in range(n))
                       if x is not None]
            if present and (max(present) - min(present)) >= 2:
                noisy.append((dim, t, present))
    if noisy:
        L.append(f"Dimensions with a ≥2 severity swing on some task ({len(noisy)}):")
        for dim, t, present in noisy:
            L.append(f"- `{dim}` on {t}: {present}")
    else:
        L.append("No dimension swings ≥2 severity on any task — good stability.")
    L.append("")

    # 4. Blocking-dim caution: flag focus dims that are blocking AND unstable
    L.append("## Promotion caution (blocking + unstable focus dims)")
    any_flag = False
    for dim in focus:
        role = role_of(runs, dim)
        if role != "blocking":
            continue
        for t in tasks:
            present = [x for x in (sev_of(runs[i].get(t, {}), dim) for i in range(n))
                       if x is not None]
            if present and (max(present) - min(present)) >= 2:
                any_flag = True
                L.append(f"- `{dim}` (blocking) swings {present} on {t} — "
                         f"verdict-affecting AND noisy; needs rubric tightening before trust.")
    if not any_flag:
        L.append("No blocking focus dimension shows a ≥2 swing.")
    L.append("")

    md = "\n".join(L)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
