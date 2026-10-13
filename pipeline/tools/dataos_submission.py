#!/usr/bin/env python3
"""Prepare a Data-OS QC submission package from a bundled EKW-GDPVal cycle.

Produces everything the "Turing QC Request Procedure for Internal Clients"
needs BEFORE the manual, Data-OS-facing steps (upload, Data-OS testing,
oracle passes, freeze, Slack post):

  1. reward-kit conversion of every bundled task (via to_rewardkit.convert)
     -> out/rewardkit/task_<id>/
  2. the one-page dataset description doc (purpose/nature, scope, structure,
     expected outputs, limitations, contact) -> out/QCR_<name>_<DDMMYYYY>.docx
  3. the #TFRL_QC Slack submission message, ready to paste -> out/slack_message.md
  4. a submission manifest (per-task convert status + batch stats) -> out/SUBMISSION.md

Usage:
  python3 dataos_submission.py <bundle_dir> <out_dir> <dataset_name> \\
      [--prefix ekw] [--contact "Name <email>"] [--deadline DD/MM/YYYY] \\
      [--only 97,160] [--stamp DDMMYYYY]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import shutil
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import to_rewardkit  # noqa: E402  (sibling script; sys.path patched above)

from docx import Document

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _add_markdown_paragraph(doc: Document, text: str, style: str | None = None):
    """Add a paragraph rendering **bold** markdown spans as real bold runs —
    manifest bullets carry this formatting and showing literal asterisks in
    the delivered docx would look broken."""
    p = doc.add_paragraph(style=style)
    pos = 0
    for m in _BOLD_RE.finditer(text):
        if m.start() > pos:
            p.add_run(text[pos:m.start()])
        p.add_run(m.group(1)).bold = True
        pos = m.end()
    if pos < len(text):
        p.add_run(text[pos:])
    return p


def _load_source_meta(task_dir: Path) -> dict:
    """category/subdomain from whichever task.toml the source provides. A
    pre-conversion harbor task.toml has both; a task that's already in
    reward-kit format only carries category (subdomain isn't part of that
    schema) — that's fine, it just stays blank for those tasks."""
    meta = {"category": "", "subdomain": ""}
    toml_path = task_dir / "task.toml"
    if toml_path.is_file():
        try:
            t = tomllib.load(toml_path.open("rb")).get("metadata", {}) or {}
            meta["category"] = t.get("category", "")
            meta["subdomain"] = t.get("subdomain", "")
        except Exception:
            pass
    return meta


def _load_converted_meta(rk_task_dir: Path) -> dict:
    """verifier count / deliverables / judge model, read from the FINAL
    reward-kit package (post-conversion or, if the source already was
    reward-kit, post-copy) — this is the single source of truth for what's
    actually being submitted, so the one-pager never describes a judge model
    or deliverable set that doesn't match what's in rewardkit/."""
    meta = {"n_verifiers": 0, "deliverables": [], "judge": ""}
    judge_path = rk_task_dir / "tests" / "deliverables" / "judge.toml"
    if judge_path.is_file():
        try:
            j = tomllib.load(judge_path.open("rb"))
            meta["n_verifiers"] = len(j.get("criterion", []) or [])
            meta["judge"] = (j.get("judge") or {}).get("judge", "")
            files = (j.get("judge") or {}).get("files", []) or []
            meta["deliverables"] = sorted({Path(f).name for f in files})
        except Exception:
            pass
    return meta


def _is_rewardkit_format(task_dir: Path) -> bool:
    return (task_dir / "tests" / "deliverables" / "judge.toml").is_file()


def _parse_md_table(text: str):
    """First markdown table whose data rows start with a bare numeric id.
    Returns (header_cells, {id: [cell values]}) or (None, {}) if none found."""
    lines = text.splitlines()
    for i, line in enumerate(lines[:-1]):
        if line.strip().startswith("|") and re.match(r"^\|[\s:|-]+\|\s*$", lines[i + 1].strip()):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            rows = {}
            for row_line in lines[i + 2:]:
                if not row_line.strip().startswith("|"):
                    break
                cells = [c.strip() for c in row_line.strip().strip("|").split("|")]
                if cells and re.match(r"^\d+$", cells[0]):
                    rows[cells[0]] = cells
            return header, rows
    return None, {}


def _extract_bullet_sections(text: str) -> dict[str, list[str]]:
    """{section heading: [bullet lines]} for every markdown '## ...' section
    that has '- ' bullets — covers whatever a manifest calls its free-text
    caveats section ("Expert-review provenance", "Notable / open items", ...)
    without hardcoding one specific heading. A bullet that word-wraps onto
    indented continuation lines (common in hand-written manifests) is
    rejoined into one line — otherwise it silently truncates at the wrap."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            current = s[3:].strip()
        elif current and s.startswith("- "):
            sections.setdefault(current, []).append(s[2:])
        elif current and s and sections.get(current) and not s.startswith(("#", "|")):
            sections[current][-1] += " " + s
    return {k: v for k, v in sections.items() if v}


def load_manifest_provenance(bundle_dir: Path) -> dict:
    """Optional: fold in any MANIFEST.md shipped with the bundle — the
    cross-cycle QC delivery convention used under cycles/delivery/ (a table
    keyed by numeric task id, plus free-text "## ..." sections of caveats).
    Checks BOTH bundle_dir/MANIFEST.md (rewardkit-conversion-level notes, e.g.
    a specific task's known verifier issues) and bundle_dir.parent/MANIFEST.md
    (cross-cycle review-rigor notes) since they carry complementary info — the
    more specific bundle_dir one wins on a per-task conflict. Returns {} if
    neither exists; this is purely additive context, never required to submit."""
    by_task: dict[str, dict] = {}
    sections: dict[str, list[str]] = {}
    # parent first, then bundle_dir, so bundle_dir's per-task data wins on conflict
    for candidate in (bundle_dir.parent / "MANIFEST.md", bundle_dir / "MANIFEST.md"):
        if not candidate.is_file():
            continue
        text = candidate.read_text()
        header, rows = _parse_md_table(text)
        if header:
            def col(*names):
                for j, h in enumerate(header):
                    if any(n in h.lower() for n in names):
                        return j
                return None
            vi, si = col("verdict"), col("source qc", "source")
            for tid, cells in rows.items():
                by_task[tid] = {
                    "verdict": cells[vi] if vi is not None and vi < len(cells) else "",
                    "source": cells[si] if si is not None and si < len(cells) else "",
                }
        for heading, bullets in _extract_bullet_sections(text).items():
            sections.setdefault(f"{heading} ({candidate.parent.name}/{candidate.name})", []).extend(bullets)
    return {"by_task": by_task, "sections": sections}


def _display_id(tid: str) -> str:
    """EKW/MedOTS ids are bare numbers (task.toml's task_<id> convention was
    already stripped) — re-add "task_" for readability. A DermOTS-style named
    id (e.g. psoriasis-flare-methotrexate) already reads fine on its own."""
    return f"task_{tid}" if tid.isdigit() else tid


def convert_tasks(bundle_dir: Path, out_dir: Path, prefix: str, only: set[str] | None,
                   provenance: dict | None = None):
    """Get every bundled task into out_dir/rewardkit/<name>/. A task already
    in reward-kit format (e.g. a DermOTS drop converted ahead of time) is
    copied as-is; a raw harbor task (task.toml v1.0 + verifier.json) is
    converted via to_rewardkit.convert. Returns a list of
    (task_id, ok, error_detail, meta) — one bad task doesn't stop the batch."""
    rk_dir = out_dir / "rewardkit"
    rk_dir.mkdir(parents=True, exist_ok=True)
    by_task = (provenance or {}).get("by_task", {})
    results = []
    # bundle_dir may itself be a single already-bundled task (task.toml at its own
    # root — the standalone case) rather than a container of task_<id>/ subdirs.
    if (bundle_dir / "task.toml").is_file():
        task_dirs = [bundle_dir]
    else:
        task_dirs = sorted((p for p in bundle_dir.iterdir()
                             if p.is_dir() and (p / "task.toml").is_file()), key=lambda p: p.name)
    for tdir in task_dirs:
        tid = tdir.name.removeprefix("task_")
        if only and tid not in only:
            continue
        src_meta = _load_source_meta(tdir)
        src_meta["verdict"] = by_task.get(tid, {}).get("verdict", "")
        src_meta["qc_source"] = by_task.get(tid, {}).get("source", "")
        dest = rk_dir / tdir.name
        if _is_rewardkit_format(tdir):
            try:
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(tdir, dest)
            except Exception as e:
                results.append((tid, False, f"{type(e).__name__}: {e}", src_meta))
                continue
        else:
            # EKW/DermOTS ship solution/golden_outputs/; SVC ships solution/golden/
            # (see to_rewardkit.py's own gold_svc/gold_ekw resolution) — check
            # whichever one actually exists so this safety net isn't silently
            # disabled for SVC tasks.
            golden = tdir / "solution" / "golden_outputs"
            if not golden.is_dir():
                golden = tdir / "solution" / "golden"
            expected = (sorted(f.name for f in golden.iterdir()
                                if f.is_file() and f.name.lower() != "reasoning.docx")
                        if golden.is_dir() else [])
            try:
                to_rewardkit.convert(str(tdir), str(dest), prefix)
            except Exception as e:
                results.append((tid, False, f"{type(e).__name__}: {e}", src_meta))
                continue
            # to_rewardkit only copies deliverables it can match by filename in
            # the golden dir — a golden dir holding a single .zip (rather than
            # the extracted files verifier.json/rubric.json names) produces a
            # *silent* empty solution/files/, which would fail Data-OS's
            # oracle-pass requirement unnoticed. Catch that here instead of a
            # false "converted".
            sol_files = dest / "solution" / "files"
            n_copied = len(list(sol_files.iterdir())) if sol_files.is_dir() else 0
            if expected and n_copied == 0:
                results.append((tid, False,
                                 "reward-kit solution/files/ is empty — the golden dir likely holds an "
                                 "archive (e.g. .zip) instead of the individual files verifier.json/"
                                 "rubric.json names; extract it in 00_fetched/ and re-bundle before "
                                 "submitting", src_meta))
                continue
        meta = {**src_meta, **_load_converted_meta(dest)}
        results.append((tid, True, "", meta))
    return results


# Per-corpus "nature of the tasks" + "what's expected" boilerplate for the
# one-pager and Slack description. Add a new key here for each corpus this
# module submits — never overload one profile's text across corpora, the
# whole point of these sections is that they describe THIS dataset correctly.
PROFILES = {
    "ekw": {
        # Official Project Omega framing (as given by the project team), not an
        # inferred paraphrase — keep this in sync if the team's canonical
        # description changes, rather than drifting into ad hoc wording.
        "label": "EKW-GDPVal long-horizon, document-grounded knowledge-work",
        "nature": (
            "Project Omega benchmarks LLMs against real professional workflows "
            "across nine economic domains (government, finance, professional "
            "services, health care, manufacturing, retail, information, real "
            "estate, and more). Each task pairs a prompt, input source documents, "
            "an expert-authored ideal solution, and a set of objective verifiers "
            "that mirror genuine day-to-day work — for example: \"Using the "
            "attached planogram reset brief, identify the top 3 category "
            "conflicts in the proposed shelf layout and recommend corrective "
            "actions with supporting rationale\" (a mid-difficulty Retail Trade "
            "task). Tasks are deliberately built to expose gaps textbook "
            "knowledge can't close: models have already seen standard "
            "frameworks and blog-style explainers, so the benchmark instead "
            "targets real-world nuance, messy data, and constraint-heavy "
            "tradeoffs — the kind of judgment where experienced professionals "
            "still outperform LLMs."
        ),
        "expectation": (
            "Each task expects the agent to produce the deliverable(s) the "
            "prompt calls for, grounded strictly in the supplied source "
            "documents. Every task passes a three-phase lifecycle before "
            "reaching a delivery batch: (1) an expert builds the prompt, "
            "source files, golden solution, and rubric, self-QCs them, and "
            "scores the golden against its own verifiers (target >90) before "
            "marking it Ready for Eval; (2) Engineering runs it through other "
            "models plus an automated QC pass; (3) a second expert peer-reviews "
            "the verifier QC feedback and the golden output before accepting "
            "it. Every task in this batch carries a weighted, multi-verifier "
            "rubric (core + secondary) that a judge model grades the "
            "deliverables against."
        ),
    },
    "medots": {
        "label": "Medical-OTS healthcare knowledge-work",
        "nature": (
            "Medical-OTS is an off-the-shelf benchmark of healthcare knowledge-work "
            "tasks (the Neda/DermOTS-adjacent tracker), each built from a real "
            "clinical or administrative scenario in Health Care and Social Assistance. "
            "Correct completion depends on domain-specific clinical/administrative "
            "judgment a generalist model would miss, and source materials often "
            "combine images (e.g. de-identified clinical photos/scans) with text "
            "documents that must be read together to reach the correct answer."
        ),
        "expectation": (
            "Each task expects the agent to produce a deliverable grounded strictly "
            "in the supplied source materials and the prompt's stated scope. Every "
            "task ships with a golden (oracle) solution and a weighted, multi-criterion "
            "rubric (core + secondary, expert-authored Importance/Valence) that a "
            "judge model grades the deliverable against."
        ),
    },
    "dermots": {
        "label": "DermOTS longitudinal dermatology clinical-reasoning",
        "nature": (
            "DermOTS is a benchmark of longitudinal dermatology clinical-reasoning "
            "tasks. Each task is built from a full patient case history (a "
            "chronological sequence of clinical encounters — visits, labs, imaging) "
            "and asks the model to reason over that history as of a specific "
            "snapshot date, the way a treating clinician would. Cases are authored "
            "and reviewed through a three-role expert pipeline (case designer, "
            "primary dermatologist, senior dermatologist); correct completion "
            "depends on synthesizing the longitudinal record — not just the latest "
            "encounter — to reach the correct clinical judgment."
        ),
        "expectation": (
            "Each task expects the agent to produce a single grounded clinical "
            "response (answer.md) — diagnosis, severity assessment, and treatment "
            "recommendation — strictly supported by the case's source materials as "
            "of the task's snapshot date. Every task ships with a golden (oracle) "
            "answer and a weighted, multi-criterion rubric (core + secondary) that a "
            "judge model grades the deliverable against."
        ),
    },
}


def build_one_pager(out_path: Path, dataset_name: str, stamp: str, results, contact: str,
                     profile: dict, sections: dict[str, list[str]] | None = None,
                     scope_note: str = "") -> None:
    ok = [r for r in results if r[1]]
    failed = [r for r in results if not r[1]]
    categories = sorted({r[3]["category"] for r in ok if r[3]["category"]})
    subdomains = sorted({r[3]["subdomain"] for r in ok if r[3]["subdomain"]})
    verifier_counts = [r[3]["n_verifiers"] for r in ok if r[3]["n_verifiers"]]
    deliverable_types = sorted({Path(d).suffix.lstrip(".") for r in ok for d in r[3]["deliverables"] if d})
    judges = sorted({r[3]["judge"] for r in ok if r[3].get("judge")})

    doc = Document()
    doc.add_heading(f"QCR_{dataset_name}_{stamp}", level=0)
    doc.add_paragraph("Dataset description for Turing internal QC (#TFRL_QC)")

    doc.add_heading("Purpose and use case", level=1)
    doc.add_paragraph(profile["nature"])

    doc.add_heading("Scope", level=1)
    if scope_note:
        doc.add_paragraph(scope_note)
    scope = f"{len(ok)} task(s) submitted"
    if failed:
        scope += f" ({len(failed)} excluded — failed reward-kit conversion, see manifest)"
    scope += f". Domains covered: {', '.join(categories) or '(n/a)'}."
    doc.add_paragraph(scope)
    if subdomains:
        doc.add_paragraph(f"Subdomains: {', '.join(subdomains)}.")

    doc.add_heading("Dataset structure and key metadata", level=1)
    doc.add_paragraph(
        "Each task is a self-contained reward-kit package: task.toml (metadata), "
        "instruction.md (agent-facing prompt), environment/initial_workspace/ "
        "(source documents), solution/files/ (oracle deliverables) + "
        "solution/solve.sh, and tests/deliverables/judge.toml (the graded "
        "rubric, weighted_mean aggregation)."
    )
    if verifier_counts:
        doc.add_paragraph(
            f"Verifier (rubric) count per task ranges {min(verifier_counts)}-"
            f"{max(verifier_counts)}, judged by {', '.join(judges) or 'the configured judge model'}."
        )

    doc.add_heading("Expected outputs", level=1)
    doc.add_paragraph(profile["expectation"])
    if deliverable_types:
        doc.add_paragraph(f"Deliverable formats in this batch: {', '.join(deliverable_types)}.")

    doc.add_heading("Known limitations / review notes", level=1)
    if failed:
        doc.add_paragraph(
            "The following task(s) failed reward-kit conversion and are NOT "
            "included in this submission: " + ", ".join(_display_id(r[0]) for r in failed) + "."
        )
    else:
        doc.add_paragraph("No conversion failures in this batch.")
    doc.add_paragraph(
        "Every included task has a recorded oracle pass (solution/solve.sh "
        "reproduces the graded deliverables) — confirm on Data-OS before QC begins."
    )
    with_verdict = [r for r in ok if r[3].get("verdict")]
    missing_verdict = [r for r in ok if not r[3].get("verdict")]
    if with_verdict:
        counts: dict[str, int] = {}
        for r in with_verdict:
            counts[r[3]["verdict"]] = counts.get(r[3]["verdict"], 0) + 1
        doc.add_paragraph(
            "QC verdict mix at acceptance (per the delivery manifest): "
            + "; ".join(f"{n} {v}" for v, n in sorted(counts.items())) + "."
        )
    if missing_verdict:
        doc.add_paragraph(
            "No delivery-manifest provenance on file for: "
            + ", ".join(_display_id(r[0]) for r in missing_verdict)
            + " — confirm QC verdict and review status for these before relying on this doc alone."
        )
    for heading, bullets in (sections or {}).items():
        doc.add_paragraph(f"{heading}:")
        for b in bullets:
            _add_markdown_paragraph(doc, b, style="List Bullet")

    doc.add_heading("Contact person", level=1)
    doc.add_paragraph(contact)

    doc.save(out_path)


SLACK_TEMPLATE = """\
Thread: QC
Dataset: QCR_{name}_{stamp}
Dataset Link: _(fill in after Data-OS upload)_
Description: {description}
Requested Deadline: {deadline}
"""


def build_slack_message(out_path: Path, dataset_name: str, stamp: str, results, deadline: str,
                         profile: dict, reviewer_note: str = "") -> None:
    ok = [r for r in results if r[1]]
    categories = sorted({r[3]["category"] for r in ok if r[3]["category"]})
    description = (
        f"{len(ok)} {profile['label']} task(s)"
        + (f" spanning {', '.join(categories)}" if categories else "")
        + ". Each task ships an oracle solution and a weighted multi-criterion rubric."
    )
    if reviewer_note:
        description += " " + reviewer_note
    out_path.write_text(SLACK_TEMPLATE.format(
        name=dataset_name, stamp=stamp, description=description,
        deadline=deadline or "_(target only — set by the requester)_"))


def build_manifest(out_path: Path, dataset_name: str, stamp: str, results) -> None:
    ok = [r for r in results if r[1]]
    failed = [r for r in results if not r[1]]
    lines = [
        f"# Data-OS submission — QCR_{dataset_name}_{stamp}", "",
        f"- Tasks converted: **{len(ok)}**  ·  failed: **{len(failed)}**", "",
        "## Converted", "",
    ]
    lines += [f"- {_display_id(r[0])}" for r in ok] or ["- (none)"]
    if failed:
        lines += ["", "## Failed conversion (excluded from submission)", ""]
        lines += [f"- {_display_id(r[0])}: {r[2]}" for r in failed]
    lines += [
        "", "## Manual steps still required (Turing QC Request Procedure)", "",
        f"1. Upload `rewardkit/` task packages to Data-OS, share with `TFRL_QC` "
        f"(admin), name the dataset `QCR_{dataset_name}_{stamp}`",
        "2. Complete Data-OS testing; confirm an oracle pass for every task",
        "3. Freeze the dataset (no edits until QC completes)",
        f"4. Share `QCR_{dataset_name}_{stamp}.docx` with qc@turing.com",
        "5. Post `slack_message.md` into #TFRL_QC (fill in the Dataset Link first)",
    ]
    out_path.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundle_dir")
    ap.add_argument("out_dir")
    ap.add_argument("dataset_name")
    ap.add_argument("--prefix", default="ekw", help="name_prefix passed to to_rewardkit.py")
    ap.add_argument("--contact", default="Luiz Araujo <luiz.araujo@turing.com>")
    ap.add_argument("--deadline", default="", help="requested deadline, e.g. 07/08/2026")
    ap.add_argument("--only", default="", help="comma-separated task ids to restrict to")
    ap.add_argument("--stamp", default="", help="DDMMYYYY override; default = today")
    ap.add_argument("--profile", default="ekw", choices=sorted(PROFILES),
                     help="which corpus's nature/expectation boilerplate to use in the one-pager + Slack message")
    ap.add_argument("--scope-note", default="", dest="scope_note",
                     help="one-off sentence describing this specific submission, shown at the top of Scope")
    args = ap.parse_args()
    profile = PROFILES[args.profile]

    bundle_dir = Path(args.bundle_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    only = {t.strip() for t in args.only.split(",") if t.strip()} or None
    stamp = args.stamp or _dt.date.today().strftime("%d%m%Y")

    if not bundle_dir.is_dir():
        sys.exit(f"bundle dir not found: {bundle_dir}")
    provenance = load_manifest_provenance(bundle_dir)
    results = convert_tasks(bundle_dir, out_dir, args.prefix, only, provenance)
    if not results:
        sys.exit(f"no task_<id> folders found in {bundle_dir}")

    docx_path = out_dir / f"QCR_{args.dataset_name}_{stamp}.docx"
    build_one_pager(docx_path, args.dataset_name, stamp, results, args.contact, profile,
                     provenance.get("sections"), args.scope_note)
    build_slack_message(out_dir / "slack_message.md", args.dataset_name, stamp, results, args.deadline, profile,
                         args.scope_note)
    build_manifest(out_dir / "SUBMISSION.md", args.dataset_name, stamp, results)

    ok = sum(1 for r in results if r[1])
    failed = len(results) - ok
    print(f"converted {ok}/{len(results)} tasks -> {out_dir / 'rewardkit'}")
    if failed:
        print(f"  {failed} FAILED conversion — see {out_dir / 'SUBMISSION.md'}")
    print(f"one-pager -> {docx_path}")
    print(f"slack message -> {out_dir / 'slack_message.md'}")
    print(f"manifest -> {out_dir / 'SUBMISSION.md'}")
    sys.exit(1 if failed and ok == 0 else 0)


if __name__ == "__main__":
    main()
