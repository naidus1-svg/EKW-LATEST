#!/usr/bin/env python3
"""pin_probe.py TASK [TASK ...] - step B: pin fragility, by metamorphic testing of the rubric.

A criterion whose Expected clause pins an exact value or layout can reject a compliant answer that differs only in representation (a rounding the instruction permits,
a unit scale, a number format, a synonym, the order of independent items). DataOS counts that as a false rejection (major at any weight). Adjudication (step A) sees only
what two GLM runs happened to write; this probes the space of valid alternatives directly, with one grading per task instead of one call per line:

  1. A weaker model (default GLM, --model glm-5.2 through the proxy) reads the instruction, the pinned criteria and the golden, and proposes REPRESENTATION-ONLY edits to the
     golden, each with the instruction sentence that permits it. Never a change of magnitude beyond a permitted rounding. At most one edit per criterion, distinct locations.
  2. The edits are applied with apply_plan.py's own ops (set_xlsx_cell, replace_docx_text) to a SCRATCH copy of the task. Nothing under the corpus is written.
  3. The real judge (judge_emulate.py deliverable, the rubric's own model) grades that variant. Baseline: probes/oracle.json (the untouched golden scores 1.0 on its own rubric).
     A criterion that passed on the golden and fails on the variant, and whose edit was aimed at it, is a candidate false rejection.
  4. A stronger model (default opus) checks each candidate: is the edit really equivalent under the instruction (quote it), and does the judge's failure reason show the criterion
     insisting on the representation? Only confirmed ones are reported.

Output: /root/qc/pinprobe/<TASK>/PINPROBE.json (+ PROMPT_*.txt, PLAN.json, VARIANT_*.json). Exit 0 always; a task that cannot be probed says why in its JSON.
Usage: python3 pin_probe.py [--model glm-5.2] [--verify-model opus] [--max-edits 40] [--lane /root/.claude-q] TASK ...
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

Q = "/root/qc"
TOOLS = f"{Q}/tools"
CORPUS = "/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready"
OUT_ROOT = f"{Q}/pinprobe"
sys.path.insert(0, TOOLS)

PLAN_PROMPT = """You are helping to test a grading rubric for robustness. Task {task}.

The task instruction (what a solver was asked to do):
-----
{instruction}
-----

Below are the rubric criteria whose Expected clause pins an exact value or layout (a digit appears in the Expected text), and then the golden deliverable (one valid answer),
dumped cell by cell (`Sheet!Cell: value=...`) or paragraph by paragraph (`[para N] text`).

PINNED CRITERIA:
{criteria}

GOLDEN FILES:
{golden}

Your job: for as many pinned criteria as you can, propose ONE edit to the golden that changes only its REPRESENTATION while leaving the answer correct under the instruction.
Allowed: number formatting (thousands separators, a $ or % sign, "1.2M" vs "1,200,000"), rounding to a precision the instruction permits, a unit scale the instruction permits,
a wording synonym, capitalisation of a label, the order of items the instruction does not order. NOT allowed: changing a value's magnitude beyond a permitted rounding,
removing a required element, adding an unsupported claim, or any edit that would make the answer wrong or inconsistent with another cell.
For each edit give the instruction sentence (verbatim) that makes the alternative acceptable. If the instruction does not permit any alternative for a criterion (it fixes the format
exactly), skip that criterion. At most one edit per criterion; the edits must be at distinct cells or paragraphs; at most {max_edits} in total.

Ops (exactly these):
- workbook cell:   {{"op": "set_xlsx_cell", "file": "solution/files/<name>.xlsx", "sheet": "<exact sheet>", "cell": "<A1>", "value": <number or string>}}
- docx paragraph:  {{"op": "replace_docx_text", "file": "solution/files/<name>.docx", "find": "<exact text, must occur exactly once>", "replace": "<new text>"}}
`sheet`, `cell` and `find` must be copied verbatim from the golden dump above.

Respond with EXACTLY ONE JSON object, no prose, no code fence:
{{"edits": [{{"criterion_id": "<name>", "op": "...", "file": "...", "sheet": "...", "cell": "...", "value": ..., "find": "...", "replace": "...",
"change": "one line: what representation changed", "instruction_quote": "verbatim sentence that permits it"}}], "skipped": "one line on criteria with no valid alternative"}}
"""

VERIFY_PROMPT = """You are checking a suspected FALSE REJECTION in a grading rubric. Task {task}.

Instruction:
-----
{instruction}
-----

Criterion {cid} (weight {weight}):
{criterion}

A weaker model edited ONE thing in the golden deliverable: {change}
It claims the instruction permits this, citing: "{quote}"
Before the edit the golden passed this criterion. After it, the real judge FAILED it, with this reasoning:
{verdict}

Decide:
- edit_equivalent: is the edited answer still a fully correct answer under the instruction (does the quoted sentence, or another sentence of the instruction, permit it)? yes|no
- criterion_rigid: does the judge's failure come from the criterion insisting on the original representation rather than from the edit making the answer wrong? yes|no
- false_rejection: yes only if BOTH are yes.
Respond with EXACTLY ONE JSON object: {{"edit_equivalent": "yes|no", "criterion_rigid": "yes|no", "false_rejection": "yes|no", "reasoning": "two sentences citing the instruction",
"fix_direction": "if false_rejection: the smallest change to the criterion text that accepts both representations; else empty"}}
"""


def glm_env() -> dict:
    env = dict(os.environ)
    tok = ""
    keys = "/root/.glm_keys"
    if os.path.exists(keys):
        for k in open(keys).read().split():
            if k and not k.startswith("#"):
                tok = k
                break
    if not tok:
        for line in open("/root/.glm_env").read().splitlines():
            m = re.match(r"\s*(?:export\s+)?ANTHROPIC_AUTH_TOKEN=(.*)", line)
            if m:
                tok = m.group(1).strip().strip("'\"")
    env["ANTHROPIC_BASE_URL"] = "http://34.41.10.8:4000"
    env["ANTHROPIC_AUTH_TOKEN"] = tok
    env["IS_SANDBOX"] = "1"
    return env


def call(prompt: str, out: Path, model: str, lane: str, timeout: int = 1500):
    pf = out.with_suffix(".prompt.txt")
    pf.write_text(prompt)
    env = (
        glm_env()
        if model.startswith("glm")
        else dict(os.environ, CLAUDE_CONFIG_DIR=lane)
    )
    if out.exists():
        out.unlink()
    subprocess.run(
        [
            sys.executable,
            f"{TOOLS}/llm_call.py",
            "--prompt-file",
            str(pf),
            "--model",
            model,
            "--timeout",
            str(timeout),
            "--out",
            str(out),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout + 300,
    )
    try:
        return json.loads(out.read_text())
    except Exception:  # noqa: BLE001
        return None


def pinned(task: str) -> list[dict]:
    import tomllib

    rows = []
    for jp in sorted(Path(f"{CORPUS}/{task}/tests").glob("*/judge.toml")):
        group = jp.parent.name
        for c in tomllib.load(open(jp, "rb")).get("criterion", []):
            desc = c.get("description", "") or ""
            m = re.search(r"Expected:(.*)", desc, re.S)
            if m and re.search(r"\d", m.group(1)):
                rows.append(
                    {
                        "id": str(c.get("name")),
                        "group": group,
                        "weight": c.get("weight"),
                        "text": desc,
                    }
                )
    return rows


def probe(task: str, model: str, vmodel: str, lane: str, max_edits: int) -> dict:
    task = task if task.startswith("SVC-PC-") else f"SVC-PC-{task}"
    d = Path(OUT_ROOT) / task
    d.mkdir(parents=True, exist_ok=True)
    res = {
        "task": task,
        "started": time.strftime("%FT%TZ", time.gmtime()),
        "model": model,
        "verify_model": vmodel,
    }
    crit = pinned(task)
    res["n_pinned"] = len(crit)
    if not crit:
        res["status"] = "no pinned criteria"
        return finish(d, res)
    oracle = Path(f"{Q}/stream-pipe/{task}/probes/oracle.json")
    try:
        ojs = json.load(open(oracle))
    except Exception:  # noqa: BLE001
        res["status"] = "no oracle probe"
        return finish(d, res)
    if float(ojs.get("total_reward") or 0) < 1.0:
        res["status"] = (
            f"golden does not score 1.0 (oracle {ojs.get('total_reward')}); fix that first"
        )
        return finish(d, res)
    from gather_files_text import render_file

    task_dir = Path(CORPUS) / task
    golden = ""
    for p in sorted((task_dir / "solution" / "files").glob("*")):
        if p.suffix.lower() in (".xlsx", ".docx"):
            golden += f"\n=== solution/files/{p.name} ===\n{render_file(p, 90_000)}\n"
    instr = (task_dir / "instruction.md").read_text(errors="replace")
    prompt = PLAN_PROMPT.format(
        task=task,
        instruction=instr[:12000],
        criteria="\n".join(
            f"- {c['id']} (group {c['group']}, weight {c['weight']}): {c['text'][:700]}"
            for c in crit
        ),
        golden=golden[:260_000],
        max_edits=max_edits,
    )
    plan = call(prompt, d / "PLAN.json", model, lane)
    if not plan or not plan.get("edits"):
        res["status"] = "the model proposed no edits"
        res["plan_skipped"] = (plan or {}).get("skipped")
        return finish(d, res)
    edits = plan["edits"][:max_edits]
    res["n_edits_proposed"] = len(edits)
    # scratch copy of the task; apply with apply_plan.py's own ops
    scratch = Path("/tmp/pinprobe") / task
    shutil.rmtree(scratch, ignore_errors=True)
    (scratch / "root").mkdir(parents=True)
    subprocess.run(
        [
            "rsync",
            "-a",
            "--exclude=environment",
            f"{task_dir}/",
            f"{scratch}/root/{task}/",
        ],
        check=True,
    )
    plan_json = {
        "task": task,
        "edits": [
            {
                k: v
                for k, v in e.items()
                if k in ("op", "file", "sheet", "cell", "value", "find", "replace")
            }
            | {"finding_id": e.get("criterion_id"), "reason": e.get("change", "")}
            for e in edits
        ],
    }
    (d / "APPLY_PLAN.json").write_text(json.dumps(plan_json, indent=2))
    fixlog = d / "APPLY.md"
    fixlog.write_text("")
    subprocess.run(
        [
            sys.executable,
            f"{TOOLS}/apply_plan.py",
            "--plan",
            str(d / "APPLY_PLAN.json"),
            "--task",
            task,
            "--corpus-root",
            f"{scratch}/root",
            "--fix-log",
            str(fixlog),
        ],
        capture_output=True,
        text=True,
    )
    lines = fixlog.read_text().splitlines()
    ok_idx = [i for i, l in enumerate(lines) if ": APPLIED" in l]
    res["n_edits_applied"] = len(ok_idx)
    if not ok_idx:
        res["status"] = "no edit applied"
        res["apply_log"] = lines[:8]
        return finish(d, res)
    applied = []
    for i, l in enumerate(lines):
        m = re.match(r"- \S+ edit (\d+) ", l)
        if m and ": APPLIED" in l:
            applied.append(edits[int(m.group(1))])
    # grade the variant with the real judge
    app = scratch / "root" / task / "solution" / "files"
    var = d / "VARIANT_reward.json"
    subprocess.run(
        [
            "timeout",
            "2400",
            sys.executable,
            f"{TOOLS}/judge_emulate.py",
            "deliverable",
            task,
            str(app),
            "--corpus-root",
            CORPUS,
            "--out",
            str(var),
        ],
        env=dict(os.environ, CLAUDE_CONFIG_DIR=lane),
        capture_output=True,
        text=True,
    )
    try:
        vj = json.load(open(var))
    except Exception:  # noqa: BLE001
        res["status"] = "variant grading failed"
        return finish(d, res)

    def rows(j):
        out = {}

        def walk(g):
            for c in g.get("criteria", []) or []:
                out[str(c.get("id") or c.get("name"))] = c
            for ch in g.get("children", []) or []:
                walk(ch)

        for g in j.get("groups", []):
            walk(g)
        return out

    base, var_rows = rows(ojs), rows(vj)
    if any(c.get("error") for c in var_rows.values()):
        res["status"] = "variant grading tainted by judge errors"
        return finish(d, res)
    target = {str(e.get("criterion_id")): e for e in applied}
    flips = [
        cid
        for cid, c in var_rows.items()
        if base.get(cid, {}).get("passed") and not c.get("passed")
    ]
    res["variant_total_reward"] = vj.get("total_reward")
    res["flipped"] = flips
    res["flipped_targeted"] = [c for c in flips if c in target]
    res["flipped_untargeted"] = [c for c in flips if c not in target]
    confirmed = []
    cmap = {c["id"]: c for c in crit}
    for cid in res["flipped_targeted"]:
        e, c, vr = target[cid], cmap.get(cid, {}), var_rows[cid]
        v = call(
            VERIFY_PROMPT.format(
                task=task,
                instruction=instr[:12000],
                cid=cid,
                weight=c.get("weight"),
                criterion=(c.get("text") or "")[:1500],
                change=e.get("change", ""),
                quote=e.get("instruction_quote", ""),
                verdict=(vr.get("verdict_text") or "")[:1500],
            ),
            d / f"VERIFY_{cid}.json",
            vmodel,
            lane,
            900,
        )
        item = {
            "criterion_id": cid,
            "weight": c.get("weight"),
            "change": e.get("change"),
            "instruction_quote": e.get("instruction_quote"),
            "edit": {
                k: e.get(k)
                for k in ("op", "file", "sheet", "cell", "value", "find", "replace")
            },
            "judge_verdict_on_variant": (vr.get("verdict_text") or "")[:800],
            "verification": v,
        }
        confirmed.append(item)
    res["candidates"] = confirmed
    res["confirmed_false_rejections"] = [
        x["criterion_id"]
        for x in confirmed
        if (x.get("verification") or {}).get("false_rejection") == "yes"
    ]
    res["status"] = "ok"
    return finish(d, res)


def finish(d: Path, res: dict) -> dict:
    res["finished"] = time.strftime("%FT%TZ", time.gmtime())
    (d / "PINPROBE.json").write_text(json.dumps(res, indent=2, default=str))
    print(
        f"{res['task']}: {res.get('status')} pinned={res.get('n_pinned')} proposed={res.get('n_edits_proposed')} applied={res.get('n_edits_applied')} flipped={res.get('flipped')} confirmed={res.get('confirmed_false_rejections')}",
        flush=True,
    )
    return res


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("tasks", nargs="+")
    ap.add_argument("--model", default="glm-5.2")
    ap.add_argument("--verify-model", default="opus")
    ap.add_argument("--max-edits", type=int, default=40)
    ap.add_argument("--lane", default="/root/.claude-q")
    a = ap.parse_args()
    for t in a.tasks:
        try:
            probe(t, a.model, a.verify_model, a.lane, a.max_edits)
        except Exception as exc:  # noqa: BLE001
            print(f"{t}: ERROR {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
