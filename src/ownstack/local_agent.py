"""Actual local trained intent -> host-validated proposal, never approval.

No provider-mode change, reservation, model shell tool or deployment authority.
The model controls the bounded proposed route; the host compiles the exact effect.
"""
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from ownstack.auth import current_principal,db_session,require_role
from ownstack.config import Settings
from ownstack.models import ChangeRequest,Evidence,PlannerRun,User
from ownstack.planner_runs import start,snapshot,retry,same_identity
from ownstack.planner_api import dispatch
from ownstack.policy import Principal,digest
from ownstack.ai import AIResult
from ownstack.service import scoped,start_attempt,claim_attempt,accept_result,record,uid
from ownstack.team_scope import require_request

router=APIRouter(prefix='/v1/local-agent')

def intent(row):return digest({name:getattr(row,name) for name in ['revision','text','kind','project_id','viewer_id','expires_at']})

class Prepare(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    revision:int=Field(ge=1)
    retry_generation:int|None=Field(default=None,ge=1,le=3)

def gate(principal):
    require_role(principal,'admin','engineer')
    if Settings().environment!='local':raise HTTPException(503,'The local agent is not enabled here')

@router.get('/requests/{request_id}')
def saved(request_id:str,principal:Principal=Depends(current_principal),db:Session=Depends(db_session)):
    gate(principal);r=scoped(db,ChangeRequest,request_id,principal.tenant_id, actor=principal)
    if r.accepted_proposal_id:return {'stage':'proposal_saved','proposal_id':r.accepted_proposal_id,'request_status':r.status,'provider_calls':0}
    run=db.scalar(select(PlannerRun).where(PlannerRun.tenant_id==principal.tenant_id,
        PlannerRun.actor_id==principal.user_id,PlannerRun.idempotency_key==f'request-{r.id}-{r.revision}'))
    value=None if run is None else snapshot(db,run)
    return {'stage':'ready' if value is None else value['status'],
        'planner_run_id':run.id if run else None,'generation':run.generation if run else None,'provider_calls':0}

@router.post('/requests/{request_id}/prepare')
def prepare(request_id:str,body:Prepare,principal:Principal=Depends(current_principal),db:Session=Depends(db_session)):
    gate(principal);request=scoped(db,ChangeRequest,request_id,principal.tenant_id, actor=principal, write=True)
    if request.revision!=body.revision:raise HTTPException(409,'The request changed; review its current revision')
    if request.accepted_proposal_id:return {'stage':'proposal_saved','proposal_id':request.accepted_proposal_id,'request_status':request.status,'provider_calls':0}
    if request.status not in {'new','failed','refused'}:raise HTTPException(409,'This request already has active work')
    if len(request.text)>1000:raise HTTPException(422,'This local checkpoint supports up to 1000 characters. Narrow the request without omitting important constraints.')
    original_revision=request.revision
    original_intent=intent(request)
    run,claimed=start(db,principal,request.text,f'request-{request.id}-{original_revision}')
    if not claimed and body.retry_generation is not None:run,claimed=retry(db,principal,run,body.retry_generation)
    result=dispatch(db,run) if claimed else snapshot(db,run)
    if result['status']=='running':return {'stage':'interpreting','planner_run_id':run.id,'provider_calls':0}
    if result['status']!='accepted':raise HTTPException(409,{'message':'The saved agent attempt needs inspection or retry.','planner_run_id':run.id,'state':result['status']})
    actions=result['plan']['actions']
    if len(actions)!=1 or actions[0]['action'] not in {'draft','refuse'}:
        raise HTTPException(422,'The model could not identify a supported change. Clarify the request; no effect was prepared.')
    action=actions[0]
    route='refuse' if action['action']=='refuse' else 'configure' if action['target']=='access' else 'engineering'
    db.expire_all()
    request=db.scalar(select(ChangeRequest).where(ChangeRequest.id==request_id,
        ChangeRequest.tenant_id==principal.tenant_id).with_for_update())
    require_request(db,principal,request_id,write=True)
    db.scalar(select(User).where(User.id==principal.user_id).with_for_update())
    if not same_identity(db,run):raise HTTPException(409,'Identity changed during interpretation')
    if request.revision!=original_revision or intent(request)!=original_intent:raise HTTPException(409,'Request changed during interpretation; the result was not applied')
    if request.accepted_proposal_id:return {'stage':'proposal_saved','proposal_id':request.accepted_proposal_id,'request_status':request.status,'provider_calls':0}
    if request.status not in {'new','failed','refused'}:raise HTTPException(409,'Other work started during interpretation')
    # Claim/accept in one transaction. No queued local task is exposed to the
    # provider worker, and no provider reservation path is entered.
    model_id='local-trained:'+result['artifact'][:16]
    attempt=start_attempt(db,request,model_id,30)
    db.flush()
    if not claim_attempt(db,attempt.id):raise HTTPException(409,'Could not claim the exact request revision')
    answer=AIResult(route,'Local trained intent, checked against the host capability contract.',model_id,
        int(result['latency_ms']),None,None)
    if not accept_result(db,attempt.id,answer):raise HTTPException(409,'The request was superseded')
    db.add(Evidence(id=uid(),tenant_id=request.tenant_id,request_id=request.id,kind='local_agent_intent',
        subject_hash=original_intent,
        result={'planner_run_id':run.id,'artifact':result['artifact'],'plan':result['plan'],
            'resolution':result['resolution'],'inference_location':'local','provider_calls':0},
        limitation='Bounded local intent model. Host validation, exact human approval and release checks remain independent.'))
    record(db,request.tenant_id,request.id,'proposal.local_agent_prepared',{'proposal_id':request.accepted_proposal_id,'planner_run_id':run.id,'actor_id':principal.user_id})
    db.commit()
    return {'stage':'proposal_saved','proposal_id':request.accepted_proposal_id,'request_status':request.status,
        'planner_run_id':run.id,'inference_location':'local','provider_calls':0}
