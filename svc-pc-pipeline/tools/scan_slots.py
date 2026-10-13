#!/usr/bin/env python3
"""scan_slots.py - admission control for the CPU-heavy deterministic scans. v2 (2026-09-19 18:00Z, after the Fable verification).

Why (15:59Z): the qc-scans cgroup caps how much CPU the scans may take (10 cores) but nothing bounded how many scan jobs were
admitted. Fifteen scans of 24 workers each (553 processes) shared those 10 cores: every CPU period was throttled, the median scan
had been running 13 minutes and the oldest 56, the per-file timeouts fired from starvation (874 skips), and load average sat near
190 for an hour. The guard's host_load alert fired three times and nothing acted on it.

What this does, at the one place every launcher goes through (the scan process itself):
  acquire(scan, task)  blocks until one of K slots is free (K = lanes/SCAN_SLOTS, default 3) and holds it by flock for the
                       life of the process, then moves the process into the slotted cgroup. The kernel releases the lock on
                       any exit, including SIGKILL, so there are no stale locks.
  workers(n)           caps a pool size at lanes/SCAN_WORKERS (default 4).
Fail-open: an error before a slot is held lets the scan run unbounded and writes one FAIL-OPEN line to scan_slots.log.
Kill switch: touch lanes/SCAN_SLOTS_OFF (both functions become no-ops).
State for the guard and scan_health.py: lanes/scan_slots/slot.<i> (holder: pid scan task epoch) and lanes/scan_slots/wait.<pid>
(waiter: scan task epoch). Both are checked against live pids by the readers. Test overrides: QC_LANES, QC_SCAN_LOG, QC_SCAN_CG.

v2 changes, from VERIFY-REPORT-2026-09-19.md sections B and F:
  - the slot dies with the acquirer: forked pool workers close the slot fd (os.register_at_fork), so a SIGKILLed parent frees
    its slot at once even while orphaned workers live (X5; a flock lives while ANY fd to the open file description is open);
  - a failed slot-file write after the flock keeps the slot (we are admitted) instead of failing open with the lock held (X8a);
  - a failed wait-marker write keeps waiting instead of bypassing admission (X8b);
  - a waiter marker whose pid was reused by a non-scan process is pruned (X4b);
  - the RELEASE line is written only by the process that acquired.
Not covered by design: a slot file deleted while held would admit a second holder (X1); nothing deletes them.
"""

import atexit
import fcntl
import os
import random
import time

LANES = os.environ.get("QC_LANES", "/root/qc/lanes")
LOGF = os.environ.get("QC_SCAN_LOG", "/root/qc/_prompts/scan_slots.log")
SLOT_DIR = os.path.join(LANES, "scan_slots")
SLOT_CG = os.environ.get("QC_SCAN_CG", "/sys/fs/cgroup/qc-scans-slotted")
DEFAULT_SLOTS = 3
DEFAULT_WORKERS = 4
_HELD = (
    []
)  # (fd, slot index); keeps the descriptor, and so the lock, alive for the life of the acquiring process
_OWNER = os.getpid()


def _iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _log(msg):
    try:
        with open(LOGF, "a") as f:
            f.write(f"{_iso()} pid={os.getpid()} {msg}\n")
    except OSError:
        pass


def _int_file(name, default, lo, hi):
    try:
        v = int(open(os.path.join(LANES, name)).read().split()[0])
        return max(lo, min(hi, v))
    except Exception:
        return default


def off():
    return os.path.exists(os.path.join(LANES, "SCAN_SLOTS_OFF"))


def slots():
    return _int_file("SCAN_SLOTS", DEFAULT_SLOTS, 1, 16)


def workers(requested):
    """A pool size capped at lanes/SCAN_WORKERS. Never raises the request; returns it unchanged when off or on error."""
    try:
        if off():
            return requested
        return max(
            1, min(int(requested), _int_file("SCAN_WORKERS", DEFAULT_WORKERS, 1, 32))
        )
    except Exception:
        return requested


def _is_scan_proc(pid):
    """Alive and still a scan: a reused pid belonging to something else counts as dead (X4b)."""
    try:
        cmd = open(f"/proc/{pid}/cmdline", "rb").read()
    except OSError:
        return False
    return b"_scan" in cmd or b"scan_slots" in cmd


def _prune_dead_waiters():
    try:
        for name in os.listdir(SLOT_DIR):
            if name.startswith("wait."):
                try:
                    if not _is_scan_proc(int(name[5:])):
                        os.remove(os.path.join(SLOT_DIR, name))
                except (ValueError, OSError):
                    pass
    except OSError:
        pass


def _drop(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _enter_cgroup():
    """Move this process (and so the pool workers it forks next) into the slotted-scans cgroup when it exists. The governor
    leaves any path containing 'qc-scans' alone. No cgroup, no permission or any error: stay where we are.
    """
    try:
        if os.path.isdir(SLOT_CG):
            with open(os.path.join(SLOT_CG, "cgroup.procs"), "w") as f:
                f.write(str(os.getpid()))
    except OSError:
        pass


def _close_in_child():
    """After fork, in the child: drop the inherited slot descriptor so the slot belongs to the parent alone (X5)."""
    while _HELD:
        fd, _ = _HELD.pop()
        try:
            os.close(fd)
        except OSError:
            pass


os.register_at_fork(after_in_child=_close_in_child)


def acquire(scan, task=""):
    """Block until a slot is free, hold it until the process exits, return the slot index.
    Returns None when admission control is off or unavailable before a slot is held (fail-open). Safe to call twice.
    """
    if _HELD:
        return _HELD[0][1]
    wait_file = os.path.join(SLOT_DIR, f"wait.{os.getpid()}")
    try:
        if off():
            return None
        os.makedirs(SLOT_DIR, exist_ok=True)
        _prune_dead_waiters()
        t0 = time.time()
        last_note = t0
        waiting = False
        while True:
            if off():
                _drop(wait_file)
                return None
            for i in range(slots()):
                fd = os.open(
                    os.path.join(SLOT_DIR, f"slot.{i}"), os.O_RDWR | os.O_CREAT, 0o644
                )
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    os.close(fd)
                    continue
                _HELD.append(
                    (fd, i)
                )  # admitted from here on: the lock is the slot, the file content is for the guard
                try:
                    os.ftruncate(fd, 0)
                    os.write(
                        fd, f"{os.getpid()} {scan} {task} {int(time.time())}\n".encode()
                    )
                except OSError as exc:
                    _log(
                        f"SLOT-WRITE-FAILED slot={i} scan={scan} task={task} error={exc!r} (slot still held)"
                    )
                _enter_cgroup()
                _drop(wait_file)
                t1 = time.time()
                _log(f"ACQUIRE slot={i} scan={scan} task={task} wait={t1 - t0:.0f}s")
                atexit.register(
                    lambda: os.getpid() == _OWNER
                    and _log(
                        f"RELEASE slot={i} scan={scan} task={task} held={time.time() - t1:.0f}s"
                    )
                )
                return i
            if not waiting:
                waiting = True
                try:
                    with open(wait_file, "w") as f:
                        f.write(f"{scan} {task} {int(t0)}\n")
                except OSError as exc:
                    _log(
                        f"WAIT-MARKER-FAILED scan={scan} task={task} error={exc!r} (still waiting)"
                    )
            if time.time() - last_note >= 300:
                last_note = time.time()
                _log(f"WAITING scan={scan} task={task} for {int(last_note - t0)}s")
            time.sleep(random.uniform(0.8, 2.5))
    except Exception as exc:
        _drop(wait_file)
        if _HELD:  # admitted before the error: keep the slot, the scan stays bounded
            return _HELD[0][1]
        _log(f"FAIL-OPEN scan={scan} task={task} error={exc!r}")
        return None
