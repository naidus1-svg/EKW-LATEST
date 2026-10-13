#!/usr/bin/env python3
"""Deterministic pre-ship static checks for SVC-PC rubric packages. Stdlib only.

CALIBRATED against wave-1 DataOS returns + the rewardkit weight convention (see the header
comment in packages like SVC-PC-1-5-0/tests/reward.toml). Only ONE static condition is a proven
hard blocker; everything else about weights is advisory, because rewardkit normalizes and the
pinned 0.1.7 ignores the reward.toml weights table entirely.

HARD BLOCK (exit 1, keep the task OUT of a DataOS batch until fixed):
  1. criteria_per_dir > MAX (default 20). A judge dir with too many criteria overflows Anthropic's
     structured-output grammar at grade time ("The compiled grammar is too large" -> HTTP 400 ->
     reward 0.0 on EVERY run incl the golden). Our sandbox oracle runs LLM_BACKEND_FORCE=cli, which
     skips grammar compilation and FALSE-PASSES these (wave 1, SVC-PC-1-2-0 at 43: our oracle 1.0,
     DataOS oracle 0.0, all 3 seats filed 1.8 major). Threshold CALIBRATED 2026-09-21 against real
     DataOS passes: SVC-PC-2-6-0 passed with three 18-criteria dirs and SVC-PC-46-4-0 passed with a
     17-criteria dir, while 1-2-0 broke at 43. So 15 (DataOS's cautious recommendation) over-flags;
     18 demonstrably grades fine. Default raised to 20 (just above the confirmed-safe 18); the
     certain breakers (24, 25, 35, 38, 43, 57) still fail. The true limit depends on description
     length too, so this is a heuristic, not a proven per-count cliff.
  2. a deliverables* dir with NEITHER judge.toml NOR a .py checker (checks.py). A dimension with no
     grader is broken. NOTE: a dir with checks.py and no judge.toml is a VALID .py-only dimension
     (intentional in this corpus) and is NOT flagged.

ADVISORY (printed, never affects exit): reward.toml weight-sum, criterion-vs-[judge] weight, and
package size. reward-sum != 1.0 is HARMLESS (rewardkit normalizes / 0.1.7 ignores the table); it is
kept only as a possible coverage-gap tell. criterion-sum != [judge] weight is a known lint
interaction for .py-only-dimension tasks, not a defect. Missing weights table = valid default.

Usage:
  svc_rubric_static_check.py <task_dir>                        human report, exit 0/1 on HARD only
  svc_rubric_static_check.py <task_dir> --judge-only --quiet   one line PASS/FAIL, exit 0/1
  svc_rubric_static_check.py --scan <corpus_root>              table across every SVC-PC-* task
"""

import argparse
import os
import re
import sys

CRIT_RE = re.compile(r"^\s*\[\[\s*criterion\s*\]\]\s*$", re.M)
WEIGHTS_RE = re.compile(r"weights\s*=\s*\{(.+?)\}", re.S)
KV_RE = re.compile(r"([A-Za-z0-9_]+)\s*=\s*([0-9]*\.?[0-9]+)")


def read(p):
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def count_criteria(text):
    return len(CRIT_RE.findall(text))


def judge_weight(text):
    head = re.split(r"\[\[\s*criterion\s*\]\]", text, maxsplit=1)[0]
    m = re.search(r"^\s*weight\s*=\s*([0-9]*\.?[0-9]+)", head, re.M)
    return float(m.group(1)) if m else None


def criterion_weights(text):
    parts = re.split(r"\[\[\s*criterion\s*\]\]", text)
    ws = []
    for blk in parts[1:]:
        m = re.search(r"^\s*weight\s*=\s*([0-9]*\.?[0-9]+)", blk, re.M)
        if m:
            ws.append(float(m.group(1)))
    return ws


def parse_reward_weights(text):
    m = WEIGHTS_RE.search(text)
    return {k: float(v) for k, v in KV_RE.findall(m.group(1))} if m else {}


def dir_size_bytes(path):
    total = 0
    for root, _, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total


def check_task(task_dir, max_criteria=20, size_warn_mb=10):
    """Return (hard_fails, advisories, facts). Exit status keys on hard_fails only."""
    hard, adv, facts = [], [], {}
    tests = os.path.join(task_dir, "tests")
    if not os.path.isdir(tests):
        return (["no tests/ dir"], [], facts)

    deliv = sorted(
        d
        for d in os.listdir(tests)
        if d.startswith("deliverables") and os.path.isdir(os.path.join(tests, d))
    )
    facts["deliv_dirs"] = deliv

    max_crit = 0
    over = []
    for d in deliv:
        dpath = os.path.join(tests, d)
        jt = os.path.join(dpath, "judge.toml")
        has_py = any(fn.endswith(".py") for fn in os.listdir(dpath))
        if not os.path.isfile(jt):
            if not has_py:
                hard.append(
                    f"{d}: no judge.toml and no .py checker (dimension has no grader)"
                )
            # else: valid .py-only dimension, silent
            continue
        txt = read(jt)
        n = count_criteria(txt)
        max_crit = max(max_crit, n)
        if n > max_criteria:
            over.append(f"{d}={n}")
        jw, cws = judge_weight(txt), criterion_weights(txt)
        if jw is not None and cws and abs(sum(cws) - jw) > 0.005:
            adv.append(
                f"{d}: criterion-sum {sum(cws):.4f} != [judge] {jw:.4f} (lint only, not a defect)"
            )
    facts["max_criteria"] = max_crit
    if over:
        hard.append(f"criteria-per-dir > {max_criteria}: {', '.join(over)}")

    rt = os.path.join(tests, "reward.toml")
    if os.path.isfile(rt):
        rw = parse_reward_weights(read(rt))
        if rw:
            s = sum(rw.values())
            facts["reward_sum"] = round(s, 6)
            # normalized/raw-scale both fine; flag only a near-1 gap as a possible dropped-criterion tell
            if 0.90 < s < 1.0 - 1e-9:
                adv.append(
                    f"reward-sum {s:.6f} just under 1.0 (possible dropped-criterion tell, rewardkit still normalizes)"
                )
        else:
            facts["reward_sum"] = "none"  # valid: weight by [judge] weight
    else:
        hard.append("missing reward.toml")

    sz = dir_size_bytes(task_dir)
    facts["size_mb"] = round(sz / 1e6, 1)
    if sz > size_warn_mb * 1e6:
        adv.append(
            f"package {facts['size_mb']} MB (advisory; _corpus_subtree may be load-bearing)"
        )

    return (hard, adv, facts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--judge-only", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--max-criteria", type=int, default=20)
    ap.add_argument("--size-warn-mb", type=float, default=10)
    a = ap.parse_args()

    if a.scan:
        tasks = sorted(
            d
            for d in os.listdir(a.target)
            if d.startswith("SVC-PC") and os.path.isdir(os.path.join(a.target, d))
        )
        nfail = 0
        print(
            f'{"task":16s} {"maxCrit":>7s} {"rewardSum":>10s} {"MB":>6s}  status  hard-block reason'
        )
        for t in tasks:
            hard, adv, facts = check_task(
                os.path.join(a.target, t), a.max_criteria, a.size_warn_mb
            )
            if hard:
                nfail += 1
            status = "FAIL" if hard else "PASS"
            print(
                f'{t:16s} {facts.get("max_criteria", "?"):>7} {str(facts.get("reward_sum", "?")):>10} '
                f'{facts.get("size_mb", "?"):>6}  {status}  {"; ".join(hard)}'
            )
        print(
            f"\n{len(tasks)} tasks, {nfail} HARD-blocked (grammar/empty-dim), {len(tasks) - nfail} static-clean"
        )
        return 0

    hard, adv, facts = check_task(a.target, a.max_criteria, a.size_warn_mb)
    if a.judge_only and a.quiet:
        print("PASS" if not hard else "FAIL: " + "; ".join(hard))
        return 1 if hard else 0
    print(f"== {os.path.basename(os.path.normpath(a.target))} ==")
    print(f'  deliverable dirs: {facts.get("deliv_dirs")}')
    print(
        f'  max criteria/dir: {facts.get("max_criteria")}  (hard limit {a.max_criteria})'
    )
    print(f'  reward.toml sum:  {facts.get("reward_sum")}')
    print(f'  package size:     {facts.get("size_mb")} MB')
    for f in hard:
        print(f"  HARD-FAIL: {f}")
    for w in adv:
        print(f"  advisory: {w}")
    print("  => " + ("PASS" if not hard else "FAIL"))
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
