"""Composed customer journeys with explicit provider transport/response doubles.

No test dispatches inference. Actual provider parsing is exercised through
MockTransport; repository execution doubles do not establish code correctness.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import httpx
import pytest
from sqlalchemy import select,func
from test_customer_domains import customer_story,discovery,publish
from test_customer_repositories import register,link
from ownstack.models import InferenceBudget,ReleaseRequirement


@pytest.mark.parametrize('fault',['timeout','tls','429','503','malformed','truncated','injection'])
def test_provider_failure_saved_replay_then_manual_customer_approval(
        client,fixture_db,customer_story,tmp_path,monkeypatch,fault):
    from ownstack import change_agent_model
    from ownstack.config import Settings
    d=customer_story;state,_=discovery(client,d,tmp_path)
    original_client=httpx.Client;original_decide=change_agent_model.decide;calls=[]
    def respond(request):
        calls.append(request.url.path)
        if fault=='timeout':raise httpx.ReadTimeout('Controlled timeout',request=request)
        if fault=='tls':raise httpx.ConnectError('Controlled TLS failure',request=request)
        if fault in {'429','503'}:return httpx.Response(int(fault),json={'error':'controlled outage'})
        if fault=='malformed':return httpx.Response(200,content=b'not-json')
        proposal={'action':'ask','field':'roles','reason':'Choose roles.','citations':['request']}
        if fault=='injection':proposal.update(action='deploy',command='untrusted-command')
        return httpx.Response(200,json={'choices':[{'finish_reason':'length' if fault=='truncated' else 'stop',
            'message':{'role':'assistant','content':json.dumps(proposal)}}]})
    monkeypatch.setattr(httpx,'Client',lambda **kw:original_client(transport=httpx.MockTransport(respond),trust_env=False))
    settings=Settings(ai_mode='nebius',environment='local',max_live_calls=40,
        nebius_key='explicit-offline-placeholder',nebius_model='nvidia/controlled-nemotron-double')
    monkeypatch.setattr(change_agent_model,'decide',lambda s,source,text,_settings:original_decide(s,source,text,settings))
    path='/v1/change-agents/'+state['id']+'/step'
    body={'expected_revision':state['revision'],'idempotency_key':'outage-then-manual'}
    first=client.post(path,headers=d['engineer'],json=body);assert first.status_code==200,first.text
    saved=first.json();assert saved['status']=='failed' and saved['last_decision'] is None
    assert saved['error']=='MODEL_STEP_FAILED' and saved['operation'] is None
    assert client.post(path,headers=d['engineer'],json=body).json()==saved and len(calls)==1
    assert client.get('/v1/change-agents/'+state['id'],headers=d['engineer']).json()['error']=='MODEL_STEP_FAILED'
    prepared=publish(client,d,saved)
    approved=client.post('/v1/change-agents/'+state['id']+'/approve',headers=d['staff'],
        json={'expected_revision':prepared['revision'],'policy_hash':prepared['policy_hash']})
    assert approved.status_code==200,approved.text
    assert approved.json()['status']=='approved'
    assert client.get('/v1/release/requirements-receipt?project_id=atlas-project',headers=d['engineer']).status_code==200
    assert client.get('/v1/customer-portal/requests',headers=d['south_auth']).json()==[]
    public=client.get('/v1/customer-portal/requests',headers=d['north_auth']).json()[0]
    assert public['review_update'] is None and public['released'] is False
    with fixture_db() as db:
        assert db.get(InferenceBudget,'global').reserved_calls==0
        assert db.scalar(select(func.count()).select_from(ReleaseRequirement).where(ReleaseRequirement.state=='approved'))==3


def test_cancel_first_wait_replacement_wins_duplicates_never_dispatch_again(
        client,fixture_db,customer_story,tmp_path,monkeypatch):
    d=customer_story;s,_=discovery(client,d,tmp_path)
    waiting=threading.Event();release=threading.Event();calls=[]
    def model(*args):
        n=len(calls);calls.append(n)
        if n==0:
            waiting.set();assert release.wait(10)
        return {'action':'ask','field':'roles','reason':'replacement accepted' if n else 'old late answer','citations':['request']},{'live':False,'controlled_double':True}
    monkeypatch.setattr('ownstack.change_agent_model.decide',model)
    path='/v1/change-agents/'+s['id']
    first={'expected_revision':s['revision'],'idempotency_key':'attempt-one'}
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(lambda:client.post(path+'/step',headers=d['engineer'],json=first))
        try:
            assert waiting.wait(5)
            saved=client.get(path,headers=d['engineer']).json();assert saved['status']=='running'
            assert client.post(path+'/step',headers=d['engineer'],json=first).json()['status']=='running'
            assert len(calls)==1
            canceled=client.post(path+'/cancel',headers=d['engineer'],json={'expected_revision':saved['revision']})
            assert canceled.status_code==200,canceled.text
            second={'expected_revision':canceled.json()['revision'],'idempotency_key':'attempt-two'}
            accepted=client.post(path+'/step',headers=d['engineer'],json=second)
            assert accepted.status_code==200,accepted.text
            assert accepted.json()['last_decision']['reason']=='replacement accepted'
        finally:release.set()
        assert future.result(timeout=10).status_code==409
    final=client.get(path,headers=d['engineer']).json()
    assert final['last_decision']['reason']=='replacement accepted' and final['operation'] is None
    assert client.post(path+'/step',headers=d['engineer'],json=second).json()['last_decision']==final['last_decision']
    assert len(calls)==2
    with fixture_db() as db:assert db.get(InferenceBudget,'global').reserved_calls==0


@pytest.mark.parametrize('change',['repository','customer','customer-project'])
def test_connected_customer_changes_during_model_wait_discard_late_answer(
        client,customer_story,tmp_path,monkeypatch,change):
    d=customer_story;old,_=discovery(client,d,tmp_path)
    repo=link(client,d,register(client,d,key='connected-ai',kind='python',case_id=None,source_sha256=old['source_sha256']))
    response=client.post('/v1/change-agents',headers=d['engineer'],json={'request_id':old['request_id'],
        'source_sha256':old['source_sha256'],'repository_id':repo['id'],'idempotency_key':'connected-wait'})
    assert response.status_code==201,response.text
    s=response.json()
    def model(*args):
        if change=='repository':
            r=client.post('/v1/repositories/'+repo['id']+'/status',headers=d['engineer'],json={'expected_revision':repo['revision'],'enabled':False})
        else:
            path='/v1/customers/'+d['north']['id']+('/status' if change=='customer' else '/projects')
            extra={} if change=='customer' else {'project_id':'atlas-project'}
            r=client.post(path,headers=d['staff'],json={**extra,'expected_revision':1,'enabled':False})
        assert r.status_code==200,r.text
        return {'action':'ask','field':'roles','reason':'late after revocation','citations':['request']},{'live':False,'controlled_double':True}
    monkeypatch.setattr('ownstack.change_agent_model.decide',model)
    r=client.post('/v1/change-agents/'+s['id']+'/step',headers=d['engineer'],json={'expected_revision':s['revision'],'idempotency_key':'revoked-wait'})
    assert r.status_code in {404,409},r.text
    saved=client.get('/v1/change-agents/'+s['id'],headers=d['engineer'])
    if saved.status_code==200:
        assert saved.json()['last_decision'] is None
        assert saved.json()['needs_fresh_discovery'] is True
