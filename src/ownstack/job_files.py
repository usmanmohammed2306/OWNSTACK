"""Bounded regular-file queue IO; never follow a submitted symlink or FIFO."""
import json
import os
from pathlib import Path
import stat
import tempfile


def read_bytes(path: Path, limit: int):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError('Queue message must be one bounded regular file')
        raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('Queue message exceeds bounds')
    return raw


def read_json(path: Path, limit: int):
    result = json.loads(read_bytes(path, limit))
    if not isinstance(result, dict):
        raise ValueError('Queue message must be an object')
    return result


def write_json(path: Path, value, limit=1_048_576):
    raw = json.dumps(value).encode()
    if len(raw) > limit:
        raise ValueError('Queue message exceeds bounds')
    fd, temporary = tempfile.mkstemp(prefix='.queue-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            # Root supervisor and UID 10001 exchange files via the shared directory GID.
            # A restrictive 0640 mode must not strand results in root's primary group.
            os.fchown(stream.fileno(), -1, path.parent.stat().st_gid)
            os.fchmod(stream.fileno(), 0o640)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)  # Replaces the link itself, never its target.
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
