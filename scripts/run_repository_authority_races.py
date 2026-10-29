"""Ordered PostgreSQL approval/review races with explicit execution doubles.

Creates only a new labelled local PG fixture through the existing guarded harness.
No candidate code/inference is executed. Actual running-container tests are saved
separately. No public service, Git operation or deployment is involved.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

from run_release_concurrency import Campaign,ROOT,private


def review_race(campaign,mutation='replacement',ordering='snapshot'):
    from fastapi.testclient import TestClient
    from sqlalchemy import event,select,update
    from ownstack.api import app
    from ownstack.auth import db_session,issue_token
    from ownstack.config import Settings
    from ownstack.models import EngineeringItem,Evidence,User,TeamMembership
    from ownstack.policy import digest
    from ownstack import repository_cockpit as cockpit,repository_release as gate
    from ownstack.release_executor import HTTP_CLIENT,READY_CLIENT,assess_observations,requirements_digest
    factory=campaign.factory();engine=factory.kw['bind']
    def dependency():
        with factory() as db:yield db
    app.dependency_overrides[db_session]=dependency
    tokens={}
    with factory() as db:
        for name in ('atlas-engineer','atlas-admin'):
            tokens[name]={'Authorization':'Bearer '+issue_token(db.get(User,name),Settings().signing_secret)}
    def call(who,method,path,body=None,status=200):
        with TestClient(app) as client:
            response=client.request(method,path,json=body,headers={**tokens[who],'Idempotency-Key':uuid4().hex})
        campaign.note('http',actor=who,method=method,path=path,status=response.status_code,passed=response.status_code==status,executor_double=True)
        if response.status_code!=status:raise AssertionError('Unexpected HTTP status '+str(response.status_code))
        return response.json()
    engineer='atlas-engineer'
    request=call(engineer,'POST','/v1/requests',{'kind':'feature','project_id':'atlas-project','text':'Synthetic ordered authority race'},201)
    call(engineer,'POST','/v1/requests/'+request['id']+'/manual-handoff')
    ident=next(i['id'] for i in call(engineer,'GET','/v1/engineering') if i['request_id']==request['id'])
    base='/v1/engineering/'+ident
    call(engineer,'POST',base+'/repository',{'case_id':'pallets__flask-4160'})
    call(engineer,'POST',base+'/release-assurance',{'requirement_ids':[campaign.requirement['id']]})
    patch=json.loads((ROOT/'evals/repository_candidates/flask-decimal.json').read_text())
    call(engineer,'POST',base+'/manual-patch',{'patch':patch,'candidate_origin':'model'})
    check=call(engineer,'POST',base+'/verify',status=202)
    with factory() as db:
        item=db.get(EngineeringItem,ident);bound=gate.bound(item);b=cockpit.binding(item)
        rows=[{'requirement_key':s['key'],'case_id':c['case_id'],**c['expected'],'error':None} for s in bound['requirements'] for c in s['cases']]
        phase={'state':'completed','failure':'','cleanup_verified':True,'observations':rows}
        source={'image_id':'sha256:'+'a'*64,'baseline_tree_sha256':'b'*64,'candidate_tree_sha256':'c'*64}
        customer={'profile':gate.PROFILE,'policy_sha256':gate.fingerprint(),'binding_sha256':digest(bound),
            'requirements_sha256':requirements_digest(bound['requirements']),
            'oracle_sha256':hashlib.sha256((gate.SERVER+HTTP_CLIENT+READY_CLIENT).encode()).hexdigest(),
            **source,'baseline':deepcopy(phase),'candidate':deepcopy(phase),'provider_calls':0,'released':False,
            **assess_observations(bound['requirements'],phase,phase)}
        names=['tests/authority_double.py::test_'+str(i) for i in range(b['required_test_count'])]
        report={'passed':True,'baseline_failed':True,'candidate_passed':True,'case_id':b['case_id'],
            'origin':'model','case_sha256':b['problem_sha256'],'candidate_sha256':item.patch_hash,
            'oracle_sha256':b['required_tests_sha256'],'base_commit':b['base_commit'],'profile':b['profile'],
            'execution_policy_sha256':b['execution_policy_sha256'],'required_tests':names,'observed_tests':{n:True for n in names},
            'diff':'explicit executor double, no code execution','diff_hash':digest('explicit executor double, no code execution'),
            'customer_release':customer,**source,'released':False,'executor_double':True}
        row=db.get(Evidence,check['id']);row.result={**row.result,'state':'passed','report':report,'receipt_hash':digest(report)}
        item.status='checks_passed';item.operation_id=None;item.operation_deadline=None;db.commit()
    detail=call(engineer,'GET',base)
    if not detail['current_checks_usable']:raise AssertionError('Control double is not usable before schedule')
    next_spec={**campaign.requirement['spec'],'version':2,'title':'Approved replacement during review'}
    drafted=call(engineer,'POST','/v1/release/requirements',{'project_id':'atlas-project','spec':next_spec},201) if mutation=='replacement' else None
    paused=threading.Event();resume=threading.Event();approved=threading.Event();outcomes={};order=[]
    def intercept(connection,cursor,statement,params,context,many):
        # FastAPI runs synchronous routes in an AnyIO thread, not the caller's
        # named thread. At this point review is the sole active request until
        # this rendezvous releases the competing approval.
        selected=('FROM release_requirements' in statement and 'release_requirements.state =' in statement) if ordering=='snapshot' else (
            statement.lstrip().startswith('UPDATE engineering_items') and 'human_decision=' in statement)
        if selected and not paused.is_set():
            paused.set()
            if not resume.wait(8):raise TimeoutError('Review snapshot gate timed out')
    def review():
        try:
            with TestClient(app) as client:
                response=client.post(base+'/decide',headers=tokens[engineer],json={'decision':'accept_for_manual_release',
                    'patch_hash':detail['patch_hash'],'verification_id':check['id'],'context_hash':detail['repository']['context_hash']})
                outcomes['review_status']=response.status_code;order.append('review_response')
        except Exception as error:outcomes['review_error']=type(error).__name__
    def approve():
        try:
            if mutation=='replacement':
                with TestClient(app) as client:
                    response=client.post('/v1/release/requirements/'+drafted['id']+'/approve',headers=tokens['atlas-admin'],json={'expected_hash':drafted['requirement_hash']})
                    outcomes['approval_status']=response.status_code
            else:
                with factory() as db:
                    if mutation=='membership':
                        db.execute(update(TeamMembership).where(TeamMembership.user_id=='atlas-admin').values(enabled=False,revision=TeamMembership.revision+1))
                    else:db.execute(update(User).where(User.id=='atlas-admin').values(role='engineer',token_version=User.token_version+1))
                    db.commit();outcomes['approval_status']=200
            order.append('approval_response');approved.set()
        except Exception as error:outcomes['approval_error']=type(error).__name__;approved.set()
    event_name='after_cursor_execute' if ordering=='snapshot' else 'before_cursor_execute'
    event.listen(engine,event_name,intercept)
    a=threading.Thread(target=review,name='authority-review');bthread=threading.Thread(target=approve,name='authority-approval')
    try:
        a.start()
        if not paused.wait(5):raise TimeoutError('Review did not reach requirement snapshot')
        bthread.start()
        # Legacy readers allow the replacement to commit before review resumes.
        # Correct readers hold a project lock and the approval must wait instead.
        replacement_committed=approved.wait(1.5)
        blocked=campaign.sql("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' AND datname='"+engine.url.database+"'")[0][0]>0
        resume.set();a.join(12);bthread.join(12)
        if a.is_alive() or bthread.is_alive():raise TimeoutError('Race threads did not stop')
    finally:
        resume.set();a.join(12)
        if bthread.ident is not None:bthread.join(12)
        event.remove(engine,event_name,intercept)
        app.dependency_overrides.clear()
    stale_accept=bool(replacement_committed and outcomes.get('review_status')==200)
    passed=not stale_accept and outcomes.get('approval_status')==200 and outcomes.get('review_status') in {200,409}
    if not replacement_committed:passed=passed and blocked
    app.dependency_overrides[db_session]=dependency
    try:
        current=call(engineer,'GET',base)
        call(engineer,'GET',base+'/artifact',status=409)
        passed=passed and not current['current_checks_usable']
    finally:app.dependency_overrides.clear()
    campaign.note(mutation+'_'+ordering+'_vs_repository_review',passed=passed,
        replacement_committed_while_review_paused=replacement_committed,approval_lock_wait_observed=blocked,
        stale_review_accepted=stale_accept,outcomes=outcomes,response_order=order,executor_double=True)
    return passed


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--requirement-json',type=Path,required=True)
    parser.add_argument('--all-orderings',action='store_true')
    args=parser.parse_args()
    campaign=Campaign(args.output);result={'passed':False,'provider_calls':0,'executor_double':True}
    try:
        os.environ['OWNSTACK_REPOSITORY_COCKPIT']='true'
        campaign.boot(json.loads(args.requirement_json.read_text()))
        schedules=[('replacement','snapshot')]
        if args.all_orderings:schedules.extend((kind,order) for kind in ('membership','role') for order in ('snapshot','finish'))
        outcomes=[review_race(campaign,kind,order) for kind,order in schedules]
        result.update(passed=all(outcomes),schedules=len(outcomes))
    finally:
        campaign.cleanup();private(campaign.output/'report.json',{**result,'records':len(campaign.records)})
    print(json.dumps(result))
    return 0 if result['passed'] else 2


if __name__=='__main__':raise SystemExit(main())
