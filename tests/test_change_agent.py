"""Explicit model doubles; actual HTTP state transitions, no provider credits."""
from copy import deepcopy
from datetime import timedelta
import hashlib
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import select
from conftest import login
from ownstack.models import ReleaseRequirement,ReleaseAudit,InferenceBudget,ChangeRequest,TeamMembership
from ownstack.change_agent_contracts import VisibilityPolicy,counterexample_requirements,expected,validate_decision,checked_answers
from ownstack.release_contracts import VisibilityInput
from ownstack.release_repository import initialize

POLICY={'roles':['engineer','manager'],'requires_assignment':True,'temporary_grants':True,'visible_fields':['id','title'],'denial_status':403}

@pytest.fixture
def discovery(client,fixture_db,tmp_path,monkeypatch):
    monkeypatch.setenv('OWNSTACK_RELEASE_ASSURANCE','true')
    engineer=login(client,'atlas-engineer');admin=login(client,'atlas-admin')
    source=tmp_path/'app';source.mkdir();(source/'serve.py').write_text('def serve():\n    pass\n');code='def visible(user):\n    return user.enabled\n';(source/'policy.py').write_text(code)
    snapshot=initialize(source,name='Agent fixture',entrypoint='serve.py',include=['serve.py','policy.py'])
    r=client.post('/v1/release/sources',headers=engineer,json={'project_id':'atlas-project','label':'baseline','snapshot':snapshot});assert r.status_code==201,r.text
    r=client.post('/v1/requests',headers={**engineer,'Idempotency-Key':uuid4().hex},json={'text':'Managers need assigned documents, with separately reviewed temporary exceptions.','kind':'feature','project_id':'atlas-project'});assert r.status_code==201
    request_id=r.json()['id']
    r=client.post(f'/v1/requests/{request_id}/code-context',headers=engineer,json={'expected_revision':1,'files':{'policy.py':code}});assert r.status_code==200,r.text
    body={'request_id':request_id,'source_sha256':snapshot['sha256'],'idempotency_key':uuid4().hex}
    r=client.post('/v1/change-agents',headers=engineer,json=body);assert r.status_code==201,r.text
    return {'state':r.json(),'body':body,'engineer':engineer,'admin':admin,'request_id':request_id,'source':source}

def answers(client,data,policy=POLICY):
    s=data['state'];r=client.post(f"/v1/change-agents/{s['id']}/answers",headers=data['engineer'],json={'expected_revision':s['revision'],'answers':policy})
    assert r.status_code==200,r.text;data['state']=r.json();return r.json()

def publish(client,data):
    s=answers(client,data);r=client.post(f"/v1/change-agents/{s['id']}/publish",headers=data['engineer'],json={'expected_revision':s['revision'],'policy_hash':s['policy_hash']})
    assert r.status_code==200,r.text;data['state']=r.json();return r.json()

def test_questions_explicit_answers_exact_approval_and_counterexample_suite(client,fixture_db,discovery):
    data=discovery;assert len(data['state']['missing'])==5
    assert client.post('/v1/change-agents',headers=data['engineer'],json=data['body']).json()['id']==data['state']['id']
    assert len(client.get('/v1/change-agents',headers=data['engineer'],params={'request_id':data['request_id']}).json())==1
    s=publish(client,data);assert s['status']=='published' and len(s['requirement_ids'])==3
    body={'expected_revision':s['revision'],'policy_hash':s['policy_hash']}
    r=client.post(f"/v1/change-agents/{s['id']}/approve",headers=data['admin'],json=body);assert r.status_code==200,r.text
    assert r.json()['status']=='approved' and r.json()['release_state']=='not_deployed'
    assert client.post(f"/v1/change-agents/{s['id']}/approve",headers=data['admin'],json=body).status_code==200
    receipt=client.get('/v1/release/requirements-receipt',headers=data['engineer'],params={'project_id':'atlas-project'});assert receipt.status_code==200,receipt.text
    assert sum(len(spec['cases']) for spec in receipt.json()['requirements'])==144
    with fixture_db() as db:assert db.get(InferenceBudget,'global').reserved_calls==0

@pytest.mark.parametrize('bad',[{'roles':['anonymous']},{'roles':['manager','manager']},{'denial_status':True},{'temporary_grants':'true'}, {'visible_fields':['__private']},{'tenant_id':'nova'}])
def test_invalid_or_model_authored_authority_answers_fail_closed(client,discovery,bad):
    s=discovery['state'];r=client.post(f"/v1/change-agents/{s['id']}/answers",headers=discovery['engineer'],json={'expected_revision':1,'answers':bad})
    assert r.status_code==422

def test_model_selects_a_question_cannot_invent_answers_or_authority(client,discovery,monkeypatch):
    from ownstack import change_agent_model
    calls=[]
    def model(state,sources,ticket,settings):
        calls.append(state['id']);return {'action':'ask','field':'temporary_grants','reason':'Expiry behavior changes the allowed effect.','citations':['request','policy.py']},{'live':False,'model':'controlled-double'}
    monkeypatch.setattr(change_agent_model,'decide',model)
    s=discovery['state'];body={'expected_revision':s['revision'],'idempotency_key':'question-operation-one'}
    r=client.post(f"/v1/change-agents/{s['id']}/step",headers=discovery['engineer'],json=body);assert r.status_code==200,r.text
    assert r.json()['last_decision']['field']=='temporary_grants' and r.json()['answers']=={}
    assert client.post(f"/v1/change-agents/{s['id']}/step",headers=discovery['engineer'],json=body).status_code==200
    assert len(calls)==1
    with pytest.raises(ValueError):validate_decision({'action':'propose','field':None,'reason':'Everything looks fine','citations':['request']},s,{'policy.py':'code'})

def test_cancellation_discards_a_late_model_answer(client,discovery,monkeypatch):
    from ownstack import change_agent_model
    def model(state,sources,ticket,settings):
        response=client.post(f"/v1/change-agents/{state['id']}/cancel",headers=discovery['engineer'],json={'expected_revision':state['revision']})
        assert response.status_code==200,response.text
        return {'action':'ask','field':'roles','reason':'Late result must not overwrite cancellation.','citations':['request']},{'live':False}
    monkeypatch.setattr(change_agent_model,'decide',model)
    s=discovery['state'];r=client.post(f"/v1/change-agents/{s['id']}/step",headers=discovery['engineer'],json={'expected_revision':1,'idempotency_key':'late-operation'})
    assert r.status_code==409,r.text
    saved=client.get(f"/v1/change-agents/{s['id']}",headers=discovery['engineer']).json();assert saved['last_decision'] is None and saved['status']=='clarifying'

def test_stale_request_and_revoked_restored_membership_cannot_approve(client,fixture_db,discovery):
    s=publish(client,discovery)
    with fixture_db() as db:
        row=db.scalar(select(TeamMembership).where(TeamMembership.user_id=='atlas-engineer'));row.revision+=2;db.commit()
    r=client.post(f"/v1/change-agents/{s['id']}/approve",headers=discovery['admin'],json={'expected_revision':s['revision'],'policy_hash':s['policy_hash']})
    assert r.status_code==409
    with fixture_db() as db:assert all(r.state=='draft' for r in db.scalars(select(ReleaseRequirement)).all())

def test_other_tenant_and_customer_reader_cannot_inspect_private_discovery(client,discovery):
    for user in ['nova-admin','atlas-contractor']:
        headers=login(client,user);r=client.get('/v1/change-agents/'+discovery['state']['id'],headers=headers)
        assert r.status_code in {403,404}

def test_off_mode_does_not_call_adapter_and_manual_answers_still_work(client,discovery,monkeypatch):
    monkeypatch.setenv('OWNSTACK_AI_MODE','off')
    monkeypatch.setattr('ownstack.change_agent_model.decide',lambda *a:pytest.fail('AI off must not dispatch'))
    r=client.post('/v1/change-agents/'+discovery['state']['id']+'/step',headers=discovery['engineer'],json={'expected_revision':1,'idempotency_key':'off-mode-test'})
    assert r.status_code==503
    assert answers(client,discovery)['status']=='ready'

def test_declared_domain_enforces_expiry_revocation_assignment_and_foreign_controls():
    policy=VisibilityPolicy.model_validate(POLICY)
    specs=counterexample_requirements(policy,session_id='example',customer='atlas',owner='engineer',source_ref='reviewed-request')
    cases=[c for spec in specs for c in spec.cases];assert len(cases)==144
    for c in cases:
        if c.input.actor_tenant_id!=c.input.resource_tenant_id:assert c.expected.status_code==404 and not c.expected.visible_fields
        if c.input.actor_role=='anonymous':assert c.expected.status_code!=200
    matches=[c for c in cases if c.input.actor_role=='contractor' and not c.input.assigned and c.kind=='target']
    assert sum(c.expected.status_code==200 for c in matches)==2 # Exact start and active, never expiry.

def test_patch_capabilities_preserve_adapter_and_unlisted_private_files(tmp_path):
    from ownstack.counterexample_loop import apply_patch
    source=tmp_path/'source';source.mkdir();(source/'serve.py').write_text('pass\n');(source/'policy.py').write_text('def read():\n    return False\n')
    initialize(source,name='Owned fixture',entrypoint='serve.py',include=['serve.py','policy.py'])
    (source/'.env').write_text('private-data')
    patch={'edits':[{'path':'policy.py','old':'return False','new':'return True'}]}
    target=tmp_path/'candidate';apply_patch(source,target,patch,{'policy.py'})
    assert not (target/'.env').exists() and 'return True' in (target/'policy.py').read_text()
    for path in ['serve.py','../policy.py','.env']:
        with pytest.raises(ValueError):apply_patch(source,tmp_path/'bad',{'edits':[{'path':path,'old':'pass','new':'print(1)'}]},{'policy.py'})

def test_duplicate_during_generation_reads_saved_running_state(client,discovery,monkeypatch):
    calls=[];s=discovery['state'];body={'expected_revision':1,'idempotency_key':'running-replay'}
    def model(state,sources,ticket,settings):
        calls.append(1)
        repeat=client.post(f"/v1/change-agents/{s['id']}/step",headers=discovery['engineer'],json=body)
        assert repeat.status_code==200 and repeat.json()['status']=='running'
        return {'action':'ask','field':'roles','reason':'Choose the allowed roles explicitly.','citations':['request']},{'live':False}
    monkeypatch.setattr('ownstack.change_agent_model.decide',model)
    assert client.post(f"/v1/change-agents/{s['id']}/step",headers=discovery['engineer'],json=body).status_code==200
    assert len(calls)==1

def test_bad_model_output_is_saved_as_failure_and_never_approves(client,fixture_db,discovery,monkeypatch):
    monkeypatch.setattr('ownstack.change_agent_model.decide',lambda *a:({'action':'approve','command':'release everything'},{'live':False}))
    s=discovery['state'];r=client.post(f"/v1/change-agents/{s['id']}/step",headers=discovery['engineer'],json={'expected_revision':1,'idempotency_key':'malformed-model'})
    assert r.status_code==200 and r.json()['status']=='failed' and not r.json()['answers']
    with fixture_db() as db:assert db.scalars(select(ReleaseRequirement)).all()==[] and db.get(InferenceBudget,'global').reserved_calls==0

def test_batch_approval_rolls_back_every_partition_if_one_is_invalid(client,fixture_db,discovery):
    s=publish(client,discovery)
    with fixture_db() as db:db.get(ReleaseRequirement,s['requirement_ids'][1]).created_by='atlas-admin';db.commit()
    r=client.post(f"/v1/change-agents/{s['id']}/approve",headers=discovery['admin'],json={'expected_revision':s['revision'],'policy_hash':s['policy_hash']})
    assert r.status_code==403,r.text
    with fixture_db() as db:
        assert all(row.state=='draft' for row in db.scalars(select(ReleaseRequirement)).all())
        assert db.scalars(select(ReleaseAudit).where(ReleaseAudit.action=='requirement.approved')).all()==[]

def test_simultaneous_answers_save_one_revision(client,discovery):
    from concurrent.futures import ThreadPoolExecutor
    s=discovery['state']
    def answer(flag):return client.post(f"/v1/change-agents/{s['id']}/answers",headers=discovery['engineer'],json={'expected_revision':1,'answers':{'requires_assignment':flag}}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(answer,[True,False]))==[200,409]

def test_changed_request_cannot_publish_or_approve_old_discovery(client,fixture_db,discovery):
    s=publish(client,discovery)
    with fixture_db() as db:db.get(ChangeRequest,discovery['request_id']).revision+=1;db.commit()
    r=client.post(f"/v1/change-agents/{s['id']}/approve",headers=discovery['admin'],json={'expected_revision':s['revision'],'policy_hash':s['policy_hash']})
    assert r.status_code==409

def test_legacy_release_gate_also_rejects_changed_discovery_lineage(client,fixture_db,discovery):
    s=publish(client,discovery)
    assert client.post(f"/v1/change-agents/{s['id']}/approve",headers=discovery['admin'],json={'expected_revision':s['revision'],'policy_hash':s['policy_hash']}).status_code==200
    with fixture_db() as db:db.get(ChangeRequest,discovery['request_id']).revision+=1;db.commit()
    r=client.get('/v1/release/requirements-receipt',headers=discovery['engineer'],params={'project_id':'atlas-project'})
    assert r.status_code==409 and 'stale' in r.text

def test_graph_preserves_failure_then_checked_repair_and_never_releases(tmp_path):
    from ownstack.counterexample_loop import run_loop
    source=tmp_path/'source';source.mkdir();(source/'serve.py').write_text('pass\n');(source/'policy.py').write_text('def read():\n    return False\n')
    initialize(source,name='Graph fixture',entrypoint='serve.py',include=['serve.py','policy.py'])
    specs=[s.model_dump(mode='json') for s in counterexample_requirements(VisibilityPolicy.model_validate(POLICY),session_id='graph',customer='atlas',owner='e',source_ref='review')]
    c=specs[0]['cases'][0];calls=[]
    def verify(candidate,out):
        calls.append(candidate);passed=len(calls)==2
        return {'id':str(len(calls)),'state':'passed' if passed else 'regression','report':{'passed':passed,'assessments':[] if passed else [{'requirement_key':specs[0]['key'],'case_id':c['case_id'],'baseline_passed':True,'candidate_passed':False,'expected':c['expected'],'observed_candidate':{'status_code':200,'visible_fields':['id']}}]}}
    def model(context):
        assert context['counterexample']['case_id']==c['case_id']
        return {'edits':[{'path':'policy.py','old':'return False','new':'return True'}]},{'live':False,'origin':'controlled-double'}
    result=run_loop(candidate=source,requirements=specs,editable={'policy.py'},output=tmp_path/'results',verify=verify,propose=model)
    assert result['state']=='ready_for_human_review' and result['attempts']==2 and not result['accepted'] and not result['released']
    assert (tmp_path/'results/counterexample-1.json').is_file() and (tmp_path/'results/attempt-1-summary.json').is_file()

def test_quoted_model_suggestions_remain_unconfirmed_until_human_answers(client,discovery,monkeypatch):
    s=discovery['state']
    def model(state,sources,ticket,settings):
        return {'action':'suggest_answers','field':None,'facts':{'requires_assignment':True},'reason':'The request explicitly says assigned documents.',
            'citations':['request'],'quotes':[{'field':'requires_assignment','source':'request','quote':'assigned documents'}]},{'live':False}
    monkeypatch.setattr('ownstack.change_agent_model.decide',model)
    r=client.post(f"/v1/change-agents/{s['id']}/step",headers=discovery['engineer'],json={'expected_revision':1,'idempotency_key':'quoted-suggestion'})
    assert r.status_code==200,r.text
    assert r.json()['last_decision']['facts']=={'requires_assignment':True} and not r.json()['answers']
    wrong={'action':'suggest_answers','field':None,'facts':{'requires_assignment':False},'reason':'An unsupported assumption needs rejection.',
        'citations':['request'],'quotes':[{'field':'requires_assignment','source':'request','quote':'made-up evidence'}]}
    with pytest.raises(ValueError):validate_decision(wrong,s,{},'Managers need assigned documents')

def test_revised_discovery_supersedes_old_partitions_atomically(client,fixture_db,discovery):
    first=publish(client,discovery)
    assert client.post(f"/v1/change-agents/{first['id']}/approve",headers=discovery['admin'],json={'expected_revision':first['revision'],'policy_hash':first['policy_hash']}).status_code==200
    body={**discovery['body'],'idempotency_key':uuid4().hex}
    r=client.post('/v1/change-agents',headers=discovery['engineer'],json=body);assert r.status_code==201
    discovery['state']=r.json();second=publish(client,discovery)
    assert client.post(f"/v1/change-agents/{second['id']}/approve",headers=discovery['admin'],json={'expected_revision':second['revision'],'policy_hash':second['policy_hash']}).status_code==200
    with fixture_db() as db:
        old=[db.get(ReleaseRequirement,id) for id in first['requirement_ids']];new=[db.get(ReleaseRequirement,id) for id in second['requirement_ids']]
        assert {r.key for r in old}=={r.key for r in new} and all(r.state=='superseded' for r in old) and all(r.version==2 for r in new)

@pytest.mark.parametrize('outcome',['proposed','forbidden-edit','canceled','changed-response'])
def test_scoped_repair_model_tool_is_fenced_and_replayed_without_duplicate_calls(client,fixture_db,discovery,monkeypatch,outcome):
    """Execution report is an explicit double here; real Docker proof is separate."""
    from ownstack.models import ReleaseCheck
    from ownstack.policy import digest
    s=publish(client,discovery)
    assert client.post(f"/v1/change-agents/{s['id']}/approve",headers=discovery['admin'],json={'expected_revision':s['revision'],'policy_hash':s['policy_hash']}).status_code==200
    current=client.get(f"/v1/change-agents/{s['id']}",headers=discovery['engineer']).json()
    queued=client.post('/v1/release/checks',headers=discovery['engineer'],json={'project_id':'atlas-project','baseline_sha256':s['source_sha256'],
        'candidate_sha256':'a'*64,'requirement_ids':s['requirement_ids'],'idempotency_key':uuid4().hex})
    assert queued.status_code==202,queued.text
    check_id=queued.json()['id'];code='def visible(user):\n    return user.enabled\n'
    if outcome=='changed-response':code="def read(data):\n    return 200, {'id':data['resource_id'],'title':'Existing title'}\n"
    with fixture_db() as db:
        check=db.get(ReleaseCheck,check_id);case=check.requirements[0]['cases'][0]
        check.state='regression';check.report={'candidate_snapshot':{'files':{'policy.py':hashlib.sha256(code.encode()).hexdigest()},'config':{'entrypoint':'serve.py'}},
            'assessments':[{'requirement_key':check.requirements[0]['key'],'case_id':case['case_id'],'baseline_passed':True,'candidate_passed':False,
                'expected':case['expected'],'observed_candidate':{'status_code':200,'visible_fields':['id']}}]};check.evidence_hash=digest(check.report);db.commit()
    monkeypatch.setattr('ownstack.release_assurance.assess_report',lambda *a:'regression')
    calls=[]
    def model(context,settings):
        calls.append(context)
        if outcome=='changed-response':
            return {'edits':[{'path':'policy.py','old':code,'new':"def read(data):\n    return 200, {k:data[k] for k in ('id','title') if k in data}\n"}]},{'live':False,'model':'controlled-response-regression'}
        if outcome=='canceled':
            saved=client.get(f"/v1/change-agents/{s['id']}",headers=discovery['engineer']).json()
            assert client.post(f"/v1/change-agents/{s['id']}/cancel",headers=discovery['engineer'],json={'expected_revision':saved['revision']}).status_code==200
        return {'edits':[{'path':'serve.py' if outcome=='forbidden-edit' else 'policy.py','old':'return user.enabled','new':'return False'}]},{'live':False,'model':'controlled-repair-double'}
    monkeypatch.setattr('ownstack.change_agent_model.propose_patch',model)
    body={'expected_revision':current['revision'],'check_id':check_id,'files':{'policy.py':code},'idempotency_key':uuid4().hex}
    r=client.post(f"/v1/change-agents/{s['id']}/patch-proposal",headers=discovery['engineer'],json=body)
    if outcome=='canceled':assert r.status_code==409,r.text
    else:
        assert r.status_code==200,r.text
        assert r.json()['status']==('failed' if outcome in {'forbidden-edit','changed-response'} else 'proposed')
        assert client.post(f"/v1/change-agents/{s['id']}/patch-proposal",headers=discovery['engineer'],json=body).json()==r.json()
    assert len(calls)==1 and calls[0]['approved_policy']['requires_assignment'] is True
    with fixture_db() as db:assert db.get(InferenceBudget,'global').reserved_calls==0 and db.get(ReleaseCheck,check_id).decision is None
