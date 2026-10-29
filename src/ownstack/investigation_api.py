"""Durable, explicitly stepped agent runs. GET and refresh never invoke a model."""
from copy import deepcopy
from datetime import timedelta
import time
from fastapi import APIRouter, Depends, Header, HTTPException, Request
import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ownstack.auth import current_principal, db_session, require_role, require_workspace_ai
from ownstack.config import Settings
from ownstack.investigation import (DecisionFailure, LIMITATION, MAX_STEPS, SCHEMA, advance, identity,
    offline_decision, provider_decision, snapshot)
from ownstack.models import ChangeRequest, Investigation
from ownstack.policy import Principal, aware, digest
from ownstack.service import idempotent, record, reserve_live_call, scoped, uid, utcnow

router = APIRouter(prefix="/v1", tags=["request investigation"])
TERMINAL = {"completed", "failed", "stopped", "stale"}


class StartBody(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    revision: int = Field(ge=1)


class StepBody(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    expected_version: int = Field(ge=0)


def serialize(run):
    return {"id": run.id, "tenant_id": run.tenant_id, "request_id": run.request_id,
        "revision": run.memory["snapshot"]["request"]["revision"], "state": run.state,
        "version": run.version, "model_id": run.model_id,
        "source": "nemotron" if run.model_id != "offline-policy" else "offline_policy",
        "steps": run.memory["steps"], "result": run.memory.get("result"),
        "failed_steps": run.memory.get("failed_steps", []), "retry_count": run.memory.get("retry_count", 0),
        "max_steps": MAX_STEPS, "error_code": run.error_code,
        "snapshot_hash": run.snapshot_hash, "workflow_hash": run.workflow_hash,
        "deadline_at": run.deadline_at, "limitation": LIMITATION}


def _finish_state(db, run, state, code=None, memory=None):
    version = run.version
    values = {"state": state, "error_code": code, "lease_id": None, "version": version + 1}
    if memory is not None:
        values["memory"] = memory
    changed = db.execute(update(Investigation).where(Investigation.id == run.id,
        Investigation.version == version, Investigation.state == run.state,
        Investigation.lease_id == run.lease_id).values(**values))
    if not changed.rowcount:
        db.rollback()
        db.refresh(run)
        return serialize(run)
    record(db, run.tenant_id, run.request_id, "investigation." + state,
        {"investigation_id": run.id, "version": version + 1, "code": code})
    db.commit()
    db.refresh(run)
    return serialize(run)


@router.post("/requests/{request_id}/investigations")
def start(request_id: str, body: StartBody, idempotency_key: str = Header(default=""),
          principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "engineer")
    settings = Settings()
    settings.validate()
    request = scoped(db, ChangeRequest, request_id, principal.tenant_id, actor=principal, write=True)
    require_workspace_ai(db, principal.tenant_id)
    if settings.ai_mode != "nebius" and not settings.investigation_baseline:
        raise HTTPException(503, "Nemotron investigation paused. Saved results remain readable; no substitute AI result is generated.")
    if request.revision != body.revision:
        raise HTTPException(409, "Request revision changed")
    witness = snapshot(db, request_id, principal.tenant_id)
    snapshot_hash, workflow_hash = digest(witness), identity()
    model = settings.nebius_model if settings.ai_mode == "nebius" else "offline-policy"
    def create():
        # A different browser key cannot fork duplicate work on the same snapshot.
        old = db.scalar(select(Investigation).where(Investigation.tenant_id == principal.tenant_id,
            Investigation.request_id == request_id, Investigation.snapshot_hash == snapshot_hash,
            Investigation.workflow_hash == workflow_hash, Investigation.model_id == model))
        if old:
            return {"id": old.id}
        run = Investigation(id=uid(), tenant_id=principal.tenant_id, request_id=request_id,
            actor_id=principal.user_id, snapshot_hash=snapshot_hash, workflow_hash=workflow_hash,
            model_id=model, state="ready", version=0,
            memory={"schema": SCHEMA, "snapshot": witness, "steps": [], "result": None})
        db.add(run)
        db.flush()
        record(db, run.tenant_id, request_id, "investigation.created", {"investigation_id": run.id})
        return {"id": run.id}
    args = (db, principal.tenant_id, "investigation:" + request_id, idempotency_key, body.model_dump(), create)
    try:
        saved = idempotent(*args)
        db.commit()
    except IntegrityError:
        db.rollback()
        saved = idempotent(*args)
        db.commit()
    return serialize(scoped(db, Investigation, saved["id"], principal.tenant_id, actor=principal, write=True))


@router.get("/requests/{request_id}/investigations")
def list_runs(request_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "engineer","manager")
    scoped(db, ChangeRequest, request_id, principal.tenant_id, actor=principal)
    rows = db.scalars(select(Investigation).where(Investigation.tenant_id == principal.tenant_id,
        Investigation.request_id == request_id).order_by(Investigation.created_at.desc(), Investigation.id.desc()).limit(20))
    return [serialize(row) for row in rows]


@router.get("/investigations/{run_id}")
def get_run(run_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "engineer","manager")
    return serialize(scoped(db, Investigation, run_id, principal.tenant_id, actor=principal))


@router.post("/investigations/{run_id}/step")
def step(run_id: str, body: StepBody, http_request: Request,
         principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "engineer")
    run = scoped(db, Investigation, run_id, principal.tenant_id, actor=principal, write=True)
    if run.state in TERMINAL:
        return serialize(run)
    if run.state == "running":
        if aware(run.deadline_at) <= utcnow():
            # Expire the LOCAL lease. Never promise remote cancellation or refund.
            changed = db.execute(update(Investigation).where(Investigation.id == run.id,
                Investigation.version == run.version, Investigation.state == "running").values(
                state="failed", error_code="LOCAL_DEADLINE", lease_id=None, version=run.version + 1))
            if changed.rowcount:
                record(db, run.tenant_id, run.request_id, "investigation.failed",
                    {"investigation_id": run.id, "code": "LOCAL_DEADLINE"})
            db.commit()
            db.refresh(run)
        return serialize(run)
    if body.expected_version > run.version:
        raise HTTPException(409, "Unknown investigation version")
    if body.expected_version < run.version:
        return serialize(run)  # Retried delivery reads the saved step, never repeats inference.
    settings = Settings()
    settings.validate()
    if settings.ai_mode != "nebius" and not settings.investigation_baseline:
        raise HTTPException(503, "Nemotron investigation paused. No model was called.")
    model = settings.nebius_model if settings.ai_mode == "nebius" else "offline-policy"
    if (run.workflow_hash != identity() or model != run.model_id
            or digest(snapshot(db, run.request_id, principal.tenant_id)) != run.snapshot_hash):
        return _finish_state(db, run, "stale", "SNAPSHOT_CHANGED")
    if len(run.memory["steps"]) >= MAX_STEPS:
        return _finish_state(db, run, "failed", "STEP_LIMIT")
    memory = deepcopy(run.memory)
    lease, version = uid(), run.version + 1
    changed = db.execute(update(Investigation).where(Investigation.id == run.id,
        Investigation.version == body.expected_version, Investigation.state == "ready").values(
        state="running", version=version, lease_id=lease,
        deadline_at=utcnow() + timedelta(seconds=settings.ai_timeout + 5)))
    if not changed.rowcount:
        db.rollback()
        db.refresh(run)
        return serialize(run)
    # In the same claim transaction. Failure rolls back the claim, no dispatch.
    reserve_live_call(db, settings, principal.tenant_id)
    record(db, run.tenant_id, run.request_id, "investigation.claimed",
        {"investigation_id": run.id, "version": version, "source": model})
    db.commit()  # Release DB connection before any remote wait.
    started, usage, error, outcome, diagnostics = time.monotonic(), {}, None, None, {}
    def decide(current):
        nonlocal usage
        if model == "offline-policy":
            return offline_decision(current)
        choice, usage = provider_decision(current, settings)
        diagnostics["decision"] = choice.model_dump(exclude={"note"})
        return choice
    try:
        outcome = advance(memory, decide)
    except DecisionFailure as failure:
        error, usage = failure.code, failure.usage
        diagnostics = failure.details
    except httpx.TimeoutException:
        error = "PROVIDER_TIMEOUT"
    except httpx.HTTPStatusError as failure:
        error = "PROVIDER_RATE_LIMIT" if failure.response.status_code == 429 else "PROVIDER_UNAVAILABLE"
    except httpx.RequestError:
        error = "PROVIDER_UNAVAILABLE"
    except (ValueError, TypeError) as failure:
        safe_codes = {"INVALID_TOOL_SEQUENCE", "UNSUPPORTED_CITATION", "STEP_LIMIT"}
        error = str(failure) if str(failure) in safe_codes else "INVALID_AGENT_OUTPUT"
    # Reauthenticate after remote wait; session revocation cannot accept late work.
    db.expire_all()
    # Load only the claimed internal lease first. Authorization must be inside
    # the cleanup boundary so a revoked actor cannot strand it as running.
    # This internal lookup never authorizes returning the saved contents.
    run = scoped(db, Investigation, run_id, principal.tenant_id)
    try:
        fresh = current_principal(http_request, http_request.headers.get("authorization"), db)
        require_role(fresh, "admin", "engineer")
        if fresh != principal:
            raise HTTPException(401, "Session changed")
        from ownstack.team_scope import require_request
        require_request(db,fresh,run.request_id,write=True)
    except HTTPException:
        if run.state == "running" and run.lease_id == lease and run.version == version:
            _finish_state(db, run, "stopped", "SESSION_CHANGED")
        raise
    if run.state != "running" or run.lease_id != lease or run.version != version:
        return serialize(run)
    if aware(run.deadline_at) <= utcnow():
        return _finish_state(db, run, "failed", "LOCAL_DEADLINE")
    if (identity() != run.workflow_hash or Settings() != settings
            or digest(snapshot(db, run.request_id, principal.tenant_id)) != run.snapshot_hash):
        return _finish_state(db, run, "stale", "SNAPSHOT_CHANGED")
    if error:
        memory["failed_steps"] = [*memory.get("failed_steps", []), {"version": version,
            "code": error, "usage": usage, "diagnostics": diagnostics,
            "latency_ms": round((time.monotonic()-started)*1000)}]
        return _finish_state(db, run, "failed", error, memory)
    outcome["step"]["latency_ms"] = round((time.monotonic() - started) * 1000)
    outcome["step"]["usage"] = usage
    memory["steps"].append(outcome["step"])
    memory["result"] = outcome["result"]
    state = "completed" if outcome["result"] else "failed" if len(memory["steps"]) >= MAX_STEPS else "ready"
    return _finish_state(db, run, state, "STEP_LIMIT" if state == "failed" else None, memory)


@router.post("/investigations/{run_id}/stop")
def stop(run_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "engineer")
    run = scoped(db, Investigation, run_id, principal.tenant_id, actor=principal, write=True)
    if run.state not in TERMINAL:
        version = run.version
        changed = db.execute(update(Investigation).where(Investigation.id == run.id,
            Investigation.version == version).values(state="stopped", lease_id=None, version=version + 1))
        if changed.rowcount:
            record(db, run.tenant_id, run.request_id, "investigation.stopped", {"investigation_id": run.id})
        db.commit()
        db.refresh(run)
    return serialize(run)


@router.post("/investigations/{run_id}/retry")
def retry(run_id: str, body: StepBody, principal: Principal = Depends(current_principal),
          db: Session = Depends(db_session)):
    """An explicit bounded retry retains failure memory and consumes no call itself."""
    require_role(principal, "admin", "engineer")
    run = scoped(db, Investigation, run_id, principal.tenant_id, actor=principal, write=True)
    if body.expected_version < run.version:
        return serialize(run)
    if body.expected_version != run.version or run.state not in {"failed", "stopped"}:
        raise HTTPException(409, "Only a current failed or stopped investigation can be retried")
    settings = Settings()
    settings.validate()
    model = settings.nebius_model if settings.ai_mode == "nebius" else "offline-policy"
    if run.workflow_hash != identity() or model != run.model_id or digest(snapshot(db, run.request_id, principal.tenant_id)) != run.snapshot_hash:
        return _finish_state(db, run, "stale", "SNAPSHOT_CHANGED")
    memory = deepcopy(run.memory)
    if memory.get("retry_count", 0) >= 2 or len(memory["steps"]) >= MAX_STEPS:
        raise HTTPException(409, "Bounded retry limit reached; inspect evidence and take over")
    memory["retry_count"] = memory.get("retry_count", 0) + 1
    return _finish_state(db, run, "ready", memory=memory)
