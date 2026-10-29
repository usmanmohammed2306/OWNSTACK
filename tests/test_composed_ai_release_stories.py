"""Composed customer/control journeys, with explicit HTTP and execution doubles.

Actual Docker/upstream proof is a separate dated campaign. No test uses credits.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import hashlib,json,threading
from pathlib import Path
from uuid import uuid4
import httpx
import pytest
from sqlalchemy import select
from conftest import login
from test_customer_domains import customer_story,submit,publish
from ownstack.models import InferenceBudget,ReleaseCheck,ReleaseAudit,Project,User
from ownstack.release_repository import initialize
from ownstack.release_assurance import claim_next,finish_check,audit
from test_release_journeys import explicit_result_double

ROOT=Path(__file__).resolve().parents[1]
BASE=(ROOT/'examples/counterexample_workspace/customer_policy.py').read_text()
CANDIDATE=BASE.replace("data['assigned'] and ",'')


@pytest.fixture
def repair_story(client,fixture_db,customer_story,tmp_path):
    d=customer_story;submission=submit(client,d['north_auth']).json()
    r=client.post('/v1/customers/inbox/'+submission['id']+'/adopt',headers=d['engineer']);assert r.status_code==200
    request_id=r.json()['request_id'];app=tmp_path/'source';app.mkdir()
    (app/'serve.py').write_text('pass\n');(app/'policy.py').write_text(BASE)
    source=initialize(app,name='Explicit control fixture',entrypoint='serve.py',include=['serve.py','policy.py'])
    r=client.post('/v1/release/sources',headers=d['engineer'],json={'project_id':'atlas-project','label':'Reviewed source','snapshot':source});assert r.status_code==201
    r=client.post('/v1/requests/'+request_id+'/code-context',headers=d['engineer'],json={'expected_revision':1,'files':{'policy.py':BASE}});assert r.status_code==200
    r=client.post('/v1/change-agents',headers=d['engineer'],json={'request_id':request_id,'source_sha256':source['sha256'],'idempotency_key':'composed-ai-discovery'});assert r.status_code==201
    s=publish(client,d,r.json())
    r=client.post('/v1/change-agents/'+s['id']+'/approve',headers=d['staff'],json={'expected_revision':s['revision'],'policy_hash':s['policy_hash']});assert r.status_code==200
    s=r.json();queued=client.post('/v1/release/checks',headers=d['engineer'],json={'project_id':'atlas-project','baseline_sha256':source['sha256'],
        'candidate_sha256':'b'*64,'requirement_ids':s['requirement_ids'],'idempotency_key':'composed-failed-candidate'});assert queued.status_code==202
    ident=queued.json()['id'];claim=claim_next(fixture_db,only_id=ident);assert claim
    report=explicit_result_double(claim,candidate_ok=False)
    report['candidate_snapshot']={'files':{'policy.py':hashlib.sha256(CANDIDATE.encode()).hexdigest()},'config':{'entrypoint':'serve.py'}}
    assert finish_check(fixture_db,ident,claim['claim_token'],report)
    with fixture_db() as db:assert db.get(ReleaseCheck,ident).state=='regression'
    return {**d,'state':s,'submission':submission,'source':source,'check_id':ident,
        'path':'/v1/change-agents/'+s['id'],'body':{'expected_revision':s['revision'],'check_id':ident,'files':{'policy.py':CANDIDATE},'idempotency_key':'repair-attempt-one'}}


def manual_finish(client,factory,d):
    """Finish the control journey with an explicit executor double, not real code."""
    s=d['state'];r=client.post('/v1/release/checks',headers=d['engineer'],json={'project_id':'atlas-project','baseline_sha256':d['source']['sha256'],
        'candidate_sha256':'c'*64,'requirement_ids':s['requirement_ids'],'idempotency_key':'human-corrected-'+uuid4().hex});assert r.status_code==202,r.text
    ident=r.json()['id'];claim=claim_next(factory,only_id=ident);assert claim
    assert finish_check(factory,ident,claim['claim_token'],explicit_result_double(claim))
    with factory() as db:
        audit(db,db.get(Project,'atlas-project'),s['id'],'agent.counterexample_completed',result={'check_id':ident,'source_diff':'Explicit executor-double diff, not actual repository execution'})
        db.commit()
    path=d['path']+'/checks/'+ident+'/review';review=client.get(path,headers=d['engineer']);assert review.status_code==200
    review=review.json();body={'expected_revision':review['revision'],'evidence_hash':review['evidence_hash'],'comment':'Explicit control-plane recovery test; no live model or execution proof.',
        'decision':'accept_for_manual_release','idempotency_key':'exact-human-review'}
    assert client.post(path,headers=d['engineer'],json=body).status_code==200
    share='/v1/customers/inbox/'+d['submission']['id']+'/share-review'
    assert client.post(share,headers=d['engineer'],json={'discovery_id':s['id'],'check_id':ident,'evidence_hash':review['evidence_hash']}).status_code==200
    public=client.get('/v1/customer-portal/requests',headers=d['north_auth']).json()[0]
    assert public['review_update'] and not public['released'] and 'source_diff' not in public
    assert client.get('/v1/customer-portal/requests',headers=d['south_auth']).json()==[]
    with factory() as db:assert db.get(InferenceBudget,'global').reserved_calls==0


@pytest.mark.parametrize('fault',['timeout','tls','429','503','malformed','truncated','tool-call','markdown','syntax','response-fields','path-escape','no-change'])
def test_repair_transport_failure_then_exact_manual_customer_review(client,fixture_db,repair_story,monkeypatch,fault):
    from ownstack import change_agent_model
    from ownstack.config import Settings
    d=repair_story;original=change_agent_model.propose_patch;calls=[]
    def respond(request):
        calls.append(request.url.path)
        if fault=='timeout':raise httpx.ReadTimeout('Controlled provider timeout',request=request)
        if fault=='tls':raise httpx.ConnectError('Controlled certificate/connection failure',request=request)
        if fault in {'429','503'}:return httpx.Response(int(fault),json={'error':'Controlled outage'})
        if fault=='malformed':return httpx.Response(200,content=b'not-json')
        source=BASE
        if fault=='syntax':source='def read(:\n'
        if fault=='no-change':source=CANDIDATE
        if fault=='response-fields':source=BASE.replace("{'id': data['resource_id'], 'title': 'Synthetic project brief'}","{k:data[k] for k in ('id','title') if k in data}")
        content=json.dumps({'files':[{'path':'../outside.py' if fault=='path-escape' else 'policy.py','lines':source.splitlines()}]})
        if fault=='markdown':content='```json\n'+content+'\n```'
        message={'role':'assistant','content':content}
        if fault=='tool-call':message['tool_calls']=[{'function':{'name':'deploy'}}]
        return httpx.Response(200,json={'choices':[{'finish_reason':'length' if fault=='truncated' else 'stop','message':message}]})
    settings=Settings(ai_mode='nebius',environment='local',max_live_calls=40,nebius_key='offline-placeholder',nebius_model='nvidia/offline-nemotron-double')
    monkeypatch.setattr(change_agent_model,'propose_patch',lambda context,_settings:original(context,settings,transport=httpx.MockTransport(respond)))
    path=d['path']+'/patch-proposal';r=client.post(path,headers=d['engineer'],json=d['body']);assert r.status_code==200,r.text
    assert r.json()['status']=='failed' and r.json()['patch'] is None
    assert client.post(path,headers=d['engineer'],json=d['body']).json()==r.json() and len(calls)==1
    progress=client.get(d['path'],headers=d['engineer']).json();assert progress['operation'] is None and progress['status']=='approved'
    assert not client.get('/v1/customer-portal/requests',headers=d['north_auth']).json()[0]['review_update']
    manual_finish(client,fixture_db,d)


def good_patch():return {'edits':[{'path':'policy.py','old':CANDIDATE,'new':BASE}]},{'live':False,'origin':'explicit controlled repair'}


def test_late_repair_timeout_clears_only_its_own_saved_operation(client,fixture_db,repair_story,monkeypatch):
    from ownstack import change_agent
    d=repair_story;start=change_agent.utcnow()
    def model(*args):
        monkeypatch.setattr(change_agent,'utcnow',lambda:start+timedelta(minutes=10))
        return good_patch()
    monkeypatch.setattr('ownstack.change_agent_model.propose_patch',model)
    r=client.post(d['path']+'/patch-proposal',headers=d['engineer'],json=d['body']);assert r.status_code==409
    progress=client.get(d['path'],headers=d['engineer']).json()
    assert progress['operation'] is None
    assert progress['status']=='approved' and progress['error']=='LOCAL_WAIT_EXPIRED'
    monkeypatch.setattr(change_agent,'utcnow',lambda:start)
    monkeypatch.setattr('ownstack.change_agent_model.propose_patch',lambda *args:good_patch())
    body={**d['body'],'expected_revision':progress['revision'],'idempotency_key':'explicit-retry-after-timeout'}
    assert client.post(d['path']+'/patch-proposal',headers=d['engineer'],json=body).json()['status']=='proposed'
    manual_finish(client,fixture_db,d)


def test_duplicate_cancel_and_replacement_repair_discards_old_late_patch(client,fixture_db,repair_story,monkeypatch):
    d=repair_story;waiting=threading.Event();release=threading.Event();calls=[]
    def model(*args):
        number=len(calls);calls.append(number)
        if number==0:waiting.set();assert release.wait(10)
        patch,usage=good_patch();return patch,{**usage,'attempt':number+1}
    monkeypatch.setattr('ownstack.change_agent_model.propose_patch',model)
    path=d['path']+'/patch-proposal'
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(lambda:client.post(path,headers=d['engineer'],json=d['body']))
        try:
            assert waiting.wait(5)
            assert client.post(path,headers=d['engineer'],json=d['body']).json()['status']=='running'
            saved=client.get(d['path'],headers=d['engineer']).json()
            r=client.post(d['path']+'/cancel',headers=d['engineer'],json={'expected_revision':saved['revision']});assert r.status_code==200
            second={**d['body'],'expected_revision':r.json()['revision'],'idempotency_key':'replacement-repair-two'}
            result=client.post(path,headers=d['engineer'],json=second);assert result.json()['usage']['attempt']==2
        finally:release.set()
        assert future.result(timeout=10).status_code==409
    assert client.post(path,headers=d['engineer'],json=second).json()==result.json() and len(calls)==2
    assert client.get(d['path'],headers=d['engineer']).json()['operation'] is None
    manual_finish(client,fixture_db,d)


def test_abandoned_expired_wait_is_visible_and_requires_explicit_stop_before_retry(client,fixture_db,repair_story,monkeypatch):
    from ownstack import change_agent
    d=repair_story;start=change_agent.utcnow();waiting=threading.Event();release=threading.Event();calls=[]
    def model(*args):
        n=len(calls);calls.append(n)
        if n==0:waiting.set();assert release.wait(10)
        return good_patch()
    monkeypatch.setattr('ownstack.change_agent_model.propose_patch',model)
    path=d['path']+'/patch-proposal'
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(lambda:client.post(path,headers=d['engineer'],json=d['body']))
        try:
            assert waiting.wait(5)
            monkeypatch.setattr(change_agent,'utcnow',lambda:start+timedelta(minutes=10))
            progress=client.get(d['path'],headers=d['engineer']).json();assert progress['local_wait_expired']
            replay=client.post(path,headers=d['engineer'],json=d['body']);assert replay.json()['status']=='timed_out'
            assert len(calls)==1
            stopped=client.post(d['path']+'/cancel',headers=d['engineer'],json={'expected_revision':progress['revision']});assert stopped.status_code==200
            body={**d['body'],'expected_revision':stopped.json()['revision'],'idempotency_key':'explicit-after-abandoned-wait'}
            assert client.post(path,headers=d['engineer'],json=body).json()['status']=='proposed'
        finally:release.set()
        assert future.result(timeout=10).status_code==409
    progress=client.get(d['path'],headers=d['engineer']).json();assert not progress['local_wait_expired'] and progress['operation'] is None
    assert len(calls)==2
    monkeypatch.setattr(change_agent,'utcnow',lambda:start)
    manual_finish(client,fixture_db,d)


def test_late_clarification_can_continue_manually_without_a_second_model_call(client,fixture_db,customer_story,tmp_path,monkeypatch):
    from test_customer_domains import discovery
    from ownstack import change_agent
    d=customer_story;s,_=discovery(client,d,tmp_path);start=change_agent.utcnow();calls=[]
    def model(*args):
        calls.append(1);monkeypatch.setattr(change_agent,'utcnow',lambda:start+timedelta(minutes=10))
        return {'action':'ask','field':'roles','reason':'Late controlled response','citations':['request']},{'live':False}
    monkeypatch.setattr('ownstack.change_agent_model.decide',model)
    body={'expected_revision':s['revision'],'idempotency_key':'clarification-expired'};path='/v1/change-agents/'+s['id']
    assert client.post(path+'/step',headers=d['engineer'],json=body).status_code==409
    progress=client.get(path,headers=d['engineer']).json()
    assert progress['status']=='failed' and progress['operation'] is None and progress['error']=='LOCAL_WAIT_EXPIRED'
    assert client.post(path+'/step',headers=d['engineer'],json=body).json()['error']=='LOCAL_WAIT_EXPIRED'
    assert len(calls)==1 and publish(client,d,progress)['status']=='published'


@pytest.mark.parametrize('change',['customer-reconnect','author-session-version','approved-requirement'])
def test_scope_changes_while_repair_runs_cannot_publish_patch(client,fixture_db,repair_story,monkeypatch,change):
    d=repair_story
    def model(*args):
        if change=='customer-reconnect':
            path='/v1/customers/'+d['north']['id']+'/status'
            for revision,value in [(1,False),(2,True)]:
                r=client.post(path,headers=d['staff'],json={'expected_revision':revision,'enabled':value});assert r.status_code==200
        elif change=='author-session-version':
            with fixture_db() as db:db.get(User,'atlas-engineer').token_version+=1;db.commit()
        else:
            row=client.get('/v1/release/requirements/'+d['state']['requirement_ids'][0],headers=d['engineer']).json()
            spec={**row['spec'],'version':row['spec']['version']+1}
            r=client.post('/v1/release/requirements',headers=d['engineer'],json={'project_id':'atlas-project','spec':spec,'customer_account_id':d['north']['id']});assert r.status_code==201,r.text
            r=client.post('/v1/release/requirements/'+r.json()['id']+'/approve',headers=d['staff'],json={'expected_hash':r.json()['requirement_hash']});assert r.status_code==200,r.text
        return good_patch()
    monkeypatch.setattr('ownstack.change_agent_model.propose_patch',model)
    result=client.post(d['path']+'/patch-proposal',headers=d['engineer'],json=d['body']);assert result.status_code in {401,403,404,409},result.text
    public=client.get('/v1/customer-portal/requests',headers=d['south_auth']);assert public.json()==[]
    with fixture_db() as db:
        assert db.get(InferenceBudget,'global').reserved_calls==0
        assert not db.scalars(select(ReleaseAudit).where(ReleaseAudit.subject_id==d['state']['id'],ReleaseAudit.action=='agent.patch_saved')).all()
