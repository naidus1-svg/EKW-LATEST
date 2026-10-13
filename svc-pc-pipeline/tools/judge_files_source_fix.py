#!/usr/bin/env python3
"""judge_files_source_fix.py - G1 "source-blind" fix (fix-task-from-review Step 4, canon check 1.4):
a criterion that grades fidelity to a named source file is undecidable when the judge group's
files= list does not include that source. For every tests/deliverables*/judge.toml: find source
filenames from environment/initial_workspace that are named in that group's criterion text and
missing from files=, and add them as /app/<name>, skipping files over --max-bytes (judge context
cliff; the big workbooks need a judge_inputs extract, which is left to a human and listed).

Deterministic, idempotent, backs up every judge.toml it edits. --dry-run prints the plan.
"""

import argparse, glob, os, re, shutil, time

ap = argparse.ArgumentParser()
ap.add_argument(
    "--corpus-root", default="/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready"
)
ap.add_argument("--max-bytes", type=int, default=1_000_000)
ap.add_argument("--dry-run", action="store_true")
a = ap.parse_args()
stamp = time.strftime("%Y%m%dT%H%MZ", time.gmtime())
bak = f"/root/backup/judge-toml-sources-{stamp}"
edited = groups = added_total = 0
skipped_big = []
for td in sorted(glob.glob(os.path.join(a.corpus_root, "SVC-PC-*"))):
    tid = os.path.basename(td)
    ws = os.path.join(td, "environment", "initial_workspace")
    if not os.path.isdir(ws):
        continue
    sources = {
        f: os.path.getsize(os.path.join(ws, f))
        for f in os.listdir(ws)
        if os.path.isfile(os.path.join(ws, f))
    }
    for jt in sorted(
        glob.glob(os.path.join(td, "tests", "deliverables*", "judge.toml"))
    ):
        s = open(jt, encoding="utf-8").read()
        m = re.search(r"^files\s*=\s*\[(.*?)\]", s, re.M | re.S)
        if not m:
            continue
        groups += 1
        listed = set(re.findall(r'"([^"]+)"', m.group(1)))
        listed_names = {os.path.basename(x) for x in listed}
        crit_text = s[m.end() :]
        need = []
        for name, size in sources.items():
            if name in listed_names:
                continue
            if re.search(re.escape(name), crit_text) or re.search(
                re.escape(os.path.splitext(name)[0]), crit_text
            ):
                if size > a.max_bytes:
                    skipped_big.append(
                        (tid, os.path.basename(os.path.dirname(jt)), name, size)
                    )
                    continue
                need.append(name)
        if not need:
            continue
        new_list = list(listed) + [f"/app/{n}" for n in sorted(need)]
        new_files = "files = [" + ", ".join(f'"{x}"' for x in new_list) + "]"
        s2 = s[: m.start()] + new_files + s[m.end() :]
        if a.dry_run:
            print(
                f"{tid}/{os.path.basename(os.path.dirname(jt))}: +{len(need)} {sorted(need)}"
            )
        else:
            os.makedirs(os.path.join(bak, tid), exist_ok=True)
            shutil.copy(
                jt,
                os.path.join(
                    bak, tid, os.path.basename(os.path.dirname(jt)) + ".judge.toml"
                ),
            )
            open(jt, "w", encoding="utf-8").write(s2)
        edited += 1
        added_total += len(need)
print(
    f"{'would edit' if a.dry_run else 'edited'} {edited} of {groups} judge groups, adding {added_total} source files"
    + ("" if a.dry_run else f"; backups in {bak}")
)
if skipped_big:
    print(
        f"skipped {len(skipped_big)} sources over {a.max_bytes} bytes (need a judge_inputs extract):"
    )
    for row in skipped_big[:15]:
        print("   ", *row)
