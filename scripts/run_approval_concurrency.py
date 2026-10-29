"""Two controlled approval/revocation races in an EMPTY loopback PostgreSQL DB.

No inference or public service is used. Set OWNSTACK_APPROVAL_TEST_DB privately
to a disposable database named ownstack_approval_scope_test.
"""
import argparse,json,os,secrets,subprocess,sys,threading,time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from pathlib import Path
from uuid import uuid4
from sqlalchemy import create_engine,event,inspect,select,text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    output=args.output.resolve();output.mkdir(mode=0o700,exist_ok=False)
    raw=os.environ.get('OWNSTACK_APPROVAL_TEST_DB','');url=make_url(raw)
    if not(url.drivername.startswith('postgresql') and url.host in {'127.0.0.1','localhost'} and url.database=='ownstack_approval_scope_test'):
        raise ValueError('An explicit empty loopback approval test database is required')
    os.environ.update(OWNSTACK_DATABASE_URL=raw,OWNSTACK_ENV='local',OWNSTACK_AI_MODE='off',OWNSTACK_MAX_LIVE_CALLS='0',
        NEBIUS_API_KEY='',NEBIUS_MODEL_ID='',NEBIUS_PATCH_MODEL_ID='',OWNSTACK_TRAINED_PLANNER_URL='',
        OWNSTACK_PLANNER_SERVICE_TOKEN='',OWNSTACK_ENFORCE_AUTH_CLOCK='false',OWNSTACK_REQUIRE_BACKGROUND='false',
        OWNSTACK_PUBLIC_ORIGIN='http://testserver',OWNSTACK_SIGNING_SECRET=secrets.token_urlsafe(48))
    root=Path(__file__).resolve().parents[1]
    engine=create_engine(raw,connect_args={'application_name':'ownstack_approval_scope_tests','options':'-c statement_timeout=12000 -c lock_timeout=10000'})
    def database_error(context):
        error=context.original_exception;diag=getattr(error,'diag',None)
        record={'type':type(error).__name__,'sqlstate':getattr(error,'sqlstate',None),
            'message':getattr(diag,'message_primary',None),'detail':getattr(diag,'message_detail',None),
            'statement':context.statement}
        with (output/'database-errors.jsonl').open('a') as file:file.write(json.dumps(record,default=str)+'\n')
    event.listen(engine,'handle_error',database_error)
    if inspect(engine).get_table_names():raise ValueError('Refusing a nonempty database')
    migrated=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=root,capture_output=True,text=True)
    (output/'migration.log').write_text(migrated.stdout+migrated.stderr);assert migrated.returncode==0
    from fastapi.testclient import TestClient
    from ownstack.api import app
    from ownstack.auth import db_session,issue_token,password_hash
    from ownstack.config import Settings
    from ownstack.models import User,Tenant,Project,Document,Contract,TeamMembership,ApprovalWitness,VariationWitness,Variation,InferenceBudget
    from ownstack.policy import CONTRACT,digest
    from ownstack.team_scope import add_general_member
    factory=sessionmaker(bind=engine,expire_on_commit=False);tokens={}
    with factory() as db:
        db.add(Tenant(id='approval-org',name='Synthetic approval organization',ai_enabled=False));db.flush()
        password=password_hash('local-synthetic-not-public')
        for user,role in [('first','admin'),('second','admin'),('third','admin'),('engineer','engineer'),('contractor','contractor')]:
            person=User(id=user,tenant_id='approval-org',role=role,password_hash=password);db.add(person);db.flush();add_general_member(db,person)
            tokens[user]={'Authorization':'Bearer '+issue_token(person,Settings().signing_secret)}
        db.add(Contract(id=CONTRACT['id'],version=CONTRACT['version'],manifest=CONTRACT,manifest_hash=digest(CONTRACT)))
        for index,name in [(1,'Ledger One'),(2,'Ledger Two')]:
            db.add(Project(id='project-'+str(index),tenant_id='approval-org',name=name,revision=1));db.flush()
            db.add(Document(id='document-'+str(index),tenant_id='approval-org',project_id='project-'+str(index),title=name,body='SYNTHETIC_PRIVATE'))
        db.commit();team=db.scalar(select(TeamMembership.team_id).where(TeamMembership.user_id=='first'))
    def override():
        with factory() as db:yield db
    app.dependency_overrides[db_session]=override
    def call(actor,method,path,body=None):
        with TestClient(app) as client:
            response=client.request(method,path,json=body,headers={**tokens[actor],'Idempotency-Key':uuid4().hex})
            return response.status_code,response.json()
    assert call('second','POST','/v1/governance',{'approval_quorum':2,'expected_quorum':1})[0]==200
    def proposal(index,name):
        status,request=call('engineer','POST','/v1/requests',{'text':f'Give contractor read-only access to {name} until the selected expiry.',
            'kind':'access','project_id':'project-'+str(index),'viewer_id':'contractor','expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()})
        assert status==201
        status,hand=call('engineer','POST','/v1/requests/'+request['id']+'/manual-handoff');assert status==200
        status,p=call('first','GET','/v1/proposals/'+hand['proposal_id']);assert status==200
        return p
    def approve(actor,p):return call(actor,'POST','/v1/proposals/'+p['id']+'/approve',{'proposal_hash':p['proposal_hash']})
    def membership(enabled,revision):return call('third','PUT',f'/v1/teams/{team}/members/first',{'role':'manager','enabled':enabled,'expected_revision':revision})
    schedules=[]
    def race(name,first,second,lock_kind):
        locked,release=threading.Event(),threading.Event()
        def held(conn,cursor,statement,params,context,many):
            sql=' '.join(statement.lower().split())
            match=('for share of users, team_memberships' in sql and 'approval_witnesses' in sql) if lock_kind=='approval' else ('from team_memberships' in sql and 'join' not in sql and 'for update' in sql)
            if match and not locked.is_set():
                locked.set()
                if not release.wait(8):raise TimeoutError('Controlled approval lock not released')
        event.listen(engine,'after_cursor_execute',held)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                a=pool.submit(first)
                assert locked.wait(8),'First call did not acquire the intended database lock'
                b=pool.submit(second);waiters=0;until=time.monotonic()+3
                try:
                    while time.monotonic()<until and not b.done():
                        with engine.connect() as db:
                            waiters=db.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND application_name='ownstack_approval_scope_tests' AND wait_event_type='Lock' AND pid<>pg_backend_pid()")).scalar_one()
                        if waiters:break
                        time.sleep(.02)
                finally:release.set()
                left,right=a.result(),b.result()
                assert waiters>0,'The second call was not observed waiting for a database lock'
        finally:release.set();event.remove(engine,'after_cursor_execute',held)
        schedules.append({'scenario':name,'first':{'status':left[0],'result':left[1]},'second':{'status':right[0],'result':right[1]},'observed_lock_waiters':waiters})
        (output/'schedules.json').write_text(json.dumps(schedules,indent=2))
        return left,right
    try:
        one=proposal(1,'Ledger One');assert approve('first',one)[1]['status']=='awaiting_second_approval'
        approved,removed=race('activation selects current reviewers before team revocation',lambda:approve('second',one),lambda:membership(False,1),'approval')
        assert approved[0]==removed[0]==200 and approved[1]['status']=='active'
        assert call('contractor','GET','/v1/host/projects/project-1/documents/document-1')[0]==200
        assert membership(True,2)[0]==200
        two=proposal(2,'Ledger Two');assert approve('first',two)[1]['status']=='awaiting_second_approval'
        removed,pending=race('team revocation commits before waiting quorum selection',lambda:membership(False,3),lambda:approve('second',two),'membership')
        assert removed[0]==pending[0]==200 and pending[1]['status']=='awaiting_second_approval' and pending[1]['approvals']==1
        assert call('contractor','GET','/v1/host/projects/project-2/documents/document-2')[0]==403
        activated=approve('third',two);assert activated[0]==200 and activated[1]['status']=='active'
        with factory() as db:
            selected=db.scalars(select(ApprovalWitness.actor_id).join(VariationWitness,VariationWitness.witness_id==ApprovalWitness.id).where(VariationWitness.variation_id==activated[1]['variation_id'])).all()
            assert set(selected)=={'second','third'}
            assert db.get(InferenceBudget,'global').reserved_calls==0
        assert call('third','POST','/v1/members/me/revoke-sessions')[0]==200
        assert call('contractor','GET','/v1/host/projects/project-2/documents/document-2')[0]==403
        assert call('contractor','GET','/v1/host/projects/project-1/documents/document-1')[0]==200
        report={'passed':True,'schedules':schedules,'selected_second_grant_reviewers':sorted(selected),'provider_calls':0,
            'scope':'Controlled real PostgreSQL schedules; synthetic actors, not production load or all interleavings.'}
        (output/'summary.json').write_text(json.dumps(report,indent=2));print(json.dumps({'passed':True,'controlled_schedules':len(schedules),'provider_calls':0}))
    finally:app.dependency_overrides.pop(db_session,None);engine.dispose()

if __name__=='__main__':main()
