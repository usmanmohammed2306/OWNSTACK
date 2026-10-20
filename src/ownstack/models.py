from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from ownstack.db import Base


def now():
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=1)


class WebSession(Base):
    __tablename__ = "web_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RateWindow(Base):
    __tablename__ = "rate_windows"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RuntimePulse(Base):
    __tablename__ = "runtime_pulses"
    component: Mapped[str] = mapped_column(String(40), primary_key=True)
    touched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    revision: Mapped[int] = mapped_column(Integer, default=1)


class IdentityEvent(Base):
    __tablename__ = "identity_events"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    subject_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(Text)


class Contract(Base):
    __tablename__ = "contracts"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    manifest: Mapped[dict] = mapped_column(JSON)
    manifest_hash: Mapped[str] = mapped_column(String(64))


class ChangeRequest(Base):
    __tablename__ = "change_requests"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    requester_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30))
    project_id: Mapped[str | None] = mapped_column(String(40))
    viewer_id: Mapped[str | None] = mapped_column(String(40))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="new")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    current_attempt_id: Mapped[str | None] = mapped_column(String(40))
    accepted_proposal_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_request_tenant_status", "tenant_id", "status"),)


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("change_requests.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    request_revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(30), default="queued")
    model_id: Mapped[str] = mapped_column(String(120), default="fixture")
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (UniqueConstraint("request_id", "request_revision", "number"),)


class Proposal(Base):
    __tablename__ = "proposals"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("change_requests.id"), index=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.id"), unique=True)
    route: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    parameters: Mapped[dict] = mapped_column(JSON)
    request_revision: Mapped[int] = mapped_column(Integer)
    contract_id: Mapped[str | None] = mapped_column(String(80))
    contract_version: Mapped[int | None] = mapped_column(Integer)
    contract_hash: Mapped[str | None] = mapped_column(String(64))
    preview_hash: Mapped[str | None] = mapped_column(String(64))
    proposal_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="ready")


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), unique=True)
    proposal_hash: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Variation(Base):
    __tablename__ = "variations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    viewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), unique=True)
    state: Mapped[str] = mapped_column(String(30), default="active")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (Index("ix_variation_read_candidate", "tenant_id", "project_id", "viewer_id", "state", "expires_at"),)


class HostObservation(Base):
    """An authorization observation, never proof a human consumed the response."""
    __tablename__ = "host_observations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id"))
    variation_id: Mapped[str | None] = mapped_column(ForeignKey("variations.id"), index=True)
    action: Mapped[str] = mapped_column(String(30))
    allowed: Mapped[bool] = mapped_column(Boolean)
    basis: Mapped[str] = mapped_column(String(30))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("ix_host_observation_tenant_time", "tenant_id", "observed_at"),)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("change_requests.id"))
    kind: Mapped[str] = mapped_column(String(50))
    subject_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    limitation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("change_requests.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Idempotency(Base):
    __tablename__ = "idempotency"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    operation: Mapped[str] = mapped_column(String(50))
    key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("tenant_id", "operation", "key"),)


class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), unique=True)
    topic: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(30), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    destination_id: Mapped[str | None] = mapped_column(String(64))
    lease_id: Mapped[str | None] = mapped_column(String(40))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (Index("ix_outbox_dispatch", "tenant_id", "state", "available_at"),)


class DeliveryReceipt(Base):
    """A deduplicated local consumer receipt, not an external notification."""
    __tablename__ = "delivery_receipts"
    event_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    destination_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    envelope_hash: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class InferenceBudget(Base):
    """Conservative cross-process reservation count, not a provider billing record."""
    __tablename__ = "inference_budget"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    reserved_calls: Mapped[int] = mapped_column(Integer, default=0)


class EngineeringItem(Base):
    __tablename__ = "engineering_items"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    request_id: Mapped[str] = mapped_column(ForeignKey("change_requests.id"), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="needs_engineer")
    patch: Mapped[dict | None] = mapped_column(JSON)
    patch_hash: Mapped[str | None] = mapped_column(String(64))
    human_decision: Mapped[str | None] = mapped_column(String(30))
    operation_id: Mapped[str | None] = mapped_column(String(40))
    operation_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConvergenceDecision(Base):
    __tablename__ = "convergence_decisions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    need_key: Mapped[str] = mapped_column(String(80), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(30))
    rationale: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
