#!/usr/bin/env python3
"""
_scratch_mojibake_check.py - deterministic detector for the SVC-PC "1.8
packaging / mojibake path" defect class.

WHAT IT DETECTS
----------------
A judge.toml files= path, or a filename actually shipped in the task
package, that carries a mojibake corruption signature: text that was
UTF-8 encoded, then had those bytes misread through a single-byte code
page (classically CP437, confirmed against real corpus data, see
below; CP1252 / Latin-1 / MacRoman are also tried since other
pipelines can produce those variants), producing garbage characters
like the three-character sequence Gamma, C-cedilla, o-diaeresis
(U+0393 U+00C7 U+00F6, one round of corruption) or the six-character
double-corrupted form U+256C U+00F4 U+251C U+00E7 U+251C U+2562 (two
rounds, seen as shipped directory names such as "My Drive <garbage>
alice.chen").

WHY THIS CHECK EXISTS (not a path-existence / internal-consistency check)
---------------------------------------------------------------------
A prior "does the judge.toml path exist somewhere in the shipped
package" resolver is blind to this defect whenever the shipped
initial_workspace directory carries the SAME corrupted bytes as
judge.toml: the path "exists" (self-consistently), the check passes,
and the package still fails DataOS grading because the real corpus
directory uses the correct Unicode name (a genuine U+2014 dash
character, not the corrupted lookalike). This script does not check
existence at all. It scans path TEXT for the corruption signature
itself, so a self-consistently-corrupted pair still fails.

DETECTION RULE
---------------
For every candidate string (a judge.toml files= entry, or a shipped
relative file path):
  1. If every non-ASCII character in the string already belongs to a
     PLAUSIBLE set (Latin-1/Latin-Extended accented letters, and the
     standard "smart" typographic punctuation: dash characters U+2013
     and U+2014, curly quotes, ellipsis, bullet, nbsp, middle dot,
     copyright/registered/trademark, degree, plus-minus, multiply,
     divide) then it is not corrupted. This is what keeps real
     accented names and a real Unicode dash between "My Drive" and
     a person's name out of the flagged set.
  2. Otherwise the string contains at least one character outside that
     set (a "candidate"). It is flagged CORRUPTED if either:
       (a) HARD TELL: it contains a character from a block that is
           never legitimate in a filename: Box Drawing (U+2500-257F),
           Block Elements (U+2580-259F), a literal C1 control
           (U+0080-009F), or the replacement character U+FFFD; or
       (b) ROUND-TRIP: encoding the string's non-ASCII run through one
           of the candidate single-byte code pages (cp437, cp1252,
           latin1, mac_roman, in that order) and decoding the result
           as UTF-8 succeeds (no UnicodeDecodeError / UnicodeEncodeError),
           and the recovered string is now fully inside the PLAUSIBLE
           set from step 1 (up to 3 rounds, to catch double encoding).
           A string that does not round-trip clean under any candidate
           is NOT flagged. Kept conservative on purpose: an unknown,
           unusual character is left alone rather than guessed at.

Confirmed empirically against the 57-task ground truth (see the
adversarial backtest report next to this script) that CP437 is the
exact code page in play here: a lone dash character, UTF-8 encoded
then decoded as cp437, reproduces the Gamma/C-cedilla/o-diaeresis
three-character form exactly; applying that same transform a second
time reproduces the six-character double-corrupted form exactly. The
other candidate code pages are included for generalization beyond
this one dataset, per the task's own request; they account for zero
of the hits in the 57-task backtest, cp437 alone explains all of them.

USAGE
------
  python _scratch_mojibake_check.py <path-to-task-package>

<path-to-task-package> is either a directory or a .zip file whose
root (or whose single top-level directory, if the zip wraps one) is a
harbor task package root: contains judge.toml file(s) somewhere under
it (commonly tests/deliverables_NN/judge.toml) and the shipped tree
(commonly environment/, solution/, tests/).

Exit code 0 = PASS (no corruption signature found).
Exit code 1 = FAIL (corruption signature found), evidence printed.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tomllib
import zipfile
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Character classification
# ---------------------------------------------------------------------------

# Built from raw code points (chr(), not \uXXXX literals) so the two
# dash characters this module has to reason about never appear as a
# literal glyph or escape sequence in this file's own source text.
_SMART_PUNCT_CODEPOINTS = [
    0x2013,
    0x2014,  # dash characters (en dash, em dash)
    0x2018,
    0x2019,
    0x201A,
    0x201B,  # single quotes / low-9 / reversed-9
    0x201C,
    0x201D,
    0x201E,
    0x201F,  # double quotes / low-9 / reversed-9
    0x2026,  # ellipsis
    0x2022,  # bullet
    0x00A0,  # nbsp
    0x00B7,  # middle dot
    0x00A9,
    0x00AE,
    0x2122,  # copyright, registered, trademark
    0x00B0,
    0x00B1,
    0x00D7,
    0x00F7,  # degree, plus-minus, multiply, divide
    0x2192,
    0x2190,  # arrows (occasionally used in doc titles)
]
_SMART_PUNCT = set(chr(cp) for cp in _SMART_PUNCT_CODEPOINTS)


def _is_plausible_char(c: str) -> bool:
    """True for a character that is fine to see, unmodified, in a real
    corpus filename: ASCII, accented Latin letters, or standard
    typographic punctuation."""
    cp = ord(c)
    if cp < 128:
        return True
    if 0x00C0 <= cp <= 0x024F:  # Latin-1 Supplement + Latin Extended-A/B letters
        return True
    if c in _SMART_PUNCT:
        return True
    return False


def _is_hard_tell_char(c: str) -> bool:
    """True for a character that is essentially never legitimate in a
    filename and is a strong standalone mojibake signature (box-drawing
    / block-element art, literal C1 control, or the replacement char)."""
    cp = ord(c)
    if 0x2500 <= cp <= 0x259F:  # Box Drawing + Block Elements
        return True
    if 0x0080 <= cp <= 0x009F:  # literal C1 controls
        return True
    if cp == 0xFFFD:  # replacement character
        return True
    return False


CANDIDATE_CODEPAGES = ["cp437", "cp1252", "latin1", "mac_roman"]
MAX_ROUNDS = 3


def _all_plausible(s: str) -> bool:
    return all(_is_plausible_char(c) for c in s)


def _any_hard_tell(s: str) -> bool:
    return any(_is_hard_tell_char(c) for c in s)


@dataclass
class RunVerdict:
    run: str
    corrupted: bool
    reason: str = ""
    chain: list = field(default_factory=list)
    recovered: str | None = None


def classify_run(run: str) -> RunVerdict:
    """Classify one maximal non-ASCII substring."""
    if _all_plausible(run):
        return RunVerdict(
            run, False, "plausible (accented letters / smart punctuation only)"
        )

    if _any_hard_tell(run):
        # still try to compute a recovered string for the evidence report
        recovered, chain = _attempt_roundtrip(run)
        return RunVerdict(
            run,
            True,
            "hard-tell character (box-drawing / block-element / C1-control / replacement char)",
            chain,
            recovered,
        )

    recovered, chain = _attempt_roundtrip(run)
    if recovered is not None and _all_plausible(recovered):
        return RunVerdict(
            run,
            True,
            f"round-trip via {' then '.join(chain)} yields a plausible string",
            chain,
            recovered,
        )

    # Contains an unusual character but neither hard-tell nor a clean
    # round-trip. Left unflagged deliberately (see module docstring:
    # conservative default to protect precision against unknown scripts).
    return RunVerdict(
        run, False, "unusual but no hard-tell and no clean round-trip found"
    )


def _attempt_roundtrip(run: str):
    """Try encode(codepage).decode(utf-8), iterated up to MAX_ROUNDS times,
    across CANDIDATE_CODEPAGES. Returns (best_result_or_None, chain_used)."""
    for codepage in CANDIDATE_CODEPAGES:
        s = run
        chain = []
        for _round in range(MAX_ROUNDS):
            try:
                nxt = s.encode(codepage).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                break
            if nxt == s:
                break
            chain.append(codepage)
            s = nxt
            if _all_plausible(s):
                return s, chain
        # loop continues to next codepage if this one didn't fully resolve
    return None, []


_NONASCII_RUN = re.compile(r"[^\x00-\x7F]+")


def scan_string(s: str):
    """Return list of RunVerdict for every non-ASCII run in s that is
    corrupted."""
    hits = []
    for m in _NONASCII_RUN.finditer(s):
        v = classify_run(m.group(0))
        if v.corrupted:
            hits.append(v)
    return hits


# ---------------------------------------------------------------------------
# judge.toml files= extraction (same recursive-collect shape as the
# reference analyzer in scratchpad/_scratch_batch_analyze.py)
# ---------------------------------------------------------------------------


def _collect_files_key(obj, acc):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "files" and isinstance(v, list):
                acc.extend(x for x in v if isinstance(x, str))
            else:
                _collect_files_key(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _collect_files_key(v, acc)


# ---------------------------------------------------------------------------
# Package readers: directory or zip, both exposing
#   .judge_toml_paths() -> list[str] (relative paths, usable with .read)
#   .read(relpath) -> bytes
#   .all_paths() -> list[str] (every shipped file path, relative to package root)
# ---------------------------------------------------------------------------


class DirPackage:
    def __init__(self, root):
        self.root = root

    def all_paths(self):
        out = []
        for dirpath, _dirnames, filenames in os.walk(self.root):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, self.root).replace(os.sep, "/")
                out.append(rel)
        return out

    def judge_toml_paths(self):
        return [p for p in self.all_paths() if p.endswith("judge.toml")]

    def read(self, relpath):
        with open(os.path.join(self.root, relpath), "rb") as f:
            return f.read()


class ZipPackage:
    def __init__(self, zpath):
        self.z = zipfile.ZipFile(zpath)
        names = [n for n in self.z.namelist() if not n.endswith("/")]
        # if every entry shares one top-level directory, treat that as an
        # implicit root (common when a package dir gets zipped whole)
        tops = set(n.split("/", 1)[0] for n in names if "/" in n)
        self.prefix = ""
        if len(tops) == 1 and all(n.startswith(next(iter(tops)) + "/") for n in names):
            self.prefix = next(iter(tops)) + "/"
        self._names = [n[len(self.prefix) :] for n in names]

    def all_paths(self):
        return list(self._names)

    def judge_toml_paths(self):
        return [p for p in self._names if p.endswith("judge.toml")]

    def read(self, relpath):
        return self.z.read(self.prefix + relpath)


def load_package(path):
    if os.path.isdir(path):
        return DirPackage(path)
    if zipfile.is_zipfile(path):
        return ZipPackage(path)
    raise ValueError(f"{path} is neither a directory nor a zip file")


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    source: str  # "judge.toml" or "shipped"
    path: str  # the full declared/shipped path string
    run: str  # the specific corrupted substring
    reason: str
    recovered: str | None


def check_package(pkg) -> list[Finding]:
    """Scan both signal sources and return every hit, tagged by source.
    judge.toml hits and shipped hits are both included here; main() below
    decides which ones gate the PASS/FAIL verdict."""
    findings: list[Finding] = []

    # (1) judge.toml files= entries
    declared: set[str] = set()
    for jt in pkg.judge_toml_paths():
        try:
            parsed = tomllib.loads(pkg.read(jt).decode("utf-8"))
        except Exception:
            continue
        acc: list[str] = []
        _collect_files_key(parsed, acc)
        declared.update(acc)
    for p in sorted(declared):
        for v in scan_string(p):
            findings.append(Finding("judge.toml", p, v.run, v.reason, v.recovered))

    # (2) shipped filenames (every path actually in the package)
    for p in sorted(pkg.all_paths()):
        for v in scan_string(p):
            findings.append(Finding("shipped", p, v.run, v.reason, v.recovered))

    return findings


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("path", help="task package directory or .zip file")
    ap.add_argument("--quiet", action="store_true", help="print only the verdict line")
    ap.add_argument(
        "--judge-only",
        action="store_true",
        help=(
            "Gate the verdict on judge.toml hits only; report shipped-only "
            "hits as advisory (does not fail the check). Measured on the "
            "57-task ground truth (see the backtest report next to this "
            "script): of the 9 tasks a DataOS review scored 1.8-major, only "
            "5 are mojibake per the reviewers' own text; the other 4 are a "
            "judge timeout, an oversized environment, entirely missing "
            "ASCII-named files, and a missing data export, none of them a "
            "corruption signature this script was built to find. Default "
            "mode (judge.toml OR shipped) recalls 8 of the 9 by the strict "
            "label but also flags 7 of the 12 DataOS-PASS tasks, because "
            "the shipped ~200-file multi-drive corpus commonly carries "
            "corrupted filenames that a given task's own judge.toml never "
            "references (irrelevant clutter elsewhere in the shared "
            "corpus). --judge-only recalls 4 of the 9 by the strict label, "
            "4 of the 5 against the mojibake-only subset (it misses the one "
            "case where judge.toml itself was spelled correctly and only "
            "the shipped copy was corrupted), and flags 2 of the 12 "
            "DataOS-PASS tasks, both of which are independently "
            "reviewer-confirmed real corruption in judge.toml (graded "
            "severity=minor that round because the rubric happened to "
            "hardcode the expected values elsewhere), never a clean path. "
            "Recommended for a pre-ship gate; leave the default on for a "
            "thorough corpus-hygiene sweep."
        ),
    )
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass

    pkg = load_package(args.path)
    findings = check_package(pkg)
    judge_findings = [f for f in findings if f.source == "judge.toml"]
    shipped_findings = [f for f in findings if f.source == "shipped"]
    gating = judge_findings if args.judge_only else findings
    advisory = shipped_findings if args.judge_only else []

    def _print_finding(f: Finding):
        print(f"  [{f.source}] {f.path}")
        print(f"      offending run: {f.run!r}")
        print(f"      reason: {f.reason}")
        if f.recovered is not None:
            print(f"      recovered (plausible) text: {f.recovered!r}")

    if gating:
        if not args.quiet:
            print(f"FAIL: {len(gating)} mojibake-signature hit(s) in {args.path}\n")
            for f in gating:
                _print_finding(f)
            if advisory:
                print(
                    f"\n  ({len(advisory)} additional shipped-only hit(s), advisory, not gating:)"
                )
                for f in advisory:
                    _print_finding(f)
        else:
            print("FAIL")
        return 1
    else:
        if not args.quiet:
            print(f"PASS: no gating mojibake corruption signature found in {args.path}")
            if advisory:
                print(
                    f"\n  ADVISORY: {len(advisory)} shipped-only hit(s) not referenced by this task's own judge.toml:"
                )
                for f in advisory:
                    _print_finding(f)
        else:
            print("PASS")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
