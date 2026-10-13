"""Deterministic, no-LLM reconciliation of checks A/B/C/D across every workflow this session
produced, plus a fresh live rescan for B and D. Replaces the earlier LLM-gather-agent approach
for these four checks (which undercounted real completed work because several gather agents
could only see a source's FLAGGED subset, not its full scanned population).

Priority for check C (structural audit): sources are listed oldest-to-newest below; a later
source's verdict for a given task_id overwrites an earlier one. This matches how the real work
happened - later sweeps rebuilt/re-audited tasks earlier sweeps had already touched.

Usage: python tools/svc_qc_reconcile_ground_truth.py
Writes: ekw/svc-qc-ground-truth-ABCD-2026-09-12.json
"""

import json
import re
import os

REPO = r"C:\Users\khiem.doan_turing\Documents\Projects\turing-context"
BUILT_ROOT = r"C:\ekwqc\repo\pipeline\data\svc_pc_qc\03_dataos_ready"
TASKS_DIR = "C:/Users/KHIEM~1.DOA/AppData/Local/Temp/claude/C--Users-khiem-doan-turing-Documents-Projects-turing-context/e54a4f5e-0d84-43d7-b71c-6c9bb512e00b/tasks"
JOURNAL_WQU = r"C:\Users\khiem.doan_turing\.claude\projects\C--Users-khiem-doan-turing-Documents-Projects-turing-context\e54a4f5e-0d84-43d7-b71c-6c9bb512e00b\subagents\workflows\wf_d8d17a31-c89\journal.jsonl"

ID_RE = re.compile(r"SVC-PC-\d+-\d+(?:-\d+)?")


def load_task_output(name):
    with open(f"{TASKS_DIR}/{name}.output", encoding="utf-8") as f:
        return json.load(f)["result"]


def first_id_token(s):
    m = ID_RE.search(s)
    return m.group(0) if m else None


# ---------- Check B: build existence, live directory listing ----------
built_ids = sorted(
    d
    for d in os.listdir(BUILT_ROOT)
    if os.path.isdir(os.path.join(BUILT_ROOT, d)) and d.startswith("SVC-PC-")
)
print(f"Check B: {len(built_ids)} tasks currently built")

# ---------- Check A: content audit, all 635, from the 22 batch files ----------
import glob

content_status = {}
for fp in sorted(glob.glob(os.path.join(REPO, "ekw", "svc-full-audit-batch-*.json"))):
    for rec in json.load(open(fp, encoding="utf-8")):
        content_status[rec["task_id"]] = rec["classification"]
print(f"Check A: {len(content_status)} tasks classified")

# ---------- Check D: mechanical filename check, fresh full rescan ----------
mech_path = os.path.join(
    REPO, "ekw", "svc-mechanical-filename-scan-FULL-2026-09-12.json"
)
mech_status = json.load(open(mech_path, encoding="utf-8"))
print(f"Check D: {len(mech_status)} tasks scanned fresh")

# ---------- Check C: structural audit, consolidated from every workflow, oldest to newest ----------
struct_status = {}  # task_id -> ("pass"|"fail", source_label)
dropped_non_ids = []  # (raw_entry, source) - annotated strings that weren't a bare id


def normalize_ids(items, source):
    """Some batch agents returned annotated strings ('SVC-PC-X (file.xlsx) - reason...')
    instead of bare ids, and a few described more than one id per entry. Extract every
    real id token from every entry rather than trusting the entry is already a bare id -
    this is the exact bug that produced 38 then 15 garbage pseudo-ids earlier in this
    script's own development."""
    out = []
    for item in items:
        found = ID_RE.findall(item)
        if not found:
            dropped_non_ids.append((item, source))
            continue
        out.extend(found)
    return out


def mark(ids, status, source):
    for tid in normalize_ids(ids, source):
        struct_status[tid] = (status, source)


# 1. w9umpn4h6 - 57-task rewardkit pool audit (earliest today)
r = load_task_output("w9umpn4h6")
for batch in r["auditResults"]:
    mark(batch.get("genuinely_clean", []), "pass", "w9umpn4h6")
    mark([d["task_id"] for d in batch.get("defective", [])], "fail", "w9umpn4h6")

# 2. wxqebuw8s - 35 hydration-pattern tasks from the original 165
r = load_task_output("wxqebuw8s")
hydration_35 = set(r["taskList"]["hydration_pattern_ids"])
still_defective_35 = {"SVC-PC-55-2-0", "SVC-PC-55-5-0", "SVC-PC-46-1-0"}
mark(hydration_35 - still_defective_35, "pass", "wxqebuw8s")
mark(still_defective_35, "fail", "wxqebuw8s")

# 3. wjng212ys - 76 hydration-pattern tasks from the 130-bad remainder
r = load_task_output("wjng212ys")
hydration_76 = set(r["taskList"]["hydration_pattern_ids"])
struct_clean_45 = set(r["contentCheck"]["also_content_clean"]) | set(
    r["contentCheck"]["needs_content_fix"]
)
mark(struct_clean_45, "pass", "wjng212ys")
mark(hydration_76 - struct_clean_45, "fail", "wjng212ys")

# 4. wv397lxqh - 5 Drive-recoverable tasks, all confirmed clean
r = load_task_output("wv397lxqh")
mark(r["repackageResult"]["added"], "pass", "wv397lxqh")

# 5. wq846p79f - SVC-PC-5-1-0 clean, SVC-PC-16-2-0 defective
mark(["SVC-PC-5-1-0"], "pass", "wq846p79f")
mark(["SVC-PC-16-2-0"], "fail", "wq846p79f")

# 6. w5x6g3kck - SVC-PC-16-3-0 defective (reclassified from an earlier "clean" claim)
mark(["SVC-PC-16-3-0"], "fail", "w5x6g3kck")

# 7. w8p10i8y9 - 4 confirmed clean, 5 SVC-36-family still defective at the time (36-5 later
#    superseded by wqu51ay4x below)
r = load_task_output("w8p10i8y9")
mark(r["verifyResult"]["confirmed_clean"], "pass", "w8p10i8y9")
mark(r["verifyResult"]["actually_still_defective"], "fail", "w8p10i8y9")

# 8. wqu51ay4x - corpus-wide placeholder sweep, 229 candidates rebuilt (supersedes anything
#    above for the same task_id, including correcting SVC-PC-36-5-0 to clean)
clean = json.load(
    open(
        os.path.join(REPO, "ekw", "_scratch_wqu_rebuild_detail.json"), encoding="utf-8"
    )
)
mark(clean["genuinely_clean"], "pass", "wqu51ay4x")
mark(clean["still_defective"], "fail", "wqu51ay4x")
mark(clean["rebuild_failed"], "fail", "wqu51ay4x")

# 9. wwgw0i13m - broad audit sweep, 471 never-audited tasks (LAST, most recent, broadest -
#    supersedes everything above for any overlapping task_id)
r = load_task_output("wwgw0i13m")
mark(r["auditResults"]["cleanIds"], "pass", "wwgw0i13m")
mark([d["task_id"] for d in r["auditResults"]["defective"]], "fail", "wwgw0i13m")

print(
    f"Check C: {len(struct_status)} distinct tasks with a structural verdict from some source"
)
pass_c = sum(1 for v in struct_status.values() if v[0] == "pass")
fail_c = sum(1 for v in struct_status.values() if v[0] == "fail")
print(f"  pass={pass_c} fail={fail_c}")

# ---------- Assemble the full 635-task ground truth ----------
all_ids = sorted(
    set(content_status) | set(built_ids) | set(struct_status) | set(mech_status)
)
print(f"Total distinct task_ids across all four checks: {len(all_ids)}")

out = {}
for tid in all_ids:
    a = content_status.get(tid)
    a_status = (
        "pass"
        if a == "clean"
        else ("fail" if a in ("fixable", "unreachable_content") else "not_run")
    )
    b_status = "pass" if tid in built_ids else "not_run"
    c = struct_status.get(tid)
    c_status, c_source = (c[0], c[1]) if c else ("not_run", None)
    d = mech_status.get(tid)
    if d is None:
        d_status = "not_run"
    elif d["status"] == "pass":
        d_status = "pass"
    elif d["status"] == "fail":
        d_status = "fail"
    else:
        d_status = (
            "not_run"  # no_instruction_file / no_tests_dir / no_judge_files_found
        )
    out[tid] = {
        "A": {"status": a_status, "raw": a},
        "B": {"status": b_status},
        "C": {"status": c_status, "source": c_source},
        "D": {"status": d_status, "detail": d},
    }

ready_abcd = [
    tid
    for tid, v in out.items()
    if v["A"]["status"] == "pass"
    and v["B"]["status"] == "pass"
    and v["C"]["status"] == "pass"
    and v["D"]["status"] == "pass"
]
print(f"\nREADY ON ALL OF A+B+C+D: {len(ready_abcd)}")

with open(
    os.path.join(REPO, "ekw", "svc-qc-ground-truth-ABCD-2026-09-12.json"),
    "w",
    encoding="utf-8",
) as f:
    json.dump({"tasks": out, "ready_abcd": sorted(ready_abcd)}, f, indent=2)
print("Wrote ekw/svc-qc-ground-truth-ABCD-2026-09-12.json")
