"""Thirty explicitly scoped diagnostic reports, not thirty security certifications."""
from datetime import timedelta
import pytest
from sqlalchemy import func, select
from conftest import login
from test_api import create_and_propose
from test_rollback_review import another_grant
from ownstack.models import (Attempt, ChangeRequest, DeliveryReceipt, Document, EngineeringItem, Event,
    Evidence, HostObservation, IdentityEvent, InferenceBudget, Outbox, Project, Proposal, User, Variation)
from ownstack.repair_models import RepairRun
from ownstack.service import utcnow

KEYS = ['approval-inbox', 'stale-previews', 'revision-lineage', 'expired-intent', 'pending-work',
    'overdue-work', 'attempt-failures', 'discarded-results', 'active-exposure', 'expiry-docket',
    'expiry-cleanup', 'scheduled-access', 'disabled-exposure', 'unused-grants', 'overlap-analysis',
    'grant-usage', 'denied-read-review', 'role-read-review', 'viewer-access-matrix', 'document-inventory',
    'contract-integrity', 'approval-audit', 'refresh-history', 'engineering-review', 'failed-check-review',
    'repair-review', 'repair-failures', 'dead-letter-review', 'delivery-receipts', 'identity-audit']


def prepare(client, factory, key):
    admin, request_id, proposal_id, proposal_hash = create_and_propose(client, factory)
    now = utcnow()
    if key in KEYS[8:16] or key == 'approval-audit':
        response = client.post(f'/v1/proposals/{proposal_id}/approve', headers={**admin, 'Idempotency-Key': 'assurance-grant'},
                               json={'proposal_hash': proposal_hash})
        assert response.status_code == 200
        grant = response.json()['variation_id']
    with factory() as db:
        request = db.get(ChangeRequest, request_id)
        attempt = db.get(Attempt, request.current_attempt_id)
        if key == 'stale-previews': db.get(Document, 'atlas-doc').body += ' synthetic drift'
        if key == 'expired-intent': request.expires_at = now - timedelta(seconds=1)
        if key in ('pending-work', 'overdue-work', 'attempt-failures'):
            attempt.state = {'pending-work': 'queued', 'overdue-work': 'running', 'attempt-failures': 'failed'}[key]
            attempt.deadline_at = now + timedelta(hours=1) if key == 'pending-work' else now - timedelta(seconds=1)
            attempt.error_code = 'SYNTHETIC_FAILURE' if key == 'attempt-failures' else None
        if key == 'discarded-results': db.add(Event(id='discard-event', tenant_id='atlas', request_id=request_id,
            event_type='attempt.late_discarded', payload={'private': 'must not appear'}))
        if key == 'refresh-history': db.add(Event(id='refresh-event', tenant_id='atlas', request_id=request_id,
            event_type='proposal.refreshed', payload={'private': 'must not appear', 'revision': 2}))
        if key in KEYS[8:16] or key == 'approval-audit':
            row = db.get(Variation, grant)
            if key == 'expiry-cleanup': row.expires_at = now - timedelta(seconds=1)
            if key == 'scheduled-access': row.starts_at = now + timedelta(hours=1)
            if key == 'disabled-exposure': db.get(User, 'atlas-contractor').enabled = False
            if key == 'overlap-analysis': another_grant(db, row)
        if key in ('grant-usage', 'denied-read-review', 'role-read-review'):
            db.add(HostObservation(id='observation', tenant_id='atlas', project_id='atlas-project',
                actor_id='atlas-contractor' if key != 'role-read-review' else 'atlas-admin',
                variation_id=grant if key == 'grant-usage' else None, document_id=None, action='list_documents',
                allowed=key != 'denied-read-review', basis='variation' if key == 'grant-usage' else 'role' if key == 'role-read-review' else 'denied'))
        if key in ('engineering-review', 'repair-review', 'repair-failures'):
            db.add(EngineeringItem(id='assurance-item', tenant_id='atlas', request_id=request_id,
                status='checks_passed', patch_hash='a' * 64))
            db.flush()
        if key in ('repair-review', 'repair-failures'):
            db.add(RepairRun(id='assurance-repair', tenant_id='atlas', item_id='assurance-item', request_id=request_id,
                actor_id='atlas-engineer', state='awaiting_review' if key == 'repair-review' else 'failed',
                original_patch={'secret': 'private code'}, original_patch_hash='b' * 64, request_revision=1,
                request_hash='c' * 64, configuration={'secret': 'private configuration'}, provenance={}, max_attempts=2,
                deadline_at=now + timedelta(minutes=1)))
        if key == 'failed-check-review': db.add(Evidence(id='failed-check', tenant_id='atlas', request_id=request_id,
            kind='patch_checks', subject_hash='d' * 64, result={'passed': False, 'stdout': 'private output'}, limitation='synthetic'))
        if key == 'dead-letter-review':
            row = db.scalar(select(Outbox).where(Outbox.tenant_id == 'atlas'))
            row.state, row.attempts, row.last_error = 'dead', 5, 'HTTP_FAILURE'
        if key == 'delivery-receipts':
            event = db.scalar(select(Event).where(Event.tenant_id == 'atlas'))
            db.add(DeliveryReceipt(event_id=event.id, tenant_id='atlas', destination_id='local-receipt', envelope_hash='e' * 64))
        if key == 'identity-audit': db.add(IdentityEvent(id='identity-event', tenant_id='atlas', actor_id='atlas-admin',
            subject_id='atlas-contractor', action='sessions_revoked'))
        db.get(InferenceBudget, 'global').reserved_calls = 10
        db.commit()
    return admin, request_id


@pytest.mark.parametrize('key', KEYS)
def test_report_capability_has_findings_and_enforces_boundaries(client, fixture_db, key):
    admin, request_id = prepare(client, fixture_db, key)
    catalogue = client.get('/v1/assurance/catalogue', headers=admin).json()
    spec = next(item for item in catalogue if item['key'] == key)
    params = {name: request_id if name == 'request_id' else 'atlas-project' if name == 'project_id' else 'atlas-contractor'
              for name in spec['required']}
    models = (Attempt, Proposal, Event, Evidence, HostObservation, Outbox, Variation, InferenceBudget)
    with fixture_db() as db: before = [db.scalar(select(func.count()).select_from(m)) for m in models]
    for _ in range(2):
        response = client.get('/v1/assurance/' + key, params=params, headers=admin)
        assert response.status_code == 200, response.text
        report = response.json()
        assert report['report'] == key and report['tenant_id'] == 'atlas' and report['items'], report
        assert report['scope'] == params and 'no-store' in response.headers['cache-control']
        for private in ('atlas secret', 'private output', 'private code', 'private configuration', 'must not appear', 'password_hash', 'token_hash', 'csrf_hash'):
            assert private not in response.text
    with fixture_db() as db:
        assert before == [db.scalar(select(func.count()).select_from(m)) for m in models]
        assert db.get(InferenceBudget, 'global').reserved_calls == 10
    assert client.get('/v1/assurance/' + key, params={**params, 'limit': 0}, headers=admin).status_code == 422
    assert client.get('/v1/assurance/' + key, params={**params, 'limit': 101}, headers=admin).status_code == 422
    for name in spec['filters']:
        foreign = 'nova-project' if name == 'project_id' else 'nova-contractor' if name == 'viewer_id' else 'missing-request'
        assert client.get('/v1/assurance/' + key, params={**params, name: foreign}, headers=admin).status_code == 404
    denied_actor = 'nova-contractor' if key == 'disabled-exposure' else 'atlas-contractor'
    assert client.get('/v1/assurance/' + key, params=params, headers=login(client, denied_actor)).status_code == 403
    if not spec['required']:
        own = client.get('/v1/assurance/' + key, headers=login(client, 'nova-admin'))
        assert own.status_code == 200 and own.json()['tenant_id'] == 'nova'
        if key != 'contract-integrity': assert not own.json()['items'], own.text
    client.cookies.clear()
    assert client.get('/v1/assurance/' + key, params=params).status_code == 401


def test_catalogue_is_role_scoped_and_unknown_reports_are_honest(client):
    admin = login(client, 'atlas-admin')
    response = client.get('/v1/assurance/catalogue', headers=admin)
    assert response.status_code == 200 and response.json()
    assert len({s['key'] for s in response.json()}) == len(response.json())
    assert client.get('/v1/assurance/not-a-report', headers=admin).status_code == 404
    engineer_specs = client.get('/v1/assurance/catalogue', headers=login(client, 'atlas-engineer')).json()
    assert all('engineer' in spec['roles'] for spec in engineer_specs)


def test_final_catalogue_has_thirty_distinct_reports_and_identity_audit_is_admin_only(client):
    admin = login(client, 'atlas-admin')
    specs = client.get('/v1/assurance/catalogue', headers=admin).json()
    assert len(specs) == 30 and {s['key'] for s in specs} == set(KEYS)
    engineer = login(client, 'atlas-engineer')
    assert client.get('/v1/assurance/identity-audit', headers=engineer).status_code == 403
    assert len(client.get('/v1/assurance/catalogue', headers=engineer).json()) == 29


def test_truncation_and_unsupported_scope_are_explicit(client, fixture_db):
    admin, request_id = prepare(client, fixture_db, 'approval-inbox')
    with fixture_db() as db:
        db.add(ChangeRequest(id='second-request', tenant_id='atlas', requester_id='atlas-admin',
            text='Synthetic bound control', kind='access', status='awaiting_approval'))
        db.commit()
    report = client.get('/v1/assurance/approval-inbox?limit=1', headers=admin).json()
    assert report['truncated'] and len(report['items']) == 1 and report['source_limit'] == 1
    assert client.get('/v1/assurance/contract-integrity?project_id=atlas-project', headers=admin).status_code == 422
    assert client.get('/v1/assurance/revision-lineage', headers=admin).status_code == 422


def test_observed_usage_removes_grant_from_unobserved_report(client, fixture_db):
    admin, _ = prepare(client, fixture_db, 'unused-grants')
    report = client.get('/v1/assurance/unused-grants', headers=admin).json()
    grant = report['items'][0]['id']
    with fixture_db() as db:
        db.add(HostObservation(id='now-observed', tenant_id='atlas', project_id='atlas-project',
            actor_id='atlas-contractor', variation_id=grant, action='list_documents', allowed=True, basis='variation'))
        db.commit()
    assert not client.get('/v1/assurance/unused-grants', headers=admin).json()['items']


def test_adjacent_grants_are_not_overlaps_but_one_second_intersection_is(client, fixture_db):
    admin, _ = prepare(client, fixture_db, 'overlap-analysis')
    with fixture_db() as db:
        extra = db.get(Variation, 'overlap-grant')
        original = db.scalar(select(Variation).where(Variation.id != 'overlap-grant'))
        extra.starts_at, extra.expires_at = original.expires_at, original.expires_at + timedelta(hours=1)
        db.commit()
    assert not client.get('/v1/assurance/overlap-analysis', headers=admin).json()['items']
    with fixture_db() as db:
        db.get(Variation, 'overlap-grant').starts_at -= timedelta(seconds=1)
        db.commit()
    assert len(client.get('/v1/assurance/overlap-analysis', headers=admin).json()['items']) == 1


def test_matrix_does_not_authorize_disabled_subject_and_creates_no_observations(client, fixture_db):
    admin, _ = prepare(client, fixture_db, 'viewer-access-matrix')
    with fixture_db() as db:
        db.get(User, 'atlas-engineer').enabled = False
        db.commit()
    report = client.get('/v1/assurance/viewer-access-matrix?project_id=atlas-project', headers=admin).json()
    rows = {r['id']: r for r in report['items']}
    assert rows['atlas-admin']['allowed'] and not rows['atlas-contractor']['allowed']
    assert not rows['atlas-engineer']['allowed'] and rows['atlas-engineer']['basis'] == 'account_disabled'
    with fixture_db() as db: assert db.scalar(select(func.count()).select_from(HostObservation)) == 0


def test_integrity_reports_surface_corruption_not_false_passes(client, fixture_db):
    from ownstack.models import Approval, Contract
    from ownstack.policy import CONTRACT
    admin, _ = prepare(client, fixture_db, 'approval-audit')
    with fixture_db() as db:
        db.scalar(select(Approval)).proposal_hash = '0' * 64
        db.get(Contract, (CONTRACT['id'], CONTRACT['version'])).manifest_hash = '0' * 64
        db.commit()
    assert not client.get('/v1/assurance/approval-audit', headers=admin).json()['items'][0]['exact_subject_matches']
    assert not client.get('/v1/assurance/contract-integrity', headers=admin).json()['items'][0]['matches_manifest']
