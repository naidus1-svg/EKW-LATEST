#!/bin/bash
# usage: run_verifier.sh <ws_dir> <out_dir> [lane]
# One fresh-context verifier call per workspace (task) with the frozen VERIFIER_PROMPT_V11.md, on Max plan
# Claude Code (no paid API). Resumable: skips a task whose <out_dir>/<task>/verdicts.json exists.
# Isolation: when <lane> is given and /root/pq/b12/work/others/h/sandbox.sh exists, each call runs in that
# private mount namespace (the agent sees only its workspace copy). Without a lane it runs `claude -p` with
# the workspace as working directory (weaker isolation; say so in the run log).
set -u
H="$(cd "$(dirname "$0")" && pwd)"
WS=$1; OUT=$2; LANE=${3:-}
P="$H/../prompts/VERIFIER_PROMPT_V11.md"
( cd "$H/../prompts" && sha256sum -c VERIFIER_PROMPT_V11.sha256 >/dev/null ) || { echo "VERIFIER PROMPT HASH MISMATCH"; exit 2; }
mkdir -p "$OUT/logs"
for d in "$WS"/*/; do
  t=$(basename "$d"); o="$OUT/$t"
  [ -s "$o/verdicts.json" ] && continue
  r=$(mktemp -d); cp -r "$d/." "$r/"
  log="$OUT/logs/$t.$(date +%s).jsonl"
  if [ -n "$LANE" ] && [ -x /root/pq/b12/work/others/h/sandbox.sh ]; then
    /root/pq/b12/work/others/h/sandbox.sh "$LANE" "$r" "$P" > "$log" 2> "${log%.jsonl}.err"
  else
    ( cd "$r" && timeout 1800 claude -p --model opus --output-format stream-json --verbose \
        --allowedTools "Read,Glob,Grep,Bash,Write" --permission-mode acceptEdits "$(cat "$P")" ) > "$log" 2> "${log%.jsonl}.err"
  fi
  if python3 "$H/check_out.py" "$r" "$log" "$o"; then echo "$(TZ=America/New_York date '+%F %T ET') $t ok" >> "$OUT/done.log"
  else echo "$(TZ=America/New_York date '+%F %T ET') $t FAIL" >> "$OUT/done.log"; fi
  cp "$r/items_index.csv" "$o/" 2>/dev/null
  rm -rf "$r"
done
