#!/usr/bin/env python3
"""metadata_verify.py - ask the metadata_leak check itself whether a metadata edit cleared it.

The check stops at the FIRST expected value a metadata item matches, so clearing one collision can expose a second one in the same
text ("$195.5K" gone, "$389K" now matches). Everything here reuses the check's own extractors and matcher, so the verdict is the one
the zip gate will reach, not a reimplementation.

  load_values(task_dir)                    the task's expected values (the check's own loader)
  collisions(text, values)                 EVERY value a text matches, not just the first
  residual_findings(path, task_dir, loc)   the check's findings for one file (optionally one location) as it stands now
"""

from __future__ import annotations

import sys
from pathlib import Path

CHECKS_DIR = "/root/ekwqc/deterministic-checks"
if CHECKS_DIR not in sys.path:
    sys.path.insert(0, CHECKS_DIR)

import metadata_leak_check as ml  # noqa: E402
from answer_key_content_leak_check import (  # noqa: E402
    _collect_numeric_tokens,
    load_values_for_task,
    match_value_in_file,
)


def load_values(task_dir) -> list[dict]:
    values, _errors = load_values_for_task(Path(task_dir))
    return values


def collisions(text: str, values: list[dict]) -> list[dict]:
    text = (text or "").strip()
    lower = text.lower()
    floats: set = set()
    _collect_numeric_tokens(ml._text_for_numeric_scan(text), floats)
    out = []
    seen = set()
    for v in values:
        mt = match_value_in_file(v, floats, text, lower)
        if mt:
            key = (v["token"], v["criterion"], v["judge_group"], mt)
            if (
                key in seen
            ):  # the same expected value can be loaded twice (once per file it is read from)
                continue
            seen.add(key)
            out.append(
                {
                    "value": v["token"],
                    "value_kind": v["kind"],
                    "match_type": mt,
                    "criterion": v["criterion"],
                    "judge_group": v["judge_group"],
                }
            )
    return out


def residual_findings(
    path, task_dir, location: str | None = None, values: list[dict] | None = None
) -> list[dict]:
    """The check's findings for one file as it stands now. `location` limits it to one comment / part."""
    values = values if values is not None else load_values(task_dir)
    items, _err = ml.extract_metadata_items(Path(path))
    found = []
    for it in items:
        if location and it.get("location") != location:
            continue
        f = ml.evaluate_metadata_item(it, values)
        if f:
            found.append(f)
    return found
