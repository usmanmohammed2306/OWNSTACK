"""Explicit team administration; read grants never confer release authority."""
import unicodedata
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field,field_validator
from sqlalchemy import func,select,update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ownstack.auth import current_principal,db_session,require_role
from ownstack.models import Project,Team,TeamAudit,TeamMembership,User,Tenant
from ownstack.policy import Principal,aware
from ownstack.team_scope import require_team,team_ids

router=APIRouter(prefix='/v1/teams',tags=['team authority'])


class TeamBody(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    name:str=Field(min_length=2,max_length=80)

    @field_validator('name')
    @classmethod
    def clean(cls,value):
        value=' '.join(unicodedata.normalize('NFKC',value).split())
        if not 2<=len(value)<=80 or any(unicodedata.category(c).startswith('C') for c in value):
            raise ValueError('Use a team name without control characters')
        return value


class MembershipBody(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    role:Literal['member','manager']='member'
    enabled:bool=True
    expected_revision:int=Field(ge=0)


def scoped_team(db,principal,team_id):
    row=db.scalar(select(Team).where(Team.id==team_id,Team.tenant_id==principal.tenant_id,Team.enabled.is_(True)))
    if row is None:raise HTTPException(404,'Not found')
    return row


def membership(row):
    return {'user_id':row.user_id,'team_id':row.team_id,'role':row.role,'enabled':row.enabled,'revision':row.revision}


@router.get('')
def teams(principal:Principal=Depends(current_principal),db:Session=Depends(db_session)):
    require_role(principal,'admin','engineer','member','manager')
    query=select(Team).where(Team.tenant_id==principal.tenant_id,Team.enabled.is_(True))
    if principal.role!='admin':query=query.where(Team.id.in_(team_ids(principal)))
    result=[]
    for team in db.scalars(query.order_by(Team.name_key,Team.id)).all():
        members=db.execute(select(TeamMembership,User).join(User,
            (User.id==TeamMembership.user_id)&(User.tenant_id==TeamMembership.tenant_id)).where(
            TeamMembership.team_id==team.id,TeamMembership.tenant_id==principal.tenant_id).order_by(User.id)).all()
        projects=db.scalars(select(Project).where(Project.team_id==team.id,Project.tenant_id==principal.tenant_id).order_by(Project.name,Project.id)).all()
        result.append({'id':team.id,'name':team.name,
            'members':[{**membership(row),'name':user.display_name or user.id,'account_role':user.role,'account_enabled':user.enabled} for row,user in members],
            'projects':[{'id':p.id,'name':p.name} for p in projects],
            'can_read_reviews':bool(db.scalar(select(TeamMembership.id).where(TeamMembership.team_id==team.id,
                TeamMembership.user_id==principal.user_id,TeamMembership.tenant_id==principal.tenant_id,TeamMembership.enabled.is_(True),
                TeamMembership.role=='manager' if principal.role=='manager' else TeamMembership.role.in_(['member','manager']))))})
    return result


@router.post('',status_code=201)
def create(body:TeamBody,principal:Principal=Depends(current_principal),db:Session=Depends(db_session)):
    require_role(principal,'admin')
    db.scalar(select(Tenant).where(Tenant.id==principal.tenant_id).with_for_update(key_share=True))
    if db.scalar(select(func.count(Team.id)).where(Team.tenant_id==principal.tenant_id))>=50:
        raise HTTPException(409,'This workspace has reached its 50-team limit')
    team=Team(id=str(uuid4()),tenant_id=principal.tenant_id,name=body.name,name_key=body.name.casefold())
    try:
        db.add(team);db.flush()
        project=Project(id=str(uuid4()),tenant_id=principal.tenant_id,team_id=team.id,name=body.name,revision=1)
        db.add(project)
        db.add(TeamAudit(id=str(uuid4()),tenant_id=principal.tenant_id,actor_id=principal.user_id,
            team_id=team.id,subject_id=None,action='team_created',payload={'name':team.name,'project_id':project.id}))
        db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'This team name is already in use') from None
    # Creating structure does not silently enroll its administrator in reviews.
    return {'id':team.id,'name':team.name,'project_id':project.id}


@router.put('/{team_id}/members/{user_id}')
def assign(team_id:str,user_id:str,body:MembershipBody,
    principal:Principal=Depends(current_principal),db:Session=Depends(db_session)):
    require_role(principal,'admin');scoped_team(db,principal,team_id)
    user=db.scalar(select(User).where(User.id==user_id,User.tenant_id==principal.tenant_id).with_for_update(read=True))
    if user is None:raise HTTPException(404,'Not found')
    if user.role=='product_owner':raise HTTPException(422,'Platform product accounts cannot join customer teams')
    row=db.scalar(select(TeamMembership).where(TeamMembership.team_id==team_id,
        TeamMembership.user_id==user_id,TeamMembership.tenant_id==principal.tenant_id).with_for_update())
    before=membership(row) if row else None
    if row:
        changed=db.execute(update(TeamMembership).where(TeamMembership.id==row.id,
            TeamMembership.revision==body.expected_revision).values(role=body.role,enabled=body.enabled,
                revision=TeamMembership.revision+1).execution_options(synchronize_session=False))
        if changed.rowcount!=1:raise HTTPException(409,'Team membership changed. Refresh before editing.')
        db.refresh(row)
    else:
        if body.expected_revision!=0:raise HTTPException(409,'Team membership changed. Refresh before editing.')
        row=TeamMembership(id=str(uuid4()),tenant_id=principal.tenant_id,team_id=team_id,user_id=user_id,
            role=body.role,enabled=body.enabled,revision=1)
        db.add(row)
    db.add(TeamAudit(id=str(uuid4()),tenant_id=principal.tenant_id,actor_id=principal.user_id,
        team_id=team_id,subject_id=user_id,action='membership_changed',payload={'before':before,'after':membership(row)}))
    try:db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'Team membership changed. Refresh before editing.') from None
    return membership(row)


@router.get('/{team_id}/audit')
def audit(team_id:str,principal:Principal=Depends(current_principal),db:Session=Depends(db_session)):
    require_role(principal,'admin','engineer','manager');scoped_team(db,principal,team_id)
    if principal.role!='admin':require_team(db,principal,team_id)
    rows=db.scalars(select(TeamAudit).where(TeamAudit.team_id==team_id,TeamAudit.tenant_id==principal.tenant_id)
        .order_by(TeamAudit.created_at.desc(),TeamAudit.id).limit(100)).all()
    return [{'id':r.id,'actor_id':r.actor_id,'subject_id':r.subject_id,'action':r.action,'change':r.payload,
        'created_at':aware(r.created_at).isoformat()} for r in rows]
