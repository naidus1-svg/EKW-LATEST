import os, re, json, glob, time, collections, datetime as dt, statistics

Q = "/root/qc"
SP = f"{Q}/stream-pipe"
C = "/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready"
NOW = dt.datetime.utcnow()


def rd(p):
    try:
        return open(p).read()
    except Exception:
        return ""


def sset(p):
    return set(rd(p).split())


corpus = sorted(d for d in os.listdir(C) if d.startswith("SVC-PC-"))
spd = sorted(d for d in os.listdir(SP) if d.startswith("SVC-PC-"))
print(
    f"NOW {NOW:%Y-%m-%d %H:%M}Z | corpus tasks {len(corpus)} | stream-pipe dirs {len(spd)} | "
    f"in stream-pipe not corpus {sorted(set(spd)-set(corpus))} | in corpus not stream-pipe {sorted(set(corpus)-set(spd))}"
)

DR = sset(f"{Q}/lanes/DATAOS_REJECTED")
SUB = sset(f"{Q}/SUBMITTED.txt")
# DataOS verdicts in hand: the 43 old returns + batch-4 returns (67-1-0, 8-2-0) + batch-3 (54-2-0, from handoff)
DATAOS_REVIEWED = set(DR) | {"SVC-PC-67-1-0", "SVC-PC-8-2-0", "SVC-PC-54-2-0"}


def latest(t, rev):
    fs = [
        f
        for f in glob.glob(f"{SP}/{t}/CR.{rev}.round*.json")
        if re.search(r"round\d+\.json$", f)
    ]
    if not fs:
        return None
    fs.sort(key=lambda f: int(re.search(r"round(\d+)\.json$", f).group(1)))
    f = fs[-1]
    rnd = int(re.search(r"round(\d+)\.json$", f).group(1))
    try:
        j = json.load(open(f))
        mc = j.get("major_count")
        if not isinstance(mc, int) or "checks" not in j:
            return ("bad", rnd, None)
        return ("ok", rnd, mc)
    except Exception:
        return ("bad", rnd, None)


def state(t):
    return rd(f"{SP}/{t}/STATE").split()


# zip step last event per task
zip_last = {}
for ln in rd(f"{Q}/_prompts/zip_when_ready.log").splitlines():
    m = re.match(r"(\S+) (ZIPPED|BLOCK|SKIP|ORACLE) (SVC-PC-\S+)(.*)", ln)
    if m:
        zip_last[m.group(3)] = (m.group(1), m.group(2), m.group(4).strip()[:110])

rows = {}
for t in corpus:
    g, s = latest(t, "glm"), latest(t, "sonnet")
    st = state(t)
    fr = [int(x) for x in re.findall(r"FIX_FROM_REVIEWS_(\d+)", " ".join(st))]
    rows[t] = dict(
        g=g,
        s=s,
        fixed=max(fr) if fr else 0,
        resolved=os.path.exists(f"{SP}/{t}/DATAOS_MAJORS_RESOLVED"),
        zipnew=os.path.exists(f"{Q}/out/pipe/{t}.zip")
        and os.path.getmtime(f"{Q}/out/pipe/{t}.zip")
        > time.mktime(dt.datetime(2026, 9, 19, 1, 53).timetuple()) - time.timezone,
        zipold=os.path.exists(f"{Q}/out/pipe/{t}.zip"),
        hold=os.path.exists(f"{Q}/out/pipe/_hold/{t}.zip"),
    )


def rv(x):
    return x is not None and x[0] == "ok"


both = [t for t in corpus if rv(rows[t]["g"]) and rv(rows[t]["s"])]
one = [t for t in corpus if (rv(rows[t]["g"]) != rv(rows[t]["s"]))]
none = [t for t in corpus if not rv(rows[t]["g"]) and not rv(rows[t]["s"])]
bad = [
    t
    for t in corpus
    if (rows[t]["g"] and rows[t]["g"][0] == "bad")
    or (rows[t]["s"] and rows[t]["s"][0] == "bad")
]
pas = [t for t in both if rows[t]["g"][2] == 0 and rows[t]["s"][2] == 0]
fail = [t for t in both if t not in pas]
print(
    "\n== A. REAL comprehensive review (canon prompt, workspace mode: GLM + Sonnet reviewers on the exact bytes), denominator = %d corpus tasks"
    % len(corpus)
)
print(
    f"   both reviewers have a verdict: {len(both)} | one reviewer only: {len(one)} | neither: {len(none)} | unparseable file present: {len(bad)}"
)
print(
    f"   of the {len(both)} with both: PASS (both 0 majors) = {len(pas)} | FAIL (>=1 major from either) = {len(fail)}"
)
print(
    f"   PASS at round0 (never needed a fix): {sum(1 for t in pas if max(rows[t]['g'][1], rows[t]['s'][1]) == 0)} | PASS after a fix round: {sum(1 for t in pas if max(rows[t]['g'][1], rows[t]['s'][1]) >= 1)}"
)
oneg = [t for t in one if rv(rows[t]["g"])]
ones = [t for t in one if rv(rows[t]["s"])]
print(
    f"   one-reviewer-only split: GLM only {len(oneg)} (of which majors seen: {sum(1 for t in oneg if rows[t]['g'][2]>0)}), Sonnet only {len(ones)} (majors seen: {sum(1 for t in ones if rows[t]['s'][2]>0)})"
)

# buckets
B = collections.OrderedDict()


def add(k, t):
    B.setdefault(k, []).append(t)


for t in corpus:
    r = rows[t]
    g, s = r["g"], r["s"]
    ok_g, ok_s = rv(g), rv(s)
    passed = ok_g and ok_s and g[2] == 0 and s[2] == 0
    if t in DATAOS_REVIEWED:
        loc = (
            "local PASS"
            if passed
            else ("local FAIL" if (ok_g and ok_s) else "local review incomplete")
        )
        k = (
            f"1. DataOS real verdict in hand, NOT accepted ({loc}"
            + (", DataOS majors verified fixed" if r["resolved"] else "")
            + ")"
        )
        add(k, t)
        continue
    if t in SUB:
        add("2. Uploaded to DataOS, verdict not received yet", t)
        continue
    if r["zipnew"]:
        add("3a. ZIPPED under the new rule (ready to upload)", t)
        continue
    if passed:
        z = zip_last.get(t)
        pk = rd(f"{SP}/{t}/PARKED.md")
        if z and z[1] == "BLOCK":
            add("3b. Clean on both reviewers, BLOCKED at the zip gates", t)
        elif z and z[1] == "SKIP":
            add(
                "3c. Clean on both reviewers, bytes changed since review (re-review needed)",
                t,
            )
        elif pk and not re.search(
            r"majors still present after|failed, rc=10|check-fix: still blocked", pk
        ):
            add("3d. Clean on both reviewers, parked for a human", t)
        else:
            add("3e. Clean on both reviewers, waiting for the zip step (queue)", t)
        continue
    if ok_g and ok_s:
        if r["fixed"] == 0:
            add("4a. Has majors, waiting for its first fix round", t)
        elif max(g[1], s[1]) < 1 or min(g[1], s[1]) < 1:
            add("4b. Fix round applied, re-reviews in flight", t)
        else:
            add("4c. Re-reviewed after a fix, still has majors", t)
        continue
    if ok_g or ok_s:
        add("5a. Review in progress: one reviewer done", t)
    else:
        add("5b. Review not started or unparseable", t)

print("\n== B. Grouping (mutually exclusive, sums to %d)" % len(corpus))
tot = 0
for k in sorted(B):
    v = B[k]
    tot += len(v)
    ids = " ".join(x.replace("SVC-PC-", "") for x in v) if len(v) <= 30 else ""
    print(f"   {len(v):4d}  {k}" + (f"\n         {ids}" if ids else ""))
print(f"   total {tot}")

# 3b block reasons
print("\n== 3b/3c detail: last zip-step event per gate-blocked task")
for t in B.get("3b. Clean on both reviewers, BLOCKED at the zip gates", []):
    print(
        "  ",
        t.replace("SVC-PC-", ""),
        zip_last[t][0][11:16] + "Z",
        zip_last[t][2][:100],
    )


# throughput
def ts(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


print("\n== C. Throughput (last 60 min unless noted)")
cut = NOW - dt.timedelta(minutes=60)
fin = []
for ln in rd(f"{Q}/_prompts/bulk_review.log").splitlines():
    m = re.match(r"(\S+) FINISH (SVC-PC-\S+) (glm|sonnet) rc=(\d+) (.*)", ln)
    if m:
        fin.append((ts(m.group(1)), m.group(3), m.group(5)))
recent = [f for f in fin if f[0] >= cut]
okr = [f for f in recent if "maj" in f[2]]
print(
    f"   bulk round0 reviews finished: {len(recent)} in 60 min ({len([f for f in okr if f[1]=='glm'])} glm ok, {len([f for f in okr if f[1]=='sonnet'])} sonnet ok, {len(recent)-len(okr)} failed/NO-JSON)"
)
bs = [ln for ln in rd(f"{Q}/_prompts/bulk_review.log").splitlines() if " START " in ln]
first_ts = ts(fin[0][0].strftime("%Y-%m-%dT%H:%M:%SZ")) if fin else None
print(
    f"   bulk since first finish {first_ts:%H:%M}Z: {len(fin)} finished, {len([f for f in fin if 'maj' in f[2]])} parsed"
)
fx = rd(f"{Q}/_prompts/fix_from_reviews.log").splitlines()
done = [
    ts(re.match(r"(\S+)", l).group(1))
    for l in fx
    if re.match(r"\S+Z DONE .* re-reviews both finished", l)
]
applied = [
    ts(re.match(r"(\S+)", l).group(1))
    for l in fx
    if re.match(r"\S+Z DONE .* round applied", l)
]
starts = {}
cyc = []
for l in fx:
    m = re.match(r"(\S+Z) START (SVC-PC-\S+) fix-from-reviews", l)
    if m:
        starts[m.group(2)] = ts(m.group(1))
    m = re.match(r"(\S+Z) DONE (SVC-PC-\S+) round1 re-reviews both finished", l)
    if m and m.group(2) in starts:
        cyc.append((ts(m.group(1)) - starts[m.group(2)]).total_seconds() / 60)
print(
    f"   fix rounds applied in last 60 min: {sum(1 for x in applied if x>=cut)}; both-reviewer re-reviews finished in last 60 min: {sum(1 for x in done if x>=cut)}; since 01:40Z: applied {len(applied)}, re-reviews done {len(done)}"
)
if cyc:
    print(
        f"   fix cycle (START fix -> both round1 re-reviews finished): n={len(cyc)} median {statistics.median(cyc):.0f} min, max {max(cyc):.0f} min"
    )
zl = rd(f"{Q}/_prompts/zip_when_ready.log").splitlines()
oz = [(ts(l.split()[0]), l) for l in zl if " ORACLE " in l]
print(
    f"   zip step: {len(oz)} oracle probes logged in total, {sum(1 for l in zl if ' BLOCK ' in l)} BLOCK, {sum(1 for l in zl if ' ZIPPED ' in l)} ZIPPED, {sum(1 for l in zl if ' SKIP ' in l)} SKIP"
)
# remaining review workload
miss_g = [t for t in corpus if not rv(rows[t]["g"])]
miss_s = [t for t in corpus if not rv(rows[t]["s"])]
print(
    f"   round0 reviews still missing: glm {len(miss_g)}, sonnet {len(miss_s)}, total {len(miss_g)+len(miss_s)}"
)
# glm solver
left = 404 - sum(
    1
    for d in glob.glob(f"{Q}/runs/SVC-PC-*/glm-*")
    if rd(f"{d}/claude_exit_code.txt").strip() == "0"
)
print(f"   GLM solver runs still needed: {left}")
print(
    "   in-flight now: review agents",
    os.popen("ps -eo args | grep -c '[r]un_workspace_review.py --task'").read().strip(),
)
