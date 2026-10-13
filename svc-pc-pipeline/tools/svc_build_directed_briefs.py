#!/usr/bin/env python3
"""Build COMPLETE directed fix briefs for SVC-PC tasks (v7).

Why this replaces the old generator: the 2026-09-21 Fable review proved the recurring 1.4/1.5 rejections
were largely OUR fault, not the severity wall. The old briefs truncated justification[:700]/suggested_fix[:400],
took the LATEST round only, kept MAJORS only, and collapsed multi-part findings to one excerpt. GPT re-audits
the WHOLE task every round; we handed the agent a fragment; it closed the fragment; GPT rejected on the part
we cut (11-3-0 is the exhibit: a 3-part 1.5 finding, brief carried 1 part, rejected on 1.5 three rounds).

This tool builds, per task, a brief carrying EVERY finding across EVERY round, from BOTH reviewer seats,
MAJOR and MODERATE, at FULL text, grouped by round, with a mandate to close each sub-finding and report the
criterion that closes it. No truncation. Usage:
  python tools/svc_build_directed_briefs.py [TASK ...]   (default: all graded in-pipeline tasks)
Outputs _deepbriefs/<task>.md. Push to the sandbox /root/qc/_deepbriefs/ and run ONE Opus agent per task.
"""

import json, re, zipfile, glob, os, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DL = os.path.join(os.path.expanduser("~"), "Downloads")
OUT = os.path.join(HERE, "_deepbriefs")
os.makedirs(OUT, exist_ok=True)
CORPUS = "/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready"
argv_tasks = [a for a in sys.argv[1:] if a.startswith("SVC-PC-")]


def lv(text):
    for pos in reversed([m.start() for m in re.finditer(r'"overall_verdict"', text)]):
        s = text.rfind("{", 0, pos)
        d = 0
        for i in range(s, len(text)):
            if text[i] == "{":
                d += 1
            elif text[i] == "}":
                d -= 1
                if d == 0:
                    try:
                        j = json.loads(text[s : i + 1])
                        if isinstance(j, dict) and isinstance(j.get("checks"), list):
                            return j
                    except Exception:
                        pass
                    break
    return None


# 2026-09-28: returns are also saved by the browser tool as "<bundle>-with-runs.zip" under
# ~/.config/opencode/data-platform-output. Reading only Downloads/*_with_runs* gave 79-2-0 and 36-3-0 briefs
# built from 1 of 3 and 1 of 2 graded rounds, so the lanes fixed blind to the newer Majors. Read both folders
# and both spellings, one zip per bundle (newest copy wins).
SRC_DIRS = [
    DL,
    os.path.join(
        os.path.expanduser("~"), ".config", "opencode", "data-platform-output"
    ),
]
_by_bundle = {}
for _d in SRC_DIRS:
    for _p in glob.glob(os.path.join(_d, "*_with_runs*.zip")) + glob.glob(
        os.path.join(_d, "*-with-runs*.zip")
    ):
        _b = re.sub(r"[-_]with[-_]runs.*$", "", os.path.basename(_p)[:-4])
        if _b not in _by_bundle or os.path.getmtime(_p) > os.path.getmtime(
            _by_bundle[_b]
        ):
            _by_bundle[_b] = _p
zips = sorted(_by_bundle.values(), key=lambda p: os.path.getmtime(p))
# task -> ordered list of (round, seat, verdict, [ (cid,sev,name,why,fix) ... ])
per = {}
# task -> [(round, first exception line)] for rounds where DataOS ran evaluations but produced no review at all
# (2026-09-26: 12-7-0's only round, batvh2 on 09-22, died at "SandboxBuildFailedError" in DataOS's own Docker
# build; the brief builder saw no findings, printed "no findings", and the runner parked it for 4 days as "no
# complete brief". An errored round is not a clean bill: the task still needs a full audit before it ships.)
errored = {}
for zp in zips:
    zn = re.sub(r"[-_]with[-_]runs.*$", "", os.path.basename(zp)[:-4])
    try:
        z = zipfile.ZipFile(zp)
    except Exception:
        continue
    names = z.namelist()
    reviewed = {
        mm.group(1)
        for mm in (
            re.match(r"(SVC-PC-\d+-\d+-\d+)/.*/verifications/comprehensive_review_", n)
            for n in names
        )
        if mm
    }
    for n in names:
        mm = re.match(r"(SVC-PC-\d+-\d+-\d+)/.*/eval_files/exception\.txt$", n)
        if mm and mm.group(1) not in reviewed and mm.group(1) not in errored:
            exc = [
                ln.strip()
                for ln in z.read(n).decode("utf-8", "replace").splitlines()
                if re.match(r"\s*[\w.]+(Error|Exception)\b", ln)
            ]
            errored[mm.group(1)] = [(zn, (exc[-1] if exc else "exception")[:220])]
    for n in names:
        m = re.match(r"(SVC-PC-\d+-\d+-\d+)/", n)
        if (
            not m
            or "/verifications/comprehensive_review_" not in n
            or not n.endswith(".md")
        ):
            continue
        t = m.group(1)
        seat = (
            "gpt-5.6-sol"
            if "gpt-5.6-sol" in n
            else "opus-5" if "opus-5" in n else "other"
        )
        d = lv(z.read(n).decode("utf-8", "replace"))
        if not d:
            continue
        findings = []
        for c in d.get("checks", []):
            sev = str(c.get("severity", "")).lower()
            if sev not in ("major", "moderate"):
                continue
            findings.append(
                (
                    str(c.get("check") or c.get("check_id") or c.get("id") or "?"),
                    sev,
                    (c.get("name") or "").strip(),
                    (c.get("justification") or c.get("reason") or "").strip(),
                    (c.get("suggested_fix") or "").strip(),
                )
            )
        if findings:
            per.setdefault(t, []).append(
                (zn, seat, str(d.get("overall_verdict")), findings)
            )

targets = argv_tasks or sorted(set(per) | set(errored))
RULES_TEXT = open(
    os.path.join(HERE, "tools", "svc_fix_method_rules.md"), encoding="utf-8"
).read()
METHOD = """You are doing a CAREFUL, INDIVIDUAL rebuild of {T}. This is NOT a batch job - take the full time
budget, work only in this task's directory, and think like the GPT-5.6-sol reviewer who re-audits the WHOLE
task every round.

WHY THIS BRIEF IS LONG: past rounds failed because the fixer was handed a FRAGMENT of the finding and closed
only that fragment, so the reviewer rejected on the part that was cut. Below is EVERY finding this task has
received, across EVERY round, from BOTH reviewer seats, at full text. Close EVERY one - every numbered
sub-point inside every finding. In your final report, list each finding and name the criterion that now
closes it.

METHOD:
1. Read instruction.md in full, the golden (solution/golden_outputs/), and every tests/deliverables*/judge.toml.
2. Re-derive from source: open environment/initial_workspace/ and compute every graded fact yourself; do not
   trust the golden. If the golden disagrees with source, fix the golden (restore formula caches).
3. For EACH finding below, fix the ROOT rubric/golden issue: coverage (1.5) -> a criterion forces every
   instruction requirement against your re-derived value, extend subset criteria to the FULL set, uncheckable
   claims must FAIL; alignment (1.4) -> repair/remove criteria grading what the instruction does not require or
   accepting a wrong basis; golden-wrong (1.1) -> fix the golden; ambiguity (1.3) -> edit instruction.md AND
   tests/task_prompt.txt IDENTICALLY; answer-leak (1.6) -> no expected value in any solver-visible file;
   consistency (1.7) -> fix the mismatched citation/figure; packaging (1.8) -> <=15 criteria/dir, filenames.
4. FULL RUBRIC AUDIT - THE STEP THAT ACTUALLY PASSES THE TASK. The finding ledger below is ONLY what GPT has
   flagged SO FAR. GPT re-audits the WHOLE task every round and rejects on defects never raised before; that
   is exactly how the last round of this task failed (r003 failed a response for cross-training two seats that
   instruction.md line 16 explicitly PERMITS as a fix - a defect that survived 3 rounds unflagged). So do NOT
   stop at the ledger. Go criterion by criterion through EVERY judge dir and check each against instruction.md:
   - OVER-ENFORCEMENT (1.4): does this criterion FAIL a response for something the instruction does not
     require, forbid something it permits, or accept a wrong basis? Repair the wording or remove it.
   - COVERAGE (1.5): trace every requirement in instruction.md to a criterion that enforces it. Any
     requirement with no criterion is a coverage hole - add it against your re-derived value.
   - SCOPE: a criterion that means to grade one tab/section must SAY so, or it catches correct behaviour
     elsewhere (r003's cross-training clause was not scoped to the ranking/holder-mapping).
   You MUST output a per-criterion audit table in your report: criterion id | what it grades | instruction
   line(s) it traces to | verdict (aligned / over-enforces / under-covers / unscoped) | action taken. A
   criterion you did not audit is a criterion GPT will reject you on.
   DIRECTION (category-aware, critical - match the fix to the finding; the old blanket "never add" rule was
   WRONG for coverage and made 1.5 tasks unfixable, the one batch-1 pass GREW its rubric by a whole memo dir):
   - 1.4 over-enforcement -> DELETE or LOOSEN the criterion so it stops failing a compliant reading. Shrink.
   - 1.5 coverage hole -> ADD one criterion enforcing the uncovered requirement against your re-derived value.
     Adding coverage is correct here; the eval-regrade gate confirms a hollow answer now fails it.
   - 1.5 compound-binary (one criterion bundling independently-variable facts) -> SPLIT into one-fact criteria,
     preserving the total weight. A reworded bundle is still a bundle.
   Every added or changed criterion is itself re-graded against the REAL answer DataOS saved (the eval-regrade
   gate): an added criterion that over-enforces, or a loosening that still fails the compliant answer, is
   caught before you ship. So: never add a NEW constraint the instruction does not require (that is the 1.4
   defect that became the next round's finding), but DO add coverage the instruction requires.
5. Adversarial: build a passing-but-wrong answer; tighten until impossible. Passing the rubric must PROVE the
   task was solved.
6. VERIFY and report the numbers: run
   `QC_REWARDKIT_SITE_PACKAGES=/root/venv/lib/python3.13/site-packages CLAUDE_CODE_BIN=$(command -v claude)
   /root/venv/bin/python3 /root/qc/tools/judge_emulate.py oracle {T} --runs 2 --corpus-root {C}
   --out /tmp/{T}_o.json` -> total_reward MUST be 1.0 on BOTH runs. Then re-read each changed criterion and
   confirm a wrong/uncheckable answer now FAILS.

HARD RULES: expected values ONLY in judge.toml; <=15 criteria/dir; LF endings; never lower difficulty; keep
the golden at 1.0.

=== COMPLETE DataOS finding ledger for {T} (every round, both seats, majors + moderates - close EVERY item) ==="""

wrote = 0
for t in targets:
    rounds = per.get(t, [])
    has_note = os.path.exists(os.path.join(OUT, "_owner_notes", t + ".md"))
    if not rounds and not has_note and t not in errored:
        print("  no findings:", t)
        continue
    blocks = []
    for zn, seat, verdict, findings in rounds:
        lines = ["--- round: %s | seat: %s | verdict: %s ---" % (zn, seat, verdict)]
        for cid, sev, name, why, fix in findings:
            lines.append("[%s | %s] %s" % (cid, sev, name))
            if why:
                lines.append("  WHY: " + why)
            if fix:
                lines.append("  FIX: " + fix)
        blocks.append("\n".join(lines))
    if not blocks and t in errored:
        zn, exc = errored[t][0]
        blocks.append(
            "(NO DataOS REVIEW EXISTS. Round %s errored before any reviewer ran: %s. That is DataOS infrastructure, "
            "not a finding against this task, and it is NOT a pass. There is no ledger to close: do step 4 (the FULL "
            "RUBRIC AUDIT) criterion by criterion against instruction.md as the GPT-5.6-sol reviewer would, re-derive "
            "the golden's facts from source (step 2), run the adversarial check (step 5), and verify the golden at 1.0 "
            "on 2 oracle runs (step 6). Fix only what the audit proves wrong; if the audit finds nothing, change "
            "nothing and say so.)" % (zn, exc)
        )
    elif not blocks:
        # never graded (e.g. 5-1-0: both DataOS runs errored before review), so the owner note is the whole brief
        blocks.append(
            "(no open DataOS review findings: either never graded, or it passed DataOS and a later human review "
            "rejected it; the OWNER DECISION above states which and is the target)"
        )
    # The single-source rules (tools/svc_fix_method_rules.md) close every brief and override anything above
    # that conflicts. The runner also appends the CURRENT copy at run time, so an old brief cannot carry old rules.
    # Owner decisions (<OUT>/_owner_notes/<task>.md) survive every brief rebuild: a decision written straight
    # into a brief was lost the next time this script regenerated it. 2026-09-23: 79-1-0's corpus-size finding.
    note_p = os.path.join(OUT, "_owner_notes", t + ".md")
    owner = ""
    if os.path.exists(note_p):
        owner = (
            "=== OWNER DECISION (binding; overrides any finding above it conflicts with) ===\n"
            + open(note_p, encoding="utf-8").read().strip()
            + "\n\n"
        )
    body = (
        METHOD.format(T=t, C=CORPUS)
        + "\n\n"
        + owner
        + "\n\n".join(blocks)
        + "\n\n"
        + "=== THE RULES (tools/svc_fix_method_rules.md) - these override anything above that conflicts ===\n"
        + RULES_TEXT
        + "\n"
    )
    open(os.path.join(OUT, t + ".md"), "w", encoding="utf-8", newline="\n").write(body)
    wrote += 1
    print(
        "  %-16s rounds=%d findings=%d chars=%d"
        % (t, len(rounds), sum(len(f[3]) for f in rounds), len(body))
    )
print("\nwrote %d complete directed briefs -> %s" % (wrote, OUT))
