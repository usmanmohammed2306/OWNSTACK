"""Durable, scoped clarification feeding the existing independent release gate.

Append-only release audit snapshots avoid a second workflow database. All writes
share the existing project/authority lock. Models cannot publish expectations.
"""
from copy import deepcopy
from datetime import timedelta
import hashlib
from uuid import uuid4
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from ownstack.auth import current_principal,db_session,require_role
from ownstack.config import Settings
from ownstack.models import ChangeRequest,ReleaseAudit,ReleaseRequirement,ReleaseCheck,Project,User
from ownstack.workspace_models import RequestWorkspace
from ownstack.policy import digest,aware
from ownstack.service import utcnow,reserve_live_call
from ownstack.team_scope import require_request
from ownstack.release_assurance import (enabled,lock_project,audit,approval_authority,
    approve_requirement_in_transaction,Approve,approval_valid)
from ownstack.change_agent_contracts import (FIELDS,QUESTIONS,checked_answers,VisibilityPolicy,
    validate_decision,policy_hash,counterexample_requirements)
from ownstack.change_agent_contracts import workflow_identity

LOADED_WORKFLOW=workflow_identity()
from ownstack import change_agent_model

router=APIRouter(prefix='/v1/change-agents',tags=['bounded change agent'],dependencies=[Depends(enabled)])

class Body(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')

class Start(Body):
    request_id:str=Field(min_length=1,max_length=40)
    source_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    idempotency_key:str=Field(min_length=8,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')
    repository_id:str|None=Field(default=None,min_length=1,max_length=40)

class Revision(Body):
    expected_revision:int=Field(ge=1)

class Answers(Revision):
    answers:dict=Field(min_length=1,max_length=5)
    note:str=Field(default='',max_length=1000)

class Step(Revision):
    idempotency_key:str=Field(min_length=8,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')

class Exact(Revision):
    policy_hash:str=Field(pattern=r'^[a-f0-9]{64}$')

class Review(Revision):
    evidence_hash:str=Field(pattern=r'^[a-f0-9]{64}$')
    comment:str=Field(min_length=2,max_length=2000)
    decision:Literal['comment','accept_for_manual_release','reject']='comment'
    idempotency_key:str=Field(min_length=8,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')

class RepairProposal(Revision):
    check_id:str=Field(min_length=1,max_length=40)
    files:dict[str,str]=Field(min_length=1,max_length=4)
    idempotency_key:str=Field(min_length=8,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')

def sources_for(db,req,source_sha):
    rows=db.scalars(select(ReleaseAudit).where(ReleaseAudit.tenant_id==req.tenant_id,
        ReleaseAudit.project_id==req.project_id,ReleaseAudit.action=='source.registered')).all()
    snapshot=next((r.payload['snapshot'] for r in rows if r.payload['snapshot']['sha256']==source_sha),None)
    workspace=db.get(RequestWorkspace,req.id)
    if snapshot is None or workspace is None or not workspace.code_files:
        raise HTTPException(409,'Register the source and connect its selected Python files to this request first.')
    if any(snapshot['files'].get(path)!=hashlib.sha256(source.encode()).hexdigest() for path,source in workspace.code_files.items()):
        raise HTTPException(409,'Connected code differs from the registered source snapshot')
    context={path:source[:8000] for path,source in sorted(workspace.code_files.items())[:4]}
    return workspace.code_hash,context

def persist(db,project,state):
    if state['revision']>100:raise HTTPException(409,'Session history limit reached; preserve it and start a new session')
    audit(db,project,state['id'],'agent.state',state=deepcopy(state))
    db.flush()

def load(db,principal,ident,write=False):
    require_role(principal,'admin','engineer','manager')
    rows=db.scalars(select(ReleaseAudit).where(ReleaseAudit.subject_id==ident,
        ReleaseAudit.tenant_id==principal.tenant_id,ReleaseAudit.action=='agent.state').limit(101)).all()
    if not rows:raise HTTPException(404,'Not found')
    state=deepcopy(max(rows,key=lambda row:row.payload['state']['revision']).payload['state'])
    req=require_request(db,principal,state['request_id'],write=write)
    project=lock_project(db,principal,req.project_id) if write else None
    if write:
        # Re-read under the project lock, after waiting for another writer.
        rows=db.scalars(select(ReleaseAudit).where(ReleaseAudit.subject_id==ident,
            ReleaseAudit.tenant_id==principal.tenant_id,ReleaseAudit.action=='agent.state').execution_options(populate_existing=True)).all()
        state=deepcopy(max(rows,key=lambda row:row.payload['state']['revision']).payload['state'])
        db.refresh(req)
    return state,req,project

def validate_context(db,state,req,project):
    if state.get('repository'):
        from ownstack.repository_registry import validate_witness
        validate_witness(db,req,state['repository'])
    from ownstack.customers import request_customer
    if request_customer(db, req, lock=True) != state.get('customer'):
        raise HTTPException(409, 'Customer request scope changed')
    if state.get('customer') and not state.get('repository'):
        from ownstack.repository_registry import states
        if states(db,project):raise HTTPException(409,'Unconnected historical discovery cannot authorize this onboarded project; start connected discovery')
    from datetime import datetime
    if state['workflow']!=LOADED_WORKFLOW or workflow_identity()!=LOADED_WORKFLOW:raise HTTPException(409,'Agent or oracle code changed; restart the service and create a fresh discovery')
    if state['status']!='approved' and utcnow()>=aware(datetime.fromisoformat(state['expires_at'])):raise HTTPException(409,'Discovery session expired')
    if req.revision!=state['request_revision'] or digest(req.text)!=state['request_hash']:
        raise HTTPException(409,'Customer request changed; start a fresh discovery')
    code_hash,sources=sources_for(db,req,state['source_sha256'])
    if code_hash!=state['code_hash']:raise HTTPException(409,'Private source context changed')
    actor=db.get(User,state['author_id'])
    if not actor or not actor.enabled or actor.role not in {'admin','engineer'}:
        raise HTTPException(409,'Discovery author authority changed')
    try:current=approval_authority(db,actor,project)
    except ValueError:raise HTTPException(409,'Discovery author authority changed') from None
    if current!=state['authority']:raise HTTPException(409,'Discovery author authority generation changed')
    return sources

def compare(state,revision):
    if state['revision']!=revision:raise HTTPException(409,'Agent state changed. Refresh before continuing.')

def present(state):
    result=deepcopy(state)
    operation=state.get('operation')
    from datetime import datetime
    result['local_wait_expired']=bool(operation and utcnow()>=aware(datetime.fromisoformat(operation['deadline'])))
    result['missing']=[key for key in FIELDS if key not in state['answers']]
    result['questions']={key:QUESTIONS[key] for key in result['missing']}
    result['policy_hash']=policy_hash(state) if not result['missing'] else None
    result['release_state']='not_deployed'
    return result


def expire_owned_wait(db,project,state,operation,deadline):
    """A late answer may clear its own expired claim, never a replacement.

    An interrupted request with no returning answer stays inspectable/cancelable
    through the derived local_wait_expired flag. No automatic retry or claim of
    remote cancellation is implied by either path.
    """
    if state.get('operation') and state['operation']['id']==operation and utcnow()>=deadline:
        state.update(revision=state['revision']+1,operation=None,
            status='failed' if state['status']=='running' else state['status'],error='LOCAL_WAIT_EXPIRED')
        persist(db,project,state)

def discovery_requirement_valid(db,item,project):
    """Close legacy gate bypasses: derived expectations retain request lineage."""
    from urllib.parse import urlsplit
    parts=urlsplit(item.spec['source_ref']).path.strip('/').split('/')
    if len(parts)!=2:raise ValueError('Malformed discovery lineage')
    rows=db.scalars(select(ReleaseAudit).where(ReleaseAudit.subject_id==parts[0],
        ReleaseAudit.project_id==project.id,ReleaseAudit.tenant_id==item.tenant_id,ReleaseAudit.action=='agent.state')).all()
    if not rows:raise ValueError('Discovery lineage is missing')
    state=max(rows,key=lambda r:r.payload['state']['revision']).payload['state']
    if state['status']!='approved' or item.id not in state['requirement_ids'] or policy_hash(state)!=parts[1]:raise ValueError('Discovery approval changed')
    request=db.get(ChangeRequest,state['request_id'])
    if not request or request.project_id!=project.id:raise ValueError('Discovery request scope changed')
    try:validate_context(db,state,request,project)
    except HTTPException as error:raise ValueError('Discovery request, source or authority is stale') from error

@router.post('',status_code=201)
def start(body:Start,principal=Depends(current_principal),db=Depends(db_session)):
    from ownstack.customers import request_customer
    require_role(principal,'admin','engineer')
    req=require_request(db,principal,body.request_id,write=True);project=lock_project(db,principal,req.project_id)
    rows=db.scalars(select(ReleaseAudit).where(ReleaseAudit.project_id==project.id,ReleaseAudit.action=='agent.state')).all()
    old=next((r.payload['state'] for r in rows if r.payload['state']['author_id']==principal.user_id and r.payload['state']['start_key']==body.idempotency_key),None)
    if old:
        if (old['request_id'],old['source_sha256'],(old.get('repository') or {}).get('repository_id'))!=(body.request_id,body.source_sha256,body.repository_id):raise HTTPException(409,'Idempotency key belongs to different discovery inputs')
        return present(load(db,principal,old['id'])[0])
    if len({r.subject_id for r in rows})>=100:raise HTTPException(409,'Project discovery session limit reached')
    code_hash,_=sources_for(db,req,body.source_sha256)
    from ownstack.repository_registry import witness
    if request_customer(db,req,lock=True) and not body.repository_id:
        from ownstack.repository_registry import states
        if states(db,project):raise HTTPException(409,'Select a repository connected to this customer before discovery')
    connection=witness(db,req,body.repository_id,kind='python',source_sha256=body.source_sha256) if body.repository_id else None
    ident=str(uuid4())
    ancestor=next((r.payload['state'] for r in rows if r.payload['state']['request_id']==req.id),None)
    state={'id':ident,'lineage_id':ancestor.get('lineage_id',ancestor['id']) if ancestor else ident,'revision':1,'project_id':project.id,'request_id':req.id,'request_revision':req.revision,
        'request_hash':digest(req.text),'code_hash':code_hash,'source_sha256':body.source_sha256,'author_id':principal.user_id,
        'authority':approval_authority(db,db.get(User,principal.user_id),project),'customer':request_customer(db,req,lock=True),'repository':connection,'answers':{},'notes':[],
        'status':'clarifying','operations':{},'operation':None,'last_decision':None,'requirement_ids':[],
        'start_key':body.idempotency_key,'workflow':LOADED_WORKFLOW,'expires_at':(utcnow()+timedelta(days=1)).isoformat()}
    persist(db,project,state)
    audit(db,project,state['id'],'agent.created',request_id=req.id,actor=principal.user_id)
    db.commit();return present(state)

@router.get('/{ident}')
def get(ident:str,principal=Depends(current_principal),db=Depends(db_session)):
    state,req,_=load(db,principal,ident);result=present(state)
    # Saved operations are history. Refresh rechecks the same current context as
    # writes, including customer/repository and author permission generations.
    try:
        validate_context(db,state,req,db.get(Project,req.project_id))
        result['needs_fresh_discovery']=False
    except HTTPException:
        result['needs_fresh_discovery']=True
    runs=db.scalars(select(ReleaseAudit).where(ReleaseAudit.subject_id==ident,
        ReleaseAudit.tenant_id==principal.tenant_id,ReleaseAudit.action=='agent.counterexample_completed')
        .order_by(ReleaseAudit.created_at.desc()).limit(5)).all()
    result['runs']=[r.payload['result'] for r in runs]
    return result


@router.get('')
def list_sessions(request_id:str,principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'admin','engineer','manager');req=require_request(db,principal,request_id)
    rows=db.scalars(select(ReleaseAudit).where(ReleaseAudit.tenant_id==principal.tenant_id,
        ReleaseAudit.project_id==req.project_id,ReleaseAudit.action=='agent.created',
        ReleaseAudit.payload['request_id'].as_string()==request_id).order_by(ReleaseAudit.created_at.desc()).limit(20)).all()
    return [{'id':r.subject_id,'request_id':req.id} for r in rows]

@router.post('/{ident}/answers')
def answer(ident:str,body:Answers,principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'admin','engineer');state,req,project=load(db,principal,ident,True)
    validate_context(db,state,req,project);compare(state,body.expected_revision)
    if state['status'] in {'published','approved','running'}:raise HTTPException(409,'Cancel the active local wait or start a new discovery after publication')
    try:answers=checked_answers({**state['answers'],**body.answers})
    except ValueError:raise HTTPException(422,'Explicit supported policy answers required') from None
    state['answers']=answers
    if body.note:state['notes']=(state['notes']+[{'actor':principal.user_id,'text':body.note}])[-10:]
    state.update(revision=state['revision']+1,status='ready' if len(answers)==len(FIELDS) else 'clarifying',operation=None)
    persist(db,project,state);db.commit();return present(state)

@router.post('/{ident}/step')
def step(ident:str,body:Step,principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'admin','engineer');state,req,project=load(db,principal,ident,True)
    sources=validate_context(db,state,req,project)
    intent=digest(body.model_dump())
    if body.idempotency_key in state['operations']:
        if state['operations'][body.idempotency_key]!=intent:raise HTTPException(409,'Idempotency key reused for different state')
        return present(state)
    compare(state,body.expected_revision)
    if state['status'] in {'running','published','approved'}:raise HTTPException(409,'Saved work is already running or in review')
    settings=Settings()
    if settings.ai_mode=='nebius':raise HTTPException(503,'Local live inference is frozen. This new local workflow cannot spend the hosted demo allowance.')
    if settings.ai_mode=='off':raise HTTPException(503,'AI_OFF. Explicit answers and human review remain available; no provider call was made.')
    if len(state['operations'])>=10:raise HTTPException(409,'Bounded model-step limit reached')
    reserve_live_call(db,settings,principal.tenant_id)
    operation=str(uuid4());deadline=utcnow()+timedelta(seconds=settings.ai_timeout+2)
    state['operations'][body.idempotency_key]=intent
    state.update(revision=state['revision']+1,status='running',operation={'id':operation,'deadline':deadline.isoformat()})
    persist(db,project,state);db.commit()
    try:
        decision,usage=change_agent_model.decide(deepcopy(state),sources,req.text,settings)
        decision=validate_decision(decision,state,sources,req.text);error=None
    except Exception as failure:
        decision=None;usage={'live':False,'outcome':'failed','error_type':type(failure).__name__};error='MODEL_STEP_FAILED'
    current,request,project=load(db,principal,ident,True)
    validate_context(db,current,request,project)
    if current['operation'] is None or current['operation']['id']!=operation or utcnow()>=deadline:
        expire_owned_wait(db,project,current,operation,deadline)
        audit(db,project,ident,'agent.late_result_discarded',operation=operation,error=error)
        db.commit();raise HTTPException(409,'Late or canceled model result discarded. Remote inference cancellation is unverified.')
    current.update(revision=current['revision']+1,status='failed' if error else 'ready' if decision['action']=='propose' else 'clarifying',
        operation=None,last_decision=decision,last_usage=usage,error=error)
    persist(db,project,current);db.commit();return present(current)

@router.post('/{ident}/cancel')
def cancel(ident:str,body:Revision,principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'admin','engineer');state,req,project=load(db,principal,ident,True)
    validate_context(db,state,req,project);compare(state,body.expected_revision)
    if state['operation'] is None:return present(state)
    state.update(revision=state['revision']+1,status='approved' if state['status']=='approved' else 'clarifying',operation=None,error=None)
    persist(db,project,state);db.commit();return present(state)

@router.post('/{ident}/patch-proposal')
def patch_proposal(ident:str,body:RepairProposal,principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'engineer');state,check,project=review_item(db,principal,ident,body.check_id,True)
    req=require_request(db,principal,state['request_id'],write=True);validate_context(db,state,req,project)
    intent=digest({**body.model_dump(),'actor':principal.user_id})
    history=db.scalars(select(ReleaseAudit).where(ReleaseAudit.subject_id==ident,
        ReleaseAudit.tenant_id==principal.tenant_id,ReleaseAudit.action=='agent.patch_saved')).all()
    old=next((r.payload for r in history if r.payload['key']==body.idempotency_key and r.payload['actor']==principal.user_id),None)
    if old:
        if old['intent']!=intent:raise HTTPException(409,'Patch key belongs to different inputs')
        return old['result']
    if state['operation']:
        if state['operation'].get('intent')==intent:
            expired=present(state)['local_wait_expired']
            return {'status':'timed_out' if expired else 'running','patch':None,'local_wait_expired':expired}
        raise HTTPException(409,'Another model operation is saved as running')
    compare(state,body.expected_revision)
    if state['status']!='approved' or check.state!='regression':raise HTTPException(409,'Approved policy and an observed regression required')
    from ownstack.release_assurance import context_valid,assess_report
    try:
        context_valid(db,check)
        if assess_report(check,check.report)!='regression':raise ValueError('No independently verified regression')
    except (ValueError,TypeError,KeyError):raise HTTPException(409,'Current independent regression evidence required') from None
    from ownstack.request_patterns import CodeBody
    try:CodeBody(expected_revision=1,files=body.files)
    except ValueError:raise HTTPException(422,'Bounded public Python source required') from None
    snapshot=check.report.get('candidate_snapshot',{})
    if any(snapshot.get('files',{}).get(path)!=hashlib.sha256(source.encode()).hexdigest() or path==snapshot.get('config',{}).get('entrypoint')
        for path,source in body.files.items()):raise HTTPException(409,'Editable source differs from the actual checked candidate')
    settings=Settings()
    if settings.ai_mode=='off' or settings.ai_mode=='nebius':raise HTTPException(503,'Local provider dispatch is frozen. Inspect the saved counterexample and supply a reviewed repair without spending credits.')
    if len(history)>=2:raise HTTPException(409,'Bounded repair proposal limit reached')
    from ownstack.counterexample_loop import counterexamples,preservation_witnesses,RepositoryPatch
    context={'source_sha256':check.candidate_sha256,'editable_files':body.files,'approved_policy':state['answers'],
        'counterexample':counterexamples(check.report,check.requirements)['minimal_observed'],
        'preservation_witnesses':preservation_witnesses(check.report,check.requirements),'oracle_hash':check.requirements_sha256}
    reserve_live_call(db,settings,principal.tenant_id)
    operation=str(uuid4());deadline=utcnow()+timedelta(seconds=settings.ai_timeout+2)
    state.update(revision=state['revision']+1,error=None,operation={'id':operation,'intent':intent,'deadline':deadline.isoformat()})
    persist(db,project,state);db.commit()
    try:
        patch,usage=change_agent_model.propose_patch(context,settings);patch=RepositoryPatch.model_validate(patch).model_dump()
        from ownstack.repair_contracts import validate_response_preservation
        validate_response_preservation(patch,context)
        for edit in patch['edits']:
            if edit['path'] not in body.files or body.files[edit['path']].count(edit['old'])!=1 or edit['old']==edit['new']:raise ValueError('Edit capability or exact anchor mismatch')
        result={'status':'proposed','patch':patch,'usage':usage,'check_id':check.id,'source_sha256':check.candidate_sha256,'released':False}
    except Exception as error:result={'status':'failed','patch':None,'error_type':type(error).__name__,'released':False}
    current,request,project=load(db,principal,ident,True);validate_context(db,current,request,project)
    try:context_valid(db,db.get(ReleaseCheck,body.check_id))
    except ValueError:raise HTTPException(409,'Repair context changed; model answer discarded') from None
    if current['operation'] is None or current['operation']['id']!=operation or utcnow()>=deadline:
        expire_owned_wait(db,project,current,operation,deadline)
        audit(db,project,ident,'agent.late_result_discarded',operation=operation);db.commit();raise HTTPException(409,'Late repair proposal discarded')
    current.update(revision=current['revision']+1,operation=None)
    persist(db,project,current);audit(db,project,ident,'agent.patch_saved',key=body.idempotency_key,actor=principal.user_id,intent=intent,result=result)
    db.commit();return result

@router.post('/{ident}/publish')
def publish(ident:str,body:Exact,principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'admin','engineer');state,req,project=load(db,principal,ident,True)
    validate_context(db,state,req,project)
    if set(state['answers'])!=set(FIELDS) or body.policy_hash!=policy_hash(state):raise HTTPException(409,'Exact complete policy required')
    if state['status'] in {'published','approved'}:return present(state)
    compare(state,body.expected_revision)
    if state['status']=='running':raise HTTPException(409,'Cancel the active model wait before publishing')
    policy=VisibilityPolicy.model_validate(state['answers'])
    specs=counterexample_requirements(policy,session_id=state.get('lineage_id',ident),customer=(state.get('customer') or {}).get('customer_id',req.tenant_id),owner=state['author_id'],
        source_ref=f'ownstack://discovery/{ident}/{body.policy_hash}')
    from ownstack.release_contracts import requirement_digest
    for spec in specs:
        previous=db.scalar(select(ReleaseRequirement).where(ReleaseRequirement.project_id==project.id,ReleaseRequirement.key==spec.key).order_by(ReleaseRequirement.version.desc()).limit(1))
        if previous:spec=spec.model_copy(update={'version':previous.version+1})
        item=ReleaseRequirement(id=str(uuid4()),tenant_id=req.tenant_id,project_id=project.id,key=spec.key,version=spec.version,
            spec=spec.model_dump(mode='json'),requirement_hash=requirement_digest(spec),created_by=state['author_id'],state='draft')
        db.add(item);state['requirement_ids'].append(item.id)
        if state.get('customer'):
            from ownstack.customers import bind_requirement
            db.flush()
            bind_requirement(db, item, state['customer']['customer_id'])
        audit(db,project,item.id,'requirement.drafted',actor=principal.user_id,requirement_hash=item.requirement_hash)
    state.update(revision=state['revision']+1,status='published')
    persist(db,project,state);db.commit();return present(state)

@router.post('/{ident}/approve')
def approve(ident:str,body:Exact,principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'admin');state,req,project=load(db,principal,ident,True)
    validate_context(db,state,req,project)
    if body.policy_hash!=policy_hash(state) or state['status'] not in {'published','approved'}:raise HTTPException(409,'Exact published policy required')
    if state['status']=='approved':
        for ident in state['requirement_ids']:approval_valid(db,db.get(ReleaseRequirement,ident),project,utcnow())
        return present(state)
    compare(state,body.expected_revision)
    # Literal overlapping contexts cannot carry different approved expectations.
    # This bounded conflict check does not claim general semantic satisfiability.
    proposed=[db.get(ReleaseRequirement,r) for r in state['requirement_ids']]
    existing=db.scalars(select(ReleaseRequirement).where(ReleaseRequirement.project_id==project.id,
        ReleaseRequirement.state=='approved',ReleaseRequirement.id.not_in(state['requirement_ids']))).all()
    replacing={row.key for row in proposed}
    expectations={digest(case['input']):digest(case['expected']) for row in existing if row.key not in replacing for case in row.spec['cases']}
    if any(digest(case['input']) in expectations and expectations[digest(case['input'])]!=digest(case['expected'])
        for row in proposed for case in row.spec['cases']):raise HTTPException(409,'Current approved behavior conflicts with this policy; resolve the requirement revisions first')
    for requirement_id in state['requirement_ids']:
        row=db.get(ReleaseRequirement,requirement_id)
        approve_requirement_in_transaction(requirement_id,Approve(expected_hash=row.requirement_hash),principal,db)
    state.update(revision=state['revision']+1,status='approved')
    persist(db,project,state);db.commit();return present(state)


def review_item(db,principal,ident,check_id,write=False):
    state,req,project=load(db,principal,ident,write)
    from ownstack.release_assurance import row
    check,project=row(db,ReleaseCheck,check_id,principal,write=write)
    if check.project_id!=state['project_id'] or not set(state['requirement_ids']) or not set(state['requirement_ids'])<=set(check.requirement_ids):
        raise HTTPException(404,'Not found')
    return state,check,project

@router.get('/{ident}/checks/{check_id}/review')
def read_review(ident:str,check_id:str,principal=Depends(current_principal),db=Depends(db_session)):
    state,check,project=review_item(db,principal,ident,check_id)
    runs=db.scalars(select(ReleaseAudit).where(ReleaseAudit.subject_id==ident,ReleaseAudit.action=='agent.counterexample_completed',
        ReleaseAudit.tenant_id==principal.tenant_id)).all()
    run=next((r.payload['result'] for r in runs if r.payload['result']['check_id']==check.id),None)
    if not run:raise HTTPException(404,'No linked observed candidate')
    comments=db.scalars(select(ReleaseAudit).where(ReleaseAudit.subject_id==check_id,
        ReleaseAudit.tenant_id==principal.tenant_id,ReleaseAudit.action=='agent.review_comment').order_by(ReleaseAudit.created_at).limit(100)).all()
    from ownstack.customer_models import CustomerAudit,CustomerRequestLink
    customer_link=db.get(CustomerRequestLink,state['request_id'])
    # Restore delivery status from the receipt for this exact customer, check
    # and evidence. A receipt for an earlier patch must not hide a new action.
    shared=bool(customer_link and db.scalar(select(CustomerAudit.id).where(
        CustomerAudit.tenant_id==principal.tenant_id,
        CustomerAudit.customer_id==customer_link.customer_id,
        CustomerAudit.action=='customer.review_shared',
        CustomerAudit.payload['submission_id'].as_string()==customer_link.submission_id,
        CustomerAudit.payload['check_id'].as_string()==check.id,
        CustomerAudit.payload['evidence_hash'].as_string()==check.evidence_hash).limit(1)))
    return {'check_id':check.id,'revision':check.revision,'evidence_hash':check.evidence_hash,'state':check.state,
        'customer_submission_id':customer_link.submission_id if customer_link else None,
        'customer_review_shared':shared,
        'decision':check.decision,'source_diff':run.get('source_diff',''),'candidate_sha256':check.candidate_sha256,
        'comments':[{'actor':r.payload['actor'],'comment':r.payload['comment']} for r in comments],'released':False}

@router.post('/{ident}/checks/{check_id}/review')
def save_review(ident:str,check_id:str,body:Review,principal=Depends(current_principal),db=Depends(db_session)):
    state,check,project=review_item(db,principal,ident,check_id,True)
    intent=digest({**body.model_dump(exclude={'idempotency_key'}),'actor':principal.user_id})
    receipts=db.scalars(select(ReleaseAudit).where(ReleaseAudit.subject_id==check_id,
        ReleaseAudit.tenant_id==principal.tenant_id,ReleaseAudit.action=='agent.review_saved')).all()
    old=next((r.payload for r in receipts if r.payload['key']==body.idempotency_key and r.payload['actor']==principal.user_id),None)
    if old:
        if old['intent']!=intent:raise HTTPException(409,'Review key belongs to different inputs')
        return old['result']
    if check.revision!=body.expected_revision or not check.evidence_hash or check.evidence_hash!=body.evidence_hash:
        raise HTTPException(409,'Checked evidence changed. Refresh before reviewing.')
    if len(body.comment.strip())<2:raise HTTPException(422,'Write a review comment')
    if len(receipts)>=100:raise HTTPException(409,'Review history limit reached')
    if body.decision!='comment':
        from ownstack.release_assurance import decide_check_in_transaction,Decide
        decide_check_in_transaction(check_id,Decide(expected_revision=body.expected_revision,evidence_hash=body.evidence_hash,decision=body.decision),principal,db)
    audit(db,project,check_id,'agent.review_comment',actor=principal.user_id,comment=body.comment.strip(),session_id=ident)
    result={'submitted':True,'decision':check.decision,'check_id':check.id,'released':False}
    audit(db,project,check_id,'agent.review_saved',key=body.idempotency_key,intent=intent,actor=principal.user_id,result=result)
    db.commit();return result
