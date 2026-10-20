from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from conftest import login
from ownstack.ai import AIResult
from ownstack.models import Attempt, ChangeRequest, Document, EngineeringItem, Proposal, Variation
from ownstack.service import accept_result, claim_attempt, fail_attempt, reap_expired_attempts, start_attempt
from ownstack.runner import trusted_local_verification


def access_body():
    return {"text": "Give contractor read-only access to Project Atlas until Friday", "kind": "access",
            "project_id": "atlas-project", "viewer_id": "atlas-contractor",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()}


def create_and_propose(client, factory):
    admin = login(client, "atlas-admin")
    created = client.post("/v1/requests", headers={**admin, "Idempotency-Key": "req-1"}, json=access_body())
    assert created.status_code == 201, created.text
    request_id = created.json()["id"]
    queued = client.post(f"/v1/requests/{request_id}/interpret", headers=admin)
    assert queued.status_code == 202
    attempt_id = queued.json()["attempt_id"]
    with factory() as db:
        claim_attempt(db, attempt_id)
        accepted = accept_result(db, attempt_id, AIResult("configure", "Narrow grant", "fixture", 0, None, None))
        assert accepted
        db.commit()
        proposal = db.scalar(select(Proposal).where(Proposal.request_id == request_id))
        return admin, request_id, proposal.id, proposal.proposal_hash


def test_direct_host_isolation_and_revoke(client, fixture_db):
    admin, request_id, proposal_id, proposal_hash = create_and_propose(client, fixture_db)
    contractor = login(client, "atlas-contractor")
    nova = login(client, "nova-admin")
    assert client.get("/v1/requests", headers=contractor).status_code == 403
    assert client.get("/v1/host/projects/atlas-project/documents/atlas-doc", headers=contractor).status_code == 403
    assert client.get("/v1/host/projects/atlas-project/documents/atlas-doc", headers=nova).status_code == 404
    preview = client.post(f"/v1/proposals/{proposal_id}/preview", headers=admin)
    assert preview.status_code == 200 and preview.json()["matches_saved_proposal"]
    assert preview.json()["before"] is False and preview.json()["after"] is True
    assert preview.json()["counterfactual"] == {"checks": 24, "intended_delta_observed": True, "unexpected_delta_count": 0}
    approved = client.post(f"/v1/proposals/{proposal_id}/approve", headers={**admin, "Idempotency-Key": "approval-1"},
                           json={"proposal_hash": proposal_hash})
    assert approved.status_code == 200, approved.text
    repeated = client.post(f"/v1/proposals/{proposal_id}/approve", headers={**admin, "Idempotency-Key": "approval-1"},
                           json={"proposal_hash": proposal_hash})
    assert repeated.json() == approved.json()
    assert client.get("/v1/host/projects/atlas-project/documents/atlas-doc", headers=contractor).status_code == 200
    assert client.get("/v1/host/projects/nova-project/documents/nova-doc", headers=contractor).status_code == 404
    variation_id = approved.json()["variation_id"]
    revoked = client.post(f"/v1/variations/{variation_id}/revoke", headers={**admin, "Idempotency-Key": "revoke-1"})
    assert revoked.status_code == 200
    assert client.get("/v1/host/projects/atlas-project/documents/atlas-doc", headers=contractor).status_code == 403
    assert client.get(f"/v1/events?request_id={request_id}", headers=nova).status_code == 404


def test_preview_fencing_and_idempotency_conflict(client, fixture_db):
    admin, _request_id, proposal_id, proposal_hash = create_and_propose(client, fixture_db)
    with fixture_db() as db:
        doc = db.get(Document, "atlas-doc")
        doc.body = "Changed after preview"
        db.commit()
    response = client.post(f"/v1/proposals/{proposal_id}/approve", headers={**admin, "Idempotency-Key": "approval-stale"},
                           json={"proposal_hash": proposal_hash})
    assert response.status_code == 409
    changed = access_body()
    changed["text"] = "Changed request"
    response = client.post("/v1/requests", headers={**admin, "Idempotency-Key": "req-1"}, json=changed)
    assert response.status_code == 409


def test_pdf_request_cannot_be_disguised_as_access_contract(client, fixture_db):
    admin = login(client, "atlas-admin")
    body = access_body()
    body["text"] = "Give contractor read-only access to Project Atlas and add PDF export"
    request_id = client.post("/v1/requests", headers={**admin, "Idempotency-Key": "disguised-pdf"}, json=body).json()["id"]
    with fixture_db() as db:
        req = db.get(ChangeRequest, request_id)
        attempt = start_attempt(db, req, "fixture", 10)
        db.commit()
        attempt_id = attempt.id
    with fixture_db() as db:
        claim_attempt(db, attempt_id)
        assert accept_result(db, attempt_id, AIResult("configure", "Looks configurable", "fixture", 0, None, None))
        db.commit()
        req = db.get(ChangeRequest, request_id)
        proposal = db.get(Proposal, req.accepted_proposal_id)
        assert proposal.route == "refuse"
        assert req.status == "refused"
    assert client.get("/v1/variations", headers=admin).json() == []


def test_duplicate_active_grant_does_not_create_second_variation(client, fixture_db):
    admin, _, proposal_id, proposal_hash = create_and_propose(client, fixture_db)
    approved = client.post(f"/v1/proposals/{proposal_id}/approve",
                           headers={**admin, "Idempotency-Key": "first-grant-approval"},
                           json={"proposal_hash": proposal_hash})
    assert approved.status_code == 200
    second = client.post("/v1/requests", headers={**admin, "Idempotency-Key": "second-grant-request"}, json=access_body())
    request_id = second.json()["id"]
    with fixture_db() as db:
        request = db.get(ChangeRequest, request_id)
        attempt = start_attempt(db, request, "fixture", 10)
        db.commit()
        attempt_id = attempt.id
    with fixture_db() as db:
        claim_attempt(db, attempt_id)
        assert accept_result(db, attempt_id, AIResult("configure", "Looks valid", "fixture", 0, None, None))
        db.commit()
        request = db.get(ChangeRequest, request_id)
        assert db.get(Proposal, request.accepted_proposal_id).route == "refuse"
    assert len(client.get("/v1/variations", headers=admin).json()) == 1


def test_timeout_retry_discards_late_result(client, fixture_db):
    admin = login(client, "atlas-admin")
    request_id = client.post("/v1/requests", headers={**admin, "Idempotency-Key": "timeout-request"}, json=access_body()).json()["id"]
    with fixture_db() as db:
        req = db.get(ChangeRequest, request_id)
        first = start_attempt(db, req, "fixture", 10)
        db.commit()
        first_id = first.id
    with fixture_db() as db:
        claim_attempt(db, first_id)
        db.get(Attempt, first_id).deadline_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    with fixture_db() as db:
        req = db.get(ChangeRequest, request_id)
        second = start_attempt(db, req, "fixture", 10)
        db.commit()
        second_id = second.id
    with fixture_db() as db:
        claim_attempt(db, second_id)
        assert accept_result(db, second_id, AIResult("configure", "Second accepted", "fixture", 0, None, None))
        db.commit()
    with fixture_db() as db:
        assert not accept_result(db, first_id, AIResult("refuse", "Late", "fixture", 0, None, None))
        db.commit()
        req = db.get(ChangeRequest, request_id)
        proposal = db.get(Proposal, req.accepted_proposal_id)
        assert proposal.reason == "Second accepted"
        assert db.get(Attempt, first_id).state == "superseded"


def test_redelivered_accepted_result_preserves_terminal_history(client, fixture_db):
    _, request_id, proposal_id, _ = create_and_propose(client, fixture_db)
    with fixture_db() as db:
        request = db.get(ChangeRequest, request_id)
        attempt_id = request.current_attempt_id
        assert not accept_result(db, attempt_id, AIResult("refuse", "Redelivery", "fixture", 0, None, None))
        db.commit()
    with fixture_db() as db:
        assert db.get(Attempt, attempt_id).state == "accepted"
        assert db.get(ChangeRequest, request_id).accepted_proposal_id == proposal_id
        assert len(db.scalars(select(Proposal).where(Proposal.request_id == request_id)).all()) == 1


def test_worker_reaps_expired_attempt_without_claiming_remote_cancel(client, fixture_db):
    admin = login(client, "atlas-admin")
    request_id = client.post("/v1/requests", headers={**admin, "Idempotency-Key": "reap-request"}, json=access_body()).json()["id"]
    with fixture_db() as db:
        req = db.get(ChangeRequest, request_id)
        attempt = start_attempt(db, req, "fixture", 10)
        db.commit()
        attempt_id = attempt.id
    with fixture_db() as db:
        claim_attempt(db, attempt_id)
        db.get(Attempt, attempt_id).deadline_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    with fixture_db() as db:
        assert reap_expired_attempts(db) == 1
        fail_attempt(db, attempt_id, "MODEL_ERROR")
        db.commit()
    with fixture_db() as db:
        assert db.get(Attempt, attempt_id).state == "timed_out"
        assert db.get(ChangeRequest, request_id).status == "failed"
    events = client.get(f"/v1/events?request_id={request_id}", headers=admin).json()
    timeout_events = [event for event in events if event["type"] == "attempt.timed_out"]
    assert len(timeout_events) == 1
    assert timeout_events[0]["payload"]["remote_cancellation_verified"] is False


def test_host_enforces_expiry_without_worker(client, fixture_db):
    admin, _, proposal_id, proposal_hash = create_and_propose(client, fixture_db)
    approved = client.post(f"/v1/proposals/{proposal_id}/approve", headers={**admin, "Idempotency-Key": "expiry-approve"},
                           json={"proposal_hash": proposal_hash})
    assert approved.status_code == 200
    with fixture_db() as db:
        variation = db.get(Variation, approved.json()["variation_id"])
        variation.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    contractor = login(client, "atlas-contractor")
    assert client.get("/v1/host/projects/atlas-project/documents/atlas-doc", headers=contractor).status_code == 403


def test_engineering_patch_requires_independent_checks_and_human_decision(client, fixture_db, monkeypatch):
    engineer = login(client, "atlas-engineer")
    created = client.post("/v1/requests", headers={**engineer, "Idempotency-Key": "pdf-request"},
                          json={"text": "Add PDF export for Project Atlas", "kind": "feature", "project_id": "atlas-project"})
    assert created.status_code == 201
    request_id = created.json()["id"]
    queued = client.post(f"/v1/requests/{request_id}/interpret", headers=engineer)
    attempt_id = queued.json()["attempt_id"]
    with fixture_db() as db:
        claim_attempt(db, attempt_id)
        assert accept_result(db, attempt_id, AIResult("engineering", "New code required", "fixture", 0, None, None))
        db.commit()
        item = db.scalar(select(EngineeringItem).where(EngineeringItem.request_id == request_id))
        item_id = item.id
    drafted = client.post(f"/v1/engineering/{item_id}/draft", headers=engineer)
    assert drafted.status_code == 200, drafted.text
    wrong = client.post(f"/v1/engineering/{item_id}/decide", headers=engineer,
                        json={"decision": "accept_for_manual_release", "patch_hash": drafted.json()["patch_hash"]})
    assert wrong.status_code == 409
    monkeypatch.setattr("ownstack.api.run_verifier", trusted_local_verification)
    verified = client.post(f"/v1/engineering/{item_id}/verify", headers=engineer)
    assert verified.status_code == 200 and verified.json()["passed"]
    decided = client.post(f"/v1/engineering/{item_id}/decide", headers=engineer,
                          json={"decision": "accept_for_manual_release", "patch_hash": drafted.json()["patch_hash"]})
    assert decided.status_code == 200 and decided.json()["release_state"] == "not_deployed"


def test_convergence_cross_tenant_count_is_product_owner_only(client, fixture_db):
    for user, project in [("atlas-admin", "atlas-project"), ("nova-admin", "nova-project")]:
        token = login(client, user)
        response = client.post("/v1/requests", headers={**token, "Idempotency-Key": f"pdf-{user}"},
                               json={"text": "Please add PDF export", "kind": "feature", "project_id": project})
        assert response.status_code == 201
        data = client.get("/v1/convergence", headers=token).json()[0]
        assert data["affected_tenant_count"] is None
        assert client.post("/v1/convergence/pdf-export/decide", headers=token,
                           json={"decision": "promote", "rationale": "Enough repeated requests to consider."}).status_code == 403
    owner = login(client, "platform-owner")
    data = client.get("/v1/convergence", headers=owner).json()[0]
    assert data["affected_tenant_count"] == 2
    decision = client.post("/v1/convergence/pdf-export/decide", headers=owner,
                           json={"decision": "keep_separate", "rationale": "Wait for measured user outcomes."})
    assert decision.status_code == 200 and decision.json()["effect"] == "record_only"
