from contextlib import contextmanager
import pytest
from sqlalchemy import select
from conftest import login
from test_api import access_body
from ownstack.ai import AIResult
from ownstack.models import Attempt, ChangeRequest, InferenceBudget, Proposal
from ownstack.service import start_attempt
from ownstack import worker


@pytest.mark.parametrize("mode,model_id,error", [
    ("off", "fixture", "AI_OFF"),
    ("nebius", "fixture", "MODEL_CONFIGURATION_CHANGED"),
    ("fixture", "nvidia/old-model", "MODEL_CONFIGURATION_CHANGED"),
])
def test_config_change_never_dispatches_queued_work(client, fixture_db, monkeypatch, mode, model_id, error):
    admin = login(client, "atlas-admin")
    request_id = client.post("/v1/requests", headers={**admin, "Idempotency-Key": "worker-change"},
                             json=access_body()).json()["id"]
    with fixture_db() as db:
        attempt = start_attempt(db, db.get(ChangeRequest, request_id), model_id, 30)
        attempt_id = attempt.id
        db.commit()

    @contextmanager
    def transaction():
        with fixture_db() as db:
            yield db
            db.commit()

    def unexpected_call(*args):
        raise AssertionError("A changed mode/model must never reach inference")

    monkeypatch.setattr(worker, "transaction", transaction)
    monkeypatch.setattr(worker, "classify", unexpected_call)
    monkeypatch.setenv("OWNSTACK_AI_MODE", mode)
    monkeypatch.setenv("NEBIUS_MODEL_ID", "nvidia/new-model")
    assert worker.run_one()
    with fixture_db() as db:
        attempt = db.get(Attempt, attempt_id)
        assert attempt.state == "failed" and attempt.error_code == error
        assert db.get(ChangeRequest, request_id).status == "failed"
        assert db.get(InferenceBudget, "global").reserved_calls == 0


@pytest.mark.parametrize("returned_model,expected_state", [("fixture", "accepted"), ("unexpected-model", "failed")])
def test_worker_uses_one_settings_snapshot_and_rejects_wrong_model(client, fixture_db, monkeypatch, returned_model, expected_state):
    admin = login(client, "atlas-admin")
    request_id = client.post("/v1/requests", headers={**admin, "Idempotency-Key": "worker-match"},
                             json=access_body()).json()["id"]
    queued = client.post(f"/v1/requests/{request_id}/interpret", headers=admin)
    attempt_id = queued.json()["attempt_id"]

    @contextmanager
    def transaction():
        with fixture_db() as db:
            yield db
            db.commit()

    def classify(text, kind, settings):
        assert settings.ai_mode == "fixture"
        return AIResult("configure", "Synthetic worker test", returned_model, 0, None, None)

    monkeypatch.setattr(worker, "transaction", transaction)
    monkeypatch.setattr(worker, "classify", classify)
    assert worker.run_one()
    with fixture_db() as db:
        assert db.get(Attempt, attempt_id).state == expected_state
        proposal = db.scalar(select(Proposal).where(Proposal.request_id == request_id))
        assert bool(proposal) == (expected_state == "accepted")
        assert db.get(InferenceBudget, "global").reserved_calls == 0
