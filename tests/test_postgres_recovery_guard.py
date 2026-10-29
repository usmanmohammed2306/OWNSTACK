import importlib.util
from pathlib import Path
import pytest
from ownstack.config import Settings

spec = importlib.util.spec_from_file_location("pg_recovery", Path(__file__).resolve().parents[1] / "scripts/rehearse_postgres_backup.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("url,mode,cap", [
    ("sqlite:///x.db", "off", 0), ("postgresql+psycopg://a:b@remote.example/db", "off", 0),
    ("postgresql+psycopg://a:b@localhost/db", "nebius", 0),
    ("postgresql+psycopg://a:b@localhost/db", "off", 1),
    ("postgresql+psycopg://a:b@localhost/db?options=x", "off", 0),
])
def test_refuse_remote_or_provider_enabled_restore(url, mode, cap):
    with pytest.raises(ValueError):
        module.local_connection(Settings(database_url=url, ai_mode=mode, max_live_calls=cap))


def test_local_restore_connection_and_missing_tools_do_not_create_artifacts(tmp_path, monkeypatch):
    settings = Settings(database_url="postgresql+psycopg://ownstack:ownstack@localhost/ownstack", ai_mode="off", max_live_calls=0)
    assert module.local_connection(settings)["host"] == "localhost"
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError):
        module.rehearse(settings, tmp_path / "blocked")
    assert not (tmp_path / "blocked").exists()
