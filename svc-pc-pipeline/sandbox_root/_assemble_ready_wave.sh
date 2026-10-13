#!/bin/bash
# Assemble the batch-ready pool from the oracle sweep. Tier 1 = oracle 1.0 (fully verified).
# Tier 2 = oracle-unverified (ERR/None, local /app-path limit; static+mojibake clean, DataOS runs golden).
# Builds a zip of the first N tier-1 tasks for the next cost-reduced DataOS batch.
set -u
CORPUS=/root/ekwqc/pipeline/data/svc_pc_qc/03_dataos_ready
P=/root/qc/_oraclesweep/progress.txt
OUT=/root/qc/_ready
mkdir -p "$OUT"
N="${1:-15}"
ZIP="${2:-/root/qc/dataos-batch2-2026-09-21.zip}"

grep "= 1.0$" "$P" | awk '{print $2}' | sort -u > "$OUT/tier1_oracle_clean.txt"
grep -E "= (ERR|None)$" "$P" | awk '{print $2}' | sort -u > "$OUT/tier2_oracle_unverified.txt"
grep -E "= 0\.[0-9]" "$P" | awk '{print $2" "$4}' > "$OUT/golden_broken.txt"

echo "tier1 oracle-clean:      $(wc -l < "$OUT/tier1_oracle_clean.txt")"
echo "tier2 oracle-unverified: $(wc -l < "$OUT/tier2_oracle_unverified.txt")"
echo "golden-broken (<1.0):    $(wc -l < "$OUT/golden_broken.txt")"

# build a wave zip from the first N tier-1 tasks
mapfile -t WAVE < <(head -n "$N" "$OUT/tier1_oracle_clean.txt")
echo "building wave zip of ${#WAVE[@]} tier-1 tasks -> $ZIP"
rm -f "$ZIP"
( cd "$CORPUS" && zip -rq "$ZIP" "${WAVE[@]}" )
/usr/bin/python3 -c "import zipfile,os
z=zipfile.ZipFile('$ZIP')
print('bytes',os.path.getsize('$ZIP'))
print('testzip',z.testzip())
print('tasks',sorted(set(n.split('/')[0] for n in z.namelist())))"
printf '%s\n' "${WAVE[@]}" > "$OUT/wave_shipped.txt"
