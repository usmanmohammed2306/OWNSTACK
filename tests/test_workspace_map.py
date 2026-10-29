from datetime import datetime,timedelta,timezone
import pytest
from ownstack.models import EngineeringItem,ChangeRequest,HostObservation,User,Variation
from conftest import login
from test_access_review import approved_grant

def test_admin_membership_map_is_tenant_local_and_not_an_access_observation(client,fixture_db):
    response=client.get('/v1/workspace-map',headers=login(client,'atlas-admin'));assert response.status_code==200
    data=response.json();assert data['as_of'] and not data['truncated']
    people=[r for r in data['nodes'] if r['kind']=='person']
    assert {r['id'] for r in people}=={'person:atlas-admin','person:atlas-engineer','person:atlas-contractor'}
    assert all('nova' not in str(r).lower() for r in data['nodes'])
    contractor=next(r for r in people if r['id']=='person:atlas-contractor')
    assert contractor['parents'] and contractor['parents'][0].startswith('team:') and contractor['details'][0]['allowed'] is False
    with fixture_db() as db:assert not db.query(HostObservation).all()

def test_engineer_gets_assigned_teammates_not_a_tenant_wide_directory(client):
    data=client.get('/v1/workspace-map',headers=login(client,'atlas-engineer')).json()
    assert {r['id'] for r in data['nodes'] if r['kind']=='person'}=={'person:atlas-admin','person:atlas-contractor','person:atlas-engineer'}
    assert len([r for r in data['nodes'] if r['kind']=='team'])==1

@pytest.mark.parametrize('name',['atlas-contractor','platform-owner'])
def test_unprivileged_map_access_denied(client,name):
    assert client.get('/v1/workspace-map',headers=login(client,name)).status_code==403

def test_disabled_and_expired_permissions_do_not_appear_allowed(client,fixture_db):
    admin,grant=approved_grant(client,fixture_db)
    with fixture_db() as db:
        user=db.get(User,'atlas-engineer');user.enabled=False
        db.get(Variation,grant).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
        db.commit()
    data=client.get('/v1/workspace-map',headers=admin).json()
    for node in data['nodes']:
        if node['id'] in {'person:atlas-engineer','person:atlas-contractor'}:assert not node['details'][0]['allowed']

def test_code_thumbnail_identifies_requester_without_inventing_authorship(client,fixture_db):
    with fixture_db() as db:
        db.add(ChangeRequest(id='r1',tenant_id='atlas',requester_id='atlas-admin',kind='feature',text='Add PDF export'))
        db.add(ChangeRequest(id='r2',tenant_id='nova',requester_id='nova-admin',kind='feature',text='NOVA PRIVATE'))
        db.flush()
        for i,tenant,req in [('one','atlas','r1'),('two','nova','r2')]:
            db.add(EngineeringItem(id=i,tenant_id=tenant,request_id=req,patch={'edits':[{'path':'sample_app/app.py','old':'old','new':tenant+' source'}]}))
        db.commit()
    rows=client.get('/v1/engineering',headers=login(client,'atlas-admin')).json()
    assert len(rows)==1 and rows[0]['requested_by']=='atlas-admin'
    assert rows[0]['thumbnail']=={'path':'sample_app/app.py','code':'atlas source'}
    assert 'author' not in rows[0]
    assert client.get('/v1/engineering',headers=login(client,'atlas-contractor')).status_code==403
