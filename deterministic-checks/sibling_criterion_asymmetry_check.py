"""Sibling-criterion asymmetry check: when a rubric grades the same underlying fact, or the
same class of undisclosed computational convention, on more than one deliverable or more than
one model parameter, does a fix applied to ONE sibling leave a structurally-identical sibling
unfixed?

Why this exists, and why it needs an LLM rather than a mechanical rule: two confirmed real
incidents in this corpus's own fix-and-reverify history (task_48, task_28; both 2026-09-16,
see skills/ekw/dataos-batch-watch/SKILL.md's "recurring defect classes" section) share one
underlying shape -- a real fix correctly resolved one instance of a defect, and a subsequent
real Data-OS re-upload found the IDENTICAL defect class sitting untouched in a sibling location
the fixer never checked:

  1. Asymmetric carve-out across deliverables (task_48): a memo-side criterion was patched to
     accept a valid per-item citation style ("R-31; R-22"); the workbook-side criterion grading
     the SAME underlying fact (which rule governs which item) was never given the matching
     carve-out. Every solver using that valid style consistently across both deliverables was
     penalized only on the unpatched side.
  2. Undisclosed convention on a sibling model parameter (task_28): a divide-vs-multiply
     ambiguity on a dual-income adjustment was correctly disclosed via an instruction sentence
     and a source-data note. A DIFFERENT parameter in the same financial model (an adoption-rate
     stock-vs-flow ambiguity) had the identical undisclosed-convention shape, untouched by that
     fix, and cost two independent real runs a large reward swing on an equally defensible
     alternate reading.

No mechanical/structural check in this folder targets this pattern specifically:
duplicate_criterion_check.py and duplicate_criterion_content_check.py flag criteria whose TEXT
is near-identical (the opposite failure mode -- silently double-weighting one fact, not leaving
a sibling fact ungraded); compound_criterion_check.py flags one criterion bundling several
facts, not a fact split correctly across two criteria where only one got fixed. Judging whether
two criteria (or two model parameters) actually grade "the same underlying fact" or share "the
same class of ambiguity" requires reading and reasoning about their prose, not a string/AST
match -- hence an LLM call, following the same pattern rubric_overspecification_check.py and
golden_groundedness_check.py already use for their own judgment-requiring checks.

Status: v1, NOT corpus-calibrated (no access to a labeled corpus of this specific defect class
beyond the two hand-confirmed incidents that motivated it). Supplementary / non-gating, like
answer_key_content_leak_check.py and judge_determinism_config_lint.py: findings are always
surfaced, never silently dropped, but this script's own exit code and JSON `status` field never
fail a build on their own -- a human (or a fix-task-from-review pass) reads every finding before
acting on it, consistent with this check needing semantic judgment a false-positive-intolerant
gate should not delegate to an LLM alone.

What it does
------------
1. Loads instruction.md and the rubric criteria (tests/verifier.json for EKW native-harbor,
   tests/deliverables_*/judge.toml for EKW rewardkit-hybrid / SVC-PC) for one task.
2. Sends the LLM one call with the full instruction + full criteria list, asking it to identify
   pairs of criteria that (a) grade the same underlying fact on two different deliverables, or
   (b) grade two different but structurally-identical undisclosed-convention risks in the same
   model, and then check whether one member of the pair carries a leniency/disclosure the other
   lacks.
3. Reports every candidate pair with the LLM's own quoted evidence (which criterion, which
   clause, why it believes they're siblings) so a human reader can accept or reject each one --
   this script does not attempt to auto-resolve any finding.

Usage:
    python sibling_criterion_asymmetry_check.py <TASK-ID> [<TASK-ID> ...] --root <path> \
        [--out report.json]
    python sibling_criterion_asymmetry_check.py --all --root <path> --id-prefix task_ \
        --out report.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools.llm_backend import call_llm, LLMBackendError  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# task / criteria discovery (same shape as tools/svc_*_check.py and formula_health_check.py)
# ---------------------------------------------------------------------------


def find_task_dirs(root: Path, task_ids=None, id_prefix: str = "SVC-PC-"):
    if task_ids:
        dirs = []
        for tid in task_ids:
            p = root / tid
            if not p.is_dir():
                print(f"WARNING: task dir not found, skipping: {p}", file=sys.stderr)
                continue
            dirs.append(p)
        return dirs
    return sorted(
        p for p in root.iterdir() if p.is_dir() and p.name.startswith(id_prefix)
    )


def load_instruction(task_dir: Path) -> str:
    for name in ("instruction.md", "instructions.md"):
        p = task_dir / name
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    return ""


def _criteria_from_verifier_json(path: Path) -> list[dict]:
    try:
        spec = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return []
    verifiers = spec.get("verifiers") if isinstance(spec, dict) else None
    if not isinstance(verifiers, list):
        return []
    out = []
    for v in verifiers:
        if not isinstance(v, dict):
            continue
        name = v.get("name") or v.get("id") or "?"
        meta = v.get("metadata", {}) if isinstance(v.get("metadata"), dict) else {}
        prompt = (
            v.get("assertion", {}).get("rubric", {}).get("prompt", "")
            if isinstance(v.get("assertion"), dict)
            else ""
        )
        source = v.get("source", {})
        source_path = (
            source.get("file", {}).get("arguments", {}).get("path", "")
            if isinstance(source, dict) and isinstance(source.get("file"), dict)
            else ""
        )
        out.append(
            {
                "label": name,
                "source_path": source_path,
                "weight": meta.get("weight"),
                "description": prompt or meta.get("why_justification", ""),
            }
        )
    return out


def _criteria_from_judge_toml(path: Path, group: str) -> list[dict]:
    try:
        spec = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, OSError):
        return []
    out = []
    for c in spec.get("criterion", []):
        if not isinstance(c, dict):
            continue
        files = c.get("files") or c.get("judge", {}).get("files", [])
        out.append(
            {
                "label": f"{group}/{c.get('name', '?')}",
                "source_path": ",".join(files) if isinstance(files, list) else str(files),
                "weight": c.get("weight"),
                "description": c.get("description", ""),
            }
        )
    return out


def load_criteria(task_dir: Path) -> list[dict]:
    """Returns a flat list of {label, source_path, weight, description} across whichever
    rubric shape this task actually uses. Both shapes can't legitimately coexist for one task
    (see the two build genres in skills/ekw/fix-task-from-review/SKILL.md), but this function
    checks both rather than assuming, so a misdetected genre still finds real criteria."""
    tests_dir = task_dir / "tests"
    criteria: list[dict] = []

    verifier_json = tests_dir / "verifier.json"
    if verifier_json.is_file():
        criteria.extend(_criteria_from_verifier_json(verifier_json))

    if tests_dir.is_dir():
        for deliverable_dir in sorted(tests_dir.glob("deliverables_*")):
            judge_toml = deliverable_dir / "judge.toml"
            if judge_toml.is_file():
                criteria.extend(_criteria_from_judge_toml(judge_toml, deliverable_dir.name))

    return criteria


def format_criteria(criteria: list[dict]) -> str:
    lines = []
    for c in criteria:
        w = f" (weight {c['weight']})" if c.get("weight") is not None else ""
        lines.append(
            f"[{c['label']}] source={c.get('source_path') or '?'}{w}\n    {c.get('description', '')}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are auditing one grading rubric for a "sibling asymmetry" defect class:
a fact or ambiguity that has been handled correctly (fixed, disclosed, or given a fairness
carve-out) in ONE criterion, while a structurally-identical sibling elsewhere in the SAME
rubric was never given the same treatment. You are not solving the task and not grading a
submission. Only report pairs you can point to concretely -- quote the actual criterion text
that makes you believe they are siblings. If you find nothing, say so plainly; do not invent a
pair to have something to report."""


def build_prompt(task_id: str, instruction: str, criteria_text: str) -> str:
    return f"""== TASK: {task_id} ==

== INSTRUCTION (instruction.md) ==
{instruction or "[instruction.md not found or empty]"}

== RUBRIC CRITERIA ==
{criteria_text or "[no criteria parsed]"}

== WHAT TO CHECK ==

Two sibling-asymmetry shapes, both real and previously confirmed in this corpus:

(A) ASYMMETRIC CARVE-OUT ACROSS DELIVERABLES. Two criteria grade the SAME underlying fact
(the same decision, the same rule-to-item mapping, the same computed figure) but on two
DIFFERENT deliverables (e.g. a memo and its companion workbook). If one of the pair's text
contains an explicit leniency, carve-out, or acceptance of a valid alternative presentation
(look for phrases like "may also state...", "is also acceptable", "does not need to match
exactly", an explicit worked example of an alternative valid form) and the other member of the
pair grading the identical fact has no matching leniency, that is a finding.

(B) UNDISCLOSED-CONVENTION-ON-A-SIBLING-PARAMETER. If any criterion's own text, or the
instruction's own text, discloses how to resolve a genuine computational ambiguity for ONE
named input/parameter of a model (a stated direction for a divide-vs-multiply choice, a stated
convention for a stock-vs-flow choice, an explicit "apply as a X, not a Y" note), scan the
REST of the rubric and instruction for other named parameters in the same model that plausibly
carry the SAME CLASS of ambiguity (a rate, ratio, or adjustment factor with no stated direction
or convention either in the instruction or in any criterion). List each such undisclosed
sibling parameter you find as a finding, quoting the disclosed parameter's own resolving text
so a reader can see the pattern you are matching.

Return ONLY a JSON object, no other text, in exactly this shape:
{{
  "task_id": "{task_id}",
  "findings": [
    {{
      "shape": "asymmetric_carveout" | "undisclosed_sibling_parameter",
      "criteria": ["<label of criterion A>", "<label of criterion B, or empty string for shape B if no explicit sibling criterion exists>"],
      "evidence": "<direct quote(s) from the criteria/instruction text that support this>",
      "explanation": "<one or two sentences: what is the shared fact/ambiguity, and what is missing on the unfixed side>",
      "confidence": "high" | "medium" | "low"
    }}
  ]
}}
If you find nothing, return {{"task_id": "{task_id}", "findings": []}}."""


def _extract_json(raw: str) -> dict | None:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def check_task(task_dir: Path, timeout: int | None = None) -> dict:
    task_id = task_dir.name
    instruction = load_instruction(task_dir)
    criteria = load_criteria(task_dir)
    if not criteria:
        return {
            "task_id": task_id,
            "status": "skip",
            "reason": "no rubric criteria found (neither tests/verifier.json nor "
            "tests/deliverables_*/judge.toml parsed any)",
            "findings": [],
        }

    prompt = build_prompt(task_id, instruction, format_criteria(criteria))
    try:
        raw = call_llm(prompt, SYSTEM_PROMPT, timeout=timeout)
    except LLMBackendError as e:
        return {
            "task_id": task_id,
            "status": "error",
            "reason": f"LLM backend unavailable: {e}",
            "findings": [],
        }

    parsed = _extract_json(raw)
    if parsed is None:
        return {
            "task_id": task_id,
            "status": "error",
            "reason": "could not parse a JSON object from the LLM response",
            "raw_response_tail": raw[-500:],
            "findings": [],
        }

    findings = parsed.get("findings", []) if isinstance(parsed, dict) else []
    return {
        "task_id": task_id,
        "status": "flagged" if findings else "clean",
        "findings": findings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("task_ids", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--id-prefix", default="SVC-PC-")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument(
        "--timeout", type=int, default=None, help="per-task LLM call timeout in seconds"
    )
    args = ap.parse_args()

    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")

    root = args.root.resolve()
    task_dirs = find_task_dirs(
        root, None if args.all else args.task_ids, id_prefix=args.id_prefix
    )
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        return 1

    results = []
    for i, task_dir in enumerate(task_dirs, 1):
        print(f"[{i}/{len(task_dirs)}] {task_dir.name}...", file=sys.stderr)
        results.append(check_task(task_dir, timeout=args.timeout))

    n_flagged = sum(1 for r in results if r["status"] == "flagged")
    n_errors = sum(1 for r in results if r["status"] == "error")
    n_skipped = sum(1 for r in results if r["status"] == "skip")
    print(
        f"\n{len(results)} task(s) checked: {n_flagged} flagged, "
        f"{len(results) - n_flagged - n_errors - n_skipped} clean, "
        f"{n_skipped} skipped (no rubric found), {n_errors} error(s)"
    )
    for r in results:
        if r["status"] == "flagged":
            print(f"  {r['task_id']}: {len(r['findings'])} finding(s)")
            for f in r["findings"]:
                print(f"      [{f.get('confidence', '?')}] {f.get('shape', '?')}: "
                      f"{f.get('criteria', [])}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"results": results}, f, indent=2)
        print(f"\nWrote {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
