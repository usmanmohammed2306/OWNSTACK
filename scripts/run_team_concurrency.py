"""Three ordered PostgreSQL authorization races in an EMPTY local test database.

Set OWNSTACK_TEAM_TEST_DB privately. The database must be named exactly
ownstack_team_scope_test on loopback. No inference, deployment or live ledger.
"""
import argparse,json,os,secrets,subprocess,sys,threading,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
from sqlalchemy import create_engine,event,func,inspect,select,text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    output=args.output.resolve();output.mkdir(mode=0o700,parents=False,exist_ok=False)
    raw=os.environ.get('OWNSTACK_TEAM_TEST_DB','');url=make_url(raw)
    if not(url.drivername.startswith('postgresql') and url.host in {'127.0.0.1','localhost'} and url.database=='ownstack_team_scope_test'):
        raise ValueError('An explicit loopback-only PostgreSQL test database is required')
    os.environ.update({'OWNSTACK_DATABASE_URL':raw,'OWNSTACK_ENV':'local','OWNSTACK_AI_MODE':'off',
        'OWNSTACK_MAX_LIVE_CALLS':'0','NEBIUS_API_KEY':'','NEBIUS_MODEL_ID':'','NEBIUS_PATCH_MODEL_ID':'',
        'OWNSTACK_TRAINED_PLANNER_URL':'','OWNSTACK_PLANNER_SERVICE_TOKEN':'','OWNSTACK_REQUIRE_BACKGROUND':'false',
        'OWNSTACK_ENFORCE_AUTH_CLOCK':'false','OWNSTACK_PUBLIC_ORIGIN':'http://testserver',
        'OWNSTACK_SIGNING_SECRET':secrets.token_urlsafe(48)})
    root=Path(__file__).resolve().parents[1]
    engine=create_engine(raw,connect_args={'application_name':'ownstack_team_scope_tests','options':'-c statement_timeout=12000 -c lock_timeout=10000'})
    if inspect(engine).get_table_names():raise ValueError('Refusing a nonempty database')
    migrated=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=root,env=os.environ,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (output/'migration.log').write_text(migrated.stdout)
    if migrated.returncode:raise RuntimeError('Test database migration failed; inspect the private log')
    from fastapi.testclient import TestClient
    from ownstack.api import app
    from ownstack.auth import db_session,issue_token,password_hash
    from ownstack.config import Settings
    from ownstack.models import ChangeRequest,InferenceBudget,Project,Team,TeamMembership,Tenant,User
    from ownstack.team_scope import ensure_general_team,add_general_member
    factory=sessionmaker(bind=engine,expire_on_commit=False)
    with factory() as db:
        db.add(Tenant(id='scope-org',name='Synthetic race organization',ai_enabled=False));db.flush()
        ensure_general_team(db,'scope-org')
        admin=User(id='scope-admin',tenant_id='scope-org',role='admin',password_hash=password_hash('synthetic-not-public'))
        engineer=User(id='scope-engineer',tenant_id='scope-org',role='engineer',password_hash=admin.password_hash)
        db.add_all([admin,engineer]);db.flush();add_general_member(db,admin)
        db.add(Team(id='scope-team',tenant_id='scope-org',name='Payments',name_key='payments'));db.flush()
        db.add(TeamMembership(id='scope-member',tenant_id='scope-org',team_id='scope-team',user_id=engineer.id,role='member'))
        db.add(Project(id='scope-project',tenant_id='scope-org',team_id='scope-team',name='Payments',revision=1));db.commit()
        tokens={u.id:{'Authorization':'Bearer '+issue_token(u,Settings().signing_secret)} for u in [admin,engineer]}
    def override():
        with factory() as db:yield db
    app.dependency_overrides[db_session]=override
    results=[]
    def call(actor,method,path,body=None):
        with TestClient(app) as client:
            response=client.request(method,path,headers={**tokens[actor],'Idempotency-Key':uuid4().hex},json=body)
            return response.status_code
    request_body={'text':'Export a PDF settlement report without changing capture.','kind':'feature','project_id':'scope-project'}
    def create_request():return call('scope-engineer','POST','/v1/requests',request_body)
    def membership(enabled,revision):return call('scope-admin','PUT','/v1/teams/scope-team/members/scope-engineer',
        {'role':'member','enabled':enabled,'expected_revision':revision})
    def race(name,first,second,kind,expected):
        locked,release,started=threading.Event(),threading.Event(),threading.Event()
        def held(conn,cursor,statement,parameters,context,many):
            sql=' '.join(statement.lower().split())
            values=parameters.values() if isinstance(parameters,dict) else parameters
            selected=('team_memberships' in sql and (('join teams' in sql)==(kind=='request'))) if kind in {'request','membership'} else 'from users' in sql
            # FastAPI executes sync handlers on another thread. Select the exact
            # SQL lock shape rather than a caller-thread label that cannot follow it.
            if (not locked.is_set() and 'for update' in sql and selected
                    and 'scope-engineer' in values):
                locked.set()
                if not release.wait(8):raise TimeoutError('Controlled lock was not released')
        def run(label,function):
            if label=='second':started.set()
            return function()
        event.listen(engine,'after_cursor_execute',held)
        try:
            with ThreadPoolExecutor(max_workers=2) as workers:
                a=workers.submit(run,'first',first)
                if not locked.wait(8):
                    (output/'lock-observation-failure.json').write_text(json.dumps({'scenario':name,'first_status':a.result() if a.done() else 'pending'}))
                    raise AssertionError('First transaction did not acquire the intended row lock')
                b=workers.submit(run,'second',second)
                if not started.wait(3):raise AssertionError('Second transaction did not start')
                waiters=0;until=time.monotonic()+3
                while time.monotonic()<until and not b.done():
                    with engine.connect() as probe:
                        waiters=probe.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND application_name='ownstack_team_scope_tests' AND wait_event_type='Lock' AND pid<>pg_backend_pid()")).scalar_one()
                    if waiters:break
                    time.sleep(.025)
                blocked=not b.done() and waiters>0;release.set()
                statuses=[a.result(timeout=15),b.result(timeout=15)]
            result={'scenario':name,'second_waited_for_lock':blocked,'observed_postgres_lock_waiters':waiters,'statuses':statuses,'expected':expected,
                'passed':blocked and statuses==expected}
            results.append(result)
            (output/'results.json').write_text(json.dumps(results,indent=2))
            assert result['passed'],name
        finally:
            release.set();event.remove(engine,'after_cursor_execute',held)
    try:
        race('authorized request commits before membership revocation',create_request,lambda:membership(False,1),'request',[201,200])
        assert create_request()==404
        assert membership(True,2)==200
        race('membership revocation commits before waiting request',lambda:membership(False,3),create_request,'membership',[200,404])
        assert membership(True,4)==200
        race('account disable commits before waiting request authentication',
            lambda:call('scope-admin','POST','/v1/members/scope-engineer/access',{'enabled':False}),create_request,'identity',[200,401])
        with factory() as db:
            assert db.scalar(select(func.count(ChangeRequest.id)))==1
            assert db.get(InferenceBudget,'global').reserved_calls==0
            version=db.execute(text('show server_version')).scalar_one()
        summary={'passed':True,'schedules':results,'requests_saved':1,'provider_calls':0,'reserved_calls':0,
            'postgres_version':version,'scope':'Real PostgreSQL row-lock schedules with API requests. Synthetic local data; not production load, hostile-code certification or independent users.'}
        (output/'summary.json').write_text(json.dumps(summary,indent=2));print('Three PostgreSQL scope races passed; one authorized request saved; zero inference calls.')
    finally:
        app.dependency_overrides.clear();engine.dispose()


if __name__=='__main__':main()
