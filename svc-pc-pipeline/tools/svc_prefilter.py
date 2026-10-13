#!/usr/bin/env python3
"""Deterministic pre-filter for an SVC-PC task package, run BEFORE building an upload zip (v7 change #7).

What it catches deterministically (no LLM, no judgment): the defect classes that do NOT need the severity
wall to detect, so we never spend a DataOS grade on a task a script could have failed first. The checks are
tuned for NEAR-ZERO false positives on real SVC-PC tasks - a pre-filter that cries wolf on every rubric gets
ignored. Notably it does NOT flag a rubric for quoting the instruction's own question (that is correct
authoring, not a leak): confirmed on 16-1-0 where judge.toml says "Expected: instruction.md asks '...'".

  1.6 answer-key leak (HARD): grader artifacts reachable by the solver. judge.toml/reward.toml/solution ARE
      the answer key and MAY hold expected values. A solver-visible file (instruction.md, tests/task_prompt.txt,
      environment/initial_workspace/**) may NOT. Flags: leak strings (golden_output, answer key, judge.toml,
      expected reward) in a solver file; a solution/ deliverable whose bytes are duplicated into
      initial_workspace (the answer copied into the workspace).
  1.6 expected-value tuple (WARN): a distinctive multi-number tuple (>=3 numbers, e.g. "6, 9, 12, 15") that
      appears in BOTH a judge.toml Expected: clause AND a solver-visible file. Warn not hard - a tuple can
      coincide - but it is where a real numeric-answer leak shows up, so a human confirms.
  1.8 packaging (HARD/WARN): >15 criteria in any judge dir (grammar bomb, HARD); a files= path absent from the
      package (HARD); lease.json (HARD); mojibake in names/text, CRLF, and build junk (_scratch_*, *.preedit,
      *.orig, *.bak, tamper scripts) as WARN - the zip builder must exclude the junk.
  files= integrity (HARD): every path in every judge group's files= resolves to a real file in the package.

Usage:
  python tools/svc_prefilter.py <package_root> [<package_root> ...]
where package_root is a task dir with tests/, environment/, solution/ (e.g. .../03_dataos_ready/SVC-PC-16-1-0).
Exit 0 if all clean/warn-only, 1 if any task has a HARD defect."""

import os, re, sys, glob, hashlib

MAX_CRIT = 15
LEAK_STRINGS = [
    "answer key",
    "golden_output",
    "golden output",
    "/solution/",
    "reward.toml",
    "expected reward",
    "the correct answer is",
    "judge.toml",
]
MOJI = [
    "Ã©",
    "Ã¨",
    "Ã¡",
    "Ã­",
    "Ã³",
    "Ãº",
    "Ã±",
    "Ã¼",
    "Ã¶",
    "Ã¤",
    "â€™",
    "â€œ",
    "â€“",
    "â€”",
    "â€¦",
    "ï»¿",
    "Â·",
]
TEXT_EXT = (".md", ".txt", ".csv", ".toml", ".json", ".py", ".sh", ".html", ".xml")
JUNK = ("_scratch_*", "*.preedit", "*.orig", "*.bak", "*tamper*.py")

# 1.4 over-enforcement pre-screen (Fable audit 2026-09-21): the mechanical patterns that a GPT-5.6-sol
# reviewer turns into a false-rejection MAJOR by reading the rubric. These are WARN-level TRIAGE, not gates -
# each flagged criterion must be checked against the instruction (some minima ARE required). Running this grep
# across the corpus first finds most of what GPT names from reading, at Haiku cost, before the Opus audit pass.
OVER_ENFORCE = [
    (
        r"at least (two|three|four|\d+)|>=\s*\d|\b(two|three) (examples|different|distinct)",
        "cardinality/diversity minimum (instruction may set none)",
    ),
    (
        r"different (labels|fix types|kinds|categories)|label diversity|diversity",
        "diversity mandate (instruction may not require variety)",
    ),
    (
        r"must (be weighed|drive|turn on|be a factor)|no placement turns on|placement turns on",
        "methodology mandate (forces HOW, not WHAT)",
    ),
    (
        r"outside this set|not supplied|cannot be opened|only these (files|sources)|supplied file",
        "source whitelist (solver may see more files than the judge)",
    ),
    (
        r"for example[^.]{0,90}\bfail",
        "for-example->fail mapping (a specific case hard-coded as failure)",
    ),
    (
        r"while also|marked [^.]{0,30} while|contradicts its own",
        "self-contradiction rule (penalises a legal combination)",
    ),
    (
        r"word for word|character[- ]exact|exact(ly)? reproduc|verbatim",
        "exact-reproduction demand (paraphrase/ASCII-normalise may be legal)",
    ),
    (
        r"committed plan|as a committed",
        "committed-vs-proposed distinction (one word separates pass from fail)",
    ),
]


def crit_count(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    return len(
        re.findall(r"^\s*\[\[\s*(?:criteria|criterion|checks)\s*\]\]", txt, re.M)
    )


def files_lists(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    out = []
    for m in re.finditer(r"files\s*=\s*\[(.*?)\]", txt, re.S):
        out += re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))
    return out


def crit_blocks(path):
    """Split a judge.toml into (criterion_name, body_text) pairs."""
    txt = open(path, encoding="utf-8", errors="replace").read()
    parts = re.split(
        r"^\s*\[\[\s*(?:criteria|criterion|checks)\s*\]\]\s*$", txt, flags=re.M
    )
    out = []
    for body in parts[1:]:
        m = re.search(r"name\s*=\s*['\"]([^'\"]+)['\"]", body)
        out.append((m.group(1) if m else "?", body))
    return out


def num_tuples(txt):
    """Distinctive numeric tuples (>=3 comma-separated integers) inside Expected: clauses."""
    out = set()
    for exp in re.finditer(r"Expected:(.*?)(?:FAIL|PASS|$)", txt, re.S):
        for m in re.finditer(r"(\d+(?:\s*,\s*\d+){2,})", exp.group(1)):
            out.add(re.sub(r"\s+", "", m.group(1)))
    return out


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(65536), b""):
            h.update(b)
    return h.hexdigest()


def _read(p):
    try:
        return open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def check(root):
    root = root.rstrip("/\\")
    task = os.path.basename(root)
    hard, soft = [], []

    judges = sorted(
        glob.glob(os.path.join(root, "tests", "deliverables*", "judge.toml"))
    )
    if not judges:
        hard.append("no tests/deliverables*/judge.toml found")

    # DataOS never injects the gs://colab-bench credential, so a Dockerfile that runs `dvc pull` fails the image build
    # before any review (5-1-0: ImageBuildError twice, 2026-09-22). assemble_task.py adds this block to every SVC
    # build (47-0-0, 48-0-0 on 2026-09-23), so it must be caught here, not on DataOS.
    if "dvc pull" in _read(os.path.join(root, "environment", "Dockerfile")):
        hard.append(
            "environment/Dockerfile runs `dvc pull`: DataOS cannot reach gs://colab-bench (ImageBuildError); "
            "remove the dvc block and ship the needed files in initial_workspace/"
        )

    all_pkg = {f for _, _, fs in os.walk(root) for f in fs}
    grader_txt = ""
    for j in judges:
        d = os.path.basename(os.path.dirname(j))
        n = crit_count(j)
        if n > MAX_CRIT:
            hard.append("grammar bomb: %s has %d criteria (>%d)" % (d, n, MAX_CRIT))
        grader_txt += open(j, encoding="utf-8", errors="replace").read() + "\n"
        for fp in files_lists(j):
            base = os.path.basename(fp)
            # tests/test.sh writes <deliverable>.formula_audit.md at grade time, so a files= entry naming it is
            # present when graded. 2026-09-23: 35-0-0 listed it exactly as DataOS's own 1.8 finding asked, and this
            # check would have refused its zip forever. Only that generated suffix is allowed, and only when the
            # deliverable itself ships and test.sh really generates the audit.
            if (
                base.endswith(".formula_audit.md")
                and base[: -len(".formula_audit.md")] in all_pkg
                and "formula_audit" in _read(os.path.join(root, "tests", "test.sh"))
            ):
                continue
            if base and base not in all_pkg:
                hard.append("%s: files= names %s (not in package)" % (d, base))
        # 1.4 over-enforcement pre-screen, per criterion (TRIAGE, verify against instruction)
        for cname, body in crit_blocks(j):
            for pat, label in OVER_ENFORCE:
                if re.search(pat, body, re.I):
                    soft.append("1.4 candidate: %s/%s -> %s" % (d, cname, label))
                    break

    # solver-visible files
    solver_files = []
    for base in ("instruction.md", os.path.join("tests", "task_prompt.txt")):
        p = os.path.join(root, base)
        if os.path.exists(p):
            solver_files.append(p)
    ip = os.path.join(root, "environment", "initial_workspace")
    for dp, _, fs in os.walk(ip):
        for f in fs:
            solver_files.append(os.path.join(dp, f))

    # 1.6 leak: strings + expected-value tuples in solver-visible text
    tuples = num_tuples(grader_txt)
    for p in solver_files:
        if not p.lower().endswith(TEXT_EXT):
            continue
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        rel, low = os.path.relpath(p, root), txt.lower()
        for s in LEAK_STRINGS:
            if s in low:
                hard.append("leak: solver-visible %s contains %r" % (rel, s))
        norm = re.sub(r"\s+", "", txt)
        for t in tuples:
            if t in norm:
                soft.append(
                    "expected-value tuple %s appears in solver-visible %s (confirm not a leak)"
                    % (",".join(re.findall(r"\d+", t)), rel)
                )

    # 1.6 leak: solution bytes duplicated into the workspace
    sol_hashes = {}
    for p in glob.glob(os.path.join(root, "solution", "**", "*"), recursive=True):
        if os.path.isfile(p):
            sol_hashes[sha(p)] = os.path.basename(p)
    for dp, _, fs in os.walk(ip):
        for f in fs:
            wp = os.path.join(dp, f)
            try:
                h = sha(wp)
            except Exception:
                continue
            if h in sol_hashes:
                hard.append(
                    "leak: workspace file %s is byte-identical to solution/%s"
                    % (os.path.relpath(wp, root), sol_hashes[h])
                )

    # mojibake + CRLF
    for dp, dirs, fs in os.walk(root):
        for nm in list(dirs) + fs:
            if "�" in nm or any(b in nm for b in MOJI):
                soft.append("mojibake in name: %s" % nm)
    for p in solver_files + judges:
        if not p.lower().endswith(TEXT_EXT):
            continue
        rel = os.path.relpath(p, root)
        raw = open(p, "rb").read()
        txt = raw.decode("utf-8", "replace")
        if "�" in txt:
            soft.append("U+FFFD (bad decode) in %s" % rel)
        elif any(b in txt for b in MOJI):
            soft.append("mojibake bigram in %s" % rel)
        if b"\r\n" in raw:
            soft.append("CRLF in %s (want LF)" % rel)

    # junk
    if glob.glob(os.path.join(root, "**", "lease.json"), recursive=True):
        hard.append("build junk present: lease.json")
    for pat in JUNK:
        hits = glob.glob(os.path.join(root, "**", pat), recursive=True)
        if hits:
            soft.append(
                "leftover (zip builder must exclude): %s"
                % ", ".join(os.path.basename(h) for h in hits[:5])
            )

    return task, hard, soft


rc = 0
for root in sys.argv[1:]:
    task, hard, soft = check(root)
    verdict = "FAIL" if hard else ("WARN" if soft else "PASS")
    if hard:
        rc = 1
    print("\n=== %s: %s ===" % (task, verdict))
    for h in hard:
        print("  HARD:", h)
    for s in soft:
        print("  warn:", s)
    if not hard and not soft:
        print("  clean: criteria within budget, no leak, no packaging defect")
if len(sys.argv) < 2:
    print("usage: python tools/svc_prefilter.py <package_root> [...]")
sys.exit(rc)
