"""Actual legacy migration preserves history and explicitly labels its limits."""
import hashlib,json,os,subprocess,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sqlalchemy import inspect,select,text
from sqlalchemy.orm import Session
from ownstack.db import make_engine
from ownstack.models import User,ChangeRequest,Attempt,Proposal,Variation,ApprovalWitness,VariationWitness,InferenceBudget
from ownstack.team_scope import add_general_member
from ownstack.policy import Principal
from ownstack.host_access import host_read_decision

def test_existing_dual_approval_history_is_preserved_and_marked_legacy(tmp_path):
    root=Path(__file__).resolve().parents[1];url='sqlite:///'+str(tmp_path/'legacy.sqlite')
    env=dict(os.environ,OWNSTACK_DATABASE_URL=url,OWNSTACK_AI_MODE='off',OWNSTACK_MAX_LIVE_CALLS='0',NEBIUS_API_KEY='',NEBIUS_MODEL_ID='')
    def command(*args):return subprocess.run([sys.executable,*args],cwd=root,env=env,capture_output=True,text=True,timeout=30)
    assert command('-m','alembic','upgrade','f7b42c1d9a60').returncode==0
    result=command('-m','ownstack.seed');assert result.returncode==0,result.stderr
    engine=make_engine(url);at=datetime.now(timezone.utc)
    with Session(engine) as db:
        admin=db.get(User,'atlas-admin')
        second=User(id='legacy-second',tenant_id='atlas',role='admin',password_hash=admin.password_hash)
        db.add(second);db.flush();add_general_member(db,second);db.flush()
        db.add(ChangeRequest(id='legacy-request',tenant_id='atlas',requester_id='atlas-engineer',text='Legacy read-only grant',kind='access',project_id='atlas-project',viewer_id='atlas-contractor',expires_at=at+timedelta(hours=1),status='active',revision=1));db.flush()
        db.add(Attempt(id='legacy-attempt',tenant_id='atlas',request_id='legacy-request',number=1,request_revision=1,state='accepted',model_id='explicit-legacy-fixture',deadline_at=at+timedelta(minutes=1)));db.flush()
        db.add(Proposal(id='legacy-proposal',tenant_id='atlas',request_id='legacy-request',attempt_id='legacy-attempt',route='configure',reason='Explicit legacy fixture',parameters={},request_revision=1,proposal_hash='a'*64,status='approved'));db.flush()
        db.add(Variation(id='legacy-grant',tenant_id='atlas',project_id='atlas-project',viewer_id='atlas-contractor',proposal_id='legacy-proposal',starts_at=at-timedelta(minutes=1),expires_at=at+timedelta(hours=1),approval_quorum=2));db.flush()
        for actor in ['atlas-admin','legacy-second']:
            db.add(ApprovalWitness(id='legacy-'+actor,tenant_id='atlas',proposal_id='legacy-proposal',proposal_hash='a'*64,actor_id=actor,identity_version=1))
        db.get(InferenceBudget,'global').reserved_calls=32;db.commit()
    inspector=inspect(engine);tables=[t for t in inspector.get_table_names() if t!='alembic_version']
    def fingerprints():
        with engine.connect() as db:
            return {table:hashlib.sha256(json.dumps(sorted([list(r) for r in db.execute(text('SELECT * FROM "'+table+'"'))],key=repr),default=str).encode()).hexdigest() for table in tables}
    before=fingerprints();result=command('-m','alembic','upgrade','head');assert result.returncode==0,result.stderr
    assert fingerprints()==before
    with Session(engine) as db:
        links=db.scalars(select(VariationWitness)).all()
        assert len(links)==2 and {r.source for r in links}=={'legacy'}
        assert {r.witness_id for r in links}=={'legacy-atlas-admin','legacy-legacy-second'}
        assert db.get(InferenceBudget,'global').reserved_calls==32
        viewer=Principal('atlas-contractor','atlas','contractor')
        assert host_read_decision(db,viewer,'atlas','atlas-project',at).allowed
        db.get(User,'legacy-second').token_version+=1;db.commit()
        assert not host_read_decision(db,viewer,'atlas','atlas-project',at).allowed
        assert db.execute(text('PRAGMA foreign_key_check')).all()==[]
    result=command('-m','alembic','downgrade','f7b42c1d9a60')
    assert result.returncode!=0 and 'explicitly reviewed downgrade' in result.stderr
    with Session(engine) as db:assert len(db.scalars(select(VariationWitness)).all())==2
    engine.dispose()
