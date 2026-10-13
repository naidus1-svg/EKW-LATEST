#!/usr/bin/env python3
"""Static estimate of what an EMPTY submission scores on a Harbor task package (the DataOS NOP eval).

DataOS pipeline 141 v8 runs a NOP eval (nothing written to /app) and files a WEAK_GRADER major when it scores above
0.20. On 2026-10-06 three lane-READY tasks failed exactly this way: MKT-131 (0.49), MKT-141 (0.483) and SVC-PC-93-5-0
(0.3488); LGL-131 (0.2311, ekw-v1-batch163) had failed the same way earlier. Every one had criteria in exception form
("FAIL only if X is stated", "A memo that states no X passes", "PASS otherwise"), which a literal judge passes when it
reports "The file was not found". The next revisions of MKT-141, LGL-131 and SVC-PC-93-5-0 added a per-criterion
presence gate ("Presence gate: FAIL if the workbook is absent. Otherwise: ...") and each scored 0.0 on the NOP eval;
MKT-131's next revision has no exposed criterion under this check and also scored 0.0.

What this computes: for every judge group in tests/*/judge.toml, the weight share of criteria that are EXPOSED (their
wording passes on an absent file) and NOT GATED (no clause failing an absent/missing/empty file), then the task score
with the reward.toml group weights (weighted_mean; a group with no reward.toml weight uses its judge.toml weight).
That is an UPPER BOUND: it assumes the judge reads every exposed criterion literally, and DataOS's judge does that on
some runs and not others (it passed 261 of 592 exposed criteria across the 44 NOP evals), so a task above the bound
can pass one round and fail the next.

Validation (nop_floor_validate.py over every DataOS *-with-runs.zip on disk, 2026-10-06): 44 task revisions carry a
NOP eval, 4 scored above 0.20. At 0.20 this check flags all 4 and 7 that scored 0.00-0.16 (precision 0.36, recall
1.00). Of 308 gated criteria, the NOP judge passed 0.

What it does NOT establish: that a task below the threshold will pass the NOP eval (the judge passed 87 criteria this
check calls safe), or anything about the other reviewers. A judge group whose files= path also exists in
environment/initial_workspace is read from that file on an empty submission; the validator lists those groups.

Usage:
  python nop_floor_check.py <package_root> [--threshold 0.20] [--json out.json]
package_root is a task dir holding tests/ (e.g. .../ekw_qc/MKT-141 or .../03_dataos_ready/SVC-PC-93-5-0), or a
one-task upload zip (e.g. .../_ekw/ready/MKT-141.zip).
Exit 0 at or below the threshold, 1 above it (the output lists every exposed criterion and the fix), 2 on a package
it cannot read (no tests/*/judge.toml)."""

import argparse, json, os, re, sys, tomllib, zipfile

THRESHOLD = 0.20

# Wording that passes when the deliverable is absent: the criterion only fails on something PRESENT in the file.
EXPOSED_RULES = [
    ("fail_only_if", r"\bfail(s|ed)?\s+only\s+(if|when|where)\b"),
    ("pass_unless", r"\bpass(es)?\s+unless\b"),
    ("pass_otherwise", r"\b(pass(es)?\s+otherwise|otherwise,?\s+(it\s+)?pass(es)?)\b"),
    (
        "absent_passes",
        r"\b(that|which|who)\s+(gives|states|reports|mentions|shows|lists|carries|cites|names|includes"
        r"|contains|presents|makes|offers|provides|has|uses|attributes|assigns|quotes)\s+no\b[^.]{0,200}?"
        r"\b(pass(es)?|meets\s+this|is\s+acceptable|satisf(y|ies))\b",
    ),
    (
        "not_mention_passes",
        r"\b(does\s+not|doesn't|never)\s+(mention|address|discuss|state|give|cite|name|include|raise"
        r"|refer|report|use|attribute|present|make|quote|list|show|carry|provide)\b[^.]{0,200}?"
        r"\b(pass(es)?|meets\s+this|is\s+acceptable)\b",
    ),
    (
        "pass_if_not",
        r"\bpass(es)?\s+if\s+(the\s+)?[\w /-]{0,40}?\b(does\s+not|doesn't|never|avoids|omits|contains\s+no"
        r"|makes\s+no|states\s+no|gives\s+no|presents\s+no|has\s+no|includes\s+no)\b",
    ),
    ("pass_if_no", r"\bpass(es)?\s+if\s+no\b"),
    (
        "avoids",
        r"\b(evaluate|check|assess)\s+whether\s+the\s+[\w /-]{0,40}?\b(avoids|refrains|does\s+not|never)\b",
    ),
    (
        "if_shown",
        r"\bif\s+(shown|present|given|stated|included|mentioned|it\s+(appears|is\s+shown|states))\b",
    ),
    (
        "conditional_antecedent",
        r"^\W*(\[[^\]]*\]\s*)?(requirement:\s*)?if\s+(the\s+)?(workbook|memo|request\s+set"
        r"|document|deliverable|tracker|response|deck|report|plan|letter|notice|file|analysis|model|sheet|brief|email"
        r"|summary)\b",
    ),
    (
        "no_x_presented",
        r"^\W*[^.]{0,120}?\b(no|none\s+of\s+the)\s+[\w ,/-]{1,80}?\s+(is|are)\s+(presented|stated"
        r"|described|treated|shown|reported|labelled|labeled|given)\s+as\b",
    ),
]
# Cross-deliverable consistency ("PASS if no figure differs between the memo and the workbook") is exposed only in a
# group that reads two or more files; in a one-file group the same words describe the file against its sources.
CONSISTENCY = (
    "consistency",
    r"\b(do(es)?\s+not\s+contradict|no\s+[\w ]{0,40}differs?\b|the\s+same\s+[\w -]{0,40}"
    r"\b(in|across|between)\s+(both|the\s+two)|consistent\s+(with|across|between))",
)

_FILE = (
    r"(file|document|memo(randum)?|workbook|spreadsheet|deliverable|notice|letter|report|deck|tracker|plan|brief"
    r"|email|output|submission|[\w-]+\.(docx|xlsx|xlsm|pptx|pdf|csv|md|txt))"
)
# A presence gate: the criterion FAILS when the deliverable is absent. Wording taken from the fixed revisions.
GATE = re.compile(
    r"(presence\s+gate|existence\s+gate"
    r"|absent\s+" + _FILE + r"\s+is\s+never\s+a\s+pass"
    r"|fail(s|ed)?\s+(immediately\s+)?if\s+(the\s+|either\s+(the\s+)?|any\s+)?[\w .,/()'-]{0,80}?\b"
    + _FILE
    + r"\b[\w .,/()'-]{0,40}?\b(is|are)\s+(missing|absent|empty|unreadable|not\s+(found|present|provided|supplied))"
    r"|if\s+(that|the|either|any)\s+[\w .,/()'-]{0,60}?\b"
    + _FILE
    + r"\b[^.]{0,30}?\b(is|are)\s+(missing|absent"
    r"|empty|unreadable|not\s+(found|present|provided))[^.]{0,120}?\bfail)",
    re.I | re.S,
)

_RULES = [(n, re.compile(p, re.I | re.S)) for n, p in EXPOSED_RULES]
_CONS = re.compile(CONSISTENCY[1], re.I | re.S)

# Commission-only form, the SVC house style: a statement, then FAIL clauses that each name something PRESENT and
# wrong ("Alice Chen is the CEO. FAIL if Alice Chen is given a title that contradicts CEO."), and no PASS clause that
# requires content. An empty file contains nothing wrong, so a literal judge passes it. A FAIL clause with an omission
# marker ("FAIL if the line is missing", "FAIL if no figure quantifies the scope") fails on an empty file instead.
_CLAUSE_END = r"(?=\.\s|\.$|;|\n|$)"
_FAIL_CLAUSE = re.compile(
    r"\bfail(?:s|ed)?\s+(?:immediately\s+)?(?:if|when|where)\b(.*?)" + _CLAUSE_END,
    re.I | re.S,
)
_PASS_CLAUSE = re.compile(
    r"\bpass(?:es)?\s+(?:only\s+)?(?:if|when|where)\b(.*?)" + _CLAUSE_END, re.I | re.S
)
_OMISSION = re.compile(
    r"\b(missing|absent|omit\w*|does\s+not|doesn't|do\s+not|did\s+not|never|no\b|none|nothing|lacks?|lacking|without"
    r"|fails?\s+to|leaves?|left|only\s+after|neither|nor|incomplete|fewer|less\s+than|not\s+(?!a\b|the\b|as\b|been\b)\w+)",
    re.I,
)
_NEGATIVE_PASS = re.compile(
    r"\b(does\s+not|doesn't|do\s+not|never|no\b|none|avoids|omits|without|not\s+\w+)",
    re.I,
)


def _commission_only(desc):
    fails = [m.group(1) for m in _FAIL_CLAUSE.finditer(desc)]
    if not fails or any(_OMISSION.search(f) for f in fails):
        return False
    return not any(
        not _NEGATIVE_PASS.search(m.group(1)) for m in _PASS_CLAUSE.finditer(desc)
    )


def classify(desc, n_files=1):
    """Return (exposed, gated, rules) for one criterion description."""
    rules = [n for n, p in _RULES if p.search(desc)]
    if n_files >= 2 and _CONS.search(desc):
        rules.append(CONSISTENCY[0])
    if _commission_only(desc):
        rules.append("commission_only_fail")
    gated = bool(GATE.search(desc))
    return bool(rules) and not gated, gated, rules


def load_dir(root):
    """{relative path under the package root: text} for tests/reward.toml and tests/*/judge.toml."""
    out, tests = {}, os.path.join(root, "tests")
    if os.path.isfile(os.path.join(tests, "reward.toml")):
        out["tests/reward.toml"] = open(
            os.path.join(tests, "reward.toml"), encoding="utf-8"
        ).read()
    if os.path.isdir(tests):
        for g in sorted(os.listdir(tests)):
            p = os.path.join(tests, g, "judge.toml")
            if os.path.isfile(p):
                out[f"tests/{g}/judge.toml"] = open(p, encoding="utf-8").read()
    return out


def load_zip(path):
    """Same as load_dir for an upload zip: finds the tests/ dir at any depth (one task per zip)."""
    out = {}
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            m = re.search(r"(?:^|/)(tests/(?:reward\.toml|[^/]+/judge\.toml))$", n)
            if m:
                if m.group(1) in out:
                    raise ValueError(
                        f"more than one task in {path}: {m.group(1)} appears twice"
                    )
                out[m.group(1)] = z.read(n).decode("utf-8")
    return out


def estimate(files):
    """files: {relpath: text} as load_dir returns. Returns the report dict."""
    gw = {}
    if "tests/reward.toml" in files:
        for r in tomllib.loads(files["tests/reward.toml"]).get("reward", []):
            if r.get("aggregation", "weighted_mean") != "weighted_mean":
                raise ValueError(
                    f"reward aggregation {r.get('aggregation')!r} is not weighted_mean"
                )
            gw.update(r.get("weights", {}))
    groups, num, den = [], 0.0, 0.0
    for path in sorted(files):
        m = re.fullmatch(r"tests/([^/]+)/judge\.toml", path)
        if not m:
            continue
        j = tomllib.loads(files[path])
        judge = j.get("judge", {})
        n_files = len(judge.get("files", []))
        w_group = gw.get(m.group(1), judge.get("weight", 1.0))
        crits, wsum, wexp = [], 0.0, 0.0
        for c in j.get("criterion", []):
            exposed, gated, rules = classify(c.get("description", ""), n_files)
            w = float(c.get("weight", 1.0))
            wsum += w
            wexp += w * exposed
            crits.append(
                dict(
                    name=c.get("name"),
                    weight=w,
                    exposed=exposed,
                    gated=gated,
                    rules=rules,
                )
            )
        share = wexp / wsum if wsum else 0.0
        groups.append(
            dict(
                group=m.group(1),
                weight=w_group,
                files=judge.get("files", []),
                exposed_share=share,
                criteria=crits,
            )
        )
        num += w_group * share
        den += w_group
    if not groups:
        raise FileNotFoundError("no tests/*/judge.toml")
    return dict(
        estimate=num / den if den else 0.0,
        groups=groups,
        n_criteria=sum(len(g["criteria"]) for g in groups),
        n_exposed=sum(c["exposed"] for g in groups for c in g["criteria"]),
        n_gated=sum(c["gated"] for g in groups for c in g["criteria"]),
    )


def directive(rep, threshold):
    """The fix instruction a lane feeds back when the estimate is over the threshold."""
    lines = [
        f"NOP floor: an empty submission can score up to {rep['estimate']:.3f} on this rubric (DataOS files a "
        f"WEAK_GRADER major above {threshold:.2f}; MKT-131, MKT-141 and SVC-PC-93-5-0 failed this way on "
        "2026-10-06). These criteria pass when the deliverable is absent because they only fail on something "
        "the file states. Add a presence gate at the START of each one, naming its file, e.g. 'FAIL if "
        "<file> is missing, empty or unreadable. Otherwise: <existing text>'. Do not change what the criterion "
        "tests, its weight, or the golden; the golden must still score 1.0."
    ]
    for g in rep["groups"]:
        ex = [c for c in g["criteria"] if c["exposed"]]
        if not ex:
            continue
        lines.append(
            f"- {g['group']} (group weight {g['weight']}, files {', '.join(os.path.basename(f) for f in g['files'])}, "
            f"exposed share {g['exposed_share']:.2f}): "
            + ", ".join(c["name"] for c in ex)
        )
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("package_root")
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    ap.add_argument("--json", help="write the full per-criterion report here")
    a = ap.parse_args(argv)
    try:
        load = load_zip if a.package_root.endswith(".zip") else load_dir
        rep = estimate(load(a.package_root))
    except (
        FileNotFoundError,
        ValueError,
        tomllib.TOMLDecodeError,
        zipfile.BadZipFile,
    ) as e:
        print(f"NOP-FLOOR ERROR {a.package_root}: {e}")
        return 2
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1)
    verdict = "FAIL" if rep["estimate"] > a.threshold else "PASS"
    print(
        f"NOP-FLOOR {verdict} estimate={rep['estimate']:.3f} threshold={a.threshold:.2f} "
        f"criteria={rep['n_criteria']} exposed={rep['n_exposed']} gated={rep['n_gated']}"
    )
    if verdict == "FAIL":
        print(directive(rep, a.threshold))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
