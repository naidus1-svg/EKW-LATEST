#!/usr/bin/env python3
"""One command for a whole QC batch: golden-comparison review of every task, merged with the internal review, ranked into HOLD / READ_FIRST / CLEAN.

Runs golden_criterion_review.review() on every bundle in a folder, in parallel, one worker per lane (CLAUDE_CONFIG_DIR). Resumable: a bundle whose output JSON already
exists is skipped. Merges with the internal zero-pass review verdicts when --verdicts is given (a task counts as internally rejected when its first pass is MAJOR
and the adversarial pass is CONFIRMED_MAJOR, the same rule apply_internal_fails.py uses).

Tiers (advisory; nothing here marks a task failed):
  HOLD         internally rejected, OR at least one criterion flagged HOLD_AI (golden Opus 2 of 3 AND the no-golden pass)
  READ_FIRST   at least one criterion flagged READ_FIRST (golden Opus 2 of 3), no HOLD
  CLEAN        no flag
  WIDE_NET     9 or more criteria flagged and no internal rejection: the instruction is probably broad enough to cover them, so read its scope first
                (labelled data: the one task with 9 flags had 0 real defects; hold-review judged 1 of 29 flags on a 58-flag task real)
Measured 2026-10-02 on batches 1 to 5 (97 tasks judged by TFRL and the internal review on the same version): internal review alone caught 18 of 32 TFRL rejections and
blocked 9 of 65 passes; HOLD as defined here caught 22 of 32 and blocked 13 of 65. See README.md in this folder.

Usage:
  python golden_review_batch.py --bundles <dir of .zip bundles or task dirs> --lanes /root/.claude-a2,/root/.claude-j,... --out <outdir> [--verdicts <bN/verdicts>] [--limit N] [--dry-run]
  Lanes may also come from the env var GCR_LANES (comma separated). Run it on a lane host, never on a personal account.
"""

import argparse
import json
import os
import re
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_criterion_review as gcr  # noqa: E402


def find_bundles(folder):
    out = []
    for p in sorted(Path(folder).iterdir()):
        if p.suffix == ".zip" or p.is_dir():
            out.append(
                (re.sub(r"__\d+$", "", p.stem if p.suffix == ".zip" else p.name), p)
            )
    return out


def internal_verdict(verdicts_dir, task):
    """'rejected' / 'passed' / None, from <task>.json (first pass) and <task>.verify.json (adversarial pass)."""
    if not verdicts_dir:
        return None
    base = Path(verdicts_dir)
    names = {task, re.sub(r"^task_", "", task), task.upper(), task.lower()}
    for n in names:
        first = base / (n + ".json")
        if first.exists():
            try:
                v = json.loads(first.read_text(encoding="utf-8")).get("verdict")
                ver = base / (n + ".verify.json")
                overall = (
                    json.loads(ver.read_text(encoding="utf-8")).get("overall")
                    if ver.exists()
                    else None
                )
            except ValueError:
                return None
            return (
                "rejected"
                if v == "MAJOR" and overall == "CONFIRMED_MAJOR"
                else "passed"
            )
    return None


WIDE_NET_MIN = 9


def tier_task(result, internal):
    hold = result.get("hold_ai") or []
    rf = result.get("read_first") or []
    reasons = []
    if internal != "rejected" and len(hold) + len(rf) >= WIDE_NET_MIN:
        return (
            "WIDE_NET",
            "%d criteria flagged: the instruction may be broad enough to cover them; read its scope before any single flag"
            % (len(hold) + len(rf)),
        )
    if internal == "rejected":
        reasons.append("internal review rejected")
    if hold:
        reasons.append("%d criterion(s) flagged HOLD_AI" % len(hold))
    if reasons:
        return "HOLD", "; ".join(reasons)
    if rf:
        return "READ_FIRST", "%d criterion(s) flagged READ_FIRST" % len(rf)
    return "CLEAN", ""


def find_current(current_dir, name):
    """The CURRENT version of a task in a folder of current bundles (same task name, any __id suffix)."""
    if not current_dir:
        return None
    want = re.sub(r"^task_", "", name.lower())
    for p in sorted(Path(current_dir).iterdir()):
        stem = re.sub(r"__\d+$", "", p.stem if p.suffix == ".zip" else p.name).lower()
        if re.sub(r"^task_", "", stem) == want:
            return str(p)
    return None


def run(
    bundles_dir,
    lanes,
    out_dir,
    verdicts_dir=None,
    limit=None,
    workers=None,
    dry_run=False,
    review=None,
    current_dir=None,
):
    review = review or gcr.review
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    items = find_bundles(bundles_dir)[:limit]
    lanes = lanes or [None]
    n_workers = workers or len(lanes)
    lock = threading.Lock()
    counter = {"i": 0}

    def work(item):
        name, path = item
        dst = out / (name + ".json")
        if dst.exists():
            return name, json.loads(dst.read_text(encoding="utf-8")), "resumed"
        with lock:
            lane = lanes[counter["i"] % len(lanes)]
            counter["i"] += 1
        try:
            cur = find_current(current_dir, name)
            res = review(
                str(path),
                config_dir=lane,
                dry_run=dry_run,
                **({"current": cur} if cur else {}),
            )
        except Exception as e:  # noqa: BLE001
            res = {
                "error": "%s: %s" % (type(e).__name__, str(e)[:300]),
                "trace": traceback.format_exc()[-600:],
            }
        if not dry_run:
            dst.write_text(
                json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        return name, res, "ran"

    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        done = list(ex.map(work, items))
    rows = []
    for name, res, how in done:
        internal = internal_verdict(verdicts_dir, name)
        tier, why = (
            ("ERROR", res["error"]) if res.get("error") else tier_task(res, internal)
        )
        rows.append(
            {
                "task": name,
                "tier": tier,
                "why": why,
                "internal": internal,
                "zero_pass_criteria": res.get("zero_pass_criteria", 0),
                "hold_ai": res.get("hold_ai", []),
                "read_first": res.get("read_first", []),
                "how": how,
                "stale": res.get("stale", []),
            }
        )
    order = {"HOLD": 0, "READ_FIRST": 1, "WIDE_NET": 2, "ERROR": 3, "CLEAN": 4}
    rows.sort(key=lambda r: (order[r["tier"]], r["task"]))
    return rows


def write_report(rows, out_dir):
    out = Path(out_dir)
    (out / "report.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    count = {
        t: sum(1 for r in rows if r["tier"] == t)
        for t in ("HOLD", "READ_FIRST", "WIDE_NET", "ERROR", "CLEAN")
    }
    lines = [
        "# Golden-comparison batch review",
        "",
        "%d tasks: %d HOLD, %d READ_FIRST, %d WIDE_NET, %d CLEAN, %d ERROR. Advisory: read each flagged criterion against the prompt and the golden."
        % (
            len(rows),
            count["HOLD"],
            count["READ_FIRST"],
            count["WIDE_NET"],
            count["CLEAN"],
            count["ERROR"],
        ),
        "",
    ]
    for tier in ("HOLD", "READ_FIRST", "WIDE_NET", "ERROR"):
        sel = [r for r in rows if r["tier"] == tier]
        if not sel:
            continue
        lines += [
            "## " + tier,
            "",
            "| Task | Why | Internal review | Criteria |",
            "|---|---|---|---|",
        ]
        for r in sel:
            crits = ", ".join(r["hold_ai"] + r["read_first"]) or "-"
            lines.append(
                "| %s | %s | %s | %s |"
                % (r["task"], r["why"], r["internal"] or "-", crits)
            )
        lines.append("")
    lines += [
        "## CLEAN",
        "",
        ", ".join(r["task"] for r in rows if r["tier"] == "CLEAN") or "-",
        "",
    ]
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return count


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bundles", required=True)
    ap.add_argument("--lanes", default=os.environ.get("GCR_LANES", ""))
    ap.add_argument("--out", required=True)
    ap.add_argument("--verdicts")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--current-dir",
        help="folder holding the CURRENT version of each task (same names): flags whose criterion text changed or vanished there are dropped as STALE",
    )
    a = ap.parse_args(argv)
    lanes = [x for x in a.lanes.split(",") if x]
    rows = run(
        a.bundles,
        lanes,
        a.out,
        a.verdicts,
        a.limit,
        a.workers,
        a.dry_run,
        current_dir=a.current_dir,
    )
    count = write_report(rows, a.out)
    print(json.dumps(count))
    return 0


if __name__ == "__main__":
    sys.exit(main())
