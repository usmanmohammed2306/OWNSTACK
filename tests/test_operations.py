from datetime import timedelta
from fastapi import HTTPException
import pytest
from sqlalchemy import select
from conftest import login
from ownstack.models import ChangeRequest, EngineeringItem, Evidence
from ownstack.patch_agent import fixture_patch
from ownstack.runner import trusted_local_verification
from ownstack.service import claim_engineering, reap_operations, utcnow


def item_for_feature(client, fixture_db):
    engineer = login(client, "atlas-engineer")
    created = client.post("/v1/requests", headers={**engineer, "Idempotency-Key": "operation-feature"},
                          json={"text": "Add PDF export", "kind": "feature", "project_id": "atlas-project"}).json()
    client.post(f"/v1/requests/{created['id']}/manual-handoff",
                headers={**engineer, "Idempotency-Key": "operation-handoff"})
    with fixture_db() as db:
        item_id = db.scalar(select(EngineeringItem.id).where(EngineeringItem.request_id == created["id"]))
    return engineer, item_id


def test_only_one_engineering_operation_can_be_claimed_and_crash_recovers(client, fixture_db):
    _, item_id = item_for_feature(client, fixture_db)
    with fixture_db() as db:
        item = db.get(EngineeringItem, item_id)
        claim_engineering(db, item, "drafting", 20)
        db.commit()
    with fixture_db() as db:
        with pytest.raises(HTTPException) as error:
            claim_engineering(db, db.get(EngineeringItem, item_id), "drafting", 20)
        assert error.value.status_code == 409
        db.rollback()
        db.get(EngineeringItem, item_id).operation_deadline = utcnow() - timedelta(seconds=1)
        db.commit()
    with fixture_db() as db:
        assert reap_operations(db) == 1
        db.commit()
        assert db.get(EngineeringItem, item_id).status == "draft_failed"
        assert db.get(EngineeringItem, item_id).operation_id is None


def test_local_cancel_leaves_remote_cancellation_unverified(client, fixture_db):
    engineer = login(client, "atlas-engineer")
    created = client.post("/v1/requests", headers={**engineer, "Idempotency-Key": "cancel-feature"},
                          json={"text": "Add PDF export", "kind": "feature", "project_id": "atlas-project"}).json()
    client.post(f"/v1/requests/{created['id']}/interpret", headers=engineer)
    canceled = client.post(f"/v1/requests/{created['id']}/cancel", headers=engineer)
    assert canceled.status_code == 200 and canceled.json()["remote_cancellation_verified"] is False
    with fixture_db() as db:
        assert db.get(ChangeRequest, created["id"]).status == "failed"


def test_human_acceptance_rejects_stale_test_provenance(client, fixture_db, monkeypatch):
    engineer, item_id = item_for_feature(client, fixture_db)
    patched = client.post(f"/v1/engineering/{item_id}/manual-patch", headers=engineer,
                          json={"patch": fixture_patch()})
    monkeypatch.setattr("ownstack.api.run_verifier", trusted_local_verification)
    checked = client.post(f"/v1/engineering/{item_id}/verify", headers=engineer)
    assert checked.status_code == 200 and checked.json()["passed"]
    with fixture_db() as db:
        evidence = db.scalar(select(Evidence).where(Evidence.kind == "patch_checks"))
        evidence.result = {**evidence.result, "checks_hash": "stale-check-suite"}
        db.commit()
    accepted = client.post(f"/v1/engineering/{item_id}/decide", headers=engineer,
                           json={"decision": "accept_for_manual_release", "patch_hash": patched.json()["patch_hash"]})
    assert accepted.status_code == 409
    assert client.get(f"/v1/engineering/{item_id}/artifact", headers=engineer).status_code == 409
