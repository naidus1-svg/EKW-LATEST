#!/usr/bin/env bash
# fix_one.sh TASK LANE - one Opus fixer pass on a gate-FAIL task, then rebuild its digest from the
# FIXED bytes and clear its verdict + reviews so the fleet re-gates the fixed content fresh.
# Bumps the per-task attempt counter. Safe: a bad fix simply re-fails the gate and never ships.
set -u
t="${1:?TASK}"; lane="${2:?LANE}"
Q=/root/qc; FLEET=$Q/fleet; REVIEWS=$FLEET/reviews; VERD=$FLEET/verdicts; ATT=$FLEET/fix_attempts
HERE=$Q/_prompts/gate-revalidate
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready; TD="$CORPUS/$t"
CLAUDE_BIN="$(command -v claude || echo /usr/bin/claude)"
mkdir -p "$ATT" "$FLEET/fixlogs" "$FLEET/jobs"
[ -d "$TD" ] || { echo "$(date -u +%FT%TZ) fix_one $t: no taskdir" >> "$FLEET/fixlogs/fix.log"; exit 2; }
[ -x "$CLAUDE_BIN" ] || { echo "$(date -u +%FT%TZ) fix_one $t: no claude bin" >> "$FLEET/fixlogs/fix.log"; exit 5; }

# 1. brief from the gate's MAJOR findings across the 4 reviews
brief="$FLEET/fixlogs/$t.brief.md"
{
  echo "You are fixing SVC-PC harbor task $t so it passes the Comprehensive Review with ZERO majors."
  echo "The task package is your current working directory. Make the MINIMAL root-cause edits that"
  echo "resolve each major below, and nothing else."
  echo
  echo "Hard rules:"
  echo "- Never lower task difficulty; remove unfairness (false rejection, false credit, golden fails"
  echo "  its own rubric, unverifiable citation, packaging), never the challenge."
  echo "- Every number you touch is recomputed from environment/initial_workspace/, never from prose."
  echo "- If you edit the prompt, edit instruction.md AND tests/task_prompt.txt identically."
  echo "- Do not wb.save() a golden xlsx without restoring its formula caches."
  echo "- Hand-grade the golden against every criterion before you finish; the golden must pass its own rubric."
  echo "- Write text files with LF line endings, no carriage returns."
  echo
  echo "MAJOR findings from the gate reviewers (fix the root cause of each):"
  echo
  for rr in opus.run1 opus.run2 sonnet.run1 sonnet.run2; do
    j="$REVIEWS/$t.$rr.json"; [ -f "$j" ] || continue
    python3 -c "import json
j=json.load(open('$j'))
for c in j.get('checks',[]):
    if c.get('severity')=='major':
        print('- ['+str(c.get('id'))+'] '+str(c.get('name')))
        print('  '+str(c.get('justification','')).replace(chr(10),' '))
        print('  SUGGESTED FIX: '+str(c.get('suggested_fix','')).replace(chr(10),' '))
        print()" 2>/dev/null
  done
  echo "When done, stop. Do not run the grader yourself; the pipeline re-verifies."
} > "$brief"

# 2. run the Opus fixer inside the task dir
cd "$TD" || exit 1
CLAUDE_CONFIG_DIR="$lane" timeout 2700 "$CLAUDE_BIN" -p "$(cat "$brief")" \
  --model opus --permission-mode dontAsk --allowedTools "Read,Edit,Write,Bash,Glob,Grep" \
  --output-format text > "$FLEET/fixlogs/$t.fix.log" 2>&1 < /dev/null
rc=$?

# 3. rebuild digest + detfindings from the FIXED bytes (else the re-gate reads stale content)
python3 "$Q/tools/v3digest_build.py" "$TD" "$HERE/digests/$t.md" > "$HERE/logs/$t.digest.refix.log" 2>&1
python3 "$Q/tools/gate_detfindings.py" "$t" "$TD" "$HERE/detfindings/$t.md" > "$HERE/logs/$t.detf.refix.log" 2>&1

# 4. bump attempt, clear verdict + reviews so the fleet re-gates fresh
a=$(cat "$ATT/$t" 2>/dev/null || echo 0); echo $((a+1)) > "$ATT/$t"
rm -f "$VERD/$t.FAIL" "$VERD/$t.PASS" "$VERD/$t.citation" "$REVIEWS/$t".*.json "$FLEET/jobs/$t".*.pid
echo "$(date -u +%FT%TZ) fix_one $t rc=$rc attempt=$((a+1)) digest-rebuilt, cleared for re-gate" >> "$FLEET/fixlogs/fix.log"
