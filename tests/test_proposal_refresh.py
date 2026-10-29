"""Recover a stale proposal without spending credits or bypassing human approval."""
from datetime import timedelta
from importlib import import_module
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from conftest import login
from test_api import create_and_propose
from ownstack.models import (Approval, Attempt, ChangeRequest, Contract, Document, Event, Evidence,
                             HostObservation, Idempotency, InferenceBudget, Outbox, Project, Proposal, User, Variation)
from ownstack.policy import CONTRACT, aware, digest


def setup_drift(client, factory):
    admin, request_id, proposal_id, old_hash = create_and_propose(client, factory)
    engineer = login(client, 'atlas-engineer')
    with factory() as db:
        db.get(Document, 'atlas-doc').body = 'Updated host content, never copied into the review'
        db.get(Project, 'atlas-project').revision += 1
        db.get(InferenceBudget, 'global').reserved_calls = 10
        db.commit()
    return admin, engineer, request_id, proposal_id, old_hash


def review(client, proposal_id, engineer):
    response = client.get(f'/v1/proposals/{proposal_id}/refresh-review', headers=engineer)
    assert response.status_code == 200, response.text
    return response.json()


def refresh(client, proposal_id, engineer, snapshot, key='refresh-1', **changes):
    body = {'proposal_hash': snapshot['proposal_hash'], 'review_hash': snapshot['review_hash'],
            'reason': 'Host content changed; same original scope and expiry.', **changes}
    return client.post(f'/v1/proposals/{proposal_id}/refresh',
        headers={**engineer, 'Idempotency-Key': key}, json=body)


def test_stale_to_refreshed_to_new_admin_approval_is_real_recovery(client, fixture_db):
    admin, engineer, request_id, proposal_id, old_hash = setup_drift(client, fixture_db)
    contractor = login(client, 'atlas-contractor')
    assert client.post(f'/v1/proposals/{proposal_id}/approve', headers={**admin, 'Idempotency-Key': 'stale-approve'},
                       json={'proposal_hash': old_hash}).status_code == 409
    with fixture_db() as db:
        original_expiry = aware(db.get(ChangeRequest, request_id).expires_at)
        original_parameters = dict(db.get(Proposal, proposal_id).parameters)
    snapshot = review(client, proposal_id, engineer)
    assert snapshot['can_refresh'] and snapshot['saved_preview_hash'] != snapshot['fresh_preview_hash']
    response = refresh(client, proposal_id, engineer, snapshot)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['ai_call'] is False and result['approval_required'] is True and result['revision'] == 2
    assert result['proposal_id'] != proposal_id and result['proposal_hash'] != old_hash
    assert client.get('/v1/host/projects/atlas-project/documents', headers=contractor).status_code == 403
    with fixture_db() as db:
        request = db.get(ChangeRequest, request_id)
        assert request.accepted_proposal_id == result['proposal_id'] and request.status == 'awaiting_approval'
        assert aware(request.expires_at) == original_expiry
        assert db.get(Proposal, proposal_id).status == 'superseded'
        replacement = db.get(Proposal, result['proposal_id'])
        assert replacement.parameters == original_parameters and replacement.request_revision == 2
        assert db.scalar(select(func.count()).select_from(Variation)) == 0
        assert db.scalar(select(func.count()).select_from(Approval)) == 0
        attempts = db.scalars(select(Attempt).where(Attempt.request_id == request_id).order_by(Attempt.request_revision)).all()
        assert [(a.request_revision, a.state) for a in attempts] == [(1, 'accepted'), (2, 'accepted')]
        assert attempts[1].model_id == 'human-ai-off'
        assert db.get(InferenceBudget, 'global').reserved_calls == 10
    assert client.post(f'/v1/proposals/{proposal_id}/approve', headers={**admin, 'Idempotency-Key': 'old-after-refresh'},
                       json={'proposal_hash': old_hash}).status_code == 409
    fresh_preview = client.post(f"/v1/proposals/{result['proposal_id']}/preview", headers=admin)
    assert fresh_preview.status_code == 200 and fresh_preview.json()['matches_saved_proposal']
    # The engineer still cannot grant access; the tenant admin must approve the new exact hash.
    assert client.post(f"/v1/proposals/{result['proposal_id']}/approve", headers={**engineer, 'Idempotency-Key': 'engineer-no'},
                       json={'proposal_hash': result['proposal_hash']}).status_code == 403
    assert client.post(f"/v1/proposals/{result['proposal_id']}/approve", headers={**admin, 'Idempotency-Key': 'new-approved'},
                       json={'proposal_hash': result['proposal_hash']}).status_code == 200
    assert client.get('/v1/host/projects/atlas-project/documents', headers=contractor).status_code == 200
    assert client.get('/v1/host/projects/nova-project/documents', headers=contractor).status_code == 404


def test_retries_share_saved_revision_and_audit_outbox(client, fixture_db):
    _, engineer, request_id, proposal_id, _ = setup_drift(client, fixture_db)
    snapshot = review(client, proposal_id, engineer)
    first = refresh(client, proposal_id, engineer, snapshot)
    assert refresh(client, proposal_id, engineer, snapshot).json() == first.json()
    assert refresh(client, proposal_id, engineer, snapshot, reason='Different reason for the same key').status_code == 409
    assert refresh(client, proposal_id, engineer, snapshot, key='second-key').status_code == 409
    with fixture_db() as db:
        assert db.get(ChangeRequest, request_id).revision == 2
        rows = db.scalars(select(Event).where(Event.event_type == 'proposal.refreshed')).all()
        assert len(rows) == 1 and rows[0].payload['previous_proposal_id'] == proposal_id
        assert rows[0].payload['review_hash'] == snapshot['review_hash']
        assert db.scalar(select(func.count()).select_from(Outbox).where(Outbox.event_id == rows[0].id)) == 1
    assert review(client, first.json()['proposal_id'], engineer)['can_refresh'] is False


@pytest.mark.parametrize('actor,read_code,write_code', [('atlas-admin', 200, 403),
    ('atlas-contractor', 403, 403), ('nova-admin', 404, 403), ('platform-owner', 403, 403)])
def test_roles_and_tenant_lookup_are_server_enforced(client, fixture_db, actor, read_code, write_code):
    _, engineer, _, proposal_id, _ = setup_drift(client, fixture_db)
    snapshot = review(client, proposal_id, engineer)
    headers = login(client, actor)
    assert client.get(f'/v1/proposals/{proposal_id}/refresh-review', headers=headers).status_code == read_code
    assert refresh(client, proposal_id, headers, snapshot).status_code == write_code
    client.cookies.clear()  # A missing bearer header is not anonymous while a login cookie remains.
    assert client.get(f'/v1/proposals/{proposal_id}/refresh-review').status_code == 401


def test_review_is_read_only_and_no_change_cannot_create_revision(client, fixture_db):
    _, request_id, proposal_id, _ = create_and_propose(client, fixture_db)
    engineer = login(client, 'atlas-engineer')
    models = (Attempt, Proposal, Event, Evidence, HostObservation, Outbox, Idempotency)
    with fixture_db() as db:
        before = [db.scalar(select(func.count()).select_from(m)) for m in models]
    for _ in range(2):
        snapshot = review(client, proposal_id, engineer)
        assert not snapshot['can_refresh']
    assert refresh(client, proposal_id, engineer, snapshot).status_code == 409
    with fixture_db() as db:
        assert before == [db.scalar(select(func.count()).select_from(m)) for m in models]
        assert db.get(ChangeRequest, request_id).revision == 1
    assert 'body' not in snapshot['preview'] and 'atlas secret' not in str(snapshot)


@pytest.mark.parametrize('change', ['document', 'project', 'disabled', 'expiry', 'scope', 'text', 'contract', 'revision'])
def test_review_fences_changed_host_identity_and_intent(client, fixture_db, change):
    _, engineer, request_id, proposal_id, _ = setup_drift(client, fixture_db)
    snapshot = review(client, proposal_id, engineer)
    with fixture_db() as db:
        request = db.get(ChangeRequest, request_id)
        if change == 'document': db.get(Document, 'atlas-doc').body += ' another change'
        elif change == 'project': db.get(Project, 'atlas-project').revision += 1
        elif change == 'disabled': db.get(User, 'atlas-contractor').enabled = False
        elif change == 'expiry': request.expires_at += timedelta(hours=1)
        elif change == 'scope': request.viewer_id = 'atlas-engineer'
        elif change == 'text': request.text += ' Modified intent'
        elif change == 'contract': db.get(Contract, (CONTRACT['id'], CONTRACT['version'])).manifest_hash = '0' * 64
        elif change == 'revision': request.revision += 1
        db.commit()
    assert refresh(client, proposal_id, engineer, snapshot).status_code == 409
    with fixture_db() as db:
        assert db.get(Proposal, proposal_id).status == 'ready'
        assert db.get(ChangeRequest, request_id).accepted_proposal_id == proposal_id
        assert db.scalar(select(func.count()).select_from(Proposal)) == 1


def test_expired_intent_requires_new_request_not_silent_extension(client, fixture_db, monkeypatch):
    _, engineer, request_id, proposal_id, _ = setup_drift(client, fixture_db)
    snapshot = review(client, proposal_id, engineer)
    with fixture_db() as db: expiry = aware(db.get(ChangeRequest, request_id).expires_at)
    monkeypatch.setattr('ownstack.service.utcnow', lambda: expiry)
    assert refresh(client, proposal_id, engineer, snapshot).status_code == 422
    with fixture_db() as db:
        assert aware(db.get(ChangeRequest, request_id).expires_at) == expiry
        assert db.get(ChangeRequest, request_id).revision == 1


def test_wrong_hash_extra_expiry_missing_key_are_rejected(client, fixture_db):
    _, engineer, _, proposal_id, _ = setup_drift(client, fixture_db)
    snapshot = review(client, proposal_id, engineer)
    for changes, code in [({'proposal_hash': '0' * 64}, 409), ({'review_hash': '0' * 64}, 409),
                          ({'expires_at': '2027-01-01T00:00:00Z'}, 422), ({'reason': 'short'}, 422),
                          ({'reason': ' ' * 20}, 422)]:
        assert refresh(client, proposal_id, engineer, snapshot, **changes).status_code == code
    assert refresh(client, proposal_id, engineer, snapshot, key='').status_code == 422


def test_approved_proposal_cannot_be_refreshed(client, fixture_db):
    admin, request_id, proposal_id, old_hash = create_and_propose(client, fixture_db)
    assert client.post(f'/v1/proposals/{proposal_id}/approve', headers={**admin, 'Idempotency-Key': 'first-approval'},
                       json={'proposal_hash': old_hash}).status_code == 200
    engineer = login(client, 'atlas-engineer')
    assert client.get(f'/v1/proposals/{proposal_id}/refresh-review', headers=engineer).status_code == 409


def test_review_belongs_to_exact_actor_and_foreign_engineer_cannot_refresh(client, fixture_db):
    from ownstack.auth import password_hash
    admin, engineer, _, proposal_id, _ = setup_drift(client, fixture_db)
    admin_review = review(client, proposal_id, admin)
    assert refresh(client, proposal_id, engineer, admin_review).status_code == 409
    with fixture_db() as db:
        db.add(User(id='nova-engineer', tenant_id='nova', role='engineer', password_hash=password_hash('pass')))
        db.commit()
    foreign = login(client, 'nova-engineer')
    assert refresh(client, proposal_id, foreign, admin_review).status_code == 404


def test_mid_refresh_preview_mismatch_rolls_back_new_revision(client, fixture_db, monkeypatch):
    _, engineer, request_id, proposal_id, _ = setup_drift(client, fixture_db)
    snapshot = review(client, proposal_id, engineer)
    module = import_module('ownstack.proposal_refresh')
    original = module.manual_handoff
    def changed(db, request, principal):
        result = original(db, request, principal)
        db.get(Proposal, result['proposal_id']).preview_hash = 'f' * 64
        return result
    monkeypatch.setattr(module, 'manual_handoff', changed)
    assert refresh(client, proposal_id, engineer, snapshot).status_code == 409
    with fixture_db() as db:
        assert db.get(ChangeRequest, request_id).revision == 1
        assert db.get(Proposal, proposal_id).status == 'ready'
        assert db.scalar(select(func.count()).select_from(Proposal)) == 1


def test_old_answer_and_proof_export_preserve_both_revisions(client, fixture_db):
    from ownstack.ai import AIResult
    from ownstack.proof import export_proof, verify_envelope
    from ownstack.service import accept_result
    _, engineer, request_id, proposal_id, _ = setup_drift(client, fixture_db)
    with fixture_db() as db: old_attempt = db.get(Proposal, proposal_id).attempt_id
    snapshot = review(client, proposal_id, engineer)
    result = refresh(client, proposal_id, engineer, snapshot).json()
    with fixture_db() as db:
        assert not accept_result(db, old_attempt, AIResult('configure', 'late original', 'fixture', 0, None, None))
        db.commit()
        request = db.get(ChangeRequest, request_id)
        assert request.revision == 2 and request.accepted_proposal_id == result['proposal_id']
        assert db.get(Attempt, old_attempt).state == 'accepted'
        bind = db.bind
    envelope = export_proof(bind, request_id, 'atlas')
    assert verify_envelope(envelope)
    assert len(envelope['payload']['proposals']) == 2
    assert len(envelope['payload']['attempts']) == 2
    assert not envelope['payload']['approvals'] and not envelope['payload']['variations']
    assert any(row['event_type'] == 'proposal.refreshed' for row in envelope['payload']['events'])


def test_missing_original_intent_evidence_cannot_be_silently_rebuilt(client, fixture_db):
    from sqlalchemy import delete
    _, engineer, request_id, proposal_id, _ = setup_drift(client, fixture_db)
    snapshot = review(client, proposal_id, engineer)
    with fixture_db() as db:
        db.execute(delete(Evidence).where(Evidence.request_id == request_id, Evidence.kind == 'model_interpretation'))
        db.commit()
    assert refresh(client, proposal_id, engineer, snapshot).status_code == 409


def test_audit_failure_rolls_back_the_entire_refresh(client, fixture_db, monkeypatch):
    _, engineer, request_id, proposal_id, _ = setup_drift(client, fixture_db)
    snapshot = review(client, proposal_id, engineer)
    module = import_module('ownstack.proposal_refresh')
    def fail(*_args, **_kwargs): raise RuntimeError('synthetic audit failure')
    monkeypatch.setattr(module, 'record', fail)
    with TestClient(import_module('ownstack.api').app, raise_server_exceptions=False) as guarded:
        assert refresh(guarded, proposal_id, engineer, snapshot).status_code == 500
    with fixture_db() as db:
        assert db.get(ChangeRequest, request_id).revision == 1
        assert db.get(ChangeRequest, request_id).accepted_proposal_id == proposal_id
        assert db.get(Proposal, proposal_id).status == 'ready'
        assert db.scalar(select(func.count()).select_from(Proposal)) == 1
        assert db.scalar(select(func.count()).select_from(Attempt)) == 1
        assert db.scalar(select(func.count()).select_from(Idempotency).where(Idempotency.operation == 'refresh_proposal')) == 0
        assert db.get(InferenceBudget, 'global').reserved_calls == 10
