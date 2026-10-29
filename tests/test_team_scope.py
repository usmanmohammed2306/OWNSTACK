"""Synthetic business/team journeys over authenticated APIs, with AI disabled.

These are scope/lifecycle tests, not proof of five independent product markets.
Real repository execution is recorded separately from these API checks.
"""
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select
from conftest import login
from ownstack.auth import password_hash
from ownstack.models import ChangeRequest,Document,EngineeringItem,InferenceBudget,Project,TeamAudit,TeamMembership,User,Team
from ownstack.service import utcnow

TEAMS=['Payments','Notifications','Billing','CRM','Deals']
NEEDS={
    'Payments':'Export a PDF reconciliation report for disputed settlements without changing payment capture.',
    'Notifications':'Export a PDF of failed notification deliveries without sending another notification.',
    'Billing':'Export a PDF of a credit-note reconciliation without changing invoice balances.',
    'CRM':'Export a PDF of a customer migration review without changing contact ownership.',
    'Deals':'Export a PDF of a partner renewal review without changing negotiated deal terms.',
}


@pytest.fixture(scope='session')
def team_password():return password_hash('pass')


@pytest.fixture
def organization(client,fixture_db,monkeypatch,team_password):
    monkeypatch.setenv('OWNSTACK_AI_MODE','off')
    admin=login(client,'atlas-admin');teams={}
    for name in TEAMS:
        response=client.post('/v1/teams',headers=admin,json={'name':name})
        assert response.status_code==201,response.text
        teams[name]=response.json()
    with fixture_db() as db:
        for name,team in teams.items():
            slug=name.lower()
            for suffix,role in [('a','engineer'),('b','engineer'),('manager','manager')]:
                user=User(id=slug+'-'+suffix,tenant_id='atlas',role=role,password_hash=team_password,display_name=name+' '+suffix)
                db.add(user);db.flush()
                db.add(TeamMembership(id=str(uuid4()),tenant_id='atlas',team_id=team['id'],user_id=user.id,
                    role='manager' if role=='manager' else 'member'))
            db.add(Document(id=slug+'-brief',tenant_id='atlas',project_id=team['project_id'],title=name+' brief',body=name.upper()+'_PRIVATE_BRIEF'))
        db.commit()
    return {'admin':admin,'teams':teams}


def headers(client,name):return login(client,name)


def create_work(client,organization,name):
    actor=headers(client,name.lower()+'-a');team=organization['teams'][name]
    result=client.post('/v1/requests',headers={**actor,'Idempotency-Key':uuid4().hex},
        json={'text':NEEDS[name],'kind':'feature','project_id':team['project_id']})
    assert result.status_code==201,result.text
    request=result.json()['id']
    result=client.post(f'/v1/requests/{request}/manual-handoff',headers={**actor,'Idempotency-Key':uuid4().hex})
    assert result.status_code==200,result.text
    work=next(row for row in client.get('/v1/engineering',headers=actor).json() if row['request_id']==request)
    return actor,request,work['id']


@pytest.mark.parametrize('team',TEAMS)
def test_peer_and_assigned_manager_can_read_while_other_teams_cannot(client,organization,team):
    author,request,item=create_work(client,organization,team)
    peer=headers(client,team.lower()+'-b');manager=headers(client,team.lower()+'-manager')
    for actor in [author,peer,manager]:
        assert client.get(f'/v1/engineering/{item}',headers=actor).status_code==200
        assert client.get(f'/v1/requests/{request}/proof',headers=actor).status_code==200
        assert [r['id'] for r in client.get('/v1/engineering',headers=actor).json()]==[item]
    other=next(t for t in TEAMS if t!=team)
    for actor in [headers(client,other.lower()+'-a'),headers(client,other.lower()+'-manager')]:
        for path in [f'/v1/engineering/{item}',f'/v1/requests/{request}',f'/v1/evidence/{request}',
            f'/v1/events?request_id={request}',f'/v1/requests/{request}/proof',f'/v1/requests/{request}/attempts',
            f'/v1/engineering/{item}/artifact',f'/v1/assurance/revision-lineage?request_id={request}']:
            response=client.get(path,headers=actor)
            assert response.status_code==404,(path,response.text)
            assert NEEDS[team] not in response.text
        assert client.get('/v1/engineering',headers=actor).json()==[]
        assert client.get('/v1/requests',headers=actor).json()==[]
        assert client.get('/v1/events',headers=actor).json()==[]


def test_administrator_does_not_implicitly_read_other_team_code(client,organization):
    _,request,item=create_work(client,organization,'Payments')
    admin=organization['admin']
    assert client.get(f'/v1/engineering/{item}',headers=admin).status_code==404
    assert client.get('/v1/engineering',headers=admin).json()==[]
    response=client.put(f"/v1/teams/{organization['teams']['Payments']['id']}/members/atlas-admin",headers=admin,
        json={'role':'manager','enabled':True,'expected_revision':0})
    assert response.status_code==200,response.text
    assert client.get(f'/v1/engineering/{item}',headers=admin).status_code==200
    assert client.get(f"/v1/teams/{organization['teams']['Payments']['id']}/audit",headers=admin).json()[0]['subject_id']=='atlas-admin'


def test_manager_with_two_assignments_sees_exact_union_and_has_no_engineer_writes(client,organization):
    _,_,payment=create_work(client,organization,'Payments')
    _,_,billing=create_work(client,organization,'Billing')
    _,_,crm=create_work(client,organization,'CRM')
    response=client.put(f"/v1/teams/{organization['teams']['Billing']['id']}/members/payments-manager",headers=organization['admin'],
        json={'role':'manager','enabled':True,'expected_revision':0})
    assert response.status_code==200
    manager=headers(client,'payments-manager')
    assert {r['id'] for r in client.get('/v1/engineering',headers=manager).json()}=={payment,billing}
    assert client.get(f'/v1/engineering/{crm}',headers=manager).status_code==404
    for action,body in [('draft',None),('verify',None),('decide',{'decision':'take_over'})]:
        assert client.post(f'/v1/engineering/{payment}/{action}',headers=manager,json=body).status_code==403
    assert client.post('/v1/teams',headers=manager,json={'name':'Shadow team'}).status_code==403


def test_membership_revocation_and_transfer_do_not_move_historical_reviews(client,organization):
    author,request,item=create_work(client,organization,'Payments')
    before=client.get('/v1/session',headers=author).json()['scope_version']
    team=organization['teams']['Payments']['id']
    response=client.put(f'/v1/teams/{team}/members/payments-a',headers=organization['admin'],
        json={'role':'member','enabled':False,'expected_revision':1})
    assert response.status_code==200
    assert client.get(f'/v1/engineering/{item}',headers=author).status_code==404
    assert client.get('/v1/session',headers=author).json()['scope_version']!=before
    response=client.put(f"/v1/teams/{organization['teams']['Billing']['id']}/members/payments-a",headers=organization['admin'],
        json={'role':'member','enabled':True,'expected_revision':0})
    assert response.status_code==200
    assert client.get(f'/v1/engineering/{item}',headers=author).status_code==404
    assert client.get(f'/v1/engineering/{item}',headers=headers(client,'payments-b')).status_code==200
    assert client.get(f'/v1/engineering/{item}',headers=headers(client,'billing-a')).status_code==404


def test_manager_member_assignment_is_not_a_management_grant(client,organization):
    _,_,item=create_work(client,organization,'Payments');manager=headers(client,'payments-manager')
    team=organization['teams']['Payments']['id']
    response=client.put(f'/v1/teams/{team}/members/payments-manager',headers=organization['admin'],
        json={'role':'member','enabled':True,'expected_revision':1})
    assert response.status_code==200
    assert client.get(f'/v1/engineering/{item}',headers=manager).status_code==404
    assert client.get('/v1/teams',headers=manager).json()==[]


def test_foreign_team_project_body_cannot_override_authorized_scope(client,organization):
    engineer=headers(client,'payments-a');billing=organization['teams']['Billing']
    base={'text':'Inspect our private reconciliation report','kind':'feature','project_id':billing['project_id']}
    assert client.post('/v1/requests',headers={**engineer,'Idempotency-Key':'wrong-project'},json=base).status_code==404
    base['project_id']=organization['teams']['Payments']['project_id'];base['team_id']=billing['id']
    assert client.post('/v1/requests',headers={**engineer,'Idempotency-Key':'forged-team'},json=base).status_code==422
    assert client.get('/v1/requests',headers=engineer).json()==[]


def test_team_membership_revision_fences_replays_and_audit_is_not_duplicated(client,organization):
    team=organization['teams']['Payments']['id'];admin=organization['admin']
    body={'role':'member','enabled':False,'expected_revision':1}
    assert client.put(f'/v1/teams/{team}/members/payments-a',headers=admin,json=body).status_code==200
    assert client.put(f'/v1/teams/{team}/members/payments-a',headers=admin,json=body).status_code==409
    rows=client.get(f'/v1/teams/{team}/audit',headers=admin).json()
    assert sum(r['action']=='membership_changed' for r in rows)==1


def test_cross_tenant_assignment_and_team_administration_are_rejected(client,organization):
    team=organization['teams']['Payments']['id'];body={'role':'member','enabled':True,'expected_revision':0}
    assert client.put(f'/v1/teams/{team}/members/nova-admin',headers=organization['admin'],json=body).status_code==404
    assert client.put(f'/v1/teams/{team}/members/nova-admin',headers=headers(client,'nova-admin'),json=body).status_code==404
    assert client.get(f'/v1/teams/{team}/audit',headers=headers(client,'billing-a')).status_code==404


@pytest.mark.parametrize('team',TEAMS)
def test_complete_team_access_story_preview_approval_read_and_revoke(client,fixture_db,organization,team):
    info=organization['teams'][team];engineer=headers(client,team.lower()+'-a');admin=organization['admin']
    assert client.put(f"/v1/teams/{info['id']}/members/atlas-admin",headers=admin,
        json={'role':'manager','enabled':True,'expected_revision':0}).status_code==200
    created=client.post('/v1/requests',headers={**engineer,'Idempotency-Key':uuid4().hex},json={
        'text':f'Give atlas-contractor read-only access to {team} until the selected expiry.',
        'kind':'access','project_id':info['project_id'],'viewer_id':'atlas-contractor',
        'expires_at':(utcnow()+timedelta(hours=1)).isoformat()})
    assert created.status_code==201,created.text
    request=created.json()['id']
    prepared=client.post(f'/v1/requests/{request}/manual-handoff',headers={**engineer,'Idempotency-Key':uuid4().hex})
    assert prepared.status_code==200,prepared.text
    proposal=prepared.json()['proposal_id']
    preview=client.post(f'/v1/proposals/{proposal}/preview',headers=admin)
    assert preview.status_code==200 and preview.json()['after'] is True and preview.json()['before'] is False
    contractor=headers(client,'atlas-contractor');path=f"/v1/host/projects/{info['project_id']}/documents/{team.lower()}-brief"
    assert client.get(path,headers=contractor).status_code==403
    subject=client.get(f'/v1/proposals/{proposal}',headers=admin).json()
    approved=client.post(f'/v1/proposals/{proposal}/approve',headers={**admin,'Idempotency-Key':uuid4().hex},json={'proposal_hash':subject['proposal_hash']})
    assert approved.status_code==200,approved.text
    assert client.get(path,headers=contractor).json()['body']==team.upper()+'_PRIVATE_BRIEF'
    other=next(t for t in TEAMS if t!=team);target=organization['teams'][other]
    assert client.get(f"/v1/host/projects/{target['project_id']}/documents/{other.lower()}-brief",headers=contractor).status_code==403
    variation=client.get('/v1/variations',headers=admin).json()[0]['id']
    assert client.post(f'/v1/variations/{variation}/revoke',headers={**admin,'Idempotency-Key':uuid4().hex}).status_code==200
    assert client.get(path,headers=contractor).status_code==403
    assert client.get(f'/v1/requests/{request}/proof',headers=headers(client,team.lower()+'-manager')).status_code==200
    with fixture_db() as db:assert db.get(InferenceBudget,'global').reserved_calls==0


def test_read_reports_people_activity_and_patterns_share_the_same_team_boundary(client,organization):
    author,request,item=create_work(client,organization,'Payments')
    other,foreign_request,foreign_item=create_work(client,organization,'Billing')
    for actor,target in [(author,item),(other,foreign_item)]:
        assert client.post(f'/v1/engineering/{target}/decide',headers=actor,json={'decision':'take_over'}).status_code==200
    manager=headers(client,'payments-manager')
    catalogue=client.get('/v1/assurance/catalogue',headers=manager)
    assert catalogue.status_code==200
    values={'request_id':request,'project_id':organization['teams']['Payments']['project_id'],'viewer_id':'payments-a'}
    for report in catalogue.json():
        params={k:values[k] for k in report['required']}
        response=client.get('/v1/assurance/'+report['key'],headers=manager,params=params)
        assert response.status_code==200,(report['key'],response.text)
        assert foreign_request not in response.text and foreign_item not in response.text
    rows=client.get('/v1/assurance/engineering-review',headers=manager).json()['items']
    assert [r['id'] for r in rows]==[item]
    assert {e['request_id'] for e in client.get('/v1/events',headers=manager).json()}=={request}
    signals=client.get('/v1/convergence',headers=manager).json()
    assert next(s for s in signals if s['need_key']=='pdf-export')['your_tenant_request_count']==1
    teams=client.get('/v1/teams',headers=manager).json()
    assert [t['name'] for t in teams]==['Payments']
    assert {m['user_id'] for m in teams[0]['members']}=={'payments-a','payments-b','payments-manager'}
    mapping=client.get('/v1/workspace-map',headers=manager)
    assert mapping.status_code==200
    assert {p['id'] for p in mapping.json()['nodes'] if p['kind']=='person'}=={'person:payments-a','person:payments-b','person:payments-manager'}
    assert client.get('/v1/members',headers=manager).status_code==403


def test_foreign_team_mutations_fail_before_models_or_runners_can_start(client,organization):
    author,request,item=create_work(client,organization,'Payments');other=headers(client,'billing-a')
    for action,body in [('draft',None),('verify',None),('decide',{'decision':'take_over'}),
        ('manual-patch',{'patch':{'edits':[{'path':'sample_app/report.py','old':'old','new':'new'}]}})]:
        assert client.post(f'/v1/engineering/{item}/{action}',headers=other,json=body).status_code==404
    for action in ['interpret','cancel','manual-handoff']:
        assert client.post(f'/v1/requests/{request}/{action}',headers={**other,'Idempotency-Key':uuid4().hex}).status_code==404
    assert client.get(f'/v1/engineering/{item}',headers=author).json()['status']=='needs_engineer'


def test_current_team_policy_matches_access_preview_and_real_host_denial(client,organization):
    payment=organization['teams']['Payments'];viewer=headers(client,'billing-a');manager=headers(client,'payments-manager')
    preview=client.get(f"/v1/host/projects/{payment['project_id']}/access-review",headers=manager,params={'viewer_id':'billing-a'})
    assert preview.status_code==200 and preview.json()['allowed'] is False and preview.json()['basis']=='team_scope'
    assert client.get(f"/v1/host/projects/{payment['project_id']}/documents/payments-brief",headers=viewer).status_code==403
    assert client.get(f"/v1/host/projects/{payment['project_id']}/documents/payments-brief",headers=manager).status_code==200
    observed=client.get('/v1/host-observations',headers=manager).json()
    assert any(r['actor_id']=='billing-a' and not r['allowed'] and r['basis']=='team_scope' for r in observed)


def test_request_idempotency_is_not_a_cross_actor_or_revoked_scope_backdoor(client,organization):
    actor=headers(client,'payments-a');peer=headers(client,'payments-b');team=organization['teams']['Payments']
    body={'text':NEEDS['Payments'],'kind':'feature','project_id':team['project_id']};key='same-customer-intent'
    first=client.post('/v1/requests',headers={**actor,'Idempotency-Key':key},json=body)
    assert first.status_code==201
    assert client.post('/v1/requests',headers={**actor,'Idempotency-Key':key},json=body).json()==first.json()
    assert client.post('/v1/requests',headers={**peer,'Idempotency-Key':key},json=body).status_code==409
    assert client.put(f"/v1/teams/{team['id']}/members/payments-a",headers=organization['admin'],
        json={'role':'member','enabled':False,'expected_revision':1}).status_code==200
    assert client.post('/v1/requests',headers={**actor,'Idempotency-Key':key},json=body).status_code==404
    assert [r['id'] for r in client.get('/v1/requests',headers=peer).json()]==[first.json()['id']]


def test_manager_invitation_grants_only_its_explicit_team(client,organization):
    _,request,item=create_work(client,organization,'Payments');billing=organization['teams']['Billing']
    invite=client.post('/v1/accounts/invitations',headers=organization['admin'],json={'role':'manager','team_id':billing['id'],'days':2})
    assert invite.status_code==201
    token=invite.json()['token'];client.cookies.clear()
    inspection=client.post('/v1/accounts/invitations/inspect',json={'token':token})
    assert inspection.status_code==200 and inspection.json()['team']=='Billing'
    joined=client.post('/v1/accounts/join',json={'token':token,'username':'billing-invited-manager','name':'Invited billing lead','password':'Synthetic-manager-pass-2026!'})
    assert joined.status_code==201,joined.text
    assert [t['id'] for t in joined.json()['teams']]==[billing['id']]
    manager={'Authorization':'Bearer '+joined.json()['token']}
    assert client.get(f'/v1/engineering/{item}',headers=manager).status_code==404
    client.cookies.clear()
    assert client.post('/v1/accounts/join',json={'token':token,'username':'billing-invited-again','name':'Second attempt','password':'Synthetic-manager-pass-2026!'}).status_code==404


def test_malformed_team_project_binding_fails_closed_for_both_teams(client,fixture_db,organization):
    author,request,item=create_work(client,organization,'Payments')
    with fixture_db() as db:
        db.get(ChangeRequest,request).team_id=organization['teams']['Billing']['id'];db.commit()
    for actor in [author,headers(client,'billing-a'),headers(client,'payments-manager')]:
        assert client.get(f'/v1/engineering/{item}',headers=actor).status_code==404
        assert client.get('/v1/engineering',headers=actor).json()==[]


def test_shared_teammate_is_one_identity_with_multiple_team_connections(client,organization):
    team=organization['teams']['Billing']
    assert client.put(f"/v1/teams/{team['id']}/members/payments-manager",headers=organization['admin'],
        json={'role':'manager','enabled':True,'expected_revision':0}).status_code==200
    rows=client.get('/v1/workspace-map',headers=headers(client,'payments-manager')).json()['nodes']
    people=[r for r in rows if r['id']=='person:payments-manager']
    assert len(people)==1 and len(people[0]['parents'])==2
    assert {r['title'] for r in rows if r['kind']=='team'}=={'Payments','Billing'}


def test_membership_restore_does_not_reenable_a_disabled_account(client,organization):
    engineer=headers(client,'payments-a');admin=organization['admin'];team=organization['teams']['Payments']
    assert client.post('/v1/members/payments-a/access',headers=admin,json={'enabled':False}).status_code==200
    assert client.put(f"/v1/teams/{team['id']}/members/payments-a",headers=admin,
        json={'role':'member','enabled':True,'expected_revision':1}).status_code==200
    assert client.get('/v1/session',headers=engineer).status_code==401


def test_identical_team_names_in_different_organizations_are_not_authority(client,organization):
    _,request,item=create_work(client,organization,'Payments');nova=headers(client,'nova-admin')
    other=client.post('/v1/teams',headers=nova,json={'name':'Payments'})
    assert other.status_code==201
    assert client.put(f"/v1/teams/{other.json()['id']}/members/nova-admin",headers=nova,
        json={'role':'manager','enabled':True,'expected_revision':0}).status_code==200
    assert client.get(f'/v1/engineering/{item}',headers=nova).status_code==404
    assert client.get('/v1/engineering',headers=nova).json()==[]
    payment=organization['teams']['Payments'];actor=headers(client,'payments-a')
    request=client.post('/v1/requests',headers={**actor,'Idempotency-Key':uuid4().hex},json={
        'text':'Give atlas-contractor read-only access to Payments until the selected expiry.',
        'kind':'access','project_id':payment['project_id'],'viewer_id':'atlas-contractor',
        'expires_at':(utcnow()+timedelta(hours=1)).isoformat()})
    assert request.status_code==201
    handoff=client.post('/v1/requests/'+request.json()['id']+'/manual-handoff',headers={**actor,'Idempotency-Key':uuid4().hex})
    assert handoff.status_code==200,handoff.text
    proposal=client.get('/v1/proposals/'+handoff.json()['proposal_id'],headers=actor)
    assert proposal.json()['route']=='configure'


def test_project_name_substring_is_not_an_explicit_access_target(client,organization):
    """Selecting Data must not turn a request for Metadata into a grant."""
    admin=organization['admin']
    team=client.post('/v1/teams',headers=admin,json={'name':'Data'}).json()
    assert client.put(f"/v1/teams/{team['id']}/members/payments-a",headers=admin,
        json={'role':'member','enabled':True,'expected_revision':0}).status_code==200
    actor=headers(client,'payments-a')
    request=client.post('/v1/requests',headers={**actor,'Idempotency-Key':uuid4().hex},json={
        'text':'Give atlas-contractor read-only access to Metadata until the selected expiry.',
        'kind':'access','project_id':team['project_id'],'viewer_id':'atlas-contractor',
        'expires_at':(utcnow()+timedelta(hours=1)).isoformat()})
    assert request.status_code==201
    result=client.post('/v1/requests/'+request.json()['id']+'/manual-handoff',headers={**actor,'Idempotency-Key':uuid4().hex})
    assert result.status_code==200
    proposal=client.get('/v1/proposals/'+result.json()['proposal_id'],headers=actor).json()
    assert proposal['route']=='refuse'


@pytest.mark.parametrize('name',['Credit','Administration'])
def test_project_name_is_data_not_an_action_keyword(client,organization,name):
    admin=organization['admin'];team=client.post('/v1/teams',headers=admin,json={'name':name}).json()
    client.put(f"/v1/teams/{team['id']}/members/payments-a",headers=admin,
        json={'role':'member','enabled':True,'expected_revision':0})
    actor=headers(client,'payments-a')
    for suffix,route in [('', 'configure'),(' and export a PDF', 'refuse'),(' and modify documents', 'refuse')]:
        result=client.post('/v1/requests',headers={**actor,'Idempotency-Key':uuid4().hex},json={
            'text':f'Give atlas-contractor read-only access to {name} until the selected expiry'+suffix,
            'kind':'access','project_id':team['project_id'],'viewer_id':'atlas-contractor',
            'expires_at':(utcnow()+timedelta(hours=1)).isoformat()})
        assert result.status_code==201
        handoff=client.post('/v1/requests/'+result.json()['id']+'/manual-handoff',headers={**actor,'Idempotency-Key':uuid4().hex})
        assert handoff.status_code==200
        assert client.get('/v1/proposals/'+handoff.json()['proposal_id'],headers=actor).json()['route']==route


def test_overlapping_membership_updates_have_one_winner_and_one_audit(client,fixture_db,organization,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi.testclient import TestClient
    from ownstack.api import app
    import ownstack.teams as module
    barrier=Barrier(2);original=module.membership;team=organization['teams']['Payments']
    def aligned(row):
        if row.user_id=='payments-a' and row.revision==1:barrier.wait(timeout=10)
        return original(row)
    monkeypatch.setattr(module,'membership',aligned)
    def update(body):
        with TestClient(app) as connection:
            return connection.put(f"/v1/teams/{team['id']}/members/payments-a",headers=organization['admin'],json=body).status_code
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures=[workers.submit(update,body) for body in [
            {'role':'member','enabled':False,'expected_revision':1},
            {'role':'manager','enabled':True,'expected_revision':1}]]
        assert sorted(f.result() for f in futures)==[200,409]
    with fixture_db() as db:
        row=db.scalar(select(TeamMembership).where(TeamMembership.team_id==team['id'],TeamMembership.user_id=='payments-a'))
        assert row.revision==2
        assert len(db.scalars(select(TeamAudit).where(TeamAudit.team_id==team['id'],TeamAudit.action=='membership_changed')).all())==1


def test_completed_check_is_saved_for_team_but_not_returned_to_a_revoked_actor(client,fixture_db,organization,monkeypatch):
    from ownstack.patch_agent import fixture_patch
    from ownstack.runner import patch_hash
    actor,request,item=create_work(client,organization,'Payments');candidate=fixture_patch()
    saved=client.post(f'/v1/engineering/{item}/manual-patch',headers=actor,json={'patch':candidate})
    assert saved.status_code==200,saved.text
    def independent_test_double(patch):
        with fixture_db() as db:
            db.scalar(select(TeamMembership).where(TeamMembership.user_id=='payments-a')).enabled=False;db.commit()
        return {'passed':False,'patch_hash':patch_hash(patch),'stdout':'PRIVATE_CHECK_RESULT','stderr':'Explicit test-double failure','runner':'explicit-test-double','exit_code':1}
    monkeypatch.setattr('ownstack.api.run_verifier',independent_test_double)
    response=client.post(f'/v1/engineering/{item}/verify',headers=actor)
    assert response.status_code==404 and 'PRIVATE_CHECK_RESULT' not in response.text
    peer=client.get(f'/v1/engineering/{item}',headers=headers(client,'payments-b'))
    assert peer.status_code==200 and peer.json()['status']=='checks_failed'
    assert peer.json()['checks'][0]['result']['stdout']=='PRIVATE_CHECK_RESULT'
    with fixture_db() as db:assert db.get(InferenceBudget,'global').reserved_calls==0
