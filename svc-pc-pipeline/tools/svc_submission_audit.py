"""Read-only audit (usage: python tools/svc_submission_audit.py 11-2-0 2-7-0 ...): every task we submitted for manual QC has a live-queue row (above Rejected) in the consolidated
SVC tab with EQC ready + a non-Reject status, and 'submit for manual QC' (or better) on the Combined tracker.
"""

import importlib.util

s = importlib.util.spec_from_file_location("m", __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "svc_consolidated_record.py"))
m = importlib.util.module_from_spec(s)
s.loader.exec_module(m)
m.TOK = m.token()

import sys

OURS = [m.norm(x) for x in sys.argv[1:]]
if not OURS:
    sys.exit("give task ids")
rows = m.getv("A1:G1000")
H = next(
    i
    for i, r in enumerate(rows, 1)
    if len(r) > 1 and r[1].strip().lower() == "duplicates"
)
R = next(
    (
        i
        for i, r in enumerate(rows, 1)
        if i < H and any((c or "").strip().lower() == "rejected" for c in r[:2])
    ),
    H,
)
print("consolidated: live 2-%d, Rejected %d, Duplicates %d" % (R - 1, R, H))

m.SHEET = "1JmpP38bcOUDmKlkx_2HndB4GdncPgObC4-_vnQFNaw4"
m.TAB = "SVC QC Tracker Combined"
comb = {m.norm(r[0]): r for r in m.getv("A1:E1000") if r}

bad = 0
for t in OURS:
    where = []
    for i, r in enumerate(rows, 1):
        r = r + [""] * 7
        if m.norm(r[3]) == t:
            sec = "LIVE" if i < R else ("REJECTED" if i < H else "DUP")
            where.append(
                "%s row %d [%s|%s|%s]" % (sec, i, r[4].split("/")[-1], r[5], r[6])
            )
    live_ok = any(w.startswith("LIVE") and "|Reject]" not in w for w in where)
    c = comb.get(t, [""] * 3) + [""] * 3
    ok = live_ok and c[2].strip() != ""
    bad += not ok
    print(
        "%s %-8s combined=%-28s %s"
        % ("OK " if ok else "BAD", t, c[2][:28], "; ".join(where))
    )
print("\n%d of %d OK" % (len(OURS) - bad, len(OURS)))
