#!/usr/bin/env python3
"""Rebuild the frozen, positionally aligned copies that fix_from_dataos.sh reads (dataos-fresh/fixer/{majors,status}.csv).
Why: build_dataos_union.py joins majors.csv and status.csv by ROW POSITION, and the verify session rewrites status.csv in
tasks.txt order, so the fixer must read a copy whose rows are aligned by key (task, reviewer, check). The first rebuild
(2026-09-19 19:20Z) was a one-off; every later fixer pass needs the same rebuild against the current rulings.
Majors = dataos-fresh/majors.csv plus opus-addendum/majors.csv (rows not already present). Status = the verify session's
status.csv, with opus-addendum/status.csv as the fallback for addendum rows it has not ruled yet. A majors row with no
status row anywhere is written as still_true=yes (the fixer's conservative default) and reported.
Usage: python3 build_fixer_copies.py [--fresh DIR] [--dry-run]
"""

import argparse
import csv
import pathlib

FRESH = pathlib.Path("/root/qc/_prompts/verify/dataos-fresh")


def rows(p):
    with open(p, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return r.fieldnames or [], list(r)


def key(r):
    return (r["task"].strip(), r["reviewer"].strip(), r["check"].strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", default=str(FRESH))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    fresh = pathlib.Path(a.fresh)
    mcols, majors = rows(fresh / "majors.csv")
    add_m = fresh / "opus-addendum" / "majors.csv"
    _, addm = rows(add_m) if add_m.is_file() else (mcols, [])
    scols, status = rows(fresh / "status.csv")
    add_s = fresh / "opus-addendum" / "status.csv"
    sadd = rows(add_s)[1] if add_s.is_file() else []
    smap = {}
    for (
        r
    ) in (
        sadd
    ):  # addendum first; the verify session's status.csv overrides once it has ruled a row
        smap[key(r)] = r
    for r in status:
        smap[key(r)] = r
    have = {key(m) for m in majors}
    allm = majors + [r for r in addm if key(r) not in have]
    out_s, missing = [], []
    for m in allm:
        s = smap.get(key(m))
        if s is None:
            missing.append(key(m))
            s = {c: "" for c in scols}
            s.update(
                task=m["task"],
                reviewer=m["reviewer"],
                check=m["check"],
                still_true="yes",
            )
        out_s.append({c: s.get(c, "") for c in scols})
    per = {}
    for m, s in zip(allm, out_s):
        p = per.setdefault(m["task"], [0, 0])
        p[0] += 1
        p[1] += s["still_true"].strip().lower() != "no"
    for t in sorted(per):
        print(f"{t}: {per[t][0]} rows, {per[t][1]} still-true")
    print(
        f"{len(allm)} majors rows ({len(majors)} batch + {len(allm) - len(majors)} addendum), "
        f"{len(missing)} without a status row (written still_true=yes): {missing[:6]}"
    )
    if a.dry_run:
        return
    (fresh / "fixer").mkdir(exist_ok=True)
    with open(fresh / "fixer" / "majors.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=mcols, lineterminator="\n")
        w.writeheader()
        for m in allm:
            w.writerow({c: m.get(c, "") for c in mcols})
    with open(fresh / "fixer" / "status.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=scols, lineterminator="\n")
        w.writeheader()
        w.writerows(out_s)
    print(
        "wrote fixer/majors.csv and fixer/status.csv, aligned by (task, reviewer, check)"
    )


if __name__ == "__main__":
    main()
