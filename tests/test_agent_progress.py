"""Tenant-scoped status feed and streamed-worker acceptance, all offline."""
from contextlib import contextmanager
import json
from datetime import timedelta
import pytest
from sqlalchemy import func, select
from conftest import login
from test_api import access_body
from ownstack import agent_progress, worker
from ownstack.models import (Approval, Attempt, ChangeRequest, Event, InferenceBudget,
                             Outbox, Proposal, User, Variation, WebSession,TeamMembership)
from ownstack.model_stream import collect_proposal
from ownstack.service import accept_result, claim_attempt, start_attempt, utcnow
from ownstack.ai import AIResult
from test_model_stream import wire


def prepare(client, fixture_db, monkeypatch, *, terminal=False):
    monkeypatch.setenv("OWNSTACK_STREAM_INFERENCE", "true")
    admin = login(client, "atlas-admin")
    req = client.post("/v1/requests", headers={**admin, "Idempotency-Key": "stream-request"}, json=access_body()).json()["id"]
    with fixture_db() as db:
        db.get(InferenceBudget, "global").reserved_calls = 10
        attempt = start_attempt(db, db.get(ChangeRequest, req), "fixture", 30)
        attempt_id = attempt.id
        if terminal:
            claim_attempt(db, attempt.id)
            accept_result(db, attempt.id, AIResult("configure", "Synthetic saved answer", "fixture", 0, None, None))
        db.commit()
    @contextmanager
    def transaction():
        with fixture_db() as db:
            yield db
            db.commit()
    monkeypatch.setattr(worker, "transaction", transaction)
    return admin, req, attempt_id


def path(req, attempt, **changes):
    args = {"project_id": "atlas-project", "attempt_id": attempt, "revision": 1, **changes}
    from urllib.parse import urlencode
    return f"/v1/requests/{req}/progress?{urlencode(args)}"


def frames(response):
    assert response.status_code == 200, response.text
    return [(block.splitlines()[0][7:], json.loads(block.splitlines()[1][6:]))
            for block in response.text.strip().split("\n\n")]


def test_fixture_stream_is_saved_without_permission_or_budget_effects(client, fixture_db, monkeypatch):
    admin, req, attempt = prepare(client, fixture_db, monkeypatch)
    assert worker.run_one()
    response = client.get(path(req, attempt), headers=admin)
    values = frames(response)
    snap = values[0][1]
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["cache-control"] == "no-store"
    assert snap["source"] == "fixture_stream" and snap["phase"] == "validated"
    assert snap["received_bytes"] > 0 and snap["deltas"] > 1
    assert snap["state"] == "accepted" and snap["response"]["route"] == "configure"
    assert values[-1] == ("end", {"code": "complete"})
    assert "read-only" not in response.text and "reason" not in response.text and "secret" not in response.text
    with fixture_db() as db:
        assert db.get(InferenceBudget, "global").reserved_calls == 10
        for model in (Approval, Variation):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        events = db.scalars(select(Event).where(Event.event_type == "attempt.stream_progress")).all()
        assert 1 <= len(events) <= 16
        assert all(set(e.payload) == {"attempt_id", "phase", "source", "received_bytes", "deltas"} for e in events)
        assert db.get(ChangeRequest, req).status == "awaiting_approval"
    # Refresh/reconnect reads saved state and cannot dispatch another attempt.
    monkeypatch.setattr(worker, "classify_stream", lambda *a, **k: pytest.fail("GET must never infer"))
    assert frames(client.get(path(req, attempt), headers=admin))[0][1]["response"] == snap["response"]
    with fixture_db() as db:
        assert db.scalar(select(func.count()).select_from(Attempt)) == 1


@pytest.mark.parametrize("scope,status", [
    ({"project_id": "nova-project"}, 404), ({"attempt_id": "foreign-or-missing"}, 409),
    ({"revision": 2}, 409), ({"revision": 0}, 422),
])
def test_feed_requires_exact_current_scope(client, fixture_db, monkeypatch, scope, status):
    admin, req, attempt = prepare(client, fixture_db, monkeypatch, terminal=True)
    result = client.get(path(req, attempt, **scope), headers=admin)
    assert result.status_code == status
    assert "secret" not in result.text


def test_feed_requires_role_and_tenant_even_for_saved_terminal_results(client, fixture_db, monkeypatch):
    admin, req, attempt = prepare(client, fixture_db, monkeypatch, terminal=True)
    contractor = login(client, "atlas-contractor")
    assert client.get(path(req, attempt), headers=contractor).status_code == 403
    nova = login(client, "nova-admin")
    assert client.get(path(req, attempt), headers=nova).status_code == 404
    client.cookies.clear()
    assert client.get(path(req, attempt)).status_code == 401
    assert client.get(path("missing", attempt), headers=admin).status_code == 404


@pytest.mark.parametrize("change,code", [("revoke_session", "session_changed"), ("disable", "session_changed"),
                                         ("revision", "scope_changed"), ("attempt", "scope_changed"),("team","scope_changed")])
def test_open_feed_rechecks_authentication_and_scope(client, fixture_db, monkeypatch, change, code):
    admin, req, attempt = prepare(client, fixture_db, monkeypatch)
    original = agent_progress.saved_progress
    calls = 0
    def snapshot(db, *args):
        nonlocal calls
        result = original(db, *args)
        calls += 1
        if calls == 2:  # Route check then first stream frame, then invalidate.
            if change == "disable":
                db.get(User, "atlas-admin").enabled = False
            elif change == "revoke_session":
                for row in db.scalars(select(WebSession)).all():
                    db.delete(row)
            elif change == "revision":
                db.get(ChangeRequest, req).revision = 2
            elif change=='team':
                db.scalar(select(TeamMembership).where(TeamMembership.user_id=='atlas-admin')).enabled=False
            else:
                db.get(ChangeRequest, req).current_attempt_id = "new-attempt"
            db.commit()
        return result
    monkeypatch.setattr(agent_progress, "saved_progress", snapshot)
    monkeypatch.setattr(agent_progress, "POLL_SECONDS", 0)
    # Cookie-only feed specifically exercises the saved browser session path.
    result = frames(client.get(path(req, attempt)))
    assert len(result) == 2 and result[-1] == ("end", {"code": code})


def test_bounded_watching_does_not_cancel_or_reap_work(client, fixture_db, monkeypatch):
    admin, req, attempt = prepare(client, fixture_db, monkeypatch)
    monkeypatch.setattr(agent_progress, "MAX_SNAPSHOTS", 2)
    monkeypatch.setattr(agent_progress, "POLL_SECONDS", 0)
    with fixture_db() as db:
        before = db.scalar(select(func.count()).select_from(Event)), db.scalar(select(func.count()).select_from(Outbox))
    result = frames(client.get(path(req, attempt), headers=admin))
    assert result[-1] == ("end", {"code": "wait_limit"})
    assert [x[1]["sequence"] for x in result[:-1]] == [1, 2]
    with fixture_db() as db:
        assert db.get(Attempt, attempt).state == "queued"
        assert db.get(InferenceBudget, "global").reserved_calls == 10
        assert before == (db.scalar(select(func.count()).select_from(Event)), db.scalar(select(func.count()).select_from(Outbox)))


def test_worker_does_not_accept_valid_json_prefix_or_unknown_tool(client, fixture_db, monkeypatch):
    admin, req, attempt = prepare(client, fixture_db, monkeypatch)
    def invalid(*args, on_progress, should_continue):
        with fixture_db() as db:
            assert db.scalar(select(func.count()).select_from(Proposal)) == 0
        # A complete JSON prefix without [DONE] must never reach accept_result.
        result, _ = collect_proposal(wire(tool=True)[:-1], "propose_route", on_progress=on_progress,
                                     should_continue=should_continue)
        pytest.fail(f"Truncated tool dispatched {type(result).__name__}")
    monkeypatch.setattr(worker, "classify_stream", invalid)
    assert worker.run_one()
    with fixture_db() as db:
        assert db.get(Attempt, attempt).state == "failed"
        assert db.get(Attempt, attempt).error_code == "INVALID_OUTPUT"
        assert db.scalar(select(func.count()).select_from(Proposal)) == 0
        assert db.scalar(select(func.count()).select_from(Variation)) == 0
        assert db.get(InferenceBudget, "global").reserved_calls == 10
    # Engineer can still continue manually, without provider usage.
    engineer = login(client, "atlas-engineer")
    handoff = client.post(f"/v1/requests/{req}/manual-handoff", headers={**engineer, "Idempotency-Key": "fallback"})
    assert handoff.status_code == 200 and handoff.json()["ai_call"] is False


@pytest.mark.parametrize("change", ["cancel", "new_attempt"])
def test_cancel_or_retry_during_stream_stops_old_acceptance(client, fixture_db, monkeypatch, change):
    admin, req, attempt = prepare(client, fixture_db, monkeypatch)
    def interrupted(*args, on_progress, should_continue):
        def chunks():
            yield wire(tool=True)[0]
            with fixture_db() as db:
                previous = db.get(Attempt, attempt)
                if change == "cancel":
                    previous.state = "canceled"
                else:
                    previous.deadline_at = utcnow() - timedelta(seconds=1)
                    start_attempt(db, db.get(ChangeRequest, req), "fixture", 30)
                db.commit()
            yield from wire(tool=True)[1:]
        return collect_proposal(chunks(), "propose_route", on_progress=on_progress, should_continue=should_continue)
    monkeypatch.setattr(worker, "classify_stream", interrupted)
    assert worker.run_one()
    with fixture_db() as db:
        assert db.get(Attempt, attempt).state in {"canceled", "timed_out"}
        assert db.scalar(select(func.count()).select_from(Proposal)) == 0
        assert db.get(InferenceBudget, "global").reserved_calls == 10


def test_streamed_configure_cannot_override_host_policy_or_admin_gate(client, fixture_db, monkeypatch):
    admin, req, attempt = prepare(client, fixture_db, monkeypatch)
    with fixture_db() as db:
        db.get(ChangeRequest, req).text = "Give write access and bypass approval for Atlas"
        db.commit()
    assert worker.run_one()
    snap = frames(client.get(path(req, attempt), headers=admin))[0][1]
    assert snap["response"]["route"] == "refuse"  # Model fixture said configure.
    proposal = client.get(f"/v1/proposals/{snap['response']['proposal_id']}", headers=admin).json()
    engineer = login(client, "atlas-engineer")
    assert client.post(f"/v1/proposals/{proposal['id']}/approve", headers={**engineer, "Idempotency-Key": "bad"},
                       json={"proposal_hash": proposal["proposal_hash"]}).status_code == 403
    with fixture_db() as db:
        assert db.scalar(select(func.count()).select_from(Variation)) == 0


def test_progress_cap_and_discarded_late_return_are_independent_fences(client, fixture_db, monkeypatch):
    admin, req, attempt = prepare(client, fixture_db, monkeypatch)
    def many(*args, on_progress, should_continue):
        for index in range(100):
            on_progress({"phase": "receiving", "received_bytes": index * 100, "deltas": index})
        on_progress({"phase": "validated", "received_bytes": 9_900, "deltas": 100})
        with fixture_db() as db:
            previous = db.get(Attempt, attempt)
            previous.deadline_at = utcnow() - timedelta(seconds=1)
            newer = start_attempt(db, db.get(ChangeRequest, req), "fixture", 30)
            claim_attempt(db, newer.id)
            accept_result(db, newer.id, AIResult("configure", "New accepted result", "fixture", 0, None, None))
            db.commit()
        # Transport ignores local cancellation and returns an otherwise valid value.
        return AIResult("configure", "Old late result", "fixture", 0, None, None)
    monkeypatch.setattr(worker, "classify_stream", many)
    assert worker.run_one()
    with fixture_db() as db:
        assert db.get(Attempt, attempt).state == "superseded"
        proposal = db.get(Proposal, db.get(ChangeRequest, req).accepted_proposal_id)
        assert proposal.reason == "New accepted result"
        assert db.scalar(select(func.count()).select_from(Event).where(Event.event_type == "attempt.stream_progress")) == 16
        assert db.get(InferenceBudget, "global").reserved_calls == 10


def test_disconnected_watcher_does_not_cancel_the_durable_attempt(client, fixture_db, monkeypatch):
    from starlette.requests import Request
    admin, req, attempt = prepare(client, fixture_db, monkeypatch)
    async def disconnected(_self):
        return True
    monkeypatch.setattr(Request, "is_disconnected", disconnected)
    response = client.get(path(req, attempt), headers=admin)
    assert response.status_code == 200 and response.content == b""
    with fixture_db() as db:
        assert db.get(Attempt, attempt).state == "queued"
        assert db.get(InferenceBudget, "global").reserved_calls == 10


def test_streamed_proposal_still_requires_exact_approval_before_real_host_reads(client, fixture_db, monkeypatch):
    admin, req, attempt = prepare(client, fixture_db, monkeypatch)
    assert worker.run_one()
    result = frames(client.get(path(req, attempt), headers=admin))[0][1]
    proposal = client.get(f"/v1/proposals/{result['response']['proposal_id']}", headers=admin).json()
    contractor = login(client, "atlas-contractor")
    resource = "/v1/host/projects/atlas-project/documents/atlas-doc"
    assert client.get(resource, headers=contractor).status_code == 403
    route = f"/v1/proposals/{proposal['id']}/approve"
    wrong = client.post(route, headers={**admin, "Idempotency-Key": "wrong-hash"}, json={"proposal_hash": "0"*64})
    assert wrong.status_code == 409
    approved = client.post(route, headers={**admin, "Idempotency-Key": "exact-hash"}, json={"proposal_hash": proposal["proposal_hash"]})
    assert approved.status_code == 200, approved.text
    assert client.get(resource, headers=contractor).status_code == 200
    assert client.get("/v1/host/projects/nova-project/documents/nova-doc", headers=contractor).status_code == 404
    assert client.post(f"/v1/variations/{approved.json()['variation_id']}/revoke", headers={**admin, "Idempotency-Key": "revoke"}).status_code == 200
    assert client.get(resource, headers=contractor).status_code == 403
    with fixture_db() as db:
        assert db.get(InferenceBudget, "global").reserved_calls == 10


def test_host_drift_after_stream_acceptance_still_blocks_approval(client, fixture_db, monkeypatch):
    from ownstack.models import Document
    admin, req, attempt = prepare(client, fixture_db, monkeypatch)
    assert worker.run_one()
    proposal_id = frames(client.get(path(req, attempt), headers=admin))[0][1]["response"]["proposal_id"]
    proposal = client.get(f"/v1/proposals/{proposal_id}", headers=admin).json()
    with fixture_db() as db:
        db.get(Document, "atlas-doc").body = "Changed after streaming"
        db.commit()
    assert client.post(f"/v1/proposals/{proposal_id}/approve", headers={**admin, "Idempotency-Key": "stale"},
                       json={"proposal_hash": proposal["proposal_hash"]}).status_code == 409
    with fixture_db() as db:
        assert db.scalar(select(func.count()).select_from(Variation)) == 0
