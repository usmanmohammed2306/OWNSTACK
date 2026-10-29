"""Offline SQLite recovery rehearsal. Private backups retain the inference ledger."""
import hashlib
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
from ownstack.backup_artifacts import publish_backup, verified_backup, _sync_directory
from ownstack.config import Settings
from ownstack.policy import digest


def fingerprint(connection):
    tables = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    state = {}
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        columns = [row[1] for row in connection.execute(f"PRAGMA table_info({quoted})")]
        rows = sorted(digest(list(row)) for row in connection.execute(f"SELECT * FROM {quoted}"))
        state[table] = {"columns": columns, "rows": rows}
    return digest(state), {table: len(value["rows"]) for table, value in state.items()}


def rehearse(source: Path, directory: Path, settings: Settings):
    if settings.ai_mode != "off" or settings.max_live_calls != 0:
        raise ValueError("Recovery requires AI off and cap zero")
    if source.is_symlink():
        raise ValueError("An explicit database file is required")
    source = source.resolve(strict=True)
    if not source.is_file():
        raise ValueError("An explicit database file is required")
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    directory.chmod(0o700)
    backup, restored = directory / "backup.sqlite3", directory / "restored.sqlite3"
    capture = directory / 'capture.sqlite3.part'
    capture.touch(mode=0o600, exist_ok=False)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original, closing(sqlite3.connect(capture)) as saved:
        original.backup(saved)
        if saved.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError('Captured SQLite backup failed integrity check')
        before, counts = fingerprint(saved)
        budget = saved.execute("SELECT reserved_calls FROM inference_budget WHERE id='global'").fetchone()
        if not budget:
            raise ValueError("Missing durable inference reservation ledger")
    def write(stream):
        with capture.open('rb') as snapshot:
            shutil.copyfileobj(snapshot, stream)
    receipt = publish_backup(directory / 'archive', write,
        metadata={'snapshot_sha256': before, 'table_counts': counts, 'reserved_calls': budget[0]})
    # Compatibility alias appears only after the archive's durable commit marker.
    os.link(directory / 'archive/backup.dump', backup)
    _sync_directory(directory)
    capture.unlink()
    partial = directory / 'restore.sqlite3.part'
    with verified_backup(directory / 'archive', receipt['manifest_sha256']) as (stream, _):
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as destination:
            shutil.copyfileobj(stream, destination)
            destination.flush()
            os.fsync(destination.fileno())
    with closing(sqlite3.connect(partial)) as target:
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError('Restored SQLite backup failed integrity check')
        if target.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError('Restored SQLite backup failed foreign key check')
        after, restored_counts = fingerprint(target)
        restored_budget = target.execute("SELECT reserved_calls FROM inference_budget WHERE id='global'").fetchone()[0]
        if before != after or counts != restored_counts or restored_budget != budget[0]:
            raise ValueError("Restore does not match the consistent backup")
        target.execute("CREATE TABLE recovery_probe (value TEXT NOT NULL)")
        target.execute("INSERT INTO recovery_probe VALUES ('restored-write')")
        target.commit()
    # Only a fully checked SQLite target gets its final pathname.
    with partial.open('rb') as completed:
        os.fsync(completed.fileno())
    os.link(partial, restored)
    _sync_directory(directory)
    partial.unlink()
    _sync_directory(directory)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        if original.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='recovery_probe'").fetchone()[0] != 0:
            raise ValueError('Unexpected recovery probe in original source')
    return {"database": "sqlite", "snapshot_sha256": before, "restored_sha256": after,
            "backup_file_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
            "backup_manifest_sha256": receipt['manifest_sha256'], "backup_generation": "archive",
            "tables": len(counts), "rows": sum(counts.values()), "reserved_calls": restored_budget,
            "integrity": "ok", "foreign_keys": "ok", "independent_target_write": True,
            "new_inference_calls": 0, "limit": "Local file recovery; not PostgreSQL or disaster recovery"}
