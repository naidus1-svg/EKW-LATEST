#!/usr/bin/env python3
"""task_ledger.py - one row per SVC-PC task: how far from a submittable zip, and why.
Reads stream-pipe/<task>/{STATE,CR.json,PARKED.md,probes/oracle.json,checks/checkfix_round*.json,pipeline.log},
runs/<task>/glm-*/claude_exit_code.txt, out/pipe. Writes /root/qc/_prompts/task_ledger.csv and prints buckets.
"""

import csv, glob, json, os, re, subprocess

CORPUS = "/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready"
PIPE = "/root/qc/stream-pipe"
DETERMINISTIC_BLOCKERS = {
    "environment_input",
    "answer_key_rubric_leak",
    "answer_key_leakage",
    "answer_key_content_leak",
    "weight_application",
    "rubric_schema",
    "deliverable_filename",
    "deliverable_integrity",
    "verifier_executability",
    "metadata_leak",
    "formula_health",
    "formula_health_extraction_loss",
    "extraction_groundedness",
    "judge_file_size_cliff",
}
running = set(
    subprocess.run(
        "pgrep -fa 'bash /root/qc/tools/gate_task.sh' | awk '{print $NF}'",
        shell=True,
        capture_output=True,
        text=True,
    ).stdout.split()
)
zipped = {os.path.basename(z)[:-4] for z in glob.glob("/root/qc/out/pipe/*.zip")}
held = {os.path.basename(z)[:-4] for z in glob.glob("/root/qc/out/pipe/_hold/*.zip")}


def jload(p):
    try:
        return json.load(open(p))
    except Exception:
        return None


rows = []
for td in sorted(glob.glob(f"{CORPUS}/SVC-PC-*")):
    t = os.path.basename(td)
    d = f"{PIPE}/{t}"
    r = {"task": t}
    # GLM solver runs
    oks = 0
    runs = 0
    for rd in glob.glob(f"/root/qc/runs/{t}/glm-*"):
        runs += 1
        p = f"{rd}/claude_exit_code.txt"
        if os.path.exists(p) and open(p).read().strip() == "0":
            oks += 1
    r["glm_ok"] = f"{oks}/2"
    if not os.path.isdir(d):
        r.update(
            stage="never started",
            verdict="",
            majors="",
            minors="",
            oracle="",
            blockers="",
            park="",
            bucket="",
        )
        rows.append(r)
        continue
    state = (
        set(open(f"{d}/STATE").read().split())
        if os.path.exists(f"{d}/STATE")
        else set()
    )
    cr = jload(f"{d}/CR.json") or {}
    real = "overall_verdict" in cr
    r["verdict"] = (
        cr.get("overall_verdict", "") if real else ("old-reviewer" if cr else "")
    )
    r["majors"] = (
        cr.get("major_count", "")
        if real
        else (
            sum(1 for x in cr.get("findings", []) if x.get("severity") == "major")
            if cr
            else ""
        )
    )
    r["minors"] = cr.get("minor_count", "") if real else ""
    orc = jload(f"{d}/probes/oracle.json") or {}
    r["oracle"] = orc.get("total_reward", "")
    cf = sorted(glob.glob(f"{d}/checks/checkfix_round*.json"))
    blockers = []
    if cf:
        j = jload(cf[-1]) or {}
        blockers = [
            f"{b['check']}={b['verdict']}"
            for b in j.get("blocked", [])
            if b["check"] in DETERMINISTIC_BLOCKERS
            or b["verdict"] == "fail"
            and b["check"] in DETERMINISTIC_BLOCKERS
        ]
    r["blockers"] = " ".join(blockers)
    park = ""
    if os.path.exists(f"{d}/PARKED.md"):
        park = open(f"{d}/PARKED.md").read().strip().split("PARKED: ")[-1][:70]
    r["park"] = park
    if t in zipped:
        stage = "ZIPPED (verified)"
    elif t in held:
        stage = "zipped pre-guard (held)"
    elif "DONE" in state:
        stage = "done, no zip"
    elif park:
        stage = "parked"
    elif t in running:
        last = ""
        try:
            for line in open(f"{d}/pipeline.log", errors="replace"):
                if line.startswith("["):
                    last = line
        except Exception:
            pass
        m = re.search(r"step ([0-9.]+)", last)
        stage = f"running step {m.group(1)}" if m else "running"
    else:
        stage = "queued/idle"
    r["stage"] = stage
    # bucket: distance to a submittable zip
    if t in zipped:
        b = "A. zip verified"
    elif (
        real
        and r["majors"] == 0
        and (r["oracle"] in ("", None) or float(r["oracle"]) >= 1.0)
        and not blockers
    ):
        b = "B. passes review; probes/zip pending"
    elif real and r["majors"] == 0:
        b = "C. passes review; oracle<1 or deterministic cell to fix"
    elif real and r["majors"] > 0:
        b = "D. real review rejects (majors) - fix round needed"
    elif cr:
        b = "E. only old-reviewer result - needs one real review"
    else:
        b = "F. no review yet"
    r["bucket"] = b
    rows.append(r)

out = "/root/qc/_prompts/task_ledger.csv"
with open(out, "w", newline="") as f:
    w = csv.DictWriter(
        f,
        fieldnames=[
            "task",
            "bucket",
            "stage",
            "verdict",
            "majors",
            "minors",
            "oracle",
            "glm_ok",
            "blockers",
            "park",
        ],
    )
    w.writeheader()
    w.writerows(rows)
from collections import Counter

print("BUCKETS (distance to a submittable zip):")
for k, v in sorted(Counter(r["bucket"] for r in rows).items()):
    print(f"  {v:4d}  {k}")
print("\nSTAGE:")
for k, v in Counter(r["stage"] for r in rows).most_common():
    print(f"  {v:4d}  {k}")
print("\nGLM solver runs:", Counter(r["glm_ok"] for r in rows))
print(
    "oracle: 1.0 =",
    sum(1 for r in rows if r["oracle"] == 1.0),
    " <1.0 =",
    sum(1 for r in rows if r["oracle"] not in ("", None) and float(r["oracle"]) < 1.0),
    " not run =",
    sum(1 for r in rows if r["oracle"] in ("", None)),
)
real = [r for r in rows if r["verdict"] not in ("", "old-reviewer")]
print(
    "real-prompt verdicts:",
    len(real),
    Counter(r["verdict"] for r in real),
    " majors dist:",
    Counter(r["majors"] for r in real),
)
print(
    "deterministic blockers seen:",
    Counter(b.split("=")[0] for r in rows for b in r["blockers"].split() if b),
)
print(
    "park reasons:", Counter(r["park"][:40] for r in rows if r["park"]).most_common(6)
)
print("csv:", out)
