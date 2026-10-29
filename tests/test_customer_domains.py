"""Full authenticated local HTTP stories; model doubles are explicitly injected."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select, func
from conftest import login
from ownstack.customer_models import CustomerAccount, CustomerIdentity, CustomerInvitation, CustomerSubmission, CustomerRequestLink, CustomerRequirementLink
from ownstack.models import ChangeRequest, InferenceBudget, ReleaseRequirement
from ownstack.release_repository import initialize
from ownstack.service import utcnow


def setup_customer(client, staff, key, username=None):
    response = client.post('/v1/customers', headers=staff, json={'name': key.title(), 'key': key})
    assert response.status_code == 201, response.text
    customer = response.json()
    response = client.post('/v1/customers/' + customer['id'] + '/projects', headers=staff,
        json={'project_id': 'atlas-project', 'expected_revision': 1, 'enabled': True})
    assert response.status_code == 200, response.text
    invite = client.post('/v1/customers/' + customer['id'] + '/invitations', headers=staff).json()
    response = client.post('/v1/customer-portal/register', json={'invitation': invite['invitation'],
        'username': username or key, 'name': 'Synthetic ' + key, 'password': 'synthetic-customer-pass'})
    assert response.status_code == 201, response.text
    return customer, {'Authorization': 'Bearer ' + response.json()['token']}


@pytest.fixture
def customer_story(client, fixture_db, monkeypatch):
    monkeypatch.setenv('OWNSTACK_RELEASE_ASSURANCE', 'true')
    staff = login(client, 'atlas-admin'); engineer = login(client, 'atlas-engineer')
    north, north_auth = setup_customer(client, staff, 'north-customer')
    south, south_auth = setup_customer(client, staff, 'south-customer')
    return dict(staff=staff, engineer=engineer, north=north, south=south, north_auth=north_auth, south_auth=south_auth)


def submit(client, auth, **override):
    return client.post('/v1/customer-portal/requests', headers=auth, json={
        'project_id': 'atlas-project', 'text': 'Only assigned engineers and managers may read our documents.',
        'idempotency_key': 'request-one', **override})


def discovery(client, data, tmp_path):
    submission = submit(client, data['north_auth']).json()
    response = client.post('/v1/customers/inbox/' + submission['id'] + '/adopt', headers=data['engineer'])
    assert response.status_code == 200, response.text
    request_id = response.json()['request_id']
    app = tmp_path / 'source'; app.mkdir()
    (app / 'serve.py').write_text('pass\n'); source = 'def visible(actor):\n    return actor.assigned\n'
    (app / 'policy.py').write_text(source)
    snapshot = initialize(app, name='Customer application', entrypoint='serve.py', include=['serve.py', 'policy.py'])
    response = client.post('/v1/release/sources', headers=data['engineer'], json={
        'project_id': 'atlas-project', 'label': 'Baseline', 'snapshot': snapshot})
    assert response.status_code == 201, response.text
    response = client.post('/v1/requests/' + request_id + '/code-context', headers=data['engineer'],
        json={'expected_revision': 1, 'files': {'policy.py': source}})
    assert response.status_code == 200, response.text
    response = client.post('/v1/change-agents', headers=data['engineer'], json={
        'request_id': request_id, 'source_sha256': snapshot['sha256'], 'idempotency_key': 'customer-discovery'})
    assert response.status_code == 201, response.text
    return response.json(), submission


def publish(client, data, state):
    response = client.post('/v1/change-agents/' + state['id'] + '/answers', headers=data['engineer'], json={
        'expected_revision': state['revision'], 'answers': {'roles': ['engineer', 'manager'], 'requires_assignment': True,
            'temporary_grants': True, 'visible_fields': ['id', 'title'], 'denial_status': 403}})
    assert response.status_code == 200, response.text
    s = response.json()
    response = client.post('/v1/change-agents/' + s['id'] + '/publish', headers=data['engineer'],
        json={'expected_revision': s['revision'], 'policy_hash': s['policy_hash']})
    assert response.status_code == 200, response.text
    return response.json()


def test_customer_to_vendor_discovery_approval_is_private_and_customer_bound(client, fixture_db, customer_story, tmp_path):
    d = customer_story; state, submission = discovery(client, d, tmp_path)
    assert state['customer']['customer_id'] == d['north']['id']
    s = publish(client, d, state)
    response = client.post('/v1/change-agents/' + s['id'] + '/approve', headers=d['staff'],
        json={'expected_revision': s['revision'], 'policy_hash': s['policy_hash']})
    assert response.status_code == 200, response.text
    with fixture_db() as db:
        assert db.scalar(select(func.count()).select_from(CustomerRequirementLink)) == 3
        for r in db.scalars(select(ReleaseRequirement)):
            assert r.tenant_id == 'atlas' and r.spec['customer_tenant_id'] == d['north']['id']
        assert db.get(InferenceBudget, 'global').reserved_calls == 0
    public = client.get('/v1/customer-portal/requests', headers=d['north_auth']).json()
    assert public[0]['status'] == 'with_engineering' and public[0]['review_update'] is None
    assert not public[0]['released']
    assert set(public[0]) == {'id', 'project_id', 'text', 'status', 'revision', 'created_at', 'released', 'review_update'}
    assert client.get('/v1/customer-portal/requests', headers=d['south_auth']).json() == []


@pytest.mark.parametrize('path', ['/v1/requests', '/v1/customers', '/v1/customers/inbox/requests',
    '/v1/release/sources', '/v1/release/requirements', '/v1/organization', '/v1/engineering', '/v1/change-agents?request_id=anything'])
def test_portal_token_cannot_become_a_staff_session(client, customer_story, path):
    assert client.get(path, headers=customer_story['north_auth']).status_code in {401, 403, 404}


def test_staff_token_cannot_become_customer_or_spoof_customer_fields(client, customer_story):
    d = customer_story
    assert client.get('/v1/customer-portal/me', headers=d['staff']).status_code == 401
    for extra in [{'tenant_id': 'nova'}, {'customer_id': d['south']['id']}, {'role': 'admin'}, {'kind': 'access'}]:
        assert submit(client, d['north_auth'], **extra).status_code == 422
    assert submit(client, d['north_auth'], project_id='nova-project').status_code == 404
    assert client.post('/v1/customers/' + d['north']['id'] + '/projects', headers=login(client, 'nova-admin'),
        json={'project_id': 'nova-project', 'expected_revision': 1, 'enabled': True}).status_code == 404


def test_duplicate_submit_and_parallel_adoption_create_one_internal_request(client, fixture_db, customer_story):
    d = customer_story
    with ThreadPoolExecutor(max_workers=4) as workers:
        responses = list(workers.map(lambda _: submit(client, d['north_auth']), range(4)))
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert len({r.json()['id'] for r in responses}) == 1
    ident = responses[0].json()['id']
    with ThreadPoolExecutor(max_workers=4) as workers:
        responses = list(workers.map(lambda _: client.post('/v1/customers/inbox/' + ident + '/adopt', headers=d['engineer']), range(4)))
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert len({r.json()['request_id'] for r in responses}) == 1
    assert submit(client, d['north_auth'], text='A different request with the same retry key.').status_code == 409
    with fixture_db() as db:
        assert db.scalar(select(func.count()).select_from(CustomerSubmission)) == 1
        assert db.scalar(select(func.count()).select_from(CustomerRequestLink)) == 1
        assert db.scalar(select(func.count()).select_from(ChangeRequest)) == 1


def test_foreign_vendor_cannot_see_adopt_or_manage_customer_request(client, customer_story):
    d = customer_story; ident = submit(client, d['north_auth']).json()['id']; other = login(client, 'nova-admin')
    assert client.get('/v1/customers', headers=other).json() == []
    assert client.get('/v1/customers/inbox/requests', headers=other).json() == []
    assert client.post('/v1/customers/inbox/' + ident + '/adopt', headers=other).status_code == 404
    assert client.post('/v1/customers/' + d['north']['id'] + '/invitations', headers=other).status_code == 404
    assert client.post('/v1/customers/' + d['north']['id'] + '/status', headers=d['engineer'],
        json={'expected_revision': 1, 'enabled': False}).status_code == 403


@pytest.mark.parametrize('change', ['customer', 'project'])
def test_revoke_restore_never_revives_approved_customer_evidence(client, fixture_db, customer_story, tmp_path, change):
    d = customer_story; state, _ = discovery(client, d, tmp_path); s = publish(client, d, state)
    r = client.post('/v1/change-agents/' + s['id'] + '/approve', headers=d['staff'],
        json={'expected_revision': s['revision'], 'policy_hash': s['policy_hash']})
    assert r.status_code == 200, r.text
    path = '/v1/customers/' + d['north']['id'] + ('/status' if change == 'customer' else '/projects')
    extra = {} if change == 'customer' else {'project_id': 'atlas-project'}
    for revision, enabled in [(1, False), (2, True)]:
        r = client.post(path, headers=d['staff'], json={**extra, 'expected_revision': revision, 'enabled': enabled})
        assert r.status_code == 200, r.text
    receipt = client.get('/v1/release/requirements-receipt', headers=d['engineer'], params={'project_id': 'atlas-project'})
    assert receipt.status_code == 409, receipt.text
    assert client.post('/v1/change-agents/' + s['id'] + '/approve', headers=d['staff'],
        json={'expected_revision': r.json().get('revision', 4), 'policy_hash': s['policy_hash']}).status_code in {404, 409}
    if change == 'customer':
        assert client.get('/v1/customer-portal/me', headers=d['north_auth']).status_code == 401
        assert client.post('/v1/customer-portal/session', json={'username': 'north-customer', 'password': 'synthetic-customer-pass'}).status_code == 200


def test_contact_disable_restore_and_logout_do_not_reactivate_old_sessions(client, customer_story):
    d = customer_story; path = '/v1/customers/' + d['north']['id'] + '/people'
    person = client.get(path, headers=d['staff']).json()[0]
    for revision, enabled in [(1, False), (2, True)]:
        assert client.post(path + '/' + person['id'] + '/status', headers=d['staff'],
            json={'expected_revision': revision, 'enabled': enabled}).status_code == 200
    assert client.get('/v1/customer-portal/me', headers=d['north_auth']).status_code == 401
    fresh = client.post('/v1/customer-portal/session', json={'username': 'north-customer', 'password': 'synthetic-customer-pass'}).json()
    h = {'Authorization': 'Bearer ' + fresh['token']}
    assert client.post('/v1/customer-portal/logout', headers=h).status_code == 200
    assert client.get('/v1/customer-portal/me', headers=h).status_code == 401


@pytest.mark.parametrize('fault', ['used', 'expired', 'revoked', 'account_changed'])
def test_invitations_are_single_use_expiring_and_generation_bound(client, fixture_db, customer_story, fault):
    d = customer_story; a = d['north']; invite = client.post('/v1/customers/' + a['id'] + '/invitations', headers=d['staff']).json()
    with fixture_db() as db:
        i = db.get(CustomerInvitation, invite['id'])
        if fault in {'used', 'revoked'}: i.used = True
        if fault == 'expired': i.expires_at = utcnow() - timedelta(seconds=1)
        if fault == 'account_changed': db.get(CustomerAccount, a['id']).revision += 2
        db.commit()
    assert client.post('/v1/customer-portal/register', json={'invitation': invite['invitation'],
        'username': 'new-contact', 'name': 'Synthetic new contact', 'password': 'synthetic-new-password'}).status_code == 409


def test_customer_revocation_during_model_wait_discards_answer(client, customer_story, tmp_path, monkeypatch):
    d = customer_story; state, _ = discovery(client, d, tmp_path)
    def model(*args):
        r = client.post('/v1/customers/' + d['north']['id'] + '/status', headers=d['staff'], json={'expected_revision': 1, 'enabled': False})
        assert r.status_code == 200
        return {'action': 'ask', 'field': 'roles', 'reason': 'Choose explicit roles.', 'citations': ['request']}, {'live': False}
    monkeypatch.setattr('ownstack.change_agent_model.decide', model)
    r = client.post('/v1/change-agents/' + state['id'] + '/step', headers=d['engineer'],
        json={'expected_revision': state['revision'], 'idempotency_key': 'revoked-during-wait'})
    assert r.status_code in {404, 409}


def test_empty_and_forged_registration_is_rejected(client):
    assert client.post('/v1/customer-portal/register', json={'invitation': 'x'*43, 'username': 'fake-person',
        'name': 'Fake', 'password': 'long-local-password'}).status_code == 404
    assert client.get('/v1/customer-portal/me', headers={'Authorization': 'Bearer customer_invalid'}).status_code == 401


def test_exact_review_lookup_and_safe_customer_update_with_explicit_executor_double(client, fixture_db, customer_story, tmp_path):
    from test_release_journeys import explicit_result_double
    from ownstack.release_assurance import claim_next, finish_check, audit
    from ownstack.models import Project
    d=customer_story; state, submission=discovery(client,d,tmp_path); s=publish(client,d,state)
    r=client.post('/v1/change-agents/'+s['id']+'/approve',headers=d['staff'],json={'expected_revision':s['revision'],'policy_hash':s['policy_hash']})
    assert r.status_code==200,r.text
    r=client.post('/v1/release/checks',headers=d['engineer'],json={'project_id':'atlas-project',
        'baseline_sha256':'a'*64,'candidate_sha256':'b'*64,'requirement_ids':s['requirement_ids'],'idempotency_key':'review-explicit-double'})
    assert r.status_code==202,r.text
    ident=r.json()['id'];claim=claim_next(fixture_db,only_id=ident)
    assert finish_check(fixture_db,ident,claim['claim_token'],explicit_result_double(claim))
    with fixture_db() as db:
        audit(db,db.get(Project,'atlas-project'),s['id'],'agent.counterexample_completed',result={
            'check_id':ident,'source_diff':'explicit executor-double diff, not actual execution'})
        db.commit()
    path=f"/v1/change-agents/{s['id']}/checks/{ident}/review"
    reviewed=client.get(path,headers=d['engineer']);assert reviewed.status_code==200,reviewed.text
    reviewed=reviewed.json();assert reviewed['customer_submission_id']==submission['id']
    assert reviewed['customer_review_shared'] is False
    share={'discovery_id':s['id'],'check_id':ident,'evidence_hash':reviewed['evidence_hash']}
    share_path=f"/v1/customers/inbox/{submission['id']}/share-review"
    assert client.post(share_path,headers=d['engineer'],json=share).status_code==409
    r=client.post(path,headers=d['engineer'],json={'expected_revision':reviewed['revision'],
        'evidence_hash':reviewed['evidence_hash'],'comment':'Explicit control-plane test, not actual patch execution.',
        'decision':'accept_for_manual_release','idempotency_key':'accepted-double-review'})
    assert r.status_code==200,r.text
    assert client.post(share_path,headers=d['engineer'],json={**share,'evidence_hash':'c'*64}).status_code==409
    for _ in range(2):
        r=client.post(share_path,headers=d['engineer'],json=share);assert r.status_code==200,r.text
    # Reopening the exact review must restore the saved delivery state, not offer
    # a second send merely because the browser component was remounted.
    assert client.get(path,headers=d['engineer']).json()['customer_review_shared'] is True
    from ownstack.customer_models import CustomerAudit
    with fixture_db() as db:
        rows=db.query(CustomerAudit).filter_by(action='customer.review_shared').all()
        assert len(rows)==1
        rows[0].payload={**rows[0].payload,'evidence_hash':'f'*64}
        db.commit()
    assert client.get(path,headers=d['engineer']).json()['customer_review_shared'] is False
    data=client.get('/v1/customer-portal/requests',headers=d['north_auth']).json()[0]
    assert data['review_update'] and data['released'] is False
    assert 'explicit executor-double diff' not in str(data) and 'evidence_hash' not in data
    assert client.post(share_path,headers=d['north_auth'],json=share).status_code==401


def test_shared_customer_does_not_bridge_two_private_vendor_teams(client, fixture_db, customer_story):
    from ownstack.models import Team,TeamMembership,Project,User
    from ownstack.auth import password_hash
    d=customer_story
    with fixture_db() as db:
        db.add(Team(id='billing-team',tenant_id='atlas',name='Billing',name_key='billing',enabled=True));db.flush()
        db.add(User(id='billing-engineer',tenant_id='atlas',role='engineer',password_hash=password_hash('pass')));db.flush()
        db.add_all([TeamMembership(id='billing-member',tenant_id='atlas',team_id='billing-team',user_id='billing-engineer',role='member',enabled=True),
                    TeamMembership(id='billing-admin',tenant_id='atlas',team_id='billing-team',user_id='atlas-admin',role='member',enabled=True)])
        db.add(Project(id='billing-product',tenant_id='atlas',team_id='billing-team',name='Billing product'));db.commit()
    billing=login(client,'billing-engineer')
    assert client.get('/v1/customers',headers=billing).json()==[]
    r=client.post('/v1/customers/'+d['north']['id']+'/projects',headers=d['staff'],
        json={'project_id':'billing-product','expected_revision':1,'enabled':True})
    assert r.status_code==200,r.text
    first=submit(client,d['north_auth']).json()
    second=submit(client,d['north_auth'],project_id='billing-product',idempotency_key='billing-request').json()
    for staff,visible,hidden in [(d['engineer'],first,second),(billing,second,first)]:
        rows=client.get('/v1/customers/inbox/requests',headers=staff).json()
        assert [r['id'] for r in rows]==[visible['id']]
        assert client.post('/v1/customers/inbox/'+hidden['id']+'/adopt',headers=staff).status_code==404
        r=client.post('/v1/customers/inbox/'+visible['id']+'/adopt',headers=staff);assert r.status_code==200,r.text
        other=billing if staff==d['engineer'] else d['engineer']
        assert client.get('/v1/requests/'+r.json()['request_id'],headers=other).status_code==404
