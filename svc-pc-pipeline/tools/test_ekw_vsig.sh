#!/bin/bash
# Tests the "same blocker" fingerprint (VSIG) in ekw_v1_lane_runner.sh. It extracts the block between "VPARA=" and
# the fallback line and runs it against fixture verify records. 2026-09-26: the old lowercase-only regex matched the
# v1/v8 inside the appended METHOD_VERSION line, so two NOT-READY verdicts citing DIFFERENT uppercase criteria
# (SCO-226: V05/V16 then V29) fingerprinted identically and the task parked as stuck.
# Usage: bash test_ekw_vsig.sh /path/to/ekw_v1_lane_runner.sh [python3]
set -u
R="${1:?runner path}"; PY="${2:-$(command -v python3)}"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
RAW="$T/raw"; mkdir -p "$RAW"
printf '{"verifiers":[{"name":"V05"},{"name":"V16"},{"name":"V29"},{"name":"NUM01"}]}' > "$RAW/verifier.json"
BLOCK="$(sed -n '/^    VPARA=/,/^    \[ -z "\$VSIG" \] && VSIG=/p' "$R")"
[ -n "$BLOCK" ] || { echo "FAIL could not extract the VSIG block"; exit 1; }
sig(){ VREC="$1"; eval "$BLOCK"; printf '%s' "$VSIG"; }
mk(){ printf 'audit notes\n\nVERDICT: NOT-READY\n%s\n\nMETHOD_VERSION: ekw-v1/v8.1-2026-09-22-class-fix\n' "$2" > "$T/$1"; }
mk a.md "B1: V05 and V16 over-enforce the date window."
mk b.md "B1: V29 grades correctness where the prompt asks for consistency."
mk c.md "B1: V05 and V16 over-enforce the date window (still)."
mk d.md "B1: the golden memo claims RNO is mix-driven; no criterion named."
mk e.md "B1: the golden memo claims RNO is mix-driven; no criterion named."
fail=0
ok(){ if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
A="$(sig "$T/a.md")"; B="$(sig "$T/b.md")"; C="$(sig "$T/c.md")"; D="$(sig "$T/d.md")"; E="$(sig "$T/e.md")"
ok "different uppercase criteria -> different signature ('$A' vs '$B')" '[ "$A" != "$B" ]'
ok "same criteria, different wording -> same signature ('$A' vs '$C')" '[ "$A" = "$C" ]'
ok "signature holds criterion names, never the METHOD_VERSION v1/v8" '[ "$A" = "V05 V16 " ] && ! printf "%s" "$A$B" | grep -qw -e v1 -e v8'
ok "no criterion named -> text fallback, stable for identical text" '[ -n "$D" ] && [ "$D" = "$E" ]'
[ "$fail" = 0 ] && echo "4/4 PASS" || { echo FAILED; exit 1; }
