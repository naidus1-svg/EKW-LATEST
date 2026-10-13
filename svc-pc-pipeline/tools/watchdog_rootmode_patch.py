#!/usr/bin/env python3
"""Add a HOST guard to watchdog.sh: the root directory must stay mode 755. On 2026-09-18 about
20:10 UTC something set / to 0700; every non-root service (networkd, resolved, sshd privsep, exim)
lost access and the VM dropped off the network until a rescue-disk repair 30 minutes later.
"""

p = "/root/qc/tools/watchdog.sh"
s = open(p).read()
anchor = "  df -P /root | awk"
add = (
    '  rm_=$(stat -c %a /); if [ "$rm_" != "755" ]; then chmod 755 / && alert "HOST FIX: root directory mode was $rm_, reset to 755 (a 0700 root took the VM off the network on 2026-09-18)"; fi\n'
    '  for dd in /etc /usr /var /run; do m=$(stat -c %a "$dd"); [ "$m" = "755" ] || { throttle "mode$dd" 3600 && alert "HOST WARN: $dd mode is $m (expected 755)"; }; done\n'
    '  m=$(stat -c %a /tmp); [ "$m" = "1777" ] || { throttle modetmp 3600 && alert "HOST WARN: /tmp mode is $m (expected 1777)"; }\n'
)
assert anchor in s and "HOST FIX: root directory" not in s
s = s.replace(anchor, add + anchor, 1)
open(p + ".new", "w").write(s)
print("watchdog.sh.new written")
