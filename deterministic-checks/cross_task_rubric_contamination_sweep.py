#!/usr/bin/env python3
"""Cross-task rubric contamination sweep: NOT a registered check, NOT wired into either
orchestrator. A manual/semi-automated triage tool for a real defect class GLM's round-37
coverage-synthesis first flagged, kept here (rather than discarded) because it found 4 real,
hand-confirmed defects beyond the one GLM reported, and because building it and disclosing why
it does not ship is itself the useful record for whoever picks this up next.

The defect class: a task's rubric criteria reference content that does not exist anywhere in
ITS OWN environment/, but exactly matches content that genuinely exists in some OTHER task's
environment -- meaning the rubric was very likely copied from a sibling task (same numbered
family, or a different one entirely) and never re-scoped to the task it now lives in.

Confirmed real instances (2026-09-16, all hand-verified against real files in
C:\\ekwqc\\repo\\pipeline\\data\\svc_pc_qc\\03_dataos_ready -- not sampled, not taken on GLM's
report alone):

  - SVC-PC-21-4-0 (the seed example): tests/deliverables_02/judge.toml r019/r020 grade
    "Workforce and monthly payroll formats differ" / "email appears only in the workforce
    export ... Payroll and time-off sources have no email field". 21-4-0's own environment has
    12 Payroll_Register_2021-NN.xlsx files (Accounting pool) but NO workforce-export or
    time-off-source file under any name, and neither its own task_prompt.txt nor its own
    solution/solve.sh ever mention "workforce" or "time-off". SVC-PC-29-2-0's environment has
    time_off.csv, Worker_Report.csv, Payroll_Register.csv -- all THREE sitting directly under
    initial_workspace/ (not the generic _corpus_subtree/ pool) -- exactly the 3-way schema
    comparison r019/r020 describe.
  - SVC-PC-56-0-0, SVC-PC-56-5-0, SVC-PC-56-7-0 (found by this sweep, not by GLM): each cites
    "the company overview deck" for specific verbatim content (56-5-0's r005 even cites "slide
    2"), but none of the three has Company_Overview_Deck.pptx anywhere in its own environment.
    Full hand check of all 10 SVC-PC-56-*-0 siblings: 4 (56-1/3/4/6-0) have the file, 6 don't;
    of those 6, exactly these 3 cite it in their own rubric (the other 4 -- 56-2/8/9/10-0 -- are
    clean on this specific issue). The file is real, plentiful corpus-wide (79 tasks' environments
    contain it via the generic Board shared-drive pool) -- these 3 tasks' own curated environment
    subset simply didn't include it.

SVC-PC-70-6-0 (GLM's weaker, unconfirmed candidate -- an "IT1-IT8" framework graded but "absent
from its own environment"): investigated and RESOLVED AS NOT CONTAMINATION, not left unresolved.
70-6-0's tests/deliverables_01,03,04/judge.toml reference "IT2 sync", "IT3 tracking", "IT4", and
"IT1-IT8 (Marcus/CTO)". Its own environment (_corpus_subtree/My Drive -- marcus.rivera/
Year_2_Tech_Roadmap_Draft.docx, read directly, not inferred from the filename) is a real 7,345-
character roadmap authored by "Marcus Rivera (CTO)" whose Workstream D ("harden inventory
allocation and order routing... stock counts never desync", "Automate reorder-point alerts and
lead-time tracking") substantively matches what the criteria describe. The real document uses
lettered workstreams A-F, not "IT1-IT8" -- so the rubric's numbering is almost certainly its own
shorthand for enumerating specific initiatives drawn from this real document, not a literal
label that should appear verbatim in a source file. Corpus-wide grep confirms no other task's
judge.toml/task_prompt.txt/instruction.md contains "IT1-IT8", "IT2 sync" or "IT3 tracking" --
there is no candidate sibling this could have been copied FROM even under the contamination
hypothesis, which independently rules it out.

Why this is NOT wired into svc_run_checks.py / ekw_run_checks.py, disclosed rather than silently
dropped, per this repo's own hard rule against softening a negative finding:

Real precision, measured, not assumed: 3 tightening rounds against the real 600-task corpus, each
one calibrated by hand-checking real candidates against real files (44 candidates hand-checked
total across both rounds, see turing-context's ekw/svc-dataos-failure-mode-tracker-2026-09-15.md
for the full log):
  1. Unigram + bigram matching, bigram DF<=150, unigram DF<=8, direct-file-owner required,
     absent-from-own-environment required: 250 tasks / 611 findings. An 11-task hand sample was
     dominated (~9/11) by lone English words ("change", "control", "required") coincidentally
     matching some rare filename fragment somewhere in a 600-task corpus -- meaningless.
  2. Dropped unigrams entirely (bigram-only): 240 tasks / 611->198 findings, still too broad. A
     25-task hand sample found the dominant failure mode was a single task, SVC-PC-5-1-0, whose
     environment mirrors the ENTIRE shared-drive pool directly under initial_workspace/data/
     Company Shared Drive/... instead of nesting it under _corpus_subtree/ like all 599 other
     tasks -- a build-pipeline path-convention difference, hand-confirmed via direct find (1185
     files), not a real task-specific signal. It alone produced >60% of that sample's spurious
     "sibling" matches. A cluster of ~20-70 further tasks show the same pattern at smaller scale
     (100s of "direct" tokens vs the 2 real confirmed siblings' 10-11).
  3. Added a citation-language filter (a criterion must use citation-shaped language -- "sourced
     to", "extracted from", "cites", "appears only in", a slide/page/row locator -- OR the
     matched phrase must be introduced by "the/a/an" within 3 words) and excluded any task whose
     own direct-token count exceeds HUB_TOKEN_COUNT_CEIL (structural-outlier guard, see that
     constant). Final: 52 tasks / 104 findings.

Even after all three rounds, hand-verification of the full family-56 cluster plus two more
25-and-11-task random samples puts real precision at roughly 4-5 genuine out of ~44 hand-checked
candidates (~10%) -- and it is NOT uniform: the "company overview deck" signature alone was 3
genuine of 4 checked (75%), while every other surviving cluster checked (customer support,
board minutes, orders/products/customers/contacts export, input files, inventory flows, cap
table, investor letter, demand plan, quality standards, cost allocation) resolved to coincidental
archetype-shared vocabulary or a paraphrase of the task's own real (differently-named) content on
every instance actually opened and read. A single mechanical threshold cannot separate these two
populations -- the signal genuinely varies by WHICH phrase matched, not just how rare it is. This
does not clear this repo's own bar for even a warn-tier check (compare duplicate_criterion_
content_check.py's warn-tier population, which the tracker's own hand sample found 85-90% benign
but the check still surfaces a real minority efficiently at a population size two orders of
magnitude larger than this sweep's signal-bearing slice). Shipping this as an unattended
letter-D/E finding would train reviewers to ignore it; shipping it as a giant warn-tier dump
would not, in practice, get read.

What WOULD make this shippable, not attempted here (time-boxed out of tonight's scope): a
narrower check built around the ONE thing that actually separated genuine from coincidental in
every hand-read case -- a criterion whose REQUIREMENT clause names a specific document-shaped
noun (deck, export, register, source, record) as something to be SOURCED/CITED/TRACED TO, cross-
checked against whether that exact noun phrase's referent exists ANYWHERE in the task's own
environment INCLUDING under a different filename (which requires either fuzzy file-content
matching or an LLM read, not filename-token matching) -- not a cross-task lookup at all. That is
a materially different, smaller-scoped check than what this file attempts; flagging it as a real
candidate for a future round rather than attempting it here.

How to use this manually: `python cross_task_rubric_contamination_sweep.py --root <corpus>
--out findings.json`, then read findings.json's `direct_owners` per candidate and hand-check
each against the real environment/ trees on both sides before trusting it -- this script's own
false-positive rate above is the reason that step is not optional.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

# ---------------------------------------------------------------------------
# calibrated constants -- see module docstring "Why this is NOT wired" for the real numbers
# behind each of these
# ---------------------------------------------------------------------------

BIGRAM_DF_CEIL = 150
UNIGRAM_DF_CEIL = 8
HUB_TOKEN_COUNT_CEIL = (
    30  # SVC-PC-5-1-0 sits at 1073; real confirmed siblings sit at 10-11
)

_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SEP_RE = re.compile(r"[^A-Za-z]+")
_DATEY_RE = re.compile(r"^(19|20)\d{2}$|^q[1-4]$|^v\d+$|^\d+$")
_FAMILY_RE = re.compile(r"^SVC-PC-(\d+)-\d+-\d+$")

_CITATION_RE = re.compile(
    r"\b(sourced to|extracted from|traced? to|cites?\b|cited\b|per the\b|according to"
    r"|appears? only in|found in the|as (?:shown|stated|reported) in|referenced? in"
    r"|drawn from|documented in|listed in the|slide \d|page \d|\btab \w|row \d)\b",
    re.IGNORECASE,
)


def family_of(task_id: str) -> str | None:
    m = _FAMILY_RE.match(task_id)
    return m.group(1) if m else None


def tokenize(text: str) -> tuple[set[str], set[str], list[str]]:
    """unigrams, bigrams, and the filtered word list (for citation-window lookups). Splits on
    camelCase boundaries and any non-letter separator (so "time_off.csv" and "time-off" both
    normalize to the same "time off" bigram), lowercases, drops tokens under 3 chars and
    date/version-shaped tokens (pure noise across a corpus using YYYY/YYYY-MM/Q1-4/vN constantly
    for unrelated files)."""
    spaced = _CAMEL_RE.sub(" ", text)
    words = [w.lower() for w in _SEP_RE.split(spaced) if w]
    words = [w for w in words if len(w) >= 3 and not _DATEY_RE.match(w)]
    uni = set(words)
    bi = {words[i] + " " + words[i + 1] for i in range(len(words) - 1)}
    return uni, bi, words


def has_citation_language(description: str, bigram: str, words: list[str]) -> bool:
    """True if the description uses citation-shaped language generally, OR the matched bigram is
    itself introduced by a determiner within 3 words back ("the workforce export", "the company
    overview deck") -- the shape that separated both originally-confirmed real cases from ~90%
    of the unfiltered hand sample's coincidental-vocabulary noise. A filter, not proof: every
    survivor still needs hand verification against real files, see module docstring."""
    if _CITATION_RE.search(description):
        return True
    bwords = bigram.split()
    try:
        i = next(
            k
            for k in range(len(words) - 1)
            if words[k] == bwords[0] and words[k + 1] == bwords[1]
        )
    except StopIteration:
        return False
    window = [w.lower() for w in words[max(0, i - 3) : i]]
    return any(w in ("the", "a", "an") for w in window)


def find_task_dirs(root: Path, task_ids=None, id_prefix: str = "") -> list[Path]:
    if task_ids:
        dirs = []
        for tid in task_ids:
            p = root / tid
            if not p.is_dir():
                print(f"WARNING: task dir not found, skipping: {p}", file=sys.stderr)
                continue
            dirs.append(p)
        return dirs
    return sorted(
        p for p in root.iterdir() if p.is_dir() and p.name.startswith(id_prefix)
    )


def find_judge_files(task_dir: Path) -> list[Path]:
    return sorted(
        set(task_dir.glob("tests/deliverables/judge.toml"))
        | set(task_dir.glob("tests/deliverables_*/judge.toml"))
    )


def load_criteria(task_dir: Path) -> list[dict]:
    out = []
    for jf in find_judge_files(task_dir):
        try:
            data = tomllib.loads(jf.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  PARSE ERROR {jf}: {exc}", file=sys.stderr)
            continue
        crits = data.get("criterion")
        if not isinstance(crits, list):
            continue
        group = jf.parent.name
        for c in crits:
            if not isinstance(c, dict):
                continue
            out.append(
                {
                    "file": group,
                    "name": c.get("name", "?"),
                    "description": c.get("description") or "",
                }
            )
    return out


def build_environment_index(root: Path, task_dirs: list[Path]) -> dict:
    """Always scans the FULL corpus under root, independent of which task_ids the caller asked
    to report on -- this check's cross-task index cannot be built from one shard's task subset
    (see module docstring: this is why it is architecturally incompatible with the sharded
    per-task-id invocation both orchestrators use for every other check, and part of why it is
    not registered there)."""
    df_any: dict[str, set[str]] = defaultdict(set)
    df_direct: dict[str, set[str]] = defaultdict(set)
    task_tokens: dict[str, set[str]] = {}
    for td in task_dirs:
        tid = td.name
        env = td / "environment"
        toks: set[str] = set()
        if env.is_dir():
            for f in env.rglob("*"):
                if not f.is_file():
                    continue
                is_pool = "_corpus_subtree/" in f.relative_to(env).as_posix()
                uni, bi, _ = tokenize(f.stem)
                all_toks = uni | bi
                toks |= all_toks
                for t in all_toks:
                    df_any[t].add(tid)
                    if not is_pool:
                        df_direct[t].add(tid)
        task_tokens[tid] = toks
    return {"df_any": df_any, "df_direct": df_direct, "task_tokens": task_tokens}


def sweep(root: Path, index: dict) -> list[dict]:
    df_any = index["df_any"]
    df_direct = index["df_direct"]
    task_tokens = index["task_tokens"]

    direct_token_count: dict[str, int] = defaultdict(int)
    for owners in df_direct.values():
        for o in owners:
            direct_token_count[o] += 1
    hub_tasks = {t for t, n in direct_token_count.items() if n > HUB_TOKEN_COUNT_CEIL}
    print(
        f"{len(hub_tasks)} hub/outlier tasks excluded from sibling ownership",
        file=sys.stderr,
    )

    findings: list[dict] = []
    for tid, own_tokens in sorted(task_tokens.items()):
        own_family = family_of(tid)
        for c in load_criteria(root / tid):
            _uni, bi, words = tokenize(c["description"])
            for tok in bi:
                if tok in own_tokens:
                    continue
                owners_any = df_any.get(tok)
                if not owners_any or len(owners_any) > BIGRAM_DF_CEIL:
                    continue
                owners_direct = sorted(
                    o for o in df_direct.get(tok, ()) if o != tid and o not in hub_tasks
                )
                if not owners_direct:
                    continue
                if not has_citation_language(c["description"], tok, words):
                    continue
                cross_family = sorted(
                    o for o in owners_direct if family_of(o) != own_family
                )
                findings.append(
                    {
                        "task_id": tid,
                        "family": own_family,
                        "file": c["file"],
                        "criterion": c["name"],
                        "description": c["description"][:300],
                        "token": tok,
                        "df_any": len(owners_any),
                        "direct_owners": owners_direct,
                        "cross_family_owners": cross_family,
                    }
                )
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Manual triage tool, NOT a registered check -- see module docstring for real "
            "precision numbers and why. Emits candidate (task, sibling) pairs for hand review; "
            "does not itself confirm contamination."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "task_ids",
        nargs="*",
        help="restrict REPORTED findings to these task ids (the cross-task index is always built from the full --root regardless)",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="report on every task (default if no task_ids given)",
    )
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--id-prefix", default="")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    all_task_dirs = find_task_dirs(args.root, None, id_prefix=args.id_prefix)
    if not all_task_dirs:
        print("No task directories found under --root.", file=sys.stderr)
        return 2
    print(
        f"indexing {len(all_task_dirs)} task environments under {args.root} ...",
        file=sys.stderr,
    )
    index = build_environment_index(args.root, all_task_dirs)

    findings = sweep(args.root, index)
    report_ids = set(args.task_ids) if (args.task_ids and not args.all) else None
    if report_ids is not None:
        findings = [f for f in findings if f["task_id"] in report_ids]

    by_task = defaultdict(list)
    for f in findings:
        by_task[f["task_id"]].append(f)

    print(
        f"\n{len(by_task)} tasks with >=1 candidate finding, {len(findings)} total findings"
    )
    for tid in sorted(by_task):
        toks = sorted({f["token"] for f in by_task[tid]})
        sib = sorted({o for f in by_task[tid] for o in f["direct_owners"]})
        tag = (
            "CROSS-FAMILY"
            if by_task[tid][0]["cross_family_owners"]
            else "same-family-only"
        )
        print(f"[{tag}] {tid} (family {family_of(tid)}): tokens={toks}  siblings={sib}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        aggregate = {
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "root": str(args.root),
            "n_tasks_indexed": len(all_task_dirs),
            "n_tasks_flagged": len(by_task),
            "n_findings": len(findings),
            "findings": findings,
        }
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(aggregate, fh, indent=2, ensure_ascii=False)
        print(f"\nWrote {args.out}")

    print(
        "\nNOT a pass/fail verdict -- every finding above needs hand verification against real "
        "files on both sides before it means anything. See module docstring for real precision."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
