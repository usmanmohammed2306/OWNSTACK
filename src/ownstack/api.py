from contextlib import asynccontextmanager
from datetime import datetime
import difflib
import json
import logging
import os
from pathlib import Path
import time
from uuid import uuid4
from fastapi import Depends, FastAPI, Header, HTTPException, Request as HTTPRequest, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from ownstack.auth import (CSRF_COOKIE, check_password, create_session, current_principal, db_session,
                          issue_token, password_hash, rate_limit, require_origin, require_role, revoke_session)
from ownstack.config import Settings
from ownstack.models import (Attempt, ChangeRequest, ConvergenceDecision, Document, EngineeringItem,
                             Event, Evidence, HostObservation, Idempotency, InferenceBudget, Project, Proposal, RuntimePulse, User, Variation)
from ownstack.policy import Principal, aware, digest
from ownstack.host_access import host_read_decision
from ownstack.access_forecast import access_forecast
from ownstack.rollback import revoke_preview
from ownstack.service import (approve, claim_engineering, create_request, host_preview, idempotent, manual_handoff, record,
                              reserve_live_call, scoped, start_attempt, utcnow)
from ownstack.patch_agent import propose_patch
from ownstack.proof import export_proof
from ownstack.demo import historical_demo
from ownstack.repair_api import router as repair_router
from ownstack.members import router as members_router
from ownstack.operations import router as operations_router
from ownstack.proposal_refresh import router as proposal_refresh_router
from ownstack.runner import ALLOWED_PATH, CHECKS, ROOT, current_provenance, patch_hash, validate_patch, verify_patch as run_verifier
from ownstack.http_security import SecurityBoundary
from ownstack.candidate_sandbox import POLICY_ID
from ownstack.auth import cookie_name
from ownstack.db import SessionLocal
from ownstack.db_security import runtime_role_safe, enabled_seed_passwords_present
from ownstack.job_files import read_bytes, read_json

SCHEMA_REVISION = "a14d09c7f602"
LOGGER = logging.getLogger("ownstack.api")
DUMMY_PASSWORD_HASH = password_hash("unusable-account-password")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = Settings()
    settings.validate()
    if settings.environment == 'production' or os.getenv('OWNSTACK_ENFORCE_DB_ROLE') == 'true':
        with SessionLocal() as db:
            if not runtime_role_safe(db):
                raise RuntimeError('API requires a least-privileged application database role')
            if settings.environment == 'production' and enabled_seed_passwords_present(db):
                raise RuntimeError('Production refuses enabled accounts using the default fixture password')
    yield


app = FastAPI(title="OwnStack", version="0.1.0", lifespan=lifespan)
app.include_router(repair_router)
app.include_router(members_router)
app.include_router(operations_router)
app.include_router(proposal_refresh_router)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_credentials=True, allow_methods=["GET", "POST"],
                   allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-CSRF-Token"])
app.add_middleware(SecurityBoundary)


@app.middleware("http")
async def request_context(request: HTTPRequest, call_next):
    request_id = str(uuid4())
    try:
        response = await call_next(request)
    except Exception as error:
        LOGGER.error("request_failed id=%s type=%s", request_id, type(error).__name__)
        response = JSONResponse(status_code=500, content={"detail": "Unexpected server error", "request_id": request_id})
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    if Settings().environment == 'production':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        response.headers['Content-Security-Policy'] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    return response


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=256)


class RequestBody(BaseModel):
    text: str = Field(min_length=5, max_length=3000)
    kind: str = Field(pattern="^(access|feature)$")
    project_id: str | None = None
    viewer_id: str | None = None
    expires_at: datetime | None = None


class ApprovalBody(BaseModel):
    proposal_hash: str = Field(min_length=64, max_length=64)


class RevokeBody(BaseModel):
    preview_hash: str = Field(pattern="^[a-f0-9]{64}$")


class DecisionBody(BaseModel):
    decision: str = Field(pattern="^(promote|keep_separate|retire)$")
    rationale: str = Field(min_length=10, max_length=2000)


class EngineeringDecisionBody(BaseModel):
    decision: str = Field(pattern="^(accept_for_manual_release|reject|take_over)$")
    patch_hash: str | None = None


class ManualPatchBody(BaseModel):
    patch: dict


def serialize_request(req: ChangeRequest):
    return {"id": req.id, "tenant_id": req.tenant_id, "text": req.text, "kind": req.kind,
            "project_id": req.project_id, "viewer_id": req.viewer_id,
            "expires_at": aware(req.expires_at).isoformat() if req.expires_at else None,
            "status": req.status, "revision": req.revision, "current_attempt_id": req.current_attempt_id,
            "accepted_proposal_id": req.accepted_proposal_id}


def serialize_attempt(attempt: Attempt):
    return {"id": attempt.id, "number": attempt.number, "state": attempt.state,
            "model_id": attempt.model_id, "deadline_at": aware(attempt.deadline_at).isoformat(),
            "error_code": attempt.error_code, "latency_ms": attempt.latency_ms,
            "input_tokens": attempt.input_tokens, "output_tokens": attempt.output_tokens}


def serialize_proposal(proposal: Proposal):
    return {"id": proposal.id, "request_id": proposal.request_id, "route": proposal.route,
            "reason": proposal.reason, "parameters": proposal.parameters,
            "proposal_hash": proposal.proposal_hash, "preview_hash": proposal.preview_hash,
            "contract_id": proposal.contract_id, "contract_version": proposal.contract_version,
    "status": proposal.status}


def committed_idempotency(db: Session, tenant_id: str, operation: str, key: str, body: dict):
    row = db.scalar(select(Idempotency).where(Idempotency.tenant_id == tenant_id,
                                              Idempotency.operation == operation, Idempotency.key == key))
    if row and row.request_hash == digest(body):
        return row.response
    raise HTTPException(409, "Concurrent idempotency conflict")


@app.get("/health/live")
def live():
    return {"status": "alive"}


@app.get("/health/ready")
def ready(db: Session = Depends(db_session)):
    try:
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except SQLAlchemyError:
        raise HTTPException(503, "Database unavailable or migration required")
    if revision != SCHEMA_REVISION:
        raise HTTPException(503, "Database migration required")
    settings = Settings()
    if settings.environment == 'production' or os.getenv('OWNSTACK_ENFORCE_DB_ROLE') == 'true':
        if not runtime_role_safe(db):
            raise HTTPException(503, 'Application database role is overprivileged')
    if settings.require_background:
        pulse = db.get(RuntimePulse, "worker")
        if pulse is None or (utcnow() - aware(pulse.touched_at)).total_seconds() > max(60, settings.ai_timeout + 15):
            raise HTTPException(503, "Worker heartbeat is unavailable")
        heartbeat = Path(os.getenv("OWNSTACK_VERIFIER_JOBS_DIR", "/srv/jobs")) / "heartbeat"
        try:
            healthy_verifier = 0 <= time.time() - float(read_bytes(heartbeat, 64)) < 30
            posture = read_json(heartbeat.with_name('sandbox-policy.json'), 4096)
            healthy_verifier = healthy_verifier and (posture.get('policy') == POLICY_ID
                and posture.get('execution_policy_hash') == current_provenance()['execution_policy_hash']
                and posture.get('landlock_abi', 0) >= 3 and 0 <= time.time()-posture['checked_at'] < 30)
        except (OSError, ValueError, TypeError, KeyError):
            healthy_verifier = False
        if not healthy_verifier:
            raise HTTPException(503, "Verifier heartbeat is unavailable")
    return {"status": "ready", "ai_mode": Settings().ai_mode}


@app.post("/v1/session")
def login(body: LoginBody, request: HTTPRequest, response: Response, db: Session = Depends(db_session)):
    settings = Settings()
    require_origin(request, settings)
    rate_limit(db, "login-ip", request.client.host if request.client else "unknown", 30, 300)
    rate_limit(db, "login-user", body.username, 15, 300)
    user = db.scalar(select(User).where(User.id == body.username).with_for_update())
    matches = check_password(body.password, user.password_hash if user else DUMMY_PASSWORD_HASH)
    if not user or not matches or not user.enabled:
        raise HTTPException(401, "Invalid credentials")
    revoke_session(db, request, response)
    csrf = create_session(db, user, response, settings)
    db.commit()
    result = {"user_id": user.id, "tenant_id": user.tenant_id, "role": user.role,
              "ai_mode": settings.ai_mode, "csrf_token": csrf}
    if settings.environment == "local":
        result["token"] = issue_token(user, settings.signing_secret)
    return result


@app.get("/v1/session")
def saved_session(request: HTTPRequest, principal: Principal = Depends(current_principal)):
    return {**principal.__dict__, "ai_mode": Settings().ai_mode,
            "csrf_token": request.cookies.get(cookie_name(CSRF_COOKIE, Settings()), "")}


@app.post("/v1/session/logout")
def logout(request: HTTPRequest, response: Response, principal: Principal = Depends(current_principal),
           db: Session = Depends(db_session)):
    revoke_session(db, request, response)
    db.commit()
    return {"signed_out": True}


@app.get("/v1/me")
def me(principal: Principal = Depends(current_principal)):
    return principal.__dict__


@app.get("/v1/inference-budget")
def inference_budget(principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "engineer", "product_owner")
    settings = Settings()
    row = db.get(InferenceBudget, "global")
    if row is None:
        raise HTTPException(503, "Database migration required")
    return {"mode": settings.ai_mode, "reserved_calls": row.reserved_calls,
            "max_live_calls": settings.max_live_calls,
            "remaining_calls": max(settings.max_live_calls - row.reserved_calls, 0) if settings.ai_mode == "nebius" else None,
            "note": "Reservations are a conservative call cap, not confirmed provider billing."}


@app.get("/v1/demo-evidence")
def demo_evidence(principal: Principal = Depends(current_principal)):
    # This is public, synthetic source material, never another tenant's DB rows.
    # Authentication still makes its presentation consistent with the workbench.
    try:
        return historical_demo()
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        raise HTTPException(503, "Historical demo evidence unavailable; inspect source artifacts")


@app.get("/v1/host/projects")
def projects(principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    rows = db.scalars(select(Project).where(Project.tenant_id == principal.tenant_id).order_by(Project.id)).all()
    return [{"id": p.id, "name": p.name, "revision": p.revision} for p in rows]


@app.get("/v1/host/projects/{project_id}/documents")
def list_documents(project_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    project = scoped(db, Project, project_id, principal.tenant_id)
    observe_read(db, principal, project, "list_documents")
    rows = db.scalars(select(Document).where(Document.tenant_id == principal.tenant_id, Document.project_id == project_id).order_by(Document.id)).all()
    return [{"id": d.id, "title": d.title} for d in rows]


@app.get("/v1/host/projects/{project_id}/access-review")
def access_review(project_id: str, viewer_id: str, response: Response,
                  principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    """Explain a tenant-local policy snapshot without impersonation or read effects."""
    require_role(principal, "admin", "engineer")
    project = scoped(db, Project, project_id, principal.tenant_id)
    viewer = scoped(db, User, viewer_id, principal.tenant_id)
    at = utcnow()
    # Authentication rejects disabled users before any host policy evaluation.
    decision, forecast = access_forecast(db, viewer, project, at)
    allowed = bool(decision and decision.allowed)
    reason = ("account_disabled" if not viewer.enabled else
              "role_access" if allowed and decision.basis == "role" else
              "active_grant" if allowed else "no_current_access")
    response.headers["Cache-Control"] = "no-store"
    return {"tenant_id": principal.tenant_id, "project_id": project.id,
            "project_revision": project.revision, "viewer_id": viewer.id,
            "viewer_enabled": viewer.enabled, "viewer_role": viewer.role,
            "allowed": allowed, "basis": decision.basis if decision else "denied",
            "reason": reason, "variation_id": decision.variation_id if decision else None,
            "evaluated_at": at.isoformat(), "diagnostic_only": True, "forecast": forecast,
            "notice": "Read-only policy snapshot, not an observed read or permission token. "
                      "The host checks identity, scope and time again on every actual read."}


@app.get("/v1/host/projects/{project_id}/documents/{document_id}")
def read_document(project_id: str, document_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    project = scoped(db, Project, project_id, principal.tenant_id)
    document = db.scalar(select(Document).where(Document.id == document_id, Document.project_id == project.id, Document.tenant_id == principal.tenant_id))
    if not document:
        raise HTTPException(404, "Not found")
    observe_read(db, principal, project, "read_document", document_id)
    return {"id": document.id, "title": document.title, "body": document.body}


def observe_read(db: Session, principal: Principal, project: Project, action: str, document_id: str | None = None):
    # One read-time instant for SQL selection, policy and the observation. No TTL cache.
    at = utcnow()
    decision = host_read_decision(db, principal, project.tenant_id, project.id, at)
    db.add(HostObservation(id=str(uuid4()), tenant_id=principal.tenant_id, project_id=project.id,
                           actor_id=principal.user_id, document_id=document_id, variation_id=decision.variation_id,
                           action=action, allowed=decision.allowed, basis=decision.basis, observed_at=at))
    # Fail closed if evidence cannot be saved. Persist denies before raising HTTPException.
    db.commit()
    if not decision.allowed:
        raise HTTPException(403, "Host denied project read")


@app.get("/v1/host-observations")
def host_observations(variation_id: str | None = None, principal: Principal = Depends(current_principal),
                      db: Session = Depends(db_session)):
    require_role(principal, "admin", "engineer")
    statement = select(HostObservation).where(HostObservation.tenant_id == principal.tenant_id)
    if variation_id:
        scoped(db, Variation, variation_id, principal.tenant_id)
        statement = statement.where(HostObservation.variation_id == variation_id)
    rows = db.scalars(statement.order_by(HostObservation.observed_at.desc(), HostObservation.id).limit(500)).all()
    return [{"id": row.id, "project_id": row.project_id, "actor_id": row.actor_id,
             "document_id": row.document_id, "variation_id": row.variation_id,
             "action": row.action, "allowed": row.allowed, "basis": row.basis,
             "observed_at": aware(row.observed_at).isoformat()} for row in rows]


@app.post("/v1/requests", status_code=201)
def post_request(body: RequestBody, idempotency_key: str | None = Header(default=None),
                 principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "member", "engineer")
    data = body.model_dump(mode="json")
    if body.kind == "access" and not (body.project_id and body.viewer_id and body.expires_at):
        raise HTTPException(422, "Access request needs project, viewer, and expiry")
    if body.kind == "feature" and not body.project_id:
        raise HTTPException(422, "Feature request needs a project")
    normalized = {**data, "expires_at": body.expires_at}
    try:
        response = create_request(db, principal, normalized, idempotency_key or "")
        db.commit()
        return response
    except IntegrityError:
        db.rollback()
        return committed_idempotency(db, principal.tenant_id, "create_request", idempotency_key or "", normalized)


@app.get("/v1/requests")
def get_requests(principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "member", "engineer")
    rows = db.scalars(select(ChangeRequest).where(ChangeRequest.tenant_id == principal.tenant_id).order_by(ChangeRequest.created_at.desc())).all()
    return [serialize_request(row) for row in rows]


@app.get("/v1/requests/{request_id}")
def get_request(request_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "member", "engineer")
    return serialize_request(scoped(db, ChangeRequest, request_id, principal.tenant_id))


@app.post("/v1/requests/{request_id}/interpret", status_code=202)
def interpret(request_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "member", "engineer")
    request = db.scalar(select(ChangeRequest).where(ChangeRequest.id == request_id,
                                                    ChangeRequest.tenant_id == principal.tenant_id).with_for_update())
    if not request:
        raise HTTPException(404, "Not found")
    if request.accepted_proposal_id and request.status not in {"failed"}:
        return {"status": request.status, "proposal_id": request.accepted_proposal_id, "attempt_id": request.current_attempt_id}
    if Settings().ai_mode == "off":
        raise HTTPException(503, "AI is off. Existing evidence remains available.")
    settings = Settings()
    model_id = settings.nebius_model if settings.ai_mode == "nebius" else "fixture"
    attempt = start_attempt(db, request, model_id, settings.ai_timeout, settings)
    db.commit()
    return {"status": attempt.state, "attempt_id": attempt.id, "number": attempt.number}


@app.get("/v1/requests/{request_id}/proof")
def request_proof(request_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "engineer")
    return JSONResponse(content=export_proof(db.get_bind(), request_id, principal.tenant_id),
                        headers={"Content-Disposition": 'attachment; filename="ownstack-proof.json"'})


@app.post("/v1/requests/{request_id}/manual-handoff")
def post_manual_handoff(request_id: str, idempotency_key: str | None = Header(default=None),
                        principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "engineer")
    request = db.scalar(select(ChangeRequest).where(ChangeRequest.id == request_id,
                                                    ChangeRequest.tenant_id == principal.tenant_id).with_for_update())
    if request is None:
        raise HTTPException(404, "Not found")
    response = idempotent(db, principal.tenant_id, "manual_handoff", idempotency_key or "",
                          {"request_id": request_id, "actor_id": principal.user_id},
                          lambda: manual_handoff(db, request, principal))
    db.commit()
    return response


@app.get("/v1/requests/{request_id}/attempts")
def get_attempts(request_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "member", "engineer")
    scoped(db, ChangeRequest, request_id, principal.tenant_id)
    rows = db.scalars(select(Attempt).where(Attempt.tenant_id == principal.tenant_id, Attempt.request_id == request_id).order_by(Attempt.number)).all()
    return [serialize_attempt(row) for row in rows]


@app.post("/v1/requests/{request_id}/cancel")
def cancel_attempt(request_id: str, principal: Principal = Depends(current_principal),
                   db: Session = Depends(db_session)):
    require_role(principal, "admin", "engineer", "member")
    request = db.scalar(select(ChangeRequest).where(ChangeRequest.id == request_id,
                                                   ChangeRequest.tenant_id == principal.tenant_id).with_for_update())
    if not request:
        raise HTTPException(404, "Not found")
    attempt = db.get(Attempt, request.current_attempt_id) if request.current_attempt_id else None
    if attempt and attempt.state in {"queued", "running"}:
        attempt.state, attempt.finished_at, attempt.error_code = "canceled", utcnow(), "LOCAL_CANCEL"
        request.status = "failed"
        record(db, principal.tenant_id, request_id, "attempt.canceled",
               {"attempt_id": attempt.id, "remote_cancellation_verified": False})
    db.commit()
    return {"status": request.status, "remote_cancellation_verified": False}


@app.get("/v1/proposals/{proposal_id}")
def get_proposal(proposal_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "member", "engineer")
    return serialize_proposal(scoped(db, Proposal, proposal_id, principal.tenant_id))


@app.post("/v1/proposals/{proposal_id}/preview")
def preview(proposal_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "engineer")
    proposal = scoped(db, Proposal, proposal_id, principal.tenant_id)
    if proposal.route != "configure":
        raise HTTPException(409, "No host preview for nonconfigurable route")
    request = scoped(db, ChangeRequest, proposal.request_id, principal.tenant_id)
    result = host_preview(db, request)
    return {**result, "matches_saved_proposal": result["snapshot_hash"] == proposal.preview_hash}


@app.post("/v1/proposals/{proposal_id}/approve")
def post_approve(proposal_id: str, body: ApprovalBody, idempotency_key: str | None = Header(default=None),
                 principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    proposal = db.scalar(select(Proposal).where(Proposal.id == proposal_id,
                                                Proposal.tenant_id == principal.tenant_id).with_for_update())
    if not proposal:
        raise HTTPException(404, "Not found")
    idem_body = {"proposal_id": proposal_id, "proposal_hash": body.proposal_hash, "actor_id": principal.user_id}
    try:
        response = approve(db, proposal, principal, body.proposal_hash, idempotency_key or "")
        db.commit()
        return response
    except IntegrityError:
        db.rollback()
        return committed_idempotency(db, principal.tenant_id, "approve", idempotency_key or "", idem_body)


@app.get("/v1/variations")
def variations(principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "member", "engineer")
    rows = db.scalars(select(Variation).where(Variation.tenant_id == principal.tenant_id)).all()
    at = utcnow()
    return [{"id": v.id, "project_id": v.project_id, "viewer_id": v.viewer_id,
             "state": "expired" if v.state == "active" and aware(v.expires_at) <= at else v.state,
             "expires_at": aware(v.expires_at).isoformat()} for v in rows]


@app.post("/v1/variations/{variation_id}/revoke")
def revoke(variation_id: str, body: RevokeBody | None = None, idempotency_key: str | None = Header(default=None),
           principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin")
    variation = db.scalar(select(Variation).where(Variation.id == variation_id,
                                                 Variation.tenant_id == principal.tenant_id).with_for_update())
    if not variation:
        raise HTTPException(404, "Not found")
    # All revokes serialize with grant approval on this project. Lock the subject
    # too so offboarding cannot change the reviewed identity before this commit.
    db.scalar(select(Project).where(Project.id == variation.project_id,
        Project.tenant_id == principal.tenant_id).with_for_update())
    db.scalar(select(User).where(User.id == variation.viewer_id,
        User.tenant_id == principal.tenant_id).with_for_update().execution_options(populate_existing=True))
    def create():
        if body:
            fresh = revoke_preview(db, variation, principal.user_id, utcnow())
            if not fresh["can_revoke"] or fresh["preview_hash"] != body.preview_hash:
                raise HTTPException(409, "Rollback preview changed; refresh and review again")
        if variation.state == "active":
            variation.state = "revoked"
            request_id = db.get(Proposal, variation.proposal_id).request_id
            db.get(ChangeRequest, request_id).status = "revoked"
            payload = {"variation_id": variation.id}
            if body:
                payload["reviewed_preview_hash"] = body.preview_hash
            record(db, principal.tenant_id, request_id, "variation.revoked", payload)
        return {"id": variation.id, "state": variation.state}
    intent = {"variation_id": variation_id}
    if body:
        intent["preview_hash"] = body.preview_hash
    response = idempotent(db, principal.tenant_id, "revoke", idempotency_key or "", intent, create)
    db.commit()
    return response


@app.get("/v1/variations/{variation_id}/revoke-preview")
def get_revoke_preview(variation_id: str, response: Response,
                       principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin")
    variation = scoped(db, Variation, variation_id, principal.tenant_id)
    response.headers["Cache-Control"] = "no-store"
    return revoke_preview(db, variation, principal.user_id, utcnow())


@app.get("/v1/events")
def events(request_id: str | None = None, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "member", "engineer")
    statement = select(Event).where(Event.tenant_id == principal.tenant_id)
    if request_id:
        scoped(db, ChangeRequest, request_id, principal.tenant_id)
        statement = statement.where(Event.request_id == request_id)
    rows = db.scalars(statement.order_by(Event.created_at)).all()
    return [{"id": e.id, "request_id": e.request_id, "type": e.event_type, "payload": e.payload,
             "created_at": aware(e.created_at).isoformat()} for e in rows]


@app.get("/v1/evidence/{request_id}")
def evidence(request_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "member", "engineer")
    scoped(db, ChangeRequest, request_id, principal.tenant_id)
    rows = db.scalars(select(Evidence).where(Evidence.tenant_id == principal.tenant_id, Evidence.request_id == request_id)).all()
    return [{"id": e.id, "kind": e.kind, "subject_hash": e.subject_hash,
             "result": e.result, "limitation": e.limitation} for e in rows]


@app.get("/v1/engineering")
def engineering(principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "engineer", "admin")
    rows = db.scalars(select(EngineeringItem).where(EngineeringItem.tenant_id == principal.tenant_id)).all()
    return [{"id": w.id, "request_id": w.request_id, "status": w.status,
             "patch_hash": w.patch_hash, "human_decision": w.human_decision} for w in rows]


@app.get("/v1/engineering/{item_id}")
def engineering_item(item_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "engineer", "admin")
    item = scoped(db, EngineeringItem, item_id, principal.tenant_id)
    request = scoped(db, ChangeRequest, item.request_id, principal.tenant_id)
    checks = db.scalars(select(Evidence).where(Evidence.request_id == request.id, Evidence.tenant_id == principal.tenant_id, Evidence.kind == "patch_checks")).all()
    return {"id": item.id, "request": serialize_request(request), "status": item.status,
            "patch": item.patch, "patch_hash": item.patch_hash, "human_decision": item.human_decision,
            "current_checks_usable": bool(item.patch_hash and matching_checks(db, item)),
            "operation_deadline": aware(item.operation_deadline).isoformat() if item.operation_deadline else None,
            "checks": [{"subject_hash": e.subject_hash, "result": e.result, "limitation": e.limitation} for e in checks]}


@app.get("/v1/engineering-source")
def engineering_source(principal: Principal = Depends(current_principal)):
    require_role(principal, "engineer")
    source = (ROOT / ALLOWED_PATH).read_text()
    return {"path": ALLOWED_PATH, "source": source, "source_hash": digest(source)}


@app.post("/v1/engineering/{item_id}/manual-patch")
def manual_patch(item_id: str, body: ManualPatchBody,
                 principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "engineer")
    item = scoped(db, EngineeringItem, item_id, principal.tenant_id)
    if item.status not in {"needs_engineer", "draft_failed", "drafting", "checks_failed"}:
        raise HTTPException(409, "Work item already has a patch or human decision")
    try:
        validate_patch(body.patch)
    except ValueError as error:
        raise HTTPException(422, str(error))
    candidate_hash = patch_hash(body.patch)
    previous_patch, previous_hash = item.patch, item.patch_hash
    changed = db.execute(update(EngineeringItem)
                         .where(EngineeringItem.id == item_id, EngineeringItem.tenant_id == principal.tenant_id,
                                EngineeringItem.status.in_(("needs_engineer", "draft_failed", "drafting", "checks_failed")))
                         .values(patch=body.patch, patch_hash=candidate_hash, status="drafted",
                                 operation_id=None, operation_deadline=None)
                         .execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Work item changed while the manual patch was submitted")
    db.refresh(item)
    if previous_patch and previous_hash:
        db.add(Evidence(id=str(uuid4()), tenant_id=principal.tenant_id, request_id=item.request_id,
                        kind="superseded_patch", subject_hash=previous_hash,
                        result={"patch": previous_patch, "replacement_hash": candidate_hash, "actor_id": principal.user_id},
                        limitation="Historical untrusted proposal, not the corrected patch or a release."))
    record(db, principal.tenant_id, item.request_id, "engineering.manual_patch",
           {"item_id": item.id, "patch_hash": item.patch_hash, "actor_id": principal.user_id})
    db.commit()
    return {"id": item.id, "status": item.status, "patch_hash": item.patch_hash,
            "ai_call": False}


@app.post("/v1/engineering/{item_id}/draft")
def draft_patch(item_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "engineer")
    item = scoped(db, EngineeringItem, item_id, principal.tenant_id)
    if item.status not in {"needs_engineer", "draft_failed"}:
        return {"id": item.id, "status": item.status, "patch_hash": item.patch_hash}
    request = scoped(db, ChangeRequest, item.request_id, principal.tenant_id)
    settings = Settings()
    operation_id = claim_engineering(db, item, "drafting", settings.ai_timeout + 5)
    reserve_live_call(db, settings)
    db.commit()
    try:
        draft = propose_patch(request.text)
        patch, model_id = draft[:2]
        metrics = draft[2] if len(draft) > 2 else {"live": False, "source": "test-double"}
        candidate_hash = patch_hash(patch)
        changed = db.execute(update(EngineeringItem)
                             .where(EngineeringItem.id == item_id, EngineeringItem.tenant_id == principal.tenant_id,
                                    EngineeringItem.status == "drafting",
                                    EngineeringItem.operation_id == operation_id,
                                    EngineeringItem.operation_deadline > utcnow())
                             .values(patch=patch, patch_hash=candidate_hash, status="drafted",
                                     operation_id=None, operation_deadline=None)
                             .execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "AI draft was superseded by an engineer")
        item = scoped(db, EngineeringItem, item_id, principal.tenant_id)
        db.refresh(item)
        db.add(Evidence(id=str(uuid4()), tenant_id=principal.tenant_id, request_id=request.id,
                        kind="patch_generation", subject_hash=candidate_hash,
                        result={"model_id": model_id, **metrics},
                        limitation="A generated patch is an untrusted proposal, not a checked or released build."))
        record(db, principal.tenant_id, request.id, "engineering.patch_drafted", {"item_id": item.id, "patch_hash": item.patch_hash, "model_id": model_id})
        db.commit()
        return {"id": item.id, "status": item.status, "patch_hash": item.patch_hash, "model_id": model_id}
    except HTTPException:
        raise
    except Exception as error:
        db.rollback()
        item = scoped(db, EngineeringItem, item_id, principal.tenant_id)
        changed = db.execute(update(EngineeringItem)
                             .where(EngineeringItem.id == item_id, EngineeringItem.status == "drafting",
                                    EngineeringItem.operation_id == operation_id)
                             .values(status="draft_failed", operation_id=None, operation_deadline=None))
        if changed.rowcount == 1:
            safe_codes = {"MODEL_OUTPUT_TRUNCATED", "INVALID_MODEL_OUTPUT", "AI_OFF",
                          "One bounded edit is required", "Patch may edit only sample_app/report.py",
                          "Invalid patch text or size", "Patch anchor must match exactly once"}
            code = str(error) if str(error) in safe_codes else "MODEL_DRAFT_ERROR"
            record(db, principal.tenant_id, request.id, "engineering.draft_failed",
                   {"item_id": item.id, "error_type": type(error).__name__, "error_code": code})
        db.commit()
        raise HTTPException(502, "Draft failed; engineer can continue manually")


@app.post("/v1/engineering/{item_id}/verify")
def verify_patch(item_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "engineer")
    item = scoped(db, EngineeringItem, item_id, principal.tenant_id)
    if item.status not in {"drafted", "checks_failed", "checks_passed"} or not item.patch:
        raise HTTPException(409, "No draft patch to verify")
    request_id, patch, expected_hash = item.request_id, item.patch, item.patch_hash
    operation_id = claim_engineering(db, item, "checking", 60)
    db.commit()
    try:
        result = run_verifier(patch)
    except (OSError, ValueError) as error:
        result = {"passed": False, "exit_code": None, "stdout": "",
                  "stderr": f"Verifier failed: {type(error).__name__}",
                  "runner": "unavailable", "patch_hash": expected_hash}
    if result["patch_hash"] != expected_hash:
        raise HTTPException(409, "Patch changed while checks ran")
    changed = db.execute(update(EngineeringItem).where(
        EngineeringItem.id == item_id, EngineeringItem.tenant_id == principal.tenant_id,
        EngineeringItem.operation_id == operation_id, EngineeringItem.status == "checking",
        EngineeringItem.operation_deadline > utcnow(), EngineeringItem.patch_hash == expected_hash)
        .values(status="checks_passed" if result["passed"] else "checks_failed",
                operation_id=None, operation_deadline=None).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Checks were superseded or exceeded their deadline")
    db.add(Evidence(id=str(uuid4()), tenant_id=principal.tenant_id, request_id=request_id,
                    kind="patch_checks", subject_hash=expected_hash, result=result,
                    limitation="These checks cover only the owned fixture. A pass is not a security guarantee or a release."))
    record(db, principal.tenant_id, request_id, "engineering.checks_finished", {"item_id": item_id, "passed": result["passed"], "patch_hash": expected_hash})
    db.commit()
    return result


@app.post("/v1/engineering/{item_id}/decide")
def engineering_decide(item_id: str, body: EngineeringDecisionBody,
                       principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "engineer")
    item = db.scalar(select(EngineeringItem).where(EngineeringItem.id == item_id,
                                                  EngineeringItem.tenant_id == principal.tenant_id).with_for_update())
    if item is None:
        raise HTTPException(404, "Not found")
    if item.human_decision:
        raise HTTPException(409, "Decision already recorded")
    if body.decision == "accept_for_manual_release":
        if item.status != "checks_passed" or body.patch_hash != item.patch_hash:
            raise HTTPException(409, "Exact checked patch required")
        if not matching_checks(db, item):
            raise HTTPException(409, "Checks do not match the current source, test suite and build revision")
    item.human_decision = body.decision
    item.status = "human_decided"
    item.operation_id, item.operation_deadline = None, None
    record(db, principal.tenant_id, item.request_id, "engineering.human_decision",
           {"decision": body.decision, "patch_hash": item.patch_hash if body.decision == "accept_for_manual_release" else None})
    db.commit()
    return {"decision": body.decision, "release_state": "not_deployed"}


def matching_checks(db: Session, item: EngineeringItem) -> list[dict]:
    from ownstack.pdf_oracle import is_external_pass
    provenance = current_provenance()
    evidence = db.scalars(select(Evidence).where(Evidence.request_id == item.request_id,
                                                Evidence.tenant_id == item.tenant_id,
                                                Evidence.kind == "patch_checks",
                                                Evidence.subject_hash == item.patch_hash)).all()
    return [row.result for row in evidence if is_external_pass(row.result) and
            (Settings().environment != 'production' or row.result.get('isolation_profile') == POLICY_ID) and
            all(row.result.get(key) == value for key, value in provenance.items())]


@app.get("/v1/engineering/{item_id}/artifact")
def engineering_artifact(item_id: str, principal: Principal = Depends(current_principal),
                         db: Session = Depends(db_session)):
    require_role(principal, "engineer")
    item = scoped(db, EngineeringItem, item_id, principal.tenant_id)
    if item.human_decision != "accept_for_manual_release" or not item.patch:
        raise HTTPException(409, "Human acceptance of the checked patch is required")
    validate_patch(item.patch)
    passed = matching_checks(db, item)
    if not passed:
        raise HTTPException(409, "Passing evidence for this exact patch is required")
    edit = item.patch["edits"][0]
    diff = "".join(difflib.unified_diff(edit["old"].splitlines(keepends=True),
                                      edit["new"].splitlines(keepends=True),
                                      fromfile=f"a/{ALLOWED_PATH}", tofile=f"b/{ALLOWED_PATH}"))
    return {"item_id": item.id, "patch_hash": item.patch_hash, "diff": diff,
            "source_hash": digest((ROOT / ALLOWED_PATH).read_text()),
            "checks_hash": digest((ROOT / CHECKS).read_text()),
            "build_revision": os.getenv("OWNSTACK_BUILD_REVISION", "uncommitted-reference"),
            "checks": passed, "release_state": "not_deployed"}


@app.get("/v1/convergence")
def convergence(principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "engineer", "product_owner")
    rows = []
    for need_key, predicate in [
        ("pdf-export", (ChangeRequest.kind == "feature") & ChangeRequest.text.ilike("%pdf%")),
        ("temporary-project-view", ChangeRequest.kind == "access"),
    ]:
        local_count = db.scalar(select(func.count(ChangeRequest.id)).where(
            ChangeRequest.tenant_id == principal.tenant_id, predicate)) or 0
        affected = None
        if principal.role == "product_owner":
            affected = db.scalar(select(func.count(func.distinct(ChangeRequest.tenant_id))).where(predicate)) or 0
        latest = db.scalar(select(ConvergenceDecision).where(ConvergenceDecision.need_key == need_key)
                           .order_by(ConvergenceDecision.created_at.desc(), ConvergenceDecision.id).limit(1))
        # Count actual granted host authorizations, not previews, approvals, denied reads or role access.
        usage = None
        if need_key == "temporary-project-view":
            statement = select(func.count(HostObservation.id)).where(
                HostObservation.allowed.is_(True), HostObservation.basis == "variation")
            if principal.role != "product_owner":
                statement = statement.where(HostObservation.tenant_id == principal.tenant_id)
            usage = db.scalar(statement) or 0
        rows.append({"need_key": need_key, "your_tenant_request_count": local_count,
                     "affected_tenant_count": affected, "decision": latest.decision if latest else None,
                     "observed_granted_reads": usage,
                     "usage_scope": "all_tenants" if principal.role == "product_owner" else "your_tenant",
                     "note": "Counts are synthetic lab signals, not validated demand. PDF matching is lexical. "
                             "Observed reads count authorized API requests, including retries, not distinct people "
                             "or proof of response delivery. Previews are excluded. Only the product owner sees cross-tenant counts."})
    return rows


@app.post("/v1/convergence/{need_key}/decide")
def decide(need_key: str, body: DecisionBody, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "product_owner")
    if need_key not in {"pdf-export", "temporary-project-view"}:
        raise HTTPException(404, "Unknown convergence need")
    row = ConvergenceDecision(id=str(uuid4()), need_key=need_key, actor_id=principal.user_id,
                              decision=body.decision, rationale=body.rationale)
    db.add(row)
    db.commit()
    return {"id": row.id, "decision": row.decision, "effect": "record_only"}
