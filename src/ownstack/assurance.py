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
