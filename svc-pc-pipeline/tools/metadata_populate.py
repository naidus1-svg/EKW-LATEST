#!/usr/bin/env python3
"""metadata_populate.py - fill task.toml [metadata] for every SVC-PC task from the task's
own text. All three DataOS Comprehensive Reviews on SVC-PC-54-2-0 (2026-09-18) filed the
empty metadata (category + tags=[] only) as a minor: "domain, occupation, sector, subdomain,
task_type must be populated". Deterministic, zero model calls. Skips a task that already
carries task_type unless --force. Backs up every task.toml it touches.

  occupation  = the instruction's "Role:" line, else the "You are the <role>" sentence
  domain      = the workbook header's function segment ("CIRRUS SLEEP . FP&A TASK WORKBOOK"
                -> "FP&A"), else the role minus title words
  sector      = "Consumer e-commerce" (the SVC-PC corpus is one direct-to-consumer company)
  subdomain   = the instruction's title line (Role format) or its imperative task sentence
  task_type   = from the graded deliverable extensions
  tags        = [domain, sector, task_type] lower-cased

Usage: python3 metadata_populate.py [--dry-run] [--force] [--corpus-root DIR]
"""

import argparse
import glob
import os
import re
import shutil
import time

ap = argparse.ArgumentParser()
ap.add_argument(
    "--corpus-root", default="/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready"
)
ap.add_argument("--dry-run", action="store_true")
ap.add_argument(
    "--force", action="store_true", help="rewrite the six fields even if present"
)
a = ap.parse_args()
stamp = time.strftime("%Y%m%dT%H%MZ", time.gmtime())
bak = f"/root/backup/task-toml-metadata-{stamp}"
TITLE_WORDS = (
    r"\b(Senior|Junior|Lead|Head of|Chief|Director|VP|Vice President|Manager|Analyst|Officer|"
    r"Specialist|Coordinator|Controller|Associate|Partner|Consultant|Advisor|Assistant|Owner|Founder)\b"
)
MIDDLE_DOT = "·"
VERBS = (
    "Build|Prepare|Produce|Create|Draft|Write|Develop|Reconcile|Analy[sz]e|Assess|Design|Compile|"
    "Update|Review|Identify|Model|Forecast|Summari[sz]e|Evaluate|Document|Map|Recommend|Audit|"
    "Calculate|Determine|Deliver|Construct|Establish|Define|Plan|Estimate|Consolidate|Validate|"
    "Classify|Propose|Outline|Set up|Quantify|Rank|Select"
)
FIELDS = ("domain", "occupation", "sector", "subdomain", "task_type", "tags")


def task_type(task_dir):
    exts = set()
    for f in glob.glob(
        os.path.join(task_dir, "solution", "files", "**", "*"), recursive=True
    ):
        if os.path.isfile(f):
            exts.add(os.path.splitext(f)[1].lower())
    kinds = []
    if exts & {".docx", ".md", ".pdf"}:
        kinds.append("memo / document synthesis")
    if exts & {".xlsx", ".xlsm", ".csv"}:
        kinds.append("spreadsheet analysis")
    if ".pptx" in exts:
        kinds.append("presentation")
    return " + ".join(kinds) if kinds else "business analysis deliverable"


def toml_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


done = skipped = 0
for tt in sorted(glob.glob(os.path.join(a.corpus_root, "SVC-PC-*", "task.toml"))):
    td = os.path.dirname(tt)
    tid = os.path.basename(td)
    src = open(tt, encoding="utf-8").read()
    if re.search(r"^\s*task_type\s*=", src, re.M):
        if not a.force:
            skipped += 1
            continue
        src = re.sub(r"^(" + "|".join(FIELDS) + r")\s*=.*\n", "", src, flags=re.M)
        src = re.sub(
            r"^\[metadata\]\s*$", "[metadata]\ntags = []", src, count=1, flags=re.M
        )
    inst_p = os.path.join(td, "instruction.md")
    if not os.path.exists(inst_p):
        print("no instruction.md:", tid)
        continue
    lines = [
        l.strip()
        for l in open(inst_p, encoding="utf-8", errors="replace").read().splitlines()
    ]
    text = " ".join(l for l in lines if l)
    header = lines[0].lstrip("# ").strip() if lines else ""
    role_line = next((l for l in lines if re.match(r"^\**\s*Role\s*:", l, re.I)), "")
    if role_line:
        occupation = re.sub(r"^\**\s*Role\s*:\s*\**", "", role_line, flags=re.I).strip(
            " *"
        )
    else:
        m = re.search(
            r"You are (?:the |a |an )?([^.:;]{3,90}?)(?:\.|:|;| who | and | at | for | tasked| asked| preparing| building)",
            text,
        )
        occupation = m.group(1).strip(" ,'") if m else "Business operator"
    hm = re.search(MIDDLE_DOT + r"\s*(.+?)\s+TASK WORKBOOK", header, re.I)
    if hm:
        domain = hm.group(1).strip().title()
        for bad, good in (
            ("Fp&A", "FP&A"),
            ("Hr", "HR"),
            ("It", "IT"),
            ("Cx", "CX"),
            ("Fp&a", "FP&A"),
        ):
            domain = domain.replace(bad, good)
    else:
        domain = (
            re.sub(TITLE_WORDS, "", occupation).replace("  ", " ").strip(" ,/&-'s")
            or occupation
        )
    sm = re.search(r"(?:^|\.\s+)((?:" + VERBS + r")\b[^.]{10,140})", text)
    if role_line:
        title = next(
            (
                l.lstrip("# ").strip()
                for l in lines
                if l and not re.match(r"^\**\s*Role\s*:", l, re.I)
            ),
            tid,
        )
    else:
        title = sm.group(1).strip() if sm else (header or tid)
    sector = "Consumer e-commerce"
    ttype = task_type(td)
    tags = sorted(
        {domain.lower(), sector.lower(), ttype.split(" / ")[0].split(" + ")[0].lower()}
    )
    block = (
        f"domain = {toml_str(domain)}\n"
        f"occupation = {toml_str(occupation)}\n"
        f"sector = {toml_str(sector)}\n"
        f"subdomain = {toml_str(title[:120])}\n"
        f"task_type = {toml_str(ttype)}\n"
        f"tags = [{', '.join(toml_str(t) for t in tags)}]\n"
    )
    if re.search(r"^\s*tags\s*=\s*\[\s*\]\s*$", src, re.M):
        new = re.sub(
            r"^\s*tags\s*=\s*\[\s*\]\s*$", block.rstrip("\n"), src, count=1, flags=re.M
        )
    elif re.search(r"^\[metadata\]\s*$", src, re.M):
        new = re.sub(
            r"^\[metadata\]\s*$",
            "[metadata]\n" + block.rstrip("\n"),
            src,
            count=1,
            flags=re.M,
        )
    else:
        new = src.rstrip("\n") + "\n\n[metadata]\n" + block
    new = re.sub(
        r"^# Only platform-recognized \[metadata\] fields emitted.*\n",
        "",
        new,
        flags=re.M,
    )
    if a.dry_run:
        print(
            f"{tid}: domain={domain!r} occupation={occupation!r} subdomain={title[:70]!r} task_type={ttype!r}"
        )
    else:
        os.makedirs(bak, exist_ok=True)
        shutil.copy(tt, os.path.join(bak, tid + ".task.toml"))
        open(tt, "w", encoding="utf-8").write(new)
    done += 1
print(
    f"{'would fill' if a.dry_run else 'filled'} {done} task.toml, skipped {skipped} already populated"
    + ("" if a.dry_run else f"; backups in {bak}")
)
