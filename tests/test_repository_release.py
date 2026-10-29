"""Finite boundary/lifecycle controls. Actual container journeys saved separately."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from conftest import login
from ownstack.models import EngineeringItem,InferenceBudget,ReleaseRequirement
from ownstack.policy import digest
from ownstack import repository_release as gate
from ownstack.release_executor import assess_observations,requirements_digest,HTTP_CLIENT,READY_CLIENT
from test_release_contracts import spec
from test_repository_cockpit import item,fake_executor,work,local_repo


def approved(client,version=1):
    engineer=login(client,'atlas-engineer')
    value=spec(version=version)
    result=client.post('/v1/release/requirements',headers=engineer,json={'project_id':'atlas-project','spec':value})
    assert result.status_code==201,result.text
    record=result.json();admin=login(client,'atlas-admin')
    response=client.post('/v1/release/requirements/'+record['id']+'/approve',headers=admin,json={'expected_hash':record['requirement_hash']})
    assert response.status_code==200,response.text
    return response.json()


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv('OWNSTACK_RELEASE_ASSURANCE','true')


def test_bind_requires_all_current_exact_coverage_and_scope(client,local_repo,enabled):
    iid,_,engineer,patch=item(client)
    route=f'/v1/engineering/{iid}/release-assurance'
    assert client.post(route,headers=engineer,json={'requirement_ids':['unknown']}).status_code==409
    requirement=approved(client)
    for ids in ([],['unknown'],[requirement['id'],requirement['id']]):
        assert client.post(route,headers=engineer,json={'requirement_ids':ids}).status_code in {409,422}
    assert client.post(route,headers=login(client,'nova-admin'),json={'requirement_ids':[requirement['id']]}).status_code in {403,404}
    result=client.post(route,headers=engineer,json={'requirement_ids':[requirement['id']]})
    assert result.status_code==200,result.text
    assert result.json()['requirements']==[requirement['spec']]
    before=client.get(f'/v1/engineering/{iid}',headers=engineer).json()
    assert client.post(route,headers=engineer,json={'requirement_ids':[requirement['id']]}).json()==result.json()
    assert client.post(f'/v1/engineering/{iid}/manual-patch',headers=engineer,json={'patch':patch,'candidate_origin':'human'}).status_code==200
    after=client.get(f'/v1/engineering/{iid}',headers=engineer).json()
    assert after['repository']['customer_release']==result.json()
    assert after['repository']['context_hash']!=before['repository']['context_hash']


def test_new_requirements_invalidate_old_context_and_explicit_rebind_works(client,local_repo,enabled):
    iid,_,headers,_=item(client);first=approved(client)
    url=f'/v1/engineering/{iid}/release-assurance'
    assert client.post(url,headers=headers,json={'requirement_ids':[first['id']]}).status_code==200
    second=approved(client,2)
    assert client.post(f'/v1/engineering/{iid}/verify',headers=headers).status_code==409
    rebound=client.post(url,headers=headers,json={'requirement_ids':[second['id']]})
    assert rebound.status_code==200,rebound.text
    assert client.post(f'/v1/engineering/{iid}/verify',headers=headers).status_code==202
    assert client.post(url,headers=headers,json={'requirement_ids':[second['id']]}).status_code==409


def synthetic_report(binding,source,regression=False):
    rows=[{'requirement_key':s['key'],'case_id':c['case_id'],'status_code':c['expected']['status_code'],
           'visible_fields':c['expected']['visible_fields'],'error':None} for s in binding['requirements'] for c in s['cases']]
    baseline={'state':'completed','cleanup_verified':True,'observations':deepcopy(rows),'failure':''}
    candidate=deepcopy(baseline)
    if regression:candidate['observations'][0]['status_code']=200
    return {'profile':gate.PROFILE,'policy_sha256':gate.fingerprint(),'binding_sha256':digest(binding),
        'requirements_sha256':requirements_digest(binding['requirements']),
        'oracle_sha256':hashlib.sha256((gate.SERVER+HTTP_CLIENT+READY_CLIENT).encode()).hexdigest(),
        **source,'provider_calls':0,'released':False,'baseline':baseline,'candidate':candidate,
        **assess_observations(binding['requirements'],baseline,candidate)}


def binding():
    return {'profile':gate.PROFILE,'requirements':[spec()],'policy_sha256':gate.fingerprint()}


SOURCE={'image_id':'sha256:'+'a'*64,'baseline_tree_sha256':'b'*64,'candidate_tree_sha256':'c'*64}


@pytest.mark.parametrize('field,value',[
    ('profile','unknown'),('policy_sha256','f'*64),('binding_sha256','f'*64),
    ('requirements_sha256','f'*64),('oracle_sha256','f'*64),('image_id','mutable:latest'),
    ('baseline_tree_sha256','f'*64),('candidate_tree_sha256','f'*64),
    ('provider_calls',True),('provider_calls',1),('released',True),('passed',False),
])
def test_report_provenance_and_claimed_verdict_tampering_rejected(field,value):
    b=binding();report=synthetic_report(b,SOURCE);report[field]=value
    with pytest.raises(ValueError):gate.validate(report,b,SOURCE)


def test_regression_and_incomplete_cleanup_cannot_be_forged_as_pass():
    b=binding();report=synthetic_report(b,SOURCE,True)
    assert gate.validate(report,b,SOURCE)['passed'] is False
    report['candidate']['cleanup_verified']=False
    with pytest.raises(ValueError):gate.validate(report,b,SOURCE)


def test_fixed_command_keeps_isolation_and_never_contains_expected_results(tmp_path):
    command=gate.command('ownstack-release-'+'a'*32,SOURCE['image_id'],tmp_path)
    for expected in ('none','--read-only','ALL','no-new-privileges','65534:65534','never'):
        assert expected in command
    assert command[-2:]==['-c',gate.SERVER]
    assert 'expected' not in gate.SERVER
    assert '/repo/src' in gate.SERVER


def test_current_requirement_authority_revocation_blocks_queue(client,fixture_db,local_repo,enabled):
    iid,_,headers,_=item(client);requirement=approved(client)
    assert client.post(f'/v1/engineering/{iid}/release-assurance',headers=headers,json={'requirement_ids':[requirement['id']]}).status_code==200
    with fixture_db() as db:
        from ownstack.models import User
        db.get(User,'atlas-admin').token_version+=1;db.commit()
    assert client.post(f'/v1/engineering/{iid}/verify',headers=headers).status_code==409


@pytest.mark.parametrize('regression',[False,True])
def test_combined_gate_controls_review_and_saved_replay(client,fixture_db,local_repo,enabled,monkeypatch,regression):
    iid,_,headers,_=item(client);requirement=approved(client)
    assert client.post(f'/v1/engineering/{iid}/release-assurance',headers=headers,json={'requirement_ids':[requirement['id']]}).status_code==200
    queued=client.post(f'/v1/engineering/{iid}/verify',headers=headers).json()
    fake_executor(monkeypatch)
    from ownstack import repository_worker
    original=repository_worker.execute
    def execute(case,patch,output,cache,origin):
        report=original(case,patch,output,cache,origin)
        (output/'source.json').write_text(json.dumps(SOURCE))
        return {**report,'image_id':SOURCE['image_id']}
    monkeypatch.setattr(repository_worker,'execute',execute)
    monkeypatch.setattr(gate,'run',lambda base,candidate,b,output,**kw:synthetic_report(b,SOURCE,regression))
    assert work(fixture_db,local_repo)
    detail=client.get(f'/v1/engineering/{iid}',headers=headers).json()
    assert detail['current_checks_usable'] is not regression
    assert detail['repository']['checks'][-1]['report']['upstream_passed'] is True
    exact={'decision':'accept_for_manual_release','patch_hash':detail['patch_hash'],
           'verification_id':queued['id'],'context_hash':detail['repository']['context_hash']}
    assert client.post(f'/v1/engineering/{iid}/decide',headers=headers,json=exact).status_code==(409 if regression else 200)
    if not regression:
        assert client.get(f'/v1/engineering/{iid}/artifact',headers=headers).status_code==200
        with fixture_db() as db:
            from ownstack.models import User
            db.get(User,'atlas-admin').token_version+=1;db.commit()
        assert client.get(f'/v1/engineering/{iid}',headers=headers).json()['current_checks_usable'] is False
        assert client.get(f'/v1/engineering/{iid}/artifact',headers=headers).status_code==409
    with fixture_db() as db:assert db.get(InferenceBudget,'global').reserved_calls==0
