#!/usr/bin/env python3
"""Sort the majors in a DataOS comprehensive review by what TFRL actually rejects.

Why: on 40 TFRL-labelled tasks, TFRL rejected for one kind of major far more than the others. A major that says the answer
key (golden), the source files or the prompt itself is wrong flagged 10 of 30 rejected tasks and 2 of 17 passed tasks.
Majors that say a weak answer can still score, or that the grading scripts misbehave, hit rejected and passed tasks at
about the same rate. See REVIEW_TRIAGE_EVIDENCE.md.

What it does: reads one or more review JSON files (the shape build_review_union.py reads: overall_verdict, checks[] with
id, severity, justification), takes the majors, and has Opus (3 independent passes, 2 of 3 must agree) label each one:
  reference_defect   answer key, sources or prompt wrong or ambiguous      -> HOLD: clear it before the task goes to TFRL
  unfair_to_correct  a correct answer is failed                             -> FIX_NEXT when a recorded run shows it
  lenient / harness / other                                                 -> FIX_LAST (the SOP still needs 0 majors to ship)
Exit code 10 when any major is HOLD, so a script can gate on it. This only orders the work and adds a hold; it does not
change the SOP rule that a task ships at 0 majors.

  python3 triage_review_majors.py REVIEW.json [REVIEW2.json ...] [--out report.md] [--lanes DIR,DIR,DIR]
  python3 triage_review_majors.py --majors-jsonl rows.jsonl      (rows with "check" and "text", for analysis)
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from golden_criterion_review import run_claude  # noqa: E402

MAJOR_WORDS = {"major", "blocking", "critical"}
TEXT_KEYS = ("justification", "description", "detail", "finding", "text", "evidence")
FIX_KEYS = ("suggested_fix", "fix", "recommendation", "remediation")
PASSES = 3
CHUNK_CHARS = 120000

DIRECTION_RULE = """You are auditing automated review findings about benchmark tasks. The batch is on standard input: each block is one MAJOR finding (the review's justification followed by its suggested fix). Use no tools. Answer from the text alone. You do not know whether the task was later accepted or rejected, and you must not guess it.

For each finding decide which DIRECTION the claimed defect works in. Choose the single best:
- "unfair_to_correct": a correct, instruction-compliant answer is failed, penalised or loses reward (the rubric demands something the instruction does not ask for, is stricter than the sources support, or a defensible alternative is rejected).
- "lenient": a wrong, hollow, empty or incomplete answer can earn credit or pass (false credit, a check that can be gamed, missing coverage that lets weak work score).
- "reference_defect": the golden answer, the provided sources, or the instruction itself is wrong, contradictory, ambiguous on a central quantity, missing something a solver needs, or contaminated.
- "harness": the grading machinery or test scripts misbehave (truncation, parsing, regex or formula detection, table detection, timeouts, crashes, file handling), independent of what the rubric intends.
- "other": none of the above.

Also decide "observed_run": "yes" if the finding cites a specific recorded run or eval (an eval id, or the actual judge votes of a run) that shows the effect; otherwise "no".

Your whole reply must be ONE JSON object and nothing else: {"<finding key>": {"direction": "unfair_to_correct" or "lenient" or "reference_defect" or "harness" or "other", "observed_run": "yes" or "no", "why": "one short sentence"}} with an entry for every finding key (the key is on each "-----MAJOR mNNN" line).
"""

DIRECTIONS = ("reference_defect", "unfair_to_correct", "lenient", "harness", "other")


def first_text(c, keys):
    for k in keys:
        v = c.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (list, dict)) and v:
            return json.dumps(v, ensure_ascii=False)[:1500]
    return ""


def load_majors(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    checks = d.get("checks")
    if "overall_verdict" not in d or not isinstance(checks, list):
        raise ValueError(
            "%s is not a review (needs overall_verdict and checks[])" % path
        )
    out = []
    for c in checks:
        if (
            isinstance(c, dict)
            and str(c.get("severity", "")).strip().lower() in MAJOR_WORDS
        ):
            text = first_text(c, TEXT_KEYS)
            fix = first_text(c, FIX_KEYS)
            out.append(
                {
                    "source": str(path),
                    "check": str(c.get("id", "?")),
                    "text": (text + " " + fix).strip(),
                }
            )
    return out


def load_jsonl(path):
    rows = [
        json.loads(l)
        for l in Path(path).read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    return [
        {"source": str(path), "check": str(r.get("check", "?")), "text": r["text"]}
        for r in rows
    ]


def build_chunks(majors, cap=CHUNK_CHARS):
    chunks, cur, size = [], [], 0
    for i, m in enumerate(majors):
        block = "-----MAJOR m%03d (review check %s)-----\n%s" % (
            i + 1,
            m["check"],
            m["text"][:3000],
        )
        if cur and size + len(block) > cap:
            chunks.append(cur)
            cur, size = [], 0
        cur.append((i, block))
        size += len(block)
    if cur:
        chunks.append(cur)
    return chunks


def label_majors(majors, runner=run_claude, lanes=None):
    """One list of per-major vote lists, in input order. Each vote is {"direction", "observed_run"}."""
    votes = [[] for _ in majors]
    jobs = []
    for chunk in build_chunks(majors):
        for p in range(PASSES):
            jobs.append((chunk, p))

    def run(job):
        chunk, p = job
        text = "\n\n".join(b for _i, b in chunk)
        cfg = lanes[p % len(lanes)] if lanes else None
        reply = runner(DIRECTION_RULE, text, config_dir=cfg)
        return chunk, reply

    with ThreadPoolExecutor(max_workers=min(len(jobs), 6) or 1) as ex:
        for chunk, reply in ex.map(run, jobs):
            for i, _b in chunk:
                v = (reply or {}).get("m%03d" % (i + 1)) or {}
                if v.get("direction") in DIRECTIONS:
                    votes[i].append(
                        {
                            "direction": v["direction"],
                            "observed_run": v.get("observed_run") == "yes",
                        }
                    )
    return votes


def decide(vote_list):
    """Direction needs 2 of 3 passes; otherwise unresolved. Tier follows the measured pattern."""
    counts = {}
    for v in vote_list:
        counts[v["direction"]] = counts.get(v["direction"], 0) + 1
    direction = next((d for d in DIRECTIONS if counts.get(d, 0) >= 2), None)
    observed = sum(1 for v in vote_list if v["observed_run"]) >= 2
    if direction == "reference_defect":
        tier = "HOLD"
    elif direction == "unfair_to_correct" and observed:
        tier = "FIX_NEXT"
    elif direction is None:
        tier = "FIX_NEXT"  # the passes disagreed: do not bury it
    else:
        tier = "FIX_LAST"
    return {
        "direction": direction or "unresolved",
        "observed_run": observed,
        "tier": tier,
    }


def report(majors, decisions):
    order = {"HOLD": 0, "FIX_NEXT": 1, "FIX_LAST": 2}
    rows = sorted(zip(majors, decisions), key=lambda x: order[x[1]["tier"]])
    lines = ["# Review majors, sorted by what TFRL rejects", ""]
    n_hold = sum(1 for d in decisions if d["tier"] == "HOLD")
    lines.append(
        "%d majors: %d HOLD, %d FIX_NEXT, %d FIX_LAST."
        % (
            len(decisions),
            n_hold,
            sum(1 for d in decisions if d["tier"] == "FIX_NEXT"),
            sum(1 for d in decisions if d["tier"] == "FIX_LAST"),
        )
    )
    lines.append(
        "HOLD means the answer key, the sources or the prompt itself is wrong: clear these before the task goes to TFRL."
    )
    lines.append("")
    for m, d in rows:
        lines.append(
            "- **%s** | check %s | %s%s | %s"
            % (
                d["tier"],
                m["check"],
                d["direction"],
                ", recorded run" if d["observed_run"] else "",
                m["text"][:240].replace("\n", " "),
            )
        )
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("reviews", nargs="*")
    ap.add_argument("--majors-jsonl")
    ap.add_argument("--out")
    ap.add_argument("--json-out")
    ap.add_argument(
        "--lanes",
        default="",
        help="comma-separated CLAUDE_CONFIG_DIR values, used round robin",
    )
    a = ap.parse_args(argv)
    majors = []
    for p in a.reviews:
        majors += load_majors(p)
    if a.majors_jsonl:
        majors += load_jsonl(a.majors_jsonl)
    if not majors:
        print("no majors found: nothing to hold")
        return 0
    lanes = [x for x in a.lanes.split(",") if x]
    decisions = [decide(v) for v in label_majors(majors, lanes=lanes or None)]
    text = report(majors, decisions)
    (Path(a.out).write_text(text, encoding="utf-8") if a.out else print(text))
    if a.json_out:
        Path(a.json_out).write_text(
            json.dumps([dict(m, **d) for m, d in zip(majors, decisions)], indent=1),
            encoding="utf-8",
        )
    return 10 if any(d["tier"] == "HOLD" for d in decisions) else 0


if __name__ == "__main__":
    sys.exit(main())
