from datetime import timedelta
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError
from conftest import login
from test_api import create_and_propose
from ownstack.models import HostObservation, Variation
from ownstack.service import utcnow


def approve(client, admin, proposal_id, proposal_hash):
    response = client.post(f"/v1/proposals/{proposal_id}/approve",
                           headers={**admin, "Idempotency-Key": "observe-approval"},
                           json={"proposal_hash": proposal_hash})
    assert response.status_code == 200, response.text
    return response.json()["variation_id"]


def test_preview_is_not_usage_and_only_granted_host_reads_count(client, fixture_db):
    admin, _, proposal_id, proposal_hash = create_and_propose(client, fixture_db)
    for _ in range(2):
        assert client.post(f"/v1/proposals/{proposal_id}/preview", headers=admin).status_code == 200
    variation_id = approve(client, admin, proposal_id, proposal_hash)
    with fixture_db() as db:
        assert db.scalar(select(func.count(HostObservation.id))) == 0
    contractor = login(client, "atlas-contractor")
    assert client.get("/v1/host/projects/atlas-project/documents", headers=contractor).status_code == 200
    assert client.get("/v1/host/projects/atlas-project/documents/atlas-doc", headers=contractor).status_code == 200
    assert client.get("/v1/host/projects/atlas-project/documents", headers=admin).status_code == 200
    rows = client.get("/v1/host-observations", headers=admin).json()
    assert len(rows) == 3
    assert sum(row["basis"] == "variation" and row["variation_id"] == variation_id for row in rows) == 2
    assert "atlas secret" not in str(rows)
    signal = client.get("/v1/convergence", headers=admin).json()[1]
    assert signal["observed_granted_reads"] == 2 and signal["usage_scope"] == "your_teams"
    assert signal["affected_tenant_count"] is None


def test_denied_expired_revoked_and_cross_tenant_reads_never_count_as_usage(client, fixture_db):
    admin, _, proposal_id, proposal_hash = create_and_propose(client, fixture_db)
    contractor, nova = login(client, "atlas-contractor"), login(client, "nova-admin")
    url = "/v1/host/projects/atlas-project/documents/atlas-doc"
    assert client.get(url, headers=contractor).status_code == 403
    variation_id = approve(client, admin, proposal_id, proposal_hash)
    with fixture_db() as db:
        db.get(Variation, variation_id).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get(url, headers=contractor).status_code == 403
    assert client.post(f"/v1/variations/{variation_id}/revoke",
                       headers={**admin, "Idempotency-Key": "observed-revoke"}).status_code == 200
    assert client.get(url, headers=contractor).status_code == 403
    assert client.get(url, headers=nova).status_code == 404
    assert client.get("/v1/host-observations", headers=nova).json() == []
    assert client.get(f"/v1/host-observations?variation_id={variation_id}", headers=nova).status_code == 404
    assert client.get("/v1/host-observations", headers=contractor).status_code == 403
    rows = client.get("/v1/host-observations", headers=admin).json()
    assert len(rows) == 3 and all(not row["allowed"] and row["variation_id"] is None for row in rows)
    signal = client.get("/v1/convergence", headers=admin).json()[1]
    assert signal["observed_granted_reads"] == 0


def test_usage_aggregation_and_decision_are_owner_scoped_not_auto_promotion(client, fixture_db):
    admin, _, proposal_id, proposal_hash = create_and_propose(client, fixture_db)
    approve(client, admin, proposal_id, proposal_hash)
    contractor = login(client, "atlas-contractor")
    client.get("/v1/host/projects/atlas-project/documents", headers=contractor)
    nova = login(client, "nova-admin")
    assert client.get("/v1/convergence", headers=nova).json()[1]["observed_granted_reads"] == 0
    assert client.post("/v1/convergence/temporary-project-view/decide", headers=admin,
                       json={"decision": "promote", "rationale": "A tenant must not promote shared behavior."}).status_code == 403
    owner = login(client, "platform-owner")
    signals = client.get("/v1/convergence", headers=owner).json()
    assert signals[1]["observed_granted_reads"] == 1
    assert signals[1]["affected_tenant_count"] == 1 and signals[1]["usage_scope"] == "all_tenants"
    assert "atlas-contractor" not in str(signals) and "atlas-project" not in str(signals)
    assert client.get("/v1/host-observations", headers=owner).status_code == 403
    result = client.post("/v1/convergence/temporary-project-view/decide", headers=owner,
                         json={"decision": "keep_separate", "rationale": "One synthetic use does not validate a shared feature."})
    assert result.status_code == 200 and result.json()["effect"] == "record_only"
    assert client.get("/v1/convergence", headers=owner).json()[1]["decision"] == "keep_separate"
    assert client.post("/v1/convergence/unknown/decide", headers=owner,
                       json={"decision": "promote", "rationale": "Unknown needs cannot be promoted."}).status_code == 404
    assert len(client.get("/v1/variations", headers=admin).json()) == 1


def test_host_fails_closed_when_observation_cannot_be_saved(client, fixture_db):
    admin = login(client, "atlas-admin")

    def reject_observation(db, *_):
        if any(isinstance(row, HostObservation) for row in db.new):
            raise SQLAlchemyError("Synthetic evidence storage outage")

    event.listen(fixture_db.class_, "before_flush", reject_observation)
    try:
        result = client.get("/v1/host/projects/atlas-project/documents/atlas-doc", headers=admin)
        assert result.status_code == 500
        assert "atlas secret" not in result.text and "Synthetic evidence" not in result.text
    finally:
        event.remove(fixture_db.class_, "before_flush", reject_observation)
    assert client.get("/v1/host-observations", headers=admin).json() == []
