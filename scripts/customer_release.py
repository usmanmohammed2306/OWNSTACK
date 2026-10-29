"""Local repository onboarding and provider-free CI entry point.

The trusted tooling checkout must be separate from candidate source in CI.
No Git writes, remote fetches, dependency installs, inference or deployment.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys


def private_json(path,value):
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as file:json.dump(value,file,indent=2);file.write('\n')


def receipt(raw,expected_sha):
    from ownstack.model_contracts import strict_json
    from ownstack.policy import digest,aware
    from ownstack.release_contracts import RequirementSpec
    from ownstack.release_assurance import bundle_hash
    if not re.fullmatch('[a-f0-9]{64}',expected_sha) or hashlib.sha256(raw).hexdigest()!=expected_sha:
        raise ValueError('Receipt differs from its independently protected file digest')
    value=strict_json(raw.decode(),limit=512000)
    keys={'schema_version','project_id','requirement_ids','requirements','requirements_sha256',
          'exported_at','expires_at','authority','receipt_sha256'}
    if not isinstance(value,dict) or set(value)!=keys or type(value['schema_version']) is not int or value['schema_version']!=1:
        raise ValueError('Invalid approved receipt envelope')
    if value['receipt_sha256']!=digest({k:v for k,v in value.items() if k!='receipt_sha256'}):raise ValueError('Receipt content changed')
    issued=aware(datetime.fromisoformat(value['exported_at']));expires=aware(datetime.fromisoformat(value['expires_at']))
    now=datetime.now(timezone.utc)
    if not issued<=now<expires or not 0<(expires-issued).total_seconds()<=600:raise ValueError('Receipt is stale or future-dated; export current approvals again')
    specs=[RequirementSpec.model_validate(s) for s in value['requirements']]
    if not 1<=len(specs)<=30 or len(value['requirement_ids'])!=len(specs) or len(set(value['requirement_ids']))!=len(specs):
        raise ValueError('Incomplete or duplicate approval identities')
    if value['requirements_sha256']!=bundle_hash([s.model_dump(mode='json') for s in specs]):raise ValueError('Receipt requirement snapshot changed')
    return value,specs


def offline():
    if (os.environ.get('OWNSTACK_AI_MODE')!='off' or os.environ.get('OWNSTACK_MAX_LIVE_CALLS')!='0'
        or any(os.environ.get(k) for k in ('NEBIUS_API_KEY','NEBIUS_MODEL_ID','NEBIUS_PATCH_MODEL_ID'))):
        raise ValueError('Explicit AI off, cap zero and empty provider credentials required')


def lab_path(name):
    if not re.fullmatch('[a-z0-9][a-z0-9-]{0,48}',name):raise ValueError('Short lowercase lab name required')
    root=Path(__file__).resolve().parents[1]
    path=root/'.private/release-labs'/name
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('No symlink lab path')
    return path


def initialize_lab(name,port):
    import secrets,subprocess
    path=lab_path(name)
    if not 8140<=port<=8999:raise ValueError('Choose a new local test port between8140 and8999')
    path.mkdir(mode=0o700,parents=True,exist_ok=False)
    state={'OWNSTACK_DATABASE_URL':'sqlite:///'+str(path/'ownstack.sqlite'),'OWNSTACK_ENV':'local',
        'OWNSTACK_PUBLIC_ORIGIN':'http://127.0.0.1:'+str(port),'OWNSTACK_SIGNING_SECRET':secrets.token_urlsafe(48),
        'OWNSTACK_COOKIE_NAMESPACE':name[:20]+'-release','OWNSTACK_RELEASE_ASSURANCE':'true','OWNSTACK_REQUIRE_BACKGROUND':'false',
        'OWNSTACK_PUBLIC_SIGNUP':'false','OWNSTACK_TRAINED_PLANNER_URL':'','OWNSTACK_PLANNER_SERVICE_TOKEN':'','OWNSTACK_REPOSITORY_COCKPIT':'false'}
    os.environ.update(state,OWNSTACK_DEMO_PASSWORD=secrets.token_urlsafe(32))
    private_json(path/'lab.json',{'schema_version':1,'purpose':'ownstack-offline-release-lab','database':'ownstack.sqlite'})
    private_json(path/'operator.json',state)
    fd=os.open(path/'api-secret.txt',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as file:file.write(state['OWNSTACK_SIGNING_SECRET'])
    run=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=Path(__file__).resolve().parents[1],capture_output=True)
    (path/'migration.log').write_bytes(run.stdout+run.stderr)
    if run.returncode:raise RuntimeError('Offline lab migration failed; preserve the log')
    from ownstack.seed import seed
    seed()
    from ownstack.db import SessionLocal
    from ownstack.models import User
    from ownstack.auth import password_hash
    passwords={}
    with SessionLocal() as db:
        for person in db.query(User).all():
            value=secrets.token_urlsafe(32);person.password_hash=password_hash(value);passwords[person.id]=value
        db.commit()
    private_json(path/'accounts.json',{'version':1,'passwords':passwords})
    return path,state


def mount_lab_web(app, directory):
    """Only the declared customer route gets the SPA shell; API404 stays404."""
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    if not (directory/'index.html').is_file():
        return
    @app.get('/customer',include_in_schema=False)
    def customer_portal_page():
        return FileResponse(directory/'index.html')
    app.mount('/',StaticFiles(directory=directory,html=True),name='customer-release-lab-web')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    lab=sub.add_parser('init-lab');lab.add_argument('--name',required=True);lab.add_argument('--port',type=int,default=8140)
    serve=sub.add_parser('serve');serve.add_argument('--name',required=True)
    measure=sub.add_parser('measure');measure.add_argument('--trials',type=Path,required=True);measure.add_argument('--output',type=Path,required=True)
    init=sub.add_parser('init');init.add_argument('--source',type=Path,required=True);init.add_argument('--name',required=True)
    init.add_argument('--entrypoint',required=True);init.add_argument('--include',action='append',required=True)
    snap=sub.add_parser('snapshot');snap.add_argument('--source',type=Path,required=True);snap.add_argument('--output',type=Path,required=True)
    register=sub.add_parser('register');register.add_argument('--source',type=Path,required=True);register.add_argument('--label',required=True)
    export=sub.add_parser('export');export.add_argument('--output',type=Path,required=True)
    register.add_argument('--customer-id',help='Explicit existing customer account to connect')
    register.add_argument('--repository-key',help='Stable key for the new named repository version')
    for arg in (register,export):
        arg.add_argument('--server',required=True);arg.add_argument('--project',required=True)
        arg.add_argument('--accounts',type=Path,required=True);arg.add_argument('--user',required=True)
        arg.add_argument('--server-secret-file',type=Path,required=True,help='Private file containing only this local API signing secret')
    check=sub.add_parser('check')
    for name in ('baseline','candidate','receipt','output'):check.add_argument('--'+name,type=Path,required=True)
    check.add_argument('--receipt-sha256',required=True);check.add_argument('--image',required=True)
    args=parser.parse_args();offline()
    if args.command=='measure':
        from ownstack.pilot_evidence import summarize
        raw=args.trials.read_bytes()
        if len(raw)>1024*1024:raise ValueError('Bounded measurement file required')
        rows=[json.loads(line) for line in raw.decode().splitlines() if line.strip()]
        if len(rows)>1000:raise ValueError('At most1000 matched task records')
        result=summarize(rows);private_json(args.output,result);print(json.dumps(result));return 0
    if args.command=='init-lab':
        path,state=initialize_lab(args.name,args.port)
        print(json.dumps({'initialized':True,'lab':str(path),'url':state['OWNSTACK_PUBLIC_ORIGIN'],
                          'accounts':'Private accounts.json; no credentials printed','provider_calls':0}));return 0
    if args.command=='serve':
        path=lab_path(args.name)
        state=json.loads((path/'operator.json').read_text())
        expected='sqlite:///'+str(path/'ownstack.sqlite')
        if state.get('OWNSTACK_DATABASE_URL')!=expected or state.get('OWNSTACK_ENV')!='local':raise ValueError('Isolated lab state required')
        from urllib.parse import urlsplit
        endpoint=urlsplit(state['OWNSTACK_PUBLIC_ORIGIN'])
        if endpoint.hostname!='127.0.0.1' or not 8140<=endpoint.port<=8999:raise ValueError('Loopback test origin required')
        os.environ.update(state)
        offline()
        from ownstack.api import app
        mount_lab_web(app,path/'web')
        import uvicorn
        uvicorn.run(app,host='127.0.0.1',port=endpoint.port);return 0
    from ownstack.release_repository import initialize
    from ownstack.release_executor import snapshot_repository
    if args.command=='init':
        result=initialize(args.source,name=args.name,entrypoint=args.entrypoint,include=args.include)
        print(json.dumps({'initialized':True,'source_sha256':result['sha256'],'files':len(result['files']),'provider_calls':0}));return 0
    if args.command=='snapshot':
        result=snapshot_repository(args.source);private_json(args.output,result)
        print(json.dumps({'source_sha256':result['sha256'],'files':len(result['files']),'provider_calls':0}));return 0
    if args.command in {'register','export'}:
        import hmac,secrets,httpx
        from urllib.parse import urlsplit
        from ownstack.deployment import read_account_file
        server=urlsplit(args.server)
        if (server.scheme!='http' or server.hostname not in {'127.0.0.1','::1'} or not server.port or server.port<1024
            or server.port in {8101,8109,8122,8130,8131,8132} or server.path not in {'','/'} or server.query or server.fragment or server.username is not None or server.password is not None):
            raise ValueError('Use a new explicitly named isolated loopback API')
        # Verify the destination before sending fixture credentials. The API
        # proves possession of its existing local signing secret for this nonce.
        secret=args.server_secret_file.read_text().strip();nonce=secrets.token_hex(32)
        with httpx.Client(base_url=args.server,trust_env=False,timeout=20,headers={'Origin':args.server.rstrip('/')}) as client:
            proof=client.get('/v1/release/local-proof',params={'nonce':nonce});proof.raise_for_status()
            expected=hmac.new(secret.encode(),(args.server.rstrip('/')+'|'+nonce).encode(),hashlib.sha256).hexdigest()
            if not hmac.compare_digest(proof.json().get('proof',''),expected):raise ValueError('Local destination identity mismatch')
            passwords=read_account_file(args.accounts)
            login=client.post('/v1/session',json={'username':args.user,'password':passwords[args.user]});login.raise_for_status()
            client.headers.update({'Authorization':'Bearer '+login.json()['token']})
            if args.command=='register':
                source=snapshot_repository(args.source)
                result=client.post('/v1/release/sources',json={'project_id':args.project,'label':args.label,'snapshot':source});result.raise_for_status()
                connection=None
                if args.customer_id or args.repository_key:
                    if not args.customer_id or not args.repository_key:raise ValueError('Customer ID and repository key must be supplied together')
                    result=client.post('/v1/repositories',json={'project_id':args.project,'label':args.label,
                        'key':args.repository_key,'kind':'python','source_sha256':source['sha256']});result.raise_for_status();connection=result.json()
                    result=client.post('/v1/repositories/'+connection['id']+'/customers',json={'expected_revision':connection['revision'],
                        'customer_id':args.customer_id,'enabled':True});result.raise_for_status();connection=result.json()
                print(json.dumps({'registered':True,'source_sha256':source['sha256'],'repository_id':connection['id'] if connection else None,'provider_calls':0}));return 0
            result=client.get('/v1/release/requirements-receipt',params={'project_id':args.project});result.raise_for_status()
            private_json(args.output,result.json())
        print(json.dumps({'exported':True,'file_sha256':hashlib.sha256(args.output.read_bytes()).hexdigest(),
                          'expires_at':result.json()['expires_at'],'authority':'At export only; revalidate before release','provider_calls':0}));return 0
    receipt_bytes=args.receipt.read_bytes()
    approved,specs=receipt(receipt_bytes,args.receipt_sha256)
    from ownstack.release_executor import run_release
    from ownstack.release_assurance import assess_report,review_markdown
    from ownstack.policy import digest
    from types import SimpleNamespace
    report=run_release(args.baseline,args.candidate,specs,args.output,image=args.image)
    receipt(receipt_bytes,args.receipt_sha256)  # Runtime cannot extend an approval receipt's expiry.
    item=SimpleNamespace(baseline_sha256=report['baseline_sha256'],candidate_sha256=report['candidate_sha256'],
        requirements_sha256=report['requirements_sha256'],requirements=[s.model_dump(mode='json') for s in specs],
        report=report,evidence_hash=digest(report),decision=None)
    item.state=assess_report(item,report)
    private_json(args.output/'ci-receipt.json',{'receipt_file_sha256':args.receipt_sha256,'project_id':approved['project_id'],
        'requirement_ids':approved['requirement_ids'],'state':item.state,'evidence_hash':item.evidence_hash,
        'authority':'Offline comparison only; live approval may since have changed','released':False,'provider_calls':0})
    with (args.output/'review.md').open('x') as file:file.write(review_markdown(item))
    print(json.dumps({'state':item.state,'evidence_hash':item.evidence_hash,'released':False,'provider_calls':0}))
    return 0 if item.state=='passed' else 1 if item.state=='regression' else 2


if __name__=='__main__':
    try:code=main()
    except Exception as error:
        print(json.dumps({'state':'blocked','error_type':type(error).__name__,'provider_calls':0}));code=2
    raise SystemExit(code)
