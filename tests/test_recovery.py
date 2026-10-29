from pathlib import Path
import sqlite3
import pytest
from ownstack.config import Settings
from ownstack.models import InferenceBudget
from ownstack.recovery import rehearse


def test_actual_file_backup_restore_preserves_exhausted_ledger(fixture_db, tmp_path):
    with fixture_db() as db:
        db.get(InferenceBudget, "global").reserved_calls = 10
        db.commit()
    source = Path(fixture_db.kw["bind"].url.database)
    report = rehearse(source, tmp_path / "private-rehearsal", Settings(ai_mode="off", max_live_calls=0))
    assert report["snapshot_sha256"] == report["restored_sha256"]
    assert report["reserved_calls"] == 10 and report["new_inference_calls"] == 0
    assert report["independent_target_write"]
    assert (tmp_path / "private-rehearsal" / "backup.sqlite3").stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(source) as db:
        assert db.execute("SELECT reserved_calls FROM inference_budget").fetchone()[0] == 10
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='recovery_probe'").fetchone()
    with pytest.raises(FileExistsError):
        rehearse(source, tmp_path / "private-rehearsal", Settings(ai_mode="off", max_live_calls=0))


@pytest.mark.parametrize("mode,cap", [("nebius", 0), ("fixture", 0), ("off", 1)])
def test_recovery_requires_offline_cap_zero(fixture_db, tmp_path, mode, cap):
    with pytest.raises(ValueError, match="AI off"):
        rehearse(Path(fixture_db.kw["bind"].url.database), tmp_path / "no-write", Settings(ai_mode=mode, max_live_calls=cap))
    assert not (tmp_path / "no-write").exists()


def test_interrupted_sqlite_capture_does_not_publish_final_names(fixture_db, tmp_path, monkeypatch):
    import ownstack.recovery as recovery
    source = Path(fixture_db.kw['bind'].url.database)
    before = source.read_bytes()
    def fail(directory, writer, **kwargs):
        raise OSError('Controlled interruption before publication')
    monkeypatch.setattr(recovery, 'publish_backup', fail)
    output = tmp_path / 'interrupted'
    with pytest.raises(OSError):
        rehearse(source, output, Settings(ai_mode='off', max_live_calls=0))
    assert not (output / 'backup.sqlite3').exists()
    assert not (output / 'restored.sqlite3').exists()
    assert (output / 'capture.sqlite3.part').exists()
    assert source.read_bytes() == before


def test_corrupt_sqlite_archive_is_refused_before_restored_target(fixture_db, tmp_path, monkeypatch):
    import ownstack.recovery as recovery
    source = Path(fixture_db.kw['bind'].url.database)
    before = source.read_bytes();real = recovery.publish_backup
    def damage(directory, *args, **kwargs):
        receipt = real(directory, *args, **kwargs)
        path = directory / 'backup.dump';data = path.read_bytes();path.write_bytes(data[:-1])
        return receipt
    monkeypatch.setattr(recovery, 'publish_backup', damage)
    output = tmp_path / 'corrupt'
    with pytest.raises(ValueError, match='checksum or length'):
        rehearse(source, output, Settings(ai_mode='off', max_live_calls=0))
    assert not (output / 'restored.sqlite3').exists()
    assert not (output / 'restore.sqlite3.part').exists()
    assert source.read_bytes() == before


def test_sqlite_foreign_key_damage_never_publishes_restored_target(tmp_path):
    source = tmp_path / 'invalid.sqlite3'
    with sqlite3.connect(source) as db:
        db.executescript("CREATE TABLE inference_budget(id TEXT PRIMARY KEY,reserved_calls INTEGER);"
            "INSERT INTO inference_budget VALUES('global',0);"
            "CREATE TABLE parent(id INTEGER PRIMARY KEY);"
            "CREATE TABLE child(id INTEGER REFERENCES parent(id));INSERT INTO child VALUES(12);")
    with pytest.raises(ValueError, match='foreign key'):
        rehearse(source, tmp_path / 'fk-invalid', Settings(ai_mode='off', max_live_calls=0))
    assert not (tmp_path / 'fk-invalid/restored.sqlite3').exists()


def test_malformed_sqlite_source_kept_and_not_published(tmp_path):
    source = tmp_path / 'invalid.sqlite3';source.write_bytes(b'not a SQLite database')
    with pytest.raises(sqlite3.DatabaseError):
        rehearse(source, tmp_path / 'bad-source', Settings(ai_mode='off', max_live_calls=0))
    assert source.read_bytes() == b'not a SQLite database'
    assert not (tmp_path / 'bad-source/backup.sqlite3').exists()
