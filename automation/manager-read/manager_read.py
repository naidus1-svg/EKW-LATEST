#!/usr/bin/env python3
"""manager_read: the step 3 manager reader, packaged. One model call per task.

It reads one task package and the DataOS Answer Check reviews of it the way the manager reader did in the
audit sandbox, and lists items: a criterion, a file, quoted words and what to change. Every item needs a written answer from the QC person.
The manager sends the QC person the whole list and approves the task only after the answers check out.

Exit codes: 0 no items, 1 items, 2 could not run.
Standard library only, Python 3.11. Read automation/manager-read/README.md first.
"""

import argparse
import glob
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

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(HERE, "prompts", "manager_prompt.md")
# sha256 of prompts/manager_prompt.md, the exact file the MGRADVIS numbers came from
PROMPT_SHA256 = "2cb1fa1180b5abf81f89a7da0e481deb391a30ed189f91ac19df9613e8492905"
MODEL = os.environ.get("MANAGER_READ_MODEL", "sonnet")
CALL_TIMEOUT = int(os.environ.get("MANAGER_READ_TIMEOUT", "2400"))
SEVERITY_CAP = 1500  # characters of one stored review major, as in the audit run

# Read-only tools, inside a throwaway copy of the package. No Write: the reader does not edit files.
BASH = "Bash(python3:*),Bash(ls:*),Bash(cat:*),Bash(head:*),Bash(unzip:*),Bash(strings:*),Bash(pdftotext:*)"
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
TOOLS = f"Read,Glob,Grep,{BASH}"

TYPE_TEXT = {
    "U": "The criterion demands something the instruction never asks for and the inputs do not supply.",
    "A7": "The criterion demands one exact wording, format or path where the instruction allows others.",
    "A1": "The golden answer has a factual error that the criterion rewards.",
    "O": "An empty, missing or wrong answer still passes the criterion.",
    "C": "Two requirements (criteria, instruction or golden) ask for opposite things.",
    "D": "The criterion needs a fact or file the model was never given.",
    "R": "A DataOS review major that the reader confirmed against the files.",
}

LIMITS = (
    "Every item needs a written answer from the QC person: FIXED, or NOT A DEFECT plus one sentence that uses the quoted words. The reader is wrong on many tasks: in a test on "
    "tasks from batches 4 to 13 that were not used to write the finder prompt (UNAUDITED, labels are model-built, "
    "no person checked them) it sent back 31 of 46 tasks the audit calls defective and 18 of 49 clean ones; "
    "read together with the step 1 task read, 35 of 46 and 22 of 49. "
    "About 4 in 10 of the clean tasks it sees get at least one item, so expect some answers to be NOT A DEFECT. "
    "Check each quote in the file when you read the answers. "
    "No item does not mean the task is clean."
)


class CouldNotRun(Exception):
    pass


try:  # layout, grader and kind helpers are shared with the step 1 task read
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "task-read"))
    import task_read as _tr  # noqa: E402
except Exception as _e:  # pragma: no cover
    _tr = None
    _tr_err = _e

jload = lambda p: json.load(open(p, encoding="utf-8"))  # noqa: E731


def jdump(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)


def need_helpers():
    if _tr is None:
        raise CouldNotRun(
            "automation/task-read/task_read.py is missing or does not import "
            f"({_tr_err}); run: python qc.py update"
        )


def prompt_text():
    try:
        raw = open(PROMPT_FILE, "rb").read()
    except OSError as e:
        raise CouldNotRun(f"cannot read {PROMPT_FILE}: {e}")
    if hashlib.sha256(raw).hexdigest() != PROMPT_SHA256:
        raise CouldNotRun(
            "prompts/manager_prompt.md does not match the recorded sha256; it is the prompt the measured "
            "numbers come from. If you changed it on purpose, update PROMPT_SHA256 and re-measure."
        )
    return raw.decode("utf-8")


# ---------------------------------------------------------------- package, reviews, evidence


def split_input(src):
    """Return (package folder, reviews folder or None, evaluations folder or None).
    Accepts a rev_<n>__<id> folder from a Dataset with runs download (task_files, verifications, evaluations),
    a package folder, or an audit-layout folder."""
    if not os.path.isdir(src):
        raise CouldNotRun(f"{src} is not a folder")
    tf = os.path.join(src, "task_files")
    if os.path.isdir(tf):
        v = os.path.join(src, "verifications")
        e = os.path.join(src, "evaluations")
        return (
            _tr.package_root(tf),
            v if os.path.isdir(v) else None,
            e if os.path.isdir(e) else None,
        )
    return _tr.package_root(src), None, None


def parse_review(path):
    """(review id, answer text) of one comprehensive_review md, or None when it is not an Answer Check review."""
    name = os.path.basename(path)
    m = re.match(r"^comprehensive_review_(\d+)___", name)
    txt = open(path, encoding="utf-8", errors="replace").read()
    i = txt.find("## transcript")
    if not m or i < 0 or "COMPREHENSIVE_REVIEW" not in txt[:i]:
        return None
    a = list(re.finditer(r"(?m)^A: ", txt[i:]))
    if not a:
        return None
    return int(m.group(1)), txt[i:][a[-1].end() :]


def review_majors(answer):
    """(complete, list of major finding texts) from the JSON block at the end of an Answer Check reply."""
    _tr_json = _tr.last_json(answer)
    if not isinstance(_tr_json, dict) or not isinstance(_tr_json.get("findings"), list):
        return False, []
    majors = [
        json.dumps(f, ensure_ascii=False)[:SEVERITY_CAP]
        for f in _tr_json["findings"]
        if isinstance(f, dict) and str(f.get("severity", "")).lower() == "major"
    ]
    if not majors and str(_tr_json.get("major_count", 0)) not in ("0", ""):
        majors = ["(the review counted a major but its text was not stored)"]
    return True, majors


def reviews_markdown(rev_dir):
    """reviews/reviews.md in the form the audit run used. Four complete reviews are needed; otherwise the note."""
    note = "No complete version 8 review run is available for this task. Judge from the package alone."
    head = "# Answer Check reviews (pipeline version 8)\n\n"
    if not rev_dir:
        return head + note + "\n", 0
    parsed = sorted(
        x
        for x in (parse_review(p) for p in glob.glob(os.path.join(rev_dir, "*.md")))
        if x
    )
    done = [(i, review_majors(a)) for i, a in parsed]
    done = [(i, m) for i, (ok, m) in done if ok][-4:]
    if len(done) < 4:
        return head + note + "\n", len(done)
    L = [
        head + "Four reviews ran (Y1 to Y4). Only MAJOR findings were stored; minor findings are not available."
    ]
    for k, (_, majors) in enumerate(done, 1):
        L += ["", f"## Review Y{k}: " + ("reports a major" if majors else "no major reported")]
        for n, t in enumerate(majors, 1):
            L += ["", f"Major {n} (text may be cut at 1500 characters):", "", t]
    return "\n".join(L) + "\n", 4


def empty_run_evidence(eval_dir):
    """evidence.json: the reward of the stored empty-answer (nop) runs, when the download has them."""
    rewards = []
    for d in sorted(glob.glob(os.path.join(eval_dir or "", "*__nop*"))):
        try:
            r = jload(os.path.join(d, "eval_files", "result.json"))
            rewards.append(float(r["verifier_result"]["rewards"]["reward"]))
        except Exception:
            pass
    if not rewards:
        return {}
    return {"empty_or_noop_answer_runs": {"n_runs": len(rewards), "max_reward": max(rewards)}}


def build_workspace(src, ws, reviews_override=None):
    """instruction.md, inputs/, golden/, rubric/criteria.json, rubric/raw/, evidence.json, reviews/reviews.md."""
    need_helpers()
    root, rev_dir, eval_dir = split_input(src)
    if reviews_override:
        rev_dir = reviews_override
    have_md = os.path.exists(os.path.join(root, "reviews", "reviews.md"))
    try:
        _tr.build_audit_layout(root, ws)
    except CouldNotRun:
        raise
    except Exception as e:  # a grader file in a shape the shared layout code does not know
        raise CouldNotRun(
            f"cannot read the grader files of this package ({type(e).__name__}: {e}); "
            "the weights are probably not where the layout code looks (same limit as qc.py read)"
        )
    ev = empty_run_evidence(eval_dir)
    if eval_dir or not os.path.exists(os.path.join(root, "rubric", "criteria.json")):
        jdump(ev, os.path.join(ws, "evidence.json"))  # replaces task_read's golden-reward summary
    os.makedirs(os.path.join(ws, "reviews"), exist_ok=True)
    n_reviews = 0
    if rev_dir or not have_md:
        md, n_reviews = reviews_markdown(rev_dir)
        with open(os.path.join(ws, "reviews", "reviews.md"), "w", encoding="utf-8") as f:
            f.write(md)
    else:
        n_reviews = 4
    return root, n_reviews


# ---------------------------------------------------------------- model call


class Runner:
    """Runs one `claude -p` call. Tests point --claude-cmd or MANAGER_READ_CLAUDE at a fake."""

    def __init__(self, claude_cmd=None):
        raw = claude_cmd or os.environ.get("MANAGER_READ_CLAUDE") or "claude"
        if os.name == "nt":
            parts = [p.strip('"') for p in shlex.split(raw, posix=False)]
        else:
            parts = shlex.split(raw)
        if len(parts) == 1:
            parts = [shutil.which(parts[0]) or parts[0]]
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
            raise CouldNotRun(f"the {kind} call took longer than {CALL_TIMEOUT} s and was stopped")
        if p.returncode != 0:
            tail = "\n".join(s.strip() for s in (p.stdout, p.stderr) if s and s.strip())[-600:]
            raise CouldNotRun(f"the {kind} call failed (claude exit {p.returncode}): {tail}")
        return p.stdout


def good_answer(j):
    return (
        isinstance(j, dict)
        and str(j.get("verdict", "")).upper() in ("APPROVE", "SEND_BACK", "HOLD")
        and isinstance(j.get("fixes", []), list)
    )


def read_task(src, runner, tab=None, reviews=None):
    t0 = time.time()
    prompt = prompt_text()
    work = tempfile.mkdtemp(prefix="manager_read_")
    try:
        ws = os.path.join(work, "task")
        root, n_reviews = build_workspace(src, ws, reviews)
        crit = {c["id"]: float(c["w"]) for c in jload(os.path.join(ws, "rubric", "criteria.json"))}
        try:
            tab_name, tab_source = _tr.detect_tab(root, ws, tab)
            if tab_source == "reward.toml guess":
                tab_name = "not stated"
        except Exception:
            tab_name, tab_source = "not stated", ""
        j = None
        for attempt in (1, 2):
            out = runner("manager reader", prompt, ws, TOOLS)
            j = _tr.last_json(out)
            if good_answer(j):
                break
            j = None
        if j is None:
            raise CouldNotRun("the reader did not return the JSON answer the prompt asks for (twice)")
        verdict = str(j["verdict"]).upper()
        fixes = [x for x in j.get("fixes") or [] if isinstance(x, dict)]
        for x in fixes:
            x["quote_found"] = quote_check(ws, x)
        return dict(
            task=os.path.basename(os.path.abspath(src)),
            tab=tab_name,
            n_criteria=len(crit),
            n_reviews_read=n_reviews,
            verdict=verdict,
            reason=str(j.get("reason", "")),
            items=fixes,
            rejected_review_majors=j.get("review_majors_rejected") or [],
            advisory=[str(a) for a in j.get("advisory") or []],
            coverage=j.get("coverage") or {},
            prompt_sha256=PROMPT_SHA256,
            calls=getattr(runner, "calls", None),
            seconds=round(time.time() - t0, 1),
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


def quote_check(ws, fix):
    """True / False when the quoted words are (not) found in the named text file; None when it cannot be checked."""
    q, f = str(fix.get("quote", "")).strip(), str(fix.get("quote_file", "")).strip()
    if not q or not f:
        return None
    p = os.path.normpath(os.path.join(ws, f))
    if not p.startswith(os.path.normpath(ws)) or not os.path.isfile(p):
        return None
    if not f.lower().endswith((".md", ".json", ".txt", ".csv", ".toml")):
        return None
    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()  # noqa: E731
    return norm(q) in norm(open(p, encoding="utf-8", errors="replace").read())


# ---------------------------------------------------------------- report


def write_report(res, path):
    n = len(res["items"])
    L = [
        "# Manager read report",
        "",
        f"Task: {res['task']}   Kind: {res['tab']}   Criteria in the grader: {res['n_criteria']}   "
        f"Answer Check reviews read (the 4 automated DataOS pipeline reviews of this task): {res['n_reviews_read']} of 4",
        "",
        "Every item needs a written answer from the QC person (FIXED, or NOT A DEFECT plus one sentence that uses the quoted words). The manager sends the "
        "whole list and approves the task only after the answers check out.",
        "",
    ]
    if res["verdict"] == "HOLD":
        L += [
            "## COULD NOT JUDGE",
            "",
            f"The reader could not judge this task: {res['reason']}",
            "",
        ]
    elif n or res["verdict"] == "SEND_BACK":
        L += [f"## {n} item(s)", "", f"Reader's summary: {res['reason']}", ""]
    else:
        L += [
            "## No items",
            "",
            "The reader found nothing that meets its four tests. This is not a clean bill of health (see the closing note).",
            "",
        ]
    for i, x in enumerate(res["items"], 1):
        t = str(x.get("type", "")).upper()
        found = x.get("quote_found")
        chk = {
            True: "quote found in that file",
            False: "quote NOT found in that file text: open the file and check the words before you rely on this item",
            None: "quote not machine-checked (file type or path); check it by hand",
        }[found if found in (True, False) else None]
        L += [
            f"### {i}. {t or 'item'} on {x.get('criterion_id', '(not named)')}",
            f"- Criterion: {x.get('criterion_id', '(not named)')}   Weight: {x.get('weight')}",
            f"- File: {x.get('quote_file', '(not named)')}",
            f"- Quoted words: \"{str(x.get('quote', ''))[:400]}\" ({chk})",
            f"- What is wrong: {x.get('problem', '')}"
            + (f" {TYPE_TEXT[t]}" if t in TYPE_TEXT else ""),
            f"- What to change: {x.get('fix', '')}",
            "",
        ]
    rej = res["rejected_review_majors"]
    if rej:
        L += ["## Review majors the reader checked and found wrong (Y1 to Y4 are the four Answer Check reviews, in order)", ""]
        for r in rej:
            if isinstance(r, dict):
                L.append(f"- {r.get('review', '?')} on {r.get('criterion_id', '?')}: {str(r.get('why', ''))[:300]}")
        L.append("")
    if res["advisory"]:
        L += [
            "## Notes the reader did not count as items",
            "",
            "Style or low-weight remarks. Not advice to change anything; read them only if you have time.",
            "",
        ] + [f"- {a[:300]}" for a in res["advisory"]] + [""]
    cov = res["coverage"]
    L += [
        "## How this was read",
        "",
        f"- One model call to the manager reader (prompt sha256 {res['prompt_sha256'][:12]}). "
        f"Reader's own coverage count: {json.dumps(cov)}.",
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
        f"# Manager read report\n\nTask: {task}\n\n## COULD NOT RUN\n\n{msg}\n\nNothing was checked. "
        f"Fix the problem and run it again.\n\n## Limits (read this)\n\n{LIMITS}\n"
    )


def main(argv=None, runner=None):
    ap = argparse.ArgumentParser(description="Read one task and its DataOS reviews the way the step 3 manager does (1 model call).")
    ap.add_argument("task_folder", help="a rev_<n>__<id> folder of a Dataset with runs download, or a task package folder")
    ap.add_argument("--out", default="manager_read_out", help="folder for manager_read_report.md and manager_read_result.json")
    ap.add_argument("--claude-cmd", default=None, help="the claude command (default: claude, or $MANAGER_READ_CLAUDE)")
    ap.add_argument("--tab", choices=("EKW", "SVC", "ekw", "svc"), default=None, help="task kind; only labels the report")
    ap.add_argument("--reviews", default=None, help="folder with comprehensive_review_*.md files, when they are not next to the package")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    rep = os.path.join(a.out, "manager_read_report.md")
    task = os.path.basename(os.path.abspath(a.task_folder))
    try:
        res = read_task(a.task_folder, runner or Runner(a.claude_cmd), a.tab, a.reviews)
    except CouldNotRun as e:
        write_failure(rep, str(e), task)
        print(f"manager_read: could not run: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # a crash is "could not run" (2), never an item list (1)
        msg = f"unexpected error {type(e).__name__}: {e}"
        write_failure(rep, msg, task)
        print(f"manager_read: could not run: {msg}", file=sys.stderr)
        return 2
    write_report(res, rep)
    jdump(res, os.path.join(a.out, "manager_read_result.json"))
    if res["verdict"] == "HOLD":
        print(f"COULD NOT JUDGE - report: {rep}", file=sys.stderr)
        return 2
    flagged = bool(res["items"]) or res["verdict"] == "SEND_BACK"
    print((f"{len(res['items'])} ITEM(S)" if flagged else "NO ITEMS") + f" - report: {rep}")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
