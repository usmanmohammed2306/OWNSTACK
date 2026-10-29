"""Read-only organizational membership and policy preview for the spatial map.

Persisted teams form the hierarchy. Multi-team people have one identity node.
Previewing another person's policy never records a protected read or grants access.
"""
from datetime import datetime,timezone
from fastapi import APIRouter,Depends
from sqlalchemy import func,select
from sqlalchemy.orm import Session
from ownstack.auth import current_principal,db_session,require_role
from ownstack.models import Project,User,Variation,Team,TeamMembership
from ownstack.policy import Principal,read_decision
from ownstack.governance import authorized_variation
from ownstack.authorization_clock import authorization_time
from ownstack.team_scope import project_visible,team_ids

router=APIRouter(prefix='/v1/workspace-map')

@router.get('')
def workspace_map(principal:Principal=Depends(current_principal),db:Session=Depends(db_session)):
    require_role(principal,'admin','engineer','manager')
    team_query=select(Team).where(Team.tenant_id==principal.tenant_id,Team.enabled.is_(True)).order_by(Team.name_key,Team.id)
    if principal.role!='admin':team_query=team_query.where(Team.id.in_(team_ids(principal)))
    teams=db.scalars(team_query.limit(51)).all();truncated=len(teams)>50;teams=teams[:50]
    team_keys=[t.id for t in teams]
    query=select(User).where(User.tenant_id==principal.tenant_id).order_by(User.role,User.id)
    query=query.where(User.id.in_(select(TeamMembership.user_id).where(TeamMembership.tenant_id==principal.tenant_id,
        TeamMembership.team_id.in_(team_keys),TeamMembership.enabled.is_(True))))
    people=db.scalars(query.limit(51)).all();truncated|=len(people)>50;people=people[:50]
    projects=db.scalars(select(Project).where(project_visible(principal)).order_by(Project.id).limit(11)).all()
    truncated|=len(projects)>10;projects=projects[:10];at=authorization_time(db,datetime.now(timezone.utc))
    # At most one candidate per visible person/project pair, matching the host's
    # first-valid-candidate selection, without an N+1 query for every connection.
    ids=select(func.min(Variation.id)).where(Variation.tenant_id==principal.tenant_id,
        Variation.viewer_id.in_([u.id for u in people]),Variation.project_id.in_([p.id for p in projects]),
        Variation.state=='active',Variation.starts_at<=at,Variation.expires_at>at,authorized_variation()).group_by(Variation.viewer_id,Variation.project_id)
    grants=db.scalars(select(Variation).where(Variation.id.in_(ids))).all()
    memberships=db.scalars(select(TeamMembership).join(Team,
        (Team.id==TeamMembership.team_id)&(Team.tenant_id==TeamMembership.tenant_id)).where(
        TeamMembership.tenant_id==principal.tenant_id,TeamMembership.enabled.is_(True),Team.enabled.is_(True),
        TeamMembership.user_id.in_([u.id for u in people]),TeamMembership.role.in_(['member','manager']))).all()
    nodes=[]
    for team in teams:
        count=len({m.user_id for m in memberships if m.team_id==team.id})
        nodes.append({'id':'team:'+team.id,'station':'demo','title':team.name,
            'description':'Team review scope','status':str(count)+' people shown','kind':'team','parent':'organization','details':[]})
    for user in people:
        access=[]
        for project in projects:
            scope=any(m.user_id==user.id and m.team_id==project.team_id and (user.role!='manager' or m.role=='manager') for m in memberships)
            decision=read_decision(Principal(user.id,user.tenant_id,user.role),project.tenant_id,project.id,grants,at,role_scope=scope)
            access.append({'project':project.name,'allowed':bool(user.enabled and decision.allowed),
                'basis':decision.basis if user.enabled else 'account_disabled'})
        nodes.append({'id':'person:'+user.id,'station':'demo','title':user.display_name or user.id,
            'description':user.role.replace('_',' '),'status':'enabled' if user.enabled else 'disabled',
            'kind':'person','parents':['team:'+m.team_id for m in memberships if m.user_id==user.id and m.team_id in team_keys],
            'related':['team:'+m.team_id for m in memberships if m.user_id==user.id and m.team_id in team_keys],'details':access})
    return {'nodes':nodes,'as_of':at.isoformat(),'truncated':truncated,
        'scope':'Assigned team members and current policy preview. Not observed reads or an individual reporting chart.'}
