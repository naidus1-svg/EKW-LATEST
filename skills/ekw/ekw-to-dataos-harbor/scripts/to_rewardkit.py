
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

Usage: python3 to_rewardkit.py <src_task_dir> <out_task_dir> <name_prefix> [max_criteria_per_judge]
  max_criteria_per_judge (optional, default 12): once a task's verifier.json has more
  criteria than this, the judge is split across tests/deliverables_NN/judge.toml files
  (NN criteria each, same deliverable file(s), same judge model) instead of one
  tests/deliverables/judge.toml. reward.toml is untouched, but each chunk carries an
  explicit [judge].weight = that chunk's own criteria weight-sum -- rewardkit treats
  each deliverables_NN/judge.toml as its own named reward DIMENSION (not a flat pool
  of criteria; confirmed against rewardkit/runner.py), and reward.toml's weighted_mean
  combines those dimensions by [judge].weight (default 1.0 if unset, which would make
  every chunk count equally regardless of size). Added 2026-08-11 after Anthropic 400s
  ("compiled grammar is too large... reduce the number of strict tools") on large
  single-call schemas (confirmed on 17 of a 26-task DataOS batch); tune the threshold
  per findings from re-testing on DataOS.
"""

import json, os, re, shlex, shutil, sys, tomllib

_STOP = {"and", "of", "the", "a", "for", "to", "with", "an", "or"}
JUDGE_ENV = (
    "ANTHROPIC_API_KEY"  # locked policy: these rewardkit builds judge with Claude only
)

# Source verifier.json config.models can name any provider (EKW's spec judge is
# openai/gpt-5.4). We deliberately do NOT carry that model over: [verifier.env] only
# ever provisions ANTHROPIC_API_KEY on these builds, so a non-Anthropic judge model
# would fail at grading time with "Missing credentials" -- which surfaced as an opaque
# RewardFileNotFoundError, not a clear auth error, because it can kill the run before
# test.sh's fallback gets to write reward.json. Force every judge onto Claude instead.
#
# NOT claude-opus-4-8: confirmed broken against harbor-rewardkit 0.1.7's judge path
# on a real DataOS run (2026-08-21, accelerator-cohort-effort-tally-credit rubric_check)
# -- rewardkit always passes reasoning_effort="medium" (rewardkit/judges.py, no way to
# suppress it), which DataOS's pinned litellm maps to the OLDER Anthropic extended-
# thinking shape (thinking.type="enabled"). Opus 4.8 rejects that outright: "'thinking.
# type.enabled' is not supported for this model. Use 'thinking.type.adaptive' and
# 'output_config.effort'..." -- a 400 that fails the whole Reward (RuntimeError, not a
# graceful per-criterion 0), so the task's ENTIRE reward comes out 0.0. No batch-2 task
# had exercised the LLM-judge path in production before this (all 50 converted to the
# pure-programmatic path), so this went undetected until the first rubric_check-based
# conversion actually ran. claude-sonnet-4-6 is a proven-working judge model elsewhere
# in this project (DermOTS) and isn't on the newest thinking-API generation.
_DEFAULT_JUDGE = "anthropic/claude-sonnet-4-6"


def pick_judge(raw_models):
    """Return the Claude judge to use, overriding any non-Anthropic model named in the
    source verifier.json (see policy note above). An already-Anthropic model is kept
    as-is (e.g. DermOTS's anthropic/claude-sonnet-4-6)."""
    candidate = (raw_models or [_DEFAULT_JUDGE])[0]
    return candidate if candidate.startswith("anthropic/") else _DEFAULT_JUDGE


# --- judge-attachment guards --------------------------------------------------
# harbor-rewardkit is pip-installed at grade time (TEST_SH below), not vendored
# here, so we can't patch its judge code directly. But its file-reading rules
# (rewardkit/judges.py: _MAX_FILE_SIZE, _DOCUMENT_EXTENSIONS) are fixed and
# silent -- an attachment that trips either one doesn't error, it just gets
# dropped from the judge prompt with a placeholder, so every criterion checking
# it scores "no" with no diagnosable failure. Confirmed on a real oracle QC pass:
# SVC-PC-15-3/4/5-0 (docx > 1MB, mostly embedded fonts) and
# cirrus-y1-task-svc-pc-6-4-0-l2-04 (.xlsm not in the allowlist -> UnicodeDecodeError
# -> the whole judge call's asyncio.TaskGroup aborted, reward=0.0 with zero
# per-deliverable detail) all zeroed out entirely from this, not from any real
# content defect. Guard against both at packaging time instead of shipping a
# task the judge can never grade correctly.
_JUDGE_MAX_FILE_SIZE = 1024 * 1024  # mirrors rewardkit/judges.py _MAX_FILE_SIZE
# Per-chunk judge timeout written into every judge.toml [judge] table. rewardkit's JudgeConfig defaults it to 300 s and
# zeroes every criterion of a chunk whose judge call outlasts it ("timed out after 300s"); chunks with long compound
# criteria over large files do. rewardkit runs at most 8 judge folders at once (max_concurrent_llm), so a task with N
# chunks pays at most ceil(N/8) ceilings, inside task.toml's verifier timeout_sec (default 3600).
JUDGE_TIMEOUT_SEC = 900
_JUDGE_DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".xls",
    ".msg",
    ".epub",
    ".html",
    ".htm",
}


def _convert_xlsm_to_xlsx(path):
    """.xlsm isn't in rewardkit's _DOCUMENT_EXTENSIONS allowlist, so the judge falls
    back to a raw-text read, hits UnicodeDecodeError on the binary zip, and the
    whole judge call aborts (confirmed: cirrus-y1-task-svc-pc-6-4-0-l2-04, reward=0.0
    flat, no per-deliverable breakdown). Round-tripping through openpyxl with
    keep_vba=False drops the macro project and writes a plain .xlsx -- the judge
    only ever reads cell/formula text via markitdown, never executes macros, so
    nothing the judge can see is lost. Returns the new (.xlsx) path."""
    import openpyxl

    wb = openpyxl.load_workbook(path, keep_vba=False)
    new_path = (
        path[: -len("xlsm")] + "xlsx"
    )  # ".xlsm" -> ".xlsx" (NOT path[:-1] -- that gives ".xls")
    wb.save(new_path)
    os.remove(path)
    return new_path


def _strip_embedded_fonts(path):
    """Best-effort shrink for a .docx that's over the judge's 1MB attachment cutoff
    almost entirely because of embedded fonts (confirmed: SVC-PC-15-4-0/15-5-0, both
    ~3.2MB docx files with ~8.5KB of actual text, bloated by word/fonts/*.odttf --
    the judge skipped them wholesale and every criterion scored "no"). Deleting the
    font parts alone corrupts the package (word/fontTable.xml.rels still points at
    them, and python-docx's PackageReader walks every relationship eagerly, raising
    KeyError on the missing target) -- confirmed by testing the naive delete-only
    version against a real bloated file from this QC pass. This also drops the
    dangling <w:embedRegular/-Bold/-Italic/-BoldItalic> refs from fontTable.xml and
    the matching Relationship entries from its .rels part, so the result is a valid,
    smaller package with visible text/formatting untouched (readers without the
    embedded font just substitute one, same as opening on a machine that never had
    it installed). Returns True if anything was stripped (caller still re-checks
    size after -- not guaranteed to clear the 1MB threshold, e.g. a doc genuinely
    full of large images)."""
    import re
    import zipfile

    with zipfile.ZipFile(path) as zin:
        names = zin.namelist()
        font_parts = {n for n in names if re.match(r"word/fonts/.+", n)}
        if not font_parts:
            return False
        blobs = {n: zin.read(n) for n in names}

    rels_path = "word/_rels/fontTable.xml.rels"
    if rels_path in blobs:
        rels = blobs[rels_path].decode("utf-8")
        rels = re.sub(r'<Relationship[^>]*Target="fonts/[^"]+"[^>]*/>', "", rels)
        blobs[rels_path] = rels.encode("utf-8")

    if "word/fontTable.xml" in blobs:
        ft = blobs["word/fontTable.xml"].decode("utf-8")
        ft = re.sub(r"<w:embed(?:Regular|Bold|Italic|BoldItalic)\b[^/]*/>", "", ft)
        blobs["word/fontTable.xml"] = ft.encode("utf-8")

    if "word/settings.xml" in blobs:
        st = blobs["word/settings.xml"].decode("utf-8")
        st = re.sub(r"<w:embedTrueTypeFonts\b[^/]*/>", "", st)
        blobs["word/settings.xml"] = st.encode("utf-8")

    for part in font_parts:
        del blobs[part]

    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for n, data in blobs.items():
            zout.writestr(n, data)
    os.replace(tmp, path)
    return True


TEST_SH = """\
#!/bin/bash
export LITELLM_DROP_PARAMS=true

VERIFIER_DIR="${VERIFIER_DIR:-/logs/verifier}"
mkdir -p "$VERIFIER_DIR"

# Task 653 ("Project Cinder") + MKT-126/SCO-128 (confirmed via real DataOS
# oracle evals, 2026-08-28): an agent follows an unrewritten or simply ignored
# instruction and writes deliverables into a subfolder (/app/output/, /app/out/,
# /app/executive_recommendation/, etc.) instead of flat /app/ -- judge.toml only
# ever reads flat /app/<file>, so the file exists but is invisible to the judge,
# scoring every criterion "file not found" (confirmed real on MKT-126: both real
# agents -- claude-opus-5 and codex -- wrote to /app/output/<file>, reward.json
# flat 0.0 across both deliverables, while the oracle run -- which uses
# solve.sh's own flat `cp` -- scored 1.0 on the identical files).
# _rewrite_instruction_paths (below, at instruction-rewrite time) already tells
# the agent the correct location, but doesn't help when the agent still
# deviates from it anyway, as confirmed above.
#
# Promote ONLY the specific expected deliverable filenames (not a blanket
# subfolder copy, which would also sweep up scratch/work directories full of
# unrelated intermediate files -- confirmed real, e.g. MKT-126's own real
# /app/work/{build_docx.py,build_xlsx.py,*.png,*.txt} scratch dir) from
# wherever they actually landed under /app/ up to the flat root the judge
# reads, without clobbering a file already correctly placed there.
for name in __DELIVERABLE_NAMES__; do
  if [ ! -e "/app/$name" ]; then
    found="$(find /app -mindepth 2 -name "$name" -type f 2>/dev/null | head -n1)"
    if [ -n "$found" ]; then
      cp "$found" "/app/$name"
      echo "WARN: $name found at $found (not flat /app/$name) -- copied up for judge resolution" >> "$VERIFIER_DIR/runtime.log"
    fi
  fi
done

# rewardkit (harbor-rewardkit 0.1.7, latest on PyPI) can't read .xlsm --
# _DOCUMENT_EXTENSIONS omits it, so an unrecognized suffix falls through to a raw
# text read() that UnicodeDecodeErrors on the binary zip and returns an empty
# judge prompt; Anthropic then rejects the system-only request outright,
# crashing rewardkit's asyncio.TaskGroup and zeroing the WHOLE task's reward
# (confirmed: cirrus-y1-task-svc-pc-6-4-0-l2-04 oracle run, exit 1, "Anthropic
# requires at least one non-system message"). The packaged solution/files/
# deliverable is pre-converted to .xlsx at build time (see to_rewardkit.py's
# _convert_xlsm_to_xlsx), but a real agent follows instruction.md -- which still
# names the .xlsm path -- and writes .xlsm at /app/, not .xlsx. Convert whatever
# lands at /app/*.xlsm here too, so judge.toml's files=[...] (which always names
# the .xlsx form) resolves for a real agent run the same way it does for oracle.
python3 - <<'PYEOF'
import glob, os
import openpyxl
for src in glob.glob("/app/*.xlsm"):
    dst = src[:-len("xlsm")] + "xlsx"
    try:
        wb = openpyxl.load_workbook(src, keep_vba=False)
        wb.save(dst)
        os.remove(src)
    except Exception as e:
        print(f"WARN: could not convert {src} to xlsx for judge: {e}")
PYEOF

# rewardkit's judge reads the FULL extracted text of every attached file into ONE
# LLM prompt -- every deliverables_NN/judge.toml chunk shares the SAME files=[...]
# list (chunking splits CRITERIA, not files), so two moderate xlsx deliverables
# combine in the same prompt even though neither alone looks oversized. No size
# cap of its own, and a genuinely large workbook (produced by the agent at eval
# time, so it can't be bounded at packaging time the way _JUDGE_MAX_FILE_SIZE
# below bounds the golden .docx copy) can push the whole prompt over Anthropic's
# hard 1,000,000-token limit. Confirmed on a real DataOS run (FIN-181,
# 2026-08-28): a single large compliance-exception-register .xlsx alone pushed
# the judge prompt to 1,009,492 tokens -- litellm.ContextWindowExceededError,
# HTTP 400, and the task's ENTIRE reward crashes to 0.0 (not a graceful
# per-criterion score; confirmed via reward.json containing only {"reward": 0.0},
# no per-deliverable breakdown).
#
# Trim in place before rewardkit ever reads any of these files, sharing ONE
# character budget across every /app/*.xlsx and every sheet in each (not
# reset per file/per sheet -- an earlier version did that, which meant only
# the FIRST oversized sheet ever got truncated and every later sheet or file
# passed through untouched at full size, still able to blow the same shared
# judge prompt). Per sheet, keep a head+tail slice (most likely to preserve
# both "earliest" and "most recent" records in a dated register) and drop the
# middle, with a marker row stating how many rows were cut, rather than
# silently pretending the file is smaller than it is. This trades some
# criteria potentially being unable to verify an omitted row for the task
# getting a real, gradeable score instead of a flat infra-crash zero -- the
# better failure mode of the two.
python3 - <<'PYEOF'
import glob
import os
import re
import openpyxl

# Only files rewardkit attaches to a judge spend this budget: the deliverables (every converter-written judge.toml
# lists exactly them) plus any source workbook a lane has since added to a judge's files so that judge can check a
# fact it cites (QC hold rule 6). Starting source workbooks that no judge lists never reach a prompt and are neither
# trimmed nor counted. Deliverables go first, so an attached source is trimmed to fit what they leave and can never
# starve one. SVC-PC-23-0-0 (2026-10-01) shipped about 60 MB of source workbooks (Sales_Orders.xlsx alone is 4.0M
# characters); the loop visited every /app/*.xlsx in sorted order, the sources spent the budget first, and the
# golden's Technology_Risk_and_Remediation_Register.xlsx was cleared as 'all data omitted': oracle 0.6048, and both
# DataOS reviews called the task invalid.
DELIVERABLES = __DELIVERABLE_NAMES_PY__

BS = chr(92)  # the template is a plain string, so the regex below is built without a literal backslash
FILES_LIST = re.compile("^ *files *= *" + BS + "[(.*?)" + BS + "]", re.S | re.M)

def attached_sources():
    names = set()
    for toml in glob.glob("/tests/**/judge.toml", recursive=True):
        try:
            text = open(toml, encoding="utf-8").read()
        except OSError:
            continue
        for m in FILES_LIST.finditer(text):
            names.update(os.path.basename(n) for n in re.findall('"([^"]+)"', m.group(1)))
    return sorted(n for n in names if n.endswith(".xlsx") and n not in DELIVERABLES)

ORDER = sorted(DELIVERABLES) + attached_sources()

# ~4 chars/token is a conservative English-text proxy; 2.8M chars total targets
# roughly 700k tokens across every xlsx deliverable COMBINED, leaving headroom
# under the 1M-token ceiling for criteria text, other attached files, and
# system-prompt overhead. Tune down further here if a task's own outsized
# files still overflow. NOT a raw-file-size pre-filter: xlsx compresses
# repetitive text (boilerplate categories, repeated status strings -- exactly
# what a real exception register looks like) extremely well. Verified on a
# synthetic 30k-row register: 1MB on disk, 38M extracted characters (~9.5M
# estimated tokens) -- a file-size shortcut would have let that exact case
# through untouched. Always open and actually count extracted characters.
CHAR_BUDGET = 2_800_000
TRUNCATION_MARKER = "... TRUNCATED FOR JUDGE REVIEW: {omitted} row(s) omitted ({reason}) -- see the original submitted file for the complete data ..."

def row_chars(row):
    return sum(len(str(c.value)) for c in row if c.value is not None) + len(row)

def clear_sheet(ws, reason):
    '''Budget was already exhausted by an earlier file/sheet sharing this same
    judge prompt -- clear this sheet's rows entirely (keeping only the header,
    if any) rather than silently leaving an untouched, still-oversized sheet
    for the judge to choke on.'''
    if not ws.max_row or ws.max_row < 1:
        return False
    header = [c.value for c in next(ws.iter_rows(max_row=1), [])]
    ws.delete_rows(1, ws.max_row)
    marker_row = 1
    if header:
        for j, v in enumerate(header, start=1):
            ws.cell(row=1, column=j, value=v)
        marker_row = 2
    ws.cell(row=marker_row, column=1,
            value=TRUNCATION_MARKER.format(omitted="all data", reason=reason))
    return True

budget = CHAR_BUDGET  # SHARED across every file below -- see comment above.
present = {os.path.basename(p): p for p in glob.glob("/app/*.xlsx")}
for path in [present[n] for n in ORDER if n in present]:  # deliverables first, then attached sources, each sorted: deterministic across runs
    try:
        # Formula text, not cached values (data_only=False, openpyxl's default):
        # a cell whose formula was never calculated/cached -- plausible for a
        # file an agent wrote programmatically without opening it in a real
        # spreadsheet app -- comes back as None under data_only=True, silently
        # BLANKING real content rather than merely losing the formula string.
        # Formula text is always present, so this never silently drops data.
        wb = openpyxl.load_workbook(path)
        changed = False
        for ws in wb.worksheets:
            if budget <= 0:
                changed = clear_sheet(ws, "judge's combined attachment budget "
                                          "already spent by another file/sheet "
                                          "in this task") or changed
                continue
            rows = list(ws.iter_rows())
            if not rows:
                continue
            total = sum(row_chars(r) for r in rows)
            if total <= budget:
                budget -= total
                continue
            half = budget // 2
            head_end, running = len(rows), 0
            for i, r in enumerate(rows):
                running += row_chars(r)
                if running > half:
                    head_end = i
                    break
            tail_start, running = head_end, 0
            for i in range(len(rows) - 1, head_end - 1, -1):
                running += row_chars(rows[i])
                if running > half:
                    tail_start = i + 1
                    break
            if tail_start > head_end:
                omitted = tail_start - head_end
                ws.delete_rows(head_end + 1, omitted)
                ws.cell(row=head_end + 1, column=1,
                        value=TRUNCATION_MARKER.format(
                            omitted=omitted,
                            reason="file too large for the judge's context window"))
                changed = True
            budget = 0
        if changed:
            wb.save(path)
            print(f"WARN: {path} exceeded the judge's shared attachment size "
                  f"budget -- truncated (head+tail kept, middle rows dropped) to "
                  f"fit the LLM context window; criteria checking an omitted "
                  f"row may not verify.")
    except Exception as e:
        # A failed truncation must not leave a still-oversized file for the
        # judge to choke on -- swallowing the exception here previously left
        # the ORIGINAL (potentially huge) file completely untouched, defeating
        # the whole point of this guard. Replace it with a minimal placeholder
        # instead: losing this one file's content for the judge is strictly
        # better than crashing the WHOLE task's reward via a context overflow.
        print(f"WARN: could not check/truncate {path} for judge size ({e}); "
              f"replacing with a placeholder so it can't overflow the judge's "
              f"context window.")
        try:
            ph = openpyxl.Workbook()
            ph.active.cell(row=1, column=1,
                           value=f"File omitted: preprocessing failed ({e}); see "
                                 f"the original submitted file for the complete data.")
            ph.save(path)
        except Exception as e2:
            print(f"WARN: could not even write a placeholder for {path}: {e2}")
PYEOF

# rewardkit writes NOTHING on failure (bad/missing judge credentials, judge API
# error, etc. -- confirmed by smoke test). Without this fallback, any hiccup at
# verify time surfaces as an opaque harbor.verifier.verifier.RewardFileNotFoundError
# instead of a diagnosable reward=0.0 + error message.
#
# IMPORTANT: harbor.verifier.verifier.Verifier reads reward.json verbatim as the
# VerifierResult.rewards dict, and every value in that dict MUST be numeric
# (float | int) -- a pydantic ValidationError, not a graceful failure, results
# otherwise. So reward.json here carries ONLY the numeric reward; the message
# goes to runtime.log instead (already the file humans check for diagnostics).
write_infra_failure() {
  local message="$1"
  echo "$message" >> "$VERIFIER_DIR/runtime.log"
  echo "0.0" > "$VERIFIER_DIR/reward.txt"
  echo '{"reward": 0.0}' > "$VERIFIER_DIR/reward.json"
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
SOLVE_SH = (
    "#!/bin/bash\nset -euo pipefail\nmkdir -p /app\ncp -a /solution/files/. /app/\n"
)
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
# SVC full-corpus tasks ship a small DVC pointer (environment/data.dvc, tracking
# the WHOLE data/ directory as one output) + environment/.dvc/config instead of
# the real corpus, and pull the real files from gs://colab-bench at BUILD time --
# this is the platform's own documented mechanism for the >60MB task-size limit
# (https://data-os.turing.com/docs/dvc-large-files), not a bespoke fetch. ARG
# name is exact and load-bearing: a reward-kit task that declares
# COLAB_BENCH_BUCKET_TOKEN_JSON is the ONLY signal that routes its build to
# Modal (which gets the GCS credential injected) instead of Daytona (which
# doesn't, and has no general internet egress -- confirmed by a live oracle
# eval: an earlier gdown/Google-Drive-based fetch failed with exit 127 on
# Daytona). Verified end-to-end 2026-08-27: real dvc push (1179 files) then a
# clean dvc pull round-tripped all 1180 files back, and a real Data-OS oracle
# eval confirmed the build routed to Modal and pulled the real corpus.
DVC_DOCKERFILE_BLOCK = """\
ARG COLAB_BENCH_BUCKET_TOKEN_JSON=""
RUN pip install --no-cache-dir "dvc[gs]==3.67.1"
RUN if [ -n "$COLAB_BENCH_BUCKET_TOKEN_JSON" ]; then \\
        printf '%s' "$COLAB_BENCH_BUCKET_TOKEN_JSON" > /tmp/gcp_creds.json && \\
        export GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp_creds.json; \\
    fi && \\
    dvc pull && \\
    rm -f /tmp/gcp_creds.json && \\
    rm -rf .dvc data.dvc

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
    """Word-dedupe descriptive text (e.g. task_type strings) into a short slug.
    Numeric tokens are exempt from dedup: an id like "SVC-PC-5-5-0" has two
    "5"s as distinct, meaningful positional segments (not redundant word
    repetition the way "the-the-report" is), so deduping them silently
    corrupted the id -- confirmed on SVC-PC-5-5-0 collapsing to svc-pc-5-0."""
    toks = [t for t in kebab(text).split("-") if t and t not in _STOP]
    seen = []
    for t in toks:
        if t.isdigit() or t not in seen:
            seen.append(t)
    return "-".join(seen[:max_words])


def toml_lit(s):
    return "'''" + s.replace("'''", "'' '").strip() + "'''"


# ── SVC rubric.json -> normalized criteria ─────────────────────────────────
# SVC ships tests/rubric.json instead of tests/verifier.json: no flat weights
# summing to 1.0, no per-criterion source-file path. Two shapes have shipped
# (see pipeline/gdpval_qc/tools/check_rubric.py, the SVC structural-QC
# checker, for the authoritative schema notes this mirrors): an older one
# with a top-level categories[] (weight sums to 100) and the current one
# (100% of the 2026-07-31 delivery) with no categories[] at all -- `category`
# is just a free-text per-criterion label. Real scoring keys off each
# criterion's own `points` against `total_points` (~100) in BOTH shapes
# (per check_rubric.py's own check_points_penalty_coherent) -- categories[]
# weight is a display/grouping concept, not part of the scoring formula --
# so this converter normalizes weight from points/total-points directly and
# does not fold in categories[] weight at all, for either shape.
def _svc_is_must_pass(c):
    v = (c or {}).get("must_pass")
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("yes", "true", "1")


def _svc_points(c):
    try:
        return float((c or {}).get("points", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _svc_expected_text(c):
    # Explicit None-checks, not `... or ...` -- a legitimate expected value of
    # literal 0 (e.g. "P(insolvency) reported about 0%.", expected_value=0)
    # is falsy in Python, so `0 or c.get("expected") or ""` would silently
    # discard it and fall through to "".
    c = c or {}
    v = c.get("expected_value")
    if v is None:
        v = c.get("expected")
    return "" if v is None else str(v).strip()


def _svc_criteria(rubric):
    """rubric.json's criteria[] -> the same normalized shape _ekw_criteria
    produces: (name, description, weight), weight signed (penalties negative)
    and normalized to sum(|weight|) == 1.0 across the rubric.

    description is the source rubric's own Description and Expected-value
    columns, concatenated as-is -- this function does not compose,
    label, or explain anything that isn't already in the source rubric.
    reward-kit's [[criterion]] schema has one text field, so combining two
    source columns into it is unavoidable, but that's a format-alignment
    step, not a content edit: no invented connective wording ("Expected:
    ...") and no conversion-tool commentary (a must-pass explanation, a
    gate-approximation note, etc.) gets added to what the task author
    actually wrote. If the source Expected-value cell is empty, nothing is
    appended -- an empty cell stays empty in the converted output, since
    inventing filler text there would misrepresent the rubric rather than
    just reformat it. (A rubric criterion with a genuinely empty
    Expected-value cell is a source-data problem for whoever owns that
    rubric to fix, not something this conversion step should paper over.)

    must_pass gates get no native reward-kit equivalent (weighted_mean has no
    hard-gate/zero-on-fail concept) -- approximated as a heavily-weighted
    criterion instead. That approximation is surfaced in the calling code's
    printed conversion summary (has_gate below), not injected into the
    criterion's own description text, so the judge model and any reviewer
    diffing the converted rubric against the source both see the same
    wording the task author wrote.
    """
    crit = rubric.get("criteria") or []
    total = sum(abs(_svc_points(c)) for c in crit) or 1.0
    out = []
    for c in crit:
        cid = str((c or {}).get("id") or "")
        desc = str((c or {}).get("description") or "").strip()
        expected = _svc_expected_text(c)
        if expected:
            desc = f"{desc} {expected}".strip()
        out.append({"name": cid, "description": desc, "weight": _svc_points(c) / total})
    return out, any(_svc_is_must_pass(c) for c in crit)


def _deterministic_description(x):
    """Build a judge-readable description for a deterministic (non-rubric) verifier
    entry. Harbor CLI 1.3 tasks (confirmed on all 50 sampled batch-2 tasks) carry
    verifiers with assertion.type="deterministic" and no assertion.rubric.prompt at
    all -- that field only exists for EKW's LLM-judge-style verifiers. Leaving the
    description empty ships a judge.toml criterion with no instructions, so the
    judge has nothing to check and every criterion silently scores "no" regardless
    of the deliverable's actual content. Compose a real description instead from
    what these verifiers DO carry: the human-readable why/how justifications plus
    the concrete expected value/comparison, so an LLM judge reading the attached
    file(s) can verify the same condition the original deterministic comparator
    checked (regex/JSONPath/tolerance match).

    why/how text is free-form SME authoring and can itself embed a literal
    workspace path (confirmed 2026-08-21: "confirms the solver created a file at
    output/orc-capacity-briefing.pptx") -- run it through the same
    _rewrite_instruction_paths rewrite as instruction.md, or the judge is told to
    look for the deliverable at a path the flat-/app/ reward-kit layout never
    uses, and grades a correctly-placed file as missing."""
    m = x.get("metadata") or {}
    a = x.get("assertion") or {}
    parts = []
    why = m.get("why_justification")
    how = m.get("how_justification")
    if why:
        parts.append(_rewrite_instruction_paths(str(why).strip()))
    if how:
        parts.append(f"Check: {_rewrite_instruction_paths(str(how).strip())}")
    det = a.get("deterministic") or {}
    comparison = det.get("comparison")
    expected = a.get("expected")
    path = det.get("path")
    if comparison and expected is not None:
        where = f" at {path}" if path else ""
        parts.append(f"Verify (via {comparison}{where}): {expected}")
    return " ".join(parts).strip()


# ── deterministic verifier.json -> native rewardkit programmatic checks ────
# rewardkit (harbor-rewardkit 0.1.7) is NOT judge-only: tests/<dir>/*.py files
# get auto-discovered and their @criterion-registered checks run as a plain
# programmatic Reward, no LLM involved (rewardkit/runner.py:discover()). Harbor
# CLI 1.3 tasks (confirmed: all 50 sampled batch-2 tasks) are 100% deterministic
# assertions (regex/JSONPath/tolerance) with their own comparator already
# vendored at tests/rl_world_verifiers/ -- routing those through a synthesized
# LLM judge (the EKW-only path this converter otherwise takes) is both lossy
# (an LLM approximating a regex match) and unnecessary.
#
# IMPORTANT (confirmed 2026-08-21 on a real DataOS upload): DataOS's own
# `rewardkit.discover()` step imports every tests/<dir>/*.py file OUTSIDE this
# task's own Docker build -- in DataOS's own Python environment, which has
# none of the packages this task's Dockerfile installs. A first version of
# this generator imported rl_world_verifiers (-> pydantic/jsonpath_ng/tenacity)
# at module top level and broke discovery immediately: "ERROR - rewardkit.
# discover() failed: No module named 'jsonpath_ng'" / "Unable to parse tests
# under tests/". So CHECKS_PY below reimplements the small deterministic-
# comparator subset this batch actually uses (confirmed by surveying all 50
# tasks' verifier.json: source types csv/json/text/md/filesystem/docx/xlsx;
# comparisons equals/regex_match/approx_equals/contains/not_regex_match/
# not_contains; every JSONPath is either "$" or a plain dotted path, no
# wildcards/indices/filters anywhere in this batch) using ONLY the stdlib at
# module level. docx/xlsx need a real parsing library no stdlib substitute
# covers, so those two source types lazily import rl_world_verifiers' own
# (already-correct, still-vendored) extractors from INSIDE the check function
# body instead of at module top -- that import only ever executes at real
# grading time inside the properly-provisioned container, never during
# DataOS's separate discovery pass.
CHECKS_PY = '''\
"""Programmatic reward: reimplements this task's original verifier.json
deterministic checks natively in rewardkit (see rewardkit/runner.py:discover()).
Pure stdlib at module level -- see to_rewardkit.py's CHECKS_PY comment for why.
Generated by to_rewardkit.py -- do not edit by hand; regenerate instead."""
import json
import math
import re
import sys
from pathlib import Path

import rewardkit as rk
# NOTE: @rk.criterion(...) returns a _CriterionHandle, not the callable factory
# -- calling the decorated name directly ("_check(...)") deliberately raises
# ("Call criteria through the rewardkit module: rk._check(...) instead"),
# confirmed 2026-08-21 on a real DataOS upload. The real factory only becomes
# callable through rewardkit's own module-level __getattr__ (rk._check(...)),
# which looks it up in the same _factory_registry the decorator populated --
# so every invocation below goes through rk.<name>(...), never the bare name.

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))  # so the lazy rl_world_verifiers imports below resolve
_SPEC = json.loads((_HERE / "verifier.json").read_text(encoding="utf-8"))
_VERIFIERS = _SPEC["verifiers"]
_BY_NAME = {v["name"]: v for v in _VERIFIERS}


def _effective_weights(verifiers):
    """Pure-stdlib port of rl_world_verifiers.models.effective_weights: explicit
    metadata.weight values are honored as-is; every unweighted verifier splits
    the remaining weight evenly, with the last one absorbing any rounding
    remainder so a perfect run always sums to exactly 1.0."""
    explicit_sum = sum((v.get("metadata") or {}).get("weight") or 0 for v in verifiers)
    unweighted = [v for v in verifiers if (v.get("metadata") or {}).get("weight") is None]
    weights = {
        v["name"]: round(v["metadata"]["weight"], 10)
        for v in verifiers if (v.get("metadata") or {}).get("weight") is not None
    }
    if unweighted:
        remaining = 1 - explicit_sum
        default = round(remaining / len(unweighted), 10)
        head_total = default * (len(unweighted) - 1)
        for index, v in enumerate(unweighted):
            last = index == len(unweighted) - 1
            weights[v["name"]] = round(remaining - head_total, 10) if last else default
    return weights


_WEIGHTS = _effective_weights(_VERIFIERS)

# Minimal JSONPath subset covering every pattern this batch's verifier.json
# files actually use (surveyed all 430 distinct paths across all 50 tasks:
# every one is one of "$", ".field", "[N]"/"[-N]", "[*]", "['key']"/["key"],
# or a single-equality filter "[?(@.field=='val')]" -- no other jsonpath_ng
# syntax appears anywhere in this batch). A task needing more than this would
# need the real jsonpath_ng, which can't be a module-level import here (see
# module docstring).
_JSONPATH_TOKEN_RE = re.compile(r"""
    \$
  | \.(?P<field>[A-Za-z0-9_]+)
  | \[(?P<index>-?\d+)\]
  | \[\*\]
  | \['(?P<sqkey>[^']*)'\]
  | \["(?P<dqkey>[^"]*)"\]
  | \[\?\(@\.(?P<ffield>[A-Za-z0-9_]+)\s*==\s*'(?P<fval>[^']*)'\)\]
""", re.VERBOSE)


def _get_jsonpath(data, path):
    """Evaluates the JSONPath subset above. Tracks the current match set as a
    list throughout (JSONPath's own context-node model), then collapses at the
    end exactly like rl_world_verifiers.compare.actual_from_matches: no matches
    -> None, one match -> that value, several -> the list of them (this is why
    a "[*]" or filter step can turn a scalar comparison into a list one)."""
    cur = [data]
    pos = 0
    for m in _JSONPATH_TOKEN_RE.finditer(path):
        if m.start() != pos:
            raise ValueError(f"unsupported jsonpath syntax at {pos}: {path!r}")
        pos = m.end()
        if m.group(0) == "$":
            continue
        if m.group("field") is not None:
            field = m.group("field")
            cur = [node[field] for node in cur if isinstance(node, dict) and field in node]
        elif m.group("index") is not None:
            idx = int(m.group("index"))
            cur = [node[idx] for node in cur if isinstance(node, list) and -len(node) <= idx < len(node)]
        elif m.group("sqkey") is not None or m.group("dqkey") is not None:
            key = m.group("sqkey") if m.group("sqkey") is not None else m.group("dqkey")
            cur = [node[key] for node in cur if isinstance(node, dict) and key in node]
        elif m.group("ffield") is not None:
            ffield, fval = m.group("ffield"), m.group("fval")
            cur = [
                item for node in cur if isinstance(node, list) for item in node
                if isinstance(item, dict) and item.get(ffield) == fval
            ]
        else:  # "[*]"
            cur = [item for node in cur if isinstance(node, list) for item in node]
    if pos != len(path):
        raise ValueError(f"unsupported jsonpath syntax at {pos}: {path!r}")
    if not cur:
        return None
    if len(cur) == 1:
        return cur[0]
    return cur


def _values_equal(a, b):
    # Bool-aware equality: Python's True == 1 would otherwise let a document
    # value of 1 satisfy an "equals: true" assertion.
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return bool(a == b)


def _contains(actual, expected):
    if isinstance(actual, str):
        return isinstance(expected, str) and expected in actual
    if isinstance(actual, list):
        return any(_values_equal(expected, item) for item in actual)
    return False


def _compare(actual, expected, comparison, tolerance):
    if comparison == "equals":
        return _values_equal(actual, expected)
    if comparison == "not_equals":
        return not _values_equal(actual, expected)
    if comparison == "approx_equals":
        abs_tol = (tolerance or {}).get("absolute")
        rel_tol = (tolerance or {}).get("relative")
        return math.isclose(
            actual, expected,
            abs_tol=1e-9 if abs_tol is None else abs_tol,
            rel_tol=1e-9 if rel_tol is None else rel_tol,
        )
    if comparison == "contains":
        return _contains(actual, expected)
    if comparison == "not_contains":
        return not _contains(actual, expected)
    if comparison == "regex_match":
        return bool(re.search(str(expected), actual))
    if comparison == "not_regex_match":
        return not bool(re.search(str(expected), actual))
    if comparison == "in_array":
        return any(_values_equal(actual, item) for item in expected)
    if comparison == "not_in_array":
        return not any(_values_equal(actual, item) for item in expected)
    if comparison == "greater_than":
        return actual > expected
    if comparison == "less_than":
        return actual < expected
    if comparison in ("greater_than_equal", "greater_or_equal"):
        return actual >= expected
    if comparison in ("less_than_equal", "less_or_equal"):
        return actual <= expected
    raise ValueError(f"unsupported comparison: {comparison}")


def _read_source(workspace, spec):
    """Reproduces the exact source.file command semantics from
    rl_world_verifiers/sources/*.py for every source type this batch uses.
    docx/xlsx defer to rl_world_verifiers' own (already-correct) extractors via
    a function-body-local import, so this stays a pure-stdlib import at
    DataOS's separate discovery time (see module docstring)."""
    kind = spec["type"]
    command = spec["command"]
    path = workspace / spec["arguments"]["path"]
    if command == "extract_text" and kind in ("csv", "text", "md"):
        return {"text": path.read_text(encoding="utf-8-sig")}
    if (kind, command) == ("json", "read_file"):
        return json.loads(path.read_text(encoding="utf-8"))
    if (kind, command) == ("filesystem", "check_path_exists"):
        return {"exists": path.exists(), "is_file": path.is_file(), "is_directory": path.is_dir()}
    if kind == "docx" and command == "extract_text":
        from rl_world_verifiers.sources.docx import extract_docx
        return {"text": extract_docx(path, 90000)}
    if kind == "xlsx":
        from rl_world_verifiers.sources import xlsx as _xlsx
        if command == "extract_text":
            return {"text": _xlsx.extract_xlsx(path, 90000)}
        if command == "extract_formulas":
            return {"text": _xlsx.extract_xlsx_formulas(path, 90000)}
        if command == "read_cell":
            reading = _xlsx.read_xlsx_cell(path, spec["arguments"]["sheet"], spec["arguments"]["cell"])
            return {"value": reading.value, "formula": reading.formula, "has_formula": reading.has_formula}
    raise ValueError(f"unsupported source: {kind}.{command}")


@rk.criterion(description="{justification}")
def _check(workspace: Path, verifier_name: str, justification: str) -> bool:
    definition = _BY_NAME[verifier_name]
    source = (definition.get("source") or {}).get("file") or {}
    specs = source if isinstance(source, list) else [source]
    assertion = definition.get("assertion") or {}
    det = assertion.get("deterministic") or {}
    path = det.get("path", "$")
    comparison = det.get("comparison", "equals")
    tolerance = det.get("tolerance")
    expected = assertion.get("expected")
    try:
        for spec in specs:
            data = _read_source(workspace, spec)
            actual = _get_jsonpath(data, path)
            if not _compare(actual, expected, comparison, tolerance):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        # rewardkit's TaskGroup aborts the WHOLE "deliverables" Reward on the
        # first uncaught exception from any one criterion -- confirmed on a
        # real DataOS oracle run (fin-f5-nwc-true-up-closing-statement,
        # law-l3-ca-rif-pretermination-memo): a single missing/malformed file
        # a minority of verifiers depend on zeroed the ENTIRE task's reward,
        # including every other, unrelated, perfectly gradable criterion in
        # the same run. rl_world_verifiers' own runner never has this
        # failure mode -- it scores each verifier independently (a missing
        # file just fails that one check). Match that: a file that can't be
        # read, parsed, or JSONPath'd into just fails this one criterion,
        # same as any other unmet assertion, instead of taking the whole
        # task's score to 0.0 regardless of what else passed. ImportError
        # included for the docx/xlsx lazy-import path (_read_source) -- the
        # Dockerfile installs those, so this shouldn't fire in practice, but
        # the same "don't crash the whole task" logic applies if it ever does.
        return False


for _v in _VERIFIERS:
    _m = _v.get("metadata") or {}
    _justification = _m.get("why_justification") or _v["name"]
    rk._check(_v["name"], _justification, weight=_WEIGHTS[_v["name"]], name=_v["name"])
'''


def _is_all_deterministic(verifiers):
    return bool(verifiers) and all(
        (x.get("assertion") or {}).get("type") == "deterministic" for x in verifiers
    )


def _write_programmatic_checks(src, tests_dir, verifier_path):
    """Vendors rl_world_verifiers + verifier.json into tests_dir/deliverables/
    and writes the generated checks.py that runs them natively (no judge)."""
    chunk_dir = os.path.join(tests_dir, "deliverables")
    os.makedirs(chunk_dir)
    shutil.copy2(verifier_path, os.path.join(chunk_dir, "verifier.json"))
    shutil.copytree(
        os.path.join(src, "tests", "rl_world_verifiers"),
        os.path.join(chunk_dir, "rl_world_verifiers"),
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    open(os.path.join(chunk_dir, "checks.py"), "w", encoding="utf-8").write(CHECKS_PY)


def _rewrite_instruction_paths(instr):
    """Point every source workspace-path convention at flat /app/, matching
    reward-kit's own Dockerfile (COPY initial_workspace/ /app/) and
    solve.sh/judge.toml, which both place deliverables FLAT at /app/, no
    subfolder. Three source conventions feed this: EKW harbor tasks use
    /workspace/{data,output}, SVC harbor tasks (convert_svc_task.py) use
    /app/{data,output}, and a newer EKW instruction template (confirmed
    2026-08-21, as-*-final-review-artifacts batch) drops the leading
    /workspace or /app entirely and just says "the `output/` subdirectory" /
    `output/<file>.xlsx`. Leaving any of these unrewritten silently keeps
    telling the agent to read/write a subfolder the verifier never looks at
    (confirmed via DataOS trajectory QC on svc-pc-7-l2-01: both agents wrote
    to /app/output/ exactly as instructed, and were scored zero because
    judge.toml only reads flat /app/<file>; reconfirmed 2026-08-21 on a real
    5-task batch — every deliverable in every task scored 0.0 "no files
    found" because the bare "output/" prefix wasn't covered yet)."""
    for prefix in (
        "/workspace/output/",
        "/workspace/output",
        "/workspace/data/",
        "/workspace/data",
        "/app/output/",
        "/app/output",
        "/app/data/",
        "/app/data",
    ):
        instr = instr.replace(prefix, "/app/")
    # Bare relative "output/" (no leading /workspace or /app) must run AFTER the
    # compound prefixes above so it doesn't fire on "workspace/output/"'s own
    # "output/" substring before the compound rule gets a chance to match it whole.
    instr = instr.replace("output/", "/app/")
    instr = instr.replace(
        "/app//", "/app/"
    )  # a trailing-slash source + our own "/app/" can double up
    # This sentence made sense against the source convention (don't dump deliverables
    # in the task root, put them in output/) but flatly contradicts our own /app/
    # rewrite above once "output/" has become "/app/" (the task root) — confirmed
    # verbatim across the 2026-08-21 as-*-final-review-artifacts batch's instruction
    # template. Drop it rather than leave the agent an explicit self-contradiction.
    instr = "\n".join(
        line
        for line in instr.split("\n")
        if "do not place deliverables at the task root" not in line.lower()
    )
    return instr

def convert(src, out, prefix, max_criteria_per_judge=12):
    verifier_path = os.path.join(src, "tests", "verifier.json")
    rubric_path = os.path.join(src, "tests", "rubric.json")
    is_svc = not os.path.exists(verifier_path) and os.path.exists(rubric_path)
    if is_svc:
        rubric_obj = json.load(open(rubric_path, encoding="utf-8"))
        criteria_norm, has_gate = _svc_criteria(rubric_obj)
        cfg = {}  # rubric.json carries no judge-model field; always defaults to Claude
    else:
        v = json.load(open(verifier_path, encoding="utf-8"))
        cfg = v.get("config", {}) or {}
        has_gate = False
        # Harbor CLI 1.3 tasks whose verifier.json is 100% deterministic assertions
        # (confirmed: all 50 sampled batch-2 tasks) ship their own comparator at
        # tests/rl_world_verifiers/ -- run that directly via rewardkit's native
        # programmatic-checks discovery instead of synthesizing an LLM judge for
        # conditions an LLM would only approximate (regex/JSONPath/tolerance match
        # a judge can't evaluate as reliably as the vendored comparator itself).
        use_programmatic = _is_all_deterministic(v["verifiers"]) and os.path.isdir(
            os.path.join(src, "tests", "rl_world_verifiers")
        )
        if use_programmatic:
            criteria_norm = []
        else:
            raw = []
            for x in v["verifiers"]:
                m = x.get("metadata") or {}
                rubric_prompt = ((x.get("assertion") or {}).get("rubric") or {}).get(
                    "prompt", ""
                )
                raw.append(
                    {
                        "name": m.get("tag") or x.get("name") or "",
                        "description": rubric_prompt or _deterministic_description(x),
                        "weight": float(m.get("weight") or 0.0),
                        "_weight_set": "weight" in m,
                    }
                )
            # Harbor CLI 1.3 tasks set no metadata.weight anywhere in the file --
            # their native engine (rl_world_verifiers) defaults to an equal split
            # across criteria in that case, not zero. This fallback only fires for
            # tasks that fell through to the LLM-judge path above (e.g. no vendored
            # rl_world_verifiers to run natively); it's a safety net, not the
            # primary path for deterministic verifiers anymore. Only fall back to
            # an equal split when NOTHING in this file set an explicit weight; a
            # file that sets weight on some criteria (EKW's convention) keeps that
            # original all-explicit-weight behavior untouched.
            if raw and not any(c["_weight_set"] for c in raw):
                even = round(1.0 / len(raw), 6)
                for c in raw:
                    c["weight"] = even
            criteria_norm = [
                {
                    "name": c["name"],
                    "description": c["description"],
                    "weight": c["weight"],
                }
                for c in raw
            ]
    judge = pick_judge(cfg.get("models"))
    st = tomllib.load(open(os.path.join(src, "task.toml"), "rb"))
    om = st.get("metadata", {}) or {}
    category = str(om.get("category", ""))
    tags = list(om.get("tags", []) or [])
    task_id = str(om.get("task_id", "") or os.path.basename(src))
    # distinct, descriptive slug: task_id's last "__" segment (DermOTS) else task_type
    base = (
        task_id.split("__")[-1] if "__" in task_id else (om.get("task_type") or task_id)
    )
    slug = name_slug(base) or kebab(task_id)
    name = f"{prefix}/{slug}"
    agent_to = (st.get("agent", {}) or {}).get("timeout_sec", 14400.0)
    verifier_to = (st.get("verifier", {}) or {}).get("timeout_sec", 3600.0)

    # DermOTS-style provenance (case_id/snapshot_key/tier) — kept as a traceability
    # comment when present; absent (EKW) sources just omit the line.
    prov_bits = [
        f"{k}={om[k]}" for k in ("case_id", "snapshot_key", "tier") if om.get(k)
    ]
    provenance = (
        (f"# source provenance: task_id={task_id} " + " ".join(prov_bits))
        if prov_bits
        else ""
    )

    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)

    open(os.path.join(out, "task.toml"), "w", encoding="utf-8").write(
        TASK_TOML.format(
            name=name,
            category=category,
            tags=json.dumps(tags),
            env=JUDGE_ENV,
            agent_to=agent_to,
            verifier_to=verifier_to,
            provenance=provenance,
        )
    )

    # instruction: point workspace paths at /app (see _rewrite_instruction_paths).
    instr = open(os.path.join(src, "instruction.md"), encoding="utf-8").read()
    instr = _rewrite_instruction_paths(instr)
    open(os.path.join(out, "instruction.md"), "w", encoding="utf-8").write(instr)

    # environment: colab-cli Dockerfile + source docs (recursively) into initial_workspace/
    env_dir = os.path.join(out, "environment")
    os.makedirs(env_dir)

    def _populated(d):
        return os.path.isdir(d) and any(f for f in os.listdir(d) if f != ".DS_Store")

    src_data = os.path.join(src, "environment", "data")
    src_input = os.path.join(src, "environment", "input")
    nest_under_input = False
    if not _populated(src_data) and _populated(src_input):
        # Harbor CLI 1.3 tasks (confirmed: all 50 sampled batch-2 tasks) name this
        # directory environment/input/, not EKW/DermOTS's environment/data/.
        src_data = src_input
        nest_under_input = True
    iw = os.path.join(env_dir, "initial_workspace")
    has_data = _populated(src_data)

    # DVC full-corpus convention: `dvc add data` run from inside environment/
    # tracks the WHOLE data/ directory as one output, writing the pointer as a
    # SIBLING of data/ (environment/data.dvc), not inside it -- so there is no
    # real environment/data/ directory to ship at all, only its pointer. `dvc
    # pull` (bare, cwd /app) then materializes data/ at exactly /app/data/,
    # matching the flat convention every other task already expects.
    src_dvc_dir = os.path.join(src, "environment", ".dvc")
    src_dvc_pointer = os.path.join(src, "environment", "data.dvc")
    has_dvc = os.path.isfile(os.path.join(src_dvc_dir, "config")) and os.path.isfile(
        src_dvc_pointer
    )

    if has_dvc:
        dockerfile = DOCKERFILE.replace(
            "COPY initial_workspace/ /app/\n",
            "COPY initial_workspace/ /app/\n" + DVC_DOCKERFILE_BLOCK,
        )
    else:
        dockerfile = DOCKERFILE
    open(os.path.join(env_dir, "Dockerfile"), "w", encoding="utf-8").write(dockerfile)

    src_data = os.path.join(src, "environment", "data")
    iw = os.path.join(env_dir, "initial_workspace")
    has_data = os.path.isdir(src_data) and any(
        f for f in os.listdir(src_data) if f != ".DS_Store"
    )
    if has_data:
        shutil.copytree(src_data, iw, ignore=shutil.ignore_patterns(".DS_Store"))
    elif not has_dvc:
        # An empty initial_workspace/ doesn't survive the reward-kit build: the
        # Dockerfile below unconditionally does COPY initial_workspace/ /app/, and
        # an empty directory doesn't survive zip upload, so Daytona fails sandbox
        # creation with "Path does not exist" (confirmed on cirrus-y1-task-svc-pc-2-2-0
        # and its sibling 2-1-0 -- both had no environment/data source and both broke
        # the same way). Every SVC-PC task's prompt expects real named input files, so
        # this is never a legitimate empty-workspace task -- fail loudly and point at
        # the fix (hydrate_environment.py resolves and stages the real source files)
        # instead of silently shipping a task the harness can never build. A DVC
        # full-corpus task is the one legitimate exception (checked above): its
        # data/ is represented entirely by environment/data.dvc + .dvc/config.
        raise RuntimeError(
            f"{src}: environment/data/ is missing or empty -- refusing to package an "
            f"empty initial_workspace/ (it breaks Daytona sandbox creation at eval time). "
            f"Run tools/hydrate_environment.py on this task first to stage its real "
            f"source files, then re-run to_rewardkit.py."
        )

    if has_dvc:
        os.makedirs(iw, exist_ok=True)
        shutil.copy2(src_dvc_pointer, os.path.join(iw, "data.dvc"))
        shutil.copytree(
            src_dvc_dir,
            os.path.join(iw, ".dvc"),
            ignore=shutil.ignore_patterns(".DS_Store"),
        )

    # deliverables = files the verifier reads back as output/<name>. A criterion
    # may check a single file (dict) or several together (list of file-specs).
    # SVC's rubric.json has no per-criterion file path at all (task-specificity
    # lives entirely in the criteria text; grading reads the produced workspace
    # as a whole) -- fall back to every file in the golden dir, same fallback
    # philosophy cycle.py's own _deliverables() uses for an EKW task with no
    # resolvable verifier paths.
    deliverables = []
    if not is_svc:
        for x in v["verifiers"]:
            f = (x.get("source") or {}).get("file") or {}
            specs = f if isinstance(f, list) else [f]
            for spec in specs:
                p = (spec or {}).get("arguments", {}).get("path", "")
                b = os.path.basename(p)
                if b and b not in deliverables:
                    deliverables.append(b)

    # SVC ships solution/golden/ (not solution/golden_outputs/ like EKW/DermOTS).
    gold_svc = os.path.join(src, "solution", "golden")
    gold_ekw = os.path.join(src, "solution", "golden_outputs")
    gold_harbor_cli = os.path.join(src, "solution", "files")
    if not os.path.isdir(gold_ekw) and _populated(gold_harbor_cli):
        # Harbor CLI 1.3 tasks (confirmed: all 50 sampled batch-2 tasks) name this
        # directory solution/files/, not EKW/DermOTS's solution/golden_outputs/.
        # Every one of the 50 has an empty golden_outputs/ (nonexistent, in fact) --
        # without this fallback every converted task's own solution/files/ output
        # ships completely empty (confirmed: fin-f10's first "fixed" conversion
        # still had zero bytes under solution/files/, silently, since nothing here
        # errors on a missing/empty golden dir).
        gold_ekw = gold_harbor_cli
    gold = gold_svc if is_svc and os.path.isdir(gold_svc) else gold_ekw
    if is_svc and not deliverables and os.path.isdir(gold):
        # SVC only: EKW's own empty-deliverables case must stay empty here (not
        # fall back to "every golden file") -- dataos_submission.py detects an
        # empty solution/files/ as the signal that golden_outputs/ held a single
        # un-extracted archive instead of the individual files, and excludes the
        # task with that explicit reason. A blanket fallback would silently mask
        # that real defect for EKW instead of surfacing it.
        deliverables = sorted(
            f
            for f in os.listdir(gold)
            if os.path.isfile(os.path.join(gold, f))
            and f.lower() not in ("reasoning.docx",)
        )

    # judge.toml's `files` list is the exact golden filename(s), hardcoded, but
    # plenty of source prompts (SVC's free-prose ones especially) never state
    # what to name the deliverable at all. An agent that picks its own reasonable
    # filename then fails every criterion with "file not found" even when the
    # work is sound (cirrus-y1-task-svc-pc-17-6-0-l2-06: claude-code wrote
    # FY2022_GM_Bridge_COGS_DPO.md instead of L2-06_GM_Bridge.xlsx, scored 0.0
    # across all 50 criteria). Restored from PR #9, which the recipes-qc-overlay
    # fold (318db63) dropped despite claiming superset coverage. .xlsm goldens
    # ship to the judge as .xlsx (see the copy loop below), so state the .xlsx
    # name. Tasks whose instruction already carries a "Graded deliverable
    # filenames" section (multi-deliverable SVC) are left alone.
    if deliverables:
        instr_path = os.path.join(out, "instruction.md")
        instr = open(instr_path, encoding="utf-8").read()
        if "Graded deliverable filenames" not in instr:
            stated = [
                os.path.splitext(n)[0] + ".xlsx" if n.lower().endswith(".xlsm") else n
                for n in deliverables
            ]
            fnames = ", ".join(stated)
            is_plural = len(stated) != 1
            addendum = (
                "\n\n---\n"
                f"Save your deliverable{'s' if is_plural else ''} to /app/ using "
                f"exactly {'these filenames' if is_plural else 'this filename'}: {fnames}\n"
            )
            instr = instr.rstrip() + addendum
            open(instr_path, "w", encoding="utf-8").write(instr)
            # `instr` stays in scope for the tests/task_prompt.txt write further
            # down, so the judge's copy of the prompt carries the addendum too.

    sol_files = os.path.join(out, "solution", "files")
    os.makedirs(sol_files)
    oversized_warnings = []
    for i, nm in enumerate(deliverables):
        f = os.path.join(gold, nm)
        if not os.path.isfile(f):
            continue
        dest = os.path.join(sol_files, nm)
        shutil.copy2(f, dest)

        ext = os.path.splitext(dest)[1].lower()
        if ext == ".xlsm":
            dest = _convert_xlsm_to_xlsx(dest)
            nm = os.path.basename(dest)
            deliverables[i] = nm  # keep judge.toml's files_list in sync with the rename
        elif ext not in _JUDGE_DOCUMENT_EXTENSIONS:
            oversized_warnings.append(
                f"{nm}: extension {ext!r} is not in rewardkit's judge-readable set "
                f"{sorted(_JUDGE_DOCUMENT_EXTENSIONS)} -- the judge will try a raw-text "
                f"read and likely skip it silently"
            )

        if (
            os.path.getsize(dest) > _JUDGE_MAX_FILE_SIZE
            and os.path.splitext(dest)[1].lower() == ".docx"
        ):
            _strip_embedded_fonts(dest)
        if os.path.getsize(dest) > _JUDGE_MAX_FILE_SIZE:
            oversized_warnings.append(
                f"{nm}: {os.path.getsize(dest) / 1024 / 1024:.2f}MB, over rewardkit's "
                f"1MB judge-attachment cutoff -- it will be silently skipped from the "
                f'judge prompt and every criterion checking it will score "no"'
            )
    for w in oversized_warnings:
        print(f"  WARNING [{name}]: {w}", file=sys.stderr)
    open(os.path.join(out, "solution", "solve.sh"), "w", encoding="utf-8").write(
        SOLVE_SH
    )
    os.chmod(os.path.join(out, "solution", "solve.sh"), 0o755)
    # expert derivation write-up (EKW) as a review artifact, if present (not in files/)
    for cand in ("Reasoning.docx", "reasoning.docx"):
        rf = os.path.join(gold, cand)
        if os.path.isfile(rf):
            shutil.copy2(rf, os.path.join(out, "solution", "reasoning.docx"))
            break

    # tests/
    tests = os.path.join(out, "tests")
    os.makedirs(tests)
    # __DELIVERABLE_NAMES__ is a plain str.replace() placeholder, not a
    # .format() field -- TEST_SH already contains many literal {}/${} characters
    # (bash variable braces, embedded Python f-strings) that would need
    # extensive escaping under .format(). Deliverable names are shell-quoted
    # since a filename could contain a space.
    deliverable_names_bash = " ".join(shlex.quote(d) for d in deliverables)
    test_sh_rendered = TEST_SH.replace("__DELIVERABLE_NAMES_PY__", json.dumps(list(deliverables))).replace(
        "__DELIVERABLE_NAMES__", deliverable_names_bash
    )
    open(os.path.join(tests, "test.sh"), "w", encoding="utf-8").write(test_sh_rendered)
    os.chmod(os.path.join(tests, "test.sh"), 0o755)
    open(os.path.join(tests, "task_prompt.txt"), "w", encoding="utf-8").write(instr)
    open(os.path.join(tests, "reward.toml"), "w", encoding="utf-8").write(
        '[[reward]]\nname = "reward"\naggregation = "weighted_mean"\n'
    )

    if use_programmatic:
        # Native rewardkit programmatic checks (see CHECKS_PY / _write_programmatic_checks):
        # no judge, no criteria_norm, no max_criteria_per_judge chunking -- a .py file has
        # no LLM structured-output schema-size limit to blow past.
        _write_programmatic_checks(src, tests, verifier_path)
        n_verifiers = len(v["verifiers"])
        print(
            f"{os.path.basename(out)}: name={name}  judge=none (programmatic/rl_world_verifiers)  "
            f"criteria={n_verifiers}  deliverables={deliverables}"
        )
        return
    files_list = ", ".join(f'"/app/{d}"' for d in deliverables)
    used = set()

    def crit_name(raw, idx):
        # reward-kit requires ^[a-zA-Z0-9_-]{1,64}$ — cap at 64, keep unique.
        n = kebab(raw)[:64].rstrip("-")
        if not n or n in used:
            n = f"{n[:58].rstrip('-')}-{idx}" if n else f"criterion-{idx}"
        used.add(n)
        return n

    # A single judge.toml with every criterion can blow past Anthropic's structured-
    # output schema-size limit ("compiled grammar is too large") on large rubrics --
    # confirmed on 17/26 in a real DataOS batch. Past max_criteria_per_judge, split into
    # multiple tests/deliverables_NN/ folders (NN criteria each, same files/judge) instead
    # of one tests/deliverables/.
    #
    # IMPORTANT: rewardkit does NOT pool criteria across these folders into one flat
    # weighted mean (checked rewardkit/runner.py directly -- discover() names each
    # folder's Reward after the folder itself, e.g. "deliverables_03", not a shared
    # name). reward.toml's weighted_mean instead combines these per-folder DIMENSIONS,
    # weighting each by [judge].weight (default 1.0 if unset). Leaving that default
    # in place makes every chunk count equally regardless of size -- e.g. a 2-criterion
    # chunk would count as much as a 12-criterion chunk, inflating whatever happens to
    # land in a small last chunk (here: two must-pass gates) to ~5x its intended share.
    # Set [judge].weight = that chunk's own criteria weight-sum so the cross-chunk
    # aggregation reconstructs the intended flat-pool weighting instead.
    if len(criteria_norm) > max_criteria_per_judge:
        chunks = [
            criteria_norm[i : i + max_criteria_per_judge]
            for i in range(0, len(criteria_norm), max_criteria_per_judge)
        ]
        folder_names = [f"deliverables_{i:02d}" for i in range(1, len(chunks) + 1)]
    else:
        chunks = [criteria_norm]
        folder_names = ["deliverables"]

    global_idx = 0
    for chunk, folder in zip(chunks, folder_names):
        chunk_dir = os.path.join(tests, folder)
        os.makedirs(chunk_dir)
        chunk_weight = round(sum(c["weight"] for c in chunk), 6)
        lines = [
            "[judge]",
            f'judge = "{judge}"',
            f"files = [{files_list}]",
            f"weight = {chunk_weight}",
            f"timeout = {JUDGE_TIMEOUT_SEC}",
            "",
        ]
        for c in chunk:
            global_idx += 1
            cname = crit_name(c["name"], global_idx)
            lines += [
                "[[criterion]]",
                f'name = "{cname}"',
                "description = " + toml_lit(c["description"]),
                'type = "binary"',
                f'weight = {c["weight"]}',
                "",
            ]
        lines += ["[scoring]", 'aggregation = "weighted_mean"', ""]
        open(os.path.join(chunk_dir, "judge.toml"), "w", encoding="utf-8").write(
            "\n".join(lines)
        )

    wsum = round(sum(c["weight"] for c in criteria_norm), 4)
    gate_note = (
        "  (has must-pass gate in source rubric.json, approximated here by "
        "weight only -- reward-kit's weighted_mean has no hard-gate concept)"
        if has_gate
        else ""
    )
    print(
        f"{os.path.basename(out)}: name={name}  judge={judge}  criteria={len(criteria_norm)}  "
        f"judge_files={len(chunks)} (max {max_criteria_per_judge}/file)  "
        f"wsum={wsum}  deliverables={deliverables}{gate_note}"
    )


if __name__ == "__main__":
    extra = [int(sys.argv[4])] if len(sys.argv) > 4 else []
    convert(sys.argv[1], sys.argv[2], sys.argv[3], *extra)
