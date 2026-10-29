"""Real PostgreSQL/API concurrency with an EXPLICIT executor test double.

No source-code resolution or inference proof. The independent real-container
restart campaign is separate. Requires an empty loopback-only disposable DB.
"""
import argparse,json,os,secrets,subprocess,sys,threading,time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from sqlalchemy import create_engine,inspect,select,func,text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--recovery',action='store_true',help='Include explicit fake crash/reaper schedules')
    parser.add_argument('--restart-storm',action='store_true',help='Include restart/cancellation ownership races (requires --recovery)')
    args=parser.parse_args()
    if args.restart_storm and not args.recovery:parser.error('--restart-storm requires --recovery')
    root=Path(__file__).resolve().parents[1];out=args.output.resolve()
    if not out.is_relative_to(root/'.private'):raise ValueError('Use a new private operator directory')
    out.mkdir(mode=0o700,exist_ok=False)
    raw=os.environ.get('OWNSTACK_REPOSITORY_TEST_DB','');url=make_url(raw)
    if not(url.drivername.startswith('postgresql') and url.host in {'127.0.0.1','localhost'} and url.database=='ownstack_repository_race_test'):
        raise ValueError('Use an empty loopback ownstack_repository_race_test database')
    os.environ.update(OWNSTACK_DATABASE_URL=raw,OWNSTACK_ENV='local',OWNSTACK_AI_MODE='off',OWNSTACK_MAX_LIVE_CALLS='0',
        NEBIUS_API_KEY='',NEBIUS_MODEL_ID='',NEBIUS_PATCH_MODEL_ID='',OWNSTACK_TRAINED_PLANNER_URL='',OWNSTACK_PLANNER_SERVICE_TOKEN='',
        OWNSTACK_REPOSITORY_COCKPIT='true',OWNSTACK_REQUIRE_BACKGROUND='false',OWNSTACK_PUBLIC_ORIGIN='http://testserver',
        OWNSTACK_ENFORCE_AUTH_CLOCK='false',OWNSTACK_SIGNING_SECRET=secrets.token_urlsafe(48))
    engine=create_engine(raw,pool_size=20,max_overflow=10,connect_args={'application_name':'ownstack_repository_races','options':'-c statement_timeout=15000 -c lock_timeout=12000'})
    if inspect(engine).get_table_names():raise ValueError('Refusing a nonempty database')
    migrated=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=root,capture_output=True,text=True)
    (out/'migration.log').write_text(migrated.stdout+migrated.stderr);assert migrated.returncode==0
    from fastapi.testclient import TestClient
    from ownstack.api import app
    from ownstack.auth import db_session,issue_token,password_hash
    from ownstack.config import Settings
    from ownstack.models import Tenant,User,TeamMembership,Project,Contract,EngineeringItem,Evidence,InferenceBudget,ChangeRequest,Event
    from ownstack.team_scope import ensure_general_team,add_general_member
    from ownstack.policy import CONTRACT,digest
    from ownstack.repository_cockpit import catalog
    from ownstack.repository_executor import canonical,digest as byte_digest,execution_fingerprint
    import ownstack.repository_worker as worker
    factory=sessionmaker(bind=engine,expire_on_commit=False)
    with factory() as db:
        db.add(Tenant(id='org',name='Synthetic overlapping requests',ai_enabled=False));db.flush();team=ensure_general_team(db,'org')
        hashed=password_hash('private-synthetic-test-password');tokens={}
        for user,role in [('admin','admin'),('one','engineer'),('two','engineer'),('old-manager','manager'),('new-manager','manager')]:
            person=User(id=user,tenant_id='org',role=role,password_hash=hashed);db.add(person);db.flush();add_general_member(db,person)
            tokens[user]={'Authorization':'Bearer '+issue_token(person,Settings().signing_secret)}
        db.add(Project(id='project',tenant_id='org',name='Payments',team_id=team,revision=1))
        db.add(Contract(id=CONTRACT['id'],version=CONTRACT['version'],manifest=CONTRACT,manifest_hash=digest(CONTRACT)));db.commit()
    def override():
        with factory() as db:yield db
    app.dependency_overrides[db_session]=override
    traces=[];episodes=[];guard=threading.Lock();counts={'executor_calls':0};execute_hook=None
    def call(actor,method,path,body=None,key=None):
        with TestClient(app) as client:
            r=client.request(method,path,json=body,headers={**tokens[actor],'Idempotency-Key':key or uuid4().hex})
            entry={'actor':actor,'method':method,'path':path,'status':r.status_code,'result':r.json()}
            with guard:
                traces.append(entry)
                with (out/'http.jsonl').open('a') as f:f.write(json.dumps(entry,default=str)+'\n')
            return r.status_code,r.json()
    @contextmanager
    def episode(name):
        row={'id':name,'passed':False};episodes.append(row)
        try:yield;row['passed']=True
        except Exception as e:row['error']={'type':type(e).__name__,'detail':str(e)[:1400]}
        finally:(out/'episodes.json').write_text(json.dumps(episodes,indent=2))
    def batch(function,n=12):
        start=threading.Barrier(n)
        def aligned():start.wait(timeout=8);return function()
        with ThreadPoolExecutor(max_workers=n) as pool:return list(pool.map(lambda _:aligned(),range(n)))
    def new_item():
        status,request=call('one','POST','/v1/requests',{'text':'Repair exact settlement serialization '+uuid4().hex,'kind':'feature','project_id':'project'});assert status==201
        assert call('one','POST','/v1/requests/'+request['id']+'/manual-handoff')[0]==200
        status,rows=call('one','GET','/v1/engineering');assert status==200
        item=next(row for row in rows if row['request_id']==request['id']);path='/v1/engineering/'+item['id']
        assert call('one','POST',path+'/repository',{'case_id':'pallets__flask-4160'})[0]==200
        candidate=call('one','GET','/v1/repository-cases/pallets__flask-4160/example')[1]['patch']
        assert call('one','POST',path+'/manual-patch',{'patch':candidate,'candidate_origin':'model'})[0]==200
        return path,request['id']
    def load(*args):
        public=catalog()[args[-1]]
        return SimpleNamespace(id=public['id'],base_commit=public['base_commit'],problem_sha256=public['problem_sha256'],oracle_sha256=public['required_tests_sha256'],public=public)
    def execute(case,candidate,output,cache,origin):
        with guard:counts['executor_calls']+=1
        if execute_hook:execute_hook()
        names=[f'tests/explicit_control.py::test_{n}' for n in range(case.public['fail_to_pass_count']+case.public['pass_to_pass_count'])]
        for name in {e['path'] for e in candidate['edits']}:
            for stage,field in [('baseline-source','old'),('candidate-source','new')]:
                p=output/stage/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(''.join(e[field] for e in candidate['edits'] if e['path']==name))
        return {'passed':True,'baseline_failed':True,'candidate_passed':True,'case_id':case.id,'origin':origin,
            'case_sha256':case.problem_sha256,'candidate_sha256':byte_digest(canonical(candidate)),
            'oracle_sha256':case.oracle_sha256,'base_commit':case.base_commit,'profile':case.public['profile'],
            'execution_policy_sha256':execution_fingerprint(case.public['profile']),
            'required_tests':names,'observed_tests':{n:True for n in names},'released':False,'explicit_executor_test_double':True}
    def once():return worker.work_once(factory,out/'control-jobs',out/'evaluator-placeholder.jsonl',out/'cache')
    def membership(user,enabled,revision,role='member'):
        return call('admin','PUT',f'/v1/teams/{team}/members/{user}',{'role':role,'enabled':enabled,'expected_revision':revision})
    try:
        with patch.object(worker.RepositoryCase,'load',load),patch.object(worker,'execute',execute):
            with episode('twelve-identical-request-deliveries'):
                key=uuid4().hex;body={'text':'One customer request delivered twelve times','kind':'feature','project_id':'project'}
                responses=batch(lambda:call('one','POST','/v1/requests',body,key))
                assert {status for status,_ in responses}=={201}
                assert len({r['id'] for _,r in responses})==1
                assert call('two','POST','/v1/requests',body,key)[0]==409
            with episode('twelve-concurrent-verifications-share-saved-work'):
                path,_=new_item();responses=batch(lambda:call('one','POST',path+'/verify'))
                episodes[-1]['statuses']=[s for s,_ in responses]
                assert {s for s,_ in responses}=={202}
                assert len({r['id'] for _,r in responses})==1
                assert once()
            # A failed assertion above must not leave its queued fixture work
            # contaminating the separate competing-claim schedule.
            for _ in range(12):
                if not once():break
            with episode('two-operators-one-claim'):
                path,_=new_item();first=call('one','POST',path+'/verify');assert first[0]==202
                entered,release=threading.Event(),threading.Event();barrier=threading.Barrier(2);auth=worker.authorized;auth_calls=0
                def aligned_auth(*args):
                    nonlocal auth_calls
                    with guard:auth_calls+=1;index=auth_calls
                    if index<=2:barrier.wait(timeout=8)
                    return auth(*args)
                def hold():entered.set();assert release.wait(10)
                execute_hook=hold;before=counts['executor_calls']
                try:
                    with patch.object(worker,'authorized',aligned_auth),ThreadPoolExecutor(max_workers=2) as pool:
                        futures=[pool.submit(once),pool.submit(once)]
                        try:
                            assert entered.wait(8)
                            until=time.monotonic()+3
                            while time.monotonic()<until and not any(f.done() for f in futures):time.sleep(.01)
                            assert any(f.done() and f.result() is False for f in futures)
                        finally:release.set()
                        results=[f.result() for f in futures]
                    assert sorted(results)==[False,True] and counts['executor_calls']==before+1
                finally:execute_hook=None;release.set()
                assert call('two','GET',path)[1]['current_checks_usable']
            with episode('late-revoked-completion-cannot-clear-peer-retry'):
                path,_=new_item();first=call('one','POST',path+'/verify')[1]
                read,release=threading.Event(),threading.Event();auth=worker.authorized;index=0
                def pause_after_read(*args):
                    nonlocal index
                    index+=1
                    if index==2:read.set();assert release.wait(10)
                    return auth(*args)
                with patch.object(worker,'authorized',pause_after_read),ThreadPoolExecutor(max_workers=1) as pool:
                    future=pool.submit(once)
                    try:
                        assert read.wait(8)
                        assert call('two','POST',path+'/repository/cancel',{'verification_id':first['id']})[0]==200
                        second=call('two','POST',path+'/repository/retry',{'verification_id':first['id']});assert second[0]==200
                        assert membership('one',False,1)[0]==200
                    finally:release.set()
                    assert future.result()
                current=call('two','GET',path)[1]
                assert current['status']=='checking' and current['repository']['verification_id']==second[1]['id']
                assert [row['state'] for row in current['repository']['checks']]==['canceled','queued']
                assert once() and call('two','GET',path)[1]['current_checks_usable']
                assert membership('one',True,2)[0]==200
            with episode('manager-handover-during-running-check'):
                path,_=new_item();assert call('one','POST',path+'/verify')[0]==202
                entered,release=threading.Event(),threading.Event()
                def hold_manager():entered.set();assert release.wait(10)
                execute_hook=hold_manager
                try:
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        future=pool.submit(once)
                        try:
                            assert entered.wait(8);assert call('old-manager','GET',path)[0]==200
                            assert membership('old-manager',False,1,'manager')[0]==200
                            assert call('old-manager','GET',path)[0]==404
                            assert call('new-manager','GET',path)[0]==200
                            assert call('new-manager','POST',path+'/verify')[0]==403
                        finally:release.set()
                        assert future.result()
                finally:execute_hook=None;release.set()
                assert call('new-manager','GET',path)[1]['current_checks_usable']
            with episode('twelve-peer-retries-and-two-exact-reviews'):
                path,_=new_item();first=call('one','POST',path+'/verify')[1]
                assert call('two','POST',path+'/repository/cancel',{'verification_id':first['id']})[0]==200
                responses=batch(lambda:call('two','POST',path+'/repository/retry',{'verification_id':first['id']}))
                episodes[-1]['statuses']=[s for s,_ in responses]
                assert {s for s,_ in responses}=={200} and len({r['id'] for _,r in responses})==1
                assert once();current=call('two','GET',path)[1]
                exact={'decision':'accept_for_manual_release','patch_hash':current['patch_hash'],
                    'verification_id':current['repository']['verification_id'],'context_hash':current['repository']['context_hash']}
                with ThreadPoolExecutor(max_workers=2) as pool:
                    responses=list(pool.map(lambda actor:call(actor,'POST',path+'/decide',exact),['one','two']))
                assert sorted(status for status,_ in responses)==[200,409]
                assert call('new-manager','GET',path+'/artifact')[1]['release_state']=='not_deployed'
            if args.recovery:
                import ownstack.repository_recovery as recovery
                from datetime import timedelta
                class ControlledCrash(BaseException):pass
                def crash_job():
                    raise ControlledCrash()
                def abandon():
                    nonlocal execute_hook
                    path,_=new_item();old=call('one','POST',path+'/verify')[1]['id']
                    execute_hook=crash_job
                    try:
                        try:once()
                        except ControlledCrash:pass
                        else:raise AssertionError('Expected explicit fake worker crash')
                    finally:execute_hook=None
                    with factory() as db:
                        row=db.get(Evidence,old)
                        row.result={**row.result,'lease_until':recovery.stamp(recovery.now(db)-timedelta(seconds=1))}
                        db.commit()
                    return path,old
                with episode('two-reapers-one-cleanup-with-late-result-and-duplicate-deliveries'):
                    path,old=abandon();entered,release=threading.Event(),threading.Event();cleanup_calls=[]
                    def controlled_cleanup(*args):
                        cleanup_calls.append(args[-1]);entered.set();assert release.wait(12)
                        return {'cleanup_verified':True,'explicit_cleanup_test_double':True}
                    with patch.object(recovery,'process_dead',lambda pid:True),patch.object(recovery,'cleanup',controlled_cleanup),ThreadPoolExecutor(max_workers=2) as pool:
                        futures=[pool.submit(recovery.recover_once,factory,out/'control-jobs') for _ in range(2)]
                        try:
                            assert entered.wait(8)
                            responses=batch(lambda:call('two','POST',path+'/repository/retry',{'verification_id':old}))
                            assert {s for s,_ in responses}=={200} and {r['id'] for _,r in responses}=={old}
                            assert {r['state'] for _,r in responses}=={'recovering'}
                            with factory() as db:
                                row=db.get(Evidence,old);target=db.get(EngineeringItem,row.result['item_id'])
                                worker.discard(db,target,row,event_type='repository.late_result_discarded',report={'passed':True},owner=row.result['lease_owner'])
                                db.commit()
                            assert call('two','GET',path)[1]['status']=='checking'
                        finally:release.set()
                        assert sorted(f.result() for f in futures)==[False,True]
                    current=call('two','GET',path)[1]
                    assert len(cleanup_calls)==1 and [r['state'] for r in current['repository']['checks']]==['recovered','queued']
                    assert current['repository']['verification_id']!=old
                    assert once() and call('two','GET',path)[1]['current_checks_usable']
                if args.restart_storm:
                    with episode('cancel-read-before-reaper-claim-preserves-new-owner'):
                        path,old=abandon();read,allow_write=threading.Event(),threading.Event()
                        entered,release=threading.Event(),threading.Event();claimed=[]
                        def pause_cancel(connection,cursor,statement,parameters,context,many):
                            # FastAPI executes this synchronous handler on its
                            # AnyIO thread, not the TestClient caller's thread.
                            if not read.is_set() and statement.startswith('UPDATE engineering_items SET'):
                                read.set();assert allow_write.wait(12)
                        def hold_cleanup(*args):entered.set();assert release.wait(12);return {'cleanup_verified':True}
                        from sqlalchemy import event as sql_event
                        sql_event.listen(engine,'before_cursor_execute',pause_cancel)
                        try:
                            with patch.object(recovery,'process_dead',lambda pid:True),patch.object(recovery,'cleanup',hold_cleanup),ThreadPoolExecutor(max_workers=1,thread_name_prefix='cancel-race') as cancel_pool,ThreadPoolExecutor(max_workers=1) as recover_pool:
                                cancel_future=cancel_pool.submit(call,'two','POST',path+'/repository/cancel',{'verification_id':old})
                                try:
                                    assert read.wait(8)
                                    recover_future=recover_pool.submit(recovery.recover_once,factory,out/'control-jobs')
                                    assert entered.wait(8)
                                    with factory() as db:token=db.get(Evidence,old).result['recovery_token']
                                    allow_write.set();assert cancel_future.result()[0]==200
                                    with factory() as db:
                                        row=db.get(Evidence,old)
                                        assert row.result['state']=='canceled' and row.result['recovery_token']==token and not row.result['lease_closed']
                                    replies=batch(lambda:call('two','POST',path+'/repository/retry',{'verification_id':old}))
                                    assert {s for s,_ in replies}=={200} and {r['id'] for _,r in replies}=={old}
                                    assert {r['state'] for _,r in replies}=={'canceled'}
                                finally:allow_write.set();release.set()
                                assert recover_future.result()
                        finally:sql_event.remove(engine,'before_cursor_execute',pause_cancel)
                        current=call('two','GET',path)[1]
                        assert [r['state'] for r in current['repository']['checks']]==['canceled'] and current['status']=='checks_failed'
                        with factory() as db:assert db.get(Evidence,old).result['lease_closed']
                    with episode('eight-restarted-reapers-claim-once'):
                        path,old=abandon();entered,release=threading.Event(),threading.Event();calls=[]
                        def hold_many(*args):calls.append(args[-1]);entered.set();assert release.wait(12);return {'cleanup_verified':True}
                        barrier=threading.Barrier(8)
                        def restarted():barrier.wait(10);return recovery.recover_once(factory,out/'control-jobs')
                        with patch.object(recovery,'process_dead',lambda pid:True),patch.object(recovery,'cleanup',hold_many),ThreadPoolExecutor(max_workers=8) as pool:
                            futures=[pool.submit(restarted) for _ in range(8)]
                            try:
                                assert entered.wait(8)
                                until=time.monotonic()+8
                                while time.monotonic()<until and sum(f.done() for f in futures)<7:time.sleep(.02)
                                assert sum(f.done() and f.result() is False for f in futures)==7
                            finally:release.set()
                            assert sum(f.result() is True for f in futures)==1
                        assert calls==[old] and once()
                        current=call('two','GET',path)[1]
                        assert [r['state'] for r in current['repository']['checks']]==['recovered','passed']
                with episode('cancellation-wins-while-reaper-holds-cleanup'):
                    path,old=abandon();entered,release=threading.Event(),threading.Event()
                    def held_cleanup(*args):entered.set();assert release.wait(10);return {'cleanup_verified':True}
                    with patch.object(recovery,'process_dead',lambda pid:True),patch.object(recovery,'cleanup',held_cleanup),ThreadPoolExecutor(max_workers=1) as pool:
                        future=pool.submit(recovery.recover_once,factory,out/'control-jobs')
                        try:
                            assert entered.wait(8)
                            assert call('two','POST',path+'/repository/cancel',{'verification_id':old})[0]==200
                        finally:release.set()
                        assert future.result()
                    current=call('two','GET',path)[1]
                    assert current['status']=='checks_failed' and [r['state'] for r in current['repository']['checks']]==['canceled']
                with episode('heartbeat-waiting-on-real-lock-cannot-revive-expired-lease'):
                    path,old=abandon()
                    with factory() as db:
                        row=db.get(Evidence,old);owner=row.result['lease_owner']
                        row.result={**row.result,'lease_until':recovery.stamp(recovery.now(db)+timedelta(seconds=2))};db.commit()
                    with factory() as blocker,ThreadPoolExecutor(max_workers=1) as pool:
                        blocker.scalar(select(Evidence).where(Evidence.id==old).with_for_update())
                        future=pool.submit(recovery.renew,factory,old,owner)
                        try:
                            until=time.monotonic()+3;observed=False
                            while time.monotonic()<until:
                                with engine.connect() as monitor:
                                    observed=bool(monitor.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE application_name='ownstack_repository_races' AND wait_event_type='Lock' AND query LIKE '%evidence%'")))
                                if observed:break
                                time.sleep(.02)
                            assert observed,'Expected actual blocked heartbeat SQL'
                            episodes[-1]['database_lock_wait_observed']=True
                            time.sleep(2.1)
                        finally:blocker.rollback()
                        assert future.result() is False
                    with patch.object(recovery,'process_dead',lambda pid:True),patch.object(recovery,'cleanup',lambda *a:{'cleanup_verified':True}):
                        assert recovery.recover_once(factory,out/'control-jobs')
                    assert once() and call('two','GET',path)[1]['current_checks_usable']
    finally:
        app.dependency_overrides.pop(db_session,None)
        with factory() as db:budget=db.get(InferenceBudget,'global').reserved_calls
        report={'passed':all(r['passed'] for r in episodes) and len(episodes)==(11 if args.restart_storm else 9 if args.recovery else 6),'episodes':episodes,
            'http_requests':len(traces),'executor_calls':counts['executor_calls'],'explicit_executor_test_double':True,
            'provider_calls':0,'reserved_calls':budget,'scope':'Actual PostgreSQL/API/worker schedules with explicit fake executor; no real repository resolution or production load claim.'}
        (out/'summary.json').write_text(json.dumps(report,indent=2));engine.dispose()
        print(json.dumps({'passed':report['passed'],'episodes':len(episodes),'failed':[r['id'] for r in episodes if not r['passed']],'provider_calls':0}))
    if not report['passed']:raise SystemExit(1)

if __name__=='__main__':main()
