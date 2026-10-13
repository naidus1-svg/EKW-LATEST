"""Data-OS upload-time discovery scaffold.

Exists solely so Data-OS's own rewardkit.discover() (which it runs against
every uploaded task's tests/ directory, independent of the task's own grading
mechanism -- see pipeline/tools/to_dataos_harbor.py's module docstring) finds
at least one native reward-kit criterion. Confirmed (2026-09-08) that a task
with zero native criteria surfaces "Unable to parse tests under tests/" as a
blocking upload error, not a cosmetic warning -- this file is the fix.

This criterion is NEVER actually invoked at real grading time: this task's
own tests/test.sh always grades via verifier_runtime.pyrun, which computes
and writes the authoritative reward.json / reward-details.json directly. This
file only needs to IMPORT successfully and register one factory call --
rewardkit.runner._build_programmatic_input() imports it and builds a Reward
descriptor from the registered criteria, but does not execute the check
function body itself (that only happens if something later actually runs the
discovered Reward). weight=0 is a deliberate second layer of safety: even in
the unlikely case Data-OS's own grading pipeline independently executes
reward-kit's discovered rewards in addition to (not instead of) this task's
test.sh, a weight=0 criterion cannot move the final score either way.
"""
import rewardkit as rk


@rk.criterion(description="Data-OS upload discovery scaffold (inert; see module docstring)")
def _dataos_discovery_probe(workspace, path: str) -> bool:
    return (workspace / path).exists()


rk._dataos_discovery_probe("instruction.md", weight=0, name="dataos_discovery_probe")
