#!/usr/bin/env python3
"""Reward-signal gate: the mechanisms behind the expert QC feedback, made deterministic.

Calibrated on the 12-task QCR_EKW_16092026 expert review (48 findings — see
dataos_qc_runs/74-ekw-sprint/feedback_16092026/_expert/EXPERT_FEEDBACK_GAP_ANALYSIS.md).
Each lint either decides a defect outright (fail) or produces a CANDIDATE that the
fixer must disposition in ``reports/<task>_TRACE.json`` (an undispositioned candidate
is a fail). Nothing here can be silently skipped.

  G1 source_blind      fidelity/traceability criterion sourced from a single deliverable
  G2 phrase_pin        PASS clause requires a quoted phrase / ID / label absent from the instruction
  G3 numeric_pin       numeric literal pinned without tolerance, "exactly", or pinned in >= 2 criteria
  G4 fail_contradiction FAIL-list term is required by the instruction, present as a source header,
                        or rewarded by a sibling criterion's PASS clause
  G5 duplicate_grading two prompts with high n-gram overlap (same fact graded twice)
  G6 uncached_formulas package extractor cannot recalculate uncached formulas (+ exposed weight
                        measured on real-run workbooks when --evidence is given)
  G7 compound          >= 4 separately checkable conditions in one pass/fail
  G8 coverage_ledger   reports/<task>_DECISIONS.json: every source-forced decision maps to a
                        criterion (or an explicit not-graded reason); false-accept sweep present
  G9 judge_samples     config.models lists < 3 judge samples (policy 2026-09-18: majority of 3)

Dispositions live in reports/<task>_TRACE.json, either per criterion
(``criteria[i].dispositions = {"G2": "...", ...}``) or top-level
(``dispositions = {"G3:v4": "...", ...}``). A disposition must start with one of
``split`` / ``widened`` / ``re-sourced`` / ``tolerance-added`` / ``removed`` /
``not-a-defect:`` (with a reason) / ``domain-decision:``.

Run: reward_signal_gate.py --root <task_dir|batch_dir> [--evidence <with_runs dir>] [--out report.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

FIDELITY_RE = re.compile(
    r"\b(invent(ed|s|ing)?|fabricat(ed|es|ion)|made[- ]up|traceab(le|ility)|trace[sd]? (back )?to|supported by the (source|attached|provided)|"
    r"consistent with the (source|attached|packet|export|brief|agreement|filing|10-k|policy)|per the (export|packet|bulletin|source|brief)|"
    r"attached (materials?|files?|source|packet|documents?)|source (documents?|materials?|packet|files?|data)|external (data|benchmark|source)|"
    r"outside (data|source|information)|not (in|from) the (provided|attached|source)|unsupported (by|claim)|matches? the (source|export|packet)|"
    r"(only if|unless|provided that|without a) (signed|written|executed|countersigned|received|approved|confirmed)[^.;]{0,40}(rights?|approval|permission|amendment|confirmation|authori[sz]ation|sign-?off|agreement)|"
    r"(rights?|approval|permission|amendment|confirmation|authori[sz]ation|sign-?off) (are|is|has been|have been|were|was) (signed|received|granted|executed|confirmed|obtained))\b",
    re.I,
)
TOLERANCE_RE = re.compile(
    r"(approximately|approx\.?|about|roughly|~|±|\+/-|within|tolerance|between|range|at least|at most|no more than|no fewer than|no less than|"
    r"greater than|less than|or more|or fewer|or higher|or lower|band|plus or minus|around|near|close to|do not fail|not fail|rounded|rounding|"
    r"of the order|order of|>=|<=|≥|≤|minimum|maximum|up to|over|under|exceed|below|above|floor|cap)",
    re.I,
)
REPRODUCE_RE = re.compile(r"\b(equal(s|ling)? to|equals?|of|is|be|reports?|states?|shows?|produc(e|es|ing)|total(s|ling)? (to|of)|reach(es|ing)?|comes? to|match(es|ing)?|=)\s*$|^\s*(is|as|in|for)\b", re.I)
EXACT_RE = re.compile(r"\b(exactly|precisely|to the cent|to the penny|exact(ly)? (figure|value|amount|match))\b", re.I)
NUM_RE = re.compile(r"(?<![A-Za-z_\-])(?:\$|€|£)?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![A-Za-z_\-.\d])\d+\.\d{2,}(?![\d%])|(?<![A-Za-z_\-.\d,])\d{4,}(?![\d,])")
YEAR_RE = re.compile(r"^(19|20)\d{2}$")
PHRASE_REQ_RE = re.compile(
    r"\b(the (exact|specific|precise) (term|phrase|label|wording|words?|heading|section title)s?)\b|\buse[sd]? the (term|phrase|label|word)s?\b|"
    r"\b(labell?ed|named|titled|headed) (exactly )?as\b|\bby (its|their) (id|identifier|code)\b|\bverbatim\b|\bword[- ]for[- ]word\b",
    re.I,
)
QUOTED_RE = re.compile(r"\b(state[sd]?|say[s]?|use[sd]?|label(?:l?ed)?|name[sd]?|call(?:ed|s)?|term(?:ed)?|word(?:ed|ing)?|phrase[sd]?|titled|headed|reads?)\s+(?:it\s+|as\s+|the\s+)?[\"“]([^\"”]{3,60})[\"”]", re.I)
ID_REQ_RE = re.compile(r"\b(explicitly|expressly)\s+(identif\w*|nam\w*|list\w*|cit\w*)\b[^.;]{0,60}?\b([A-Z]{1,5}-[A-Z0-9]{2,10})\b|\bby (its|their) (id|identifier|code)\b")
ID_RE = re.compile(r"\b[A-Z]{1,5}-[A-Z0-9]{2,10}(?:-[A-Z0-9]{1,6})?\b")
REQ_SENT_RE = re.compile(r"\b(must|require[sd]?|work out|include|produce|determine|state|show|provide|present|prepare|build|report|calculate|compute|deliver|identify|explain|address)\b", re.I)
FAIL_SPLIT_RE = re.compile(r"\bFAIL(?:S)?\b(?: only)? if\b|\bFail(?:s)?\b(?: only)? if\b|\bfail(?:s)?\b(?: only)? if\b")
FAIL_ITEMS_RE = re.compile(r"\b(?:introduc\w*|includ\w*|add\w*|cit\w*|import\w*|rel(?:y|ies) on|us(?:e|es|ing)|contain\w*|present\w*|assert\w*|recommend\w*|propos\w*|expand\w*|mention\w*|report\w*|show\w*)\b\s+(.{5,900}?)(?=\bPASS\b|\bor if\b|\. [A-Z]|$)", re.I | re.S)
STOP = set("the a an and or of to in on for with by from that this these those any all its their it is are be been not no than as at into over under per which who whose what when where such e.g. i.e. etc including include includes rather only also each every some one two three via within without about above below other another same different more less most least new own".split())
COMPOUND_MAX = 5
DOC_NOUN_RE = re.compile(
    r"\b(per|in|from|against|according to|matches|shown in|documented in|recorded in|stated in|listed in|based on|reflected in|confirmed by|supported by|consistent with)\s+(the|its|each)\s+"
    r"(\w+\s){0,3}?(export|bulletin|packet|brief|agreement|statement|filing|10-k|10-q|form 10|policy|register|ledger|trial balance|schedule|estoppel|order|handoff|report|master|actuals|source data|source files?|rent roll|data room|assumptions?|memo(randum)?|pdf)\b",
    re.I,
)
STATUS_RE = re.compile(r"\b(execution|system|field|build|fixture|dc|store|inventory|hold|release|approval|signed|authorization)[- ]status\b", re.I)
DELIV_NOUN = {"docx": r"\b(the|its|their) (memo|note|letter|report|deck|narrative|write-?up|summary document)\b", "xlsx": r"\b(the|its|their) (workbook|model|spreadsheet|schedule tab|tracker|action file|workpaper)\b", "pptx": r"\b(the|its|their) (deck|presentation|slides?)\b", "pdf": r"\b(the|its|their) (pdf|report document)\b"}
DUP_JACCARD = 0.35
DISPO_OK = re.compile(r"^(split|widened|re-sourced|tolerance-added|removed|not-a-defect:|domain-decision:)", re.I)


# ----------------------------------------------------------------------------- package model

def resolve_package_dir(task_dir: Path) -> Path | None:
    if (task_dir / "tests").is_dir():
        return task_dir
    if (task_dir / "task_files").is_dir():
        return task_dir / "task_files"
    revs = sorted(task_dir.glob("rev_*/task_files"))
    return revs[-1] if revs else None


def task_name_of(task_dir: Path, package: Path) -> str:
    n = task_dir.name if task_dir.name.startswith("task_") else package.parent.name
    return re.sub(r"_fixed$", "", n)


def load_criteria(package: Path) -> tuple[list[dict], dict]:
    """Returns (criteria, config). Each criterion: name, prompt, weight, sources[list of str paths], kind."""
    vj = package / "tests" / "verifier.json"
    out: list[dict] = []
    if vj.is_file():
        j = json.loads(vj.read_text(encoding="utf-8"))
        for c in j.get("verifiers", []):
            a = c.get("assertion", {})
            src = c.get("source", {})
            paths: list[str] = []
            f = src.get("file", {}) if src.get("type") == "file" else {}
            args = f.get("arguments", {}) if isinstance(f, dict) else {}
            if "path" in args:
                paths.append(str(args["path"]))
            for p in args.get("paths", []) or []:
                paths.append(str(p))
            for p in args.get("files", []) or []:
                paths.append(str(p if isinstance(p, str) else p.get("path", "")))
            out.append({
                "name": c["name"], "kind": a.get("type", "rubric"),
                "prompt": a.get("rubric", {}).get("prompt", "") if a.get("type") == "rubric" else "",
                "weight": float(c.get("metadata", {}).get("weight", 0) or 0),
                "sources": paths, "command": str(f.get("command", "")), "stype": str(f.get("type", "")),
            })
        return out, j.get("config", {})
    import tomllib
    for toml in sorted((package / "tests").glob("deliverables_*/judge.toml")):
        try:
            data = tomllib.loads(toml.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            continue
        files = [str(x) for x in (data.get("judge", {}) or {}).get("files", [])]
        for c in data.get("criterion", []) or data.get("criteria", []) or []:
            out.append({"name": f"{toml.parent.name}:{c.get('name', '?')}", "kind": "rubric",
                        "prompt": str(c.get("description", "")), "weight": float(c.get("weight", 0) or 0),
                        "sources": files, "command": "judge.toml", "stype": "rewardkit"})
    return out, {}


def is_deliverable_path(p: str, package: Path) -> bool:
    if p.startswith("output/") or "/output/" in p:
        return True
    inputs = {x.name for x in (package / "environment" / "initial_workspace").rglob("*") if x.is_file()} if (package / "environment" / "initial_workspace").is_dir() else set()
    return Path(p).name not in inputs and p.startswith("/app/")


def split_pass_fail(prompt: str) -> tuple[str, str]:
    m = FAIL_SPLIT_RE.search(prompt)
    if not m:
        return prompt, ""
    return prompt[: m.start()], prompt[m.start():]


def read_instruction(package: Path) -> str:
    p = package / "instruction.md"
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def source_terms(package: Path) -> dict[str, set[str]]:
    """Header-ish strings from every source file: xlsx first rows + docx/pdf text tokens (lowercased)."""
    terms: dict[str, set[str]] = {}
    for d in ("environment/data", "environment/initial_workspace"):
        base = package / d
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if not f.is_file():
                continue
            words: set[str] = set()
            try:
                if f.suffix.lower() in (".xlsx", ".xlsm"):
                    from openpyxl import load_workbook
                    wb = load_workbook(f, read_only=True, data_only=True)
                    for ws in wb.worksheets:
                        for i, row in enumerate(ws.iter_rows(values_only=True)):
                            if i > 6:
                                break
                            for v in row:
                                if isinstance(v, str) and 2 < len(v) < 60:
                                    words.add(v.strip().lower())
                    wb.close()
                elif f.suffix.lower() == ".docx":
                    with zipfile.ZipFile(f) as z:
                        xml = z.read("word/document.xml").decode("utf-8", "replace")
                    txt = re.sub(r"<[^>]+>", " ", xml)
                    words |= {w for w in re.findall(r"[A-Za-z][A-Za-z\- %]{3,40}", txt)[:5000]}
                    words = {w.strip().lower() for w in words}
                elif f.suffix.lower() == ".pdf":
                    from pypdf import PdfReader
                    txt = " ".join((pg.extract_text() or "") for pg in PdfReader(str(f)).pages[:30])
                    words = {w.strip().lower() for w in re.findall(r"[A-Za-z][A-Za-z\- %]{3,40}", txt)[:8000]}
            except Exception:  # noqa: BLE001
                continue
            terms[f.name] = words
    return terms


def load_trace(package: Path, task: str) -> dict:
    for parent in [package, *package.parents][:4]:
        p = parent / "reports" / f"{task}_TRACE.json"
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
    return {}


def dispositions(trace: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in trace.get("criteria", []) if isinstance(trace, dict) else []:
        for k, v in (c.get("dispositions") or {}).items():
            out[f"{k}:{c.get('name')}"] = str(v)
    for k, v in (trace.get("dispositions") or {}).items() if isinstance(trace, dict) else []:
        out[k] = str(v)
    return out


# ----------------------------------------------------------------------------- lints

def g1_source_blind(crits: list[dict], package: Path) -> list[dict]:
    out = []
    for c in crits:
        if c["kind"] != "rubric":
            continue
        non_deliv = [p for p in c["sources"] if not is_deliverable_path(p, package)]
        ev: list[str] = []
        if not non_deliv:
            m = FIDELITY_RE.search(c["prompt"])
            if m:
                ev.append(f"fidelity claim '{m.group(0)}' graded from deliverables only")
            m = DOC_NOUN_RE.search(c["prompt"]) or STATUS_RE.search(c["prompt"])
            if m:
                ev.append(f"references a source document/status ('{m.group(0)}') the judge never receives")
        # cross-deliverable: names another deliverable type that is not among its sources
        exts = {Path(p).suffix.lower().lstrip(".") for p in c["sources"]}
        if exts and len(c["sources"]) == 1:
            for ext, pat in DELIV_NOUN.items():
                if ext not in exts and re.search(pat, c["prompt"], re.I):
                    m = re.search(pat, c["prompt"], re.I)
                    ev.append(f"cross-deliverable: mentions '{m.group(0)}' but only sources {c['sources']}")
                    break
        if ev:
            out.append({"criterion": c["name"], "weight": c["weight"], "evidence": ev + [f"sources={c['sources'] or '[]'}"]})
    return out


def g2_phrase_pin(crits: list[dict], instruction: str) -> list[dict]:
    ins = instruction.lower()
    out = []
    for c in crits:
        if c["kind"] != "rubric":
            continue
        pas, _ = split_pass_fail(c["prompt"])
        hits = []
        for m in PHRASE_REQ_RE.finditer(pas):
            hits.append(pas[max(0, m.start() - 20): m.end() + 60].replace("\n", " "))
        for m in QUOTED_RE.finditer(pas):
            q = m.group(2)
            if q.lower() not in ins and not re.fullmatch(r"[\d\W]+", q):
                hits.append(f"must {m.group(1)} '{q}' — phrase not in instruction")
        for m in ID_REQ_RE.finditer(pas):
            hits.append(f"explicit-ID requirement: '{pas[max(0, m.start()-10): m.end()+20].strip()}'")
        if hits:
            out.append({"criterion": c["name"], "weight": c["weight"], "evidence": hits[:6]})
    return out


def g3_numeric_pin(crits: list[dict], instruction: str) -> list[dict]:
    out = []
    seen: dict[str, list[str]] = defaultdict(list)
    for c in crits:
        if c["kind"] != "rubric":
            continue
        text = c["prompt"]
        hits = []
        if EXACT_RE.search(text):
            hits.append(f"exact-match language: '{EXACT_RE.search(text).group(0)}'")
        pas, _ = split_pass_fail(text)
        for m in NUM_RE.finditer(pas):
            lit = m.group(0)
            core = re.sub(r"[^\d.]", "", lit)
            if YEAR_RE.match(core) or core in ("", ".") or re.fullmatch(r"\d{4}", core) and 1900 <= int(core) <= 2100:
                continue
            ctx = pas[max(0, m.start() - 90): m.end() + 90]
            requires = REPRODUCE_RE.search(pas[max(0, m.start() - 60): m.start()]) or REPRODUCE_RE.search(pas[m.end(): m.end() + 40])
            if requires and len(core.replace(".", "")) >= 5:
                seen[core].append(c["name"])
            cents = bool(re.search(r"\.\d{2}(?!\d)", lit))
            if (requires or cents) and not TOLERANCE_RE.search(ctx):
                hits.append(f"'{lit}' must be reproduced with no tolerance in ±90 chars")
        if hits:
            out.append({"criterion": c["name"], "weight": c["weight"], "evidence": hits[:6]})
    dup = [{"criterion": ",".join(sorted(set(v))), "weight": None, "evidence": f"literal {k} pinned in {len(set(v))} criteria (double grading)"} for k, v in seen.items() if len(set(v)) >= 2 and len(k) >= 4]
    return out + dup


def g4_fail_contradiction(crits: list[dict], instruction: str, sources: dict[str, set[str]]) -> list[dict]:
    req_sents = [s for s in re.split(r"(?<=[.!?])\s+|\n+", instruction) if REQ_SENT_RE.search(s)]
    req_text = " ".join(req_sents).lower()
    src_terms = set()
    for ws in sources.values():
        src_terms |= ws
    out = []
    for c in crits:
        if c["kind"] != "rubric":
            continue
        _, fail = split_pass_fail(c["prompt"])
        if not fail:
            continue
        items: list[str] = []
        for m in FAIL_ITEMS_RE.finditer(fail):
            seg = re.sub(r"\bany of the following\b[^:]*:", " ", m.group(1) or "")
            items += [x.strip(" ()") for x in re.split(r",|\bor\b|;|\([a-z]\)|\band\b", seg) if len(x.strip()) > 3]
        hits = []
        headers = sorted(t for t in src_terms if len(t.split()) <= 4)  # sorted: the quoted header must not vary run to run
        for it in items[:40]:
            words = [w for w in re.findall(r"[a-z][a-z\-]{3,}", it.lower()) if w not in STOP]
            if not words:
                continue
            key = " ".join(words[:3]) if len(words) >= 2 else words[0]
            probe = words[0] if len(words) == 1 else key
            if re.search(rf"\b{re.escape(probe)}\b", req_text):
                hits.append({"strength": "strong", "item": it[:80], "where": f"instruction requirement sentence contains '{probe}'"})
                continue
            hdr = next((h for h in headers if re.search(rf"\b{re.escape(probe)}\b", h)), None)
            if hdr and len(probe) >= 5:
                hits.append({"strength": "strong", "item": it[:80], "where": f"source header/term '{hdr}'"})
                continue
            for sib in crits:
                if sib["name"] == c["name"] or sib["kind"] != "rubric":
                    continue
                spas, _ = split_pass_fail(sib["prompt"])
                if len(words) >= 2 and key in spas.lower():
                    hits.append({"strength": "strong", "item": it[:80], "where": f"sibling {sib['name']} PASS text contains '{key}'"})
                    break
        if hits:
            out.append({"criterion": c["name"], "weight": c["weight"], "evidence": hits[:6]})
    return out


def _ngrams(text: str, n: int = 4) -> set[str]:
    w = [x for x in re.findall(r"[a-z0-9]+", text.lower()) if x not in STOP]
    return {" ".join(w[i: i + n]) for i in range(max(0, len(w) - n + 1))}


def _strip_shared_prefix(a: str, b: str) -> tuple[str, str]:
    """Strips a verbatim shared leading run of words from both prompts.

    A standing per-criterion SCOPE note (e.g. the cell-view/NaN-fallback clause the
    fix-task-from-review skill's G6 mechanism prepends to every criterion touching a
    workbook, task_382/task_388) is deliberately IDENTICAL boilerplate repeated at the
    front of every criterion in a deliverable group. That is a packaging/robustness
    fix, not two criteria grading the same fact -- but it inflates whole-prompt 4-gram
    Jaccard similarity for every pair that shares it, since dozens of identical words
    dominate the n-gram set regardless of how different the actual graded concept is.
    Stripping the shared leading words before n-gramming removes that artifact while
    leaving genuine content overlap (which does not start at word 0 identically across
    unrelated criteria) fully intact.
    """
    wa = re.findall(r"[A-Za-z0-9']+|[^\sA-Za-z0-9']", a)
    wb = re.findall(r"[A-Za-z0-9']+|[^\sA-Za-z0-9']", b)
    i = 0
    while i < len(wa) and i < len(wb) and wa[i].lower() == wb[i].lower():
        i += 1
    return " ".join(wa[i:]), " ".join(wb[i:])


def g5_duplicate(crits: list[dict]) -> list[dict]:
    out = []
    rub = [c for c in crits if c["kind"] == "rubric" and len(c["prompt"]) > 80]
    for i, a in enumerate(rub):
        for b in rub[i + 1:]:
            ra, rb = _strip_shared_prefix(a["prompt"], b["prompt"])
            ga, gb = _ngrams(ra), _ngrams(rb)
            if not ga or not gb:
                continue
            j = len(ga & gb) / len(ga | gb)
            if j >= DUP_JACCARD:
                out.append({"criterion": f"{a['name']},{b['name']}", "weight": a["weight"] + b["weight"], "evidence": f"4-gram Jaccard {j:.2f}"})
    return out


def g6_uncached(package: Path, crits: list[dict], evidence_root: Path | None, task: str) -> dict:
    lib = None
    for name in ("__verifier_lib", "verifier_lib"):
        p = package / "tests" / name / "sources" / "xlsx.py"
        if p.is_file():
            lib = p
            break
    res: dict = {"status": "skip", "evidence": []}
    if lib is None:
        return res
    txt = lib.read_text(encoding="utf-8", errors="replace")
    has_recalc = "_recalculated_copy_if_uncached" in txt or "_recompute_formula_map" in txt
    xlsx_weight = round(sum(c["weight"] for c in crits if c["stype"] == "xlsx" and c["command"] == "extract_text") + sum(c["weight"] for c in crits if c["command"] == "extract_many"), 4)
    res["evidence"].append(f"library recalculates uncached formulas: {has_recalc}; weight read through extract_text/extract_many on xlsx: {xlsx_weight}")
    res["status"] = "pass" if has_recalc else "fail"
    if not has_recalc:
        # I2 (QC batch 1-6 analysis, 2026-09-28): vendored-copy drift, not authoring. SCO-240 / GTM-178
        # carry the recalc; SCO-272 / FIN-385 / PHR-152 were vendored before it landed.
        res["evidence"].append(
            f"{lib.relative_to(package).as_posix()} lacks _recalculated_copy_if_uncached (vendored copy predates it). "
            "Fix: re-vendor verifier_lib into tests/ from the current rl_world_verifiers release"
        )
    if evidence_root is not None:
        try:
            from openpyxl import load_workbook
            runs = sorted(evidence_root.glob(f"{task}*/rev_*/evaluations/eval_*/eval_files/artifacts/workspace/output/*.xlsx"))
            for wbp in runs:
                wf = load_workbook(wbp, data_only=False, read_only=True)
                wv = load_workbook(wbp, data_only=True, read_only=True)
                nf = blank = 0
                for ws in wf.worksheets:
                    for rf, rv in zip(ws.iter_rows(), wv[ws.title].iter_rows()):
                        for cf, cv in zip(rf, rv):
                            if cf.data_type == "f":
                                nf += 1
                                if cv.value is None:
                                    blank += 1
                wf.close(); wv.close()
                run = wbp.parts[wbp.parts.index("evaluations") + 1] if "evaluations" in wbp.parts else wbp.name
                if nf and blank / nf > 0.5:
                    res["evidence"].append(f"{run}: {blank}/{nf} formula cells uncached -> ~{xlsx_weight} of weight extracts blank without recalc")
        except Exception as exc:  # noqa: BLE001
            res["evidence"].append(f"run scan error: {exc}")
    return res


def g7_compound(crits: list[dict]) -> list[dict]:
    out = []
    for c in crits:
        if c["kind"] != "rubric":
            continue
        pas, _ = split_pass_fail(c["prompt"])
        enum = len(set(re.findall(r"\(([a-h]|[ivx]{1,4}|\d)\)", pas)))
        ands = len(re.findall(r";\s*(?:and\s+)?|\band\b(?=[^()]*(?:\(|$))", re.sub(r"\([^)]*\)", "", pas)))
        n = max(enum, ands)
        if n >= COMPOUND_MAX:
            out.append({"criterion": c["name"], "weight": c["weight"], "evidence": f"~{n} separately checkable conditions in one PASS"})
    return out


def g8_ledger(package: Path, task: str, crits: list[dict]) -> dict:
    p = None
    for parent in [package, *package.parents][:4]:
        q = parent / "reports" / f"{task}_DECISIONS.json"
        if q.is_file():
            p = q
            break
    if p is None:
        return {"status": "fail", "evidence": ["reports/<task>_DECISIONS.json missing (decision ledger + false-accept sweep)"]}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "fail", "evidence": [f"unreadable: {exc}"]}
    names = {c["name"] for c in crits}
    ev = []
    decs = d.get("decisions", [])
    if not decs:
        ev.append("no decisions listed")
    for x in decs:
        crit = x.get("criterion") or x.get("criteria")
        if crit:
            missing = [n for n in ([crit] if isinstance(crit, str) else crit) if n not in names]
            if missing:
                ev.append(f"decision '{x.get('decision', '')[:60]}' maps to unknown criteria {missing}")
        elif not x.get("not_graded_reason"):
            ev.append(f"decision '{x.get('decision', '')[:60]}' has no criterion and no not_graded_reason")
    fa = d.get("false_accept_sweep")
    if fa is None:
        ev.append("false_accept_sweep missing")
    elif not isinstance(fa, list) or any(not isinstance(x, dict) for x in fa):
        # A task with no agent runs has nothing to sweep; the ledger must still say so as an empty
        # list (plus a free-text sibling key), never as a bare string -- iterating a string here
        # used to crash the whole gate with AttributeError instead of reporting the bad shape.
        ev.append(
            "false_accept_sweep must be a list of run objects "
            f"(got {type(fa).__name__}); use [] plus false_accept_sweep_status when no runs exist"
        )
    else:
        for x in fa:
            if x.get("wrong") and not (x.get("caught_by") or x.get("gap")):
                ev.append(f"run {x.get('run')} wrong but neither caught_by nor gap recorded")
    return {"status": "fail" if ev else "pass", "evidence": ev or [f"{len(decs)} decisions mapped; false-accept sweep over {len(fa)} run(s)"]}


def g9_judge(config: dict, genre: str, package: Path | None = None) -> dict:
    if genre == "rewardkit":
        # rewardkit has no sampling key; policy (2026-09-18) is a mean of 3 byte-identical judge
        # tomls per chunk, written by pipeline/tools/rewardkit_mean_of_3.py.
        bad = []
        for jt in sorted((package / "tests").glob("deliverables_*/judge.toml")) if package else []:
            for s in ("judge_s2.toml", "judge_s3.toml"):
                f = jt.parent / s
                if not f.is_file() or f.read_bytes() != jt.read_bytes():
                    bad.append(f"{jt.parent.name}/{s} missing or differs from judge.toml")
        if bad:
            return {"status": "fail", "evidence": bad[:6] + ["run pipeline/tools/rewardkit_mean_of_3.py <package>"]}
        return {"status": "pass", "evidence": ["rewardkit: 3 judge samples per chunk (mean of 3)"]}
    models = config.get("models") or []
    if len(models) < 3:
        return {"status": "fail", "evidence": [f"config.models has {len(models)} sample(s); policy is a majority of 3 (list the model 3x)"]}
    return {"status": "pass", "evidence": [f"{len(models)} judge samples"]}


def apply_dispositions(lint: str, cands: list[dict], dispo: dict[str, str]) -> dict:
    if not cands:
        return {"status": "pass", "evidence": ["no candidates"], "candidates": []}
    open_ = []
    for c in cands:
        names = str(c["criterion"]).split(",")
        d = next((dispo.get(f"{lint}:{n}") for n in names if dispo.get(f"{lint}:{n}")), None)
        c["disposition"] = d
        if not d or not DISPO_OK.match(d):
            open_.append(c["criterion"])
    st = "fail" if open_ else "pass"
    return {"status": st, "evidence": [f"{len(cands)} candidate(s), {len(open_)} undispositioned: {open_[:8]}"], "candidates": cands}


def check_task(task_dir: Path, evidence_root: Path | None = None) -> dict:
    package = resolve_package_dir(task_dir)
    if package is None:
        return {"status": "skip", "checks": {}}
    task = task_name_of(task_dir, package)
    crits, config = load_criteria(package)
    genre = "rewardkit" if any(c["stype"] == "rewardkit" for c in crits) else "native"
    instruction = read_instruction(package)
    sources = source_terms(package)
    dispo = dispositions(load_trace(package, task))
    g1 = g1_source_blind(crits, package)
    g4 = g4_fail_contradiction(crits, instruction, sources)
    checks = {
        "G1_source_blind": apply_dispositions("G1", g1, dispo),
        "G2_phrase_pin": apply_dispositions("G2", g2_phrase_pin(crits, instruction), dispo),
        "G3_numeric_pin": apply_dispositions("G3", g3_numeric_pin(crits, instruction), dispo),
        "G4_fail_contradiction": apply_dispositions("G4", g4, dispo),
        "G5_duplicate_grading": apply_dispositions("G5", g5_duplicate(crits), dispo),
        "G6_uncached_formulas": g6_uncached(package, crits, evidence_root, task),
        "G7_compound": apply_dispositions("G7", g7_compound(crits), dispo),
        "G8_coverage_ledger": g8_ledger(package, task, crits),
        "G9_judge_samples": g9_judge(config, genre, package),
    }
    # G1 candidates are defects unless re-sourced; a "not-a-defect" disposition is only acceptable if the prompt was narrowed (fixer's claim, reviewer verifies)
    order = {"fail": 3, "warn": 2, "pass": 1, "skip": 0}
    worst = max(checks.values(), key=lambda c: order[c["status"]])["status"]
    return {"status": worst, "task": task, "package": str(package), "genre": genre, "n_criteria": len(crits), "checks": checks}


def discover(root: Path) -> list[Path]:
    root = root.resolve()
    if (root / "tests").is_dir() or (root / "task_files").is_dir() or list(root.glob("rev_*/task_files")):
        return [root]
    return sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("task_"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--evidence", type=Path, help="with_runs bundle dir for the uncached-formula run scan")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--task", action="append", dest="task_ids")
    args = ap.parse_args(argv)
    dirs = discover(args.root)
    if args.task_ids:
        want = set(args.task_ids)
        dirs = [d for d in dirs if d.name in want or d.name.replace("_fixed", "") in want]
    rows = {}
    for d in dirs:
        r = check_task(d, args.evidence)
        rows[d.name] = r
        fails = [k for k, v in r.get("checks", {}).items() if v["status"] == "fail"]
        print(f"{d.name:12} {r['status']:5} fail={fails}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"generated": datetime.now(timezone.utc).isoformat(), "tasks": rows}, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    return 1 if any(r["status"] == "fail" for r in rows.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
