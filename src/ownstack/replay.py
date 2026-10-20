"""Counterfactual host-policy replay over the owned two-tenant fixture."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from sqlalchemy import select
from sqlalchemy.orm import Session
from ownstack.models import Project, User, Variation
from ownstack.policy import Principal, can_read


def replay_grant(db: Session, tenant_id: str, project_id: str, viewer_id: str,
                 expires_at: datetime, at: datetime) -> dict:
    """Compare the same host decision function before and after one candidate.

    Every seeded principal and project is checked at activation and after expiry.
    This is finite fixture coverage, not exhaustive proof of security.
    """
    users = db.scalars(select(User).order_by(User.id)).all()
    projects = db.scalars(select(Project).order_by(Project.id)).all()
    variations = db.scalars(select(Variation).where(Variation.state == "active")).all()
    candidate = SimpleNamespace(tenant_id=tenant_id, project_id=project_id, viewer_id=viewer_id,
                                state="active", starts_at=at, expires_at=expires_at)
    expected = (viewer_id, project_id, "activation")
    deltas = []
    unexpected = []
    checked = 0
    for moment, when in (("activation", at), ("post_expiry", expires_at + timedelta(seconds=1))):
        for user in users:
            principal = Principal(user.id, user.tenant_id, user.role)
            for project in projects:
                before = can_read(principal, project.tenant_id, project.id, variations, when)
                after = can_read(principal, project.tenant_id, project.id, [*variations, candidate], when)
                checked += 1
                if before != after:
                    item = (user.id, project.id, moment, before, after)
                    deltas.append(item)
                    if (user.id, project.id, moment) != expected or before or not after:
                        unexpected.append(item)
    target = next((item for item in deltas if item[:3] == expected), None)
    return {"checks": checked, "intended_delta_observed": target is not None,
            "unexpected_delta_count": len(unexpected), "deltas": deltas,
            "method": "same_host_policy_before_after_at_activation_and_expiry"}
