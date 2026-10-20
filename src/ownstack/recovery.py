"""Offline SQLite recovery rehearsal. Private backups retain the inference ledger."""
import hashlib
from pathlib import Path
import sqlite3
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
    for path in (backup, restored):
        path.touch(mode=0o600, exist_ok=False)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original, sqlite3.connect(backup) as saved:
        original.backup(saved)
        assert saved.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        before, counts = fingerprint(saved)
        budget = saved.execute("SELECT reserved_calls FROM inference_budget WHERE id='global'").fetchone()
        if not budget:
            raise ValueError("Missing durable inference reservation ledger")
    with sqlite3.connect(backup) as saved, sqlite3.connect(restored) as target:
        saved.backup(target)
        assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert target.execute("PRAGMA foreign_key_check").fetchall() == []
        after, restored_counts = fingerprint(target)
        restored_budget = target.execute("SELECT reserved_calls FROM inference_budget WHERE id='global'").fetchone()[0]
        if before != after or counts != restored_counts or restored_budget != budget[0]:
            raise ValueError("Restore does not match the consistent backup")
        target.execute("CREATE TABLE recovery_probe (value TEXT NOT NULL)")
        target.execute("INSERT INTO recovery_probe VALUES ('restored-write')")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        assert original.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='recovery_probe'").fetchone()[0] == 0
    return {"database": "sqlite", "snapshot_sha256": before, "restored_sha256": after,
            "backup_file_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
            "tables": len(counts), "rows": sum(counts.values()), "reserved_calls": restored_budget,
            "integrity": "ok", "foreign_keys": "ok", "independent_target_write": True,
            "new_inference_calls": 0, "limit": "Local file recovery; not PostgreSQL or disaster recovery"}
