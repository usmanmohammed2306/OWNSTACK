"""Offline variation-compatibility lab. Not imported by production authorization.

Every state is immutable. The digest is an exact-content fence, not a signature.
Adapters normalize owned synthetic resources; this is not arbitrary SaaS support.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from typing import Literal, Protocol


def digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class FenceError(ValueError):
    pass


class VariationConflict(ValueError):
    pass


@dataclass(frozen=True)
class Contract:
    id: str
    version: int
    effect: Literal["temporary_read", "redact_fields"]
    max_duration_seconds: int
    required_semantics: tuple[tuple[str, str], ...]
    redactable_fields: tuple[str, ...] = ()

    @property
    def hash(self) -> str:
        return digest(asdict(self))


READ = Contract("temporary-read", 1, "temporary_read", 604800,
                (("tenant", "owner-tenant"), ("scope", "single-workspace"),
                 ("title", "public-title"), ("content", "public-content")))
REDACT = Contract("sensitive-field-redaction", 1, "redact_fields", 604800,
                  (("tenant", "owner-tenant"), ("scope", "single-workspace"),
                   ("internal_notes", "private-internal-notes"),
                   ("customer_email", "private-contact-email")),
                  ("internal_notes", "customer_email"))
CONTRACTS = {(c.id, c.version): c for c in (READ, REDACT)}


@dataclass(frozen=True)
class HostManifest:
    host: str
    version: int
    resource_kind: str
    semantics: tuple[tuple[str, str], ...]
    supported_contracts: tuple[tuple[str, int, str], ...]
    adapter_revision: str

    @property
    def hash(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class Principal:
    id: str
    tenant: str
    role: Literal["contractor", "member", "admin", "platform_owner"]


@dataclass(frozen=True)
class Resource:
    key: str
    tenant: str
    scope: str
    fields: tuple[tuple[str, str], ...]


class HostAdapter(Protocol):
    manifest: HostManifest

    def resource(self, key: str) -> Resource | None: ...

    def snapshot(self) -> tuple[Resource, ...]: ...


@dataclass(frozen=True)
class Variation:
    id: str
    tenant: str
    host: str
    scope: str
    subject: str
    contract_id: str
    contract_version: int
    contract_hash: str
    starts: int
    expires: int
    fields: tuple[str, ...] = ()
    revoked: bool = False

    def active(self, now: int) -> bool:
        return not self.revoked and self.starts <= now < self.expires


@dataclass(frozen=True)
class LabState:
    revision: int
    hosts: tuple[HostManifest, ...]
    variations: tuple[Variation, ...] = ()

    @property
    def hash(self) -> str:
        return digest(asdict(self))

    def host(self, name: str) -> HostManifest:
        matches = [host for host in self.hosts if host.host == name]
        if len(matches) != 1:
            raise FenceError("Unknown or duplicated host")
        return matches[0]


def contract_for(variation: Variation) -> Contract:
    contract = CONTRACTS.get((variation.contract_id, variation.contract_version))
    if contract is None or contract.hash != variation.contract_hash:
        raise FenceError("Unknown contract version or changed contract hash")
    return contract


def compatibility_reasons(host: HostManifest, contract: Contract) -> tuple[str, ...]:
    reasons = []
    if (contract.id, contract.version, contract.hash) not in host.supported_contracts:
        reasons.append("contract-version-or-hash-unsupported")
    semantics = dict(host.semantics)
    if len(semantics) != len(host.semantics):
        reasons.append("ambiguous-field-mapping")
    for field, expected in contract.required_semantics:
        if semantics.get(field) != expected:
            reasons.append(f"semantic-mismatch:{field}")
    return tuple(reasons)


def _validate(state: LabState, variation: Variation) -> None:
    contract = contract_for(variation)
    if compatibility_reasons(state.host(variation.host), contract):
        raise FenceError("Contract incompatible with current host")
    if any(not value or value == "*" for value in
           (variation.id, variation.tenant, variation.host, variation.scope, variation.subject)):
        raise FenceError("Exact non-wildcard identifiers required")
    if type(variation.starts) is not int or type(variation.expires) is not int:
        raise FenceError("Integer UTC epoch seconds required")
    if not 0 < variation.expires - variation.starts <= contract.max_duration_seconds:
        raise FenceError("Duration outside contract")
    if variation.revoked:
        raise FenceError("New proposal cannot already be revoked")
    if tuple(sorted(set(variation.fields))) != variation.fields:
        raise FenceError("Fields must be sorted and unique")
    if contract.effect == "temporary_read" and variation.fields:
        raise FenceError("Read grant cannot change fields")
    if contract.effect == "redact_fields" and (
        not variation.fields or not set(variation.fields) <= set(contract.redactable_fields)
    ):
        raise FenceError("Redaction can only remove declared sensitive fields")
    for existing in state.variations:
        if existing.id == variation.id:
            raise VariationConflict("Variation IDs cannot be reused, including after revoke")
        same_scope = (existing.tenant, existing.host, existing.scope, existing.subject) == (
            variation.tenant, variation.host, variation.scope, variation.subject)
        overlaps = max(existing.starts, variation.starts) < min(existing.expires, variation.expires)
        if (same_scope and overlaps and not existing.revoked
                and contract.effect == contract_for(existing).effect == "temporary_read"):
            raise VariationConflict("Overlapping grants need explicit reconciliation")
    # Redactions intentionally compose by union. They never establish read access.


@dataclass(frozen=True)
class Proposal:
    state_hash: str
    variation: Variation

    @property
    def hash(self) -> str:
        return digest(asdict(self))


def propose(state: LabState, variation: Variation) -> Proposal:
    _validate(state, variation)
    return Proposal(state.hash, variation)


def approve(state: LabState, proposal: Proposal, actor: Principal, exact_hash: str) -> LabState:
    if actor.role != "admin" or actor.tenant != proposal.variation.tenant:
        raise PermissionError("The exact tenant admin must approve")
    if proposal.state_hash != state.hash or exact_hash != proposal.hash:
        raise FenceError("Stale state or changed proposal")
    _validate(state, proposal.variation)
    return replace(state, revision=state.revision + 1,
                   variations=state.variations + (proposal.variation,))


def revoke(state: LabState, variation_id: str, actor: Principal, exact_state_hash: str) -> LabState:
    if exact_state_hash != state.hash:
        raise FenceError("Stale rollback state")
    matches = [v for v in state.variations if v.id == variation_id]
    if not matches:
        raise FenceError("Unknown variation")
    selected = matches[0]
    if actor.role != "admin" or actor.tenant != selected.tenant:
        raise PermissionError("Tenant admin required")
    if selected.revoked:
        return state
    return replace(state, revision=state.revision + 1,
                   variations=tuple(replace(v, revoked=True) if v.id == variation_id else v
                                    for v in state.variations))


@dataclass(frozen=True)
class ReadResult:
    allowed: bool
    reason: str
    fields: tuple[tuple[str, str], ...] = ()
    applied: tuple[str, ...] = ()


def read(state: LabState, adapter: HostAdapter, actor: Principal, key: str, now: int) -> ReadResult:
    """The host returns only this protected projection, never its native record."""
    if state.host(adapter.manifest.host).hash != adapter.manifest.hash:
        return ReadResult(False, "host-version-fence")
    resource = adapter.resource(key)
    if resource is None or resource.tenant != actor.tenant:
        return ReadResult(False, "not-found")
    relevant = [v for v in state.variations if v.active(now) and
                (v.tenant, v.host, v.scope, v.subject) ==
                (actor.tenant, adapter.manifest.host, resource.scope, actor.id)]
    try:
        contracts = [(v, contract_for(v)) for v in relevant]
    except FenceError:
        return ReadResult(False, "contract-fence")
    if any(compatibility_reasons(adapter.manifest, c) for _, c in contracts):
        return ReadResult(False, "contract-fence")
    grants = [v for v, c in contracts if c.effect == "temporary_read"]
    if actor.role not in ("member", "admin") and not (actor.role == "contractor" and grants):
        return ReadResult(False, "no-read-permission")
    restrictions = [v for v, c in contracts if c.effect == "redact_fields"]
    redacted = {field for v in restrictions for field in v.fields}
    return ReadResult(True, "base-role" if actor.role in ("member", "admin") else "temporary-grant",
                      tuple((key, value) for key, value in resource.fields if key not in redacted),
                      tuple(sorted(v.id for v in grants + restrictions)))


def preview(state: LabState, proposal: Proposal, adapter: HostAdapter,
            actor: Principal, key: str, now: int) -> dict:
    """Same read function with counterfactual state. No approval or mutation."""
    if proposal.state_hash != state.hash:
        raise FenceError("Stale preview")
    _validate(state, proposal.variation)
    counterfactual = replace(state, variations=state.variations + (proposal.variation,))
    return {"observed": False, "proposal_hash": proposal.hash,
            "before": asdict(read(state, adapter, actor, key, now)),
            "after": asdict(read(counterfactual, adapter, actor, key, now))}


@dataclass(frozen=True)
class Impact:
    variation_id: str
    tenant: str
    disposition: Literal["compatible", "blocked", "inactive"]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class UpgradePlan:
    state_hash: str
    source_host_hash: str
    target: HostManifest
    resource_snapshot_hash: str
    planned_at: int
    impacts: tuple[Impact, ...]

    @property
    def hash(self) -> str:
        return digest(asdict(self))


def plan_upgrade(state: LabState, current: HostAdapter, target: HostAdapter, now: int) -> UpgradePlan:
    if state.host(current.manifest.host).hash != current.manifest.hash:
        raise FenceError("Current host is not the recorded version")
    if (target.manifest.host != current.manifest.host or
            target.manifest.version <= current.manifest.version or
            target.manifest.resource_kind != current.manifest.resource_kind):
        raise FenceError("Explicit same-host forward upgrade required")
    source_snapshot = [asdict(r) for r in current.snapshot()]
    target_snapshot = [asdict(r) for r in target.snapshot()]
    if source_snapshot != target_snapshot:
        raise FenceError("Normalized data changed; require a separate data-migration review")
    impacts = []
    for variation in state.variations:
        if variation.host != current.manifest.host:
            continue
        # Future-starting variations still need a valid migration. Expired and
        # revoked entries stay in history but cannot authorize a read again.
        if variation.revoked or variation.expires <= now:
            impacts.append(Impact(variation.id, variation.tenant, "inactive", ()))
            continue
        reasons = compatibility_reasons(target.manifest, contract_for(variation))
        impacts.append(Impact(variation.id, variation.tenant,
                              "blocked" if reasons else "compatible", reasons))
    return UpgradePlan(state.hash, current.manifest.hash, target.manifest,
                       digest(source_snapshot), now, tuple(impacts))


def approve_upgrade(state: LabState, plan: UpgradePlan, current: HostAdapter,
                    target: HostAdapter, actor: Principal, exact_hash: str, now: int) -> LabState:
    if actor.role != "platform_owner" or actor.tenant != "platform":
        raise PermissionError("Platform owner must review cross-tenant host upgrades")
    if now < plan.planned_at or now - plan.planned_at > 300:
        raise FenceError("Upgrade preview expired or clock moved backwards")
    reconstructed = plan_upgrade(state, current, target, plan.planned_at)
    if plan != reconstructed or exact_hash != plan.hash:
        raise FenceError("Upgrade state, adapter, data or exact approval changed")
    if any(impact.disposition == "blocked" for impact in plan.impacts):
        raise FenceError("Unsafe variation migration blocked")
    return replace(state, revision=state.revision + 1,
                   hosts=tuple(target.manifest if h.host == target.manifest.host else h
                               for h in state.hosts))
