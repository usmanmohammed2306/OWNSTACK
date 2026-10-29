"""Backup commit markers, corruption detection and held-descriptor controls."""
import errno
import hashlib
import json
import os
from pathlib import Path

import pytest

from ownstack.backup_artifacts import publish_backup, verified_backup


def generation(tmp_path, data=b'owned backup bytes'):
    directory = tmp_path / 'generation'
    receipt = publish_backup(directory, lambda stream: stream.write(data))
    return directory, receipt


def test_complete_private_generation_and_no_overwrite(tmp_path):
    directory, receipt = generation(tmp_path)
    assert {p.name for p in directory.iterdir()} == {'backup.dump', 'manifest.json'}
    assert directory.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in directory.iterdir())
    with verified_backup(directory, receipt['manifest_sha256']) as (stream, manifest):
        assert stream.read() == b'owned backup bytes' and manifest['bytes'] == 18
    with pytest.raises(FileExistsError):
        publish_backup(directory, lambda stream: stream.write(b'overwrite'))
    assert (directory / 'backup.dump').read_bytes() == b'owned backup bytes'


@pytest.mark.parametrize('fault', [errno.ENOSPC, errno.EROFS, errno.EIO, errno.EACCES])
def test_writer_failure_never_publishes_commit_marker(tmp_path, fault):
    directory = tmp_path / 'failed'
    def writer(stream):
        stream.write(b'partial')
        raise OSError(fault, 'controlled writer failure')
    with pytest.raises(OSError):
        publish_backup(directory, writer)
    assert not (directory / 'manifest.json').exists()
    assert not (directory / 'backup.dump').exists()
    assert (directory / 'archive.part').read_bytes() == b'partial'


def test_validation_failure_and_empty_archive_do_not_commit(tmp_path):
    def reject(stream):
        assert stream.read() == b'bad format'
        raise ValueError('Invalid archive')
    with pytest.raises(ValueError):
        publish_backup(tmp_path / 'invalid', lambda stream: stream.write(b'bad format'), validate=reject)
    with pytest.raises(ValueError, match='Empty'):
        publish_backup(tmp_path / 'empty', lambda stream: None)
    assert not list(tmp_path.glob('*/manifest.json'))


@pytest.mark.parametrize('stage', ['archive_fsync', 'archive_link', 'manifest_link'])
def test_publication_fault_before_marker_is_incomplete(tmp_path, monkeypatch, stage):
    import ownstack.backup_artifacts as artifacts
    real_link = artifacts.os.link
    if stage == 'archive_fsync':
        monkeypatch.setattr(artifacts.os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError(errno.ENOSPC, 'fsync')))
    else:
        def link(source, target):
            if Path(target).name == ('backup.dump' if stage == 'archive_link' else 'manifest.json'):
                raise OSError(errno.ENOSPC, 'link')
            real_link(source, target)
        monkeypatch.setattr(artifacts.os, 'link', link)
    directory = tmp_path / 'failed'
    with pytest.raises(OSError):
        publish_backup(directory, lambda stream: stream.write(b'complete bytes'))
    assert not (directory / 'manifest.json').exists()
    # An archive without its marker is never accepted, even when its bytes exist.
    with pytest.raises(FileNotFoundError):
        with verified_backup(directory, '0' * 64):
            pytest.fail('Incomplete generation was accepted')


def test_uncertain_post_marker_error_can_be_inspected_without_resending(tmp_path, monkeypatch):
    import ownstack.backup_artifacts as artifacts
    directory = tmp_path / 'uncertain'
    real = artifacts._sync_directory
    def sync(path):
        if (directory / 'manifest.json').exists():
            raise OSError(errno.EIO, 'post-marker sync uncertainty')
        real(path)
    monkeypatch.setattr(artifacts, '_sync_directory', sync)
    with pytest.raises(OSError):
        publish_backup(directory, lambda stream: stream.write(b'bytes'))
    raw = (directory / 'manifest.json').read_bytes()
    with verified_backup(directory, hashlib.sha256(raw).hexdigest()) as (stream, _):
        assert stream.read() == b'bytes'


@pytest.mark.parametrize('mutation', ['empty', 'truncate', 'flip', 'append', 'replace'])
def test_damaged_archive_rejected_before_restore(tmp_path, mutation):
    directory, receipt = generation(tmp_path)
    target = directory / 'backup.dump';raw = target.read_bytes()
    damaged = {'empty': b'', 'truncate': raw[:-1], 'flip': bytes([raw[0] ^ 1]) + raw[1:],
               'append': raw + b'extra', 'replace': b'x' * len(raw)}[mutation]
    target.write_bytes(damaged)
    with pytest.raises(ValueError, match='checksum or length'):
        with verified_backup(directory, receipt['manifest_sha256']):
            pytest.fail('Corrupt archive reached restore')


def test_manifest_and_archive_tamper_cannot_replace_pinned_receipt(tmp_path):
    directory, receipt = generation(tmp_path)
    raw = b'tampered';(directory / 'backup.dump').write_bytes(raw)
    marker = json.loads((directory / 'manifest.json').read_text())
    marker.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    (directory / 'manifest.json').write_text(json.dumps(marker))
    with pytest.raises(ValueError, match='trusted receipt'):
        with verified_backup(directory, receipt['manifest_sha256']):
            pytest.fail('Unpinned manifest accepted')


@pytest.mark.parametrize('value', ['', None, 'x' * 64, '0' * 63, 'A' * 64])
def test_pinned_receipt_required(tmp_path, value):
    with pytest.raises(ValueError, match='Pinned'):
        with verified_backup(tmp_path / 'absent', value):
            pytest.fail('No pinned receipt')


@pytest.mark.parametrize('component', ['directory', 'manifest.json', 'backup.dump'])
def test_symlink_rejected(tmp_path, component):
    directory, receipt = generation(tmp_path)
    if component == 'directory':
        link = tmp_path / 'link';link.symlink_to(directory, target_is_directory=True);directory = link
    else:
        target = directory / component;renamed = directory / ('original-' + component)
        target.rename(renamed);target.symlink_to(renamed)
    with pytest.raises(OSError):
        with verified_backup(directory, receipt['manifest_sha256']):
            pytest.fail('Symlink accepted')


@pytest.mark.parametrize('component', ['directory', 'manifest.json', 'backup.dump'])
def test_nonprivate_generation_rejected(tmp_path, component):
    directory, receipt = generation(tmp_path)
    target = directory if component == 'directory' else directory / component
    target.chmod(0o755 if component == 'directory' else 0o644)
    with pytest.raises(ValueError, match='private'):
        with verified_backup(directory, receipt['manifest_sha256']):
            pytest.fail('Nonprivate backup accepted')


def test_path_replacement_after_validation_does_not_switch_restore_bytes(tmp_path):
    directory, receipt = generation(tmp_path)
    with verified_backup(directory, receipt['manifest_sha256']) as (stream, _):
        (directory / 'backup.dump').rename(directory / 'original.dump')
        (directory / 'backup.dump').write_bytes(b'different path bytes')
        assert stream.read() == b'owned backup bytes'


def test_fifo_is_rejected_without_blocking(tmp_path):
    directory, receipt = generation(tmp_path)
    (directory / 'backup.dump').unlink();os.mkfifo(directory / 'backup.dump', 0o600)
    with pytest.raises(ValueError, match='regular'):
        with verified_backup(directory, receipt['manifest_sha256']):
            pytest.fail('FIFO accepted')


@pytest.mark.parametrize('change', [
    {'version': True}, {'version': 2}, {'archive': '../elsewhere'},
    {'bytes': True}, {'bytes': -1}, {'sha256': None},
])
def test_invalid_pinned_manifest_schema_rejected(tmp_path, change):
    directory, receipt = generation(tmp_path)
    path = directory / 'manifest.json';value = json.loads(path.read_text());value.update(change)
    raw = json.dumps(value).encode();path.write_bytes(raw)
    with pytest.raises(ValueError, match='Invalid backup manifest'):
        with verified_backup(directory, hashlib.sha256(raw).hexdigest()):
            pytest.fail('Malformed pinned manifest accepted')
