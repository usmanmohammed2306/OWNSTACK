from datetime import datetime, timedelta, timezone
import re
from types import SimpleNamespace
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from ownstack.config import Settings
from ownstack.ai import AIResult
from sqlalchemy.orm import Session
from ownstack.models import (Approval, Attempt, ChangeRequest, Contract, Document, EngineeringItem,
                             Event, Evidence, Idempotency, InferenceBudget, Outbox, Project, Proposal,
                             RateWindow, RuntimePulse, User, Variation, WebSession)
from ownstack.policy import CONTRACT, Principal, aware, can_read, digest, validate_grant
from ownstack.replay import replay_grant


def uid() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def mark_pulse(db: Session, component: str) -> None:
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    statement = insert(RuntimePulse).values(component=component, touched_at=utcnow())
    db.execute(statement.on_conflict_do_update(index_elements=[RuntimePulse.component],
                                               set_={"touched_at": utcnow()}))


def scoped(db: Session, model, object_id: str, tenant_id: str):
    obj = db.scalar(select(model).where(model.id == object_id, model.tenant_id == tenant_id))
    if obj is None:
        raise HTTPException(404, "Not found")
    return obj


def record(db: Session, tenant_id: str, request_id: str, event_type: str, payload: dict) -> None:
    event = Event(id=uid(), tenant_id=tenant_id, request_id=request_id, event_type=event_type, payload=payload)
    db.add(event)
    db.flush()
    db.add(Outbox(id=uid(), tenant_id=tenant_id, event_id=event.id, topic=event_type, payload=payload))


def idempotent(db: Session, tenant_id: str, operation: str, key: str, body: dict, create):
    if not key or len(key) > 100:
        raise HTTPException(422, "Idempotency-Key required, maximum 100 characters")
    body_hash = digest(body)
    old = db.scalar(select(Idempotency).where(Idempotency.tenant_id == tenant_id, Idempotency.operation == operation, Idempotency.key == key))
    if old:
        if old.request_hash != body_hash:
            raise HTTPException(409, "Idempotency key reused with different body")
        return old.response
    response = create()
    db.add(Idempotency(id=uid(), tenant_id=tenant_id, operation=operation, key=key, request_hash=body_hash, response=response))
    return response


def reserve_live_call(db: Session, settings: Settings) -> None:
    """Reserve before dispatch. A failed or timed-out remote call still consumes one slot."""
    if settings.ai_mode != "nebius":
        return
    changed = db.execute(update(InferenceBudget)
                         .where(InferenceBudget.id == "global",
                                InferenceBudget.reserved_calls < settings.max_live_calls)
                         .values(reserved_calls=InferenceBudget.reserved_calls + 1))
    if changed.rowcount != 1:
        raise HTTPException(429, "Live inference call cap reached or budget not initialized")


def create_request(db: Session, principal: Principal, body: dict, key: str) -> dict:
    def create():
        project_id = body.get("project_id")
        viewer_id = body.get("viewer_id")
        if project_id and not db.scalar(select(Project.id).where(Project.id == project_id, Project.tenant_id == principal.tenant_id)):
            raise HTTPException(404, "Project not found")
        if viewer_id and not db.scalar(select(User.id).where(User.id == viewer_id, User.tenant_id == principal.tenant_id)):
            raise HTTPException(404, "Viewer not found")
        request = ChangeRequest(id=uid(), tenant_id=principal.tenant_id, requester_id=principal.user_id,
                                text=body["text"], kind=body["kind"], project_id=project_id,
                                viewer_id=viewer_id, expires_at=body.get("expires_at"), status="new", revision=1)
        db.add(request)
        db.flush()
        record(db, request.tenant_id, request.id, "request.created", {"kind": request.kind})
        return {"id": request.id, "status": request.status, "revision": request.revision}
    return idempotent(db, principal.tenant_id, "create_request", key, body, create)


def start_attempt(db: Session, request: ChangeRequest, model_id: str, timeout_seconds: float,
                  settings: Settings | None = None) -> Attempt:
    current = db.get(Attempt, request.current_attempt_id) if request.current_attempt_id else None
    at = utcnow()
    if current and current.state in {"queued", "running"} and aware(current.deadline_at) > at:
        return current
    if current and current.state in {"queued", "running"}:
        current.state, current.error_code, current.finished_at = "timed_out", "DEADLINE", at
        record(db, request.tenant_id, request.id, "attempt.timed_out", {"attempt_id": current.id})
    if settings:
        reserve_live_call(db, settings)
    count = db.scalar(select(func.count(Attempt.id)).where(Attempt.request_id == request.id, Attempt.request_revision == request.revision)) or 0
    attempt = Attempt(id=uid(), tenant_id=request.tenant_id, request_id=request.id,
                      number=count + 1, request_revision=request.revision, state="queued",
                      model_id=model_id, deadline_at=at + timedelta(seconds=timeout_seconds))
    db.add(attempt)
    request.current_attempt_id = attempt.id
    request.status = "interpreting"
    record(db, request.tenant_id, request.id, "attempt.queued", {"attempt_id": attempt.id, "number": attempt.number})
    return attempt


def claim_attempt(db: Session, attempt_id: str) -> Attempt | None:
    attempt = db.get(Attempt, attempt_id)
    if not attempt or attempt.state != "queued":
        return None
    request = db.scalar(select(ChangeRequest).where(ChangeRequest.id == attempt.request_id)
                        .with_for_update().execution_options(populate_existing=True))
    db.refresh(attempt)
    if attempt.state != "queued":
        return None
    if request.current_attempt_id != attempt.id:
        attempt.state = "superseded"
        return None
    if aware(attempt.deadline_at) <= utcnow():
        timeout_attempt(db, attempt)
        return None
    claimed_at = utcnow()
    changed = db.execute(update(Attempt).where(Attempt.id == attempt_id, Attempt.state == "queued")
                         .values(state="running", started_at=claimed_at))
    if changed.rowcount != 1:
        return None
    db.refresh(attempt)
    record(db, attempt.tenant_id, attempt.request_id, "attempt.started", {"attempt_id": attempt.id})
    return attempt


def timeout_attempt(db: Session, attempt: Attempt) -> bool:
    """Persist a local deadline, without claiming the remote provider stopped."""
    at = utcnow()
    request = db.scalar(select(ChangeRequest).where(ChangeRequest.id == attempt.request_id)
                        .with_for_update().execution_options(populate_existing=True))
    changed = db.execute(update(Attempt).where(Attempt.id == attempt.id,
                                               Attempt.state.in_(("queued", "running")),
                                               Attempt.deadline_at <= at)
                         .values(state="timed_out", error_code="DEADLINE", finished_at=at)
                         .execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        return False
    db.refresh(attempt)
    if request.current_attempt_id == attempt.id:
        request.status = "failed"
    record(db, attempt.tenant_id, attempt.request_id, "attempt.timed_out",
           {"attempt_id": attempt.id, "remote_cancellation_verified": False})
    return True


def reap_expired_attempts(db: Session) -> int:
    expired = db.scalars(select(Attempt).where(Attempt.state.in_(("queued", "running")),
                                               Attempt.deadline_at <= utcnow())).all()
    return sum(timeout_attempt(db, attempt) for attempt in expired)


def reap_operations(db: Session) -> int:
    expired = db.scalars(select(EngineeringItem).where(
        EngineeringItem.status.in_(("drafting", "checking")), EngineeringItem.operation_deadline <= utcnow())).all()
    count = 0
    for item in expired:
        status = "draft_failed" if item.status == "drafting" else "checks_failed"
        changed = db.execute(update(EngineeringItem).where(
            EngineeringItem.id == item.id, EngineeringItem.operation_id == item.operation_id,
            EngineeringItem.status == item.status).values(
                status=status, operation_id=None, operation_deadline=None))
        if changed.rowcount:
            count += 1
            record(db, item.tenant_id, item.request_id, "engineering.operation_timed_out",
                   {"item_id": item.id, "remote_cancellation_verified": False})
    at = utcnow()
    db.execute(delete(WebSession).where(WebSession.expires_at <= at))
    db.execute(delete(RateWindow).where(RateWindow.expires_at <= at))
    return count


def claim_engineering(db: Session, item: EngineeringItem, action: str, seconds: float) -> str:
    operation_id = uid()
    allowed = ("needs_engineer", "draft_failed") if action == "drafting" else ("drafted", "checks_failed", "checks_passed")
    changed = db.execute(update(EngineeringItem).where(
        EngineeringItem.id == item.id, EngineeringItem.status.in_(allowed),
        EngineeringItem.human_decision.is_(None)).values(
            status=action, operation_id=operation_id,
            operation_deadline=utcnow() + timedelta(seconds=seconds))
        .execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise HTTPException(409, "An operation is already running or a human decision exists")
    db.refresh(item)
    return operation_id


def host_preview(db: Session, request: ChangeRequest) -> dict:
    project = scoped(db, Project, request.project_id or "", request.tenant_id)
    viewer = scoped(db, User, request.viewer_id or "", request.tenant_id)
    intent = request.text.lower()
    forbidden = ("pdf", "export", "write", "edit", "admin", "delete", "bypass", "skip approval", "permanent")
    if (not re.search(r"\bread[- ]only\b", intent) or "access" not in intent
            or project.name.lower() not in intent or any(word in intent for word in forbidden)):
        raise HTTPException(422, "Request text does not match the temporary read-only access contract")
    other_project_names = db.scalars(select(Project.name).where(Project.tenant_id != request.tenant_id)).all()
    if any(name.lower() in intent for name in other_project_names):
        raise HTTPException(422, "Request text names another tenant's project")
    if viewer.role != "contractor":
        raise HTTPException(422, "Capability requires a contractor viewer")
    if request.expires_at is None:
        raise HTTPException(422, "Expiry required")
    try:
        validate_grant(request.tenant_id, project.tenant_id, viewer.tenant_id, request.expires_at, utcnow())
    except ValueError as error:
        raise HTTPException(422, str(error))
    docs = db.scalars(select(Document).where(Document.tenant_id == request.tenant_id, Document.project_id == project.id).order_by(Document.id)).all()
    variations = db.scalars(select(Variation).where(Variation.tenant_id == request.tenant_id, Variation.project_id == project.id)).all()
    principal = Principal(viewer.id, viewer.tenant_id, viewer.role)
    before = can_read(principal, project.tenant_id, project.id, variations, utcnow())
    candidate = SimpleNamespace(tenant_id=request.tenant_id, project_id=project.id, viewer_id=viewer.id,
                                state="active", starts_at=utcnow(), expires_at=request.expires_at)
    after = can_read(principal, project.tenant_id, project.id, [*variations, candidate], utcnow())
    replay = replay_grant(db, request.tenant_id, project.id, viewer.id, request.expires_at, utcnow())
    if replay["unexpected_delta_count"]:
        raise HTTPException(409, "Counterfactual replay found an unexpected effect")
    if not replay["intended_delta_observed"]:
        raise HTTPException(409, "Grant would have no new effect; revoke or revise the existing variation")
    snapshot = {"tenant_id": request.tenant_id, "project_id": project.id, "project_revision": project.revision,
                "viewer_id": viewer.id, "expires_at": aware(request.expires_at).isoformat(),
                "document_digests": [(doc.id, digest(doc.body)) for doc in docs],
                "before": before, "after": after, "visible_document_ids": [doc.id for doc in docs] if after else [],
                "replay": replay}
    return {"before": before, "after": after, "visible_documents": [{"id": d.id, "title": d.title} for d in docs] if after else [],
            "expires_at": snapshot["expires_at"], "snapshot_hash": digest(snapshot),
            "counterfactual": {"checks": replay["checks"], "intended_delta_observed": replay["intended_delta_observed"],
                               "unexpected_delta_count": replay["unexpected_delta_count"]},
            "limitations": "Finite replay over the current synthetic host fixture. Not a production observation or exhaustive security proof."}


def accept_result(db: Session, attempt_id: str, result) -> bool:
    attempt = db.get(Attempt, attempt_id)
    if not attempt:
        return False
    request = db.scalar(select(ChangeRequest).where(ChangeRequest.id == attempt.request_id)
                        .with_for_update().execution_options(populate_existing=True))
    db.refresh(attempt)
    at = utcnow()
    if attempt.state == "accepted":
        # A redelivered result is not a new acceptance and must not rewrite the
        # terminal history behind the already saved proposal.
        record(db, attempt.tenant_id, attempt.request_id, "attempt.duplicate_discarded",
               {"attempt_id": attempt.id})
        return False
    if request.current_attempt_id != attempt.id or request.revision != attempt.request_revision or aware(attempt.deadline_at) <= at or attempt.state != "running":
        attempt.state, attempt.finished_at = "superseded", at
        record(db, attempt.tenant_id, attempt.request_id, "attempt.late_discarded", {"attempt_id": attempt.id})
        return False
    route, reason = result.route, result.reason
    contract = db.get(Contract, (CONTRACT["id"], CONTRACT["version"]))
    preview = None
    if request.kind == "feature":
        route = "engineering" if route != "refuse" else "refuse"
    elif route == "configure":
        try:
            preview = host_preview(db, request)
        except HTTPException as error:
            route, reason = "refuse", f"Deterministic policy rejected the request: {error.detail}"
    if route not in {"configure", "engineering", "refuse"}:
        route, reason = "refuse", "Unsupported route"
    parameters = {"project_id": request.project_id, "viewer_id": request.viewer_id,
                  "expires_at": aware(request.expires_at).isoformat() if request.expires_at else None}
    fields = {"request_id": request.id, "request_revision": request.revision, "route": route,
              "reason": reason, "parameters": parameters, "contract_hash": contract.manifest_hash if route == "configure" else None,
              "preview_hash": preview["snapshot_hash"] if preview else None}
    proposal = Proposal(id=uid(), tenant_id=request.tenant_id, request_id=request.id, attempt_id=attempt.id,
                        route=route, reason=reason, parameters=parameters, request_revision=request.revision,
                        contract_id=contract.id if route == "configure" else None,
                        contract_version=contract.version if route == "configure" else None,
                        contract_hash=fields["contract_hash"], preview_hash=fields["preview_hash"],
                        proposal_hash=digest(fields), status="ready")
    db.add(proposal)
    db.flush()
    if preview:
        db.add(Evidence(id=uid(), tenant_id=request.tenant_id, request_id=request.id,
                        kind="counterfactual_preview", subject_hash=preview["snapshot_hash"],
                        result=preview["counterfactual"], limitation=preview["limitations"]))
    if route == "engineering":
        db.add(EngineeringItem(id=uid(), tenant_id=request.tenant_id, request_id=request.id))
    request.accepted_proposal_id = proposal.id
    request.status = {"configure": "awaiting_approval", "engineering": "engineering", "refuse": "refused"}[route]
    db.add(Evidence(id=uid(), tenant_id=request.tenant_id, request_id=request.id,
                    kind="model_interpretation", subject_hash=digest({"text": request.text, "revision": request.revision}),
                    result={"proposed_route": result.route, "accepted_route": route,
                            "reason": result.reason, "model_id": result.model_id,
                            "latency_ms": result.latency_ms, "input_tokens": result.input_tokens,
                            "output_tokens": result.output_tokens,
                            "live": result.model_id not in {"fixture", "human-ai-off"}},
                    limitation="Model interpretation is not an authorization decision, preview observation, or security proof."))
    attempt.state, attempt.finished_at, attempt.latency_ms = "accepted", at, result.latency_ms
    attempt.model_id, attempt.input_tokens, attempt.output_tokens = result.model_id, result.input_tokens, result.output_tokens
    record(db, request.tenant_id, request.id, "proposal.ready", {"proposal_id": proposal.id, "route": route})
    return True


def manual_handoff(db: Session, request: ChangeRequest, principal: Principal) -> dict:
    """Engineer-controlled, AI-free proposal through the same policy and approval path."""
    if principal.role != "engineer":
        raise HTTPException(403, "Engineer required")
    if request.status not in {"new", "failed", "refused"}:
        raise HTTPException(409, "Request is already processing or has a current proposal")
    attempt = start_attempt(db, request, "human-ai-off", 30)
    db.flush()
    if not claim_attempt(db, attempt.id):
        raise HTTPException(409, "Could not claim manual handoff")
    route = "configure" if request.kind == "access" else "engineering"
    result = AIResult(route, "Engineer-created proposal without AI inference.", "human-ai-off", 0, None, None)
    if not accept_result(db, attempt.id, result):
        raise HTTPException(409, "Manual handoff was superseded")
    record(db, request.tenant_id, request.id, "proposal.manual_handoff",
           {"actor_id": principal.user_id, "proposal_id": request.accepted_proposal_id})
    return {"request_id": request.id, "status": request.status,
            "proposal_id": request.accepted_proposal_id, "ai_call": False}


def fail_attempt(db: Session, attempt_id: str, error_code: str) -> None:
    attempt = db.get(Attempt, attempt_id)
    if not attempt or attempt.state != "running":
        return
    request = db.scalar(select(ChangeRequest).where(ChangeRequest.id == attempt.request_id)
                        .with_for_update().execution_options(populate_existing=True))
    db.refresh(attempt)
    if attempt.state != "running":
        return
    if request.current_attempt_id != attempt.id or aware(attempt.deadline_at) <= utcnow():
        timeout_attempt(db, attempt)
        return
    attempt.state, attempt.error_code, attempt.finished_at = "failed", error_code[:80], utcnow()
    if request.current_attempt_id == attempt.id:
        request.status = "failed"
    record(db, attempt.tenant_id, attempt.request_id, "attempt.failed", {"attempt_id": attempt.id, "error_code": attempt.error_code})


def approve(db: Session, proposal: Proposal, principal: Principal, supplied_hash: str, key: str) -> dict:
    if principal.role != "admin":
        raise HTTPException(403, "Tenant admin required")
    body = {"proposal_id": proposal.id, "proposal_hash": supplied_hash, "actor_id": principal.user_id}
    def create():
        request = scoped(db, ChangeRequest, proposal.request_id, principal.tenant_id)
        if proposal.route != "configure" or proposal.status != "ready" or request.accepted_proposal_id != proposal.id or request.revision != proposal.request_revision:
            raise HTTPException(409, "Stale or nonconfigurable proposal")
        if proposal.proposal_hash != supplied_hash:
            raise HTTPException(409, "Exact proposal hash mismatch")
        contract = db.get(Contract, (proposal.contract_id, proposal.contract_version))
        if contract is None or contract.manifest_hash != proposal.contract_hash:
            raise HTTPException(409, "Contract changed")
        # Serialize grants on the host project, including approvals of different proposals.
        db.scalar(select(Project).where(Project.id == request.project_id,
                                        Project.tenant_id == principal.tenant_id).with_for_update())
        fresh = host_preview(db, request)
        if fresh["snapshot_hash"] != proposal.preview_hash:
            raise HTTPException(409, "Host preview changed; interpret again")
        variation = Variation(id=uid(), tenant_id=request.tenant_id, project_id=request.project_id,
                              viewer_id=request.viewer_id, proposal_id=proposal.id, state="active",
                              starts_at=utcnow(), expires_at=request.expires_at)
        db.add(Approval(id=uid(), tenant_id=request.tenant_id, proposal_id=proposal.id,
                        proposal_hash=proposal.proposal_hash, actor_id=principal.user_id))
        db.add(variation)
        proposal.status, request.status = "approved", "active"
        record(db, request.tenant_id, request.id, "variation.activated", {"variation_id": variation.id, "proposal_hash": proposal.proposal_hash})
        return {"variation_id": variation.id, "status": "active", "host_enforcement": "shared_fixture_database"}
    return idempotent(db, principal.tenant_id, "approve", key, body, create)
