#!/usr/bin/env python3
"""oracle_reproducibility_check -- which criteria give a DIFFERENT verdict on the SAME bytes?

WHY THIS EXISTS (measured, 2026-09-22, 30-task fix session).

Four tasks returned different rewards from two or more ORACLE runs over byte-identical goldens.
A criterion that is not reproducible is the mechanism behind "DataOS fails at random":

  * task_120       two oracle runs, identical `task_checksum`, **0.98 vs 1.00**. `v6c` alone
                   differs (1T/2F in eval_501550, 3T/0F in eval_505918).
  * task_LGL-168   **1.0 vs 0.958**, `v9` alone flips the outcome (2T/1F vs 1T/2F); the judge
                   cites an execution-date/signature point that this criterion's own sibling
                   criteria expressly reward flagging.
  * task_LGL-161   `v14` splits 1T/2F on BOTH oracle runs -- never a clean 3-0 on the golden in
                   any run, so the task's own answer key does not unanimously satisfy it.
  * task_LGL-131   `v13` returned 3-0, 2-1 and 1-2 across three identical copies of the golden.

Mean-of-3 sampling HIDES this. A 2-1 criterion scores 0.667 and a 3-0 scores 1.0; both look
like "a number", and only the vote counts show that one of them is a coin flip. The weighted
reward then moves run to run on identical bytes, and the task looks flaky rather than defective.

WHAT IT READS.

A `with_runs`-shaped DataOS bundle -- both real layouts in this corpus:

    <root>/<task>/rev_*/evaluations/<eval>/eval_files/verifier/{verifier-report.json,reward-details.json}
    <root>/<task>/<task>/rev_*/evaluations/<eval>/eval_files/verifier/...      (qcr_21092026 nesting)

Only evaluations whose directory name contains `oracle` are used: an agent run scoring
differently is expected (different deliverable), an ORACLE run scoring differently is not
(same golden, same bytes). `verifier-report.json` is the primary source -- it carries, per
criterion, `result.evaluation.{true_count,false_count,attempts}` (the per-sample judge votes)
plus `result.effective_weight`. `reward-details.json` is the fallback for a run whose report is
absent: it carries the criterion's mean score and weight but NOT the per-sample votes, so
split-vote detection degrades to unavailable for that run (reported, not silently dropped).

WHAT IT REPORTS, per criterion (vocabulary deliberately reused from
`ready_to_upload_v7/_oracle_merge.py`, which already computes 3-pass agreement over a separate
locally-generated Opus-5 judge corpus and calls its output "the answer to why DataOS fails at
random" -- same `verdicts` / `majority` / `agreement: unanimous|SPLIT` / `weight_at_risk`
shape, so the two reports read the same way; this check differs in its SOURCE, reading
DataOS's own bundled per-sample artifacts rather than a locally re-judged corpus):

  1. `oracle_cross_run_disagreement` -- the criterion's pass/fail outcome (or its mean score)
     is not the same in every oracle run. THE STRONGEST SIGNAL: same bytes, different verdict.
  2. `split_vote_within_run` -- inside a single run the judge samples are not unanimous
     (e.g. 2T/1F). Mean-of-3 masks it; one more sample could have flipped the outcome.
  3. per task, an `unstable_criteria` list with each criterion's weight and a `weight_at_risk`
     total, so the reader can see how much reward is riding on non-reproducible judgments.

`task_checksum` is read from each run's `eval_files/result.json` and reported. When two oracle
runs have DIFFERENT checksums they graded different bytes and the comparison is NOT a
reproducibility finding -- those runs are excluded from cross-run comparison and named in
`notes`. (In the calibration corpus every compared oracle pair had identical checksums.)

RELATIONSHIP TO `oracle_reward_details_audit.py`. That check already flags mechanism 1 at the
MEAN-SCORE level from `reward-details.json`, and is warn-only. This one is not a replacement
for it: it adds the per-sample vote layer (mechanism 2), which `reward-details.json` cannot
express at all, and which is what distinguishes "this criterion is a coin flip" from "these two
runs happened to differ". A criterion like task_LGL-161 `v14` -- identical mean in both runs,
1T/2F in both -- is invisible to a mean-score comparison and is exactly the criterion most
likely to flip the next time it is run.

WHAT IT DOES NOT CATCH.

  * A criterion that is unstable but happened to land the same way in every run in the bundle.
    Two runs can only ever be weak evidence of stability; three is better. `n_oracle_runs` is
    reported per task so the reader can weigh it, and a task with ONE oracle run is reported
    `skip` for the cross-run mechanism (split votes are still checked -- they need only one run).
  * WHY a criterion is unstable. It reports the vote split and the judge's own justifications
    (truncated), not a diagnosis. The repair -- re-source, narrow, split a compound criterion --
    is `reward_signal_gate.py`'s territory and a human/LLM call.
  * Anything about agent runs. Non-oracle evaluations are ignored on purpose.
  * The rewardkit-hybrid genre, whose judging is chunked and which writes no
    `verifier-report.json`; such tasks report `skip` with a note when no oracle artifacts parse.
  * Floating-point noise is NOT treated as disagreement: mean scores are compared at 1e-9.

CALIBRATION STATUS. Validated on the two real bundles
`dataos_qc_runs/74-ekw-sprint/qcr_20092026_rework/incoming/` (11 tasks) and
`dataos_qc_runs/74-ekw-sprint/qcr_21092026/incoming/` (10 tasks). It independently rediscovers
all four known-unstable criteria -- task_120 `v6c`, task_LGL-168 `v9`, task_LGL-161 `v14`,
task_LGL-131 `v13` -- without being told to look for them. Regression-pinned in
`oracle_reproducibility_check_test.py`.

USAGE
    python oracle_reproducibility_check.py <TASK-ID> [...] --root <bundle> --out report.json
    python oracle_reproducibility_check.py --all --root <bundle> --id-prefix task_ --out r.json
    python oracle_reproducibility_check.py --all --root <bundle> --min-weight-at-risk 0.05

Exit code: 0 always (disclosure report). Pass `--exit-nonzero-on-fail` to use it as a gate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCORE_TOL = 1e-9
RUN_ID_RE = re.compile(r"(eval_\d+__attempt_\d+)")


# ---------------------------------------------------------------------------
# bundle discovery -- both real nestings in this corpus
# ---------------------------------------------------------------------------


def revision_dirs(task_dir: Path) -> list[Path]:
    """Every `rev_*` directory under a task, whether it sits directly under <task>/ (the
    qcr_20092026_rework layout) or under <task>/<task>/ (the qcr_21092026 layout)."""
    revs = sorted(p for p in task_dir.glob("rev_*") if p.is_dir())
    if revs:
        return revs
    nested = task_dir / task_dir.name
    if nested.is_dir():
        revs = sorted(p for p in nested.glob("rev_*") if p.is_dir())
        if revs:
            return revs
    # Last resort: any rev_* at any depth (keeps this working on a re-shaped bundle).
    return sorted({p for p in task_dir.glob("*/rev_*") if p.is_dir()})


def oracle_run_dirs(task_dir: Path) -> list[Path]:
    """Every ORACLE evaluation directory across every revision of this task."""
    out: list[Path] = []
    for rev in revision_dirs(task_dir):
        evals = rev / "evaluations"
        if not evals.is_dir():
            continue
        for run in sorted(evals.iterdir()):
            if run.is_dir() and "oracle" in run.name.lower():
                out.append(run)
    return out


def run_id(run_dir: Path) -> str:
    m = RUN_ID_RE.search(run_dir.name)
    return m.group(1) if m else run_dir.name


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# one oracle run -> per-criterion rows
# ---------------------------------------------------------------------------


def read_run(run_dir: Path) -> dict:
    """{run, checksum, reward, source, criteria: {name: {...}}, error} for one oracle run."""
    out: dict = {
        "run": run_id(run_dir),
        "checksum": None,
        "reward": None,
        "source": None,
        "criteria": {},
        "error": None,
    }

    result = _load_json(run_dir / "eval_files" / "result.json")
    if isinstance(result, dict):
        out["checksum"] = result.get("task_checksum")

    verifier_dir = run_dir / "eval_files" / "verifier"
    report = _load_json(verifier_dir / "verifier-report.json")
    if isinstance(report, dict) and isinstance(report.get("assertion_results"), list):
        out["source"] = "verifier-report.json"
        out["reward"] = report.get("reward")
        for a in report["assertion_results"]:
            if not isinstance(a, dict):
                continue
            name = str(a.get("name"))
            res = a.get("result") if isinstance(a.get("result"), dict) else {}
            ev = res.get("evaluation") if isinstance(res.get("evaluation"), dict) else {}
            definition = a.get("definition") if isinstance(a.get("definition"), dict) else {}
            meta = (
                definition.get("metadata")
                if isinstance(definition.get("metadata"), dict)
                else {}
            )
            true_count = ev.get("true_count")
            false_count = ev.get("false_count")
            attempts = ev.get("attempts") if isinstance(ev.get("attempts"), list) else []
            weight = res.get("effective_weight")
            if not isinstance(weight, (int, float)):
                weight = meta.get("weight")
            out["criteria"][name] = {
                "verdict": (
                    "PASS"
                    if res.get("success") is True
                    else "FAIL"
                    if res.get("success") is False
                    else None
                ),
                "score": None,
                "true_count": true_count if isinstance(true_count, int) else None,
                "false_count": false_count if isinstance(false_count, int) else None,
                "n_samples": len(attempts) or None,
                "weight": float(weight) if isinstance(weight, (int, float)) else 0.0,
                "reasons": [
                    str(at.get("justification") or "")[:300]
                    for at in attempts
                    if isinstance(at, dict)
                ],
            }
        return out

    details = _load_json(verifier_dir / "reward-details.json")
    if isinstance(details, dict):
        out["source"] = "reward-details.json"
        for name, block in details.items():
            if not isinstance(block, dict):
                continue
            score = block.get("score")
            weight = 0.0
            crits = block.get("criteria")
            if isinstance(crits, list) and crits and isinstance(crits[0], dict):
                if not isinstance(score, (int, float)):
                    score = crits[0].get("value")
                if isinstance(crits[0].get("weight"), (int, float)):
                    weight = float(crits[0]["weight"])
            if not isinstance(score, (int, float)):
                continue
            out["criteria"][str(name)] = {
                "verdict": None,
                "score": float(score),
                # reward-details.json records the MEAN, never the per-sample votes.
                "true_count": None,
                "false_count": None,
                "n_samples": None,
                "weight": weight,
                "reasons": [],
            }
        return out

    out["error"] = "no verifier-report.json and no reward-details.json in eval_files/verifier/"
    return out


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def _outcome_key(row: dict):
    """What 'the same verdict' means for one run, preferring the pass/fail outcome and falling
    back to the rounded mean score when only reward-details.json was available."""
    if row["verdict"] is not None:
        return ("verdict", row["verdict"])
    if row["score"] is not None:
        return ("score", round(row["score"] / SCORE_TOL))
    return ("unknown", None)


def analyze_task(task_dir: Path, min_weight_at_risk: float = 0.0) -> dict:
    """One result dict for one task's bundle. Never raises."""
    result: dict = {
        "task_id": task_dir.name,
        "status": None,
        "n_oracle_runs": 0,
        "oracle_runs": [],
        "checksums": [],
        "n_criteria": 0,
        "unstable_criteria": [],
        "weight_at_risk": 0.0,
        "findings": [],
        "notes": [],
    }

    runs = [read_run(d) for d in oracle_run_dirs(task_dir)]
    runs = [r for r in runs if r["criteria"] or r["error"]]
    usable = [r for r in runs if r["criteria"]]
    result["n_oracle_runs"] = len(usable)
    result["oracle_runs"] = [
        {
            "run": r["run"],
            "reward": r["reward"],
            "checksum": r["checksum"],
            "source": r["source"],
            "n_criteria": len(r["criteria"]),
        }
        for r in usable
    ]
    for r in runs:
        if r["error"]:
            result["notes"].append(f"{r['run']}: {r['error']}")

    if not usable:
        result["status"] = "skip"
        result["notes"].append(
            "no readable ORACLE verifier artifacts under this task's rev_*/evaluations/ -- "
            "nothing to compare (rewardkit-hybrid tasks write no verifier-report.json)"
        )
        return result

    checksums = sorted({r["checksum"] for r in usable if r["checksum"]})
    result["checksums"] = checksums

    # Only runs that graded the SAME bytes can evidence irreproducibility. When the bundle
    # holds more than one checksum, compare within the largest same-checksum group and say so.
    comparable = usable
    if len(checksums) > 1:
        groups: dict[str, list[dict]] = {}
        for r in usable:
            groups.setdefault(str(r["checksum"]), []).append(r)
        comparable = max(groups.values(), key=len)
        result["notes"].append(
            f"{len(checksums)} distinct task_checksum values across {len(usable)} oracle runs "
            f"-- they did not grade identical bytes. Cross-run comparison is restricted to the "
            f"largest same-checksum group ({len(comparable)} run(s), checksum "
            f"{comparable[0]['checksum']}); the rest are reported but not compared."
        )

    names = sorted({n for r in usable for n in r["criteria"]})
    result["n_criteria"] = len(names)

    unstable: list[dict] = []
    for name in names:
        present_all = [(r, r["criteria"][name]) for r in usable if name in r["criteria"]]
        present_cmp = [(r, r["criteria"][name]) for r in comparable if name in r["criteria"]]

        weight = max((row["weight"] for _, row in present_all), default=0.0)
        verdicts = [row["verdict"] or "?" for _, row in present_all]
        votes = [
            None
            if row["true_count"] is None or row["false_count"] is None
            else f"{row['true_count']}T/{row['false_count']}F"
            for _, row in present_all
        ]

        kinds: list[str] = []

        # 1. cross-run disagreement (only within the same-checksum group, >= 2 runs)
        if len(present_cmp) >= 2:
            keys = {_outcome_key(row) for _, row in present_cmp}
            if len(keys) > 1:
                kinds.append("oracle_cross_run_disagreement")

        # 2. split vote inside any single run
        split_runs = [
            r["run"]
            for r, row in present_all
            if row["true_count"] is not None
            and row["false_count"] is not None
            and row["true_count"] > 0
            and row["false_count"] > 0
        ]
        if split_runs:
            kinds.append("split_vote_within_run")

        if not kinds:
            continue

        # `agreement` / `majority` spellings match _oracle_merge.py's own report.
        entry = {
            "criterion": name,
            "weight": weight,
            "kinds": kinds,
            "agreement": "SPLIT",
            "majority": (
                "FAIL" if verdicts.count("FAIL") > verdicts.count("PASS") else "PASS"
            ),
            "verdicts": verdicts,
            "votes": votes,
            "runs": [r["run"] for r, _ in present_all],
            "split_vote_runs": split_runs,
            "rewards": [r["reward"] for r, _ in present_all],
            "reasons": [row["reasons"][:3] for _, row in present_all],
        }
        unstable.append(entry)

    unstable.sort(key=lambda e: (-e["weight"], e["criterion"]))
    result["unstable_criteria"] = unstable
    result["weight_at_risk"] = round(sum(e["weight"] for e in unstable), 6)

    for e in unstable:
        if "oracle_cross_run_disagreement" in e["kinds"]:
            result["findings"].append(
                {
                    "kind": "oracle_cross_run_disagreement",
                    "severity": "fail",
                    "criterion": e["criterion"],
                    "weight": e["weight"],
                    "detail": (
                        f"criterion {e['criterion']} (weight {e['weight']}) scored differently "
                        f"across oracle runs on the same golden bytes: "
                        + ", ".join(
                            f"{run}={v}" + (f" [{vote}]" if vote else "")
                            for run, v, vote in zip(e["runs"], e["verdicts"], e["votes"])
                        )
                        + ". Same bytes, different verdict -- this criterion can fail the task "
                        "at random."
                    ),
                }
            )
        if "split_vote_within_run" in e["kinds"]:
            result["findings"].append(
                {
                    "kind": "split_vote_within_run",
                    "severity": "fail",
                    "criterion": e["criterion"],
                    "weight": e["weight"],
                    "detail": (
                        f"criterion {e['criterion']} (weight {e['weight']}) drew a non-unanimous "
                        f"judge vote in run(s) {', '.join(e['split_vote_runs'])}: "
                        + ", ".join(
                            f"{run}={vote}"
                            for run, vote in zip(e["runs"], e["votes"])
                            if vote
                        )
                        + ". Mean-of-3 turns a coin flip into a plausible-looking number; one "
                        "more sample could flip the outcome."
                    ),
                }
            )

    if unstable and result["weight_at_risk"] >= min_weight_at_risk:
        result["status"] = "fail"
    elif unstable:
        result["status"] = "pass"
        result["notes"].append(
            f"{len(unstable)} unstable criterion/criteria found but total weight at risk "
            f"{result['weight_at_risk']} is below --min-weight-at-risk {min_weight_at_risk} -- "
            "disclosed, not gated."
        )
    else:
        result["status"] = "pass"

    if len(comparable) < 2:
        result["notes"].append(
            "fewer than two comparable oracle runs -- cross-run disagreement could not be "
            "assessed at all; only split votes within the single run were checked. Absence of "
            "a finding here is NOT evidence of reproducibility."
        )
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

HOW_TO_READ_THIS_REPORT = {
    "purpose": (
        "Finds criteria whose verdict is not reproducible on byte-identical goldens: the same "
        "criterion scoring differently across ORACLE runs, and non-unanimous judge votes "
        "within a single run that mean-of-3 sampling hides."
    ),
    "task_status": {
        "fail": (
            "At least one unstable criterion, with total weight at risk at or above "
            "--min-weight-at-risk."
        ),
        "pass": "Oracle artifacts read and every criterion agreed (see notes for caveats).",
        "skip": "No readable ORACLE verifier artifacts under this task's rev_*/evaluations/.",
    },
    "finding_kinds": {
        "oracle_cross_run_disagreement": (
            "Same criterion, same golden bytes (same task_checksum), different verdict across "
            "two or more oracle runs. The strongest available evidence of irreproducibility."
        ),
        "split_vote_within_run": (
            "Judge samples inside ONE run were not unanimous (e.g. 2T/1F). The mean-of-3 score "
            "looks like a number; the votes show it is a coin flip."
        ),
    },
    "the_one_thing_this_check_cannot_see": (
        "A criterion that is unstable but happened to land the same way in every run present in "
        "the bundle. Two runs are weak evidence of stability; n_oracle_runs is reported so the "
        "reader can weigh it."
    ),
}


def find_task_dirs(root: Path, task_ids=None, id_prefix: str = "") -> list[Path]:
    if task_ids:
        dirs = []
        for tid in task_ids:
            p = root / tid
            if not p.is_dir():
                print(f"WARNING: task dir not found, skipping: {p}", file=sys.stderr)
                continue
            dirs.append(p)
        return dirs
    return sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith(id_prefix))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Oracle reproducibility check: criteria that score differently across oracle runs "
            "on identical goldens, plus split judge votes within a run."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("task_ids", nargs="*", help="one or more task ids")
    ap.add_argument("--all", action="store_true", help="run every task under --root")
    ap.add_argument("--root", type=Path, required=True, help="a with_runs-shaped bundle root")
    ap.add_argument("--id-prefix", default="")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument(
        "--min-weight-at-risk",
        type=float,
        default=0.0,
        help="only fail a task whose unstable criteria carry at least this much total weight "
        "(default 0.0 -- any unstable criterion fails)",
    )
    ap.add_argument(
        "--exit-nonzero-on-fail",
        action="store_true",
        help="exit 1 if any task fails (for use as a hard gate)",
    )
    args = ap.parse_args(argv)

    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")
    if not args.root.is_dir():
        print(f"--root does not exist or is not a directory: {args.root}", file=sys.stderr)
        return 2

    task_dirs = find_task_dirs(
        args.root, None if args.all else args.task_ids, id_prefix=args.id_prefix
    )
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        return 2

    results = []
    for task_dir in task_dirs:
        try:
            r = analyze_task(task_dir, args.min_weight_at_risk)
        except Exception as exc:  # noqa: BLE001
            r = {
                "task_id": task_dir.name,
                "status": "skip",
                "findings": [],
                "notes": [f"unhandled exception: {exc}"],
                "unstable_criteria": [],
                "weight_at_risk": 0.0,
                "n_oracle_runs": 0,
            }
        results.append(r)

    counts: dict[str, int] = {}
    finding_counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        for f in r.get("findings", []):
            finding_counts[f["kind"]] = finding_counts.get(f["kind"], 0) + 1

    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "id_prefix": args.id_prefix,
        "min_weight_at_risk": args.min_weight_at_risk,
        "n_tasks": len(results),
        "status_counts": counts,
        "finding_counts": finding_counts,
        "how_to_read_this_report": HOW_TO_READ_THIS_REPORT,
        "results": results,
    }

    print(f"\n{len(results)} task(s) checked.")
    print("status counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if finding_counts:
        print("finding counts: " + ", ".join(f"{k}={v}" for k, v in sorted(finding_counts.items())))
    flagged = [r for r in results if r.get("unstable_criteria")]
    if flagged:
        print(f"\n{'task':18} {'runs':>4} {'crit':>5} {'unstable':>8} {'wt@risk':>8}  criteria")
        for r in sorted(flagged, key=lambda r: -r["weight_at_risk"]):
            names = ", ".join(
                f"{e['criterion']}({'/'.join(v for v in e['votes'] if v)})"
                for e in r["unstable_criteria"]
            )
            print(f"{r['task_id']:18} {r['n_oracle_runs']:>4} {r['n_criteria']:>5} "
                  f"{len(r['unstable_criteria']):>8} {r['weight_at_risk']:>8.3f}  {names}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(aggregate, indent=2, default=str), encoding="utf-8")
        print(f"\nWrote {args.out}")

    if args.exit_nonzero_on_fail and counts.get("fail"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
