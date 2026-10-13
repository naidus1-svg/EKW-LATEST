#!/usr/bin/env python3
"""assemble_gate.py - HANDOFF.md section 3 step 6: build GATE.md from the
artifacts a gate_task.sh run left under its stream-pipe/<task>/ directory.

Pure script, no model call. Reads whatever is present (a task that parked
after step 4 will be missing probes/ and solver/; this script records that as
"not reached" rather than failing) and writes one markdown file with the
GATE-V2 3.4 / 3.6.11 ship-criteria checklist, each line naming its evidence
file, per GATE-V2 3: "recorded per task in GATE.md ... with the evidence
pointer for each line."

Usage:
    python3 assemble_gate.py --pipe-dir DIR --task TASK --out GATE.md
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
from pathlib import Path


def load_json(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def fmt_bool(b) -> str:
    if b is None:
        return "N/A"
    return "YES" if b else "NO"


def criterion_rows(reward_json: dict | None) -> list[dict]:
    if not reward_json:
        return []
    out = []

    def walk(group):
        for c in group.get("criteria", []):
            out.append(c)
        for child in group.get("children", []):
            walk(child)

    for g in reward_json.get("groups", []):
        walk(g)
    return out


def truncate(s: str, n: int = 100) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pipe-dir", type=Path, required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--corpus-root", type=Path, default=None,
                     help="task corpus root, for deriving class-K applicability from the "
                          "shipped deliverable file type directly rather than from a CR.json "
                          "field the canon ekw-svc-comprehensive-review.md schema doesn't have")
    args = ap.parse_args()

    pd = args.pipe_dir
    task = args.task
    lines: list[str] = []
    lines.append(f"# GATE-V2 gate_task.sh pipeline record - {task}")
    lines.append("")
    lines.append(f"Working directory: `{pd}`")
    lines.append("")

    # --- CR: canon ekw-svc-comprehensive-review.md §5 schema (redirect build,
    # 2026-09-18) - overall_verdict/major_count/minor_count/matrix/checks[],
    # not the pre-redirect verdict/majors_present/maps/findings shape. Both are
    # read here since archived zips built before the redirect still carry the
    # old shape in their own CR.json copies.
    cr = load_json(pd / "CR.json")
    lines.append("## 1. Blind CR")
    is_canon_schema = cr is not None and "overall_verdict" in cr
    if cr is None:
        lines.append("- CR.json: **NOT PRESENT** (step 3 did not complete)")
    elif is_canon_schema:
        lines.append("- Evidence: `CR.json` (raw completion: `CR.json.raw.txt`), schema: canon ekw-svc-comprehensive-review.md §5")
        overall_verdict = cr.get("overall_verdict")
        major_count = cr.get("major_count")
        minor_count = cr.get("minor_count")
        lines.append(
            f"- overall_verdict: **{overall_verdict}**, major_count: **{major_count}**, minor_count: **{minor_count}**"
        )
        lines.append(f"- summary: {cr.get('summary', '')}")
        checks = cr.get("checks", [])
        majors = [c for c in checks if c.get("severity") == "major"]
        minors = [c for c in checks if c.get("severity") == "minor"]
        lines.append("")
        lines.append(f"- Checks: {len(checks)} total, {len(majors)} major, {len(minors)} minor (full text in `CR.json`)")
        if majors:
            lines.append("- Major checks:")
            for c in majors:
                lines.append(f"  - **{c.get('id')} {c.get('name')}**: {truncate(c.get('justification', ''), 200)}")
        if minors:
            lines.append("- Minor checks (fixed if class K/mechanical only — otherwise logged, not fixed, per the ship-bar correction below):")
            for c in minors:
                lines.append(f"  - {c.get('id')} {c.get('name')}: {truncate(c.get('justification', ''), 200)}")
        matrix = cr.get("matrix", {})
        if matrix:
            lines.append("")
            lines.append("- Per-mechanism matrix (§1b; `finding:` cells truncated to 100 chars, full text in `CR.json`):")
            lines.append("")
            lines.append("| criterion | M1 | M2 | M3 | M4 | M5 | M6 |")
            lines.append("|---|---|---|---|---|---|---|")
            for crit, row in matrix.items():
                cells = [truncate(str(row.get(m, "")), 100) for m in ("M1", "M2", "M3", "M4", "M5", "M6")]
                lines.append(f"| {crit} | " + " | ".join(cells) + " |")
        lines.append("")
        lines.append("### Ship decision (fix-task-from-review.SKILL.md Step 6, corrected ship bar)")
        if major_count == 0 and overall_verdict == "accept":
            lines.append("- **SHIPPED** — overall_verdict=accept, major_count=0. Shipped on accept per fix-task-from-review Step 6.")
        elif major_count == 0:
            lines.append(
                f"- **SHIPPED** — major_count=0 (overall_verdict={overall_verdict}, minor_count={minor_count}). "
                "Ship bar is major_count == 0, not overall_verdict == accept alone (correction from Khiem, "
                "2026-09-18: accept OR needs_revision-with-minors-only both ship). Minors above are logged in "
                "this GATE.md, not fixed — a passed package is not edited (canon §1a)."
            )
        else:
            lines.append(f"- **NOT SHIPPED** — major_count={major_count} > 0. Fix rounds run while major_count > 0 (max rounds enforced by gate_task.sh).")

        # GATE-V2 (laptop, 2026-09-18 23:20Z): workspace-mode review - one
        # CR_STATS_<round-label>.json per run_blind_cr call (run_workspace_review.py's
        # own output), never a hardcoded list, so this never drifts from what
        # actually ran.
        stats_files = sorted(glob.glob(str(pd / "CR_STATS_*.json")))
        if stats_files:
            lines.append("")
            lines.append("- Workspace-mode review stats (tool calls / tokens per round, from `claude -p`'s own usage):")
            lines.append("")
            lines.append("| round | tool calls | input tok | output tok | cache read tok | cost ($) |")
            lines.append("|---|---|---|---|---|---|")
            for sf in stats_files:
                label = Path(sf).stem.replace("CR_STATS_", "")
                s = load_json(Path(sf)) or {}
                u = s.get("usage") or {}
                lines.append(
                    f"| {label} | {s.get('tool_calls', '?')} | {u.get('input_tokens', '?')} | "
                    f"{u.get('output_tokens', '?')} | {u.get('cache_read_input_tokens', '?')} | "
                    f"{s.get('total_cost_usd', '?')} |"
                )
    else:
        lines.append(f"- Evidence: `CR.json` (raw completion: `CR.json.raw.txt`), schema: pre-redirect")
        lines.append(f"- Deliverable type: {cr.get('deliverable_type')}, class K applicable: {fmt_bool(cr.get('class_k_applicable'))}")
        lines.append(f"- verdict: **{cr.get('verdict')}**, majors_present: {fmt_bool(cr.get('majors_present'))}")
        maps = cr.get("maps", {})
        map_names = {
            "a_criterion_to_instruction": "(a) criterion -> instruction",
            "b_golden_claim_to_source": "(b) golden claim -> source",
            "c_quantifier_map": "(c) quantifier",
            "d_reliability_map": "(d) reliability",
            "e_requirement_map": "(e) requirement",
            "f_discretion_map": "(f) discretion",
        }
        lines.append("")
        lines.append("| Map | Rows | NONE / major | Zero-NONE? |")
        lines.append("|---|---|---|---|")
        all_zero = True
        for key, label in map_names.items():
            rows = maps.get(key, [])
            bad = [r for r in rows if r.get("verdict") in ("NONE", "major")]
            ok = len(bad) == 0
            all_zero = all_zero and ok
            lines.append(f"| {label} | {len(rows)} | {len(bad)} | {fmt_bool(ok)} |")
        lines.append("")
        lines.append(f"- **All six maps zero-NONE/zero-major: {fmt_bool(all_zero)}**")
        findings = cr.get("findings", [])
        majors = [f for f in findings if f.get("severity") == "major"]
        lines.append(f"- Findings: {len(findings)} total, {len(majors)} major (see `CR.json` for full list)")
    lines.append("")

    # --- Fix log ---
    lines.append("## 2. Fix plan / apply")
    plan = load_json(pd / "PLAN.json")
    fix_log = pd / "FIX-LOG.md"
    if plan is None and not fix_log.is_file():
        lines.append("- No PLAN.json / FIX-LOG.md: no majors found by the CR, no fix round needed.")
    else:
        n_edits = len(plan.get("edits", [])) if plan else 0
        lines.append(f"- Evidence: `PLAN.json` ({n_edits} edits), `FIX-LOG.md` (full apply log)")
        if fix_log.is_file():
            failed = [l for l in fix_log.read_text().splitlines() if "FAILED" in l]
            lines.append(f"- FIX-LOG entries with FAILED outcome: {len(failed)}")
    lines.append("")

    # --- Probes ---
    lines.append("## 3. Probes")
    oracle = load_json(pd / "probes" / "oracle.json")
    if oracle is None:
        lines.append("- Oracle run: **NOT PRESENT**")
    else:
        rows = criterion_rows(oracle)
        failing = [c for c in rows if not c.get("passed")]
        lines.append(
            f"- Oracle run: total_reward={oracle.get('total_reward')}, "
            f"{len(rows)} criteria, {len(failing)} failing "
            f"({fmt_bool(len(failing) == 0)} = 1.0 on every criterion) - evidence `probes/oracle.json`"
        )
        for c in failing:
            lines.append(f"  - FAIL {c.get('id')} ({c.get('name')})")

    nocache = load_json(pd / "probes" / "nocache.json")
    if cr and cr.get("class_k_applicable"):
        if nocache is None:
            lines.append("- No-cache probe (class K, xlsx): **NOT PRESENT**")
        else:
            rows = criterion_rows(nocache)
            failing = [c for c in rows if not c.get("passed")]
            lines.append(
                f"- No-cache probe: total_reward={nocache.get('total_reward')}, "
                f"{len(failing)} criteria lost to formula-cache exposure - evidence `probes/nocache.json`"
            )
    else:
        lines.append("- No-cache probe: N/A (deliverable is not xlsx per CR.json)")

    echo = load_json(pd / "probes" / "echo.json")
    if echo is None:
        lines.append("- Echo probe: **NOT PRESENT**")
    else:
        er = echo.get("total_reward")
        ok = (er is not None) and (er < 0.3)
        lines.append(f"- Echo probe: total_reward={er} (< 0.3 required: {fmt_bool(ok)}) - evidence `probes/echo.json`")
    lines.append("")

    # --- K sentence ---
    lines.append("## 4. Class K disclosure sentence")
    k_flag = pd / "checks" / "k_sentence_applied.txt"
    if k_flag.is_file():
        lines.append(f"- {k_flag.read_text().strip()} - evidence `checks/k_sentence_applied.txt`")
    else:
        lines.append("- Not applicable / not recorded (see checks/formula_cache_exposed.csv)")
    lines.append("")

    # --- Scans ---
    lines.append("## 5. Mechanical scans")
    summary = pd / "checks" / "scan_summary.csv"
    if not summary.is_file():
        lines.append("- scan_summary.csv: **NOT PRESENT**")
    else:
        with summary.open() as f:
            rows = list(csv.DictReader(f))
        my_rows = [r for r in rows if r.get("task_id") == task]
        lines.append(f"- Evidence: `checks/scan_summary.csv` ({len(rows)} rows total)")
        if my_rows:
            r = my_rows[0]
            nonpass = {k: v for k, v in r.items() if k != "task_id" and v not in ("", "pass", None)}
            lines.append(f"- Non-pass cells for {task}: {nonpass if nonpass else 'none'}")
        else:
            lines.append(f"- **no row for {task} in scan_summary.csv**")
    lines.append("")

    # --- Solver runs ---
    lines.append("## 6. GLM solver runs")
    for n in (1, 2):
        rd = load_json(pd.parent.parent / "runs" / task / f"glm-{n}" / "reward-details.json")
        if rd is None:
            lines.append(f"- glm-{n}: **NOT GRADED / NOT PRESENT**")
        else:
            rows = criterion_rows(rd)
            failing = [c for c in rows if not c.get("passed")]
            lines.append(
                f"- glm-{n}: total_reward={rd.get('total_reward')}, {len(failing)} failing criteria - "
                f"evidence `/root/qc/runs/{task}/glm-{n}/reward-details.json`"
            )
    adjud = load_json(pd / "ADJUDICATE.json")
    if adjud is not None:
        afr = adjud.get("any_false_rejection")
        lines.append(f"- Both-runs-failed adjudication: any_false_rejection={fmt_bool(afr)} - evidence `ADJUDICATE.json`")
    lines.append("")

    # --- Actuator ---
    lines.append("## 7. Actuator (stage_and_zip.sh)")
    ziplog = pd / "zip.log"
    if ziplog.is_file():
        tail = ziplog.read_text().splitlines()[-15:]
        lines.append("- Evidence: `zip.log` (tail below)")
        lines.append("```")
        lines.extend(tail)
        lines.append("```")
    else:
        lines.append("- zip.log: **NOT PRESENT** (actuator not yet run)")
    lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
