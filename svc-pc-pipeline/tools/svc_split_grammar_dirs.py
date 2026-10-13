#!/usr/bin/env python3
"""Split judge dirs with > MAX criteria into <= MAX-criteria sub-dirs, to fix the DataOS
grammar-too-large 1.8 failure (a judge dir over ~15 criteria overflows the structured-output
grammar -> reward 0.0). Deterministic and share-preserving:

  For an over-limit dir D with [judge] weight w_D and criteria summing to S_D, partition its
  criteria into k = ceil(n/MAX) balanced groups. Each new sub-dir keeps its criteria VERBATIM
  (weights unchanged) and gets [judge] weight = w_D * (sum of its criteria) / S_D. The first
  group stays in D; the rest go to D_p2, D_p3, ... reward.toml weights table (if present) is
  updated the same proportional way; if absent, rewardkit weights by [judge] weight and needs
  no table edit.

  Because every criterion keeps its exact weight and each sub-dir's weight is its share of the
  parent, the global effective weight of every criterion is preserved, so non-golden grading is
  unchanged and the golden (all-pass) stays at reward 1.0. Verify with the oracle after.

Usage: svc_split_grammar_dirs.py <task_dir> [--max 15] [--apply]   (dry-run without --apply)
"""

import argparse
import math
import os
import re
import shutil
import sys

CRIT_SPLIT = re.compile(r"(?=^\s*\[\[\s*criterion\s*\]\])", re.M)
WEIGHT_LINE = re.compile(r"^(\s*weight\s*=\s*)([0-9]*\.?[0-9]+)", re.M)


def parse_judge(text):
    """Return (head_text, [criterion_block_text,...])."""
    parts = CRIT_SPLIT.split(text)
    head = parts[0]
    crits = [p for p in parts[1:] if p.strip()]
    return head, crits


def head_weight(head):
    m = WEIGHT_LINE.search(head)
    return float(m.group(2)) if m else None


def crit_weight(block):
    m = WEIGHT_LINE.search(block)
    return float(m.group(2)) if m else 0.0


def set_head_weight(head, w):
    return WEIGHT_LINE.sub(lambda m: f"{m.group(1)}{w:.6f}", head, count=1)


def balanced_groups(items, maxsize):
    k = math.ceil(len(items) / maxsize)
    # distribute as evenly as possible, no group over maxsize
    base, extra = divmod(len(items), k)
    groups, i = [], 0
    for g in range(k):
        size = base + (1 if g < extra else 0)
        groups.append(items[i : i + size])
        i += size
    return groups


def parse_reward_weights(text):
    m = re.search(r"weights\s*=\s*\{(.+?)\}", text, re.S)
    if not m:
        return None, None
    inner = m.group(1)
    kv = re.findall(r"([A-Za-z0-9_]+)\s*=\s*([0-9]*\.?[0-9]+)", inner)
    return m, [(k, float(v)) for k, v in kv]


def split_task(task_dir, maxc=15, apply=False):
    tests = os.path.join(task_dir, "tests")
    deliv = sorted(
        d
        for d in os.listdir(tests)
        if d.startswith("deliverables") and os.path.isdir(os.path.join(tests, d))
    )
    actions = []
    # dir -> list of (new_dir_name, summed_weight) for reward.toml rewrite
    reward_repl = {}
    for d in deliv:
        jt = os.path.join(tests, d, "judge.toml")
        if not os.path.isfile(jt):
            continue
        with open(jt, encoding="utf-8") as f:
            text = f.read()
        head, crits = parse_judge(text)
        if len(crits) <= maxc:
            continue
        w_D = head_weight(head)
        S_D = sum(crit_weight(c) for c in crits) or 1.0
        groups = balanced_groups(crits, maxc)
        newdirs = []
        for gi, grp in enumerate(groups):
            grp_sum = sum(crit_weight(c) for c in grp)
            new_w = (w_D * grp_sum / S_D) if w_D is not None else grp_sum
            dname = d if gi == 0 else f"{d}_p{gi + 1}"
            newdirs.append((dname, new_w, grp))
            reward_repl.setdefault(d, []).append((dname, new_w))
        actions.append((d, len(crits), [(n, len(g)) for n, _, g in newdirs]))
        if apply:
            for dname, new_w, grp in newdirs:
                ddir = os.path.join(tests, dname)
                os.makedirs(ddir, exist_ok=True)
                new_head = set_head_weight(head, new_w) if w_D is not None else head
                body = (
                    new_head.rstrip()
                    + "\n\n"
                    + "\n".join(c.rstrip() + "\n" for c in grp)
                )
                with open(
                    os.path.join(ddir, "judge.toml"),
                    "w",
                    encoding="utf-8",
                    newline="\n",
                ) as f:
                    f.write(body)

    # rewrite reward.toml weights table if present and any dir was split
    rt = os.path.join(tests, "reward.toml")
    if apply and reward_repl and os.path.isfile(rt):
        with open(rt, encoding="utf-8") as f:
            rtext = f.read()
        m, kv = parse_reward_weights(rtext)
        if m and kv:
            newkv = []
            for k, v in kv:
                if k in reward_repl:
                    subs = reward_repl[k]
                    ssum = sum(w for _, w in subs) or 1.0
                    for name, w in subs:
                        newkv.append((name, v * w / ssum))
                else:
                    newkv.append((k, v))
            inner = ", ".join(f"{k} = {v:.6f}" for k, v in newkv)
            rtext = rtext[: m.start(1)] + inner + rtext[m.end(1) :]
            with open(rt, "w", encoding="utf-8", newline="\n") as f:
                f.write(rtext)
    return actions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task_dir")
    ap.add_argument("--max", type=int, default=15)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    actions = split_task(a.task_dir, a.max, a.apply)
    name = os.path.basename(os.path.normpath(a.task_dir))
    if not actions:
        print(f"{name}: nothing to split (all dirs <= {a.max})")
        return 0
    for d, n, newdirs in actions:
        print(
            f"{name}: {d} ({n} crit) -> " + ", ".join(f"{nm}={c}" for nm, c in newdirs)
        )
    print(f"{name}: {'APPLIED' if a.apply else 'DRY-RUN'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
