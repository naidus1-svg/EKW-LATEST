#!/usr/bin/env bash
# Every 2 minutes (cron, flock singleton): archive stale higher-round reviewer verdicts that shadow a fresh lower-round one.
# Why (2026-09-19 21:10Z): zip_when_ready.sh, the actuator and the guard take the HIGHEST round number per reviewer. A gate
# re-open archives round>=2 and the fix cycle writes its re-reviews as round 1, but guard_rt.check_dataos_reviews_promoted()
# can copy the DataOS-fixer reviews in as a new round 2 before the fix runs; once the fix changes bytes, that round 2 (older
# bytes) outranks the fresh round 1 and the task sits behind the byte check for good. tools/archive_shadowed_rounds.py has the
# exact rule (older than the newest shipped file, a lower canonical round at least as new as it, no review running); nothing
# ran it on a cadence. 12-6-0, 17-2-0 and 38-1-0 were in that state at 21:05Z.
cd /root/qc || exit 1
ids=$(python3 tools/archive_shadowed_rounds.py scan 2>/dev/null | grep -oE "^SVC-PC-[0-9]+-[0-9]+-[0-9]+" | sort -u)
[ -n "$ids" ] || exit 0
# shellcheck disable=SC2086
python3 tools/archive_shadowed_rounds.py apply $ids >> _prompts/archive_shadowed.log 2>&1
