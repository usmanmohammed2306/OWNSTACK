"""Read-only diagnostic snapshots never replace authenticated host reads."""
from datetime import datetime, timedelta, timezone
from importlib import import_module
import pytest
from sqlalchemy import func, select
from conftest import login
from test_api import create_and_propose
from ownstack.models import (Attempt, Event, Evidence, HostObservation, InferenceBudget,
                             Proposal, User, Variation)

URL = "/v1/host/projects/atlas-project/access-review"


def approved_grant(client, factory):
    admin, _, proposal_id, proposal_hash = create_and_propose(client, factory)
    response = client.post(f"/v1/proposals/{proposal_id}/approve",
        headers={**admin, "Idempotency-Key": "review-grant"}, json={"proposal_hash": proposal_hash})
    assert response.status_code == 200, response.text
    return admin, response.json()["variation_id"]


def test_access_review_requires_sign_in_and_privileged_tenant_role(client):
    assert client.get(URL, params={"viewer_id": "atlas-contractor"}).status_code == 401
    for user in ("atlas-contractor", "platform-owner"):
        assert client.get(URL, params={"viewer_id": "atlas-contractor"},
                          headers=login(client, user)).status_code == 403


@pytest.mark.parametrize("actor", ["atlas-admin", "atlas-engineer"])
def test_review_is_read_only_and_returns_no_documents_or_inference(client, fixture_db, actor):
    headers = login(client, actor)
    models = (Attempt, Event, Evidence, HostObservation, Proposal, Variation)
    with fixture_db() as db:
        db.get(InferenceBudget, "global").reserved_calls = 10
        db.commit()
        before = [db.scalar(select(func.count()).select_from(model)) for model in models]
    for _ in range(2):
        response = client.get(URL, params={"viewer_id": "atlas-contractor"}, headers=headers)
        assert response.status_code == 200
        result = response.json()
        assert result["allowed"] is False and result["reason"] == "no_current_access"
        assert result["diagnostic_only"] is True and result["variation_id"] is None
        assert result["tenant_id"] == "atlas" and result["project_revision"] == 1
        assert datetime.fromisoformat(result["evaluated_at"]).tzinfo is not None
        assert "no-store" in response.headers["cache-control"]
        assert "atlas secret" not in response.text and "body" not in result
    with fixture_db() as db:
        assert before == [db.scalar(select(func.count()).select_from(model)) for model in models]
        assert db.get(InferenceBudget, "global").reserved_calls == 10


@pytest.mark.parametrize("project,viewer", [("nova-project", "atlas-contractor"),
    ("atlas-project", "nova-contractor"), ("missing", "atlas-contractor"),
    ("atlas-project", "missing")])
def test_foreign_and_missing_objects_are_indistinguishable(client, project, viewer):
    response = client.get(f"/v1/host/projects/{project}/access-review", params={"viewer_id": viewer},
                          headers=login(client, "atlas-admin"))
    assert response.status_code == 404 and response.json() == {"detail": "Not found"}


def test_role_access_is_not_misreported_as_a_grant(client):
    result = client.get(URL, params={"viewer_id": "atlas-engineer"},
                        headers=login(client, "atlas-admin")).json()
    assert result["allowed"] is True and result["reason"] == "role_access"
    assert result["basis"] == "role" and result["variation_id"] is None


def test_review_tracks_real_approval_and_revoke_but_cannot_authorize_reads(client, fixture_db):
    admin, grant = approved_grant(client, fixture_db)
    contractor = login(client, "atlas-contractor")
    snapshot = client.get(URL, params={"viewer_id": "atlas-contractor"}, headers=admin).json()
    assert snapshot["allowed"] is True and snapshot["reason"] == "active_grant"
    assert snapshot["variation_id"] == grant and snapshot["basis"] == "variation"
    assert client.get("/v1/host/projects/atlas-project/documents", headers=contractor).status_code == 200
    assert client.post(f"/v1/variations/{grant}/revoke",
                      headers={**admin, "Idempotency-Key": "review-revoke"}).status_code == 200
    assert client.get(URL, params={"viewer_id": "atlas-contractor"}, headers=admin).json()["allowed"] is False
    assert snapshot["allowed"] is True  # Old data cannot act as a permission token.
    assert client.get("/v1/host/projects/atlas-project/documents", headers=contractor).status_code == 403


@pytest.mark.parametrize("boundary", ["expired", "not_started", "disabled"])
def test_server_time_and_account_state_override_saved_grant(client, fixture_db, monkeypatch, boundary):
    admin, grant = approved_grant(client, fixture_db)
    at = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    with fixture_db() as db:
        variation = db.get(Variation, grant)
        variation.starts_at = at + timedelta(seconds=1) if boundary == "not_started" else at - timedelta(hours=1)
        variation.expires_at = at if boundary == "expired" else at + timedelta(hours=1)
        if boundary == "disabled": db.get(User, "atlas-contractor").enabled = False
        db.commit()
    monkeypatch.setattr(import_module("ownstack.api"), "utcnow", lambda: at)
    result = client.get(URL, params={"viewer_id": "atlas-contractor"}, headers=admin).json()
    assert result["allowed"] is False and result["variation_id"] is None
    assert result["reason"] == ("account_disabled" if boundary == "disabled" else "no_current_access")
    with fixture_db() as db:
        assert db.get(Variation, grant).state == "active"  # Diagnosis itself changes nothing.
