"""Opt-in local trained-model bridge. No Token Factory calls or budget changes."""
import os
import math
from uuid import uuid4
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from sqlalchemy import func,select
from ownstack.action_plans import resolve_command_plan
from ownstack.auth import current_principal, db_session, require_origin
from ownstack.models import PlannerRun
from ownstack.planner_runs import finish,retry,same_identity,scoped_run,snapshot,start
from ownstack.config import Settings
from ownstack.policy import Principal

router=APIRouter(prefix='/v1/agent/planner',tags=['trained local planner'])

def local_endpoint():
    url=os.getenv('OWNSTACK_TRAINED_PLANNER_URL','')
    parsed=urlsplit(url)
    # This experimental companion is deliberately not a public inference gateway.
    if Settings().environment!='local' or parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','localhost','host.docker.internal'} or parsed.username or parsed.password or parsed.path not in {'','/'} or parsed.query or parsed.fragment:
        raise HTTPException(503,'The trained planner is not enabled on this installation')
    return url.rstrip('/')

class Command(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    text: str=Field(min_length=1,max_length=1000)

class Retry(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    generation:int=Field(ge=1,le=3)

class CancelCommand(Command):
    generation:int=Field(default=1,ge=1,le=3)

def dispatch(db,row):
    """Only this ticket can complete; cancellation never claims remote stop."""
    generation=row.generation
    error=None;status=503
    try:
        endpoint=local_endpoint()
        with httpx.Client(timeout=55,trust_env=False,follow_redirects=False) as client:
            service_key=os.getenv('OWNSTACK_PLANNER_SERVICE_TOKEN','')
            response=client.post(endpoint+'/plan',json={'text':row.command_text},
                headers={'X-OwnStack-Planner-Key':service_key} if service_key else {});response.raise_for_status()
            if len(response.content)>8192:raise ValueError('Oversized result')
            data=response.json()
        proposal,resolution=resolve_command_plan(data['output'],row.role,row.command_text)
        artifact=data['artifact'];latency=data['latency_ms']
        if (not isinstance(artifact,str) or len(artifact)!=64 or any(c not in '0123456789abcdef' for c in artifact)
                or type(latency) not in (int,float) or not math.isfinite(latency) or not 0<=latency<=60000):
            raise ValueError('Invalid provenance or latency')
        expected=os.getenv('OWNSTACK_TRAINED_PLANNER_ARTIFACT_SHA256','')
        if expected and artifact!=expected:raise ValueError('Unexpected checkpoint')
        db.expire_all()
        if not same_identity(db,row):finish(db,row.id,generation,'cancelled',error='IDENTITY_CHANGED')
        else:finish(db,row.id,generation,'accepted',result={'plan':proposal.model_dump(),
            'artifact':artifact,'latency_ms':latency,'resolution':resolution})
        return snapshot(db,row)
    except httpx.TimeoutException:error='DEADLINE';status=504
    except httpx.HTTPStatusError as exc:error='BUSY' if exc.response.status_code==429 else 'MODEL_UNAVAILABLE';status=429 if exc.response.status_code==429 else 503
    except (ValueError,KeyError,TypeError):error='INVALID_MODEL_OUTPUT';status=422
    except httpx.HTTPError:error='MODEL_UNAVAILABLE'
    except HTTPException as exc:error='MODEL_DISABLED';status=exc.status_code
    finish(db,row.id,generation,'timed_out' if error=='DEADLINE' else 'failed',error=error,allow_expired=True)
    saved=snapshot(db,row)
    if saved['generation']!=generation or saved['status'] not in {'failed','timed_out'}:return saved
    raise HTTPException(status,{'message':'Planning could not finish. Inspect the saved status or retry.',
        'run_id':row.id,'error_code':error,'remote_cancellation_verified':False})

@router.get('')
def status(principal:Principal=Depends(current_principal)):
    endpoint=local_endpoint()
    try:
        with httpx.Client(timeout=2,trust_env=False,follow_redirects=False) as client:
            response=client.get(endpoint+'/health');response.raise_for_status()
            data=response.json()
        return {'ready':data.get('ready') is True,'kind':'local_fine_tuned_planner','artifact':data.get('artifact')}
    except (httpx.HTTPError,ValueError):
        raise HTTPException(503,'The trained planner is unavailable') from None

@router.get('/metrics')
def metrics(principal:Principal=Depends(current_principal),db:Session=Depends(db_session)):
    rows=db.execute(select(PlannerRun.status,func.count()).where(PlannerRun.tenant_id==principal.tenant_id,
        PlannerRun.actor_id==principal.user_id).group_by(PlannerRun.status)).all()
    return {'scope':'own_commands','states':dict(rows),'provider_calls':0}

@router.post('/cancel-command')
def cancel_command(body:CancelCommand,request:Request,idempotency_key:str=Header(),
                   principal:Principal=Depends(current_principal),db:Session=Depends(db_session)):
    require_origin(request,Settings())
    if not body.text.strip():raise HTTPException(422,'Enter a command')
    # A cancellation can arrive before the initial POST. Persist a tombstone so
    # that a late initial delivery cannot start generation under the same key.
    row,_=start(db,principal,body.text,idempotency_key)
    finish(db,row.id,body.generation,'cancelled',error='LOCAL_CANCEL',allow_expired=True)
    return snapshot(db,row)

@router.get('/saved/{key}')
def by_key(key:str,principal:Principal=Depends(current_principal),db:Session=Depends(db_session)):
    row=db.scalar(select(PlannerRun).where(PlannerRun.tenant_id==principal.tenant_id,
        PlannerRun.actor_id==principal.user_id,PlannerRun.idempotency_key==key))
    if row is None:raise HTTPException(404,'Not found')
    return {**snapshot(db,row),'text':row.command_text}

@router.get('/{run_id}')
def saved(run_id:str,principal:Principal=Depends(current_principal),db:Session=Depends(db_session)):
    row=scoped_run(db,principal,run_id)
    return {**snapshot(db,row),'text':row.command_text}

@router.post('')
def plan(body:Command,request:Request,idempotency_key:str|None=Header(default=None),
         principal:Principal=Depends(current_principal),db:Session=Depends(db_session)):
    require_origin(request,Settings())
    if not body.text.strip():raise HTTPException(422,'Enter a command')
    row,claimed=start(db,principal,body.text,idempotency_key if idempotency_key is not None else str(uuid4()))
    return dispatch(db,row) if claimed else snapshot(db,row)

@router.post('/{run_id}/cancel')
def cancel(run_id:str,request:Request,body:Retry,principal:Principal=Depends(current_principal),db:Session=Depends(db_session)):
    require_origin(request,Settings());row=scoped_run(db,principal,run_id)
    finish(db,row.id,body.generation,'cancelled',error='LOCAL_CANCEL',allow_expired=True)
    return snapshot(db,row)

@router.post('/{run_id}/retry')
def retry_plan(run_id:str,request:Request,body:Retry,principal:Principal=Depends(current_principal),db:Session=Depends(db_session)):
    require_origin(request,Settings());row=scoped_run(db,principal,run_id)
    row,claimed=retry(db,principal,row,body.generation)
    return dispatch(db,row) if claimed else snapshot(db,row)
