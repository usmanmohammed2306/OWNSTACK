"""Authored journey protocol tests. HTTP mocks are not repository execution proof."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_journey_script', ROOT / 'scripts/run_release_journeys.py')
journeys = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journeys)


@pytest.mark.parametrize('url', [
    'https://127.0.0.1:8130', 'http://example.com:8130', 'http://localhost:8130',
    'http://127.0.0.1', 'http://127.0.0.1:8109', 'http://127.0.0.1:8122',
    'http://127.0.0.1:8101', 'http://127.0.0.1:80', 'http://user:pass@127.0.0.1:8130',
    'http://127.0.0.1:8130/path', 'http://127.0.0.1:8130/?q=1',
    'http://127.0.0.1:8130/#fragment', 'http://127.0.0.1:bad',
])
def test_campaign_refuses_remote_primary_or_ambiguous_targets(url):
    with pytest.raises(ValueError, match='isolated loopback'):
        journeys.fixture_url(url)


def test_explicit_new_loopback_fixture_is_accepted():
    assert journeys.fixture_url('http://127.0.0.1:8130/') == 'http://127.0.0.1:8130'
    assert journeys.fixture_url('http://[::1]:8131') == 'http://[::1]:8131'


def test_journal_preserves_failure_and_redacts_authentication(tmp_path):
    journal = journeys.Journal(tmp_path / 'private')
    journal.append({'passed': False, 'request': {'password': 'sensitive-pass'},
                    'response': {'token': 'bearer-material', 'nested': [{'csrf_token': 'csrf-value'}]}})
    journal.finish({'passed': False, 'error_type': 'ObservedFailure'})
    raw = (tmp_path / 'private/results.jsonl').read_text()
    assert 'sensitive-pass' not in raw and 'bearer-material' not in raw and 'csrf-value' not in raw
    assert json.loads(raw)['passed'] is False
    assert (tmp_path / 'private').stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in (tmp_path / 'private').iterdir())
    with pytest.raises(FileExistsError):
        journeys.Journal(tmp_path / 'private')
    with pytest.raises(FileExistsError):
        journal.finish({'passed': True})


def test_actor_records_unexpected_http_status_before_raising(tmp_path):
    journal = journeys.Journal(tmp_path / 'private')
    def response(request):
        if request.url.path == '/v1/session':
            return httpx.Response(200, json={'token': 'synthetic-token', 'csrf_token': 'synthetic-csrf'})
        return httpx.Response(503, json={'detail': 'Temporary isolated fixture unavailable'})
    actor = journeys.Actor('http://127.0.0.1:8130', 'synthetic-user', 'synthetic-pass', journal,
                           transport=httpx.MockTransport(response))
    try:
        with pytest.raises(AssertionError, match='observed 503'):
            actor.call('GET', '/v1/release/checks/id')
        assert journal.records[-1]['status'] == 503 and not journal.records[-1]['passed']
        assert journal.records[0]['request']['password'] == '[redacted]'
    finally:
        actor.close()


def test_actor_records_transport_loss_without_fabricating_status(tmp_path):
    journal = journeys.Journal(tmp_path / 'private')
    def response(request):
        if request.url.path == '/v1/session':
            return httpx.Response(200, json={'token': 'synthetic-token', 'csrf_token': 'synthetic-csrf'})
        raise httpx.ReadTimeout('controlled local transport interruption')
    actor = journeys.Actor('http://127.0.0.1:8130', 'synthetic-user', 'synthetic-pass', journal,
                           transport=httpx.MockTransport(response))
    try:
        with pytest.raises(httpx.ReadTimeout):
            actor.call('GET', '/v1/release/checks/id')
        assert journal.records[-1]['error_type'] == 'ReadTimeout'
        assert 'status' not in journal.records[-1]
    finally:
        actor.close()


def test_campaign_saves_unready_health_before_any_login(tmp_path, monkeypatch):
    monkeypatch.setattr(journeys, 'ROOT', tmp_path)
    monkeypatch.setenv('OWNSTACK_AI_MODE', 'off');monkeypatch.setenv('OWNSTACK_MAX_LIVE_CALLS', '0')
    original = httpx.Client
    paths = []
    def respond(request):
        paths.append(request.url.path)
        return httpx.Response(503, json={'status': 'not_ready', 'ai_mode': 'off'})
    monkeypatch.setattr(journeys.httpx, 'Client', lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(respond)))
    output = tmp_path / '.private/unready'
    with pytest.raises(httpx.HTTPStatusError):
        journeys.campaign('http://127.0.0.1:8130', output, {}, {}, {})
    assert paths == ['/health/ready']
    result = json.loads((output / 'report.json').read_text())
    row = json.loads((output / 'results.jsonl').read_text())
    assert not result['passed'] and result['http_results'] == 1
    assert row['status'] == 503 and not row['passed']


def test_persona_story_catalog_is_explicitly_synthetic_and_unexecuted():
    folder = ROOT / 'evals/release_assurance'
    personas = json.loads((folder / 'personas.json').read_text())
    stories = json.loads((folder / 'stories.json').read_text())
    ids = {row['id'] for row in personas['personas']}
    assert len(ids) == 8 and 'not interviewed customers' in personas['provenance']
    assert stories['status'] == 'planned' and len(stories['stories']) == 16
    assert len({row['id'] for row in stories['stories']}) == 16
    assert all(row['persona'] in ids and row['acceptance'] for row in stories['stories'])
    assert not any('passed' in row for row in stories['stories'])


def requirement_spec():
    """Independent expected policy for API controls; no executor success implied."""
    context = {'actor_id': 'atlas-contractor', 'actor_tenant_id': 'atlas', 'actor_role': 'contractor',
               'resource_id': 'atlas-roadmap', 'resource_tenant_id': 'atlas', 'assigned': False,
               'at': '2026-10-27T12:00:00Z', 'grant_starts_at': None,
               'grant_expires_at': None, 'grant_revoked': False}
    return {'schema_version': 1, 'key': 'atlas-assigned-visibility', 'version': 1,
            'customer_tenant_id': 'atlas', 'title': 'Synthetic Atlas assigned-document restriction',
            'source_ref': 'SYNTHETIC-ATLAS-42', 'owner_id': 'atlas-admin', 'expires_at': None,
            'cases': [
                {'case_id': 'atlas-unassigned', 'title': 'Unassigned contractor is denied', 'kind': 'target',
                 'input': context, 'expected': {'status_code': 403, 'visible_fields': []}},
                {'case_id': 'nova-standard', 'title': 'Nova member keeps ordinary access', 'kind': 'control',
                 'input': {**context, 'actor_id': 'nova-member', 'actor_tenant_id': 'nova', 'actor_role': 'member',
                           'resource_id': 'nova-roadmap', 'resource_tenant_id': 'nova', 'assigned': True},
                 'expected': {'status_code': 200, 'visible_fields': ['id', 'title', 'internal_notes']}}
            ]}


@pytest.fixture
def release_enabled(monkeypatch):
    monkeypatch.setenv('OWNSTACK_RELEASE_ASSURANCE', 'true')
    monkeypatch.setenv('OWNSTACK_AI_MODE', 'off')


def approved_requirement(client, spec=None):
    from conftest import login
    engineer = login(client, 'atlas-engineer');owner = login(client, 'atlas-admin')
    response = client.post('/v1/release/requirements', headers=engineer,
                           json={'project_id': 'atlas-project', 'spec': spec or requirement_spec()})
    assert response.status_code == 201, response.text
    draft = response.json()
    response = client.post('/v1/release/requirements/' + draft['id'] + '/approve', headers=owner,
                           json={'expected_hash': draft['requirement_hash']})
    assert response.status_code == 200, response.text
    return response.json(), engineer, owner


def queue_check(client, requirement, actor, *, key=None, candidate='b' * 64):
    from uuid import uuid4
    body = {'project_id': 'atlas-project', 'baseline_sha256': 'a' * 64,
            'candidate_sha256': candidate, 'requirement_ids': [requirement['id']],
            'idempotency_key': key or uuid4().hex}
    response = client.post('/v1/release/checks', headers=actor, json=body)
    assert response.status_code == 202, response.text
    return response.json(), body


def explicit_result_double(claim, *, candidate_ok=True):
    """Only lifecycle controls use this double. No actual Docker result implied."""
    observations = []
    for spec in claim['requirements']:
        for case in spec['cases']:
            observations.append({'requirement_key': spec['key'], 'case_id': case['case_id'],
                                 **case['expected'], 'error': None})
    candidate = deepcopy(observations)
    if not candidate_ok:
        candidate[0].update(status_code=200, visible_fields=['id', 'title'])
    from ownstack.release_executor import POLICY, HTTP_CLIENT, READY_CLIENT, execution_fingerprint, assess_observations
    import hashlib
    baseline = {'state': 'completed', 'failure': '', 'cleanup_verified': True, 'observations': observations}
    proposed = {'state': 'completed', 'failure': '', 'cleanup_verified': True, 'observations': candidate}
    return {'runner': 'release-http-docker-v1', 'profile': 'python-http-visibility-v1',
            'policy': POLICY, 'execution_policy_sha256': execution_fingerprint(),
            'oracle_sha256': hashlib.sha256((HTTP_CLIENT + READY_CLIENT).encode()).hexdigest(),
            'image_id': 'sha256:' + 'a' * 64,
            'test_double': True, 'limitation': 'Explicit result double; no repository execution in this test.',
            'baseline_sha256': claim['baseline_sha256'], 'candidate_sha256': claim['candidate_sha256'],
            'requirements_sha256': claim['requirements_sha256'], 'provider_calls': 0, 'released': False,
            'baseline': baseline, 'candidate': proposed,
            **assess_observations(claim['requirements'], baseline, proposed)}


def test_exact_approval_and_immutable_revisions_story(client, release_enabled):
    from conftest import login
    engineer = login(client, 'atlas-engineer');owner = login(client, 'atlas-admin')
    spec = requirement_spec()
    draft = client.post('/v1/release/requirements', headers=engineer,
                        json={'project_id': 'atlas-project', 'spec': spec}).json()
    path = '/v1/release/requirements/' + draft['id']
    assert client.post(path + '/approve', headers=engineer, json={'expected_hash': draft['requirement_hash']}).status_code == 403
    assert client.post(path + '/approve', headers=owner, json={'expected_hash': '0' * 64}).status_code == 409
    assert client.post(path + '/approve', headers=owner, json={'expected_hash': draft['requirement_hash']}).status_code == 200
    changed = deepcopy(spec);changed['version'] = 2
    changed['cases'][0]['expected'] = {'status_code': 200, 'visible_fields': ['id', 'title']}
    second = client.post('/v1/release/requirements', headers=engineer,
                         json={'project_id': 'atlas-project', 'spec': changed})
    assert second.status_code == 201
    revised = second.json();assert revised['requirement_hash'] != draft['requirement_hash']
    assert client.post('/v1/release/requirements/' + revised['id'] + '/approve', headers=owner,
                       json={'expected_hash': draft['requirement_hash']}).status_code == 409
    assert client.get(path, headers=engineer).json()['spec'] == draft['spec']
    assert client.put(path, headers=engineer, json=changed).status_code == 405


def test_inconsistent_report_claiming_pass_cannot_override_observed_customer_regression(client, fixture_db, release_enabled):
    from ownstack.release_assurance import claim_next, finish_check
    requirement, engineer, _ = approved_requirement(client)
    checked, _ = queue_check(client, requirement, engineer)
    claim = claim_next(fixture_db);result = explicit_result_double(claim, candidate_ok=False)
    result['status'] = 'passed'  # Deliberately lying double must be unusable.
    assert finish_check(fixture_db, checked['id'], claim['claim_token'], result)
    saved = client.get('/v1/release/checks/' + checked['id'], headers=engineer).json()
    assert saved['state'] == 'blocked'
    assert 'claim_token' not in saved
    response = client.post('/v1/release/checks/' + checked['id'] + '/decide', headers=engineer,
                           json={'expected_revision': saved['revision'], 'evidence_hash': saved['evidence_hash'],
                                 'decision': 'accept_for_manual_release'})
    assert response.status_code == 409


@pytest.mark.parametrize('phase', ['baseline', 'candidate'])
def test_unverified_cleanup_never_becomes_passing_review(client, fixture_db, release_enabled, phase):
    from ownstack.release_assurance import claim_next, finish_check
    requirement, engineer, _ = approved_requirement(client)
    checked, _ = queue_check(client, requirement, engineer)
    claim = claim_next(fixture_db);result = explicit_result_double(claim)
    result[phase]['cleanup_verified'] = False
    assert finish_check(fixture_db, checked['id'], claim['claim_token'], result)
    saved = client.get('/v1/release/checks/' + checked['id'], headers=engineer).json()
    assert saved['state'] == 'blocked'


@pytest.mark.parametrize('shape', ['report-none', 'report-list', 'report-string', 'baseline-none', 'candidate-string', 'assessments-none'])
def test_malformed_operator_result_saves_blocked_progress(client, fixture_db, release_enabled, shape):
    from ownstack.release_assurance import claim_next, finish_check
    requirement, engineer, _ = approved_requirement(client)
    checked, _ = queue_check(client, requirement, engineer)
    claim = claim_next(fixture_db);result = explicit_result_double(claim)
    if shape == 'report-none':result = None
    elif shape == 'report-list':result = [{'malformed': True}]
    elif shape == 'report-string':result = 'malformed'
    elif shape == 'baseline-none':result['baseline'] = None
    elif shape == 'candidate-string':result['candidate'] = 'malformed'
    else:result['assessments'] = None
    assert finish_check(fixture_db, checked['id'], claim['claim_token'], result)
    saved = client.get('/v1/release/checks/' + checked['id'], headers=engineer).json()
    assert saved['state'] == 'blocked'
    review = client.get('/v1/release/checks/' + checked['id'] + '/review', headers=engineer)
    assert review.status_code == 200
    assert 'blocked' in review.text and 'Nothing was deployed' in review.text


def test_duplicate_saved_status_and_collision_have_no_second_job(client, fixture_db, release_enabled):
    from sqlalchemy import func, select
    from ownstack.models import ReleaseCheck
    requirement, engineer, _ = approved_requirement(client)
    first, body = queue_check(client, requirement, engineer)
    repeated = client.post('/v1/release/checks', headers=engineer, json=body)
    assert repeated.status_code == 202 and repeated.json()['id'] == first['id']
    assert client.post('/v1/release/checks', headers=engineer,
                       json={**body, 'candidate_sha256': 'c' * 64}).status_code == 409
    with fixture_db() as db:
        assert db.scalar(select(func.count()).select_from(ReleaseCheck)) == 1


def test_cancellation_and_late_attempt_cannot_overwrite_new_check(client, fixture_db, release_enabled):
    from ownstack.release_assurance import claim_next, finish_check
    requirement, engineer, _ = approved_requirement(client)
    old, _ = queue_check(client, requirement, engineer);old_claim = claim_next(fixture_db)
    canceled = client.post('/v1/release/checks/' + old['id'] + '/cancel', headers=engineer,
                           json={'expected_revision': old_claim['revision']})
    assert canceled.status_code == 200
    assert canceled.json()['state'] == 'canceled'
    assert 'remote process termination is not asserted' in canceled.json()['reason']
    newer, _ = queue_check(client, requirement, engineer, candidate='c' * 64);new_claim = claim_next(fixture_db)
    assert not finish_check(fixture_db, old['id'], old_claim['claim_token'], explicit_result_double(old_claim))
    assert client.get('/v1/release/checks/' + newer['id'], headers=engineer).json()['state'] == 'running'
    assert finish_check(fixture_db, newer['id'], new_claim['claim_token'], explicit_result_double(new_claim))
    assert client.get('/v1/release/checks/' + old['id'], headers=engineer).json()['state'] == 'canceled'


def test_new_approved_requirement_invalidates_existing_check_snapshot(client, fixture_db, release_enabled):
    from ownstack.release_assurance import claim_next, finish_check
    requirement, engineer, _ = approved_requirement(client)
    checked, _ = queue_check(client, requirement, engineer);claim = claim_next(fixture_db)
    second = requirement_spec();second['key'] = 'second-explicit-customer-rule'
    approved_requirement(client, second)
    assert finish_check(fixture_db, checked['id'], claim['claim_token'], explicit_result_double(claim))
    saved = client.get('/v1/release/checks/' + checked['id'], headers=engineer).json()
    assert saved['state'] == 'blocked' and 'requirements changed' in saved['reason'].lower()


def test_requester_disabled_during_execution_cannot_publish_usable_result(client, fixture_db, release_enabled):
    from ownstack.models import User
    from ownstack.release_assurance import claim_next, finish_check
    requirement, engineer, owner = approved_requirement(client)
    checked, _ = queue_check(client, requirement, engineer);claim = claim_next(fixture_db)
    with fixture_db() as db:
        db.get(User, 'atlas-engineer').enabled = False;db.commit()
    assert finish_check(fixture_db, checked['id'], claim['claim_token'], explicit_result_double(claim))
    assert client.get('/v1/release/checks/' + checked['id'], headers=engineer).status_code == 401
    saved = client.get('/v1/release/checks/' + checked['id'], headers=owner).json()
    assert saved['state'] == 'blocked' and 'authority changed' in saved['reason']


def test_nova_cannot_read_atlas_requirements_or_reports(client, release_enabled):
    from conftest import login
    requirement, engineer, _ = approved_requirement(client)
    checked, _ = queue_check(client, requirement, engineer);outsider = login(client, 'nova-admin')
    for path in ('/v1/release/requirements/' + requirement['id'], '/v1/release/checks/' + checked['id'],
                 '/v1/release/checks/' + checked['id'] + '/review'):
        response = client.get(path, headers=outsider)
        assert response.status_code == 404 and requirement['spec']['title'] not in response.text
    assert client.get('/v1/release/requirements', headers=outsider).json() == []
    assert client.get('/v1/release/checks', headers=outsider).json() == []


def test_expired_requirement_refused_for_approval(client, release_enabled):
    from conftest import login
    engineer = login(client, 'atlas-engineer');owner = login(client, 'atlas-admin')
    spec = requirement_spec();spec['expires_at'] = '2020-01-01T00:00:00Z'
    response = client.post('/v1/release/requirements', headers=engineer,
                           json={'project_id': 'atlas-project', 'spec': spec})
    assert response.status_code == 201
    item = response.json()
    response = client.post('/v1/release/requirements/' + item['id'] + '/approve', headers=owner,
                           json={'expected_hash': item['requirement_hash']})
    assert response.status_code == 409 and 'expired' in response.text


def test_fresh_client_reads_saved_report_without_claiming_another_job(client, fixture_db, release_enabled):
    from fastapi.testclient import TestClient
    from ownstack.api import app
    from ownstack.release_assurance import claim_next, finish_check
    requirement, engineer, _ = approved_requirement(client)
    checked, _ = queue_check(client, requirement, engineer);claim = claim_next(fixture_db)
    assert finish_check(fixture_db, checked['id'], claim['claim_token'], explicit_result_double(claim))
    first = client.get('/v1/release/checks/' + checked['id'], headers=engineer).json()
    with TestClient(app) as other:
        replay = other.get('/v1/release/checks/' + checked['id'], headers=engineer).json()
    assert replay['evidence_hash'] == first['evidence_hash'] and replay['id'] == first['id']
    assert claim_next(fixture_db) is None


def test_manager_scope_and_read_only_role_story(client, fixture_db, release_enabled):
    from conftest import login
    from ownstack.models import Project, Team, TeamMembership, User
    from uuid import uuid4
    requirement, engineer, _ = approved_requirement(client)
    checked, _ = queue_check(client, requirement, engineer)
    with fixture_db() as db:
        password = db.get(User, 'atlas-engineer').password_hash
        team_id = db.get(Project, 'atlas-project').team_id
        db.add(Team(id='unrelated-team', tenant_id='atlas', name='Unrelated team', name_key='unrelated team'))
        for username, assigned_team in [('review-manager', team_id), ('other-manager', 'unrelated-team')]:
            db.add(User(id=username, tenant_id='atlas', role='manager', password_hash=password))
            db.flush()
            db.add(TeamMembership(id=str(uuid4()), tenant_id='atlas', team_id=assigned_team,
                                  user_id=username, role='manager', enabled=True))
        db.commit()
    manager = login(client, 'review-manager');outsider = login(client, 'other-manager')
    for path in ('/v1/release/requirements/' + requirement['id'], '/v1/release/checks/' + checked['id']):
        assert client.get(path, headers=manager).status_code == 200
        assert client.get(path, headers=outsider).status_code == 404
    assert client.get('/v1/release/checks', headers=outsider).json() == []
    assert client.get('/v1/release/requirements', headers=outsider).json() == []
    assert client.post('/v1/release/requirements/' + requirement['id'] + '/approve', headers=manager,
                       json={'expected_hash': requirement['requirement_hash']}).status_code == 403
    assert client.post('/v1/release/checks/' + checked['id'] + '/cancel', headers=manager,
                       json={'expected_revision': checked['revision']}).status_code == 403


def test_requirement_expiry_after_enqueue_blocks_claim(client, fixture_db, release_enabled, monkeypatch):
    from datetime import timedelta
    import ownstack.release_assurance as release
    now = release.utcnow();spec = requirement_spec();spec['expires_at'] = (now + timedelta(hours=1)).isoformat()
    requirement, engineer, _ = approved_requirement(client, spec)
    checked, _ = queue_check(client, requirement, engineer)
    monkeypatch.setattr(release, 'utcnow', lambda: now + timedelta(hours=2))
    assert release.claim_next(fixture_db) is None
    saved = client.get('/v1/release/checks/' + checked['id'], headers=engineer).json()
    assert saved['state'] == 'blocked' and 'expired' in saved['reason']


def test_requester_team_removal_during_execution_cannot_publish_usable_result(client, fixture_db, release_enabled):
    from sqlalchemy import select
    from ownstack.models import Project, TeamMembership
    from ownstack.release_assurance import claim_next, finish_check
    requirement, engineer, owner = approved_requirement(client)
    checked, _ = queue_check(client, requirement, engineer);claim = claim_next(fixture_db)
    with fixture_db() as db:
        team_id = db.get(Project, 'atlas-project').team_id
        member = db.scalar(select(TeamMembership).where(TeamMembership.team_id == team_id,
                                                      TeamMembership.user_id == 'atlas-engineer'))
        member.enabled = False;member.revision += 1;db.commit()
    assert finish_check(fixture_db, checked['id'], claim['claim_token'], explicit_result_double(claim))
    assert client.get('/v1/release/checks/' + checked['id'], headers=engineer).status_code == 404
    saved = client.get('/v1/release/checks/' + checked['id'], headers=owner).json()
    assert saved['state'] == 'blocked' and 'team changed' in saved['reason']


@pytest.mark.parametrize('phase', ['queued', 'running', 'passed'])
def test_restored_requester_membership_cannot_revive_an_old_check(client, fixture_db, release_enabled, phase):
    """A permission gap needs a new request even when access is later restored."""
    from sqlalchemy import select
    from ownstack.models import Project, TeamMembership
    import ownstack.release_assurance as release
    requirement, engineer, owner = approved_requirement(client)
    checked, _ = queue_check(client, requirement, engineer)
    claim = release.claim_next(fixture_db) if phase != 'queued' else None
    if phase == 'passed':
        assert release.finish_check(fixture_db, checked['id'], claim['claim_token'], explicit_result_double(claim))
    with fixture_db() as db:
        team_id = db.get(Project, 'atlas-project').team_id
        member = db.scalar(select(TeamMembership).where(TeamMembership.team_id == team_id,
                                                      TeamMembership.user_id == 'atlas-engineer'))
        member.enabled = False;member.revision += 1;db.commit()
        member.enabled = True;member.revision += 1;db.commit()
    if phase == 'queued':
        assert release.claim_next(fixture_db) is None
    elif phase == 'running':
        assert release.finish_check(fixture_db, checked['id'], claim['claim_token'], explicit_result_double(claim))
    saved = client.get('/v1/release/checks/' + checked['id'], headers=owner).json()
    if phase == 'passed':
        response = client.post('/v1/release/checks/' + checked['id'] + '/decide', headers=engineer,
            json={'expected_revision': saved['revision'], 'evidence_hash': saved['evidence_hash'],
                  'decision': 'accept_for_manual_release'})
        assert response.status_code == 409
    else:
        assert saved['state'] == 'blocked' and 'authority generation' in saved['reason']
    # Restored membership permits a genuinely fresh check; it cannot repair the old one.
    fresh, _ = queue_check(client, requirement, engineer)
    next_claim = release.claim_next(fixture_db)
    assert next_claim['id'] == fresh['id']
    assert release.finish_check(fixture_db, fresh['id'], next_claim['claim_token'], explicit_result_double(next_claim))


def test_missing_requester_witness_requires_a_new_check(client, fixture_db, release_enabled):
    from ownstack.models import ReleaseAudit
    from ownstack.release_assurance import claim_next
    requirement, engineer, owner = approved_requirement(client)
    checked, _ = queue_check(client, requirement, engineer)
    with fixture_db() as db:
        event = db.query(ReleaseAudit).filter_by(subject_id=checked['id'], action='check.queued').one()
        event.payload = {key:value for key,value in event.payload.items() if key != 'authority'}
        db.commit()
    assert claim_next(fixture_db) is None
    saved = client.get('/v1/release/checks/' + checked['id'], headers=owner).json()
    assert saved['state'] == 'blocked' and 'authority generation' in saved['reason']


def test_elapsed_worker_deadline_blocks_and_discards_late_completion(client, fixture_db, release_enabled, monkeypatch):
    from datetime import timedelta
    import ownstack.release_assurance as release
    requirement, engineer, _ = approved_requirement(client)
    checked, _ = queue_check(client, requirement, engineer);claim = release.claim_next(fixture_db)
    future = release.utcnow() + timedelta(minutes=6)
    monkeypatch.setattr(release, 'utcnow', lambda: future)
    assert release.expire_checks(fixture_db) == 1
    assert release.expire_checks(fixture_db) == 0
    assert not release.finish_check(fixture_db, checked['id'], claim['claim_token'], explicit_result_double(claim))
    saved = client.get('/v1/release/checks/' + checked['id'], headers=engineer).json()
    assert saved['state'] == 'blocked' and 'inspect owned runner' in saved['reason']


def test_approval_revoked_after_passing_result_requires_new_check(client, fixture_db, release_enabled):
    from ownstack.release_assurance import claim_next, finish_check
    requirement, engineer, owner = approved_requirement(client)
    checked, _ = queue_check(client, requirement, engineer);claim = claim_next(fixture_db)
    assert finish_check(fixture_db, checked['id'], claim['claim_token'], explicit_result_double(claim))
    saved = client.get('/v1/release/checks/' + checked['id'], headers=engineer).json()
    assert saved['state'] == 'passed'
    changed = requirement_spec();changed['version'] = 2;changed['title'] += ' revision two'
    approved_requirement(client, changed)
    response = client.post('/v1/release/checks/' + checked['id'] + '/decide', headers=engineer,
                           json={'expected_revision': saved['revision'], 'evidence_hash': saved['evidence_hash'],
                                 'decision': 'accept_for_manual_release'})
    assert response.status_code == 409
    assert client.get('/v1/release/checks/' + checked['id'], headers=owner).json()['decision'] is None


def test_browser_cannot_supply_report_or_execution_command(client, release_enabled):
    requirement, engineer, _ = approved_requirement(client)
    _, body = queue_check(client, requirement, engineer)
    for extra in ({'report': {'passed': True}}, {'command': ['arbitrary-shell']}, {'source_path': '/private/data'}):
        response = client.post('/v1/release/checks', headers=engineer, json={**body, **extra})
        assert response.status_code == 422


def test_omitting_newly_approved_requirements_cannot_narrow_suite(client, release_enabled):
    requirement, engineer, _ = approved_requirement(client)
    _, body = queue_check(client, requirement, engineer)
    extra = requirement_spec();extra['key'] = 'second-approved-requirement'
    approved_requirement(client, extra)
    response = client.post('/v1/release/checks', headers=engineer,
                           json={**body, 'idempotency_key': 'different-new-check-key'})
    assert response.status_code == 409 and 'Every current approved requirement' in response.text
