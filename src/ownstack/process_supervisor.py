"""Linux sidecar child cleanup, not a substitute for per-job kernel isolation."""
import ctypes
import os
from pathlib import Path
import signal
import time


def enable_subreaper() -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # Linux PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), "Cannot establish child supervision")


def descendants() -> dict[int, int]:
    """Return PID -> Linux start ticks for descendants of this supervisor only."""
    records = {}
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            raw = (path / "stat").read_text()
            fields = raw[raw.rfind(")") + 2:].split()
            records[int(path.name)] = (int(fields[1]), int(fields[19]))
        except (OSError, ValueError, IndexError):
            continue
    parents, found = {os.getpid()}, {}
    while True:
        added = {pid: start for pid, (parent, start) in records.items() if parent in parents and pid not in found}
        if not added:
            return found
        found.update(added)
        parents.update(added)


def cleanup_descendants() -> dict:
    deadline = time.monotonic() + 2
    signalled = set()
    while True:
        for pid, start in descendants().items():
            # Recheck the process identity before signalling, not a cached PID alone.
            if descendants().get(pid) != start:
                continue
            try:
                os.kill(pid, signal.SIGKILL)
                signalled.add((pid, start))
            except ProcessLookupError:
                pass
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
            except ChildProcessError:
                break
        remaining = descendants()
        if not remaining or time.monotonic() >= deadline:
            return {"descendants_reaped": not remaining, "signalled_descendants": len(signalled),
                    "remaining_descendants": len(remaining)}
        time.sleep(0.01)
