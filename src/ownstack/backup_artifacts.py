"""Private backup generations with an explicit, durable completion marker.

An archive filename alone is never a completed backup. Readers require a pinned
manifest and verify the opened archive before giving that same descriptor to a
restore process. These digests detect damage, not an untrusted archive's SQL.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat


def _sync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _hash(stream) -> tuple[str, int]:
    stream.seek(0)
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
    stream.seek(0)
    return digest.hexdigest(), size


def publish_backup(directory: Path, writer, *, validate=None, metadata=None) -> dict:
    """Publish a new generation only after writer success, validation and fsync.

    Failures intentionally retain private partials for diagnosis. Never retry in
    place or overwrite a previous generation. The manifest is the commit marker.
    A failure after its link/fsync can be uncertain: inspect using its digest,
    rather than assuming that the generation was rolled back.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    directory.chmod(0o700)
    partial = directory / 'archive.part'
    fd = os.open(partial, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w+b') as stream:
        writer(stream)
        stream.flush()
        os.fsync(stream.fileno())
        archive_hash, size = _hash(stream)
        if not size:
            raise ValueError('Empty backup archive')
        if validate:
            validate(stream)
    manifest = {'version': 1, 'archive': 'backup.dump', 'sha256': archive_hash,
                'bytes': size, 'metadata': metadata or {}}
    # Hard links give exclusive publication without replacing another pathname.
    os.link(partial, directory / 'backup.dump')
    _sync_directory(directory)
    raw = (json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n').encode()
    fd = os.open(directory / 'manifest.part', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(directory / 'manifest.part', directory / 'manifest.json')
    _sync_directory(directory)
    partial.unlink()
    (directory / 'manifest.part').unlink()
    _sync_directory(directory)
    _sync_directory(directory.parent)
    return {**manifest, 'manifest_sha256': hashlib.sha256(raw).hexdigest()}


def _private_file(directory_fd: int, name: str):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ValueError('Backup files must be private regular files')
        return os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def verified_backup(directory: Path, manifest_sha256: str):
    """Yield verified bytes through the held descriptor, not a reopened path.

    The manifest digest must come from a separately retained trusted receipt.
    No DB creation/restore should occur before this context is entered. A local
    directory rename cannot redirect the already opened directory/archive.
    """
    if (not isinstance(manifest_sha256, str) or len(manifest_sha256) != 64
            or any(c not in '0123456789abcdef' for c in manifest_sha256)):
        raise ValueError('Pinned manifest SHA-256 required')
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if os.fstat(fd).st_mode & 0o077:
            raise ValueError('Backup generation must be private')
        with _private_file(fd, 'manifest.json') as marker:
            raw = marker.read(65537)
        if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != manifest_sha256:
            raise ValueError('Backup manifest does not match trusted receipt')
        manifest = json.loads(raw)
        if (not isinstance(manifest, dict) or type(manifest.get('version')) is not int or manifest['version'] != 1
                or manifest.get('archive') != 'backup.dump'
                or type(manifest.get('bytes')) is not int or manifest['bytes'] < 1
                or not isinstance(manifest.get('sha256'), str)):
            raise ValueError('Invalid backup manifest')
        with _private_file(fd, 'backup.dump') as archive:
            actual_hash, size = _hash(archive)
            if size != manifest['bytes'] or actual_hash != manifest['sha256']:
                raise ValueError('Backup archive checksum or length mismatch')
            yield archive, manifest
    finally:
        os.close(fd)
