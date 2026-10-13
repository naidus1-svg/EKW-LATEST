#!/usr/bin/env python3
"""Convert an old-format harbor task (verifier.json + verifier_lib) to the
reference-aligned reward-kit format used on the Data OS platform.

Works for both EKW and DermOTS source bundles:
  in:   instruction.md, task.toml([metadata]), environment/{Dockerfile,data/...},
        solution/{solve.sh,golden_outputs/*}, tests/{verifier.json,...}
  out:  reward-kit task — task.toml(schema 1.1), environment/{Dockerfile(colab-cli),
        initial_workspace/*}, solution/{solve.sh, files/<deliverables>, reasoning.docx?},
        tests/{test.sh, task_prompt.txt, reward.toml, deliverables/judge.toml}

Format decisions (locked): workspace=/app; judge read from verifier.json config.models;
single judge.toml over the specific deliverable file(s); per-criterion weight kept;
[scoring]=weighted_mean; reward.toml headline reward=weighted_mean; [metadata]=category+tags
only (recognized fields); benchmark_type/expert_time_estimate omitted; skills dropped.

Usage: python3 to_rewardkit.py <src_task_dir> <out_task_dir> <name_prefix>   # prefix e.g. ekw | dermots
"""
import json, os, re, shutil, sys, tomllib

_STOP = {"and", "of", "the", "a", "for", "to", "with", "an", "or"}
JUDGE_ENV = "ANTHROPIC_API_KEY"   # locked policy: these rewardkit builds judge with Claude only

# Source verifier.json config.models can name any provider (EKW's spec judge is
# openai/gpt-5.4). We deliberately do NOT carry that model over: [verifier.env] only
# ever provisions ANTHROPIC_API_KEY on these builds, so a non-Anthropic judge model
# would fail at grading time with "Missing credentials" -- which surfaced as an opaque
# RewardFileNotFoundError, not a clear auth error, because it can kill the run before
# test.sh's fallback gets to write reward.json. Force every judge onto Claude instead.
_DEFAULT_JUDGE = "anthropic/claude-opus-4-8"


def pick_judge(raw_models):
    """Return the Claude judge to use, overriding any non-Anthropic model named in the
    source verifier.json (see policy note above). An already-Anthropic model is kept
    as-is (e.g. DermOTS's anthropic/claude-sonnet-4-6)."""
    candidate = (raw_models or [_DEFAULT_JUDGE])[0]
    return candidate if candidate.startswith("anthropic/") else _DEFAULT_JUDGE

TEST_SH = """\
#!/bin/bash
export LITELLM_DROP_PARAMS=true

VERIFIER_DIR="${VERIFIER_DIR:-/logs/verifier}"
mkdir -p "$VERIFIER_DIR"

# rewardkit writes NOTHING on failure (bad/missing judge credentials, judge API
# error, etc. -- confirmed by smoke test). Without this fallback, any hiccup at
# verify time surfaces as an opaque harbor.verifier.verifier.RewardFileNotFoundError
# instead of a diagnosable reward=0.0 + error message.
write_infra_failure() {
  local message="$1"
  echo "0.0" > "$VERIFIER_DIR/reward.txt"
  python3 - "$VERIFIER_DIR" "$message" <<'PY'
import json, sys
from pathlib import Path
verifier_dir = Path(sys.argv[1])
message = sys.argv[2]
(verifier_dir / "reward.json").write_text(
    json.dumps({"reward": 0.0, "error": message}, indent=2), encoding="utf-8")
PY
}

if ! pip install --quiet 'harbor-rewardkit[all]'; then
  write_infra_failure "pip install harbor-rewardkit[all] failed (network/PyPI unavailable?)"
  exit 1
fi

rewardkit /tests --output "$VERIFIER_DIR/reward.json" 2>&1 | tee "$VERIFIER_DIR/runtime.log"
RC=${PIPESTATUS[0]}

if [ ! -s "$VERIFIER_DIR/reward.json" ]; then
  write_infra_failure "rewardkit exited $RC and wrote no reward.json; see runtime.log"
  exit 1
fi

exit "$RC"
"""
SOLVE_SH = "#!/bin/bash\nset -euo pipefail\nmkdir -p /app\ncp -a /solution/files/. /app/\n"
DOCKERFILE = """\
FROM us-central1-docker.pkg.dev/turing-gpt/gdm-agentic-vet-ext/colab-cli:1.1.0

ENV GEMINI_CLI_TRUST_WORKSPACE=true

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \\
    poppler-utils \\
    file \\
    jq \\
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \\
    pandas==3.0.3 numpy==2.4.4 scipy==1.17.1 openpyxl==3.1.5 xlsxwriter==3.2.9 python-pptx==1.0.2 python-docx==1.2.0 lxml==6.1.0 pdfplumber==0.11.9 PyMuPDF==1.27.2.3 PyPDF2==3.0.1 pypdf==6.11.0 pdfminer.six==20251230 pdf2image==1.17.0 Pillow==12.2.0 matplotlib==3.10.9 seaborn==0.13.2

COPY initial_workspace/ /app/
"""
TASK_TOML = """\
schema_version = "1.1"

[task]
name = "{name}"

[metadata]
category = "{category}"
tags = {tags}
# Only platform-recognized [metadata] fields emitted (category, tags).
# benchmark_type / expert_time_estimate omitted (no fitting enum value / tracker-sourced).
{provenance}

[agent]
timeout_sec = {agent_to}

[verifier]
timeout_sec = {verifier_to}

[verifier.env]
{env} = "${{{env}}}"

[environment]
os = "linux"
cpus = 2
memory_mb = 4096
allow_internet = true
"""


def kebab(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def name_slug(text, max_words=5):
    toks = [t for t in kebab(text).split("-") if t and t not in _STOP]
    seen = []
    for t in toks:
        if t not in seen:
            seen.append(t)
    return "-".join(seen[:max_words])


def toml_lit(s):
    return "'''" + s.replace("'''", "'' '").strip() + "'''"


def convert(src, out, prefix):
    v = json.load(open(os.path.join(src, "tests", "verifier.json")))
    cfg = v.get("config", {}) or {}
    judge = pick_judge(cfg.get("models"))
    st = tomllib.load(open(os.path.join(src, "task.toml"), "rb"))
    om = st.get("metadata", {}) or {}
    category = str(om.get("category", "")); tags = list(om.get("tags", []) or [])
    task_id = str(om.get("task_id", "") or os.path.basename(src))
    # distinct, descriptive slug: task_id's last "__" segment (DermOTS) else task_type
    base = task_id.split("__")[-1] if "__" in task_id else (om.get("task_type") or task_id)
    slug = name_slug(base) or kebab(task_id)
    name = f"{prefix}/{slug}"
    agent_to = (st.get("agent", {}) or {}).get("timeout_sec", 14400.0)
    verifier_to = (st.get("verifier", {}) or {}).get("timeout_sec", 3600.0)

    # DermOTS-style provenance (case_id/snapshot_key/tier) — kept as a traceability
    # comment when present; absent (EKW) sources just omit the line.
    prov_bits = [f"{k}={om[k]}" for k in ("case_id", "snapshot_key", "tier") if om.get(k)]
    provenance = (f"# source provenance: task_id={task_id} " + " ".join(prov_bits)) if prov_bits else ""

    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)

    open(os.path.join(out, "task.toml"), "w").write(TASK_TOML.format(
        name=name, category=category, tags=json.dumps(tags), env=JUDGE_ENV,
        agent_to=agent_to, verifier_to=verifier_to, provenance=provenance))

    # instruction: point workspace paths at /app
    instr = open(os.path.join(src, "instruction.md")).read()
    instr = (instr.replace("/workspace/output/", "/app/").replace("/workspace/output", "/app")
                  .replace("/workspace/data", "/app"))
    open(os.path.join(out, "instruction.md"), "w").write(instr)

    # environment: colab-cli Dockerfile + source docs (recursively) into initial_workspace/
    env_dir = os.path.join(out, "environment")
    os.makedirs(env_dir)
    open(os.path.join(env_dir, "Dockerfile"), "w").write(DOCKERFILE)
    src_data = os.path.join(src, "environment", "data")
    iw = os.path.join(env_dir, "initial_workspace")
    if os.path.isdir(src_data):
        shutil.copytree(src_data, iw, ignore=shutil.ignore_patterns(".DS_Store"))
    else:
        os.makedirs(iw)

    # deliverables = files the verifier reads back as output/<name>
    deliverables = []
    for x in v["verifiers"]:
        p = ((x.get("source") or {}).get("file") or {}).get("arguments", {}).get("path", "")
        b = os.path.basename(p)
        if b and b not in deliverables:
            deliverables.append(b)

    gold = os.path.join(src, "solution", "golden_outputs")
    sol_files = os.path.join(out, "solution", "files"); os.makedirs(sol_files)
    for nm in deliverables:
        f = os.path.join(gold, nm)
        if os.path.isfile(f):
            shutil.copy2(f, os.path.join(sol_files, nm))
    open(os.path.join(out, "solution", "solve.sh"), "w").write(SOLVE_SH)
    os.chmod(os.path.join(out, "solution", "solve.sh"), 0o755)
    # expert derivation write-up (EKW) as a review artifact, if present (not in files/)
    for cand in ("Reasoning.docx", "reasoning.docx"):
        rf = os.path.join(gold, cand)
        if os.path.isfile(rf):
            shutil.copy2(rf, os.path.join(out, "solution", "reasoning.docx")); break

    # tests/
    tests = os.path.join(out, "tests"); os.makedirs(os.path.join(tests, "deliverables"))
    open(os.path.join(tests, "test.sh"), "w").write(TEST_SH); os.chmod(os.path.join(tests, "test.sh"), 0o755)
    open(os.path.join(tests, "task_prompt.txt"), "w").write(instr)
    open(os.path.join(tests, "reward.toml"), "w").write(
        '[[reward]]\nname = "reward"\naggregation = "weighted_mean"\n')

    files_list = ", ".join(f'"/app/{d}"' for d in deliverables)
    lines = ["[judge]", f'judge = "{judge}"', f"files = [{files_list}]", ""]
    used = set()

    def crit_name(raw, idx):
        # reward-kit requires ^[a-zA-Z0-9_-]{1,64}$ — cap at 64, keep unique.
        n = kebab(raw)[:64].rstrip("-")
        if not n or n in used:
            n = (f"{n[:58].rstrip('-')}-{idx}" if n else f"criterion-{idx}")
        used.add(n)
        return n

    for i, x in enumerate(v["verifiers"], 1):
        m = x.get("metadata") or {}
        rubric = ((x.get("assertion") or {}).get("rubric") or {}).get("prompt", "")
        cname = crit_name(m.get("tag") or x.get("name") or "", i)
        lines += ["[[criterion]]", f'name = "{cname}"',
                  "description = " + toml_lit(rubric), 'type = "binary"',
                  f'weight = {float(m.get("weight") or 0.0)}', ""]
    lines += ["[scoring]", 'aggregation = "weighted_mean"', ""]
    open(os.path.join(tests, "deliverables", "judge.toml"), "w").write("\n".join(lines))

    wsum = round(sum(float((x.get("metadata") or {}).get("weight") or 0) for x in v["verifiers"]), 4)
    print(f"{os.path.basename(out)}: name={name}  judge={judge}  criteria={len(v['verifiers'])}  "
          f"wsum={wsum}  deliverables={deliverables}")


if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2], sys.argv[3])
