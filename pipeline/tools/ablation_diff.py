#!/usr/bin/env python3
"""Diff two QC runs (baseline vs candidate spec) over the same corpus.

Answers the ablation question: what does adding/amending dimensions do to the
verdicts and per-dimension findings, and does it stay faithful to the expert
labels? Keys on `sample_id` across the two `batch_review.json` files and on
`dimension` within each task, so it handles specs with different dimension sets
(the candidate's new dims show as `added`; anything only in baseline as `removed`).

Reuses the batch_review.json shape read by measure.py:
  d["samples"][i] -> {sample_id, verdict, all_findings:[{dimension, severity,
                      applicable, gate_role, headline}]}

Usage:
  ablation_diff.py <baseline.json> <candidate.json> [--out f.md]
                   [--only-changed] [--sev-threshold N]
                   [--amended dimA,dimB] [--expected <corpus_dir>]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ABSENT = "(absent)"


# ── Data model ──────────────────────────────────────────────────────────────

@dataclass
class FindingDelta:
    dimension: str
    base_sev: int | None      # None ⇒ dim absent/not-applicable in baseline
    cand_sev: int | None
    status: str               # added | removed | changed | same
    base_head: str = ""
    cand_head: str = ""


@dataclass
class TaskDiff:
    task_id: str
    verdict_base: str
    verdict_cand: str
    expected: str | None = None
    deltas: list[FindingDelta] = field(default_factory=list)

    def verdict_changed(self) -> bool:
        return self.verdict_base != self.verdict_cand

    def changed_deltas(self, thr: int) -> list[FindingDelta]:
        out = []
        for d in self.deltas:
            if d.status in ("added", "removed"):
                out.append(d)
            elif d.status == "changed" and abs((d.cand_sev or 0) - (d.base_sev or 0)) >= thr:
                out.append(d)
        return out

    def has_changes(self, thr: int) -> bool:
        return self.verdict_changed() or bool(self.changed_deltas(thr))


# ── Loading ─────────────────────────────────────────────────────────────────

def load_run(path: Path) -> tuple[dict, dict[str, dict]]:
    d = json.loads(path.read_text(encoding="utf-8"))
    samples = {s["sample_id"]: s for s in d.get("samples", [])}
    meta = {"spec_name": d.get("spec_name"), "spec_version": d.get("spec_version"),
            "n": len(samples)}
    return meta, samples


def _headline(f: dict) -> str:
    for k in ("headline", "one_line", "evidence_quote", "detail"):
        v = f.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def index_findings(sample: dict | None) -> dict[str, dict]:
    """dimension -> finding, applicable findings only (skipped dims are absent)."""
    if not sample:
        return {}
    out: dict[str, dict] = {}
    for f in sample.get("all_findings", []):
        if f.get("applicable"):
            out[f["dimension"]] = f
    return out


def read_expected(corpus: Path | None) -> dict[str, str]:
    if not corpus:
        return {}
    out: dict[str, str] = {}
    for p in sorted(corpus.glob("*/expected_verdict.txt")):
        out[p.parent.name] = p.read_text(encoding="utf-8").strip()
    return out


# ── Diff ────────────────────────────────────────────────────────────────────

def diff_task(task_id: str, base: dict | None, cand: dict | None,
              expected: str | None) -> TaskDiff:
    td = TaskDiff(
        task_id=task_id,
        verdict_base=base["verdict"] if base else ABSENT,
        verdict_cand=cand["verdict"] if cand else ABSENT,
        expected=expected,
    )
    fb, fc = index_findings(base), index_findings(cand)
    for dim in sorted(set(fb) | set(fc)):
        b, c = fb.get(dim), fc.get(dim)
        bs = b["severity"] if b else None
        cs = c["severity"] if c else None
        if b and not c:
            status = "removed"
        elif c and not b:
            status = "added"
        elif bs == cs:
            status = "same"
        else:
            status = "changed"
        td.deltas.append(FindingDelta(
            dimension=dim, base_sev=bs, cand_sev=cs, status=status,
            base_head=_headline(b) if b else "", cand_head=_headline(c) if c else "",
        ))
    return td


# ── Rendering ───────────────────────────────────────────────────────────────

def _esc(s: str, cap: int = 130) -> str:
    s = s.replace("|", "\\|").replace("\n", " ").strip()
    return s if len(s) <= cap else s[:cap] + "…"


def _sev(x: int | None) -> str:
    return "–" if x is None else str(x)


def render_markdown(diffs: list[TaskDiff], base_meta: dict, cand_meta: dict,
                    amended: set[str], only_changed: bool, thr: int) -> str:
    L: list[str] = []
    L.append(f"# Ablation: {base_meta.get('spec_version')} (baseline) → "
             f"{cand_meta.get('spec_version')} (candidate)")
    L.append("")
    L.append(f"Corpus: {len(diffs)} tasks · baseline `{base_meta.get('spec_name')} "
             f"{base_meta.get('spec_version')}` vs candidate "
             f"`{cand_meta.get('spec_name')} {cand_meta.get('spec_version')}`")
    L.append("")

    # 1. Verdict transitions
    trans = Counter((d.verdict_base, d.verdict_cand) for d in diffs)
    L.append("## Verdict transitions (baseline → candidate)")
    L.append("| baseline → candidate | count |")
    L.append("|---|---|")
    for (vb, vc), n in trans.most_common():
        mark = "  ← changed" if vb != vc else ""
        L.append(f"| {vb} → {vc}{mark} | {n} |")
    L.append("")

    # 2. Expected-vs-observed (if labels provided)
    if any(d.expected for d in diffs):
        L.append("## Faithfulness to expert label")
        L.append("| task | expected | baseline | candidate |")
        L.append("|---|---|---|---|")
        for d in diffs:
            def mk(v: str) -> str:
                return f"**{v}**" if d.expected and v != d.expected else v
            L.append(f"| {d.task_id} | {d.expected or '—'} | "
                     f"{mk(d.verdict_base)} | {mk(d.verdict_cand)} |")
        L.append("(bold = differs from expert label)")
        L.append("")

    # 3. New / amended dimension impact
    new_dims: dict[str, dict] = defaultdict(lambda: {"applicable": 0, "sev2": 0, "flipped": 0})
    for d in diffs:
        flipped = d.verdict_changed()
        for delta in d.deltas:
            if delta.status == "added" or delta.dimension in amended:
                rec = new_dims[delta.dimension]
                rec["applicable"] += 1
                if (delta.cand_sev or 0) >= 2:
                    rec["sev2"] += 1
                if flipped:
                    rec["flipped"] += 1
    if new_dims:
        L.append("## New / amended dimension impact")
        L.append("| dimension | applicable | sev≥2 fires | on verdict-flipped tasks | note |")
        L.append("|---|---|---|---|---|")
        for dim, rec in sorted(new_dims.items()):
            note = "amended" if dim in amended else "new"
            L.append(f"| {dim} | {rec['applicable']} | {rec['sev2']} | "
                     f"{rec['flipped']} | {note} |")
        L.append("")

    # 4. Per-task deltas
    L.append("## Per-task deltas")
    L.append("| task | verdict Δ | severity deltas | findings added | findings removed |")
    L.append("|---|---|---|---|---|")
    for d in diffs:
        if only_changed and not d.has_changes(thr):
            continue
        vdelta = (f"{d.verdict_base} → {d.verdict_cand}"
                  if d.verdict_changed() else "—")
        cd = d.changed_deltas(thr)
        sev_bits = [f"{x.dimension}: {_sev(x.base_sev)}→{_sev(x.cand_sev)}"
                    for x in cd if x.status == "changed"]
        added = [f"{x.dimension} (\"{_esc(x.cand_head)}\")" for x in cd if x.status == "added"]
        removed = [f"{x.dimension}" for x in cd if x.status == "removed"]
        L.append(f"| {d.task_id} | {vdelta} | {'; '.join(sev_bits) or '—'} | "
                 f"{'; '.join(added) or '—'} | {'; '.join(removed) or '—'} |")
    L.append("")

    # 5. Dimension churn (sev>=2 counts across all tasks)
    base_fire: Counter = Counter()
    cand_fire: Counter = Counter()
    presence: dict[str, set] = defaultdict(set)
    for d in diffs:
        for delta in d.deltas:
            if delta.base_sev is not None:
                presence[delta.dimension].add("base")
                if delta.base_sev >= 2:
                    base_fire[delta.dimension] += 1
            if delta.cand_sev is not None:
                presence[delta.dimension].add("cand")
                if delta.cand_sev >= 2:
                    cand_fire[delta.dimension] += 1
    L.append("## Dimension churn (sev≥2 task counts)")
    L.append("| dimension | baseline | candidate | Δ | present in |")
    L.append("|---|---|---|---|---|")
    for dim in sorted(set(base_fire) | set(cand_fire) | set(presence)):
        b, c = base_fire[dim], cand_fire[dim]
        if b == 0 and c == 0:
            continue
        where = "both" if presence[dim] == {"base", "cand"} else next(iter(presence[dim]))
        L.append(f"| {dim} | {b} | {c} | {c - b:+d} | {where} |")
    L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("baseline", type=Path)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("--out", type=Path, help="write markdown here (default: stdout)")
    ap.add_argument("--only-changed", action="store_true",
                    help="per-task table shows only tasks with a change")
    ap.add_argument("--sev-threshold", type=int, default=1,
                    help="count a severity change only when |Δ| >= N (default 1)")
    ap.add_argument("--amended", default="",
                    help="comma-separated dims amended (not new) to surface in impact table")
    ap.add_argument("--expected", type=Path,
                    help="corpus dir with <task>/expected_verdict.txt for a faithfulness table")
    args = ap.parse_args()

    base_meta, base = load_run(args.baseline)
    cand_meta, cand = load_run(args.candidate)
    expected = read_expected(args.expected)
    amended = {x.strip() for x in args.amended.split(",") if x.strip()}

    task_ids = sorted(set(base) | set(cand))
    diffs = [diff_task(t, base.get(t), cand.get(t), expected.get(t)) for t in task_ids]

    md = render_markdown(diffs, base_meta, cand_meta, amended,
                         args.only_changed, args.sev_threshold)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
