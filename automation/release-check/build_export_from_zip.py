#!/usr/bin/env python3
"""Build the release_check export folder from DataOS "with runs" downloads (zip files or already-extracted folders).

  python3 build_export_from_zip.py INPUT [INPUT ...] OUT_EXPORT [--spec 557] [--any-prompt] [--all-revisions] [--known-prompts FILE]

  INPUT        a "with runs" zip, or a folder holding one (an extracted zip). Layout inside:
               <task name>/rev_<n>__<task id>/{task_files/, evaluations/eval_<eval id>__attempt_<k>__<agent>[__<model>]/
               eval_files/{result.json, verifier/reward-details.json, ...}, verifications/comprehensive_review_<id>___<agent>__<model>.md}
  OUT_EXPORT   written in the same layout as build_export.py (results.jsonl, runs.csv, nop.csv, map.csv, tasks.csv,
               newruns/index.csv, runs/), plus these helper folders so run_release.py works with no other input:
                 _pkgs/<task id>/      copy of the zip's task_files (the task package; PKGS_DIRS for run_release.py)
                 _dl_stub/<task id>/   task.json with id and name only (run_release.py --dl)
                 _extracted/           where zips were unpacked
                 build_report.txt, reviews_not_used.csv, run_mapping.csv

Rules (each checked on the two zips in out/WITHRUNS.md):
  run id        the number in result.json config.task.path ("/tmp/eval_<run id>_.../task_<task id>"). It is cross-checked
                against the review's evaluationrun_ids. The number in the folder name (eval_<id>) is the evaluation id, not the run id.
                If result.json has no such path, the run gets the id e<eval id>a<attempt> and is listed as unmapped.
  agent         first word after attempt_<k>__ in the folder name, upper-cased (oracle, nop, codex, terminus-2 ...).
  status        PASSED if the reward is 1.0, otherwise FAILED (the zip has no status field; this matches 135 of 135 runs in work/trial3a/dl).
  review prompt sha256 of the stripped question text, looked up in known_prompts.json (the zip does not carry the saved prompt id).
                Only reviews whose prompt is --spec (the saved prompt id; default 557, which is answer-check-v11) go to results.jsonl;
                the rest are listed in reviews_not_used.csv.
                --any-prompt keeps all finished reviews, each tagged with its prompt id (check 2 then reads them as if they were answer-check-v11).
  revisions     when a task name has several rev_ folders, only the highest rev is used unless --all-revisions.
"""

import argparse
import csv
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile

H = os.path.dirname(os.path.abspath(__file__))
REV_RE = re.compile(r"^rev_(\d+)__(\d+)$")
EVAL_RE = re.compile(r"^eval_(\d+)__attempt_(\d+)__(.+)$")
REVIEW_RE = re.compile(r"^comprehensive_review_(\d+)___(.*)\.md$")
PATH_RE = re.compile(r"/eval_(\d+)_")


def safe_extract(zpath, dest):
    root = os.path.realpath(dest)
    with zipfile.ZipFile(zpath) as zf:
        for m in zf.infolist():
            target = os.path.realpath(os.path.join(dest, m.filename))
            if target != root and not target.startswith(root + os.sep):
                raise SystemExit("zip member escapes the folder: %s" % m.filename)
        zf.extractall(dest)


def find_revs(root):
    """(task name, rev number, task id, rev dir) for every rev_<n>__<id> folder under root."""
    out = []
    for dp, dn, _fn in os.walk(root):
        for d in list(dn):
            m = REV_RE.match(d)
            if m:
                p = os.path.join(dp, d)
                out.append((os.path.basename(dp), int(m.group(1)), m.group(2), p))
                dn.remove(d)
    return sorted(out, key=lambda x: (x[0], x[1]))


def parse_review(path):
    """Return dict(review_id, header, question, answer) from one verification .md; None if it is not that shape."""
    name = os.path.basename(path)
    m = REVIEW_RE.match(name)
    txt = open(path, encoding="utf-8", errors="replace").read()
    i = txt.find("## transcript")
    if not m or i < 0:
        return None
    head, body = txt[:i], txt[i + len("## transcript") :]
    hdr = {}
    for sec in re.split(r"(?m)^## ", head):
        if not sec.strip():
            continue
        k, _, v = sec.partition("\n")
        hdr[k.strip()] = v.strip()
    q = re.search(r"(?m)^Q: ", body)
    a = list(re.finditer(r"(?m)^A: ", body))
    if not q or not a:
        return dict(
            review_id=m.group(1),
            header=hdr,
            question=body.strip(),
            answer=None,
            file=name,
        )
    question = body[q.end() : a[0].start()]
    answer = body[a[-1].end() :]
    return dict(
        review_id=m.group(1),
        header=hdr,
        question=question.strip(),
        answer=answer.rstrip("\n"),
        file=name,
    )


def review_sort_key(path):
    m = REVIEW_RE.match(os.path.basename(path))
    return int(m.group(1)) if m else 0


def ids_of(s):
    try:
        v = json.loads(s)
    except (TypeError, ValueError):
        return []
    return [str(x) for x in v] if isinstance(v, list) else []


def read_json(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, ValueError):
        return None


def exc_text(e):
    if not e:
        return ""
    if isinstance(e, dict):
        return "%s: %s" % (
            e.get("exception_type", ""),
            str(e.get("exception_message", ""))[:200],
        )
    return str(e)[:200]


def load_runs(rev_dir):
    """One dict per evaluation folder: eval id, attempt, agent, model, run id (or None), reward, status ..."""
    runs = []
    for ed in sorted(glob.glob(os.path.join(rev_dir, "evaluations", "eval_*"))):
        m = EVAL_RE.match(os.path.basename(ed))
        if not m:
            continue
        ef = os.path.join(ed, "eval_files")
        if not os.path.isdir(ef):
            ef = ed
        res = read_json(os.path.join(ef, "result.json")) or {}
        parts = m.group(3).split("__")
        path = ((res.get("config") or {}).get("task") or {}).get("path") or ""
        pm = PATH_RE.search(path)
        rew = ((res.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        if rew is None:
            r2 = read_json(os.path.join(ef, "verifier", "reward.json")) or {}
            rew = r2.get("reward")
        try:
            rew = float(rew) if rew is not None else None
        except (TypeError, ValueError):
            rew = None
        det = os.path.join(ef, "verifier", "reward-details.json")
        runs.append(
            dict(
                eval_id=m.group(1),
                attempt=int(m.group(2)),
                agent=parts[0].upper(),
                model=parts[1] if len(parts) > 1 else "",
                run_id=pm.group(1) if pm else None,
                reward=rew,
                exc=exc_text(res.get("exception_info")),
                started=res.get("started_at") or "",
                details=det if os.path.exists(det) else None,
                folder=os.path.basename(ed),
            )
        )
    return runs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "inputs",
        nargs="+",
        help="one or more zips or extracted folders, then the output folder (last)",
    )
    ap.add_argument("--spec", type=int, default=557)
    ap.add_argument("--any-prompt", action="store_true")
    ap.add_argument("--all-revisions", action="store_true")
    ap.add_argument(
        "--known-prompts",
        default=os.path.join(H, "known_prompts.json"),
        help="sha256 of review prompt text -> saved prompt id",
    )
    a = ap.parse_args(argv)
    if len(a.inputs) < 2:
        ap.error("need at least one INPUT and OUT_EXPORT")
    out = a.inputs[-1]
    if os.name == "nt" and not out.startswith("\\\\?\\"):
        out = "\\\\?\\" + os.path.abspath(out)
    srcs = a.inputs[:-1]
    for d in ("runs", "newruns", "_pkgs", "_dl_stub", "_extracted"):
        os.makedirs(os.path.join(out, d), exist_ok=True)
    roots = []
    for i, s in enumerate(srcs):
        if os.path.isdir(s):
            roots.append(s)
        elif zipfile.is_zipfile(s):
            dest = os.path.join(
                out,
                "_extracted",
                "%d_%s" % (i, re.sub(r"\W+", "_", os.path.basename(s))[:60]),
            )
            os.makedirs(dest, exist_ok=True)
            safe_extract(s, dest)
            roots.append(dest)
        else:
            raise SystemExit("not a zip or folder: %s" % s)
    known = (read_json(a.known_prompts) or {}).get("prompts", {})
    revs = []
    for r in roots:
        revs += find_revs(r)
    notes, chosen = [], {}
    for name, n, t, p in revs:
        chosen.setdefault(name, []).append((n, t, p))
    use = []
    for name, lst in sorted(chosen.items()):
        lst.sort()
        keep = lst if a.all_revisions else [lst[-1]]
        for n, t, p in lst:
            if (n, t, p) not in keep:
                notes.append(
                    "task %s: revision %d (task id %s) skipped, newer revision %d (task id %s) used"
                    % (name, n, t, lst[-1][0], lst[-1][1])
                )
        use += [(name, n, t, p) for n, t, p in keep]
    reviews, not_used, run_rows, mapping, tasks_rows = [], [], [], [], []
    runs_csv, nop, idx, seen = {}, {}, [], set()
    for name, n, t, p in use:
        tasks_rows.append((t, name))
        tf = os.path.join(p, "task_files")
        if os.path.isdir(tf):
            dst = os.path.join(out, "_pkgs", t)
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(tf, dst)
        else:
            notes.append("task %s: no task_files folder, so no package for check 2" % t)
        os.makedirs(os.path.join(out, "_dl_stub", t), exist_ok=True)
        json.dump(
            dict(id=int(t), name=name, revision=n),
            open(os.path.join(out, "_dl_stub", t, "task.json"), "w"),
        )
        # reviews first, so evaluation folders can be matched to run ids
        revw = []
        for mp in sorted(
            glob.glob(os.path.join(p, "verifications", "*.md")), key=review_sort_key
        ):
            pr = parse_review(mp)
            if pr is None:
                notes.append(
                    "task %s: %s is not a review file in the expected shape, skipped"
                    % (t, os.path.basename(mp))
                )
                continue
            revw.append(pr)
        runs = load_runs(p)
        target_ids = set()
        for pr in revw:
            target_ids |= set(ids_of(pr["header"].get("evaluationrun_ids", "")))
        # unmapped runs: fall back to a synthetic id (never guessed from the evaluation id)
        for r in runs:
            how = "result.json config.task.path"
            if r["run_id"] is None:
                r["run_id"] = "e%sa%d" % (r["eval_id"], r["attempt"])
                how = "UNMAPPED (no run id in result.json); synthetic id"
            elif target_ids and r["run_id"] in target_ids:
                how += " + listed in a review evaluationrun_ids"
            elif target_ids:
                how += "; not targeted by any review"
            mapping.append(
                dict(
                    task_id=t,
                    run_id=r["run_id"],
                    eval_folder=r["folder"],
                    eval_id=r["eval_id"],
                    attempt=r["attempt"],
                    agent=r["agent"],
                    model=r["model"],
                    reward=r["reward"],
                    how=how,
                )
            )
        for tid_ in sorted(target_ids - {r["run_id"] for r in runs}):
            notes.append(
                "task %s: review lists run %s but no evaluation folder maps to it"
                % (t, tid_)
            )
        for r in runs:
            rid = r["run_id"]
            status = (
                "PASSED"
                if (r["reward"] is not None and r["reward"] >= 1.0)
                else "FAILED"
            )
            rj = dict(
                id=rid,
                _agent=r["agent"],
                _model=r["model"],
                status=status,
                aggregate_reward=r["reward"],
                created_at=r["started"],
                exception_info=r["exc"],
                evaluation=r["eval_id"],
                attempt_number=r["attempt"],
                _source="with_runs_zip",
            )
            json.dump(rj, open(os.path.join(out, "runs", rid + ".json"), "w"))
            if r["details"]:
                shutil.copy(
                    r["details"],
                    os.path.join(out, "runs", rid + ".reward-details.json"),
                )
            if r["agent"] == "NOP":
                prev = nop.get(t)
                if prev is None or r["started"] >= prev[0]:
                    nop[t] = (r["started"], r["reward"])
                continue
            if rid in seen:
                continue
            seen.add(rid)
            idx.append(
                dict(
                    run_id=rid,
                    agent=r["agent"],
                    status=status,
                    reward=r["reward"],
                    cost_usd="",
                    task_id=t,
                    orig_task_id=t,
                    source="with_runs_zip",
                    detail="reward-details" if r["details"] else "none",
                )
            )
        agent_of = {r["run_id"]: r["agent"] for r in runs}
        k = 0
        for pr in revw:
            h = hashlib.sha256((pr["question"] or "").encode("utf-8")).hexdigest()
            kp = known.get(h) or {}
            pid = kp.get("saved_prompt_id")
            status = pr["header"].get("status", "")
            tids = ids_of(pr["header"].get("task_ids", ""))
            why = ""
            if status != "PASSED":
                why = "status %s" % status
            elif pr["answer"] is None:
                why = "no answer in transcript"
            elif not a.any_prompt and pid != a.spec:
                why = "prompt is %s (%s), not %s (DataOS saved prompt id %d)" % (
                    pid if pid is not None else "not in known_prompts.json",
                    kp.get("name", "unknown text"),
                    next((v.get("name") for v in known.values() if v.get("saved_prompt_id") == a.spec and v.get("name")), "the prompt check 2 needs"),
                    a.spec,
                )
            if tids and t not in tids:
                why = why or "task_ids %s do not include the folder task id %s" % (
                    tids,
                    t,
                )
            if why:
                not_used.append(
                    dict(
                        task_id=t,
                        review_id=pr["review_id"],
                        prompt_id=pid,
                        prompt_name=kp.get("name", ""),
                        prompt_sha256=h[:16],
                        status=status,
                        reason=why,
                    )
                )
                continue
            k += 1
            tr = ids_of(pr["header"].get("evaluationrun_ids", ""))
            reviews.append(
                dict(
                    key="%s-V%d" % (t, k),
                    review_id=int(pr["review_id"]),
                    status=status,
                    token_usage=None,
                    targets_runs=[int(x) if x.isdigit() else x for x in tr],
                    targets_tasks=[int(x) for x in tids],
                    output={"response": pr["answer"]},
                    saved_prompt_id=pid,
                    prompt_sha256=h[:16],
                    model=pr["header"].get("model", ""),
                    agent=pr["header"].get("agent", ""),
                )
            )
            for x in tr:
                runs_csv[x] = agent_of.get(x, "")
        if not revw:
            notes.append("task %s: no verifications folder or no review files" % t)
    with open(os.path.join(out, "results.jsonl"), "w", encoding="utf-8") as f:
        for r in reviews:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(out, "runs.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run_id", "agent"])
        for k_, v in runs_csv.items():
            if v:
                w.writerow([k_, v])
    with open(os.path.join(out, "nop.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["task_id", "nop_reward"])
        for k_, (_c, rew) in sorted(nop.items()):
            w.writerow([k_, rew])
    with open(os.path.join(out, "map.csv"), "w", newline="") as f:
        csv.writer(f).writerow(["copy_task_id", "orig_task_id"])
    with open(os.path.join(out, "tasks.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["task_id", "name", "tab"])
        for t, name in tasks_rows:
            w.writerow([t, name, ""])
    with open(os.path.join(out, "newruns", "index.csv"), "w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "run_id",
                "agent",
                "status",
                "reward",
                "cost_usd",
                "task_id",
                "orig_task_id",
                "source",
                "detail",
            ],
        )
        w.writeheader()
        w.writerows(idx)
    for fn, rows in (("reviews_not_used.csv", not_used), ("run_mapping.csv", mapping)):
        with open(os.path.join(out, fn), "w", newline="", encoding="utf-8") as f:
            cols = list(rows[0]) if rows else ["none"]
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    line = (
        "tasks %d, reviews used %d (not used %d), runs in index %d, nop rows %d, evaluation folders %d"
        % (
            len(tasks_rows),
            len(reviews),
            len(not_used),
            len(idx),
            len(nop),
            len(mapping),
        )
    )
    with open(os.path.join(out, "build_report.txt"), "w") as f:
        f.write(line + "\n" + "\n".join(notes) + "\n")
    print(line)
    for n_ in notes:
        print("note:", n_)
    if not_used:
        print(
            "note: %d review(s) not used (see reviews_not_used.csv): %s"
            % (len(not_used), sorted({x["reason"] for x in not_used}))
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
