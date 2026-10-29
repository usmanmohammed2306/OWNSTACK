"""Finite real PostgreSQL schedules for the local release-control protocol.

Executor results are explicit doubles. This script creates only a new labelled
local fixture, migrates/seeds synthetic data, saves a private dump and removes its
exact resources. It never dispatches candidate code, inference or a deployment.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea'


def run(args, *, check=True, timeout=60, **kwargs):
    return subprocess.run(args, capture_output=True, check=check, timeout=timeout, **kwargs)


def private(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(value if isinstance(value, bytes) else json.dumps(value, indent=2, default=str).encode())
        stream.flush();os.fsync(stream.fileno())


def result_double(claim):
    from ownstack.release_executor import (RUNNER, PROFILE, POLICY, HTTP_CLIENT, READY_CLIENT,
        execution_fingerprint, assess_observations)
    observations = [{'requirement_key': spec['key'], 'case_id': case['case_id'],
                     **case['expected'], 'error': None}
                    for spec in claim['requirements'] for case in spec['cases']]
    phase = {'state': 'completed', 'failure': '', 'cleanup_verified': True, 'observations': observations}
    return {'runner': RUNNER, 'profile': PROFILE, 'policy': POLICY,
            'image_id': 'sha256:' + 'a' * 64,
            'baseline_sha256': claim['baseline_sha256'], 'candidate_sha256': claim['candidate_sha256'],
            'requirements_sha256': claim['requirements_sha256'], 'provider_calls': 0, 'released': False,
            'oracle_sha256': hashlib.sha256((HTTP_CLIENT + READY_CLIENT).encode()).hexdigest(),
            'execution_policy_sha256': execution_fingerprint(), 'baseline': deepcopy(phase), 'candidate': deepcopy(phase),
            'executor_double': True, 'limitation': 'Control-plane schedule only. No candidate code executed.',
            **assess_observations(claim['requirements'], phase, phase)}


class Campaign:
    def __init__(self, output):
        self.output = output.resolve()
        if not self.output.is_relative_to(ROOT / '.private/release-assurance-20261027/pg-controls'):
            raise ValueError('New private release-concurrency output directory required')
        if (os.environ.get('OWNSTACK_AI_MODE') != 'off' or os.environ.get('OWNSTACK_MAX_LIVE_CALLS') != '0'
                or any(os.environ.get(k) for k in ('NEBIUS_API_KEY', 'NEBIUS_MODEL_ID', 'NEBIUS_PATCH_MODEL_ID'))):
            raise ValueError('Explicit AI off, cap zero and empty provider credentials required')
        if os.environ.get('DOCKER_HOST') and not os.environ['DOCKER_HOST'].startswith('unix://'):
            raise ValueError('Local Unix Docker endpoint required')
        endpoint = json.loads(run(['docker','context','inspect','--format','{{json .Endpoints.docker.Host}}']).stdout)
        if not endpoint.startswith('unix://'):raise ValueError('Local Unix Docker endpoint required')
        run(['docker','image','inspect',IMAGE])
        self.output.mkdir(parents=True, mode=0o700, exist_ok=False);self.output.chmod(0o700)
        self.name = 'ownstack-release-concurrency-' + uuid4().hex[:12]
        self.volume = self.name + '-data';self.ident = None;self.records = []
        self.password = secrets.token_urlsafe(24);self.engines = []

    def note(self, name, **value):
        row = {'schedule': name, **value, 'at': datetime.now(timezone.utc).isoformat()}
        self.records.append(row)
        fd = os.open(self.output/'results.jsonl',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        with os.fdopen(fd,'a') as stream:
            stream.write(json.dumps(row,default=str)+'\n');stream.flush();os.fsync(stream.fileno())

    def boot(self, requirement):
        run(['docker','volume','create','--label','ownstack.job=release-concurrency',self.volume])
        created = run(['docker','run','-d','--name',self.name,'--label','ownstack.job=release-concurrency',
            '--pull','never','--network','bridge','--publish','127.0.0.1::5432',
            '--memory','512m','--cpus','1','--pids-limit','128',
            '--mount','type=volume,src='+self.volume+',dst=/var/lib/postgresql/data',
            '-e','POSTGRES_USER=ownstack','-e','POSTGRES_PASSWORD='+self.password,
            IMAGE,'postgres','-c','shared_buffers=64MB','-c','max_wal_size=64MB','-c','min_wal_size=32MB'])
        self.ident = created.stdout.decode().strip()
        for _ in range(100):
            if run(['docker','exec',self.name,'pg_isready','-h','127.0.0.1','-U','ownstack'],check=False).returncode==0:break
            time.sleep(.2)
        else:raise RuntimeError('Disposable PostgreSQL fixture did not become ready')
        port = json.loads(run(['docker','inspect',self.name,'--format','{{json .NetworkSettings.Ports}}']).stdout)['5432/tcp'][0]
        if port['HostIp']!='127.0.0.1':raise ValueError('Only loopback publication permitted')
        self.port = int(port['HostPort'])
        os.environ.update(OWNSTACK_DATABASE_URL=self.url('ownstack'), OWNSTACK_ENV='local',
            OWNSTACK_REQUIRE_BACKGROUND='false', OWNSTACK_RELEASE_ASSURANCE='true',
            OWNSTACK_PUBLIC_ORIGIN='http://testserver',OWNSTACK_COOKIE_NAMESPACE='release-pg-'+uuid4().hex[:8],
            OWNSTACK_DEMO_PASSWORD='synthetic-local-concurrency-'+uuid4().hex)
        migrated = run([sys.executable,'-m','alembic','upgrade','head'],cwd=ROOT,env=os.environ.copy())
        private(self.output/'migration.log',migrated.stdout+migrated.stderr)
        from ownstack.seed import seed
        seed()
        from ownstack.db import SessionLocal, engine
        from ownstack.policy import Principal
        from ownstack.release_assurance import NewRequirement, Approve, create_requirement, approve_requirement
        self.engineer = Principal('atlas-engineer','atlas','engineer')
        self.owner = Principal('atlas-admin','atlas','admin')
        with SessionLocal() as db:
            drafted = create_requirement(NewRequirement(project_id='atlas-project',spec=requirement),self.engineer,db)
        with SessionLocal() as db:
            self.requirement = approve_requirement(drafted['id'],Approve(expected_hash=drafted['requirement_hash']),self.owner,db)
        engine.dispose()
        private(self.output/'fixture.json',{'id':self.ident,'name':self.name,'volume':self.volume,'image':IMAGE,
            'loopback_port':self.port,'executor_double':True,'provider_calls':0})

    def url(self, database):
        from sqlalchemy.engine import URL
        return URL.create('postgresql+psycopg',username='ownstack',password=self.password,
            host='127.0.0.1',port=self.port,database=database,
            query={'options':'-c timezone=UTC -c lock_timeout=5000 -c statement_timeout=10000'}).render_as_string(hide_password=False)

    def sql(self, query):
        import psycopg
        with psycopg.connect(host='127.0.0.1',port=self.port,user='ownstack',password=self.password,
                dbname='ownstack',autocommit=True,connect_timeout=5) as db:
            return db.execute(query).fetchall() if not query.startswith('CREATE DATABASE') else db.execute(query)

    @staticmethod
    def outcome(operation):
        try:return {'completed':True,'value':operation()}
        except Exception as error:
            return {'completed':False,'error_type':type(error).__name__,
                'status_code':getattr(error,'status_code',None),
                'sqlstate':getattr(getattr(error,'orig',None),'sqlstate',None),'detail':str(error)[:1800]}

    def saved(self,factory,ident):
        from ownstack.models import ReleaseCheck
        from ownstack.release_assurance import serialize_check
        with factory() as db:return serialize_check(db.get(ReleaseCheck,ident))

    def accept(self,factory,saved):
        from ownstack.release_assurance import decide_check,Decide
        with factory() as db:return decide_check(saved['id'],Decide(expected_revision=saved['revision'],
            evidence_hash=saved['evidence_hash'],decision='accept_for_manual_release'),self.engineer,db)

    def factory(self):
        from sqlalchemy.orm import sessionmaker
        from ownstack.db import make_engine
        name = 'release_schedule_' + uuid4().hex[:16]
        self.sql('CREATE DATABASE '+name+' TEMPLATE ownstack')
        engine = make_engine(self.url(name));self.engines.append(engine)
        return sessionmaker(bind=engine,expire_on_commit=False)

    def queue(self, factory, *, key=None):
        from ownstack.release_assurance import NewCheck, create_check
        body = NewCheck(project_id='atlas-project',baseline_sha256='a'*64,candidate_sha256='b'*64,
            requirement_ids=[self.requirement['id']],idempotency_key=key or uuid4().hex)
        with factory() as db:return create_check(body,self.engineer,db),body

    def ordered_claim_cancel_deadlock(self):
        """Deliberately expose the legacy opposite lock order, not an executor."""
        from sqlalchemy import event
        from ownstack.release_assurance import claim_next,cancel_check,Version
        factory = self.factory();queued,_=self.queue(factory)
        check_locked=threading.Event();project_locked=threading.Event();release_claim=threading.Event()
        engine = factory.kw['bind'];outcomes={}
        def after(connection,cursor,statement,params,context,many):
            thread=threading.current_thread().name
            if thread=='claim-first' and statement.lstrip().startswith('UPDATE release_checks') and not check_locked.is_set():
                check_locked.set()
                if not release_claim.wait(8):raise TimeoutError('Deadlock probe gate timed out')
            if thread=='cancel-second' and 'FROM projects' in statement and 'FOR NO KEY UPDATE' in statement:
                project_locked.set()
        event.listen(engine,'after_cursor_execute',after)
        def invoke(name,operation):
            try:outcomes[name]={'completed':True,'value':operation()}
            except Exception as error:
                outcomes[name]={'completed':False,'error_type':type(error).__name__,
                    'sqlstate':getattr(getattr(error,'orig',None),'sqlstate',None),'detail':str(error)[:1800]}
        def cancel():
            with factory() as db:return cancel_check(queued['id'],Version(expected_revision=1),self.engineer,db)
        claim_thread=threading.Thread(name='claim-first',target=invoke,args=('claim',lambda:claim_next(factory)))
        cancel_thread=threading.Thread(name='cancel-second',target=invoke,args=('cancel',cancel))
        try:
            claim_thread.start()
            if not check_locked.wait(8):raise TimeoutError('Claim did not obtain its check lock')
            cancel_thread.start()
            acquired=project_locked.wait(2)
            release_claim.set();claim_thread.join(12);cancel_thread.join(12)
            if claim_thread.is_alive() or cancel_thread.is_alive():raise TimeoutError('Owned probe threads did not terminate')
        finally:
            release_claim.set();event.remove(engine,'after_cursor_execute',after)
        clean={name:{k:v for k,v in value.items() if k!='value'} for name,value in outcomes.items()}
        reproduced=acquired and any(value.get('sqlstate')=='40P01' for value in clean.values())
        if not reproduced and any(value.get('sqlstate') for value in clean.values()):
            raise AssertionError('Unexpected PostgreSQL failure in corrected claim/cancel ordering')
        self.note('claim_cancel_opposite_lock_order',passed=not reproduced,reproduced_deadlock=reproduced,
            cancel_acquired_project_before_claim_released=acquired,outcomes=clean,executor_double=True)
        return reproduced

    def duplicate_creates(self):
        from ownstack.release_assurance import create_check,NewCheck
        from ownstack.models import ReleaseCheck
        from sqlalchemy import func,select
        factory=self.factory();barrier=threading.Barrier(8)
        body=NewCheck(project_id='atlas-project',baseline_sha256='a'*64,candidate_sha256='b'*64,
            requirement_ids=[self.requirement['id']],idempotency_key=uuid4().hex)
        def create(_):
            with factory() as db:
                barrier.wait(5);return create_check(body,self.engineer,db)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(create,range(8)))
        identities={row['id'] for row in results}
        with factory() as db:count=db.scalar(select(func.count()).select_from(ReleaseCheck))
        if len(identities)!=1 or count!=1:raise AssertionError('Duplicate delivery created multiple jobs')
        self.note('eight_simultaneous_duplicate_creates',passed=True,workers=8,accepted_ids=len(identities),rows=count,executor_double=True)

    def competing_claims(self):
        from ownstack.release_assurance import claim_next
        factory=self.factory();queued,_=self.queue(factory);barrier=threading.Barrier(8)
        def claim(_):barrier.wait(5);return claim_next(factory)
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(claim,range(8)))
        winners=[row for row in results if row is not None]
        if len(winners)!=1 or winners[0]['id']!=queued['id']:raise AssertionError('Competing claims duplicated work')
        self.note('eight_simultaneous_claims',passed=True,workers=8,winning_claims=1,executor_double=True)

    def cancel_finish(self):
        from ownstack.release_assurance import claim_next,finish_check,cancel_check,Version
        factory=self.factory();queued,_=self.queue(factory);claim=claim_next(factory);barrier=threading.Barrier(2)
        def cancel():
            with factory() as db:
                barrier.wait(5);return cancel_check(queued['id'],Version(expected_revision=claim['revision']),self.engineer,db)
        def finish():
            barrier.wait(5);return finish_check(factory,queued['id'],claim['claim_token'],result_double(claim))
        with ThreadPoolExecutor(max_workers=2) as pool:
            canceled=pool.submit(self.outcome,cancel);finished=pool.submit(self.outcome,finish)
            outcomes={'cancel':canceled.result(timeout=20),'finish':finished.result(timeout=20)}
        saved=self.saved(factory,queued['id'])
        if saved['state']=='canceled':
            if not outcomes['cancel']['completed'] or outcomes['finish'].get('value') is not False:
                raise AssertionError('Cancellation winner was overwritten')
        elif saved['state']=='passed':
            if outcomes['finish'].get('value') is not True or outcomes['cancel'].get('status_code')!=409:
                raise AssertionError('Completion winner did not fence stale cancel')
        else:raise AssertionError('Unexpected cancellation/completion terminal state')
        self.note('simultaneous_cancel_finish',passed=True,state=saved['state'],
            outcomes={name:{k:v for k,v in value.items() if k!='value'} for name,value in outcomes.items()},executor_double=True)

    def approver_change(self,kind,ordering):
        from sqlalchemy import event,text
        from ownstack.release_assurance import claim_next,finish_check
        factory=self.factory();queued,_=self.queue(factory);claim=claim_next(factory)
        team_query="UPDATE team_memberships SET enabled=false,revision=revision+1 WHERE user_id='atlas-admin'"
        role_query="UPDATE users SET role='engineer',token_version=token_version+1 WHERE id='atlas-admin'"
        change_query=team_query if kind=='membership' else role_query
        if ordering=='revoke-first':
            with factory() as db:db.execute(text(change_query));db.commit()
            finish_check(factory,queued['id'],claim['claim_token'],result_double(claim))
            saved=self.saved(factory,queued['id'])
            if saved['state']!='blocked':raise AssertionError('Revoked approver authorized completed result')
            self.note('approver_'+kind+'_revoke_before_finish',passed=True,state=saved['state'],executor_double=True)
            return
        protected=threading.Event();release_finish=threading.Event();update_started=threading.Event()
        update_committed=threading.Event();outcomes={};engine=factory.kw['bind']
        target='FROM team_memberships' if kind=='membership' else 'FROM users'
        def after(connection,cursor,statement,params,context,many):
            if threading.current_thread().name!='finisher' or target not in statement or 'FOR ' not in statement:return
            values=params.values() if isinstance(params,dict) else params
            if 'atlas-admin' in values and not protected.is_set():
                protected.set()
                if not release_finish.wait(8):raise TimeoutError('Authority-lock gate did not release')
        event.listen(engine,'after_cursor_execute',after)
        tag='release_revoke_'+uuid4().hex[:12]
        def change():
            with factory() as db:
                db.execute(text("SET LOCAL application_name='"+tag+"'"));update_started.set()
                db.execute(text(change_query));db.commit();update_committed.set()
        def finish():return finish_check(factory,queued['id'],claim['claim_token'],result_double(claim))
        def invoke(name,operation):outcomes[name]=self.outcome(operation)
        first=threading.Thread(name='finisher',target=invoke,args=('finish',finish))
        second=threading.Thread(name='revoker',target=invoke,args=('change',change))
        blocked=False
        try:
            first.start()
            if not protected.wait(8):raise TimeoutError('Finisher did not reach approver authority lock')
            second.start()
            if not update_started.wait(5):raise TimeoutError('Revoker did not start')
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                rows=self.sql("SELECT wait_event_type FROM pg_stat_activity WHERE application_name='"+tag+"'")
                if rows and rows[0][0]=='Lock':blocked=True;break
                if update_committed.is_set():break
                time.sleep(.02)
            if not blocked or update_committed.is_set():raise AssertionError('Approver change was not fenced through completion')
        finally:
            release_finish.set();first.join(12)
            if second.ident is not None:second.join(12)
            event.remove(engine,'after_cursor_execute',after)
        if first.is_alive() or second.is_alive() or not all(row['completed'] for row in outcomes.values()):
            raise AssertionError('Authority schedule did not commit cleanly')
        saved=self.saved(factory,queued['id'])
        if saved['state']!='passed':raise AssertionError('Valid result did not commit before authority change')
        decision=self.outcome(lambda:self.accept(factory,saved))
        if decision.get('status_code')!=409:raise AssertionError('Stale approver authority authorized release review')
        self.note('approver_'+kind+'_finish_before_revoke',passed=True,state=saved['state'],
            revoker_waited_on_real_lock=blocked,stale_review_status=409,executor_double=True)

    def restart_replay(self):
        from ownstack.release_assurance import claim_next,finish_check
        from ownstack.db import make_engine
        from sqlalchemy.orm import sessionmaker
        factory=self.factory();queued,_=self.queue(factory);claim=claim_next(factory)
        finish_check(factory,queued['id'],claim['claim_token'],result_double(claim))
        self.accept(factory,self.saved(factory,queued['id']))
        before=self.saved(factory,queued['id']);dbname=factory.kw['bind'].url.database
        for engine in self.engines:engine.dispose()
        run(['docker','restart','--timeout','10',self.name])
        for _ in range(100):
            if run(['docker','exec',self.name,'pg_isready','-h','127.0.0.1','-U','ownstack'],check=False).returncode==0:break
            time.sleep(.1)
        else:raise TimeoutError('Owned PostgreSQL restart did not recover')
        binding=json.loads(run(['docker','inspect',self.name,'--format','{{json .NetworkSettings.Ports}}']).stdout)['5432/tcp'][0]
        if binding['HostIp']!='127.0.0.1':raise ValueError('Restart exposed a non-loopback port')
        self.port=int(binding['HostPort'])
        engine=make_engine(self.url(dbname));self.engines.append(engine)
        restored=sessionmaker(bind=engine,expire_on_commit=False)
        after=self.saved(restored,queued['id'])
        if before!=after or claim_next(restored) is not None:raise AssertionError('Saved review changed or restarted work was duplicated')
        from sqlalchemy import text
        with restored() as db:
            counter=db.execute(text("SELECT reserved_calls FROM inference_budget WHERE id='global'")).scalar_one()
        if counter!=0:raise AssertionError('Synthetic inference budget changed')
        self.note('owned_postgres_restart_saved_review',passed=True,state=after['state'],decision=after['decision'],
            same_evidence_hash=before['evidence_hash']==after['evidence_hash'],reserved_calls=counter,executor_double=True)

    def after(self):
        self.duplicate_creates();self.competing_claims()
        if self.ordered_claim_cancel_deadlock():raise AssertionError('Claim/cancel deadlock remains')
        self.cancel_finish()
        for kind in ('membership','role'):
            for ordering in ('revoke-first','finish-first'):self.approver_change(kind,ordering)
        self.restart_replay()

    def cleanup(self):
        for engine in self.engines:engine.dispose()
        if not self.ident:return
        info=json.loads(run(['docker','inspect',self.name]).stdout)[0]
        if info['Id']!=self.ident or info['Config']['Labels'].get('ownstack.job')!='release-concurrency':
            raise ValueError('Refuse cleanup of an unowned fixture')
        dump=run(['docker','exec',self.name,'pg_dumpall','-U','ownstack','--no-role-passwords'],timeout=90).stdout
        compressed=gzip.compress(dump);private(self.output/'fixture.sql.gz',compressed)
        if gzip.decompress(compressed)!=dump:raise ValueError('Fixture gzip validation failed')
        logs=run(['docker','logs',self.name],check=False)
        private(self.output/'postgres.log',logs.stdout+logs.stderr)
        run(['docker','rm','-f',self.ident])
        volume=json.loads(run(['docker','volume','inspect',self.volume]).stdout)[0]
        if volume['Labels'].get('ownstack.job')!='release-concurrency':raise ValueError('Refuse unowned volume cleanup')
        run(['docker','volume','rm',self.volume])
        private(self.output/'cleanup.json',{'passed':True,'container_removed':self.ident,'volume_removed':self.volume,
            'backup_sha256':hashlib.sha256(compressed).hexdigest(),'backup_bytes':len(compressed),
            'backup_gzip_roundtrip':True,'provider_calls':0})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-output',type=Path,required=True)
    parser.add_argument('--requirement-json',type=Path,required=True)
    parser.add_argument('--phase',choices=['before','after'],required=True)
    args=parser.parse_args();campaign=Campaign(args.private_output)
    result={'passed':False,'executor_double':True,'provider_calls':0}
    try:
        campaign.boot(json.loads(args.requirement_json.read_text()))
        if args.phase=='before':
            reproduced=campaign.ordered_claim_cancel_deadlock()
            result.update(passed=not reproduced,reproduced_legacy_deadlock=reproduced)
        else:
            campaign.after();result.update(passed=True,accepted_schedules=len(campaign.records))
    except Exception as error:
        result.update(error_type=type(error).__name__)
        private(campaign.output/'failure.json',result)
        raise
    finally:
        campaign.cleanup()
        private(campaign.output/'report.json',{**result,'schedules':len(campaign.records),
            'limitations':'Finite local PostgreSQL schedules with explicit executor doubles, not actual code checks or all interleavings.'})
    print(json.dumps(result))
    return 0 if result['passed'] else 2


if __name__=='__main__':raise SystemExit(main())
