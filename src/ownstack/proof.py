"""Tenant-private, point-in-time evidence export. A digest is not an attestation."""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from ownstack.models import (Approval, Attempt, ChangeRequest, Contract, EngineeringItem, Event,
                             Evidence, HostObservation, Investigation, Proposal, Variation, ApprovalWitness, VariationWitness)
from ownstack.policy import aware, digest
from ownstack.runner import ROOT, current_provenance
from ownstack.service import scoped, utcnow
from ownstack.repair_models import RepairAttempt, RepairRun
from ownstack.repository_recovery import public_result

# Explicit public-to-this-tenant configuration fields, never arbitrary settings.
REPAIR_CONFIGURATION_FIELDS = (
    "mode", "model", "timeout", "generator_hash", "max_tokens", "temperature",
    "top_p", "workflow_schema", "langgraph_version", "workflow_hash",
)


def fields(row, names: str) -> dict:
    result = {}
    for name in names.split():
        value = getattr(row, name)
        result[name] = aware(value).isoformat() if isinstance(value, datetime) else value
    return result


def source_inventory() -> dict:
    paths = sorted((ROOT / "src/ownstack").glob("*.py"))
    paths += sorted((ROOT / "migrations/versions").glob("*.py"))
    return {str(path.relative_to(ROOT)): digest(path.read_text()) for path in paths}


def export_proof(bind, request_id: str, tenant_id: str) -> dict:
    # Authentication uses a separate API session. Establish isolation before the first SELECT.
    with Session(bind=bind) as db:
        if bind.dialect.name == "postgresql":
            db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        else:
            db.connection().exec_driver_sql("BEGIN")
        request = scoped(db, ChangeRequest, request_id, tenant_id)

        def related(model):
            return db.scalars(select(model).where(model.request_id == request_id,
                                                  model.tenant_id == tenant_id).order_by(model.id)).all()

        proposals = related(Proposal)
        proposal_ids = [row.id for row in proposals]
        approvals = db.scalars(select(Approval).where(Approval.tenant_id == tenant_id,
                                                      Approval.proposal_id.in_(proposal_ids)).order_by(Approval.id)).all()
        variations = db.scalars(select(Variation).where(Variation.tenant_id == tenant_id,
                                                        Variation.proposal_id.in_(proposal_ids)).order_by(Variation.id)).all()
        observations = db.scalars(select(HostObservation).where(
            HostObservation.tenant_id == tenant_id,
            HostObservation.variation_id.in_([row.id for row in variations])).order_by(HostObservation.id)).all()
        contracts = []
        for key in sorted({(row.contract_id, row.contract_version) for row in proposals if row.contract_id}):
            contract = db.get(Contract, key)
            if contract:
                contracts.append(fields(contract, "id version manifest manifest_hash"))
        runs = related(RepairRun)
        repair_attempts = db.scalars(select(RepairAttempt).join(
            RepairRun, RepairRun.id == RepairAttempt.run_id).where(
            RepairRun.request_id == request_id, RepairRun.tenant_id == tenant_id)
            .order_by(RepairAttempt.run_id, RepairAttempt.number)).all()
        grouped = {run.id: [] for run in runs}
        for attempt in repair_attempts:
            grouped[attempt.run_id].append(fields(attempt,
                "id number state model_id input_patch feedback candidate candidate_hash checks usage "
                "error_code deadline_at started_at finished_at"))
        repair_history = []
        for run in runs:
            repair_history.append({**fields(run,
                "id item_id actor_id state original_patch original_patch_hash request_revision "
                "request_hash provenance max_attempts current_attempt_id error_code deadline_at created_at finished_at"),
                "configuration": {key: run.configuration[key] for key in REPAIR_CONFIGURATION_FIELDS
                                  if key in run.configuration},
                "attempts": grouped[run.id], "release_state": "not_deployed"})
        payload = {
            "exported_at": utcnow().isoformat(), "tenant_id": tenant_id,
            "request": fields(request, "id tenant_id team_id requester_id text kind project_id viewer_id expires_at status revision current_attempt_id accepted_proposal_id created_at"),
            "attempts": [fields(row, "id number request_revision state model_id deadline_at started_at finished_at latency_ms input_tokens output_tokens error_code") for row in related(Attempt)],
            "proposals": [fields(row, "id attempt_id route reason parameters request_revision contract_id contract_version contract_hash preview_hash proposal_hash status") for row in proposals],
            "contracts": contracts,
            "approvals": [fields(row, "id proposal_id proposal_hash actor_id created_at") for row in approvals],
            "variations": [fields(row, "id project_id viewer_id proposal_id state starts_at expires_at revision approval_quorum") for row in variations],
            "approval_witnesses": [fields(row,'id proposal_id proposal_hash actor_id identity_version created_at') for row in db.scalars(
                select(ApprovalWitness).where(ApprovalWitness.tenant_id==tenant_id,ApprovalWitness.proposal_id.in_(proposal_ids)).order_by(ApprovalWitness.id))],
            "selected_witnesses": [fields(row,'id variation_id witness_id source') for row in db.scalars(
                select(VariationWitness).where(VariationWitness.tenant_id==tenant_id,VariationWitness.variation_id.in_([v.id for v in variations])).order_by(VariationWitness.id))],
            "observations": [fields(row, "id actor_id project_id document_id variation_id action allowed basis observed_at") for row in observations],
            "engineering": [fields(row, "id status patch patch_hash human_decision operation_id operation_deadline") for row in related(EngineeringItem)],
            "repair_runs": repair_history,
            "investigations": [fields(row, "id actor_id snapshot_hash workflow_hash model_id state version memory error_code deadline_at created_at")
                               for row in related(Investigation)],
            "evidence": [{**fields(row, "id kind subject_hash limitation created_at"), 'result':public_result(row)}
                         for row in related(Evidence)],
            "events": [fields(row, "id event_type payload created_at") for row in related(Event)],
            "current_fixture_provenance": current_provenance(),
            "source_hashes_at_export": source_inventory(),
            "limitations": [
                "Private tenant text and code may be included. Review before publishing.",
                "The digest detects accidental changes, not authenticity: anyone can recompute it. This is not a signed attestation.",
                "Database records share a read snapshot; source hashes describe files at export, not the source used by every historical attempt.",
                "Observations include only reads attributed to these variations. Unattributed denies and role reads remain in the tenant observation ledger.",
                "Authorization is observed at check time, not proof of response delivery, distinct users, production safety or deployment.",
                "Preserved evidence may include failed or superseded checks. A historical pass is not necessarily a current pass.",
                "Repair history includes private candidate code and bounded feedback; workflow events are saved observations, not a release or a signed attestation.",
            ],
        }
    return {"schema": "ownstack.proof.v1", "payload": payload, "sha256": digest(payload)}


def verify_envelope(envelope: dict) -> bool:
    return (isinstance(envelope, dict) and envelope.get("schema") == "ownstack.proof.v1"
            and isinstance(envelope.get("payload"), dict)
            and envelope.get("sha256") == digest(envelope["payload"]))


def saved_state_fingerprint(envelope: dict) -> str:
    """Compare durable request history across restarts, not export time/current files.

    v1 exports predating repair history remain readable. The additive field is
    normalized to an empty list only when absent, never dropped when present.
    """
    if not verify_envelope(envelope):
        raise ValueError("Invalid proof envelope")
    payload = envelope["payload"]
    names = ("request", "attempts", "proposals", "contracts", "approvals", "variations",
             "observations", "engineering", "evidence", "events")
    return digest({**{name: payload[name] for name in names},
                   "repair_runs": payload.get("repair_runs", []),
                   "investigations": payload.get("investigations", [])})
