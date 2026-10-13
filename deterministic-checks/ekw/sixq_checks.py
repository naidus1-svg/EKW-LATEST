#!/usr/bin/env python3
"""Six pre-submission questions as checks (roll-up letter F, columns F1 to F6).

Source of the questions: docs/author-pre-submission-checklist.md. Each question is one check:

  F1  a rule fails a correct answer in another valid form   (script part + AI reader)
  F2  a rule asks for what the instruction never requested  (script part + AI reader)
  F3  an instruction sentence has a second reading          (AI reader only)
  F4  a wrong or empty answer can still earn weight         (script only)
  F5  weights, output location or inputs do not line up     (script only)
  F6  a number pinned in a rule is not in the golden        (script only)

Input shape: the BUILD-CONTRACT task folder (instruction.md, solution/files/, environment/
initial_workspace/, tests/deliverables_NN/judge.toml, tests/__support/evidence_map.json).

Output (same "std" shape as the other shared checks): {"results": [one record per task]}, each
record {task_id, question, status (pass/warn/skip/error), findings[], dropped_no_anchor, ...}.
Every finding carries rule_id, file and line; a finding without a file and a line is dropped and
counted in `dropped_no_anchor`. Findings are candidates for the QC person, never verdicts.

The AI-reader parts call `claude -p --model sonnet` once per task per question (prompts in
sixq_prompts.py). With `--no-llm`, or when no `claude` is on the path, F1 and F2 run their
script part only and F3 reports skip, each saying so in `note`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import sixq_prompts  # noqa: E402

HEAVY_WEIGHT = 0.05
MAX_RULES_FOR_READER = 40
QUESTIONS = ("F1", "F2", "F3", "F4", "F5", "F6")
LLM_QUESTIONS = ("F1", "F2", "F3")

# ----------------------------------------------------------------------------- loading


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def load_rules(task: Path) -> tuple[list[dict], list[str]]:
    """All rules of a task as dicts with id, file (relative), line, text, weight, group, files.
    Returns (rules, parse_errors). `line` is the line of the [[criterion]] header."""
    rules, errs = [], []
    for jt in sorted(task.glob("tests/deliverables_*/judge.toml")):
        rel = jt.relative_to(task).as_posix()
        group = jt.parent.name
        text = _read(jt)
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            errs.append(f"{rel}: {e}")
            continue
        header_lines = [
            i + 1 for i, ln in enumerate(text.splitlines()) if ln.strip() == "[[criterion]]"
        ]
        files = list((data.get("judge") or {}).get("files") or [])
        for k, c in enumerate(data.get("criterion") or []):
            if not isinstance(c, dict):
                continue
            name = str(c.get("name", f"c{k + 1}"))
            line = header_lines[k] if k < len(header_lines) else None
            try:
                w = float(c.get("weight", 0) or 0)
            except (TypeError, ValueError):
                w = 0.0
            rules.append(
                dict(
                    id=f"{group}/{name}",
                    name=name,
                    group=group,
                    file=rel,
                    line=line,
                    text=str(c.get("description", "")),
                    weight=w,
                    files=files,
                )
            )
    if not rules and not errs and (task / "tests" / "verifier.json").is_file():
        rules, errs = _load_rules_verifier_json(task)
    return rules, errs


def _load_rules_verifier_json(task: Path) -> tuple[list[dict], list[str]]:
    """EKW raw layout: tests/verifier.json (one verifier per rule). Line = first line holding
    the verifier's own "name": "<name>" entry."""
    sys.path.insert(0, str(HERE.parent))
    try:
        import ekw_verifier_json as evj
    except ImportError as e:
        return [], [f"cannot import ekw_verifier_json: {e}"]
    rel = "tests/verifier.json"
    text = _read(task / rel).splitlines()
    rules = []
    for c in evj.load_ekw_criteria(task):
        if c.get("name") == "__parse_error__":
            return [], [f"{rel}: {c.get('description')}"]
        name = str(c.get("name"))
        pat = re.compile(r'"name"\s*:\s*"' + re.escape(name) + r'"')
        line = next((i + 1 for i, ln in enumerate(text) if pat.search(ln)), None)
        try:
            w = float(c.get("weight") or 0)
        except (TypeError, ValueError):
            w = 0.0
        rules.append(
            dict(id=f"verifier/{name}", name=name, group=name, file=rel, line=line,
                 text=str(c.get("description") or ""), weight=w, files=list(c.get("files") or []))
        )
    return rules, []


def load_instruction(task: Path) -> list[str]:
    return _read(task / "instruction.md").splitlines()


def load_evidence_map(task: Path) -> dict:
    p = task / "tests" / "__support" / "evidence_map.json"
    try:
        return json.loads(_read(p)) if p.is_file() else {}
    except json.JSONDecodeError:
        return {}


def _finding(rule: dict, kind: str, detail: str, **extra) -> dict:
    d = dict(
        rule_id=rule["id"],
        file=rule["file"],
        line=rule["line"],
        kind=kind,
        detail=detail,
        weight=rule["weight"],
    )
    d.update(extra)
    return d


def _anchor_ok(f: dict) -> bool:
    return bool(f.get("rule_id")) and bool(f.get("file")) and isinstance(f.get("line"), int)


# ----------------------------------------------------------------------------- F1 script

STRICT = re.compile(
    r"\b(exact figure|exact value|exactly|verbatim|to the cent|no rounding|literal(ly)?|"
    r"character[- ]for[- ]character|must be (named|labell?ed|titled|called))\b",
    re.I,
)
EQUIV = re.compile(
    r"(accept|equivalent|within|toleran|round(ed|ing)|either|any of|alternativ|or the same|"
    r"approximately|±|\+/-|same value (written|expressed)|any (valid|reasonable))",
    re.I,
)
PINNED = re.compile(r"(\$\s?\d[\d,]*(\.\d+)?|\b\d{1,3}(,\d{3})+(\.\d+)?|\b\d+\.\d+\s?%?|\b\d+\s?%)")


def f1_script(rules: list[dict]) -> list[dict]:
    out = []
    for r in rules:
        t = r["text"]
        m = STRICT.search(t)
        if m and PINNED.search(t) and not EQUIV.search(t):
            out.append(
                _finding(
                    r,
                    "strict_form_pinned_figure",
                    f"strict wording '{m.group(0)}' with a pinned figure and no wording that accepts another form",
                )
            )
    return out


# ----------------------------------------------------------------------------- F2 script

NUMWORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
}
UNITS = (
    r"words?|pages?|slides?|sheets?|tabs?|rows?|columns?|bullets?|items?|fields?|paragraphs?|"
    r"sentences?|scenarios?|risks?|checks?|options?|metrics?|sections?|charts?|tables?|lines?"
)
COUNT_RULE = re.compile(
    r"\b(at least|at most|no more than|no fewer than|exactly|maximum of|minimum of|up to|"
    r"fewer than|more than|limited to|capped at)\s+(?:\w+\s+)?(\d[\d,]*|" + "|".join(NUMWORDS) + r")\s+(" + UNITS + r")\b",
    re.I,
)
NAMED = re.compile(
    r"\b(?:sheet|tab|worksheet|section|heading|column|file|slide)\s+(?:named|called|titled|labell?ed)\s+[\"'“‘]([^\"'”’]{2,40})[\"'”’]",
    re.I,
)


def _norm_num(s: str) -> str:
    s = s.lower().replace(",", "")
    return NUMWORDS.get(s, s)


def _instruction_numbers(instr: str) -> set[str]:
    nums = {m.replace(",", "") for m in re.findall(r"\d[\d,]*(?:\.\d+)?", instr)}
    for w, d in NUMWORDS.items():
        if re.search(rf"\b{w}\b", instr, re.I):
            nums.add(d)
    return nums


def f2_script(rules: list[dict], instr_lines: list[str]) -> list[dict]:
    instr = "\n".join(instr_lines)
    low = instr.lower()
    have = _instruction_numbers(instr)
    out = []
    for r in rules:
        for m in COUNT_RULE.finditer(r["text"]):
            n = _norm_num(m.group(2))
            if n not in have:
                out.append(
                    _finding(
                        r,
                        "constraint_number_not_in_instruction",
                        f"rule requires '{m.group(0)[:60]}'; the number {n} does not appear in instruction.md",
                    )
                )
        for m in NAMED.finditer(r["text"]):
            if m.group(1).lower() not in low:
                out.append(
                    _finding(
                        r,
                        "required_name_not_in_instruction",
                        f"rule requires a name '{m.group(1)[:40]}' that instruction.md never uses",
                    )
                )
    return out


# ----------------------------------------------------------------------------- F4 script

PASS_MARK = re.compile(
    r"\b(?:pass(?:es)? if|pass:|score yes if|yes if|satisf(?:ied|ies) if|meets this criterion if|required:)",
    re.I,
)
END_MARK = re.compile(r"\b(?:fail|score no|score 0|no if|do not pass)\b", re.I)
# a negation inside the first 60 characters of the pass clause, i.e. the clause is led by an absence
LEAD_NEG = re.compile(
    r"^\W*(?:\w+\s+){0,6}?(?:no|not|without|never|neither|none|does not|doesn't|do not|is not|are not|free of|absence of)\b",
    re.I,
)
EXISTS_ONLY = re.compile(
    r"\b(exists?|is present|are present|is provided|is non-empty|opens?|is included|"
    r"has a (sheet|tab|section)|contains (a|an|any) (sheet|tab|section|table))\b",
    re.I,
)


def _pass_clause(t: str) -> str:
    m = PASS_MARK.search(t)
    start = m.end() if m else 0
    e = END_MARK.search(t, start)
    return t[start : e.start() if e else len(t)].strip()


def f4_script(rules: list[dict]) -> tuple[list[dict], dict]:
    """Only rules with an explicit pass marker ("pass if", "score yes if", ...) are read, and only
    the first sentence of the pass clause: it must open with an absence word within its first
    four words, or be a short existence statement, with no number or quoted name in it."""
    out = []
    for r in rules:
        if not PASS_MARK.search(r["text"]):
            continue
        clause = _pass_clause(r["text"])
        first = re.split(r"(?<=[.;])\s", clause, maxsplit=1)[0][:200]
        has_value = bool(re.search(r"\d|[\"'\u201c]", first))
        words = first.split()
        lead = " ".join(words[:4])
        if first and not has_value and re.search(r"\b(no|not|without|never|neither|none|free of|absence of)\b", lead, re.I):
            out.append(
                _finding(
                    r,
                    "passes_on_absence",
                    "the pass condition opens with an absence ('no', 'not', 'without'), so an empty answer can satisfy it",
                )
            )
        elif first and len(first) < 140 and not has_value and EXISTS_ONLY.search(first):
            out.append(
                _finding(
                    r,
                    "existence_only",
                    "the pass condition is only that something exists or is present, with no value or name to match",
                )
            )
    total = sum(r["weight"] for r in rules)
    flagged = sum(f["weight"] for f in out)
    return out, dict(
        n_rules=len(rules),
        weight_total=round(total, 4),
        weight_on_flagged_rules=round(flagged, 4),
    )


# ----------------------------------------------------------------------------- F5 script

FILE_RE = re.compile(r"[\w\-\.]{2,60}\.(?:xlsx|xlsm|docx|pdf|csv|pptx)\b", re.I)
PRIORITY = re.compile(
    r"\b(most important|highest priority|top priority|primary|above all|critical|key priority|"
    r"matters most|chiefly|mainly)\b",
    re.I,
)
STOP = set(
    "about above after again against being below between could would should their there these "
    "those which while where other through under until having during before because".split()
)


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{5,}", s.lower()) if w not in STOP}


def _flatten(x):
    for i in x:
        if isinstance(i, (list, tuple)):
            yield from _flatten(i)
        else:
            yield i


def f5_script(rules: list[dict], instr_lines: list[str], emap: dict, env_names: set | None = None) -> list[dict]:
    out = []
    env_names = env_names or set()
    groups = (emap.get("groups") or {}) if isinstance(emap, dict) else {}
    for r in rules:
        g = groups.get(r["group"]) or {}
        flat = [str(x) for x in _flatten(g.get("paths") or [])]
        rfiles = [str(x) for x in _flatten(r["files"])]
        seen = {Path(p).name.lower() for p in flat}
        seen |= {Path(p).name.lower() for p in rfiles}
        sources_visible = any("sources" in Path(p).name.lower() for p in rfiles)
        for m in FILE_RE.finditer(r["text"]):
            nm = Path(m.group(0).strip()).name.lower()
            if nm in seen or (sources_visible and nm in env_names):
                continue
            kind = "rule_names_file_judge_may_not_see" if sources_visible else "rule_names_file_judge_cannot_see"
            out.append(
                _finding(
                    r,
                    kind,
                    f"rule text names '{m.group(0).strip()[:50]}' which is not among this group's judged files "
                    f"({', '.join(sorted(seen))[:120]})"
                    + ("; a sources file is attached, so check it holds that file" if sources_visible else ""),
                )
            )
    # instruction priority sentence vs the weights of the rules that share its words
    if rules:
        ws = sorted(r["weight"] for r in rules)
        median = ws[len(ws) // 2]
        for i, ln in enumerate(instr_lines):
            if not PRIORITY.search(ln):
                continue
            toks = _tokens(ln)
            match = [r for r in rules if len(toks & _tokens(r["text"])) >= 2]
            if len(match) < 1:
                continue
            mean_w = sum(r["weight"] for r in match) / len(match)
            if mean_w < median:
                top = max(match, key=lambda r: r["weight"])
                out.append(
                    _finding(
                        top,
                        "priority_sentence_weight_below_median",
                        f"instruction.md line {i + 1} names a priority; the {len(match)} rules sharing its words "
                        f"average weight {mean_w:.4f}, the task median is {median:.4f}",
                        instruction_line=i + 1,
                    )
                )
    return out


# ----------------------------------------------------------------------------- F6 script

NUM_IN_RULE = re.compile(
    r"(?P<cur>[$€£])?\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d{3,})\s?(?P<suf>%|million|billion|bn|m\b|k\b|thousand)?",
    re.I,
)


def _read_numbers_text(p: Path) -> str:
    suf = p.suffix.lower()
    try:
        if suf in (".xlsx", ".xlsm"):
            import openpyxl

            wb = openpyxl.load_workbook(p, data_only=True, read_only=True)
            parts = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    for v in row:
                        if v is not None:
                            parts.append(str(v))
            return " ".join(parts)
        if suf == ".docx":
            with zipfile.ZipFile(p) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
            return re.sub(r"<[^>]+>", " ", xml)
        if suf == ".pptx":
            with zipfile.ZipFile(p) as z:
                names = sorted(n for n in z.namelist() if re.match(r"ppt/(slides|notesSlides)/[^/]+\.xml$", n))
                return " ".join(re.sub(r"<[^>]+>", " ", z.read(n).decode("utf-8", "replace")) for n in names)
        if suf == ".pdf":
            if not shutil.which("pdftotext"):
                return ""
            # UTF-8 on both sides: the system code page (cp1252 on Windows) garbles the euro sign and long dashes, or fails on a byte it cannot decode
            r = subprocess.run(
                ["pdftotext", "-q", "-enc", "UTF-8", str(p), "-"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            )
            return r.stdout
        if suf in (".csv", ".txt", ".md", ".json"):
            return _read(p)
    except Exception:
        return ""
    return ""


def _values_in(text: str) -> list[float]:
    vals = []
    for m in re.finditer(r"-?\d[\d,]*(?:\.\d+)?", text):
        try:
            vals.append(float(m.group(0).replace(",", "")))
        except ValueError:
            pass
    return vals


def _decimals(s: str) -> int:
    return len(s.split(".")[1]) if "." in s else 0


def _candidates(m: re.Match) -> tuple[list[float], float]:
    """Values the golden could show for the rule's number, and the tolerance (display rounding)."""
    raw = m.group("num").replace(",", "")
    v = float(raw)
    d = _decimals(raw)
    suf = (m.group("suf") or "").lower()
    cands = [v]
    if suf == "%":
        cands += [v / 100.0]
    if suf in ("million", "m"):
        cands += [v * 1e6]
    if suf in ("billion", "bn"):
        cands += [v * 1e9]
    if suf in ("thousand", "k"):
        cands += [v * 1e3]
    tol = 0.5 * 10 ** (-d)
    return cands, tol


def _has(vals: list[float], cands: list[float], tol: float) -> bool:
    for c in cands:
        t = tol * (c / cands[0] if cands[0] else 1)
        t = max(abs(t), 1e-9)
        for v in vals:
            if abs(v - c) <= t + 1e-9 * max(1.0, abs(c)):
                return True
            if abs(v * 100 - c) <= t * 100 + 1e-9 and abs(v) < 1.5:
                return True
    return False


def f6_script(task: Path, rules: list[dict]) -> tuple[list[dict], dict]:
    gdir = task / "solution"
    gfiles = [p for p in sorted(gdir.rglob("*")) if p.is_file() and p.suffix.lower() in (".xlsx", ".xlsm", ".docx", ".pptx", ".pdf", ".csv", ".txt", ".md", ".json")] if gdir.is_dir() else []
    if not gfiles:
        return [], dict(skip="no golden files under solution/")
    gtext = " ".join(_read_numbers_text(p) for p in gfiles)
    gvals = _values_in(gtext)
    if not gvals:
        return [], dict(skip="golden files held no readable numbers")
    out, n_checked = [], 0
    in_cache: dict[str, list[float]] = {}

    def input_vals() -> list[float]:
        if "v" not in in_cache:
            idir = task / "environment"
            vals: list[float] = []
            if idir.is_dir():
                files = [p for p in sorted(idir.rglob("*")) if p.is_file() and p.suffix.lower() in (".xlsx", ".xlsm", ".docx", ".pptx", ".pdf", ".csv", ".txt", ".md")][:15]
                for p in files:
                    vals += _values_in(_read_numbers_text(p))
            in_cache["v"] = vals
        return in_cache["v"]

    for r in rules:
        missing, n_rule = [], 0
        for m in NUM_IN_RULE.finditer(r["text"]):
            raw = m.group("num")
            # skip years and bare numbers that are not amounts (no currency, suffix, comma or decimal)
            if re.fullmatch(r"(19|20)\d\d", raw):
                continue
            if not (m.group("cur") or m.group("suf") or "," in raw or "." in raw):
                continue
            n_checked += 1
            n_rule += 1
            cands, tol = _candidates(m)
            if not _has(gvals, cands, tol):
                missing.append((m.group(0).strip()[:20], _has(input_vals(), cands, tol)))
        if missing:
            shown = "; ".join(f"{a}{' (in an input file)' if b else ''}" for a, b in missing[:4])
            out.append(
                _finding(
                    r,
                    "rule_number_not_in_golden",
                    f"{len(missing)} of {n_rule} pinned numbers in this rule are in no golden file within display rounding: {shown}",
                    n_missing=len(missing),
                    n_pinned=n_rule,
                )
            )
    return out, dict(n_numbers_checked=n_checked, n_golden_files=len(gfiles))


# ----------------------------------------------------------------------------- AI reader


def claude_available() -> bool:
    return shutil.which("claude") is not None


def call_claude(prompt: str, timeout: int = 300) -> str:
    """One `claude -p --model sonnet` call; the prompt goes in on stdin."""
    p = subprocess.run(
        ["claude", "-p", "--model", "sonnet"],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "claude failed")[-300:])
    return p.stdout


LLM = call_claude  # tests replace this


def _json_obj(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j < i:
        raise ValueError("no JSON object in reply")
    return json.loads(text[i : j + 1])


def _prompts() -> dict:
    """Prompt set: version 1 (default) or version 2 when SIXQ_PROMPT_VERSION=v2."""
    if os.environ.get("SIXQ_PROMPT_VERSION") == "v2":
        import sixq_prompts_v2

        return sixq_prompts_v2.PROMPTS
    return sixq_prompts.PROMPTS


def build_reader_prompt(q: str, instr_lines: list[str], rules: list[dict]) -> tuple[str, int]:
    keep = sorted(rules, key=lambda r: -r["weight"])[:MAX_RULES_FOR_READER]
    instr = "\n".join(f"{i + 1}: {ln}" for i, ln in enumerate(instr_lines))
    body = "\n".join(
        f"RULE {r['id']} (weight {r['weight']:.4f}): {r['text'][:900]}" for r in keep
    )
    return f"{_prompts()[q]}\n\n=== INSTRUCTION ===\n{instr}\n\n=== RULES ===\n{body}\n", len(keep)


def llm_part(q: str, instr_lines: list[str], rules: list[dict]) -> tuple[list[dict], dict]:
    prompt, n = build_reader_prompt(q, instr_lines, rules)
    raw = LLM(prompt)
    obj = _json_obj(raw)
    by_id = {r["id"]: r for r in rules}
    out, dropped = [], 0
    for fl in obj.get("flags") or []:
        r = by_id.get(str(fl.get("rule", "")))
        if r is None or r["line"] is None:
            dropped += 1
            continue
        detail = fl.get("other_form") or fl.get("unrequested") or fl.get("other_reading") or ""
        extra = {}
        il = fl.get("instruction_line") or fl.get("nearest_instruction_line")
        if isinstance(il, int) and 1 <= il <= len(instr_lines):
            extra["instruction_line"] = il
        elif q == "F3":
            dropped += 1  # F3 must cite the instruction line it rests on
            continue
        if q == "F3" and fl.get("loses_rule") is not True:
            continue
        out.append(_finding(r, f"ai_reader_{q.lower()}", str(detail)[:300], **extra))
    return out, dict(rules_shown=n, dropped_from_reader=dropped)


# ----------------------------------------------------------------------------- per task


def check_task(task: Path, q: str, use_llm: bool = True) -> dict:
    rec = dict(task_id=task.name, question=q, status="pass", findings=[], dropped_no_anchor=0, note="")
    try:
        instr = load_instruction(task)
        rules, errs = load_rules(task)
        if errs:
            rec.update(status="error", note="; ".join(errs)[:300])
            return rec
        if not rules:
            rec.update(status="skip", note="no grading rules under tests/deliverables_*/judge.toml")
            return rec
        if not instr and q != "F4" and q != "F6":
            rec.update(status="skip", note="no instruction.md")
            return rec
        finds: list[dict] = []
        info: dict = {}
        if q == "F1":
            finds += f1_script(rules)
        elif q == "F2":
            finds += f2_script(rules, instr)
        elif q == "F4":
            f, info = f4_script(rules)
            finds += f
        elif q == "F5":
            env = task / "environment"
            names = {p.name.lower() for p in env.rglob("*") if p.is_file()} if env.is_dir() else set()
            finds += f5_script(rules, instr, load_evidence_map(task), names)
        elif q == "F6":
            f, info = f6_script(task, rules)
            if info.get("skip"):
                rec.update(status="skip", note=info["skip"])
                return rec
            finds += f
        if q in LLM_QUESTIONS:
            if use_llm and claude_available():
                f, i2 = llm_part(q, instr, rules)
                finds += f
                info.update(i2)
                rec["ai_reader_ran"] = True
            else:
                rec["ai_reader_ran"] = False
                if q == "F3":
                    rec.update(status="skip", note="F3 is AI reader only; no claude login or --no-llm")
                    return rec
                rec["note"] = "script part only; AI reader not run (no claude login or --no-llm)"
        kept = [f for f in finds if _anchor_ok(f)]
        rec["dropped_no_anchor"] = len(finds) - len(kept)
        rec["findings"] = kept
        rec["info"] = info
        rec["n_rules"] = len(rules)
        rec["status"] = "warn" if kept else "pass"
    except Exception as e:  # a bad package or reader reply must not stop the batch
        rec.update(status="error", note=f"{type(e).__name__}: {e}"[:300])
    return rec


def find_tasks(root: Path, ids: list[str], all_: bool) -> list[Path]:
    if ids:
        return [root / t for t in ids]
    return sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task_ids", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--question", required=True, choices=[q[1] for q in QUESTIONS] + list(QUESTIONS))
    ap.add_argument("--no-llm", action="store_true")
    a = ap.parse_args()
    q = a.question if a.question.startswith("F") else f"F{a.question}"
    root = Path(a.root)
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2
    if not a.all and not a.task_ids:
        sys.stderr.write("give task ids or --all\n")
        return 2
    res = []
    for t in find_tasks(root, a.task_ids, a.all):
        if not t.is_dir():
            res.append(dict(task_id=t.name, question=q, status="error", findings=[], dropped_no_anchor=0, note="task folder missing"))
            continue
        res.append(check_task(t, q, use_llm=not a.no_llm))
    Path(a.out).write_text(json.dumps({"question": q, "results": res}, indent=2, ensure_ascii=False), encoding="utf-8")
    counts = {s: sum(r["status"] == s for r in res) for s in ("pass", "warn", "skip", "error")}
    print(f"{q}: {len(res)} tasks {counts}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
