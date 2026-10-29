"""Durable, actor-scoped state for local trained-model interactions.

No provider dispatch. A generation ticket can save only its own current result.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from ownstack.action_plans import validate_command_plan
from ownstack.auth import rate_limit
from ownstack.models import PlannerRun, PlannerEvent, User
from ownstack.policy import aware, digest

MAX_GENERATIONS=3

def now():return datetime.now(timezone.utc)

def scoped_run(db,principal,run_id):
    row=db.scalar(select(PlannerRun).where(PlannerRun.id==run_id,
        PlannerRun.tenant_id==principal.tenant_id,PlannerRun.actor_id==principal.user_id))
    if row is None:raise HTTPException(404,'Not found')
    return row

def same_identity(db,row):
    person=db.get(User,row.actor_id)
    return bool(person and person.enabled and person.tenant_id==row.tenant_id
        and person.role==row.role and person.token_version==row.identity_version)

def snapshot(db,row):
    """GET may reap a deadline, but never launches generation."""
    db.refresh(row)
    if row.status=='running' and aware(row.deadline_at)<=now():
        finish(db,row.id,row.generation,'timed_out',error='DEADLINE',allow_expired=True);db.refresh(row)
    value={'id':row.id,'status':row.status,'generation':row.generation,
        'created_at':aware(row.created_at).isoformat(),'deadline_at':aware(row.deadline_at).isoformat(),
        'error_code':row.error_code,'remote_cancellation_verified':False,'effect':'preview_only','provider_calls':0}
    value['attempts']=[{'generation':e.generation,'status':e.status,'error_code':e.error_code,
        'finished_at':aware(e.finished_at).isoformat()} for e in db.scalars(select(PlannerEvent)
            .where(PlannerEvent.run_id==row.id).order_by(PlannerEvent.generation)).all()]
    if not same_identity(db,row):return {**value,'status':'identity_changed','error_code':'IDENTITY_CHANGED'}
    if row.status=='accepted' and row.result:
        import json
        try:validate_command_plan(json.dumps(row.result['plan']),row.role,row.command_text)
        except (ValueError,KeyError,TypeError):return {**value,'status':'invalidated','error_code':'POLICY_CHANGED'}
        value.update(row.result)
    return value

def start(db,principal,text,key):
    if not key or len(key)>100 or any(ord(c)<33 or ord(c)>126 for c in key):
        raise HTTPException(422,'Use a nonempty command key of at most 100 ASCII characters')
    text=text.strip()
    query=select(PlannerRun).where(PlannerRun.tenant_id==principal.tenant_id,
        PlannerRun.actor_id==principal.user_id,PlannerRun.idempotency_key==key)
    existing=db.scalar(query)
    if existing:
        if existing.command_hash!=digest(text):raise HTTPException(409,'That command key belongs to different text')
        return existing,False
    rate_limit(db,'trained-planner',principal.tenant_id+':'+principal.user_id,10,60)
    rate_limit(db,'trained-planner-day',principal.tenant_id+':'+principal.user_id,100,86400)
    person=db.get(User,principal.user_id)
    if not person or not person.enabled or person.role!=principal.role:raise HTTPException(401,'Identity changed')
    at=now()
    row=PlannerRun(id=str(uuid4()),tenant_id=principal.tenant_id,actor_id=principal.user_id,
        idempotency_key=key,command_hash=digest(text),command_text=text,role=principal.role,
        identity_version=person.token_version,generation=1,status='running',deadline_at=at+timedelta(seconds=55),
        created_at=at,updated_at=at)
    db.add(row)
    try:db.commit()
    except IntegrityError:
        db.rollback();row=db.scalar(query)
        if row is None or row.command_hash!=digest(text):raise HTTPException(409,'Concurrent command conflict') from None
        return row,False
    return row,True

def finish(db,run_id,generation,status,*,result=None,error=None,allow_expired=False):
    at=now()
    filters=[PlannerRun.id==run_id,PlannerRun.generation==generation,PlannerRun.status=='running']
    if not allow_expired:filters.append(PlannerRun.deadline_at>at)
    changed=db.execute(update(PlannerRun).where(*filters).values(status=status,result=result,
        error_code=error,updated_at=at).execution_options(synchronize_session=False)).rowcount
    if changed==1:db.add(PlannerEvent(id=str(uuid4()),run_id=run_id,generation=generation,
        status=status,error_code=error,finished_at=at))
    db.commit();return changed==1

def retry(db,principal,row,generation):
    saved=snapshot(db,row)
    if generation!=row.generation:return row,False
    if not same_identity(db,row):raise HTTPException(409,'Identity changed; start a new command')
    if saved['status']=='running':return row,False
    if row.status not in {'failed','timed_out','cancelled'}:raise HTTPException(409,'This command cannot be retried')
    if row.generation>=MAX_GENERATIONS:raise HTTPException(409,'Retry limit reached; inspect the error or start a new command')
    rate_limit(db,'trained-planner',principal.tenant_id+':'+principal.user_id,10,60)
    changed=db.execute(update(PlannerRun).where(PlannerRun.id==row.id,
        PlannerRun.generation==generation,PlannerRun.status.in_(['failed','timed_out','cancelled']))
        .values(generation=generation+1,status='running',result=None,error_code=None,
            deadline_at=now()+timedelta(seconds=55),updated_at=now())
        .execution_options(synchronize_session=False)).rowcount
    db.commit();db.refresh(row);return row,changed==1
