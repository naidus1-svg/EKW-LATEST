#!/bin/bash
# Add a Claude Max account as a new SVC/EKW lane, driven from chat (no terminal needed by the account owner).
#   lane_login.sh start  <lane> <expected-email>   -> prints the sign-in URL to send to the account owner
#   lane_login.sh finish <lane> <code>             -> enters the code, verifies, starts a dispatcher
#   lane_login.sh remove <lane>                    -> stops the lane and deletes its login
# finish refuses (and deletes the login) if the signed-in email is not the expected one or is already on another lane.
set -u
QC=/root/qc; ST=$QC/_lanes_pending; mkdir -p "$ST"
cmd=${1:-}; L=${2:-}
[[ "$L" =~ ^[a-z][0-9]{0,2}$ ]] || { echo "usage: $0 start|finish|remove <lane> ..." >&2; exit 2; }
D=/root/.claude-$L; S=lane_$L
email_of() { python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("oauthAccount",{}).get("emailAddress",""))' "$1/.claude.json" 2>/dev/null; }

case $cmd in
start)
  want=${3:?expected email required}
  [ -f "$D/.credentials.json" ] && { echo "REFUSED: lane $L already has a login ($(email_of $D))"; exit 1; }
  for o in /root/.claude-*; do [ "$(email_of $o)" = "$want" ] && [ -f "$o/.credentials.json" ] && { echo "REFUSED: $want is already lane ${o##*-}"; exit 1; }; done
  echo "$want" > "$ST/$L.expect"
  mkdir -p "$D"; tmux kill-session -t "$S" 2>/dev/null
  tmux new-session -d -s "$S" -x 400 -y 60 "CLAUDE_CONFIG_DIR=$D claude"
  for i in $(seq 1 20); do
    sleep 2; P=$(tmux capture-pane -J -pt "$S")
    if grep -q "oauth/authorize" <<<"$P"; then break; fi
    grep -qiE "text style|Select login method|Press Enter" <<<"$P" && tmux send-keys -t "$S" Enter
  done
  URL=$(tmux capture-pane -J -pt "$S" | tr -d '\n' | grep -oE 'https://claude\.com/cai/oauth/authorize[^ ]*' | head -1)
  [ -n "$URL" ] || { echo "FAILED: no sign-in URL appeared"; tmux capture-pane -pt "$S" | tail -15; exit 1; }
  echo "LANE $L  ACCOUNT $want"; echo "$URL" ;;
finish)
  code=${3:?code required}; want=$(cat "$ST/$L.expect" 2>/dev/null)
  tmux has-session -t "$S" 2>/dev/null || { echo "FAILED: no pending login for $L (run start again)"; exit 1; }
  tmux send-keys -t "$S" -l "$code"; sleep 1; tmux send-keys -t "$S" Enter; sleep 10
  tmux send-keys -t "$S" Enter; sleep 3; tmux kill-session -t "$S" 2>/dev/null
  [ -f "$D/.credentials.json" ] || { echo "FAILED: login did not complete (code expired or wrong); run start again"; exit 1; }
  got=$(email_of $D)
  bad=""; [ -n "$want" ] && [ "$want" != any ] && [ "$got" != "$want" ] && bad="signed in as $got, expected $want"
  for o in /root/.claude-*; do [ "$o" != "$D" ] && [ -f "$o/.credentials.json" ] && [ "$(email_of $o)" = "$got" ] && bad="$got is already lane ${o##*-}"; done
  if [ -n "$bad" ]; then shred -u "$D/.credentials.json"; echo "REFUSED and login deleted: $bad"; exit 1; fi
  ok=$(cd /root && timeout 120 env CLAUDE_CONFIG_DIR=$D claude -p "reply with the single word ok" --model sonnet 2>&1 | tail -1)
  if [ "$ok" != ok ]; then grep -qi "limit" <<<"$ok" && { echo "CAPPED (login kept, pool starts it when the limit resets): $ok"; st=CAPPED; } || { echo "FAILED: test call answered: $ok"; exit 1; }; fi
  (setsid nohup bash $QC/svc_v7_pool.sh "$L" > $QC/_v7/pool_$L.out 2>&1 < /dev/null &)
  rm -f "$ST/$L.expect"; sleep 30
  echo "LANE $L ${st:-LIVE, test call ok,} as $got; dispatcher started"; grep "lane $L " $QC/_v7/pool.log | tail -2 ;;
remove)
  pkill -f "svc_v7_pool.sh $L\$"
  for p in $(pgrep -f "claude|lane_runner"); do grep -qz "CLAUDE_CONFIG_DIR=$D" /proc/$p/environ 2>/dev/null && kill $p; done
  tmux kill-session -t "$S" 2>/dev/null
  [ -f "$D/.credentials.json" ] && shred -u "$D/.credentials.json"
  [ -d "$D" ] && mv "$D" "/root/_removed_claude-${L}_$(date +%s)"
  # claim dirs carry no lane id; the pool log does. Release every task this lane claimed (its runner is dead now).
  for t in $(grep -oP "POOL lane $L claim \K\S+" $QC/_v7/pool.log | sort -u); do
    for c in $QC/_v7/claims/$t $QC/_ekw/claims/$t; do [ -d "$c" ] && rm -f "$c"/* && rmdir "$c" && echo "released claim $t"; done
  done
  echo "LANE $L removed (login deleted)" ;;
*) echo "usage: $0 start|finish|remove <lane> ..." >&2; exit 2 ;;
esac
