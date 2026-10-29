"""Execute frozen authored stories through the owned HTTP application.

Run with --model local for actual authenticated loopback checkpoint inference.
Synthetic transport is available only to debug the harness and is labeled.
Industry narratives are context, not implementations of external systems. Each
case exercises one of forty repeated controls with pre-authenticated identities.
Time/identity/storage faults are injected explicitly. No hosted app is touched.
"""
import argparse
from collections import Counter
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def runtime():
    # Set before application imports. A developer's .env cannot enable a provider.
    for key, value in {
        'OWNSTACK_AI_MODE': 'off', 'OWNSTACK_MAX_LIVE_CALLS': '0',
        'NEBIUS_API_KEY': '', 'NEBIUS_MODEL_ID': '', 'NEBIUS_PATCH_MODEL_ID': '',
        'OWNSTACK_ENV': 'local', 'OWNSTACK_REQUIRE_BACKGROUND': 'false',
        'OWNSTACK_PUBLIC_ORIGIN': 'http://testserver',
        'OWNSTACK_DATABASE_URL': 'sqlite://', 'OWNSTACK_ENFORCE_AUTH_CLOCK': 'false',
        'OWNSTACK_TRAINED_PLANNER_URL': 'http://127.0.0.1:8812',
    }.items():
        os.environ[key] = value


class Journey:
    def __init__(self, case, model):
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine, event
        from sqlalchemy.pool import StaticPool
        from sqlalchemy.orm import sessionmaker
        from ownstack.api import app
        from ownstack.auth import db_session, issue_token
        from ownstack.config import Settings
        from ownstack.db import Base
        from ownstack.models import Tenant, User, Project, Document, Contract, InferenceBudget
        from ownstack.policy import CONTRACT, digest
        self.case, self.mode, self.app = case, model, app
        self.trace, self.ai_issues, self.fallbacks = [], [], 0
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        @event.listens_for(self.engine, 'connect')
        def fk(connection, _): connection.execute('PRAGMA foreign_keys=ON')
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.headers = {}
        with self.factory() as db:
            db.add_all([Tenant(id='atlas', name='Atlas'), Tenant(id='nova', name='Nova')]); db.flush()
            # Login hashing is covered separately. These isolated journeys start
            # with signed local identities, never production cookies or accounts.
            for name, tenant, role in [('admin','atlas','admin'),('admin2','atlas','admin'),
                ('engineer','atlas','engineer'),('contractor','atlas','contractor'),('foreign','nova','admin')]:
                user = User(id=name, tenant_id=tenant, role=role, password_hash='not-a-login-record')
                db.add(user); db.flush()
                self.headers[name] = {'Authorization': 'Bearer '+issue_token(user, Settings().signing_secret)}
            db.add_all([Project(id='p',tenant_id='atlas',name=case['project'],revision=1),
                Project(id='p2',tenant_id='atlas',name=case['project']+' annex',revision=1),
                Project(id='foreign-p',tenant_id='nova',name='Other customer',revision=1)])
            db.flush()
            db.add_all([Document(id='d',tenant_id='atlas',project_id='p',title='Review',body='private '+case['id']),
                Document(id='d2',tenant_id='atlas',project_id='p2',title='Annex',body='annex private'),
                Document(id='foreign-d',tenant_id='nova',project_id='foreign-p',title='Other',body='foreign private'),
                Contract(id=CONTRACT['id'],version=1,manifest=CONTRACT,manifest_hash=digest(CONTRACT)),
                InferenceBudget(id='global',reserved_calls=0)])
            db.commit()
        def dependency():
            with self.factory() as db: yield db
        app.dependency_overrides[db_session] = dependency
        self.client = TestClient(app, raise_server_exceptions=False)

    def close(self):
        self.client.close(); self.app.dependency_overrides.clear(); self.engine.dispose()

    def call(self, method, path, actor='engineer', body=None, code=200, key=None):
        headers = {**self.headers[actor]}
        if method == 'POST': headers['Idempotency-Key'] = key or str(len(self.trace))
        kw = {'headers': headers}
        if body is not None: kw['json'] = body
        response = self.client.request(method, path, **kw)
        self.trace.append({'method':method,'path':path,'actor':actor,'status':response.status_code})
        assert response.status_code in ((code,) if isinstance(code,int) else code), (
            self.case['id'], self.case['pattern'], self.trace[-1], response.text[:500])
        return response.json() if response.content else None

    def mutate(self, model, object_id, **fields):
        with self.factory() as db:
            row = db.get(model, object_id)
            for name, value in fields.items(): setattr(row,name,value)
            db.commit()

    def create(self, body=None, key='request'):
        expires = (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
        self.body = body or {'text':self.case['request'],'kind':self.case['kind'],'project_id':'p',
            **({'viewer_id':'contractor','expires_at':expires} if self.case['kind']=='access' else {})}
        self.rid = self.call('POST','/v1/requests',body=self.body,key=key,code=201)['id']
        return self.rid

    def prepare(self, expected='configure', allow_fallback=True):
        from ownstack.models import ChangeRequest
        with self.factory() as db: revision = db.get(ChangeRequest,self.rid).revision
        url = f'/v1/local-agent/requests/{self.rid}/prepare'
        result = self.call('POST',url,body={'revision':revision},code=(200,409,422))
        pid = result.get('proposal_id')
        proposal = self.call('GET','/v1/proposals/'+pid) if pid else None
        if not proposal or proposal['route'] != expected:
            self.ai_issues.append({'request_id':self.rid,'expected_route':expected,
                'observed_route':proposal['route'] if proposal else None,'result':result})
            if allow_fallback:
                # A human handoff is a measured recovery, never model success.
                result = self.call('POST',f'/v1/requests/{self.rid}/manual-handoff')
                self.fallbacks += 1
                pid = result['proposal_id']; proposal = self.call('GET','/v1/proposals/'+pid)
        self.pid, self.proposal = pid, proposal
        return proposal

    def approve(self, actor='admin', key=None, proposal_hash=None, code=200):
        return self.call('POST',f'/v1/proposals/{self.pid}/approve',actor,
            {'proposal_hash':proposal_hash or self.proposal['proposal_hash']},code=code,key=key)

    def read(self, code=200, actor='contractor', project='p', doc='d'):
        return self.call('GET',f'/v1/host/projects/{project}/documents/{doc}',actor,code=code)

    def revoke(self, grant, body=None, code=200):
        return self.call('POST',f'/v1/variations/{grant}/revoke','admin',body,code)

    def refresh(self):
        review = self.call('GET',f'/v1/proposals/{self.pid}/refresh-review')
        result = self.call('POST',f'/v1/proposals/{self.pid}/refresh',body={
            'proposal_hash':review['proposal_hash'],'review_hash':review['review_hash'],
            'reason':'Host changed; preserve the original scope and expiry.'})
        self.pid=result['proposal_id']; self.proposal=self.call('GET','/v1/proposals/'+self.pid)

    def execute(self):
        from sqlalchemy import select, func, event
        from sqlalchemy.exc import SQLAlchemyError
        from ownstack.models import (User, Project, Document, Tenant, Variation, ChangeRequest,
            ApprovalWitness, HostObservation, EngineeringItem, InferenceBudget, PlannerRun, Proposal)
        from ownstack.patch_agent import fixture_patch
        from ownstack.proof import verify_envelope
        from ownstack.policy import aware
        p=self.case['pattern']
        if p in {'foreign_project','foreign_viewer'}:
            body={'text':self.case['request'],'kind':'access','project_id':'foreign-p' if p=='foreign_project' else 'p',
                'viewer_id':'foreign' if p=='foreign_viewer' else 'contractor',
                'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
            self.call('POST','/v1/requests',body=body,code=404)
            return 'foreign_scope_denied_before_model'
        self.create()
        if p=='duplicate_request':
            assert self.call('POST','/v1/requests',body=self.body,key='request',code=201)['id']==self.rid
        if p=='changed_idempotency':self.call('POST','/v1/requests',body={**self.body,'text':self.body['text']+' changed'},key='request',code=409)
        if p=='forged_agent_fields':
            self.call('POST',f'/v1/local-agent/requests/{self.rid}/prepare',body={'revision':1,'approve':True},code=422)
        if p in {'two_reviews','duplicate_reviewer','signer_role_loss','signer_rotation','review_age'}:
            self.call('POST','/v1/governance','admin',{'approval_quorum':2,'expected_quorum':1})
        if p=='disabled_viewer':self.mutate(User,'contractor',enabled=False)
        if p in {'actor_changes','request_revision_changes','intent_changes'}:
            module=importlib.import_module('ownstack.local_agent'); original=module.dispatch
            def changed(db,run):
                result=original(db,run)
                if p=='actor_changes':self.mutate(User,'engineer',role='contractor')
                elif p=='request_revision_changes':self.mutate(ChangeRequest,self.rid,revision=2)
                else:self.mutate(ChangeRequest,self.rid,text=self.case['request']+' altered intent')
                return result
            with patch.object(module,'dispatch',changed):
                self.call('POST',f'/v1/local-agent/requests/{self.rid}/prepare',body={'revision':1},code=409)
            with self.factory() as db:assert db.scalar(select(func.count()).select_from(Proposal))==0
            return 'stale_model_answer_discarded'
        feature=p in {'disguised_feature','feature_handoff','patch_role','patch_escape','oversized_patch','release_without_checks','stale_patch_hash'}
        expected='refuse' if p=='disabled_viewer' else 'engineering' if feature else 'configure'
        self.prepare(expected,allow_fallback=not (p in {'disabled_viewer','disguised_feature'}))
        if p=='disabled_viewer':
            assert self.proposal and self.proposal['route']=='refuse', 'Disabled viewer must not get an allowed preview'
            self.read(401)
            return 'disabled_identity_refused'
        if p=='disguised_feature':
            assert self.proposal and self.proposal['route'] in {'engineering','refuse'}
            assert self.approve(code=409)
            self.read(403)
            return 'unsupported_effect_never_configured'
        if feature:
            assert self.proposal['route']=='engineering'
            items=self.call('GET','/v1/engineering')
            item=next(row for row in items if row['request_id']==self.rid)
            iid=item['id']; candidate=fixture_patch()
            if p=='patch_role':self.call('POST',f'/v1/engineering/{iid}/manual-patch','admin',{'patch':candidate},code=403)
            if p=='patch_escape':
                candidate['edits'][0]['path']='../escape.py'
                self.call('POST',f'/v1/engineering/{iid}/manual-patch',body={'patch':candidate},code=422)
            if p=='oversized_patch':
                candidate['edits'][0]['new']='x'*100001
                self.call('POST',f'/v1/engineering/{iid}/manual-patch',body={'patch':candidate},code=(413,422))
            if p in {'release_without_checks','stale_patch_hash'}:
                saved=self.call('POST',f'/v1/engineering/{iid}/manual-patch',body={'patch':candidate})
                if p=='stale_patch_hash':
                    # Exercise the real offline disposable Docker runner. A
                    # drafted-only item would reject any hash and could mask a
                    # broken exact-checked-hash gate.
                    checked=self.call('POST',f'/v1/engineering/{iid}/verify')
                    assert checked['passed'] and checked['runner']=='docker-external-oracle'
                    assert len(checked['cases'])==7
                self.call('POST',f'/v1/engineering/{iid}/decide',body={'decision':'accept_for_manual_release',
                    'patch_hash':saved['patch_hash'] if p=='release_without_checks' else '0'*64},code=409)
                if p=='stale_patch_hash':
                    decision=self.call('POST',f'/v1/engineering/{iid}/decide',body={
                        'decision':'accept_for_manual_release','patch_hash':saved['patch_hash']})
                    assert decision['release_state']=='not_deployed'
            self.read(403)
            self.call('GET',f'/v1/engineering/{iid}','foreign',code=404)
            return 'checked_manual_patch_human_record_only' if p=='stale_patch_hash' else 'engineering_handoff_not_released'
        self.read(403)
        fresh=self.call('POST',f'/v1/proposals/{self.pid}/preview','admin')
        assert fresh['matches_saved_proposal']
        if p in {'duplicate_preparation','saved_refresh'}:
            with self.factory() as db:before=db.scalar(select(func.count()).select_from(PlannerRun))
            if p=='duplicate_preparation':self.call('POST',f'/v1/local-agent/requests/{self.rid}/prepare',body={'revision':1})
            self.call('GET',f'/v1/local-agent/requests/{self.rid}')
            with self.factory() as db:assert db.scalar(select(func.count()).select_from(PlannerRun))==before
        if p in {'project_drift','document_drift','policy_drift'}:
            if p=='project_drift':self.mutate(Project,'p',revision=2)
            elif p=='document_drift':self.mutate(Document,'d',body='Updated evidence '+self.case['id'])
            else:self.call('POST','/v1/governance','admin',{'approval_quorum':2,'expected_quorum':1})
            self.approve(code=409);self.read(403);self.refresh()
        if p=='wrong_hash':self.approve(proposal_hash='0'*64,code=409)
        if p=='wrong_approver':self.approve(actor='engineer',code=403)
        if p=='approval_audit_failure':
            module=importlib.import_module('ownstack.service'); original=module.record
            def fail(db,tenant,rid,kind,payload):
                if kind=='variation.activated':raise SQLAlchemyError('Injected evidence write outage')
                return original(db,tenant,rid,kind,payload)
            with patch.object(module,'record',fail):self.approve(code=500)
            self.read(403)
        approved=self.approve(key='approve')
        if p in {'two_reviews','duplicate_reviewer','signer_role_loss','signer_rotation','review_age','policy_drift'}:
            assert approved['status']=='awaiting_second_approval';self.read(403)
            if p=='duplicate_reviewer':assert self.approve(key='same-person')['approvals']==1
            if p=='review_age':
                with self.factory() as db:
                    row=db.scalar(select(ApprovalWitness));row.created_at-=timedelta(minutes=16);db.commit()
                assert self.approve('admin2')['status']=='awaiting_second_approval';self.read(403)
                approved=self.approve(key='fresh-review')
            else:approved=self.approve('admin2')
        grant=approved['variation_id']; assert grant
        if p=='approval_replay':assert self.approve(key='approve')==approved
        self.read();self.read(404,actor='foreign');self.read(404,project='foreign-p',doc='foreign-d')
        if p=='observation_failure':
            def fail(db,*_):
                if any(isinstance(row,HostObservation) for row in db.new):raise SQLAlchemyError('Injected observation outage')
            event.listen(self.factory.class_,'before_flush',fail)
            try:self.read(500)
            finally:event.remove(self.factory.class_,'before_flush',fail)
            self.read()
        if p in {'expiry','exact_expiry','future_start'}:
            with self.factory() as db:variation=db.get(Variation,grant);end=aware(variation.expires_at)
            module=importlib.import_module('ownstack.api')
            if p=='future_start':
                start=datetime.now(timezone.utc)+timedelta(minutes=1)
                self.mutate(Variation,grant,starts_at=start);self.read(403)
                with patch.object(module,'utcnow',lambda:start):self.read()
            else:
                at=end+(timedelta(microseconds=1) if p=='expiry' else timedelta())
                with patch.object(module,'utcnow',lambda:at):self.read(403)
        if p=='disable_after_grant':
            self.call('POST','/v1/members/contractor/access','admin',{'enabled':False});self.read(401)
        if p in {'signer_role_loss','signer_rotation'}:
            self.mutate(User,'admin2',**({'role':'member'} if p=='signer_role_loss' else {'token_version':2}))
            self.read(403)
        if p=='proof_tampering':
            proof=self.call('GET',f'/v1/requests/{self.rid}/proof');assert verify_envelope(proof)
            proof['payload']['request']['text']='tampered';assert not verify_envelope(proof)
            self.call('GET',f'/v1/requests/{self.rid}/proof','foreign',code=404)
        if p=='selective_revoke':
            first=(self.rid,self.pid,self.proposal)
            self.create({'text':self.case['request'].replace(self.case['project'],self.case['project']+' annex'),
                'kind':'access','project_id':'p2','viewer_id':'contractor',
                'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()},key='request2')
            self.prepare();other=self.approve()['variation_id'];self.read(project='p2',doc='d2')
            self.revoke(grant);self.read(403);self.read(project='p2',doc='d2');self.revoke(other)
            self.rid,self.pid,self.proposal=first
            return 'selective_revoke_preserves_other_project'
        if p=='role_survives_revoke':self.mutate(User,'contractor',role='member')
        if p=='revoke_drift':
            snap=self.call('GET',f'/v1/variations/{grant}/revoke-preview','admin')
            self.mutate(Variation,grant,revision=2)
            self.revoke(grant,{'preview_hash':snap['preview_hash']},409)
            self.read()
        self.revoke(grant)
        self.read(200 if p=='role_survives_revoke' else 401 if p=='disable_after_grant' else 403)
        return 'access_delivered_and_removed' if p!='role_survives_revoke' else 'role_access_honestly_survives_revoke'

    def evidence(self):
        from sqlalchemy import select
        from ownstack.models import PlannerRun, InferenceBudget, Variation, EngineeringItem
        with self.factory() as db:
            runs=db.scalars(select(PlannerRun)).all()
            assert db.get(InferenceBudget,'global').reserved_calls==0
            assert all(item.human_decision is None or self.case['pattern']=='stale_patch_hash'
                and item.human_decision=='accept_for_manual_release' for item in db.scalars(select(EngineeringItem)))
            return {'model_runs':[{'status':r.status,'generation':r.generation,'result':r.result} for r in runs],
                'provider_reservations':0,'variations':len(db.scalars(select(Variation)).all())}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',choices=['local','synthetic'],default='local')
    parser.add_argument('--limit',type=int,default=1000)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();runtime()
    if args.output.exists():raise SystemExit('Use a new output directory to preserve failed runs')
    args.output.mkdir(parents=True,mode=0o700)
    source=ROOT/'evals/story_matrix_v1/cases.jsonl';raw=source.read_bytes()
    cases=[json.loads(line) for line in raw.splitlines()][:args.limit]
    if args.model=='local':
        import httpx
        keyfile=ROOT/'.private/gaps-local-20261025/planner-service-key'
        os.environ['OWNSTACK_PLANNER_SERVICE_TOKEN']=keyfile.read_text().strip()
        health=httpx.get('http://127.0.0.1:8812/health',timeout=5,trust_env=False).json()
        expected='add27bfb98ee80ad39ef217e5677e820c92f8a92dd8629528c383c83aea38949'
        if not health.get('ready') or health.get('artifact')!=expected:raise SystemExit('Pinned local checkpoint is not ready')
        os.environ['OWNSTACK_TRAINED_PLANNER_ARTIFACT_SHA256']=expected
    import httpx
    transport=importlib.import_module('ownstack.planner_api')
    class Synthetic:
        def __init__(self,*a,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def post(self,url,json,**kw):
            target='feature' if 'PDF' in json['text'] else 'access'
            return httpx.Response(200,request=httpx.Request('POST',url),json={
                'output':__import__('json').dumps({'actions':[{'action':'draft','target':target}]}),
                'artifact':'a'*64,'latency_ms':1})
    if args.model=='synthetic':os.environ['OWNSTACK_TRAINED_PLANNER_ARTIFACT_SHA256']='a'*64
    started=time.monotonic();rows=[]
    with (patch.object(transport.httpx,'Client',Synthetic) if args.model=='synthetic' else nullcontext()):
        for i,case in enumerate(cases):
            journey=Journey(case,args.model);at=time.monotonic()
            row={'id':case['id'],'domain':case['domain'],'pattern':case['pattern']}
            try:
                row['outcome']=journey.execute();row['evidence']=journey.evidence();row['passed']=True
            except Exception as exc:
                row.update(passed=False,error=type(exc).__name__+': '+str(exc))
                # Keep exact failing DB, never an original account/production DB.
                import sqlite3
                with journey.engine.connect() as connection:
                    dest=sqlite3.connect(args.output/(case['id']+'-failed.sqlite'))
                    connection.connection.driver_connection.backup(dest);dest.close()
            finally:
                row.update(trace=journey.trace,model_issues=journey.ai_issues,human_fallbacks=journey.fallbacks,
                    elapsed_s=round(time.monotonic()-at,4))
                (args.output/(case['id']+'.json')).write_text(json.dumps(row,indent=2,default=str)+'\n')
                journey.close();rows.append(row)
            if (i+1)%10==0 or not row['passed']:
                print(json.dumps({'completed':i+1,'failed':sum(not r['passed'] for r in rows),'last':case['id']}),flush=True)
    runs=[run for row in rows for run in row.get('evidence',{}).get('model_runs',[])]
    latencies=sorted(run['result']['latency_ms'] for run in runs if run['result'])
    report={'dataset_sha256':hashlib.sha256(raw).hexdigest(),'transport':args.model,
        'scope':'In-process HTTP, isolated SQLite, pre-authenticated local identities; 25 authored contexts crossed with 40 repeated control patterns. Not 1000 independent systems or observed customers.',
        'cases':len(rows),'passed':sum(r['passed'] for r in rows),'failed':sum(not r['passed'] for r in rows),
        'human_fallbacks':sum(r['human_fallbacks'] for r in rows),'model_issue_cases':sum(bool(r['model_issues']) for r in rows),
        'http_requests':sum(len(r['trace']) for r in rows),'outcomes':dict(Counter(r.get('outcome','failed') for r in rows)),
        'elapsed_s':round(time.monotonic()-started,3),'provider_calls':0,'deployed':False,
        'saved_model_runs':len(runs),'saved_model_states':dict(Counter(run['status'] for run in runs)),
        'accepted_model_latency_ms':{'samples':len(latencies),'p50':latencies[len(latencies)//2] if latencies else None,
            'p95':latencies[min(len(latencies)-1,int(len(latencies)*.95))] if latencies else None},
        'limitations':['Faults/time injected; not a real distributed outage or wall-clock expiry wait.',
            'Engineering handoffs are not delivered PDF features. The stale-hash pattern runs a manual fixture patch in real no-network Docker and records a human decision without deployment.',
            'Human recovery is not model accuracy; narrow request text, not full narrative, is passed to the model.']}
    (args.output/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    return 0 if report['failed']==0 else 1


if __name__=='__main__':raise SystemExit(main())
