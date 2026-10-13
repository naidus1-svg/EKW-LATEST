#!/usr/bin/env python3
"""package_shape_check -- is the thing we are about to SHIP actually shaped like a task package?

WHY THIS EXISTS (real, measured -- 2026-09-22 30-task fix session). 13 of 30 shipped zips carried a
packaging defect that no existing gate caught; every one was found by hand, after the fact:

  * 11 of the 19 round-1 zips shipped WITHOUT `reports/<task>_TRACE.json` +
    `reports/<task>_DECISIONS.json` INSIDE the package. The fix agents had built the ledgers, but
    left them next to the package instead of in it. `reward_signal_gate.py`'s G8 reads the ledger
    from the package, so all 11 failed G8 the moment anyone re-verified the shipped artifact.
  * task_462 shipped with NO wrapper folder at all -- `instruction.md`, `tests/`, `environment/`
    sat bare at the zip root while all 18 siblings used `task_462/...`. Unzipping the batch into
    one directory made its files collide with every other task's.
  * task_470 and task_388 shipped with a `task_files/` root -- the raw "download with runs" shape
    that `skills/ekw/fix-task-from-review/SKILL.md` Step 7 explicitly warns about.
  * task_139 and task_133: the `<task>_fixed.zip` sibling in `ready_to_upload_v7/submitted/` was
    STALE relative to the loose package directory next to it -- a silent revert of the fix. The
    skill's GAP 5 exists for exactly this and it happened anyway.

Every one of these is mechanically decidable from the archive's own member list. This gate decides
them, so nobody has to unzip 30 files by hand again.

WHAT IT CHECKS, per package (a built `.zip` OR a package directory):

  1. root_shape        -- the archive root is exactly ONE directory named `task_<id>` matching the
                          expected id. Bare files at the root, a `task_files/` root, a differently
                          named wrapper, or multiple top-level entries all FAIL. The expected id is
                          inferred from the zip filename (`task_470_fixed.zip` -> `task_470`,
                          `_DO_NOT_UPLOAD_task_X_fixed.zip` -> `task_X`) unless `--expect-id` says
                          otherwise; for a directory package it is the directory's own name, so
                          this check degrades to "is it named task_<something>".
  2. ledger_present    -- `reports/<task>_TRACE.json` and `reports/<task>_DECISIONS.json` exist
                          inside the wrapper AND parse as JSON. This is the file
                          `reward_signal_gate.py` G8 reads; the failure message says so.
  3. hygiene           -- no `__pycache__/`, `*.pyc`/`*.pyo`, `.DS_Store`, `*.round*`, `*.bak`,
                          `*.tmp`, `*.orig`, editor swap/backup files (`*.swp`, `*.swo`, `*~`,
                          `#...#`), and no nested `.zip` anywhere in the archive.
  4. required_members  -- `instruction.md`, `task.toml`, `tests/`, `solution/`, `environment/` all
                          present under the wrapper.
  5. genre_coherence   -- exactly one of the two real build genres:
                            native-harbor   = `tests/verifier.json` + a vendored verifier library
                                              dir, EITHER `tests/__verifier_lib/` OR
                                              `tests/verifier_lib/` (BOTH spellings are real -- 28
                                              of the 79 shipped v7 tasks use the single-underscore
                                              one; see container_build_check.py's own note)
                            rewardkit-hybrid = `tests/deliverables_*/judge.toml` + `tests/reward.toml`
                                              + `environment/initial_workspace/`
                          A package that is NEITHER, or a MIX of both, FAILS. "unknown genre" is
                          never reported as a pass -- treating unknown as benign is exactly the
                          convention that let a broken package ship this session.
  6. drift_vs_source   -- opt-in, `--against <dir>`: diff the archive's member list and per-file
                          sha256 against the working directory that produced it. Any file that
                          differs, is missing from the zip, or is extra in the zip is reported.
                          This mechanizes the skill's GAP 5 (the stale-sibling-zip revert).

WHAT IT DOES NOT CHECK. Nothing about CONTENT: it does not read instruction.md, does not parse the
rubric, does not know whether the ledger's dispositions are correct or even non-empty (only that the
file is present and is JSON -- `reward_signal_gate.py` G8 owns the semantics), does not verify the
Dockerfile builds (`container_build_check.py` owns that), and does not compare requirements pins
(`verifier_requirements_pin_mismatch_check.py` owns that). `drift_vs_source` compares bytes, so a
legitimate post-build normalization (line endings, a regenerated xlsx) reads as drift; it is opt-in
for that reason. It also cannot tell a deliberately-excluded working file (scratch notes you meant to
leave out) from an accidentally-dropped one -- it reports both as `only_in_source`.

CALIBRATION STATUS. **Calibrated 2026-09-22 on the real shipped artifacts.** All 29 hand-fixed final
zips under `dataos_qc_runs/74-ekw-sprint/qcr_21092026/ready/` and
`.../qcr_20092026_rework/ready/task_*.zip` pass all five always-on detectors -- that clean sweep is
the regression baseline. Each detector is separately proven to FIRE by a reconstructed known-bad
fixture in `package_shape_check_test.py` (task_files root, bare-files root, stripped reports/,
__pycache__, mixed genre, drifted source). Not yet run against any non-EKW benchmark.

    package_shape_check.py --root <dir of zips or packages> [--out report.json]
    package_shape_check.py path/to/task_470_fixed.zip --expect-id task_470
    package_shape_check.py path/to/task_470_fixed.zip --against build/task_470

Exit code: 0 if every package passes, 1 if any fails, 2 on a usage/IO error.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

#: Both real spellings of the vendored verifier library dir in this corpus. Recognising only the
#: double-underscore one made container_build_check.py's genre() return "unknown" for 35% of the
#: shipped corpus; do not "simplify" this to one entry.
VERIFIER_LIB_DIRS = ("__verifier_lib", "verifier_lib")

REQUIRED_FILES = ("instruction.md", "task.toml")
REQUIRED_DIRS = ("tests", "solution", "environment")

#: Matched against each member's BASENAME with fnmatch, case-sensitively except where noted.
HYGIENE_FILE_GLOBS = (
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    "*.bak",
    "*.tmp",
    "*.orig",
    "*.swp",
    "*.swo",
    "*.zip",
    "*~",
)
#: Any path SEGMENT equal to one of these fails hygiene.
HYGIENE_DIR_NAMES = ("__pycache__", ".ipynb_checkpoints")
#: `foo.round1`, `judge.toml.round2`, `*.round` -- the fix-session scratch convention.
HYGIENE_ROUND_RE = re.compile(r"\.round\d*(\.|$)")
#: Emacs interlock/backup `#file#`.
HYGIENE_EMACS_RE = re.compile(r"^#.*#$")

TASK_ID_RE = re.compile(r"task_[A-Za-z0-9][A-Za-z0-9._-]*")

HOW_TO_READ_THIS_REPORT = (
    "status 'pass' = all applicable detectors passed. 'fail' = at least one detector failed; read "
    "checks.<name>.detail. 'skip' = the package could not be opened at all (a corrupt zip, a path "
    "that is neither a zip nor a directory) -- never read a skip as clean. Per-detector status is "
    "'pass'/'fail'/'skip'; drift_vs_source is 'skip' unless --against was passed. genre_coherence "
    "reports 'fail' (never 'skip') on a package whose genre cannot be identified: an unidentifiable "
    "genre is the defect, not an absence of evidence."
)


# ---------------------------------------------------------------------------
# package reading -- a zip and a directory are normalized to the same shape
# ---------------------------------------------------------------------------


class Package:
    """A built package, read either from a .zip or from a directory on disk.

    `members` are POSIX paths relative to the ARCHIVE ROOT, i.e. they include the wrapper
    directory (`task_470/instruction.md`). Directory entries are normalized to a trailing `/`.
    A directory package is presented as if it were zipped from its own parent, so both sources
    exercise the identical root_shape logic.
    """

    def __init__(self, path: Path):
        self.path = path
        self.kind = "zip" if path.suffix == ".zip" else "dir"
        self.members: list[str] = []
        self._zf: zipfile.ZipFile | None = None
        if self.kind == "zip":
            self._zf = zipfile.ZipFile(path)
            for info in self._zf.infolist():
                name = info.filename.replace("\\", "/")
                if info.is_dir():
                    self.members.append(name.rstrip("/") + "/")
                else:
                    self.members.append(name)
        else:
            prefix = path.name
            self.members.append(prefix + "/")
            for p in sorted(path.rglob("*")):
                rel = prefix + "/" + p.relative_to(path).as_posix()
                self.members.append(rel + "/" if p.is_dir() else rel)
        # macOS resource forks are an artifact of `zip` on a Mac, never task content, and are not
        # what this gate is about; drop them before anything else looks at the list.
        self.members = [m for m in self.members if not m.startswith("__MACOSX/")]

    def close(self) -> None:
        if self._zf is not None:
            self._zf.close()

    def __enter__(self) -> "Package":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def files(self) -> list[str]:
        return [m for m in self.members if not m.endswith("/")]

    def roots(self) -> list[str]:
        """Distinct top-level entries, each suffixed `/` if it is (or contains) a directory."""
        out: dict[str, bool] = {}
        for m in self.members:
            head, _, rest = m.partition("/")
            is_dir = bool(rest) or m.endswith("/")
            out[head] = out.get(head, False) or is_dir
        return sorted(h + "/" if d else h for h, d in out.items())

    def read(self, member: str) -> bytes:
        if self._zf is not None:
            return self._zf.read(member)
        head, _, rest = member.partition("/")
        return (self.path / rest).read_bytes()


def expected_id_for(path: Path) -> str:
    """The wrapper directory name this artifact should contain.

    For a directory: its own name. For a zip: the first `task_<id>` substring in the filename, with
    a trailing `_fixed` stripped -- this handles `task_470_fixed.zip`, `task_LGL-168_fixed.zip` and
    `_DO_NOT_UPLOAD_task_LGL-140_fixed.zip` alike. Falls back to the bare stem if no `task_` token
    is present, which then fails root_shape loudly rather than silently accepting anything.
    """
    if path.suffix != ".zip":
        return path.name
    stem = path.name[: -len(".zip")]
    m = TASK_ID_RE.search(stem)
    token = m.group(0) if m else stem
    if token.endswith("_fixed"):
        token = token[: -len("_fixed")]
    return token


# ---------------------------------------------------------------------------
# detectors
# ---------------------------------------------------------------------------


def _ok(detail: str = "") -> dict:
    return {"status": "pass", "detail": detail}


def _bad(detail: str) -> dict:
    return {"status": "fail", "detail": detail}


def check_root_shape(pkg: Package, expect_id: str) -> dict:
    roots = pkg.roots()
    if not roots:
        return _bad("archive is empty")
    if len(roots) > 1:
        bare = [r for r in roots if not r.endswith("/")]
        extra = (
            f" ({len(bare)} of them are bare FILES at the archive root: {', '.join(bare[:5])})"
            if bare
            else ""
        )
        return _bad(
            f"archive root has {len(roots)} top-level entries, expected exactly one directory "
            f"'{expect_id}/': {', '.join(roots[:8])}{extra}. Unzipping this batch into one "
            "directory makes its files collide with every other task's."
        )
    root = roots[0]
    if not root.endswith("/"):
        return _bad(
            f"the single archive-root entry '{root}' is a FILE, not the '{expect_id}/' wrapper "
            "directory"
        )
    name = root.rstrip("/")
    if name == "task_files":
        return _bad(
            "archive root is 'task_files/' -- that is the raw DataOS 'download with runs' shape, "
            f"not a shippable package. Repack with a '{expect_id}/' wrapper "
            "(see skills/ekw/fix-task-from-review/SKILL.md Step 7)."
        )
    if name != expect_id:
        return _bad(
            f"archive root is '{name}/' but this artifact should wrap '{expect_id}/' "
            "(pass --expect-id if the inference is wrong)"
        )
    return _ok(f"single wrapper '{name}/'")


def check_ledger_present(pkg: Package, wrapper: str, task_id: str) -> dict:
    """`task_id` names the ledger files; `wrapper` says where to look. They differ exactly when
    root_shape already failed (a `task_files/` wrapper), and using the expected id there keeps this
    detector reporting the ledger the task actually needs rather than one named after the defect."""
    if wrapper is None:
        return {"status": "skip", "detail": "no single wrapper directory to look under"}
    missing, unparseable = [], []
    for kind in ("TRACE", "DECISIONS"):
        rel = f"reports/{task_id}_{kind}.json"
        member = f"{wrapper}/{rel}"
        if member not in pkg.members:
            missing.append(rel)
            continue
        try:
            json.loads(pkg.read(member).decode("utf-8", errors="replace"))
        except Exception as e:
            unparseable.append(f"{rel} ({type(e).__name__}: {e})")
    if not missing and not unparseable:
        return _ok(f"reports/{task_id}_TRACE.json + _DECISIONS.json present and parse as JSON")
    parts = []
    if missing:
        parts.append("missing from the package: " + ", ".join(missing))
    if unparseable:
        parts.append("present but not valid JSON: " + ", ".join(unparseable))
    return _bad(
        "; ".join(parts)
        + ". reward_signal_gate.py G8 reads the decision ledger FROM THE PACKAGE -- a ledger built "
        "next to the package but left out of it fails G8 on re-verification (11 of 19 round-1 zips "
        "shipped this way on 2026-09-22)."
    )


def _hygiene_hits(members: list[str]) -> list[str]:
    hits = []
    for m in members:
        segs = [s for s in m.split("/") if s]
        if any(s in HYGIENE_DIR_NAMES for s in segs):
            hits.append(m)
            continue
        if m.endswith("/"):
            continue
        base = segs[-1] if segs else m
        if any(fnmatch.fnmatch(base, g) for g in HYGIENE_FILE_GLOBS):
            hits.append(m)
            continue
        if HYGIENE_ROUND_RE.search(base) or HYGIENE_EMACS_RE.match(base):
            hits.append(m)
    return hits


def check_hygiene(pkg: Package) -> dict:
    hits = _hygiene_hits(pkg.members)
    if not hits:
        return _ok("no build/editor/scratch artifacts")
    shown = ", ".join(sorted(hits)[:10])
    more = f" (+{len(hits) - 10} more)" if len(hits) > 10 else ""
    return _bad(f"{len(hits)} junk member(s) shipped inside the package: {shown}{more}")


def check_required_members(pkg: Package, wrapper: str) -> dict:
    if wrapper is None:
        return {"status": "skip", "detail": "no single wrapper directory to look under"}
    members = set(pkg.members)
    missing = [f for f in REQUIRED_FILES if f"{wrapper}/{f}" not in members]
    for d in REQUIRED_DIRS:
        if not any(m.startswith(f"{wrapper}/{d}/") for m in members):
            missing.append(d + "/")
    if missing:
        return _bad(f"missing under {wrapper}/: {', '.join(sorted(missing))}")
    return _ok("instruction.md, task.toml, tests/, solution/, environment/ all present")


def detect_genre(pkg: Package, wrapper: str) -> tuple[list[str], dict[str, list[str]]]:
    """Returns (genres_matched, evidence). A genre matches only if ALL its markers are present."""
    members = set(pkg.members)

    def has_dir(rel: str) -> bool:
        return any(m.startswith(f"{wrapper}/{rel}") for m in members)

    native_markers = {
        "tests/verifier.json": f"{wrapper}/tests/verifier.json" in members,
        "tests/{__verifier_lib,verifier_lib}/": any(
            has_dir(f"tests/{n}/") for n in VERIFIER_LIB_DIRS
        ),
    }
    rewardkit_markers = {
        "tests/deliverables_*/judge.toml": any(
            re.fullmatch(rf"{re.escape(wrapper)}/tests/deliverables_[^/]+/judge\.toml", m)
            for m in members
        ),
        "tests/reward.toml": f"{wrapper}/tests/reward.toml" in members,
        "environment/initial_workspace/": has_dir("environment/initial_workspace/"),
    }
    matched = []
    if all(native_markers.values()):
        matched.append("native-harbor")
    if all(rewardkit_markers.values()):
        matched.append("rewardkit-hybrid")
    evidence = {
        "native-harbor": sorted(k for k, v in native_markers.items() if v),
        "rewardkit-hybrid": sorted(k for k, v in rewardkit_markers.items() if v),
    }
    return matched, evidence


def check_genre_coherence(pkg: Package, wrapper: str) -> dict:
    if wrapper is None:
        return {"status": "skip", "detail": "no single wrapper directory to look under"}
    matched, evidence = detect_genre(pkg, wrapper)
    if len(matched) == 1:
        return {"status": "pass", "detail": f"{matched[0]}", "genre": matched[0]}
    if len(matched) > 1:
        return {
            "status": "fail",
            "detail": (
                "package matches BOTH build genres at once "
                f"({', '.join(matched)}); markers found: {evidence}. A mixed package grades through "
                "whichever path the harness probes first."
            ),
            "genre": "mixed",
        }
    return {
        "status": "fail",
        "detail": (
            "package matches NEITHER build genre. native-harbor needs tests/verifier.json + "
            "tests/__verifier_lib/ (or tests/verifier_lib/); rewardkit-hybrid needs "
            "tests/deliverables_*/judge.toml + tests/reward.toml + environment/initial_workspace/. "
            f"Markers actually found: {evidence}. This is reported as FAIL, not skip: an "
            "unidentifiable genre is exactly how a broken package shipped on 2026-09-22."
        ),
        "genre": "unknown",
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_source_dir(against: Path, wrapper: str | None) -> Path | None:
    """`--against` may point at the package dir itself or at its parent."""
    if (against / "instruction.md").is_file():
        return against
    if wrapper and (against / wrapper / "instruction.md").is_file():
        return against / wrapper
    if against.is_dir():
        return against
    return None


def check_drift_vs_source(pkg: Package, wrapper: str | None, against: Path | None) -> dict:
    if against is None:
        return {"status": "skip", "detail": "not requested (pass --against <dir>)"}
    src = resolve_source_dir(against, wrapper)
    if src is None or not src.is_dir():
        return {"status": "skip", "detail": f"--against path is not a directory: {against}"}

    src_files: dict[str, bytes] = {}
    for p in sorted(src.rglob("*")):
        if p.is_file():
            src_files[p.relative_to(src).as_posix()] = p.read_bytes()

    prefix = f"{wrapper}/" if wrapper else ""
    pkg_files = {
        m[len(prefix):]: m for m in pkg.files if not prefix or m.startswith(prefix)
    }
    # Hygiene junk on EITHER side is reported by check_hygiene, not re-reported as drift.
    junk = set(_hygiene_hits(list(pkg_files) + list(src_files)))
    only_in_pkg = sorted(set(pkg_files) - set(src_files) - junk)
    only_in_src = sorted(set(src_files) - set(pkg_files) - junk)
    differs = []
    for rel in sorted(set(pkg_files) & set(src_files)):
        if rel in junk:
            continue
        if _sha256(pkg.read(pkg_files[rel])) != _sha256(src_files[rel]):
            differs.append(rel)

    if not (only_in_pkg or only_in_src or differs):
        return {
            "status": "pass",
            "detail": f"{len(pkg_files)} file(s) byte-identical to {src}",
            "source": str(src),
        }
    parts = []
    if differs:
        parts.append(f"{len(differs)} file(s) DIFFER: " + ", ".join(differs[:8]))
    if only_in_src:
        parts.append(f"{len(only_in_src)} only_in_source: " + ", ".join(only_in_src[:8]))
    if only_in_pkg:
        parts.append(f"{len(only_in_pkg)} only_in_package: " + ", ".join(only_in_pkg[:8]))
    return {
        "status": "fail",
        "detail": "; ".join(parts)
        + f". The zip is out of sync with {src} -- shipping it silently reverts whatever the "
        "working directory fixed (GAP 5; hit task_133 and task_139 on 2026-09-22).",
        "source": str(src),
        "differs": differs,
        "only_in_source": only_in_src,
        "only_in_package": only_in_pkg,
    }


# ---------------------------------------------------------------------------
# per-package driver
# ---------------------------------------------------------------------------


def check_package(path: Path, expect_id: str | None = None, against: Path | None = None) -> dict:
    """One result dict for one package. Never raises."""
    exp = expect_id or expected_id_for(path)
    result: dict = {
        "package": str(path),
        "kind": "zip" if path.suffix == ".zip" else "dir",
        "expect_id": exp,
        "wrapper": None,
        "status": None,
        "checks": {},
        "errors": [],
    }
    try:
        pkg = Package(path)
    except Exception as e:
        result["status"] = "skip"
        result["errors"].append(f"could not open package: {type(e).__name__}: {e}")
        return result

    with pkg:
        root_res = check_root_shape(pkg, exp)
        roots = pkg.roots()
        wrapper = roots[0].rstrip("/") if len(roots) == 1 and roots[0].endswith("/") else None
        result["wrapper"] = wrapper
        result["checks"] = {
            "root_shape": root_res,
            "ledger_present": check_ledger_present(pkg, wrapper, exp),
            "hygiene": check_hygiene(pkg),
            "required_members": check_required_members(pkg, wrapper),
            "genre_coherence": check_genre_coherence(pkg, wrapper),
            "drift_vs_source": check_drift_vs_source(pkg, wrapper, against),
        }

    result["status"] = (
        "fail" if any(c["status"] == "fail" for c in result["checks"].values()) else "pass"
    )
    result["failed_checks"] = sorted(
        k for k, c in result["checks"].items() if c["status"] == "fail"
    )
    return result


def discover(root: Path) -> list[Path]:
    """Every shippable artifact directly under `root`: `*.zip` plus `task_*` directories."""
    out = [p for p in sorted(root.glob("*.zip")) if p.is_file()]
    out += [p for p in sorted(root.glob("task_*")) if p.is_dir()]
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "package_shape_check: ship gate for a built task package (.zip or directory) -- "
            "wrapper shape, in-package decision ledger, hygiene, required members, build genre, "
            "and optional drift against the directory that produced it."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("packages", nargs="*", type=Path, help="explicit .zip or package directories")
    ap.add_argument("--root", type=Path, default=None,
                    help="sweep every *.zip and task_* directory directly under this directory")
    ap.add_argument("--expect-id", default=None,
                    help="override the inferred wrapper name (single-package runs only)")
    ap.add_argument("--against", type=Path, default=None,
                    help="working directory that produced the package; enables drift_vs_source")
    ap.add_argument("--out", type=Path, default=None, help="write the JSON report here")
    args = ap.parse_args(argv)

    targets: list[Path] = list(args.packages)
    if args.root is not None:
        if not args.root.is_dir():
            print(f"--root is not a directory: {args.root}", file=sys.stderr)
            return 2
        targets += discover(args.root)
    if not targets:
        print("pass one or more packages, and/or --root <dir>", file=sys.stderr)
        return 2
    if args.expect_id and len(targets) != 1:
        print("--expect-id only makes sense with exactly one package", file=sys.stderr)
        return 2

    results = [check_package(p, expect_id=args.expect_id, against=args.against) for p in targets]

    counts: dict[str, int] = {}
    failed_detectors: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        for k in r.get("failed_checks", []):
            failed_detectors[k] = failed_detectors.get(k, 0) + 1

    width = max((len(Path(r["package"]).name) for r in results), default=10)
    for r in results:
        name = Path(r["package"]).name
        detail = ", ".join(r["failed_checks"]) if r.get("failed_checks") else ""
        if r["status"] == "skip":
            detail = "; ".join(r["errors"])
        print(f"{name:{width}}  {r['status']:5} {detail}")

    print(f"\n{len(results)} package(s) checked.")
    print("status counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if failed_detectors:
        print(
            "failed detectors: "
            + ", ".join(f"{k}={v}" for k, v in sorted(failed_detectors.items()))
        )

    report = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(args.root) if args.root else None,
        "against": str(args.against) if args.against else None,
        "n_packages": len(results),
        "status_counts": counts,
        "failed_detector_counts": failed_detectors,
        "how_to_read_this_report": HOW_TO_READ_THIS_REPORT,
        "results": results,
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")

    return 1 if counts.get("fail") or counts.get("skip") else 0


if __name__ == "__main__":
    sys.exit(main())
