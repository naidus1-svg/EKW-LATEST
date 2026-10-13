"""Judge-determinism config lint: does a built task's grading config expose a sampling
temperature and, if it does, does it also expose a panel/sample-count control alongside it?

Why this exists. An external adversarial QC review of three DIFFERENT benchmarks (not this
repo's own SVC-PC) found, as their single most damaging finding, marked CRITICAL severity: an
LLM-judge criterion ran at a nonzero sampling temperature with only ONE sample and no
panel/majority vote. The exact same submission is not guaranteed the same score twice. One
reviewed benchmark's config exposed this directly as a literal JSON field: tests/verifier.json
-> config.temperature, with a value of 1.0 as the smoking gun.

This repo's OWN benchmark (SVC-PC) uses tests/deliverables*/judge.toml with [[criterion]]
blocks, and confirmed by reading many real judge.toml files directly, that shape carries no
temperature or sample-count field anywhere: only [judge] judge/files/weight, [[criterion]]
name/description/type/weight, and a [scoring] aggregation = "weighted_mean" line. If SVC-PC
controls this at all, it is a HARNESS-level setting, not a per-task one -- and that absence is
itself worth surfacing, not silently assumed to be fine. See "Known limits" below.

This is a MULTI-SCHEMA prober, not a single-format parser, because this folder is meant to be used
across benchmarks with different config shapes. For each task directory it tries, in order:

  (a) tests/deliverables/judge.toml and tests/deliverables_*/judge.toml (TOML, this folder's own
      SVC-PC shape -- a task can have more than one, one per deliverable group; every one found
      is parsed and scanned, not just the first).
  (b) tests/verifier.json (JSON), if present.
  (c) tests/manifest.json (JSON), if present.
  (d) any other *.toml or *.json found directly under tests/ (non-recursive, e.g. reward.toml)
      not already covered by (a)-(c), parsed generically by extension.

For whichever config file(s) are found, it walks the PARSED structure (dict keys and list
indices, never raw text and never string VALUES) looking for any key whose name matches
/temperature|sample_?count|n_samples|num_samples|panel|votes?|repeats?/i, at any depth, and
records the field's full path and value. Walking the parsed structure rather than grepping raw
text is deliberate and load-bearing: a raw-text grep for this same pattern across the real
SVC-PC corpus (600+ tasks) hit 129 judge.toml files, and every single hit was a criterion
DESCRIPTION sentence using an English word like "repeats" or "panel" in prose (e.g. "the golden
repeats the same monthly table"), not a config field. Scanning parsed keys, never values, is
what keeps this check from mistaking rubric prose for a determinism-control setting.

Classification per config file (see the aggregate JSON's own "how_to_read_this_report" block
for the same thing in the artifact itself, so a reader never needs this docstring to interpret
the output):

  - "temperature_found_no_panel"  -- FLAGGED. The PX-01 pattern: a temperature-like field with
    a nonzero-looking value, and no panel/sample-count-like field anywhere in the same config.
  - "temperature_and_panel_found" -- NOT flagged. Both a temperature-like and a panel-like field
    are present; reported for confirmation as looking like an intentionally mitigated setup.
  - "temperature_zero_no_panel"   -- NOT flagged. A temperature-like field is present but every
    match reads as zero (greedy/deterministic decoding) -- not the PX-01 risk pattern.
  - "panel_found_no_temperature"  -- NOT flagged. A panel/sample-count-like field is present but
    no temperature-like field was found -- not the PX-01 pattern as written, but not confirmed
    safe either: this check cannot see a temperature control it was never shown.
  - "no_determinism_fields_found" -- EXPLICITLY NOT A PASS/FAIL VERDICT. This config format does
    not expose ANY of these fields at all. If the harness controls sampling determinism
    elsewhere (a global harness setting, an environment variable, code outside this file), this
    check cannot see it, and that absence-of-evidence must never be read as absence-of-risk.
  - "parse_error" -- the file could not be parsed; not scanned, not a verdict of any kind.

Separately, and specific to SVC-PC's own judge.toml shape: since [judge].judge names a judge
model string (e.g. "anthropic/claude-sonnet-4-6") but the schema has no field anywhere to
express a temperature or panel size, every judge.toml where no temperature-like field was found
also carries its own "config_exposes_no_determinism_control" finding. This is independent of the
five buckets above (a future judge.toml that DID add a temperature field would stop carrying
this finding) and is reported as a disclosed, real gap in what this benchmark's task-level
config can express -- not a bug in this script, and not itself a fail verdict.

Task-level status (rolled up across every config file found for that task, worst-first):
    "flag"                -- at least one config file is flagged (temperature_found_no_panel).
    "mitigated"           -- no flags, but at least one config file is temperature_and_panel_found.
    "deterministic_confirmed" -- no flags, no mitigation evidence, and EVERY non-error config
                            file is temperature_zero_no_panel (temperature present and confirmed
                            zero / greedy decoding). This IS a pass: the config explicitly pins
                            temperature to zero, which is deterministic decoding by definition.
    "not_exposed"         -- no flags, no mitigation evidence, and at least one config file is
                            no_determinism_fields_found or panel_found_no_temperature (the
                            config format does not expose a temperature field, so determinism
                            is UNKNOWN, not confirmed). NOT a pass -- see the bucket note above.
    "parse_error"         -- every config file found for this task failed to parse.
    "no_config_found"     -- tests/ exists but none of (a)-(d) matched anything -- nothing to scan.
    "no_tests_dir"        -- the task directory has no tests/ at all.

Exit code: 1 if any task is "flag", 0 otherwise. "deterministic_confirmed" is a pass.
"not_exposed", "mitigated", "no_config_found" and "parse_error" never fail the run by
themselves -- they are disclosed states, not verdicts, except where noted above.

Known limits, disclosed rather than silently dropped:
    - THE HARNESS-LEVEL BLIND SPOT (the important one). This script only ever reads task-level
      config files under a task's tests/ directory. If a benchmark's actual sampling temperature
      and panel size are set once, globally, by the harness that RUNS judge.toml/verifier.json
      (a launcher flag, an environment variable, code in the eval runner) rather than declared
      per-task, this script cannot see that setting and reports "no_determinism_fields_found" /
      "config_exposes_no_determinism_control" regardless of whether the harness-level setting is
      safe or not. Confirming SVC-PC's actual runtime determinism control (if any) requires
      reading the harness/eval-runner code or its own config, not this script's output.
    - Key-NAME substring matching, not word-boundary matching, on purpose (matches the field
      names the motivating review actually cited). A hypothetical field literally named e.g.
      "control_panel_id" would match the "panel" pattern and be reported even though it plainly
      has nothing to do with a judge panel. Every match is reported with its full field path and
      raw value specifically so a human can make that call in seconds; this script never
      silently drops a weak-looking match, and never silently promotes one to a verdict either.
    - "Nonzero-looking" value classification is best-effort: numbers and numeric strings are
      classified exactly (zero vs nonzero); a non-numeric value (a string like "default", a
      JSON null, a nested object) is classified as "non_numeric"/"null" and treated as
      NOT confirmed-zero for flagging purposes -- i.e. this script would rather over-flag an
      ambiguous value than silently treat "could not confirm zero" as "confirmed safe."
    - Only scans dict/table KEYS, never string values, deliberately (see the 129-file false
      positive avoidance above). A config that encodes its temperature inside a string blob
      (e.g. a YAML or JSON literal embedded inside a TOML string value) will not be seen.
    - (d) only looks directly under tests/, one level, non-recursive, mirroring the "directly
      under tests/" wording this check was specified against. A stray config nested two
      directories deep under tests/ that is not a deliverables*/judge.toml is invisible to it.
    - Reads the CURRENT on-disk state only. Says nothing about whether a config was fixed by
      other work after this check last ran.

Provenance: built 2026-09-14 in response to an external adversarial QC review of three other
benchmarks whose most damaging (CRITICAL) finding was exactly this pattern, evidenced in one
reviewed benchmark's own file as the literal field tests/verifier.json -> config.temperature
(value 1.0). Built for this folder (harbor-qc-checks) following the CLI/output conventions of its
sibling checks (deliverable_filename_check.py, rubric_schema_check.py, duplicate_criterion_check.py):
argparse with a required --root and no default, --all + --id-prefix for batch runs, UTF-8
stdout/stderr reconfigure, per-task result + aggregate JSON, and a batch run that never crashes
on one task's malformed file.

Usage:
    python judge_determinism_config_lint.py <TASK-ID> [<TASK-ID> ...] --root <path> --out report.json
    python judge_determinism_config_lint.py --all --root <path> --out report.json
    python judge_determinism_config_lint.py --all --root <path> --id-prefix SVC-PC- --out report.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

# Windows console defaults to cp1252, which can't encode every character that shows up in a
# real task's judge.toml/verifier.json (curly quotes, non-ASCII in vendored text, etc). Force
# UTF-8 with replacement so a printable-but-non-cp1252 character never crashes a batch run
# partway through.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# field-name patterns
# ---------------------------------------------------------------------------

# Matches the field-name evidence the motivating external review actually cited
# (tests/verifier.json -> config.temperature) plus the panel/sample-count controls that would
# mitigate it. Applied to KEY NAMES only -- never to string values -- so criterion-description
# prose that happens to use one of these English words is never mistaken for a config field.
TEMPERATURE_RE = re.compile(r"temperature", re.I)
PANEL_RE = re.compile(
    r"sample_?count|n_samples|num_samples|panel|votes?|repeats?", re.I
)

KNOWN_JUDGE_TOML_GLOB_A = "deliverables/judge.toml"
KNOWN_JUDGE_TOML_GLOB_B = "deliverables_*/judge.toml"

MAX_WALK_DEPTH = 60  # guard rail only; TOML/JSON can't actually cycle


# ---------------------------------------------------------------------------
# generic value/field helpers
# ---------------------------------------------------------------------------


def to_jsonable(v):
    if v is None or isinstance(v, (str, bool, int, float)):
        return v
    if isinstance(v, list):
        return [to_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): to_jsonable(x) for k, x in v.items()}
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def classify_value(value) -> str:
    """Best-effort zero/nonzero read of a matched field's value. Anything that can't be
    confirmed as exactly zero is classified as non-zero-looking territory ("nonzero" or
    "non_numeric"/"null"), never silently folded into "zero" -- see Known limits: this script
    would rather over-flag an ambiguous value than treat "unconfirmed" as "safe"."""
    if isinstance(value, bool):
        return "nonzero" if value else "zero"
    if isinstance(value, (int, float)):
        return "zero" if value == 0 else "nonzero"
    if isinstance(value, str):
        try:
            f = float(value.strip())
            return "zero" if f == 0 else "nonzero"
        except ValueError:
            return "non_numeric"
    if value is None:
        return "null"
    return "non_numeric"


def field_categories(key: str) -> list[str]:
    cats = []
    if TEMPERATURE_RE.search(key):
        cats.append("temperature")
    if PANEL_RE.search(key):
        cats.append("panel_or_sample_count")
    return cats


def walk_for_fields(node, path: str, out: list, depth: int = 0) -> None:
    """Recursively search a parsed TOML/JSON structure for keys matching the determinism
    field-name patterns. Only dict KEYS are ever tested against the patterns -- string, list,
    and scalar VALUES are recursed into (for nested dicts/lists) but never pattern-matched
    themselves. This is what keeps rubric-criterion prose ("...the golden repeats the same
    monthly table...") from ever being reported as a config field."""
    if depth > MAX_WALK_DEPTH:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            key_str = str(k)
            child_path = f"{path}.{key_str}" if path else key_str
            cats = field_categories(key_str)
            if cats:
                out.append(
                    {
                        "field_path": child_path,
                        "value": to_jsonable(v),
                        "value_kind": classify_value(v),
                        "categories": cats,
                    }
                )
            walk_for_fields(v, child_path, out, depth + 1)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk_for_fields(v, f"{path}[{i}]", out, depth + 1)
    # scalars: nothing further to recurse into


# ---------------------------------------------------------------------------
# task/file discovery
# ---------------------------------------------------------------------------


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
    return sorted(
        p for p in root.iterdir() if p.is_dir() and p.name.startswith(id_prefix)
    )


def discover_config_specs(task_dir: Path) -> list[tuple[Path, str]]:
    """Returns [(path, format_label), ...] in the (a)-(d) order from the module docstring.
    format_label is one of judge_toml / verifier_json / manifest_json / other_toml /
    other_json. Every match is included -- this does not stop at the first format found,
    because a real SVC-PC task legitimately has multiple judge.toml (one per deliverable
    group) plus other tests/*.toml files (e.g. reward.toml) in the same task."""
    tests_dir = task_dir / "tests"
    specs: list[tuple[Path, str]] = []
    covered: set[Path] = set()

    # (a) judge.toml, both the single-deliverable and numbered-deliverable-group layouts.
    judge_paths = sorted(
        set(tests_dir.glob(KNOWN_JUDGE_TOML_GLOB_A))
        | set(tests_dir.glob(KNOWN_JUDGE_TOML_GLOB_B))
    )
    for p in judge_paths:
        specs.append((p, "judge_toml"))
        covered.add(p.resolve())

    # (b) verifier.json
    vp = tests_dir / "verifier.json"
    if vp.is_file():
        specs.append((vp, "verifier_json"))
        covered.add(vp.resolve())

    # (c) manifest.json
    mp = tests_dir / "manifest.json"
    if mp.is_file():
        specs.append((mp, "manifest_json"))
        covered.add(mp.resolve())

    # (d) any other *.toml / *.json directly under tests/ (non-recursive), not already covered
    if tests_dir.is_dir():
        for p in sorted(tests_dir.glob("*.toml")) + sorted(tests_dir.glob("*.json")):
            if p.resolve() in covered:
                continue
            fmt = "other_toml" if p.suffix == ".toml" else "other_json"
            specs.append((p, fmt))
            covered.add(p.resolve())

    return specs


# ---------------------------------------------------------------------------
# per-config-file analysis
# ---------------------------------------------------------------------------


def analyze_config_file(path: Path, fmt: str, task_dir: Path) -> dict:
    """Returns one result dict for one config file. Never raises -- a parse failure is
    recorded as parse_error, not a crash that would kill the batch."""
    rel = str(path.relative_to(task_dir)).replace("\\", "/")
    cfg = {
        "path": rel,
        "format": fmt,
        "parse_error": None,
        "fields_found": [],
        "has_temperature_field": False,
        "has_panel_field": False,
        "classification": None,
        "classification_note": None,
        "flagged": False,
        "svc_pc_config_exposes_no_determinism_control": None,
    }

    try:
        text = path.read_text(encoding="utf-8")
        if fmt in ("judge_toml", "other_toml"):
            data = tomllib.loads(text)
        else:
            data = json.loads(text)
    except Exception as e:
        cfg["parse_error"] = f"{type(e).__name__}: {e}"
        cfg["classification"] = "parse_error"
        cfg["classification_note"] = (
            "this config file could not be parsed, so this check could not scan it for "
            "determinism-control fields at all -- a parse failure, not a verified-clean result."
        )
        return cfg

    matches: list[dict] = []
    if isinstance(data, dict):
        walk_for_fields(data, "", matches)
    # a top-level JSON array is legal JSON but not a config shape this check expects; if it
    # happens, there is simply nothing to walk (no dict keys at the top), which is disclosed
    # via an empty fields_found + no_determinism_fields_found rather than a crash.
    cfg["fields_found"] = matches

    temp_matches = [m for m in matches if "temperature" in m["categories"]]
    panel_matches = [m for m in matches if "panel_or_sample_count" in m["categories"]]
    cfg["has_temperature_field"] = bool(temp_matches)
    cfg["has_panel_field"] = bool(panel_matches)
    temp_nonzero = [m for m in temp_matches if m["value_kind"] != "zero"]

    if temp_matches and panel_matches:
        cfg["classification"] = "temperature_and_panel_found"
        cfg["flagged"] = False
        cfg["classification_note"] = (
            "NOT FLAGGED. Both a temperature-like field and a panel/sample-count-like field are "
            "present in this config -- looks like an intentionally mitigated setup (repeated "
            "sampling with a panel/vote aggregation). Reported for human confirmation, not "
            "flagged as a defect."
        )
    elif temp_matches:
        if temp_nonzero:
            cfg["classification"] = "temperature_found_no_panel"
            cfg["flagged"] = True
            cfg["classification_note"] = (
                "FLAGGED -- PX-01 pattern. A temperature-like field with a nonzero-looking value "
                "and no panel/sample-count-like field anywhere in this config. The exact same "
                "submission is not guaranteed the same score twice."
            )
        else:
            cfg["classification"] = "temperature_zero_no_panel"
            cfg["flagged"] = False
            cfg["classification_note"] = (
                "NOT FLAGGED. A temperature-like field is present but every match reads as zero "
                "(greedy/deterministic decoding) -- not the PX-01 risk pattern; no panel field "
                "is needed for a temperature of zero."
            )
    elif panel_matches:
        cfg["classification"] = "panel_found_no_temperature"
        cfg["flagged"] = False
        cfg["classification_note"] = (
            "NOT FLAGGED, NOT CONFIRMED SAFE. A panel/sample-count-like field is present but no "
            "temperature-like field was found in this config -- this check cannot assess "
            "sampling-temperature risk without a temperature field to read."
        )
    else:
        cfg["classification"] = "no_determinism_fields_found"
        cfg["flagged"] = False
        cfg["classification_note"] = (
            "EXPLICITLY NOT A PASS/FAIL VERDICT. This config format does not expose any "
            "temperature/panel/sample-count-like field at all. If a harness controls sampling "
            "determinism elsewhere (a global harness setting, an environment variable, code "
            "outside this config file), this check cannot see it -- absence of the field here "
            "is absence of evidence, not evidence of safety."
        )

    if fmt == "judge_toml" and not cfg["has_temperature_field"]:
        judge_table = data.get("judge") if isinstance(data.get("judge"), dict) else {}
        judge_model = judge_table.get("judge")
        cfg["svc_pc_config_exposes_no_determinism_control"] = {
            "finding": "config_exposes_no_determinism_control",
            "judge_model": to_jsonable(judge_model),
            "note": (
                "SVC-PC's own judge.toml shape names a judge model string in [judge].judge "
                f"({judge_model!r}) but has no field in this benchmark's schema to express a "
                "sampling temperature or a panel/vote count. This is a disclosed, real gap in "
                "what this benchmark's task-level config can express -- not a bug in this "
                "script -- reported for every SVC-PC-shaped judge.toml regardless of the "
                "classification bucket above."
            ),
        }

    return cfg


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(task_dir: Path) -> dict:
    """Returns one result dict for one task. Never raises."""
    task_id = task_dir.name
    result = {
        "task_id": task_id,
        "tests_dir_exists": False,
        "configs": [],
        "config_formats_found": [],
        "flagged_configs": [],
        "svc_pc_findings": [],
        "parse_errors": [],
        "status": None,
        "errors": [],
    }

    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        result["status"] = "no_tests_dir"
        result["errors"].append(
            "no tests/ directory found for this task -- nothing to check"
        )
        return result
    result["tests_dir_exists"] = True

    specs = discover_config_specs(task_dir)
    if not specs:
        result["status"] = "no_config_found"
        result["errors"].append(
            "no tests/deliverables*/judge.toml, tests/verifier.json, tests/manifest.json, or "
            "any other tests/*.toml or tests/*.json found -- nothing for this check to scan"
        )
        return result

    for path, fmt in specs:
        try:
            cfg = analyze_config_file(path, fmt, task_dir)
        except Exception as e:  # never let one file's crash kill the whole batch
            cfg = {
                "path": str(path.relative_to(task_dir)).replace("\\", "/"),
                "format": fmt,
                "parse_error": f"unhandled exception: {e}",
                "fields_found": [],
                "has_temperature_field": False,
                "has_panel_field": False,
                "classification": "parse_error",
                "classification_note": "unhandled exception while analyzing this file",
                "flagged": False,
                "svc_pc_config_exposes_no_determinism_control": None,
            }
        result["configs"].append(cfg)

    result["config_formats_found"] = sorted({c["format"] for c in result["configs"]})
    result["flagged_configs"] = [c["path"] for c in result["configs"] if c["flagged"]]
    result["svc_pc_findings"] = [
        {"path": c["path"], **c["svc_pc_config_exposes_no_determinism_control"]}
        for c in result["configs"]
        if c["svc_pc_config_exposes_no_determinism_control"]
    ]
    result["parse_errors"] = [
        {"path": c["path"], "error": c["parse_error"]}
        for c in result["configs"]
        if c["parse_error"]
    ]

    non_error = [c for c in result["configs"] if not c["parse_error"]]
    if not non_error:
        result["status"] = "parse_error"
    elif any(c["flagged"] for c in non_error):
        result["status"] = "flag"
    elif any(c["classification"] == "temperature_and_panel_found" for c in non_error):
        result["status"] = "mitigated"
    elif all(
        c["classification"] == "temperature_zero_no_panel" for c in non_error
    ):
        result["status"] = "deterministic_confirmed"
    else:
        result["status"] = "not_exposed"

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


HOW_TO_READ_THIS_REPORT = {
    "purpose": (
        "Probes a task's grading config for a sampling-temperature field and, if found, whether "
        "a panel/sample-count field sits alongside it -- the CRITICAL pattern an external review "
        "found in three other benchmarks: a nonzero-temperature LLM-judge criterion with only "
        "one sample and no panel/majority vote, so the same submission is not guaranteed the "
        "same score twice."
    ),
    "task_status": {
        "flag": "At least one config file for this task is the PX-01 pattern. Actionable.",
        "mitigated": (
            "No flags; at least one config file shows both a temperature-like field and a "
            "panel-like field together. Looks intentionally safe, not independently proven safe."
        ),
        "deterministic_confirmed": (
            "Every non-error config file for this task explicitly pins temperature to zero "
            "(temperature_zero_no_panel). This IS a pass: greedy/deterministic decoding by "
            "definition, no panel needed."
        ),
        "not_exposed": (
            "NOT A PASS. At least one config file found for this task exposes none of these "
            "fields (or only a panel field with no temperature). This means the config format "
            "used by that file cannot express the risk this check looks for -- it says nothing "
            "about whether a harness-level setting elsewhere is safe."
        ),
        "parse_error": "Every config file found for this task failed to parse. Not scanned.",
        "no_config_found": (
            "tests/ exists but none of judge.toml / verifier.json / manifest.json / other "
            "tests/*.toml|*.json was found. Nothing to scan."
        ),
        "no_tests_dir": "This task directory has no tests/ at all.",
    },
    "config_classification": {
        "temperature_found_no_panel": "FLAGGED. The PX-01 pattern.",
        "temperature_and_panel_found": "Not flagged. Both fields present together.",
        "temperature_zero_no_panel": "Not flagged. Temperature present but reads as zero.",
        "panel_found_no_temperature": "Not flagged, not confirmed safe. No temperature field to read.",
        "no_determinism_fields_found": (
            "NOT A VERDICT OF SAFETY. This config format exposes none of these fields. A "
            "harness-level setting this check cannot see may or may not exist."
        ),
        "parse_error": "File could not be parsed. Not scanned.",
    },
    "svc_pc_config_exposes_no_determinism_control": (
        "A separate, always-on finding for every SVC-PC-shaped judge.toml with no temperature "
        "field: this benchmark's own schema has nowhere to declare a sampling temperature or "
        "panel size at the task level. Disclosed gap, not a bug in this script, not itself a "
        "fail verdict."
    ),
    "the_one_thing_this_check_cannot_see": (
        "A harness-level or environment-level determinism setting that lives outside every "
        "task's tests/ directory. 'not_exposed' / 'config_exposes_no_determinism_control' mean "
        "this script found no task-level field -- they do NOT mean the run is verified "
        "deterministic. Confirm the harness/eval-runner's own settings separately."
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Multi-schema prober for a judge-determinism config gap: an LLM-judge criterion run "
            "at a nonzero sampling temperature with no panel/sample-count control (the PX-01 "
            "pattern an external review found as its most damaging finding in three other "
            "benchmarks). Tries, per task, tests/deliverables*/judge.toml (this folder's own "
            "SVC-PC shape), tests/verifier.json, tests/manifest.json, and any other tests/*.toml "
            "or *.json, and reports every temperature/panel/sample-count-like field found in the "
            "PARSED structure (never raw text, never string values -- see the module docstring "
            "for why that distinction matters on this corpus)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "task_ids",
        nargs="*",
        help="one or more task ids (directory names under --root)",
    )
    ap.add_argument(
        "--all", action="store_true", help="run every task directory found under --root"
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=None,
        required=False,
        help="root directory containing one subdirectory per task (REQUIRED -- no default, "
        "this must never silently assume a project-specific path)",
    )
    ap.add_argument(
        "--id-prefix",
        default="",
        help="when using --all, only treat subdirectories starting with this prefix as tasks "
        "(default: empty, i.e. every subdirectory is treated as a task)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the aggregate JSON report here (default: print summary only)",
    )
    args = ap.parse_args()

    if args.root is None:
        ap.error(
            "--root is required (point it at the directory containing your task folders)"
        )

    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")

    if not args.root.is_dir():
        print(
            f"--root does not exist or is not a directory: {args.root}", file=sys.stderr
        )
        return 2

    task_dirs = find_task_dirs(
        args.root, None if args.all else args.task_ids, id_prefix=args.id_prefix
    )
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        return 2

    results = []
    for i, task_dir in enumerate(task_dirs, 1):
        print(f"[{i}/{len(task_dirs)}] {task_dir.name} ...", file=sys.stderr)
        try:
            r = analyze_task(task_dir)
        except Exception as e:  # never let one task's crash kill the whole batch
            r = {
                "task_id": task_dir.name,
                "status": "flag",
                "errors": [f"unhandled exception analyzing this task: {e}"],
                "tests_dir_exists": False,
                "configs": [],
                "config_formats_found": [],
                "flagged_configs": [],
                "svc_pc_findings": [],
                "parse_errors": [],
            }
        results.append(r)
        n_flagged = len(r.get("flagged_configs", []))
        n_svc = len(r.get("svc_pc_findings", []))
        print(
            f"    -> {r['status']}  ({len(r.get('configs', []))} config file(s), "
            f"{n_flagged} flagged, {n_svc} svc_pc no-determinism-control finding(s))",
            file=sys.stderr,
        )

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    format_counts: dict[str, int] = {}
    for r in results:
        for fmt in r.get("config_formats_found", []):
            format_counts[fmt] = format_counts.get(fmt, 0) + 1

    n_flag = counts.get("flag", 0)
    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "id_prefix": args.id_prefix,
        "n_tasks": len(results),
        "status_counts": counts,
        "config_format_counts": format_counts,
        "how_to_read_this_report": HOW_TO_READ_THIS_REPORT,
        "results": results,
    }

    print(f"\n{len(results)} task(s) checked.")
    print("status counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print("config formats seen: " + (", ".join(sorted(format_counts)) or "none"))
    if n_flag:
        print(f"\n{n_flag} task(s) FLAGGED (PX-01 pattern):")
        for r in results:
            if r["status"] == "flag":
                print(f"  {r['task_id']}: {', '.join(r['flagged_configs'])}")
    else:
        print(
            "\nNo task hit the PX-01 flag. This does NOT mean determinism is verified -- see "
            "'not_exposed' in status_counts and how_to_read_this_report.the_one_thing_this_"
            "check_cannot_see."
        )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, default=str)
        print(f"\nWrote {args.out}")

    return 1 if n_flag else 0


if __name__ == "__main__":
    raise SystemExit(main())
