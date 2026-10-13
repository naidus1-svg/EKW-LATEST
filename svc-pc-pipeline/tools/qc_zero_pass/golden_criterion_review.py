#!/usr/bin/env python3
"""Golden-comparison review of zero-pass criteria (advisory read-first / hold list).

For one task bundle, finds every criterion that EVERY solver run failed (at least 2 runs), then asks Opus, three times with the golden answer in view and once without it, whether the
criterion is the problem ("criterion_defect") or the runs missed it ("solver_miss"). Measured 2026-10-02 on 133 TFRL-labelled bundles (see GOLDEN_REVIEW_EVIDENCE.md in this folder): with the instruction-coverage step (a criterion is fair when any prompt sentence, even a broad one, covers what it demands), golden Opus 2 of 3 finds 61 percent of TFRL-confirmed defect criteria at 6.0 percent false flags (precision 41 percent); 2 of 3 AND the no-golden pass finds 45 percent at 2.7 percent (precision 54 percent).
Stacked on the internal review it caught 22 of 32 TFRL rejections and blocked 13 of 65 TFRL-passed tasks (internal review alone: 18 and 9).

Tiers (advisory; nothing here blocks a task by itself):
  HOLD_AI     golden Opus 2 of 3 AND the no-golden Opus pass say criterion_defect
  READ_FIRST  golden Opus 2 of 3 say criterion_defect

Usage:
  python golden_criterion_review.py <bundle.zip | bundle_dir> [--config-dir DIR] [--out FILE] [--passes 3] [--dry-run]
  python golden_criterion_review.py <bundle> --replay-dir DIR     # score saved model replies, no model call (DIR holds gold1.json, gold2.json, gold3.json, base.json)

Needs: the claude CLI on PATH (Max-plan lane; set --config-dir or CLAUDE_CONFIG_DIR to the lane), and markitdown for the golden text.
"""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

MODEL = "opus"
GOLD_CAP = 16000
FILE_CAP = 7000
PROMPT_CAP = 10000
CRIT_CAP = 3500
REASON_CAP = 1500
MAX_RUNS = 6

BASE_RULE = 'You are a QC reviewer. The batch of items is on standard input. Each item gives a TASK PROMPT, ONE grading CRITERION, and, for several independent solver runs that all FAILED this criterion, the grader\'s account of what that run did and why it failed. You see nothing else: no reference answer, no verdict on the task. Use no tools; answer from the text alone.\n\nFor each item decide which of two things happened:\n- "solver_miss": the runs failed for their own reasons (they missed the instruction, got a value wrong, left something out, made different errors). The criterion is fair for the prompt.\n- "criterion_defect": the criterion is the problem. Typical signs: several runs make the SAME defensible choice or reading that the prompt allows and the criterion rejects; the criterion demands a value, label, wording, structure or convention the prompt does not ask for or licence; the criterion cannot be met from the prompt and inputs; or the runs\' answers look right on the prompt\'s own terms.\n\nMethod: first say to yourself what a correct answer requires. Then check whether the failing runs agree with each other on a defensible alternative, or fail in unrelated ways. Give confidence 1 to 3.\n\nYour whole reply must be ONE JSON object and nothing else: {"<item key>": {"verdict": "solver_miss" or "criterion_defect", "why": "one or two sentences quoting the prompt text and what the runs did", "confidence": 1 or 2 or 3}} with an entry for every item key (the key is on each "=====ITEM kNNN=====" line).\n'

GOLD_RULE = 'You are a QC reviewer. The batch is on standard input. It contains one or more TASK blocks. Each block has the TASK PROMPT, the REFERENCE ANSWER (the golden the grading criteria were written from), and several CRITERION ITEMs. Each criterion item gives one grading criterion and, for several independent solver runs that all FAILED it, the grader\'s account of what the run did. Use no tools; answer from the text alone.\n\nFor each criterion item decide:\n- "solver_miss": the runs failed for their own reasons and the criterion is fair for the prompt.\n- "criterion_defect": the criterion is the problem. Compare the criterion with BOTH the prompt and the reference answer. Typical signs: the criterion requires something that appears in the reference answer but that the prompt never asks for or licenses (the golden\'s own assumption, an unsourced figure, an alternative or analysis that exists only in the golden, its particular reading, label, structure or wording); several runs make the same defensible choice the prompt allows; the criterion cannot be met from the prompt and inputs.\n\nDo not flag a criterion because it is hard. Flag it only when the prompt\'s own words do not require or license what the criterion demands. Give confidence 1 to 3.\n\n\nINSTRUCTION-COVERAGE CHECK (required before you answer "criterion_defect"): search the TASK PROMPT for any sentence that covers what the criterion demands, even broadly. Broad wording counts: for example "anything missing, stale, duplicated, unsigned or otherwise unexecuted", "each affected file", "file by file", "where two files disagree, establish which copy governs", "show your work". If such a sentence covers the item the criterion demands, the criterion is fair and the runs missed it: answer "solver_miss". Answer "criterion_defect" only when NO sentence of the prompt covers it (it is the golden\'s own choice), or when the criterion contradicts an explicit prompt sentence (for example the prompt says not to test or opine on something and the criterion requires it). In the "why" field quote the prompt sentence that covers it, or write "no covering sentence".\n\nYour whole reply must be ONE JSON object and nothing else: {"<criterion item key>": {"verdict": "solver_miss" or "criterion_defect", "why": "one sentence naming the prompt text and what the golden adds", "confidence": 1 or 2 or 3}} with an entry for every criterion item key (the key is on each "-----CRITERION ITEM kNNN-----" line).\n'


# the golden answer sits in solution/files in the DataOS shape and in solution/golden_outputs in the harbor shape
GOLDEN_DIRS = ("/solution/files/", "/solution/golden_outputs/")


def _read_members(path):
    """{relative path under task_files/: bytes} for the files this tool needs."""
    out = {}
    want = lambda n: (
        n.endswith("/instruction.md")
        or n.endswith("/task_prompt.txt")
        or n.endswith("judge.toml")
        or n.endswith("verifier.json")
        or any(d in n for d in GOLDEN_DIRS)
        or n.endswith("reward-details.json")
    )
    if str(path).endswith(".zip"):
        z = zipfile.ZipFile(path)
        for n in z.namelist():
            if not n.endswith("/") and want("/" + n):
                out[n] = z.read(n)
    else:
        root = Path(path)
        for p in root.rglob("*"):
            if p.is_file() and want("/" + p.as_posix()):
                out[p.relative_to(root).as_posix()] = p.read_bytes()
    return out


def _golden_text(members):
    try:
        from markitdown import MarkItDown
    except ImportError:
        return "(golden not available: markitdown is not installed)"
    md = MarkItDown()
    parts = []
    tmp = tempfile.mkdtemp()
    for n in sorted(members):
        if not any(d in "/" + n for d in GOLDEN_DIRS):
            continue
        f = Path(tmp) / Path(n).name
        if f.suffix.lower() not in (
            ".docx",
            ".xlsx",
            ".xlsm",
            ".pdf",
            ".md",
            ".txt",
            ".csv",
            ".pptx",
        ):
            continue
        f.write_bytes(members[n])
        try:
            txt = md.convert(str(f)).text_content
        except Exception as e:  # noqa: BLE001
            txt = "(could not extract: %s)" % str(e)[:80]
        parts.append("### GOLDEN FILE %s\n%s" % (f.name, txt[:FILE_CAP]))
    return "\n\n".join(parts)[:GOLD_CAP] or "(golden not available)"


def _graded(node):
    """Every criterion entry in one value of a reward-details.json. It comes in three shapes:
    {"criteria": [...]}, a list of those (judge passes), or a group whose components hold them.
    """
    if isinstance(node, list):
        for x in node:
            yield from _graded(x)
    elif isinstance(node, dict):
        crit = node.get("criteria")
        if isinstance(crit, list):
            yield from (c for c in crit if isinstance(c, dict))
        for k, v in node.items():
            if k != "criteria":
                yield from _graded(v)


def load_bundle(path, golden=True):
    m = _read_members(path)
    prompt = None
    for n, b in m.items():
        if n.endswith("/instruction.md") and "task_files/" in n:
            prompt = b.decode("utf-8", "replace")
    if prompt is None:
        for n, b in m.items():
            if n.endswith("/task_prompt.txt"):
                prompt = b.decode("utf-8", "replace")
    criteria = {}
    for n, b in m.items():
        if n.endswith("judge.toml"):
            d = tomllib.loads(b.decode("utf-8", "replace"))
            for c in d.get("criterion", []):
                criteria[c.get("name", "")] = c.get("description", "")
        elif n.endswith("verifier.json") and "task_files/" in n:
            d = json.loads(b.decode("utf-8", "replace"))
            for v in d.get("verifiers", []):
                a = v.get("assertion", {}) or {}
                rb = a.get("rubric")
                rb = rb.get("prompt", "") if isinstance(rb, dict) else ""
                criteria[v.get("name", "")] = rb or json.dumps(
                    a.get("deterministic", "")
                )
    runs = {}
    for n, b in m.items():
        # a rev_<n>__<id> folder as the root has "evaluations/..." with no folder before it
        n = "/" + n
        if (
            not n.endswith("reward-details.json")
            or "/evaluations/" not in n
            or "oracle" in n.lower()
        ):
            continue
        label = n.split("/evaluations/")[1].split("/")[0].split("__", 1)[-1][:40]
        try:
            d = json.loads(b)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        for key, g in d.items():
            for c in _graded(g):
                rs = c.get("reasoning") or ""
                rs = rs if isinstance(rs, str) else " ".join(str(x) for x in rs)
                name = c.get("name", "")
                # a verifier.json grader calls its criteria v1, v2, ...: that name is the
                # key in reward-details.json, and the criterion itself carries another one
                if key in criteria and name not in criteria:
                    name = key
                runs.setdefault(name, []).append((label, c.get("value"), rs))
    return {
        "prompt": prompt or "",
        "criteria": criteria,
        "runs": runs,
        "golden": _golden_text(m) if golden else "",
    }


def zero_pass(bundle):
    out = []
    for name, rs in bundle["runs"].items():
        vals = [v for _l, v, _r in rs if v is not None]
        if len(vals) < 2 or any(v and float(v) >= 1.0 for v in vals):
            continue
        fails = [(l, r) for l, v, r in rs if v is not None and r]
        if len(fails) >= 2 and name in bundle["criteria"]:
            out.append((name, fails[:MAX_RUNS]))
    return out


def _crit_block(name, key, bundle, fails):
    runs = "\n".join(
        "- RUN %d (%s): %s" % (i + 1, l, r[:REASON_CAP])
        for i, (l, r) in enumerate(fails)
    )
    return (
        "[CRITERION]\n%s\n\n[WHY EACH INDEPENDENT RUN FAILED IT, from the grader]\n%s\n"
        % (bundle["criteria"][name][:CRIT_CAP], runs)
    )


def build_base_input(bundle, zp, keys):
    parts = []
    for (name, fails), key in zip(zp, keys):
        parts.append(
            "=====ITEM %s=====\n[TASK PROMPT]\n%s\n\n%s"
            % (
                key,
                bundle["prompt"][:PROMPT_CAP],
                _crit_block(name, key, bundle, fails),
            )
        )
    return "\n".join(parts)


def build_gold_input(bundle, zp, keys):
    head = (
        "=====TASK task=====\n[TASK PROMPT]\n%s\n\n[REFERENCE ANSWER (the golden the criteria were written from)]\n%s\n"
        % (bundle["prompt"][:PROMPT_CAP], bundle["golden"][:GOLD_CAP])
    )
    crits = "\n".join(
        "-----CRITERION ITEM %s-----\n%s" % (key, _crit_block(name, key, bundle, fails))
        for (name, fails), key in zip(zp, keys)
    )
    return head + "\n" + crits


def parse_reply(text):
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(t)


def claude_argv():
    """The claude command as an argv list: $GCR_CLAUDE when set (tests point it at a fake), else the claude on PATH."""
    raw = os.environ.get("GCR_CLAUDE", "").strip()
    if raw:
        if os.name == "nt":  # POSIX splitting eats the backslashes in Windows paths
            parts = [p.strip('"') for p in shlex.split(raw, posix=False)]
        else:
            parts = shlex.split(raw)
        if parts:
            return parts
    # which() also finds claude.cmd on Windows, where a bare "claude" would not start
    command = shutil.which("claude") or "claude"
    return [command]


def run_claude(rule, stdin_text, model=MODEL, config_dir=None, timeout=1500):
    env = dict(os.environ)
    if config_dir:
        env["CLAUDE_CONFIG_DIR"] = config_dir
    r = subprocess.run(
        claude_argv() + ["-p", "--model", model, "--output-format", "text", rule],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        encoding="utf-8",
    )
    if r.returncode != 0:
        raise RuntimeError("claude exited %s: %s" % (r.returncode, r.stderr[:300]))
    return parse_reply(r.stdout)


def is_defect(v, key):
    x = v.get(key) or {}
    return x.get("verdict") == "criterion_defect"


def tier(gold_replies, base_reply, keys, names):
    out = []
    for key, name in zip(keys, names):
        votes = sum(is_defect(g, key) for g in gold_replies)
        base = is_defect(base_reply, key)
        t = "HOLD_AI" if votes >= 2 and base else "READ_FIRST" if votes >= 2 else None
        out.append(
            {
                "criterion": name,
                "tier": t,
                "golden_votes": votes,
                "golden_passes": len(gold_replies),
                "no_golden_defect": base,
                "why": [
                    ((g.get(key) or {}).get("why") or "")
                    for g in gold_replies
                    if is_defect(g, key)
                ][:1],
            }
        )
    return out


def _norm(t):
    return re.sub(r"\s+", " ", t or "").strip()


def apply_staleness(res, bundle, current_path):
    """A flag is STALE when its criterion is missing from the current version of the task or its text differs there: the authors have changed it since this copy."""
    cur = load_bundle(current_path, golden=False)["criteria"]
    stale = []
    for it in res["items"]:
        if not it.get("tier"):
            continue
        name = it["criterion"]
        if name not in cur:
            it["tier"], it["stale_reason"] = (
                "STALE",
                "criterion no longer exists in the current version",
            )
        elif _norm(cur[name]) != _norm(bundle["criteria"].get(name)):
            it["tier"], it["stale_reason"] = (
                "STALE",
                "criterion text changed in the current version",
            )
        if it["tier"] == "STALE":
            stale.append(name)
    res["stale"] = stale
    res["hold_ai"] = [i["criterion"] for i in res["items"] if i["tier"] == "HOLD_AI"]
    res["read_first"] = [
        i["criterion"] for i in res["items"] if i["tier"] == "READ_FIRST"
    ]


def answered(reply, key):
    """True when a model reply holds a verdict for this item key (a skipped key would otherwise count as 'not a defect')."""
    x = reply.get(key) if isinstance(reply, dict) else None
    return isinstance(x, dict) and x.get("verdict") in (
        "solver_miss",
        "criterion_defect",
    )


def review(
    bundle_path,
    passes=3,
    config_dir=None,
    replay_dir=None,
    dry_run=False,
    current=None,
):
    return review_bundle(
        load_bundle(bundle_path), passes, config_dir, replay_dir, dry_run, current
    )


def review_bundle(
    bundle,
    passes=3,
    config_dir=None,
    replay_dir=None,
    dry_run=False,
    current=None,
):
    """review() on a bundle that load_bundle already read. res["unanswered"] lists the criteria some reply skipped."""
    zp = zero_pass(bundle)
    keys = ["k%03d" % i for i in range(len(zp))]
    names = [n for n, _f in zp]
    base_in, gold_in = build_base_input(bundle, zp, keys), build_gold_input(
        bundle, zp, keys
    )
    res = {
        "zero_pass_criteria": len(zp),
        "prompt_chars": len(base_in) + len(gold_in),
        "items": [],
    }
    if not zp or dry_run:
        res["note"] = "no zero-pass criteria" if not zp else "dry run: nothing sent"
        return res
    if replay_dir:
        gold = [
            json.loads(
                (Path(replay_dir) / ("gold%d.json" % i)).read_text(encoding="utf-8")
            )
            for i in range(1, passes + 1)
        ]
        base = json.loads((Path(replay_dir) / "base.json").read_text(encoding="utf-8"))
    else:
        gold = [
            run_claude(GOLD_RULE, gold_in, config_dir=config_dir) for _ in range(passes)
        ]
        base = run_claude(BASE_RULE, base_in, config_dir=config_dir)
    res["items"] = tier(gold, base, keys, names)
    res["unanswered"] = [
        n for k, n in zip(keys, names) if not all(answered(r, k) for r in gold + [base])
    ]
    res["hold_ai"] = [i["criterion"] for i in res["items"] if i["tier"] == "HOLD_AI"]
    res["read_first"] = [
        i["criterion"] for i in res["items"] if i["tier"] == "READ_FIRST"
    ]
    if current:
        apply_staleness(res, bundle, current)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("bundle")
    ap.add_argument("--config-dir")
    ap.add_argument("--out")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--replay-dir")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--current",
        help="the CURRENT version of the same task (zip or dir): flags whose criterion text changed or vanished there are labelled STALE",
    )
    a = ap.parse_args(argv)
    res = review(a.bundle, a.passes, a.config_dir, a.replay_dir, a.dry_run, a.current)
    txt = json.dumps(res, indent=2, ensure_ascii=False)
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
    print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
