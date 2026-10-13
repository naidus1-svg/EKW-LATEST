#!/usr/bin/env bash
# zip_when_ready.sh - the zip step while the launcher is paused. Every 2 minutes: for each task whose
# LATEST glm and sonnet workspace verdicts both say major_count 0, not already zipped or submitted:
#   1. verify the bytes the reviewers read == current staging (both reviewer workspaces), else skip (needs re-review)
#   2. judge-input gate (rewardkit 1 MiB / not found) -> probes/judge_input.json
#   3. oracle probe against the real /app if probes/oracle.json is missing (judge_emulate.py, fixed content root)
#   4. write REVIEWED_MANIFEST.sha256, add to lanes/ZIP_ALLOW, run the actuator
# Log: /root/qc/_prompts/zip_when_ready.log. Idempotent.
cd /root/qc || exit 1
C=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
LOG=/root/qc/_prompts/zip_when_ready.log
ORACLE_LANES=(/root/.claude-d /root/.claude-e /root/.claude-f /root/.claude-c /root/.claude-b)
log() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }
EXCL=(--exclude='_prior' --exclude='_runs' --exclude='FIX-LOG*.md' --exclude='REFUTER*.md' --exclude='CR-REFUTER.md' --exclude='_scratch' --exclude='COMPREHENSIVE-REVIEW.md' --exclude='GATE.md' --exclude='*.round1' --exclude='*.round2' --exclude='*.bak' --exclude='*.bak-*' --exclude='__pycache__' --exclude='_golden_*' --exclude='_conv_test*' --exclude='__img_embed_test__*' --exclude='capacity_tmp_conv.*' --exclude='.DS_Store')
latest() { ls "$1"/CR."$2".round*.json 2>/dev/null | grep -E 'round[0-9]+\.json$' | sed -E 's/.*round([0-9]+)\.json/\1 &/' | sort -n | tail -1 | cut -d' ' -f2; }
# stale parks came from the retired single-shot reviewer, ZIP_HOLD (rc=10) or check-fix; the actuator re-checks all of that, so they do not exclude a task here
# 20:10Z: a park is also stale when BOTH latest reviewer verdicts are newer than it (the reviewers re-read the bytes after the
# park, and the actuator re-checks the deterministic side at the zip step). The dispatcher writes "N major finding(s) still
# present after round2 (MAX_ROUNDS reached)", which the phrase list never matched, so every fix-from-reviews park skipped its
# task here for good (17-2-0: parked 03:19Z, clean round-3 verdicts, DATAOS_MAJORS_RESOLVED set 19:03Z, never attempted).
stale_park() {
  # 21:20Z: a fix-from-reviews park is stale too. It is written in the same second as the last re-review, so the verdict-age
  # test below never matched it (21-3-0), and since the 20:12Z union change its surviving majors are gate-visible findings the
  # actuator adjudicates at the zip step; a park with reviewer majors never reaches the attempt (the 0/0 check follows).
  grep -qE 'majors still present after [0-9]+ fix rounds|fix-from-reviews - [0-9]+ major finding|failed, rc=10|check-fix: still blocked' "$1" && return 0
  local d g s
  d=$(dirname "$1"); g=$(latest "$d" glm); s=$(latest "$d" sonnet)
  [ -n "$g" ] && [ -n "$s" ] && [ "$1" -ot "$g" ] && [ "$1" -ot "$s" ]
}
i=0
log "START zip_when_ready"
while true; do
  only_skipped=0
  for d in stream-pipe/SVC-PC-*; do
    t=$(basename "$d")
    # 18:45Z addendum, step B: lanes/ZIP_ONLY_LIST, when present, is an allowlist (one id
    # per line, same form as SUBMITTED.txt) - every task not on it is skipped this pass.
    # Absent file: unchanged behaviour (every task eligible as before).
    if [ -f lanes/ZIP_ONLY_LIST ] && ! grep -qx "$t" lanes/ZIP_ONLY_LIST; then
      only_skipped=$((only_skipped + 1))
      continue
    fi
    # 19:35Z addendum: by this point either ZIP_ONLY_LIST is absent, or $t IS on it (the
    # block above already `continue`d for every listed-file/not-on-it case) - a task on
    # the allowlist is explicit intent to rebuild, so it stays eligible even if it is
    # already on SUBMITTED.txt (batches 6-8's 22 calibration tasks all are). Every other
    # task keeps the ordinary SUBMITTED skip, unchanged.
    if [ ! -f lanes/ZIP_ONLY_LIST ]; then
      grep -qx "$t" SUBMITTED.txt 2>/dev/null && continue
    fi
    [ -f "out/pipe/$t.zip" ] && continue
    # 21:00Z: re-opened by the guard (or un-parked by hand) and the fixer has not run yet: the re-open cleared the
    # FIX_FROM_REVIEWS markers and archived round>=2 verdicts, so the newest pair looks new to the attempt marker and the
    # loop re-attempted 92-4-0 three times in 2.5 minutes on one block. Wait for the fix cycle to mark FIX_FROM_REVIEWS_1.
    if grep -qx "$t" lanes/FIX_FROM_REVIEWS_PRIORITY 2>/dev/null && ! grep -qx FIX_FROM_REVIEWS_1 "$d/STATE" 2>/dev/null; then
      log "SKIP $t fix pending (re-opened, fixer has not run yet)"; continue
    fi
    if [ -f "$d/PARKED.md" ] && ! stale_park "$d/PARKED.md"; then
      [ -f lanes/ZIP_ONLY_LIST ] && log "SKIP $t parked: $(tail -1 "$d/PARKED.md" | cut -c1-100)"
      continue
    fi
    if grep -qx "$t" lanes/DATAOS_REJECTED 2>/dev/null && [ ! -f "$d/DATAOS_MAJORS_RESOLVED" ]; then
      [ -f lanes/ZIP_ONLY_LIST ] && log "SKIP $t no DATAOS_MAJORS_RESOLVED marker yet (verify loop owns it)"
      continue
    fi  # DataOS already rejected these bytes-or-earlier; verifier must clear each major first
    g=$(latest "$d" glm); s=$(latest "$d" sonnet)
    if [ -z "$g" ] || [ -z "$s" ]; then
      [ -f lanes/ZIP_ONLY_LIST ] && log "SKIP $t no canonical verdict pair (glm=${g:-none} sonnet=${s:-none})"
      continue
    fi
    python3 -c "import json,sys; a=json.load(open(sys.argv[1])); b=json.load(open(sys.argv[2])); sys.exit(0 if a.get('major_count')==0 and b.get('major_count')==0 and 'checks' in a and 'checks' in b else 1)" "$g" "$s" 2>/dev/null || { [ -f lanes/ZIP_ONLY_LIST ] && log "SKIP $t pair not clean or not canonical ($(basename "$g") $(basename "$s"))"; continue; }
    # 2026-09-19 02:11Z: ZIP_ATTEMPTED used to be touched here, before the
    # oracle even ran - SVC-PC-11-4-0's oracle came back total_reward=0.0
    # because lane d hit its session limit (an infra refusal judge_emulate.py
    # used to score as a numeric 0.0, indistinguishable from a real golden
    # failure - fixed there to write total_reward=null + infra_failure=true
    # instead), the actuator blocked it rc=8, and the marker below would have
    # then skipped this task on every future loop pass forever - "BLOCK rc=8"
    # is not the same claim as "the golden actually scored under 1.0". The
    # marker is now touched only after a non-infra oracle result exists (see
    # below), so an infra-tainted probe gets exactly one retry per loop pass,
    # on the next lane in rotation, and is never treated as final.
    if [ -f "$d/ZIP_ATTEMPTED.$(basename "$g").$(basename "$s")" ]; then
      [ -f lanes/ZIP_ONLY_LIST ] && log "SKIP $t pair already attempted ($(basename "$g") $(basename "$s"))"
      continue
    fi
    S=$(mktemp -d /root/qc/checks_scratch/zwr.XXXX); rsync -a "${EXCL[@]}" "$C/$t/" "$S/$t/"
    same=1; for r in glm sonnet; do ws="review_workspace_bulk/$r/$t/task_files"; [ -d "$ws" ] || ws=$(ls -d review_workspace*/"$r"/"$t"/task_files 2>/dev/null | head -1); [ -d "$ws" ] && diff -rq "$S/$t" "$ws" >/dev/null 2>&1 || same=0; done
    [ $same = 1 ] || { log "SKIP $t bytes differ from what the reviewers read (needs re-review)"; rm -rf "$S"; continue; }
    python3 tools/judge_input_report.py --task "$t" --out "$d/probes/judge_input.json" >/dev/null 2>&1
    jb=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('blocking_major'))" "$d/probes/judge_input.json" 2>/dev/null)
    [ "$jb" = "False" ] || { log "BLOCK $t judge_input blocking ($jb)"; rm -rf "$S"; continue; }
    # oracle_needs_run: missing/unparseable file, OR a parseable file that is
    # itself an infra refusal (null/missing total_reward, infra_failure=true,
    # or - for a stale file a pre-fix judge_emulate.py already wrote - the
    # lane-refused error text still sitting in a criterion's own "error"
    # field even though total_reward came out as a misleading number).
    oracle_needs_run=1
    # oracle_taint_check: tainted if total_reward is null/missing, infra_failure
    # is set, or ANY criterion anywhere (recursing into nested group children) has
    # a non-empty per-criterion "error" - a pre-fix judge_emulate.py always wrote its
    # lane-refused text into exactly that field via _synthetic_error_scores, so this
    # already catches a stale file too. 2026-09-19 18:50Z: dropped the additional
    # LANE_RE.search(json.dumps(d)) blob-scan that used to sit here - it scanned every
    # judge verdict_text, not just error fields, and misclassified a golden that
    # legitimately discusses a "Shopify API rate-limit event" as a business fact
    # (SVC-PC-26-8-0, SVC-PC-92-4-0) as an infra refusal, discarding a real total_reward
    # =1.0. has_error() alone covers every real case with no false positives on content.
    if python3 -c "
import json, sys
def has_error(groups):
    for g in groups or []:
        for c in g.get('criteria') or []:
            if c.get('error'):
                return True
        if has_error(g.get('children')):
            return True
    return False
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
if d.get('total_reward') is None or d.get('infra_failure'):
    sys.exit(1)
if has_error(d.get('groups')):
    sys.exit(1)
sys.exit(0)
" "$d/probes/oracle.json" 2>/dev/null; then
      oracle_needs_run=0
    fi
    # 00:35Z: a probe older than the newest shipped byte has not run on these bytes (21-2-0 blocked on an 18:54Z probe
    # after a 00:17Z golden edit). Compare with the same fingerprint the verify loop uses.
    # 01:10Z: rewardkit compiles each judge group into one strict schema; Anthropic rejects large ones and the run scores 0
    # (DataOS 1.8 on 38-1-0). Measured with rewardkit's own builder; block at 4,000 bytes, the failing group was 4,574.
    mkdir -p "$d/checks"
    python3 tools/judge_schema_bytes.py "$C/$t" > "$d/checks/judge_schema_bytes.txt" 2>&1
    jsb=$?
    if [ "$jsb" -ge 2 ]; then
      log "BLOCK $t judge group schema too large for the Anthropic judge: $(grep ' BLOCK$' "$d/checks/judge_schema_bytes.txt" | awk '{print $2"="$4"B"}' | tr '\n' ' ')(rewardkit compile, limit 4000)"
      continue
    fi
    if [ "$oracle_needs_run" = "0" ] && [ -f "$d/probes/oracle.json" ]; then
      if python3 - "$t" "$d/probes/oracle.json" <<'PY' 2>/dev/null
import os, sys
sys.path.insert(0, "/root/qc/_prompts/verify/dataos-old")
import task_fingerprint as tf
sys.exit(0 if tf.newest_mtime(sys.argv[1]) > os.path.getmtime(sys.argv[2]) else 1)
PY
      then
        log "ORACLE $t probe is older than the newest shipped byte, re-running (stale probe never counts)"
        mv "$d/probes/oracle.json" "$d/probes/oracle.stale-$(date -u +%H%M%S).json"
        oracle_needs_run=1
      fi
    fi
    if [ "$oracle_needs_run" = "1" ]; then
      load1=$(awk '{print $1}' /proc/loadavg 2>/dev/null); load1_int=${load1%.*}
      case "$load1_int" in ''|*[!0-9]*) load1_int=0 ;; esac
      if [ "$load1_int" -gt 64 ]; then
        log "SKIP $t deferring oracle launch, load1=$load1 > 64"
        rm -rf "$S"; continue
      fi
      lane="${ORACLE_LANES[$(( i % ${#ORACLE_LANES[@]} ))]}"; i=$((i+1)); mkdir -p "$d/probes"
      log "ORACLE $t on $(basename "$lane") (missing/infra-tainted probe treated as not-yet-run)"
      # step B (verifier, 2026-09-19 18:25Z): the judge is not deterministic on compound
      # criteria (DataOS's own oracle scored 5-4-0 at 0.9714, q27 failed, on a bytes-
      # identical re-read) - 3 independent runs per probe, total_reward = the minimum,
      # flips (a criterion that passed in one run and failed in another) written
      # alongside to probes/oracle.runs.json. Triples this call's wall-clock cost; timeout
      # raised 1800->3600 to match.
      CLAUDE_CONFIG_DIR="$lane" timeout 3600 python3 tools/judge_emulate.py oracle "$t" --runs 3 --corpus-root "$C" --out "$d/probes/oracle.json" >> "$d/probes/oracle.log" 2>&1
      # Still infra-tainted after this one retry (e.g. the freshly-rotated
      # lane is ALSO refused): leave ZIP_ATTEMPTED unset and try again next
      # loop pass, on whichever lane is next in rotation - never zip on it.
      if python3 -c "
import json, sys
def has_error(groups):
    for g in groups or []:
        for c in g.get('criteria') or []:
            if c.get('error'):
                return True
        if has_error(g.get('children')):
            return True
    return False
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
sys.exit(1 if (d.get('total_reward') is None or d.get('infra_failure') or has_error(d.get('groups'))) else 0)
" "$d/probes/oracle.json" 2>/dev/null; then
        :  # resolved, fall through
      else
        log "SKIP $t oracle still infra-tainted after retry on $(basename "$lane"), will retry next pass"
        rm -rf "$S"; continue
      fi
    fi
    touch "$d/ZIP_ATTEMPTED.$(basename "$g").$(basename "$s")"
    o=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('total_reward'))" "$d/probes/oracle.json" 2>/dev/null)
    python3 - "$S/$t" "$d/REVIEWED_MANIFEST.sha256" <<'PYG'
import hashlib, os, sys, time
root, mf = sys.argv[1], sys.argv[2]; lines = []
for dp, dn, fn in os.walk(root):
    for f in fn:
        p = os.path.join(dp, f); lines.append(os.path.relpath(p, root) + " " + hashlib.sha256(open(p, "rb").read()).hexdigest())
open(mf, "w").write(hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest() + " " + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n")
PYG
    grep -qx "$t" lanes/ZIP_ALLOW 2>/dev/null || echo "$t" >> lanes/ZIP_ALLOW
    mkdir -p "$d/checks"
    if ! python3 tools/gate_groups_fire.py "$t" > "$d/checks/groups_fire.txt" 2>&1; then
      log "BLOCK $t judge group did not fire: $(grep BLOCK "$d/checks/groups_fire.txt" | head -1 | cut -c1-120)"
      rm -rf "$S"; continue
    fi
    out=$(bash stage_and_zip.sh "$C" "$t" out/pipe --accept-skip golden_arithmetic,deliverable_count,source_truncation 2>&1); rc=$?
    if [ $rc = 0 ] && [ -s "out/pipe/$t.zip" ]; then
      log "ZIPPED $t (oracle=$o)"
    elif [ $rc = 0 ]; then
      log "BLOCK $t rc=0 but out/pipe/$t.zip missing or empty, actuator tail: $(echo "$out" | tail -3 | tr '\n' '|')"
    else
      log "BLOCK $t rc=$rc oracle=$o $(echo "$out" | grep -E 'BLOCKED|HOLD' | tail -1 | cut -c1-150)"
    fi
    rm -rf "$S"
  done
  if [ -f lanes/ZIP_ONLY_LIST ]; then
    log "ZIP_ONLY_LIST active: skipped $only_skipped task(s) not on the list"
  fi
  sleep 120
done
