#!/usr/bin/env python3
r"""Weight/must-pass gate structure check: from the task PACKAGE alone (no completed run needed),
can this task's declared per-group weights and "must-pass" criteria even be honored by the real
scoring config that ships with it?

Why this exists, and why it is narrower than the "Class 5" framing that prompted it. A GLM
round-27/28 coverage synthesis proposed a check for "declared rubric weights not applied at
runtime / inert must-pass semantics." Before building that from scratch, this session read the
real files it named (SVC-PC-29-2-0's judge.toml/reward.toml) and the actual installed
harbor-rewardkit 0.2.0 source (`rewardkit/runner.py`, `models.py`, `reward.py` under this
machine's site-packages), and found BOTH halves of that finding already exist in this folder,
each validated more strongly than a static config read can validate anything:

  - `weight_aggregation_check.py` (commit d6cdb9c, 2026-09-15) already confirms, against REAL
    completed runs (reward.json vs a hand-computed weighted/unweighted recompute), that the
    platform's cross-group aggregation is an unweighted mean despite declared per-group weights:
    45/45 discriminating SVC-PC task-run pairs show the signature, 0/45 show correct weighting.
  - `certification_gate_check.py` already states, in its own docstring, this exact claim about
    must-pass: "Every SVC-PC judge.toml aggregates by a plain weighted_mean; 'This is a must-pass
    criterion.' is prose inside the description and nothing else," citing the same
    `evaluate_release_outcome` function at the same path (`rubric_xlsx_to_verifier.py:1455`) this
    session was pointed at independently -- and it replays that gate against REAL run output
    (ground truth: SVC-PC-80-7-0, 16 must-pass criteria, both model runs failed several, platform
    still reported 0.7 and 0.6667).

  Neither is redundant busywork to re-verify: this session re-derived the SAME mechanism from the
  installed rewardkit source directly (not by trusting either script's docstring), and it agrees
  exactly. What's real and net-new is the GAP both of those scripts explicitly disclose: they need
  `--run`-pointed completed judge output (reward-details.json / reward.json), which is why
  `svc_run_checks.py` deliberately excludes both from its per-package CHECKS dict ("a post-hoc
  release-time replay, not a per-package deterministic check this runner's sweep model can
  drive" -- see that file's own comment above the `criterion_groundedness` entry). Most of the
  202/600-task corpus has no completed run yet. THIS check fills that specific gap: it asks a
  narrower, purely structural question answerable from the package alone -- "if this task were
  graded today, does its OWN shipped config even have the shape needed to honor its declared
  weights / must-pass language, independent of what any run would show?" It is deliberately a
  precondition check, not a re-detection of the same defect from a different data source.

The confirmed mechanism (read directly from harbor-rewardkit 0.2.0, this machine's installed
copy, `pip show harbor-rewardkit` -> Version: 0.2.0; test.sh installs whatever is "latest on
PyPI" with no version pin, so a future run may use a different version than what this check's
citations were confirmed against -- disclosed, not assumed static):

  1. Cross-group weighting (`rewardkit/runner.py`). Each `tests/deliverables_NN/judge.toml`'s own
     `[judge].weight` becomes that Reward's `reward_weight` attribute (`_build_judge_reward`,
     `judge_cfg.get("weight", 1.0)`). But the TOP-level combination across groups
     (`_score_layout`, when `tests/reward.toml` declares a named `[[reward]]` block) builds each
     group's Score with `weight=spec.weights.get(group.name, 1.0)` -- `spec.weights` is
     `RewardAggregationConfig.weights: dict[str, float] = Field(default_factory=dict)`, so ANY
     group missing from that dict (the common case: SVC-PC-29-2-0's reward.toml is just
     `aggregation = "weighted_mean"` with no `weights` table at all) silently gets weight 1.0,
     NOT its own judge.toml weight. Per-CRITERION weights within a single judge.toml/group ARE
     honored correctly (`_build_judge_reward` passes `weights=[c["weight"] for c in criteria]`
     into `Reward`, consumed by `reward.py`'s `_weighted_mean`) -- the bug is specifically the
     cross-group step, not all weighting everywhere. Fix: an explicit
     `weights = { deliverables_01 = 0.2823, ... }` table inside `tests/reward.toml`'s `[[reward]]`
     block, with keys matching each subdirectory name exactly (rewardkit's own
     `_validate_root_specs` raises `ValueError` at run time if a key doesn't match a real group
     name -- a worse failure than silent unweighting, and this check flags that shape too).
  2. Must-pass gating (`rewardkit/models.py`, `reward.py`). `Aggregation = Literal["weighted_mean",
     "all_pass", "any_pass", "threshold", "required_pass"]`. Only `all_pass` (every criterion must
     score >0) and `required_pass` (every NON-optional criterion must score >0) zero a score on a
     failed criterion; `aggregate_scores()` shows `weighted_mean`/`threshold`/`any_pass` have no
     such gate. "This is a must-pass criterion." in a `description` string is never read by any
     scoring code -- `_build_criteria_from_toml` only carries `description` through as prompt
     text for the judge model to read, never inspects it for gating. A criterion is "optional"
     only via an explicit `optional` key or `annotations.importance` containing "optional" (both
     checked here, matching `_build_criteria_from_toml` exactly) -- absent either, it is NOT
     optional by default, but that only matters under `required_pass`, which none of
     SVC-PC-29-2-0's judge.toml/reward.toml files use (all five groups plus the task-level
     `[[reward]]` are `weighted_mean`).

What this checks, per task directory under `root`:
  SVC-PC (`tests/deliverables*/judge.toml` + `tests/reward.toml`):
    a. Cross-group weight applicability -- only meaningful with 2+ groups whose OWN declared
       `[judge].weight` values are not all equal (if they're all equal, an unweighted mean
       produces the same result and there's nothing to flag, per this check's own brief).
       Fires `weight_gate_unusable` with one of:
         - `reward_toml_missing`      -- no tests/reward.toml at all; rewardkit's discover_layout
                                          then produces no combined top-level score in this shape.
         - `reward_block_missing`     -- reward.toml exists but declares no `[[reward]]` block.
         - `weights_table_unknown_keys` -- a `[[reward]].weights` table exists but names a key
                                          that isn't a real group directory (rewardkit raises
                                          ValueError at run time for this exact shape -- confirmed
                                          against `_validate_root_specs`).
         - `weights_declared_but_unusable` -- the real, common case: unequal group weights exist,
                                          reward.toml's `[[reward]]` has no `weights` table at all,
                                          so every group defaults to weight 1.0 at the combination
                                          step.
       Softer, non-blocking `possible_findings`:
         - `weights_table_partial`     -- a weights table exists but omits some real groups (those
                                          default to 1.0 too, but at least some intent is present).
         - `weights_table_value_mismatch` -- a weights table exists and covers every group, but its
                                          values disagree with judge.toml's own [judge].weight
                                          beyond FLOAT_TOL (stale/hand-edited table, most likely).
    b. Must-pass gate structure -- per group, independent of group count. Fires
       `must_pass_no_gate` (hard) when a group has 1+ criteria whose description matches
       MUST_PASS_RE and that group's own `[scoring].aggregation` is not `required_pass`/`all_pass`
       (task-level reward.toml aggregation is also not a gating mode in every real case checked;
       see Validation). Never fires when the group's aggregation already is required_pass/all_pass
       -- a real gate mechanism exists there, whether or not any run has exercised it yet
       (exercising it is certification_gate_check.py's job).
  EKW (`tests/verifier.json`, via the shared `ekw_verifier_json.load_ekw_criteria`):
    Cross-group weighting is not checked -- EKW has no judge.toml-style subdirectory grouping for
    the platform to get wrong (confirmed empirically by weight_aggregation_check.py's own EKW
    sample: 0/22 pairs flagged, "consistent with EKW having no cross-file grouping step"). Only
    must-pass presence is checked, and only at `possible_findings` (info) tier, never hard-flagged:
    `tests/verifier.json`'s schema (per ekw_verifier_json.py's own documented field list) exposes
    no aggregation/scoring field this check can read, so unlike SVC-PC this check cannot confirm
    from the package alone whether the CONVERTED rewardkit-consumable form (built by
    `pipeline/tools/to_rewardkit.py`, not visible at this path) ends up gating or not.
    `certification_gate_check.py` has the identical package-level blind spot on EKW and only
    resolves it by replaying real run output -- this check does not claim to do better.

Validation (RAN 2026-09-15, real data, not synthetic):
  SVC-PC-29-2-0 (the cited example): 5 groups, weights 0.2823/0.258/0.24/0.1931/0.0266 (not
  equal), tests/reward.toml is exactly `[[reward]] name="reward" aggregation="weighted_mean"`
  with no weights table -> fires `weights_declared_but_unusable`. 10 criteria across the 5 groups
  match MUST_PASS_RE, every group's own [scoring].aggregation is "weighted_mean" -> fires
  `must_pass_no_gate` once per affected group (4 of 5 groups: deliverables_01/02/03/04). Both
  findings reproduced exactly as predicted before running the script, then confirmed by it.
  See this commit's own message for the full-sample fail/warn/pass counts this session measured
  across the real 202-task corpus (`docs/EVAL_RUNBOOK.md`-style: counted, not assumed) --
  recorded there rather than hardcoded in this docstring so the count can't go stale silently in
  this file.

Exit 0 clean (no `weight_gate_unusable` findings across every task checked), 1 if any exist, 2 on
bad usage. Stdlib only; reuses `ekw_verifier_json.py` for the EKW read per this folder's dual-
format convention, never reimplements it. `svc_run_checks.py` / `runner.py` never trust the exit
code either way (every verdict comes from this script's own JSON, matching every sibling check).

    python weight_application_check.py <package_root> [--task TASK-ID ...] [--json out.json]
    python weight_application_check.py C:/ekwqc/repo/pipeline/data/svc_pc_qc/03_dataos_ready \
        --task SVC-PC-29-2-0 --json out.json

Known limits, disclosed rather than silently dropped:
    - This check reads ONLY the package. It never re-derives what `weight_aggregation_check.py`
      or `certification_gate_check.py` already measure from real run output, and a task passing
      here is not evidence a real run would score correctly -- only that the config, if run
      today, structurally COULD apply its own declared weights/gates. A task this check flags
      clean but that still misbehaves at run time is that config actually being fine and some
      OTHER stage (a rewardkit version change, a harness override) causing the mismatch; go check
      the two run-dependent scripts, not this one.
    - `reward.toml`'s `[[reward]]` array can in principle carry more than one named block (an
      EKW-shaped multi-dimension export, per `models.py`'s own comment about "several named
      output aggregations"). No real SVC-PC package sampled has more than one; this check picks
      the entry named "reward" when present, else the first, and does not evaluate any additional
      named dimension beyond that one. Disclosed, not assumed absent.
    - The cross-group weight-applicability check (`check_task_svc`'s `if len(groups) >= 2`
      block) silently skips -- no `weight_gate_unusable`, not even a `possible_findings` entry
      -- when any group's own judge.toml omits `[judge].weight` entirely (`weights.values()`
      containing a `None`). Confirmed 2026-09-15 against every real SVC-PC task directory in the
      600-task corpus at `03_dataos_ready` (511 of those 600 have 2+ groups): 0 of 511 have a
      group missing `[judge].weight`, so this branch is currently dead on real data, not a live
      false negative. Re-check this count before trusting the silence if a future task ever
      omits the field -- this check would currently say nothing about it either way.
    - `MUST_PASS_RE` is a text-marker heuristic (`r"must[\s-]*pass"`, matching
      `ekw_verifier_json.py`'s own `_MUST_PASS_RE` exactly, re-declared here rather than imported
      per this folder's no-downstream-import convention for shared literals) over the criterion's
      `description` string. A must-pass criterion authored without that literal phrase is invisible
      to this check, same blind spot `certification_gate_check.py`'s own text-marker fallback has.
    - The installed harbor-rewardkit version this check's mechanism citations were confirmed
      against is 0.2.0 (this machine, `pip show harbor-rewardkit`). `tests/test.sh` installs
      `harbor-rewardkit[all]` with NO version pin ("latest on PyPI" per that script's own
      comment), so a real run may execute against a newer version whose aggregation internals
      have changed. This check's citations are dated evidence, not a permanent guarantee; re-read
      the installed source before trusting this docstring against a future rewardkit release.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from ekw_verifier_json import has_ekw_config, load_ekw_criteria

# Matches ekw_verifier_json.py's own _MUST_PASS_RE exactly. Re-declared as a separate literal
# here rather than imported, per this folder's established convention for shared regexes
# (weight_aggregation_check.py's PATH_TASK_ID_RE docstring states the same reasoning): every
# consumer keeps its own literal so a future edit to one can't silently desync from the other
# without a diff showing both sides.
MUST_PASS_RE = re.compile(r"must[\s-]*pass", re.IGNORECASE)

FLOAT_TOL = 1e-4
RK_VERSION = "0.2.0"  # installed harbor-rewardkit version this check's citations were confirmed against (2026-09-15); see Known limits.


# --------------------------------------------------------------------------- SVC-PC package read


def _svc_judge_files(task_dir: Path) -> list[Path]:
    return sorted(
        set(task_dir.glob("tests/deliverables/judge.toml"))
        | set(task_dir.glob("tests/deliverables_*/judge.toml"))
    )


def _has_svc_pc_config(task_dir: Path) -> bool:
    return bool(_svc_judge_files(task_dir))


def _load_toml(p: Path) -> dict:
    return tomllib.loads(p.read_text(encoding="utf-8"))


def _svc_group_info(jf: Path) -> tuple[str, float | None, str, list[dict]]:
    """(group_name, declared_weight, aggregation, criteria). criteria: [{"name", "must_pass",
    "optional"}, ...]. optional detection matches rewardkit's own _build_criteria_from_toml
    exactly: an explicit 'optional' key wins, else 'optional' in annotations.importance.
    """
    data = _load_toml(jf)
    group = jf.parent.name
    judge_weight = (data.get("judge") or {}).get("weight")
    declared_weight = (
        float(judge_weight) if isinstance(judge_weight, (int, float)) else None
    )
    scoring = data.get("scoring") or {}
    aggregation = scoring.get("aggregation", "weighted_mean")
    criteria = []
    for c in data.get("criterion") or []:
        desc = str(c.get("description") or "")
        ann = c.get("annotations") or {}
        if "optional" in c:
            optional = bool(c["optional"])
        else:
            optional = "optional" in str(ann.get("importance", "")).lower()
        criteria.append(
            {
                "name": c.get("name"),
                "must_pass": bool(MUST_PASS_RE.search(desc)),
                "optional": optional,
            }
        )
    return group, declared_weight, aggregation, criteria


def _load_reward_spec(
    tests_dir: Path,
) -> tuple[str | None, dict, bool, str | None]:
    """(aggregation, weights_dict, reward_toml_exists, parse_error). aggregation is None when
    reward.toml exists but declares no [[reward]] block at all (reward_block_missing case).
    weights_dict is {} when no 'weights' table is present under the chosen [[reward]] entry.
    """
    p = tests_dir / "reward.toml"
    if not p.is_file():
        return None, {}, False, None
    try:
        data = _load_toml(p)
    except Exception as e:  # noqa: BLE001
        return None, {}, True, f"tests/reward.toml failed to parse: {e}"
    rewards = data.get("reward") or []
    if not rewards:
        return None, {}, True, None
    spec = next((r for r in rewards if r.get("name") == "reward"), rewards[0])
    aggregation = spec.get("aggregation", "weighted_mean")
    weights = spec.get("weights") or {}
    return aggregation, weights, True, None


GATING_AGGREGATIONS = {"required_pass", "all_pass"}


def check_task_svc(task_dir: Path) -> dict:
    parse_errors: list[str] = []
    groups: dict[str, dict] = {}
    for jf in _svc_judge_files(task_dir):
        try:
            name, weight, agg, criteria = _svc_group_info(jf)
        except Exception as e:  # noqa: BLE001
            parse_errors.append(f"{jf.parent.name}/judge.toml: {e}")
            continue
        groups[name] = {
            "declared_weight": weight,
            "aggregation": agg,
            "criteria": criteria,
        }

    weight_gate_unusable: list[dict] = []
    possible_findings: list[dict] = []

    if len(groups) >= 2:
        weights = {g: v["declared_weight"] for g, v in groups.items()}
        if all(w is not None for w in weights.values()):
            vals = list(weights.values())
            all_equal = (max(vals) - min(vals)) <= FLOAT_TOL if vals else True
            if not all_equal:
                agg, reward_weights, reward_exists, reward_err = _load_reward_spec(
                    task_dir / "tests"
                )
                if reward_err:
                    parse_errors.append(reward_err)
                elif not reward_exists:
                    weight_gate_unusable.append(
                        {
                            "type": "reward_toml_missing",
                            "detail": (
                                f"{len(groups)} groups declare unequal weights ({weights}) but "
                                "tests/reward.toml does not exist -- rewardkit's discover_layout "
                                "produces no combined top-level score in this shape at all."
                            ),
                        }
                    )
                elif agg is None:
                    weight_gate_unusable.append(
                        {
                            "type": "reward_block_missing",
                            "detail": (
                                f"{len(groups)} groups declare unequal weights ({weights}) but "
                                "tests/reward.toml has no [[reward]] block -- no combined "
                                "task-level reward name is produced."
                            ),
                        }
                    )
                else:
                    unknown_keys = sorted(set(reward_weights) - set(groups))
                    if unknown_keys:
                        weight_gate_unusable.append(
                            {
                                "type": "weights_table_unknown_keys",
                                "detail": (
                                    f"[[reward]].weights names {unknown_keys}, which do not match "
                                    f"any group directory ({sorted(groups)}). Confirmed against "
                                    f"the installed harbor-rewardkit {RK_VERSION} source "
                                    "(runner.py's _validate_root_specs): this raises ValueError "
                                    "at run time, so the task cannot be graded at all until fixed."
                                ),
                            }
                        )
                    elif not reward_weights:
                        weight_gate_unusable.append(
                            {
                                "type": "weights_declared_but_unusable",
                                "detail": (
                                    f"{len(groups)} groups declare unequal per-group weights via "
                                    f"judge.toml's own [judge].weight ({weights}), but tests/"
                                    f"reward.toml's [[reward]] block has aggregation={agg!r} with "
                                    "no 'weights' table. Confirmed against the installed "
                                    f"harbor-rewardkit {RK_VERSION} source (runner.py's "
                                    "_score_layout): the top-level combination across groups "
                                    "falls back to weight=1.0 for every group absent from "
                                    "[[reward]].weights, producing a plain unweighted mean "
                                    "regardless of each judge.toml's own declared weight. Same "
                                    "underlying mechanism weight_aggregation_check.py confirms "
                                    "empirically against real completed runs; this check flags "
                                    "it statically, from the package alone, before any run exists."
                                ),
                            }
                        )
                    else:
                        missing = sorted(set(groups) - set(reward_weights))
                        if missing:
                            possible_findings.append(
                                {
                                    "type": "weights_table_partial",
                                    "detail": (
                                        f"[[reward]].weights covers {sorted(reward_weights)} but "
                                        f"omits {missing} -- those groups default to weight=1.0 "
                                        "at the combination step even though a weights table "
                                        "exists for the rest."
                                    ),
                                }
                            )
                        else:
                            mismatched = {
                                g: (reward_weights[g], weights[g])
                                for g in groups
                                if abs(float(reward_weights[g]) - weights[g])
                                > FLOAT_TOL
                            }
                            if mismatched:
                                possible_findings.append(
                                    {
                                        "type": "weights_table_value_mismatch",
                                        "detail": (
                                            "[[reward]].weights values disagree with each group's "
                                            "own judge.toml [judge].weight beyond tolerance "
                                            f"(reward.toml value, judge.toml value): {mismatched}"
                                        ),
                                    }
                                )

    for gname, g in groups.items():
        mp = [c for c in g["criteria"] if c["must_pass"]]
        if not mp:
            continue
        if g["aggregation"] in GATING_AGGREGATIONS:
            continue
        weight_gate_unusable.append(
            {
                "type": "must_pass_no_gate",
                "group": gname,
                "criteria": [c["name"] for c in mp],
                "detail": (
                    f"{len(mp)} criterion/criteria in {gname} carry 'must-pass' language in "
                    f"their description, but {gname}/judge.toml's own [scoring].aggregation is "
                    f"{g['aggregation']!r} (not required_pass/all_pass). Confirmed against the "
                    f"installed harbor-rewardkit {RK_VERSION} source (models.py's Aggregation "
                    "literal, reward.py's aggregate_scores): only required_pass/all_pass zero a "
                    "score on a failed criterion; 'must-pass' text in a description is never read "
                    "by any scoring code. Same mechanism certification_gate_check.py already "
                    "replays against real run output (SVC-PC-80-7-0 ground truth in its own "
                    "docstring); this check flags the structural precondition statically."
                ),
            }
        )

    return {
        "task": task_dir.name,
        "format": "svc-pc",
        "n_groups": len(groups),
        "parse_errors": parse_errors,
        "weight_gate_unusable": weight_gate_unusable,
        "possible_findings": possible_findings,
    }


# --------------------------------------------------------------------------- EKW package read


def check_task_ekw(task_dir: Path) -> dict:
    raw = load_ekw_criteria(task_dir)
    parse_errors = [
        str(c.get("description")) for c in raw if c.get("name") == "__parse_error__"
    ]
    criteria = [c for c in raw if c.get("name") != "__parse_error__"]
    possible_findings: list[dict] = []
    mp = [c for c in criteria if c.get("must_pass")]
    if mp:
        possible_findings.append(
            {
                "type": "must_pass_present_no_visible_gate_field",
                "criteria": [c["name"] for c in mp],
                "detail": (
                    f"{len(mp)} verifier(s) declare must_pass, but tests/verifier.json exposes no "
                    "aggregation/scoring field this check can read to confirm a gate exists in "
                    "the converted (rewardkit-consumable) form. certification_gate_check.py's own "
                    "EKW branch has the same package-level blind spot and only resolves it by "
                    "replaying real run output; this check does not claim to do better and "
                    "reports this at info/warn tier only, never hard-flagged."
                ),
            }
        )
    return {
        "task": task_dir.name,
        "format": "ekw",
        "n_groups": len(criteria),
        "parse_errors": parse_errors,
        "weight_gate_unusable": [],  # EKW has no cross-file grouping step; see module docstring.
        "possible_findings": possible_findings,
    }


def check_task_dispatch(task_dir: Path) -> dict:
    if _has_svc_pc_config(task_dir):
        return check_task_svc(task_dir)
    if has_ekw_config(task_dir):
        return check_task_ekw(task_dir)
    return {
        "task": task_dir.name,
        "format": "unknown",
        "n_groups": 0,
        "parse_errors": [
            "no tests/deliverables*/judge.toml (SVC-PC) and no tests/verifier.json (EKW)"
        ],
        "weight_gate_unusable": [],
        "possible_findings": [],
    }


# --------------------------------------------------------------------------- main


def _severity(r: dict) -> str:
    if r.get("weight_gate_unusable"):
        return "FAIL"
    if r.get("parse_errors"):
        return "ERROR"
    if r.get("possible_findings"):
        return "WARN"
    return "PASS"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "root",
        help="package root (one task dir per subdirectory), or a single task dir itself",
    )
    ap.add_argument(
        "--task",
        action="append",
        default=[],
        help="task id(s) to check (repeatable; default: every subdirectory under root)",
    )
    ap.add_argument("--json", help="write the full JSON list here")
    ap.add_argument("--quiet", action="store_true", help="suppress PASS lines")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2

    if (root / "tests").is_dir():
        task_dirs = [root]
    else:
        task_dirs = sorted(d for d in root.iterdir() if d.is_dir())
    if args.task:
        want = set(args.task)
        task_dirs = [d for d in task_dirs if d.name in want]
        for m in sorted(want - {d.name for d in task_dirs}):
            sys.stderr.write(f"warning: task id not found under {root}: {m}\n")
    if not task_dirs:
        sys.stderr.write(f"no task directories matched under {root}\n")
        return 2

    results = [check_task_dispatch(d) for d in task_dirs]

    counts = {"PASS": 0, "WARN": 0, "FAIL": 0, "ERROR": 0}
    for r in results:
        sev = _severity(r)
        counts[sev] += 1
        if args.quiet and sev == "PASS":
            continue
        line = (
            f"{sev:<5} {r['task']:<20} [{r['format']}]  groups={r.get('n_groups', 0)}  "
            f"fail={len(r.get('weight_gate_unusable', []))} "
            f"warn={len(r.get('possible_findings', []))} "
            f"errors={len(r.get('parse_errors', []))}"
        )
        print(line)

    print()
    print(
        f"{len(results)} task(s): pass={counts['PASS']} warn={counts['WARN']} "
        f"fail={counts['FAIL']} error={counts['ERROR']}"
    )

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")

    if counts["FAIL"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
