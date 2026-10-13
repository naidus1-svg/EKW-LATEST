#!/bin/bash
# Overnight directed-fix + deterministic verify, fire-and-forget on the lanes.
# The laptop writes and launches this; the LANES do every fix and every oracle.
#
# $1 = task-list file (one SVC-PC-<t> id per line; CRLF tolerated, blanks dropped).
# Requires on the sandbox: /root/qc/_findings.json (from svc_harvest_dataos_findings.py, pushed by the
# laptop), /root/qc/svc_dataos_fix.sh, /root/qc/svc_dataos_fix_brief.py, /root/qc/tools/svc_preship_gate.sh.
#
# Launch DETACHED so an SSH drop under load does not kill it:
#   scp -P 2222 -i ~/.ssh/kiem_sandbox tools/svc_dataos_overnight.sh root@136.113.78.105:/root/qc/
#   ssh ... 'chmod +x /root/qc/svc_dataos_overnight.sh; \
#     (setsid nohup bash /root/qc/svc_dataos_overnight.sh /root/qc/_round.txt \
#        >/root/qc/_overnight.log 2>&1 </dev/null &); exit 0'
# Then poll (do NOT wrap in an until-grep loop; just re-read):
#   ssh ... 'tail -5 /root/qc/_dataosfix/progress.txt; echo ---; tail -20 /root/qc/_preship/verdicts.txt'
set -u
QC=/root/qc
W=$QC/_dataosfix
MODEL="${2:-sonnet}"   # $2 = fixer model; targeted re-derivation rounds pass 'opus'
mkdir -p "$W"

# normalize the list: strip CR (a Windows-written list glues \r to every id -> tasks silently not found),
# drop blank lines. Everything downstream reads this LF copy.
tr -d '\r' < "$1" | grep . > "$W/_list_lf.txt"
N=$(wc -l < "$W/_list_lf.txt")
echo "OVERNIGHT_START $(date -u +%FT%TZ) list=$1 tasks=$N model=$MODEL" >> "$W/progress.txt"
if [ "$N" -eq 0 ]; then
  echo "OVERNIGHT_ABORT empty task list" >> "$W/progress.txt"; exit 1
fi

# 1) directed fix: Sonnet, one agent per task, that task's exact DataOS findings. Blocks until FIX_DONE.
bash "$QC/svc_dataos_fix.sh" "$W/_list_lf.txt" "$MODEL"

# 2) deterministic + oracle verify on every task (static <=15/dir, mojibake, missing-file, golden 1.0).
mapfile -t TASKS < "$W/_list_lf.txt"
bash "$QC/tools/svc_preship_gate.sh" "${TASKS[@]}"

# 3) ready = golden actually oracle-1.0 AND all deterministic clean.
#    tier2 = SHIPPABLE but oracle could not run locally (/app path or a capped lane): shippable, not proven.
V=$QC/_preship/verdicts.txt
grep ' SHIPPABLE' "$V" | grep -v 'oracle-unverified' | awk '{print $1}' > "$W/ready.txt"
grep ' SHIPPABLE' "$V" | grep    'oracle-unverified' | awk '{print $1}' > "$W/ready_tier2.txt"
grep ' BLOCK'     "$V"                                | awk '{print $1}' > "$W/held.txt"
echo "OVERNIGHT_DONE $(date -u +%FT%TZ) ready=$(wc -l < "$W/ready.txt") tier2=$(wc -l < "$W/ready_tier2.txt") held=$(wc -l < "$W/held.txt")" >> "$W/progress.txt"
# Zip + upload is the user's action. ready.txt is the locally-verified resubmit set.
