"""Exercise the actual owned host API with container-local identity/grant fixtures.

Fixture-issued tokens traverse the real authentication and host authorization
routes. This tests enforcement, not an external identity provider or a new live
AI/approval journey. All data lives in this disposable container's /tmp.
"""
import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
os.environ.update(OWNSTACK_SOURCE_ROOT=str(ROOT),OWNSTACK_DATABASE_URL='sqlite:////tmp/ownstack-source-fixture.sqlite',
    OWNSTACK_AI_MODE='off',OWNSTACK_MAX_LIVE_CALLS='0',NEBIUS_API_KEY='',NEBIUS_MODEL_ID='',NEBIUS_PATCH_MODEL_ID='',
    OWNSTACK_ENV='local',OWNSTACK_PUBLIC_ORIGIN='http://testserver',OWNSTACK_REQUIRE_BACKGROUND='false',
    OWNSTACK_SIGNING_SECRET='synthetic-container-only-signing-secret',OWNSTACK_REPOSITORY_COCKPIT='false',
    OWNSTACK_RELEASE_ASSURANCE='false',OWNSTACK_ENFORCE_AUTH_CLOCK='false')
from datetime import datetime,timedelta,timezone
from http.server import BaseHTTPRequestHandler,HTTPServer
import json
from uuid import uuid4
from sqlalchemy import update
from fastapi.testclient import TestClient
from ownstack.db import Base,engine,SessionLocal
from ownstack.models import Tenant,User,Project,Document,ChangeRequest,Attempt,Proposal,Variation
from ownstack.team_scope import ensure_general_team,add_general_member
from ownstack.auth import issue_token
from ownstack.config import Settings
from ownstack.api import app
Base.metadata.create_all(engine)
client=TestClient(app)

def read(value):
    now=datetime.now(timezone.utc)
    with SessionLocal() as db:
        for tenant in {value['actor_tenant_id'],value['resource_tenant_id']}:
            if not db.get(Tenant,tenant):
                db.add(Tenant(id=tenant,name=tenant));db.flush();ensure_general_team(db,tenant)
        actor=db.get(User,value['actor_id'])
        if actor is None:
            actor=User(id=value['actor_id'],tenant_id=value['actor_tenant_id'],role=value['actor_role'],password_hash='fixture:no-password-login')
            db.add(actor);db.flush();add_general_member(db,actor)
        elif actor.tenant_id!=value['actor_tenant_id']:return 400,{}
        actor.role=value['actor_role'];actor.token_version+=1
        project_id=value['resource_tenant_id']+'-project'
        if not db.get(Project,project_id):db.add(Project(id=project_id,tenant_id=value['resource_tenant_id'],name='Fixture project'));db.flush()
        if not db.get(Document,value['resource_id']):
            db.add(Document(id=value['resource_id'],tenant_id=value['resource_tenant_id'],project_id=project_id,title='Fixture document',body='Fixture private body'));db.flush()
        db.execute(update(Variation).values(state='revoked'))
        if value['assigned'] or value.get('grant_starts_at'):
            if value.get('grant_starts_at'):
                at=datetime.fromisoformat(value['at'].replace('Z','+00:00'))
                starts=now+(datetime.fromisoformat(value['grant_starts_at'].replace('Z','+00:00'))-at)
                expires=now+(datetime.fromisoformat(value['grant_expires_at'].replace('Z','+00:00'))-at)
            else:starts=now-timedelta(hours=1);expires=now+timedelta(hours=1)
            request=ChangeRequest(id=str(uuid4()),tenant_id=actor.tenant_id,requester_id=actor.id,text='Synthetic grant fixture',kind='access',project_id=project_id)
            db.add(request);db.flush()
            attempt=Attempt(id=str(uuid4()),tenant_id=actor.tenant_id,request_id=request.id,number=1,request_revision=1,
                state='accepted',model_id='fixture:no-inference',deadline_at=now+timedelta(seconds=60))
            db.add(attempt);db.flush()
            proposal=Proposal(id=str(uuid4()),tenant_id=actor.tenant_id,request_id=request.id,attempt_id=attempt.id,route='configure',
                reason='Synthetic fixture, no model call',parameters={},request_revision=1,proposal_hash='fixture-only')
            db.add(proposal);db.flush()
            db.add(Variation(id=str(uuid4()),tenant_id=actor.tenant_id,project_id=project_id,viewer_id=actor.id,proposal_id=proposal.id,
                state='revoked' if value.get('grant_revoked') else 'active',starts_at=starts,expires_at=expires,approval_quorum=1))
        db.commit();token=issue_token(actor,Settings().signing_secret)
    response=client.get('/v1/host/projects/'+project_id+'/documents/'+value['resource_id'],headers={'Authorization':'Bearer '+token})
    return response.status_code,response.json() if response.status_code==200 else {}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        self.send_response(200);self.end_headers();self.wfile.write(b'ready')
    def do_POST(self):
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16384:raise ValueError('Bounded input required')
            value=json.loads(self.rfile.read(length));status,body=read(value)
        except Exception:status,body=500,{}
        raw=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

if __name__=='__main__':HTTPServer(('127.0.0.1',8765),Handler).serve_forever()
