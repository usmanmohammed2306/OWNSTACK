"""Current database membership, never browser filters or signed team claims.

Team ownership belongs to the saved request, not its author's current assignment.
No tenant-wide administrator bypass exists for request/code contents.
"""
from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select
from ownstack.models import ChangeRequest, Project, Team, TeamMembership, User, Event


def team_ids(principal):
    statement=select(TeamMembership.team_id).join(Team,
        (Team.id==TeamMembership.team_id)&(Team.tenant_id==TeamMembership.tenant_id)).where(
        TeamMembership.tenant_id==principal.tenant_id,TeamMembership.user_id==principal.user_id,
        TeamMembership.enabled.is_(True),TeamMembership.role.in_(['member','manager']),Team.enabled.is_(True))
    if principal.role=='manager':statement=statement.where(TeamMembership.role=='manager')
    return statement.correlate(None)


def project_visible(principal):
    return and_(Project.tenant_id==principal.tenant_id,Project.team_id.in_(team_ids(principal)))


def metadata_projects(db,principal):
    if principal.role!='contractor':return project_visible(principal)
    from datetime import datetime,timezone
    from ownstack.models import Variation
    from ownstack.governance import authorized_variation
    from ownstack.authorization_clock import authorization_time
    at=authorization_time(db,datetime.now(timezone.utc))
    grants=select(Variation.project_id).where(Variation.tenant_id==principal.tenant_id,
        Variation.viewer_id==principal.user_id,Variation.state=='active',Variation.starts_at<=at,
        Variation.expires_at>at,authorized_variation()).correlate(None)
    return and_(Project.tenant_id==principal.tenant_id,or_(Project.team_id.in_(team_ids(principal)),Project.id.in_(grants)))


def request_visible(principal):
    # A malformed cross-tenant/project/team association is not readable even if
    # one of its identifiers happens to match the actor's team.
    return and_(ChangeRequest.tenant_id==principal.tenant_id,
        ChangeRequest.team_id.in_(team_ids(principal)),
        or_(ChangeRequest.project_id.is_(None),exists(select(Project.id).where(
            Project.id==ChangeRequest.project_id,Project.tenant_id==ChangeRequest.tenant_id,
            Project.team_id==ChangeRequest.team_id).correlate(ChangeRequest))))


def require_team(db,principal,team_id,*,write=False):
    if write:
        user=db.scalar(select(User).where(User.id==principal.user_id,User.tenant_id==principal.tenant_id).with_for_update(read=True).execution_options(populate_existing=True))
        if user is None or not user.enabled or user.role!=principal.role:raise HTTPException(401,'Identity changed')
    query=select(TeamMembership).join(Team,
        (Team.id==TeamMembership.team_id)&(Team.tenant_id==TeamMembership.tenant_id)).where(
        TeamMembership.team_id==team_id,TeamMembership.tenant_id==principal.tenant_id,
        TeamMembership.user_id==principal.user_id,TeamMembership.enabled.is_(True),TeamMembership.role.in_(['member','manager']),Team.enabled.is_(True))
    if principal.role=='manager':query=query.where(TeamMembership.role=='manager')
    # Mutations serialize with membership revocation on PostgreSQL. SQLite's
    # writer serialization is separate; neither a session nor UI caches authority.
    if write:query=query.with_for_update(of=TeamMembership)
    if db.scalar(query) is None:raise HTTPException(404,'Not found')


def require_project(db,principal,project_id,*,write=False):
    project=db.scalar(select(Project).where(Project.id==project_id,project_visible(principal)))
    if project is None:raise HTTPException(404,'Not found')
    require_team(db,principal,project.team_id,write=write)
    return project


def require_request(db,principal,request_id,*,write=False):
    request=db.scalar(select(ChangeRequest).where(ChangeRequest.id==request_id,request_visible(principal)))
    if request is None:raise HTTPException(404,'Not found')
    require_team(db,principal,request.team_id,write=write)
    return request


def visible_condition(model,principal):
    """SQL predicates for lists/reports, before private text or patches load."""
    requests=select(ChangeRequest.id).where(request_visible(principal)).correlate(None)
    projects=select(Project.id).where(project_visible(principal)).correlate(None)
    if model is ChangeRequest:return request_visible(principal)
    if model is Project:return project_visible(principal)
    if hasattr(model,'request_id'):return and_(model.tenant_id==principal.tenant_id,model.request_id.in_(requests))
    if hasattr(model,'project_id'):return and_(model.tenant_id==principal.tenant_id,model.project_id.in_(projects))
    if model.__name__=='Outbox':return model.event_id.in_(select(Event.id).where(Event.request_id.in_(requests),Event.tenant_id==principal.tenant_id))
    if model.__name__=='DeliveryReceipt':
        from ownstack.models import Outbox
        return model.event_id.in_(select(Outbox.event_id).where(visible_condition(Outbox,principal)))
    if model is User and principal.role!='admin':
        return and_(User.tenant_id==principal.tenant_id,User.id.in_(select(TeamMembership.user_id).where(
            TeamMembership.team_id.in_(team_ids(principal)),TeamMembership.tenant_id==principal.tenant_id,TeamMembership.enabled.is_(True))))
    return model.tenant_id==principal.tenant_id


def guard_object(db,principal,obj,*,write=False):
    if isinstance(obj,ChangeRequest):require_request(db,principal,obj.id,write=write)
    elif isinstance(obj,Project):
        # Contractors receive no role-based read. Their exact grant is checked
        # by the host immediately after lookup, including cross-team grants.
        if principal.role!='contractor':require_project(db,principal,obj.id,write=write)
    elif hasattr(obj,'request_id'):require_request(db,principal,obj.request_id,write=write)
    elif hasattr(obj,'project_id'):require_project(db,principal,obj.project_id,write=write)


def created_response(db,principal,response):
    request=require_request(db,principal,response['id'])
    if request.requester_id!=principal.user_id:raise HTTPException(409,'Idempotency key is already in use')
    return response


def ensure_general_team(db,tenant_id):
    from ownstack.team_identity import general_team_id
    key=general_team_id(tenant_id)
    if db.get(Team,key) is None:
        db.add(Team(id=key,tenant_id=tenant_id,name='General',name_key='general'));db.flush()
    return key


def add_general_member(db,user):
    from uuid import uuid4
    key=ensure_general_team(db,user.tenant_id)
    if db.scalar(select(TeamMembership.id).where(TeamMembership.team_id==key,TeamMembership.user_id==user.id)) is None:
        db.add(TeamMembership(id=str(uuid4()),tenant_id=user.tenant_id,team_id=key,user_id=user.id,
            role='manager' if user.role in {'admin','manager'} else 'member'))
