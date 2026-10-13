#!/bin/bash
# Send the 1.18 update to each tmux session. -l sends literally, C-m submits (queues behind the current turn).
set -u
send() { tmux send-keys -t "$1" -l "$2"; tmux send-keys -t "$1" C-m; }

ALL="Update 12:30 UTC. Four more DataOS verdicts are in (10-2-0, 12-2-0, 19-6-0, 22-5-0; 11 of 15 back, 0 accept). Read /root/qc/GATE-V2.md section 1b (six new classes K to P), the 3.1 no-cache probe, the 3.2 maps a/c/d, the 3.3 additions, and the 3.4 additions, then /root/qc/SESSIONS.md 1.18. The one that touches every xlsx task: class K, the grader reads stored cell values only and an openpyxl workbook has none, so every xlsx deliverable gets the one-sentence disclosure from 3.3 K in instruction.md and tests/task_prompt.txt before it ships. Quantifier gaps in the golden are 1.1 major. Acknowledge in your STATUS file. Keep holding for Z's tools where you were already holding."

send main "$ALL Main-specific: you now have 11 returned tasks to rebuild into out/main/resubmit/, not 7; the four new JSON pairs are in /root/qc/in/dataos-cr-batch1-returns/ with a README table. Read both reviewers per task; the fix list is the union."
send Z "$ALL Z-specific: GATE-V2 section 4 step 1 now lists six more scans and one extension for you (formula_cache_scan.py with a --probe mode that calls judge_emulate.py, quantifier_scope_scan.py, escape_hatch_scan.py, source_reliability_scan.py, rubric_consistency_scan.py, and named-document matching in instruction_input_scan.py), plus stripping the must-pass sentence corpus-wide alongside the rewardkit pin. Same Sonnet-writes pattern, same tools/reports/ CSVs, stay under BUDGET. judge_emulate.py stays as built: reusing rewardkit's _build_user_content is exactly what class K needs."
for s in B D E F; do send "$s" "$ALL"; done
echo sent
