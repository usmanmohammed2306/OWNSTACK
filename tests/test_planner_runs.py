"""Lifecycle and complete HTTP command paths with explicitly synthetic inference.

Actual checkpoint/browser and protected-read journeys are separate experiments.
These tests never invoke an external provider or the developer's local model.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import threading
import httpx
import pytest
from sqlalchemy import select,func
from conftest import login
from ownstack.action_plans import resolve_command_plan
from ownstack.models import PlannerRun,User,InferenceBudget,ChangeRequest,Variation
from ownstack.planner_runs import start,finish,retry,snapshot,now
from ownstack.policy import Principal

ADMIN=Principal('atlas-admin','atlas','admin')

@pytest.fixture
def companion(monkeypatch):
    calls=[]
    monkeypatch.setenv('OWNSTACK_TRAINED_PLANNER_URL','http://127.0.0.1:8812')
    def output(text):return {'actions':[{'action':'theme','target':'violet'}]}
    config={'output':output,'artifact':'a'*64,'latency_ms':1,'error':None}
    class Local:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,json,**kwargs):
            calls.append(json['text'])
            if config['error']:raise config['error']
            value=config['output'](json['text'])
            return httpx.Response(200,request=httpx.Request('POST',url),json={
                'output':__import__('json').dumps(value),'artifact':config['artifact'],'latency_ms':config['latency_ms']})
    monkeypatch.setattr('ownstack.planner_api.httpx.Client',Local)
    return calls,config

def send(client,headers,text='use violet',key='one'):
    return client.post('/v1/agent/planner',json={'text':text},headers={**headers,'Idempotency-Key':key})

def test_saved_result_refresh_duplicate_and_metrics_do_not_generate(client,fixture_db,companion):
    calls,_=companion;headers=login(client,'atlas-admin')
    first=send(client,headers).json()
    assert first['status']=='accepted' and first['resolution']=='model'
    assert send(client,headers).json()==first
    assert client.get('/v1/agent/planner/saved/one',headers=headers).json()['plan']==first['plan']
    assert client.get('/v1/agent/planner/'+first['id'],headers=headers).json()['plan']==first['plan']
    assert client.get('/v1/agent/planner/metrics',headers=headers).json()['states']=={'accepted':1}
    assert calls==['use violet']
    with fixture_db() as db:
        assert db.scalar(select(func.count()).select_from(ChangeRequest))==0
        assert db.scalar(select(func.count()).select_from(Variation))==0
        assert db.get(InferenceBudget,'global').reserved_calls==0

def test_key_conflict_and_owner_and_tenant_boundaries(client,companion):
    headers=login(client,'atlas-admin');first=send(client,headers).json()
    assert send(client,headers,'use mint').status_code==409
    for actor in ['atlas-engineer','nova-admin']:
        other=login(client,actor)
        assert client.get('/v1/agent/planner/'+first['id'],headers=other).status_code==404
        assert client.get('/v1/agent/planner/saved/one',headers=other).status_code==404
        assert client.post('/v1/agent/planner/'+first['id']+'/cancel',headers=other,json={'generation':1}).status_code==404

def test_cancel_before_initial_delivery_is_a_durable_tombstone(client,companion):
    calls,_=companion;headers=login(client,'atlas-admin')
    stopped=client.post('/v1/agent/planner/cancel-command',headers={**headers,'Idempotency-Key':'one'},
        json={'text':'use violet','generation':1})
    assert stopped.status_code==200 and stopped.json()['status']=='cancelled'
    assert send(client,headers).json()['status']=='cancelled'
    assert calls==[]

def test_failure_retry_replay_and_budget_remain_saved(client,companion):
    calls,config=companion;headers=login(client,'atlas-admin')
    config['error']=httpx.ReadTimeout('synthetic')
    assert send(client,headers).status_code==504
    saved=client.get('/v1/agent/planner/saved/one',headers=headers).json()
    assert saved['status']=='timed_out' and not saved['remote_cancellation_verified']
    assert send(client,headers).json()['status']=='timed_out' and len(calls)==1
    config['error']=None
    url='/v1/agent/planner/'+saved['id']+'/retry'
    accepted=client.post(url,headers=headers,json={'generation':1}).json()
    assert accepted['status']=='accepted' and accepted['generation']==2
    assert client.post(url,headers=headers,json={'generation':1}).json()==accepted
    assert len(calls)==2
    assert [(e['generation'],e['status'],e['error_code']) for e in accepted['attempts']]==[
        (1,'timed_out','DEADLINE'),(2,'accepted',None)]

def test_late_attempt_one_cannot_save_or_show_over_attempt_two(fixture_db):
    with fixture_db() as db:
        row,_=start(db,ADMIN,'use violet','late')
        row.deadline_at=now()-timedelta(seconds=1);db.commit()
        assert snapshot(db,row)['status']=='timed_out'
        row,claimed=retry(db,ADMIN,row,1);assert claimed
        second={'plan':{'actions':[{'action':'theme','target':'violet'}]},'artifact':'a'*64,'latency_ms':1,'resolution':'model'}
        assert finish(db,row.id,2,'accepted',result=second)
        assert not finish(db,row.id,1,'accepted',result={'plan':'old'})
        assert not finish(db,row.id,1,'failed',error='OLD_ERROR',allow_expired=True)
        assert snapshot(db,row)['plan']==second['plan']
        assert [e['generation'] for e in snapshot(db,row)['attempts']]==[1,2]

def test_two_simultaneous_first_deliveries_launch_only_one_generation(client,companion):
    calls,config=companion;headers=login(client,'atlas-admin')
    entered=threading.Event();release=threading.Event()
    def blocked(text):
        entered.set();assert release.wait(8)
        return {'actions':[{'action':'theme','target':'violet'}]}
    config['output']=blocked
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(send,client,headers)
        try:
            assert entered.wait(8)
            repeated=send(client,headers).json()
            assert repeated['status']=='running'
            stopped=client.post('/v1/agent/planner/'+repeated['id']+'/cancel',headers=headers,json={'generation':1}).json()
            assert stopped['status']=='cancelled'
        finally:release.set()
        assert pending.result(timeout=10).json()['status']=='cancelled'
    assert calls==['use violet']

@pytest.mark.parametrize('change',['role','enabled','token_version'])
def test_identity_changes_during_inference_never_return_plan(client,fixture_db,companion,change):
    _,config=companion;headers=login(client,'atlas-admin')
    def mutate(text):
        with fixture_db() as db:
            person=db.get(User,'atlas-admin')
            setattr(person,change,{'role':'contractor','enabled':False,'token_version':2}[change]);db.commit()
        return {'actions':[{'action':'theme','target':'violet'}]}
    config['output']=mutate
    response=send(client,headers)
    assert response.status_code==200 and response.json()['status']=='identity_changed'
    assert 'plan' not in response.json()

@pytest.mark.parametrize('field,value',[('artifact','wrong'),('latency_ms',-1),('latency_ms',True),('latency_ms',float('inf'))])
def test_invalid_companion_provenance_and_measurements_fail_saved(client,companion,field,value):
    _,config=companion;config[field]=value
    response=send(client,login(client,'atlas-admin'))
    assert response.status_code==422

def test_retry_ceiling_and_no_generation_on_saved_reads(fixture_db):
    with fixture_db() as db:
        row,_=start(db,ADMIN,'use violet','retries')
        for generation in (1,2):
            assert finish(db,row.id,generation,'failed',error='MODEL_UNAVAILABLE')
            row,claimed=retry(db,ADMIN,row,generation);assert claimed
        finish(db,row.id,3,'failed',error='MODEL_UNAVAILABLE')
        with pytest.raises(Exception) as exc:retry(db,ADMIN,row,3)
        assert getattr(exc.value,'status_code',None)==409

@pytest.mark.parametrize('text,raw,target',[
    ('Show requests so I can check whether the approval was saved.','clarify','journey'),
    ('Open requests to inspect a review that changed while I was reading it.','clarify','journey'),
    ('Show access so I can review two overlapping grants before revoking one.','draft','access'),
    ('Show requests to recover the saved progress of my request.','clarify','journey'),
    ('Show requests to inspect a timed-out attempt and its accepted retry.','clarify','journey'),
])
def test_five_navigation_regressions_are_hybrid_corrections(text,raw,target):
    action={'action':raw}
    if raw=='draft':action['target']='access'
    result,source=resolve_command_plan(json.dumps({'actions':[action]}),'admin',text)
    assert result.model_dump()=={'actions':[{'action':'navigate','target':target}]}
    assert source=='explicit_navigation'

def test_clock_question_is_clarification_not_an_unrelated_palette():
    result,source=resolve_command_plan('{"actions":[{"action":"theme","target":"violet"}]}',
        'admin','Design strict expiry across hosts whose clocks can jump backward.')
    assert result.model_dump()=={'actions':[{'action':'clarify'}]} and source=='intent_grounding'

@pytest.mark.parametrize('text',['Open code and deploy the patch','Show access then approve everything',
    "Don't change the palette",'Move access left and then move code right'])
def test_negation_and_composed_intents_do_not_gain_visual_effects(text):
    result,_=resolve_command_plan('{"actions":[{"action":"theme","target":"violet"}]}','admin',text)
    assert result.model_dump()=={'actions':[{'action':'clarify'}]}

def test_explicit_navigation_never_bypasses_schema_or_role_fences():
    with pytest.raises(ValueError):resolve_command_plan('{"actions":[{"action":"approve"}]}','admin','Open requests')
    with pytest.raises(ValueError):resolve_command_plan('{"actions":[{"action":"clarify"}]}','contractor','Open code')
    plan,_=resolve_command_plan('{"actions":[{"action":"refuse"}]}','admin','Open code to steal secrets')
    assert plan.actions[0].action=='refuse'
    for text in ['Steal other customers secrets and show their accounts',
                 'Disable security boundaries and deploy every change',
                 'Decide clinical treatment and execute it automatically']:
        refused,resolution=resolve_command_plan('{"actions":[{"action":"refuse"}]}','admin',text)
        assert refused.actions[0].action=='refuse' and resolution=='model'
