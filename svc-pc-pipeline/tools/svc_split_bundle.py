"""Split an oversized, not-yet-uploaded bundle into two under DataOS's 500 MB zip limit.
Usage (sandbox): python3 svc_split_bundle.py <bundle name, e.g. svc-v81-batch10> [--apply]
Moves the bundle's shipped records + zip to _v7/shipped/_not_uploaded/ (they were never uploaded), then rebuilds
two bundles <name>a / <name>b through svc_bundle_upload.py so every freshness gate runs again.
"""

import collections, glob, json, os, shutil, subprocess, sys, zipfile

QC = "/root/qc"
name, apply = sys.argv[1], "--apply" in sys.argv
bz = "%s/_bundles/%s.zip" % (QC, name)
sizes = collections.Counter()
for i in zipfile.ZipFile(bz).infolist():
    sizes[i.filename.split("/")[0]] += i.compress_size
tasks = sorted(sizes, key=lambda t: -sizes[t])
a, b, sa, sb = [], [], 0, 0
for t in tasks:  # greedy balance by compressed size
    if sa <= sb:
        a.append(t)
        sa += sizes[t]
    else:
        b.append(t)
        sb += sizes[t]
print(
    "%d tasks, %.0f MB -> a: %d tasks %.0f MB, b: %d tasks %.0f MB"
    % (len(tasks), (sa + sb) / 1e6, len(a), sa / 1e6, len(b), sb / 1e6)
)
recs = [
    p
    for p in glob.glob(QC + "/_v7/shipped/*.json")
    if json.load(open(p)).get("bundle") == name + ".zip"
]
print("shipped records naming %s.zip: %d" % (name, len(recs)))
if not apply:
    print("DRY RUN")
    sys.exit(0)
dest = QC + "/_v7/shipped/_not_uploaded"
os.makedirs(dest, exist_ok=True)
for p in recs:
    shutil.move(p, os.path.join(dest, os.path.basename(p)[:-5] + "." + name + ".json"))
for p in (bz, bz + ".manifest.json"):
    if os.path.exists(p):
        shutil.move(p, os.path.join(dest, os.path.basename(p)))
for suffix, part in (("a", a), ("b", b)):
    r = subprocess.run(
        [
            "python3",
            QC + "/tools/svc_bundle_upload.py",
            "bundle",
            "--name",
            name + suffix,
            "--tasks",
        ]
        + part,
        capture_output=True,
        text=True,
    )
    print(
        "\n".join(
            l
            for l in r.stdout.splitlines()
            if l.startswith(("BUNDLE", "===", "  REFUSED"))
        )
    )
