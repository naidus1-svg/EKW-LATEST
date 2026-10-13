#!/usr/bin/env python3
"""
build_corpus.py — turn the public openai/gdpval dataset into a gdpval-qc corpus.

Calibration harness, Stage 0. Fetches the 220 gold GDPval tasks, takes a
deterministic stratified sample of size N (any N is a prefix of the full
ordering, so the N=10 sample is a strict subset of the N=50 sample), downloads
each task's reference + deliverable files, and writes a corpus laid out the way
`gdpval-assess` expects:

    corpus/task_<shortid>/
        task.toml
        instruction.md
        environment/              <- reference_files
        solution/golden_outputs/  <- deliverable_files
        tests/verifier.json       <- adapted from rubric_json

Stdlib only — no `datasets`/`huggingface_hub` install required.

Usage:
    python build_corpus.py --n 10
    python build_corpus.py --n 50 --out corpus_50

The rubric adapter (rubric_json -> verifier.json) is the one lossy step.
GDPval rubric items are a flat list of {score, criterion, tags, ...} with no
outcome/process split and no per-criterion source file, so three fields are
*invented* by this adapter and must be read as adapter choices, not GDPval
signal:
  - metadata.grading_role : defaulted to "outcome" (GDPval criteria grade the
                            deliverable's content). measure.py flags the
                            verifier_outcome_grader_present dim as adapter-driven.
  - metadata.weight       : GDPval `score` normalized over positive scores.
  - source                : pointed at the first deliverable under output/.
Everything that carries real GDPval signal (criterion text -> rubric prompt,
score sign/magnitude) is preserved verbatim.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
ROWS_CACHE = HERE / "rows.json"
DATASET = "openai/gdpval"
ROWS_API = "https://datasets-server.huggingface.co/rows"


def _curl(url: str, dest: Path | None = None) -> bytes:
    """Fetch via curl (-L: HF resolve/ URLs 302-redirect LFS files to a CDN;
    the system trust store works where this Python's certifi doesn't)."""
    cmd = ["curl", "-sSL", "--fail", "--retry", "3", url]
    if dest is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd += ["-o", str(dest)]
        subprocess.run(cmd, check=True)
        head = dest.read_bytes()[:64]
        if b"Redirect" in head or b"<html" in head[:16].lower():
            raise RuntimeError(f"got a redirect/HTML stub, not the file: {dest.name} ({url})")
        return b""
    return subprocess.run(cmd, check=True, capture_output=True).stdout


# ── Fetch rows (cached) ──────────────────────────────────────────────────────

def fetch_rows() -> list[dict]:
    """All 220 gold rows, cached to rows.json after the first pull."""
    if ROWS_CACHE.exists():
        return json.loads(ROWS_CACHE.read_text())
    rows: list[dict] = []
    offset = 0
    while True:
        url = (f"{ROWS_API}?dataset={urllib.parse.quote(DATASET)}"
               f"&config=default&split=train&offset={offset}&length=100")
        page = json.loads(_curl(url))
        batch = [r["row"] for r in page.get("rows", [])]
        if not batch:
            break
        rows.extend(batch)
        offset += len(batch)
        if offset >= page.get("num_rows_total", offset):
            break
    ROWS_CACHE.write_text(json.dumps(rows))
    print(f"fetched {len(rows)} rows -> {ROWS_CACHE.name}")
    return rows


# ── Deterministic stratified sampling ────────────────────────────────────────

def stratified_order(rows: list[dict]) -> list[dict]:
    """Round-robin across sectors, occupations within a sector, task_id within.

    Pure function of the data (no RNG), so the prefix of length N is a stable,
    reproducible, sector-balanced sample and N=10 is a subset of N=50.
    """
    buckets: dict[str, list[dict]] = {}
    for r in rows:
        buckets.setdefault(r["sector"], []).append(r)
    for sector in buckets:
        buckets[sector].sort(key=lambda r: (r["occupation"], r["task_id"]))
    sectors = sorted(buckets)
    ordered: list[dict] = []
    i = 0
    while any(buckets[s] for s in sectors):
        sector = sectors[i % len(sectors)]
        if buckets[sector]:
            ordered.append(buckets[sector].pop(0))
        i += 1
    return ordered


# ── File download ────────────────────────────────────────────────────────────

def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    _curl(url, dest)


def basename_from_path(p: str) -> str:
    """Decoded final path component, e.g. 'reference_files/h/Population%20v2.xlsx'
    -> 'Population v2.xlsx'."""
    return urllib.parse.unquote(p.rsplit("/", 1)[-1])


# ── Rubric adapter: rubric_json -> verifier.json ─────────────────────────────

def adapt_rubric(rubric_items: list[dict], deliverable_basenames: list[str]) -> dict:
    """Map GDPval rubric items to the gdpval-qc verifier.json schema.

    Faithful to the actual GDPval fields:
      - assertion.expected  <- score SIGN: score>=0 -> True (award when met),
                               score<0 -> False (penalty; pass means the bad
                               thing is absent). rubric_pretty renders these as
                               "[+-N]" deductions. NOTE: the `tags` true/false
                               field is NOT grader polarity (false-tagged items
                               render as positive "[+N]" awards) — it's a
                               baseline/label flag, passed through but unused.
      - weight              <- |score| normalized (penalty items carry real
                               importance: a -10 is a major check).
      - rubric.prompt       <- criterion text, verbatim.
    Adapter-invented (no GDPval equivalent), flagged in measure.py:
      - grading_role="outcome" (GDPval has no outcome/process axis).
      - source -> the deliverable DIRECTORY "output/", not a specific file.
        GDPval criteria don't encode a per-criterion target file, and pointing
        every verifier at deliverable[0] made multi-deliverable tasks look
        "wired to one wrong file" (false construct_validity/missing_critical
        sev3). A directory path is the honest representation; the criterion text
        already names its artifact.
    """
    abs_total = sum(abs(it["score"]) for it in rubric_items
                    if isinstance(it.get("score"), (int, float))) or 1.0

    verifiers = []
    for i, it in enumerate(rubric_items, start=1):
        criterion = (it.get("criterion") or "").strip()
        score = it.get("score")
        is_num = isinstance(score, (int, float))
        weight = round(abs(score) / abs_total, 6) if is_num else 0.0
        expected = (score >= 0) if is_num else True  # negative score = penalty -> pass if absent
        verifiers.append({
            "name": f"v{i}",
            "metadata": {
                # adapter-invented (no GDPval equivalent) — flagged in measure.py:
                "grading_role": "outcome",
                "weight": weight,
                # faithful passthrough:
                "gdpval_score": score,
                "gdpval_rubric_item_id": it.get("rubric_item_id"),
                "gdpval_author_type": it.get("author_type"),
                "gdpval_tags": it.get("tags"),
            },
            "source": {
                "type": "file",
                "file": {"type": "any", "command": "extract_text",
                         "arguments": {"path": "output/"}},
            },
            "assertion": {
                "type": "rubric",
                "expected": expected,
                "rubric": {"prompt": criterion},  # verbatim GDPval criterion
            },
        })
    return {
        "task_id": None,  # filled by caller
        "config": {"models": ["openai/gpt-5.4"], "temperature": 1.0,
                   "reasoning_effort": "xhigh"},
        "verifiers": verifiers,
    }


# ── Convert one row -> task dir ──────────────────────────────────────────────

def short_id(task_id: str) -> str:
    return task_id.split("-", 1)[0]


def convert_row(row: dict, corpus: Path) -> str:
    tid = row["task_id"]
    dest = corpus / f"task_{short_id(tid)}"
    dest.mkdir(parents=True, exist_ok=True)

    # instruction.md
    (dest / "instruction.md").write_text(row["prompt"])

    # environment/ <- reference files
    env = dest / "environment"
    env.mkdir(exist_ok=True)
    for path, url in zip(row.get("reference_files", []), row.get("reference_file_urls", [])):
        download(url, env / basename_from_path(path))

    # solution/golden_outputs/ <- deliverable files
    sol = dest / "solution" / "golden_outputs"
    sol.mkdir(parents=True, exist_ok=True)
    deliverable_names = []
    for path, url in zip(row.get("deliverable_files", []), row.get("deliverable_file_urls", [])):
        name = basename_from_path(path)
        deliverable_names.append(name)
        download(url, sol / name)

    # tests/verifier.json <- adapted rubric
    tests = dest / "tests"
    tests.mkdir(exist_ok=True)
    rubric = json.loads(row["rubric_json"])
    verifier = adapt_rubric(rubric, deliverable_names)
    verifier["task_id"] = tid
    (tests / "verifier.json").write_text(json.dumps(verifier, indent=2))

    # task.toml — category must be non-empty (else metadata_completeness sev2)
    toml = (
        f'version = "1.0"\n'
        f'artifacts = ["/workspace/output"]\n\n'
        f'[metadata]\n'
        f'task_id = "{tid}"\n'
        f'category = "{row["sector"]}"\n'
        f'subdomain = "{row["occupation"]}"\n'
        f'difficulty = ""\n'
        f'tags = []\n'
    )
    (dest / "task.toml").write_text(toml)
    return dest.name


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, required=True, help="sample size (prefix of the stratified order)")
    ap.add_argument("--out", default=None, help="corpus dir name (default: corpus_<N>)")
    args = ap.parse_args()

    rows = fetch_rows()
    ordered = stratified_order(rows)
    sample = ordered[: args.n]
    corpus = HERE / (args.out or f"corpus_{args.n}")
    corpus.mkdir(parents=True, exist_ok=True)

    print(f"building {len(sample)}-task corpus -> {corpus}")
    sectors: dict[str, int] = {}
    for row in sample:
        name = convert_row(row, corpus)
        sectors[row["sector"]] = sectors.get(row["sector"], 0) + 1
        print(f"  ✓ {name:18s} {row['sector'][:32]:32s} {row['occupation']}")
    print("\nsector balance:")
    for s, c in sorted(sectors.items()):
        print(f"  {c:3d}  {s}")


if __name__ == "__main__":
    main()
