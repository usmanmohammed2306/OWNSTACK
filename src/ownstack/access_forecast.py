"""Bounded, conditional access forecast. Never use it to authorize a read."""
from datetime import timedelta
from sqlalchemy import select
from ownstack.host_access import host_read_decision
from ownstack.models import Variation
from ownstack.governance import authorized_variation
from ownstack.authorization_clock import authorization_time
from ownstack.policy import Principal, ReadDecision, aware, read_decision

MAX_FORECAST_GRANTS = 128
FORECAST_DAYS = 7


def access_forecast(db, viewer, project, at):
    """Evaluate one saved grant set at its exact start/expiry boundaries.

    Between boundaries the pure policy's boolean cannot change. A grant handing
    off to another at the same instant is not an access change. Refuse to infer
    expiry from a truncated set; the protected-read selector remains independent.
    """
    at = authorization_time(db,aware(at))
    through = at + timedelta(days=FORECAST_DAYS)
    principal = Principal(viewer.id, viewer.tenant_id, viewer.role)
    forecast = {"status": "no_scheduled_change", "through": through.isoformat(),
                "next_change": None,
                "notice": "Conditional forecast, not an observed read or permission. Assumes the "
                          "current account, role and saved grants stay unchanged. New approvals, "
                          "revokes and account changes require a fresh check."}
    if not viewer.enabled:
        return ReadDecision(False, "denied"), forecast
    if viewer.role != "contractor":
        return host_read_decision(db,principal,project.tenant_id,project.id,at), forecast
    rows = db.scalars(select(Variation).where(
        Variation.tenant_id == project.tenant_id, Variation.project_id == project.id,
        Variation.viewer_id == viewer.id, Variation.state == "active",
        Variation.expires_at > at, Variation.starts_at <= through,
        authorized_variation(),
    ).order_by(Variation.id).limit(MAX_FORECAST_GRANTS + 1)).all()
    if len(rows) > MAX_FORECAST_GRANTS:
        # Never label a partial schedule as complete or invent a cutoff time.
        forecast.update(status="unavailable", notice="Forecast withheld: too many matching grants "
                        "for the bounded review. Current access is checked separately; no expiry "
                        "prediction is available. This is not a permission token.")
        return host_read_decision(db, principal, project.tenant_id, project.id, at), forecast
    current = read_decision(principal, project.tenant_id, project.id, rows, at)
    boundaries = sorted({aware(value) for row in rows for value in (row.starts_at, row.expires_at)
                         if at < aware(value) <= through})
    for boundary in boundaries:
        future = read_decision(principal, project.tenant_id, project.id, rows, boundary)
        if future.allowed != current.allowed:
            forecast.update(status="predicted_change", next_change={
                "at": boundary.isoformat(), "allowed": future.allowed})
            break
    return current, forecast
