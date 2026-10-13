"""Brittle construction-ordering check: does a rubric criterion pin the GOLDEN's specific
intermediate-calculation ordering, labeling, or construction sequence as the only acceptable
one, when the instruction never mandates that ordering and a different, equally valid ordering
reaches the identical final result?

Why this exists, and why no golden-only check can catch it: a real, confirmed incident in this
corpus (task_28, 2026-09-16 -- see skills/ekw/dataos-batch-watch/SKILL.md's "recurring defect
classes" section) had a criterion require a workbook show "Total TAM Students" computed by
applying a household-conversion step BEFORE two filtering steps, with a required intermediate
value pinned to the golden's own specific pipeline order. All three independent real model
submissions applied the same two filtering steps FIRST and the household conversion after --
mathematically commutative, reaching the identical final answer -- and were hard-failed because
their (equally correct) intermediate value didn't match the golden's specific staging point.

This defect is structurally invisible to any check that only reads the golden against the
rubric: the golden, by construction, always satisfies its own convention. Confirming a
criterion is brittle in this way requires ONE of: (a) a real alternate-but-valid submission to
check the criterion's text against (this script's --submission mode, when eval trajectories are
available), or (b) constructing the alternate ordering by hand and reasoning about whether the
instruction actually mandates the golden's specific sequence (this script's default mode, an
LLM call, since "does the instruction mandate this specific sequence" and "is an alternate
sequence mathematically/logically equivalent" both require reading prose and following
arithmetic/logic, not a structural/AST check).

Distinct from existing checks: rubric_overspecification_check.py asks whether the instruction
supports a pinned VALUE, COUNT, NAME, or FORMAT -- a different specificity dimension than a
pinned INTERMEDIATE ORDER/STAGE in a multi-step derivation. golden_arithmetic_check.py
recomputes whether the golden's own literal numbers are correct, not whether the rubric would
also accept a differently-sequenced correct derivation. Neither targets ordering brittleness.

Status: v1, NOT corpus-calibrated (one hand-confirmed real incident, no labeled corpus).
Supplementary / non-gating, same posture as sibling_criterion_asymmetry_check.py and
answer_key_content_leak_check.py: every finding is surfaced with the LLM's own reasoning
attached, but this script's status/exit code never fails a build by itself -- read every
finding before acting on it.

Usage:
    python brittle_construction_ordering_check.py <TASK-ID> [<TASK-ID> ...] --root <path> \
        [--out report.json]
    python brittle_construction_ordering_check.py --all --root <path> --id-prefix task_ \
        --out report.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools.llm_backend import call_llm, LLMBackendError  # noqa: E402
from sibling_criterion_asymmetry_check import (  # noqa: E402
    find_task_dirs,
    load_instruction,
    load_criteria,
    format_criteria,
)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


SYSTEM_PROMPT = """You are auditing one grading rubric for "construction-ordering brittleness":
a criterion that requires a specific INTERMEDIATE value, label, or checkpoint from a multi-step
derivation (a running subtotal partway through a calculation chain, a named stage in a pipeline
of filters/adjustments), where that intermediate checkpoint's numeric value or presence depends
entirely on WHICH ORDER the steps were applied in -- not on whether the final answer is correct.
You are not solving the task and not grading a submission. Only report criteria you can point to
concretely; quote the actual criterion text. If you find nothing, say so plainly."""


def build_prompt(task_id: str, instruction: str, criteria_text: str) -> str:
    return f"""== TASK: {task_id} ==

== INSTRUCTION (instruction.md) ==
{instruction or "[instruction.md not found or empty]"}

== RUBRIC CRITERIA ==
{criteria_text or "[no criteria parsed]"}

== WHAT TO CHECK ==

For each criterion that requires a computed/derived value (not a final headline result, but an
INTERMEDIATE checkpoint partway through a multi-step calculation -- e.g. "Total TAM Students
must be approximately X before applying the role/affordability filters", "the post-role
population must equal Y"), ask two questions:

1. Does the instruction's own text specify, anywhere, the REQUIRED ORDER in which the
   calculation's component steps (filters, adjustments, conversions) must be applied? Quote the
   exact instruction text if so. If the instruction is silent on ordering, or only lists the
   applicable factors/filters without saying which must be applied first, treat that as
   "ordering NOT mandated."

2. If ordering is not mandated by the instruction: is there a DIFFERENT valid order of applying
   the same steps that is mathematically or logically equivalent at the FINAL result (e.g. the
   steps are multiplicative/commutative, or the logical effect is order-independent), but which
   would produce a DIFFERENT value at the specific INTERMEDIATE checkpoint this criterion pins?
   Show your work: name the steps, state that they commute (or don't), and give the two
   candidate values (golden's ordering vs. the alternate ordering) for the pinned checkpoint if
   you can derive them from the instruction/criteria text alone (you do not have the golden
   file's actual data -- reason about the STRUCTURE of the calculation, not exact numbers, if
   the actual figures aren't available to you in what's provided).

A criterion is a finding only if BOTH: ordering is not instruction-mandated, AND a genuinely
different, equally-valid ordering would change the pinned intermediate value/label. A criterion
that only checks the FINAL result (order-independent by construction) is never a finding, even
if it comes from a multi-step calculation.

Return ONLY a JSON object, no other text, in exactly this shape:
{{
  "task_id": "{task_id}",
  "findings": [
    {{
      "criterion": "<label of the flagged criterion>",
      "pinned_checkpoint": "<what intermediate value/label the criterion requires>",
      "instruction_mandates_order": false,
      "alternate_ordering": "<describe the alternate valid ordering and why it's equivalent at the final result>",
      "evidence": "<direct quote(s) from the criterion/instruction text>",
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
            "reason": "no rubric criteria found",
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
    ap.add_argument("--timeout", type=int, default=None)
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
        f"{n_skipped} skipped, {n_errors} error(s)"
    )
    for r in results:
        if r["status"] == "flagged":
            print(f"  {r['task_id']}: {len(r['findings'])} finding(s)")
            for f in r["findings"]:
                print(f"      [{f.get('confidence', '?')}] {f.get('criterion', '?')}: "
                      f"{f.get('pinned_checkpoint', '')}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"results": results}, f, indent=2)
        print(f"\nWrote {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
