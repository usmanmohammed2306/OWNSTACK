"""Reviewed rollback is a fenced prediction, not a grant or observed read."""
from datetime import timedelta
from importlib import import_module
import pytest
from sqlalchemy import func, select
from conftest import login
from test_access_review import approved_grant
from ownstack.models import (Attempt, Event, HostObservation, Idempotency, InferenceBudget,
                             Outbox, Project, Proposal, User, Variation)
from ownstack.policy import aware
from ownstack.service import utcnow


def preview(client, admin, grant):
    response = client.get(f"/v1/variations/{grant}/revoke-preview", headers=admin)
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, admin, grant, snapshot, key="reviewed-revoke"):
    return client.post(f"/v1/variations/{grant}/revoke", headers={**admin, "Idempotency-Key": key},
                       json={"preview_hash": snapshot["preview_hash"]})


def another_grant(db, original):
    """Explicit synthetic overlap; normal approval rejects redundant grants."""
    proposal = db.get(Proposal, original.proposal_id)
    attempt = db.get(Attempt, proposal.attempt_id)
    attributes = {c.name: getattr(attempt, c.name) for c in Attempt.__table__.columns}
    db.add(Attempt(**{**attributes, "id": "overlap-attempt", "number": 99}))
    db.flush()
    attributes = {c.name: getattr(proposal, c.name) for c in Proposal.__table__.columns}
    db.add(Proposal(**{**attributes, "id": "overlap-proposal", "attempt_id": "overlap-attempt"}))
    db.flush()
    db.add(Variation(id="overlap-grant", tenant_id=original.tenant_id, project_id=original.project_id,
        viewer_id=original.viewer_id, proposal_id="overlap-proposal", state="active",
        starts_at=original.starts_at, expires_at=original.expires_at))


def test_preview_is_authenticated_admin_only_and_tenant_scoped(client, fixture_db):
    admin, grant = approved_grant(client, fixture_db)
    for actor, code in [("atlas-engineer", 403), ("atlas-contractor", 403), ("nova-admin", 404)]:
        assert client.get(f"/v1/variations/{grant}/revoke-preview", headers=login(client, actor)).status_code == code
    assert client.get("/v1/variations/missing/revoke-preview", headers=admin).status_code == 404


def test_preview_makes_no_reads_or_mutations_and_time_alone_is_not_a_fence(client, fixture_db, monkeypatch):
    admin, grant = approved_grant(client, fixture_db)
    with fixture_db() as db:
        db.get(InferenceBudget, "global").reserved_calls = 10
        db.commit()
        models = (Event, Outbox, HostObservation, Idempotency)
        before = [db.scalar(select(func.count()).select_from(m)) for m in models]
    at = utcnow()
    monkeypatch.setattr(import_module("ownstack.api"), "utcnow", lambda: at)
    first = preview(client, admin, grant)
    monkeypatch.setattr(import_module("ownstack.api"), "utcnow", lambda: at + timedelta(seconds=1))
    second = preview(client, admin, grant)
    assert first["preview_hash"] == second["preview_hash"]
    assert first["evaluated_at"] != second["evaluated_at"]
    assert first["before"]["allowed"] and not first["after"]["allowed"]
    assert first["can_revoke"] and first["viewer_id"] == "atlas-contractor"
    with fixture_db() as db:
        assert before == [db.scalar(select(func.count()).select_from(m)) for m in models]
        assert db.get(InferenceBudget, "global").reserved_calls == 10


def test_exact_reviewed_revoke_is_idempotent_audited_and_enforced(client, fixture_db):
    admin, grant = approved_grant(client, fixture_db)
    snapshot = preview(client, admin, grant)
    result = confirm(client, admin, grant, snapshot)
    assert result.status_code == 200 and result.json()["state"] == "revoked"
    assert confirm(client, admin, grant, snapshot).json() == result.json()
    altered = {**snapshot, "preview_hash": "0" * 64}
    assert confirm(client, admin, grant, altered).status_code == 409
    with fixture_db() as db:
        events = db.scalars(select(Event).where(Event.event_type == "variation.revoked")).all()
        assert len(events) == 1 and events[0].payload["reviewed_preview_hash"] == snapshot["preview_hash"]
        assert db.scalar(select(func.count()).select_from(Outbox).where(Outbox.event_id == events[0].id)) == 1
    contractor = login(client, "atlas-contractor")
    assert client.get("/v1/host/projects/atlas-project/documents", headers=contractor).status_code == 403


@pytest.mark.parametrize("change", ["project", "expiry", "disabled", "role", "revision", "overlap", "time_boundary"])
def test_changed_snapshot_rejects_without_revocation(client, fixture_db, monkeypatch, change):
    admin, grant = approved_grant(client, fixture_db)
    snapshot = preview(client, admin, grant)
    with fixture_db() as db:
        variation = db.get(Variation, grant)
        if change == "project": db.get(Project, "atlas-project").revision += 1
        elif change == "expiry": variation.expires_at += timedelta(minutes=1)
        elif change == "disabled": db.get(User, variation.viewer_id).enabled = False
        elif change == "role": db.get(User, variation.viewer_id).role = "member"
        elif change == "revision": variation.revision += 1
        elif change == "overlap": another_grant(db, variation)
        elif change == "time_boundary":
            at = aware(variation.expires_at)
            monkeypatch.setattr(import_module("ownstack.api"), "utcnow", lambda: at)
        db.commit()
    response = confirm(client, admin, grant, snapshot)
    assert response.status_code == 409, response.text
    with fixture_db() as db:
        assert db.get(Variation, grant).state == "active"
        assert db.scalar(select(func.count()).select_from(Event).where(Event.event_type == "variation.revoked")) == 0


def test_overlap_preview_does_not_promise_complete_offboarding(client, fixture_db):
    admin, grant = approved_grant(client, fixture_db)
    with fixture_db() as db:
        another_grant(db, db.get(Variation, grant))
        db.commit()
    snapshot = preview(client, admin, grant)
    assert snapshot["before"]["allowed"] and snapshot["after"]["allowed"]
    assert confirm(client, admin, grant, snapshot).status_code == 200
    contractor = login(client, "atlas-contractor")
    assert client.get("/v1/host/projects/atlas-project/documents", headers=contractor).status_code == 200
    assert client.get("/v1/host/projects/nova-project/documents", headers=contractor).status_code == 404
    with fixture_db() as db:
        assert db.get(Variation, "overlap-grant").state == "active"


def test_wrong_hash_or_foreign_scope_cannot_revoke(client, fixture_db):
    admin, grant = approved_grant(client, fixture_db)
    snapshot = preview(client, admin, grant)
    assert confirm(client, admin, grant, {"preview_hash": "0" * 64}).status_code == 409
    assert confirm(client, login(client, "nova-admin"), grant, snapshot).status_code == 404
    assert confirm(client, login(client, "atlas-engineer"), grant, snapshot).status_code == 403
    with fixture_db() as db: assert db.get(Variation, grant).state == "active"


def test_role_access_survives_revoking_a_grant(client, fixture_db):
    admin, grant = approved_grant(client, fixture_db)
    with fixture_db() as db:
        db.get(User, "atlas-contractor").role = "member"
        db.commit()
    snapshot = preview(client, admin, grant)
    assert snapshot["after"] == {"allowed": True, "basis": "role", "variation_id": None}
    assert confirm(client, admin, grant, snapshot).status_code == 200
    assert client.get("/v1/host/projects/atlas-project/documents",
                      headers=login(client, "atlas-contractor")).status_code == 200


def test_audit_failure_rolls_back_reviewed_revoke(client, fixture_db, monkeypatch):
    from fastapi.testclient import TestClient
    module = import_module("ownstack.api")
    admin, grant = approved_grant(client, fixture_db)
    snapshot = preview(client, admin, grant)
    def fail(*_args, **_kwargs): raise RuntimeError("synthetic-audit-failure")
    monkeypatch.setattr(module, "record", fail)
    with TestClient(module.app, raise_server_exceptions=False) as checked:
        assert confirm(checked, admin, grant, snapshot).status_code == 500
    with fixture_db() as db:
        assert db.get(Variation, grant).state == "active"
        assert db.scalar(select(func.count()).select_from(Idempotency).where(Idempotency.operation == "revoke")) == 0
