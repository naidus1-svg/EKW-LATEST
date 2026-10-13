#!/usr/bin/env python3
"""metadata_classify_glm.py - fill domain / occupation / subdomain in task.toml [metadata] using
GLM through the solver proxy, one short call per task, for tasks whose instruction has no Role line.
Vocabulary for domain is fixed (DataOS review 1.9: classify against a controlled vocabulary, do not
invent). occupation = the person doing the task (the addressee), free text but short. subdomain = one
short noun phrase naming the work. Keeps sector, task_type; rebuilds tags. Backs up every file.

Usage: python3 metadata_classify_glm.py [--only-generic] [--limit N] [--dry-run] [--workers 8]
"""

import argparse, concurrent.futures as cf, glob, json, os, re, shutil, time, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument(
    "--corpus-root", default="/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready"
)
ap.add_argument(
    "--only-generic",
    action="store_true",
    help="only tasks whose occupation is the fallback",
)
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--workers", type=int, default=8)
a = ap.parse_args()

BASE = "http://34.41.10.8:4000"
KEYS = [k.strip() for k in open("/root/.glm_keys") if k.strip()]
DOMAINS = [
    "FP&A",
    "Accounting",
    "Treasury and Cash",
    "Revenue Operations",
    "Operations and Fulfillment",
    "Supply Chain and Procurement",
    "Customer Service",
    "Marketing",
    "Sales",
    "People and HR",
    "IT and Security",
    "Legal and Compliance",
    "Risk Management",
    "Executive and Strategy",
    "Data and Analytics",
]
stamp = time.strftime("%Y%m%dT%H%MZ", time.gmtime())
bak = f"/root/backup/task-toml-metadata-glm-{stamp}"


def ask(i, instr):
    prompt = (
        "You classify one business task for a catalogue. Read the task instruction below and answer with ONE JSON object and nothing else, keys:\n"
        f"domain: exactly one value from this list: {json.dumps(DOMAINS)}\n"
        "occupation: the job title of the person who is asked to DO the task (the addressee, not the requester), 2 to 6 words, e.g. 'CTO', 'FP&A analyst', 'Controller', 'Head of Customer Service'\n"
        "subdomain: a 3 to 8 word noun phrase naming the specific work, e.g. 'FY2021 revenue and order source reconciliation'\n\n"
        "INSTRUCTION:\n" + instr[:6000]
    )
    body = json.dumps(
        {
            "model": "glm-5.2",
            "max_tokens": 1500,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()
    req = urllib.request.Request(
        BASE + "/v1/messages",
        data=body,
        headers={
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            "Authorization": "Bearer " + KEYS[i % len(KEYS)],
            "x-api-key": KEYS[i % len(KEYS)],
        },
    )
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                j = json.load(r)
            txt = "".join(b.get("text", "") for b in j.get("content", []))
            m = re.search(r"\{.*\}", txt, re.S)
            d = json.loads(m.group(0))
            if d.get("domain") not in DOMAINS:
                d["domain"] = next(
                    (
                        x
                        for x in DOMAINS
                        if x.lower() in str(d.get("domain", "")).lower()
                    ),
                    "Executive and Strategy",
                )
            return d
        except Exception as e:
            err = e
            time.sleep(5 + 8 * attempt)
    return {"error": str(err)}


def toml_str(s):
    return (
        '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'
    )


tasks = []
for tt in sorted(glob.glob(os.path.join(a.corpus_root, "SVC-PC-*", "task.toml"))):
    src = open(tt, encoding="utf-8").read()
    if a.only_generic and 'occupation = "Business operator"' not in src:
        continue
    tasks.append(tt)
if a.limit:
    tasks = tasks[: a.limit]
print(f"{len(tasks)} tasks to classify via {BASE} with {len(KEYS)} keys")


def work(item):
    i, tt = item
    td = os.path.dirname(tt)
    tid = os.path.basename(td)
    instr = open(
        os.path.join(td, "instruction.md"), encoding="utf-8", errors="replace"
    ).read()
    d = ask(i, instr)
    if "error" in d:
        return f"{tid}: ERROR {d['error'][:100]}"
    src = open(tt, encoding="utf-8").read()
    ttype = re.search(r'^task_type\s*=\s*"(.*)"', src, re.M)
    ttype = ttype.group(1) if ttype else "business analysis deliverable"
    tags = sorted(
        {
            d["domain"].lower(),
            "consumer e-commerce",
            ttype.split(" / ")[0].split(" + ")[0].lower(),
        }
    )
    new = src
    new = re.sub(
        r"^domain\s*=.*$", "domain = " + toml_str(d["domain"]), new, count=1, flags=re.M
    )
    new = re.sub(
        r"^occupation\s*=.*$",
        "occupation = " + toml_str(d["occupation"][:80]),
        new,
        count=1,
        flags=re.M,
    )
    new = re.sub(
        r"^subdomain\s*=.*$",
        "subdomain = " + toml_str(d["subdomain"][:120]),
        new,
        count=1,
        flags=re.M,
    )
    new = re.sub(
        r"^tags\s*=.*$",
        "tags = [" + ", ".join(toml_str(t) for t in tags) + "]",
        new,
        count=1,
        flags=re.M,
    )
    if not a.dry_run and new != src:
        os.makedirs(bak, exist_ok=True)
        shutil.copy(tt, os.path.join(bak, tid + ".task.toml"))
        open(tt, "w", encoding="utf-8").write(new)
    return f"{tid}: {d['domain']} | {d['occupation']} | {d['subdomain']}"


with cf.ThreadPoolExecutor(a.workers) as ex:
    for line in ex.map(work, enumerate(tasks)):
        print(line)
print("done" + ("" if a.dry_run else f"; backups in {bak}"))
