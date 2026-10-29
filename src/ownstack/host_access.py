"""Read-time candidate selection, not an authorization cache.

SQL narrows the candidates; the shared pure policy remains the final decision.
Keep these predicates and policy parity tests together when adding contracts.
"""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from ownstack.models import Variation
from ownstack.governance import authorized_variation
from ownstack.authorization_clock import authorization_time
from ownstack.policy import Principal, ReadDecision, aware, read_decision


def candidate_query(principal: Principal, project_id: str, at: datetime):
    return select(Variation).where(
        Variation.tenant_id == principal.tenant_id,
        Variation.project_id == project_id,
        Variation.viewer_id == principal.user_id,
        Variation.state == "active",
        Variation.starts_at <= aware(at),
        Variation.expires_at > aware(at),
        authorized_variation(),
    ).order_by(Variation.id).limit(1)


def host_read_decision(db: Session, principal: Principal, project_tenant: str,
                       project_id: str, at: datetime) -> ReadDecision:
    at=authorization_time(db,at)
    role_scope=True
    if principal.tenant_id==project_tenant and principal.role in {'admin','engineer','member','manager'}:
        from ownstack.team_scope import project_visible
        from ownstack.models import Project
        if db.scalar(select(Project.id).where(Project.id==project_id,project_visible(principal))) is None:
            role_scope=False
    # Non-contractors need no grant lookup. The policy still checks tenant first.
    candidates = []
    if principal.tenant_id == project_tenant and principal.role == "contractor":
        candidates = db.scalars(candidate_query(principal, project_id, at)).all()
    return read_decision(principal, project_tenant, project_id, candidates, at,role_scope=role_scope)
