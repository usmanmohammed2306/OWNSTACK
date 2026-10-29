import os
from pathlib import Path
import subprocess
import sys
from sqlalchemy import create_engine, inspect, text


def test_fresh_database_uses_recorded_migration(tmp_path):
    database = tmp_path / "fresh.db"
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "OWNSTACK_DATABASE_URL": f"sqlite:///{database}"}
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                            cwd=root, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    engine = create_engine(f"sqlite:///{database}")
    try:
        tables = set(inspect(engine).get_table_names())
        assert {"alembic_version", "attempts", "approvals", "variations", "evidence", "events", "outbox", "inference_budget", "web_sessions", "rate_windows", "host_observations", "repair_runs", "repair_attempts"} <= tables
        with engine.connect() as connection:
            from ownstack.api import SCHEMA_REVISION
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == SCHEMA_REVISION == "e28f10d3a603"
            assert {'customer_accounts','customer_identities','customer_submissions','customer_requirement_links'}<=tables
            assert {'organization_profiles','organization_changes','request_workspaces','request_guidance','engineering_comments'}<=tables
            assert {'release_requirements','release_checks','release_audit'}<=tables
            assert {'teams','team_memberships','team_audit'}<=tables
            assert {'planner_runs','planner_events','approval_witnesses'}<=tables
            assert "investigations" in tables
            assert connection.execute(text("SELECT reserved_calls FROM inference_budget WHERE id='global'")).scalar_one() == 0
    finally:
        engine.dispose()


def test_observation_upgrade_preserves_exhausted_budget(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "existing.db"
    env = {**os.environ, "OWNSTACK_DATABASE_URL": f"sqlite:///{database}"}
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "92ab71f0d614"],
                            cwd=root, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE inference_budget SET reserved_calls=10 WHERE id='global'"))
        result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                                cwd=root, env=env, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        with engine.connect() as connection:
            assert connection.execute(text("SELECT reserved_calls FROM inference_budget WHERE id='global'")).scalar_one() == 10
            assert connection.execute(text("SELECT COUNT(*) FROM host_observations")).scalar_one() == 0
        indexes = {index["name"]: index["column_names"] for index in inspect(engine).get_indexes("variations")}
        assert indexes["ix_variation_read_candidate"] == ["tenant_id", "project_id", "viewer_id", "state", "expires_at"]
        result = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "c62e84a910f3"],
                                cwd=root, env=env, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        assert "ix_variation_read_candidate" not in {index["name"] for index in inspect(engine).get_indexes("variations")}
        result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                                cwd=root, env=env, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        with engine.connect() as connection:
            assert connection.execute(text("SELECT reserved_calls FROM inference_budget WHERE id='global'")).scalar_one() == 10
    finally:
        engine.dispose()
