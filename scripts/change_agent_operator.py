"""Run a reviewed discovery's actual local counterexample/repair journey.

Explicit AI off. Supplied repair JSON is labeled supplied, never live model proof.
Uses the existing independent Docker executor and SQL claim/completion fences.
"""
import argparse,json,os
from pathlib import Path
from uuid import uuid4

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('name','discovery','image'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--baseline',type=Path,required=True);parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--editable',action='append',required=True)
    parser.add_argument('--repair-responses',type=Path);parser.add_argument('--user',default='atlas-engineer')
    args=parser.parse_args()
    from customer_release import offline,lab_path
    offline();lab=lab_path(args.name);state=json.loads((lab/'operator.json').read_text())
    from release_assurance_operator import database
    url=database(state['OWNSTACK_DATABASE_URL'])
    from urllib.parse import urlsplit
    endpoint=urlsplit(state['OWNSTACK_PUBLIC_ORIGIN'])
    if endpoint.hostname!='127.0.0.1' or not 8140<=endpoint.port<=8999:raise ValueError('Named loopback fixture required')
    os.environ.update(state);offline()
    from ownstack.db import make_engine
    from sqlalchemy.orm import sessionmaker
    from ownstack.models import User,ReleaseCheck
    from ownstack.auth import issue_token
    from ownstack.release_executor import snapshot_repository,run_release
    from ownstack.release_assurance import claim_next,finish_check,context_valid,audit
    from ownstack.change_agent import load,validate_context
    from ownstack.policy import Principal
    from ownstack.counterexample_loop import run_loop
    from ownstack.model_contracts import strict_json
    import httpx
    engine=make_engine(url);factory=sessionmaker(bind=engine,expire_on_commit=False)
    with factory() as db:
        user=db.get(User,args.user)
        if not user or not user.enabled or user.role!='engineer':raise ValueError('Enabled scoped engineer required')
        principal=Principal(user.id,user.tenant_id,user.role);token=issue_token(user,state['OWNSTACK_SIGNING_SECRET'])
    repairs=[]
    if args.repair_responses:
        raw=args.repair_responses.read_text()
        repairs=strict_json(raw,limit=128000)
        if not isinstance(repairs,list) or len(repairs)>2:raise ValueError('At most two supplied repair proposals')
    with httpx.Client(base_url=state['OWNSTACK_PUBLIC_ORIGIN'],headers={'Authorization':'Bearer '+token},trust_env=False,timeout=15) as client:
        discovery=client.get('/v1/change-agents/'+args.discovery);discovery.raise_for_status();discovery=discovery.json()
        if discovery['status']!='approved':raise ValueError('Exact human policy approval required')
        baseline=snapshot_repository(args.baseline)
        if baseline['sha256']!=discovery['source_sha256']:raise ValueError('Baseline differs from discovery source')
        receipt=client.get('/v1/release/requirements-receipt',params={'project_id':discovery['project_id']});receipt.raise_for_status();receipt=receipt.json()
        if not set(discovery['requirement_ids'])<=set(receipt['requirement_ids']):raise ValueError('Discovery requirements are no longer current')
        def verify(candidate,output):
            snapshot=snapshot_repository(candidate)
            response=client.post('/v1/release/checks',json={'project_id':discovery['project_id'],
                'baseline_sha256':baseline['sha256'],'candidate_sha256':snapshot['sha256'],
                'requirement_ids':receipt['requirement_ids'],'idempotency_key':uuid4().hex})
            response.raise_for_status();ident=response.json()['id']
            item=claim_next(factory,only_id=ident)
            if not item:raise ValueError('Exact queued check could not be claimed')
            result=run_release(args.baseline,candidate,item['requirements'],output,image=args.image,
                expected_baseline_sha256=baseline['sha256'],expected_candidate_sha256=snapshot['sha256'])
            if not finish_check(factory,ident,item['claim_token'],result):raise ValueError('Result was stale or superseded')
            response=client.get('/v1/release/checks/'+ident);response.raise_for_status();return response.json()
        def propose(context):
            if repairs:return repairs.pop(0),{'live':False,'origin':'explicitly supplied repair JSON; no model inference','oracle_hash':context['oracle_hash']}
            current=client.get('/v1/change-agents/'+args.discovery);current.raise_for_status()
            response=client.post('/v1/change-agents/'+args.discovery+'/patch-proposal',json={'expected_revision':current.json()['revision'],
                'check_id':context['check_id'],'files':context['editable_files'],'idempotency_key':uuid4().hex},timeout=135)
            response.raise_for_status();value=response.json()
            if value['status']!='proposed':raise ValueError('Model repair failed; evidence remains available for human takeover')
            return value['patch'],value['usage']
        output=lab/'agent-runs'/uuid4().hex
        result=run_loop(candidate=args.candidate,requirements=receipt['requirements'],editable=args.editable,
            output=output,verify=verify,propose=propose)
        # Link the completed observed run to the request, without accepting it.
        with factory() as db:
            saved,request,project=load(db,principal,args.discovery,True);validate_context(db,saved,request,project)
            check=db.get(ReleaseCheck,result['check_id']);context_valid(db,check)
            from ownstack.release_repository import load as load_source
            import difflib
            final_snapshot,files=load_source(Path(result['final_candidate']));initial_snapshot,base_files=load_source(args.candidate)
            if final_snapshot['sha256']!=check.candidate_sha256:raise ValueError('Final diff differs from checked candidate')
            first=json.loads((output/'attempt-1-summary.json').read_text())
            if first['candidate_sha256']!=initial_snapshot['sha256']:raise ValueError('Repair base changed after its failed check')
            diff=''.join(''.join(difflib.unified_diff(base_files[name].decode().splitlines(True),files[name].decode().splitlines(True),fromfile='before-repair/'+name,tofile='checked-candidate/'+name)) for name in sorted(files))
            if len(diff.encode())>64000:raise ValueError('Review diff exceeds supported limit')
            linked={k:v for k,v in result.items() if k!='final_candidate'};linked['source_diff']=diff or 'No repair changes were needed.';linked['repair_base_sha256']=initial_snapshot['sha256']
            audit(db,project,args.discovery,'agent.counterexample_completed',result=linked)
            db.commit()
        proposals=[json.loads(p.read_text()) for p in output.glob('proposal-*.json')]
        live_proposals=sum(p.get('provenance',{}).get('live') is True for p in proposals)
        print(json.dumps({'state':result['state'],'check_id':result['check_id'],'attempts':result['attempts'],
            'output':str(output),'live_proposals':live_proposals,
            'provider_calls':None if live_proposals else 0,'accepted':False,'released':False}))
    engine.dispose()

if __name__=='__main__':main()
