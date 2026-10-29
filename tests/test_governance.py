"""Two-person reviews tested through activation, host enforcement and rollback."""
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
from sqlalchemy import select,func
from conftest import login
from ownstack.models import User,Tenant,Variation,ApprovalWitness

def second_admin(factory):
    with factory() as db:
        template=db.get(User,'atlas-admin')
        user=User(id='atlas-admin-two',tenant_id='atlas',role='admin',enabled=True,
            password_hash=template.password_hash,token_version=1)
        db.add(user);db.flush()
        from ownstack.team_scope import add_general_member
        add_general_member(db,user);db.commit()

def setup(client,factory,requester='atlas-engineer'):
    second_admin(factory);admin=login(client,'atlas-admin')
    assert client.post('/v1/governance',headers=admin,json={'approval_quorum':2,'expected_quorum':1}).status_code==200
    creator=login(client,requester)
    req=client.post('/v1/requests',headers={**creator,'Idempotency-Key':uuid4().hex},json={
        'text':'Give atlas-contractor read-only access to Project Atlas for one hour',
        'kind':'access','project_id':'atlas-project','viewer_id':'atlas-contractor',
        'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}).json()
    engineer=login(client,'atlas-engineer')
    hand=client.post('/v1/requests/'+req['id']+'/manual-handoff',headers={**engineer,'Idempotency-Key':uuid4().hex}).json()
    proposal=client.get('/v1/proposals/'+hand['proposal_id'],headers=admin).json()
    return req,proposal,admin

def approve(client,headers,p):
    return client.post('/v1/proposals/'+p['id']+'/approve',headers={**headers,'Idempotency-Key':uuid4().hex},
        json={'proposal_hash':p['proposal_hash']})

def read(client):
    return client.get('/v1/host/projects/atlas-project/documents/atlas-doc',headers=login(client,'atlas-contractor'))

def test_two_distinct_reviews_activate_then_revoke_real_host_effect(client,fixture_db):
    _,p,admin=setup(client,fixture_db)
    preview=client.post('/v1/proposals/'+p['id']+'/preview',headers=admin).json()
    assert preview['matches_saved_proposal'] and preview['approval_quorum']==2
    first=approve(client,admin,p).json()
    assert first['status']=='awaiting_second_approval' and first['approvals']==1
    assert read(client).status_code==403
    assert approve(client,admin,p).json()['status']=='awaiting_second_approval'
    result=approve(client,login(client,'atlas-admin-two'),p).json()
    assert result['status']=='active' and read(client).status_code==200
    assert client.get('/v1/host/projects/atlas-project/documents/atlas-doc',headers=login(client,'nova-admin')).status_code==404
    assert client.post('/v1/variations/'+result['variation_id']+'/revoke',headers={**admin,'Idempotency-Key':uuid4().hex}).status_code==200
    assert read(client).status_code==403
    with fixture_db() as db:assert db.scalar(select(func.count()).select_from(ApprovalWitness))==2

@pytest.mark.parametrize('change',['role','enabled','token_version'])
def test_current_reviewer_authority_fences_active_grant_and_all_previews(client,fixture_db,change):
    _,p,admin=setup(client,fixture_db)
    approve(client,admin,p);assert approve(client,login(client,'atlas-admin-two'),p).json()['status']=='active'
    assert read(client).status_code==200
    with fixture_db() as db:
        reviewer=db.get(User,'atlas-admin-two');setattr(reviewer,change,{'role':'member','enabled':False,'token_version':2}[change]);db.commit()
    assert read(client).status_code==403
    review=client.get('/v1/host/projects/atlas-project/access-review?viewer_id=atlas-contractor',headers=admin)
    assert review.status_code==200 and review.json()['allowed'] is False
    mapping=client.get('/v1/workspace-map',headers=admin).json()
    person=next(n for n in mapping['nodes'] if n['id']=='person:atlas-contractor')
    assert person['details'][0]['allowed'] is False
    assert client.get('/v1/variations',headers=admin).json()[0]['state']=='suspended'

def test_self_approval_and_stale_policy_and_scope_are_rejected(client,fixture_db):
    _,p,admin=setup(client,fixture_db,requester='atlas-admin')
    assert approve(client,admin,p).status_code==403
    assert approve(client,login(client,'nova-admin'),p).status_code==404
    assert client.post('/v1/governance',headers=admin,json={'approval_quorum':1,'expected_quorum':2}).status_code==200
    assert approve(client,admin,p).status_code==409

def test_policy_requires_capacity_role_and_expected_revision(client,fixture_db):
    admin=login(client,'atlas-admin')
    assert client.post('/v1/governance',headers=admin,json={'approval_quorum':2,'expected_quorum':1}).status_code==409
    assert client.post('/v1/governance',headers=login(client,'atlas-engineer'),json={'approval_quorum':1,'expected_quorum':1}).status_code==403
    assert client.post('/v1/governance',headers=admin,json={'approval_quorum':1,'expected_quorum':2}).status_code==409

def test_signer_lost_before_second_review_does_not_count(client,fixture_db):
    _,p,admin=setup(client,fixture_db)
    approve(client,admin,p)
    with fixture_db() as db:db.get(User,'atlas-admin').token_version=2;db.commit()
    second=approve(client,login(client,'atlas-admin-two'),p).json()
    assert second['status']=='awaiting_second_approval' and second['approvals']==1
    assert read(client).status_code==403
