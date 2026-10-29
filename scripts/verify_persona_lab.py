"""Exercise saved synthetic accounts through HTTP routes without model calls.

In-process TestClient uses 100 documented virtual device IPs. This is not a test
of 100 physical devices or a bypass of the real server's shared-IP limiter.
Authentication/isolation checks do not count as persona business fulfillment.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import time
from ownstack.persona_lab import ROOT,configure

def verify(directory,output):
    if output.exists():raise FileExistsError('Preserve the previous verification')
    configure(directory)
    accounts=json.loads((directory/'accounts.json').read_text())
    from fastapi.testclient import TestClient
    from sqlalchemy import func,select
    from ownstack.api import app
    from ownstack.db import SessionLocal
    from ownstack.models import InferenceBudget,Tenant,User,WebSession
    from ownstack.experiment_store import ExperimentStore,Result
    journal=ExperimentStore(output.parent/('journal-'+output.stem))
    rows=[];started=time.monotonic()
    for i,(pid,a) in enumerate(accounts.items()):
        checks=[]
        def require(name,condition):
            checks.append({'name':name,'passed':bool(condition)})
            if not condition:raise AssertionError(name)
        row={'persona_id':pid,'role':a['role'],'checks':checks}
        try:
            with TestClient(app,client=(f'192.0.2.{i+1}',50000)) as client:
                response=client.post('/v1/session',json={'username':a['username'],'password':a['password']})
                require('actual_password_sign_in',response.status_code==200)
                session=response.json();headers={'Origin':'http://127.0.0.1:8107','X-CSRF-Token':session['csrf_token']}
                require('current_session_identity',client.get('/v1/session').json()['user_id']==a['username'])
                own=client.get('/v1/host/projects/'+a['project_id']+'/documents')
                require('own_read_matches_role',own.status_code==(403 if a['role']=='contractor' else 200))
                other=accounts[list(accounts)[(i+1)%100]]
                require('foreign_tenant_direct_read_denied',client.get('/v1/host/projects/'+other['project_id']+'/documents').status_code==404)
                require('foreign_request_identity_unavailable',client.get('/v1/requests/not-a-request').status_code in (403,404))
                require('logout_requires_csrf',client.post('/v1/session/logout').status_code==403)
                require('logout_revokes_session',client.post('/v1/session/logout',headers=headers).status_code==200)
                require('replay_after_logout_denied',client.get('/v1/session').status_code==401)
                require('incorrect_password_denied',client.post('/v1/session',json={'username':a['username'],'password':'incorrect-test-only'}).status_code==401)
            row['passed']=True
        except Exception as exc:row.update(passed=False,error=type(exc).__name__+': '+str(exc))
        rows.append(row)
        # Commit each completed account before a later case or summary can fail.
        journal.append(Result(case_id=pid,persona_id=pid,scope='authentication',
            status='passed' if row['passed'] else 'failed',source_group='ownstack-persona-auth',
            source_split='test',checks=checks,reason=row.get('error','Saved-account authentication and isolation checks only.')),
            event_id='auth-'+pid)
    with SessionLocal() as db:
        assert db.get(InferenceBudget,'global').reserved_calls==0
        assert db.scalar(select(func.count()).select_from(User))==100
        assert db.scalar(select(func.count()).select_from(Tenant).where(Tenant.ai_enabled.is_(True)))==0
        # Logout deletes the session record in this implementation; there is no
        # fictional revoked flag to query. Every session created here logs out.
        active=db.scalar(select(func.count()).select_from(WebSession))
    report={'passed':all(r['passed'] for r in rows),'accounts':len(rows),'role_counts':dict(Counter(r['role'] for r in rows)),
        'passed_accounts':sum(r['passed'] for r in rows),'failed_accounts':sum(not r['passed'] for r in rows),
        'checks':sum(len(r['checks']) for r in rows),'rows':rows,'elapsed_s':round(time.monotonic()-started,3),
        'provider_reservations':0,'active_sessions_after':active,'full_business_journeys_verified':0,
        'scope':'In-process HTTP, saved synthetic accounts, distinct virtual IPs, no model or public registration call. No real-device load or persona-need fulfillment claim.'}
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as file:json.dump(report,file,indent=2)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();directory=a.directory.absolute()
    if not directory.resolve().is_relative_to((ROOT/'.private').resolve()):raise SystemExit('Use the isolated private laboratory')
    result=verify(directory,a.output)
    print(json.dumps({k:result[k] for k in ['passed','accounts','passed_accounts','failed_accounts','checks','provider_reservations','full_business_journeys_verified']}))
    raise SystemExit(0 if result['passed'] else 1)
