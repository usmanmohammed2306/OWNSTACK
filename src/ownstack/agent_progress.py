"""Read-only saved progress SSE. This is NOT the upstream model token stream."""
import asyncio
import json
import time
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from starlette.concurrency import run_in_threadpool
from ownstack.auth import current_principal, db_session, require_role
from ownstack.models import Attempt, ChangeRequest, Event, Proposal
from ownstack.policy import Principal, aware
from ownstack.service import scoped, utcnow

router = APIRouter()
WAIT_SECONDS, POLL_SECONDS, MAX_SNAPSHOTS = 25, 0.5, 52
TERMINAL = {"accepted", "failed", "timed_out", "canceled", "superseded"}


class ProgressRecord(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    attempt_id: str
    phase: Literal["receiving", "validated"]
    received_bytes: int = Field(ge=0, le=16_384)
    deltas: int = Field(ge=0, le=512)
    source: Literal["fixture_stream", "provider_stream"]


def saved_progress(db, principal, request_id, project_id, attempt_id, revision):
    """Recheck current scope on every poll; never return text/code or dispatch AI."""
    req = scoped(db, ChangeRequest, request_id, principal.tenant_id, actor=principal)
    if req.project_id != project_id:
        raise HTTPException(404, "Not found")
    if req.current_attempt_id != attempt_id or req.revision != revision:
        raise HTTPException(409, "Progress scope changed")
    attempt = scoped(db, Attempt, attempt_id, principal.tenant_id, actor=principal)
    if attempt.request_id != req.id or attempt.request_revision != revision:
        raise HTTPException(409, "Progress scope changed")
    event = db.scalar(select(Event).where(Event.tenant_id == principal.tenant_id,
        Event.request_id == req.id, Event.event_type == "attempt.stream_progress",
        Event.payload["attempt_id"].as_string() == attempt_id).order_by(Event.created_at.desc(), Event.id.desc()).limit(1))
    progress = {"phase": "not_streamed", "received_bytes": 0, "deltas": 0, "source": "saved_status"}
    if event:
        try:
            parsed = ProgressRecord.model_validate(event.payload)
        except ValidationError:
            raise HTTPException(503, "Progress unavailable") from None
        progress = parsed.model_dump(exclude={"attempt_id"})
    response = None
    if attempt.state == "accepted" and req.accepted_proposal_id:
        proposal = scoped(db, Proposal, req.accepted_proposal_id, principal.tenant_id, actor=principal)
        if (proposal.attempt_id == attempt.id and proposal.request_revision == revision
                and proposal.route in {"configure", "engineering", "refuse"}):
            response = {"proposal_id": proposal.id, "route": proposal.route}
    # Deadline here is an observation only. GET never reaps or mutates the attempt.
    return {"tenant_id": principal.tenant_id, "request_id": req.id, "project_id": project_id,
            "attempt_id": attempt.id, "revision": revision, "state": attempt.state,
            "deadline_elapsed": aware(attempt.deadline_at) <= utcnow(),
            **progress, "terminal": attempt.state in TERMINAL, "response": response}


def frame(event, data):
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


@router.get("/v1/requests/{request_id}/progress")
def progress_feed(request_id: str, request: Request, project_id: str = Query(min_length=1, max_length=40),
                  attempt_id: str = Query(min_length=1, max_length=40), revision: int = Query(ge=1),
                  authorization: str | None = Header(default=None),
                  principal: Principal = Depends(current_principal), db=Depends(db_session)):
    require_role(principal, "admin", "engineer","manager")
    saved_progress(db, principal, request_id, project_id, attempt_id, revision)
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    # Do not retain a DB transaction/connection throughout a slow browser stream.
    db.rollback()

    def snapshot():
        with factory() as connection:
            current = current_principal(request, authorization, connection)
            require_role(current, "admin", "engineer","manager")
            if current != principal:
                raise HTTPException(401, "Session changed")
            return saved_progress(connection, current, request_id, project_id, attempt_id, revision)

    async def events():
        started, sequence = time.monotonic(), 0
        # Reauthenticate before the first frame too: an authorization performed
        # at route entry does not keep a revoked session alive for 25 seconds.
        while sequence < MAX_SNAPSHOTS and time.monotonic() - started < WAIT_SECONDS:
            if await request.is_disconnected():
                return  # Detaches only. Durable work is not canceled by a GET.
            try:
                value = await run_in_threadpool(snapshot)
            except HTTPException as error:
                code = "session_changed" if error.status_code in {401, 403} else "scope_changed" if error.status_code in {404, 409} else "unavailable"
                yield frame("end", {"code": code})
                return
            except SQLAlchemyError:
                yield frame("end", {"code": "unavailable"})
                return
            sequence += 1
            yield frame("snapshot", {**value, "sequence": sequence})
            if value["terminal"]:
                yield frame("end", {"code": "complete"})
                return
            await asyncio.sleep(POLL_SECONDS)
        yield frame("end", {"code": "wait_limit"})

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-store", "X-Accel-Buffering": "no",
        "X-OwnStack-Stream": "saved-progress-not-model-tokens"})
