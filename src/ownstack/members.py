"""Tenant admin offboarding and explicit session revocation."""
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from ownstack.auth import current_principal, db_session, require_role
from ownstack.models import IdentityEvent, User, WebSession
from ownstack.policy import Principal, aware
from ownstack.service import scoped

router = APIRouter(prefix="/v1/members")


class AccessBody(BaseModel):
    enabled: bool


@router.get("")
def members(principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin")
    return [{"id": u.id, "role": u.role, "enabled": u.enabled} for u in
            db.scalars(select(User).where(User.tenant_id == principal.tenant_id).order_by(User.id))]


@router.post("/{user_id}/access")
def member_access(user_id: str, body: AccessBody, principal: Principal = Depends(current_principal),
                  db: Session = Depends(db_session)):
    require_role(principal, "admin")
    user = scoped(db, User, user_id, principal.tenant_id)
    # Keep this slice narrow: no role escalation or administrator lockout.
    if user.role not in {"contractor", "engineer", "member"}:
        raise HTTPException(409, "Administrator and platform accounts require a separate owner workflow")
    user = db.scalar(select(User).where(User.id == user.id).with_for_update())
    if user.enabled != body.enabled:
        user.enabled = body.enabled
        user.token_version += 1
        db.execute(delete(WebSession).where(WebSession.user_id == user.id))
        db.add(IdentityEvent(id=str(uuid4()), tenant_id=principal.tenant_id, actor_id=principal.user_id,
                            subject_id=user.id, action="account_enabled" if body.enabled else "account_disabled"))
    db.commit()
    return {"id": user.id, "enabled": user.enabled}


@router.post("/me/revoke-sessions")
def revoke_all(principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    user = db.scalar(select(User).where(User.id == principal.user_id).with_for_update())
    user.token_version += 1
    revoked = db.execute(delete(WebSession).where(WebSession.user_id == user.id)).rowcount
    db.add(IdentityEvent(id=str(uuid4()), tenant_id=principal.tenant_id, actor_id=principal.user_id,
                        subject_id=user.id, action="sessions_revoked"))
    db.commit()
    return {"revoked_sessions": revoked, "sign_in_required": True}


@router.get("/audit")
def audit(principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin")
    return [{"id": e.id, "subject_id": e.subject_id, "actor_id": e.actor_id, "action": e.action,
             "created_at": aware(e.created_at).isoformat()} for e in db.scalars(select(IdentityEvent)
        .where(IdentityEvent.tenant_id == principal.tenant_id).order_by(IdentityEvent.created_at.desc()).limit(100))]
