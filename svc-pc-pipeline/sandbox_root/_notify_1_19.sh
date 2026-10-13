#!/bin/bash
set -u
send() { tmux send-keys -t "$1" -l "$2"; tmux send-keys -t "$1" C-m; }
echo 8 > /root/qc/BUDGET
echo "$(date -u +%FT%TZ): Khiem raised BUDGET to 8 agents per session (was 6). Ramp per 1.14 still applies." >> /root/qc/RATE-LIMIT-LOG.md

ALL="Khiem, 12:50 UTC. Three items. (1) BUDGET is now 8 agents per session (/root/qc/BUDGET), ramp per 1.14. (2) 25-4-0, 53-0-0, 53-5-0 are back: 14 of 15, 0 accept. Read /root/qc/GATE-V2.md 1c (classes Q pre-answered corpus, R authority labels, S pinned discretion, golden failing its own row rules, Sources boilerplate), 2b (what the 45 checks did: they fired, stage_and_zip.sh printed the fail list and zipped anyway, warn never printed, skip read as pass), the new maps (e) requirement and (f) discretion in 3.2, the 3.3 additions, and the 3.4 actuator paragraph. Then SESSIONS.md 1.19. (3) A skip or warn in a gate-relevant check is not a pass; it needs a written reason in GATE.md."

send main "$ALL Main-specific: before your next zip, edit /root/qc/stage_and_zip.sh per GATE-V2 3.4 last paragraph (exit non-zero on any fail; on warn/skip/error in the named gate-relevant set; print every non-pass cell; environment_size_budget threshold 10,000,000 bytes). You own 14 returned tasks now (plus 25-4-0, 53-0-0, 53-5-0); rebuild in batches of 10 into out/main/resubmit/. Restore business-readable names in 25-4-0 Sources!B6:B32."
send Z "$ALL Z-specific: GATE-V2 section 4 step 1 gained five scan additions (answer_preexposure_scan.py; authority-label and unrendered-template passes inside source_reliability_scan.py; band text and self-contradicting thresholds inside rubric_consistency_scan.py; row-caption and repeated-boilerplate checks inside formula_cache_scan.py; discretion_pin_scan.py). Same pattern, same tools/reports/ CSVs. Also make every scan able to report into summary.csv so the actuator sees it."
send D "$ALL D-specific: 42-3-0 and 42-9-0 goldens carry the boilerplate Sources sentence; restore business-readable record names as part of their gate-v2 pass. You were unblocked at 12:35, start now."
send B "$ALL B-specific: 42-7-0 golden carries the boilerplate Sources sentence three times; restore business-readable record names as part of its gate-v2 pass. You were unblocked at 12:35, start now."
for s in E F; do send "$s" "$ALL You were unblocked at 12:35, start now."; done
echo sent
