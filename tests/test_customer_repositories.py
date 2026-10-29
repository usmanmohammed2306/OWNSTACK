"""Customer repository HTTP stories with explicitly doubled execution controls."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import pytest
from sqlalchemy import select,func
from conftest import login
from test_customer_domains import customer_story,submit,discovery  # noqa: F401
from test_repository_cockpit import local_repo,fake_executor,work  # noqa: F401
from test_repository_release import synthetic_report,SOURCE
from test_release_contracts import spec
from ownstack.models import EngineeringItem,InferenceBudget,ReleaseAudit


def register(client,d,**changes):
    r=client.post('/v1/repositories',headers=d['engineer'],json={'project_id':'atlas-project','key':'shared-flask',
        'label':'Shared Flask product','kind':'pinned','case_id':'pallets__flask-4160',**changes})
    assert r.status_code==201,r.text
    return r.json()


def link(client,d,repo,customer=None,enabled=True):
    r=client.post('/v1/repositories/'+repo['id']+'/customers',headers=d['engineer'],json={
        'expected_revision':repo['revision'],'customer_id':customer or d['north']['id'],'enabled':enabled})
    assert r.status_code==200,r.text
    return r.json()


def adopted(client,d):
    submission=submit(client,d['north_auth']).json()
    r=client.post('/v1/customers/inbox/'+submission['id']+'/adopt',headers=d['engineer']);assert r.status_code==200,r.text
    return r.json()['request_id'],submission['id']


def handoff(client,d,repo,req):
    r=client.post('/v1/repositories/handoff',headers=d['engineer'],json={'request_id':req,'repository_id':repo['id']})
    assert r.status_code==200,r.text
    return r.json()['engineering_id']


def coverage(client,d):
    value=spec();old=value['customer_tenant_id'];value['customer_tenant_id']=d['north']['id']
    for c in value['cases']:
        for name in ('actor_tenant_id','resource_tenant_id'):
            if c['input'][name]==old:c['input'][name]=d['north']['id']
    r=client.post('/v1/release/requirements',headers=d['engineer'],json={'project_id':'atlas-project','spec':value,'customer_account_id':d['north']['id']})
    assert r.status_code==201,r.text
    r=client.post('/v1/release/requirements/'+r.json()['id']+'/approve',headers=d['staff'],json={'expected_hash':r.json()['requirement_hash']})
    assert r.status_code==200,r.text
    return r.json()


def candidate(client,d,iid):
    patch=client.get('/v1/repository-cases/pallets__flask-4160/example',headers=d['engineer']).json()['patch']
    r=client.post(f'/v1/engineering/{iid}/manual-patch',headers=d['engineer'],json={'patch':patch,'candidate_origin':'human'})
    assert r.status_code==200,r.text


def test_registration_scope_replay_and_no_false_execution_proof(client,customer_story):
    d=customer_story;repo=register(client,d);assert register(client,d)==repo
    assert 'Metadata only' in repo['registration_proof'] and not repo['customers']
    assert client.get('/v1/repositories',headers=login(client,'nova-admin')).json()==[]
    assert client.get('/v1/repositories',headers=d['north_auth']).status_code==401
    r=client.post('/v1/repositories',headers=d['engineer'],json={'project_id':'atlas-project','key':'shared-flask','label':'Different','kind':'pinned','case_id':'pallets__flask-4160'})
    assert r.status_code==409


@pytest.mark.parametrize('extra',[{'path':'/tmp/repo'},{'url':'https://user:secret@example.com/repo'},{'command':'run tests'}, {'token':'secret'}])
def test_browser_never_supplies_repository_paths_commands_or_credentials(client,customer_story,extra):
    r=client.post('/v1/repositories',headers=customer_story['engineer'],json={'project_id':'atlas-project','key':'bad-input','label':'Source','kind':'pinned','case_id':'pallets__flask-4160',**extra})
    assert r.status_code==422


def test_customer_association_required_before_handoff_no_partial_work(client,fixture_db,customer_story,local_repo):
    d=customer_story;repo=register(client,d);req,_=adopted(client,d)
    r=client.post('/v1/repositories/handoff',headers=d['engineer'],json={'request_id':req,'repository_id':repo['id']})
    assert r.status_code==409
    with fixture_db() as db:assert db.scalar(select(func.count()).select_from(EngineeringItem))==0
    repo=link(client,d,repo)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses=list(pool.map(lambda _:client.post('/v1/repositories/handoff',headers=d['engineer'],json={'request_id':req,'repository_id':repo['id']}),range(4)))
    assert all(r.status_code==200 for r in responses),[r.text for r in responses]
    assert len({r.json()['engineering_id'] for r in responses})==1
    with fixture_db() as db:assert db.scalar(select(func.count()).select_from(EngineeringItem))==1 and db.get(InferenceBudget,'global').reserved_calls==0


def test_no_cross_vendor_customer_connection_or_unsupported_compatibility(client,customer_story):
    d=customer_story;repo=register(client,d)
    r=client.post('/v1/repositories/'+repo['id']+'/customers',headers=login(client,'nova-admin'),json={'expected_revision':1,'customer_id':d['north']['id'],'enabled':True})
    assert r.status_code==404
    unsupported=register(client,d,key='other-flask',case_id='pallets__flask-4169')
    assert client.post('/v1/repositories/'+unsupported['id']+'/customers',headers=d['engineer'],json={'expected_revision':1,'customer_id':d['north']['id'],'enabled':True}).status_code==422


def test_unconnected_legacy_case_binding_cannot_bypass_customer_intake(client,customer_story,local_repo):
    d=customer_story;req,_=adopted(client,d)
    r=client.post('/v1/requests/'+req+'/manual-handoff',headers={**d['engineer'],'Idempotency-Key':'manual-customer-handoff'});assert r.status_code==200,r.text
    iid=client.get('/v1/engineering',headers=d['engineer']).json()[0]['id']
    assert client.post(f'/v1/engineering/{iid}/repository',headers=d['engineer'],json={'case_id':'pallets__flask-4160'}).status_code==422


def test_disconnect_restore_fences_candidate_then_explicit_reconnect_requires_fresh_coverage(client,customer_story,local_repo):
    d=customer_story;repo=link(client,d,register(client,d));req,_=adopted(client,d);iid=handoff(client,d,repo,req)
    candidate(client,d,iid)
    assert client.post(f'/v1/engineering/{iid}/verify',headers=d['engineer']).status_code==409
    requirement=coverage(client,d)
    assert client.post(f'/v1/engineering/{iid}/release-assurance',headers=d['engineer'],json={'requirement_ids':[requirement['id']]}).status_code==200
    detail=client.get(f'/v1/engineering/{iid}',headers=d['engineer']).json();repo=link(client,d,repo,enabled=False);repo=link(client,d,repo,enabled=True)
    assert client.post(f'/v1/engineering/{iid}/verify',headers=d['engineer']).status_code==409
    r=client.post(f'/v1/engineering/{iid}/repository/reconnect',headers=d['engineer'],json={'repository_id':repo['id'],'expected_context_hash':detail['repository']['context_hash']})
    assert r.status_code==200,r.text
    assert r.json()['customer_release'] is None and r.json()['verification_id'] is None
    assert client.post(f'/v1/engineering/{iid}/verify',headers=d['engineer']).status_code==409
    assert client.post(f'/v1/engineering/{iid}/release-assurance',headers=d['engineer'],json={'requirement_ids':[requirement['id']]}).status_code==200
    assert client.post(f'/v1/engineering/{iid}/verify',headers=d['engineer']).status_code==202


def test_complete_customer_repository_review_update_with_explicit_execution_doubles(client,fixture_db,customer_story,local_repo,monkeypatch):
    d=customer_story;repo=link(client,d,register(client,d));req,submission=adopted(client,d);iid=handoff(client,d,repo,req)
    requirement=coverage(client,d);candidate(client,d,iid)
    assert client.post(f'/v1/engineering/{iid}/release-assurance',headers=d['engineer'],json={'requirement_ids':[requirement['id']]}).status_code==200
    queued=client.post(f'/v1/engineering/{iid}/verify',headers=d['engineer']);assert queued.status_code==202,queued.text
    fake_executor(monkeypatch)
    from ownstack import repository_worker,repository_release
    execute=repository_worker.execute
    def wrapped(case,patch,output,cache,origin):
        report=execute(case,patch,output,cache,origin);(output/'source.json').write_text(json.dumps(SOURCE));return {**report,'image_id':SOURCE['image_id']}
    monkeypatch.setattr(repository_worker,'execute',wrapped)
    monkeypatch.setattr(repository_release,'run',lambda base,candidate,b,output,**kw:synthetic_report(b,SOURCE))
    assert work(fixture_db,local_repo)
    detail=client.get(f'/v1/engineering/{iid}',headers=d['engineer']).json();assert detail['current_checks_usable']
    exact={'patch_hash':detail['patch_hash'],'verification_id':detail['repository']['verification_id'],'context_hash':detail['repository']['context_hash']}
    share={'item_id':iid,**exact};path='/v1/customers/inbox/'+submission+'/share-repository-review'
    assert client.post(path,headers=d['engineer'],json=share).status_code==409
    assert client.post(f'/v1/engineering/{iid}/decide',headers=d['engineer'],json={'decision':'accept_for_manual_release',**exact}).status_code==200
    for _ in range(2):assert client.post(path,headers=d['engineer'],json=share).status_code==200
    public=client.get('/v1/customer-portal/requests',headers=d['north_auth']).json()[0]
    assert public['review_update'] and public['released'] is False and 'patch_hash' not in public
    assert client.get('/v1/customer-portal/requests',headers=d['south_auth']).json()==[]
    repo=link(client,d,repo,enabled=False)
    assert client.get(f'/v1/engineering/{iid}/artifact',headers=d['engineer']).status_code==409
    assert client.post(path,headers=d['engineer'],json=share).status_code==409


def test_python_snapshot_connection_is_exact_and_discovery_fences_later_revision(client,fixture_db,customer_story,tmp_path):
    d=customer_story;s,_=discovery(client,d,tmp_path)
    repo=register(client,d,key='python-app',kind='python',case_id=None,source_sha256=s['source_sha256']);repo=link(client,d,repo)
    req=s['request_id']
    r=client.post('/v1/change-agents',headers=d['engineer'],json={'request_id':req,'source_sha256':s['source_sha256'],'repository_id':repo['id'],'idempotency_key':'connected-python-discovery'})
    assert r.status_code==201,r.text
    saved=r.json();assert saved['repository']['repository_id']==repo['id']
    assert client.post('/v1/change-agents',headers=d['engineer'],json={'request_id':req,'source_sha256':s['source_sha256'],'idempotency_key':'connected-python-discovery'}).status_code==409
    assert client.post('/v1/change-agents',headers=d['engineer'],json={'request_id':req,'source_sha256':s['source_sha256'],'idempotency_key':'new-unconnected-key'}).status_code==409
    client.post('/v1/repositories/'+repo['id']+'/status',headers=d['engineer'],json={'expected_revision':repo['revision'],'enabled':False})
    assert client.post('/v1/change-agents/'+saved['id']+'/answers',headers=d['engineer'],json={'expected_revision':saved['revision'],'answers':{'roles':['manager']}}).status_code==409


def test_offline_missing_repository_archive_never_constructs_network_client(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from ownstack import repository_executor as executor
    monkeypatch.setenv('OWNSTACK_REPOSITORY_OFFLINE','true');monkeypatch.setattr(executor,'private_directory',lambda p:p)
    monkeypatch.setattr('httpx.Client',lambda *a,**kw:pytest.fail('Offline must not fetch'))
    case=SimpleNamespace(base_commit='a'*40,repo='pallets/flask')
    with pytest.raises(ValueError,match='no fetch was attempted'):executor.fetch_source(case,tmp_path)
    assert list(tmp_path.iterdir())==[]


def test_legacy_source_check_cannot_bypass_configured_customer_repository(client,fixture_db,customer_story):
    d=customer_story;repo=link(client,d,register(client,d));requirement=coverage(client,d)
    r=client.post('/v1/release/checks',headers=d['engineer'],json={'project_id':'atlas-project','baseline_sha256':'a'*64,
        'candidate_sha256':'b'*64,'requirement_ids':[requirement['id']],'idempotency_key':'legacy-admission-denied'})
    assert r.status_code==409 and 'repository' in r.json()['detail'].lower()


def test_source_comparison_carries_repository_witness_and_discards_after_disconnect(client,fixture_db,customer_story,tmp_path):
    from test_release_journeys import explicit_result_double
    from ownstack.release_assurance import claim_next,finish_check
    d=customer_story;s,_=discovery(client,d,tmp_path)
    repo=link(client,d,register(client,d,key='source-comparison',kind='python',case_id=None,source_sha256=s['source_sha256']))
    requirement=coverage(client,d)
    r=client.post('/v1/release/checks',headers=d['engineer'],json={'project_id':'atlas-project','baseline_sha256':s['source_sha256'],
        'candidate_sha256':'b'*64,'requirement_ids':[requirement['id']],'idempotency_key':'connected-source-check'})
    assert r.status_code==202,r.text
    ident=r.json()['id'];claim=claim_next(fixture_db,only_id=ident);assert claim
    r=client.post('/v1/repositories/'+repo['id']+'/status',headers=d['engineer'],json={'expected_revision':repo['revision'],'enabled':False});assert r.status_code==200
    assert finish_check(fixture_db,ident,claim['claim_token'],explicit_result_double(claim))
    assert client.get('/v1/release/checks/'+ident,headers=d['engineer']).json()['state']=='blocked'
