"""Fast policy/identity checks; actual isolated HTTP journeys are separate."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import ownstack.release_executor as executor
from ownstack.release_contracts import RequirementSpec
from ownstack.policy import digest


@pytest.fixture
def requirement():
    context={'actor_id':'contractor-a','actor_tenant_id':'atlas','actor_role':'contractor',
             'resource_id':'atlas-doc','resource_tenant_id':'atlas','assigned':False,'at':'2026-10-27T12:00:00Z'}
    return RequirementSpec.model_validate({'schema_version':1,'key':'atlas-assignment','version':1,
        'customer_tenant_id':'atlas','title':'Contractors need assignment','source_ref':'synthetic:approved-1','owner_id':'engineer',
        'cases':[{'case_id':'atlas-unassigned','title':'Atlas unassigned deny','kind':'target','input':context,
                  'expected':{'status_code':403,'visible_fields':[]}},
                 {'case_id':'nova-member','title':'Nova remains readable','kind':'control',
                  'input':dict(context,actor_id='member-n',actor_tenant_id='nova',actor_role='member',resource_id='nova-doc',resource_tenant_id='nova'),
                  'expected':{'status_code':200,'visible_fields':['id','title','internal_notes']}}]})


def observations(requirement,*,bad=False):
    rows=[]
    for case in requirement.cases:
        rows.append({'requirement_key':requirement.key,'case_id':case.case_id,
                     'status_code':200 if bad and case.case_id=='atlas-unassigned' else case.expected.status_code,
                     'visible_fields':['id','title'] if bad and case.case_id=='atlas-unassigned' else list(case.expected.visible_fields),
                     'error':None})
    return {'state':'completed','failure':'','cleanup_verified':True,'observations':rows}


def test_snapshot_only_reads_and_binds_reviewed_app_file(tmp_path):
    root=tmp_path/'repo';root.mkdir();(root/'app.py').write_text('print("not executed")\n')
    (root/'unreviewed.txt').write_text('ignored by declared profile')
    first=executor.snapshot_repository(root)
    assert first['files']=={'app.py':hashlib.sha256((root/'app.py').read_bytes()).hexdigest()}
    (root/'app.py').write_text('print("changed")\n')
    assert executor.snapshot_repository(root)['sha256']!=first['sha256']


@pytest.mark.parametrize('kind',['symlink-root','symlink-file','fifo','empty','oversized'])
def test_unsafe_source_refused_without_importing_it(tmp_path,kind):
    root=tmp_path/'repo';root.mkdir();file=root/'app.py'
    if kind=='symlink-root':
        file.write_text('x=1');link=tmp_path/'link';link.symlink_to(root,target_is_directory=True);root=link
    elif kind=='symlink-file':
        target=tmp_path/'outside';target.write_text('x=1');file.symlink_to(target)
    elif kind=='fifo':os.mkfifo(file)
    elif kind=='empty':file.write_bytes(b'')
    else:file.write_bytes(b'x'*(executor.MAX_FILE+1))
    with pytest.raises((ValueError,OSError)):executor.snapshot_repository(root)


def test_container_command_has_fixed_entrypoint_and_isolation(tmp_path):
    command=executor.docker_command('ownstack-release-'+'a'*32,'sha256:'+'b'*64,tmp_path)
    for option,value in [('--network','none'),('--user','65534:65534'),('--pull','never'),('--entrypoint','python')]:
        assert command[command.index(option)+1]==value
    assert '--read-only' in command and '--cap-drop' in command
    assert command[command.index('--mount')+1].endswith('dst=/repo,readonly')
    assert not any('KEY' in item or 'TOKEN' in item or 'docker.sock' in item for item in command)
    assert command[-3:]==['-I','-B','/repo/app.py']


@pytest.mark.parametrize('name,image,path',[('foreign','sha256:'+'b'*64,'safe'),('ownstack-release-'+'a'*32,'latest','safe'),
 ('ownstack-release-'+'a'*32,'sha256:'+'b'*64,'bad,src=/etc')])
def test_mutable_image_name_and_mount_injection_refused(tmp_path,name,image,path):
    with pytest.raises(ValueError):executor.docker_command(name,image,tmp_path/path)


def test_bundle_hash_matches_control_plane_sorting(requirement):
    other=RequirementSpec.model_validate({**requirement.model_dump(mode='json'),'key':'another-requirement'})
    expected=digest([s.model_dump(mode='json') for s in sorted([requirement,other],key=lambda s:(s.key,s.version))])
    assert executor.requirements_digest([requirement,other])==executor.requirements_digest([other,requirement])==expected
    with pytest.raises(ValueError):executor.requirements_digest([requirement,requirement])


def test_exact_customer_regression_and_control_are_visible(requirement):
    report=executor.assess_observations([requirement],observations(requirement),observations(requirement,bad=True))
    assert report['status']=='failed' and report['baseline_valid'] and not report['candidate_valid']
    assert report['assessments'][0]['regression'] and not report['assessments'][1]['regression']
    assert report['assessments'][1]['candidate_passed']


@pytest.mark.parametrize('mutation',['duplicate','missing','transport-error','cleanup-unverified','blocked','wrong-id'])
def test_missing_duplicate_or_uncertain_evidence_never_passes(requirement,mutation):
    base=observations(requirement);candidate=deepcopy(base)
    if mutation=='duplicate':candidate['observations'].append(candidate['observations'][0])
    elif mutation=='missing':candidate['observations'].pop()
    elif mutation=='transport-error':candidate['observations'][0]['error']='TimeoutError'
    elif mutation=='cleanup-unverified':candidate['cleanup_verified']=False
    elif mutation=='blocked':candidate['state']='blocked'
    else:candidate['observations'][0]['case_id']='different'
    assert executor.assess_observations([requirement],base,candidate)['status']=='blocked'


def test_a_broken_baseline_does_not_make_candidate_acceptable(requirement):
    result=executor.assess_observations([requirement],observations(requirement,bad=True),observations(requirement))
    assert result['status']=='blocked' and not result['passed'] and result['candidate_valid']


def test_actual500_and_field_leak_are_retained_as_failures(requirement):
    base=observations(requirement);candidate=deepcopy(base)
    candidate['observations'][0].update(status_code=500,visible_fields=['internal_notes'])
    result=executor.assess_observations([requirement],base,candidate)
    assert result['status']=='failed'
    assert result['assessments'][0]['observed_candidate']=={'status_code':500,'visible_fields':['internal_notes']}


def test_host_recomputes_flags_instead_of_trusting_operator_boolean(requirement):
    base=observations(requirement);candidate=observations(requirement,bad=True)
    report={'runner':executor.RUNNER,'profile':executor.PROFILE,'policy':executor.POLICY,
        'baseline_sha256':'a'*64,'candidate_sha256':'b'*64,'requirements_sha256':executor.requirements_digest([requirement]),
        'oracle_sha256':hashlib.sha256((executor.HTTP_CLIENT+executor.READY_CLIENT).encode()).hexdigest(),
        'execution_policy_sha256':executor.execution_fingerprint(),
        'image_id':'sha256:'+'c'*64,'provider_calls':0,'released':False,'baseline':base,'candidate':candidate,
        **executor.assess_observations([requirement],base,candidate)}
    assert executor.validate_report(report,[requirement],'a'*64,'b'*64)['status']=='failed'
    report['passed']=True
    with pytest.raises(ValueError,match='decision differs'):executor.validate_report(report,[requirement],'a'*64,'b'*64)


@pytest.mark.parametrize('deadline',[0,91,True,1.5])
def test_unbounded_deadline_rejected_before_docker(tmp_path,requirement,deadline):
    with pytest.raises(ValueError,match='deadline'):
        executor.run_release(tmp_path,tmp_path,[requirement],tmp_path/'nope',image='sha256:'+'a'*64,timeout=deadline)


def test_expected_snapshot_fencing_happens_before_any_tool(tmp_path,requirement,monkeypatch):
    source=tmp_path/'repo';source.mkdir();(source/'app.py').write_text('raise RuntimeError("must not import")')
    monkeypatch.setattr(executor,'capture',lambda *args,**kw:pytest.fail('No Docker before source fences'))
    with pytest.raises(ValueError,match='Baseline snapshot'):
        executor.run_release(source,source,[requirement],tmp_path/'nope',image='sha256:'+'a'*64,expected_baseline_sha256='b'*64)


def test_remote_context_refused_before_execution(tmp_path,requirement,monkeypatch):
    monkeypatch.setenv('DOCKER_HOST','tcp://remote:2375')
    monkeypatch.setattr(executor,'capture',lambda *args,**kw:pytest.fail('No remote Docker calls'))
    with pytest.raises(ValueError,match='Remote Docker'):
        executor.run_release(tmp_path,tmp_path,[requirement],tmp_path/'nope',image='sha256:'+'a'*64)


def test_independent_client_never_receives_expected_results(tmp_path,requirement,monkeypatch):
    calls=[]
    expected=observations(requirement)['observations']
    def fake(command,payload,**kwargs):
        calls.append((command,payload,kwargs))
        if command[:2]==['docker','run']:raw=('a'*64).encode()
        elif executor.READY_CLIENT in command:raw=b'{"ready":true}'
        else:
            assert json.loads(payload)==[{'requirement_key':requirement.key,'case_id':case.case_id,'input':case.input.model_dump(mode='json')} for case in requirement.cases]
            raw=json.dumps({'observations':expected}).encode()
        return {'stdout_bytes':raw,'stderr':'','exit_code':0,'failure':''}
    monkeypatch.setattr(executor,'capture',fake)
    def cleanup(command,**kwargs):
        return SimpleNamespace(returncode=1,stderr=b'error: no such object: owned') if 'inspect' in command else SimpleNamespace(returncode=0,stderr=b'')
    monkeypatch.setattr(executor.subprocess,'run',cleanup)
    tree=tmp_path/'snapshot';tree.mkdir();(tree/'app.py').write_text('never imported')
    rows=[{'requirement_key':requirement.key,'case_id':case.case_id,'input':case.input.model_dump(mode='json')} for case in requirement.cases]
    report=executor._stage(tree,rows,tmp_path/'output','sha256:'+'b'*64,timeout=10)
    assert report['state']=='completed' and report['cleanup_verified']
    for command,payload,kwargs in calls:
        if command[:2]==['docker','exec']:assert command[command.index('--user')+1]=='65533:65533'
        assert set(kwargs['env'])=={'PATH','HOME'}


def test_ambiguous_start_never_deletes_by_container_name(tmp_path,requirement,monkeypatch):
    monkeypatch.setattr(executor,'capture',lambda *args,**kw:{'stdout_bytes':b'','stderr':'','exit_code':1,'failure':'start uncertain'})
    monkeypatch.setattr(executor.subprocess,'run',lambda *args,**kwargs:pytest.fail('No deletion without creation receipt'))
    tree=tmp_path/'source';tree.mkdir()
    result=executor._stage(tree,[],tmp_path/'output','sha256:'+'b'*64,timeout=5)
    assert result['state']=='blocked' and not result['cleanup_verified']


@pytest.mark.parametrize('change',[{'Id':'wrong'},{'Name':'/unrelated'},{'Image':'different'},{'Config':{'Labels':{'ownstack.job':'other'}}}])
def test_positive_creation_id_still_requires_exact_owner_metadata(monkeypatch,change):
    container='a'*64;name='ownstack-release-'+'b'*32;image='sha256:'+'c'*64
    info={'Id':container,'Name':'/'+name,'Image':image,'Config':{'Labels':{'ownstack.job':'release-assurance'}},**change}
    def inspect_only(command,**kwargs):
        assert command==['docker','inspect',container],'Never delete a mismatched owner'
        return SimpleNamespace(returncode=0,stdout=json.dumps([info]).encode(),stderr=b'')
    monkeypatch.setattr(executor.subprocess,'run',inspect_only)
    assert executor._cleanup_created(container,name,image,{}) is False


def test_cleanup_uses_verified_exact_id_then_explicit_absence(monkeypatch):
    container='a'*64;name='ownstack-release-'+'b'*32;image='sha256:'+'c'*64;calls=[]
    info={'Id':container,'Name':'/'+name,'Image':image,'Config':{'Labels':{'ownstack.job':'release-assurance'}}}
    def command(argv,**kwargs):
        calls.append(argv)
        if len(calls)==1:return SimpleNamespace(returncode=0,stdout=json.dumps([info]).encode(),stderr=b'')
        if len(calls)==2:
            assert argv==['docker','rm','--force',container]
            return SimpleNamespace(returncode=0,stdout=b'',stderr=b'')
        return SimpleNamespace(returncode=1,stdout=b'',stderr=b'error: no such object: owned')
    monkeypatch.setattr(executor.subprocess,'run',command)
    assert executor._cleanup_created(container,name,image,{})
