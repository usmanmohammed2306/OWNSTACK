"""Tenant-scoped directory and reporting lines. Titles never alter host policy."""
from datetime import datetime,timezone
from collections import Counter,defaultdict
from uuid import uuid4
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,ConfigDict,Field,field_validator
from sqlalchemy import func,or_,select,update
from ownstack.auth import current_principal,db_session,require_role
from ownstack.models import Tenant,User,Team,TeamMembership,Project,Variation
from ownstack.workspace_models import OrganizationProfile,OrganizationChange
from ownstack.team_scope import team_ids,visible_condition
from ownstack.policy import Principal,read_decision,aware
from ownstack.governance import authorized_variation
from ownstack.authorization_clock import authorization_time

router=APIRouter(prefix='/v1/organization',tags=['organization'])


def people_scope(principal):
    if principal.role in {'admin','engineer','manager','member'}:return visible_condition(User,principal)
    return (User.tenant_id==principal.tenant_id)&(User.id==principal.user_id)


def directory_data(db,principal):
    users=db.scalars(select(User).where(people_scope(principal)).order_by(User.id)).all()
    ids={u.id for u in users}
    profiles={p.user_id:p for p in db.scalars(select(OrganizationProfile).where(OrganizationProfile.tenant_id==principal.tenant_id,OrganizationProfile.user_id.in_(ids))).all()}
    memberships=db.scalars(select(TeamMembership).join(Team,Team.id==TeamMembership.team_id).where(
        TeamMembership.tenant_id==principal.tenant_id,TeamMembership.user_id.in_(ids),TeamMembership.enabled.is_(True),Team.enabled.is_(True))).all()
    teams=db.scalars(select(Team).where(Team.tenant_id==principal.tenant_id,Team.enabled.is_(True),
        True if principal.role=='admin' else Team.id.in_(team_ids(principal)))).all()
    team_map={t.id:t.name for t in teams}
    reporting=Counter(p.manager_id for p in profiles.values() if p.manager_id)
    by_user=defaultdict(list)
    for m in memberships:
        if m.team_id in team_map:by_user[m.user_id].append({'id':m.team_id,'name':team_map[m.team_id],'role':m.role})
    result=[]
    for u in users:
        p=profiles.get(u.id);manager=p.manager_id if p else None
        result.append({'id':u.id,'name':u.display_name or u.id,'title':p.title if p else 'Employee',
            'manager_id':manager if manager in ids else None,'manager_outside_scope':bool(manager and manager not in ids),
            'revision':p.revision if p else 0,'enabled':u.enabled,
            'teams':by_user[u.id],'reports':reporting[u.id]})
    return result,teams


@router.get('')
def directory(q:str=Query('',max_length=100),team_id:str|None=None,reports_to:str|None=None,roots:bool=False,
    page:int=Query(0,ge=0,le=10000),principal:Principal=Depends(current_principal),db=Depends(db_session)):
    rows,teams=directory_data(db,principal);total=len(rows)
    if team_id:
        if team_id not in {t.id for t in teams}:raise HTTPException(404,'Not found')
        rows=[r for r in rows if any(t['id']==team_id for t in r['teams'])]
    if reports_to:
        if reports_to not in {r['id'] for r in rows}:raise HTTPException(404,'Not found')
        rows=[r for r in rows if r['manager_id']==reports_to]
    elif roots:rows=[r for r in rows if not r['manager_id']]
    if q.strip():
        terms=q.casefold().split();rows=[r for r in rows if all(t in (' '.join([r['name'],r['title'],*(g['name'] for g in r['teams'])])).casefold() for t in terms)]
    rows.sort(key=lambda r:(r['name'].casefold(),r['id']))
    return {'people':rows[page*40:(page+1)*40],'count':len(rows),'total':total,'page':page,'page_size':40,
        'teams':[{'id':t.id,'name':t.name} for t in sorted(teams,key=lambda t:t.name.casefold())],
        'can_edit':principal.role=='admin','scope':'Reporting titles do not confer permissions.'}


class ProfileBody(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    title:str=Field(min_length=2,max_length=80)
    manager_id:str|None=Field(default=None,max_length=40)
    expected_revision:int=Field(ge=0)

    @field_validator('title')
    @classmethod
    def title_text(cls,value):
        if len(value.strip())<2 or any(ord(c)<32 for c in value):raise ValueError('Plain job title required')
        return value.strip()


@router.put('/people/{user_id}')
def profile(user_id:str,body:ProfileBody,principal:Principal=Depends(current_principal),db=Depends(db_session)):
    require_role(principal,'admin')
    # One tenant-level lock serializes graph changes, preventing simultaneous
    # A -> B and B -> A edits from each observing an acyclic old graph.
    db.execute(update(Tenant).where(Tenant.id==principal.tenant_id).values(name=Tenant.name))
    actor=db.scalar(select(User).where(User.id==principal.user_id).with_for_update(read=True).execution_options(populate_existing=True))
    if not actor or not actor.enabled or actor.role!='admin':raise HTTPException(403,'Administrator required')
    subject=db.scalar(select(User).where(User.id==user_id,User.tenant_id==principal.tenant_id))
    if not subject:raise HTTPException(404,'Not found')
    if body.manager_id and not db.scalar(select(User.id).where(User.id==body.manager_id,User.tenant_id==principal.tenant_id,User.enabled.is_(True))):raise HTTPException(404,'Manager not found')
    graph={p.user_id:p.manager_id for p in db.scalars(select(OrganizationProfile).where(OrganizationProfile.tenant_id==principal.tenant_id)).all()}
    current=body.manager_id;seen={user_id}
    while current:
        if current in seen:raise HTTPException(422,'Reporting lines cannot contain a cycle')
        seen.add(current);current=graph.get(current)
    row=db.get(OrganizationProfile,user_id)
    if (row.revision if row else 0)!=body.expected_revision:raise HTTPException(409,'Reporting line changed. Refresh before saving.')
    before={'title':row.title,'manager_id':row.manager_id,'revision':row.revision} if row else None
    if row:row.title=body.title;row.manager_id=body.manager_id;row.revision+=1;row.updated_by=principal.user_id;row.updated_at=datetime.now(timezone.utc)
    else:row=OrganizationProfile(user_id=user_id,tenant_id=principal.tenant_id,title=body.title,manager_id=body.manager_id,revision=1,updated_by=principal.user_id);db.add(row)
    db.add(OrganizationChange(id=str(uuid4()),tenant_id=principal.tenant_id,actor_id=principal.user_id,subject_id=user_id,
        payload={'before':before,'after':{'title':body.title,'manager_id':body.manager_id,'revision':row.revision}}))
    db.commit();return {'id':user_id,'title':row.title,'manager_id':row.manager_id,'revision':row.revision}


@router.get('/people/{user_id}/access')
def access(user_id:str,principal:Principal=Depends(current_principal),db=Depends(db_session)):
    user=db.scalar(select(User).where(User.id==user_id,people_scope(principal)))
    if not user:raise HTTPException(404,'Not found')
    # Access metadata is not a document read or permission to see code reviews.
    from ownstack.team_scope import metadata_projects
    projects=db.scalars(select(Project).where(Project.tenant_id==principal.tenant_id,
        True if principal.role=='admin' else metadata_projects(db,principal))).all()
    at=authorization_time(db,datetime.now(timezone.utc))
    grants=db.scalars(select(Variation).where(Variation.tenant_id==principal.tenant_id,Variation.viewer_id==user_id,
        Variation.state=='active',Variation.starts_at<=at,Variation.expires_at>at,authorized_variation()).order_by(Variation.id)).all()
    from ownstack.team_scope import project_visible
    scoped_projects=set(db.scalars(select(Project.id).where(project_visible(principal))).all())
    memberships=db.scalars(select(TeamMembership).join(Team,Team.id==TeamMembership.team_id).where(
        TeamMembership.user_id==user_id,TeamMembership.tenant_id==principal.tenant_id,TeamMembership.enabled.is_(True),Team.enabled.is_(True))).all()
    result=[]
    for p in sorted(projects,key=lambda p:p.name):
        scope=any(m.team_id==p.team_id and (user.role!='manager' or m.role=='manager') for m in memberships)
        d=read_decision(Principal(user.id,user.tenant_id,user.role),p.tenant_id,p.id,grants,at,role_scope=scope)
        matching=next((v for v in grants if v.id==d.variation_id),None)
        result.append({'project_id':p.id,'project':p.name,'allowed':bool(user.enabled and d.allowed),
            'basis':d.basis if user.enabled else 'account_disabled','variation_id':d.variation_id,
            'expires_at':aware(matching.expires_at).isoformat() if matching else None,
            'can_request':p.id in scoped_projects and principal.role in {'admin','engineer','member'},
            'can_manage':p.id in scoped_projects and principal.role=='admin',
            'grants':[{'id':v.id,'expires_at':aware(v.expires_at).isoformat()} for v in grants if v.project_id==p.id]})
    return {'user_id':user.id,'rules':result,'as_of':at.isoformat(),'preview_only':True}
