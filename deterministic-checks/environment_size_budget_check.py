#!/usr/bin/env python3
r"""Environment size-budget and within-task duplicate-file check.

Provenance: GLM's round 27/28 coverage synthesis flagged "Class 6: oversized inlined
environment, no package-size budget" as a gap, citing SVC-PC-41-4-0's environment as
"~19MB, roughly 2x a ~10MB guidance figure" and citing other tasks at "15.4MB and 55MB
(5.5x guidance)". Built 2026-09-15 to close that gap -- but the ~10MB guidance figure was
never checked against the real corpus before this session, and it does not survive contact
with it (see Calibration below). Two independent, separately-reported defect shapes live in
this one script because they were investigated together and the corpus-size context needed
for one (the real distribution) was cheap to reuse for the other:

  1. oversized_environment: this task's environment workspace (environment/initial_workspace/
     for SVC-PC, environment/data/ for EKW -- same WORKSPACE_DIRNAME_BY_FORMAT split
     environment_input_check.py already established, reused here rather than re-derived) totals
     more than a calibrated size budget. A large environment bloats the package that ships to
     DataOS and to every solver, and is worth a human look even when nothing inside it is
     individually wrong.
  2. duplicate_environment_file: two or more files anywhere under that same workspace, at any
     size, share identical MD5 content under different names. This is independent of the size
     finding and fires even on a workspace well under budget. Whether any GIVEN pair is
     byte-identical needs no calibration -- that part is a fact, not a threshold -- but whether
     firing on it should read as "fail" does need calibration, and got it: see "Duplicate-file
     severity" below, added after running this check against a real 202-task sample showed the
     naive "always fail" framing this defect shape was originally pitched under does not survive
     contact with the corpus any better than the 10MB size guidance did.

## Calibration (RAN this session against the real corpus, not the guidance figure)

The ~10MB guidance figure this check's brief cited was checked against a full, cheap (stat-only,
no hashing needed) scan of every one of the 600 real task directories under
`03_dataos_ready/` (11.5s total). It does not hold up:

    n=600  min=0.04MB  p10=0.60MB  p25=5.41MB  p50=13.26MB  p75=21.45MB
           p90=24.70MB  p95=54.08MB  p99=54.38MB  max=58.82MB  mean=15.05MB

The median task (13.26MB) already exceeds the 10MB guidance figure, and 373/600 tasks (62%)
are over 10MB. A 10MB threshold would flag a majority of the corpus -- the exact "universal
noise" failure mode this check's own brief warned against, just from the opposite direction
(the guidance was too LOW relative to the real median, not too high).

The real distribution is bimodal with a sharp, empty gap, not a smooth tail: a fine-grained
2MB-bucket histogram over the full corpus shows continuous mass from 0MB up to 28.66MB, then
**zero tasks anywhere in [30MB, 54MB)** (confirmed by re-querying the exact boundary: counts for
>=30MB, >=35MB, >=40MB, and >=45MB are all identically 37), then a second, tight cluster of
exactly 37 tasks packed into 54.08-55.82MB. The top-20-by-size listing shows every one of those
37 tasks carries ~1182-1184 files, roughly 5-6x the file count of a typical task (SVC-PC-41-4-0,
the brief's own cited example, has 218) -- consistent with a genuinely different task template
that legitimately ships more reference files, not "the same tasks, just more bloated." This
check does not attempt to adjudicate that root cause; it only reports that these 37 are cleanly,
structurally separated from the other 563, which is the actual, data-grounded definition of
"outlier" a budget check should use.

DEFAULT_THRESHOLD_BYTES is therefore set to 35MB (36,700,160 bytes) -- inside the real empty gap
or with wide margin on the finding side (its wide gap tapers below, this only 46MB from the top
end and ~5MB clear of the top of the main population, safely reflecting the real corpus, not the
originally-cited guidance number). Consequences worth stating plainly rather than burying:

  - This threshold flags exactly the 37-task cluster (6.2% of the corpus) -- a small, genuinely
    separated minority, not universal noise.
  - It does NOT flag SVC-PC-41-4-0 (18.47MB) on size. Measured directly this session: 18.47MB
    sits at roughly the p65 mark of the real distribution -- normal, not an outlier, by the
    corpus's own shape, whatever the 10MB guidance figure implied. All seven SVC-PC-41-x
    siblings (41-0 through 41-6) measure 3.95-21.93MB, also all inside the normal population.
  - The "15.4MB" figure the brief also cited is, like 41-4-0, an ordinary value near this
    corpus's own mean (15.05MB) and median (13.26MB) -- not an outlier by this distribution
    either, whichever real task it was rounded from.
  - The "55MB" figure the brief cited DOES match this check's flagged cluster precisely --
    that part of the original synthesis holds up against the real data.
  - SVC-PC-41-4-0 still fires on THIS check, just on finding kind 2 (duplicate_environment_file),
    confirmed below -- the size claim about that task did not hold up, but the file the brief
    named as suspicious in it (capacity_tmp_conv.doc) genuinely is a build-residue duplicate.

`--threshold-mb` overrides this at the CLI for anyone who wants to recompute against a different
number; the distribution above is also in this script's own `--out` JSON aggregate
(`corpus_context` key) so a future recalibration has the same numbers to check against, not just
this docstring's prose.

## Duplicate-file severity (RAN this session against a real 202-task sample, not assumed)

The brief motivating this check framed a within-task MD5 duplicate as unconditionally
fail-worthy ("should never ship, at any size"). Running the finished check against all 202
tasks in Khiem's own sample (`--jobs 8`, 15.5s wall time) shows that framing does not survive
contact with the real corpus either, for a different reason than the size threshold did:

    118/202 tasks (58.4%) have at least one duplicate_environment_file finding -- 204 groups
    total, 46.77MB of duplicate-copy bytes. But those 204 groups resolve to only 28 DISTINCT
    MD5s, and two of them dominate completely: md5 adfc4b9c... (capacity_tmp_conv.doc, the
    exact file this check's brief named) appears in 88/202 tasks; md5 c33a2b1e... (a
    FY2021_Legal_Status_and_Risk_Report.docx / _v2.docx pair) appears in 84/202. The other 26
    MD5s appear in 1-3 tasks each.

That shape means the two dominant duplicates are not 88 and 84 independent per-task authoring
mistakes -- they are ONE shared-source artifact each (a "Company Shared Drive__Operations" and
a "Company Shared Drive__Legal" subtree reused as environment material across many different
tasks), inherited wholesale by every task whose environment happens to include that subtree.
Fixing either is a single upstream edit to the shared source material, not 88 or 84 separate
per-task fixes -- and per-task "fail" severity would imply the latter.

The long tail is also not uniformly "build residue." Spot-checked SVC-PC-12-1-0's own singleton
duplicate directly: `Brian_Q4_Pipeline_Tracker.xlsx` and `Elena_Q4_Pipeline_Tracker.xlsx` each
appear once at the workspace root AND once under a nested `L1-00-00/` source-tree copy, and
`instruction.md` names both files by their bare filename ("Brian's ... Brian_Q4_Pipeline_
Tracker.xlsx"). Read directly: this is a flat convenience copy placed where a bare-filename
instruction reference resolves naturally, alongside the full nested source tree kept intact --
a deliberate build convention, not a leftover temp file, even though the bytes are identical
under this check's own definition of "duplicate." Several other singleton groups in the sample
(Shipping_Rate_Card_2021.xlsx, 2022_Benefits_Broker_Quote_Woodruff_Sawyer.xlsx, and others,
all root-plus-nested-copy pairs) match the same shape on inspection.

Conclusion: this check still REPORTS every MD5 duplicate it finds -- detection stays exactly as
specified, unconditional, no filename heuristics, two files are either byte-identical or they
are not -- but severity defaults to **warn**, not fail, for the whole finding kind. A blanket
fail would put 58% of a real sample into a status this codebase treats as a per-task hard
defect, for a pattern that is dominated by a shared-source issue plus a plausibly-intentional
convenience-copy convention, neither of which is "this task's author shipped something broken."
Every finding still carries the full file list and MD5 so a human loses no information; the
aggregate report additionally surfaces `top_duplicate_hashes` (which MD5s recur across how many
tasks in THIS run) precisely so a reviewer sees "fix these two shared files once" rather than
"triage 118 unrelated tasks." `--fail-on-duplicate` is available for anyone who wants the
original unconditional-fail behavior once the two dominant shared-source files are fixed
upstream and the remaining signal is more plausibly per-task.

Reconfirmed at full-corpus scale after the long-path fix below (see "Verification"): 392/600
tasks (65.3%), 642 groups, 46 distinct MD5s, 139.72MB wasted -- and the same two hashes still
dominate completely (291 and 285 of the 600 tasks respectively). The 202-task sample's shape was
not a sampling artifact.

## Verification (RAN this session, real files, real hashes)

SVC-PC-41-4-0's `environment/initial_workspace/` (218 files under a nested `_corpus_subtree/`,
not flat -- this check walks recursively via `os.walk`, matching `source_truncation_check.py`'s
own walk, so nesting depth does not matter): measured 19,365,412 bytes (18.47MB) directly with
`os.walk` + `os.path.getsize`, not estimated. `certutil -hashfile MD5` against every file in
`Company Shared Drive__Operations/` confirms `capacity_tmp_conv.doc` (427,434 bytes) and
`FY2022 Ops Capacity & Headcount Plan (final).doc` (427,434 bytes, note: no "($4-5M)" in the
real filename and "&" not "and" -- the brief's paraphrase of the filename was imprecise, the
duplicate itself is real) share MD5 `adfc4b9c7ab299f98c7ce92a7e4e6583`. Also hashed, individually,
the other three similarly-named files in the same directory (`($4-5M) (final)(1).doc`,
`($4-5M) (final).doc`, `($4-5M, 20-22 FTE) (final).doc`): each has its own distinct MD5, so
those three are near-duplicate BY NAME only, not by content -- exactly the class this check's
"Known limits" section below says it cannot see, and correctly does not flag. This script's own
run against the full task finds exactly the one real pair, matching this manual check.

Full 202-task sample run (`--jobs 8`, real wall time 15.5-51s across two runs -- the range
itself is disclosed rather than picking the faster number, see "A note on timing" below): 118
warn / 84 pass, 19 tasks over the 35MB size budget, 118 tasks with at least one duplicate group,
204 duplicate groups / 28 distinct MD5s total, 46.77MB of duplicate-copy bytes -- see
"Duplicate-file severity" above for what that shape means for the severity default.

A real long-path failure was found and fixed during this verification, not merely disclosed: the
first full-202-task run showed 19 tasks each dropping exactly one file with `[WinError 3] The
system cannot find the path specified` -- a real 272-character path under SVC-PC-1-2-0 (one of
several tasks in the >1180-file cluster, all built from a "Company Shared Drive" subtree deep
enough to exceed Windows' 260-char MAX_PATH). Confirmed directly (`os.stat` on the plain path
fails, the identical call with a `\\?\` extended-length prefix succeeds and reads real content),
then fixed in `_stat_size`/`_hash_file` (fallback to the prefixed path on OSError) and an
`onerror` callback added to the `os.walk` call in case a whole subtree, not just one filename,
was ever silently dropped (not observed on the real corpus -- every affected task showed exactly
one file-level failure, never a missing subtree). A full re-run of all 600 real tasks through
this SHIPPED script (`--all --jobs 8`, 2m39s, see CORPUS_CONTEXT_2026_09_15's
`full_corpus_*` keys) shows zero remaining errors on any task, 37 tasks over the size budget
(exactly the cluster identified by the original stat-only scan), and 392/600 tasks (65.3%) with
at least one duplicate group -- confirming the 202-task sample's severity shape held at full
scale, not by sampling luck.

A note on timing, stated plainly rather than picking the flattering number: the SAME 202-task
command measured 15.5s on one run and 51.5s on another (filesystem cache state differs between
runs -- this check does real file I/O, hashing every non-empty file, so a cold cache costs real
wall time). The full-600-task run (2m39s) is the more representative number for "how long does
this take in practice" and the one carried in this script's own `--jobs`/CLI docs.

## Known limits, disclosed rather than silently dropped

  - Zero-byte files are excluded from duplicate detection (MIN_DUPLICATE_SIZE_BYTES=1 gates the
    hash step). Two empty files are byte-identical by vacuous truth, not because of any real
    content correlation -- flagging them would be noise, not a finding.
  - MD5 is used for content identity, not cryptographic security -- collision resistance is
    irrelevant here (this never runs against adversarial input; a task's own shipped files are
    not attacker-controlled). Chosen over SHA-256 only for speed on repeated full-corpus runs;
    swap `hashlib.md5` for `hashlib.sha256` in `_hash_file` if that assumption ever stops holding.
  - "Duplicate" means byte-identical content under different names in the SAME task's workspace.
    Two files with different content that a human would call "near-duplicate" (the four
    similarly-named capacity/headcount .doc variants in SVC-PC-41-4-0's own Operations folder,
    three of which are NOT byte-identical to each other or to anything else) are invisible to
    this check by design -- that is a semantic/near-duplicate detection problem, a different and
    much harder check than this one, not attempted here.
  - This check never compares across tasks, only within one task's own workspace -- it reports a
    finding per task, computed from that task's own files alone. A file duplicated across two
    DIFFERENT tasks' environments (e.g. the same shared company template reused by many tasks)
    is out of scope for the per-task finding, but the aggregate report's `top_duplicate_hashes`
    breaks the within-task findings down by MD5 across the whole run specifically so that
    cross-task pattern (one shared-source file inherited by many tasks, see "Duplicate-file
    severity" above) is visible in the aggregate even though each per-task finding only ever
    describes that one task's own files.
  - Not every within-task MD5 duplicate is build residue. Confirmed directly this session
    (SVC-PC-12-1-0, see "Duplicate-file severity" above): a flat root-level copy of a file
    `instruction.md` names by its bare filename, sitting alongside a nested copy of the same
    file inside a preserved source-tree directory, is a plausible deliberate convenience-copy
    convention, not a mistake -- even though the bytes are identical under this check's
    definition. This check reports the fact of the duplicate; it does not and cannot judge intent
    from the filesystem alone, which is the main reason severity defaults to warn rather than
    fail (see above).
  - The size-budget threshold is calibrated against SVC-PC's real distribution only. EKW tasks
    are walked with the same code path (environment/data/, via the same WORKSPACE_DIRNAME_BY_FORMAT
    dict environment_input_check.py defines) but this session did not run the same corpus-wide
    stat scan against the EKW corpus, so the 35MB threshold is applied to EKW tasks without an
    EKW-specific calibration check. Disclosed rather than assumed identical.

## OS-metadata exclusion from duplicate detection (RAN 2026-09-16 against real bytes, not assumed)

A second GLM-authored mirror check (independently built, not a fork of this file -- its own
"Duplicate findings are ALWAYS fail severity" design differs from this file's calibrated
warn-by-default) flagged a real-sounding risk: OS Finder metadata files (.DS_Store etc.) could
collide by MD5 and trip a false duplicate finding, "confirmed" via a 19/202-task, 14-files-at-
exactly-6148-bytes same-SIZE cluster in a text-only reconstructed corpus (that corpus has no
real file bytes, only sizes from a listing). Checked directly against this file's own real
600-task corpus before trusting that claim: 37/600 tasks (6.2%) carry .DS_Store files, 629
files total, same 14x6148B + 2x8196B + 1x14340B per-task shape confirmed real. But hashing
every one of those 629 real files directly (MD5, not size) found **zero** collisions, within a
task or across the whole corpus -- confirmed by cross-referencing every duplicate_environment_file
group this script's own full-corpus run (600 tasks, --fail-on-duplicate) produced: none contains
a .DS_Store (or any other OS-metadata) path. The same-size same-role files (e.g. fourteen
per-user "My Drive" folders' .DS_Store, all 6148 bytes) are NOT byte-identical to each other on
this real corpus -- each encodes different per-directory Finder state. The claimed failure mode
does not reproduce against real data; the size-only proxy the reconstructed corpus was limited
to overstated it.

The exclusion below is still added, as a real, unconditionally-safe improvement rather than a
fix to an observed defect: it is name-based (matches the widely-known OS/tooling metadata
filenames regardless of content), so it can only ever remove already-inert files from the
hashing pass -- confirmed by re-running the full 600-task corpus after adding it, both in
default mode and with --fail-on-duplicate: identical status counts and an identical fail-set
(392 tasks) either way, i.e. zero verdict changes on any real task. It also skips hashing 629
files this session confirmed never contribute a real finding, and closes the exposure if a
future corpus refresh ever does produce byte-identical OS metadata (plausible in principle --
just not what this corpus's actual bytes show today).

CLI (matches this folder's other "std"-style checks -- harness_fragility_check.py's argparse
shape, find_task_dirs, UTF-8 stdout/stderr reconfigure -- and source_truncation_check.py's
--jobs/ProcessPoolExecutor pattern for the hashing pass, since that is the expensive part here):

    python environment_size_budget_check.py <TASK-ID> [<TASK-ID> ...] --root <path> --out report.json
    python environment_size_budget_check.py --all --root <path> --id-prefix SVC-PC- --out report.json
    python environment_size_budget_check.py --all --root <path> --threshold-mb 35 --jobs 8 --out report.json
    python environment_size_budget_check.py --all --root <path> --fail-on-duplicate --out report.json

Exit code: 0 always (matches harness_fragility_check.py's convention -- these are warn-level
disclosures for a human to triage, never a hard gate on their own). Stdlib only.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

for _stream in (sys.stdout, sys.stderr):  # unicode task/file names on a cp1252 console
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from ekw_verifier_json import has_ekw_config  # noqa: E402

# ---------------------------------------------------------------------------
# format / workspace-dir resolution -- reused verbatim from environment_input_check.py's own
# WORKSPACE_DIRNAME_BY_FORMAT / detect_task_format / resolve_workspace_dir, so this check can
# never disagree with that one about which directory a given task's "environment" actually is.
# ---------------------------------------------------------------------------

WORKSPACE_DIRNAME_BY_FORMAT = {"svc_pc": "initial_workspace", "ekw": "data"}

# Calibrated against the real 600-task SVC-PC corpus this session (see module docstring
# "Calibration"): the real distribution has an empty gap in [30MB, 54MB), so 35MB sits well
# inside it. 1MB == 1024*1024 bytes here, matching source_truncation_check.py's
# SVC_PC_MAX_FILE_SIZE convention, not decimal MB.
DEFAULT_THRESHOLD_BYTES = 35 * 1024 * 1024

# Real corpus-wide size distribution (bytes), measured this session over all 600 SVC-PC tasks
# under 03_dataos_ready/ two ways: first a stat-only os.walk scratch scan (11.5s, no hashing,
# before the long-path fix below existed), then reconfirmed by this SHIPPED script's own --all
# run (--jobs 8, 2m39s, full stat+MD5 hashing pass, zero remaining errors on any of the 600
# tasks -- the long-path fallback in _stat_size/_hash_file resolves every WinError 3 the first
# pass hit). The two runs agree to within the one previously-dropped file's ~9KB (max moved
# 58.82->58.83MB); the numbers below are the second, authoritative, error-free run. Carried here
# (not just in the docstring) so --out JSON always ships the numbers a future recalibration
# needs, and so a report reader never has to trust the docstring's prose without the data behind
# it.
CORPUS_CONTEXT_2026_09_15 = {
    "measured": "2026-09-15",
    "root": r"C:\ekwqc\repo\pipeline\data\svc_pc_qc\03_dataos_ready",
    "n_tasks": 600,
    "method": "this script's own --all --jobs 8 run (full stat+MD5 pass, 2m39s, 0 errors)",
    "min_mb": 0.04,
    "p10_mb": 0.60,
    "p25_mb": 5.41,
    "p50_mb": 13.26,
    "p75_mb": 21.45,
    "p90_mb": 24.70,
    "p95_mb": 54.08,
    "p99_mb": 54.39,
    "max_mb": 58.83,
    "mean_mb": 15.05,
    "empty_gap_mb": [30, 54],
    "n_in_top_cluster": 37,
    "top_cluster_range_mb": [54.08, 55.82],
    "top_cluster_typical_file_count": "~1182-1184 (vs. ~218 for SVC-PC-41-4-0, a normal-range task)",
    "full_corpus_n_tasks_oversized_at_35mb": 37,
    "full_corpus_n_tasks_with_duplicate_files": 392,
    "full_corpus_n_duplicate_groups": 642,
    "full_corpus_duplicate_wasted_mb": 139.72,
    "full_corpus_top_2_duplicate_hashes_n_tasks": [291, 285],
}

# Zero-byte files are excluded from duplicate detection -- see module docstring "Known limits".
MIN_DUPLICATE_SIZE_BYTES = 1

# OS/tooling metadata filenames excluded from duplicate grouping (name-based, not content- or
# size-based -- see module docstring "OS-metadata exclusion from duplicate detection" for why
# this was added and what was and was not confirmed against the real corpus). Basename match is
# case-insensitive (Windows filesystems are case-insensitive and no real task content file is
# ever named exactly one of these). __MACOSX is a directory macOS Archive Utility writes inside
# zips it creates; matched as a path segment, not a basename, since the files inside it are the
# noise, not the directory itself.
OS_METADATA_BASENAMES_LOWER = frozenset(
    {".ds_store", "thumbs.db", "desktop.ini", ".localized"}
)
OS_METADATA_PATH_SEGMENTS_LOWER = frozenset({"__macosx"})


def _is_os_metadata(p: Path) -> bool:
    """True if p is a known OS/tooling metadata file that must never contribute to a
    duplicate_environment_file finding. See OS_METADATA_BASENAMES_LOWER above."""
    if p.name.lower() in OS_METADATA_BASENAMES_LOWER:
        return True
    return any(part.lower() in OS_METADATA_PATH_SEGMENTS_LOWER for part in p.parts)


def _has_svc_pc_config(task_dir: Path) -> bool:
    """Same unrestricted glob deliverable_filename_check.py's and environment_input_check.py's
    own _has_svc_pc_config() use, so no script in this folder can disagree about format.
    """
    tests_dir = task_dir / "tests"
    if not tests_dir.is_dir():
        return False
    return any(tests_dir.glob("*/judge.toml"))


def detect_task_format(task_dir: Path) -> str:
    """Returns "svc_pc" or "ekw". SVC-PC wins whenever its config exists (same precedence
    environment_input_check.py uses); a task with neither shape defaults to "svc_pc"."""
    if _has_svc_pc_config(task_dir):
        return "svc_pc"
    if has_ekw_config(task_dir):
        return "ekw"
    return "svc_pc"


def resolve_workspace_dir(task_dir: Path) -> tuple[Path, str]:
    """Returns (ws_dir, task_format). ws_dir is environment/initial_workspace/ for SVC-PC,
    environment/data/ for EKW."""
    task_format = detect_task_format(task_dir)
    return (
        task_dir / "environment" / WORKSPACE_DIRNAME_BY_FORMAT[task_format],
        task_format,
    )


def find_task_dirs(
    root: Path, task_ids: list[str] | None = None, id_prefix: str = ""
) -> list[Path]:
    if task_ids:
        dirs = []
        for tid in task_ids:
            p = root / tid
            if not p.is_dir():
                print(f"WARNING: task dir not found, skipping: {p}", file=sys.stderr)
                continue
            dirs.append(p)
        return dirs
    return sorted(
        p for p in root.iterdir() if p.is_dir() and p.name.startswith(id_prefix)
    )


def _winlong(p: Path) -> str:
    """Windows extended-length (\\\\?\\) path prefix -- a fallback for a real subset of this
    corpus's deeply-nested _corpus_subtree paths that exceed the 260-char MAX_PATH limit.
    Confirmed this session: a real 272-char path under SVC-PC-1-2-0 throws WinError 3 ("The
    system cannot find the path specified") on a plain stat/open, and resolves cleanly with this
    prefix (stat and read both succeed). No-op on non-Windows; only ever tried as a fallback
    after a plain access already raised OSError, so this never changes behavior for the (vast
    majority) of paths under the limit."""
    s = str(p)
    if os.name == "nt" and not s.startswith("\\\\?\\"):
        s = str(Path(s).resolve())
        if not s.startswith("\\\\?\\"):
            s = "\\\\?\\" + s
    return s


def _stat_size(p: Path) -> int:
    """os.stat().st_size with a long-path fallback -- see _winlong."""
    try:
        return p.stat().st_size
    except OSError:
        if os.name != "nt":
            raise
        return os.stat(_winlong(p)).st_size


def _hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.md5()
    try:
        f = open(path, "rb")
    except OSError:
        if os.name != "nt":
            raise
        f = open(_winlong(path), "rb")
    with f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# per-task analysis
# ---------------------------------------------------------------------------


def analyze_task(
    task_dir: Path, threshold_bytes: int, fail_on_duplicate: bool = False
) -> dict[str, Any]:
    """Returns one result dict for one task. Never raises -- any per-file OSError is
    collected into errors/stat_errors/hash_errors, never allowed to abort the whole task.
    fail_on_duplicate reverts duplicate_environment_file findings to the originally-pitched
    unconditional "fail" severity instead of the corpus-calibrated default "warn" -- see module
    docstring "Duplicate-file severity" for why warn is the default.
    """
    task_id = task_dir.name
    ws_dir, task_format = resolve_workspace_dir(task_dir)
    try:
        rel_ws = str(ws_dir.relative_to(task_dir)).replace("\\", "/")
    except ValueError:
        rel_ws = str(ws_dir)

    result: dict[str, Any] = {
        "task_id": task_id,
        "format": task_format,
        "workspace_rel": rel_ws,
        "workspace_exists": ws_dir.is_dir(),
        "size_budget": None,
        "duplicate_files": None,
        "findings": [],
        "n_findings": 0,
        "status": None,
        "errors": [],
    }

    if not ws_dir.is_dir():
        result["status"] = "skip"
        result["errors"].append(f"no {rel_ws} directory found for this task")
        return result

    files: list[tuple[Path, int]] = []
    stat_errors: list[str] = []
    walk_errors: list[str] = []
    total_bytes = 0

    # onerror: os.walk's default silently drops a directory it cannot scandir (e.g. the same
    # long-path class _winlong works around, but at the DIRECTORY level, not just the final
    # filename) -- that would silently undercount rather than report a stat_error, so this
    # records it instead of letting os.walk swallow it. Not seen on the real corpus this
    # session (every affected task showed exactly the file-level WinError _stat_size now
    # recovers from, never a missing subtree), but disclosed rather than assumed impossible.
    def _on_walk_error(exc: OSError) -> None:
        walk_errors.append(str(exc))

    for dirpath, _dirnames, filenames in os.walk(ws_dir, onerror=_on_walk_error):
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                size = _stat_size(p)
            except OSError as e:
                stat_errors.append(f"{p}: {e}")
                continue
            total_bytes += size
            files.append((p, size))

    n_files = len(files)
    over_budget = total_bytes > threshold_bytes
    result["size_budget"] = {
        "outcome": "checked",
        "n_files": n_files,
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / (1024 * 1024), 2),
        "threshold_bytes": threshold_bytes,
        "threshold_mb": round(threshold_bytes / (1024 * 1024), 2),
        "over_budget": over_budget,
        "walk_errors": walk_errors,
        "ratio_to_threshold": (
            round(total_bytes / threshold_bytes, 2) if threshold_bytes else None
        ),
        "stat_errors": stat_errors,
    }

    findings: list[dict[str, Any]] = []
    if over_budget:
        findings.append(
            {
                "kind": "oversized_environment",
                "severity": "warn",
                "detail": (
                    f"{rel_ws} totals {total_bytes / (1024 * 1024):.2f} MB across {n_files} "
                    f"files, {total_bytes / threshold_bytes:.1f}x the calibrated "
                    f"{threshold_bytes / (1024 * 1024):.0f} MB budget (see module docstring "
                    f"Calibration for how this threshold was derived from the real corpus)."
                ),
                "total_bytes": total_bytes,
                "n_files": n_files,
                "threshold_bytes": threshold_bytes,
            }
        )

    # duplicate MD5 detection -- independent of the size budget, fires at any total size.
    hash_errors: list[str] = []
    by_hash: dict[str, list[dict[str, Any]]] = {}
    n_hashed = 0
    n_os_metadata_skipped = 0
    for p, size in files:
        if size < MIN_DUPLICATE_SIZE_BYTES:
            continue
        if _is_os_metadata(p):
            # OS/tooling metadata files (.DS_Store, Thumbs.db, desktop.ini, .localized,
            # anything under a __MACOSX/ segment) excluded from duplicate grouping -- see
            # module docstring "OS-metadata exclusion from duplicate detection".
            n_os_metadata_skipped += 1
            continue
        try:
            digest = _hash_file(p)
        except OSError as e:
            hash_errors.append(f"{p}: {e}")
            continue
        n_hashed += 1
        try:
            rel = str(p.relative_to(ws_dir)).replace("\\", "/")
        except ValueError:
            rel = str(p)
        by_hash.setdefault(digest, []).append({"path": rel, "size_bytes": size})

    dup_groups = [
        {
            "md5": h,
            "size_bytes": entries[0]["size_bytes"],
            "files": [e["path"] for e in entries],
        }
        for h, entries in sorted(by_hash.items())
        if len(entries) > 1
    ]
    n_dup_files = sum(len(g["files"]) - 1 for g in dup_groups)
    dup_wasted_bytes = sum(g["size_bytes"] * (len(g["files"]) - 1) for g in dup_groups)

    result["duplicate_files"] = {
        "outcome": "checked",
        "n_files_hashed": n_hashed,
        "n_files_skipped_zero_byte": (
            n_files - n_hashed - len(hash_errors) - n_os_metadata_skipped
        ),
        "n_files_skipped_os_metadata": n_os_metadata_skipped,
        "n_duplicate_groups": len(dup_groups),
        "n_duplicate_files": n_dup_files,
        "duplicate_wasted_bytes": dup_wasted_bytes,
        "groups": dup_groups,
        "hash_errors": hash_errors,
    }
    dup_severity = "fail" if fail_on_duplicate else "warn"
    for g in dup_groups:
        findings.append(
            {
                "kind": "duplicate_environment_file",
                "severity": dup_severity,
                "detail": (
                    f"{len(g['files'])} files under {rel_ws} share identical content "
                    f"(md5={g['md5'][:12]}\u2026, {g['size_bytes']} bytes each): "
                    + ", ".join(g["files"])
                ),
                "md5": g["md5"],
                "size_bytes": g["size_bytes"],
                "files": g["files"],
            }
        )

    result["findings"] = findings
    result["n_findings"] = len(findings)
    if stat_errors or hash_errors or walk_errors:
        result["errors"].extend(walk_errors)
        result["errors"].extend(stat_errors)
        result["errors"].extend(hash_errors)

    if any(f["severity"] == "fail" for f in findings):
        result["status"] = "fail"
    elif findings:
        result["status"] = "warn"
    else:
        result["status"] = "pass"
    return result


def _analyze_task_safe(
    task_dir: Path, threshold_bytes: int, fail_on_duplicate: bool = False
) -> dict[str, Any]:
    """Module-level (picklable) wrapper so ProcessPoolExecutor can use it under Windows spawn.
    Never lets one task's crash kill the whole batch."""
    try:
        return analyze_task(task_dir, threshold_bytes, fail_on_duplicate)
    except Exception as e:  # noqa: BLE001
        return {
            "task_id": task_dir.name,
            "format": "unknown",
            "workspace_rel": None,
            "workspace_exists": None,
            "size_budget": None,
            "duplicate_files": None,
            "findings": [],
            "n_findings": 0,
            "status": "error",
            "errors": [
                f"unhandled exception in environment_size_budget_check.py analyzing this "
                f"task (this is a bug in the check, not necessarily a task defect): "
                f"{type(e).__name__}: {e}"
            ],
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

HOW_TO_READ_THIS_REPORT = {
    "purpose": (
        "Flags two independent defect shapes in a task's environment workspace "
        "(environment/initial_workspace/ for SVC-PC, environment/data/ for EKW): a total size "
        "over a corpus-calibrated budget, and two-or-more files anywhere in that workspace "
        "sharing identical MD5 content under different names."
    ),
    "task_status": {
        "fail": "Only reachable with --fail-on-duplicate: at least one duplicate_environment_"
        "file finding fired. Byte-identity itself is unambiguous, but see finding_kinds below "
        "-- a real 202-task run found most duplicates are a shared-source artifact or a "
        "plausible intentional convenience copy, not evidence THIS task's author shipped "
        "something broken, which is why this is not the default severity.",
        "warn": "At least one finding fired (oversized_environment, and/or "
        "duplicate_environment_file under the default severity).",
        "pass": "Neither finding fired.",
        "skip": "No environment workspace directory found for this task.",
        "error": "This check itself failed to run (see errors) -- not a task finding.",
    },
    "finding_kinds": {
        "oversized_environment": (
            "Total workspace size exceeds the calibrated threshold (default 35MB, derived from "
            "a real empty gap in the corpus's own size distribution -- see module docstring)."
        ),
        "duplicate_environment_file": (
            "Two or more files in the same task's workspace are byte-identical (same MD5) under "
            "different names. Real examples found this session include a genuine build-residue "
            "temp file duplicating a real source file, a shared-source template file inherited "
            "by dozens of unrelated tasks, and a deliberate flat-copy-plus-nested-source-tree "
            "convention that instruction.md's own bare-filename references rely on -- this "
            "check reports the byte-identity fact for all three shapes alike; distinguishing "
            "them is a human triage step, aided by this report's top_duplicate_hashes."
        ),
    },
    "the_one_thing_this_check_cannot_see": (
        "Near-duplicate files that are NOT byte-identical (different formatting, a re-save, a "
        "genuinely revised version) -- only exact MD5 matches are flagged. A human still has to "
        "eyeball similarly-named files that this check leaves alone."
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Environment size-budget and within-task MD5-duplicate-file check. See module "
            "docstring for how the 35MB default threshold was calibrated against the real "
            "600-task SVC-PC corpus."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "task_ids",
        nargs="*",
        help="one or more task ids (directory names under --root)",
    )
    ap.add_argument(
        "--all", action="store_true", help="run every task directory found under --root"
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=None,
        required=False,
        help="root directory containing one subdirectory per task (REQUIRED)",
    )
    ap.add_argument(
        "--id-prefix",
        default="",
        help="when using --all, only treat subdirectories starting with this prefix",
    )
    ap.add_argument(
        "--threshold-mb",
        type=float,
        default=None,
        help=f"override the size-budget threshold in MB (1MB=1024*1024 bytes); default "
        f"{DEFAULT_THRESHOLD_BYTES / (1024 * 1024):.0f}MB, calibrated against the real corpus "
        f"(see module docstring)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the aggregate JSON report here (default: print summary only)",
    )
    ap.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=max(1, (os.cpu_count() or 4) - 1),
        help="parallel worker processes for the hashing pass (default: cpu_count-1, "
        "%(default)s; pass 1 to force serial)",
    )
    ap.add_argument(
        "--fail-on-duplicate",
        action="store_true",
        help="report duplicate_environment_file findings as severity=fail instead of the "
        "corpus-calibrated default warn (see module docstring 'Duplicate-file severity' -- a "
        "real 202-task sample run found 58%% of tasks would fail on this basis, dominated by "
        "two shared-source files, not per-task mistakes)",
    )
    args = ap.parse_args()

    if args.root is None:
        ap.error("--root is required")
    if not args.all and not args.task_ids:
        ap.error("pass one or more task ids, or --all")
    if not args.root.is_dir():
        print(
            f"--root does not exist or is not a directory: {args.root}", file=sys.stderr
        )
        return 2

    threshold_bytes = (
        int(args.threshold_mb * 1024 * 1024)
        if args.threshold_mb is not None
        else DEFAULT_THRESHOLD_BYTES
    )

    task_dirs = find_task_dirs(
        args.root, None if args.all else args.task_ids, id_prefix=args.id_prefix
    )
    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []
    if args.jobs <= 1 or len(task_dirs) <= 1:
        for i, task_dir in enumerate(task_dirs, 1):
            print(f"[{i}/{len(task_dirs)}] {task_dir.name} ...", file=sys.stderr)
            r = _analyze_task_safe(task_dir, threshold_bytes, args.fail_on_duplicate)
            results.append(r)
            print(
                f"    -> {r['status']}  ({r['n_findings']} finding(s))", file=sys.stderr
            )
    else:
        print(
            f"Checking {len(task_dirs)} tasks with {args.jobs} parallel workers "
            "(size stat + MD5 hashing, each task independent)...",
            file=sys.stderr,
        )
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as ex:
            future_to_dir = {
                ex.submit(
                    _analyze_task_safe, td, threshold_bytes, args.fail_on_duplicate
                ): td
                for td in task_dirs
            }
            done = 0
            for fut in concurrent.futures.as_completed(future_to_dir):
                task_dir = future_to_dir[fut]
                done += 1
                r = fut.result()  # _analyze_task_safe never raises
                results.append(r)
                print(
                    f"[{done}/{len(task_dirs)}] {task_dir.name} -> {r['status']}  "
                    f"({r['n_findings']} finding(s))",
                    file=sys.stderr,
                )
        results.sort(key=lambda r: r.get("task_id", ""))

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    n_oversized = sum(
        1
        for r in results
        if any(f["kind"] == "oversized_environment" for f in r["findings"])
    )
    n_with_dups = sum(
        1
        for r in results
        if any(f["kind"] == "duplicate_environment_file" for f in r["findings"])
    )
    n_dup_groups_total = sum(
        (r.get("duplicate_files") or {}).get("n_duplicate_groups", 0) for r in results
    )
    total_wasted_bytes = sum(
        (r.get("duplicate_files") or {}).get("duplicate_wasted_bytes", 0)
        for r in results
    )

    # Which MD5s recur across how many DIFFERENT tasks in this run -- see module docstring
    # "Duplicate-file severity": a hash shared by many tasks is a shared-source artifact worth
    # one upstream fix, not N independent per-task mistakes, and this is what makes that visible
    # in the aggregate without a human re-deriving it from 100+ individual per-task findings.
    hash_task_counts: dict[str, int] = {}
    hash_example: dict[str, dict[str, Any]] = {}
    for r in results:
        for g in (r.get("duplicate_files") or {}).get("groups", []):
            h = g["md5"]
            hash_task_counts[h] = hash_task_counts.get(h, 0) + 1
            hash_example.setdefault(
                h, {"size_bytes": g["size_bytes"], "example_file": g["files"][0]}
            )
    top_duplicate_hashes = [
        {
            "md5": h,
            "n_tasks_in_this_run": c,
            "size_bytes": hash_example[h]["size_bytes"],
            "example_file": hash_example[h]["example_file"],
        }
        for h, c in sorted(hash_task_counts.items(), key=lambda kv: -kv[1])
    ]

    aggregate = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root),
        "id_prefix": args.id_prefix,
        "threshold_bytes": threshold_bytes,
        "threshold_mb": round(threshold_bytes / (1024 * 1024), 2),
        "n_tasks": len(results),
        "status_counts": counts,
        "n_tasks_oversized": n_oversized,
        "n_tasks_with_duplicate_files": n_with_dups,
        "n_duplicate_groups_total": n_dup_groups_total,
        "total_duplicate_wasted_bytes": total_wasted_bytes,
        "top_duplicate_hashes": top_duplicate_hashes,
        "fail_on_duplicate": args.fail_on_duplicate,
        "corpus_context": CORPUS_CONTEXT_2026_09_15,
        "how_to_read_this_report": HOW_TO_READ_THIS_REPORT,
        "results": results,
    }

    print(f"\n{len(results)} task(s) checked.")
    print("status counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(
        f"oversized_environment: {n_oversized} task(s) over {threshold_bytes / (1024 * 1024):.0f}MB  |  "
        f"duplicate_environment_file: {n_with_dups} task(s), {n_dup_groups_total} duplicate "
        f"group(s) total, {total_wasted_bytes / (1024 * 1024):.2f}MB wasted in duplicate copies "
        f"(severity={'fail' if args.fail_on_duplicate else 'warn'})"
    )
    if top_duplicate_hashes:
        print(
            f"top duplicate MD5s by task recurrence in this run "
            f"({len(top_duplicate_hashes)} distinct hash(es) total):"
        )
        for h in top_duplicate_hashes[:10]:
            print(
                f"    {h['md5'][:12]}…  {h['n_tasks_in_this_run']:>4} task(s)  "
                f"{h['size_bytes']:>8} bytes  e.g. {h['example_file']}"
            )
    for r in results:
        if r["status"] == "error":
            print(f"  {r['task_id']}: ERROR  {r['errors']}")
        elif r["findings"]:
            kinds = ", ".join(sorted({f["kind"] for f in r["findings"]}))
            print(f"  {r['task_id']}: {r['status'].upper()}  ({kinds})")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, indent=2, default=str)
        print(f"\nWrote {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
