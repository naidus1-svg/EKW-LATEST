#!/usr/bin/env python3
"""Convert a RAW-format EKW task (the new GTM-/HLT-/MKT-/FIN-/SCO-/LGL-/PHR-/ENG- tasks) into the
harbor-rewardkit package DataOS grades, the same shape SVC-PC ships from 03_dataos_ready/.

Raw format (as delivered on Drive, one folder per task, surveyed 2026-09-24 on GTM-142, FIN-102,
HLT-101, MKT-104, SCO-120):

    <TASK-ID>/
      prompt.txt              the solver prompt; deliverables go to /workspace/output/
      verifier.json           {task_id, config:{models:["openai/gpt-5.4"], temperature, reasoning_effort},
                               verifiers:[{name:"v1", metadata:{weight, tag, importance, grading_role,
                               how_justification, why_justification},
                               source:{type:"file", file:{type, command:"extract_text",
                               arguments:{path:"output/<deliverable>"}} | file:[{...}, {...}]},
                               assertion:{type:"rubric", expected:true, rubric:{prompt:"PASS only if ..."}}}]}
                               weights sum to 1.0; can carry a trailing ``` fence (GTM-142 does)
      source_documents/       solver inputs (can be absent or empty; see the collision rule below)
      expert_solution/        the golden deliverables plus Reasoning.docx, sometimes with Drive
                               duplicate suffixes ("Reasoning(1).docx") and names that differ from
                               the path the verifiers read (GTM-142), sometimes extra files
                               (HLT-101's qc_golden_review.md)

Output (one package per task, top-level dir = task id, same as SVC-PC):

    <out-root>/<TASK-ID>/
      task.toml                         schema 1.1, name "ekw/<task-id>", ANTHROPIC_API_KEY env
      instruction.md                    prompt.txt with /workspace/... repointed to /app/, then the
                                        "## Graded deliverable filenames" section and, when an .xlsx
                                        is graded, the stored-value sentence (apply_k_sentence.py)
      environment/Dockerfile            the SVC colab-cli base (to_rewardkit.DOCKERFILE)
      environment/initial_workspace/    source_documents/ (omitted, with no COPY, when there are none)
      solution/solve.sh
      solution/files/<deliverable>      ONLY the files a verifier reads, renamed to the graded name
      solution/reasoning.docx           the expert Reasoning doc, outside files/
      tests/test.sh, tests/task_prompt.txt, tests/reward.toml
      tests/deliverables_NN[_pK]/judge.toml
      tests/checks_deterministic/*.py   copied from <raw>/checks_deterministic/ when that folder exists

Grouping: criteria are grouped by the exact file set their verifier reads, so each judge dir's
files= list holds only what its criteria grade (one group per deliverable, plus one per multi-file
set). A group over 15 criteria is split into balanced deliverables_NN, deliverables_NN_p2, ... dirs
(the DataOS grammar-too-large limit; same naming as svc_split_grammar_dirs.py). Each dir's
[judge] weight is the sum of its criteria weights, and reward.toml carries the same numbers as a
weights table. Both are needed: DataOS loads the package with rewardkit 0.1.7, which weights dirs
by [judge] weight and ignores the table, but test.sh pip-installs the latest rewardkit (0.2.1 on
2026-09-24) at grade time, which weights dirs by the table and defaults each to 1.0 without it.
Run with a mocked judge failing one 0.07 criterion in a 0.13 dir (GTM-142): no table gave 0.93 on
0.1.7 and 0.8205 on 0.2.1; with the table both gave 0.93. Inside a dir weighted_mean normalises
by the criteria sum, so every criterion keeps its exact global weight from verifier.json.

Judge: anthropic/claude-sonnet-4-6, NOT the raw file's openai/gpt-5.4. DataOS provisions only
ANTHROPIC_API_KEY for rewardkit tasks (to_rewardkit.py pick_judge, task_74's missing-OPENAI_API_KEY
failure), and every SVC-PC package DataOS grades today ships this exact judge string.

Criterion names are "<verifier name>-<tag>" (v7-execution-sequence), so any DataOS or check finding
maps straight back to the verifier.json entry the author edits.

Collision rule: a source_documents/ file with the same name as a graded deliverable would land at
/app/<deliverable> before the solver starts, i.e. a pre-filled answer at the graded path. GTM-142
ships exactly this (a complete alternative answer under all three deliverable names, while its
prompt asks the solver to invent everything). The converter REFUSES such a task unless
--drop-colliding-sources is passed, which leaves those files out of the workspace.

Usage:
  python svc-pc-pipeline/tools/ekw_raw_to_rewardkit.py <raw_task_dir> [<raw_task_dir> ...]
      [--out-root DIR] [--drop-colliding-sources] [--max-criteria 15]
Exit 0 all converted and self-validated, 1 any task refused or failed validation, 2 usage.
"""

import argparse
import json
import math
import os
import re
import shutil
import sys
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "pipeline", "tools"))
with warnings.catch_warnings():
    warnings.simplefilter("ignore", SyntaxWarning)
    import to_rewardkit as trk  # noqa: E402

JUDGE = trk.pick_judge(None)  # anthropic/claude-sonnet-4-6, the SVC-PC judge
MAX_CRIT = 15
NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
DUP_SUFFIX = re.compile(r"\s*\(\d+\)$")  # Drive's "Reasoning(1).docx" duplicate marker
K_SENTENCE = (
    "The grader reads each cell's stored value, not its formula. Formula cells "
    "must carry their computed values when the file is read programmatically "
    "(write the value alongside the formula, or recalculate before saving)."
)
EXTRA_PATHS = (  # raw-prompt workspace conventions to_rewardkit does not cover
    "/workspace/source_documents/",
    "/workspace/source_documents",
    "/workspace/inputs/",
    "/workspace/input/",
)


class Refuse(Exception):
    pass


def norm_name(fn):
    stem, ext = os.path.splitext(fn)
    return (DUP_SUFFIX.sub("", stem) + ext).lower()


def is_reasoning(fn):
    return norm_name(fn).startswith("reasoning")


def rewrite_paths(text):
    for p in EXTRA_PATHS:
        text = text.replace(p, "/app/")
    text = trk._rewrite_instruction_paths(text)
    return text.replace("/workspace/", "/app/")


def load_verifier(path):
    raw = open(path, encoding="utf-8-sig").read().strip()
    raw = re.sub(r"^```\w*\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def verifier_files(x):
    """Deliverable basenames one verifier reads, in source order."""
    srcs = x.get("source") or {}
    srcs = srcs if isinstance(srcs, list) else [srcs]
    out = []
    for s in srcs:
        f = s.get("file") or {}
        for spec in f if isinstance(f, list) else [f]:
            b = os.path.basename(((spec or {}).get("arguments") or {}).get("path", ""))
            if b and b not in out:
                out.append(b)
    return out


def tokens(fn):
    stem = os.path.splitext(norm_name(fn))[0]
    return {t for t in re.split(r"[^a-z0-9]+", stem) if t and t not in trk._STOP}


def map_expert(deliverables, expert_dir):
    """deliverable name -> expert file path. Exact (dup-suffix-insensitive) name first, then the only
    unclaimed same-extension file, then the unique best token overlap. Refuses on ambiguity.
    """
    files = sorted(
        f for f in os.listdir(expert_dir) if os.path.isfile(os.path.join(expert_dir, f))
    )
    cands = [f for f in files if not is_reasoning(f)]
    mapping, how = {}, {}
    for d in deliverables:
        hit = [f for f in cands if norm_name(f) == d.lower()]
        if hit:
            mapping[d], how[d] = hit[0], "exact"
    for d in deliverables:
        if d in mapping:
            continue
        ext = os.path.splitext(d)[1].lower()
        pool = [
            f
            for f in cands
            if f not in mapping.values() and os.path.splitext(f)[1].lower() == ext
        ]
        if len(pool) == 1:
            mapping[d], how[d] = pool[0], "only unclaimed %s" % ext
            continue
        scored = sorted(
            (
                (len(tokens(d) & tokens(f)) / len(tokens(d) | tokens(f) or {1}), f)
                for f in pool
            ),
            reverse=True,
        )
        if (
            scored
            and scored[0][0] > 0
            and (len(scored) == 1 or scored[0][0] > scored[1][0])
        ):
            mapping[d], how[d] = scored[0][1], "best name match of %d %s" % (
                len(pool),
                ext,
            )
        else:
            raise Refuse(
                "cannot tell which expert_solution file is graded deliverable %s (candidates: %s)"
                % (d, pool or "none")
            )
    unused = [f for f in cands if f not in mapping.values()]
    reasoning = [f for f in files if is_reasoning(f)]
    return mapping, how, unused, reasoning


def balanced(items, maxsize):
    k = max(1, math.ceil(len(items) / maxsize))
    base, extra = divmod(len(items), k)
    out, i = [], 0
    for g in range(k):
        n = base + (1 if g < extra else 0)
        out.append(items[i : i + n])
        i += n
    return out


def convert(src, out_root, drop_colliding=False, max_crit=MAX_CRIT, fix_formulas=True):
    src = os.path.abspath(src)
    for need in ("prompt.txt", "verifier.json"):
        if not os.path.isfile(os.path.join(src, need)):
            raise Refuse("missing %s" % need)
    expert_dir = os.path.join(src, "expert_solution")
    if not os.path.isdir(expert_dir) or not os.listdir(expert_dir):
        raise Refuse("expert_solution/ missing or empty: no golden to ship")

    v = load_verifier(os.path.join(src, "verifier.json"))
    task_id = str(v.get("task_id") or os.path.basename(src)).strip()
    if not re.match(r"^[A-Za-z0-9._-]+$", task_id):
        raise Refuse("task_id %r is not a safe directory name" % task_id)
    vs = v.get("verifiers") or []
    if not vs:
        raise Refuse("verifier.json has no verifiers")

    crits, deliverables = [], []
    for x in vs:
        a = x.get("assertion") or {}
        prompt = ((a.get("rubric") or {}).get("prompt") or "").strip()
        if a.get("type") != "rubric" or not prompt:
            raise Refuse(
                "%s: assertion is %r with no rubric prompt; this converter handles rubric verifiers only"
                % (x.get("name"), a.get("type"))
            )
        if a.get("expected") is not True:
            raise Refuse(
                "%s: assertion.expected is %r, not true"
                % (x.get("name"), a.get("expected"))
            )
        files = verifier_files(x)
        if not files:
            raise Refuse("%s: no source file path" % x.get("name"))
        m = x.get("metadata") or {}
        if "weight" not in m:
            raise Refuse("%s: no metadata.weight" % x.get("name"))
        name = ("%s-%s" % (trk.kebab(x.get("name")), trk.kebab(m.get("tag"))))[
            :64
        ].strip("-")
        crits.append(
            {
                "name": name,
                "description": rewrite_paths(prompt),
                "weight": float(m["weight"]),
                "files": tuple(files),
            }
        )
        for f in files:
            if f not in deliverables:
                deliverables.append(f)

    names = [c["name"] for c in crits]
    bad = [n for n in names if not NAME_RE.match(n)]
    dups = sorted({n for n in names if names.count(n) > 1})
    if bad or dups:
        raise Refuse("criterion names invalid %s or duplicated %s" % (bad, dups))
    wsum = sum(c["weight"] for c in crits)
    if abs(wsum - 1.0) > 0.01 or any(c["weight"] <= 0 for c in crits):
        raise Refuse(
            "criterion weights sum to %.4f (want 1.0) or include a non-positive weight"
            % wsum
        )

    mapping, how, unused, reasoning = map_expert(deliverables, expert_dir)

    src_docs = os.path.join(src, "source_documents")
    inputs = (
        sorted(
            f
            for f in os.listdir(src_docs)
            if os.path.isfile(os.path.join(src_docs, f)) and f != ".DS_Store"
        )
        if os.path.isdir(src_docs)
        else []
    )
    dl_lower = {d.lower() for d in deliverables}
    colliding = [f for f in inputs if norm_name(f) in dl_lower]
    if colliding and not drop_colliding:
        raise Refuse(
            "source_documents/ holds %s, the same name(s) as graded deliverables. Shipped, they sit at "
            "/app/<deliverable> before the solver starts (a pre-filled answer at the graded path). "
            "Check the files; if they are not genuine inputs the prompt tells the solver to edit, re-run "
            "with --drop-colliding-sources." % colliding
        )
    inputs = [f for f in inputs if f not in colliding]

    pkg = os.path.join(os.path.abspath(out_root), task_id)
    if os.path.exists(pkg):
        shutil.rmtree(pkg)
    os.makedirs(pkg)

    # task.toml
    prefix = task_id.split("-")[0].upper()
    with open(os.path.join(pkg, "task.toml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(
            trk.TASK_TOML.format(
                name="ekw/%s" % trk.kebab(task_id),
                category="EKW",
                tags=json.dumps([prefix]),
                env=trk.JUDGE_ENV,
                agent_to=14400.0,
                verifier_to=3600.0,
                provenance="# source: raw EKW task %s (prompt.txt + verifier.json), ekw_raw_to_rewardkit.py"
                % task_id,
            )
        )

    # environment/
    env = os.path.join(pkg, "environment")
    os.makedirs(env)
    dockerfile = trk.DOCKERFILE
    if inputs:
        iw = os.path.join(env, "initial_workspace")
        os.makedirs(iw)
        for fn in inputs:
            shutil.copy2(os.path.join(src_docs, fn), os.path.join(iw, fn))
    else:
        # No inputs: an empty initial_workspace/ does not survive the zip and breaks the COPY
        # (to_rewardkit.py, SVC-PC-2-1-0/2-2-0), so drop the COPY instead of shipping a stub file.
        dockerfile = dockerfile.replace("COPY initial_workspace/ /app/\n", "")
    with open(
        os.path.join(env, "Dockerfile"), "w", encoding="utf-8", newline="\n"
    ) as f:
        f.write(dockerfile)

    # solution/
    sol = os.path.join(pkg, "solution")
    sol_files = os.path.join(sol, "files")
    os.makedirs(sol_files)
    warn = []
    renamed = {}
    for i, d in enumerate(deliverables):
        dest = os.path.join(sol_files, d)
        shutil.copy2(os.path.join(expert_dir, mapping[d]), dest)
        ext = os.path.splitext(d)[1].lower()
        if ext == ".xlsm":
            dest = trk._convert_xlsm_to_xlsx(dest)
            renamed[d] = os.path.basename(dest)
        elif ext not in trk._JUDGE_DOCUMENT_EXTENSIONS:
            warn.append("%s: %s is not in rewardkit's judge-readable set" % (d, ext))
        if os.path.getsize(dest) > trk._JUDGE_MAX_FILE_SIZE and dest.lower().endswith(
            ".docx"
        ):
            trk._strip_embedded_fonts(dest)
        if os.path.getsize(dest) > trk._JUDGE_MAX_FILE_SIZE:
            warn.append(
                "%s: %.2f MB, over rewardkit's 1 MB judge-attachment cutoff (the judge skips it)"
                % (d, os.path.getsize(dest) / 1048576.0)
            )
    deliverables = [renamed.get(d, d) for d in deliverables]
    for c in crits:
        c["files"] = tuple(renamed.get(f, f) for f in c["files"])
    with open(os.path.join(sol, "solve.sh"), "w", encoding="utf-8", newline="\n") as f:
        f.write(trk.SOLVE_SH)
    if reasoning:
        shutil.copy2(
            os.path.join(expert_dir, reasoning[0]), os.path.join(sol, "reasoning.docx")
        )
    else:
        warn.append("no Reasoning.docx in expert_solution/")

    # instruction.md + tests/task_prompt.txt
    instr = rewrite_paths(
        open(os.path.join(src, "prompt.txt"), encoding="utf-8-sig").read()
    )
    instr = (
        instr.replace("\r\n", "\n").rstrip()
        + "\n\n\n## Graded deliverable filenames\n\n"
    )
    instr += "Submit the graded deliverables using these exact filenames (and paths where shown):\n\n"
    instr += "".join("- `%s`\n" % d for d in deliverables)
    if any(d.lower().endswith(".xlsx") for d in deliverables):
        instr += "\n" + K_SENTENCE + "\n"
    with open(
        os.path.join(pkg, "instruction.md"), "w", encoding="utf-8", newline="\n"
    ) as f:
        f.write(instr)

    tests = os.path.join(pkg, "tests")
    os.makedirs(tests)
    import shlex

    with open(os.path.join(tests, "test.sh"), "w", encoding="utf-8", newline="\n") as f:
        f.write(
            trk.TEST_SH.replace("__DELIVERABLE_NAMES_PY__", json.dumps(list(deliverables))).replace(
                "__DELIVERABLE_NAMES__", " ".join(shlex.quote(d) for d in deliverables)
            )
        )
    with open(
        os.path.join(tests, "task_prompt.txt"), "w", encoding="utf-8", newline="\n"
    ) as f:
        f.write(instr)
    # judge dirs: one group per file set (first-seen order), split balanced at max_crit
    groups = {}
    for c in crits:
        groups.setdefault(c["files"], []).append(c)
    dirs = []
    for gi, (files, members) in enumerate(groups.items(), 1):
        for pi, chunk in enumerate(balanced(members, max_crit), 1):
            dname = "deliverables_%02d" % gi + ("" if pi == 1 else "_p%d" % pi)
            dirs.append((dname, files, chunk))
    for dname, files, chunk in dirs:
        d = os.path.join(tests, dname)
        os.makedirs(d)
        cw = round(sum(c["weight"] for c in chunk), 6)
        lines = [
            "[judge]",
            'judge = "%s"' % JUDGE,
            "files = [%s]" % ", ".join('"/app/%s"' % fn for fn in files),
            "weight = %s" % cw,
        ]
        if getattr(trk, "JUDGE_TIMEOUT_SEC", None):  # to_rewardkit's per-judge timeout; older converters have none
            lines.append("timeout = %d" % trk.JUDGE_TIMEOUT_SEC)
        lines.append("")
        for c in chunk:
            lines += [
                "[[criterion]]",
                'name = "%s"' % c["name"],
                "description = " + trk.toml_lit(c["description"]),
                'type = "binary"',
                "weight = %s" % c["weight"],
                "",
            ]
        lines += ["[scoring]", 'aggregation = "weighted_mean"', ""]
        with open(
            os.path.join(d, "judge.toml"), "w", encoding="utf-8", newline="\n"
        ) as f:
            f.write("\n".join(lines))
    # Deterministic code checks authored beside the rubric (<raw>/checks_deterministic/*.py) ship as
    # tests/checks_deterministic/. rewardkit scores that folder as one more programmatic dimension at weight 1.0,
    # so the live split is judges 50% / deterministic checks 50%. It stays out of the weights table below on purpose.
    det_src = os.path.join(src, "checks_deterministic")
    det_files = (
        sorted(
            f
            for f in os.listdir(det_src)
            if f.endswith(".py") and os.path.isfile(os.path.join(det_src, f))
        )
        if os.path.isdir(det_src)
        else []
    )
    if det_files:
        det_dst = os.path.join(tests, "checks_deterministic")
        os.makedirs(det_dst)
        for f in det_files:
            shutil.copy2(os.path.join(det_src, f), os.path.join(det_dst, f))
    reward_note = (
        "# tests/checks_deterministic/ is a programmatic dimension: rewardkit gives it weight 1.0 beside the judge\n"
        "# dimensions below (which sum to 1.0), so the live split is judges 50% / deterministic checks 50%. It is\n"
        "# absent from this table on purpose: rewardkit 0.1.7 ignores the table, and 0.2.x gives a dimension the\n"
        "# table does not list its own weight.\n"
        if det_files
        else ""
    )
    table = ", ".join(
        '"%s" = %s' % (dn, round(sum(c["weight"] for c in ch), 6)) for dn, _, ch in dirs
    )
    with open(
        os.path.join(tests, "reward.toml"), "w", encoding="utf-8", newline="\n"
    ) as f:
        f.write(
            reward_note
            + '[[reward]]\nname = "reward"\naggregation = "weighted_mean"\n'
            + "weights = {%s}\n" % table
        )

    formula_fix = (
        fix_formula_cache(pkg) if fix_formulas else "skipped (--no-formula-fix)"
    )
    problems = self_validate(pkg, deliverables, crits, dirs, max_crit)
    return {
        "formula_fix": formula_fix,
        "task": task_id,
        "pkg": pkg,
        "judge": JUDGE,
        "source_judge": (v.get("config") or {}).get("models"),
        "criteria": len(crits),
        "wsum": round(wsum, 6),
        "dirs": [
            (dn, list(fs), len(ch), round(sum(c["weight"] for c in ch), 6))
            for dn, fs, ch in dirs
        ],
        "mapping": {
            d: (mapping[k], how[k])
            for k, d in zip(mapping, [renamed.get(k, k) for k in mapping])
        },
        "not_shipped": unused,
        "reasoning": reasoning[:1],
        "inputs": inputs,
        "dropped_colliding": colliding,
        "warnings": warn,
        "problems": problems,
    }


def self_validate(pkg, deliverables, crits, dirs, max_crit):
    """The constraints that have broken uploads before, re-read from the written files."""
    import tomllib

    p = []
    seen = []
    total = 0.0
    for dname, files, _ in dirs:
        jt = tomllib.load(open(os.path.join(pkg, "tests", dname, "judge.toml"), "rb"))
        cs = jt.get("criterion", [])
        if len(cs) > max_crit:
            p.append("%s: %d criteria > %d" % (dname, len(cs), max_crit))
        if not isinstance(jt["judge"]["judge"], str):
            p.append(
                "%s: judge is not one string (rewardkit 0.1.7 rejects a panel)" % dname
            )
        s = sum(c["weight"] for c in cs)
        if abs(s - jt["judge"]["weight"]) > 1e-6:
            p.append(
                "%s: [judge] weight %s != criteria sum %s"
                % (dname, jt["judge"]["weight"], s)
            )
        total += jt["judge"]["weight"]
        for fp in jt["judge"]["files"]:
            if not os.path.isfile(
                os.path.join(pkg, "solution", "files", os.path.basename(fp))
            ):
                p.append("%s: files= %s not in solution/files" % (dname, fp))
        seen += [c["name"] for c in cs]
    if sorted(seen) != sorted(c["name"] for c in crits):
        p.append("criteria written != criteria read from verifier.json")
    rt = tomllib.load(open(os.path.join(pkg, "tests", "reward.toml"), "rb"))["reward"][
        0
    ]
    for dname, _, ch in dirs:
        jw = round(sum(c["weight"] for c in ch), 6)
        if abs(rt.get("weights", {}).get(dname, -1) - jw) > 1e-6:
            p.append("reward.toml weights[%s] != [judge] weight %s" % (dname, jw))
    if abs(total - 1.0) > 0.01:
        p.append("judge weights sum to %.4f, not 1.0" % total)
    shipped = sorted(os.listdir(os.path.join(pkg, "solution", "files")))
    if shipped != sorted(deliverables):
        p.append(
            "solution/files %s != graded deliverables %s"
            % (shipped, sorted(deliverables))
        )
    for rel in ("instruction.md", os.path.join("tests", "task_prompt.txt")):
        t = open(os.path.join(pkg, rel), encoding="utf-8").read()
        if "/workspace/" in t:
            p.append("%s still names /workspace/" % rel)
    return p


def fix_formula_cache(pkg):
    """A golden .xlsx saved without a recalculation has formula cells with no stored value, which the
    judge reads as blank (GTM-142: 247 of 247). Run the SVC mechanical fixer, which writes each
    recomputed value into the cell's cache and never touches the formula text."""
    if not any(
        f.lower().endswith(".xlsx")
        for f in os.listdir(os.path.join(pkg, "solution", "files"))
    ):
        return "n/a (no graded .xlsx)"
    import subprocess
    import tempfile

    rep = os.path.join(tempfile.mkdtemp(), "fca.json")
    r = subprocess.run(
        [
            sys.executable,
            os.path.join(HERE, "svc_formula_cache_autofix.py"),
            os.path.basename(pkg),
            "--root",
            os.path.dirname(pkg),
            "--out",
            rep,
        ],
        capture_output=True,
        text=True,
    )
    if not os.path.isfile(rep):
        return "ERROR: svc_formula_cache_autofix.py wrote no report (rc %s): %s" % (
            r.returncode,
            (r.stderr or r.stdout)[-300:],
        )
    # the fixer keeps <file>.orig next to what it patched; solution/files/ may hold only graded files,
    # and the raw expert_solution/ on Drive is the untouched original
    sf = os.path.join(pkg, "solution", "files")
    for fn in os.listdir(sf):
        if fn.endswith(".orig"):
            os.remove(os.path.join(sf, fn))
    res = json.load(open(rep, encoding="utf-8"))["results"][0]
    n = len(res.get("cells_to_patch", []))
    detail = "; ".join(res.get("reasons", []) + res.get("errors", []))
    return "%s%s%s" % (
        res["status"],
        " (%d cells)" % n if n else "",
        ": " + detail if detail else "",
    )


def main(argv):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("raw_dirs", nargs="+")
    ap.add_argument("--out-root", default="ekw_rewardkit")
    ap.add_argument("--drop-colliding-sources", action="store_true")
    ap.add_argument("--max-criteria", type=int, default=MAX_CRIT)
    ap.add_argument("--no-formula-fix", action="store_true")
    a = ap.parse_args(argv)
    rc = 0
    for rd in a.raw_dirs:
        name = os.path.basename(os.path.abspath(rd))
        try:
            r = convert(
                rd,
                a.out_root,
                a.drop_colliding_sources,
                a.max_criteria,
                not a.no_formula_fix,
            )
        except Refuse as e:
            print("\n=== %s: REFUSED ===\n  %s" % (name, e))
            rc = 1
            continue
        ok = not r["problems"]
        rc = rc if ok else 1
        print(
            "\n=== %s: %s ===" % (r["task"], "CONVERTED" if ok else "FAILED SELF-CHECK")
        )
        print("  package:   %s" % r["pkg"])
        print(
            "  judge:     %s (source verifier.json named %s)"
            % (r["judge"], r["source_judge"])
        )
        print("  criteria:  %d, weights sum %s" % (r["criteria"], r["wsum"]))
        for dn, fs, n, w in r["dirs"]:
            print("  %-20s %2d criteria  weight %-8s files %s" % (dn, n, w, fs))
        for d, (e, how) in r["mapping"].items():
            print(
                "  golden:    solution/files/%s  <-  expert_solution/%s  (%s)"
                % (d, e, how)
            )
        print("  reasoning: %s" % (r["reasoning"] or "none"))
        print("  stored values: %s" % r["formula_fix"])
        if r["formula_fix"].startswith(("ERROR", "needs_judgment", "error")):
            rc = 1
        print(
            "  inputs:    %d file(s) -> environment/initial_workspace/%s"
            % (len(r["inputs"]), "" if r["inputs"] else " (none; COPY removed)")
        )
        if r["dropped_colliding"]:
            print(
                "  DROPPED from workspace (same name as a graded deliverable): %s"
                % r["dropped_colliding"]
            )
        if r["not_shipped"]:
            print(
                "  not shipped (expert extras no verifier reads): %s" % r["not_shipped"]
            )
        for w in r["warnings"]:
            print("  warn: %s" % w)
        for pr in r["problems"]:
            print("  PROBLEM: %s" % pr)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
