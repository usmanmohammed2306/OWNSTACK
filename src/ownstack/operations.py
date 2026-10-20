"""Tenant-local operating signals derived from durable records, with no inference."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ownstack.auth import current_principal, db_session, require_role
from ownstack.models import Outbox, RuntimePulse
from ownstack.policy import Principal, aware
from ownstack.service import utcnow

router = APIRouter(prefix="/v1/operations")


@router.get("")
def operations(principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "admin", "engineer")
    counts = dict(db.execute(select(Outbox.state, func.count(Outbox.id))
                  .where(Outbox.tenant_id == principal.tenant_id).group_by(Outbox.state)).all())
    pulse = db.get(RuntimePulse, "worker")
    age = max(0, (utcnow() - aware(pulse.touched_at)).total_seconds()) if pulse else None
    signals = []
    if counts.get("dead", 0):
        signals.append({"code": "OUTBOX_DEAD", "count": counts["dead"]})
    if age is None or age > 150:
        signals.append({"code": "WORKER_PULSE_STALE"})
    return {"outbox": counts, "worker_age_seconds": age, "signals": signals,
            "alert_delivery": "local_status_only"}
