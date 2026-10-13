#!/usr/bin/env python3
"""Turn a DataOS ``with_runs`` bundle into a per-task evidence worklist.

For each ``task_<id>[_fixed]/rev_*/`` in ``--root``:
  * oracle runs: every criterion scoring < 1.0 (golden fails its own rubric)
  * agent runs: criteria failing >= ``--agent-fail-ratio`` of runs (brittle or
    unstated-requirement candidates), with the judge's first reasoning
  * nop run: reward, and whether it came from a fatal error (whole-task zero)
  * verifications: platform ``qc_*.md`` 15-check outcomes (fail explanations) and
    ``comprehensive_review_*.md`` overall verdicts
  * if ``--package-root`` is given, each flagged criterion is marked
    UNCHANGED / EDITED / DROPPED against that package's current verifier.json

Output: ``<out>/<task>_EVIDENCE.json`` and a combined ``<out>/EVIDENCE_SUMMARY.md``.
Findings are claims for a fixer to verify, not defects.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def prompt_map(package: Path) -> dict[str, str]:
    vj = package / "tests" / "verifier.json"
    if not vj.is_file():
        return {}
    out = {}
    for c in json.loads(vj.read_text(encoding="utf-8")).get("verifiers", []):
        a = c.get("assertion", {})
        out[c["name"]] = a.get("rubric", {}).get("prompt") if a.get("type") == "rubric" else json.dumps(a, sort_keys=True)
    return out


def parse_qc(md: Path) -> dict:
    text = md.read_text(encoding="utf-8", errors="replace")
    status = re.search(r"## status\n(\w+)", text)
    m = re.search(r"A: (\{.*\})\s*$", text, re.S)
    checks = {}
    if m:
        try:
            checks = json.loads(m.group(1)).get("checks", {})
        except json.JSONDecodeError:
            pass
    return {
        "file": md.name,
        "status": status.group(1) if status else None,
        "fails": {k: v.get("explanation") for k, v in checks.items() if v.get("outcome") == "fail"},
        "passes": sorted(k for k, v in checks.items() if v.get("outcome") == "pass"),
    }


def parse_cr(md: Path) -> dict:
    text = md.read_text(encoding="utf-8", errors="replace")
    m = list(re.finditer(r'"overall_verdict"\s*:\s*"([^"]+)"', text))
    return {"file": md.name, "overall_verdict": m[-1].group(1) if m else None}


def sweep_task(rev: Path, ratio: float, package: Path | None) -> dict:
    task = re.sub(r"_fixed$", "", rev.parent.name)
    fb_prompts = prompt_map(rev / "task_files")
    cur_prompts = prompt_map(package) if package else {}

    def state(name: str) -> str:
        if not package:
            return "n/a"
        if name not in cur_prompts:
            return "DROPPED"
        return "UNCHANGED" if cur_prompts[name] == fb_prompts.get(name) else "EDITED"

    oracle_fails: dict[str, list] = {}
    agent_fail: dict[str, int] = {}
    agent_reason: dict[str, str] = {}
    n_agent = 0
    rewards = {}
    nop = None
    for ev in sorted((rev / "evaluations").glob("eval_*")):
        kind = "oracle" if "oracle" in ev.name else ("nop" if ev.name.endswith("__nop") else "agent")
        rd = ev / "eval_files" / "verifier" / "reward-details.json"
        rt = ev / "eval_files" / "verifier" / "reward.txt"
        reward = rt.read_text().strip() if rt.is_file() else ""
        rewards[ev.name] = reward
        if kind == "nop":
            rep = ev / "eval_files" / "verifier" / "verifier-report.json"
            fatal = None
            if rep.is_file():
                try:
                    fatal = json.loads(rep.read_text()).get("fatal_error")
                except json.JSONDecodeError:
                    fatal = "unreadable"
            nop = {"reward": reward, "fatal_error": fatal}
            continue
        if not rd.is_file():
            continue
        try:
            details = json.loads(rd.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if kind == "agent":
            n_agent += 1
        for name, e in details.items():
            if float(e.get("score", 1.0)) >= 1.0:
                continue
            reason = (e.get("criteria") or [{}])[0].get("reasoning", "") or ""
            if kind == "oracle":
                oracle_fails.setdefault(name, []).append({"run": ev.name, "reasoning": reason[:600]})
            else:
                agent_fail[name] = agent_fail.get(name, 0) + 1
                agent_reason.setdefault(name, reason[:600])
    hot = {n: c for n, c in agent_fail.items() if n_agent and c / n_agent >= ratio}
    ver = rev / "verifications"
    return {
        "task": task,
        "rev": rev.name,
        "rewards": rewards,
        "nop": nop,
        "n_agent_runs": n_agent,
        "oracle_failing_criteria": {n: {"runs": v, "state_in_package": state(n), "weight_fb": None} for n, v in oracle_fails.items()},
        "agent_hot_criteria": {n: {"fails": c, "of": n_agent, "state_in_package": state(n), "reasoning": agent_reason[n]} for n, c in sorted(hot.items(), key=lambda kv: -kv[1])},
        "platform_qc": [parse_qc(p) for p in sorted(ver.glob("qc_*.md"))] if ver.is_dir() else [],
        "comprehensive_reviews": [parse_cr(p) for p in sorted(ver.glob("comprehensive_review_*.md"))] if ver.is_dir() else [],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True, help="with_runs bundle dir (task_*/rev_*/...)")
    ap.add_argument("--package-root", type=Path, help="dir of current packages task_<id>/ to diff criteria against")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--agent-fail-ratio", type=float, default=0.75)
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    lines = ["# Evidence summary", ""]
    for tdir in sorted(p for p in args.root.iterdir() if p.is_dir() and p.name.startswith("task_")):
        revs = sorted(tdir.glob("rev_*"))
        if not revs:
            continue
        rev = revs[-1]
        task = re.sub(r"_fixed$", "", tdir.name)
        package = (args.package_root / task) if args.package_root and (args.package_root / task).is_dir() else None
        res = sweep_task(rev, args.agent_fail_ratio, package)
        (args.out / f"{task}_EVIDENCE.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
        qc_fails = sorted({k for q in res["platform_qc"] for k in q["fails"]})
        lines.append(f"## {task}  ({rev.name})")
        lines.append(f"- rewards: " + ", ".join(f"{k.split('__attempt')[0].replace('eval_','')}:{v or '∅'}" for k, v in res["rewards"].items()))
        lines.append(f"- nop: {res['nop']}")
        lines.append(f"- platform QC fails: {qc_fails}")
        for n, v in res["oracle_failing_criteria"].items():
            lines.append(f"- ORACLE FAIL {n} ({len(v['runs'])} run(s), {v['state_in_package']}): {v['runs'][0]['reasoning'][:200]}")
        for n, v in res["agent_hot_criteria"].items():
            lines.append(f"- agents fail {n} {v['fails']}/{v['of']} ({v['state_in_package']}): {v['reasoning'][:200]}")
        lines.append("")
        print(f"{task:9} qc_fails={len(qc_fails)} oracle_fail={len(res['oracle_failing_criteria'])} hot={len(res['agent_hot_criteria'])} nop={res['nop'] and res['nop']['reward']}")
    (args.out / "EVIDENCE_SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.out}/EVIDENCE_SUMMARY.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
