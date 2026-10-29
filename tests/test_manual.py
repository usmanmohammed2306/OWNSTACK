from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from conftest import login
from ownstack.models import ChangeRequest, EngineeringItem, Evidence, InferenceBudget, Proposal
from ownstack.patch_agent import fixture_patch
from ownstack.runner import patch_hash, trusted_local_verification
from ownstack.service import claim_attempt, fail_attempt, start_attempt


def access_body():
    return {"text": "Give atlas-contractor read-only access to Project Atlas until Friday",
            "kind": "access", "project_id": "atlas-project", "viewer_id": "atlas-contractor",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()}


def test_engineer_can_restore_access_journey_without_ai(client, fixture_db):
    admin = login(client, "atlas-admin")
    engineer = login(client, "atlas-engineer")
    contractor = login(client, "atlas-contractor")
    created = client.post("/v1/requests", headers={**admin, "Idempotency-Key": "manual-access-request"},
                          json=access_body())
    request_id = created.json()["id"]
    with fixture_db() as db:
        request = db.get(ChangeRequest, request_id)
        attempt = start_attempt(db, request, "synthetic-failure", 20)
        db.commit()
        attempt_id = attempt.id
    with fixture_db() as db:
        claim_attempt(db, attempt_id)
        fail_attempt(db, attempt_id, "MODEL_ERROR")
        db.commit()
    handoff = client.post(f"/v1/requests/{request_id}/manual-handoff",
                          headers={**engineer, "Idempotency-Key": "manual-access-handoff"})
    assert handoff.status_code == 200, handoff.text
    assert handoff.json()["ai_call"] is False
    duplicate = client.post(f"/v1/requests/{request_id}/manual-handoff",
                            headers={**engineer, "Idempotency-Key": "manual-access-handoff"})
    assert duplicate.json() == handoff.json()
    proposal_id = handoff.json()["proposal_id"]
    proposal = client.get(f"/v1/proposals/{proposal_id}", headers=admin).json()
    assert proposal["route"] == "configure"
    preview = client.post(f"/v1/proposals/{proposal_id}/preview", headers=admin)
    assert preview.status_code == 200 and preview.json()["matches_saved_proposal"]
    approved = client.post(f"/v1/proposals/{proposal_id}/approve",
                           headers={**admin, "Idempotency-Key": "manual-access-approve"},
                           json={"proposal_hash": proposal["proposal_hash"]})
    assert approved.status_code == 200
    assert client.get("/v1/host/projects/atlas-project/documents/atlas-doc", headers=contractor).status_code == 200
    with fixture_db() as db:
        assert db.get(InferenceBudget, "global").reserved_calls == 0


def test_feature_can_be_patched_and_checked_without_ai(client, fixture_db, monkeypatch):
    engineer = login(client, "atlas-engineer")
    created = client.post("/v1/requests", headers={**engineer, "Idempotency-Key": "manual-feature-request"},
                          json={"text": "Add PDF export for Project Atlas", "kind": "feature",
                                "project_id": "atlas-project"})
    request_id = created.json()["id"]
    handoff = client.post(f"/v1/requests/{request_id}/manual-handoff",
                          headers={**engineer, "Idempotency-Key": "manual-feature-handoff"})
    assert handoff.status_code == 200 and handoff.json()["status"] == "engineering"
    with fixture_db() as db:
        item = db.scalar(select(EngineeringItem).where(EngineeringItem.request_id == request_id))
        item_id = item.id
    source = client.get("/v1/engineering-source", headers=engineer)
    assert source.status_code == 200 and source.json()["path"] == "sample_app/report.py"
    bad_patch = fixture_patch()
    bad_patch["edits"][0]["path"] = "../other.py"
    assert client.post(f"/v1/engineering/{item_id}/manual-patch", headers=engineer,
                       json={"patch": bad_patch}).status_code == 422
    patched = client.post(f"/v1/engineering/{item_id}/manual-patch", headers=engineer,
                          json={"patch": fixture_patch()})
    assert patched.status_code == 200 and patched.json()["ai_call"] is False
    assert client.get(f"/v1/engineering/{item_id}", headers=engineer).json()["current_checks_usable"] is False
    monkeypatch.setattr("ownstack.api.run_verifier", trusted_local_verification)
    checked = client.post(f"/v1/engineering/{item_id}/verify", headers=engineer)
    assert checked.status_code == 200 and checked.json()["passed"]
    assert client.get(f"/v1/engineering/{item_id}", headers=engineer).json()["current_checks_usable"] is True
    from ownstack.runner import current_provenance
    with monkeypatch.context() as changed:
        changed.setattr("ownstack.api.current_provenance", lambda: {**current_provenance(), "oracle_hash": "changed"})
        assert client.get(f"/v1/engineering/{item_id}", headers=engineer).json()["current_checks_usable"] is False
        assert client.post(f"/v1/engineering/{item_id}/decide", headers=engineer,
                           json={"decision": "accept_for_manual_release", "patch_hash": patched.json()["patch_hash"]}).status_code == 409
    decision = client.post(f"/v1/engineering/{item_id}/decide", headers=engineer,
                           json={"decision": "accept_for_manual_release", "patch_hash": patched.json()["patch_hash"]})
    assert decision.status_code == 200 and decision.json()["release_state"] == "not_deployed"
    with fixture_db() as db:
        assert db.get(InferenceBudget, "global").reserved_calls == 0


def test_late_ai_draft_cannot_overwrite_manual_patch(client, fixture_db, monkeypatch):
    engineer = login(client, "atlas-engineer")
    created = client.post("/v1/requests", headers={**engineer, "Idempotency-Key": "draft-race-request"},
                          json={"text": "Add PDF export for Project Atlas", "kind": "feature",
                                "project_id": "atlas-project"})
    request_id = created.json()["id"]
    client.post(f"/v1/requests/{request_id}/manual-handoff",
                headers={**engineer, "Idempotency-Key": "draft-race-handoff"})
    with fixture_db() as db:
        item_id = db.scalar(select(EngineeringItem.id).where(EngineeringItem.request_id == request_id))

    def manual_wins_while_model_runs(_text):
        with fixture_db() as db:
            item = db.get(EngineeringItem, item_id)
            item.patch = fixture_patch()
            item.patch_hash = patch_hash(item.patch)
            item.status = "drafted"
            db.commit()
        return fixture_patch(), "late-fixture"

    monkeypatch.setattr("ownstack.api.propose_patch", manual_wins_while_model_runs)
    response = client.post(f"/v1/engineering/{item_id}/draft", headers=engineer)
    assert response.status_code == 409
    with fixture_db() as db:
        item = db.get(EngineeringItem, item_id)
        assert item.status == "drafted"
        assert item.patch_hash == patch_hash(fixture_patch())


def test_engineer_can_correct_failed_checks_without_losing_original(client, fixture_db, monkeypatch):
    engineer = login(client, "atlas-engineer")
    created = client.post("/v1/requests", headers={**engineer, "Idempotency-Key": "correct-failed-pdf"},
                          json={"text": "Add PDF export", "kind": "feature", "project_id": "atlas-project"}).json()
    handoff = client.post(f"/v1/requests/{created['id']}/manual-handoff",
                          headers={**engineer, "Idempotency-Key": "correct-failed-pdf-handoff"})
    assert handoff.status_code == 200, handoff.text
    broken = fixture_patch()
    broken["edits"][0]["new"] = "def broken syntax:\n"
    with fixture_db() as db:
        item = db.scalar(select(EngineeringItem).where(EngineeringItem.request_id == created["id"]))
        item_id = item.id
        item.patch, item.patch_hash, item.status = broken, patch_hash(broken), "checks_failed"
        db.commit()
    response = client.post(f"/v1/engineering/{item_id}/manual-patch", headers=engineer, json={"patch": fixture_patch()})
    assert response.status_code == 200 and response.json()["ai_call"] is False
    with fixture_db() as db:
        previous = db.scalar(select(Evidence).where(Evidence.kind == "superseded_patch"))
        assert previous.subject_hash == patch_hash(broken) and previous.result["patch"] == broken
        assert db.get(InferenceBudget, "global").reserved_calls == 0
    monkeypatch.setattr("ownstack.api.run_verifier", trusted_local_verification)
    checked = client.post(f"/v1/engineering/{item_id}/verify", headers=engineer)
    assert checked.status_code == 200 and checked.json()["passed"]
