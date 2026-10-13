#!/usr/bin/env python3
"""task_read: read one task package the way the audit did, before it goes to DataOS.

Four model calls through the `claude` command you already use (Max plan, no paid API):
  1. the v2 manager-guide reader (rules A1, A2, A3, A7 only count),
  2. finder A  (goes criterion by criterion and tests correct answers against the heavy criteria),
  3. finder B  (the same prompt as A, a second independent pass),
  4. one verifier over the union of the finders' findings (must quote file evidence).
A task is FLAGGED when the reader fires A1, A2, A3 or A7, or the verifier keeps a finding on a
criterion that counts (EKW: weight 0.05 or more; SVC: one of the three heaviest criteria).

Exit codes: 0 not flagged, 1 flagged, 2 could not run.
Standard library only, Python 3.11. Read automation/task-read/README.md first.
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPTS = os.path.join(HERE, "prompts")
MODEL = os.environ.get("TASK_READ_MODEL", "sonnet")
CAP = 12  # findings per verifier call
READER_RULES = ("A1", "A2", "A3", "A7")
CALL_TIMEOUT = int(os.environ.get("TASK_READ_TIMEOUT", "1800"))

# The model works in a throwaway copy of the package. It can read files and run a few
# read-only commands; Write exists only so a finder can save its defects.json.
BASH = (
    "Bash(python3:*),Bash(ls:*),Bash(cat:*),Bash(head:*),Bash(unzip:*),Bash(strings:*)"
)
if os.name == "nt":
    # Windows has no python3 command, and the shell tool is PowerShell or Bash depending on the Claude Code build.
    BASH += (
        ",Bash(python:*),Bash(py:*),PowerShell(python:*),PowerShell(py:*)"
        ",PowerShell(Get-ChildItem:*),PowerShell(Get-Content:*)"
    )
    # A run without a person cannot approve a command that chains steps, so the model is told to keep them plain.
    WINDOWS_NOTE = (
        "Windows note: there is no python3 command here; run Python as python. Run one plain command per call: "
        "a command that chains steps with ;, | or && or uses $() is refused because nobody is here to approve it. "
        "To run several steps, save them as a .py file with the Write tool (if you have it) and run python thatfile.py, "
        "or put one short expression in python -c inside one pair of double quotes. Word, Excel and PDF files cannot "
        "be opened with Read; open them with python (python-docx, openpyxl, pdfplumber or pypdf) and print the text."
    )
else:
    WINDOWS_NOTE = ""
TOOLS_READ = f"Read,Glob,Grep,{BASH}"
TOOLS_WRITE = f"Read,Glob,Grep,Write,{BASH}"

TESTN = {
    "a": "false rejection (an answer that follows the instruction loses this criterion)",
    "b": "false credit (an empty or wrong answer earns this criterion)",
    "c": "contradiction between requirements",
    "d": "missing input (needed fact or file not provided)",
}
FIX_BY_TEST = {
    "a": "Reword the criterion (or add the missing requirement to the instruction) so the answer described above earns the credit.",
    "b": "Tighten the criterion so an empty or wrong answer cannot earn it.",
    "c": "Remove or reconcile one of the two requirements that clash.",
    "d": "Add the missing fact or file to the inputs or the instruction, or drop the criterion.",
}
RULE_TEXT = {
    "A1": (
        "The answer key has a factual error or contradicts the source files.",
        "Correct the golden answer or the check so they agree with the source files.",
    ),
    "A2": (
        "A check requires something neither the instruction nor the inputs ask for.",
        "Remove the check, or add the requirement to the instruction.",
    ),
    "A3": (
        "A judge must check facts against files it is not given, and the check text does not carry the values.",
        "Put the needed values in the check text, or give the judge the files.",
    ),
    "A7": (
        "A correct answer written differently fails (exact filename, exact wording or a band that excludes a valid answer).",
        "Accept the equivalent forms, or state the exact requirement in the instruction.",
    ),
}

LIMITS = (
    "No flag does not mean the task is clean. In a test on tasks from batches 4 to 13 that were not used to "
    "write the finder prompt (UNAUDITED, labels are model-built, no person checked them) this reader flagged "
    "14 of 46 tasks the audit calls defective (about 3 in 10) and 4 of 49 clean ones (about 1 in 12); "
    "on batches 10 to 13 alone, 5 of 22 and 1 of 20. The test used wider tools than this script. "
    "Keep reading the task yourself: "
    "most defects the audit finds (coverage gaps, ambiguous sentences) are not found by this reader."
)


class CouldNotRun(Exception):
    pass


def jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _toml(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def jdump(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)


# ---------------------------------------------------------------- package layout


def package_root(src):
    """Accept the task folder itself, or a folder whose single child is the task folder."""
    if os.path.exists(os.path.join(src, "instruction.md")):
        return src
    kids = [d for d in sorted(os.listdir(src)) if os.path.isdir(os.path.join(src, d))]
    if len(kids) == 1 and os.path.exists(os.path.join(src, kids[0], "instruction.md")):
        return os.path.join(src, kids[0])
    raise CouldNotRun(
        f"{src} has no instruction.md; point task_read at the task folder"
    )


def lp(p):
    """Absolute path in Windows extended-length form (the prefix that lifts the 260-character limit).

    Copying a package with long file names (SVC corpus files) into a temp folder fails without it.
    Other systems get the plain absolute path.
    """
    p = os.path.abspath(p)
    if os.name == "nt" and not p.startswith("\\\\?\\"):
        p = "\\\\?\\UNC\\" + p[2:] if p.startswith("\\\\") else "\\\\?\\" + p
    return p


def criteria_from_tests(root):
    """Effective weight = share of the final reward. Same arithmetic the audit used."""
    t = os.path.join(root, "tests")
    out = []
    rt = os.path.join(t, "reward.toml")
    vj = os.path.join(t, "verifier.json")
    if os.path.exists(rt):
        rw = _toml(rt)["reward"][0].get("weights") or {
            d: 1.0 for d in sorted(os.listdir(t)) if d.startswith("deliverables")
        }
        tot = sum(rw.values())
        for d, dw in rw.items():
            jt = os.path.join(t, d, "judge.toml")
            if os.path.exists(jt):
                cs = _toml(jt).get("criterion", [])
                s = sum(c["weight"] for c in cs) or 1.0
                for c in cs:
                    out.append(
                        dict(
                            id=f'{d}/{c["name"]}',
                            w=dw / tot * c["weight"] / s,
                            text=c["description"],
                        )
                    )
            else:
                out.append(
                    dict(id=d, w=dw / tot, text="(deterministic check, no rubric text)")
                )
    elif os.path.exists(vj):
        v = jload(vj)["verifiers"]
        s = sum(x["metadata"]["weight"] for x in v) or 1.0
        for x in v:
            a = x.get("assertion", {})
            txt = (a.get("rubric") or {}).get("prompt") or json.dumps(a)[:1500]
            out.append(dict(id=x["name"], w=x["metadata"]["weight"] / s, text=txt))
    else:
        raise CouldNotRun(
            "no tests/reward.toml or tests/verifier.json: cannot find the grader"
        )
    if not out:
        raise CouldNotRun("the grader has no criteria")
    return sorted(out, key=lambda c: -c["w"])


def build_audit_layout(root, ws):
    """instruction.md, inputs/, golden/, rubric/criteria.json, rubric/raw/, evidence.json."""
    if os.path.exists(os.path.join(root, "rubric", "criteria.json")):
        shutil.copytree(lp(root), lp(ws))
        return
    os.makedirs(os.path.join(ws, "rubric", "raw"))
    shutil.copy(lp(os.path.join(root, "instruction.md")), lp(ws))
    iw = next(
        (
            x
            for x in (
                os.path.join(root, "environment", "initial_workspace"),
                os.path.join(root, "environment", "data"),
            )
            if os.path.isdir(x)
        ),
        None,
    )
    if iw:
        shutil.copytree(lp(iw), lp(os.path.join(ws, "inputs")))
    else:
        os.makedirs(os.path.join(ws, "inputs"))
    if os.path.isdir(os.path.join(root, "solution")):
        shutil.copytree(
            lp(os.path.join(root, "solution")), lp(os.path.join(ws, "golden"))
        )
    t = os.path.join(root, "tests")
    for dp, _, fs in os.walk(t):
        for f in fs:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, t)
            if f.endswith((".toml", ".json", ".txt")) and not any(
                k in rel for k in ("lib", "pristine", "_data")
            ):
                os.makedirs(
                    lp(os.path.dirname(os.path.join(ws, "rubric", "raw", rel))),
                    exist_ok=True,
                )
                shutil.copy(lp(p), lp(os.path.join(ws, "rubric", "raw", rel)))
    crit = criteria_from_tests(root)
    jdump(
        [dict(id=c["id"], w=round(c["w"], 4), text=c["text"]) for c in crit],
        os.path.join(ws, "rubric", "criteria.json"),
    )
    ev = {}
    rep = os.path.join(root, "reports")
    if os.path.isdir(rep):
        for f in sorted(os.listdir(rep)):
            if "golden_reward" in f:
                with open(os.path.join(rep, f)) as fh:
                    ev["golden_answer_reward_report"] = fh.read()[:3000]
                break
    jdump(ev, os.path.join(ws, "evidence.json"))


def is_ekw(ws):
    """Original rule, kept as the last-resort guess: reward.toml present. SVC packages carry reward.toml too, so it does not tell the kinds apart."""
    return os.path.exists(os.path.join(ws, "rubric", "raw", "reward.toml"))


KIND_SOURCE = {
    "flag": "the --tab option",
    "task.toml category": "the task.toml category word",
    "verifier.json grader": "the verifier.json grader file",
}


def detect_tab(root, ws, forced=None):
    """Return (tab, source). Order: --tab option, task.toml [metadata] category, a verifier.json grader with no reward.toml (EKW), then the old reward.toml guess."""
    return detect_tab_in(root, os.path.join(ws, "rubric", "raw"), forced)


def detect_tab_in(root, raw, forced=None):
    """detect_tab for grader files given directly: raw is the folder holding verifier.json / reward.toml (the audit layout's rubric/raw, or a package's own tests folder)."""
    if forced:
        return forced.upper(), "flag"
    tt = os.path.join(root, "task.toml")
    if os.path.exists(tt):
        try:
            cat = str(_toml(tt).get("metadata", {}).get("category", "")).strip().lower()
        except Exception:
            cat = ""
        if cat.startswith("ekw"):
            return "EKW", "task.toml category"
        if cat.startswith("svc"):
            return "SVC", "task.toml category"
    has_reward = os.path.exists(os.path.join(raw, "reward.toml"))
    if os.path.exists(os.path.join(raw, "verifier.json")) and not has_reward:
        return "EKW", "verifier.json grader"
    return ("EKW" if has_reward else "SVC"), "reward.toml guess"


def counts(w, crit_weights, ekw):
    if ekw:
        return w >= 0.05 - 1e-9
    ws = sorted(crit_weights.values(), reverse=True)
    thr = ws[2] if len(ws) >= 3 else (ws[-1] if ws else 0.0)
    return w >= thr - 1e-6


# ---------------------------------------------------------------- model calls


class Runner:
    """Runs one `claude -p` call. Tests inject a different runner or point TASK_READ_CLAUDE at a fake."""

    def __init__(self, claude_cmd=None):
        raw = claude_cmd or os.environ.get("TASK_READ_CLAUDE") or "claude"
        if os.name == "nt":
            # POSIX splitting eats the backslashes in Windows paths
            parts = [p.strip('"') for p in shlex.split(raw, posix=False)]
        else:
            parts = shlex.split(raw)
        if len(parts) == 1:
            import shutil

            parts = [
                shutil.which(parts[0]) or parts[0]
            ]  # finds claude.cmd or claude.exe on Windows
        self.cmd = parts
        self.calls = 0
        self.lock = threading.Lock()

    def __call__(self, kind, prompt, cwd, tools):
        if WINDOWS_NOTE:
            prompt = prompt + "\n\n" + WINDOWS_NOTE
        # --tools limits which tools exist at all (--allowedTools only skips the permission prompt).
        # Without it a model such as GLM starts helper agents and wake-up timers instead of reading the task.
        names = ",".join(dict.fromkeys(t.split("(")[0] for t in tools.split(",")))
        argv = self.cmd + [
            "-p",
            "--model",
            MODEL,
            "--tools",
            names,
            "--allowedTools",
            tools,
            "--permission-mode",
            "acceptEdits",
            prompt,
        ]
        with self.lock:
            self.calls += 1
        try:
            p = subprocess.run(
                argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=CALL_TIMEOUT
            )
        except FileNotFoundError:
            raise CouldNotRun(
                f"cannot start `{self.cmd[0]}`: is the claude command installed and on your PATH?"
            )
        except subprocess.TimeoutExpired:
            raise CouldNotRun(
                f"the {kind} call took longer than {CALL_TIMEOUT} s and was stopped"
            )
        if p.returncode != 0:
            tail = "\n".join(s.strip() for s in (p.stdout, p.stderr) if s and s.strip())[-600:]
            raise CouldNotRun(
                f"the {kind} call failed (claude exit {p.returncode}): {tail}"
            )
        return p.stdout


def last_json(text):
    for b in reversed(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)):
        try:
            return json.loads(b)
        except Exception:
            pass
    s = text.strip()
    if s.startswith("{"):
        try:
            return json.loads(s)
        except Exception:
            pass
    return None


def read_prompt(name):
    return open(os.path.join(PROMPTS, name), encoding="utf-8").read()


LAYOUT_NOTE = (
    "Layout note: this folder is arranged as instruction.md, inputs/ (the input files), golden/ "
    "(the reference answer), rubric/criteria.json (every criterion with id, weight w and text) "
    'and rubric/raw/ (the original grader files). Read "environment/" as inputs/, "solution/" '
    'as golden/ and "tests/" as rubric/.\n\n'
)


def run_reader(runner, root, work, ws_audit):
    """The v2 reader sees the raw package when there is one, else the audit layout with a note."""
    d = os.path.join(work, "reader")
    prompt = read_prompt("v2_reader.md")
    if os.path.isdir(os.path.join(root, "tests")):
        shutil.copytree(lp(root), lp(d))
    else:
        shutil.copytree(lp(ws_audit), lp(d))
        prompt = LAYOUT_NOTE + prompt
    for attempt in (1, 2):
        out = runner("reader", prompt, d, TOOLS_READ)
        j = last_json(out)
        if (
            isinstance(j, dict)
            and isinstance(j.get("tier_a", []), list)
            and str(j.get("verdict", "")).upper() in ("APPROVE", "DENY")
        ):
            items = [
                x
                for x in j.get("tier_a", [])
                if isinstance(x, dict)
                and str(x.get("rule", "")).upper() in READER_RULES
            ]
            return dict(
                verdict=str(j["verdict"]).upper(),
                items=items,
                calls=attempt,
                other_rules=sorted(
                    {
                        str(x.get("rule"))
                        for x in j.get("tier_a", [])
                        if isinstance(x, dict)
                    }
                    - set(READER_RULES)
                ),
                tier_b=len(j.get("tier_b", []) or []),
            )
    raise CouldNotRun(
        "the reader did not return the JSON answer the prompt asks for (twice)"
    )


def ok_finder(j):
    try:
        return (
            isinstance(j["defects"], list)
            and isinstance(j.get("coverage"), dict)
            and all(
                isinstance(x.get("criteria"), list)
                and str(x.get("test", "")).strip().lower() in tuple("abcd")
                for x in j["defects"]
            )
        )
    except Exception:
        return False


def run_finder(runner, ws_audit, work, name, prompt_file):
    for attempt in (1, 2):
        d = os.path.join(work, f"{name}{attempt}")
        shutil.copytree(lp(ws_audit), lp(d))
        runner(f"finder {name}", read_prompt(prompt_file), d, TOOLS_WRITE)
        try:
            j = jload(os.path.join(d, "defects.json"))
        except Exception:
            j = None
        if j is not None and ok_finder(j):
            return j
    raise CouldNotRun(f"finder {name} did not write a valid defects.json (twice)")


def norm(d, crit):
    ids = [str(c).strip() for c in d.get("criteria") or []]
    return dict(
        ids=ids,
        test=str(d.get("test")).strip().lower(),
        w=round(sum(crit.get(i, 0.0) for i in dict.fromkeys(ids)), 4),
        desc=str(d.get("description", ""))[:600],
        sketch=str(d.get("answer_sketch", ""))[:600],
        quotes=[str(q)[:300] for q in (d.get("quotes") or [])][:4],
    )


def finding_text(f):
    t = (
        f"Criteria: {', '.join(f['ids'])} (combined effective weight {f['w']}). Claimed defect, test "
        f"({f['test']}) {TESTN.get(f['test'], '')}: {f['desc']}"
    )
    if f["sketch"]:
        t += f" Answer sketch offered: {f['sketch']}"
    if f["quotes"]:
        t += " Evidence cited: " + " | ".join(f["quotes"])
    return t


def merge(a_defects, b_defects, crit):
    """Pair finder A and finder B findings with the same test letter and a shared criterion (best overlap first)."""
    A = [norm(d, crit) for d in a_defects]
    B = [norm(d, crit) for d in b_defects]
    cand = []
    for i, a in enumerate(A):
        for j, b in enumerate(B):
            sa, sb = set(a["ids"]), set(b["ids"])
            if a["test"] == b["test"] and sa & sb:
                cand.append((-len(sa & sb) / len(sa | sb), i, j))
    cand.sort()
    ua, ub, out = set(), set(), []
    for _, i, j in cand:
        if i in ua or j in ub:
            continue
        ua.add(i)
        ub.add(j)
        f = dict(A[i])
        f["ids"] = list(dict.fromkeys(A[i]["ids"] + B[j]["ids"]))
        f["w"] = round(sum(crit.get(x, 0.0) for x in f["ids"]), 4)
        out.append(dict(f, found_by="both"))
    out += [dict(a, found_by="A") for i, a in enumerate(A) if i not in ua]
    out += [dict(b, found_by="B") for j, b in enumerate(B) if j not in ub]
    for f in out:
        f["text"] = finding_text(f)
        f["fid"] = hashlib.sha1(f["text"].encode()).hexdigest()[:10]
    return sorted(out, key=lambda f: f["fid"])


def run_verifier(runner, ws_audit, work, merged):
    verdicts, calls = [], 0
    for k in range(0, len(merged), CAP):
        chunk = merged[k : k + CAP]
        want = {f["fid"] for f in chunk}
        got = None
        for attempt in (1, 2):
            d = os.path.join(work, f"verifier{k // CAP}_{attempt}")
            shutil.copytree(lp(ws_audit), lp(d))
            jdump(
                [dict(id=f["fid"], text=f["text"]) for f in chunk],
                os.path.join(d, "findings.json"),
            )
            runner("verifier", read_prompt("verifier.md"), d, TOOLS_WRITE)
            calls += 1
            try:
                v = jload(os.path.join(d, "verdicts.json"))["verdicts"]
                if {x["id"] for x in v} == want and all(
                    x.get("verdict") in ("VERIFIED", "NOT_A_DEFECT", "UNCLEAR")
                    for x in v
                ):
                    got = v
            except Exception:
                pass
            if got:
                break
        if got is None:
            raise CouldNotRun(
                "the verifier did not write a valid verdicts.json (twice)"
            )
        verdicts += got
    return verdicts, calls


# ---------------------------------------------------------------- the read


def read_task(src, runner, max_parallel=3, tab=None):
    t0 = time.time()
    root = package_root(src)
    work = tempfile.mkdtemp(prefix="task_read_")
    try:
        ws = os.path.join(work, "audit")
        build_audit_layout(root, ws)
        crit_list = jload(os.path.join(ws, "rubric", "criteria.json"))
        crit = {c["id"]: float(c["w"]) for c in crit_list}
        tab, tab_source = detect_tab(root, ws, tab)
        if tab_source == "reward.toml guess":
            # the files do not separate the two kinds; a wrong guess silently changes which findings count
            raise CouldNotRun(
                "cannot tell from the files whether this task is EKW or SVC; "
                "run again with --tab EKW or --tab SVC"
            )
        ekw = tab == "EKW"
        with ThreadPoolExecutor(max_parallel) as ex:
            fr = ex.submit(run_reader, runner, root, work, ws)
            fa = ex.submit(run_finder, runner, ws, work, "finderA", "finder_a.md")
            fb = ex.submit(run_finder, runner, ws, work, "finderB", "finder_b.md")
            reader, ja, jb = fr.result(), fa.result(), fb.result()
        merged = merge(ja["defects"], jb["defects"], crit)
        verdicts, vcalls = run_verifier(runner, ws, work, merged) if merged else ([], 0)
        by_fid = {f["fid"]: f for f in merged}
        kept = []
        for v in verdicts:
            if v["verdict"] != "VERIFIED":
                continue
            ids = [str(c) for c in v.get("criteria") or []]
            w = max([crit.get(c, 0.0) for c in ids] or [0.0])
            f = by_fid.get(v["id"], {})
            tests = [str(x).lower() for x in v.get("tests_met") or []] or (
                [f["test"]] if f.get("test") else []
            )
            kept.append(
                dict(
                    fid=v["id"],
                    criteria=ids,
                    w=w,
                    counts=counts(w, crit, ekw),
                    tests=tests,
                    evidence=[str(e) for e in v.get("evidence") or []],
                    note=str(v.get("note", "")),
                    sketch=str(v.get("answer_sketch", "")),
                    described=f.get("desc", ""),
                    found_by=f.get("found_by", ""),
                )
            )
        flagged_reader = bool(reader["items"])
        flagged_verifier = any(k["counts"] for k in kept)
        return dict(
            task=os.path.basename(os.path.abspath(root)),
            tab=tab,
            tab_source=tab_source,
            n_criteria=len(crit),
            flagged=flagged_reader or flagged_verifier,
            flagged_by_reader=flagged_reader,
            flagged_by_verifier=flagged_verifier,
            reader=reader,
            finder_a=len(ja["defects"]),
            finder_b=len(jb["defects"]),
            read_closely_a=len(ja["coverage"].get("read_closely") or []),
            read_closely_b=len(jb["coverage"].get("read_closely") or []),
            merged=len(merged),
            kept=kept,
            calls=runner.calls if hasattr(runner, "calls") else None,
            seconds=round(time.time() - t0, 1),
        )
    finally:
        shutil.rmtree(lp(work), ignore_errors=True)


# ---------------------------------------------------------------- report


def quote_list(ev):
    return [e.strip() for e in ev if e.strip()]


def write_report(res, path):
    L = [
        "# Task read report",
        "",
        f"Task: {res['task']}   Kind: {res['tab']} (from {KIND_SOURCE.get(res.get('tab_source'), 'unknown')})   Criteria in the grader: {res['n_criteria']}",
        "",
    ]
    if res["flagged"]:
        L += [
            "## FLAGGED",
            "",
            "At least one specific defect was found. Open each item below, check the quoted words in the files, "
            "and fix the task or decide the item is wrong before you send it.",
            "",
        ]
    else:
        L += [
            "## NOT FLAGGED",
            "",
            "The reader and the verifier found nothing on a criterion that counts. This is not a clean bill of health (see the closing note).",
            "",
        ]
    n = 0
    for x in res["reader"]["items"]:
        n += 1
        rule = str(x.get("rule", "")).upper()
        what, fix = RULE_TEXT.get(rule, ("", ""))
        L += [
            f"### {n}. Reader rule {rule}",
            f"- Criterion: {', '.join(str(c) for c in x.get('criteria') or []) or '(not named)'}   Weight: {x.get('weight')}",
            f"- Where and what the files say: {str(x.get('evidence', ''))[:800]}",
            f"- What is wrong: {what}",
            f"- What to change: {fix}",
            "",
        ]
    for k in res["kept"]:
        if not k["counts"]:
            continue
        n += 1
        t = k["tests"][0] if k["tests"] else "a"
        L += [
            f"### {n}. Verified finding ({', '.join(TESTN.get(x, x) for x in k['tests'])})",
            f"- Criterion: {', '.join(k['criteria'])}   Weight: {k['w']:.4f}",
            "- File and quoted words:",
        ]
        L += [f"  - {q}" for q in quote_list(k["evidence"])] or [
            "  - (the verifier gave no quote)"
        ]
        L += [f"- What is wrong: {k['note'] or k['described']}"]
        if k["sketch"]:
            L += [f"- Answer that loses credit: {k['sketch']}"]
        L += [f'- What to change: {FIX_BY_TEST.get(t, FIX_BY_TEST["a"])}', ""]
    low = [k for k in res["kept"] if not k["counts"]]
    if low:
        L += [
            f"Also verified, on criteria too light to flag ({len(low)}): "
            + "; ".join(
                f"{', '.join(k['criteria'])} (weight {k['w']:.4f})" for k in low
            ),
            "",
        ]
    L += [
        "## How this was read",
        "",
        f"- v2 reader (the call that applies rules A1, A2, A3 and A7): verdict {res['reader']['verdict']}; findings on A1, A2, A3 or A7: {len(res['reader']['items'])}.",
        f"- Finders: A reported {res['finder_a']}, B reported {res['finder_b']}; after pairing {res['merged']} to verify; "
        f"criteria each finder says it read closely: A {res['read_closely_a']}, B {res['read_closely_b']} of {res['n_criteria']}; "
        f"verifier kept {len(res['kept'])}, of which {sum(1 for k in res['kept'] if k['counts'])} on a criterion that counts "
        f"({'weight 0.05 or more' if res['tab'] == 'EKW' else 'one of the three heaviest'}).",
        f"- Model calls: {res['calls']}. Time: {res['seconds']} s.",
        "",
        "## Limits (read this)",
        "",
        LIMITS,
        "",
    ]
    open(path, "w", encoding="utf-8").write("\n".join(L))


def write_failure(path, msg, task):
    open(path, "w", encoding="utf-8").write(
        f"# Task read report\n\nTask: {task}\n\n## COULD NOT RUN\n\n{msg}\n\nNothing was checked. "
        f"Fix the problem and run it again.\n\n## Limits (read this)\n\n{LIMITS}\n"
    )


def main(argv=None, runner=None):
    ap = argparse.ArgumentParser(
        description="Read one task package the way the audit does (4 model calls)."
    )
    ap.add_argument("task_folder")
    ap.add_argument(
        "--out",
        default="task_read_out",
        help="folder for task_read_report.md and task_read_result.json",
    )
    ap.add_argument(
        "--claude-cmd",
        default=None,
        help="the claude command (default: claude, or $TASK_READ_CLAUDE)",
    )
    ap.add_argument("--max-parallel", type=int, default=3)
    ap.add_argument(
        "--tab",
        choices=("EKW", "SVC", "ekw", "svc"),
        default=None,
        help="task kind; give it when the files cannot tell (the report then says so)",
    )
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    rep = os.path.join(a.out, "task_read_report.md")
    task = os.path.basename(os.path.abspath(a.task_folder))
    try:
        if not os.path.isdir(a.task_folder):
            raise CouldNotRun(f"{a.task_folder} is not a folder")
        res = read_task(
            a.task_folder, runner or Runner(a.claude_cmd), a.max_parallel, a.tab
        )
    except CouldNotRun as e:
        write_failure(rep, str(e), task)
        print(f"task_read: could not run: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # a crash is 'could not run' (2), never FLAGGED (1)
        msg = f"unexpected error {type(e).__name__}: {e}"
        write_failure(rep, msg, task)
        print(f"task_read: could not run: {msg}", file=sys.stderr)
        return 2
    write_report(res, rep)
    jdump(res, os.path.join(a.out, "task_read_result.json"))
    print(("FLAGGED" if res["flagged"] else "NOT FLAGGED") + f" - report: {rep}")
    return 1 if res["flagged"] else 0


if __name__ == "__main__":
    sys.exit(main())
