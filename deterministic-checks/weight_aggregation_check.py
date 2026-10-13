#!/usr/bin/env python3
r"""Weight-aggregation check: does the platform's reported reward for a real run come from
an UNWEIGHTED mean of a task's group scores, when the rubric declares those groups (SVC-PC's
deliverables_NN files, EKW's per-verifier "groups") at UNEQUAL weight?

Why this exists. An independent verifier session (2026-09-14) traced the live DataOS scoring
code directly and found: rubrics declare per-criterion weights, but the platform's aggregation
step computes a plain, unweighted mean of GROUP scores, ignoring those declared weights
entirely. This matches a pattern a stakeholder's own manual-QC artifact already flagged on 6
of 19 reviewed tasks ("weights ignored at aggregation"). No check in this folder tests for it;
this one does, and only this.

This is NOT certification_gate_check.py's job and does not overlap it. That script replays
must-pass gates and release thresholds; its own `recomputed_weighted_score` field computes a
single FLAT weighted mean across every criterion in a task regardless of group, using each
criterion's own declared `weight` as an absolute (task-scaled) number -- confirmed against real
run data before writing this module (see Validation below), NOT the same unweighted-mean bug
the platform has. This script is the other half: it looks specifically at the GAP between that
flat/correct computation and a naive mean-of-group-scores, because that gap is the actual
fingerprint of the platform bug, and nothing upstream of this reports it.

The test, per task-run:
  1. Load the rubric's own per-group declared weight. SVC-PC: `[judge] weight` at the top of
     each tests/deliverables*/judge.toml (cross-checked against the sum of that file's own
     `[[criterion]] weight`s -- real data shows these agree, e.g. SVC-PC-12-6-0's
     deliverables_01 declares weight=0.52172 AND its 12 criteria weights sum to 0.52172
     exactly; a mismatch beyond FLOAT_TOL is reported as `weight_source_disagreement`, not
     silently resolved). EKW: `ekw_verifier_json.load_ekw_criteria` -- each verifier is its
     own group with exactly one criterion, so the group weight IS that criterion's
     `metadata.weight`, no separate field exists to cross-check against.
  2. Load the run's own per-group score from verifier/reward.json (top-level keys other than
     "reward") and the platform's own total from reward.json's "reward" -- both already
     computed and persisted by the platform itself, not re-derived from pass/fail here (that
     re-derivation, with its must-pass/key-mode complexity, is certification_gate_check.py's
     job; this check stays narrow).
  3. Compute two candidate totals from the SAME group scores: `unweighted` (plain mean) and
     `weighted` (mean weighted by each group's declared weight, step 1). Only groups present
     in BOTH the package and the run are used; a task needs 2+ such groups or the two
     candidates cannot differ (verdict `insufficient_groups`, real for every single-group
     SVC-PC task and every single-verifier-group... there are none, EKW's groups are its
     verifiers, of which real tasks have many).
  4. Compare the platform's own reported total against both candidates. `unweighted_mean_
     signature` (FAIL) is the bug: reported lands within MATCH_TOLERANCE of the unweighted
     mean while landing further than that from the weighted one, AND the two candidates
     themselves differ by at least MIN_DISCRIMINATION (a task whose groups happen to carry
     near-equal weight cannot discriminate the two formulas -- verdict `not_discriminating`,
     reported separately, never silently counted as clean). `weighted_mean_signature` is the
     healthy control: reported matches the weighted candidate instead. `closer_to_unweighted`/
     `closer_to_weighted` (WARN) cover a reported total that favours one side without landing
     inside MATCH_TOLERANCE of it -- softer than the FAIL case, reported so a human can look,
     never silently dropped.

Validation (RAN, 2026-09-14, real data, not synthetic):
  SVC-PC, 56-task population (`C:/b/_stage_0914_reconciled56`) against all 6 real terminus
  batches (`C:/b/_terminus_extract`, claude_opus_5 x3 + gpt_5.6 x3): see the module's own
  --json output for the full table this run produced. Ground-truth instance confirmed by hand
  before running the script, then reproduced by it: SVC-PC-12-6-0's claude_opus_5 run --
  deliverables_01 (declared weight 0.52172) scored 0.8333, deliverables_02 (0.47828) scored
  0.7273. Platform `reward.json` reports 0.7803 -- exactly `(0.8333+0.7273)/2`, the UNWEIGHTED
  mean, matching to 4 decimals (delta 0.0000). The weighted candidate is 0.7826 (delta 0.0023).
  `unweighted_mean_signature`, confirmed. Control case, same population: SVC-PC-53-1-0 has only
  1 group (tests/deliverables/, no _NN split) so the two candidates cannot differ --
  `insufficient_groups`, correctly not flagged; this is also the task certification_gate_
  check.py's own docstring used to show its flat weighted recompute (0.74) matches reported
  (0.74) exactly, and a plain unweighted pass-count (8/9=0.8889) would NOT have -- consistent
  with this module's read of the same underlying mechanism.
  EKW: run against `C:/ekwqc/_harbor_ekw8/_jobs` (real harbor trial output) with package root
  `C:/ekwqc/_merged274/files`, per certification_gate_check.py's own documented EKW paths.

Exit 0 clean (no unweighted_mean_signature, no closer_to_unweighted), 1 if either kind of
finding exists, 2 on bad usage. Stdlib only; reuses ekw_verifier_json.py for the EKW package
read per this folder's dual-format convention, never reimplements it.

    python weight_aggregation_check.py --root <package_root> --all \\
        --run <run_root> [--run <run_root> ...] [--json out.json]
    python weight_aggregation_check.py --root C:/b/_stage_0914_reconciled56 SVC-PC-12-6-0 \\
        --run C:/b/_terminus_extract
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    sys.stderr.write("needs Python 3.11+ for tomllib\n")
    raise SystemExit(2)

import re

from ekw_verifier_json import has_ekw_config, load_ekw_criteria

# EKW's harbor staging convention nests the real task under a fixed generic leaf directory
# ("<job>/ekw-0908-task_139/v1/harbor_task"), so the trial dir itself is named "harbor_task"
# for every EKW model AND oracle trial on this population -- confirmed against
# C:/ekwqc/_harbor_ekw8/_jobs while validating this script, and already documented by
# certification_gate_check.py's own discover_runs, which needed the identical fallback for
# the identical reason. Re-implemented here (not imported) per this module's own no-downstream-
# import rule; kept as the same regex so the two scripts can't silently drift on what counts as
# a task id.
PATH_TASK_ID_RE = re.compile(r"task[-_](\d+)\b", re.IGNORECASE)

FLOAT_TOL = 1e-4
MATCH_TOLERANCE = 0.0015  # reported reward within this of a candidate counts as "matches"
MIN_DISCRIMINATION = 0.002  # the two candidates must differ at least this much to mean anything
RUN_WALK_MAX_DEPTH = 8


# --------------------------------------------------------------------------- package (weights)


def _svc_judge_files(task_dir: Path) -> list[Path]:
    return sorted(
        set(task_dir.glob("tests/deliverables/judge.toml"))
        | set(task_dir.glob("tests/deliverables_*/judge.toml"))
    )


def _has_svc_pc_config(task_dir: Path) -> bool:
    return bool(_svc_judge_files(task_dir))


def load_svc_groups(task_dir: Path) -> tuple[dict, list[str]]:
    """{group_name: {"declared_weight": float|None, "criterion_weight_sum": float,
    "weight_source": str, "n_criteria": int}}, parse_errors. declared_weight comes from the
    file's own [judge] weight; criterion_weight_sum is independently summed from every
    [[criterion]] weight in that same file, so the two can be cross-checked rather than
    trusted blindly."""
    groups: dict = {}
    errors: list[str] = []
    for jf in _svc_judge_files(task_dir):
        group = jf.parent.name
        try:
            data = tomllib.loads(jf.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{group}/judge.toml: {exc}")
            continue
        judge_weight = (data.get("judge") or {}).get("weight")
        crit_sum = 0.0
        n = 0
        for c in data.get("criterion") or []:
            w = c.get("weight")
            if isinstance(w, (int, float)):
                crit_sum += float(w)
                n += 1
        declared = (
            float(judge_weight) if isinstance(judge_weight, (int, float)) else None
        )
        source = "judge.weight" if declared is not None else "criterion_weight_sum"
        disagreement = (
            declared is not None
            and n > 0
            and abs(declared - crit_sum) > FLOAT_TOL
        )
        groups[group] = {
            "declared_weight": declared if declared is not None else (crit_sum if n else None),
            "criterion_weight_sum": crit_sum if n else None,
            "weight_source": source,
            "n_criteria": n,
            "weight_source_disagreement": disagreement,
        }
    return groups, errors


def load_ekw_groups(task_dir: Path) -> tuple[dict, list[str]]:
    """Same shape as load_svc_groups. EKW has no separate group-level weight field -- each
    verifier is its own group with exactly one criterion (ekw_verifier_json's own convention),
    so declared_weight and criterion_weight_sum are the same number by construction."""
    groups: dict = {}
    errors: list[str] = []
    criteria = load_ekw_criteria(task_dir)
    for c in criteria:
        if c["name"] == "__parse_error__":
            errors.append(str(c.get("description")))
            continue
        w = c.get("weight")
        declared = float(w) if isinstance(w, (int, float)) else None
        groups[c["group"]] = {
            "declared_weight": declared,
            "criterion_weight_sum": declared,
            "weight_source": "criterion.metadata.weight",
            "n_criteria": 1,
            "weight_source_disagreement": False,
        }
    return groups, errors


def load_package_groups(task_dir: Path) -> tuple[str, dict, list[str]]:
    """(format, groups, parse_errors). SVC-PC judge.toml takes precedence when both exist,
    matching every other dual-format script's own EKW-port rule."""
    if _has_svc_pc_config(task_dir):
        groups, errors = load_svc_groups(task_dir)
        if not groups and not errors:
            errors = ["no [[criterion]] entries found under tests/deliverables*/judge.toml"]
        return "svc-pc", groups, errors
    if has_ekw_config(task_dir):
        groups, errors = load_ekw_groups(task_dir)
        return "ekw", groups, errors
    return "unknown", {}, ["no tests/deliverables*/judge.toml (SVC-PC) and no tests/verifier.json (EKW)"]


# --------------------------------------------------------------------------- runs (scores)


def _read_json(p: Path):
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def discover_runs(run_roots: list[str]) -> tuple[list[dict], list[str]]:
    """Every <task-dir>/verifier/reward-details.json under each run root, same walk
    certification_gate_check.py's discover_runs uses (independently re-implemented here, not
    imported, so this module never depends on a downstream consumer's internals). Returns
    (runs, notes); each run is {label, root, task_id, run_dir}."""
    runs: list[dict] = []
    notes: list[str] = []
    for spec in run_roots:
        root = Path(spec)
        if not root.is_dir():
            notes.append(f"run root not a directory, skipped: {root}")
            continue
        root_depth = len(root.parts)
        found = 0
        for rd in root.rglob("reward-details.json"):
            if rd.parent.name != "verifier":
                continue
            if len(rd.parts) - root_depth > RUN_WALK_MAX_DEPTH:
                continue
            run_dir = rd.parent.parent
            task_id = run_dir.name
            if task_id == "harbor_task" or not re.search(r"\d", task_id):
                # Not a real id (EKW's generic staging leaf, see PATH_TASK_ID_RE above) --
                # search the trial's own result.json task path for a task_NNN component
                # instead of attributing the run to an unmatchable literal "harbor_task".
                result = _read_json(run_dir / "result.json")
                for path_field in (
                    (((result or {}).get("config") or {}).get("task") or {}).get("path"),
                    ((result or {}).get("task_id") or {}).get("path"),
                ):
                    if not path_field:
                        continue
                    m = PATH_TASK_ID_RE.search(str(path_field))
                    if m:
                        task_id = f"task_{int(m.group(1))}"
                        break
            try:
                label = str(run_dir.relative_to(root)).replace("\\", "/")
            except ValueError:
                label = str(run_dir)
            runs.append(
                {
                    "label": f"{root.name}/{label}",
                    "task_id": task_id,
                    "run_dir": run_dir,
                }
            )
            found += 1
        notes.append(f"{found} run(s) under {root}")
    return runs, notes


def load_run_scores(run_dir: Path) -> dict:
    """{"group_scores": {group: float}, "reported_reward": float|None, "source": str}.
    reward.json is the platform's own persisted per-group + task-total record and is preferred;
    reward-details.json's per-group "score" is the fallback when reward.json is missing or has
    no usable group keys (both were designed to agree -- neither script re-derives one from
    per-criterion pass/fail, unlike certification_gate_check.py, which is a deliberate scope
    cut: this check is about the aggregation step only, not about re-scoring criteria)."""
    reward = _read_json(run_dir / "verifier" / "reward.json")
    group_scores: dict = {}
    reported = None
    source = "missing"
    if isinstance(reward, dict):
        reported = reward.get("reward") if isinstance(reward.get("reward"), (int, float)) else None
        for k, v in reward.items():
            if k == "reward":
                continue
            if isinstance(v, (int, float)):
                group_scores[k] = float(v)
        if group_scores:
            source = "reward.json"
    if not group_scores:
        details = _read_json(run_dir / "verifier" / "reward-details.json")
        if isinstance(details, dict):
            for group, g in details.items():
                if isinstance(g, dict) and isinstance(g.get("score"), (int, float)):
                    group_scores[group] = float(g["score"])
            if group_scores:
                source = "reward-details.json"
    return {
        "group_scores": group_scores,
        "reported_reward": reported,
        "source": source,
    }


# --------------------------------------------------------------------------- evaluation


def evaluate(pkg_groups: dict, run: dict) -> dict:
    scores = run["group_scores"]
    common = sorted(set(pkg_groups) & set(scores))
    rec = {
        "label": run["label"],
        "run_dir": str(run["run_dir"]),
        "reported_reward": run["reported_reward"],
        "score_source": run["source"],
        "groups_in_package": sorted(pkg_groups),
        "groups_in_run": sorted(scores),
        "groups_used": common,
        "missing_in_run": sorted(set(pkg_groups) - set(scores)),
        "extra_in_run": sorted(set(scores) - set(pkg_groups)),
    }
    if len(common) < 2:
        rec["verdict"] = "insufficient_groups"
        return rec
    if run["reported_reward"] is None:
        rec["verdict"] = "no_reported_reward"
        return rec

    weights = {g: pkg_groups[g]["declared_weight"] for g in common}
    unresolved = [g for g, w in weights.items() if w is None]
    if unresolved:
        rec["verdict"] = "weight_unresolved"
        rec["unresolved_groups"] = unresolved
        return rec

    total_w = sum(weights.values())
    if total_w <= 0:
        rec["verdict"] = "weight_unresolved"
        rec["unresolved_groups"] = common
        return rec

    unweighted = sum(scores[g] for g in common) / len(common)
    weighted = sum(weights[g] * scores[g] for g in common) / total_w
    reported = run["reported_reward"]
    discrimination = abs(weighted - unweighted)
    delta_u = abs(reported - unweighted)
    delta_w = abs(reported - weighted)

    rec.update(
        {
            "group_scores_used": {g: scores[g] for g in common},
            "group_weights_used": weights,
            "unweighted_mean": round(unweighted, 4),
            "weighted_mean": round(weighted, 4),
            "discrimination": round(discrimination, 4),
            "delta_reported_vs_unweighted": round(delta_u, 4),
            "delta_reported_vs_weighted": round(delta_w, 4),
        }
    )
    if discrimination < MIN_DISCRIMINATION:
        rec["verdict"] = "not_discriminating"
        return rec
    if delta_u <= MATCH_TOLERANCE and delta_w > MATCH_TOLERANCE:
        rec["verdict"] = "unweighted_mean_signature"
    elif delta_w <= MATCH_TOLERANCE and delta_u > MATCH_TOLERANCE:
        rec["verdict"] = "weighted_mean_signature"
    elif delta_u < delta_w:
        rec["verdict"] = "closer_to_unweighted"
    elif delta_w < delta_u:
        rec["verdict"] = "closer_to_weighted"
    else:
        rec["verdict"] = "tied"
    return rec


VERDICT_SEVERITY = {
    "unweighted_mean_signature": "FAIL",
    "closer_to_unweighted": "WARN",
    "weighted_mean_signature": "OK",
    "closer_to_weighted": "OK",
    "tied": "OK",
    "not_discriminating": "INFO",
    "insufficient_groups": "INFO",
    "weight_unresolved": "INFO",
    "no_reported_reward": "INFO",
}

HOW_TO_READ = {
    "unweighted_mean_signature": "the bug: reported reward matches the plain mean of group scores, not a mean weighted by the rubric's own declared group weights",
    "closer_to_unweighted": "softer version of the same signature: reported favours the unweighted candidate but isn't within MATCH_TOLERANCE of it",
    "weighted_mean_signature": "healthy control: reported matches the properly weighted candidate",
    "closer_to_weighted": "healthy: reported favours the weighted candidate without landing inside MATCH_TOLERANCE",
    "not_discriminating": "the task's group weights are too close to each other for the two candidates to differ meaningfully -- no signal either way",
    "insufficient_groups": "fewer than 2 groups matched between package and run -- the bug cannot manifest with only one group",
    "weight_unresolved": "one or more matched groups have no numeric declared weight in the package",
    "no_reported_reward": "run has no usable reward.json / result.json reward to compare against",
}


# --------------------------------------------------------------------------- main


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("task_ids", nargs="*", help="task ids to check (default: --all)")
    ap.add_argument("--all", action="store_true", help="every task directory under --root")
    ap.add_argument("--root", required=True, help="package root: one task directory per task")
    ap.add_argument(
        "--run",
        action="append",
        default=[],
        required=True,
        help="a run root holding <task>/verifier/{reward.json,reward-details.json} at any "
        "depth; repeatable",
    )
    ap.add_argument("--json", help="write the full JSON report here")
    ap.add_argument("--quiet", action="store_true", help="one line per task-run, no detail")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2
    if not args.all and not args.task_ids:
        sys.stderr.write("give task ids or --all\n")
        return 2

    if (root / "tests").is_dir():
        task_dirs = [root]
    else:
        task_dirs = sorted(d for d in root.iterdir() if d.is_dir())
    if args.task_ids:
        want = set(args.task_ids)
        task_dirs = [d for d in task_dirs if d.name in want]
    if not task_dirs:
        sys.stderr.write(f"no task directories matched under {root}\n")
        return 2

    runs, run_notes = discover_runs(args.run)
    runs_by_task: dict[str, list[dict]] = {}
    for r in runs:
        runs_by_task.setdefault(r["task_id"], []).append(r)

    print(f"packages: {len(task_dirs)} task dir(s) under {root}")
    for n in run_notes:
        print(f"runs: {n}")
    print()

    task_results = []
    any_fail = False
    any_warn = False
    for d in task_dirs:
        fmt, groups, pkg_errors = load_package_groups(d)
        task_runs = runs_by_task.get(d.name, [])
        run_recs = []
        for r in task_runs:
            scores = load_run_scores(r["run_dir"])
            run_recs.append(evaluate(groups, {**r, **scores}))
        task_results.append(
            {
                "task": d.name,
                "format": fmt,
                "n_groups": len(groups),
                "package_parse_errors": pkg_errors,
                "runs": run_recs,
            }
        )
        if pkg_errors and not groups:
            continue
        if not task_runs and not args.quiet:
            print(f"INFO {d.name:<20} [{fmt}]  {len(groups)} group(s)  no run data found")
            continue
        for rr in run_recs:
            sev = VERDICT_SEVERITY[rr["verdict"]]
            any_fail = any_fail or sev == "FAIL"
            any_warn = any_warn or sev == "WARN"
            if args.quiet and sev in ("OK", "INFO"):
                continue
            line = f"{sev:<4} {d.name:<20} [{fmt}]  {rr['verdict']:<26} {rr['label']}"
            if "unweighted_mean" in rr:
                line += (
                    f"  reported={rr['reported_reward']} unweighted={rr['unweighted_mean']} "
                    f"weighted={rr['weighted_mean']}"
                )
            print(line)

    counts: dict[str, int] = {}
    for tr in task_results:
        for rr in tr["runs"]:
            counts[rr["verdict"]] = counts.get(rr["verdict"], 0) + 1
    n_run_evals = sum(counts.values())
    print()
    print(
        f"{n_run_evals} task-run pair(s) evaluated: "
        + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    )

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {"how_to_read": HOW_TO_READ, "run_notes": run_notes, "summary": counts, "tasks": task_results},
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"wrote {args.json}")

    if any_fail or any_warn:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
