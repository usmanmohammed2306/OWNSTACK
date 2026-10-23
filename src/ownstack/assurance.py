"""Read-only, tenant-scoped operational reports. Findings are not certifications."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from ownstack.auth import current_principal, db_session, require_role
from ownstack.models import (Approval, Attempt, ChangeRequest, Contract, DeliveryReceipt, Document,
    EngineeringItem, Event, Evidence, HostObservation, IdentityEvent, Outbox, Project, Proposal, User, Variation)
from ownstack.repair_models import RepairRun
from ownstack.policy import Principal, aware, digest
from ownstack.service import host_preview, scoped, utcnow

router = APIRouter(prefix="/v1/assurance")
REPORTS = {}


def report(key, title, description, filters=(), required=(), roles=("admin", "engineer")):
    def register(function):
        REPORTS[key] = {"key": key, "title": title, "description": description,
                        "filters": list(filters), "required": list(required), "roles": list(roles), "run": function}
        return function
    return register


@dataclass
class Context:
    db: Session
    principal: Principal
    at: datetime
    limit: int
    days: int
    scope: dict
    truncated: bool = False

    def collect(self, statement):
        rows = self.db.execute(statement.limit(self.limit + 1)).mappings().all()
        self.truncated |= len(rows) > self.limit
        return [{key: aware(value).isoformat() if isinstance(value, datetime) else value
                 for key, value in row.items()} for row in rows[:self.limit]]

    def rows(self, model, columns, *conditions):
        fields = [getattr(model, name) for name in columns.split()]
        statement = select(*fields).where(model.tenant_id == self.principal.tenant_id, *conditions)
        mapping = {name: getattr(model, name, None) for name in ("project_id", "viewer_id", "request_id")}
        if model == ChangeRequest: mapping['request_id'] = model.id
        if model == User: mapping['viewer_id'] = model.id
        if model == HostObservation: mapping['viewer_id'] = model.actor_id
        for name, value in self.scope.items():
            if mapping.get(name) is None: raise HTTPException(422, "Filter unsupported by this report")
            statement = statement.where(mapping[name] == value)
        return self.collect(statement.order_by(model.id))


@router.get("/catalogue")
def catalogue(principal: Principal = Depends(current_principal)):
    require_role(principal, "admin", "engineer")
    return [{key: value for key, value in spec.items() if key != "run"}
            for spec in REPORTS.values() if principal.role in spec["roles"]]


@router.get("/{report_id}")
def run_report(report_id: str, project_id: str | None = Query(default=None, max_length=200),
               viewer_id: str | None = Query(default=None, max_length=200),
               request_id: str | None = Query(default=None, max_length=200),
               limit: int = Query(default=25, ge=1, le=100), days: int = Query(default=7, ge=1, le=30),
               principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "engineer")
    spec = REPORTS.get(report_id)
    if spec is None: raise HTTPException(404, "Report not found")
    require_role(principal, *spec["roles"])
    scope = {key: value for key, value in {"project_id": project_id, "viewer_id": viewer_id, "request_id": request_id}.items() if value is not None}
    if set(scope) - set(spec["filters"]) or set(spec["required"]) - set(scope):
        raise HTTPException(422, "Supply only supported filters and all required scope")
    for key, model in (("project_id", Project), ("viewer_id", User), ("request_id", ChangeRequest)):
        if key in scope: scoped(db, model, scope[key], principal.tenant_id)
    ctx = Context(db, principal, utcnow(), limit, days, scope)
    items = spec["run"](ctx)
    return {"report": report_id, "tenant_id": principal.tenant_id, "scope": scope,
            "evaluated_at": ctx.at.isoformat(), "items": items, "truncated": ctx.truncated,
            "notice": "Read-only diagnostic snapshot, not a security certification or permission. "
                      "Top-level result pages are bounded, not database latency or nested policy work; "
                      "partial or empty findings do not prove absence of problems. "
                      "No AI call, observed document read, grant, release or deployment is performed."}


@report("approval-inbox", "Approval inbox", "Pending requests ordered within a bounded tenant-local review.",
        filters=("project_id", "viewer_id", "request_id"))
def approval_inbox(ctx):
    return ctx.rows(ChangeRequest, "id project_id viewer_id revision created_at expires_at",
                    ChangeRequest.status == "awaiting_approval")


@report("stale-previews", "Preview drift monitor", "Recompute pending previews without replacing proposals or granting access.", filters=("request_id",))
def stale_previews(ctx):
    findings = []
    for row in ctx.rows(Proposal, "id request_id preview_hash", Proposal.route == "configure", Proposal.status == "ready"):
        request = scoped(ctx.db, ChangeRequest, row["request_id"], ctx.principal.tenant_id)
        try:
            preview = host_preview(ctx.db, request)
            if preview["snapshot_hash"] != row["preview_hash"]:
                findings.append({"proposal_id": row["id"], "request_id": request.id, "finding": "host_snapshot_changed"})
        except HTTPException as error:
            findings.append({"proposal_id": row["id"], "request_id": request.id, "finding": "preview_blocked", "status_code": error.status_code})
    return findings


@report("revision-lineage", "Proposal revision lineage", "Inspect preserved proposal subjects and revision states without exporting request text.", filters=("request_id",), required=("request_id",))
def revision_lineage(ctx):
    return ctx.rows(Proposal, "id request_id request_revision proposal_hash preview_hash status", Proposal.route == "configure")


@report("expired-intent", "Expired approval intent", "Pending requests whose original expiry elapsed; this does not extend them.", filters=("project_id", "viewer_id", "request_id"))
def expired_intent(ctx):
    return ctx.rows(ChangeRequest, "id project_id viewer_id revision expires_at", ChangeRequest.status == "awaiting_approval", ChangeRequest.expires_at <= ctx.at)


@report("pending-work", "Pending attempt queue", "Saved queued or running attempts with unexpired deadlines. Reading cannot dispatch inference.", filters=("request_id",))
def pending_work(ctx):
    return ctx.rows(Attempt, "id request_id request_revision number state model_id deadline_at", Attempt.state.in_(("queued", "running")), Attempt.deadline_at > ctx.at)


@report("overdue-work", "Overdue attempt recovery", "Unfinished attempts past their local deadline; not proof remote inference stopped.", filters=("request_id",))
def overdue_work(ctx):
    return ctx.rows(Attempt, "id request_id request_revision state model_id deadline_at", Attempt.state.in_(("queued", "running")), Attempt.deadline_at <= ctx.at)


@report("attempt-failures", "Attempt failure triage", "Terminal failure states and bounded error codes, without prompts or model responses.", filters=("request_id",))
def attempt_failures(ctx):
    return ctx.rows(Attempt, "id request_id request_revision state model_id error_code finished_at", Attempt.state.in_(("failed", "timed_out", "canceled", "superseded")))


@report("discarded-results", "Discarded answer audit", "Late or duplicate answer events. Private event payloads are omitted.", filters=("request_id",))
def discarded_results(ctx):
    return ctx.rows(Event, "id request_id event_type created_at", Event.event_type.in_(("attempt.late_discarded", "attempt.duplicate_discarded")))


@report("active-exposure", "Current grant exposure", "Time-effective grant records, not proof that a disabled account can authenticate.", filters=("project_id", "viewer_id"))
def active_exposure(ctx):
    return ctx.rows(Variation, "id project_id viewer_id starts_at expires_at revision", Variation.state == "active", Variation.starts_at <= ctx.at, Variation.expires_at > ctx.at)


@report("expiry-docket", "Upcoming expiry docket", "Effective grants expiring within the day window. Overlapping grants can still retain access.", filters=("project_id", "viewer_id"))
def expiry_docket(ctx):
    return ctx.rows(Variation, "id project_id viewer_id expires_at revision", Variation.state == "active", Variation.starts_at <= ctx.at, Variation.expires_at > ctx.at, Variation.expires_at <= ctx.at + timedelta(days=ctx.days))


@report("expiry-cleanup", "Expired grant ledger", "Stored active records whose expiry denies the grant. Enforcement needs no cleanup job.", filters=("project_id", "viewer_id"))
def expiry_cleanup(ctx):
    return ctx.rows(Variation, "id project_id viewer_id state expires_at", Variation.state == "active", Variation.expires_at <= ctx.at)


@report("scheduled-access", "Scheduled grant starts", "Future active grant records with nonempty intervals, not current permission.", filters=("project_id", "viewer_id"))
def scheduled_access(ctx):
    return ctx.rows(Variation, "id project_id viewer_id starts_at expires_at", Variation.state == "active", Variation.starts_at > ctx.at, Variation.expires_at > Variation.starts_at)


@report("disabled-exposure", "Disabled-account grant review", "Grants retained for disabled subjects. Re-enabling can make these grants relevant again.", filters=("project_id", "viewer_id"))
def disabled_exposure(ctx):
    disabled = select(User.id).where(User.tenant_id == ctx.principal.tenant_id, User.enabled.is_(False))
    return ctx.rows(Variation, "id project_id viewer_id expires_at", Variation.state == "active", Variation.expires_at > ctx.at, Variation.viewer_id.in_(disabled))


@report("unused-grants", "Unobserved grant review", "Grants with no saved allowed variation-attributed check. Absence is not proof of no real-world use.", filters=("project_id", "viewer_id"))
def unused_grants(ctx):
    used = select(HostObservation.variation_id).where(HostObservation.tenant_id == ctx.principal.tenant_id, HostObservation.allowed.is_(True), HostObservation.basis == "variation", HostObservation.variation_id.is_not(None))
    return ctx.rows(Variation, "id project_id viewer_id starts_at expires_at", Variation.state == "active", Variation.expires_at > ctx.at, Variation.id.not_in(used))
