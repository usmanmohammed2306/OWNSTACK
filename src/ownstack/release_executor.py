"""Bounded, operator-only HTTP checks of a reviewed one-file Python adapter.

Candidate code runs only in a fresh non-root, read-only, networkless container.
A different-UID fixed HTTP client observes responses; expected results remain on
the operator host. This finite local profile is not arbitrary repository support
or a certified hostile-code sandbox. A result never authorizes deployment.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
from uuid import uuid4

from ownstack.bounded_process import capture

ROOT = Path(__file__).resolve().parents[2]
PROFILE = 'python-http-visibility-v1'
RUNNER = 'release-http-docker-v1'
POLICY = 'release-http-no-network-readonly-separate-oracle-uid-v1'
MAX_FILE = 262144
MAX_CASES = 256
MAX_OUTPUT = 1024 * 1024

# This code is sent directly to a separate UID's docker-exec process. Repository
# stdout is never parsed as a test report, and no expected assertions are mounted.
HTTP_CLIENT = r'''
import json,sys,time,urllib.error,urllib.parse,urllib.request
rows=json.load(sys.stdin)
observations=[]
for row in rows:
    data=row['input']
    path='/documents/'+urllib.parse.quote(data['resource_id'],safe='')
    request=urllib.request.Request('http://127.0.0.1:8765'+path,
        data=json.dumps(data,separators=(',',':')).encode(),
        headers={'Content-Type':'application/json'},method='POST')
    result={'requirement_key':row['requirement_key'],'case_id':row['case_id'],
            'status_code':None,'visible_fields':[],'error':None}
    try:
        try:
            response=urllib.request.urlopen(request,timeout=.75)
        except urllib.error.HTTPError as error:
            response=error
        with response:
            result['status_code']=response.status
            body=response.read(65537)
        if len(body)>65536:raise ValueError('Response exceeds profile bound')
        body=json.loads(body)
        if not isinstance(body,dict) or any(not isinstance(key,str) or len(key)>128 for key in body):
            raise ValueError('Response must be a bounded field object')
        result['visible_fields']=sorted(body)
    except Exception as error:
        result['error']=type(error).__name__
    observations.append(result)
print(json.dumps({'observations':observations},separators=(',',':')))
'''

READY_CLIENT = r'''
import json,time,urllib.request
ready=False
for unused in range(50):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/health',timeout=.2) as response:
            ready=response.status==200 and response.read(32)==b'ready'
        if ready:break
    except Exception:pass
    time.sleep(.1)
print(json.dumps({'ready':ready}))
'''


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _json(path: Path, value) -> None:
    fd, temporary = tempfile.mkstemp(prefix='.private-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(value,stream,sort_keys=True,indent=2);stream.write('\n')
            stream.flush();os.fsync(stream.fileno())
        os.link(temporary,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _private_output(path: Path) -> Path:
    path=Path(path).absolute()
    anchor=ROOT/'.private'
    if anchor.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(anchor.resolve()):
        raise ValueError('Execution output must be a new private OwnStack directory')
    for ancestor in (path,*path.parents):
        if ancestor.is_symlink():raise ValueError('Symlink output ancestor is forbidden')
        if ancestor==anchor:break
    if path.exists():raise FileExistsError('Preserve existing release check output')
    path.mkdir(parents=True,mode=0o700)
    path.chmod(0o700)
    return path


def _source(path: Path) -> tuple[dict, bytes]:
    path=Path(path)
    if path.is_symlink() or not path.is_dir():
        raise ValueError('An explicit nonsymlink adapter directory is required')
    file=path/'app.py'
    fd=os.open(file,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0<before.st_size<=MAX_FILE:
            raise ValueError('Adapter must be a bounded regular app.py file')
        data=os.read(fd,MAX_FILE+1)
        after=os.fstat(fd)
        if (len(data)!=before.st_size or before.st_size!=after.st_size
                or before.st_mtime_ns!=after.st_mtime_ns):
            raise ValueError('Adapter changed while snapshotting')
    finally:os.close(fd)
    data.decode('utf-8')
    manifest={'app.py':hashlib.sha256(data).hexdigest()}
    return {'profile':PROFILE,'sha256':_digest({'profile':PROFILE,'files':manifest}),'files':manifest},data


def snapshot_repository(path: Path) -> dict:
    """Hash the explicitly reviewed manifest inventory, or the legacy app.py."""
    return _snapshot(path)[0]


def _snapshot(path):
    from ownstack.release_repository import MANIFEST,load
    if (Path(path)/MANIFEST).exists() or (Path(path)/MANIFEST).is_symlink():return load(path)
    identity,raw=_source(path)
    return identity,{'app.py':raw}


def repository_command(snapshot):
    from ownstack.release_repository import validate_snapshot
    config=validate_snapshot(snapshot)
    def build(name,image,tree):return docker_command(name,image,tree)[:-1]+['/repo/'+config.entrypoint]
    return build


def requirements_digest(requirements) -> str:
    from ownstack.release_contracts import RequirementSpec
    specs=[r if isinstance(r,RequirementSpec) else RequirementSpec.model_validate(r) for r in requirements]
    if not specs or len(specs)>32 or len({s.key for s in specs})!=len(specs):
        raise ValueError('Use one to32 uniquely identified requirements')
    return _digest([s.model_dump(mode='json') for s in sorted(specs,key=lambda s:(s.key,s.version))])


def docker_command(name: str,image_id: str,tree: Path) -> list[str]:
    if not re.fullmatch(r'ownstack-release-[a-f0-9]{32}',name):
        raise ValueError('Owned unique container name required')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',image_id):
        raise ValueError('Immutable existing image ID required')
    if any(c in str(tree.resolve()) for c in ',\n\r\x00'):
        raise ValueError('Unsafe mount path')
    return ['docker','run','--detach','--name',name,'--pull','never','--log-driver','none',
            '--label','ownstack.job=release-assurance','--network','none','--read-only',
            '--cap-drop','ALL','--security-opt','no-new-privileges','--user','65534:65534',
            '--pids-limit','64','--memory','256m','--memory-swap','256m','--cpus','1',
            '--ulimit','cpu=60:60','--ulimit','fsize=1048576:1048576','--ulimit','nofile=64:64',
            '--tmpfs','/tmp:rw,noexec,nosuid,size=16777216,mode=1777',
            '--mount',f'type=bind,src={tree.resolve()},dst=/repo,readonly',
            '--workdir','/repo','--entrypoint','python',image_id,'-I','-B','/repo/app.py']


def assess_observations(requirements,baseline: dict,candidate: dict) -> dict:
    """Independently evaluate exact case identities and observed response fields."""
    from ownstack.release_contracts import RequirementSpec,VisibilityObservation,evaluate_observation
    specs=[r if isinstance(r,RequirementSpec) else RequirementSpec.model_validate(r) for r in requirements]
    cases={(spec.key,case.case_id):case for spec in specs for case in spec.cases}
    assessments=[]
    observed={}
    for stage,value in (('baseline',baseline),('candidate',candidate)):
        if not isinstance(value,dict):raise ValueError('Stage must be an observed HTTP report')
        rows=value.get('observations',[])
        if (not isinstance(rows,list) or any(not isinstance(row,dict)
                or set(row)!={'requirement_key','case_id','status_code','visible_fields','error'}
                or not isinstance(row['requirement_key'],str) or not isinstance(row['case_id'],str) for row in rows)):
            raise ValueError('Invalid HTTP observation identity/shape')
        ids=[(row.get('requirement_key'),row.get('case_id')) for row in rows]
        if (value.get('state')!='completed' or value.get('failure') or len(ids)!=len(set(ids))
                or value.get('cleanup_verified') is not True
                or set(ids)!=set(cases) or any(row.get('error') for row in rows)):
            return {'passed':False,'status':'blocked','baseline_valid':False,'candidate_valid':False,
                    'assessments':[],'reason':'Incomplete, duplicate, failed or mismatched HTTP observation set'}
        observed[stage]={ident:row for ident,row in zip(ids,rows)}
    for ident,case in cases.items():
        values={}
        for stage in ('baseline','candidate'):
            row=observed[stage][ident]
            try:
                actual=VisibilityObservation(status_code=row['status_code'],visible_fields=row['visible_fields'])
            except ValueError:
                return {'passed':False,'status':'blocked','baseline_valid':False,'candidate_valid':False,
                        'assessments':[],'reason':'Observed response violates the reviewed profile schema'}
            values[stage]=evaluate_observation(case,actual)
        base_pass=values['baseline'].passed;cand_pass=values['candidate'].passed
        assessments.append({'requirement_key':ident[0],'case_id':ident[1],
            'baseline_passed':base_pass,'candidate_passed':cand_pass,'regression':base_pass and not cand_pass,
            'expected':case.expected.model_dump(mode='json'),
            'observed_baseline':{k:observed['baseline'][ident][k] for k in ('status_code','visible_fields')},
            'observed_candidate':{k:observed['candidate'][ident][k] for k in ('status_code','visible_fields')}})
    base_ok=all(r['baseline_passed'] for r in assessments)
    candidate_ok=all(r['candidate_passed'] for r in assessments)
    return {'passed':base_ok and candidate_ok,'status':'passed' if base_ok and candidate_ok else 'failed' if base_ok else 'blocked',
            'baseline_valid':base_ok,'candidate_valid':candidate_ok,'assessments':assessments,
            'reason':'' if base_ok else 'Baseline does not satisfy approved requirements; candidate is not accepted'}


def validate_report(report: dict,requirements,baseline_sha256: str,candidate_sha256: str) -> dict:
    """Recompute decisions from frozen expectations; never trust submitted flags."""
    from ownstack.release_repository import PROFILE as repository_profile,validate_snapshot
    if (not isinstance(report,dict) or report.get('runner')!=RUNNER or report.get('profile') not in {PROFILE,repository_profile}
            or report.get('policy')!=POLICY or report.get('baseline_sha256')!=baseline_sha256
            or report.get('candidate_sha256')!=candidate_sha256
            or report.get('requirements_sha256')!=requirements_digest(requirements)
            or report.get('execution_policy_sha256')!=execution_fingerprint()
            or report.get('oracle_sha256')!=hashlib.sha256((HTTP_CLIENT+READY_CLIENT).encode()).hexdigest()
            or not re.fullmatch(r'sha256:[a-f0-9]{64}',str(report.get('image_id','')))
            or report.get('released') is not False or type(report.get('provider_calls')) is not int
            or report['provider_calls']!=0):
        raise ValueError('Report does not match frozen source, requirements or execution profile')
    if report['profile']==repository_profile:
        for phase,expected in (('baseline',baseline_sha256),('candidate',candidate_sha256)):
            snapshot=report.get(phase+'_snapshot');validate_snapshot(snapshot)
            if snapshot['sha256']!=expected:raise ValueError('Reviewed repository inventory differs from queued source')
    actual=assess_observations(requirements,report.get('baseline'),report.get('candidate'))
    for key in ('passed','status','baseline_valid','candidate_valid','assessments','reason'):
        if report.get(key)!=actual[key]:raise ValueError('Reported decision differs from independent observations')
    return actual


def _read_execution_fingerprint() -> str:
    source=Path(__file__).resolve().parent
    return _digest({name:hashlib.sha256((source/name).read_bytes()).hexdigest()
                    for name in ('release_executor.py','release_repository.py','release_contracts.py','bounded_process.py')})


def execution_fingerprint() -> str:
    if _read_execution_fingerprint()!=_LOADED_EXECUTION:
        raise ValueError('Release execution policy changed; restart the operator')
    return _LOADED_EXECUTION


def _missing_container(result) -> bool:
    message=result.stderr.lower()
    return result.returncode==1 and (b'no such object:' in message or b'no such container:' in message)


def _cleanup_created(container_id: str|None,name: str,image_id: str,env: dict) -> bool:
    """No deletion without a successful Docker creation receipt and ownership.

    A timed-out or malformed start can be ambiguous. Preserve that uncertainty
    for inspection instead of removing whatever occupies a generated name.
    """
    if container_id is None:return False
    inspected=subprocess.run(['docker','inspect',container_id],capture_output=True,timeout=10,check=False,env=env)
    if _missing_container(inspected):return True
    if inspected.returncode:return False
    info=json.loads(inspected.stdout)
    if not isinstance(info,list) or len(info)!=1:return False
    owned=info[0]
    if (owned.get('Id')!=container_id or owned.get('Name')!='/'+name or owned.get('Image')!=image_id
            or owned.get('Config',{}).get('Labels',{}).get('ownstack.job')!='release-assurance'):
        return False
    cleanup=subprocess.run(['docker','rm','--force',container_id],capture_output=True,timeout=15,check=False,env=env)
    absent=subprocess.run(['docker','inspect',container_id],capture_output=True,timeout=10,check=False,env=env)
    return cleanup.returncode==0 and _missing_container(absent)


def _stage(tree: Path,rows: list[dict],output: Path,image_id: str,*,timeout: int,command_factory=None) -> dict:
    output.mkdir(mode=0o700)
    name='ownstack-release-'+uuid4().hex
    # Only trusted operator code supplies a reviewed command builder. No API
    # accepts it, and neither expectations nor model-authored commands enter it.
    command=(command_factory or docker_command)(name,image_id,tree)
    _json(output/'invocation.json',{'argv':command,'policy':POLICY,'timeout_s':timeout})
    started=time.monotonic()
    result={'state':'blocked','failure':'','observations':[],'elapsed_s':0}
    container_id=None
    env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'HOME':os.environ.get('HOME','/tmp')}
    try:
        run=capture(command,b'',timeout=15,limit=4096,env=env)
        if run['failure'] or run['exit_code']!=0:
            raise RuntimeError('Container start failed')
        container_id=run['stdout_bytes'].decode().strip()
        if not re.fullmatch('[a-f0-9]{64}',container_id):
            container_id=None
            raise ValueError('Invalid owned container receipt')
        _json(output/'container.json',{'id':container_id,'name':name,'image_id':image_id})
        ready=capture(['docker','exec','--user','65533:65533',name,'python','-I','-B','-c',READY_CLIENT],b'',
                      timeout=10,limit=4096,env=env)
        if ready['failure'] or ready['exit_code']!=0 or json.loads(ready['stdout_bytes'])!={'ready':True}:
            raise RuntimeError('Adapter did not become ready within profile deadline')
        observed=capture(['docker','exec','--interactive','--user','65533:65533',name,'python','-I','-B','-c',HTTP_CLIENT],
            json.dumps(rows,separators=(',',':')).encode(),timeout=timeout,limit=MAX_OUTPUT,
            process_record=output/'process.json',env=env)
        _json(output/'transport.json',{'exit_code':observed['exit_code'],'failure':observed['failure'],'stderr':observed['stderr']})
        if observed['failure'] or observed['exit_code']!=0:raise RuntimeError('Independent HTTP client did not complete')
        envelope=json.loads(observed['stdout_bytes'])
        if not isinstance(envelope,dict) or set(envelope)!={'observations'} or not isinstance(envelope['observations'],list):
            raise ValueError('Invalid independent HTTP envelope')
        result.update(state='completed',observations=envelope['observations'])
    except (OSError,RuntimeError,ValueError,subprocess.SubprocessError) as error:
        result.update(failure=str(error)[:300],error_type=type(error).__name__)
    finally:
        # Only the exact positively owned creation receipt can be removed.
        result['cleanup_verified']=False
        try:
            result['cleanup_verified']=_cleanup_created(container_id,name,image_id,env)
        except (OSError,ValueError,subprocess.SubprocessError):
            pass
        if not result['cleanup_verified']:
            result.update(state='blocked',failure='Owned container cleanup could not be verified')
    result['elapsed_s']=round(time.monotonic()-started,3)
    _json(output/'report.json',result)
    return result


def run_release(base_dir: Path,candidate_dir: Path,requirements,output_dir: Path,*,image: str,
                expected_baseline_sha256: str|None=None,expected_candidate_sha256: str|None=None,
                timeout: int=60) -> dict:
    """Run both source snapshots against frozen expectations, never release code."""
    from ownstack.release_contracts import RequirementSpec
    if type(timeout) is not int or not 1<=timeout<=90:raise ValueError('Bounded integer check deadline required')
    if os.environ.get('DOCKER_HOST') and not os.environ['DOCKER_HOST'].startswith('unix://'):
        raise ValueError('Remote Docker endpoint is forbidden')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise ValueError('Immutable existing image ID required')
    specs=[r if isinstance(r,RequirementSpec) else RequirementSpec.model_validate(r) for r in requirements]
    requirements_hash=requirements_digest(specs)
    rows=[{'requirement_key':spec.key,'case_id':case.case_id,'input':case.input.model_dump(mode='json')}
          for spec in specs for case in spec.cases]
    if not 1<=len(rows)<=MAX_CASES:raise ValueError('HTTP case count exceeds reviewed profile bound')
    baseline_manifest,baseline_files=_snapshot(base_dir);candidate_manifest,candidate_files=_snapshot(candidate_dir)
    if baseline_manifest['profile']!=candidate_manifest['profile']:raise ValueError('Use the same reviewed repository profile for both versions')
    from ownstack.release_repository import PROFILE as repository_profile
    generalized=baseline_manifest['profile']==repository_profile
    if generalized and any(baseline_manifest['config'][k]!=candidate_manifest['config'][k] for k in ('entrypoint','name')):
        raise ValueError('Baseline and candidate must name the same app/adapter entrypoint')
    if expected_baseline_sha256 and baseline_manifest['sha256']!=expected_baseline_sha256:
        raise ValueError('Baseline snapshot differs from queued source')
    if expected_candidate_sha256 and candidate_manifest['sha256']!=expected_candidate_sha256:
        raise ValueError('Candidate snapshot differs from queued source')
    context=capture(['docker','context','inspect','--format','{{json .Endpoints.docker.Host}}'],b'',timeout=10,limit=4096)
    if context['failure'] or context['exit_code']!=0 or not json.loads(context['stdout_bytes']).startswith('unix://'):
        raise ValueError('Verified local Docker context required')
    output=_private_output(output_dir)
    for label,files in (('baseline',baseline_files),('candidate',candidate_files)):
        snapshot=output/(label+'-source');snapshot.mkdir(mode=0o755)
        for name,raw in files.items():
            path=snapshot/name;path.parent.mkdir(mode=0o755,parents=True,exist_ok=True);path.write_bytes(raw);path.chmod(0o644)
    identity={'runner':RUNNER,'profile':baseline_manifest['profile'],'policy':POLICY,'baseline_sha256':baseline_manifest['sha256'],
              'candidate_sha256':candidate_manifest['sha256'],'requirements_sha256':requirements_hash,
              'oracle_sha256':hashlib.sha256((HTTP_CLIENT+READY_CLIENT).encode()).hexdigest(),
              'execution_policy_sha256':execution_fingerprint(),
              'image_id':image,'provider_calls':0,'released':False}
    if generalized:identity.update(baseline_snapshot=baseline_manifest,candidate_snapshot=candidate_manifest)
    _json(output/'identity.json',identity)
    baseline=_stage(output/'baseline-source',rows,output/'baseline',image,timeout=timeout,
        **({'command_factory':repository_command(baseline_manifest)} if generalized else {}))
    candidate=_stage(output/'candidate-source',rows,output/'candidate',image,timeout=timeout,
        **({'command_factory':repository_command(candidate_manifest)} if generalized else {}))
    try:
        assessment=assess_observations(specs,baseline,candidate)
    except ValueError:
        assessment={'passed':False,'status':'blocked','baseline_valid':False,'candidate_valid':False,
                    'assessments':[],'reason':'Observed response violates the reviewed profile schema'}
    result={**identity,'baseline':baseline,'candidate':candidate,**assessment,
            'limits':['Explicit reviewed Python HTTP adapter source inventory; no dependency installation or universal repository support.',
                      'Synthetic case input is not production authentication, customer validation or universal security proof.']}
    _json(output/'report.json',result)
    return result


_LOADED_EXECUTION=_read_execution_fingerprint()
