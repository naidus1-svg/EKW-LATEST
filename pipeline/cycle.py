#!/usr/bin/env python3
"""EKW-GDPVal QC cycle driver — one entrypoint for the 2x/week run.

Every run is a dated folder under cycles/ with the SAME numbered stages, so the
output of each of your 5 steps always lives in the same place:

    cycles/<YYYY-MM-DD>/
        00_fetched/   1. raw tasks pulled from the tracker
        01_diff/      2. changes.md  (new + changed vs the previous cycle)
        02_bundle/    3. harbor-format package sent to the evaluator
        03_evals/     4. evals received back (input to QC)
        04_qc/        4. QC pipeline output (batch_review, reviewer_queue, dashboard)
        05_report/    5. study + team share
        MANIFEST.md      what ran: versions, task list, new/changed, verdicts

Usage:
    python3 pipeline/cycle.py new            [--date YYYY-MM-DD]
    python3 pipeline/cycle.py fetch  <date>          # manual step — prints instructions
    python3 pipeline/cycle.py diff   <date>          # compare 00_fetched vs cycles/latest
    python3 pipeline/cycle.py bundle <date>          # manual step — prints instructions
    python3 pipeline/cycle.py dataos <date>          # Turing internal QC track: reward-kit convert + one-pager + Slack msg
    python3 pipeline/cycle.py dataos-standalone <bundle_dir> <out_dir>   # same, no cycle folder required
    python3 pipeline/cycle.py qc     <date> [-- extra gdpval-assess args]
    python3 pipeline/cycle.py report <date>          # collect human-facing artifacts
    python3 pipeline/cycle.py close  <date>          # advance cycles/latest -> <date>
    python3 pipeline/cycle.py status

    # SVC/Cirrus front — no fetch/diff/bundle; tasks arrive pre-bundled:
    python3 pipeline/cycle.py svc-qc <path/to/tasks/> [--only ids] [--out-dir DIR]

    # Request Phase 1's k=1 Harbor-beta eval directly (see reference/harbor_evals_quick_guide.md):
    python3 pipeline/cycle.py evals-package <date> --batch-prefix PREFIX
    python3 pipeline/cycle.py evals-upload  <date>
    python3 pipeline/cycle.py evals-enqueue <date> --base-url URL --k N --models-file PATH [--live]
    python3 pipeline/cycle.py evals-status  <date> --batch-prefix PREFIX --expected-trials N [--wait]
    python3 pipeline/cycle.py evals-fetch   <date>

new/diff/status/report use only the stdlib; qc shells out to the pinned venv.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent          # project root
PIPELINE = BASE / "pipeline"
CYCLES = BASE / "cycles"
SPEC_DEFAULT = PIPELINE / "specs" / "gdpval_task_quality_v18.md"
SPEC_SVC = PIPELINE / "specs" / "overlays" / "svc.md"       # SVC/Cirrus front: extends the base spec
VENV_PY = PIPELINE / ".venv" / "bin" / "python"
STAGES = ["00_fetched", "01_diff", "02_bundle", "03_evals", "04_qc", "05_report"]

# Change detection hashes the task's ACTUAL CONTENT: every artifact file
# (source documents, expert solution, any verifier.json) plus the task-defining
# tracker fields below. Administrative churn (status, links, dates, scores) is
# deliberately excluded so "changed" means the artifacts genuinely differ.
CONTENT_ROW_FIELDS = ("Prompt", "Rubric JSON")
_STUB_FILES = {"_source.txt", "_row.json"}


def _today() -> str:
    return _dt.date.today().isoformat()


def _cycle(date: str) -> Path:
    return CYCLES / date


def _read_version() -> str:
    vf = PIPELINE / "VERSION"
    return vf.read_text().strip().splitlines()[0] if vf.exists() else "unknown"


def cmd_new(args) -> None:
    date = args.date or _today()
    c = _cycle(date)
    if c.exists():
        print(f"cycle {date} already exists at {c}")
    for s in STAGES:
        (c / s).mkdir(parents=True, exist_ok=True)
    manifest = c / "MANIFEST.md"
    if not manifest.exists():
        prev = os.readlink(CYCLES / "latest") if (CYCLES / "latest").is_symlink() else "(none)"
        manifest.write_text(
            f"# QC Cycle — {date}\n\n"
            f"- Pipeline: {_read_version()}\n"
            f"- Previous cycle (diff baseline): {prev}\n"
            f"- Fetched tasks: _(fill after fetch)_\n"
            f"- New / changed this cycle: _(fill from 01_diff/changes.md)_\n"
            f"- Eval model: _(fill)_\n"
            f"- Verdict summary: _(fill from 04_qc/batch_summary.md)_\n"
            f"- Report: 05_report/\n\n"
            f"## Notes\n\n"
        )
    print(f"created cycle {date}")
    print(f"  next (Step A): export tracker CSV(s) into {c} (tracker.csv or "
          f"tracker_<ekw|svc|intake>.csv), then python3 pipeline/cycle.py fetch {date}")


def _fingerprint(task_dir: Path) -> str:
    h = hashlib.sha256()
    # 1) every artifact file's path + full content (source docs, solution, verifier.json…)
    for f in sorted(task_dir.rglob("*")):
        if f.is_file() and f.name not in _STUB_FILES:
            h.update(str(f.relative_to(task_dir)).encode())
            h.update(f.read_bytes())
    # 2) the task-defining tracker fields (prompt, rubric) — not status/links/dates
    rj = task_dir / "_row.json"
    if rj.is_file():
        try:
            row = json.loads(rj.read_text())
            for k in CONTENT_ROW_FIELDS:
                h.update(k.encode())
                h.update(str(row.get(k, "")).encode())
        except Exception:
            pass
    return h.hexdigest()[:16]


def _task_map(fetched: Path) -> dict[str, str]:
    if not fetched.is_dir():
        return {}
    return {d.name: _fingerprint(d) for d in sorted(fetched.iterdir()) if d.is_dir()}


def cmd_diff(args) -> None:
    c = _cycle(args.date)
    cur = _task_map(c / "00_fetched")
    latest = CYCLES / "latest"
    prev_dir = (CYCLES / os.readlink(latest)) if latest.is_symlink() else None
    prev = _task_map(prev_dir / "00_fetched") if prev_dir else {}
    prev_name = prev_dir.name if prev_dir else "(no baseline)"

    new = sorted(set(cur) - set(prev))
    removed = sorted(set(prev) - set(cur))
    changed = sorted(k for k in cur if k in prev and cur[k] != prev[k])
    unchanged = sorted(k for k in cur if k in prev and cur[k] == prev[k])

    def section(title, items):
        body = [f"- {t}" for t in items] if items else ["- (none)"]
        return [title, *body, ""]

    out = c / "01_diff" / "changes.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Changes — {args.date} vs {prev_name}\n",
        f"- Fetched: {len(cur)} tasks",
        f"- **New: {len(new)}** · **Changed: {len(changed)}** · "
        f"Unchanged: {len(unchanged)} · Removed: {len(removed)}\n",
    ]
    lines += section("## New tasks", new)
    lines += section("## Changed tasks (re-run QC)", changed)
    lines += section("## Removed", removed)
    lines += [f"## Unchanged ({len(unchanged)}) — skip"]
    out.write_text("\n".join(lines) + "\n")
    print(f"diff vs {prev_name}: {len(new)} new, {len(changed)} changed, {len(unchanged)} unchanged, {len(removed)} removed")
    print(f"  -> {out}")
    if new or changed:
        print("  bundle these (new+changed) for the evaluator:")
        for t in new + changed:
            print(f"    {t}")


FETCH_CONFIG = PIPELINE / "fetch.config.json"
DEFAULT_READY = ["ready for review", "ready", "ready_for_review"]
_HDR_PATS = {
    "id": re.compile(r"task\s*id|^id$|task", re.I),
    "status": re.compile(r"status|state|stage", re.I),
    "link": re.compile(r"link|drive|url|folder", re.I),
}


KNOWN_FRONTS = ("ekw", "svc", "intake")


def _load_fetch_cfg(front: str = "ekw") -> dict:
    """Front-scoped fetch config. Supports the current fronts-registry shape
    (fetch.config.json's top-level "fronts": {ekw: {...}, svc: {...}, ...}) and
    falls back to treating the whole file as one flat (legacy, front-less)
    config when no "fronts" key is present, for any old-shape fetch.config.json
    lying around."""
    if not FETCH_CONFIG.exists():
        return {}
    try:
        raw = json.loads(FETCH_CONFIG.read_text())
    except Exception as e:
        print(f"warning: could not parse {FETCH_CONFIG}: {e}")
        return {}
    fronts = raw.get("fronts")
    if fronts is not None:
        return fronts.get(front, {})
    return raw


def _resolve_cols(header: list[str], cfg: dict) -> dict:
    """Map id/status/link -> column index, from config names or fuzzy detection."""
    cells = [str(h or "").strip() for h in header]
    idx = {}
    for key in ("id", "status", "link"):
        want = cfg.get(f"{key}_col")
        if want:  # explicit header name from config (exact, then contains)
            for j, c in enumerate(cells):
                if c.lower() == want.lower():
                    idx[key] = j
                    break
            else:
                for j, c in enumerate(cells):
                    if want.lower() in c.lower():
                        idx[key] = j
                        break
        else:  # fuzzy
            for j, c in enumerate(cells):
                if c and _HDR_PATS[key].search(c):
                    idx[key] = j
                    break
    return idx


def _discover_trackers(c: Path, front_arg: str | None) -> list[tuple[Path, str]]:
    """(csv_path, front) pairs to fetch this run. `tracker.csv` is the legacy
    single-front name (front=ekw, unless --front overrides it). Any
    `tracker_<front>.csv` is picked up per its front. A single other loose
    *.csv is treated the same as legacy tracker.csv, for the pre-multi-front
    workflow where there's exactly one export and no naming convention yet."""
    pairs: list[tuple[Path, str]] = []
    legacy = c / "tracker.csv"
    if legacy.is_file():
        pairs.append((legacy, front_arg or "ekw"))
    for front in KNOWN_FRONTS:
        p = c / f"tracker_{front}.csv"
        if p.is_file() and p != legacy:
            pairs.append((p, front))
    if not pairs:
        loose = [p for p in c.glob("*.csv")]
        if len(loose) == 1:
            pairs.append((loose[0], front_arg or "ekw"))
    return pairs


def _fetch_one_tracker(c: Path, csv_path: Path, front: str, exclude: set[str],
                        fetched_dir: Path) -> dict:
    """Fetch ready tasks from one tracker CSV into 00_fetched/, tagged with
    `front`. Returns a result dict consumed by cmd_fetch for aggregation."""
    cfg = _load_fetch_cfg(front)
    rows = list(csv.reader(csv_path.open(newline="", encoding="utf-8-sig")))
    hdr_i = cfg.get("header_row")
    if hdr_i is None:  # find the first row that looks like a header (id + status)
        for i, r in enumerate(rows[:10]):
            probe = _resolve_cols(r, cfg)
            if "id" in probe and "status" in probe:
                hdr_i = i
                break
    if hdr_i is None:
        sys.exit(f"could not find a header row (id + status) in {csv_path.name} "
                 f"(front={front}). Set columns in {FETCH_CONFIG}.")
    header = rows[hdr_i]
    cols = _resolve_cols(header, cfg)
    if "id" not in cols or "status" not in cols:
        sys.exit(f"missing id/status column in {csv_path.name} (front={front}). "
                 f"Header was: {header}\nSet *_col in {FETCH_CONFIG}.")
    ready = {v.lower() for v in cfg.get("ready_values", DEFAULT_READY)}
    use_gdown = cfg.get("use_gdown", True)

    ready_tasks, downloaded, manual, checklist, nolink = [], [], [], [], []
    for r in rows[hdr_i + 1:]:
        if cols["id"] >= len(r) or cols["status"] >= len(r):
            continue
        status = str(r[cols["status"]]).strip().lower()
        tid = str(r[cols["id"]]).strip()
        if not tid or status not in ready:
            continue
        if tid in exclude:
            continue
        link = str(r[cols["link"]]).strip() if "link" in cols and cols["link"] < len(r) else ""
        if not link.lower().startswith("http"):
            nolink.append(tid)  # no per-row link; download by Task <id> from master Tasks folder
        ready_tasks.append(tid)
        tdir = fetched_dir / re.sub(r"[^A-Za-z0-9._-]", "_", tid)
        tdir.mkdir(exist_ok=True)
        (tdir / "_source.txt").write_text(f"task_id: {tid}\nfront: {front}\nstatus: {status}\ndrive_link: {link}\n")
        # lossless: keep the full tracker row so inline prompt/rubric + other links survive
        row_obj = {header[j]: (r[j] if j < len(r) else "") for j in range(len(header)) if header[j]}
        row_obj["front"] = front
        (tdir / "_row.json").write_text(json.dumps(row_obj, ensure_ascii=False, indent=2))
        sol = next((v for k, v in row_obj.items()
                    if "solution" in k.lower() and "link" in k.lower()), "")
        checklist.append((tid, status, link, sol, tdir.name))
        pulled = False
        if use_gdown and link and "drive.google" in link:
            try:
                rc = subprocess.call([str(VENV_PY), "-m", "gdown", "--folder", "-q",
                                      "-O", str(tdir), link],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                pulled = rc == 0 and any(p.name != "_source.txt" for p in tdir.iterdir())
            except Exception:
                pulled = False
        (downloaded if pulled else manual).append(tid)

    return {"front": front, "csv_name": csv_path.name, "hdr_i": hdr_i, "cols": cols,
            "ready_tasks": ready_tasks, "downloaded": downloaded, "manual": manual,
            "checklist": checklist, "nolink": nolink}


def cmd_fetch(args) -> None:
    c = _cycle(args.date)
    front_arg = getattr(args, "front", None)
    trackers = _discover_trackers(c, front_arg)
    if not trackers:
        print(f"[manual] Export a tracker's 'ready for eval' tab as CSV and save it to one of:")
        print(f"  {c/'tracker.csv'}  (single front, defaults to ekw)")
        for front in KNOWN_FRONTS:
            print(f"  {c / f'tracker_{front}.csv'}")
        print(f"Then re-run: python3 pipeline/cycle.py fetch {args.date}")
        return

    exclude = set()
    exf = c / "_exclude.txt"
    if exf.exists():
        exclude = {ln.strip() for ln in exf.read_text().splitlines()
                   if ln.strip() and not ln.startswith("#")}

    fetched_dir = c / "00_fetched"
    fetched_dir.mkdir(exist_ok=True)
    results = [_fetch_one_tracker(c, csv_path, front, exclude, fetched_dir)
               for csv_path, front in trackers]

    total_checklist = sum(len(res["checklist"]) for res in results)
    cl = [f"# Tasks to fetch — {args.date}  ({total_checklist} ready across {len(results)} tracker(s))\n",
          f"For each task: download its **Source documents** and **Expert solution** from Drive "
          f"into the local folder shown, then run `python3 pipeline/cycle.py check {args.date}`.\n"]
    for res in results:
        if not res["checklist"]:
            continue
        cl.append(f"## front: {res['front']}  ({res['csv_name']})\n")
        for tid, st, src, sol, folder in res["checklist"]:
            cl.append(f"- [ ] **{tid}**  ({st})  -> drop files into `00_fetched/{folder}/`")
            if src.lower().startswith("http"):
                cl.append(f"    - source docs: {src}")
                if sol.lower().startswith("http"):
                    cl.append(f"    - expert solution: {sol}")
            else:
                cl.append(f"    - (no per-row link — download `Task {tid}` from the master 'Tasks' Drive folder)")
    (c / "_TO_FETCH.md").write_text("\n".join(cl) + "\n")

    for res in results:
        print(f"tracker: {res['csv_name']} front={res['front']} (header row {res['hdr_i']})  cols={res['cols']}")
        print(f"  ready-for-eval tasks: {len(res['ready_tasks'])}")
        if res["nolink"]:
            print(f"  note: {len(res['nolink'])} ready task(s) have no per-row link — download by Task <id> from the master 'Tasks' folder: " + ", ".join(res["nolink"]))
        if res["downloaded"]:
            print(f"  downloaded via gdown: {len(res['downloaded'])}")
        if res["manual"]:
            print(f"  need manual file pull ({len(res['manual'])}): see each 00_fetched/<id>/_source.txt")
    print(f"checklist -> {c / '_TO_FETCH.md'}")
    if exclude:
        print(f"excluded {len(exclude)} task(s) via _exclude.txt: " + ", ".join(sorted(exclude)))
    print(f"Then: python3 pipeline/cycle.py diff {args.date}")


DOCKERFILE_TEMPLATE = """# EKW task - Python environment with data analysis + document skills

FROM alpine/git:2.45.2 AS skills

ARG ANTHROPIC_SKILLS_REF=da20c92503b2e8ff1cf28ca81a0df4673debdbf7

RUN git clone --filter=blob:none --no-checkout https://github.com/anthropics/skills.git /tmp/anthropic-skills \\
    && cd /tmp/anthropic-skills \\
    && git sparse-checkout init --cone \\
    && git sparse-checkout set skills/xlsx skills/pdf skills/docx \\
    && git -c advice.detachedHead=false checkout "${ANTHROPIC_SKILLS_REF}" \\
    && mkdir -p /harbor/skills \\
    && cp -a skills/xlsx /harbor/skills/xlsx \\
    && cp -a skills/pdf /harbor/skills/pdf \\
    && cp -a skills/docx /harbor/skills/docx

FROM python:3.11-slim
WORKDIR /workspace
RUN apt-get update && apt-get install -y --no-install-recommends \\
    libreoffice poppler-utils && rm -rf /var/lib/apt/lists/*
COPY --from=skills /harbor/skills /harbor/skills
RUN chmod -R a+rX /harbor/skills
RUN pip install --no-cache-dir \\
    numpy==2.3.3 pandas==2.3.3 matplotlib==3.10.7 pypdf==6.7.0 openpyxl \\
    pdfplumber pdf2image pillow defusedxml lxml python-docx pytest pyyaml
COPY data/ /workspace/data/
"""


# Generic Harbor verifier runtime shipped verbatim in every task's tests/ dir
# (test.sh entrypoint + verifier_runtime.py + verifier_lib/). Only verifier.json
# varies per task; these are task-agnostic. Kept as a canonical template so a
# harbor upload validator finds tests/test.sh and a runnable test harness.
HARBOR_TEMPLATE = PIPELINE / "templates" / "harbor"


def _deliverables(vobj: dict | None, golden_dir: Path) -> list[str]:
    """The files solve.sh must reproduce in /workspace/output/.

    A deliverable is a golden file the verifier actually reads back as an
    ``output/<name>`` source path. This deliberately excludes expert-only
    artifacts like ``Reasoning.docx`` that are present in golden_outputs but
    never graded — copying those into output/ would be an unsolicited
    side-effect a side-effect-aware verifier can penalize. Falls back to every
    golden file except Reasoning.docx when no verifier paths are resolvable.
    """
    present = {f.name for f in golden_dir.iterdir() if f.is_file()}
    wanted: set[str] = set()
    if isinstance(vobj, dict):
        for v in vobj.get("verifiers", []) or []:
            fsrc = (v.get("source") or {}).get("file") or {}
            # source.file may be a single dict or a list of file-sources
            # (multi-file verifiers grading across several deliverables)
            for src in (fsrc if isinstance(fsrc, list) else [fsrc]):
                if not isinstance(src, dict):
                    continue
                p = ((src.get("arguments") or {}).get("path") or "")
                base = os.path.basename(p)
                if p.startswith("output/") and base in present:
                    wanted.add(base)
    if not wanted:
        wanted = {n for n in present if n.lower() != "reasoning.docx"}
    return sorted(wanted)


def _solve_sh(deliverables: list[str]) -> str:
    """Oracle solver: copies the graded golden deliverables into output/.

    Deliverables are held in a quoted bash array so filenames containing spaces
    (e.g. ``Output 1 - Task-8.docx``) survive iteration intact.
    """
    files = "".join(f'  "{d}"\n' for d in deliverables)
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        'WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"\n'
        'OUTPUT_DIR="$WORKSPACE_DIR/output"\n'
        'SOLUTION_DIR="${SOLUTION_DIR:-/solution}"\n'
        'GOLDEN_DIR="$SOLUTION_DIR/golden_outputs"\n\n'
        'mkdir -p "$OUTPUT_DIR"\n\n'
        'if [ ! -d "$GOLDEN_DIR" ]; then\n'
        '  echo "Missing golden outputs directory: $GOLDEN_DIR" >&2\n'
        "  exit 1\n"
        "fi\n\n"
        f"required_files=(\n{files})\n"
        'for required_file in "${required_files[@]}"; do\n'
        '  if [ ! -f "$GOLDEN_DIR/$required_file" ]; then\n'
        '    echo "Missing golden output: $GOLDEN_DIR/$required_file" >&2\n'
        "    exit 1\n"
        "  fi\n"
        '  cp -p "$GOLDEN_DIR/$required_file" "$OUTPUT_DIR/$required_file"\n'
        "done\n"
    )


def _install_harbor_runtime(tdir: Path) -> None:
    """Copy the generic test.sh + verifier_runtime.py + verifier_lib/ into tests/."""
    tests = tdir / "tests"
    shutil.copy2(HARBOR_TEMPLATE / "test.sh", tests / "test.sh")
    shutil.copy2(HARBOR_TEMPLATE / "verifier_runtime.py", tests / "verifier_runtime.py")
    dst_lib = tests / "verifier_lib"
    if dst_lib.exists():
        shutil.rmtree(dst_lib)
    shutil.copytree(HARBOR_TEMPLATE / "verifier_lib", dst_lib,
                    ignore=shutil.ignore_patterns("__pycache__"))
    os.chmod(tests / "test.sh", 0o755)
    os.chmod(tests / "verifier_runtime.py", 0o755)


def _task_toml(tid: str, row: dict) -> str:
    def esc(v):
        return str(v or "").replace('"', "'").strip()
    return (
        'version = "1.0"\nartifacts = ["/workspace/output"]\n\n'
        "[verifier]\ntimeout_sec = 3600.0\n\n"
        '[verifier.env]\nOPENAI_API_KEY = "${OPENAI_API_KEY}"\n\n'
        "[agent]\ntimeout_sec = 14400.0\n\n"
        "[environment]\nbuild_timeout_sec = 900.0\nmemory_mb = 4096\n"
        "storage_mb = 10240\nallow_internet = true\nskills_dir = \"/harbor/skills\"\n\n"
        "[metadata]\n"
        f'task_id = "task_{tid}"\n'
        f'category = "{esc(row.get("Sector"))}"\n'
        f'subdomain = "{esc(row.get("Subdomain"))}"\n'
        f'task_type = "{esc(row.get("Task Type"))}"\n'
        'difficulty = ""\ntags = []\n'
    )


def _subdir(task_dir: Path, *keywords: str) -> Path | None:
    for d in task_dir.iterdir():
        if d.is_dir() and any(k in d.name.lower() for k in keywords):
            return d
    return None


def _verifier_weight(v: dict):
    """Weight lives either at the verifier root or nested under metadata."""
    w = v.get("weight")
    if w is None:
        w = (v.get("metadata") or {}).get("weight")
    try:
        return float(w)
    except (TypeError, ValueError):
        return None


def _verifier_sanity(obj: dict):
    """Objective QC checks on a parsed verifier.json. Yields (level, category, detail)."""
    vs = obj.get("verifiers")
    if not isinstance(vs, list):
        yield ("ERROR", "verifier-shape", "no top-level 'verifiers' array")
        return
    n = len(vs)
    # Minimum-only: no upper limit on verifier count (a thorough rubric with many
    # checks is not a defect). Minimum aligns with the spec's verifier_count_in_range.
    if n < 6:
        yield ("WARN", "verifier-count",
               f"only {n} verifiers; project minimum is 6")
    # weight sum must equal 1.0
    ws = [_verifier_weight(v) for v in vs]
    if any(w is None for w in ws):
        missing = [v.get("name", f"#{i}") for i, (v, w) in enumerate(zip(vs, ws)) if w is None]
        yield ("WARN", "verifier-weight-missing",
               f"{len(missing)} verifier(s) lack a numeric weight: {', '.join(missing)}")
    else:
        total = round(sum(ws), 4)
        if abs(total - 1.0) > 0.001:
            yield ("WARN", "verifier-weight-sum",
                   f"weights sum to {total}, expected 1.0")
    # sequential-name numbering gaps (v1, v2, ...)
    nums = []
    for v in vs:
        nm = str(v.get("name", ""))
        if nm.startswith("v") and nm[1:].isdigit():
            nums.append(int(nm[1:]))
    if nums:
        gaps = sorted(set(range(min(nums), max(nums) + 1)) - set(nums))
        if gaps:
            yield ("INFO", "verifier-numbering-gap",
                   f"verifier names skip {', '.join('v'+str(g) for g in gaps)} "
                   f"(present: v{min(nums)}..v{max(nums)}, count {len(nums)})")
    # outcome mean weight should be >= process mean weight
    def role(v):
        return (v.get("grading_role") or (v.get("metadata") or {}).get("grading_role") or "").lower()
    out_w = [w for v, w in zip(vs, ws) if w is not None and role(v) == "outcome"]
    proc_w = [w for v, w in zip(vs, ws) if w is not None and role(v) == "process"]
    if out_w and proc_w:
        mo, mp = sum(out_w) / len(out_w), sum(proc_w) / len(proc_w)
        if mo < mp - 1e-9:
            yield ("WARN", "verifier-role-balance",
                   f"mean outcome weight {round(mo,4)} < mean process weight {round(mp,4)}")


_LEVEL_RANK = {"ERROR": 0, "WARN": 1, "INFO": 2}


def _write_incident_report(path: Path, date: str, out: Path,
                           assembled: list, no_files: list, incidents: list) -> None:
    """Write a shareable markdown report of all intercurrences for this bundle run."""
    by_level = {"ERROR": [], "WARN": [], "INFO": []}
    for tid, level, cat, detail in incidents:
        by_level.setdefault(level, []).append((tid, cat, detail))
    lines = [
        f"# Pipeline run report — cycle {date}",
        "",
        "_Auto-generated by `cycle.py bundle`. Lists every intercurrence (data or rubric",
        "issue) detected while assembling harbor tasks, for hand-off to the experts team._",
        "",
        "## Summary",
        "",
        f"- Bundle output: `{out.name}/`",
        f"- Tasks assembled (with `verifier.json`): **{len(assembled)}**",
        f"- Tasks skipped (no source files): **{len(no_files)}**",
        f"- Incidents: **{len(incidents)}** "
        f"({len(by_level['ERROR'])} error / {len(by_level['WARN'])} warn / {len(by_level['INFO'])} info)",
        "",
    ]
    if not incidents:
        lines += ["No intercurrences detected. ✅", ""]
    for level in ("ERROR", "WARN", "INFO"):
        rows = by_level[level]
        if not rows:
            continue
        icon = {"ERROR": "🔴", "WARN": "🟡", "INFO": "🔵"}[level]
        lines += [f"## {icon} {level} ({len(rows)})", "", "| Task | Category | Detail |",
                  "|------|----------|--------|"]
        for tid, cat, detail in sorted(rows, key=lambda r: (r[1], int(r[0]) if r[0].isdigit() else 0)):
            lines.append(f"| task_{tid} | `{cat}` | {detail.replace('|', chr(92)+'|')} |")
        lines.append("")
    if no_files:
        lines += ["## Not downloaded (skipped entirely)", "",
                  ", ".join(f"task_{t}" for t in no_files), ""]
    path.write_text("\n".join(lines))


def cmd_bundle(args) -> None:
    """Assemble harbor-format tasks from 00_fetched/<id>/ and report all intercurrences.

    --only 97,160   restrict to specific task ids (comma-separated)
    --out NAME       output subdir under the cycle (default 02_bundle)
    """
    c = _cycle(args.date)
    only = {t.strip() for t in (args.only or "").split(",") if t.strip()}
    out_name = getattr(args, "out", None) or "02_bundle"
    fetched, out = c / "00_fetched", c / out_name
    out.mkdir(exist_ok=True)
    exclude = set()
    exf = c / "_exclude.txt"
    if exf.exists():
        exclude = {ln.strip() for ln in exf.read_text().splitlines()
                   if ln.strip() and not ln.startswith("#")}
    assembled, no_files = [], []
    tid_fronts: dict[str, str] = {}
    incidents = []  # (tid, level, category, detail)
    # Task ids aren't always numeric once non-EKW fronts are in the mix (SVC's
    # "cirrus-y1-task-05", for instance) — accept any fetched dir, not just
    # digit-named ones, and sort as plain strings.
    for d in sorted((p for p in fetched.iterdir() if p.is_dir()), key=lambda p: p.name):
        tid = d.name
        if tid in exclude or (only and tid not in only):
            continue
        rj = d / "_row.json"
        row = json.loads(rj.read_text()) if rj.exists() else {}
        front = row.get("front", "ekw")
        tid_fronts[tid] = front

        # SVC tasks arrive pre-bundled (see SOP 1.7 — a decomposition-DAG corpus
        # built outside this pipeline, not raw source+solution files we assemble
        # from scratch). If fetch already dropped a complete harbor-shaped task
        # here, register it verbatim instead of running the EKW assembly path
        # below, which expects "source"/"solution" subfolders + a Prompt/Rubric
        # tracker cell neither of which a pre-bundled SVC task has.
        if front == "svc":
            has_verifier = (d / "tests" / "verifier.json").is_file() or (d / "tests" / "rubric.json").is_file()
            if (d / "instruction.md").is_file() and (d / "task.toml").is_file() and has_verifier:
                tdir = out / f"task_{tid}"
                if tdir.exists():
                    shutil.rmtree(tdir)
                shutil.copytree(d, tdir, ignore=shutil.ignore_patterns("_source.txt", "_row.json"))
                assembled.append(tid)
                incidents.append((tid, "INFO", "svc-prebundled",
                                  "SVC task arrived pre-bundled; registered into 02_bundle/ verbatim, "
                                  "no harbor assembly run"))
                continue
            incidents.append((tid, "ERROR", "svc-not-prebundled",
                              "front=svc but 00_fetched/<id>/ isn't a complete harbor-shaped task "
                              "(missing instruction.md/task.toml/tests/{verifier,rubric}.json) — "
                              "SVC tasks are expected pre-bundled; cmd_bundle has no from-scratch "
                              "assembly path for SVC's DAG/rubric.json shape"))
            no_files.append(tid)
            continue

        src = _subdir(d, "source")
        sol = _subdir(d, "solution", "expert")
        if not src or not any(src.iterdir()):
            no_files.append(tid)
            incidents.append((tid, "ERROR", "no-source-files",
                              "no source documents downloaded; task skipped entirely"))
            continue
        tdir = out / f"task_{tid}"
        if tdir.exists():
            shutil.rmtree(tdir)
        (tdir / "environment" / "data").mkdir(parents=True)
        (tdir / "solution" / "golden_outputs").mkdir(parents=True)
        (tdir / "tests").mkdir()
        # instruction.md
        (tdir / "instruction.md").write_text(str(row.get("Prompt", "")))
        # environment
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(f, tdir / "environment" / "data" / f.name)
        (tdir / "environment" / "Dockerfile").write_text(DOCKERFILE_TEMPLATE)
        # solution
        if sol and any(f.is_file() for f in sol.iterdir()):
            for f in sol.iterdir():
                if f.is_file():
                    shutil.copy2(f, tdir / "solution" / "golden_outputs" / f.name)
        else:
            incidents.append((tid, "WARN", "no-solution",
                              "no expert/golden solution files found"))
        # task.toml
        (tdir / "task.toml").write_text(_task_toml(tid, row))
        # verifier.json: prefer a shipped (possibly hand-repaired) file, else parse the Rubric cell
        vfile = d / "verifier.json"
        rub = (row.get("Rubric JSON") or row.get("Rubric") or "").strip()
        wrote_v, vobj = False, None
        if vfile.exists():
            try:
                vobj = json.loads(vfile.read_text())
                shutil.copy2(vfile, tdir / "tests" / "verifier.json")
                wrote_v = True
                incidents.append((tid, "INFO", "verifier-shipped",
                                  "used shipped verifier.json from 00_fetched/ "
                                  "(hand-repaired or externally supplied rubric)"))
            except Exception as e:
                incidents.append((tid, "ERROR", "verifier-shipped-bad",
                                  f"shipped verifier.json is invalid JSON: {e}"))
        elif rub:
            try:
                vobj = json.loads(rub)  # already valid
                (tdir / "tests" / "verifier.json").write_text(rub)
                wrote_v = True
            except Exception:
                # tolerate a single valid JSON value followed by trailing junk
                # (e.g. a stray "</verifier>" wrapper tag pasted into the cell)
                try:
                    vobj, _ = json.JSONDecoder().raw_decode(rub)
                    (tdir / "tests" / "verifier.json").write_text(
                        json.dumps(vobj, indent=2, ensure_ascii=False))
                    wrote_v = True
                    incidents.append((tid, "WARN", "rubric-recovered",
                                      "Rubric cell had trailing junk after valid JSON "
                                      "(e.g. stray </verifier> tag); auto-recovered via raw_decode"))
                except Exception as e:
                    incidents.append((tid, "ERROR", "rubric-malformed",
                                      f"Rubric cell is malformed JSON, not auto-recoverable ({e}); "
                                      f"hand-repair and drop verifier.json in 00_fetched/{tid}/"))
        else:
            incidents.append((tid, "ERROR", "rubric-empty",
                              "Rubric cell is empty in the tracker; no verifier.json produced"))
        if wrote_v:
            assembled.append(tid)
            if isinstance(vobj, dict):
                for level, cat, detail in _verifier_sanity(vobj):
                    incidents.append((tid, level, cat, detail))
        # harbor runtime: generic test.sh + verifier_runtime.py + verifier_lib/,
        # and a per-task solve.sh oracle. Shipped for every assembled task so a
        # strict harbor upload validator finds a runnable tests/ and solution/.
        _install_harbor_runtime(tdir)
        golden = tdir / "solution" / "golden_outputs"
        deliverables = _deliverables(vobj, golden) if any(golden.iterdir()) else []
        if deliverables:
            solve = tdir / "solution" / "solve.sh"
            solve.write_text(_solve_sh(deliverables))
            os.chmod(solve, 0o755)
        else:
            incidents.append((tid, "WARN", "no-solve-sh",
                              "no golden deliverables resolved; solution/solve.sh not written"))
    report = out / "_INCIDENTS.md"
    _write_incident_report(report, args.date, out, assembled, no_files, incidents)
    print(f"assembled {len(assembled)} harbor tasks -> {out}")
    errs = [i for i in incidents if i[1] == "ERROR"]
    warns = [i for i in incidents if i[1] == "WARN"]
    if errs:
        print(f"  {len(errs)} ERROR incident(s): "
              + ", ".join(f"task_{t}:{cat}" for t, _, cat, _ in errs))
    if warns:
        print(f"  {len(warns)} WARN incident(s): "
              + ", ".join(f"task_{t}:{cat}" for t, _, cat, _ in warns))
    print(f"  intercurrence report -> {report}")

    # Dual bundle: also produce the Data-OS reward-kit conversion in the same
    # step, instead of requiring a separate `cycle.py dataos` call later —
    # a task assembled here is ready for both harbor eval and Data-OS upload.
    # PROFILE_BY_FRONT maps a fetched task's tracked front to the one-pager/
    # Slack boilerplate profile dataos_submission.py already supports; a batch
    # mixing fronts falls back to "ekw" (approximation, noted below) since
    # the one-pager is drafted once per bundle run, not once per front.
    dataos_out = c / "dataos"
    conversion_ok = False
    if assembled and VENV_PY.exists():
        PROFILE_BY_FRONT = {"ekw": "ekw", "intake": "ekw", "svc": "ekw"}  # no svc profile yet
        fronts_present = {tid_fronts.get(tid, "ekw") for tid in assembled}
        profile = PROFILE_BY_FRONT.get(next(iter(fronts_present)), "ekw") if len(fronts_present) == 1 else "ekw"
        if len(fronts_present) > 1:
            print(f"  note: bundle mixes fronts ({', '.join(sorted(fronts_present))}) — "
                  f"dataos one-pager profile defaults to 'ekw'")
        parts = Path(args.date).parts
        track = parts[0] if len(parts) > 1 else "batch"
        name = f"ekw_{track}".replace("-", "_")
        rc = _run_dataos_convert(out, dataos_out, name, prefix="ekw", profile=profile,
                                  contact="Luiz Araujo <luiz.araujo@turing.com>", deadline="",
                                  only=args.only, missing_hint="bundle produced no assembled tasks")
        conversion_ok = rc == 0
        if not conversion_ok:
            print("  WARN: dataos reward-kit conversion exited non-zero — see output above")
    elif assembled:
        print("  skipped dataos reward-kit conversion: pipeline venv missing at " + str(VENV_PY))

    if conversion_ok:
        print(f"Next (Step D, manual): create/reuse a Data-OS dataset and upload every task under "
              f"{dataos_out / 'rewardkit'} into it — ignore SUBMISSION.md's own checklist for now, "
              f"that's the later Phase 2/Turing hand-off, not this step. Once every task shows "
              f"\"Ready\", run the full automated eval + trajectory-verification pass (Step E — see "
              f"the dataos-qc-run skill), then python3 pipeline/cycle.py dataos-evals-import "
              f"{args.date} <dataos_qc_runs_dir> (Step F).")
    elif assembled:
        print(f"Next: fix the dataos reward-kit conversion above, then re-run "
              f"python3 pipeline/cycle.py bundle {args.date} before proceeding to Step D.")
    else:
        print(f"No tasks assembled — check the incident report above before proceeding.")


def _run_dataos_convert(bundle: Path, out: Path, name: str, prefix: str,
                         profile: str, contact: str, deadline: str, only: str,
                         missing_hint: str) -> int:
    if not bundle.is_dir() or not any(bundle.iterdir()):
        sys.exit(f"no such bundle directory (or empty): {bundle} — {missing_hint}")
    if not VENV_PY.exists():
        sys.exit(f"pipeline venv missing at {VENV_PY}")
    script = PIPELINE / "tools" / "dataos_submission.py"
    cmd = [str(VENV_PY), str(script), str(bundle), str(out), name,
           "--prefix", prefix, "--contact", contact, "--profile", profile]
    if deadline:
        cmd += ["--deadline", deadline]
    if only:
        cmd += ["--only", only]
    print("running:", " ".join(cmd))
    rc = subprocess.call(cmd)
    if rc == 0:
        print(f"Data-OS submission package ready -> {out}")
        print("Manual next steps (Turing QC Request Procedure) — see "
              f"{out / 'SUBMISSION.md'} for the full checklist.")
    return rc


def cmd_dataos(args) -> None:
    """Prepare a Data-OS QC submission package from a bundled cycle.

    This is the entry step for the Turing internal QC track (the "Turing QC
    Request Procedure for Internal Clients") — it replaces the old local
    20%%/redflag QC as the starting point for that track. It reward-kit-
    converts every bundled task, then drafts the one-page dataset description
    and the #TFRL_QC Slack message that the procedure requires. Everything
    after that (Data-OS upload, Data-OS testing, oracle passes, freezing the
    dataset, and posting to Slack) is manual — see cycles/<date>/dataos/SUBMISSION.md.

    cycle.py dataos <date> [--bundle-dir 02_bundle] [--only 97,160]
                           [--name NAME] [--prefix ekw] [--contact "..."] [--deadline DD/MM/YYYY]
    """
    c = _cycle(args.date)
    bundle = c / args.bundle_dir
    out = c / "dataos"
    if args.name:
        name = args.name
    else:
        parts = Path(args.date).parts
        track = parts[0] if len(parts) > 1 else "batch"
        name = f"ekw_{track}".replace("-", "_")
    sys.exit(_run_dataos_convert(bundle, out, name, args.prefix, args.profile,
                                  args.contact, args.deadline, args.only,
                                  missing_hint="run bundle first"))


def cmd_dataos_standalone(args) -> None:
    """Same conversion as `dataos`, but for a bundle that isn't inside a cycle
    folder — e.g. one QC phase is handed a standalone bundled harbor task (or a
    directory of them) by someone else, and building out a full cycles/<date>/
    tree just to run this one step would be redundant.

    cycle.py dataos-standalone <bundle_dir> <out_dir> [--only 97,160]
                                [--name NAME] [--prefix ekw] [--contact "..."] [--deadline DD/MM/YYYY]
    """
    bundle = Path(args.bundle_dir)
    out = Path(args.out_dir)
    name = args.name or bundle.name.replace("-", "_") or "batch"
    sys.exit(_run_dataos_convert(bundle, out, name, args.prefix, args.profile,
                                  args.contact, args.deadline, args.only,
                                  missing_hint="pass the harbor-bundled task dir(s)"))


DATAOS_EVALS_IMPORT_SCRIPT = PIPELINE / "tools" / "dataos_evals_import.py"


def cmd_dataos_evals_import(args) -> None:
    """Import a Data-OS QC-run drop (the `dataos-qc-run` skill's downloaded
    evals.zip + verifications_results.json per task) into the 03_evals/ shape
    Internal QC's engine already reads -- so the same automated-eval artifacts
    that feed External QC's trajectory-verification pass also ground Internal
    QC's own eval-dependent verifier-quality dims, instead of a separate local
    k=1 trial run.

    cycle.py dataos-evals-import <date> <dataos_qc_runs_dir> [--bundle-dir 02_bundle] [--only ids]
    """
    c = _cycle(args.date)
    bundle = c / args.bundle_dir
    evals_out = c / "03_evals"
    runs_dir = Path(args.dataos_qc_runs_dir)
    if not bundle.is_dir() or not any(bundle.iterdir()):
        sys.exit(f"no {args.bundle_dir} in {c} — run bundle first")
    if not runs_dir.is_dir():
        sys.exit(f"dataos_qc_runs_dir not found: {runs_dir}")
    if not VENV_PY.exists():
        sys.exit(f"pipeline venv missing at {VENV_PY}")
    cmd = [str(VENV_PY), str(DATAOS_EVALS_IMPORT_SCRIPT), str(runs_dir), str(bundle), str(evals_out)]
    if args.only:
        cmd += ["--only", args.only]
    print("running:", " ".join(cmd))
    rc = subprocess.call(cmd)
    if rc == 0:
        print(f"next: python3 pipeline/cycle.py qc {args.date}")
    sys.exit(rc)


def _merge_move(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in list(src.iterdir()):
        target = dst / item.name
        if item.is_dir():
            _merge_move(item, target)
        elif not target.exists():
            shutil.move(str(item), str(target))
    try:
        src.rmdir()
    except OSError:
        pass


def cmd_normalize(args) -> None:
    """Flatten bulk-downloaded 'Task NNN' folders (any depth, any case) into
    00_fetched/<id>/, then drop emptied wrapper dirs (e.g. drive-download-*)."""
    c = _cycle(args.date)
    fetched = c / "00_fetched"
    pat = re.compile(r"^task\s*0*(\d+)$", re.I)
    cands = [d for d in fetched.rglob("*") if d.is_dir() and pat.match(d.name.strip())]
    moved = []
    for d in sorted(cands, key=lambda p: len(p.parts), reverse=True):
        tid = pat.match(d.name.strip()).group(1)
        dst = fetched / tid
        if d.resolve() == dst.resolve():
            continue
        _merge_move(d, dst)
        moved.append((d.name, tid))
    # remove now-empty non-id wrapper dirs (e.g. drive-download-*)
    for d in [p for p in fetched.iterdir() if p.is_dir() and not p.name.isdigit()]:
        if not any(d.rglob("*")):
            d.rmdir()
    print(f"normalized {len(moved)} folders -> 00_fetched/<id>/")
    for src, tid in sorted(moved, key=lambda x: int(x[1])):
        print(f"  {src!r} -> {tid}")
    print(f"next: python3 pipeline/cycle.py fetch {args.date}  (restores stubs), then check")


def cmd_check(args) -> None:
    """Verify every ready task folder now has downloaded files (not just stubs)."""
    c = _cycle(args.date)
    fetched = c / "00_fetched"
    if not fetched.is_dir():
        sys.exit(f"no 00_fetched in {c} — run fetch first")
    stubs = {"_source.txt", "_row.json"}
    done, missing = [], []
    for d in sorted(p for p in fetched.iterdir() if p.is_dir()):
        files = [f for f in d.rglob("*") if f.is_file() and f.name not in stubs]
        (done if files else missing).append((d.name, len(files)))
    total = len(done) + len(missing)
    print(f"downloaded: {len(done)}/{total} task folders have files")
    if missing:
        print(f"still empty ({len(missing)}): " + ", ".join(m[0] for m in missing))
        print("download the rest (see _TO_FETCH.md), then re-run check.")
        sys.exit(1)
    print(f"all {total} tasks downloaded. next: python3 pipeline/cycle.py diff {args.date}")


_EVAL_ID_RE = re.compile(r"task[_-]?(\d+)$")


def cmd_evals(args) -> None:
    """Merge returned eval trials into their bundled task packages -> 03_evals/.

    Each 03_evals/task_<id>/ = the authoritative task definition (from 02_bundle:
    task.toml, instruction.md, environment/, solution/, tests/) with the returned
    eval trials copied under evals/. The v18 QC pipeline reads the task definition
    and ignores evals/, but merging keeps 03_evals a complete, archival corpus.

    cycle.py evals <date> [src]   src = eval drop dir (default: the cycle's b0630/
                                  or any single non-stage dir); relative to the cycle.
    """
    c = _cycle(args.date)
    bundle, evals_out = c / "02_bundle", c / "03_evals"
    if not bundle.is_dir():
        sys.exit(f"no 02_bundle in {c} — run bundle first")
    # locate the eval drop
    if args.src:
        src = Path(args.src)
        if not src.is_absolute():
            src = c / args.src
    else:
        stages = {"00_fetched", "01_diff", "02_bundle", "02_bundle_fixed",
                  "03_evals", "04_qc", "05_report"}
        cands = [p for p in c.iterdir()
                 if p.is_dir() and p.name not in stages and not p.name.startswith(".")]
        if len(cands) != 1:
            sys.exit(f"specify the eval drop dir; candidates in {c}: "
                     + ", ".join(p.name for p in cands))
        src = cands[0]
    if not src.is_dir():
        sys.exit(f"eval drop dir not found: {src}")
    evals_out.mkdir(exist_ok=True)
    merged, no_task, no_report = [], [], []
    for d in sorted(p for p in src.iterdir() if p.is_dir()):
        m = _EVAL_ID_RE.search(d.name)
        if not m:
            continue
        tid = m.group(1)
        task_src = bundle / f"task_{tid}"
        if not task_src.is_dir():
            no_task.append(tid)
            continue
        dst = evals_out / f"task_{tid}"
        if dst.exists():
            shutil.rmtree(dst)
        # authoritative task definition from the bundle
        shutil.copytree(task_src, dst)
        # Returned eval trials, flattened to evals/<model>/<trial>/ — the layout
        # build_verifier_assertion_summary() walks (it then recursive-globs each
        # trial for verifier/verifier-report.json). The raw drop nests trials as
        # <task>/v*/execution_*/<model>/trial_*/… so we lift each trial_* dir up
        # under its model-named parent.
        n_trials = 0
        for trial in sorted(d.rglob("trial_*")):
            if not trial.is_dir() or trial.parent.name == trial.name:
                continue
            model = trial.parent.name          # e.g. google__gemini-3.5-flash
            if "__" not in model:               # not a model dir; skip stray matches
                continue
            label = trial.name
            tgt = dst / "evals" / model / label
            i = 2
            while tgt.exists():                 # namespace collisions across executions
                tgt = dst / "evals" / model / f"{label}_{i}"; i += 1
            shutil.copytree(trial, tgt)
            n_trials += 1
        if n_trials == 0 or not any((dst / "evals").rglob("verifier-report.json")):
            no_report.append(tid)
        merged.append(tid)
    print(f"merged {len(merged)} task packages -> {evals_out}")
    if no_task:
        print(f"  WARN: {len(no_task)} eval dir(s) had no matching 02_bundle/task_<id>: "
              + ", ".join(no_task))
    if no_report:
        print(f"  WARN: {len(no_report)} merged task(s) have no verifier-report.json in any trial: "
              + ", ".join(no_report))
    print(f"next: python3 pipeline/cycle.py qc {args.date}")


HARBOR_EVALS_SCRIPT = PIPELINE / "tools" / "harbor_evals.py"


def cmd_evals_package(args) -> None:
    """Package 02_bundle/ tasks for a Harbor-beta eval request (strips solution/,
    applies the guide's sanitization checklist as hard gates).

    cycle.py evals-package <date> --batch-prefix PREFIX [--only ids]
    """
    c = _cycle(args.date)
    bundle = c / args.bundle_dir
    out = c / "03_evals_package"
    if not bundle.is_dir() or not any(bundle.iterdir()):
        sys.exit(f"no {args.bundle_dir} in {c} — run bundle first")
    cmd = [str(VENV_PY), str(HARBOR_EVALS_SCRIPT), "package", str(bundle), str(out),
           "--batch-prefix", args.batch_prefix]
    if args.only:
        cmd += ["--only", args.only]
    print("running:", " ".join(cmd))
    rc = subprocess.call(cmd)
    if rc == 0:
        print(f"packaged -> {out}.  Next: python3 pipeline/cycle.py evals-upload {args.date}")
    sys.exit(rc)


def cmd_evals_upload(args) -> None:
    """Upload a packaged batch to the Harbor-beta GCS bucket and write ready markers.

    cycle.py evals-upload <date> [--project P] [--bucket B] [--yes]
    """
    c = _cycle(args.date)
    package_dir = c / "03_evals_package"
    if not package_dir.is_dir() or not any(package_dir.iterdir()):
        sys.exit(f"no 03_evals_package in {c} — run evals-package first")
    cmd = [str(VENV_PY), str(HARBOR_EVALS_SCRIPT), "upload", str(package_dir),
           "--project", args.project, "--bucket", args.bucket]
    if args.yes:
        cmd += ["--yes"]
    print("running:", " ".join(cmd))
    sys.exit(subprocess.call(cmd))


def cmd_evals_enqueue(args) -> None:
    """Enqueue the Harbor-beta eval — dry-run by default, --live for a real (paid) run.

    cycle.py evals-enqueue <date> --base-url URL --k N --models-file PATH [--live]
    """
    c = _cycle(args.date)
    package_dir = c / "03_evals_package"
    if not package_dir.is_dir() or not any(package_dir.iterdir()):
        sys.exit(f"no 03_evals_package in {c} — run evals-package first")
    cmd = [str(VENV_PY), str(HARBOR_EVALS_SCRIPT), "enqueue", str(package_dir), str(c),
           "--base-url", args.base_url, "--k", str(args.k),
           "--models-file", args.models_file,
           "--project", args.project, "--bucket", args.bucket]
    if args.live:
        cmd += ["--live"]
    print("running:", " ".join(cmd))
    sys.exit(subprocess.call(cmd))


def cmd_evals_status(args) -> None:
    """Poll Harbor-beta for eval completion.

    cycle.py evals-status <date> --batch-prefix PREFIX --expected-trials N [--wait]
    """
    cmd = [str(VENV_PY), str(HARBOR_EVALS_SCRIPT), "status",
           "--batch-prefix", args.batch_prefix, "--expected-trials", str(args.expected_trials),
           "--project", args.project, "--evals-bucket", args.evals_bucket,
           "--poll-seconds", str(args.poll_seconds)]
    if args.wait:
        cmd += ["--wait"]
    print("running:", " ".join(cmd))
    sys.exit(subprocess.call(cmd))


def cmd_evals_fetch(args) -> None:
    """Download finished Harbor-beta trials into the layout `cycle.py evals` expects.

    cycle.py evals-fetch <date> [--project P] [--evals-bucket B]
    """
    c = _cycle(args.date)
    runs_csv = c / "_eval-runs.csv"
    out = c / "03_evals_raw"
    if not runs_csv.is_file():
        sys.exit(f"no _eval-runs.csv in {c} — run evals-enqueue --live first")
    cmd = [str(VENV_PY), str(HARBOR_EVALS_SCRIPT), "fetch", str(runs_csv), str(out),
           "--project", args.project, "--evals-bucket", args.evals_bucket]
    print("running:", " ".join(cmd))
    rc = subprocess.call(cmd)
    if rc == 0:
        print(f"next: python3 pipeline/cycle.py evals {args.date} 03_evals_raw")
    sys.exit(rc)


def cmd_qc(args) -> None:
    c = _cycle(args.date)
    corpus = c / "03_evals"
    outdir = c / "04_qc"
    if not corpus.is_dir() or not any(corpus.iterdir()):
        sys.exit(f"no evals in {corpus} — drop the returned evals there first")
    if not VENV_PY.exists():
        sys.exit(f"pipeline venv missing at {VENV_PY}")
    cmd = [str(VENV_PY), "-m", "gdpval_qc.cli",
           "--spec", str(args.spec), "--corpus", str(corpus), "--output-dir", str(outdir)]
    # Heavy parallelism by default: grade several tasks at once (default 1 in the
    # underlying CLI is far too slow for a full cycle). Only inject when the user
    # hasn't set the flag themselves via `extra`. The API token rate limiters
    # (Gemini 2M tpm, OpenAI 1M tpm/key) throttle gracefully under the load.
    if not any(a.startswith("--sample-parallelism") for a in args.extra):
        cmd += ["--sample-parallelism", str(args.sample_parallelism)]
    if not any(a.startswith("--dim-parallelism") for a in args.extra):
        cmd += ["--dim-parallelism", str(args.dim_parallelism)]
    # Calibration (5 known-verdict goldens) is OPT-IN: it adds a full task's worth
    # of grading + slow multimodal dims to every run, and is only useful as a
    # drift check on the full/final pass. Skip by default; re-enable with
    # --calibrate (or by passing --skip-calibration explicitly to override).
    if not getattr(args, "calibrate", False) and not any(
            a.startswith("--skip-calibration") for a in args.extra):
        cmd += ["--skip-calibration"]
    cmd += args.extra
    print("running:", " ".join(cmd))
    rc = subprocess.call(cmd)
    if rc == 0:
        print(f"QC done -> {outdir}.  Next (Step H): python3 pipeline/cycle.py joint-feedback {args.date}")
    sys.exit(rc)


def cmd_svc_qc(args) -> None:
    """SVC/Cirrus QC entrypoint — no fetch/diff/bundle: SVC tasks arrive pre-bundled
    (no tracker, no Shared Drive step), so this points straight at a corpus directory
    instead of a cycles/<date>/ stage folder.

    Wraps the invocation documented in SVC/RUN_FULL_QC.md against the SVC overlay
    spec (specs/overlays/svc.md by default; pass --spec specs/overlays/svc-noeval.md
    when evals/<model>/trial_*/ isn't populated yet). --no-conversion is the default
    (text-only judging — reliable, no libreoffice dependency; formula-driven xlsx
    sheets may extract as blank, a known false-"unfinished" risk noted in
    RUN_FULL_QC.md — pass --with-conversion to re-check a flagged node).

    Unlike `qc` (which just subprocess.call and leaves logging to whoever invoked
    it — most historical cycles never redirected it), this always tees its own
    run to <out-dir>/_run.log, so every SVC run keeps a timing/audit trail.

    cycle.py svc-qc <corpus> [--only ids] [--out-dir DIR] [--date YYYY-MM-DD]
                     [--spec PATH] [--sample-parallelism N] [--with-conversion]
                     [extra args passed through to gdpval-assess]
    """
    corpus = Path(args.corpus).expanduser().resolve()
    if not corpus.is_dir():
        sys.exit(f"not a directory: {corpus}")
    if not VENV_PY.exists():
        sys.exit(f"pipeline venv missing at {VENV_PY}")

    date = args.date or _today()
    outdir = (Path(args.out_dir).expanduser().resolve() if args.out_dir
              else (BASE / "runs" / f"svc_{date}"))
    outdir.mkdir(parents=True, exist_ok=True)

    cmd = [str(VENV_PY), "-m", "gdpval_qc.cli",
           "--spec", str(args.spec), "--corpus", str(corpus), "--output-dir", str(outdir)]
    if not any(a.startswith("--skip-calibration") for a in args.extra):
        cmd += ["--skip-calibration"]   # the spec's calibration goldens are EKW's, not SVC's
    if not args.with_conversion and not any(a.startswith("--no-conversion") for a in args.extra):
        cmd += ["--no-conversion"]
    if args.only and not any(a.startswith("--tasks") for a in args.extra):
        cmd += ["--tasks", args.only]
    if not any(a.startswith("--sample-parallelism") for a in args.extra):
        cmd += ["--sample-parallelism", str(args.sample_parallelism)]
    cmd += args.extra

    log_path = outdir / "_run.log"
    print("running:", " ".join(cmd))
    print(f"teeing output -> {log_path}")
    with open(log_path, "w", encoding="utf-8") as logf:
        logf.write("running: " + " ".join(cmd) + "\n")
        logf.flush()
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
        for line in proc.stdout:
            sys.stdout.write(line)
            logf.write(line)
        rc = proc.wait()
    if rc == 0:
        print(f"SVC QC done -> {outdir}")
    sys.exit(rc)


def cmd_report(args) -> None:
    c = _cycle(args.date)
    src, dst = c / "04_qc", c / "05_report"
    dst.mkdir(exist_ok=True)
    picked = []
    for f in ["batch_summary.md", "reviewer_queue.csv", "dashboard.html", "REPORT.md",
              "batch_review.json"]:
        s = src / f
        if s.is_file():
            (dst / f).write_bytes(s.read_bytes())
            picked.append(f)
    print(f"collected into 05_report/: {', '.join(picked) or '(nothing — run qc first)'}")
    print("Study 05_report/, then share with the team. Update MANIFEST.md verdict summary.")
    print(f"Next (Step L, cont.): python3 pipeline/cycle.py ledger {args.date}")


def _find_failed_checks(obj, path=""):
    """Best-effort walk of a verifications_results.json blob for anything
    indicating a FAILED check: a dict with status/result/verdict=="FAILED", or
    a bare "FAILED" string value under some key. The real on-disk schema
    hasn't been independently confirmed (see the plan's open items) -- this
    walks any dict/list nesting rather than assuming one fixed shape, so it
    degrades gracefully (finds nothing) instead of crashing on a shape this
    wasn't written against. Yields (path, detail) pairs."""
    if isinstance(obj, dict):
        status_key = next((k for k in ("status", "result", "verdict") if k in obj), None)
        if status_key and isinstance(obj[status_key], str) and obj[status_key].strip().upper() == "FAILED":
            yield path, obj
        for k, v in obj.items():
            if k == status_key:
                continue  # already handled as this dict's own status above
            if isinstance(v, str) and v.strip().upper() == "FAILED":
                yield (f"{path}.{k}" if path else k), {"check": k, "status": v}
            elif isinstance(v, (dict, list)):
                yield from _find_failed_checks(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            yield from _find_failed_checks(item, f"{path}[{i}]" if path else f"[{i}]")


def _load_reviewer_queue(csv_path: Path) -> dict[str, dict]:
    """04_qc/reviewer_queue.csv -> {sample_id: {verdict, one_line, review_reason, issues[]}}.

    One row per issue (both "blocking" and "cosmetic" classification, per
    v18.6's synthesizer -- see gdpval_qc/v18_emitter.py's to_csv()), or a
    single issue-less row for a clean sample. Reading the CSV directly (the
    literal required artifact) rather than re-deriving the same data from
    batch_review.json keeps this in lockstep with whatever a reviewer
    actually opened and by-eye-checked."""
    out: dict[str, dict] = {}
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sid = row.get("sample_id", "")
            entry = out.setdefault(sid, {
                "verdict": row.get("verdict"),
                "one_line": row.get("one_line"),
                "review_reason": row.get("review_reason") or None,
                "issues": [],
            })
            if row.get("classification"):  # empty for a clean/no-issue sample's single row
                entry["issues"].append({
                    "classification": row.get("classification"),
                    "dimension": row.get("dimension"),
                    "severity": row.get("severity"),
                    "fixability": row.get("fixability"),
                    "headline": row.get("headline"),
                    "action": row.get("action") or "",
                    "evidence_quote": row.get("evidence_quote") or None,
                    "detail": row.get("detail") or None,
                })
    return out


def cmd_joint_feedback(args) -> None:
    """Merge Internal QC's reviewer_queue.csv rows with Data-OS's trajectory-
    verification flags into one joint candidate-complaint packet per task, so
    the TP/FP + actionable-guidance session-starter prompt runs once per batch
    against the combined set instead of once per source.

    Reads 04_qc/reviewer_queue.csv (Internal QC, run cycle.py qc first --
    the literal required artifact, not a re-derivation from batch_review.json,
    so this always matches what a reviewer actually sees) and, per task,
    03_evals/task_<id>/verifications_results.json (written by
    dataos-evals-import). No auto-merge/dedupe of overlapping complaints from
    the two sources -- both are listed side by side for the human-run prompt to
    adjudicate, per the decision to keep TP/FP judgment human-run.

    cycle.py joint-feedback <date>
    """
    c = _cycle(args.date)
    rq_path = c / "04_qc" / "reviewer_queue.csv"
    evals_dir = c / "03_evals"
    out_dir = c / "joint_feedback"
    if not rq_path.is_file():
        sys.exit(f"no {rq_path} — run cycle.py qc first")
    try:
        by_sample = _load_reviewer_queue(rq_path)
    except Exception as e:
        sys.exit(f"could not parse {rq_path}: {e}")
    out_dir.mkdir(exist_ok=True)

    written, no_input = [], []
    for sid, row in by_sample.items():
        tid = sid.removeprefix("task_") if sid.startswith("task_") else sid
        internal_issues = row["issues"]
        verif_path = evals_dir / sid / "verifications_results.json"
        automated_flags = []
        if verif_path.is_file():
            try:
                verif = json.loads(verif_path.read_text())
            except Exception as e:
                automated_flags.append({"path": str(verif_path), "parse_error": str(e)})
            else:
                for chk_path, detail in _find_failed_checks(verif):
                    automated_flags.append({"check": chk_path, **{k: v for k, v in detail.items()
                                                                    if k not in ("check",)}})
        if not internal_issues and not automated_flags:
            no_input.append(tid)
            continue
        packet = {
            "task_id": tid,
            "sample_id": sid,
            "internal_qc_verdict": row["verdict"],
            "internal_qc_one_line": row["one_line"],
            "internal_qc_review_reason": row["review_reason"],
            "internal_qc_issues": internal_issues,
            "external_qc_automated_flags": automated_flags,
            "required_source_files": {
                "internal_qc_reviewer_queue": "04_qc/reviewer_queue.csv",
                "external_qc_verification_json": f"03_evals/{sid}/verifications_results.json",
                "task_artifacts": f"02_bundle/{sid}/ (instruction.md, environment/data/, "
                                   f"solution/golden_outputs/, tests/verifier.json)",
                "eval_trajectories": f"03_evals/{sid}/evals/<model>/trial_1/ "
                                      f"(agent/, artifacts/, verifier/reward-details.json)",
            },
        }
        (out_dir / f"task_{tid}_packet.json").write_text(
            json.dumps(packet, indent=2, ensure_ascii=False))
        written.append(tid)

    print(f"wrote {len(written)} joint-feedback packet(s) -> {out_dir}")
    if no_input:
        print(f"  {len(no_input)} task(s) had neither a reviewer_queue.csv issue row nor "
              f"a verifications_results.json with a FAILED check (skipped, no packet written): "
              + ", ".join(no_input))
    if not evals_dir.is_dir():
        print(f"  note: {evals_dir} not found — automated flags will be empty for every task "
              f"until dataos-evals-import has run")
    if written:
        print(f"Next (Step I, manual/out-of-script): paste the External QC Feedback "
              f"Classification Loop prompt (SOP §1.4 Step I) into a fresh Claude Code session, "
              f"with these {len(written)} packet(s) plus each task's reviewer_queue.csv row, "
              f"verifications_results.json, eval trajectories, and harbor bundle artifacts "
              f"attached. Then Step J (publish) and Step K (route) happen inside that same "
              f"session; once done, run: python3 pipeline/cycle.py report {args.date}")


LEDGER_PATH = CYCLES / "task_ledger.json"


def _canon_id(name: str) -> str:
    """Canonical task id = its digits, so 'Task 72' / 'TASK 72' / '72' all key alike
    across cycles that name folders differently. Falls back to the raw name if no digits."""
    digits = re.sub(r"\D", "", name)
    return digits or name


def _qc_verdicts(cycle_dir: Path) -> dict[str, dict]:
    """Read 04_qc/batch_review.json -> {task_id_without_prefix: {verdict, complaints}}.
    Complaints = dimensions of findings at severity >= 2 (the actionable ones)."""
    br = cycle_dir / "04_qc" / "batch_review.json"
    if not br.is_file():
        return {}
    try:
        data = json.loads(br.read_text())
    except Exception:
        return {}
    out = {}
    for s in data.get("samples", []):
        sid = _canon_id(str(s.get("sample_id", "")))
        dims = sorted({
            f.get("dimension") for f in s.get("all_findings", [])
            if (f.get("severity") or 0) >= 2 and f.get("dimension")
        })
        out[sid] = {"verdict": s.get("verdict"), "complaints": dims}
    return out


def cmd_ledger(args) -> None:
    """Update the cross-cycle task ledger and render the novelty / repeated-feedback view.

    Persistent record keyed by task id. Each cycle a task appears in adds one
    observation {cycle, fingerprint, verdict, complaints}. From the history we derive:
      - novelty      — did the content fingerprint change since last appearance?
      - repeats      — task seen in >1 cycle (with content-changed vs unchanged split)
      - recurring    — a complaint dimension flagged in >= 2 different cycles

    `ledger <date>` ingests that cycle; `ledger` (no date) just re-renders from disk.
    """
    ledger = {"tasks": {}}
    if LEDGER_PATH.is_file():
        try:
            ledger = json.loads(LEDGER_PATH.read_text())
        except Exception:
            pass
    tasks = ledger.setdefault("tasks", {})

    if getattr(args, "date", None):
        c = _cycle(args.date)
        fps = _task_map(c / "00_fetched")               # {raw_name: fingerprint}
        qc = _qc_verdicts(c)                            # {id: {verdict, complaints}}
        for raw_name, fp in fps.items():
            tid = _canon_id(raw_name)
            rec = tasks.setdefault(tid, {"observations": []})
            obs = [o for o in rec["observations"] if o["cycle"] != args.date]  # idempotent
            obs.append({
                "cycle": args.date,
                "fingerprint": fp,
                "verdict": qc.get(tid, {}).get("verdict"),
                "complaints": qc.get(tid, {}).get("complaints", []),
            })
            rec["observations"] = sorted(obs, key=lambda o: o["cycle"])
        LEDGER_PATH.write_text(json.dumps(ledger, indent=2, ensure_ascii=False))
        print(f"ledger updated with {len(fps)} tasks from {args.date} -> {LEDGER_PATH}")

    # ── render view ──────────────────────────────────────────────────────────
    repeats, recurring, stale = [], [], []
    for tid, rec in tasks.items():
        obs = rec["observations"]
        if len(obs) < 2:
            continue
        cycles = [o["cycle"] for o in obs]
        fps = [o["fingerprint"] for o in obs]
        content_changed = len(set(fps)) > 1
        repeats.append((tid, cycles, content_changed,
                        [o.get("verdict") for o in obs]))
        # unchanged content on a re-appearance = not novel, feedback likely unaddressed
        if not content_changed:
            stale.append((tid, cycles))
        # complaint dimensions seen in >= 2 distinct cycles
        dim_cycles = {}
        for o in obs:
            for d in o.get("complaints", []):
                dim_cycles.setdefault(d, set()).add(o["cycle"])
        rec_dims = sorted(d for d, cs in dim_cycles.items() if len(cs) >= 2)
        if rec_dims:
            recurring.append((tid, rec_dims))

    lines = [
        "# Task ledger — cross-cycle novelty & repeated-feedback tracker", "",
        f"Total tasks tracked: **{len(tasks)}**  ·  seen in >1 cycle: **{len(repeats)}**", "",
        "## Repeated tasks (seen in more than one cycle)", "",
        "| task | cycles | content | verdict history |",
        "|------|--------|---------|-----------------|",
    ]
    for tid, cycles, changed, verds in sorted(repeats, key=lambda x: x[0]):
        tag = "CHANGED" if changed else "**unchanged**"
        vh = " → ".join(str(v) for v in verds)
        lines.append(f"| task_{tid} | {', '.join(cycles)} | {tag} | {vh} |")
    if not repeats:
        lines.append("| (none yet) | | | |")
    lines += [
        "", "## Stale repeats — reappeared with identical content (not novel; feedback likely unaddressed)", "",
        (", ".join(f"task_{t}" for t, _ in sorted(stale)) or "(none)"), "",
        "## Recurring complaints — same dimension flagged in ≥ 2 cycles for a task", "",
        "| task | recurring complaint dimensions |",
        "|------|-------------------------------|",
    ]
    for tid, dims in sorted(recurring, key=lambda x: x[0]):
        lines.append(f"| task_{tid} | {', '.join(dims)} |")
    if not recurring:
        lines.append("| (none yet) | |")
    view = LEDGER_PATH.with_suffix(".md")
    view.write_text("\n".join(lines) + "\n")
    print(f"repeated tasks: {len(repeats)} · stale (unchanged) repeats: {len(stale)} · "
          f"tasks with recurring complaints: {len(recurring)}")
    print(f"  view -> {view}")
    if getattr(args, "date", None):
        print(f"Next (Step L, cont.): python3 pipeline/cycle.py close {args.date}")


def cmd_close(args) -> None:
    link = CYCLES / "latest"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(args.date)
    print(f"cycles/latest -> {args.date}")
    print("Cycle closed — that's the end of the in-script part of Phase 1. Two things live "
          "outside this script from here (see SOP §2.1-2.2, manual/out-of-script):")
    print("  - Any task approved in Step K needs to be added to the SOP owner's current weekly "
          "shared Data-OS dataset for its front (EKW or SVC) for Phase 2 — that's the "
          "contributor procedure in SOP §2.3, not a cycle.py command.")
    print("  - Any task rejected in Step K goes back to intake (SOP §1.1) as feedback for the "
          "experts, tracked on the RL-World QC tracker, not re-run through this cycle.")


def cmd_status(args) -> None:
    latest = os.readlink(CYCLES / "latest") if (CYCLES / "latest").is_symlink() else "(none)"
    print(f"pipeline: {_read_version()}")
    print(f"latest (diff baseline): {latest}\n")
    for c in sorted(p for p in CYCLES.iterdir() if p.is_dir() and not p.is_symlink()):
        filled = []
        for s in STAGES:
            d = c / s
            n = len([x for x in d.iterdir()]) if d.is_dir() else 0
            filled.append(f"{s.split('_')[1][:4]}:{n}")
        star = " *" if c.name == latest else ""
        print(f"  {c.name}{star}  " + "  ".join(filled))


def main() -> None:
    p = argparse.ArgumentParser(description="EKW-GDPVal QC cycle driver")
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new"); n.add_argument("--date"); n.set_defaults(fn=cmd_new)
    f = sub.add_parser("fetch"); f.add_argument("date")
    f.add_argument("--front", default=None, choices=KNOWN_FRONTS,
                   help="front for a legacy single tracker.csv/loose *.csv (default ekw); "
                        "ignored for tracker_<front>.csv files, which are front-tagged by name")
    f.set_defaults(fn=cmd_fetch)
    for name, fn in [("normalize", cmd_normalize), ("check", cmd_check),
                     ("diff", cmd_diff), ("report", cmd_report), ("close", cmd_close),
                     ("joint-feedback", cmd_joint_feedback)]:
        sp = sub.add_parser(name); sp.add_argument("date"); sp.set_defaults(fn=fn)
    b = sub.add_parser("bundle"); b.add_argument("date")
    b.add_argument("--only", default="", help="comma-separated task ids to restrict the bundle to")
    b.add_argument("--out", default="02_bundle", help="output subdir under the cycle (default 02_bundle)")
    b.set_defaults(fn=cmd_bundle)
    do_ = sub.add_parser("dataos",
                         help="prepare a Data-OS QC submission package (reward-kit convert + one-pager + Slack message)")
    do_.add_argument("date")
    do_.add_argument("--bundle-dir", default="02_bundle", dest="bundle_dir",
                     help="source of harbor tasks to convert (default 02_bundle)")
    do_.add_argument("--only", default="", help="comma-separated task ids to restrict to")
    do_.add_argument("--name", default="",
                     help="dataset name stub; final name is QCR_<name>_DDMMYYYY (default derived from date/track)")
    do_.add_argument("--prefix", default="ekw", help="name_prefix passed to to_rewardkit.py")
    do_.add_argument("--profile", default="ekw", choices=["ekw", "medots", "dermots"],
                     help="which corpus's nature/expectation boilerplate to use in the one-pager + Slack message")
    do_.add_argument("--contact", default="Luiz Araujo <luiz.araujo@turing.com>")
    do_.add_argument("--deadline", default="",
                     help="requested deadline, e.g. 07/08/2026 (target only, doesn't affect queue priority)")
    do_.set_defaults(fn=cmd_dataos)
    ds = sub.add_parser("dataos-standalone",
                        help="same as dataos, but for a bundle outside any cycle folder "
                             "(a standalone task dir, or a dir of task_<id>/ dirs)")
    ds.add_argument("bundle_dir")
    ds.add_argument("out_dir")
    ds.add_argument("--only", default="", help="comma-separated task ids to restrict to")
    ds.add_argument("--name", default="",
                    help="dataset name stub; final name is QCR_<name>_DDMMYYYY (default derived from bundle_dir name)")
    ds.add_argument("--prefix", default="ekw", help="name_prefix passed to to_rewardkit.py")
    ds.add_argument("--profile", default="ekw", choices=["ekw", "medots", "dermots"],
                    help="which corpus's nature/expectation boilerplate to use in the one-pager + Slack message")
    ds.add_argument("--contact", default="Luiz Araujo <luiz.araujo@turing.com>")
    ds.add_argument("--deadline", default="",
                    help="requested deadline, e.g. 07/08/2026 (target only, doesn't affect queue priority)")
    ds.set_defaults(fn=cmd_dataos_standalone)
    di = sub.add_parser("dataos-evals-import",
                        help="import a Data-OS QC-run drop (dataos-qc-run skill's output) into 03_evals/")
    di.add_argument("date")
    di.add_argument("dataos_qc_runs_dir")
    di.add_argument("--bundle-dir", default="02_bundle", dest="bundle_dir")
    di.add_argument("--only", default="", help="comma-separated task ids to restrict to")
    di.set_defaults(fn=cmd_dataos_evals_import)
    e = sub.add_parser("evals"); e.add_argument("date")
    e.add_argument("src", nargs="?", default="", help="eval drop dir (relative to the cycle; auto-detected if omitted)")
    e.set_defaults(fn=cmd_evals)
    ep = sub.add_parser("evals-package",
                        help="package 02_bundle/ tasks for a Harbor-beta eval request")
    ep.add_argument("date")
    ep.add_argument("--batch-prefix", required=True)
    ep.add_argument("--bundle-dir", default="02_bundle", dest="bundle_dir")
    ep.add_argument("--only", default="")
    ep.set_defaults(fn=cmd_evals_package)
    eu = sub.add_parser("evals-upload",
                        help="upload a packaged batch to Harbor-beta and write ready markers")
    eu.add_argument("date")
    eu.add_argument("--project", default="turing-delivery-apac-dev")
    eu.add_argument("--bucket", default="long-horizon-beta")
    eu.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    eu.set_defaults(fn=cmd_evals_upload)
    ee = sub.add_parser("evals-enqueue",
                        help="enqueue the Harbor-beta eval (dry-run by default; --live for real)")
    ee.add_argument("date")
    ee.add_argument("--base-url", required=True)
    ee.add_argument("--k", type=int, required=True)
    ee.add_argument("--models-file", required=True)
    ee.add_argument("--project", default="turing-delivery-apac-dev")
    ee.add_argument("--bucket", default="long-horizon-beta")
    ee.add_argument("--live", action="store_true",
                    help="actually enqueue (real spend); omit for dry-run only")
    ee.set_defaults(fn=cmd_evals_enqueue)
    es = sub.add_parser("evals-status", help="poll Harbor-beta for eval completion")
    es.add_argument("date")
    es.add_argument("--batch-prefix", required=True)
    es.add_argument("--expected-trials", type=int, required=True)
    es.add_argument("--project", default="turing-delivery-apac-dev")
    es.add_argument("--evals-bucket", default="long-horizon-evals-beta")
    es.add_argument("--wait", action="store_true")
    es.add_argument("--poll-seconds", type=int, default=120)
    es.set_defaults(fn=cmd_evals_status)
    ef = sub.add_parser("evals-fetch",
                        help="download finished Harbor-beta trials into cycle.py evals' expected layout")
    ef.add_argument("date")
    ef.add_argument("--project", default="turing-delivery-apac-dev")
    ef.add_argument("--evals-bucket", default="long-horizon-evals-beta")
    ef.set_defaults(fn=cmd_evals_fetch)
    q = sub.add_parser("qc"); q.add_argument("date")
    q.add_argument("--spec", default=str(SPEC_DEFAULT))
    q.add_argument("--sample-parallelism", type=int, default=5, dest="sample_parallelism",
                   help="tasks graded concurrently (default 5; CLI's own default is 1)")
    q.add_argument("--dim-parallelism", type=int, default=4, dest="dim_parallelism",
                   help="dims graded concurrently per task (default 4)")
    q.add_argument("--calibrate", action="store_true",
                   help="also grade the 5 calibration goldens (drift check); off by default")
    q.add_argument("extra", nargs="*", help="extra args passed to gdpval-assess (e.g. --no-multimodal)")
    q.set_defaults(fn=cmd_qc)
    sv = sub.add_parser("svc-qc",
                        help="SVC/Cirrus QC — no fetch/diff/bundle; points straight at a corpus dir")
    sv.add_argument("corpus", help="path to the SVC tasks/ directory")
    sv.add_argument("--only", default="", help="comma-separated task ids to restrict to (passed as --tasks)")
    sv.add_argument("--out-dir", default="", dest="out_dir",
                    help="output dir (default: runs/svc_<date>/)")
    sv.add_argument("--date", default="",
                    help="date stamp for the default out-dir (default: today)")
    sv.add_argument("--spec", default=str(SPEC_SVC),
                    help="spec to run (default: specs/overlays/svc.md; use "
                         "specs/overlays/svc-noeval.md when evals/ isn't populated yet)")
    sv.add_argument("--sample-parallelism", type=int, default=3, dest="sample_parallelism",
                    help="tasks graded concurrently (default 3, per RUN_FULL_QC.md)")
    sv.add_argument("--with-conversion", action="store_true",
                    help="enable libreoffice doc conversion (default: --no-conversion, text-only)")
    sv.add_argument("extra", nargs="*", help="extra args passed to gdpval-assess")
    sv.set_defaults(fn=cmd_svc_qc)
    lg = sub.add_parser("ledger")
    lg.add_argument("date", nargs="?", default=None,
                    help="cycle to ingest into the ledger; omit to just re-render the view")
    lg.set_defaults(fn=cmd_ledger)
    s = sub.add_parser("status"); s.set_defaults(fn=cmd_status)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
