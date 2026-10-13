#!/usr/bin/env python3
"""Automate the Harbor-beta eval request runbook (reference/harbor_evals_quick_guide.md)
so nobody has to hand-run the PowerShell version to get Phase 1's k=1 model-agent
trial on a batch.

Five sub-actions, matching the guide's own five sections:

  package  02_bundle/task_<id>/ -> upload-ready <prefix>-task_<id>/v1/harbor_task/
           (drops solution/, runs the guide's sanitization checklist as hard gates)
  upload   gcloud storage cp the packaged tasks to gs://<bucket>/tasks/,
           then write .harbor_package_ready markers (only after upload succeeds)
  enqueue  POST to /api/internal/harbor-enqueue-eval — dryRun by default,
           --live required for a real (money-spending) enqueue
  status   poll gs://<evals-bucket>/evals/ + /pending/ for completion
  fetch    download finished trials into the exact layout `cycle.py evals` expects

Safety properties (non-negotiable, per the guide's own "Cautions"):
  - dry-run is always the default; a real enqueue needs an explicit --live flag
  - the internal secret is fetched fresh via `gcloud secrets versions access` at
    call time and is never written to disk, logged, or reused across processes
  - this script never touches provider keys, deletes pending markers, purges
    queues, or kills pods — only the documented REST endpoint and the same
    `gcloud storage` operations the guide itself performs
  - .harbor_package_ready markers go up last (after upload) and come down
    immediately after a live enqueue, exactly as the guide specifies

Usage:
  python3 harbor_evals.py package <bundle_dir> <out_dir> --batch-prefix k1-0720 [--only 97,160]
  python3 harbor_evals.py upload  <package_dir> [--project P] [--bucket B] [--yes]
  python3 harbor_evals.py enqueue <package_dir> <out_dir> --base-url URL --k N
                                  --models-file models.json [--live]
  python3 harbor_evals.py status  --batch-prefix k1-0720 --expected-trials N
                                  [--evals-bucket B] [--wait]
  python3 harbor_evals.py fetch   <out_dir>/_eval-runs.csv <out_dir>/03_evals_raw
                                  [--evals-bucket B]
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

DEFAULT_PROJECT = "turing-delivery-apac-dev"
DEFAULT_TASKS_BUCKET = "long-horizon-beta"
DEFAULT_EVALS_BUCKET = "long-horizon-evals-beta"
ENQUEUE_PATH = "/api/internal/harbor-enqueue-eval"
SECRET_NAME = "gdpval_INTERNAL_WORKER_SECRET"
READY_MARKER = ".harbor_package_ready"
JUNK_NAMES = {".DS_Store", "node_modules", "__pycache__"}
TEXT_SUFFIXES = {".md", ".txt", ".toml", ".json", ".yaml", ".yml", ".sh", ".py", ".csv"}


def _find_gcloud() -> str:
    found = shutil.which("gcloud")
    if found:
        return found
    fallback = Path.home() / "google-cloud-sdk" / "bin" / "gcloud"
    if fallback.is_file():
        return str(fallback)
    sys.exit("gcloud not found on PATH or at ~/google-cloud-sdk/bin/gcloud — "
             "install/auth the Google Cloud SDK first "
             "(gcloud auth login; gcloud config set project ...).")


def _gcloud(*args: str, capture: bool = True) -> subprocess.CompletedProcess:
    cmd = [_find_gcloud(), *args]
    return subprocess.run(cmd, capture_output=capture, text=True)


# ── package ──────────────────────────────────────────────────────────────────

def _check_instruction(path: Path) -> str | None:
    if not path.is_file():
        return "instruction.md missing"
    text = path.read_text(encoding="utf-8", errors="replace")
    if "/workspace/output" not in text:
        return "instruction.md never mentions saving to /workspace/output/"
    return None


def _check_task_toml(path: Path) -> str | None:
    if not path.is_file():
        return "task.toml missing"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return f"task.toml does not parse: {e}"
    artifacts = data.get("artifacts") or []
    if not any("/workspace/output" in a for a in artifacts):
        return "task.toml `artifacts` does not reference /workspace/output"
    storage_mb = (data.get("environment") or {}).get("storage_mb")
    if storage_mb is not None and storage_mb > 10240:
        return f"task.toml environment.storage_mb={storage_mb} exceeds the 10240 cap"
    return None


def _check_environment_data(path: Path) -> str | None:
    if not path.is_dir() or not any(f.is_file() for f in path.rglob("*")):
        return "environment/data/ is missing or empty — real input files required, not just links"
    return None


def _check_tests(path: Path) -> str | None:
    test_sh = path / "test.sh"
    if not test_sh.is_file() or test_sh.stat().st_size == 0:
        return "tests/test.sh missing or empty"
    return None


def _check_text_encoding(root: Path) -> list[str]:
    bad = []
    for f in root.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw:
            bad.append(f"{f.relative_to(root)}: contains a NUL byte")
            continue
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            bad.append(f"{f.relative_to(root)}: not valid UTF-8")
    return bad


def _copy_clean(src: Path, dst: Path) -> None:
    """Copy src -> dst, skipping junk names. Caller decides what subtree to copy."""
    for item in src.rglob("*"):
        if any(part in JUNK_NAMES for part in item.relative_to(src).parts):
            continue
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def cmd_package(args: argparse.Namespace) -> int:
    bundle_dir = Path(args.bundle_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    only = {t.strip() for t in (args.only or "").split(",") if t.strip()}

    # A task is any dir that looks like a bundled harbor task (has instruction.md) —
    # not every front names them task_<id> (e.g. Med-OTS/DermOTS bundles use free-form
    # names like "PSORIASIS-1.4"), so don't filter on a "task_" prefix. bundle_dir
    # itself may be a single task (e.g. a bare `task_165/` drop) rather than a
    # multi-task container (e.g. `02_bundle/` with several task_<id>/ subdirs) —
    # support both instead of assuming bundle_dir is always the container.
    if (bundle_dir / "instruction.md").is_file():
        task_dirs = [bundle_dir]
    else:
        task_dirs = sorted(p for p in bundle_dir.iterdir() if p.is_dir() and (p / "instruction.md").is_file())
    incidents: list[tuple[str, str, str]] = []  # (task, level, detail)
    packaged: list[str] = []

    for td in task_dirs:
        tid = td.name
        if only and tid not in only:
            continue
        harbor_id = f"{args.batch_prefix}-{tid}"
        dest_root = out_dir / harbor_id / "v1" / "harbor_task"
        if dest_root.exists():
            shutil.rmtree(dest_root)
        dest_root.mkdir(parents=True)

        # copy everything except solution/ — the agent under eval must never see the golden
        for name in ("instruction.md", "task.toml"):
            src = td / name
            if src.is_file():
                shutil.copy2(src, dest_root / name)
        for name in ("environment", "tests"):
            src = td / name
            if src.is_dir():
                _copy_clean(src, dest_root / name)

        problems = [
            p for p in (
                _check_instruction(dest_root / "instruction.md"),
                _check_task_toml(dest_root / "task.toml"),
                _check_environment_data(dest_root / "environment" / "data"),
                _check_tests(dest_root / "tests"),
            ) if p
        ]
        problems += _check_text_encoding(dest_root)

        if problems:
            for p in problems:
                incidents.append((harbor_id, "ERROR", p))
            shutil.rmtree(out_dir / harbor_id)  # don't ship a task that fails the checklist
            continue

        packaged.append(harbor_id)

    report_lines = [
        f"# Harbor-eval packaging report — {out_dir}",
        "",
        f"- Packaged: **{len(packaged)}**",
        f"- Rejected (failed sanitization checklist): **{len({t for t, _, _ in incidents})}**",
        "",
    ]
    if incidents:
        report_lines += ["## Rejected tasks", "", "| Task | Detail |", "|------|--------|"]
        for tid, _, detail in incidents:
            report_lines.append(f"| {tid} | {detail.replace('|', chr(92) + '|')} |")
        report_lines.append("")
    (out_dir / "_INCIDENTS.md").write_text("\n".join(report_lines))

    print(f"packaged {len(packaged)} task(s) -> {out_dir}")
    if incidents:
        print(f"  {len({t for t, _, _ in incidents})} task(s) rejected — see {out_dir / '_INCIDENTS.md'}")
    return 1 if not packaged else 0


# ── upload ───────────────────────────────────────────────────────────────────

PREFLIGHT_BANNER = """
Before uploading, confirm with the run owner:
  - the batch prefix matches what you're about to upload
  - exact model names and reasoning efforts are agreed
  - k (trials per task per model) is agreed
  - the current beta app URL is correct
  - the enqueue cron is suspended
  - the correct provider keys are deployed
Do NOT repair verifier code, change keys, delete pending markers, purge queues,
or kill pods. Ask an engineer when a check fails.
"""


def cmd_upload(args: argparse.Namespace) -> int:
    package_dir = Path(args.package_dir)
    task_dirs = sorted(p for p in package_dir.iterdir() if p.is_dir())
    if not task_dirs:
        sys.exit(f"no packaged tasks found in {package_dir}")

    print(PREFLIGHT_BANNER)
    print(f"About to upload {len(task_dirs)} task(s) to "
          f"gs://{args.bucket}/tasks/ (project {args.project}).")
    if not args.yes:
        if input("Type 'yes' to continue: ").strip().lower() != "yes":
            print("aborted.")
            return 1

    r = _gcloud("storage", "cp", "-r", *[str(d) for d in task_dirs],
                f"gs://{args.bucket}/tasks/", "--project", args.project, capture=False)
    if r.returncode != 0:
        return r.returncode

    print("upload succeeded — writing ready markers...")
    marker_tmp = Path.cwd() / ".harbor-ready-marker-tmp"
    marker_tmp.write_bytes(b"")
    try:
        for d in task_dirs:
            dest = f"gs://{args.bucket}/tasks/{d.name}/v1/{READY_MARKER}"
            r = _gcloud("storage", "cp", str(marker_tmp), dest,
                        "--project", args.project, capture=False)
            if r.returncode != 0:
                print(f"  WARN: failed to write ready marker for {d.name}")
    finally:
        marker_tmp.unlink(missing_ok=True)
    print(f"ready markers written for {len(task_dirs)} task(s).")
    return 0


# ── enqueue ──────────────────────────────────────────────────────────────────

def _fetch_secret(project: str) -> str:
    r = _gcloud("secrets", "versions", "access", "latest",
                "--secret", SECRET_NAME, "--project", project)
    if r.returncode != 0:
        sys.exit(f"failed to fetch {SECRET_NAME}: {r.stderr.strip()}")
    return r.stdout.strip()


def _ssl_context():
    """Use certifi's CA bundle explicitly — some Python.org macOS installs don't
    wire up the system CA store, which makes the default context fail with
    CERTIFICATE_VERIFY_FAILED even though the server's cert is fine."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _post_enqueue(base_url: str, secret: str, task_id: str, k: int,
                  models: list[dict], dry_run: bool) -> dict:
    import urllib.error
    import urllib.request

    body = json.dumps({"taskId": task_id, "k": k, "models": models, "dryRun": dry_run}).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{ENQUEUE_PATH}",
        data=body,
        method="POST",
        headers={"X-Worker-Secret": secret, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"enqueue call failed for {task_id}: HTTP {e.code} {e.read().decode(errors='replace')}")


def cmd_enqueue(args: argparse.Namespace) -> int:
    package_dir = Path(args.package_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    task_ids = sorted(p.name for p in package_dir.iterdir() if p.is_dir())
    if not task_ids:
        sys.exit(f"no packaged tasks found in {package_dir}")

    models = json.loads(Path(args.models_file).read_text())
    if not isinstance(models, list) or not models:
        sys.exit(f"{args.models_file} must be a JSON array of {{name, provider, reasoningEffort}}")

    expected_trials = len(task_ids) * len(models) * args.k
    print(f"expected trials: {expected_trials} ({len(task_ids)} tasks x "
          f"{len(models)} models x k={args.k})")

    # The endpoint requires a valid worker secret for dryRun calls too — the guide's
    # own script builds the header once and reuses it for both the dry run and the
    # real call, so fetch it fresh here regardless of --live.
    secret = _fetch_secret(args.project)

    # ---- dry run, always ----
    bad = []
    for tid in task_ids:
        resp = _post_enqueue(args.base_url, secret, tid, args.k, models, True)
        enq = resp.get("enqueued") or []
        skip_pending = resp.get("skippedPending") or []
        skip_no_input = resp.get("skippedNoInput") or []
        # the API returns "<task>/v1" (or similar) in `enqueued`, not the bare task
        # id, so match by prefix rather than exact membership
        if not any(e.startswith(tid) for e in enq) or skip_pending or skip_no_input:
            bad.append((tid, resp))
    if bad:
        print(f"dry run found {len(bad)} problem task(s) — not proceeding:")
        for tid, resp in bad:
            print(f"  {tid}: {resp}")
        return 1
    print(f"dry run clean for all {len(task_ids)} task(s).")

    if not args.live:
        print("no --live flag passed — stopping after dry run. "
              "Ready markers are untouched; re-run with --live to actually enqueue.")
        return 0

    # ---- real enqueue ----
    rows = []
    for tid in task_ids:
        resp = _post_enqueue(args.base_url, secret, tid, args.k, models, False)
        rows.append({"task": tid, "execution": resp.get("execution", "")})
    csv_path = out_dir / "_eval-runs.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["task", "execution"])
        w.writeheader()
        w.writerows(rows)
    print(f"enqueued {len(rows)} task(s) live -> {csv_path}")

    secret = None  # drop it from this process's memory as soon as we're done with it

    print("removing ready markers...")
    for tid in task_ids:
        dest = f"gs://{args.bucket}/tasks/{tid}/v1/{READY_MARKER}"
        _gcloud("storage", "rm", dest, "--project", args.project, capture=False)
    print("done. Remember to clear any shell variables holding the secret.")
    return 0


# ── status ───────────────────────────────────────────────────────────────────

def _gcloud_ls(pattern: str, project: str) -> list[str]:
    """`gcloud storage ls` exits non-zero both for "no objects matched" (benign —
    the pattern is just genuinely empty) and for real failures (auth expired,
    permission denied, ...). Conflating the two silently reports a false "0
    results" on a real failure, which is worse than crashing — surface anything
    that isn't the documented empty-match message instead of swallowing it."""
    r = _gcloud("storage", "ls", pattern, "--project", project)
    if r.returncode != 0:
        if "matched no objects" in (r.stderr or ""):
            return []
        sys.exit(f"gcloud storage ls failed (not a benign empty-match) for "
                 f"{pattern!r}:\n{r.stderr.strip()}")
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def _check_statuses(status_urls: list[str], project: str) -> list[dict]:
    out = []
    for url in status_urls:
        r = _gcloud("storage", "cat", url, "--project", project)
        if r.returncode != 0:
            # a real failure here (auth expired, permission denied) would
            # otherwise silently skip escalation checks on this trial — surface it
            print(f"  WARN: could not read {url}: {r.stderr.strip()}")
            continue
        try:
            out.append(json.loads(r.stdout))
        except json.JSONDecodeError:
            continue
    return out


def cmd_status(args: argparse.Namespace) -> int:
    while True:
        status_pattern = (f"gs://{args.evals_bucket}/evals/{args.batch_prefix}-*/v1/"
                          f"execution_*/*/trial_*/trial_status/status.json")
        pending_pattern = f"gs://{args.evals_bucket}/pending/{args.batch_prefix}-*/v1"

        status_urls = _gcloud_ls(status_pattern, args.project)
        pending = _gcloud_ls(pending_pattern, args.project)
        print(f"status files: {len(status_urls)} / {args.expected_trials}   pending: {len(pending)}")

        if status_urls:
            statuses = _check_statuses(status_urls, args.project)
            escalate = [s for s in statuses
                       if s.get("send_to_retry") or s.get("status") not in
                       ("healthy", "warning", "accepted_by_verdict")]
            if escalate:
                print(f"  {len(escalate)} trial(s) need escalation:")
                for s in escalate:
                    print(f"    {s.get('task_id')}/{s.get('model_slug')}/trial_{s.get('trial')}: "
                          f"status={s.get('status')} send_to_retry={s.get('send_to_retry')}")

        ready = len(status_urls) >= args.expected_trials and not pending
        if ready:
            print("batch is ready to fetch.")
            return 0
        if not args.wait:
            return 1
        print(f"  not ready yet, retrying in {args.poll_seconds}s...")
        time.sleep(args.poll_seconds)


# ── fetch ────────────────────────────────────────────────────────────────────

def cmd_fetch(args: argparse.Namespace) -> int:
    runs_csv = Path(args.runs_csv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(runs_csv) as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f"no rows in {runs_csv}")

    problems = []
    for row in rows:
        tid, execution = row["task"], row["execution"]
        dest = out_dir / tid / "v1"
        dest.mkdir(parents=True, exist_ok=True)
        src = f"gs://{args.evals_bucket}/evals/{tid}/v1/execution_{execution}"
        r = _gcloud("storage", "cp", "-r", src, str(dest), "--project", args.project, capture=False)
        if r.returncode != 0:
            problems.append((tid, "download failed"))
            continue
        exec_dir = dest / f"execution_{execution}"
        for status_file in exec_dir.rglob("trial_status/status.json"):
            try:
                status = json.loads(status_file.read_text())
            except json.JSONDecodeError:
                problems.append((tid, f"{status_file}: unreadable status.json"))
                continue
            if status.get("send_to_retry"):
                problems.append((tid, f"{status_file.parent.parent}: send_to_retry=true"))
            trial_dir = status_file.parent.parent
            if not (trial_dir / "job").exists() or not list(trial_dir.rglob("verifier/reward.json")):
                problems.append((tid, f"{trial_dir}: missing verifier/reward.json"))
            if (trial_dir / "job" / "result.json").exists():
                problems.append((tid, f"{trial_dir}: unexpected top-level job/result.json"))

    print(f"fetched {len(rows)} task(s) -> {out_dir}")
    if problems:
        print(f"  {len(problems)} problem(s) found — review before treating the batch as delivered:")
        for tid, detail in problems:
            print(f"    {tid}: {detail}")
    print(f"next: python3 cycle.py evals <date> {out_dir}")
    return 1 if problems else 0


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="action", required=True)

    pk = sub.add_parser("package")
    pk.add_argument("bundle_dir")
    pk.add_argument("out_dir")
    pk.add_argument("--batch-prefix", required=True)
    pk.add_argument("--only", default="")
    pk.set_defaults(fn=cmd_package)

    up = sub.add_parser("upload")
    up.add_argument("package_dir")
    up.add_argument("--project", default=DEFAULT_PROJECT)
    up.add_argument("--bucket", default=DEFAULT_TASKS_BUCKET)
    up.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    up.set_defaults(fn=cmd_upload)

    en = sub.add_parser("enqueue")
    en.add_argument("package_dir")
    en.add_argument("out_dir")
    en.add_argument("--base-url", required=True)
    en.add_argument("--k", type=int, required=True)
    en.add_argument("--models-file", required=True)
    en.add_argument("--project", default=DEFAULT_PROJECT)
    en.add_argument("--bucket", default=DEFAULT_TASKS_BUCKET)
    en.add_argument("--live", action="store_true",
                    help="actually enqueue (real spend); omit for dry-run only")
    en.set_defaults(fn=cmd_enqueue)

    st = sub.add_parser("status")
    st.add_argument("--batch-prefix", required=True)
    st.add_argument("--expected-trials", type=int, required=True)
    st.add_argument("--project", default=DEFAULT_PROJECT)
    st.add_argument("--evals-bucket", default=DEFAULT_EVALS_BUCKET)
    st.add_argument("--wait", action="store_true")
    st.add_argument("--poll-seconds", type=int, default=120)
    st.set_defaults(fn=cmd_status)

    fe = sub.add_parser("fetch")
    fe.add_argument("runs_csv")
    fe.add_argument("out_dir")
    fe.add_argument("--project", default=DEFAULT_PROJECT)
    fe.add_argument("--evals-bucket", default=DEFAULT_EVALS_BUCKET)
    fe.set_defaults(fn=cmd_fetch)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
