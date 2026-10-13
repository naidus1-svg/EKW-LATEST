#!/usr/bin/env python3
"""qc.py: the one command a QC person runs. It updates itself from GitHub, then runs the step you ask for.

  python qc.py update                       pull the latest team repo and refresh the skill file
  python qc.py checks ROOT [STAGE OUT]      step 1: run the first-run checks (B to F) on a folder of tasks
  python qc.py fix TASK_DIR FINDINGS.md     step 2 (optional): the AI fixes a COPY of the task for the problems in FINDINGS.md (one AI call,
                                            several minutes). It writes fix_diff.md; you read it and copy the changes you accept by hand.
                                            Your task folder is never changed. --out DIR picks the output folder; --no-ask makes no AI call
  python qc.py read TASK_DIR                step 1: read one task with the audit reader (4 AI calls, about 2 minutes);
                                            add --tab EKW or --tab SVC if it says it cannot tell the task kind
  python qc.py review TASK_DIR PROBLEMS.md  step 2 (SOP 6c): test each problem the DataOS reviews listed
  python qc.py siblings TASK_DIR PROBLEMS.md  step 2 (after the 6c table): for each test a problem names, 1 AI call names up to 3
                                            other tests of the task with the same kind of gap; writes siblings.md and
                                            siblings_answers.csv next to PROBLEMS.md. REQUIRED: step 2 is not done until every
                                            suggested test has a yes or no and a note in that file. Add --check (no AI call): the
                                            last line says SIBLINGS: COMPLETE or SIBLINGS: HOLD (n open). --no-ask prints saved answers only
  python qc.py release ZIP [ZIP ...]        step 3: build the pre-send table from a Dataset with runs download
  python qc.py manage ZIP_OR_FOLDER [...]   step 3: the manager reader on every task of a Dataset with runs download
                                            (1 AI call per task, about 1 minute; every item it lists needs a written answer)
  python qc.py tfrl-read REV_FOLDER         step 2 (one Opus call, about 3 minutes): TFRL's own review prompt read by an AI over the task and its
                                            DataOS runs. Saves tfrl_replay.json and tfrl_replay_report.md in the rev folder; hand them over with
                                            blame_reader.json. It never changes the task and never blocks it (--again asks again)
  python qc.py look-first REV_FOLDER [--replay-flags FLAGS.csv]
                                            step 2 or 3 (no AI call, never blocks): says whether the blame reader and TFRL's own review
                                            prompt (read by an AI; our lanes write FLAGS.csv for the batch) both flagged this task. Both
                                            flagged = read it first. It is a pointer, not a rule. manage takes the same --replay-flags
  python qc.py proof init TASK_FOLDER       step 3: write zero_pass_proof.csv, one row for each heavy test (5 percent
                                            or more of the task's total weight) that every AI attempt failed
                                            (TASK_FOLDER: the rev_<n>__<id> folder of a Dataset with runs download).
                                            On an EKW task it also asks the golden-answer reader (4 AI calls, about
                                            2 minutes) and adds a row for every test the reader flags HOLD
  python qc.py proof check TASK_FOLDER      step 3: check that file for those tests; the last line says
                                            PROOF: COMPLETE or PROOF: HOLD (n open)
                                            add --tab EKW or --tab SVC if the task files do not say the kind
  The blame reader is on by default in proof init (EKW and SVC): for each zero-pass test it says whether the test itself
                                            may be wrong (1 AI call per test, 40 tests at most per task, --blame-max N changes
                                            that). Every test it flags needs a proof row, so PROOF stays HOLD until it is filled.
                                            --no-blame turns it off (the task then has no blame check). proof check and manage
                                            make no AI call: they read blame_reader.json that proof init saved

Words used above: EKW and SVC are the two task kinds (automation/task-read/README.md, section "Which kind of task").
A Dataset with runs download is the zip from the Dataset with runs button in DataOS (automation/release-check/README.md,
section "Get the zip"). On the last lines SIBLINGS: and PROOF:, HOLD means the check is not satisfied yet, so the step is not done; COMPLETE means it is done.

Every command pulls the latest repo first (git pull --ff-only). Add --no-update to skip that, for example
when you are offline. If you changed files in your copy of the repo the pull stops and says so; nothing is
overwritten. Needs Python 3.11 or newer and git. Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent
SKILL_SRC = REPO / "skills" / "ekw" / "verify-review-findings" / "SKILL.md"
SKILL_DST = Path.home() / ".claude" / "skills" / "verify-review-findings" / "SKILL.md"
RUNNER = REPO / "deterministic-checks" / "ekw" / "ekw_run_checks.py"
RC = REPO / "automation" / "release-check"
TASK_READ = REPO / "automation" / "task-read"
READER = REPO / "svc-pc-pipeline" / "tools" / "qc_zero_pass"


def say(msg: str) -> None:
    print(f"[qc] {msg}", flush=True)


def run(cmd: list[str], cwd: Path | None = None) -> int:
    say("running: " + " ".join(str(c) for c in cmd))
    return subprocess.run(
        [str(c) for c in cmd], cwd=str(cwd) if cwd else None
    ).returncode


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True
    )


def update() -> bool:
    """Pull the latest repo. Returns True when the repo is current, False when the pull could not run."""
    if shutil.which("git") is None:
        say(
            "git is not installed, so I cannot update. Install git, or run with --no-update."
        )
        return False
    if not (REPO / ".git").exists():
        say(
            "this folder is not a git clone, so I cannot update. Clone the repo once, then run qc.py from the clone."
        )
        return False
    before = git("rev-parse", "HEAD").stdout.strip()
    res = git("pull", "--ff-only")
    if res.returncode != 0:
        say(
            "update stopped, nothing was overwritten. Reason: "
            + (res.stderr or res.stdout).strip().splitlines()[-1]
        )
        say(
            "if you edited files in the repo, copy your edits elsewhere, then run: git -C "
            + str(REPO)
            + " status"
        )
        return False
    after = git("rev-parse", "HEAD").stdout.strip()
    if before != after:
        say("updated. What changed:")
        print(
            git(
                "log", "--no-merges", "--format=  - %s", f"{before}..{after}"
            ).stdout.rstrip()[:2000],
            flush=True,
        )
    else:
        say("already up to date.")
    refresh_skill()
    return True


def refresh_skill() -> None:
    if not SKILL_SRC.exists():
        return
    SKILL_DST.parent.mkdir(parents=True, exist_ok=True)
    if not SKILL_DST.exists() or SKILL_DST.read_bytes() != SKILL_SRC.read_bytes():
        shutil.copyfile(SKILL_SRC, SKILL_DST)
        say(f"skill file refreshed at {SKILL_DST}")


def cmd_checks(a) -> int:
    root = Path(a.root).resolve()
    stage = Path(a.stage) if a.stage else root.parent / (root.name + "_qc_stage")
    out = Path(a.out) if a.out else root.parent / (root.name + "_qc_out")
    cmd = [
        sys.executable,
        RUNNER,
        "--all",
        "--root",
        root,
        "--stage",
        stage,
        "--out-dir",
        out,
    ]
    try:
        out.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        say(f"checks stopped: cannot write to {out} ({e.strerror or 'permission denied'}).")
        return 2
    say("running: " + " ".join(str(c) for c in cmd))
    proc = subprocess.Popen([str(c) for c in cmd], stderr=subprocess.PIPE, text=True)
    lines = []
    for line in proc.stderr:
        sys.stderr.write(line)
        if line.strip():
            lines.append(line.strip())
    rc = proc.wait()
    table = out / "summary.csv"
    if table.exists():
        say(f"table: {table}")
        return rc
    err = next((x for x in lines if re.search(r"error|not exist|not a directory|cannot", x, re.I)), lines[0] if lines else "")
    say("checks stopped: no table was written." + (f" {err}" if err else ""))
    return 2


def cmd_review(a) -> int:
    task = Path(a.task_dir).resolve()
    problems = Path(a.problems).resolve()
    if not task.exists() or not problems.exists():
        say("task folder or problems file not found.")
        return 2
    work = Path(a.work).resolve() if a.work else task.parent
    prompt = (
        "Follow this skill file exactly. "
        + SKILL_SRC.read_text(encoding="utf-8")
        + f" Task folder: {task} Problem list: {problems}"
    )
    cmd = [
        "claude",
        "-p",
        "--model",
        "sonnet",
        "--allowedTools",
        "Bash,Read,Glob,Grep,Write",
        "--permission-mode",
        "dontAsk",
        prompt,
    ]
    say(
        "work on a COPY of the task folder, not your only copy. The table is also saved in the working folder."
    )
    return run(cmd, cwd=work)


READ_TIMES_MAX = 5
READ_RESULT = re.compile(r"(NOT FLAGGED|FLAGGED) - report: ")  # the line task_read.py prints last


def run_read(cmd: list, tag: str) -> int:
    """One read of a several-read run. The reader's output is shown as it comes, except its own result line, which is shown after the tag,
    so that the last line of the whole command is the only plain result line."""
    say("running: " + " ".join(str(c) for c in cmd))
    p = subprocess.Popen(
        [str(c) for c in cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    for line in p.stdout:
        s = line.rstrip("\r\n")
        print(f"[qc] {tag}: {s}" if READ_RESULT.match(s) else s, flush=True)
    return p.wait()


def cmd_read(a) -> int:
    script = REPO / "automation" / "task-read" / "task_read.py"
    if not script.exists():
        say(
            "automation/task-read/task_read.py is missing. Run: python qc.py update, then try again."
        )
        return 2
    folder = Path(a.task_folder).resolve()
    times = int(getattr(a, "times", 1) or 1)
    if times < 1 or times > READ_TIMES_MAX:
        times = min(max(times, 1), READ_TIMES_MAX)
        say(f"--times must be between 1 and {READ_TIMES_MAX}; reading {times} time(s)")

    def command(out) -> list:
        cmd = [sys.executable, script, str(folder)]
        if out:
            cmd += ["--out", str(out)]
        if a.tab:
            cmd += ["--tab", a.tab]
        return cmd

    if times == 1:
        # exit code passes through: 0 not flagged, 1 flagged, 2 could not run
        rc = run(command(a.out))
        if rc == 0:
            say("One read can miss. If you run it again and any run flags the task, treat it as flagged.")
            say("To have qc.py repeat the read for you, add --times 3.")
        return rc
    # Several reads of one task. The reader does not give the same answer on every run (in the batch 14 run 26 of 146 approved tasks that were clean
    # on the first read were flagged on a repeat read), so any flag counts. It stops at the first flag and at the first read that could not run.
    base = Path(a.out) if a.out else folder.parent / f"read_{folder.name}"
    first_report = None
    for k in range(1, times + 1):
        out = base / f"read{k}"
        tag = f"read {k} of {times}"
        say(f"{tag}: {out}")
        code = run_read(command(out), tag)
        report = out / "task_read_report.md"
        first_report = first_report or report
        if code == 1:
            say(f"{tag} flagged the task. Any flag counts, so the other reads are not run.")
            print(f"FLAGGED - report: {report}", flush=True)
            return 1
        if code != 0:
            say(f"{tag} could not run (exit {code}); the result is incomplete. Fix the cause it names and run again.")
            return 2
    say(f"all {times} reads of the task are clean (that does not prove the task is good).")
    print(f"NOT FLAGGED - report: {first_report}", flush=True)
    return 0


def cmd_release(a) -> int:
    out = Path(a.out).resolve()
    export = out / "export"
    if os.name == "nt":
        export = Path("\\\\?\\" + str(export))
    zips = [str(Path(z).resolve()) for z in a.zips]
    rc = run(
        [sys.executable, "-I", RC / "build_export_from_zip.py", *zips, export], cwd=RC
    )
    if rc:
        return rc
    rc = run(
        [
            sys.executable,
            "-I",
            RC / "run_release.py",
            export,
            export / "_pkgs",
            out / "table",
            "--dl",
            export / "_dl_stub",
            "--tasks",
            export / "tasks.csv",
        ],
        cwd=RC,
    )
    say(f"table: {out / 'table' / 'release_table.csv'}")
    say(
        "HOLD = a grading rule every valid attempt lost: look at that rule. Send the task back only if the rule or the golden answer is wrong. "
        "EVIDENCE MISSING = a check could not be computed from the download; it is not a failure."
    )
    return rc


def find_revs(root: Path) -> list[tuple[str, int, str, Path]]:
    """(task name, rev number, task id, folder) of the newest rev_<n>__<id> folder of each task under root."""
    best: dict[str, tuple[str, int, str, Path]] = {}
    for dp, dn, _ in os.walk(root):
        for d in list(dn):
            m = re.match(r"^rev_(\d+)__(\d+)$", d)
            if m:
                dn.remove(d)
                name = os.path.basename(dp)
                if name not in best or int(m.group(1)) > best[name][1]:
                    best[name] = (name, int(m.group(1)), m.group(2), Path(dp) / d)
    return sorted(best.values(), key=lambda x: x[0])


def unpack(z: Path, dest: Path) -> None:
    root = os.path.realpath(dest)
    with zipfile.ZipFile(z) as zf:
        for m in zf.infolist():
            t = os.path.realpath(os.path.join(dest, m.filename))
            if t != root and not t.startswith(root + os.sep):
                raise SystemExit(f"zip member escapes the folder: {m.filename}")
        zf.extractall(dest)


def cmd_manage(a) -> int:
    script = REPO / "automation" / "manager-read" / "manager_read.py"
    if not script.exists():
        say("automation/manager-read/manager_read.py is missing. Run: python qc.py update, then try again.")
        return 2
    out = Path(a.out).resolve()
    roots = []
    for i in a.inputs:
        p = Path(i).resolve()
        if p.is_file() and p.suffix.lower() == ".zip":
            dest = out / "extracted" / p.stem
            if os.name == "nt":
                dest = Path("\\\\?\\" + str(dest))
            dest.mkdir(parents=True, exist_ok=True)
            unpack(p, dest)
            roots.append(dest)
        elif p.is_dir():
            roots.append(p)
        else:
            say(f"{i} is not a zip file or a folder.")
            return 2
    revs = [r for root in roots for r in find_revs(root)]
    if not revs:
        say("no rev_<n>__<task id> folders found: is this a Dataset with runs download?")
        return 2
    say(f"{len(revs)} tasks. One AI call each; the reader only lists items.")
    look_flags = None
    if getattr(a, "replay_flags", None):
        try:
            look_flags = look_flags_read(Path(a.replay_flags).resolve())
        except ValueError as e:
            say(f"manage stopped: {e}.")
            return 2
    look_on = look_flags is not None or any(replay_present(r[3]) for r in revs)  # a flags file, or at least one saved tfrl_replay.json
    blame_on = not getattr(a, "no_blame", False)
    if not blame_on:
        say("blame reader: skipped (--no-blame), so the table has no blame check.")
    rows, looks = [], []
    for name, rev, tid, folder in revs:
        rc = run([sys.executable, script, str(folder), "--out", str(out / "manager" / tid)]
                 + (["--tab", a.tab] if a.tab else []))
        word = {0: "no items", 1: "items", 2: "could not run"}.get(rc, f"exit {rc}")
        row = (tid, name, rev, word, str(out / "manager" / tid / "manager_read_report.md"))
        if blame_on:
            row += (manage_blame(folder, a.blame, a.blame_max, out / "manager" / tid / "blame_reader_report.md"),)
        if look_on:  # after manage_blame, so an answer it just asked for is counted
            located = locate_rev(folder)
            kind = task_kind(located[1], a.tab)[0] if located else "UNKNOWN"
            replay = look_flags.get(tid, "no answer") if look_flags is not None else replay_state(folder)
            look = look_label(blame_state(folder, a.blame_max), replay)
            looks.append((tid, kind, look))
            row += (look,)
        rows.append(row)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "manager_summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["task_id", "task_name", "rev", "result", "report"] + (["blame"] if blame_on else []) + (["look_first"] if look_on else []))
        w.writerows(rows)
    n = {k: sum(1 for r in rows if r[3] == k) for k in ("no items", "items", "could not run")}
    say(f"table: {out / 'manager_summary.csv'}   items on {n['items']} of {len(rows)} tasks, "
        f"no items on {n['no items']}, could not run on {n['could not run']}")
    if blame_on:
        held = sum(1 for r in rows if r[5].startswith("HOLD"))
        say(f"blame reader: HOLD on {held} of {len(rows)} tasks (a flagged test with no filled proof row, or no saved blame_reader.json). Column: blame.")
    if look_on:
        first = [f"{t} ({k})" for t, k, lab in looks if lab == "both flagged"]
        none = sum(1 for _t, _k, lab in looks if lab.startswith("no pointer"))
        say(
            f"look first (column look_first): both checks flagged {len(first)} of {len(looks)} tasks"
            + (": " + ", ".join(first) if first else "")
            + (f"; no pointer for {none} (blame reader not run, or no TFRL review read: python qc.py tfrl-read <rev folder>)" if none else "")
            + "."
        )
        say(
            f"This is where to read first, not a rule: TFRL had rejected {look_pct(LOOK_GROUPS['both'])} of older tasks both checks flagged and "
            f"{look_pct(LOOK_GROUPS['neither'])} of those neither flagged. It sends no task back and passes none. On SVC tasks both flagged was mostly approved."
        )
    say("Every item needs a written answer. For each task with items, send the QC person the whole list. Approve the task only after "
        "each item is FIXED, or NOT A DEFECT with one sentence that uses the quoted words (docs/QC-RUNBOOK-manager.md, rule D).")
    return 2 if n["could not run"] else 0


PROOF_FILE = "zero_pass_proof.csv"
PROOF_COLS = ["criterion_id", "criterion_text", "weight", "instruction_quote", "golden_location", "other_valid_answer"]
QUOTE_WORDS, ANSWER_WORDS = 8, 10
HEAVY_SHARE = 0.05  # a test is heavy when its weight is at least this share of the revision's total recorded weight
HEAVY_TEXT = f"{round(HEAVY_SHARE * 100, 6):g} percent or more of the task's total weight"
CURLY = {0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"'}  # curly quotes -> straight


def norm(text: str) -> str:
    """Lower case, curly quotes made straight, whitespace collapsed: the form a quote is compared with the instruction in."""
    return re.sub(r"\s+", " ", text.translate(CURLY)).strip().lower()


def criterion_entries(node):
    """Every {name, value, weight} entry in a reward-details.json value (judge passes are a list, groups nest components)."""
    if isinstance(node, dict):
        if {"name", "value", "weight"} <= node.keys() and not isinstance(node["value"], (dict, list)):
            yield node
        else:
            for v in node.values():
                yield from criterion_entries(v)
    elif isinstance(node, list):
        for v in node:
            yield from criterion_entries(v)


def zero_pass_criteria(rev: Path) -> tuple[list[tuple[str, str, float, float]], int, int, float]:
    """(tests, scored attempts, AI attempts, total weight) for one rev_<n>__<id> folder of a Dataset with runs download.

    A scored attempt is an AI run (not the oracle run, which is the reference answer, and not the nop run, which submits an empty answer) with a per-test file and no recorded exception. A test the judge
    could not grade (it carries an error) is left out of that run. A test is listed when at least two scored attempts graded
    it and every judge pass of each of them gave 0. A test is (id, text, weight, share), heaviest first; the share is its
    weight divided by the total weight, the sum of the recorded weights of all the revision's tests, each counted once.

    Run folders are read by the release check's load_runs. The rule is new: golden_criterion_review.load_bundle found no
    runs on 87 of 464 real revisions with two or more AI runs (it reads one of the three shapes a reward-details.json
    comes in), and release_check.check1 needs a built export and a passing oracle run."""
    if str(RC) not in sys.path:
        sys.path.insert(0, str(RC))
    from build_export_from_zip import load_runs

    ai = [r for r in load_runs(glob.escape(str(rev))) if r["agent"] not in ("ORACLE", "NOP")]  # escape: [ ] in a folder name
    attempts, firsts = [], {}  # firsts: every test once, as its first scored attempt graded it
    for r in ai:
        if not r["details"] or r["exc"]:
            continue
        got: dict[str, list[dict]] = {}
        with open(r["details"], encoding="utf-8") as f:
            for key, node in json.load(f).items():
                for c in criterion_entries(node):
                    if not c.get("error") and c["value"] is not None:
                        got.setdefault(f"{key}/{c['name']}", []).append(c)
        if got:
            attempts.append(got)
            for cid, cs in got.items():
                firsts.setdefault(cid, cs[0])
    total = sum(float(c.get("weight") or 0) for c in firsts.values())
    tests = []
    for cid, c in firsts.items():
        graded = [a[cid] for a in attempts if cid in a]
        if len(graded) >= 2 and all(x["value"] == 0 for cs in graded for x in cs):
            w = float(c.get("weight") or 0)
            tests.append((cid, re.sub(r"\s+", " ", str(c.get("description") or "")).strip(), w, w / total if total > 0 else 0.0))
    return sorted(tests, key=lambda t: (-t[2], t[0])), len(attempts), len(ai), total


# ---- the golden-answer reader inside the proof step (EKW tasks) ---------------------------------------------------
# svc-pc-pipeline/tools/qc_zero_pass/golden_criterion_review.py judges every test that every AI attempt failed, three times
# with the golden answer in view and once without. A test it flags HOLD (golden 2 of 3 and the no-golden pass) gets a row in
# the proof sheet, like a heavy test. proof init asks the reader once and saves the answer; proof check only reads the saved
# answer, so the manager gets the same result with no claude command and no AI call.

GOLDEN_FILE = "golden_reader.json"  # the reader's answer for one download
KIND_HOW = {
    "flag": "you gave --tab",
    "task.toml category": "the task.toml category word",
    "verifier.json grader": "tests/verifier.json with no tests/reward.toml",
}


class ReaderStop(Exception):
    """The golden-answer reader cannot run, or cannot be trusted, on this download."""


def locate_rev(folder: Path):
    """(rev folder, package folder) for the folder a person names, or None when it is not a rev_<n>__<id> folder of a Dataset with runs download."""
    rev = folder if (folder / "evaluations").is_dir() else folder.parent
    pkg = rev / "task_files" if (rev / "task_files").is_dir() else rev
    if not (rev / "evaluations").is_dir() or not (pkg / "instruction.md").is_file():
        return None
    return rev, pkg


def task_kind(pkg: Path, forced: str | None) -> tuple[str, str]:
    """('EKW' | 'SVC' | 'UNKNOWN', how it was told), in the order automation/task-read uses: --tab, the task.toml category word,
    a verifier.json grader with no reward.toml. Where the files do not say but a grader file exists, the task counts as EKW: a
    missing sign must never let an EKW task skip the golden-answer block, and an SVC task can always be named with --tab SVC."""
    if str(TASK_READ) not in sys.path:
        sys.path.insert(0, str(TASK_READ))
    import task_read

    kind, how = task_read.detect_tab_in(str(pkg), str(pkg / "tests"), forced)
    if how != "reward.toml guess":
        return kind, how
    if (pkg / "tests" / "reward.toml").is_file():
        return "EKW", "not stated"
    return "UNKNOWN", "no grader file"


def golden_kind(pkg: Path, forced: str | None) -> tuple[str, str]:
    """(task kind, how it was told) for the golden-answer block, after printing the one line that says what happens to this task."""
    kind, how = task_kind(pkg, forced)
    if kind == "SVC":
        say(f"golden-answer reader: skipped, this is an SVC task ({KIND_HOW.get(how, how)}). The reader block is for EKW tasks only.")
    elif kind == "UNKNOWN":
        say("golden-answer reader: skipped, the task files have no grader file (tests/reward.toml or tests/verifier.json), so I cannot tell the task kind. On an EKW task add --tab EKW.")
    elif how == "not stated":
        say("the task files do not say whether this is an EKW or an SVC task, so I treat it as EKW and the golden-answer reader applies. If it is an SVC task, add --tab SVC.")
    return kind, how


def safe(text, limit: int = 230) -> str:
    """One line of reader text that any console can print."""
    one = re.sub(r"\s+", " ", str(text)).strip()
    one = one[: limit - 3] + "..." if len(one) > limit else one
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    return one.encode(enc, "replace").decode(enc)


def load_runs_fn():
    if str(RC) not in sys.path:
        sys.path.insert(0, str(RC))
    from build_export_from_zip import load_runs

    return load_runs


def ai_run_folders(rev: Path) -> list[str]:
    """Folder names of the AI attempts (not oracle, not nop) in a download: tells a saved reader answer which attempts it looked at."""
    return sorted(r["folder"] for r in load_runs_fn()(glob.escape(str(rev))) if r["agent"] not in ("ORACLE", "NOP"))


def judged_counts(rev: Path) -> dict[str, int]:
    """Test id -> in how many scored AI attempts a written grader reason came with the grade. The reader judges a test only through those reasons."""
    counts: dict[str, int] = {}
    for r in load_runs_fn()(glob.escape(str(rev))):
        if r["agent"] in ("ORACLE", "NOP") or not r["details"] or r["exc"]:
            continue
        with open(r["details"], encoding="utf-8") as f:
            data = json.load(f)
        explained = set()
        for key, node in data.items():
            for c in criterion_entries(node):
                why = c.get("reasoning")
                if isinstance(why, list):
                    why = " ".join(str(x) for x in why)
                if not c.get("error") and c["value"] is not None and why and str(why).strip():
                    explained.add(f"{key}/{c['name']}")
        for cid in explained:
            counts[cid] = counts.get(cid, 0) + 1
    return counts


def instruction_hash(pkg: Path) -> str:
    text = (pkg / "instruction.md").read_text(encoding="utf-8", errors="replace")
    return hashlib.sha256(norm(text).encode("utf-8")).hexdigest()


def golden_readable(text: str) -> bool:
    """True when the golden text the reader got has real content, not only its 'not available' and 'could not extract' notes."""
    if text.startswith("(golden not available"):
        return False
    body = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith(("### GOLDEN FILE", "(could not extract"))]
    return sum(len(ln) for ln in body) >= 20


def golden_ask(rev: Path, pkg: Path, tests, kind: str, how: str) -> dict:
    """Ask the golden-answer reader about every test that every AI attempt failed. Returns what to save as golden_reader.json.
    Raises ReaderStop, with the reason in plain words, when it cannot run or when it would look at less than all of them."""
    if str(READER) not in sys.path:
        sys.path.insert(0, str(READER))
    try:
        import golden_criterion_review as gcr
    except ImportError:
        raise ReaderStop("svc-pc-pipeline/tools/qc_zero_pass/golden_criterion_review.py is missing; run: python qc.py update, then try again")
    command = gcr.claude_argv()[0]
    if shutil.which(command) is None and not os.path.isfile(command):
        raise ReaderStop("the claude command was not found; install Claude Code and sign in (the Once section of the QC person run sheet)")
    try:
        import markitdown  # noqa: F401  the reader turns the golden files into text with it
    except ImportError:
        raise ReaderStop('the Python package markitdown is not installed; run once: python -m pip install "markitdown[docx,xlsx,pdf,pptx]"')
    except Exception as e:
        raise ReaderStop(f"the Python package markitdown does not load ({type(e).__name__}: {str(e)[:120]})")
    try:
        bundle = gcr.load_bundle(str(rev))
    except Exception as e:
        raise ReaderStop(f"the reader could not open the task files ({type(e).__name__}: {str(e)[:150]})")
    if not golden_readable(bundle["golden"]):
        raise ReaderStop("the reader found no golden answer text; it reads the golden from solution/files or solution/golden_outputs, in a .docx, .xlsx, .pdf, .pptx, .md, .txt or .csv file")
    judged = judged_counts(rev)
    seen = set(bundle["runs"]) & set(bundle["criteria"])  # the reader names a test by its criterion name, or by its v1, v2 ... key in a verifier.json grader
    unseen = sorted({t[0].split("/", 1)[1] for t in tests if judged.get(t[0], 0) >= 2 and not set(t[0].split("/", 1)) & seen})
    if unseen:  # a test the reader cannot see would be skipped without a word: that must not look like 'not flagged'
        raise ReaderStop(
            f"the reader cannot see {len(unseen)} of the tests that every AI attempt failed ({', '.join(unseen[:4])}{', ...' * (len(unseen) > 4)}); "
            "it does not read this task's grader or run files in their layout yet"
        )
    ask = len(gcr.zero_pass(bundle))
    if ask:
        say(f"asking the golden-answer reader about {ask} test{'s' * (ask != 1)} (4 AI calls, about 2 minutes)...")
    try:
        res = gcr.review_bundle(bundle)
    except Exception as e:
        raise ReaderStop(f"an AI call failed ({type(e).__name__}: {str(e)[:200]})")
    if res.get("unanswered"):  # a reply that skips a test would count as 'not a defect'
        raise ReaderStop(f"the reader's answers skipped {len(res['unanswered'])} test{'s' * (len(res['unanswered']) != 1)} ({', '.join(res['unanswered'][:4])})")
    why = {i["criterion"]: " ".join((i.get("why") or [""])[:1]).strip() for i in res.get("items", [])}
    by_name: dict[str, list] = {}
    for t in tests:
        for part in dict.fromkeys(t[0].split("/", 1)):  # by criterion name or by key, as the reader names it
            by_name.setdefault(part, []).append(t)
    hold = []
    for name in res.get("hold_ai", []):
        for t in by_name.get(name) or [None]:
            text = t[1] if t else re.sub(r"\s+", " ", bundle["criteria"].get(name, "")).strip()
            hold.append({"id": t[0] if t else name, "name": name, "why": why.get(name, ""), "text": text[:200], "weight": t[2] if t else None})
    return {
        "version": 1,
        "task": rev.parent.name,
        "rev": rev.name,
        "kind": kind,
        "kind_from": how,
        "instruction_sha256": instruction_hash(pkg),
        "ai_runs": ai_run_folders(rev),
        "zero_pass_tests": len(tests),
        "hold": hold,
        "read_first": list(res.get("read_first", [])),
        "reader": {"model": gcr.MODEL, "golden_passes": 3, "result": res},
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def golden_saved(rev: Path, pkg: Path) -> tuple[dict | None, str]:
    """(the saved reader answer, "") when golden_reader.json fits this download; otherwise (None, "missing") or (None, why it cannot be used)."""
    path = rev / GOLDEN_FILE
    if not path.is_file():
        return None, "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        ok = isinstance(data, dict) and all(isinstance(h, dict) and h.get("id") for h in data["hold"])
    except Exception:
        ok = False
    if not ok:
        return None, f"{GOLDEN_FILE} cannot be read (do not edit it by hand)"
    differs = [
        why
        for why, same in (
            (f"it was made for {data.get('rev')}, this folder is {rev.name}", data.get("rev") == rev.name),
            ("instruction.md has changed", data.get("instruction_sha256") == instruction_hash(pkg)),
            ("the AI attempts in this download are not the ones it looked at", data.get("ai_runs") == ai_run_folders(rev)),
        )
        if not same
    ]
    if differs:
        return None, f"{GOLDEN_FILE} is for other files ({'; '.join(differs)})"
    return data, ""


def golden_report(saved: dict, detail: bool) -> None:
    hold, n = saved["hold"], saved.get("zero_pass_tests", 0)
    if not hold:
        say(f"golden-answer reader (EKW task): flagged none of the {n} tests that every AI attempt failed.")
    elif detail:
        say(f"golden-answer reader (EKW task): flagged {len(hold)} of the {n} tests that every AI attempt failed (HOLD). For each it says the golden answer, not the instruction, is what the test asks for:")
        for h in hold:
            say(f"  {h['id']}: {safe(h.get('why') or '(no sentence given)')}")
    else:
        say(f"golden-answer reader (EKW task): flagged {len(hold)} of the {n} tests that every AI attempt failed (HOLD): {', '.join(h['id'] for h in hold)}")
    more = saved.get("read_first") or []
    if detail and more:
        say(f"the reader also marked {len(more)} more as read first (no row needed): {', '.join(more[:6])}{', ...' * (len(more) > 6)}")
    if detail and len(hold) + len(more) >= 9:
        say("that is many tests: the instruction may be broad enough to cover several of them. Read its scope first, then answer each row.")


def golden_stop(e: ReaderStop, rev: Path) -> int:
    """proof init on an EKW task whose reader cannot run: nothing is written, and the person is told what to send the lead."""
    say("STOP: the golden-answer reader could not run on this EKW task, so step 6 cannot be finished.")
    say(f"Reason: {e}.")
    say(f"Send your lead the task name {rev.parent.name}, the folder name {rev.name} and the lines above.")
    print("PROOF: HOLD (the golden-answer reader could not run)", flush=True)
    return 2


def golden_missing(why: str) -> int:
    """proof check on an EKW task with no usable reader answer: HOLD, never COMPLETE."""
    if why == "missing":
        say("EKW task: the golden-answer reader has no saved answer for this download, so the proof cannot be complete.")
        say("The QC person runs: python qc.py proof init <the same folder>. It asks the reader once, adds the rows it asks for and keeps the rows already there.")
        print("PROOF: HOLD (the golden-answer reader has not run on this download)", flush=True)
    else:
        say(f"EKW task: {why}.")
        say(f"Use the {GOLDEN_FILE} and {PROOF_FILE} made from this download, or run proof init on a new download.")
        print(f"PROOF: HOLD ({GOLDEN_FILE} does not fit this download)", flush=True)
    return 1


# ---- the blame reader (on by default in proof init; proof check and manage read what it saved) ---------------------
# For each test that every AI attempt failed it asks one question: was the AI solver at fault (SOLVER), is the test itself
# wrong or unfair (CRITERION), both (MIXED), or can it not tell (UNCLEAR)? It sees only the instruction, the test and the
# grader's written reasons. A test that ends CRITERION or MIXED gets a proof row like a test the golden-answer reader flags
# HOLD, so PROOF is HOLD until the row is filled; with no saved answer (not run, or the model failed) it is HOLD too. Answers
# are saved in blame_reader.json, keyed by a hash of what the reader was shown, so an unchanged test is never asked twice.

BLAME_FILE = "blame_reader.json"
BLAME_NOTE = "BLAME READER FLAGGED THIS TEST"  # starts the criterion_text cell of a proof row it asked for
BLAME_MAX = 40  # most tests asked per task, heaviest first (the tested run had no cap: 5 of 101 tasks held more than 15, one held 79)
BLAME_HELP = "ask the blame reader now (manage only; it is on by default in proof init, and manage otherwise reads the saved blame_reader.json)"
NO_BLAME_HELP = "turn the blame reader off: no AI call, no proof rows from it, and the task has no blame check"
BLAME_WORDS = ("SOLVER", "CRITERION", "MIXED", "UNCLEAR")
BLAME_CRIT_CAP, BLAME_REASON_CAP, BLAME_QUOTE_MIN = 2500, 1200, 12
BLAME_STRIP = {0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-", 0x2212: "-", 0xA0: " ", 0x2A: None, 0x60: None}  # dashes -> hyphen, no-break space -> space, asterisks and backticks dropped
BLAME_RULE = """You decide who was at fault when AI solvers failed one grading criterion of a benchmark task. Work alone, use no tools, ask no questions. The task instruction, the criterion and the grader's written reason for each failed run are on standard input. Answer with one JSON object and nothing else.

No AI solver run passed this criterion (the reference solution did).

Decide:
 blame: SOLVER if the instruction clearly asks for what the criterion requires and the solvers did not deliver it, so the criterion is fair.
        CRITERION if a solver could follow the instruction faithfully and still fail: the criterion demands something the instruction does not ask for, accepts only one of several defensible answers, wordings or formats, or depends on a fact the instruction leaves open.
        MIXED if some failures are the solvers' fault and others show the criterion is too narrow or unrequested.
        UNCLEAR if the texts do not let you decide.
 unfair_runs: how many of the failed runs were, in your view, failed unfairly (a whole number, 0 to the number of runs).
 reason: one sentence.
 instruction_quote: a sentence of the instruction copied exactly that supports your decision (empty if none).
 grader_quote: a passage of one grader reason copied exactly that supports your decision (empty if none).
Answer in this form and nothing else:
{"blame":"SOLVER","unfair_runs":0,"reason":"...","instruction_quote":"...","grader_quote":"..."}
"""


def blame_model(rule: str, text: str) -> str:
    """The reader's raw reply text, through the same helper the golden-answer reader uses (so the same claude command and model).
    The helper parses the reply itself and drops it when that fails; the parse is watched so the text can still be shown and
    read when a model wraps its JSON in other words."""
    if str(READER) not in sys.path:
        sys.path.insert(0, str(READER))
    import golden_criterion_review as gcr

    seen: list[str] = []
    parse = gcr.parse_reply
    gcr.parse_reply = lambda t: (seen.append(t), parse(t))[1]
    try:
        gcr.run_claude(rule, text, model=gcr.MODEL)
    except ValueError:  # a reply that is not one JSON object: the text in seen is read below
        pass
    finally:
        gcr.parse_reply = parse
    return seen[-1] if seen else ""


def blame_object(text: str) -> dict | None:
    """The longest JSON object in the reply that has a "blame" word, or None."""
    dec, best, size = json.JSONDecoder(), None, 0
    for m in re.finditer(r"\{", text):
        try:
            obj, end = dec.raw_decode(text[m.start():])
        except ValueError:
            continue
        if isinstance(obj, dict) and str(obj.get("blame", "")).upper() in BLAME_WORDS and end > size:
            best, size = obj, end
    return best


def zero_pass_reasons(rev: Path, ids: set[str]) -> dict[str, list[str]]:
    """Test id -> the grader's written reason from each scored AI attempt that graded it (judge passes of one attempt joined)."""
    out: dict[str, list[str]] = {}
    for r in load_runs_fn()(glob.escape(str(rev))):
        if r["agent"] in ("ORACLE", "NOP") or not r["details"] or r["exc"]:
            continue
        with open(r["details"], encoding="utf-8") as f:
            data = json.load(f)
        got: dict[str, list[str]] = {}
        for key, node in data.items():
            for c in criterion_entries(node):
                if c.get("error") or c["value"] is None or f"{key}/{c['name']}" not in ids:
                    continue
                why = c.get("reasoning")
                if isinstance(why, list):
                    why = " ".join(str(x) for x in why)
                got.setdefault(f"{key}/{c['name']}", []).append(re.sub(r"\s+", " ", str(why or "")).strip())
        for cid, parts in got.items():
            out.setdefault(cid, []).append((" / ".join(p for p in parts if p) or "(no written reason stored)")[:BLAME_REASON_CAP])
    return out


def oracle_failed(rev: Path) -> set[str]:
    """Ids of the tests the reference solution (the ORACLE run) failed: graded by an ORACLE run, every judge pass of every ORACLE run that
    graded it at 0. The blame reader is told the reference solution passed the test, as it was in the run that measured the reader, so such a
    test is left to the release check's oracle run. A missing or unreadable ORACLE run leaves the set empty, so nothing is dropped."""
    seen: dict[str, bool] = {}  # id -> some judge pass of some ORACLE run gave more than 0
    try:
        for r in load_runs_fn()(glob.escape(str(rev))):
            if r["agent"] != "ORACLE" or not r["details"] or r["exc"]:
                continue
            with open(r["details"], encoding="utf-8") as f:
                data = json.load(f)
            for key, node in data.items():
                for c in criterion_entries(node):
                    if c.get("error") or c["value"] is None:
                        continue
                    cid = f"{key}/{c['name']}"
                    seen[cid] = seen.get(cid, False) or c["value"] != 0
    except Exception:
        return set()
    return {cid for cid, passed in seen.items() if not passed}


def blame_key(instruction: str, text: str, reasons: list[str]) -> str:
    """Hash of everything the reader is shown (and of its wording, so a new prompt asks again)."""
    seen = "\n".join([BLAME_RULE, norm(instruction), norm(text), *map(norm, reasons)])
    return hashlib.sha256(seen.encode("utf-8")).hexdigest()


def blame_norm(text: str) -> str:
    """norm(), also with dashes of every length as one hyphen, no-break spaces as spaces and no asterisks or backticks: a model often
    drops the markdown marks of a sentence when it quotes it. The words themselves must still match."""
    return norm(text.translate(BLAME_STRIP))


def blame_check(ans: dict, instruction: str, reasons: list[str]) -> dict:
    """Quote check by script. A CRITERION or MIXED answer whose instruction quote and grader quote are both missing from the
    texts word for word (after blame_norm) becomes UNCLEAR. A quote that is not found is dropped, so the report never shows words
    the texts do not hold."""
    def found(q, text):
        q = blame_norm(str(q or ""))
        return len(q) >= BLAME_QUOTE_MIN and q in blame_norm(text)

    word = str(ans.get("blame", "")).upper()
    iq, gq = found(ans.get("instruction_quote"), instruction), found(ans.get("grader_quote"), " ".join(reasons))
    if word in ("CRITERION", "MIXED") and not (iq or gq):
        word = "UNCLEAR"
    return {
        "blame": word,
        "reason": re.sub(r"\s+", " ", str(ans.get("reason") or "")).strip(),
        "unfair_runs": ans.get("unfair_runs"),
        "instruction_quote": str(ans.get("instruction_quote") or "").strip() if iq else "",
        "grader_quote": str(ans.get("grader_quote") or "").strip() if gq else "",
        "downgraded": str(ans.get("blame", "")).upper() != word,
    }


def blame_saved(rev: Path) -> dict[str, dict]:
    """The saved answers of this download, key -> answer. A file that cannot be read counts as empty."""
    path = rev / BLAME_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict) and isinstance(data["answers"], dict):
            return {k: v for k, v in data["answers"].items() if isinstance(v, dict) and v.get("blame") in BLAME_WORDS}
    except Exception:
        pass
    say(f"blame reader: {BLAME_FILE} cannot be read, so I ask again (do not edit it by hand).")
    return {}


def blame_write(rev: Path, answers: dict[str, dict]) -> None:
    data = {"version": 1, "task": rev.parent.name, "rev": rev.name, "answers": answers}
    (rev / BLAME_FILE).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def blame_ask(rev: Path, pkg: Path, tests, cap: int, ask: bool) -> tuple[list[dict], int, int]:
    """(one result per test with an answer, heaviest first; tests left out by the cap; tests inside the cap with no usable answer).
    Without ask the saved answers are used and nothing is asked, whatever the cap. Raises ReaderStop when the model cannot be
    called; the answers already saved stay."""
    instruction = (pkg / "instruction.md").read_text(encoding="utf-8", errors="replace")
    reasons = zero_pass_reasons(rev, {t[0] for t in tests})  # tests come heaviest first
    answers = blame_saved(rev)
    keys = [blame_key(instruction, t[1], reasons.get(t[0], [])) for t in tests]
    todo = [k for k in keys[: max(cap, 0)] if k not in answers]
    if todo and ask:
        say(f"asking the blame reader about {len(todo)} test{'s' * (len(todo) != 1)} (1 AI call each)...")
    results, skipped, missing = [], 0, 0
    for i, ((cid, text, weight, _share), key) in enumerate(zip(tests, keys)):
        runs = reasons.get(cid, [])
        ans = answers.get(key)
        if ans is None and i >= max(cap, 0):
            skipped += 1
            continue
        if ans is None and not ask:
            missing += 1
            continue
        if ans is None:
            shown = text if len(text) <= BLAME_CRIT_CAP else text[:BLAME_CRIT_CAP] + f" [... {len(text) - BLAME_CRIT_CAP} more characters not shown]"
            stdin = (
                f"TASK INSTRUCTION (verbatim):\n<<<INSTRUCTION\n{instruction}\nINSTRUCTION>>>\n\n"
                f"GRADING CRITERION (weight {weight:.4g}):\n<<<CRITERION\n{shown}\nCRITERION>>>\n\n"
                f"The grader's written reason for each of the {len(runs)} failed runs:\n"
                + "\n".join(f"Run {n}: {r}" for n, r in enumerate(runs, 1))
            )
            reply = None
            for _try in (1, 2):  # a second call when the reply holds no answer
                try:
                    raw = blame_model(BLAME_RULE, stdin)
                except Exception as e:
                    raise ReaderStop(f"an AI call failed ({type(e).__name__}: {str(e)[:400]}); stdout and stderr are in that text")
                reply = blame_object(raw)
                if reply:
                    break
                say(f"blame reader: no answer in the reply for {cid}. Its output was: {safe(raw or '(nothing on stdout)', 300)}")
            if reply:
                ans = blame_check(reply, instruction, runs)
                answers[key] = ans
                try:
                    blame_write(rev, answers)
                except OSError as e:
                    raise ReaderStop(f"cannot save {BLAME_FILE} ({e})")
            else:  # not saved: the next run asks again, and until then the task has no blame check
                missing += 1
                ans = {"blame": "UNCLEAR", "reason": "the reader gave no usable answer", "instruction_quote": "", "grader_quote": "", "downgraded": False}
        results.append({"id": cid, "text": text, "weight": weight, **ans})
    return results, skipped, missing


def blame_lines(results: list[dict], total: int, skipped: int, missing: int, cap: int) -> list[str]:
    """The block the person reads. Plain words; the tests that may be the test's fault come first, heaviest first."""
    flagged = [r for r in results if r["blame"] in ("CRITERION", "MIXED")]
    fair = [r for r in results if r["blame"] == "SOLVER"]
    unclear = [r for r in results if r["blame"] == "UNCLEAR"]
    out = [f"blame reader: {len(results)} of the {total} tests that every AI attempt failed looked at."]
    if flagged:
        out.append(f"These zero-pass tests may be the test's fault, not the answer's ({len(flagged)}):")
        out.append("  Each one needs a row in zero_pass_proof.csv; PROOF is HOLD until it is filled.")
        for r in flagged:
            out.append(f"  {r['id']} (weight {r['weight']:.4g}, {'the test' if r['blame'] == 'CRITERION' else 'the test and the answers'}): {safe(r['reason'] or '(no sentence given)')}")
            if r["instruction_quote"]:
                out.append(f"    instruction says: \"{safe(r['instruction_quote'], 170)}\"")
            if r["grader_quote"]:
                out.append(f"    grader said: \"{safe(r['grader_quote'], 170)}\"")
    else:
        out.append("No zero-pass test looks like the test's fault.")
    for r in fair:
        out.append(f"  {r['id']} (weight {r['weight']:.4g}): the test looks fair, the instruction asks for it and the AI attempts missed it (a hard task, not a defect).")
    if unclear:
        out.append(f"  the reader could not decide: {', '.join(r['id'] for r in unclear)}")
    if skipped:
        out.append(f"  {skipped} lighter test{'s' * (skipped != 1)} left out, the cap is {cap} per task (--blame-max N changes it).")
    if missing:
        out.append(f"  {missing} test{'s' * (missing != 1)} with no answer yet: run python qc.py proof init <the same folder> again.")
    return out


def blame_note(r: dict) -> str:
    """The words in the criterion_text cell of the proof row of a flagged test: that the blame reader flagged it, and why."""
    quotes = "".join(
        f" {label}: \"{safe(r[k], 170)}\"." for label, k in (("Instruction quote", "instruction_quote"), ("Grader quote", "grader_quote")) if r.get(k)
    )
    who = "the test" if r["blame"] == "CRITERION" else "the test and the answers"
    return f"{BLAME_NOTE} ({who} may be at fault, not only the answer): {safe(r.get('reason') or '(no sentence given)', 300)}{quotes} TEST: {r['text'][:200]}"


def blame_apply(rev: Path, pkg: Path, tests, ask: bool, cap: int, report: Path | None = None) -> tuple[list, str]:
    """(the flagged tests as proof rows, why this task has no blame check). The second is "" when every test inside the cap has an answer,
    "missing" when blame_reader.json is not there (nothing is asked unless ask is set), "stopped" when the model failed, and "partial"
    when some test has no answer yet. Prints the block the person reads; report: also saves it to this file."""
    gone = oracle_failed(rev)
    left = [t for t in tests if t[0] in gone]
    if left:
        say(f"blame reader: {len(left)} zero-pass test{'s' * (len(left) != 1)} left out because the reference solution failed {'them' if len(left) != 1 else 'it'} too; the release check's oracle run (python qc.py release) covers that.")
        tests = [t for t in tests if t[0] not in gone]
        if not tests:
            return [], ""
    if not ask and not (rev / BLAME_FILE).is_file():
        return [], "missing"
    try:
        results, skipped, missing = blame_ask(rev, pkg, tests, cap, ask)
    except ReaderStop as e:
        say(f"blame reader: stopped, this task has no blame check. Reason: {e}.")
        return [], "stopped"
    except Exception as e:
        say(f"blame reader: stopped, this task has no blame check. Reason: {type(e).__name__}: {str(e)[:200]}.")
        return [], "stopped"
    lines = blame_lines(results, len(tests), skipped, missing, cap)
    for ln in lines:
        say(ln)
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    flagged = [(r["id"], blame_note(r), r["weight"], 0.0) for r in results if r["blame"] in ("CRITERION", "MIXED")]
    return flagged, "partial" if missing else ""


def blame_missing(why: str) -> int:
    """proof check on a task with zero-pass tests and no complete saved blame answer: HOLD, never COMPLETE. The check never calls the model."""
    if why == "missing":
        say(f"the blame reader has not run for this task: there is no {BLAME_FILE} for this download, so the proof cannot be complete.")
    else:
        say(f"the blame reader has not run for every zero-pass test of this task ({BLAME_FILE} lacks answers, or the AI call failed the last time).")
    say("The QC person runs: python qc.py proof init <the same folder>. It asks the reader once, adds the rows it asks for and keeps the rows already there. "
        "--no-blame skips the reader, and the task then has no blame check.")
    print("PROOF: HOLD (the blame reader has not run on this task)", flush=True)
    return 1


def blame_hold() -> int:
    """proof init when the blame reader could not run: the sheet is written, but the task does not pass without a blame check."""
    print("PROOF: HOLD (the blame reader did not run on this task; run proof init again once the AI calls work, or add --no-blame)", flush=True)
    return 1


def manage_blame(folder: Path, ask: bool, cap: int, report: Path) -> str:
    """The blame cell of the manage table for one rev folder. Reads the saved blame_reader.json and the proof sheet beside it; asks the model only with ask."""
    try:
        found = locate_rev(folder)
        if found is None:
            return "nothing to read"
        rev, pkg = found
        tests, scored, _ai, _total = zero_pass_criteria(rev)
        if scored < 2 or not tests:
            return "nothing to read"
        flagged, why = blame_apply(rev, pkg, tests, ask, cap, report)
        if why:
            return "HOLD (blame reader has not run)"
        if not flagged:
            return "no flagged tests"
        rows = proof_rows(rev / PROOF_FILE) or {}
        want = norm((pkg / "instruction.md").read_text(encoding="utf-8", errors="replace"))
        n = sum(1 for t in flagged if proof_bad(rows.get(t[0]), want))
        return f"HOLD ({n} flagged open)" if n else f"{len(flagged)} flagged (all answered)"
    except Exception as e:
        say(f"blame reader: {type(e).__name__}: {str(e)[:200]}")
        return "could not run"


# ---- the look-first pointer (steps 2 and 3; no AI call, never blocks, never passes a task) --------------------------------
# Two checks say whether a task needs a close read: the blame reader above (from blame_reader.json) and TFRL's own
# review prompt read by an AI on Opus (python qc.py tfrl-read, saved as tfrl_replay.json; a lane flags.csv can stand in with
# --replay-flags). Measured on the 105 older tasks TFRL had rated (47 rejected, 58 approved), readings locked
# before the ratings were opened and independently recounted: both checks flagged 40 tasks and TFRL rejected 25 of them (62
# percent); neither flagged 23 and TFRL rejected 4 (17 percent); one check alone sorted nothing (42 and 45 percent against 45
# percent overall). The first 151 tasks had suggested 90 percent or better and that did not hold, so this is a pointer to a task,
# never a rule: on SVC tasks both-flagged tasks were mostly approved (14 of 24).
LOOK_FILE_HELP = (
    "optional: a flags.csv (columns task_id and opus_replay_flag: 1 flagged, 0 not flagged, NA no answer) to use instead of the "
    "tfrl_replay.json that python qc.py tfrl-read saved in the rev folder"
)
TFRL_PROMPT = REPO / "docs" / "prompts" / "tfrl-comprehensive-review.md"
LOOK_ALL = (47, 105)
LOOK_GROUPS = {"both": (25, 40), "neither": (4, 23), "blame only": (13, 31), "replay only": (5, 11)}
LOOK_BY_KIND = {"EKW": {"both": (15, 16), "neither": (3, 13)}, "SVC": {"both": (10, 24), "neither": (1, 10)}}


def look_pct(pair: tuple[int, int]) -> str:
    return f"{pair[0]} of {pair[1]} ({round(100 * pair[0] / pair[1])} percent)"


def look_flags_read(path: Path) -> dict[str, str]:
    """task id -> "flagged" | "not flagged" | "no answer" from a lane flags.csv. Raises ValueError with a plain sentence when the file cannot be used."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except OSError as e:
        raise ValueError(f"cannot read {path} ({e.strerror or e})")
    if not rows or "task_id" not in rows[0] or "opus_replay_flag" not in rows[0]:
        raise ValueError(f"{path} has no task_id and opus_replay_flag columns: use the flags.csv your lead gave you")
    word = {"1": "flagged", "true": "flagged", "yes": "flagged", "0": "not flagged", "false": "not flagged", "no": "not flagged"}
    return {(r["task_id"] or "").strip(): word.get((r["opus_replay_flag"] or "").strip().lower(), "no answer") for r in rows}


def blame_state(folder: Path, cap: int = BLAME_MAX) -> str:
    """The blame reader's result for one rev folder from its saved answers, no AI call: "flagged", "not flagged" (a task with no zero-pass test
    counts here, as there is nothing to blame), or "not run" when a test inside the cap has no saved answer or the folder cannot be read."""
    try:
        found = locate_rev(folder)
        if found is None:
            return "not run"
        rev, pkg = found
        tests, scored, _ai, _total = zero_pass_criteria(rev)
        if scored < 2 or not tests:
            return "not flagged"
        gone = oracle_failed(rev)
        tests = [t for t in tests if t[0] not in gone]
        if not tests:
            return "not flagged"
        results, _skipped, missing = blame_ask(rev, pkg, tests, cap, False)
    except Exception:
        return "not run"
    if any(r["blame"] in ("CRITERION", "MIXED") for r in results):
        return "flagged"
    return "not run" if missing else "not flagged"


def look_label(blame: str, replay: str) -> str:
    if blame == "not run":
        return "no pointer (blame reader not run)"
    if replay == "no answer":
        return "no pointer (no TFRL review read)"
    return {("flagged", "flagged"): "both flagged", ("not flagged", "not flagged"): "neither flagged"}.get((blame, replay), "one flagged")


def look_lines(blame: str, replay: str, kind: str, flags_name: str = "the flags file", folder: str = "<the same folder>") -> list[str]:
    """The pointer for one task, in plain words. kind is EKW, SVC or anything else (then no kind line)."""
    label = look_label(blame, replay)
    if label.startswith("no pointer (blame"):
        return [f"look first: no pointer. The blame reader has not run on this task: python qc.py proof init {folder}."]
    if label.startswith("no pointer"):
        if flags_name:
            return [f"look first: no pointer. {flags_name} has no usable TFRL review read answer for this task."]
        return [f"look first: no pointer. This task has no TFRL review read yet: python qc.py tfrl-read {folder} (one Opus call, about 3 minutes)."]
    by = LOOK_BY_KIND.get(kind, {})
    if label == "both flagged":
        out = [
            "LOOK FIRST: both checks flagged this task (the blame reader and the TFRL review read).",
            f"  TFRL had rejected {look_pct(LOOK_GROUPS['both'])} of the older tasks that both checks flagged, "
            f"and {look_pct(LOOK_GROUPS['neither'])} of the ones neither flagged; {look_pct(LOOK_ALL)} of all of them were rejected.",
        ]
        if kind == "EKW":
            out.append(
                f"  On EKW tasks it was {by['both'][0]} of {by['both'][1]} against {by['neither'][0]} of {by['neither'][1]}. "
                "That split was seen after the data was in and is not confirmed yet."
            )
        elif kind == "SVC":
            out.append(
                f"  On SVC tasks it is weaker: TFRL approved {by['both'][1] - by['both'][0]} of the {by['both'][1]} that both checks flagged. "
                "Do not send an SVC task back for this line alone."
            )
        out.append("  This says where to read first. It does not send the task back and it does not pass it.")
        return out
    if label == "neither flagged":
        return [
            f"neither check flagged this task. TFRL had rejected {look_pct(LOOK_GROUPS['neither'])} of the older tasks like it, "
            f"against {look_pct(LOOK_ALL)} of all of them.",
            "  That is a lower chance, not a pass: every other step still applies.",
        ]
    who = "the blame reader" if blame == "flagged" else "the TFRL review read"
    return [
        f"only one check flagged this task ({who}). That did not sort tasks: TFRL had rejected {look_pct(LOOK_GROUPS['blame only'])} "
        f"of those flagged by the blame reader alone and {look_pct(LOOK_GROUPS['replay only'])} of those flagged by the TFRL review read alone, "
        f"against {look_pct(LOOK_ALL)} of all of them. Treat it like any other task."
    ]


# ---- the TFRL review read (step 2): TFRL's own review prompt, read by an AI on Opus --------------------------------------
# docs/prompts/tfrl-comprehensive-review.md is the Comprehensive Review prompt TFRL shared on 2026-09-15, unchanged. The model is given the
# task package and the stored DataOS runs in a private copy (no earlier review output, no blame answers, no TFRL ratings), has the tools
# Read, Write, Glob and Grep only, and writes its review to out/review.md. The read counts as FLAGGED when check 1.3 (ambiguity), 1.4
# (instruction and tests do not match) or 1.5 (test coverage) has severity major. One read, no voting: that is how the numbers behind
# look-first were measured. The answer is saved as tfrl_replay.json in the rev folder, keyed by a hash of instruction.md.
REPLAY_FILE = "tfrl_replay.json"
REPLAY_REPORT = "tfrl_replay_report.md"
REPLAY_TIMEOUT = 1500
REPLAY_CHECKS = {"1.3": "the prompt is ambiguous", "1.4": "the prompt and the tests do not match", "1.5": "the tests do not cover what the prompt asks"}
REPLAY_LEAVE_OUT = {"evaluations", "verifications", "tfrl_replay.json", "tfrl_replay_report.md", "blame_reader.json", "golden_reader.json", "zero_pass_proof.csv"}


def replay_json(text: str):
    """The review's final JSON object (the one with a "checks" list), or None."""
    dec, cands = json.JSONDecoder(), []
    for key in ('{"benchmark"', '{\n  "benchmark"'):
        i = text.rfind(key)
        if i >= 0:
            cands.append(i)
    cands += [m.start() for m in re.finditer(r"\{", text)][::-1][:300]
    for st in cands:
        try:
            obj, _end = dec.raw_decode(text[st:])
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("checks"), list):
            return obj
    return None


def replay_severities(js) -> dict[str, str] | None:
    """{"1.3": "good|minor|major", "1.4": ..., "1.5": ...} or None when any of the three is missing."""
    out = {}
    for ck in (js or {}).get("checks", []):
        cid, sev = str(ck.get("id")), str(ck.get("severity") or "").lower()
        if cid in REPLAY_CHECKS and sev in ("good", "minor", "major"):
            out[cid] = sev
    return out if len(out) == len(REPLAY_CHECKS) else None


def replay_addendum(pkg: Path, runs: Path, out: Path) -> str:
    return f"""
## WORKSPACE FOR THIS REVIEW (replaces the agentic-verification-workspace skill, which is not installed here)
- Task package (read-only copy): {pkg}/ - instruction.md, task.toml, tests/ (the verifier), solution/ (reference solution and golden files), environment/ (input files) and any other files of the task.
- Evaluations (read-only copy): {runs}/ - one folder per evaluation run, named eval_<id>__attempt_<n>__<agent>__<model>. Inside, eval_files/verifier/reward-details.json has the per-criterion scores and the judge's reasons, and eval_files/result.json the run result when present. The agent named NOP is the empty-answer run (it submits nothing) and ORACLE is the reference-solution run.
- You cannot start the task container here. Where the prompt tells you to run something, read the code and the stored run results instead, and say in the justification what you could not run (mark verdict-relevant gaps inconclusive, as the prompt says). You have the tools Read, Write, Glob and Grep only (no shell).
- Write your full review (prose first, then the final JSON object exactly as section 5 specifies) to {out}/review.md. Do not read or write anything outside those two folders and that output file. No network, no other tools.
- Work alone, ask no questions, and finish within about 20 minutes.
"""


def replay_ask(cwd: Path, prompt: str) -> tuple[int, str]:
    """One Opus call with cwd = the private copy; the long prompt goes on stdin. Returns (exit code, everything it printed). Tests replace this."""
    cmd = [fx_claude() or "claude", "-p", "--model", "opus", "--tools", "Read,Write,Glob,Grep", "--setting-sources", "user", "--permission-mode", "acceptEdits"]
    r = subprocess.run(cmd, cwd=str(cwd), input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=REPLAY_TIMEOUT)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def replay_saved(rev: Path, pkg: Path) -> dict | None:
    """The saved read of this task when it is usable (flag 0 or 1 and the same instruction.md), else None."""
    try:
        data = json.loads((rev / REPLAY_FILE).read_text(encoding="utf-8-sig"))
        if data.get("flag") in ("0", "1") and data.get("instruction_sha") == instruction_hash(pkg):
            return data
    except Exception:
        pass
    return None


def replay_state(folder: Path) -> str:
    """"flagged" | "not flagged" | "no answer" from the saved tfrl_replay.json of a rev folder. No AI call."""
    try:
        found = locate_rev(folder)
        data = replay_saved(found[0], found[1]) if found else None
    except Exception:
        data = None
    return "no answer" if data is None else ("flagged" if data["flag"] == "1" else "not flagged")


def replay_present(folder: Path) -> bool:
    found = locate_rev(folder)
    return bool(found and (found[0] / REPLAY_FILE).is_file())


def replay_report(rev: Path, data: dict, saved: bool) -> int:
    flagged = data["flag"] == "1"
    majors = [c for c, v in (data.get("severities") or {}).items() if v == "major"]
    if flagged:
        say("TFRL review read: FLAGGED. Major on " + ", ".join(f"check {c} ({REPLAY_CHECKS[c]})" for c in majors) + ".")
    else:
        say("TFRL review read: no major on checks 1.3 (ambiguity), 1.4 (prompt and tests) or 1.5 (test coverage).")
    say(f"  The AI's whole review is in {rev / REPLAY_REPORT}. It is advice: it does not change the task and it does not send it back.")
    if saved:
        say("  (saved answer for this task, no AI call; --again asks again)")
    say("  Next: python qc.py look-first <the same folder> says whether this and the blame reader agree.")
    print("TFRL READ: " + ("flagged (major on " + ", ".join(majors) + ")" if flagged else "not flagged"), flush=True)
    return 0


def cmd_tfrl_read(a) -> int:
    """qc.py tfrl-read REV_FOLDER: one Opus read of the task with TFRL's own review prompt. Exit 0 flagged or not (a pointer, not a check), 2 could not run."""
    import tempfile
    import time

    folder = Path(a.task_folder).resolve()
    found = locate_rev(folder)
    if found is None:
        say(f"cannot run: {folder} needs an instruction.md and an evaluations folder. Point this at the rev_<n>__<task id> folder of a Dataset with runs download.")
        print("TFRL READ: could not run (not a rev folder)", flush=True)
        return 2
    rev, pkg = found
    if not TFRL_PROMPT.is_file():
        say("docs/prompts/tfrl-comprehensive-review.md is missing. Run: python qc.py update, then try again.")
        print("TFRL READ: could not run (prompt file missing)", flush=True)
        return 2
    saved = replay_saved(rev, pkg)
    if saved and not a.again:
        return replay_report(rev, saved, True)
    if not (rev / "evaluations").is_dir() or not any((rev / "evaluations").glob("eval_*")):
        say("this download has no evaluation runs to read: download Dataset with runs after the DataOS pipeline finished.")
        print("TFRL READ: could not run (no evaluation runs)", flush=True)
        return 2
    work = Path(tempfile.mkdtemp(prefix="qc_tfrl_"))
    try:
        skip = shutil.ignore_patterns(*REPLAY_LEAVE_OUT)
        shutil.copytree(pkg, work / "pkg", ignore=skip)
        shutil.copytree(rev / "evaluations", work / "runs")
        (work / "out").mkdir()
        prompt = TFRL_PROMPT.read_text(encoding="utf-8") + replay_addendum(work / "pkg", work / "runs", work / "out")
        say("TFRL review read: asking Opus to review the task with TFRL's own review prompt (one AI call, about 3 minutes)...")
        t0 = time.time()
        try:
            rc, printed = replay_ask(work, prompt)
        except subprocess.TimeoutExpired:
            say(f"TFRL review read: no answer within {REPLAY_TIMEOUT // 60} minutes. Run it again.")
            print("TFRL READ: could not run (timed out)", flush=True)
            return 2
        except OSError as e:
            say(f"cannot start `claude`: {e}. Is the claude command installed and on your PATH?")
            print("TFRL READ: could not run (no claude command)", flush=True)
            return 2
        secs = int(time.time() - t0)
        review = work / "out" / "review.md"
        text = review.read_text(encoding="utf-8", errors="replace") if review.is_file() else ""
        sev = replay_severities(replay_json(text) or replay_json(printed))
        if sev is None:
            say("TFRL review read: no usable answer (the final JSON with checks 1.3, 1.4 and 1.5 is missing). What the AI printed: " + safe(printed or "(nothing)", 400))
            print("TFRL READ: could not run (no usable answer)", flush=True)
            return 2
        (rev / REPLAY_REPORT).write_text(text or printed, encoding="utf-8")
        data = {
            "version": 1,
            "task": rev.parent.name,
            "rev": rev.name,
            "flag": "1" if "major" in sev.values() else "0",
            "severities": sev,
            "instruction_sha": instruction_hash(pkg),
            "model": "opus",
            "secs": secs,
            "made": datetime.now().isoformat(timespec="seconds"),
        }
        (rev / REPLAY_FILE).write_text(json.dumps(data, indent=1), encoding="utf-8")
        return replay_report(rev, data, False)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def cmd_look(a) -> int:
    """qc.py look-first REV_FOLDER [--replay-flags FLAGS.csv]: print the pointer for one task. No AI call. Exit 0 whatever it says (it is not a check).
    The TFRL review read comes from the rev folder's tfrl_replay.json (python qc.py tfrl-read), or from FLAGS.csv when one is given."""
    folder = Path(a.task_folder).resolve()
    found = locate_rev(folder)
    if found is None:
        say(f"cannot run: {folder} needs an instruction.md and an evaluations folder. Point this at the rev_<n>__<task id> folder of a Dataset with runs download.")
        return 2
    rev, pkg = found
    m = re.match(r"^rev_\d+__(\d+)$", rev.name)
    tid = m.group(1) if m else ""
    if a.replay_flags:
        try:
            flags = look_flags_read(Path(a.replay_flags).resolve())
        except ValueError as e:
            say(f"look-first: {e}.")
            return 2
        replay, source = flags.get(tid, "no answer"), Path(a.replay_flags).name
    else:
        replay, source = replay_state(folder), None
    blame = blame_state(folder, a.blame_max)
    kind = task_kind(pkg, getattr(a, "tab", None))[0]
    for ln in look_lines(blame, replay, kind, source, str(a.task_folder)):
        say(ln)
    print(f"LOOK: {look_label(blame, replay)} (task {tid or rev.name}; the blame reader {blame}, the TFRL review read {replay})", flush=True)
    return 0


# ---- the sibling reader (step 2, after the SOP 6c table) ---------------------------------------------------------------
# python qc.py siblings TASK_DIR PROBLEMS.md: for each test a problem names, one AI call names up to 3 OTHER tests of the same
# task that have the same kind of gap. The check is required: every test it suggests becomes a row of siblings_answers.csv, and
# step 2 is not done until each row has a yes or no and a note. `python qc.py siblings ... --check` makes no AI call, ends with
# SIBLINGS: COMPLETE or SIBLINGS: HOLD (n open) and exits 1 on HOLD, like proof check. The AI answers are saved next to
# problems.md, so a rerun asks nothing and keeps the answers already written.

SIB_CACHE = "siblings_reader.json"
SIB_OUT = "siblings.md"
SIB_ANS = "siblings_answers.csv"
SIB_COLS = ["problem", "test_id", "weight", "reason", "test_start", "answer", "note"]
SIB_NOTE_WORDS = 4
SIB_INSTR_CAP, SIB_TEST_CAP, SIB_SHOW_CAP, SIB_MAX, SIB_CONC, SIB_TIMEOUT = 12000, 400, 200, 3, 4, 600
SIB_HEADING = "Check these tests (required; about half are judged to have the same flaw)"
SIB_PLACEHOLDER = "[another test]"
SIB_PROMPT = """You are a reviewer of grading criteria for a benchmark task. A task has an instruction written for an AI model, and a list of criteria (a grader checks an AI's answer against each one, each with a weight).

A human quality reviewer found a defect in ONE criterion of this task (shown below as criterion A, with the reviewer's words about the defect). Other criteria of the same task may have the same kind of defect.

Name at most 3 OTHER criteria of this task (never criterion A) that have the same kind of gap as the one the reviewer described. Name fewer than 3, or none, if fewer fit. Judge by what the criterion demands against what the instruction asks for and supports.

Return only JSON, no other text, in this form:
{"siblings": [{"id": "<criterion id exactly as listed>", "reason": "<one line>"}]}
"""


class SibStop(Exception):
    """The sibling reader cannot be called (or the package cannot be read)."""


def sib_package(task_dir: Path) -> Path:
    """The package folder (the one with instruction.md or tests/task_prompt.txt) for a task folder, a working folder holding a copy named task, or a rev folder."""
    for cand in (task_dir, task_dir / "task", task_dir / "task_files"):
        if (cand / "instruction.md").is_file() or (cand / "tests" / "task_prompt.txt").is_file():
            return cand
    found = locate_rev(task_dir)
    if found:
        return found[1]
    raise SibStop(f"no task package in {task_dir} (expected instruction.md and tests/)")


def sib_tests(pkg: Path) -> tuple[str, list[tuple[str, float, str]]]:
    """(instruction text, every test of the package as (id, weight, text), in file order).

    Reads files only, never runs package code. Two layouts: tests/verifier.json (a test is one verifier; a verifier with no
    written weight shares what the written weights leave) and tests/reward.toml with one <dir>/judge*.toml per group (a
    test is one [[criterion]]; its weight is the group's weight times its share of the group). Weights are shares of the whole
    task. Checks written as python code in the second layout are not listed."""
    ins = ""
    for rel in ("instruction.md", "tests/task_prompt.txt"):
        if (pkg / rel).is_file():
            ins = (pkg / rel).read_text(encoding="utf-8", errors="replace")
            break
    tests: list[tuple[str, float, str]] = []
    vj = pkg / "tests" / "verifier.json"
    if vj.is_file():
        try:
            vs = json.loads(vj.read_text(encoding="utf-8-sig")).get("verifiers", [])
        except ValueError as e:
            raise SibStop(f"tests/verifier.json cannot be read ({e})")
        ws = [(v.get("metadata") or {}).get("weight") for v in vs]
        written = sum(w for w in ws if isinstance(w, (int, float)))
        blank = [w for w in ws if not isinstance(w, (int, float))]
        share = (1 - written) / len(blank) if blank else 0.0
        for v, w in zip(vs, ws):
            a, meta = v.get("assertion") or {}, v.get("metadata") or {}
            text = ((a.get("rubric") or {}).get("prompt") if a.get("type") == "rubric" else meta.get("how_justification")) or ""
            tests.append((str(v.get("name")), float(w) if isinstance(w, (int, float)) else share, text))
    else:
        import tomllib

        groups = []
        for tp in sorted((pkg / "tests").glob("*/judge*.toml")):
            try:
                d = tomllib.loads(tp.read_text(encoding="utf-8"))
            except Exception as e:
                raise SibStop(f"{tp.name} cannot be read ({e})")
            crit = d.get("criterion") or []
            gw = float((d.get("judge") or {}).get("weight") or 1.0)
            groups.append((gw, crit))
        total = sum(gw for gw, _ in groups) or 1.0
        for gw, crit in groups:
            inner = sum(float(c.get("weight") or 1.0) for c in crit) or 1.0
            for c in crit:
                tests.append((str(c.get("name")), gw / total * float(c.get("weight") or 1.0) / inner, str(c.get("description") or "")))
    if not tests:
        raise SibStop("no tests found in the package (tests/verifier.json or tests/*/judge*.toml)")
    return ins, tests


def sib_blocks(text: str) -> list[tuple[str, str]]:
    """problems.md as (label, text) per block; a block starts at a line beginning P1., P2. and so on (SOP 6c step 1)."""
    marks = list(re.finditer(r"^[ \t]*P(\d+)\.", text, re.M))
    return [(f"P{m.group(1)}", text[m.start(): marks[i + 1].start() if i + 1 < len(marks) else len(text)].strip()) for i, m in enumerate(marks)]


def sib_spans(text: str, tid: str) -> list[tuple[int, int]]:
    """Where test id tid appears in text as a whole token. An id with a digit, hyphen or underscore counts anywhere; a plain-word
    id (which is also an ordinary word) counts only inside quotes, backticks, brackets or parentheses, or after the word
    test, criterion, criteria or check."""
    out = []
    plain = not re.search(r"[\d_-]", tid)
    for m in re.finditer(r"(?<![A-Za-z0-9_-])" + re.escape(tid) + r"(?![A-Za-z0-9_-])", text):
        if plain:
            before, after = text[max(0, m.start() - 12): m.start()], text[m.end(): m.end() + 1]
            wrapped = before[-1:] in "`'\"([{" and after in "`'\")]}"
            if not (wrapped or re.search(r"(?i)\b(test|criterion|criteria|check)s?\s+$", before)):
                continue
        out.append((m.start(), m.end()))
    return out


def sib_named(text: str, ids: list[str]) -> list[str]:
    """The test ids a problem block names, in order of first mention."""
    hits = [(sib_spans(text, t)[0][0], t) for t in ids if sib_spans(text, t)]
    return [t for _, t in sorted(hits)]


def sib_redact(text: str, others: list[str]) -> str:
    """text with every id in others replaced by the placeholder, so the reader cannot see which tests were named together."""
    spans = sorted((s, e) for t in others for s, e in sib_spans(text, t))
    out, pos = [], 0
    for s, e in spans:
        if s >= pos:
            out.append(text[pos:s])
            out.append(SIB_PLACEHOLDER)
            pos = e
    return "".join(out) + text[pos:]


def one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def sib_stdin(ins: str, tests, a: str, problem: str) -> str:
    """The reader's input, laid out as in the sibling sweep that measured it."""
    lines = [f"[{i}] weight {w:.4f}: {one_line(t)[:SIB_TEST_CAP]}" for i, w, t in tests]
    atext = one_line(next(t for i, _w, t in tests if i == a))[:SIB_TEST_CAP]
    return (f"TASK INSTRUCTION:\n{ins.strip()[:SIB_INSTR_CAP]}\n\nCRITERIA OF THE TASK ({len(lines)}):\n" + "\n".join(lines) +
            f"\n\nCRITERION A: [{a}] {atext}\n\nTHE REVIEWER'S WORDS ABOUT THE DEFECT IN A:\n{problem}\n")


def sib_parse(reply: str, valid: set[str], a: str) -> list[dict] | None:
    """The tests the reader named, [] when it named none, None when the reply holds no usable JSON. Ids not in the task, A itself and repeats are dropped; at most 3 kept."""
    m = re.search(r"\{.*\}", reply or "", re.S)
    if not m:
        return None
    try:
        sib = json.loads(m.group(0)).get("siblings")
    except (ValueError, AttributeError):
        return None
    if not isinstance(sib, list):
        return None
    out, seen = [], set()
    for x in sib:
        cid = str(x.get("id", "")).strip().strip("[]") if isinstance(x, dict) else ""
        if cid in valid and cid != a and cid not in seen:
            seen.add(cid)
            out.append({"id": cid, "reason": re.sub(r"\s+", " ", str(x.get("reason", ""))).strip()[:300]})
    return out[:SIB_MAX]


def sib_model(prompt: str, stdin: str) -> str:
    """The reader's raw reply: claude -p --model sonnet with no tools, run in an empty temporary folder, the input on stdin only."""
    import tempfile

    with tempfile.TemporaryDirectory() as empty:
        try:
            r = subprocess.run(["claude", "-p", "--model", "sonnet", "--tools", "", "--output-format", "text", prompt], input=stdin,
                               cwd=empty, capture_output=True, text=True, timeout=SIB_TIMEOUT, encoding="utf-8", errors="replace")
        except FileNotFoundError:
            raise SibStop("the claude command was not found")
        except subprocess.TimeoutExpired:
            raise SibStop(f"an AI call took more than {SIB_TIMEOUT} seconds")
    blob = (r.stdout + r.stderr).lower()
    if "weekly limit" in blob or "hit your limit" in blob:
        raise SibStop("the Claude usage limit is reached")
    if r.returncode != 0 and not r.stdout.strip():
        raise SibStop(f"an AI call failed (exit {r.returncode}): {safe(r.stderr or '(no message)', 200)}")
    return r.stdout


def sib_key(stdin: str) -> str:
    """Hash of everything the reader is shown and of its wording, so a new prompt or a changed problem asks again."""
    return hashlib.sha256((SIB_PROMPT + "\n" + stdin).encode("utf-8")).hexdigest()


def sib_saved(path: Path) -> dict[str, list[dict]]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return {k: v for k, v in data["answers"].items() if isinstance(v, list)}
    except Exception:
        say(f"sibling reader: {path.name} cannot be read, so I ask again (do not edit it by hand).")
        return {}


def sib_ask_one(stdin: str, valid: set[str], a: str) -> list[dict]:
    """One reader call, a second call when the reply holds no usable JSON. Raises SibStop when both give none."""
    for _try in (1, 2):
        got = sib_parse(sib_model(SIB_PROMPT, stdin), valid, a)
        if got is not None:
            return got
    raise SibStop(f"the reader gave no usable answer twice for test {a}; run the same command again")


def sib_picked(items, answers, named_all) -> list[dict]:
    """The tests suggested for one problem block, in order, each once. A test problems.md already names is left out: it is already on the list."""
    picked, seen = [], set()
    for _a, key in items:
        for s in answers.get(key, []):
            if s["id"] not in named_all and s["id"] not in seen:
                seen.add(s["id"])
                picked.append(s)
    return picked


def sib_rows(blocks, plan, answers, by_id) -> list[dict]:
    """One row of siblings_answers.csv for every suggested test of every problem block, answer and note empty."""
    named_all = {t for ids in plan.values() for t in ids}
    rows = []
    for label, _text, _ids, items in blocks:
        for s in sib_picked(items, answers, named_all):
            w, t = by_id[s["id"]]
            rows.append({"problem": label, "test_id": s["id"], "weight": f"{w:.4f}", "reason": s["reason"],
                         "test_start": one_line(t)[:SIB_SHOW_CAP], "answer": "", "note": ""})
    return rows


def sib_read_answers(path: Path) -> dict[tuple[str, str], dict]:
    """The rows of siblings_answers.csv by (problem, test id). {} when the file is not there. A file that cannot be read stops the command, so it is never overwritten."""
    if not path.is_file():
        return {}
    try:
        text = path.read_bytes().decode("utf-8-sig")
        return {((r.get("problem") or "").strip(), (r.get("test_id") or "").strip()): r for r in csv.DictReader(io.StringIO(text, newline=""))}
    except Exception as e:
        raise SibStop(f"{path.name} cannot be read ({e}); fix it or move it away, then run the command again")


def sib_write_answers(path: Path, rows: list[dict], old: dict) -> None:
    """Write siblings_answers.csv: the current suggestions, each keeping the answer and note already written for the same problem and test.
    A row that is no longer suggested but has an answer or a note stays at the end, so written work is never lost."""
    out, keys = [], set()
    for r in rows:
        keys.add((r["problem"], r["test_id"]))
        prev = old.get((r["problem"], r["test_id"]))
        if prev:
            r = dict(r, answer=(prev.get("answer") or "").strip(), note=(prev.get("note") or "").strip())
        out.append(r)
    stale = "(no longer suggested) "
    for k, prev in old.items():
        if k not in keys and ((prev.get("answer") or "").strip() or (prev.get("note") or "").strip()):
            row = {c: (prev.get(c) or "").strip() for c in SIB_COLS}
            if not row["reason"].startswith(stale):
                row["reason"] = stale + row["reason"]
            out.append(row)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=SIB_COLS)
        w.writeheader()
        w.writerows(out)
    tmp.replace(path)


def sib_bad(row) -> list[str]:
    """What is still missing in one row of siblings_answers.csv; [] when the row is answered."""
    if row is None:
        return ["no row for this test in siblings_answers.csv (run without --check first)"]
    bad = []
    if (row.get("answer") or "").strip().lower() not in ("yes", "no"):
        bad.append("answer must be yes or no")
    if len((row.get("note") or "").split()) < SIB_NOTE_WORDS:
        bad.append(f"note needs {SIB_NOTE_WORDS} words or more (yes: what you changed; no: why the test is fair)")
    return bad


def sib_check(problems: Path, plan, blocks, answers, by_id, uncached: int) -> int:
    """No AI call. One line per suggested test, then SIBLINGS: COMPLETE or SIBLINGS: HOLD (n open). Returns 1 on HOLD, like proof check."""
    held = 0
    if not any(plan.values()):
        print("HOLD: problems.md names no test id of this task, so the reader cannot run (name the tests each problem is about, SOP 6c)")
        held += 1
    if uncached:
        print(f"HOLD: the reader has not run on {uncached} named test{'s' * (uncached != 1)}; run: python qc.py siblings <task> <problems.md>")
        held += 1
    saved = sib_read_answers(problems.parent / SIB_ANS)
    for r in sib_rows(blocks, plan, answers, by_id):
        bad = sib_bad(saved.get((r["problem"], r["test_id"])))
        held += bool(bad)
        print(f"{'; '.join(bad) or 'OK'}: {r['problem']} {r['test_id']}")
    print("SIBLINGS: COMPLETE" if not held else f"SIBLINGS: HOLD ({held} open)")
    return 1 if held else 0


def sib_report(path: Path, task: str, blocks, plan, answers, by_id, uncached: int) -> list[str]:
    """Write siblings.md and return the console lines. blocks: (label, text, named ids, [(id, key)]); plan: label -> named ids; answers: key -> list."""
    named_all = {t for ids in plan.values() for t in ids}
    md = [f"# Sibling tests for {task}", "",
          f"Required for step 2. Open each test below and read it against the instruction. For every row of {SIB_ANS} write yes (the same flaw: "
          f"fix it the way you fixed the listed test) or no (you read it and it is fair), and a note of {SIB_NOTE_WORDS} words or more. "
          "Then run: python qc.py siblings <task> <problems.md> --check", ""]
    console, shown = [], 0
    for label, text, ids, items in blocks:
        md += [f"## {label}. tests named: {', '.join(ids) if ids else '(none found)'}", ""]
        if not ids:
            md += ["No test id of this task is named in this problem, so the reader was not asked.", ""]
            console.append(f"{label}: no test id found in the block")
            continue
        picked = sib_picked(items, answers, named_all)
        md += [f"### {SIB_HEADING}", ""]
        for s in picked:
            w, t = by_id[s["id"]]
            md.append(f"- `{s['id']}` (weight {w:.4f}): {s['reason']}")
            md.append(f"  Test: {one_line(t)[:SIB_SHOW_CAP]}")
        if not picked:
            md.append("No other test suggested." if not uncached else "No answer saved yet for this block.")
        md.append("")
        shown += len(picked)
        console.append(f"{label}: named {', '.join(ids)}; suggested {', '.join(s['id'] for s in picked) or 'none'}")
    path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return [f"{len(blocks)} problem blocks, {shown} tests suggested in all (required: answer each one in {SIB_ANS})", *console]


def cmd_siblings(a) -> int:
    task, problems = Path(a.task_dir).resolve(), Path(a.problems).resolve()
    if not task.exists() or not problems.is_file():
        say("task folder or problems file not found.")
        return 2
    if a.check:
        a.no_ask = True  # --check never calls the AI
    try:
        pkg = sib_package(task)
        ins, tests = sib_tests(pkg)
        by_id = {i: (w, t) for i, w, t in tests}
        ids = [i for i, _w, _t in tests]
        parts = sib_blocks(problems.read_text(encoding="utf-8", errors="replace"))
        if not parts:
            raise SibStop("problems.md has no block starting P1., P2. (SOP 6c step 1)")
        plan = {label: sib_named(text, ids) for label, text in parts}
        named_all = sorted({t for v in plan.values() for t in v})
        cache_path = problems.parent / SIB_CACHE
        answers = sib_saved(cache_path)
        valid = set(ids)
        jobs, blocks = {}, []
        for label, text in parts:
            items = []
            for t in plan[label]:
                stdin = sib_stdin(ins, tests, t, sib_redact(text, [o for o in named_all if o != t]))
                key = sib_key(stdin)
                items.append((t, key))
                jobs[key] = (stdin, t)
            blocks.append((label, text, plan[label], items))
        todo = {k: v for k, v in jobs.items() if k not in answers}
        if todo and not a.no_ask:
            say(f"asking the sibling reader {len(todo)} time{'s' * (len(todo) != 1)} (1 AI call each, {SIB_CONC} at once)...")
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(SIB_CONC) as ex:
                futs = {k: ex.submit(sib_ask_one, s, valid, t) for k, (s, t) in todo.items()}
                failure = None
                for k, f in futs.items():
                    try:
                        answers[k] = f.result()
                    except SibStop as e:
                        failure = failure or e
                    if k in answers:
                        cache_path.write_text(json.dumps({"version": 1, "answers": answers}, indent=1, ensure_ascii=False), encoding="utf-8")
                if failure:
                    raise failure
        uncached = sum(1 for k in jobs if k not in answers)
        if a.check:
            return sib_check(problems, plan, blocks, answers, by_id, uncached)
        lines = sib_report(problems.parent / SIB_OUT, task.parent.name if task.name == "task" else task.name, blocks, plan, answers, by_id, uncached)
        if not uncached:
            ans_path = problems.parent / SIB_ANS
            sib_write_answers(ans_path, sib_rows(blocks, plan, answers, by_id), sib_read_answers(ans_path))
    except SibStop as e:
        say(f"siblings: stopped. {e}")
        return 2
    say(f"siblings: {len(jobs)} reader answers needed, {len(todo)} asked now, {len(jobs) - len(todo)} from the saved file.")
    if uncached:
        say(f"siblings: {uncached} answer{'s' * (uncached != 1)} not saved yet (--no-ask); run again without it.")
    for ln in lines:
        say(f"siblings: {ln}")
    say(f"siblings: wrote {problems.parent / SIB_OUT}")
    if not uncached:
        say(f"siblings: wrote {problems.parent / SIB_ANS}. Step 2 is not done until every row has a yes or no and a note. Then run: python qc.py siblings {a.task_dir} {a.problems} --check")
    return 0


def fill_help() -> None:
    say("fill the last three columns of every row:")
    say(f"  instruction_quote: the sentence of the instruction that asks for the test, copied word for word ({QUOTE_WORDS} words or more)")
    say("  golden_location: where the golden answer meets the test")
    say(f"  other_valid_answer: why a different valid answer would also pass it ({ANSWER_WORDS} words or more)")
    say("then run: python qc.py proof check <the same folder>")


def proof_extend(path: Path, rows: list[list[str]]):
    """Add the rows a proof sheet lacks to the end of it; the rows already there are not changed. None when nothing is missing."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:  # saved from Excel as plain "CSV (Comma delimited)"
        text = raw.decode("cp1252", errors="replace")
    table = list(csv.reader(io.StringIO(text, newline="")))
    head = table[0] if table else []
    lacking = [c for c in PROOF_COLS if c not in head]
    if lacking:
        say(f"cannot add rows: {path.name} lacks the column(s) {', '.join(lacking)}. Save it as plain CSV (comma delimited) and keep the header row that proof init wrote.")
        return 2
    at = head.index("criterion_id")
    have = {(r[at] if len(r) > at else "").strip() for r in table[1:]}
    add = [r for r in rows if r[0] not in have]
    if not add:
        return None
    for r in add:
        new = [""] * len(head)
        for col, val in zip(PROOF_COLS, r):
            new[head.index(col)] = val
        table.append(new)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows(table)
        os.replace(tmp, path)
    except OSError as e:  # for example the sheet is open in Excel
        tmp.unlink(missing_ok=True)
        say(f"cannot add rows to {path}: {e}. Close the file in Excel and run the same command again. Nothing was changed.")
        return 2
    say(f"added {len(add)} row{'s' * (len(add) != 1)} to the end of {path}; the rows already there were not changed: {', '.join(r[0] for r in add)}")
    fill_help()
    return 0


def proof_init(path: Path, heavy, light: int, scored: int, rule: str, flagged=(), extend: bool = False, who: str = "the golden-answer reader") -> int:
    """Write the proof sheet: a row for every heavy test, then one for every other test a reader (who) flagged.
    A sheet that already exists is never overwritten. With extend (an EKW task) the rows it lacks are added at the end."""
    rows = [[cid, text if text.startswith(BLAME_NOTE) else text[:200], "" if weight is None else f"{weight:.4g}", "", "", ""] for cid, text, weight, _share in [*heavy, *flagged]]
    if path.exists():
        done = proof_extend(path, rows) if extend else None
        if done is not None:
            return done
        say(f"{path} already exists, so I stopped and changed nothing. Move it away if you want a fresh one.")
        return 2
    with open(path, "x", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(PROOF_COLS)
        w.writerows(rows)
    more = f", and {who} flagged {len(flagged)} more test{'s' * (len(flagged) != 1)}" if flagged else ""
    say(f"{len(heavy)} heavy test{'s' * (len(heavy) != 1)} failed in all {scored} scored AI attempts ({rule}){more}. Wrote {path}")
    say(f"lighter zero-pass tests left out (they need no proof): {light}")
    fill_help()
    return 0


def proof_rows(path: Path):
    """The rows of a proof sheet by criterion_id; {} when there is no sheet; None (after saying why) when its header lacks a column."""
    if not path.exists():
        return {}
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:  # saved from Excel as plain "CSV (Comma delimited)"
        text = raw.decode("cp1252", errors="replace")
    rd = csv.DictReader(io.StringIO(text, newline=""))
    lacking = [c for c in PROOF_COLS if c not in (rd.fieldnames or [])]
    if lacking:
        say(f"cannot run: {path.name} lacks the column(s) {', '.join(lacking)}. Save it as plain CSV (comma delimited) and keep the header row that proof init wrote.")
        return None
    return {(r["criterion_id"] or "").strip(): r for r in rd}


def proof_bad(r, want: str) -> list[str]:
    """What is wrong with one proof row (r is None when the row is missing); want is the normalised instruction."""
    if r is None:
        return ["MISSING ROW"]
    bad = []
    quote, where, other = (r[k] or "" for k in ("instruction_quote", "golden_location", "other_valid_answer"))
    n = len(norm(quote).split())
    if n == 0:
        bad.append("EMPTY FIELD instruction_quote")
    elif n < QUOTE_WORDS:
        bad.append(f"QUOTE TOO SHORT ({n} words, need {QUOTE_WORDS})")
    elif norm(quote) not in want:
        bad.append("QUOTE NOT FOUND (copy the sentence from instruction.md word for word)")
    if not where.strip():
        bad.append("EMPTY FIELD golden_location")
    if len(other.split()) < ANSWER_WORDS:
        bad.append(f"EMPTY FIELD other_valid_answer (need {ANSWER_WORDS} words, has {len(other.split())})")
    return bad


def proof_check(path: Path, tests, instruction: str) -> int:
    rows = proof_rows(path)
    if rows is None:
        return 2
    if not path.exists():
        say(f"{path.name} does not exist yet. Run: python qc.py proof init <the same folder>")
    want, held = norm(instruction), 0
    for cid, *_ in tests:
        bad = proof_bad(rows.get(cid), want)
        held += bool(bad)
        print(f"{'; '.join(bad) or 'OK'}: {cid}")
    print("PROOF: COMPLETE" if not held else f"PROOF: HOLD ({held} open)")
    return 1 if held else 0


def proof_main(a) -> int:
    """proof init / proof check. Exit codes: 0 complete or nothing to prove, 1 hold (also when fewer than 2 AI attempts were scored), 2 could not run.
    On an EKW task the tests the golden-answer reader flags HOLD need a row too: init asks the reader once and saves
    golden_reader.json, check only reads it, so the manager needs no claude command and gets the same answer. The blame reader works
    the same way for EKW and SVC tasks (blame_reader.json): a test it flags needs a row too, and a task with zero-pass tests and no
    complete blame answer is a HOLD, unless init is run with --no-blame."""
    try:
        folder = Path(a.task_folder).resolve()
        found = locate_rev(folder)
        if found is None:
            say(f"cannot run: {folder} needs an instruction.md and an evaluations folder. Point this at the "
                "rev_<n>__<task id> folder of a Dataset with runs download.")
            return 2
        rev, pkg = found
        tests, scored, ai, total = zero_pass_criteria(rev)
        heavy = [t for t in tests if t[3] >= HEAVY_SHARE - 1e-9]  # only heavy tests need a proof
        kind, how = golden_kind(pkg, getattr(a, "tab", None))
        if scored < 2:  # fewer than 2 scored AI attempts cannot show which tests every attempt failed: never COMPLETE
            say(f"only {scored} of {ai} AI attempts could be scored, and the rule needs 2. Run the DataOS pipeline again, then download the new Dataset with runs.")
            if a.action == "check":
                print(f"PROOF: HOLD (only {scored} of {ai} AI attempts could be scored)")
            return 1
        saved = None
        if kind == "EKW":
            if not tests:
                say(f"golden-answer reader: nothing to read, no test failed in all {scored} scored AI attempts.")
            else:
                saved, why = golden_saved(rev, pkg)
                if saved is None and a.action == "check":  # no usable reader answer: HOLD, never COMPLETE
                    return golden_missing(why)
                if saved is None and why != "missing":
                    say(f"cannot run: {why}. Start step 6 again from a fresh download folder.")
                    print(f"PROOF: HOLD ({GOLDEN_FILE} does not fit this download)", flush=True)
                    return 2
                if saved is None:  # init, and the reader has not looked at this download yet
                    try:
                        saved = golden_ask(rev, pkg, tests, kind, how)
                    except ReaderStop as e:
                        return golden_stop(e, rev)
                    except Exception as e:  # whatever else goes wrong, the task still does not pass step 6 without a reader answer
                        return golden_stop(ReaderStop(f"unexpected error {type(e).__name__}: {str(e)[:200]}"), rev)
                    try:
                        (rev / GOLDEN_FILE).write_text(json.dumps(saved, indent=1, ensure_ascii=False), encoding="utf-8")
                    except OSError as e:
                        return golden_stop(ReaderStop(f"cannot save {GOLDEN_FILE} ({e})"), rev)
                golden_report(saved, detail=a.action == "init")
        bflag, bwhy, no_blame = [], "", bool(getattr(a, "no_blame", False))
        if tests and no_blame:
            say("blame reader: skipped (--no-blame), so this task has no blame check.")
        elif tests:
            bflag, bwhy = blame_apply(rev, pkg, tests, a.action == "init", getattr(a, "blame_max", BLAME_MAX))
            if bwhy and a.action == "check":  # no complete blame answer: HOLD, never COMPLETE, and no AI call
                return blame_missing(bwhy)
        have = {t[0] for t in heavy}
        flagged = [(h["id"], h.get("text") or "", h.get("weight"), 0.0) for h in (saved or {}).get("hold", []) if h["id"] not in have]
        n_golden = len(flagged)
        have |= {f[0] for f in flagged}
        flagged += [b for b in bflag if b[0] not in have]
        who = " and ".join(n for n, k in (("the golden-answer reader", n_golden), ("the blame reader", len(flagged) - n_golden)) if k)
        need = heavy + flagged  # a row for each heavy test and for each other test the reader flagged
        asked = {t[0] for t in need}
        light = len([t for t in tests if t[0] not in asked])
        if not need:
            if not tests:
                why = f"no test failed in all {scored} scored AI attempts."
            else:
                why = (f"no heavy test failed in all {scored} scored AI attempts ({light} lighter zero-pass test{'s' * (light != 1)} "
                       f"left out; heavy means {HEAVY_TEXT})")
            say("no proof required: " + why)
            if a.action == "check":
                print("PROOF: COMPLETE")
            return blame_hold() if bwhy else 0
        if a.action == "init":
            rule = f"heavy: {HEAVY_TEXT}, here a weight of {HEAVY_SHARE * total:.4g} or more"
            rc = proof_init(rev / PROOF_FILE, heavy, light, scored, rule, flagged, extend=kind == "EKW" or bool(tests and not no_blame), who=who or "the golden-answer reader")
            return blame_hold() if bwhy and rc == 0 else rc
        return proof_check(rev / PROOF_FILE, need, (pkg / "instruction.md").read_text(encoding="utf-8", errors="replace"))
    except ImportError as e:
        gone = "automation/task-read/task_read.py" if "task_read" in str(e) else "automation/release-check/build_export_from_zip.py"
        say(f"{gone} is missing. Run: python qc.py update, then try again.")
    except Exception as e:  # exit code 1 is kept for HOLD
        say(f"cannot run: {type(e).__name__}: {e}")
    return 2


# ---- the AI fix (qc.py fix) -----------------------------------------------------------------------------------------
# One claude call edits a COPY of the task (never TASK_DIR) so that the problems in FINDINGS.md go away. A checker then
# tests the copy against fixed rules (below). fix_diff.md lists every change in plain words; the QC person reads it, copies
# the changes they accept into the task by hand, and runs qc.py read on the changed task.

FIX_OWN = {"FIX_FINDINGS.md", "fix_log.md"}  # the two files the command writes at the top of the copy; ignored there and nowhere else
FIX_STRIP = {"claude.md", "claude.local.md", ".mcp.json", ".claude"}  # settings files claude would load from the copy; deleted from it (any folder, any letter case)
FIX_TOLERANCE = 1e-3  # a judge.toml's weights may move by this much in total
FIX_TIMEOUT = 2700
FIX_LIMIT = re.compile(
    r"usage limit|limit reached|hit your (\w+ )?limit|reached your (\w+ )?limit|weekly limit|rate[ _]limit|API Error: 429|too many requests|overloaded|credit balance|out of (extra )?usage|session limit|(message|spend) cap|payment required|resets? (at|in) ",
    re.I,
)
FIX_QUIET = 300  # a call that exits 0, writes no fix_log.md and prints fewer characters than this did not do the work
# judge_s2.toml, judge_s3.toml beside a judge.toml: byte copies of it (the mean-of-3 judge samples) that pipeline/tools/rewardkit_mean_of_3.py
# rewrites; judge.toml is the only file anyone edits. They are left out of the same-name check and refreshed from the fixed judge.toml.
FIX_SAMPLE = re.compile(r"judge_s\d+\.toml", re.I)
FIX_REPORT_LINE = re.compile(r"(NOT FLAGGED|FLAGGED) - report: (.+)")  # the last line qc.py read prints
FIX_PROMPT = """You are fixing one benchmark task package so that it no longer has the defects listed below. The package is in the current directory:

- instruction.md: the instruction an AI solver reads.
- environment/: the input files the solver gets.
- solution/: the reference answer (files and solve script).
- tests/: the grader. Each tests/deliverables_NN/judge.toml holds [[criterion]] entries, each with a "name", a "description" (the pass/fail rule) and a "weight". A tests/verifier.json holds "verifiers", each with a "name", a weight in "metadata" and an "assertion". Other files in tests/ (reward.toml, scripts) combine the scores. A judge_s2.toml or judge_s3.toml beside a judge.toml is a byte copy of it: edit judge.toml only, the command refreshes the copies after your fix. These files are the authoritative grader.
- FIX_FINDINGS.md: the defects a reviewer found in this package, with the criterion names, the quoted evidence and what is wrong.

Your job: make the smallest edits that remove each stated defect, so that an answer which follows the instruction correctly earns full credit, a wrong or empty answer does not, the requirements do not contradict each other, and every fact the solver needs is provided.

Allowed edits:
- Reword instruction.md (clarify, add a missing requirement the grader already checks, remove an ambiguity).
- Reword a criterion's description, or change its weight, in tests/ (keep the weights of each judge.toml summing to what they summed to before, within 0.001; do not change the group weights in reward.toml).
- Correct the reference answer in solution/ where it is wrong.
- Add a missing input file, or a missing fact to an existing input, when the defect is a missing input.

Not allowed:
- Deleting criteria or setting many weights to zero to make the problem disappear. At most one criterion may be removed, and only when it is a pure duplicate of another; say so in the log.
- Changing the task's topic, deliverables or the work it asks for.
- Changing a criterion or the reference answer so that a wrong answer passes.
- Editing FIX_FINDINGS.md.

When you edit instruction.md you may add WHAT must be delivered and in what form (a file, a sheet, a section, a unit). Do not write the expected conclusion, number or verdict that a grader checks into the instruction: that tells the solver the answer. If a grader checks a conclusion the instruction does not ask for, fix the grader (reword or loosen the criterion) or say so in fix_log.md.

If you judge a listed defect is not actually a defect, leave it alone and say why in the log. Do not make unrelated improvements.

When you are done, write fix_log.md in the current directory: one section per finding, with what you changed (file, criterion name, before and after in short), or "no change" and why. End with a line "FILES CHANGED: <comma separated relative paths>".

Keep every .toml and .json file in tests/ valid. Work only inside the current directory."""
FIX_RETRY = "\n\nYour first attempt was rejected by the checker for these reasons: {why}\nThe package has been reset to the original. Fix it again and keep to the rules above."


def fx_package(folder: Path) -> Path | None:
    """The package folder (instruction.md and tests/) for the folder a person names: that folder, its task_files folder, or its only child that is a package."""
    def ok(p: Path) -> bool:
        return (p / "instruction.md").is_file() and (p / "tests").is_dir()
    if ok(folder):
        return folder
    if ok(folder / "task_files"):
        return folder / "task_files"
    kids = [p for p in sorted(folder.iterdir()) if p.is_dir() and ok(p)] if folder.is_dir() else []
    return kids[0] if len(kids) == 1 else None


def fx_mode(p: Path) -> str:
    """The permission bits as text, off Windows (they mean little there); empty on Windows or when unreadable."""
    if os.name == "nt":
        return ""
    try:
        return ":" + format(stat.S_IMODE(p.lstat().st_mode), "o")
    except OSError:
        return ""


def fx_tree(d: Path, top_skip=(), leave_out=(), with_dirs=False) -> dict[str, str]:
    """relative path -> sha256 of every file under d. top_skip: file names left out at the top of d only. leave_out: folders (absolute) left out.
    with_dirs: also record every folder and link (and, off Windows, the permission bits), so an empty folder, a new link or a chmod is seen."""
    out = {}
    left = {os.path.normcase(str(x)) for x in leave_out}
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if os.path.normcase(str(Path(root) / x)) not in left]
        if with_dirs:
            for x in dirs:
                q = Path(root) / x
                out[q.relative_to(d).as_posix() + "/"] = ("link:" + os.readlink(q)) if q.is_symlink() else "dir" + fx_mode(q)
        for f in files:
            if f in top_skip and Path(root) == d:
                continue
            p = Path(root) / f
            if with_dirs and p.is_symlink():
                out[p.relative_to(d).as_posix()] = "link:" + os.readlink(p)
                continue
            h = hashlib.sha256()
            try:
                with open(p, "rb") as fh:
                    for b in iter(lambda: fh.read(1 << 20), b""):
                        h.update(b)
            except OSError:
                h.update(b"unreadable")
            out[p.relative_to(d).as_posix()] = h.hexdigest() + (fx_mode(p) if with_dirs else "")
    return out


def fx_weights(node, path=""):
    """Every value stored under a key named weight or weights (group weights), as {path: value}."""
    got = {}
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "criterion":
                continue
            if k in ("weight", "weights"):
                got[f"{path}/{k}"] = v
            else:
                got.update(fx_weights(v, f"{path}/{k}"))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            got.update(fx_weights(v, f"{path}[{i}]"))
    return got


def fx_is_sample(p: Path) -> bool:
    """A judge_s2.toml / judge_s3.toml beside a judge.toml: a copy of it, not a grader of its own."""
    return bool(FIX_SAMPLE.fullmatch(p.name)) and (p.parent / "judge.toml").is_file()


def fx_is_judge_copy(work: Path, rel: str) -> bool:
    """rel (relative to the package) is a sample copy that is, byte for byte, the judge.toml beside it in work."""
    p = work / rel
    j = p.parent / "judge.toml"
    try:
        return bool(FIX_SAMPLE.fullmatch(p.name)) and p.is_file() and j.is_file() and p.read_bytes() == j.read_bytes()
    except OSError:
        return False


def fx_copies(n: int) -> str:
    return f"{n} {'copy' if n == 1 else 'copies'} of judge.toml"


def fx_mirror_samples(orig: Path, work: Path) -> list[str]:
    """After the fixer ran: make each sample copy that was a byte copy of its judge.toml in the original a byte copy of the fixed judge.toml again
    (what pipeline/tools/rewardkit_mean_of_3.py does). A copy that already differed from its judge.toml in the original is left alone.
    Returns the paths, relative to the package, that it rewrote."""
    done = []
    tests = orig / "tests"
    for sp in sorted(tests.rglob("*.toml")) if tests.is_dir() else []:
        if not fx_is_sample(sp):
            continue
        rel = sp.relative_to(orig)
        try:
            if sp.read_bytes() != (sp.parent / "judge.toml").read_bytes():
                continue
            new_judge = work / rel.parent / "judge.toml"
            if not new_judge.is_file():
                continue
            want, dst = new_judge.read_bytes(), work / rel
            if not dst.is_file() or dst.read_bytes() != want:
                dst.write_bytes(want)
                done.append(rel.as_posix())
        except OSError:
            continue
    return done


def fx_criteria(pkg: Path):
    """(criteria, sums, groups, broken, dups) of the grader files in pkg/tests.
    criteria: id -> {w, text, file}; ids look like deliverables_01/name (a verifier.json test is its name).
    sums: grader file -> total of its criterion weights. groups: group weights in the .toml files. broken: grader files that do not parse.
    dups: criterion ids that occur twice (or have no name) in one grader file, which the checker cannot tell apart."""
    import tomllib

    crit, sums, groups, broken, dups = {}, {}, {}, [], []
    tests = pkg / "tests"
    for p in sorted(tests.rglob("*")) if tests.is_dir() else []:
        rel = p.relative_to(tests).as_posix()
        if "__pycache__" in rel:
            continue
        try:
            if p.suffix == ".toml":
                d = tomllib.loads(p.read_text(encoding="utf-8-sig"))
                groups[rel] = fx_weights(d)
                folder = p.parent.relative_to(tests).as_posix()
                copy = fx_is_sample(p)  # a sample copy of judge.toml: its weights are counted, its criteria are judge.toml's
                for c in d.get("criterion") or []:
                    if not isinstance(c, dict):
                        continue
                    cid = (folder + "/" if folder != "." else "") + str(c.get("name", ""))
                    w = c.get("weight")
                    w = float(w) if isinstance(w, (int, float)) and not isinstance(w, bool) else 1.0
                    sums[rel] = sums.get(rel, 0.0) + w
                    if copy:
                        continue
                    if cid in crit or not c.get("name"):
                        dups.append(cid or rel)
                    crit[cid] = {"w": w, "text": str(c.get("description") or c.get("prompt") or ""), "file": rel}
            elif p.name == "verifier.json":
                d = json.loads(p.read_text(encoding="utf-8-sig"))
                for v in d.get("verifiers") or []:
                    meta = v.get("metadata") or {}
                    w = meta.get("weight")
                    w = float(w) if isinstance(w, (int, float)) and not isinstance(w, bool) else 1.0
                    a = v.get("assertion")
                    rub = a.get("rubric") if isinstance(a, dict) else None
                    text = rub.get("prompt") if isinstance(rub, dict) and rub.get("prompt") else json.dumps(a, sort_keys=True, default=str)
                    if str(v.get("name")) in crit or not v.get("name"):
                        dups.append(str(v.get("name") or rel))
                    crit[str(v.get("name"))] = {"w": w, "text": str(text), "file": rel}
                    sums[rel] = sums.get(rel, 0.0) + w
        except Exception:
            broken.append(rel)
    return crit, sums, groups, broken, dups


def fx_check(orig: Path, work: Path, findings_text: str) -> tuple[list[str], dict]:
    """The checker. Returns (reasons the fix is rejected, facts for the diff). No reasons means accepted.
    Rules (the tested free-fix rules): fix_log.md exists; FIX_FINDINGS.md is untouched; every grader file still parses; the weights of each
    grader file keep their total (within 0.001); the group weights are unchanged; at most one criterion is removed.
    Settings files the command deletes from the copy (FIX_STRIP names) are left out of the comparison and listed in the diff."""
    reasons = []
    if not (work / "fix_log.md").is_file():
        reasons.append("fix_log.md missing")
    try:
        if (work / "FIX_FINDINGS.md").read_text(encoding="utf-8") != findings_text:
            reasons.append("FIX_FINDINGS.md was edited")
    except OSError:
        reasons.append("FIX_FINDINGS.md was deleted")
    ot, wt = fx_tree(orig, FIX_OWN), fx_tree(work, FIX_OWN)
    stripped = [k for k in ot if any(part.lower() in FIX_STRIP for part in k.split("/"))]
    for k in stripped:
        del ot[k]
    changed = sorted(k for k in set(ot) | set(wt) if ot.get(k) != wt.get(k))
    oc, osum, ogrp, obroken, _ = fx_criteria(orig)
    nc, nsum, ngrp, nbroken, _ = fx_criteria(work)
    for f in sorted(set(nbroken) - set(obroken)):
        reasons.append(f"tests/{f} is no longer valid")
    for f in sorted(set(osum) | set(nsum)):
        a, b = osum.get(f, 0.0), nsum.get(f, 0.0)
        if abs(a - b) > FIX_TOLERANCE:
            reasons.append(f"weight total of tests/{f} moved {a:g} -> {b:g}")
    if ogrp != ngrp:
        reasons.append("group weights in a tests/ .toml file changed: " + ", ".join(sorted(f for f in set(ogrp) | set(ngrp) if ogrp.get(f) != ngrp.get(f))[:4]))
    removed = [i for i in oc if i not in nc]
    if len(removed) > 1:
        reasons.append(f"{len(removed)} criteria removed, the rule is at most one")
    facts = {
        "stripped": sorted(stripped), "changed": changed, "added": [k for k in changed if k not in ot], "removed_files": [k for k in changed if k not in wt],
        "oc": oc, "nc": nc, "osum": osum, "nsum": nsum, "removed": removed,
        "zeroed": [i for i in oc if i in nc and nc[i]["w"] == 0 and oc[i]["w"] != 0],
        "looser": fx_looser(oc, nc),
    }
    return reasons, facts


FIX_LOOSER_SHORTER = 0.8  # new text at most this share of the old length counts as shorter by 20 percent or more
FIX_REQ_WORDS = re.compile(r"\b(must|require[sd]?|need(?:s|ed)?|at least|all of|every|each|both|only|exactly|state[sd]?|name[sd]?|cite[sd]?|include[sd]?|show[sd]?|explicit(?:ly)?)\b", re.I)
FIX_BROADEN = re.compile(r"\baccept|\babout\b|\bapproximately\b|\broughly\b|\baround\b|\boptional|\bmay\b|\bneed not\b|\bnot required\b|\beither\b|\brange\b|\bbetween\b|\bwithin\b|\bany (?:one|two|three|of|reasonable|defensible|well)|\btoleran|\bmargin\b|\bplus or minus\b|\u00b1", re.I)
FIX_QUOTED = re.compile(r'"([^"\n]{3,80})"|\u201c([^\u201d\n]{3,80})\u201d|`([^`\n]{2,80})`')


def fx_det(text: str):
    """The parsed deterministic check ({"type": "deterministic", "expected": n, "deterministic": {"comparison": ...}}) or None."""
    try:
        d = json.loads(text)
    except Exception:
        return None
    if isinstance(d, dict) and d.get("type") == "deterministic" and isinstance(d.get("deterministic"), dict):
        return d
    return None


def fx_words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9.%]*", t.lower()) if len(w) > 3 or any(c.isdigit() for c in w)}


def fx_looser(oc: dict, nc: dict) -> list[dict]:
    """Criteria the fix made looser, by fixed rules (no model). oc and nc are fx_criteria-style dicts: id -> {w, text}.
    A criterion is listed when its weight went down, its text got 20 percent or more shorter, a quoted phrase or a sentence that
    states a requirement was dropped from the text, a deterministic floor went down (or a ceiling went up), or it was removed.
    Returns [{id, old_w, new_w, why}] in id order; why is one plain line."""
    out = []
    for i in sorted(oc):
        o, n = oc[i], nc.get(i)
        if n is None:
            out.append({"id": i, "old_w": o["w"], "new_w": 0.0, "why": "criterion removed"})
            continue
        why = []
        if n["w"] < o["w"] - 1e-9:
            why.append(f"weight went down {o['w']:g} -> {n['w']:g}")
        od, nd = fx_det(o["text"]), fx_det(n["text"])
        if od and nd:
            try:
                eo, en = float(od["expected"]), float(nd["expected"])
                cmp_ = od["deterministic"].get("comparison", "")
                if cmp_ in ("greater_than_equal", "greater_than") and en < eo:
                    why.append(f"floor lowered {eo:g} -> {en:g}")
                elif cmp_ in ("less_than_equal", "less_than") and en > eo:
                    why.append(f"ceiling raised {eo:g} -> {en:g}")
            except (TypeError, ValueError, KeyError):
                pass
        elif o["text"] != n["text"] and not od:
            a, b = re.sub(r"\s+", " ", o["text"]).strip(), re.sub(r"\s+", " ", n["text"]).strip()
            if a and len(b) <= FIX_LOOSER_SHORTER * len(a):
                why.append(f"text {100 * (1 - len(b) / len(a)):.0f} percent shorter")
            bl = b.lower()
            gone = [next(g for g in m.groups() if g) for m in FIX_QUOTED.finditer(a) if next(g for g in m.groups() if g).lower() not in bl]
            if gone:
                why.append(f'required phrase "{fx_short(gone[0], 50)}" removed')
            added = len(FIX_BROADEN.findall(b)) - len(FIX_BROADEN.findall(a))
            if added > 0:
                why.append(f"wording now accepts more ({added} more of: accept, about, optional, either, range, any of)")
            bw = fx_words(b)
            for s in fx_sentences(a):
                sw = fx_words(s)
                if FIX_REQ_WORDS.search(s) and len(sw) >= 4 and len(sw & bw) / len(sw) < 0.5:
                    why.append(f'requirement dropped: "{fx_short(s, 70)}"')
                    break
        if why:
            out.append({"id": i, "old_w": o["w"], "new_w": n["w"], "why": "; ".join(why)})
    return out


def fx_short(text, limit: int = 600) -> str:
    one = re.sub(r"\s+", " ", str(text)).strip()
    return one[: limit - 3] + "..." if len(one) > limit else one


def fx_window(old: str, new: str, ctx: int = 150, limit: int = 600) -> tuple[str, str, bool]:
    """(old, new, cut) for display. A long text is cut to the part around the change, so the change is not hidden past the limit."""
    if max(len(old), len(new)) <= limit:
        return fx_short(old, limit), fx_short(new, limit), False
    m = min(len(old), len(new))
    p = 0
    while p < m and old[p] == new[p]:
        p += 1
    q = 0
    while q < m - p and old[-1 - q] == new[-1 - q]:
        q += 1

    def cut(t: str) -> str:
        lo, hi = max(0, p - ctx), min(len(t), len(t) - q + ctx)
        return ("..." if lo else "") + t[lo:hi] + ("..." if hi < len(t) else "")

    return fx_short(cut(old), 3 * limit), fx_short(cut(new), 3 * limit), True


def fx_read(p: Path) -> str | None:
    try:
        if p.stat().st_size > 400_000:
            return None
        return p.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def fx_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


FIX_NUM = re.compile(r"[$]\s?\d[\d,]*(?:\.\d+)?|\d+(?:\.\d+)?\s?(?:%|percent\b|per cent\b)|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d{3,}")
FIX_PHRASE = re.compile(r"\"([^\"\n]{3,}?)\"|\u201c([^\u201d\n]{3,}?)\u201d|\b[A-Z][\w&'-]*(?:\s+[A-Z][\w&'-]*)+")


def fx_grader_text(*pkgs: Path) -> str:
    """All text of the grader (tests/) and the reference answer (solution/ or golden/) of each package, one string."""
    parts = []
    for pkg in pkgs:
        for top in ("tests", "solution", "golden"):
            for root, _dirs, files in os.walk(pkg / top):
                for f in sorted(files):
                    t = fx_read(Path(root) / f)
                    if t:
                        parts.append(t)
    return "\n".join(parts)


def fx_fold(t: str) -> str:
    """Text made comparable: curly quotes straight, thousands commas and the word percent normalised, lower case, white space collapsed."""
    t = t.replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    t = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", t)
    t = re.sub(r"\s*(?:percent|per cent)\b", "%", t, flags=re.I)
    return re.sub(r"\s+", " ", t).lower()


FIX_SHARED_RUN = 6  # words in a row that a new instruction sentence shares with the grader text before it is shown as shared wording (0 = off)
FIX_WORD = re.compile(r"[a-z0-9$%](?:[a-z0-9$%'-]|\.(?=[a-z0-9$%]))*")


def fx_shared(sentence: str, old_instruction: str, grader_text: str) -> str:
    """The first run of FIX_SHARED_RUN words in a row that a new instruction sentence shares with the grader or reference answer text and
    the old instruction did not have ('' if none). It finds wording the number and phrase rule cannot, such as a plain-words conclusion."""
    if not FIX_SHARED_RUN:
        return ""
    w = FIX_WORD.findall(fx_fold(sentence))
    g, o = " ".join(FIX_WORD.findall(fx_fold(grader_text))), " ".join(FIX_WORD.findall(fx_fold(old_instruction)))
    for i in range(len(w) - FIX_SHARED_RUN + 1):
        run = " ".join(w[i : i + FIX_SHARED_RUN])
        if run in g and run not in o:
            return run
    return ""


def fx_leaks(sentence: str, old_instruction: str, grader_text: str) -> list[str]:
    """Items in a new instruction sentence that look like a grader's answer: a number (3+ digits, or a decimal, percent or dollar amount)
    or a quoted or capitalised multi-word phrase that is in the grader or reference answer text and not in the old instruction.
    Compared after fx_fold, so 1,234 matches 1234, 12 percent matches 12% and a curly quote matches a straight one."""
    g, o = fx_fold(grader_text), fx_fold(old_instruction)
    got = []
    for m in FIX_NUM.finditer(sentence):
        item = m.group(0).strip()
        digits = re.escape(fx_fold(item))
        if re.search(rf"(?<![\d.]){digits}(?![\d])", g) and not re.search(rf"(?<![\d.]){digits}(?![\d])", o):
            got.append(item)
    sentence = sentence.replace("\u2018", "'").replace("\u2019", "'")  # FIX_PHRASE reads straight apostrophes
    for m in FIX_PHRASE.finditer(sentence):
        if m.group(1) or m.group(2):
            runs = [(m.group(1) or m.group(2)).strip().split()]
        else:  # a capitalised run: also try it without its first or last words (the first word may only start the sentence)
            w = m.group(0).split()
            runs = [w[i:j] for n in range(len(w), 1, -1) for i in range(len(w) - n + 1) for j in [i + n]]
        for r in runs:
            item = " ".join(r)
            fi = fx_fold(item)
            if len(r) >= 2 and fi in g and fi not in o:
                got.append(f'"{item}"')
                break
    return list(dict.fromkeys(got))


def fx_diff_text(orig: Path, work: Path, facts: dict, reasons: list[str], name: str) -> str:
    """fix_diff.md: what changed, file by file, in plain words."""
    import difflib

    changed = facts["changed"]
    copies = [f for f in changed if fx_is_judge_copy(work, f)]
    plus = f" (plus {fx_copies(len(copies))})" if copies else ""
    L = [f"# Changes the AI fix made to {name}", ""]
    if reasons:
        L += ["**The checker REJECTED this fix.** Reasons: " + "; ".join(reasons), "Read it only to see what the fixer tried. Do not copy it in.", ""]
    L += [
        f"Files changed: {len(changed) - len(copies)}{plus}. Your task folder was not touched. The fixed copy is the folder `fixed` next to this file.",
        "Read each change below, copy the ones you accept into the task by hand, then run `python qc.py read` on the changed task to re-check it.",
        "",
    ]
    if facts.get("stripped"):
        L += ["Settings files removed from the copy before the AI ran (they are not changes the AI made): " + ", ".join(facts["stripped"]), ""]
    if not changed:
        L += ["The fixer changed no file. Read fix_log.md for why.", ""]
    leaks = 0
    leak_at = len(L)
    for f in changed:
        op, wp = orig / f, work / f
        if f in copies:
            L += [f"## {f} (copy of judge.toml)", "", "A byte copy of the fixed judge.toml in the same folder (the mean-of-3 judge samples), refreshed by the command. Read the change in judge.toml; there is nothing else to read here.", ""]
            continue
        kind = "added" if f in facts["added"] else "removed" if f in facts["removed_files"] else "changed"
        L += [f"## {f} ({kind})", ""]
        if kind == "added":
            t = fx_read(wp)
            L += [f"New file, {wp.stat().st_size} bytes." + (" First lines: " + fx_short(t, 300) if t else " Not a text file."), ""]
            continue
        if kind == "removed":
            L += ["The fixer deleted this file.", ""]
            continue
        a, b = fx_read(op), fx_read(wp)
        if a is None or b is None:
            L += [f"Not a text file or too large to show: {op.stat().st_size} bytes before, {wp.stat().st_size} bytes after.", ""]
            continue
        if f == "instruction.md":
            sa, sb = fx_sentences(a), fx_sentences(b)
            gtext = fx_grader_text(orig, work)
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, sa, sb, autojunk=False).get_opcodes():
                if tag == "equal":
                    continue
                o, n, cut = fx_window(" ".join(sa[i1:i2]), " ".join(sb[j1:j2]))
                if sa[i1:i2]:
                    L.append(f"- Old sentence: {o}" + (" (long: only the part around the change is shown)" if cut else ""))
                if sb[j1:j2]:
                    L.append(f"- New sentence: {n}" + (" (long: only the part around the change is shown)" if cut else ""))
                    hit = fx_leaks(" ".join(sb[j1:j2]), a, gtext)
                    shared = fx_shared(" ".join(sb[j1:j2]), a, gtext)
                    if hit or shared:
                        leaks += 1
                    if hit:
                        L.append(f"  - POSSIBLE ANSWER LEAK: {', '.join(hit)}")
                    if shared:
                        L.append(f'  - SHARED WORDING WITH A GRADER: "{shared}" (the new sentence repeats {FIX_SHARED_RUN} words in a row from the grader or the reference answer)')
            L.append("")
            continue
        oc, nc = facts["oc"], facts["nc"]
        mine = [i for i in sorted(set(oc) | set(nc)) if "tests/" + (oc.get(i) or nc.get(i))["file"] == f]
        shown = False
        for i in mine:
            o, n = oc.get(i), nc.get(i)
            if o and n:
                if o["text"] != n["text"]:
                    ot, nt, cut = fx_window(o["text"], n["text"])
                    L += [f"- Criterion {i}: text changed." + (" (long text: only the part around the change is shown)" if cut else ""), f"  - Old text: {ot}", f"  - New text: {nt}"]
                    shown = True
                if abs(o["w"] - n["w"]) > 1e-9:
                    L.append(f"- Criterion {i}: weight {o['w']:g} -> {n['w']:g}.")
                    shown = True
            elif o:
                L += [f"- Criterion {i}: REMOVED (weight {o['w']:g}).", f"  - Old text: {fx_short(o['text'])}"]
                shown = True
            else:
                L += [f"- Criterion {i}: ADDED (weight {n['w']:g}).", f"  - New text: {fx_short(n['text'])}"]
                shown = True
        if not shown:
            lines = [x for x in difflib.unified_diff(a.splitlines(), b.splitlines(), "before", "after", n=0, lineterm="") if not x.startswith(("---", "+++", "@@"))]
            L += [f"- {fx_short(x, 300)}" for x in lines[:40]]
            if len(lines) > 40:
                L.append(f"- ... {len(lines) - 40} more changed lines")
        L.append("")
    loose = facts.get("looser", [])
    top = [f"## Made looser (read these first)", ""]
    if loose:
        top += [f"{len(loose)} criteri{'a' if len(loose) != 1 else 'on'} may accept work the old version rejected. Some of these are the point of the fix (the old criterion asked for more than the instruction). Check each one against the instruction.", ""]
        top += [f"- {x['id']}: weight {x['old_w']:g} -> {x['new_w']:g}. {x['why']}." for x in loose] + [""]
    else:
        top += ["No criterion was found easier by the fixed rules (weight down, text 20 percent or more shorter, quoted phrase or requirement dropped, lower floor, removed). This does not prove none is easier: read the criterion changes below.", ""]
    L[leak_at:leak_at] = top
    leak_at += len(top)
    L[leak_at:leak_at] = [f"Possible answer leaks flagged: {leaks}" + (" (read each POSSIBLE ANSWER LEAK and SHARED WORDING line below: the new sentence may tell the solver what a grader checks)" if leaks else ""), ""]
    sums = [(f, facts["osum"].get(f, 0.0), facts["nsum"].get(f, 0.0)) for f in sorted(set(facts["osum"]) | set(facts["nsum"]))]
    moved = [s for s in sums if abs(s[1] - s[2]) > 1e-9]
    L += ["## Weights", ""]
    L.append("Weight total of each grader file: unchanged." if not moved else "Weight total moved in: " + "; ".join(f"tests/{f} {a:g} -> {b:g}" for f, a, b in moved) + ".")
    L.append(f"Criteria removed: {len(facts['removed'])}. Criteria whose weight went to zero: {len(facts['zeroed'])}." + (" Check that these are not hiding a problem." if facts["zeroed"] else ""))
    return "\n".join(L) + "\n"


def fx_claude() -> str | None:
    return shutil.which("claude")


def fx_ask(cwd: Path, prompt: str) -> tuple[int, str]:
    """One claude call with cwd = the copy. Returns (exit code, everything it printed). Tests replace this function."""
    # --tools gives exactly these five tools (no shell) and, unlike --allowedTools, does not grant them on every path: edits stay inside cwd.
    # --setting-sources user keeps hooks and settings of the package out. The long prompt goes on stdin (a short argument list is safe for a Windows .cmd shim).
    cmd = [fx_claude() or "claude", "-p", "--model", "sonnet", "--tools", "Read,Glob,Grep,Write,Edit", "--setting-sources", "user", "--permission-mode", "acceptEdits"]
    r = subprocess.run(cmd, cwd=str(cwd), input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=FIX_TIMEOUT)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def fx_links(pkg: Path) -> list[str]:
    """Symbolic links (file or folder) anywhere in pkg, as relative paths."""
    got = [] if not pkg.is_symlink() else ["."]
    for root, dirs, files in os.walk(pkg):
        for n in dirs + files:
            if (Path(root) / n).is_symlink():
                got.append((Path(root) / n).relative_to(pkg).as_posix())
    return got


def fx_strip(work: Path) -> list[str]:
    """Delete settings files claude would load from the copy (any folder). Returns what was deleted, relative to work."""
    gone = []
    for root, dirs, files in os.walk(work, topdown=True):
        for n in list(dirs):
            if n.lower() in FIX_STRIP:
                gone.append((Path(root) / n).relative_to(work).as_posix() + "/")
                shutil.rmtree(Path(root) / n)
                dirs.remove(n)
        for n in files:
            if n.lower() in FIX_STRIP:
                gone.append((Path(root) / n).relative_to(work).as_posix())
                (Path(root) / n).unlink()
    return sorted(gone)


def fx_read_findings_raw(path: Path) -> tuple[str | None, str]:
    """(text, why not). Handles a UTF-8 or UTF-16 byte order mark (PowerShell > writes UTF-16); other text with NUL bytes is refused."""
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16"), ""
        except UnicodeDecodeError:
            return None, f"{path.name} looks like UTF-16 text but cannot be read; save it as UTF-8 and run again"
    if b"\x00" in raw:
        return None, f"{path.name} holds NUL bytes (UTF-16 without a byte order mark?); save it as UTF-8 and run again"
    try:
        return raw.decode("utf-8-sig"), ""
    except UnicodeDecodeError:  # PowerShell 5 Set-Content and Notepad write the ANSI code page
        return raw.decode("cp1252", errors="replace"), ""


def fx_read_findings(path: Path) -> tuple[str | None, str]:
    """The findings text with LF line endings (a file written on Windows has CRLF; the copy of it is written back in text mode and compared)."""
    text, why = fx_read_findings_raw(path)
    if text is not None:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text, why


def fx_follow_report(text: str, findings: Path) -> tuple[str | None, str]:
    """When the findings file holds only the printed result of qc.py read (a '[qc] running: ...' line and 'FLAGGED - report: <path>'), the problems
    are in the report that line names: return that report's text. Any other findings text comes back unchanged. Returns (text, why not)."""
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    found = [FIX_REPORT_LINE.fullmatch(x) for x in lines]
    # a qc.py read --times N run prints a few [qc] lines per read and then one plain result line: the last result line counts
    if not lines or len(lines) > 30 or not any(found) or any(m is None and not x.startswith("[qc]") for m, x in zip(found, lines)):
        return text, ""
    m = [m for m in found if m][-1]
    if m.group(1) == "NOT FLAGGED":
        return None, f"{findings.name} holds a qc.py read result that says NOT FLAGGED, so there is no problem to fix. Pass the DataOS review table (problems.md) or a read report that says FLAGGED"
    named = Path(m.group(2).strip())
    if named.suffix.lower() != ".md":
        return None, f"{findings.name} names {named}, which is not a .md report; pass the report file itself (task_read_report.md)"
    for cand in (named, findings.parent / named.name):
        if cand.is_file():
            report, why = fx_read_findings(cand)
            if report is None:
                return None, why
            if not report.strip():
                return None, f"the report {cand} is empty"
            say(f"{findings.name} holds the printed result of qc.py read; using the report it names: {cand}")
            return report, ""
    return None, f"{findings.name} holds the printed result of qc.py read, and the report it names is not at {named}. Pass the report file itself (task_read_report.md, written next to the read output)"


def fx_changed_names(a: dict[str, str], b: dict[str, str]) -> str:
    names = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    return ", ".join(names[:5]) + (f" and {len(names) - 5} more" if len(names) > 5 else "")


def fx_stop(why: str) -> int:
    say(why)
    print(f"FIX: NOT RUN ({why})", flush=True)
    return 2


def cmd_fix(a) -> int:
    """fix TASK_DIR FINDINGS.md. Exit 0 accepted by the checker, 1 rejected, 2 could not run (also a usage limit: that is not a rejection)."""
    folder, findings = Path(a.task_dir).resolve(), Path(a.findings).resolve()
    pkg = fx_package(folder) if folder.is_dir() else None
    if pkg is None:
        return fx_stop(f"no task package found in {folder}: it needs an instruction.md and a tests folder")
    if not findings.is_file():
        return fx_stop(f"findings file not found: {findings}")
    text, bad = fx_read_findings(findings)
    if text is None:
        return fx_stop(bad)
    if not text.strip():
        return fx_stop(f"{findings.name} is empty; paste in the problems the review table or qc.py read listed")
    text, bad = fx_follow_report(text, findings)
    if text is None:
        return fx_stop(bad)
    name = re.sub(r"[^\w.-]+", "_", pkg.name if pkg.name != "task_files" else pkg.parent.name)
    base = findings.parent
    if base == pkg or pkg in base.parents:  # findings kept inside the task folder: write beside the task instead
        base = pkg.parent
    out = Path(a.out).resolve() if a.out else base / f"fix_{name}"
    if out == pkg or pkg in out.parents:
        return fx_stop("the output folder is inside the task folder; pass --out with a folder elsewhere")
    fixed = out / "fixed"
    if fixed == pkg or fixed == folder or fixed in pkg.parents or pkg in fixed.parents:
        return fx_stop("the output folder would overwrite the task folder (a rerun into the fixed copy of an earlier run does this); pass --out with another folder")
    links = fx_links(pkg)
    if links:
        return fx_stop(f"the task folder holds a symbolic link ({', '.join(links[:3])}); the AI fix does not run on those. Replace the link with a real copy of the file and run again")
    _, _, _, obroken, odups = fx_criteria(pkg)
    if obroken:
        return fx_stop("a grader file in the task does not parse before any fix: " + ", ".join("tests/" + f for f in obroken[:4]) + ". Repair it by hand first")
    if odups:
        return fx_stop("a grader file has two criteria with the same name (or one with no name): " + ", ".join(odups[:4]) + ". The checker cannot tell them apart; give each criterion its own name first")
    head = f"# Problems found in this task\n\nThe fix is asked to remove each of these. The reviewer's text follows unchanged.\n\n"
    findings_text = head + text
    before, before_findings = fx_tree(folder, leave_out=[out], with_dirs=True), hashlib.sha256(findings.read_bytes()).hexdigest()
    reasons: list[str] = []
    if a.no_ask:
        if not (fixed / "fix_log.md").is_file() or not (fixed / "FIX_FINDINGS.md").is_file():
            return fx_stop(f"nothing saved to reuse in {fixed}; run without --no-ask first")
        findings_text = (fixed / "FIX_FINDINGS.md").read_text(encoding="utf-8")
        say(f"--no-ask: reusing the saved fix in {fixed} (no AI call).")
        reasons, facts = fx_check(pkg, fixed, findings_text)
    else:
        if fx_claude() is None:
            return fx_stop("the claude command was not found; install Claude Code and sign in (the Once section of the QC person run sheet)")
        if fixed.exists():
            if not (fixed / "FIX_FINDINGS.md").is_file():
                return fx_stop(f"{fixed} exists and was not made by qc.py fix; pass --out with another folder")
            shutil.rmtree(fixed)
        out.mkdir(parents=True, exist_ok=True)
        prompt = FIX_PROMPT
        for attempt in (1, 2):
            try:
                shutil.copytree(pkg, fixed, symlinks=True)
            except (OSError, shutil.Error) as e:
                shutil.rmtree(fixed, ignore_errors=True)
                return fx_stop(f"could not copy the task to {fixed} ({str(e)[:160]}). On Windows a path over 260 characters fails: pass --out with a short folder such as C:/fx")
            for n in FIX_OWN:
                (fixed / n).unlink(missing_ok=True)
            fx_strip(fixed)
            (fixed / "FIX_FINDINGS.md").write_text(findings_text, encoding="utf-8")
            say(f"attempt {attempt} of 2: the AI fix works on a copy in {fixed} (one AI call)...")
            try:
                rc, reply = fx_ask(fixed, prompt)
            except subprocess.TimeoutExpired:
                return fx_stop(f"the AI call ran longer than {FIX_TIMEOUT // 60} minutes and was stopped; nothing was judged")
            except OSError as e:
                return fx_stop(f"the claude command could not start ({e})")
            after = fx_tree(folder, leave_out=[out], with_dirs=True)
            if after != before:
                return fx_stop(f"the task folder {folder} changed while the fixer ran ({fx_changed_names(before, after)}); compare it with your copy before you go on")
            if hashlib.sha256(findings.read_bytes()).hexdigest() != before_findings:
                return fx_stop(f"the findings file {findings} changed while the fixer ran; compare it with your copy before you go on")
            logged = (fixed / "fix_log.md").is_file()
            if FIX_LIMIT.search(reply) and (rc != 0 or (not logged and len(reply.strip()) < FIX_QUIET)):
                return fx_stop("the AI usage limit was reached, so no fix was made. This is not a rejected fix: try again when the limit resets. " + safe(reply, 160))
            if rc != 0:
                return fx_stop(f"the claude command failed (exit {rc}) and the copy in {fixed} may be half edited, so nothing was judged. This is not a rejected fix: run again. {safe(reply, 160)}")
            if not logged and len(reply.strip()) < FIX_QUIET:
                return fx_stop(f"the claude command ended without a fix_log.md and printed almost nothing ({safe(reply, 120)}), so no fix was made. This is not a rejected fix: run again")
            fx_mirror_samples(pkg, fixed)
            reasons, facts = fx_check(pkg, fixed, findings_text)
            if not reasons:
                break
            say("the checker rejected the fix: " + "; ".join(reasons))
            if attempt == 1:
                kept = out / "rejected_try1"
                if kept.exists():
                    shutil.rmtree(kept)
                shutil.move(str(fixed), str(kept))
                say(f"first try kept for reading in {kept}; trying once more.")
                prompt = FIX_PROMPT + FIX_RETRY.format(why="; ".join(reasons))
    if not reasons and (out / "rejected_try1").exists():
        shutil.rmtree(out / "rejected_try1")
    name_shown = pkg.name if pkg.name != "task_files" else pkg.parent.name
    (out / "fix_diff.md").write_text(fx_diff_text(pkg, fixed, facts, reasons, name_shown), encoding="utf-8")
    log = fixed / "fix_log.md"
    (out / "fix_log.md").write_text(log.read_text(encoding="utf-8", errors="replace") if log.is_file() else "The fixer wrote no fix_log.md.\n", encoding="utf-8")
    copies = [f for f in facts["changed"] if fx_is_judge_copy(fixed, f)]
    n = len(facts["changed"]) - len(copies)
    say(f"read {out / 'fix_diff.md'} and {out / 'fix_log.md'}. Copy the changes you accept into the task by hand, then run: python qc.py read on the changed task.")
    if reasons:
        print(f"FIX: REJECTED ({'; '.join(reasons)[:300]})", flush=True)
        return 1
    if n == 0:
        print("FIX: NO CHANGE MADE (the fixer changed no file; read fix_log.md for why)", flush=True)
        return 0
    print(f"FIX: ACCEPTED BY CHECKER ({n} file{'s' * (n != 1)} changed" + (f"; {fx_copies(len(copies))} refreshed" if copies else "") + f"; {len(facts['looser'])} criteri{'a' if len(facts['looser']) != 1 else 'on'} made looser)", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--no-update", action="store_true", help="skip the git pull")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("update")
    c = sub.add_parser("checks")
    c.add_argument("root")
    c.add_argument("stage", nargs="?")
    c.add_argument("out", nargs="?")
    r = sub.add_parser("review")
    r.add_argument("task_dir")
    r.add_argument("problems")
    r.add_argument("--work")
    fx = sub.add_parser("fix")
    fx.add_argument("task_dir", help="the task package folder (instruction.md and tests/); the command works in a copy and stops if it sees a file in it change")
    fx.add_argument("findings", help="FINDINGS.md: the DataOS review table (problems.md), or the printed result of qc.py read (the command then opens the report that result names)")
    fx.add_argument("--out", default=None, help="where to write fixed/, fix_diff.md and fix_log.md (default: fix_<task name> next to FINDINGS.md)")
    fx.add_argument("--no-ask", action="store_true", help="make no AI call: re-check and re-write the diff from the fix saved in OUT")
    rd = sub.add_parser("read")
    rd.add_argument("task_folder")
    rd.add_argument("--out", default=None)
    rd.add_argument(
        "--tab",
        choices=["EKW", "SVC", "ekw", "svc"],
        default=None,
        help="task kind; give it when the read says it cannot tell",
    )
    rd.add_argument(
        "--times",
        type=int,
        default=1,
        help="read the task this many times, 1 to 5; any flag counts and the command stops at the first flag. 3 is recommended before a task goes into a batch: "
        "in the batch 14 run 26 of 146 approved tasks that were clean on the first read were flagged on a repeat read",
    )
    sb = sub.add_parser("siblings")
    sb.add_argument("task_dir")
    sb.add_argument("problems")
    sb.add_argument("--no-ask", action="store_true", help="make no AI call: use the saved answers (siblings_reader.json beside problems.md) only")
    sb.add_argument("--check", action="store_true", help="make no AI call: say SIBLINGS: COMPLETE when every suggested test has a yes or no and a note in siblings_answers.csv, else SIBLINGS: HOLD (n open) and exit 1")
    mg = sub.add_parser("manage")
    mg.add_argument("inputs", nargs="+", help="Dataset with runs zip files, or folders holding them extracted")
    mg.add_argument("--out", default="qc_manage_out")
    mg.add_argument("--tab", choices=["EKW", "SVC", "ekw", "svc"], default=None, help="task kind, if every task is the same kind")
    mg.add_argument("--blame", action="store_true", help=BLAME_HELP)
    mg.add_argument("--no-blame", action="store_true", help=NO_BLAME_HELP)
    mg.add_argument("--blame-max", type=int, default=BLAME_MAX, help="most zero-pass tests the blame reader asks about per task (default %(default)s)")
    mg.add_argument("--replay-flags", default=None, metavar="FLAGS.CSV", help="look_first column; " + LOOK_FILE_HELP)
    lk = sub.add_parser("look-first")
    lk.add_argument("task_folder", help="the rev_<n>__<task id> folder of a Dataset with runs download")
    lk.add_argument("--replay-flags", default=None, metavar="FLAGS.CSV", help=LOOK_FILE_HELP)
    tr = sub.add_parser("tfrl-read")
    tr.add_argument("task_folder", help="the rev_<n>__<task id> folder of a Dataset with runs download")
    tr.add_argument("--again", action="store_true", help="ask again even when tfrl_replay.json already holds an answer for this instruction.md")
    lk.add_argument("--tab", choices=["EKW", "SVC", "ekw", "svc"], default=None, help="task kind; only needed when the task files do not say it")
    lk.add_argument("--blame-max", type=int, default=BLAME_MAX, help="most zero-pass tests counted per task (default %(default)s); keep the value proof init used")
    pf = sub.add_parser("proof")
    pf.add_argument("action", choices=["init", "check"])
    pf.add_argument("task_folder", help="the rev_<n>__<task id> folder of a Dataset with runs download")
    pf.add_argument("--tab", choices=["EKW", "SVC", "ekw", "svc"], default=None, help="task kind; only needed when the task files do not say it")
    pf.add_argument("--blame", action="store_true", help=argparse.SUPPRESS)  # old name, does nothing new: the reader is on by default
    pf.add_argument("--no-blame", action="store_true", help=NO_BLAME_HELP)
    pf.add_argument("--blame-max", type=int, default=BLAME_MAX, help="most zero-pass tests the blame reader asks about per task (default %(default)s)")
    z = sub.add_parser("release")
    z.add_argument("zips", nargs="+")
    z.add_argument("--out", default="qc_release_out")
    for sp in sub.choices.values():  # also accept --no-update after the command word
        sp.add_argument("--no-update", action="store_true", default=argparse.SUPPRESS, help="skip the git pull (same as before the command word)")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    if a.cmd == "update":
        return 0 if update() else 1
    if not a.no_update:
        update()
    return {
        "checks": cmd_checks,
        "review": cmd_review,
        "fix": cmd_fix,
        "siblings": cmd_siblings,
        "release": cmd_release,
        "read": cmd_read,
        "manage": cmd_manage,
        "look-first": cmd_look,
        "tfrl-read": cmd_tfrl_read,
        "proof": proof_main,
    }[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
