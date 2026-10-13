#!/usr/bin/env python3
"""Oracle check: stage a task's golden as the agent's output and run the real verifier over it.

This is the local half of an oracle run. `solution/solve.sh` is executed exactly as Harbor runs it
(it copies `solution/golden_outputs/` into `$WORKSPACE_DIR/output/`), then the package's OWN
`verifier_lib` grades that workspace through `run_verifier`.

What this can and cannot tell you
---------------------------------
* **deterministic criteria -> a true oracle verdict.** They are evaluated for real. Any `FAIL` here
  is a genuine oracle failure: the golden does not satisfy the task's own rubric.
* **rubric (LLM judge) criteria -> NOT a verdict.** There is no judge API key in this repo, so the
  judge is stubbed and its verdict is discarded, never reported as pass or fail. What IS checked for
  real is the evidence the judge would have been handed: the source command resolves, and returns
  non-empty, untruncated content. A criterion whose source errors or returns nothing fails at the
  platform no matter what the judge thinks, so those are reported as `NO_EVIDENCE` / `TRUNCATED`.

Anything this prints about rubric criteria is a statement about evidence, never about correctness.

Usage:
    oracle_golden_check.py <package_dir> [<package_dir> ...] [--json OUT] [--quiet]

Exit status: 1 if any package has a deterministic FAIL, a NO_EVIDENCE criterion, a fatal error, or
no gradable output at all; 0 otherwise.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

TRUNCATION_MARK = "[TRUNCATED: extraction stopped at the"
DEFAULT_MAX_CONTENT = 90000


def _load_runner(tests_scratch: Path, libname: str):
    """Imports the package's own verifier library from a SCRATCH copy.

    Importing from inside the package would write __pycache__ into a deliverable, so the caller
    copies tests/ out first and we import the copy under a unique module name.

    Every task ships its OWN copy of the library, often with task-custom source commands, and they
    all use the same top-level name. Python caches by name, so without this purge the second and
    later packages in one run would silently be graded by the FIRST package's library -- which
    reports a task's custom command as "unknown source". Drop the whole namespace first.
    """
    for mod in [m for m in sys.modules if m == libname or m.startswith(libname + ".")]:
        del sys.modules[mod]
    importlib.invalidate_caches()

    pkg_root = tests_scratch / libname
    spec = importlib.util.spec_from_file_location(
        libname, pkg_root / "__init__.py", submodule_search_locations=[str(pkg_root)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[libname] = module
    spec.loader.exec_module(module)
    runner = importlib.import_module(f"{libname}.runner")
    return runner


def _max_content_of(package: Path) -> int:
    """Honours a task-specific VERIFIER_MAX_CONTENT baked into its runtime, as test.sh would."""
    for name in ("verifier_runtime.py", "verifier_runtime.pyrun"):
        p = package / "tests" / name
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if "VERIFIER_MAX_CONTENT" in line and "environ" in line:
                digits = "".join(c for c in line.split('"')[-2] if c.isdigit())
                if digits:
                    return int(digits)
    return DEFAULT_MAX_CONTENT


def make_glm_judge(samples: int) -> Any:
    """A real judge backed by the OpenAI-compatible proxy in LLM_API_* (the 'GLM stand-in').

    Reads LLM_API_BASE_URL / LLM_API_MODEL / LLM_API_KEY from the environment; the key is only ever
    put in the Authorization header, never logged, echoed or written to a report. With this the
    rubric criteria get REAL verdicts, so the oracle check becomes a true end-to-end golden run.

    `samples` controls how many independent verdicts per criterion (the judge model id is written
    into config.models that many times); the reported verdict is the majority.
    """
    import urllib.request

    base = os.environ.get("LLM_API_BASE_URL", "").rstrip("/")
    model = os.environ.get("LLM_API_MODEL", "")
    key = os.environ.get("LLM_API_KEY", "")
    missing = [n for n, v in (("LLM_API_BASE_URL", base), ("LLM_API_MODEL", model), ("LLM_API_KEY", key)) if not v]
    if missing:
        raise SystemExit(
            "--judge glm needs these environment variables, which are not set in this process: "
            + ", ".join(missing)
            + "\nExport them in the shell that runs this tool (the key is read from the env and never printed)."
        )

    def judge(**kwargs: Any) -> dict[str, Any]:
        body = json.dumps({
            "model": model,
            "messages": kwargs.get("messages", []),
            "temperature": 0,
            "max_tokens": int(os.environ.get("LLM_API_MAX_TOKENS", "4096")),
        }).encode()
        req = urllib.request.Request(
            f"{base}/chat/completions", data=body,
            headers={"content-type": "application/json", "authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            payload = json.loads(resp.read())
        content = payload["choices"][0]["message"]["content"]
        # The proxy's model is not guaranteed to honour response_format, so recover the JSON object.
        if "{" in content:
            content = content[content.index("{"): content.rindex("}") + 1]
        return {"choices": [{"message": {"content": content}}]}

    judge.samples = samples  # type: ignore[attr-defined]
    return judge


def check_package(package: Path, judge_fn: Any = None, samples: int = 0) -> dict[str, Any]:
    """Runs solve.sh + the verifier over the golden. Returns a per-criterion report.

    With `judge_fn` None the judge is stubbed and rubric criteria are reported as evidence health
    only. With a real judge_fn, rubric criteria carry real PASS/FAIL verdicts.
    """
    task = package.name
    out: dict[str, Any] = {"task": task, "criteria": [], "errors": []}

    libname = "__verifier_lib" if (package / "tests" / "__verifier_lib").is_dir() else "verifier_lib"
    if not (package / "tests" / libname).is_dir():
        out["errors"].append(f"no verifier library in {package}/tests (rewardkit genre is not supported here)")
        return out

    with tempfile.TemporaryDirectory(prefix=f"oracle-{task}-") as tmp:
        tmpd = Path(tmp)
        workspace, verifier_dir = tmpd / "workspace", tmpd / "verifier"
        workspace.mkdir()
        verifier_dir.mkdir()

        # 1a. Stage the task inputs where Harbor puts them. The image does `COPY data/ /workspace/data/`,
        # so criteria that read `data/...` (every extract_many that cites a source document against the
        # deliverable) only resolve when the inputs are in the workspace, not just the outputs.
        data_src = package / "environment" / "data"
        if data_src.is_dir():
            shutil.copytree(data_src, workspace / "data",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

        # 1b. Stage the golden exactly as Harbor does, by running the package's own solve.sh.
        solve = package / "solution" / "solve.sh"
        if not solve.is_file():
            out["errors"].append("solution/solve.sh missing")
            return out
        env = {**os.environ, "WORKSPACE_DIR": str(workspace), "SOLUTION_DIR": str(package / "solution")}
        r = subprocess.run(["bash", str(solve)], capture_output=True, text=True, env=env, timeout=600)
        out["solve_sh"] = {"returncode": r.returncode, "stderr": r.stderr.strip()[:500]}
        if r.returncode != 0:
            out["errors"].append(f"solve.sh exited {r.returncode}: {r.stderr.strip()[:300]}")
            return out
        staged = sorted(p.name for p in (workspace / "output").glob("*")) if (workspace / "output").is_dir() else []
        out["staged_outputs"] = staged
        if not staged:
            out["errors"].append("solve.sh staged no files into output/")
            return out

        # 2. Import the library from a scratch copy so the package keeps no __pycache__.
        tests_scratch = tmpd / "tests"
        shutil.copytree(package / "tests", tests_scratch, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if judge_fn is not None and samples:
            # Point the scratch spec at the stand-in judge, `samples` times over. Only the scratch
            # copy is touched; the shipped verifier.json keeps its real judge config.
            vj = tests_scratch / "verifier.json"
            doc = json.loads(vj.read_text())
            doc.setdefault("config", {})["models"] = [os.environ.get("LLM_API_MODEL", "")] * samples
            vj.write_text(json.dumps(doc, indent=2))
            out["judge"] = {"model": os.environ.get("LLM_API_MODEL", ""), "samples": samples}
        try:
            runner = _load_runner(tests_scratch, libname)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            out["errors"].append(f"cannot import {libname}: {exc}")
            return out

        # 3. Stub judge: capture the evidence, discard the verdict.
        # The judge is called MULTIPLE times per criterion (one per entry in config.models, since
        # judge sampling is mean/majority of 3), so call order cannot be zipped against criteria.
        # Key the captured evidence by the criterion's own <source> declaration instead: evidence
        # depends only on the source, and every criterion's source is in verifier.json.
        evidence_by_source: dict[str, str] = {}

        def _norm(src: Any) -> str:
            """Canonical form of a source declaration, with unset keys dropped."""
            def strip(o: Any) -> Any:
                if isinstance(o, dict):
                    return {k: strip(v) for k, v in o.items() if v is not None}
                if isinstance(o, list):
                    return [strip(v) for v in o]
                return o
            return json.dumps(strip(src), sort_keys=True)

        def stub_completion(**kwargs: Any) -> dict[str, Any]:
            user = ""
            for m in kwargs.get("messages", []):
                if m.get("role") == "user":
                    user = str(m.get("content", ""))
            if "<source>" in user and "<data>" in user:
                src_txt = user.split("<source>", 1)[1].split("</source>", 1)[0].strip()
                data = user.split("<data>", 1)[1].split("</data>", 1)[0].strip()
                try:
                    evidence_by_source[_norm(json.loads(src_txt))] = data
                except json.JSONDecodeError:
                    pass
            if judge_fn is not None:
                return judge_fn(**kwargs)
            return {"choices": [{"message": {"content": json.dumps(
                {"verdict": True, "justification": "STUBBED - no judge available locally"})}}]}

        try:
            payload = runner.run_verifier(
                tests_scratch / "verifier.json",
                workspace_dir=workspace,
                verifier_dir=verifier_dir,
                agent_logs_dir=tmpd / "agent_logs",
                llm_completion=stub_completion,
                max_content_chars=_max_content_of(package),
            )
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"verifier raised: {type(exc).__name__}: {exc}")
            report = verifier_dir / "verifier-report.json"
            if report.is_file():
                payload = json.loads(report.read_text())
            else:
                return out

        if payload.get("error"):
            out["errors"].append(f"fatal_error: {payload['error']}")

        spec = json.loads((tests_scratch / "verifier.json").read_text())
        kinds = {v["name"]: v["assertion"]["type"] for v in spec["verifiers"]}
        sources = {v["name"]: _norm(v["source"]) for v in spec["verifiers"]}

        for entry in payload.get("assertion_results", []):
            name = entry.get("name")
            # Each entry is {name, definition, result:{success, expected, actual, effective_weight,
            # error, reason, evaluation}} -- the verdict lives under "result", never at top level.
            res = entry.get("result", entry)
            kind = kinds.get(name, "?")
            row: dict[str, Any] = {
                "name": name, "type": kind,
                "weight": res.get("effective_weight"),
            }
            if res.get("error"):
                row["outcome"] = "ERROR"
                row["detail"] = str(res["error"])[:300]
            elif kind == "deterministic":
                row["outcome"] = "PASS" if res.get("success") else "FAIL"
                if not res.get("success"):
                    row["detail"] = (f"expected={res.get('expected')!r} actual={res.get('actual')!r}"
                                     f" reason={res.get('reason')!r}")
            elif judge_fn is not None:
                # Real judge: this IS a verdict on the golden.
                row["outcome"] = "PASS" if res.get("success") else "FAIL"
                ev = res.get("evaluation") or {}
                row["votes"] = f"{ev.get('true_count')}T/{ev.get('false_count')}F"
                if not res.get("success"):
                    row["detail"] = str(res.get("reason") or "")[:200]
                    attempts = ev.get("attempts") or []
                    if attempts:
                        just = (attempts[0] or {}).get("justification")
                        if just:
                            row["detail"] += f" | judge: {str(just)[:220]}"
            else:
                # Rubric: judge verdict is stubbed and deliberately ignored. Grade the EVIDENCE.
                key = sources.get(name)
                if key not in evidence_by_source:
                    row["outcome"] = "NO_EVIDENCE"
                    row["detail"] = "the judge was never handed this criterion's source output"
                    row["evidence_chars"] = 0
                    out["criteria"].append(row)
                    continue
                data = evidence_by_source[key]
                body = data.strip('"').strip()
                if body in ("", "null", "{}", "[]", '""'):
                    row["outcome"] = "NO_EVIDENCE"
                    row["detail"] = "source returned empty content; the judge would grade a blank"
                elif TRUNCATION_MARK in data:
                    row["outcome"] = "TRUNCATED"
                    row["detail"] = "source content hit the char cap before the end of the file"
                else:
                    row["outcome"] = "EVIDENCE_OK"
                row["evidence_chars"] = len(data)
            out["criteria"].append(row)

        if not out["criteria"]:
            out["errors"].append("verifier produced no assertion results")

    dets = [c for c in out["criteria"] if c["type"] == "deterministic"]
    rubs = [c for c in out["criteria"] if c["type"] == "rubric"]
    out["summary"] = {
        "criteria": len(out["criteria"]),
        "deterministic": len(dets),
        "deterministic_pass": sum(1 for c in dets if c["outcome"] == "PASS"),
        "deterministic_fail": sum(1 for c in dets if c["outcome"] == "FAIL"),
        "rubric_pass": sum(1 for c in rubs if c["outcome"] == "PASS"),
        "rubric_fail": sum(1 for c in rubs if c["outcome"] == "FAIL"),
        "errored": sum(1 for c in out["criteria"] if c["outcome"] == "ERROR"),
        "no_evidence": sum(1 for c in out["criteria"] if c["outcome"] == "NO_EVIDENCE"),
        "truncated": sum(1 for c in out["criteria"] if c["outcome"] == "TRUNCATED"),
        "evidence_ok": sum(1 for c in out["criteria"] if c["outcome"] == "EVIDENCE_OK"),
        # Weight that is confirmed-broken on the golden, i.e. reward a correct answer cannot earn.
        "broken_weight": round(sum(
            c.get("weight") or 0 for c in out["criteria"]
            if c["outcome"] in ("FAIL", "ERROR", "NO_EVIDENCE")), 4),
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("packages", nargs="+", type=Path)
    ap.add_argument("--json", type=Path, help="write the full per-criterion report here")
    ap.add_argument("--quiet", action="store_true", help="only print packages with a problem")
    ap.add_argument("--judge", choices=("none", "glm"), default="none",
                    help="'none' (default) stubs the judge and reports rubric EVIDENCE health only; "
                         "'glm' grades rubric criteria for real through the LLM_API_* stand-in proxy")
    ap.add_argument("--samples", type=int, default=1,
                    help="judge verdicts per rubric criterion when --judge glm (majority wins)")
    args = ap.parse_args()

    judge_fn = make_glm_judge(args.samples) if args.judge == "glm" else None
    if judge_fn is not None:
        print(f"judge: {os.environ.get('LLM_API_MODEL')} via stand-in proxy, {args.samples} sample(s)/criterion\n")

    reports, bad = [], False
    for pkg in args.packages:
        rep = check_package(pkg, judge_fn=judge_fn, samples=args.samples if judge_fn else 0)
        reports.append(rep)
        s = rep.get("summary", {})
        problem = bool(rep["errors"]) or s.get("deterministic_fail") or s.get("errored") \
            or s.get("no_evidence") or s.get("rubric_fail")
        bad = bad or bool(problem)
        if args.quiet and not problem:
            continue
        flag = "PROBLEM" if problem else "ok     "
        if rep["errors"]:
            print(f"{flag} {rep['task']}: {'; '.join(rep['errors'])[:200]}")
            continue
        rubric = (f"rubric {s['rubric_pass']}/{s['rubric_pass'] + s['rubric_fail']} pass"
                  if judge_fn is not None else
                  f"rubric evidence ok={s['evidence_ok']} none={s['no_evidence']} trunc={s['truncated']}")
        print(
            f"{flag} {rep['task']}: det {s['deterministic_pass']}/{s['deterministic']} pass"
            f"{', ' + str(s['deterministic_fail']) + ' FAIL' if s['deterministic_fail'] else ''}"
            f" | {rubric} | errored={s['errored']} | broken_weight={s['broken_weight']}"
        )
        for c in rep["criteria"]:
            if c["outcome"] in ("FAIL", "ERROR", "NO_EVIDENCE"):
                print(f"         - {c['name']} [{c['type']} w={c.get('weight')}] {c['outcome']}: {c.get('detail','')}")

    if args.json:
        args.json.write_text(json.dumps(reports, indent=1), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
