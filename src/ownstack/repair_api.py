"""Authenticated, tenant-scoped repair controls. GET never dispatches inference."""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ownstack.auth import current_principal, db_session, require_role
from ownstack.policy import Principal
from ownstack.repair import adopt_candidate, serialize_run, start_repair, stop_repair
from ownstack.repair_models import RepairRun
from ownstack.service import scoped
from ownstack.models import EngineeringItem

router = APIRouter(prefix="/v1", tags=["bounded repair"])


class RepairBody(BaseModel):
    patch_hash: str = Field(pattern="^[0-9a-f]{64}$")
    max_attempts: int = Field(default=2, ge=1, le=2, strict=True)


class AdoptBody(BaseModel):
    patch_hash: str = Field(pattern="^[0-9a-f]{64}$")


@router.post("/engineering/{item_id}/repairs")
def start(item_id: str, body: RepairBody, idempotency_key: str = Header(default=""),
          principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "engineer")
    try:
        run = start_repair(db, item_id, principal, idempotency_key, body.patch_hash, body.max_attempts)
        db.commit()
    except IntegrityError:
        db.rollback()
        # Concurrent insert can race on SQLite; repeat resolves the saved key.
        run = start_repair(db, item_id, principal, idempotency_key, body.patch_hash, body.max_attempts)
        db.commit()
    return serialize_run(db, run)


@router.get("/engineering/{item_id}/repairs")
def list_runs(item_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "engineer", "admin")
    scoped(db, EngineeringItem, item_id, principal.tenant_id)
    rows = db.scalars(select(RepairRun).where(RepairRun.item_id == item_id,
        RepairRun.tenant_id == principal.tenant_id).order_by(RepairRun.created_at.desc())).all()
    return [serialize_run(db, run) for run in rows]


@router.get("/repairs/{run_id}")
def get_run(run_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "engineer", "admin")
    return serialize_run(db, scoped(db, RepairRun, run_id, principal.tenant_id))


@router.post("/repairs/{run_id}/take-over")
def take_over(run_id: str, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "engineer")
    scoped(db, RepairRun, run_id, principal.tenant_id)
    run = stop_repair(db, run_id)
    db.commit()
    return serialize_run(db, run)


@router.post("/repairs/{run_id}/adopt")
def adopt(run_id: str, body: AdoptBody, principal: Principal = Depends(current_principal), db: Session = Depends(db_session)):
    require_role(principal, "engineer")
    scoped(db, RepairRun, run_id, principal.tenant_id)
    run = adopt_candidate(db, run_id, body.patch_hash)
    db.commit()
    return serialize_run(db, run)
