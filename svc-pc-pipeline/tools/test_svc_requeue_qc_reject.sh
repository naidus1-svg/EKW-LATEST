#!/usr/bin/env bash
# Tests for svc_requeue_qc_reject.py against a throwaway root. Run on the sandbox: bash tools/test_svc_requeue_qc_reject.sh
# No fixture zip here (the bundle-gate hook forbids scripts that write archives); the lastreject.sha path is checked
# by the dry run on real ready zips, which prints each shipped sha.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
R="$(mktemp -d)"; trap 'rm -rf "$R"' EXIT
export SVC_QC_ROOT="$R"
mkdir -p "$R/_v7/ready" "$R/_v7/claims/T-A" "$R/_deepfix" "$R/_deepbriefs/_owner_notes"
printf 'T-A\nT-B\nT-C\n' > "$R/_v7/accepted.txt"
printf 'T-C\n' > "$R/_v7/do_not_touch.txt"
printf 'X-1\nT-A\nX-2\n' > "$R/_v7/queue.txt"
echo '{}' > "$R/_v7/ready/T-A.zip.manifest.json"
echo "verdict" > "$R/_deepbriefs/_owner_notes/T-A.md"
echo "verdict" > "$R/_deepbriefs/_owner_notes/T-C.md"
echo "old" > "$R/_deepfix/T-A.verify.md"
pass=0; fail=0
ck(){ if eval "$2"; then pass=$((pass+1)); echo "ok   $1"; else fail=$((fail+1)); echo "FAIL $1"; fi; }

OUT="$(python3 "$HERE/svc_requeue_qc_reject.py" T-A T-B T-C 2>&1)"
ck "dry run refuses T-B without an owner note" 'echo "$OUT" | grep -q "T-B.*REFUSED.*no owner note"'
ck "dry run refuses T-C on do_not_touch" 'echo "$OUT" | grep -q "T-C.*REFUSED.*do_not_touch"'
ck "dry run accepts T-A" 'echo "$OUT" | grep -q "T-A .*requeue"'
ck "dry run writes nothing" 'grep -qx T-A "$R/_v7/accepted.txt" && [ -d "$R/_v7/claims/T-A" ]'

python3 "$HERE/svc_requeue_qc_reject.py" T-A --apply >/dev/null 2>&1
ck "T-A off accepted, T-B/T-C kept" '! grep -qx T-A "$R/_v7/accepted.txt" && grep -qx T-B "$R/_v7/accepted.txt" && grep -qx T-C "$R/_v7/accepted.txt"'
ck "T-A at queue head, not duplicated, others kept" '[ "$(head -1 "$R/_v7/queue.txt")" = T-A ] && [ "$(grep -cx T-A "$R/_v7/queue.txt")" = 1 ] && grep -qx X-2 "$R/_v7/queue.txt"'
ck "manifest archived" '[ ! -f "$R/_v7/ready/T-A.zip.manifest.json" ] && ls "$R"/_v7/ready/_manualqc_reject_*/T-A.zip.manifest.json >/dev/null 2>&1'
ck "claim released, verify archived" '[ ! -d "$R/_v7/claims/T-A" ] && [ ! -f "$R/_deepfix/T-A.verify.md" ]'
ck "accepted.txt backed up" 'ls "$R"/_v7/accepted.txt.bak.* >/dev/null 2>&1'

# --- EKW mode ---
mkdir -p "$R/_ekw/ready" "$R/_ekw/claims/E-1" "$R/_ekw/briefs/_owner_notes" "$R/_ekw/verify" "$R/_ekw/gate"
printf 'E-1
E-2
' > "$R/_ekw/accepted.txt"; : > "$R/_ekw/do_not_touch.txt"
printf '# header comment
Z-9
' > "$R/_ekw/queue.txt"; printf 'E-1
Z-8
' > "$R/_ekw/decide.txt"
echo "ekw verdict text" > "$R/_ekw/briefs/_owner_notes/E-1.md"
echo "old READY" > "$R/_ekw/verify/E-1.verify.md"; echo '{}' > "$R/_ekw/gate/E-1.gate.json"
python3 "$HERE/svc_requeue_qc_reject.py" --ws ekw E-1 --apply >/dev/null 2>&1
ck "ekw: off accepted, E-2 kept" '! grep -qx E-1 "$R/_ekw/accepted.txt" && grep -qx E-2 "$R/_ekw/accepted.txt"'
ck "ekw: comment stays on top, E-1 next" '[ "$(sed -n 1p "$R/_ekw/queue.txt")" = "# header comment" ] && [ "$(sed -n 2p "$R/_ekw/queue.txt")" = E-1 ]'
ck "ekw: verify seeded NOT-READY with the owner note" 'grep -q "VERDICT: NOT-READY" "$R/_ekw/verify/E-1.verify.md" && grep -q "ekw verdict text" "$R/_ekw/verify/E-1.verify.md" && grep -q "ekw verdict text" "$R/_ekw/briefs/E-1.md"'
ck "ekw: old verify + gate archived" 'ls "$R"/_ekw/verify/_pre_manualqc_*/E-1.verify.md "$R"/_ekw/verify/_pre_manualqc_*/E-1.gate.json >/dev/null 2>&1 && [ ! -f "$R/_ekw/gate/E-1.gate.json" ]'
ck "ekw: dropped from decide.txt, Z-8 kept" '! grep -qx E-1 "$R/_ekw/decide.txt" && grep -qx Z-8 "$R/_ekw/decide.txt"'
ck "ekw: claim released" '[ ! -d "$R/_ekw/claims/E-1" ]'
echo "$pass/$((pass+fail)) passed"; [ "$fail" = 0 ]
