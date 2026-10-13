#!/usr/bin/env python3
r"""PROTOTYPE, not a rollout tool. Answers one question from
`ekw/svc-dataos-failure-mode-tracker-2026-09-15.md` row 5's Step 3: is the cross-group
weighting half of the "declared rubric weights not applied" defect mechanically
bulk-fixable? Verified yes -- this script IS the mechanical fix, derived from real
source, not invented.

Root cause, confirmed by reading the actual generator (`pipeline/tools/to_rewardkit.py`,
lines ~1108-1137): when a task's criteria are chunked into `tests/deliverables_NN/`
folders, that code already computes `chunk_weight = round(sum(c["weight"] for c in
chunk), 6)` and writes it as each chunk's `[judge].weight`, with its OWN comment stating
the intent explicitly: "Set [judge].weight = that chunk's own criteria weight-sum so the
cross-chunk aggregation reconstructs the intended flat-pool weighting instead." But
`tests/reward.toml` is written earlier (line ~1075) as a bare hardcoded string --
`'[[reward]]\nname = "reward"\naggregation = "weighted_mean"\n'` -- with no weights
table, and nothing ever feeds the chunk weights back into it. The intended number is
computed and discarded, not merely absent. This script recovers it by re-reading each
group's own `[judge].weight`, exactly as rewardkit's `runner.py` does at run time --
no re-derivation, no judgment call about what a weight "should" be.

Confirmed at full-corpus scale (read-only scan, this session, 2026-09-16, all 600 real
tasks under `03_dataos_ready`): 2246 of 2252 groups (99.7%) have `[judge].weight` equal
to that group's own sum(criterion weight) within 1e-3; all 511 multi-group tasks have
their groups' judge.weight values summing to 1.0 exactly; 0 of 600 reward.toml files
have a populated weights table today. The 6 exceptions (SVC-PC-51-1-0/2-0/6-0's
deliverables_04/05 -- a real drift, e.g. 51-1-0/deliverables_04: judge.weight=0.21 vs
its own criteria summing to 0.18, most likely stale after a later duplicate-criterion
removal never propagated back up) are detected below and SKIPPED, not silently
patched over -- this script propagates judge.toml's declared weight verbatim (the value
rewardkit actually reads), and flags disagreement with the group's own criteria sum as
a separate, narrower data-quality issue outside this script's job.

This script does NOT touch the must-pass gating sub-issue. That one is NOT mechanically
bulk-fixable the same way -- see this session's tracker update (row 5, Step 3) for why:
1541 of 1577 real groups (97.7%) carrying 1+ must-pass criterion mix them with
non-must-pass criteria in the SAME rewardkit group, and rewardkit's aggregate_scores()
(confirmed in the installed harbor-rewardkit 0.2.0 source) has exactly one aggregation
per group -- switching a mixed group to required_pass/all_pass would zero every OTHER
criterion's partial credit in that group too, not just gate the must-pass ones. Also,
`to_rewardkit.py` (lines 351-397) shows this was ALREADY a deliberate, disclosed design
choice by whoever wrote the converter ("must_pass gates get no native reward-kit
equivalent ... approximated as a heavily-weighted ... criterion"), not an oversight like
the weights-table omission above -- reversing it is a scoring-philosophy decision, not a
bug fix. A working, ALREADY-CORRECT gate exists at a different layer entirely
(`rubric_xlsx_to_verifier.py`'s `evaluate_release_outcome`, replayed by
`certification_gate_check.py`: a must-pass failure sets `gate_implied_reward = 0.0` for
the WHOLE task) -- the more defensible fix path is likely a harness-level decision to
use that number as the authoritative reward, not a per-task reward.toml edit. Out of
scope for this script either way.

What this script does, per task directory:
  1. Read every `tests/deliverables*/judge.toml`, collecting {group_name: [judge].weight}.
  2. Skip (no-op, report "not_applicable") if fewer than 2 groups, if any group's
     [judge].weight is missing, or if all groups' weights are already equal --
     matching weight_application_check.py's own "nothing to flag" conditions exactly,
     so this script never touches a task that check would not have flagged.
  3. Skip (report "weight_drift_detected", do NOT write) if any group's declared
     [judge].weight disagrees with that group's own sum(criterion weight) by more than
     FLOAT_TOL -- a real data-quality question for a human, not something this script
     guesses past.
  4. Skip (report "unexpected_reward_toml_shape") if tests/reward.toml does not match
     the exact known-generated shape (one [[reward]] block named "reward" or the sole
     entry, aggregation="weighted_mean", no existing weights table) -- this script only
     ever adds a table where the check confirmed none exists, never overwrites a
     human's own hand-edit.
  5. Otherwise, back up the existing reward.toml (`.bak-<timestamp>` alongside it) and,
     with --apply, rewrite it with an inline `weights = { ... }` table listing every
     group's own declared weight verbatim, sorted by group name, rounded to 6 decimals
     (matching to_rewardkit.py's own rounding). Without --apply: dry-run, prints the
     diff, writes nothing.

Usage:
    python derive_reward_weights.py <root> --task ID [--task ID ...] [--apply] [--json out.json]
    python derive_reward_weights.py C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready \
        --task SVC-PC-29-2-0 --apply

Restore a task this script changed:
    copy the printed .bak-<timestamp> path back over tests/reward.toml.

Exit 0 if every requested task was either not_applicable or fixed cleanly; 1 if any task
was skipped for drift/unexpected-shape (see the JSON for which); 2 on bad usage. Stdlib
only.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import tomllib
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

FLOAT_TOL = 1e-3


def load_toml(p: Path) -> dict:
    return tomllib.loads(p.read_text(encoding="utf-8"))


def svc_judge_files(task_dir: Path) -> list[Path]:
    return sorted(
        set(task_dir.glob("tests/deliverables/judge.toml"))
        | set(task_dir.glob("tests/deliverables_*/judge.toml"))
    )


def process_task(task_dir: Path, apply: bool) -> dict:
    result: dict = {"task": task_dir.name, "status": None, "detail": None}

    jfiles = svc_judge_files(task_dir)
    if not jfiles:
        result["status"] = "not_applicable"
        result["detail"] = "no tests/deliverables*/judge.toml (not an SVC-PC package)"
        return result

    groups: dict[str, float | None] = {}
    crit_sums: dict[str, float] = {}
    for jf in jfiles:
        data = load_toml(jf)
        group = jf.parent.name
        jw = (data.get("judge") or {}).get("weight")
        groups[group] = float(jw) if isinstance(jw, (int, float)) else None
        crit_sums[group] = sum(
            float(c.get("weight", 1.0)) for c in (data.get("criterion") or [])
        )

    if len(groups) < 2:
        result["status"] = "not_applicable"
        result["detail"] = (
            "single group -- rewardkit needs no cross-group weights table"
        )
        return result

    if any(w is None for w in groups.values()):
        result["status"] = "not_applicable"
        result["detail"] = (
            "a group is missing [judge].weight -- weight_application_check.py's own "
            "disclosed dead branch (0/511 real tasks hit this as of 2026-09-15); "
            "not safe to guess a value here"
        )
        return result

    vals = list(groups.values())
    if (max(vals) - min(vals)) <= FLOAT_TOL:
        result["status"] = "not_applicable"
        result["detail"] = (
            "all group weights already equal -- unweighted mean == weighted mean"
        )
        return result

    drift = {
        g: (groups[g], crit_sums[g])
        for g in groups
        if abs(groups[g] - crit_sums[g]) > FLOAT_TOL
    }
    if drift:
        result["status"] = "weight_drift_detected"
        result["detail"] = (
            f"[judge].weight disagrees with that group's own sum(criterion weight) in "
            f"{len(drift)} group(s) -- (declared, criteria_sum): {drift}. This is a real "
            "data-quality question (which number is authoritative?), not something this "
            "script resolves; skipped, nothing written."
        )
        return result

    reward_path = task_dir / "tests" / "reward.toml"
    if not reward_path.is_file():
        result["status"] = "unexpected_reward_toml_shape"
        result["detail"] = "tests/reward.toml does not exist"
        return result
    raw_text = reward_path.read_text(encoding="utf-8")
    try:
        rdata = load_toml(reward_path)
    except Exception as e:  # noqa: BLE001
        result["status"] = "unexpected_reward_toml_shape"
        result["detail"] = f"reward.toml failed to parse: {e}"
        return result
    rewards = rdata.get("reward") or []
    if len(rewards) != 1:
        result["status"] = "unexpected_reward_toml_shape"
        result["detail"] = (
            f"expected exactly one [[reward]] block, found {len(rewards)}"
        )
        return result
    spec = rewards[0]
    if spec.get("weights"):
        result["status"] = "unexpected_reward_toml_shape"
        result["detail"] = (
            "reward.toml already has a non-empty weights table -- not touching a hand-edit"
        )
        return result
    if spec.get("aggregation", "weighted_mean") != "weighted_mean":
        result["status"] = "unexpected_reward_toml_shape"
        result["detail"] = (
            f"aggregation is {spec.get('aggregation')!r}, not the expected 'weighted_mean'"
        )
        return result
    name = spec.get("name") or "reward"

    weights_str = ", ".join(f"{g} = {round(groups[g], 6)}" for g in sorted(groups))
    new_text = (
        f'[[reward]]\nname = "{name}"\naggregation = "weighted_mean"\n'
        f"weights = {{ {weights_str} }}\n"
    )

    result["status"] = "fix_derived"
    result["derived_weights"] = {g: round(groups[g], 6) for g in sorted(groups)}
    result["old_text"] = raw_text
    result["new_text"] = new_text

    if apply:
        backup_path = reward_path.with_name(
            f"reward.toml.bak-{time.strftime('%Y%m%dT%H%M%S')}"
        )
        shutil.copy2(reward_path, backup_path)
        # Confirm the backup is byte-identical before touching the original.
        if backup_path.read_bytes() != reward_path.read_bytes():
            result["status"] = "backup_verification_failed"
            result["detail"] = (
                f"backup at {backup_path} did not match original; nothing written"
            )
            return result
        reward_path.write_text(new_text, encoding="utf-8", newline="\n")
        # Read back and confirm the write landed and re-parses to the same weights.
        reread = load_toml(reward_path)
        reread_weights = (reread.get("reward") or [{}])[0].get("weights") or {}
        if {g: round(v, 6) for g, v in reread_weights.items()} != result[
            "derived_weights"
        ]:
            result["status"] = "write_verification_failed"
            result["detail"] = "post-write re-read did not match derived weights"
            return result
        result["backup_path"] = str(backup_path)
        result["status"] = "fix_applied"

    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("root", help="package root, or a single task dir")
    ap.add_argument(
        "--task", action="append", default=[], help="task id(s), repeatable"
    )
    ap.add_argument(
        "--apply", action="store_true", help="write changes (default: dry-run)"
    )
    ap.add_argument("--json", help="write full JSON results here")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2

    if (root / "tests").is_dir():
        task_dirs = [root]
    elif args.task:
        task_dirs = [root / t for t in args.task if (root / t).is_dir()]
        missing = [t for t in args.task if not (root / t).is_dir()]
        for m in missing:
            sys.stderr.write(f"warning: task id not found under {root}: {m}\n")
    else:
        sys.stderr.write(
            "refusing to run over every task under root without --task -- this is a prototype, not a rollout tool\n"
        )
        return 2

    if not task_dirs:
        sys.stderr.write("no task directories matched\n")
        return 2

    results = [process_task(d, args.apply) for d in task_dirs]
    for r in results:
        line = f"{r['status']:<26} {r['task']:<20} {r.get('detail', '')}"
        print(line)
        if r["status"] in ("fix_derived", "fix_applied"):
            print(f"    weights: {r['derived_weights']}")
            if r["status"] == "fix_applied":
                print(f"    backup: {r['backup_path']}")

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")

    bad = [
        r
        for r in results
        if r["status"] not in ("not_applicable", "fix_derived", "fix_applied")
    ]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
