"""Host-owned deterministic boundary. The model cannot change this module at runtime."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json

CONTRACT = {
    "id": "temporary-project-view",
    "version": 1,
    "scope": "one tenant, one project, one viewer",
    "effect": "read_only",
    "max_seconds": 7 * 24 * 3600,
    "approval_role": "admin",
    "preview": "host_authorization",
    "rollback": "revoke",
}


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    role: str


def validate_grant(tenant_id: str, project_tenant: str, viewer_tenant: str, expires_at: datetime, at: datetime) -> None:
    if project_tenant != tenant_id or viewer_tenant != tenant_id:
        raise ValueError("cross_tenant")
    duration = aware(expires_at) - aware(at)
    if duration <= timedelta() or duration > timedelta(days=7):
        raise ValueError("invalid_expiry")


@dataclass(frozen=True)
class ReadDecision:
    allowed: bool
    basis: str
    variation_id: str | None = None


def read_decision(principal: Principal, project_tenant: str, project_id: str, variations: list, at: datetime) -> ReadDecision:
    """One pure decision for preview and enforcement. Preview fixtures need no saved ID."""
    if principal.tenant_id != project_tenant:
        return ReadDecision(False, "denied")
    if principal.role in {"admin", "member", "engineer"}:
        return ReadDecision(True, "role")
    if principal.role != "contractor":
        return ReadDecision(False, "denied")
    for v in variations:
        if (v.tenant_id == principal.tenant_id and v.project_id == project_id
                and v.viewer_id == principal.user_id and v.state == "active"
                and aware(v.starts_at) <= aware(at) < aware(v.expires_at)):
            return ReadDecision(True, "variation", getattr(v, "id", None))
    return ReadDecision(False, "denied")


def can_read(principal: Principal, project_tenant: str, project_id: str, variations: list, at: datetime) -> bool:
    return read_decision(principal, project_tenant, project_id, variations, at).allowed
