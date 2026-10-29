"""Whole proposal/approval/read flow; model transport is explicitly synthetic here."""
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
from sqlalchemy import select,func
from conftest import login
from test_planner_runs import companion
from ownstack.models import ChangeRequest,Project,Proposal,InferenceBudget,Evidence,User,Variation

def create(client,actor='atlas-engineer',kind='access',text=None):
    h=login(client,actor)
    body={'text':text or ('Give contractor read-only access to Project Atlas for one hour' if kind=='access' else 'Add PDF export to our app'),
        'kind':kind,'project_id':'atlas-project'}
    if kind=='access':body.update(viewer_id='atlas-contractor',expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    r=client.post('/v1/requests',headers={**h,'Idempotency-Key':uuid4().hex},json=body)
    assert r.status_code==201
    return h,r.json()['id']

def test_actual_host_outcome_after_local_intent_is_preview_approve_read_revoke(client,fixture_db,companion):
    calls,cfg=companion;cfg['output']=lambda _: {'actions':[{'action':'draft','target':'access'}]}
    engineer,rid=create(client)
    url=f'/v1/local-agent/requests/{rid}/prepare'
    first=client.post(url,headers=engineer,json={'revision':1});assert first.status_code==200
    pid=first.json()['proposal_id']
    assert client.post(url,headers=engineer,json={'revision':1}).json()['proposal_id']==pid and len(calls)==1
    assert client.get(f'/v1/local-agent/requests/{rid}',headers=engineer).json()['proposal_id']==pid and len(calls)==1
    contractor=login(client,'atlas-contractor');path='/v1/host/projects/atlas-project/documents/atlas-doc'
    assert client.get(path,headers=contractor).status_code==403
    admin=login(client,'atlas-admin');p=client.get('/v1/proposals/'+pid,headers=admin).json()
    assert client.post('/v1/proposals/'+pid+'/preview',headers=admin).json()['matches_saved_proposal']
    grant=client.post('/v1/proposals/'+pid+'/approve',headers={**admin,'Idempotency-Key':'approve-local'},json={'proposal_hash':p['proposal_hash']}).json()
    assert client.get(path,headers=contractor).status_code==200
    assert client.get(path,headers=login(client,'nova-admin')).status_code==404
    assert client.post('/v1/variations/'+grant['variation_id']+'/revoke',headers={**admin,'Idempotency-Key':'revoke-local'}).status_code==200
    assert client.get(path,headers=contractor).status_code==403
    with fixture_db() as db:
        assert db.get(InferenceBudget,'global').reserved_calls==0
        assert db.scalar(select(Evidence).where(Evidence.request_id==rid,Evidence.kind=='local_agent_intent')).result['inference_location']=='local'

@pytest.mark.parametrize('kind,target',[('feature','access'),('feature','feature'),('access','feature')])
def test_feature_never_becomes_access_and_unsupported_work_reaches_engineering(client,companion,kind,target):
    _,cfg=companion;cfg['output']=lambda _: {'actions':[{'action':'draft','target':target}]}
    h,rid=create(client,kind=kind)
    p=client.post(f'/v1/local-agent/requests/{rid}/prepare',headers=h,json={'revision':1}).json()
    assert client.get('/v1/proposals/'+p['proposal_id'],headers=h).json()['route']=='engineering'

@pytest.mark.parametrize('actor,status',[('atlas-contractor',403),('nova-admin',404)])
def test_role_and_tenant_fences_run_before_model(client,companion,actor,status):
    calls,_=companion;_,rid=create(client)
    assert client.post(f'/v1/local-agent/requests/{rid}/prepare',headers=login(client,actor),json={'revision':1}).status_code==status
    assert calls==[]

def test_stale_intent_during_generation_cannot_prepare_new_effect(client,fixture_db,companion):
    _,cfg=companion;h,rid=create(client)
    def mutate(_):
        with fixture_db() as db:db.get(ChangeRequest,rid).text='Changed request without a revision bump';db.commit()
        return {'actions':[{'action':'draft','target':'access'}]}
    cfg['output']=mutate
    assert client.post(f'/v1/local-agent/requests/{rid}/prepare',headers=h,json={'revision':1}).status_code==409
    with fixture_db() as db:assert db.scalar(select(func.count()).select_from(Proposal))==0

def test_unrelated_plan_and_model_refusal_never_create_a_grant(client,fixture_db,companion):
    _,rid=create(client);h=login(client,'atlas-engineer')
    result=client.post(f'/v1/local-agent/requests/{rid}/prepare',headers=h,json={'revision':1})
    assert result.status_code==422
    with fixture_db() as db:assert db.scalar(select(func.count()).select_from(Proposal))==0

def test_exact_revision_extra_fields_and_production_fail_before_generation(client,companion,monkeypatch):
    calls,_=companion;h,rid=create(client)
    url=f'/v1/local-agent/requests/{rid}/prepare'
    assert client.post(url,headers=h,json={'revision':2}).status_code==409
    assert client.post(url,headers=h,json={'revision':1,'approve':True}).status_code==422
    monkeypatch.setenv('OWNSTACK_ENV','production')
    # Use the gate directly because production correctly rejects local bearer tokens.
    from ownstack.local_agent import gate
    from ownstack.policy import Principal
    with pytest.raises(Exception) as exc:gate(Principal('atlas-engineer','atlas','engineer'))
    assert getattr(exc.value,'status_code',None)==503 and calls==[]

def test_disabled_viewer_is_refused_before_an_allowed_preview_or_approval(client,fixture_db,companion):
    _,cfg=companion;cfg['output']=lambda _: {'actions':[{'action':'draft','target':'access'}]}
    h,rid=create(client)
    with fixture_db() as db:db.get(User,'atlas-contractor').enabled=False;db.commit()
    result=client.post(f'/v1/local-agent/requests/{rid}/prepare',headers=h,json={'revision':1})
    assert result.status_code==200
    pid=result.json()['proposal_id']
    proposal=client.get('/v1/proposals/'+pid,headers=h).json()
    assert proposal['route']=='refuse' and proposal['preview_hash'] is None
    assert client.post('/v1/proposals/'+pid+'/approve',headers={**login(client,'atlas-admin'),
        'Idempotency-Key':'disabled-approval'},json={'proposal_hash':proposal['proposal_hash']}).status_code==409
    with fixture_db() as db:assert db.scalar(select(func.count()).select_from(Variation))==0
