#!/usr/bin/env python3
"""extract_audit_data.py <short_task_id>

Pull everything an audit needs for one task from the run output and corpus:
  runs/run_10_v2/audit_<id>.json      - all gate findings + both judges' verbatim responses
  runs/run_10_v2/artifacts_<id>.json  - extracted input/deliverable text + full rubric

Generic over task id; the per-gate assessment prose is authored separately.
"""
import glob, json, os, re, shutil, subprocess, sys
from pathlib import Path


def _norm(s):
    """Aggressive normalization for matching: keep only lowercase alphanumerics.
    PDF extraction mangles whitespace and punctuation (e.g. 'FROM :' vs 'FROM:',
    per-character spacing, smart quotes), so anything short of stripping all
    non-alphanumerics produces false 'not found' results."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def locate_evidence(quote, sources):
    """Return the source labels whose normalized text contains the evidence quote.
    Returns [] only when the quote genuinely cannot be located in anything the
    judge could read (prompt, inputs, deliverables, rubric)."""
    nq = _norm(quote)
    if not nq:
        return []
    hits = [label for label, text in sources if nq in text]
    if not hits and len(nq) > 40:  # try the head, in case the quote was truncated
        hits = [label for label, text in sources if nq[:40] in text]
    return hits

HERE = Path(__file__).parent
RUN = HERE / os.environ.get("AUDIT_RUN", "runs/run_10_v2")
CORPUS = HERE / os.environ.get("AUDIT_CORPUS", "corpus_10")
short = sys.argv[1]


def extract(p):
    """Text extraction matching what the pipeline's loader feeds the judges:
    PDFs via pdftotext/pypdf, spreadsheets via openpyxl, Word via python-docx."""
    ext = Path(p).suffix.lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
            out = []
            for ws in wb.worksheets:
                out.append(f"# sheet: {ws.title}")
                for row in ws.iter_rows(values_only=True):
                    cells = [str(c) for c in row if c is not None]
                    if cells:
                        out.append("\t".join(cells))
            return "\n".join(out).strip()
        except Exception as e:
            return f"[xlsx extract failed: {e}]"
    if ext == ".docx":
        try:
            import docx
            d = docx.Document(p)
            parts = [para.text for para in d.paragraphs if para.text.strip()]
            for t in d.tables:
                for r in t.rows:
                    cells = [c.text for c in r.cells if c.text.strip()]
                    if cells:
                        parts.append("\t".join(cells))
            return "\n".join(parts).strip()
        except Exception as e:
            return f"[docx extract failed: {e}]"
    if ext in (".pdf",):
        if shutil.which("pdftotext"):
            try:
                t = subprocess.run(["pdftotext", "-q", "-layout", p, "-"],
                                   capture_output=True, text=True, timeout=60).stdout.strip()
                if t:
                    return t
            except Exception:
                pass
        try:
            import pypdf
            return "\n".join((pg.extract_text() or "") for pg in pypdf.PdfReader(p).pages).strip()
        except Exception as e:
            return f"[pdf extract failed: {e}]"
    return f"[no extractor for {ext}]"


def main():
    review = json.loads((RUN / "batch_review.json").read_text())
    sample = next(s for s in review["samples"] if s["sample_id"] == f"task_{short}")
    rows = {r["task_id"]: r for r in json.loads((HERE / "rows.json").read_text())}
    tid = next(k for k in rows if k.startswith(short))
    row = rows[tid]

    # 1) Build artifacts first so evidence quotes can be located against them.
    tdir = CORPUS / f"task_{short}"
    art = {"inputs": {}, "deliverables": {}}
    for p in sorted(glob.glob(f"{tdir}/environment/*")):
        t = extract(p); art["inputs"][os.path.basename(p)] = {"chars": len(t), "text": t}
    for p in sorted(glob.glob(f"{tdir}/solution/golden_outputs/*")):
        t = extract(p); art["deliverables"][os.path.basename(p)] = {"chars": len(t), "text": t}
    art["rubric_pretty"] = row["rubric_pretty"]
    art["rubric_items"] = json.loads(row["rubric_json"])
    (RUN / f"artifacts_{short}.json").write_text(json.dumps(art, indent=2))

    # Every source a judge could have read, whitespace-normalized for matching.
    sources = [("prompt", _norm(row["prompt"]))]
    sources += [(f"input: {n}", _norm(d["text"])) for n, d in art["inputs"].items()]
    sources += [(f"deliverable: {n}", _norm(d["text"])) for n, d in art["deliverables"].items()]
    sources += [("rubric", _norm(row["rubric_pretty"]))]

    # 2) Build findings, locating each judge's evidence quote in the sources.
    audit = {
        "task_id": tid, "sector": row["sector"], "occupation": row["occupation"],
        "verdict": sample["verdict"], "one_line": sample.get("one_line"),
        "review_required_because": sample.get("review_required_because"),
        "prompt": row["prompt"],
        "reference_files": [p.split("/")[-1] for p in row["reference_files"]],
        "deliverable_files": [p.split("/")[-1] for p in row["deliverable_files"]],
        "n_rubric_items": len(json.loads(row["rubric_json"])),
        "findings": [],
    }
    unlocated = []  # (dim, model) for sev>=2 quotes not found anywhere
    for f in sample["all_findings"]:
        judges = []
        for a in (f.get("raw_attempts") or []):
            j = {kk: a.get(kk) for kk in ("model", "severity", "confidence", "applicable",
                                          "headline", "justification", "evidence_quote",
                                          "fixability", "error")}
            j["evidence_source"] = locate_evidence(a.get("evidence_quote"), sources)
            if a.get("evidence_quote") and not j["evidence_source"] and f["severity"] >= 2:
                unlocated.append((f["dimension"], a.get("model")))
            judges.append(j)
        audit["findings"].append({
            k: f.get(k) for k in ("dimension", "dimension_name", "gate_role", "applicable",
                                  "severity", "fixability", "confidence", "judges_agreed",
                                  "headline", "detail", "evidence_quote",
                                  "demoted_because", "skipped_because")
        } | {"judges": judges})
    (RUN / f"audit_{short}.json").write_text(json.dumps(audit, indent=2))

    print(f"task_{short}: verdict={audit['verdict']}  findings={len(audit['findings'])}")
    print(f"inputs={len(art['inputs'])} deliverables={len(art['deliverables'])} rubric={audit['n_rubric_items']}")
    print("sev>=2 gates (with judge evidence source):")
    for f in audit["findings"]:
        if f["severity"] >= 2:
            js = [(j["model"].split("-")[0], j["severity"]) for j in f["judges"]]
            print(f"  {f['dimension']:42s} sev{f['severity']} role={f['gate_role']:9s} agree={f['judges_agreed']} {js}")
            for j in f["judges"]:
                if j.get("evidence_quote"):
                    src = ", ".join(j["evidence_source"]) or "*** NOT LOCATED IN TASK DATA ***"
                    print(f"        {j['model'].split('-')[0]:7s} evidence -> {src}")
    if unlocated:
        print("\n⚠ sev>=2 evidence quotes NOT located in any source (verify by hand):")
        for dim, model in unlocated:
            print(f"   {dim}  ({model})")


if __name__ == "__main__":
    main()
