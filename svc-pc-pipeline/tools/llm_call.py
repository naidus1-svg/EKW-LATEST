#!/usr/bin/env python3
"""llm_call.py - the ONLY three model-call sites in the gate_task.sh pipeline
(HANDOFF.md section 3: "Model calls are `claude -p --model opus` only at
steps 3, 4 and the both-runs-failed adjudication in step 5; everything else
is script").

Thin CLI around /root/ekwqc/deterministic-checks/tools/llm_backend.call_llm
(the exact `claude -p --output-format json` subprocess, prompt on stdin never
argv, that judge_emulate.py's own CLI backend uses) rather than reimplementing
the subprocess call. Forces the CLI backend (Max-plan compute, no API key,
same guarantee judge_emulate.py gives) and the given --model via the
CLAUDE_CODE_MODEL env var llm_backend already reads.

Writes:
  --out.raw.txt   the raw completion text, always.
  --out           the FIRST balanced top-level {...} JSON object found in the
                   completion, extracted tolerant of prose/code-fence wrapping
                   around it. Exits 3 (out still not written) if no JSON
                   object parses, so the caller can park the task rather than
                   act on unparsed text.

Usage:
    python3 llm_call.py --prompt-file P.txt [--system-file S.txt] \
        --model opus --timeout 900 --out OUT.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/root/ekwqc/deterministic-checks/tools")
from llm_backend import LLMBackendError, call_llm  # noqa: E402


def _first_balanced_from(text: str, end: int) -> dict | None:
    """Original fallback: first '{' (scanning left to right, up to index `end`
    exclusive) whose balanced span parses as JSON - used only when the text
    doesn't end cleanly on '}', i.e. the model didn't close with JSON as the
    final content."""
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
                        break  # try next start
    return None


def extract_json_object(text: str) -> dict | None:
    """Return the JSON object that is the FINAL CONTENT of the completion, or
    None. Both blind_cr.md and fix_plan.md instruct the model to close its
    message with the JSON object "as the final content, with no text after
    it" - so the correct object is the one whose closing '}' is the last
    non-whitespace character of the text, not simply the first (nor simply
    the last) '{' that happens to balance somewhere.

    A naive "last '{' that balances" is WRONG: the last '{' in the text is
    the innermost trailing element (e.g. the final array item of an outer
    object, such as CR.json's last `checks[]` entry) - it balances against
    its OWN close long before the real end, so a scan that just tries
    right-to-left and returns the first success grabs that inner fragment
    instead of the outer object surrounding it (confirmed on the
    SVC-PC-54-2-0 redirect test: extracted only check "1.11" in isolation,
    dropping overall_verdict/major_count/checks[]/matrix entirely).

    Correct approach: scan candidate '{' starts LEFT TO RIGHT (so the
    outermost wrapping object is tried before anything nested inside it),
    forward-scan each one's own balanced close (honoring string literals),
    and accept the first candidate whose close lands exactly on the last
    non-whitespace character of the text - by construction this can only be
    the outermost object, since any object nested inside it closes strictly
    before the text's true end. Falls back to the old first-balanced-anywhere
    scan if the text doesn't end cleanly on '}' (a messier completion that
    didn't follow the "JSON as final content" instruction).
    """
    stripped_len = len(text.rstrip())
    if stripped_len == 0:
        return None
    end_idx = stripped_len - 1  # index of the last non-whitespace char
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
                            break  # this span reaches the end but isn't valid JSON; try next start
                    else:
                        break  # this start closes before the true end - not the outer object, try next start
        # unbalanced (or closed early) from this start; move on
    # No candidate's close reached the exact end (e.g. trailing punctuation
    # after the object) - fall back to the most permissive scan.
    return _first_balanced_from(text, len(text))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt-file", type=Path, required=True)
    ap.add_argument("--system-file", type=Path, default=None)
    ap.add_argument("--model", required=True, help="e.g. opus")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    prompt = args.prompt_file.read_text()
    system = args.system_file.read_text() if args.system_file else None

    os.environ["LLM_BACKEND_FORCE"] = "cli"
    os.environ["CLAUDE_CODE_MODEL"] = args.model

    try:
        result = call_llm(prompt, system=system, timeout=args.timeout)
    except LLMBackendError as exc:
        sys.stderr.write(f"ERROR: llm call failed: {exc}\n")
        return 2

    raw_path = args.out.with_suffix(args.out.suffix + ".raw.txt")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(result)

    obj = extract_json_object(result)
    if obj is None:
        sys.stderr.write(f"ERROR: no valid JSON object found in completion, see {raw_path}\n")
        return 3

    args.out.write_text(json.dumps(obj, indent=2))
    sys.stderr.write(f"wrote {args.out} ({len(result)} raw chars -> parsed JSON)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
