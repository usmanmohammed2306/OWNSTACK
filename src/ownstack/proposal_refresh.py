"""AI-free recovery from host drift. Refresh is not approval or activation."""
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from ownstack.auth import current_principal, db_session, require_role
from ownstack.models import ChangeRequest, Contract, Evidence, Project, Proposal, User
from ownstack.policy import CONTRACT, Principal, aware, digest
from ownstack.service import host_preview, idempotent, manual_handoff, record, scoped

router = APIRouter()


class RefreshBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_hash: str = Field(pattern="^[a-f0-9]{64}$")
    review_hash: str = Field(pattern="^[a-f0-9]{64}$")
    reason: str = Field(min_length=10, max_length=500, pattern=r"\S")


def refresh_review(db, proposal, request, principal):
    """Bind unchanged intent and the current host preview to this reviewer."""
    if (proposal.route != "configure" or proposal.status != "ready"
            or request.status != "awaiting_approval" or request.accepted_proposal_id != proposal.id
            or request.revision != proposal.request_revision):
        raise HTTPException(409, "Only the current unapproved access proposal can be refreshed")
    parameters = {"project_id": request.project_id, "viewer_id": request.viewer_id,
                  "expires_at": aware(request.expires_at).isoformat() if request.expires_at else None}
    original_intent = digest({"text": request.text, "revision": request.revision})
    evidence = db.scalar(select(Evidence.id).where(Evidence.tenant_id == principal.tenant_id,
        Evidence.request_id == request.id, Evidence.kind == "model_interpretation",
        Evidence.subject_hash == original_intent).limit(1))
    if parameters != proposal.parameters or not evidence:
        raise HTTPException(409, "Original intent changed or its evidence is unavailable; create a new request")
    contract = db.get(Contract, (proposal.contract_id, proposal.contract_version))
    if (proposal.contract_id != CONTRACT["id"] or proposal.contract_version != CONTRACT["version"]
            or contract is None or contract.manifest != CONTRACT
            or contract.manifest_hash != digest(CONTRACT) or proposal.contract_hash != contract.manifest_hash):
        raise HTTPException(409, "Contract changed; refreshing cannot authorize a different capability")
    viewer = scoped(db, User, request.viewer_id or "", principal.tenant_id)
    if not viewer.enabled:
        raise HTTPException(409, "Viewer is disabled; refreshing cannot restore account access")
    preview = host_preview(db, request)
    snapshot = {"schema": "ownstack.proposal-refresh.v1", "actor_id": principal.user_id,
        "tenant_id": principal.tenant_id, "request_id": request.id, "request_revision": request.revision,
        "proposal_id": proposal.id, "proposal_hash": proposal.proposal_hash,
        "intent_hash": original_intent, "parameters": parameters, "contract_hash": contract.manifest_hash,
        "saved_preview_hash": proposal.preview_hash, "fresh_preview_hash": preview["snapshot_hash"],
        "can_refresh": preview["snapshot_hash"] != proposal.preview_hash}
    return {**snapshot, "review_hash": digest(snapshot), "preview": preview,
        "notice": "Creates a new proposal revision with the same request, scope and expiry. "
                  "The original stays in history. No access is granted, no expiry is extended, "
                  "and a tenant admin must preview and approve the new exact proposal."}


@router.get("/v1/proposals/{proposal_id}/refresh-review")
def get_refresh_review(proposal_id: str, response: Response,
                       principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "engineer")
    proposal = scoped(db, Proposal, proposal_id, principal.tenant_id)
    request = scoped(db, ChangeRequest, proposal.request_id, principal.tenant_id)
    response.headers["Cache-Control"] = "no-store"
    return refresh_review(db, proposal, request, principal)


@router.post("/v1/proposals/{proposal_id}/refresh")
def refresh_proposal(proposal_id: str, body: RefreshBody, idempotency_key: str | None = Header(default=None),
                     principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "engineer")
    proposal = db.scalar(select(Proposal).where(Proposal.id == proposal_id,
        Proposal.tenant_id == principal.tenant_id).with_for_update().execution_options(populate_existing=True))
    if proposal is None:
        raise HTTPException(404, "Not found")
    request = db.scalar(select(ChangeRequest).where(ChangeRequest.id == proposal.request_id,
        ChangeRequest.tenant_id == principal.tenant_id).with_for_update().execution_options(populate_existing=True))
    if request is None:
        raise HTTPException(404, "Not found")

    def create():
        if body.proposal_hash != proposal.proposal_hash:
            raise HTTPException(409, "Exact original proposal hash required")
        # Match approval's proposal-first ordering and serialize the project and
        # identity while recomputing the reviewed effect. No DB commit mid-flow.
        for model, object_id in ((Project, request.project_id), (User, request.viewer_id)):
            db.scalar(select(model).where(model.id == object_id, model.tenant_id == principal.tenant_id)
                      .with_for_update().execution_options(populate_existing=True))
        review = refresh_review(db, proposal, request, principal)
        if not review["can_refresh"]:
            raise HTTPException(409, "Host preview has not changed; keep the existing proposal")
        if body.review_hash != review["review_hash"]:
            raise HTTPException(409, "Refresh review changed; review the current host state again")
        previous_revision = request.revision
        proposal.status = "superseded"
        request.revision += 1
        request.status = "new"
        result = manual_handoff(db, request, principal)
        replacement = db.get(Proposal, result["proposal_id"])
        if replacement.route != "configure" or replacement.preview_hash != review["fresh_preview_hash"]:
            raise HTTPException(409, "Host changed during refresh; no replacement was saved")
        record(db, principal.tenant_id, request.id, "proposal.refreshed", {
            "actor_id": principal.user_id, "reason": body.reason, "review_hash": body.review_hash,
            "previous_proposal_id": proposal.id, "previous_proposal_hash": proposal.proposal_hash,
            "proposal_id": replacement.id, "proposal_hash": replacement.proposal_hash,
            "previous_revision": previous_revision, "revision": request.revision,
            "approval_required": True, "ai_call": False})
        return {**result, "previous_proposal_id": proposal.id, "revision": request.revision,
                "proposal_hash": replacement.proposal_hash, "approval_required": True}

    intent = {"proposal_id": proposal_id, "actor_id": principal.user_id, **body.model_dump()}
    result = idempotent(db, principal.tenant_id, "refresh_proposal", idempotency_key or "", intent, create)
    db.commit()
    return result
