from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
import pytest
from ownstack.config import Settings
from ownstack.models import ChangeRequest, InferenceBudget
from ownstack.service import start_attempt


def test_repeated_generation_reuses_attempt_without_spending_another_slot(fixture_db):
    settings = Settings(ai_mode="nebius", nebius_key="synthetic-test-key",
                        nebius_model="nvidia/Nemotron-synthetic-test", max_live_calls=1)
    with fixture_db() as db:
        db.add_all([
            ChangeRequest(id="r1", tenant_id="atlas", requester_id="atlas-admin", text="read-only access Project Atlas",
                          kind="access", project_id="atlas-project", viewer_id="atlas-contractor",
                          expires_at=datetime.now(timezone.utc) + timedelta(days=1), status="new", revision=1),
            ChangeRequest(id="r2", tenant_id="atlas", requester_id="atlas-admin", text="read-only access Project Atlas",
                          kind="access", project_id="atlas-project", viewer_id="atlas-contractor",
                          expires_at=datetime.now(timezone.utc) + timedelta(days=1), status="new", revision=1),
        ])
        db.commit()
    with fixture_db() as db:
        request = db.get(ChangeRequest, "r1")
        first = start_attempt(db, request, settings.nebius_model, 20, settings)
        assert start_attempt(db, request, settings.nebius_model, 20, settings).id == first.id
        db.commit()
    with fixture_db() as db:
        assert db.get(InferenceBudget, "global").reserved_calls == 1
        with pytest.raises(HTTPException) as error:
            start_attempt(db, db.get(ChangeRequest, "r2"), settings.nebius_model, 20, settings)
        assert error.value.status_code == 429
        db.rollback()
        assert db.get(InferenceBudget, "global").reserved_calls == 1


def test_production_configuration_refuses_fixture_and_default_password(monkeypatch):
    monkeypatch.setenv("OWNSTACK_ENV", "production")
    base = dict(database_url="postgresql+psycopg://user:pass@localhost/db", signing_secret="s" * 40,
                ai_mode="nebius", nebius_key="test-key", nebius_model="nvidia/Nemotron-test",
                max_live_calls=10, public_origin="https://ownstack.example", require_background=True,
                trusted_proxy_ips='127.0.0.1')
    with pytest.raises(ValueError, match="demo password"):
        Settings(**base).validate()
    Settings(**base, demo_password="different-demo-password-123").validate()


def test_budget_status_is_visible_to_admin_not_contractor(client):
    from conftest import login
    admin = login(client, "atlas-admin")
    contractor = login(client, "atlas-contractor")
    status = client.get("/v1/inference-budget", headers=admin)
    assert status.status_code == 200
    assert status.json()["reserved_calls"] == 0
    assert status.json()["mode"] == "fixture"
    assert client.get("/v1/inference-budget", headers=contractor).status_code == 403
