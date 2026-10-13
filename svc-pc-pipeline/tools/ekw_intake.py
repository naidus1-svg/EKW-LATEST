#!/usr/bin/env python3
"""EKW intake for the sandbox fix lanes: normalise a Drive-pulled raw task, check it, build it.

Directories (sandbox; override the root with EKW_ROOT):
    $EKW_ROOT/_pull/<TASK>/     verbatim Drive copy (tools/ekw_pull_drive.py). Never edited.
    $EKW_ROOT/_raw/<TASK>/      normalised authoring source: prompt.txt, verifier.json,
                                source_documents/, expert_solution/. THE LANE EDITS HERE.
    $EKW_ROOT/_harbor/task_<TASK>/  native harbor tree assembled from _raw (complete_harbor_task.py),
                                what ekw_run_checks.py / Check B read.
    $EKW_ROOT/<TASK>/           the DataOS package (ekw_raw_to_rewardkit.py), same shape as an SVC-PC
                                03_dataos_ready package, so judge_emulate.py / svc_prefilter.py read it.

Subcommands (each prints one JSON object on stdout):
    normalize <TASK> [--force]  _pull -> _raw. Layout: nested "Source Documents" / "Expert Solution"
                                folders are used, "Claude Output" is dropped, zips are extracted flat,
                                identical duplicates collapse. verifier.json: fences stripped, task_id set
                                to <TASK>, list-valued rubric prompt / tag / justifications joined into the
                                strings the verifier library's schema requires, one-element path lists
                                unwrapped, missing config filled with the house default. Every coercion is
                                listed in the output.
    check <TASK>                validates _raw against the vendored verifier_lib schema (the copy harbor
                                tasks execute), weights, and the presence of prompt, golden and sources.
    build <TASK>                assembles _harbor/task_<TASK> and converts _raw -> $EKW_ROOT/<TASK>.

Exit codes: 0 ok; 1 findings a fix attempt can address (schema, conversion refusal); 3 an input no fix
can create (no verifier.json, no prompt, no golden files) -> the runner parks; 2 usage/tool error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(os.environ.get("EKW_ROOT", "/root/ekwqc/pipeline/data/ekw_qc"))
TEAM = Path(os.environ.get("EKW_TEAM", "/root/qc/_ekw/team"))
PY = os.environ.get("EKW_PY", sys.executable)
CONVERTER = TEAM / "svc-pc-pipeline" / "tools" / "ekw_raw_to_rewardkit.py"
ASSEMBLER = TEAM / "assemble" / "complete_harbor_task.py"
VLIB_PARENT = (
    TEAM / "assemble" / "harbor_template"
)  # holds verifier_lib/ (the executing copy)
DEFAULT_CONFIG = {
    "models": ["openai/gpt-5.4"],
    "temperature": 1.0,
    "reasoning_effort": "xhigh",
}
SKIP_NAMES = {".ds_store", "thumbs.db", "desktop.ini", "_pull.json"}


def out(obj: dict, rc: int) -> int:
    print(json.dumps(obj, indent=1, ensure_ascii=False))
    return rc


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def classify(rel: str, top: str) -> str | None:
    """Which bucket a pulled file belongs to: 'source', 'expert', or None (dropped)."""
    low = rel.lower()
    if "claude output" in low or "claude_output" in low:
        return None
    if "source documents" in low or "source_documents/source" in low:
        return "source"
    if "expert solution" in low:
        return "expert"
    return {"source_documents": "source", "expert_solution": "expert"}.get(top)


def place(data: bytes, name: str, dest: Path, rec: dict, origin: str) -> None:
    name = os.path.basename(name)
    if not name or name.lower() in SKIP_NAMES or name.startswith("."):
        return
    target = dest / name
    if target.exists():
        if target.read_bytes() == data:
            rec["collapsed_duplicates"].append(origin)
            return
        rec["name_conflicts"].append(f"{origin} (kept the first {name})")
        return
    dest.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    rec["placed"].append(f"{origin} -> {dest.name}/{name}")


def coerce_verifier(raw_text: str, task: str, rec: dict) -> str:
    t = raw_text.lstrip("﻿").strip()
    t2 = re.sub(r"^```\w*\s*", "", t)
    t2 = re.sub(r"\s*```$", "", t2)
    if t2 != t:
        rec["coercions"].append("stripped a markdown code fence around verifier.json")
    try:
        v = json.loads(t2)
    except json.JSONDecodeError as e:
        rec["verifier_problems"].append(f"verifier.json is not valid JSON: {e}")
        return raw_text
    if not isinstance(v, dict) or not isinstance(v.get("verifiers"), list):
        keys = list(v)[:8] if isinstance(v, dict) else type(v).__name__
        rec["verifier_problems"].append(
            f"verifier.json is not in the EKW verifier schema (top-level keys {keys}); it must be rewritten "
            "as {task_id, config, verifiers:[{name, metadata, source, assertion}]}"
        )
        return raw_text
    if v.get("task_id") != task:
        rec["coercions"].append(f"task_id {v.get('task_id')!r} -> {task!r}")
        v["task_id"] = task
    if not isinstance(v.get("config"), dict) or not v["config"].get("models"):
        rec["coercions"].append(
            f"config {v.get('config')!r} -> house default {DEFAULT_CONFIG}"
        )
        v["config"] = dict(DEFAULT_CONFIG, **(v.get("config") or {}))
        v["config"]["models"] = DEFAULT_CONFIG["models"]
    v["config"].setdefault("temperature", 1.0)
    n = {"prompt": 0, "tag": 0, "just": 0, "path": 0}
    for x in v["verifiers"]:
        if not isinstance(x, dict):
            continue
        rub = ((x.get("assertion") or {}).get("rubric")) or {}
        if isinstance(rub.get("prompt"), list):
            rub["prompt"] = "\n".join(str(s) for s in rub["prompt"])
            n["prompt"] += 1
        m = x.get("metadata") or {}
        if isinstance(m.get("tag"), list):
            m["tag"] = "-".join(str(s) for s in m["tag"])
            n["tag"] += 1
        for k in ("how_justification", "why_justification"):
            if isinstance(m.get(k), list):
                m[k] = " ".join(str(s) for s in m[k])
                n["just"] += 1
        src = x.get("source") or {}
        if not isinstance(src, dict):
            continue
        for spec in (
            src.get("file") if isinstance(src.get("file"), list) else [src.get("file")]
        ):
            if not isinstance(spec, dict):
                n["bad_source"] = n.get("bad_source", 0) + 1
                continue
            args = spec.get("arguments") or {}
            if isinstance(args.get("path"), list) and len(args["path"]) == 1:
                args["path"] = args["path"][0]
                n["path"] += 1
    if n.get("bad_source"):
        rec["verifier_problems"].append(
            f"{n['bad_source']} verifier(s) have source.file as a bare string, not "
            '{"type", "command": "extract_text", "arguments": {"path": "output/<file>"}}; rewrite them'
        )
    for k, label in (
        ("prompt", "rubric prompt list -> string"),
        ("tag", "tag list -> string"),
        ("just", "justification list -> string"),
        ("path", "one-element path list -> string"),
    ):
        if n[k]:
            rec["coercions"].append(f"{label} on {n[k]} verifier(s)")
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


def normalize(task: str, force: bool) -> int:
    src, dst = ROOT / "_pull" / task, ROOT / "_raw" / task
    rec = {
        "task": task,
        "cmd": "normalize",
        "pull": str(src),
        "raw": str(dst),
        "placed": [],
        "collapsed_duplicates": [],
        "name_conflicts": [],
        "dropped": [],
        "coercions": [],
        "verifier_problems": [],
        "missing": [],
    }
    if not src.is_dir():
        rec["missing"].append(f"no Drive pull at {src}")
        return out(rec, 3)
    if dst.exists():
        if not force:
            rec["note"] = (
                "_raw exists; left untouched (lane edits live there). Use --force to rebuild from _pull."
            )
            return out(rec, 0)
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    buckets = {"source": dst / "source_documents", "expert": dst / "expert_solution"}
    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(src).as_posix()
        top = rel.split("/", 1)[0]
        if "/" not in rel:
            if rel in ("prompt.txt", "verifier.json"):
                continue
            if rel.lower() not in SKIP_NAMES:
                rec["dropped"].append(
                    f"{rel} (top-level file that is not prompt.txt / verifier.json)"
                )
            continue
        b = classify(rel, top)
        if b is None:
            rec["dropped"].append(f"{rel} (Claude Output / unknown folder)")
            continue
        if p.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(p) as z:
                    for info in z.infolist():
                        mn = info.filename
                        if info.is_dir() or "__MACOSX" in mn:
                            continue
                        mb = classify(mn, "") or (
                            None if "claude output" in mn.lower() else b
                        )
                        if mb is None:
                            rec["dropped"].append(
                                f"{rel}!{mn} (Claude Output inside zip)"
                            )
                            continue
                        place(z.read(info), mn, buckets[mb], rec, f"{rel}!{mn}")
            except zipfile.BadZipFile:
                rec["dropped"].append(f"{rel} (bad zip)")
            continue
        place(p.read_bytes(), p.name, buckets[b], rec, rel)
    if (src / "prompt.txt").is_file():
        shutil.copy2(src / "prompt.txt", dst / "prompt.txt")
    else:
        rec["missing"].append("prompt.txt")
    if (src / "verifier.json").is_file():
        (dst / "verifier.json").write_text(
            coerce_verifier(
                (src / "verifier.json").read_text(
                    encoding="utf-8-sig", errors="replace"
                ),
                task,
                rec,
            ),
            encoding="utf-8",
        )
    else:
        rec["missing"].append("verifier.json")
    if not any(buckets["expert"].glob("*")):
        rec["missing"].append("expert_solution (no golden files)")
    if not any(buckets["source"].glob("*")):
        rec["warn_no_sources"] = (
            "source_documents/ is empty (allowed by the converter; check the prompt needs none)"
        )
    return out(rec, 3 if rec["missing"] else (1 if rec["verifier_problems"] else 0))


def check(task: str) -> int:
    raw = ROOT / "_raw" / task
    rec = {"task": task, "cmd": "check", "raw": str(raw), "missing": [], "findings": []}
    for need in ("prompt.txt", "verifier.json"):
        if not (raw / need).is_file():
            rec["missing"].append(need)
    if not (raw / "expert_solution").is_dir() or not any(
        (raw / "expert_solution").iterdir()
    ):
        rec["missing"].append("expert_solution (no golden files)")
    if rec["missing"]:
        return out(rec, 3)
    sys.path.insert(0, str(VLIB_PARENT))
    # jsonpath_ng is installed with pip --target here, not in the shared /root/venv
    sys.path.insert(0, os.environ.get("EKW_PYLIB", "/root/qc/_ekw/pylib"))
    try:
        from verifier_lib.models import (
            VerifierSpec,
        )  # the vendored copy, which is what executes
    except Exception as e:  # noqa: BLE001
        rec["findings"].append(f"TOOL: cannot import vendored verifier_lib ({e})")
        return out(rec, 2)
    text = (raw / "verifier.json").read_text(encoding="utf-8")
    try:
        spec = VerifierSpec.model_validate_json(text)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        rec["findings"].append(
            "SCHEMA: verifier.json fails the verifier library schema: " + msg[:3000]
        )
        return out(rec, 1)
    if spec.task_id != task:
        rec["findings"].append(f"SCHEMA: task_id {spec.task_id!r} is not {task!r}")
    graded = set()
    for x in spec.verifiers:
        f = x.source.file
        pth = (f.arguments or {}).get("path") if f else None
        for pp in pth if isinstance(pth, list) else [pth]:
            if pp:
                graded.add(os.path.basename(pp))
    have = {p.name.lower() for p in (raw / "expert_solution").iterdir()}
    missing_g = sorted(g for g in graded if g.lower() not in have)
    if missing_g:
        rec["warn_golden_names"] = (
            "graded deliverables with no same-named golden (the converter maps by name "
            "tokens and may still resolve them): " + ", ".join(missing_g)
        )
    rec["verifiers"] = len(spec.verifiers)
    rec["graded_files"] = sorted(graded)
    return out(rec, 1 if rec["findings"] else 0)


def conversion_view(raw: Path, tmp: Path, task: str) -> Path:
    """Copy of _raw the converter can read: multi-path verifiers become the file:[...] list form it takes."""
    view = tmp / task
    shutil.copytree(raw, view)
    v = json.loads((view / "verifier.json").read_text(encoding="utf-8"))
    for x in v.get("verifiers", []):
        src = x.get("source") or {}
        f = src.get("file")
        if isinstance(f, dict) and isinstance(
            (f.get("arguments") or {}).get("path"), list
        ):
            src["file"] = [
                dict(f, arguments=dict(f["arguments"], path=p))
                for p in f["arguments"]["path"]
            ]
    v["task_id"] = task
    (view / "verifier.json").write_text(json.dumps(v, indent=2), encoding="utf-8")
    return view


def build(task: str) -> int:
    raw = ROOT / "_raw" / task
    rec = {"task": task, "cmd": "build", "findings": []}
    if not (raw / "verifier.json").is_file():
        rec["findings"].append("no _raw verifier.json; run normalize first")
        return out(rec, 3)
    # 1. harbor tree for EKW's own checks
    hroot = ROOT / "_harbor"
    hroot.mkdir(exist_ok=True)
    hdir = hroot / f"task_{task}"
    if hdir.exists():
        shutil.rmtree(hdir)
    a = subprocess.run(
        [
            PY,
            str(ASSEMBLER),
            "--task-id",
            task,
            "--prompt",
            str(raw / "prompt.txt"),
            "--source-dir",
            str(raw / "source_documents"),
            "--solution-dir",
            str(raw / "expert_solution"),
            "--verifier",
            str(raw / "verifier.json"),
            "--out",
            str(hroot),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    rec["assemble_rc"] = a.returncode
    rec["harbor"] = str(hdir)
    if a.returncode != 0 or not hdir.is_dir():
        rec["findings"].append(
            "ASSEMBLE: complete_harbor_task.py failed: "
            + (a.stderr or a.stdout)[-1500:]
        )
    # 2. DataOS package
    with tempfile.TemporaryDirectory() as td:
        view = conversion_view(raw, Path(td), task)
        pkg = ROOT / task
        if pkg.exists():
            shutil.rmtree(pkg)
        c = subprocess.run(
            [PY, str(CONVERTER), str(view), "--out-root", str(ROOT)],
            capture_output=True,
            text=True,
            timeout=1800,
        )
    rec["convert_rc"] = c.returncode
    rec["convert_log"] = (c.stdout + c.stderr)[-4000:]
    rec["package"] = str(ROOT / task)
    if c.returncode != 0 or not (ROOT / task / "tests").is_dir():
        rec["findings"].append(
            "CONVERT: ekw_raw_to_rewardkit.py did not produce a clean package:\n"
            + rec["convert_log"]
        )
    return out(rec, 1 if rec["findings"] else 0)


JUNK_SUFFIX = (".orig", ".bak", ".pyc", ".tmp")
JUNK_NAMES = {"lease.json", ".ds_store", "thumbs.db", "__pycache__", "_incidents.md"}


def package(task: str, zip_out: str, evidence: list[str]) -> int:
    """Zip $EKW_ROOT/<TASK> (top-level dir = task id) + a freshness manifest; cold-audit the result."""
    pkg = ROOT / task
    rec = {"task": task, "cmd": "package", "zip": zip_out, "findings": []}
    if not (pkg / "tests").is_dir():
        rec["findings"].append(f"no package at {pkg}")
        return out(rec, 1)
    files = []
    for p in sorted(pkg.rglob("*")):
        rel = p.relative_to(pkg)
        if any(
            part.lower() in JUNK_NAMES for part in rel.parts
        ) or p.name.lower().endswith(JUNK_SUFFIX):
            continue
        if p.is_file():
            files.append((rel.as_posix(), p))
    tmp = zip_out + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, p in files:
            z.write(p, f"{task}/{rel}")
    with zipfile.ZipFile(tmp) as z:  # cold audit of the finished file
        names = z.namelist()
        bad = z.testzip()
    roots = {n.split("/", 1)[0] for n in names}
    if bad:
        rec["findings"].append(f"corrupt member {bad}")
    if roots != {task}:
        rec["findings"].append(f"zip roots {sorted(roots)} != [{task}]")
    for need in (
        "task.toml",
        "instruction.md",
        "tests/reward.toml",
        "tests/test.sh",
        "solution/solve.sh",
    ):
        if f"{task}/{need}" not in names:
            rec["findings"].append(f"missing {need}")
    if not any(
        n.startswith(f"{task}/solution/files/") and not n.endswith("/") for n in names
    ):
        rec["findings"].append("solution/files/ is empty")
    if not any(
        n.startswith(f"{task}/tests/deliverables") and n.endswith("judge.toml")
        for n in names
    ):
        rec["findings"].append("no tests/deliverables*/judge.toml")
    if any(
        n.lower().endswith("lease.json") or "/_raw/" in n or "verifier.json" in n
        for n in names
    ):
        rec["findings"].append("zip carries lease.json / raw authoring files")
    if rec["findings"]:
        os.remove(tmp)
        return out(rec, 1)
    os.replace(tmp, zip_out)
    man = {
        "task": task,
        "zip_sha256": sha(Path(zip_out)),
        "files": {r: sha(p) for r, p in files},
        "evidence": {
            e: (sha(Path(e)) if Path(e).is_file() else None) for e in evidence
        },
        "raw_verifier_sha256": (
            sha(ROOT / "_raw" / task / "verifier.json")
            if (ROOT / "_raw" / task / "verifier.json").is_file()
            else None
        ),
    }
    Path(zip_out + ".manifest.json").write_text(json.dumps(man, indent=1))
    rec["members"] = len(names)
    return out(rec, 0)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("cmd", choices=["normalize", "check", "build", "package"])
    ap.add_argument("task")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--zip", help="package: output zip path")
    ap.add_argument(
        "--evidence",
        action="append",
        default=[],
        help="package: file to hash into the manifest",
    )
    a = ap.parse_args()
    if a.cmd == "package":
        if not a.zip:
            ap.error("package needs --zip")
        return (
            package(a.task, a.zip, a.evidence)
            if re.match(r"^[A-Z]{3}-\d+$", a.task)
            else 2
        )
    if not re.match(r"^[A-Z]{3}-\d+$", a.task):
        return out({"error": f"task id {a.task!r} is not like LGL-131"}, 2)
    if a.cmd == "normalize":
        return normalize(a.task, a.force)
    if a.cmd == "check":
        return check(a.task)
    return build(a.task)


if __name__ == "__main__":
    sys.exit(main())
