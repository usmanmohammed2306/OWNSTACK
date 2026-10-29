"""Actual authenticated workflows over synthetic data, with no provider calls."""
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select
from conftest import login
from ownstack.models import ChangeRequest,EngineeringItem,InferenceBudget,User,TeamMembership,Team
from ownstack.workspace_models import OrganizationProfile,RequestGuidance,EngineeringComment
from ownstack.org_simulation import seed_organization
from ownstack.service import start_attempt,claim_attempt,accept_result,utcnow
from ownstack.ai import AIResult


def create(client,headers,text='Add PDF export for project summaries',kind='feature'):
    body={'text':text,'kind':kind,'project_id':'atlas-project'}
    if kind=='access':body.update(viewer_id='atlas-contractor',expires_at=(utcnow()+timedelta(days=1)).isoformat())
    r=client.post('/v1/requests',headers={**headers,'Idempotency-Key':uuid4().hex},json=body)
    assert r.status_code==201,r.text
    return r.json()['id']


def suggest(client,headers,id):
    r=client.get(f'/v1/requests/{id}/patterns',headers=headers);assert r.status_code==200,r.text
    return r.json()


def test_full_500_person_directory_and_reporting_drilldown(client,fixture_db):
    admin=login(client,'atlas-admin')
    with fixture_db() as db:simulation=seed_organization(db);db.commit()
    first=client.get('/v1/organization',headers=admin).json()
    assert first['total']==500 and first['count']==500 and len(first['people'])==40
    ids=[]
    for page in range(13):ids.extend(p['id'] for p in client.get('/v1/organization',headers=admin,params={'page':page}).json()['people'])
    assert len(ids)==len(set(ids))==500
    roots=client.get('/v1/organization',headers=admin,params={'roots':'true'}).json()['people']
    assert len(roots)==1 and roots[0]['title']=='CEO'
    leaders=client.get('/v1/organization',headers=admin,params={'reports_to':roots[0]['id']}).json()['people']
    assert {'CTO','CFO','COO','CPO','CISO'}<={p['title'] for p in leaders}
    architects=client.get('/v1/organization',headers=admin,params={'q':'Architect'}).json()
    assert architects['count']>0 and all('Architect' in p['title'] for p in architects['people'])
    with fixture_db() as db:
        assert db.get(InferenceBudget,'global').reserved_calls==0
        assert all(not u.password_hash.startswith('pbkdf2') for u in db.scalars(select(User).where(User.id.like('sim-atlas-%'))).all())
    assert simulation['new_credentials_created'] is False


def test_reporting_cycle_stale_edit_and_cross_tenant_manager_are_rejected(client):
    admin=login(client,'atlas-admin')
    def edit(user,manager,rev=0,title='Architect'):
        return client.put('/v1/organization/people/'+user,headers=admin,json={'title':title,'manager_id':manager,'expected_revision':rev})
    assert edit('atlas-engineer','atlas-admin').status_code==200
    assert edit('atlas-admin','atlas-engineer',title='CEO').status_code==422
    assert edit('atlas-engineer','atlas-contractor').status_code==409
    assert edit('atlas-engineer','nova-admin',1).status_code==404
    assert edit('atlas-engineer','atlas-engineer',1).status_code==422
    assert edit('atlas-engineer',None,1,title=' ').status_code==422


@pytest.mark.parametrize('title',['CEO','CTO','CFO','Architect','Engineering Manager','Staff Engineer','Accountant','Legal Counsel'])
def test_position_is_not_an_authorization_role(client,fixture_db,title):
    admin=login(client,'atlas-admin');contractor=login(client,'atlas-contractor')
    r=client.put('/v1/organization/people/atlas-contractor',headers=admin,json={'title':title,'manager_id':'atlas-admin','expected_revision':0})
    assert r.status_code==200
    assert client.get('/v1/host/projects/atlas-project/documents',headers=contractor).status_code==403
    assert client.get('/v1/engineering',headers=contractor).status_code==403
    assert client.put('/v1/organization/people/atlas-admin',headers=contractor,json={'title':'CEO','manager_id':None,'expected_revision':0}).status_code==403
    assert client.get('/v1/organization/people/nova-admin/access',headers=admin).status_code==404
    with fixture_db() as db:assert db.get(User,'atlas-contractor').role=='contractor'


def test_directory_and_access_follow_current_team_scope(client,fixture_db):
    admin=login(client,'atlas-admin');engineer=login(client,'atlas-engineer')
    with fixture_db() as db:seed_organization(db);db.commit()
    full=client.get('/v1/organization',headers=admin).json();scoped=client.get('/v1/organization',headers=engineer).json()
    assert full['total']==500 and scoped['total']==3
    hidden=next(p['id'] for p in full['people'] if p['id'].startswith('sim-'))
    assert client.get(f'/v1/organization/people/{hidden}/access',headers=engineer).status_code==404
    assert client.get('/v1/organization',headers=engineer,params={'reports_to':hidden}).status_code==404
    with fixture_db() as db:
        m=db.scalar(select(TeamMembership).where(TeamMembership.user_id=='atlas-engineer'));m.enabled=False;m.revision+=1;db.commit()
    assert client.get('/v1/organization',headers=engineer).json()['total']==0


@pytest.mark.parametrize('decision',['use','drop'])
def test_pattern_context_is_durable_replayed_once_and_sent_in_next_prompt(client,fixture_db,decision):
    engineer=login(client,'atlas-engineer');create(client,engineer)
    id=create(client,engineer);data=suggest(client,engineer,id);p=data['patterns'][0]
    body={'expected_revision':1,'pattern_id':p['id'],'pattern_hash':p['hash'],'decision':decision,'note':'Keep billing totals unchanged and preserve tenant boundaries.'}
    headers={**engineer,'Idempotency-Key':uuid4().hex}
    r=client.post(f'/v1/requests/{id}/patterns/decision',headers=headers,json=body);assert r.status_code==200,r.text
    assert r.json()['revision']==2 and r.json()['generation_started'] is False
    assert client.post(f'/v1/requests/{id}/patterns/decision',headers=headers,json=body).json()==r.json()
    current=client.get('/v1/requests/'+id,headers=engineer).json()
    assert current['text']=='Add PDF export for project summaries'
    assert suggest(client,engineer,id)['choices'][p['id']]['decision']==decision
    with fixture_db() as db:
        from ownstack.request_context import engineering_prompt
        prompt=engineering_prompt(db,db.get(ChangeRequest,id))
        assert body['note'] in prompt and ('Reuse:' if decision=='use' else 'Do not reuse:') in prompt
        assert len(db.scalars(select(RequestGuidance).where(RequestGuidance.request_id==id)).all())==1
        assert db.get(InferenceBudget,'global').reserved_calls==0


def test_guidance_cancels_old_attempt_and_its_late_answer_cannot_publish(client,fixture_db):
    engineer=login(client,'atlas-engineer');create(client,engineer);id=create(client,engineer)
    with fixture_db() as db:
        req=db.get(ChangeRequest,id);attempt=start_attempt(db,req,'controlled-model-double',60);db.flush();assert claim_attempt(db,attempt.id);attempt_id=attempt.id;db.commit()
    data=suggest(client,engineer,id);p=data['patterns'][0]
    r=client.post(f'/v1/requests/{id}/patterns/decision',headers={**engineer,'Idempotency-Key':uuid4().hex},json={'expected_revision':1,'pattern_id':p['id'],'pattern_hash':p['hash'],'decision':'drop','note':'Use a tenant scoped implementation instead of a global setting.'})
    assert r.status_code==200,r.text
    with fixture_db() as db:
        assert not accept_result(db,attempt_id,AIResult('engineering','Late controlled answer','controlled-model-double',0,None,None))
        db.commit();assert db.get(ChangeRequest,id).accepted_proposal_id is None


def test_code_context_detects_actual_duplicate_functions_but_preserves_constants(client):
    engineer=login(client,'atlas-engineer');id=create(client,engineer)
    source='def visible(user, project):\n    if not user.enabled:\n        return False\n    return user.tenant_id == project.tenant_id\n'
    r=client.post(f'/v1/requests/{id}/code-context',headers=engineer,json={'expected_revision':1,'files':{'a.py':source,'b.py':source.replace('visible','can_read')}})
    assert r.status_code==200,r.text
    patterns=suggest(client,engineer,id)['patterns'];assert len(patterns)==1 and patterns[0]['kind']=='code' and patterns[0]['count']==2
    assert {p['path'] for p in patterns[0]['locations']}=={'a.py','b.py'}
    assert client.post(f'/v1/requests/{id}/code-context',headers=engineer,json={'expected_revision':2,'files':{'../private.py':source}}).status_code==422
    assert client.post(f'/v1/requests/{id}/code-context',headers=engineer,json={'expected_revision':2,'files':{'x.py':'def broken('}}).status_code==422
    from ownstack.request_patterns import code_patterns
    assert not code_patterns({'a.py':'def f(x):\n    if x > 2:\n        return 3\n    return 4\n','b.py':'def g(x):\n    if x > 2:\n        return 300\n    return 4\n'})


def test_pattern_scope_and_proposal_fence(client):
    engineer=login(client,'atlas-engineer');nova=login(client,'nova-admin');create(client,engineer);id=create(client,engineer)
    p=suggest(client,engineer,id)['patterns'][0]
    body={'expected_revision':1,'pattern_id':p['id'],'pattern_hash':'0'*64,'decision':'use','note':'Keep all customer boundaries explicit.'}
    assert client.post(f'/v1/requests/{id}/patterns/decision',headers={**engineer,'Idempotency-Key':uuid4().hex},json=body).status_code==409
    assert client.get(f'/v1/requests/{id}/patterns',headers=nova).status_code==404
    assert client.post(f'/v1/requests/{id}/manual-handoff',headers={**engineer,'Idempotency-Key':uuid4().hex}).status_code==200
    body['pattern_hash']=p['hash']
    assert client.post(f'/v1/requests/{id}/patterns/decision',headers={**engineer,'Idempotency-Key':uuid4().hex},json=body).status_code==409


def test_code_comments_are_exact_private_and_never_release(client,fixture_db):
    engineer=login(client,'atlas-engineer');nova=login(client,'nova-admin');id=create(client,engineer)
    assert client.post(f'/v1/requests/{id}/manual-handoff',headers={**engineer,'Idempotency-Key':uuid4().hex}).status_code==200
    item=next(w for w in client.get('/v1/engineering',headers=engineer).json() if w['request_id']==id)
    source=client.get('/v1/engineering-source',headers=engineer).json()
    r=client.post(f"/v1/engineering/{item['id']}/manual-patch",headers=engineer,json={'patch':{'edits':[{'path':source['path'],'old':source['source'],'new':source['source']+'\n# Review fixture\n'}]}})
    assert r.status_code==200,r.text
    detail=client.get(f"/v1/engineering/{item['id']}",headers=engineer).json()
    body={'patch_hash':detail['patch_hash'],'request_revision':1,'comment':'Preserve tenant isolation and test an expired contractor.'}
    headers={**engineer,'Idempotency-Key':uuid4().hex};url=f"/v1/engineering/{item['id']}/comments"
    response=client.post(url,headers=headers,json=body);assert response.status_code==200,response.text
    assert client.post(url,headers=headers,json=body).json()==response.json()
    rows=client.get(url,headers=engineer).json();assert len(rows)==1 and not rows[0]['historical']
    assert client.get(url,headers=nova).status_code==404
    assert client.post(url,headers={**engineer,'Idempotency-Key':uuid4().hex},json={**body,'patch_hash':'0'*64}).status_code==409
    with fixture_db() as db:
        saved=db.get(EngineeringItem,item['id']);assert saved.human_decision is None and saved.status=='drafted'
        assert len(db.scalars(select(EngineeringComment)).all())==1


def test_access_button_tracks_actual_approval_read_and_reviewed_rollback(client,fixture_db):
    engineer=login(client,'atlas-engineer');admin=login(client,'atlas-admin');contractor=login(client,'atlas-contractor')
    url='/v1/organization/people/atlas-contractor/access'
    assert client.get(url,headers=admin).json()['rules'][0]['allowed'] is False
    id=create(client,engineer,'Give the contractor temporary read-only Atlas access.',kind='access')
    assert client.post(f'/v1/requests/{id}/manual-handoff',headers={**engineer,'Idempotency-Key':uuid4().hex}).status_code==200
    with fixture_db() as db:
        from ownstack.models import Proposal
        req=db.get(ChangeRequest,id);proposal=db.get(Proposal,req.accepted_proposal_id);pid=proposal.id;ph=proposal.proposal_hash
    response=client.post(f'/v1/proposals/{pid}/approve',headers={**admin,'Idempotency-Key':uuid4().hex},json={'proposal_hash':ph})
    assert response.status_code==200,response.text
    grant=response.json()['variation_id'];rules=client.get(url,headers=admin).json()['rules']
    assert rules[0]['allowed'] and rules[0]['grants'][0]['id']==grant
    assert rules[0]['expires_at'].endswith('+00:00') and rules[0]['can_manage']
    assert client.get('/v1/host/projects/atlas-project/documents',headers=contractor).status_code==200
    assert client.get('/v1/host/projects/nova-project/documents',headers=contractor).status_code in {403,404}
    preview=client.get(f'/v1/variations/{grant}/revoke-preview',headers=admin).json()
    assert client.post(f'/v1/variations/{grant}/revoke',headers={**admin,'Idempotency-Key':uuid4().hex},json={'preview_hash':preview['preview_hash']}).status_code==200
    assert not client.get(url,headers=admin).json()['rules'][0]['allowed']
    assert client.get('/v1/host/projects/atlas-project/documents',headers=contractor).status_code==403


def test_parallel_reporting_changes_cannot_create_a_cycle(client):
    from concurrent.futures import ThreadPoolExecutor
    admin=login(client,'atlas-admin')
    def assign(pair):
        user,manager=pair
        return client.put('/v1/organization/people/'+user,headers=admin,json={'title':'Architect','manager_id':manager,'expected_revision':0}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(assign,[('atlas-engineer','atlas-contractor'),('atlas-contractor','atlas-engineer')]))
    assert sorted(codes)==[200,422]


def test_parallel_guidance_saves_one_revision_and_keeps_the_original_prompt(client):
    from concurrent.futures import ThreadPoolExecutor
    engineer=login(client,'atlas-engineer');create(client,engineer);id=create(client,engineer)
    p=suggest(client,engineer,id)['patterns'][0]
    def decide(decision):
        return client.post(f'/v1/requests/{id}/patterns/decision',headers={**engineer,'Idempotency-Key':uuid4().hex},json={'expected_revision':1,'pattern_id':p['id'],'pattern_hash':p['hash'],'decision':decision,'note':'Keep the exact tenant scope and existing invoice totals.'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(decide,['use','drop']))
    assert sorted(codes)==[200,409]
    state=suggest(client,engineer,id);assert state['revision']==2 and state['customer_text']=='Add PDF export for project summaries'


def test_private_code_and_guidance_do_not_leak_to_customer_request_readers(client,fixture_db):
    from ownstack.auth import password_hash
    from ownstack.team_scope import add_general_member
    with fixture_db() as db:
        user=User(id='atlas-member',tenant_id='atlas',role='member',password_hash=password_hash('pass'));db.add(user);db.flush();add_general_member(db,user);db.commit()
    engineer=login(client,'atlas-engineer');member=login(client,'atlas-member');id=create(client,engineer)
    code='def allowed(user):\n    if not user.enabled:\n        return False\n    return user.name == "PRIVATE_CODE_MARKER"\n'
    assert client.post(f'/v1/requests/{id}/code-context',headers=engineer,json={'expected_revision':1,'files':{'one.py':code,'two.py':code.replace('allowed','can_read')}}).status_code==200
    pattern=suggest(client,engineer,id)['patterns'][0]
    assert client.post(f'/v1/requests/{id}/patterns/decision',headers={**engineer,'Idempotency-Key':uuid4().hex},json={'expected_revision':2,'pattern_id':pattern['id'],'pattern_hash':pattern['hash'],'decision':'use','note':'INTERNAL_REVIEW_MARKER: preserve the exact identity comparison.'}).status_code==200
    for url in ['/v1/requests',f'/v1/requests/{id}',f'/v1/requests/{id}/patterns']:
        r=client.get(url,headers=member);assert r.status_code==200,r.text
        assert 'PRIVATE_CODE_MARKER' not in r.text and 'INTERNAL_REVIEW_MARKER' not in r.text
    assert client.get('/v1/engineering',headers=member).status_code==403


def test_private_guidance_reaches_the_bounded_patch_adapter_without_provider_use(client,fixture_db,monkeypatch):
    engineer=login(client,'atlas-engineer');create(client,engineer);id=create(client,engineer)
    pattern=suggest(client,engineer,id)['patterns'][0]
    note='Use the existing export structure while preserving all billing totals.'
    assert client.post(f'/v1/requests/{id}/patterns/decision',headers={**engineer,'Idempotency-Key':uuid4().hex},json={'expected_revision':1,'pattern_id':pattern['id'],'pattern_hash':pattern['hash'],'decision':'use','note':note}).status_code==200
    assert client.post(f'/v1/requests/{id}/manual-handoff',headers={**engineer,'Idempotency-Key':uuid4().hex}).status_code==200
    item=next(w for w in client.get('/v1/engineering',headers=engineer).json() if w['request_id']==id)
    captured=[]
    def controlled_adapter(prompt):
        from ownstack.patch_agent import fixture_patch
        captured.append(prompt);return fixture_patch(),'controlled-adapter-not-live',{'live':False}
    monkeypatch.setattr('ownstack.api.propose_patch',controlled_adapter)
    r=client.post(f"/v1/engineering/{item['id']}/draft",headers=engineer)
    assert r.status_code==200,r.text
    assert len(captured)==1 and note in captured[0] and 'Reuse:' in captured[0]
    with fixture_db() as db:
        assert db.get(ChangeRequest,id).text=='Add PDF export for project summaries'
        assert db.get(InferenceBudget,'global').reserved_calls==0


@pytest.mark.parametrize('replacement',['patch','requirements'])
def test_rejection_cannot_decide_a_replacement_candidate(client,fixture_db,replacement):
    engineer=login(client,'atlas-engineer');id=create(client,engineer)
    assert client.post(f'/v1/requests/{id}/manual-handoff',headers={**engineer,'Idempotency-Key':uuid4().hex}).status_code==200
    item=next(w for w in client.get('/v1/engineering',headers=engineer).json() if w['request_id']==id)
    with fixture_db() as db:
        row=db.get(EngineeringItem,item['id']);row.patch_hash='a'*64;row.status='drafted';db.commit()
    body={'decision':'reject','patch_hash':'a'*64,'request_revision':1}
    with fixture_db() as db:
        if replacement=='patch':db.get(EngineeringItem,item['id']).patch_hash='b'*64
        else:db.get(ChangeRequest,id).revision=2
        db.commit()
    result=client.post(f"/v1/engineering/{item['id']}/decide",headers=engineer,json=body)
    assert result.status_code==409,result.text
    with fixture_db() as db:assert db.get(EngineeringItem,item['id']).human_decision is None


@pytest.mark.parametrize('prepared',[False,True])
def test_private_context_upgrade_preserves_history_and_fences_prototype_work(client,fixture_db,prepared):
    import os,subprocess,sys
    from pathlib import Path
    from sqlalchemy import text,inspect
    from ownstack.workspace_models import RequestWorkspace
    engineer=login(client,'atlas-engineer');id=create(client,engineer)
    if prepared:assert client.post(f'/v1/requests/{id}/manual-handoff',headers={**engineer,'Idempotency-Key':uuid4().hex}).status_code==200
    with fixture_db() as db:
        req=db.get(ChangeRequest,id)
        attempt=start_attempt(db,req,'migration-controlled-double',60) if not prepared else None
        if attempt:attempt_id=attempt.id
        req.text='Original customer request\nPRIVATE PROTOTYPE GUIDANCE'
        db.add(RequestWorkspace(request_id=id,tenant_id='atlas',customer_text='Original customer request',effective_text=req.text,code_files={}))
        db.commit()
    engine=fixture_db.kw['bind']
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE request_workspaces DROP COLUMN effective_text'))
        connection.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)'))
        connection.execute(text("INSERT INTO alembic_version VALUES ('c28f10d3a601')"))
    env=dict(os.environ,OWNSTACK_DATABASE_URL=str(engine.url),OWNSTACK_AI_MODE='off',OWNSTACK_MAX_LIVE_CALLS='0',NEBIUS_API_KEY='',NEBIUS_MODEL_ID='',NEBIUS_PATCH_MODEL_ID='')
    # This fixture removes one historical column from current metadata. Test
    # that exact historical upgrade, not unrelated future table creation.
    result=subprocess.run([sys.executable,'-m','alembic','upgrade','d28f10d3a602'],cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True,timeout=30)
    with engine.connect() as connection:
        if prepared:
            assert result.returncode!=0 and 'operator-reviewed private-context migration' in result.stderr
            assert 'effective_text' not in {c['name'] for c in inspect(engine).get_columns('request_workspaces')}
            assert 'PRIVATE PROTOTYPE GUIDANCE' in connection.execute(text('SELECT text FROM change_requests WHERE id=:id'),{'id':id}).scalar_one()
        else:
            assert result.returncode==0,result.stderr
            assert connection.execute(text('SELECT text FROM change_requests WHERE id=:id'),{'id':id}).scalar_one()=='Original customer request'
            assert 'PRIVATE PROTOTYPE GUIDANCE' in connection.execute(text('SELECT effective_text FROM request_workspaces WHERE request_id=:id'),{'id':id}).scalar_one()
            assert connection.execute(text('SELECT state FROM attempts WHERE id=:id'),{'id':attempt_id}).scalar_one()=='superseded'
            assert connection.execute(text('SELECT current_attempt_id FROM change_requests WHERE id=:id'),{'id':id}).scalar_one() is None
        assert connection.execute(text("SELECT reserved_calls FROM inference_budget WHERE id='global'")).scalar_one()==0
