"""Read-only rollback impact. A digest fences a snapshot; it grants no authority."""
from sqlalchemy import select
from ownstack.models import Project, User, Variation
from ownstack.policy import Principal, ReadDecision, aware, digest, read_decision
from ownstack.service import scoped


def revoke_preview(db, variation, actor_id, at):
    project = scoped(db, Project, variation.project_id, variation.tenant_id)
    viewer = scoped(db, User, variation.viewer_id, variation.tenant_id)
    candidates = db.scalars(select(Variation).where(
        Variation.tenant_id == variation.tenant_id, Variation.project_id == project.id,
        Variation.viewer_id == viewer.id, Variation.state == "active",
        Variation.starts_at <= at, Variation.expires_at > at).order_by(Variation.id)).all()
    principal = Principal(viewer.id, viewer.tenant_id, viewer.role)

    def decision(rows):
        result = read_decision(principal, project.tenant_id, project.id, rows, at) if viewer.enabled else ReadDecision(False, "denied")
        return {"allowed": result.allowed, "basis": result.basis, "variation_id": result.variation_id}

    def identity(row):
        return {"id": row.id, "revision": row.revision, "state": row.state,
                "starts_at": aware(row.starts_at).isoformat(), "expires_at": aware(row.expires_at).isoformat()}

    # Do not hash evaluation time itself: unchanged previews must be confirmable.
    # Crossing a start/expiry boundary changes effective candidates or can_revoke.
    snapshot = {"schema": "ownstack.revoke-preview.v1", "actor_id": actor_id,
        "tenant_id": variation.tenant_id, "variation_id": variation.id,
        "project_id": project.id, "project_revision": project.revision,
        "viewer_id": viewer.id, "viewer_role": viewer.role, "viewer_enabled": viewer.enabled,
        "grant": identity(variation), "effective_candidates": [identity(v) for v in candidates],
        "can_revoke": variation.state == "active" and aware(variation.expires_at) > at,
        "before": decision(candidates),
        "after": decision([v for v in candidates if v.id != variation.id])}
    return {**snapshot, "preview_hash": digest(snapshot), "evaluated_at": at.isoformat(),
        "notice": "Predicted effect of revoking this grant only, not an observed read. "
                  "Other grants and roles remain; already-authorized in-flight reads are not recalled."}
