from datetime import datetime, timedelta, timezone
import base64
import binascii
import hashlib
import hmac
import json
import secrets
from fastapi import Depends, Header, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from ownstack.config import Settings
from ownstack.db import SessionLocal
from ownstack.models import Project, RateWindow, Tenant, User, WebSession
from ownstack.policy import Principal, aware

SESSION_COOKIE = "ownstack_session"
CSRF_COOKIE = "ownstack_csrf"
SESSION_SECONDS = 8 * 60 * 60


def cookie_name(name, settings):
    # Browser cookies are scoped by hostname/path, not TCP port. Independent
    # localhost labs need different names while the existing default stays stable.
    scoped=(settings.cookie_namespace+'-' if settings.cookie_namespace else '')+name
    return '__Host-' + scoped if settings.secure_cookies else scoped


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return f"pbkdf2_sha256:600000:{salt.hex()}:{key.hex()}"


def check_password(password: str, stored: str) -> bool:
    """Read existing 300k records without resetting or invalidating an account."""
    try:
        parts = stored.split(":")
        if len(parts) == 2:
            salt, expected = parts; iterations = 300_000
        elif len(parts) == 4 and parts[:2] == ["pbkdf2_sha256", "600000"]:
            _, _, salt, expected = parts; iterations = 600_000
        else:
            return False
        raw_salt = bytes.fromhex(salt)
        if len(raw_salt) != 16 or len(expected) != 64:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), raw_salt, iterations).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, AttributeError):
        return False


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def require_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    permitted = {settings.public_origin}
    if settings.environment == "local":
        permitted.update({"http://localhost:5173", "http://127.0.0.1:5173", "http://testserver"})
    if origin is None and settings.environment == "local":
        return
    if origin not in permitted:
        raise HTTPException(403, "Request origin is not permitted")


def create_session(db: Session, user: User, response: Response, settings: Settings) -> str:
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.add(WebSession(token_hash=hash_secret(token), user_id=user.id, csrf_hash=hash_secret(csrf),
                      expires_at=datetime.now(timezone.utc) + timedelta(seconds=SESSION_SECONDS)))
    response.set_cookie(cookie_name(SESSION_COOKIE, settings), token, max_age=SESSION_SECONDS, httponly=True,
                        secure=settings.secure_cookies, samesite="strict", path="/")
    response.set_cookie(cookie_name(CSRF_COOKIE, settings), csrf, max_age=SESSION_SECONDS, httponly=False,
                        secure=settings.secure_cookies, samesite="strict", path="/")
    return csrf


def revoke_session(db: Session, request: Request, response: Response) -> None:
    settings = Settings()
    token = request.cookies.get(cookie_name(SESSION_COOKIE, settings))
    if token:
        db.execute(delete(WebSession).where(WebSession.token_hash == hash_secret(token)))
    response.delete_cookie(cookie_name(SESSION_COOKIE, settings), path="/", secure=settings.secure_cookies,
                           httponly=True, samesite="strict")
    response.delete_cookie(cookie_name(CSRF_COOKIE, settings), path="/", secure=settings.secure_cookies, samesite="strict")


def rate_limit(db: Session, namespace: str, identity: str, maximum: int, seconds: int) -> None:
    """A fixed window shared by all API processes. Identity is never stored in clear text."""
    now = datetime.now(timezone.utc)
    window = int(now.timestamp()) // seconds
    key = hmac.new(Settings().signing_secret.encode(),
                   f"{namespace}:{identity}:{window}".encode(), hashlib.sha256).hexdigest()
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    statement = insert(RateWindow).values(key=key, count=1,
                                         expires_at=now + timedelta(seconds=seconds * 2))
    statement = statement.on_conflict_do_update(index_elements=[RateWindow.key],
                                                set_={"count": RateWindow.count + 1}).returning(RateWindow.count)
    count = db.execute(statement).scalar_one()
    # Commit even rejected requests so a rollback cannot erase the rate limit.
    db.commit()
    if count > maximum:
        raise HTTPException(429, "Too many requests. Try again after the rate window.",
                            headers={"Retry-After": str(seconds)})


def issue_token(user: User, secret: str) -> str:
    payload = {"sub": user.id, "version": user.token_version,
               "exp": int((datetime.now(timezone.utc) + timedelta(hours=8)).timestamp())}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode()
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def parse_token(token: str, secret: str, expected_version: int | None = None) -> str:
    try:
        if len(token) > 4096:
            raise ValueError("token_too_long")
        body, signature = token.split(".", 1)
        correct = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, correct):
            raise ValueError("signature")
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if int(payload["exp"]) <= int(datetime.now(timezone.utc).timestamp()):
            raise ValueError("expired")
        if expected_version is not None and payload.get("version") != expected_version:
            raise ValueError("revoked")
        return str(payload["sub"])
    except (ValueError, KeyError, TypeError, binascii.Error, UnicodeDecodeError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_principal(request: Request, authorization: str | None = Header(default=None),
                      db: Session = Depends(db_session)) -> Principal:
    settings = Settings()
    token = request.cookies.get(cookie_name(SESSION_COOKIE, settings))
    if settings.environment == "local" and authorization and authorization.startswith("Bearer "):
        user_id = parse_token(authorization[7:], settings.signing_secret)
    elif token:
        row = db.get(WebSession, hash_secret(token))
        if row is None or aware(row.expires_at) <= datetime.now(timezone.utc):
            raise HTTPException(401, "Session expired. Sign in again.")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            require_origin(request, settings)
            csrf = request.headers.get("x-csrf-token", "")
            cookie_csrf = request.cookies.get(cookie_name(CSRF_COOKIE, settings), "")
            if not csrf or not hmac.compare_digest(csrf, cookie_csrf) or not hmac.compare_digest(hash_secret(csrf), row.csrf_hash):
                raise HTTPException(403, "CSRF token required")
        user_id = row.user_id
    else:
        raise HTTPException(401, "Sign in required")
    user_query=select(User).where(User.id==user_id)
    if request.method not in {'GET','HEAD','OPTIONS'}:user_query=user_query.with_for_update(read=True)
    user = db.scalar(user_query)
    if not user or not user.enabled:
        raise HTTPException(status_code=401, detail="Unknown user")
    if settings.environment == "local" and authorization and authorization.startswith("Bearer "):
        parse_token(authorization[7:], settings.signing_secret, expected_version=user.token_version)
    return Principal(user.id, user.tenant_id, user.role)


def require_role(principal: Principal, *roles: str) -> None:
    if principal.role not in roles:
        raise HTTPException(status_code=403, detail="Role cannot perform this action")


def require_workspace_ai(db: Session, tenant_id: str) -> None:
    """A public account never inherits the operator's finite provider allowance."""
    tenant = db.get(Tenant, tenant_id)
    if not tenant or not tenant.ai_enabled:
        raise HTTPException(403, "AI has not been activated for this workspace. Saved work and manual review remain available.")


def session_payload(db: Session, user: User, csrf: str, settings: Settings) -> dict:
    from ownstack.models import Team,TeamMembership
    from ownstack.team_scope import metadata_projects,team_ids
    from ownstack.policy import digest
    import os
    tenant = db.get(Tenant, user.tenant_id)
    principal=Principal(user.id,user.tenant_id,user.role)
    projects=db.scalars(select(Project).where(metadata_projects(db,principal)).order_by(Project.id)).all()
    project=projects[0] if projects else None
    teams=db.scalars(select(Team).where(Team.tenant_id==user.tenant_id,Team.id.in_(team_ids(principal))).order_by(Team.id)).all()
    membership_rows=db.execute(select(TeamMembership.team_id,TeamMembership.role,TeamMembership.enabled,TeamMembership.revision,Team.enabled)
        .join(Team,(Team.id==TeamMembership.team_id)&(Team.tenant_id==TeamMembership.tenant_id))
        .where(TeamMembership.user_id==user.id,TeamMembership.tenant_id==user.tenant_id).order_by(TeamMembership.id)).all()
    return {"user_id": user.id, "tenant_id": user.tenant_id, "role": user.role,
            "display_name": user.display_name or user.id, "workspace_name": tenant.name,
            "project_id": project.id if project else None, "project_name": project.name if project else None,
            "ai_mode": settings.ai_mode if tenant.ai_enabled else "off", "csrf_token": csrf,
            "release_assurance_enabled": settings.environment=='local' and os.getenv('OWNSTACK_RELEASE_ASSURANCE')=='true',
            "teams":[{'id':t.id,'name':t.name} for t in teams],
            "projects":[{'id':p.id,'name':p.name,'team_id':p.team_id} for p in projects],
            "scope_version":digest({'role':user.role,'memberships':[list(r) for r in membership_rows],'projects':[p.id for p in projects]})}
