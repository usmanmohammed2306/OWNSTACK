"""Customer onboarding. New-workspace authority and invitation authority never mix.

Accounts use usernames, not unverified email addresses. No email delivery or
email/password recovery is implied. Invitation secrets are shown once and hashed
at rest. The transaction owns account, workspace, invite consumption and audit.
"""
from datetime import datetime, timedelta, timezone
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ownstack.auth import (SESSION_COOKIE, check_password, cookie_name, create_session,
    current_principal, db_session, hash_secret, issue_token, password_hash, rate_limit,
    require_origin, require_role, revoke_session, session_payload)
from ownstack.config import Settings
from ownstack.identity_admin import validate_password
from ownstack.models import Document, IdentityEvent, Project, Tenant, User, WebSession, WorkspaceInvitation
from ownstack.policy import Principal, aware
from ownstack.team_scope import ensure_general_team,add_general_member
from ownstack.models import Team,TeamMembership,TeamAudit

router = APIRouter(prefix="/v1/accounts", tags=["customer accounts"])


class AccountBody(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    username: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,39}$")
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=16, max_length=128, repr=False)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError("Use a name without control characters")
        return value

    @field_validator("password")
    @classmethod
    def private_password(cls, value):
        validate_password(value)
        return value


class SignupBody(AccountBody):
    workspace: str = Field(min_length=2, max_length=80)

    @field_validator("workspace")
    @classmethod
    def workspace_name(cls, value):
        value = cls.clean_name(value)
        if len(value) < 2:
            raise ValueError("Use at least two characters for the workspace name")
        return value


class InvitationToken(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    token: str = Field(min_length=32, max_length=128, repr=False)


class JoinBody(AccountBody):
    token: str = Field(min_length=32, max_length=128, repr=False)


class InviteBody(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    role: str = Field(pattern="^(member|engineer|contractor|manager)$")
    team_id: str | None=Field(default=None,min_length=1,max_length=40)
    days: int = Field(default=2, ge=1, le=7)


class PasswordBody(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    current_password: str = Field(min_length=1, max_length=256, repr=False)
    password: str = Field(min_length=16, max_length=128, repr=False)

    @field_validator("password")
    @classmethod
    def private_password(cls, value):
        validate_password(value)
        return value


def now():
    return datetime.now(timezone.utc)


def team_name(db,team_id):
    row=db.get(Team,team_id)
    return row.name if row else None


def anonymous(request, db, settings):
    require_origin(request, settings)
    token = request.cookies.get(cookie_name(SESSION_COOKIE, settings))
    session = db.get(WebSession, hash_secret(token)) if token else None
    if session and aware(session.expires_at) > now():
        raise HTTPException(409, "Sign out before creating a different account")


def audit(db, user, action):
    db.add(IdentityEvent(id=str(uuid4()), tenant_id=user.tenant_id, actor_id=user.id,
                         subject_id=user.id, action=action))


def signed_in(db, user, request, response, settings):
    revoke_session(db, request, response)
    csrf = create_session(db, user, response, settings)
    db.flush()
    result = session_payload(db, user, csrf, settings)
    if settings.environment == "local":
        result["token"] = issue_token(user, settings.signing_secret)
    db.commit()
    return result


def invitation(db, token, lock=False):
    query = select(WorkspaceInvitation).where(WorkspaceInvitation.token_hash == hash_secret(token))
    row = db.scalar(query.with_for_update() if lock else query)
    issuer = db.get(User, row.issuer_id) if row else None
    team=db.get(Team,row.team_id) if row and row.team_id else None
    if (not row or not team or team.tenant_id!=row.tenant_id or not team.enabled or row.revoked or row.used_at is not None or aware(row.expires_at) <= now()
            or not issuer or not issuer.enabled or issuer.role != "admin" or issuer.tenant_id != row.tenant_id):
        raise HTTPException(404, "Invitation unavailable or expired")
    return row


@router.get("/config")
def configuration():
    return {"signup_enabled": Settings().public_signup, "account_identifier": "username"}


@router.post("/signup", status_code=201)
def signup(body: SignupBody, request: Request, response: Response, db: Session = Depends(db_session)):
    settings = Settings()
    anonymous(request, db, settings)
    if not settings.public_signup:
        raise HTTPException(403, "New workspace registration is closed. An administrator can invite you.")
    rate_limit(db, "signup-ip", request.client.host if request.client else "unknown", 5, 3600)
    rate_limit(db, "signup-total", "all", 30, 86400)
    try:
        tenant = Tenant(id=str(uuid4()), name=body.workspace, ai_enabled=False)
        db.add(tenant); db.flush()
        ensure_general_team(db,tenant.id)
        user = User(id=body.username, tenant_id=tenant.id, role="admin", display_name=body.name,
                    password_hash=password_hash(body.password))
        db.add(user); db.flush()
        add_general_member(db,user)
        project = Project(id=str(uuid4()), tenant_id=tenant.id, name=body.workspace, revision=1)
        db.add(project); db.flush()
        db.add(Document(id=str(uuid4()), tenant_id=tenant.id, project_id=project.id,
                        title="Welcome", body="Your private workspace is ready."))
        db.add(TeamAudit(id=str(uuid4()),tenant_id=tenant.id,team_id=project.team_id,actor_id=user.id,
            subject_id=user.id,action='workspace_initialized',payload={'role':'manager'}))
        audit(db, user, "workspace_created")
        return signed_in(db, user, request, response, settings)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This account could not be created. Choose another username or sign in.") from None


@router.post("/invitations/inspect")
def inspect(body: InvitationToken, request: Request, db: Session = Depends(db_session)):
    require_origin(request, Settings())
    rate_limit(db, "invite-inspect", request.client.host if request.client else "unknown", 30, 3600)
    row = invitation(db, body.token)
    return {"workspace": db.get(Tenant, row.tenant_id).name,"team":team_name(db,row.team_id), "role": row.role, "expires_at": row.expires_at}


@router.post("/join", status_code=201)
def join(body: JoinBody, request: Request, response: Response, db: Session = Depends(db_session)):
    settings = Settings(); anonymous(request, db, settings)
    rate_limit(db, "invite-join", request.client.host if request.client else "unknown", 10, 3600)
    try:
        row = invitation(db, body.token, lock=True)
        user = User(id=body.username, tenant_id=row.tenant_id, role=row.role, display_name=body.name,
                    password_hash=password_hash(body.password))
        db.add(user); db.flush()
        db.add(TeamMembership(id=str(uuid4()),tenant_id=row.tenant_id,team_id=row.team_id,user_id=user.id,
            role='manager' if row.role=='manager' else 'member'))
        db.add(TeamAudit(id=str(uuid4()),tenant_id=row.tenant_id,team_id=row.team_id,actor_id=row.issuer_id,
            subject_id=user.id,action='invitation_joined',payload={'invitation_id':row.id,'team_role':'manager' if row.role=='manager' else 'member'}))
        claimed = db.execute(update(WorkspaceInvitation).where(WorkspaceInvitation.id == row.id,
            WorkspaceInvitation.used_at.is_(None), WorkspaceInvitation.revoked.is_(False),
            WorkspaceInvitation.expires_at > now()).values(used_at=now(), used_by=user.id)
            .execution_options(synchronize_session=False))
        if claimed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "Invitation already used or unavailable")
        audit(db, user, "invitation_accepted")
        return signed_in(db, user, request, response, settings)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This account could not be created. Choose another username or sign in.") from None


@router.get("/invitations")
def invites(principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin")
    rows = db.scalars(select(WorkspaceInvitation).where(WorkspaceInvitation.tenant_id == principal.tenant_id)
                      .order_by(WorkspaceInvitation.created_at.desc()).limit(50))
    return [{"id": r.id, "role": r.role,"team_id":r.team_id, "expires_at": r.expires_at, "used": r.used_at is not None,
             "revoked": r.revoked} for r in rows]


@router.post("/invitations", status_code=201)
def invite(body: InviteBody, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin")
    team_id=body.team_id or ensure_general_team(db,principal.tenant_id)
    team=db.scalar(select(Team).where(Team.id==team_id,Team.tenant_id==principal.tenant_id,Team.enabled.is_(True)))
    if team is None:raise HTTPException(404,'Not found')
    rate_limit(db, "invite-issue", principal.user_id, 20, 3600)
    pending = db.scalar(select(func.count()).select_from(WorkspaceInvitation).where(
        WorkspaceInvitation.tenant_id == principal.tenant_id, WorkspaceInvitation.used_at.is_(None),
        WorkspaceInvitation.revoked.is_(False), WorkspaceInvitation.expires_at > now()))
    if pending >= 20:
        raise HTTPException(409, "Revoke an existing invitation before creating another")
    token = secrets.token_urlsafe(32)
    row = WorkspaceInvitation(id=str(uuid4()), tenant_id=principal.tenant_id, issuer_id=principal.user_id,
        token_hash=hash_secret(token), role=body.role,team_id=team_id, expires_at=now()+timedelta(days=body.days), revoked=False)
    db.add(row)
    db.add(TeamAudit(id=str(uuid4()),tenant_id=principal.tenant_id,team_id=team_id,actor_id=principal.user_id,
        subject_id=None,action='invitation_created',payload={'invitation_id':row.id,'account_role':row.role}))
    user = db.get(User, principal.user_id); audit(db, user, "invitation_created")
    db.commit()
    return {"id": row.id, "token": token, "role": row.role,"team_id":row.team_id, "expires_at": row.expires_at}


@router.post("/invitations/{invite_id}/revoke")
def revoke(invite_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin")
    row = db.scalar(select(WorkspaceInvitation).where(WorkspaceInvitation.id == invite_id,
        WorkspaceInvitation.tenant_id == principal.tenant_id).with_for_update())
    if not row:
        raise HTTPException(404, "Invitation unavailable")
    if not row.revoked:
        row.revoked = True; audit(db, db.get(User, principal.user_id), "invitation_revoked")
    db.commit()
    return {"revoked": True}


@router.post("/password")
def change_password(body: PasswordBody, request: Request, response: Response,
                    principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    settings = Settings()
    rate_limit(db, "change-password", principal.user_id, 5, 3600)
    user = db.scalar(select(User).where(User.id == principal.user_id).with_for_update())
    if not check_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    if check_password(body.password, user.password_hash):
        raise HTTPException(422, "Choose a different passphrase")
    user.password_hash = password_hash(body.password); user.token_version += 1
    db.execute(delete(WebSession).where(WebSession.user_id == user.id))
    audit(db, user, "password_changed")
    return signed_in(db, user, request, response, settings)
