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
