#!/usr/bin/env python3
"""build_audit.py <short_task_id>

Generic per-task QC audit builder. Reads:
  runs/run_10_v2/audit_<id>.json        (gate findings + judge responses)
  runs/run_10_v2/artifacts_<id>.json    (extracted text + rubric; for reference)
  assessments_<id>.json                 (hand-authored: verdict_computation, summary,
                                          and per-gate {call, assessment, verify})
and writes runs/run_10_v2/AUDIT_<id>.docx.

The gate definitions below are shared (spec-derived). The analysis is per task.
"""
import json, os, sys
from pathlib import Path
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

HERE = Path(__file__).parent
RUN = HERE / os.environ.get("AUDIT_RUN", "runs/run_10_v2")
RUN_LABEL = os.environ.get("AUDIT_RUN", "runs/run_10_v2").split("/")[-1]
short = sys.argv[1]
A = json.loads((RUN / f"audit_{short}.json").read_text())
ASMT = json.loads((HERE / f"assessments_{short}.json").read_text())

# Shared gate definitions (from the v18 spec).
GATE_DEF = {
    "input_file_authenticity": "Whether the input files look like real artifacts from a real workflow or look synthesised. The gate's rubric treats generic placeholders, perfect regularity, and rounded numbers as synthetic markers.",
    "feasibility_and_clarity": "Whether the task is doable within its stated scope and given inputs, and whether two competent professionals would interpret the request the same way.",
    "self_containedness": "Whether the task can be solved from the instruction and inputs alone, or implicitly requires things the agent does not have: external context, credentials, network access, or undocumented domain knowledge.",
    "professional_complexity": "Whether the task needs genuine professional judgment (synthesis across documents, weighing tradeoffs, domain expertise) or a non-expert could produce the same answer by mechanically following a template.",
    "instruction_input_consistency": "Whether the instruction matches the inputs provided: every file or data element the instruction references should be locatable in the inputs.",
    "verifier_rubric_clarity": "Across all rubrics, whether each criterion is stated clearly enough that two judges would reach the same verdict on the same solution.",
    "verifier_rubric_specificity": "Whether rubrics ask for something observable rather than a vague qualitative judgment the grader has to invent.",
    "verifier_rubric_construct_validity": "Whether the rubrics measure the quality they claim to, rather than a proxy that happens to correlate (for example, grading layout the prompt never requested).",
    "verifier_count_in_range": "Programmatic. Whether the verifier count falls within the configured range of 6 to 20.",
}

NAVY = RGBColor(0x1F, 0x38, 0x64)
GREY = RGBColor(0x55, 0x55, 0x55)
RED = RGBColor(0xB0, 0x00, 0x00)


def shade(cell, hex_fill):
    sh = OxmlElement("w:shd"); sh.set(qn("w:val"), "clear"); sh.set(qn("w:fill"), hex_fill)
    cell._tc.get_or_add_tcPr().append(sh)


def set_widths(table, widths):
    table.autofit = False
    for row in table.rows:
        for i, w in enumerate(widths):
            row.cells[i].width = w


def runp(p, text, bold=False, italic=False, size=None, color=None):
    r = p.add_run(text); r.bold = bold; r.italic = italic
    if size: r.font.size = Pt(size)
    if color: r.font.color.rgb = color
    return r


def mono_block(doc, text, max_chars=None):
    truncated = max_chars and len(text) > max_chars
    body = (text[:max_chars] + "\n…") if truncated else text
    p = doc.add_paragraph(); p.paragraph_format.left_indent = Inches(0.2)
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run(body); r.font.name = "Consolas"; r.font.size = Pt(8)
    r.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
    if truncated:
        n = doc.add_paragraph()
        runp(n, f"[shown: first {max_chars:,} of {len(text):,} characters]", italic=True, size=8, color=GREY)


def main():
    doc = Document()
    doc.styles["Normal"].font.name = "Arial"; doc.styles["Normal"].font.size = Pt(10.5)
    sec = doc.sections[0]; sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    for m in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(sec, m, Inches(1))
    for h, sz in (("Heading 1", 17), ("Heading 2", 13), ("Heading 3", 11.5)):
        s = doc.styles[h]; s.font.name = "Arial"; s.font.color.rgb = NAVY; s.font.size = Pt(sz); s.font.bold = True

    # Header
    doc.add_heading("QC Gate Audit", level=0)
    p = doc.add_paragraph(); runp(p, f"Task {A['task_id']}", bold=True, size=12)
    p = doc.add_paragraph()
    runp(p, "Sector: ", bold=True); runp(p, A["sector"])
    runp(p, "    Occupation: ", bold=True); runp(p, A["occupation"])
    p = doc.add_paragraph()
    runp(p, "Pipeline verdict: ", bold=True); runp(p, A["verdict"], bold=True, color=RED)
    runp(p, "    Source: ", bold=True)
    runp(p, f"gdpval-assess v18.5, {RUN_LABEL} (gpt-5.5 + gemini-3.1-pro)", size=9, color=GREY)
    doc.add_paragraph(
        "This document audits every quality gate the pipeline ran on the task. For each flagged "
        "gate it states what the gate evaluates, the exact task data to verify against, the verbatim "
        "response from each judge, and an audit assessment with a line for the auditor's own verdict."
    )

    # A. Task under audit
    doc.add_heading("A. The task under audit", level=1)
    doc.add_heading("Prompt (verbatim)", level=3)
    q = doc.add_paragraph(); q.paragraph_format.left_indent = Inches(0.25)
    runp(q, A["prompt"].strip(), italic=True)
    doc.add_heading("Files", level=3)
    p = doc.add_paragraph()
    runp(p, f"Input files ({len(A['reference_files'])}): ", bold=True)
    runp(p, ", ".join(A["reference_files"]), size=9.5)
    p = doc.add_paragraph()
    runp(p, f"Deliverables ({len(A['deliverable_files'])}): ", bold=True)
    runp(p, ", ".join(A["deliverable_files"]), size=9.5)
    p = doc.add_paragraph()
    runp(p, "Rubric: ", bold=True); runp(p, f"{A['n_rubric_items']} criteria (adapted from the GDPval rubric).")
    doc.add_paragraph(
        "Each flagged gate in Section C inlines the specific artifact text its judgment rests on, "
        "so the call can be checked without leaving the page."
    )

    # B. Verdict computation
    doc.add_heading("B. How the verdict was computed", level=1)
    doc.add_paragraph(ASMT["verdict_computation"])

    # C. Flagged gates
    doc.add_heading("C. Flagged gates (severity 2 and above)", level=1)
    flagged = [f for f in A["findings"] if f["severity"] >= 2]
    flagged.sort(key=lambda f: (f["gate_role"] != "blocking", -f["severity"]))
    for f in flagged:
        dim = f["dimension"]; g = ASMT["gates"].get(dim, {})
        doc.add_heading(f["dimension_name"] or dim, level=2)
        p = doc.add_paragraph()
        runp(p, "Severity ", bold=True); runp(p, str(f["severity"]), bold=True, color=RED)
        runp(p, f"   ·   role: {f['gate_role']}   ·   fixability: {f['fixability']}   ·   "
                f"judges agreed: {'yes' if f['judges_agreed'] else 'NO'}", size=9.5, color=GREY)
        p = doc.add_paragraph(); runp(p, "What this gate evaluates: ", bold=True)
        runp(p, GATE_DEF.get(dim, ""))
        if g.get("verify"):
            p = doc.add_paragraph()
            runp(p, "Verify against (from the task’s own data):", bold=True, color=NAVY)
            for label, txt in g["verify"]:
                lp = doc.add_paragraph(); runp(lp, label, italic=True, size=9, color=GREY)
                mono_block(doc, txt)
        if f["judges"]:
            doc.add_paragraph().add_run("Judge responses (verbatim):").bold = True
            tbl = doc.add_table(rows=1, cols=4); tbl.style = "Table Grid"; tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
            for i, h in enumerate(("Judge", "Sev", "Conf", "Justification (verbatim)")):
                c = tbl.rows[0].cells[i]; c.text = ""; rp = c.paragraphs[0].add_run(h)
                rp.bold = True; rp.font.size = Pt(9.5); shade(c, "1F3864"); rp.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            for j in f["judges"]:
                row = tbl.add_row().cells
                row[0].paragraphs[0].add_run(j["model"]).font.size = Pt(9)
                row[1].paragraphs[0].add_run(str(j["severity"])).font.size = Pt(9)
                row[2].paragraphs[0].add_run(j["confidence"] or "").font.size = Pt(9)
                jr = row[3].paragraphs[0].add_run(j["justification"] or "(none)"); jr.font.size = Pt(9)
                if j.get("evidence_quote"):
                    ep = row[3].add_paragraph()
                    er = ep.add_run(f"Evidence: “{j['evidence_quote']}”")
                    er.italic = True; er.font.size = Pt(8.5); er.font.color.rgb = GREY
                    src = j.get("evidence_source")
                    note = ("source: " + ", ".join(src)) if src else "⚠ not located in task data"
                    sr = ep.add_run(f"  [{note}]")
                    sr.font.size = Pt(8); sr.font.color.rgb = (NAVY if src else RED)
            set_widths(tbl, [Inches(1.35), Inches(0.5), Inches(0.7), Inches(3.95)])
        p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(6)
        runp(p, "Audit assessment: ", bold=True); runp(p, g.get("call", ""), bold=True, color=RED)
        doc.add_paragraph(g.get("assessment", ""))
        p = doc.add_paragraph()
        runp(p, "Auditor verdict: ", bold=True)
        runp(p, "☐ agree   ☐ over-call   ☐ genuine   ☐ other:  ______________________________", color=GREY)

    # D. Passing gates
    doc.add_heading("D. Gates that passed (severity 0 to 1)", level=1)
    doc.add_paragraph(
        "These gates did not flag the task at a blocking level. Both judges' severities are shown so "
        "approvals are auditable too. Gates marked not applicable were skipped by precondition."
    )
    tbl = doc.add_table(rows=1, cols=4); tbl.style = "Table Grid"
    for i, h in enumerate(("Gate", "Role", "Final sev", "Judge severities")):
        c = tbl.rows[0].cells[i]; c.text = ""; rp = c.paragraphs[0].add_run(h)
        rp.bold = True; rp.font.size = Pt(9.5); shade(c, "1F3864"); rp.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    for f in [x for x in A["findings"] if x["severity"] < 2]:
        skipped = "not applicable" if f.get("skipped_because") else ""
        js = ", ".join(f"{j['model'].split('-')[0]}:{j['severity']}" for j in f["judges"]) or "programmatic"
        vals = [f["dimension"], f["gate_role"] or "", "n/a" if skipped else str(f["severity"]), skipped or js]
        cells = tbl.add_row().cells
        for i, v in enumerate(vals):
            cells[i].paragraphs[0].add_run(v).font.size = Pt(8.5)
    set_widths(tbl, [Inches(2.7), Inches(1.3), Inches(0.9), Inches(1.6)])

    # E. Summary + sign-off
    doc.add_heading("E. Audit summary", level=1)
    doc.add_paragraph(ASMT["summary"])
    doc.add_heading("Sign-off", level=3)
    for label in ("Auditor:", "Date:", "Agree with the audit assessment above? (yes / no / partial):", "Notes:"):
        p = doc.add_paragraph(); runp(p, label + "  ", bold=True)
        runp(p, "______________________________________________", color=GREY)

    out = RUN / f"AUDIT_{short}.docx"
    doc.save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
