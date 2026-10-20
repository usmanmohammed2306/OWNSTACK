"""Pure, tenant-scoped read authorization for the initial OwnStack host.

Only same-tenant admins, members and engineers have role-based read access.
Contractors have no access yet; temporary grants and their lifecycle come later.
This module does not authenticate anyone. A future server must construct the
principal from a verified identity, never trust role/tenant claims from a browser.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    """Identity and role supplied by the trusted host's authentication layer.

    Frozen fields prevent accidental reassignment, not malicious Python code.
    Type annotations describe expected inputs but do not validate them at runtime.
    """

    user_id: str
    tenant_id: str
    role: str


@dataclass(frozen=True)
class ReadDecision:
    """A boolean result and a stable, deliberately non-sensitive explanation.

    Use ``decision.allowed`` or ``can_read(...)`` in conditionals. Testing the
    decision object itself does not inspect its allowed field.
    """

    allowed: bool
    basis: str


def read_decision(principal: Principal, project_tenant: str) -> ReadDecision:
    """Deny malformed identity data, then enforce tenant and role boundaries.

    User and tenant IDs must be non-blank strings. Identifiers and roles are
    compared exactly: no coercion, trimming or case folding grants permissions.
    Unknown roles are denied by default. The function is deterministic and does
    not mutate inputs, consult a database or retain a previous decision.

    Shape checks cannot prove the principal is authentic or a project exists;
    those remain the caller's responsibilities.
    """
    # Missing fields must not become matching tenant IDs or bypass role checks.
    if not isinstance(principal, Principal):
        return ReadDecision(False, "denied")
    identity_fields = (principal.user_id, principal.tenant_id, project_tenant)
    if not all(isinstance(value, str) and value.strip() for value in identity_fields):
        return ReadDecision(False, "denied")
    if not isinstance(principal.role, str):
        return ReadDecision(False, "denied")

    # Tenant scope is checked before role authority, including for admins.
    if principal.tenant_id != project_tenant:
        return ReadDecision(False, "denied")
    if principal.role in {"admin", "member", "engineer"}:
        return ReadDecision(True, "role")
    # Everything outside the explicit allowlist stays denied.
    return ReadDecision(False, "denied")


def can_read(principal: Principal, project_tenant: str) -> bool:
    """Return only the permission bool for callers that do not need its basis."""
    return read_decision(principal, project_tenant).allowed
