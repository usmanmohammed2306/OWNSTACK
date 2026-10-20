"""Authored, zero-inference kernel-denial controls in no-network containers.

Caught-denial probes must BOTH observe the expected errno and pass the PDF oracle.
The unfiltered control measures real capability availability, not model output.
No probe is executed on the host. Sidecar selection uses explicit Compose args.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
from uuid import uuid4
from ownstack.candidate_sandbox import POLICY_ID
from ownstack.patch_agent import fixture_patch,REFERENCE_IMPLEMENTATION
from ownstack.runner import verify_in_docker,current_provenance,candidate_payload
from ownstack.candidate_driver import DRIVER
from ownstack.bounded_process import capture
from ownstack.pdf_oracle import is_external_pass

PRELUDE='import os,ctypes,errno\nlib=ctypes.CDLL(None,use_errno=True)\n'
PROBES={
 'filesystem_read':"try: open('/etc/passwd','rb').read(1)\nexcept PermissionError: pass\nelse: raise AssertionError('read allowed')\n",
 'proc_environment':"try: open('/proc/self/environ','rb').read(1)\nexcept PermissionError: pass\nelse: raise AssertionError('proc read allowed')\n",
 'filesystem_write':"try: open('/tmp/ownstack-security-probe','w').write('probe')\nexcept PermissionError: pass\nelse: raise AssertionError('write allowed')\n",
 'native_file_open':"ctypes.set_errno(0)\nassert lib.open(b'/etc/passwd',0)==-1 and ctypes.get_errno()==errno.EPERM\n",
 'unix_socket':"ctypes.set_errno(0)\nassert lib.socket(1,1,0)==-1 and ctypes.get_errno()==errno.EPERM\n",
 'inet_socket':"ctypes.set_errno(0)\nassert lib.socket(2,1,0)==-1 and ctypes.get_errno()==errno.EPERM\n",
 'process_creation':"try: child=os.fork()\nexcept PermissionError: pass\nelse:\n    if child==0: os._exit(0)\n    os.waitpid(child,0)\n    raise AssertionError('fork allowed')\n",
 'exec':"ctypes.set_errno(0)\nassert lib.execve(b'/never-execute',None,None)==-1 and ctypes.get_errno()==errno.EPERM\n",
 'ptrace':"ctypes.set_errno(0)\nassert lib.ptrace(65535,0,None,None)==-1 and ctypes.get_errno()==errno.EPERM\n",
 'namespace_creation':"ctypes.set_errno(0)\nassert lib.unshare(0x10000000)==-1 and ctypes.get_errno()==errno.EPERM\n",
 'memfd':"ctypes.set_errno(0)\nassert lib.memfd_create(b'probe',0)==-1 and ctypes.get_errno()==errno.EPERM\n",
 'executable_mprotect':"ctypes.set_errno(0)\nassert lib.mprotect(None,4096,7)==-1 and ctypes.get_errno()==errno.EPERM\n",
 'executable_mmap':"lib.mmap.restype=ctypes.c_void_p\nctypes.set_errno(0)\nassert lib.mmap(None,4096,5,0x22,-1,0)==ctypes.c_void_p(-1).value and ctypes.get_errno()==errno.EPERM\n",
 'process_memory_write':"ctypes.set_errno(0)\nassert lib.process_vm_writev(os.getpid(),None,0,None,0,0)==-1 and ctypes.get_errno()==errno.EPERM\n",
 'policy_changes':"ctypes.set_errno(0)\nassert lib.prctl(39,0,0,0,0)==-1 and ctypes.get_errno()==errno.EPERM\n",
}


def disposable(command,payload=b'',timeout=10):
    name='ownstack-security-'+uuid4().hex
    try:
        return capture(['docker','run','--rm','--pull','never','--name',name,'-i',
            '--user','65534:65534','--network','none','--read-only','--cap-drop','ALL',
            '--security-opt','no-new-privileges','--pids-limit','16','--memory','256m','--cpus','1',
            'python:3.12-slim','python','-I','-B','-c',command],payload,timeout=timeout,limit=16384)
    finally:
        subprocess.run(['docker','rm','--force',name],capture_output=True,timeout=10)


def controls():
    baseline=disposable("""import os,socket,json
assert open('/etc/passwd','rb').read(1)
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.close()
child=os.fork()
if child==0: os._exit(0)
os.waitpid(child,0)
print(json.dumps({'filesystem_read':True,'unix_socket':True,'fork':True}))
""")
    available=json.loads(baseline['stdout_bytes']) if baseline['exit_code']==0 else {}
    patch=fixture_patch()
    patch['edits'][0]['new']="print('CANDIDATE_EXECUTED')\n"+REFERENCE_IMPLEMENTATION
    payload,_=candidate_payload(patch)
    injected=DRIVER.replace('payload = json.load(sys.stdin)',
        "platform.machine=lambda:'unsupported'\npayload = json.load(sys.stdin)")
    unsupported=disposable(injected,payload)
    return {'base_container_capabilities':available,
        'baseline_passed':available=={'filesystem_read':True,'unix_socket':True,'fork':True},
        'unsupported_runtime_executed_candidate':b'CANDIDATE_EXECUTED' in unsupported['stdout_bytes'],
        'unsupported_runtime_failed_closed':unsupported['exit_code']!=0 and b'CANDIDATE_EXECUTED' not in unsupported['stdout_bytes']}


def run(backend,compose):
    records=[]
    if backend=='sidecar':
        def verify(patch):
            code='import json,sys;from ownstack.verifier_service import check;print(json.dumps(check(json.load(sys.stdin))))'
            result=capture(['docker','compose',*compose,'exec','-T','verifier','python','-c',code],
                json.dumps(patch).encode(),timeout=25,limit=1048576)
            if result['exit_code']!=0 or result['failure']:raise RuntimeError('Sidecar probe unavailable')
            return json.loads(result['stdout_bytes'])
    else:verify=verify_in_docker
    for name,code in PROBES.items():
        patch=fixture_patch();patch['edits'][0]['new']=PRELUDE+code+REFERENCE_IMPLEMENTATION
        result=verify(patch)
        passed=(is_external_pass(result) and result.get('isolation_profile')==POLICY_ID
                and all(result.get(k)==v for k,v in current_provenance().items()))
        records.append({'probe':name,'denial_asserted_and_pdf_passed':passed,'result':result})
        print(name+': '+str(passed),flush=True)
    control=controls()
    return {'date':datetime.now(timezone.utc).isoformat(),'backend':backend,'policy':POLICY_ID,
        'probes':records,'controls':control,'new_inference_calls':0,
        'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path('src/ownstack/candidate_sandbox.py'),Path('src/ownstack/candidate_driver.py'),
             Path('src/ownstack/runner.py'),Path('src/ownstack/verifier_service.py'),Path(__file__).relative_to(Path.cwd())]},
        'passed':all(r['denial_asserted_and_pdf_passed'] for r in records)
            and control['baseline_passed'] and control['unsupported_runtime_failed_closed'],
        'limits':['Fifteen authored controls, not a security certificate or arbitrary-code escape audit.',
                  'Some denials overlap existing container policy; the baseline calibrates only three capabilities.',
                  'Same shared kernel and reused supervisor remain; no microVM, physical failover or independent review.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',choices=['docker','sidecar'],default='docker')
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--compose-project')
    parser.add_argument('--compose-env-file',action='append',default=[])
    parser.add_argument('--compose-overlay')
    args=parser.parse_args()
    compose=['-f','compose.full.yaml']
    if args.compose_project:compose+=['-p',args.compose_project]
    for path in args.compose_env_file:compose+=['--env-file',path]
    if args.compose_overlay:compose+=['-f',args.compose_overlay]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:
        try:report=run(args.backend,compose)
        except Exception as error:report={'passed':False,'error_type':type(error).__name__,'new_inference_calls':0,'incomplete':True}
        json.dump(report,stream,indent=2);stream.write('\n')
    print(json.dumps({'passed':report['passed'],'output':str(args.output),'new_inference_calls':0}))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
