"""Durable bounded repair history, separate from the engineer's selected patch."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ownstack.db import Base
from ownstack.models import now


class RepairRun(Base):
    __tablename__ = "repair_runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("engineering_items.id"), index=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("change_requests.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    state: Mapped[str] = mapped_column(String(30), default="running", index=True)
    original_patch: Mapped[dict] = mapped_column(JSON)
    original_patch_hash: Mapped[str] = mapped_column(String(64))
    request_revision: Mapped[int] = mapped_column(Integer)
    request_hash: Mapped[str] = mapped_column(String(64))
    configuration: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[dict] = mapped_column(JSON)
    max_attempts: Mapped[int] = mapped_column(Integer)
    current_attempt_id: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(80))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RepairAttempt(Base):
    __tablename__ = "repair_attempts"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("repair_runs.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    model_id: Mapped[str] = mapped_column(String(120))
    input_patch: Mapped[dict] = mapped_column(JSON)
    feedback: Mapped[dict] = mapped_column(JSON)
    candidate: Mapped[dict | None] = mapped_column(JSON)
    candidate_hash: Mapped[str | None] = mapped_column(String(64))
    checks: Mapped[dict | None] = mapped_column(JSON)
    usage: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(80))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("run_id", "number"),)
