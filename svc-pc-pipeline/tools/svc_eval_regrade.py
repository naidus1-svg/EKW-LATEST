#!/usr/bin/env python3
"""
svc_eval_regrade.py - the SVC-PC v8 exit-door gate's core check.

WHY THIS EXISTS
When DataOS grades a task it runs real solver models (oracle, codex, terminus, gpt-5.6-sol) and SAVES
each model's actual answer inside the return zip under evaluations/eval_*/eval_files/artifacts/app/, next
to verifier/reward-details.json (per-criterion scores) and the task_files/tests rubric as-graded. When
DataOS rejects on a "false rejection" (1.3/1.4), its reviewer points at a solver answer that is a correct
but different reading and that our rubric FAILED. That answer is a real, capable, already-paid-for probe of
our rubric. This tool re-grades it against the CURRENT (fixed) rubric so we can tell whether a fix actually
landed BEFORE spending another DataOS round.

TWO DIRECTIONS
  A (false-rejection, 1.3/1.4): a solver answer that our rubric wrongly FAILED must now PASS the fixed rubric.
  B (false-credit, 1.5): a degenerate/hollow answer that our rubric wrongly PASSED must now FAIL the fixed
     rubric on the added coverage criterion.

SUBCOMMANDS
  reproduce <task> --zip <return.zip>
      Read-only. Parse the return, list the GPT-flagged (eval, criterion) pairs, and from reward-details.json
      confirm the flagged answer actually scored < 1.0 on those criteria (direction A) - i.e. the reject
      reproduces. Prints the rev id (currency). This is the teeth test: run before any fix.

  regrade <task> --zip <return.zip> --rubric <tests_dir>
      Re-grade the flagged answers against the rubric in <tests_dir> (the CURRENT, fixed one). For each
      flagged criterion, PASS the fix only if BOTH: (1) the deterministic over-constraint the reviewer named
      is textually gone from the criterion, AND (2) an LLM re-grade of the answer on that criterion returns
      pass (judge = the rubric's own model via judge_emulate; extraction pinned to 0.1.7). Writes
      <out>/<task>.regrade.json {verdict, direction_A:[...], direction_B:[...], rev, checked_utc, rubric_sha}.

This module is stdlib-only for `reproduce`. `regrade` shells to judge_emulate for the LLM re-grade so the
extraction/judge path stays single-sourced.
"""

from __future__ import annotations
import argparse, hashlib, json, re, sys, time, zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---- return-zip parsing -------------------------------------------------------


def _checks_blocks(text: str):
    """Every parseable JSON object that has a 'checks' list, in document order."""
    out, seen = [], set()
    for m in re.finditer(r'"checks"', text):
        s = text.rfind("{", 0, m.start())
        while s >= 0 and s not in seen:
            depth = 0
            for i in range(s, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            j = json.loads(text[s : i + 1])
                            if isinstance(j, dict) and isinstance(
                                j.get("checks"), list
                            ):
                                out.append(j)
                                seen.add(s)
                        except Exception:
                            pass
                        break
            s = text.rfind("{", 0, s)
    return out


def _answer_block(text: str):
    """The model's ANSWER checks-block = the LAST block whose checks carry real pass/fail results
    (the prompt's schema block, with no results, comes first)."""
    blocks = _checks_blocks(text)
    real = [
        j
        for j in blocks
        if any(
            str(c.get("result", "")).lower() in ("pass", "fail")
            for c in j.get("checks", [])
        )
    ]
    return (real or blocks or [None])[-1]


CRIT_RE = re.compile(r"\b([a-z]{1,4}\d{1,3}[a-z]?)\b")  # c04b, r009, q27, e6b, d13a ...
EVAL_RE = re.compile(
    r"\beval[_ ]?(\d{4,})", re.I
)  # eval_511732 / eval 511732 (no trailing \b: path has eval_511731__)


def task_dirs(names, task):
    return sorted(
        set(
            n.split("/", 1)[0]
            for n in names
            if n.split("/", 1)[0].endswith(task)
            or re.match(rf"^{re.escape(task)}$", n.split("/", 1)[0])
        )
    )


def parse_return(zip_path: str, task: str):
    """Return {rev, majors:[{seat, category, name, criteria:set, evals:set, justification}], reward:{eval:{crit:score}}}."""
    z = zipfile.ZipFile(zip_path)
    names = z.namelist()
    root = None
    for n in names:
        seg = n.split("/", 1)[0]
        if task in seg:
            root = seg
            break
    if root is None:
        raise SystemExit(f"{task}: not in {zip_path}")
    revm = re.search(r"rev_\d+__(\d+)", "\n".join(n for n in names if root in n))
    rev = revm.group(1) if revm else "?"

    majors = []
    for n in names:
        if root not in n or "comprehensive_review" not in n or not n.endswith(".md"):
            continue
        seat = n.rsplit("/", 1)[-1][:44]
        d = _answer_block(z.read(n).decode("utf-8", "replace"))
        if not d:
            continue
        for c in d.get("checks", []):
            if str(c.get("severity", "")).lower() != "major":
                continue
            just = c.get("justification") or ""
            majors.append(
                {
                    "seat": seat,
                    "category": c.get("id"),
                    "name": c.get("name"),
                    "criteria": set(CRIT_RE.findall(just)),
                    "evals": set(EVAL_RE.findall(just)),
                    "justification": just,
                }
            )

    # per-eval per-criterion scores from reward-details.json
    reward = {}
    for n in names:
        if root not in n or not n.endswith("reward-details.json") or "oracle" in n:
            continue
        em = EVAL_RE.search(n)
        eid = em.group(1) if em else n
        try:
            rd = json.loads(z.read(n).decode("utf-8", "replace"))
        except Exception:
            continue
        crits = {}
        if isinstance(rd, dict):
            for dv in rd.values():
                if isinstance(dv, dict):
                    for c in dv.get("criteria", []) or []:
                        crits[str(c.get("name"))] = c.get("value")
        reward[eid] = crits
    return {
        "rev": rev,
        "root": root,
        "majors": majors,
        "reward": reward,
        "zip": zip_path,
    }


# ---- subcommands --------------------------------------------------------------


class InfraError(Exception):
    """The judge could not grade at all (capped lane, backend refusal): not evidence about the rubric."""


def cmd_reproduce(args):
    r = parse_return(args.zip, args.task)
    flagged_crit, flagged_eval = set(), set()
    for m in r["majors"]:
        flagged_crit |= m["criteria"]
        flagged_eval |= m["evals"]
    print(f"=== {args.task}  rev {r['rev']}  ({Path(args.zip).name}) ===")
    print(f"GPT major categories: {sorted(set(m['category'] for m in r['majors']))}")
    print(f"flagged criteria: {sorted(flagged_crit) or 'none named'}")
    print(f"flagged evals:    {sorted(flagged_eval) or 'none named'}")
    # teeth (direction A): does a flagged eval's reward-details confirm it FAILED a flagged criterion?
    teeth = []
    for eid, crits in r["reward"].items():
        if flagged_eval and eid not in flagged_eval:
            continue
        for cname, val in crits.items():
            if cname in flagged_crit and isinstance(val, (int, float)) and val < 1.0:
                teeth.append((eid, cname, val))
    if teeth:
        print(
            "TEETH OK - flagged compliant answer failed these criteria (the reject reproduces):"
        )
        for eid, cname, val in sorted(teeth):
            print(f"    eval_{eid}  {cname} = {val}")
    else:
        # a pass task (10-3-0) or a 1.5-only reject with no per-criterion false-rejection
        cats = sorted(set(m["category"] for m in r["majors"]))
        print(
            f"no direction-A teeth: {'no majors (PASS task)' if not cats else 'majors are '+str(cats)+' (likely 1.5 coverage/form; direction B applies)'}"
        )
    return 0 if (teeth or not r["majors"]) else 0  # reproduce is informational


try:
    import tomllib
except ModuleNotFoundError:  # py<3.11
    tomllib = None


def load_criteria_text(toml_bytes: bytes):
    """{criterion_name: description} from one judge.toml's [[criterion]] tables."""
    if tomllib is None:
        # minimal fallback parser: name = "..." then description = '''...''' pairs
        txt = toml_bytes.decode("utf-8", "replace")
        out = {}
        for m in re.finditer(
            r'name\s*=\s*"([^"]+)".*?description\s*=\s*(?:\'\'\'(.*?)\'\'\'|"([^"]*)")',
            txt,
            re.S,
        ):
            out[m.group(1)] = (m.group(2) or m.group(3) or "").strip()
        return out
    data = tomllib.loads(toml_bytes.decode("utf-8", "replace"))
    return {
        c.get("name"): (c.get("description") or "")
        for c in data.get("criterion", [])
        if c.get("name")
    }


def load_checks_criteria(src: str):
    """{criterion_name: fingerprint} for the programmatic criteria a checks.py registers (`rk.<fn>(..., name="d008")`).

    2026-09-24: this gate compared judge.toml text only, so it could not see a coverage fix made in checks.py and
    failed 40-1-0, 52-5-0, 41-3-0 and 25-4-0 with "no criterion added or rewritten" while their checks.py rewrites
    did close the DataOS 1.5 finding. The fingerprint covers the registration line, the criterion function with its
    decorators, every same-file function and module constant it reaches, so a rewrite inside a helper counts too.
    """
    import ast

    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {}
    funcs = {
        n.name: n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    consts = {}
    for n in tree.body:
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            for t in n.targets if isinstance(n, ast.Assign) else [n.target]:
                if isinstance(t, ast.Name):
                    consts[t.id] = n

    def seg(node):
        lines = src.splitlines()
        start = min(
            [node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]
        )
        return "\n".join(lines[start - 1 : node.end_lineno])

    def closure(fn):
        seen, stack = set(), [fn]
        while stack:
            f = stack.pop()
            if f in seen or (f not in funcs and f not in consts):
                continue
            seen.add(f)
            if f in consts:
                continue
            for n in ast.walk(funcs[f]):
                ref = (
                    n.id
                    if isinstance(n, ast.Name)
                    else (n.attr if isinstance(n, ast.Attribute) else None)
                )
                if ref and (ref in funcs or ref in consts):
                    stack.append(ref)
        return sorted(seen)

    # literal module constants (WEEKS = 13 ...) so a registration loop's range and f-string names resolve
    env = {}
    for k, n in consts.items():
        try:
            env[k] = ast.literal_eval(n.value)
        except Exception:
            pass
    out = {}

    def register(call, reg_stmt, loop_env):
        kw = next((k.value for k in call.keywords if k.arg == "name"), None)
        if kw is None:
            return
        if isinstance(kw, ast.Constant) and isinstance(kw.value, str):
            name = kw.value
        else:  # f"r{_w:02d}" inside a registration loop
            try:
                name = eval(compile(ast.Expression(kw), "<name>", "eval"), {"__builtins__": {}}, loop_env)
            except Exception:
                return
        fn = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
        parts = [seg(reg_stmt)] + [seg(funcs[f] if f in funcs else consts[f]) for f in closure(fn)]
        fp = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
        out[name] = "checks.py::" + (out[name].split("::", 1)[1] + fp if name in out else fp)

    for stmt in tree.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            register(stmt.value, stmt, dict(env))
        elif isinstance(stmt, ast.For) and isinstance(stmt.target, ast.Name):
            # 2026-09-24: 52-5-0 registers c01..c13 / r01..r13 / x01..x13 in `for _w in range(1, WEEKS + 1):`
            try:
                values = list(eval(compile(ast.Expression(stmt.iter), "<iter>", "eval"), {"__builtins__": {"range": range}}, dict(env)))
            except Exception:
                continue
            for v in values:
                le = dict(env, **{stmt.target.id: v})
                for sub in stmt.body:
                    if isinstance(sub, ast.Expr) and isinstance(sub.value, ast.Call):
                        register(sub.value, stmt, le)
    return out


def criteria_from_zip(zip_path, root):
    z = zipfile.ZipFile(zip_path)
    out = {}
    for n in z.namelist():
        if root in n and "task_files/tests" in n and n.endswith("judge.toml"):
            out.update(load_criteria_text(z.read(n)))
        elif (
            root in n
            and "task_files/tests" in n
            and n.endswith("checks.py")  # checks.py and formula_checks.py (88-0-0, 2026-09-26)
            and "verifier_lib" not in n
        ):
            out.update(load_checks_criteria(z.read(n).decode("utf-8", "replace")))
    return out


def criteria_from_dir(tests_dir):
    out = {}
    for p in Path(tests_dir).rglob("judge.toml"):
        out.update(load_criteria_text(p.read_bytes()))
    for p in Path(tests_dir).rglob("*checks.py"):
        if "verifier_lib" in p.parts or "__pycache__" in p.parts:
            continue
        out.update(
            load_checks_criteria(p.read_text(encoding="utf-8", errors="replace"))
        )
    return out


def cmd_regrade(args):
    r = parse_return(args.zip, args.task)
    as_graded = criteria_from_zip(args.zip, r["root"])
    current = criteria_from_dir(args.rubric)
    flagged_crit, flagged_eval = set(), set()
    cats = set()
    b_evals = (
        set()
    )  # answers a 1.5 finding names: the hollow answers the old rubric credited
    # 2026-09-28: a 1.5 major is not always a coverage hole. DataOS files some FALSE REJECTIONS under 1.5 too: the
    # answer it names FAILED one of the major's own criteria (3-9-0: 632689 failed s2z). That answer is compliant, it
    # is a direction-A target, and demanding a new criterion that takes points off it re-introduces the defect. So a
    # named answer counts as hollow only if it did not fail any of that major's criteria, and direction B is needed
    # only when some 1.5 major is a real coverage finding (a hollow answer, or no failed answer at all).
    b15 = []  # per 1.5 major: (hollow answers, named answers that failed its own criteria, its criteria)
    for m in r["majors"]:
        flagged_crit |= m["criteria"]
        flagged_eval |= m["evals"]
        cats.add(m["category"])
        if str(m["category"]).startswith("1.5"):
            named = set(m["evals"]) & set(r["reward"])
            failed_own = {
                e
                for e in named
                if any(
                    c in m["criteria"] and isinstance(v, (int, float)) and v < 1.0
                    for c, v in r["reward"][e].items()
                )
            }
            hollow = named - failed_own
            b_evals |= hollow
            b15.append((hollow, failed_own, set(m["criteria"])))
    b_evals &= set(r["reward"])  # only answers the return actually holds
    # direction-A targets: flagged criteria a flagged compliant answer actually failed
    a_targets = {}
    for eid, crits in r["reward"].items():
        if flagged_eval and eid not in flagged_eval:
            continue
        for cname, val in crits.items():
            if cname in flagged_crit and isinstance(val, (int, float)) and val < 1.0:
                a_targets.setdefault(cname, []).append(eid)
    a_targets = {c: sorted(set(v)) for c, v in a_targets.items() if c in as_graded}

    # deterministic: was each direction-A criterion actually CHANGED vs as-graded? (removed counts as changed)
    det = {}
    for c in a_targets:
        was, now = as_graded.get(c, ""), current.get(c)
        det[c] = (
            "removed" if now is None else ("changed" if now != was else "UNCHANGED")
        )
    unaddressed = [c for c, s in det.items() if s == "UNCHANGED"]

    # direction-B (1.5 coverage). The coverage fix is the set of criteria added OR rewritten since the grade.
    # 2026-09-23: this used to pass on `len(added) > 0` alone, so any added criterion satisfied it whether or not
    # it graded the missing fact, and every 1.5 major that came back had passed it. Now, when the finding names
    # the hollow answer it credited, that answer is re-graded against the current rubric and at least one
    # coverage-fix criterion must take points off it. A 1.5 finding that names no answer can only be checked
    # for an added/rewritten criterion; the record says "unproven" so nobody mistakes it for the real check.
    added = sorted(set(current) - set(as_graded))
    rewritten = sorted(
        c
        for c in current
        if c in as_graded and current[c] != as_graded[c] and c not in a_targets
    )
    coverage_fix = added + rewritten
    # A 1.5 major is a real coverage finding if it names a hollow answer, or names no failing answer AND cites a
    # criterion outside the direction-A set (3-9-0 seat 151264 named s2z and no answer; s2z is a direction-A target
    # failed by 632689, so that major is the same false rejection, not a coverage hole).
    b_needed = any(
        h or (not f and not (crit and crit <= set(a_targets))) for h, f, crit in b15
    )
    b_ok = (len(coverage_fix) > 0) if b_needed else None
    b_proof = None
    if b_needed:
        b_proof = (
            "no criterion added or rewritten"
            if not coverage_fix
            else (
                "unproven: the 1.5 finding names no answer to re-grade"
                if not b_evals
                else "pending"
            )
        )

    import subprocess, tempfile

    infra = []

    z = zipfile.ZipFile(args.zip)
    graded_cache = {}

    def grade_answer(eid):
        """Stage one saved DataOS answer and grade it against the CURRENT rubric; {criterion: score}."""
        if eid in graded_cache:
            return graded_cache[eid]
        stage = Path(tempfile.mkdtemp(prefix=f"regrade_{args.task}_{eid}_"))
        for n in z.namelist():
            if (
                r["root"] in n
                and f"eval_{eid}" in n
                and "/artifacts/app/" in n
                and not n.endswith("/")
            ):
                dst = stage / Path(n.split("/artifacts/app/", 1)[1])
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(z.read(n))
        # 2026-09-24: some evals (terminus-2) save the answer only as artifacts/app.tar.gz, no artifacts/app/ tree.
        # Staging nothing graded an EMPTY dir and scored the real answer 0.0 (SVC-PC-55-0-0 eval 522182).
        if not any(stage.iterdir()):
            import io, tarfile

            for n in z.namelist():
                if (
                    r["root"] in n
                    and f"eval_{eid}" in n
                    and n.endswith("/artifacts/app.tar.gz")
                ):
                    with tarfile.open(fileobj=io.BytesIO(z.read(n)), mode="r:gz") as tf:
                        for m in tf.getmembers():
                            p = Path(m.name)
                            if (
                                not m.isfile()
                                or ".." in p.parts
                                or p.parts[:1] != ("app",)
                            ):
                                continue
                            dst = stage / Path(*p.parts[1:])
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            dst.write_bytes(tf.extractfile(m).read())
        outj = stage / "scores.json"
        cmd = [
            args.python or "python3",
            args.judge_emulate,
            "deliverable",
            args.task,
            str(
                stage
            ),  # deliverable dir is a POSITIONAL arg in judge_emulate, not a flag
            "--corpus-root",
            args.corpus_root,
            "--out",
            str(outj),
            "--runs",
            "1",
            "--timeout",
            "600",  # per-criterion CLI ceiling; 300 (default) timed out on a large-xlsx answer
        ]
        subprocess.run(cmd, check=False, capture_output=True, timeout=3600)
        sc = json.loads(outj.read_text())
        # 2026-09-23: a capped lane writes infra_failure + total_reward null and NO criteria. Read as "no scores"
        # that became a false FAIL in both directions (4 of 4 accepted rubrics "failed" on a weekly-capped lane)
        # and fed a pointless fix attempt. Raise instead, so the verdict is INFRA and the runner releases the lane.
        if sc.get("infra_failure") or (
            "total_reward" in sc
            and sc.get("total_reward") is None
            and not sc.get("runs")
        ):
            raise InfraError(str(sc.get("error") or "judge returned no reward")[:300])
        got = {}
        for run in sc.get("runs") or sc.get("completed_runs") or [sc]:
            for g in run.get("groups", []):
                for cc in g.get("criteria", []):
                    # judge_emulate keys criteria by name (id is always None) and stores the score in value
                    got[cc.get("name") or cc.get("id")] = cc.get("value")
        graded_cache[eid] = got
        return got

    # Decision-run exemptions (2026-09-23). A task that failed this gate 5+ times with the same blocker gets one
    # decision run (runner DECIDE mode) that must pick rewrite / drop / keep per failing criterion. "keep" means
    # the DataOS-graded answer is genuinely wrong per the sources, so the criterion stays and this gate must not
    # demand that the answer pass it. Only a keep with cited source evidence AND a reason is honoured; the
    # exemption is written into the verdict record so a reviewer sees exactly what was overruled and why.
    # 2026-09-24: applied BEFORE the LLM re-grade. It used to run after, so a kept (unchanged) criterion still sat
    # in `unaddressed` when the re-grade decided whether to run, the re-grade was skipped, and the verdict failed
    # with "re-grade did not confirm loosened criteria: {}" (94-0-0, 25-2-0, 31-5-0 parked on this).
    kept = {}
    if getattr(args, "decision", None) and Path(args.decision).exists():
        try:
            for d in json.loads(Path(args.decision).read_text()).get("decisions", []):
                c = str(d.get("criterion", "")).strip()
                if (
                    c
                    and d.get("action") == "keep"
                    and str(d.get("evidence", "")).strip()
                    and str(d.get("reason", "")).strip()
                ):
                    kept[c] = {"evidence": d["evidence"], "reason": d["reason"]}
        except Exception as e:
            print(f"WARN decision file unreadable, no exemptions applied: {e}")
    unaddressed = [c for c in unaddressed if c not in kept]

    # LLM re-grade (sandbox only): stage each flagged answer, run judge_emulate deliverable mode,
    # confirm every direction-A criterion now scores pass on the compliant answer.
    # A flagged criterion is "addressed" by EITHER deletion (removed the over-enforcement) OR loosening
    # (still exists, must now pass the compliant answer). Only the loosened ones need an LLM re-grade;
    # a removed criterion is addressed deterministically - grading a criterion that no longer exists would
    # wrongly fail the delete-direction fix (the most common correct 1.4 fix) and re-block the right answer.
    to_confirm = [c for c in a_targets if det.get(c) == "changed"]
    llm = {"ran": False, "passed": None, "detail": {}}
    if args.judge_emulate and to_confirm and not unaddressed:
        allpass = True
        for eid in sorted({e for c in to_confirm for e in a_targets[c]}):
            try:
                got = grade_answer(eid)
                for (
                    c
                ) in (
                    to_confirm
                ):  # loosened criteria only; removed ones are addressed by deletion
                    if c not in a_targets or eid not in a_targets[c]:
                        continue
                    v = got.get(c)
                    ok = isinstance(v, (int, float)) and v >= 1.0
                    llm["detail"][f"{eid}:{c}"] = v
                    if not ok:
                        allpass = False
            except InfraError as e:
                infra.append(f"{eid}: {e}")
                allpass = False
            except Exception as e:
                llm["detail"][f"{eid}:error"] = str(e)[:200]
                allpass = False
        llm["ran"] = True
        llm["passed"] = allpass

    # direction-B proof: a hollow answer the 1.5 finding named must now lose points on a coverage-fix criterion.
    b_detail = {}
    if args.judge_emulate and args.b_proof and b_needed and coverage_fix and b_evals:
        caught = False
        for eid in sorted(b_evals):
            try:
                got = grade_answer(eid)
            except InfraError as e:
                infra.append(f"{eid}: {e}")
                continue
            except Exception as e:
                b_detail[f"{eid}:error"] = str(e)[:200]
                continue
            fails = {
                c: got.get(c)
                for c in coverage_fix
                if isinstance(got.get(c), (int, float)) and got.get(c) < 1.0
            }
            b_detail[eid] = (
                fails or "no coverage-fix criterion took points off this answer"
            )
            caught = caught or bool(fails)
        b_ok = caught
        b_proof = (
            "proven: a named hollow answer now fails a coverage-fix criterion"
            if caught
            else "FAILED: every answer the 1.5 finding named still passes every added/rewritten criterion"
        )

    if b_proof == "pending":
        b_proof = "not enforced (--b-proof off): an added/rewritten criterion exists, hollow re-grade not run"

    if kept:
        if llm["ran"] and not llm["passed"] and not infra:
            failing = [
                k
                for k, v in llm["detail"].items()
                if not (isinstance(v, (int, float)) and v >= 1.0)
            ]
            if failing and all(
                ":" in k and k.split(":", 1)[1] in kept for k in failing
            ):
                llm["passed"] = True
                llm["exempted"] = failing

    # verdict. Addressed = every flagged criterion either removed (deletion) or changed-and-now-passing.
    removed_only = [c for c in a_targets if det.get(c) == "removed"]
    confirm_ok = (not to_confirm) or (llm["ran"] and llm["passed"])
    b_ok_final = b_ok if b_needed else True
    if infra:
        # the runner's LIMIT_RE matches "infra refusal" in this printed line and releases the lane (cap_exit)
        verdict = "INFRA"
        why = (
            "infra refusal: the judge could not grade (lane capped?): "
            + " | ".join(infra)[:600]
        )
        print(why)
    elif unaddressed:
        verdict = "FAIL"
        why = f"flagged criteria unchanged vs as-graded: {unaddressed}"
    elif b_needed and not b_ok:
        verdict = "FAIL"
        why = f"1.5 coverage fix not proven: {b_proof}; per answer: {b_detail}"
    elif args.judge_emulate and to_confirm and not llm["ran"]:
        # 2026-09-24 structural guard: a sub-check this gate is required to run did not run. That is a defect in
        # this tool, never a task blocker, so it gets its own verdict. The runner parks it as GATE-ERROR in
        # gate_errors.txt (reported every cycle) instead of burning fix and decide rounds on the task.
        verdict = "GATE-ERROR"
        why = f"gate internal: {len(to_confirm)} loosened criteria need a re-grade but the re-grade did not run ({to_confirm})"
    elif args.judge_emulate:
        verdict = "PASS" if (confirm_ok and b_ok_final) else "FAIL"
        why = (
            f"addressed: {len(removed_only)} removed, {len(to_confirm)} loosened+re-graded-passing; coverage_ok={b_ok_final}"
            if verdict == "PASS"
            else f"re-grade did not confirm loosened criteria: {llm['detail']}"
        )
    else:
        verdict = "DETERMINISTIC-ONLY"
        why = "flagged criteria addressed (removed/loosened/coverage-added); LLM re-grade not run (no --judge-emulate)"

    rec = {
        "task": args.task,
        "rev": r["rev"],
        "verdict": verdict,
        "why": why,
        "direction_A": {
            "targets": a_targets,
            "changed": det,
            "unaddressed": unaddressed,
        },
        "direction_B": {
            "needed": b_needed,
            "added_criteria": added,
            "rewritten_criteria": rewritten,
            "hollow_answers": sorted(b_evals),
            "ok": b_ok,
            "proof": b_proof,
            "detail": b_detail,
        },
        "llm_regrade": llm,
        "kept_by_decision": kept,
        "categories": sorted(cats),
        "checked_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rubric_sha": hashlib.sha256(
            repr(sorted(current.items())).encode()
        ).hexdigest()[:16],
    }
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{args.task}.regrade.json").write_text(json.dumps(rec, indent=2))
    print(json.dumps({k: rec[k] for k in ("task", "rev", "verdict", "why")}, indent=2))
    print(f"-> {outdir / (args.task + '.regrade.json')}")
    return 0 if verdict in ("PASS", "DETERMINISTIC-ONLY") else 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("reproduce")
    p.add_argument("task")
    p.add_argument("--zip", required=True)
    p.set_defaults(fn=cmd_reproduce)
    g = sub.add_parser("regrade")
    g.add_argument("task")
    g.add_argument("--zip", required=True)
    g.add_argument("--rubric", required=True, help="current (fixed) tests/ dir")
    g.add_argument("--out", default=".")
    g.add_argument(
        "--judge-emulate",
        default=None,
        help="path to judge_emulate.py (sandbox) to run the LLM re-grade",
    )
    g.add_argument("--corpus-root", default=None)
    g.add_argument("--python", default=None)
    g.add_argument(
        "--b-proof",
        action="store_true",
        help="direction B: re-grade the hollow answers a 1.5 finding names and require a coverage-fix criterion "
        "to take points off one (off until its precision on accepted rubrics is measured)",
    )
    g.add_argument(
        "--decision",
        default=None,
        help="decision-run record (<task>.decision.json); a criterion marked keep with cited evidence + reason "
        "is exempt from the unchanged / still-fails checks and listed under kept_by_decision",
    )
    g.set_defaults(fn=cmd_regrade)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
