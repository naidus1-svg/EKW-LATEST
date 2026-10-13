"""Pass rate by cohort (verify_capped vs full READY) for one return zip, plus each pass's DataOS rev id.
Usage (sandbox, /root/qc): python3 tools/svc_return_cohort.py <return zip>"""

import re, sys, zipfile

z = sys.argv[1]
names = zipfile.ZipFile(z).namelist()
cap = {}
for l in open("_v7/ready.txt"):
    p = l.rstrip("\n").split("\t")
    if p and p[0]:
        cap[p[0]] = "verify_capped" in l
acc = set(open("_v7/accepted.txt").read().split())
tasks = sorted({n.split("/")[0] for n in names if n.startswith("SVC-PC-")})
c = {True: [0, 0], False: [0, 0]}
for t in tasks:
    k = cap.get(t, False)
    c[k][1] += 1
    c[k][0] += t in acc
print(
    "verify_capped: %d/%d pass | full READY: %d/%d pass"
    % (c[True][0], c[True][1], c[False][0], c[False][1])
)
for t in tasks:
    if t in acc:
        rev = sorted(
            {
                m.group(1)
                for n in names
                if n.startswith(t + "/")
                for m in [re.search(r"rev_\d+__(\d+)", n)]
                if m
            }
        )
        print("PASS", t, rev, "capped" if cap.get(t) else "full")
