#!/usr/bin/env python3
"""Requirement -> criterion coverage trace for one SVC-PC package (R8, 2026-09-23).

WHY: the remaining DataOS majors are overwhelmingly 1.5 coverage (an instruction requirement no criterion
grades), and 26-8-0 took 13 rounds because each fix closed only the cited gap. The LLM verify is told to check
coverage, but nothing mechanical checks that it walked EVERY requirement. This tool makes the walk checkable:

  list  <pkg>          print the instruction's requirement units, each with a stable id (R01..) and a short hash
  check <pkg> <map>    verify a map file covers every unit; exit 0 clean, 1 uncovered requirements, 2 malformed map

Requirement units are extracted deterministically from instruction.md: every bullet / numbered item, plus every
paragraph sentence that carries a directive verb. The map is a TSV the verify step writes, one row per unit:

  <id>\t<hash>\t<criterion names, comma-separated, or ->\t<note>

A '-' row means "not a gradeable requirement" and needs a note starting NOT-A-REQUIREMENT:; without that note the
unit counts as UNCOVERED. A '-' on a must / required / should unit is allowed only with the note and is printed as
EXEMPT, so every must-sentence left ungraded is a visible, logged call.

The check is only as honest as the map; it does not judge whether a named criterion really grades the unit. What
it guarantees is that no requirement was skipped, no named criterion is invented, and the map matches the
CURRENT instruction.md (a hash mismatch means the instruction changed after the map was written).
"""

import hashlib, os, re, sys, glob

DIRECTIVE = re.compile(
    r"\b(must|should|shall|required?|include|includes|provide|list|identify|calculate|compute|state|explain|"
    r"recommend|produce|create|build|report|quantify|flag|summari[sz]e|determine|estimate|prepare|draft|"
    r"deliver|save|name|rank|compare|assess|reconcile|document|cite|show|give|write|propose|justify|"
    r"highlight|note|specify|separate|break down|classify|forecast|project|model)\b",
    re.I,
)
STRONG = re.compile(r"\b(must|required?|should|shall)\b", re.I)
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)]|[a-z][.)]|\([a-z0-9]+\))\s+(.*)$", re.I)


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()


def units(pkg):
    """[(id, hash, text)] for the package's instruction.md, in document order."""
    txt = open(
        os.path.join(pkg, "instruction.md"), encoding="utf-8", errors="replace"
    ).read()
    out, in_code = [], False
    for line in txt.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line.strip() or line.lstrip().startswith("#"):
            continue
        # A semicolon joins independent asks ("assess X; determine Y; identify Z"), and a coverage gap is
        # usually one of those clauses, so each clause is its own unit.
        m = BULLET.match(line)
        if m:
            for cl in re.split(r";\s+", _norm(m.group(1))):
                if len(cl) >= 12:
                    out.append(cl)
            continue
        for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z(])", _norm(line)):
            for cl in re.split(r";\s+", sent):
                if len(cl) >= 20 and DIRECTIVE.search(cl):
                    out.append(cl)
    res = []
    for i, t in enumerate(out, 1):
        res.append(("R%02d" % i, hashlib.sha1(t.encode()).hexdigest()[:8], t))
    return res


def criterion_names(pkg):
    names = set()
    for p in glob.glob(os.path.join(pkg, "tests", "**", "*.toml"), recursive=True):
        t = open(p, encoding="utf-8", errors="replace").read()
        names |= set(re.findall(r"^\s*name\s*=\s*['\"]([^'\"]+)['\"]", t, re.M))
    return names


def cmd_list(pkg):
    u = units(pkg)
    print(
        "# %d requirement units from %s/instruction.md"
        % (len(u), os.path.basename(pkg.rstrip("/\\")))
    )
    print(
        "# map row format: <id>\\t<hash>\\t<criterion names comma-separated, or ->\\t<note>"
    )
    for i, h, t in u:
        print("%s\t%s\t%s%s" % (i, h, "[STRONG] " if STRONG.search(t) else "", t))
    return 0


def cmd_check(pkg, mp):
    u = {i: (h, t) for i, h, t in units(pkg)}
    names = criterion_names(pkg)
    if not os.path.exists(mp):
        print("MALFORMED: map file missing: %s" % mp)
        return 2
    rows, malformed = {}, []
    for ln in open(mp, encoding="utf-8", errors="replace").read().splitlines():
        if not ln.strip() or ln.startswith("#"):
            continue
        f = ln.split("\t")
        if len(f) < 3 or not re.match(r"^R\d{2,}$", f[0].strip()):
            malformed.append("bad row: %s" % ln[:120])
            continue
        rows[f[0].strip()] = (
            f[1].strip(),
            f[2].strip(),
            (f[3].strip() if len(f) > 3 else ""),
        )
    uncovered, exempt = [], []
    for i, (h, t) in u.items():
        if i not in rows:
            malformed.append("%s missing from map: %s" % (i, t[:100]))
            continue
        mh, crit, note = rows[i]
        if mh != h:
            malformed.append(
                "%s hash %s != current %s (instruction.md changed since the map; rewrite it)"
                % (i, mh, h)
            )
            continue
        if crit in ("", "-"):
            # A must-sentence can still be ungradeable (R6: "formula cells must carry computed values" cannot be
            # checked under rewardkit 0.1.7), so an explicit NOT-A-REQUIREMENT: note exempts it; every exemption
            # of a must-sentence is printed so the call stays visible in the log.
            if not note.upper().startswith("NOT-A-REQUIREMENT:"):
                uncovered.append(
                    "%s maps to no criterion and has no NOT-A-REQUIREMENT: note: %s"
                    % (i, t[:140])
                )
            elif STRONG.search(t):
                exempt.append("%s %s -> %s" % (i, t[:100], note[:120]))
            continue
        bad = [
            c.strip() for c in crit.split(",") if c.strip() and c.strip() not in names
        ]
        if bad:
            malformed.append(
                "%s names criteria not in tests/*.toml: %s" % (i, ", ".join(bad))
            )
    for i in rows:
        if i not in u:
            malformed.append("map row %s is not a current requirement unit" % i)
    graded = sum(1 for i in u if i in rows and rows[i][1] not in ("", "-"))
    print(
        "coverage trace %s: %d units, %d mapped to criteria, %d uncovered, %d malformed"
        % (
            os.path.basename(pkg.rstrip("/\\")),
            len(u),
            graded,
            len(uncovered),
            len(malformed),
        )
    )
    for m in exempt:
        print("  EXEMPT (must-sentence, not gradeable):", m)
    for m in uncovered:
        print("  UNCOVERED:", m)
    for m in malformed:
        print("  MALFORMED:", m)
    if uncovered:
        return 1
    return 2 if malformed else 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "list":
        sys.exit(cmd_list(sys.argv[2]))
    if len(sys.argv) >= 4 and sys.argv[1] == "check":
        sys.exit(cmd_check(sys.argv[2], sys.argv[3]))
    print(__doc__)
    sys.exit(2)
