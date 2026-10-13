#!/usr/bin/env python3
"""v3digest_extract_result.py RAW_STDOUT_JSON STDERR_FILE TASK REVIEWER ATTEMPT WALL_SECONDS OUT_JSON STATS_JSON

Post-processes ONE `claude -p --output-format json` attempt for the digest-review
pilot. RAW_STDOUT_JSON is the raw stdout of that call (one JSON object per Claude
Code's --output-format json contract: type/subtype/is_error/result/usage/
total_cost_usd/duration_ms/num_turns). This script:

  1. Parses RAW_STDOUT_JSON; if that fails, treats the whole call as a hard
     failure and records STDERR_FILE's content verbatim as the error.
  2. Extracts the "result" field (the model's final text) and runs the SAME
     extract_json_object()/_first_balanced_from() algorithm
     run_workspace_review_sev2.py uses (copied verbatim from
     /root/qc/tools/llm_call.py, which is read-only - never edited, never
     imported cross-tree since this runs standalone per task+reviewer).
  3. Validates the canonical CR shape with the exact rule
     /root/qc/tools/sev2_pilot.sh's is_canonical() uses: overall_verdict in
     {accept,reject,invalid,needs_revision}, checks a non-empty list of dicts
     each with severity in {major,minor,good}, major_count/minor_count both
     ints.
  4. On success: writes the canonical object to OUT_JSON (pretty JSON) and
     appends this attempt's record to STATS_JSON (creating it if absent).
     Exit 0.
  5. On failure (parse error, is_error=true, or non-canonical shape): does
     NOT write OUT_JSON, appends this attempt's record (with the verbatim
     error/non-canonical reason) to STATS_JSON, and exits 1 so the caller
     (v3digest_review.sh) knows to retry or give up.

STATS_JSON accumulates one entry per attempt under "attempts", plus a
top-level "status" set by the LAST attempt written (v3digest_review.sh
overwrites "status" again after its own retry-or-give-up decision, in
particular to set "TOO_LARGE" when the verbatim error names a context/length
limit - this script only records what happened on ITS attempt).
"""

import json
import sys
from pathlib import Path


def _first_balanced_from(text: str, end: int):
    starts = [i for i, ch in enumerate(text[:end]) if ch == "{"]
    for start in starts:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, end):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
    return None


def extract_json_object(text: str):
    """Verbatim copy of /root/qc/tools/llm_call.py's extract_json_object -
    see that file for the full rationale (outermost-object, left-to-right,
    close-must-land-on-the-text's-true-end scan, falling back to the old
    first-balanced-anywhere scan)."""
    stripped_len = len(text.rstrip())
    if stripped_len == 0:
        return None
    end_idx = stripped_len - 1
    if text[end_idx] != "}":
        return _first_balanced_from(text, len(text))

    starts = [i for i, ch in enumerate(text[: end_idx + 1]) if ch == "{"]
    for start in starts:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, end_idx + 1):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    if i == end_idx:
                        candidate = text[start : i + 1]
                        try:
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            break
                    else:
                        break
        # falls through to try next start
    return _first_balanced_from(text, len(text))


def is_canonical(obj) -> tuple[bool, str]:
    """Same rule as sev2_pilot.sh's is_canonical(), operating on a parsed
    dict instead of a file path. Returns (ok, reason_if_not)."""
    if not isinstance(obj, dict):
        return False, "not a JSON object"
    if obj.get("overall_verdict") not in (
        "accept",
        "reject",
        "invalid",
        "needs_revision",
    ):
        return False, f"bad overall_verdict={obj.get('overall_verdict')!r}"
    checks = obj.get("checks")
    if not isinstance(checks, list) or not checks:
        return False, "checks not a non-empty list"
    for c in checks:
        if not isinstance(c, dict) or c.get("severity") not in (
            "major",
            "minor",
            "good",
        ):
            return False, f"bad check entry: {c!r}"
    if not isinstance(obj.get("major_count"), int) or not isinstance(
        obj.get("minor_count"), int
    ):
        return False, "major_count/minor_count not both int"
    return True, ""


def main():
    if len(sys.argv) != 9:
        print(
            "usage: v3digest_extract_result.py RAW_STDOUT_JSON STDERR_FILE TASK REVIEWER "
            "ATTEMPT WALL_SECONDS OUT_JSON STATS_JSON",
            file=sys.stderr,
        )
        return 2
    raw_p, stderr_p, task, reviewer, attempt, wall_seconds, out_json, stats_json = (
        sys.argv[1:9]
    )
    attempt = int(attempt)
    wall_seconds = float(wall_seconds)
    out_json = Path(out_json)
    stats_json = Path(stats_json)

    record = {
        "attempt": attempt,
        "task": task,
        "reviewer": reviewer,
        "wall_seconds": wall_seconds,
        "canonical": False,
        "usage": None,
        "total_cost_usd": None,
        "num_turns": None,
        "is_error": None,
        "subtype": None,
        "error_verbatim": None,
    }

    raw_text = (
        Path(raw_p).read_text(encoding="utf-8", errors="replace")
        if Path(raw_p).is_file()
        else ""
    )
    stderr_text = (
        Path(stderr_p).read_text(encoding="utf-8", errors="replace")
        if Path(stderr_p).is_file()
        else ""
    )

    top = None
    if raw_text.strip():
        try:
            top = json.loads(raw_text)
        except json.JSONDecodeError as e:
            record["error_verbatim"] = (
                f"claude -p stdout did not parse as JSON: {e}\n--- stdout tail ---\n{raw_text[-3000:]}\n--- stderr tail ---\n{stderr_text[-2000:]}"
            )
    else:
        record["error_verbatim"] = (
            f"claude -p produced no stdout.\n--- stderr tail ---\n{stderr_text[-3000:]}"
        )

    ok = False
    if top is not None:
        record["usage"] = top.get("usage")
        record["total_cost_usd"] = top.get("total_cost_usd")
        record["num_turns"] = top.get("num_turns")
        record["is_error"] = top.get("is_error")
        record["subtype"] = top.get("subtype")
        if top.get("is_error"):
            record["error_verbatim"] = (
                f"claude -p reported is_error=true (subtype={top.get('subtype')}): "
                f"{json.dumps(top.get('result'))[:4000]}"
            )
        else:
            result_text = top.get("result") or ""
            obj = extract_json_object(result_text)
            if obj is None:
                record["error_verbatim"] = (
                    f"no JSON object found in result text (len={len(result_text)}). tail:\n{result_text[-3000:]}"
                )
            else:
                canon_ok, reason = is_canonical(obj)
                if canon_ok:
                    ok = True
                    record["canonical"] = True
                    out_json.parent.mkdir(parents=True, exist_ok=True)
                    out_json.write_text(json.dumps(obj, indent=2), encoding="utf-8")
                else:
                    record["error_verbatim"] = (
                        f"non-canonical shape: {reason}. Parsed object keys: {list(obj.keys())}"
                    )

    stats_json.parent.mkdir(parents=True, exist_ok=True)
    if stats_json.is_file():
        try:
            stats = json.loads(stats_json.read_text(encoding="utf-8"))
        except Exception:
            stats = {"task": task, "reviewer": reviewer, "attempts": []}
    else:
        stats = {"task": task, "reviewer": reviewer, "attempts": []}
    stats["attempts"].append(record)
    stats["status"] = "ok" if ok else "pending"
    stats_json.write_text(json.dumps(stats, indent=2), encoding="utf-8")

    print(
        f"{task} {reviewer} attempt={attempt} canonical={ok}"
        + (
            ""
            if ok
            else f" reason={record['error_verbatim'][:200] if record['error_verbatim'] else 'unknown'}"
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
