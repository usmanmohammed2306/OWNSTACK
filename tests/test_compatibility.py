"""Finite offline correctness and deliberate-defect checks, not sandbox claims."""
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from ownstack.compatibility import (READ, REDACT, FenceError, LabState, Principal,
                                   Variation, VariationConflict, approve, approve_upgrade,
                                   plan_upgrade, preview, propose, read, revoke)

# These are source-owned lab fixtures, not part of the production Python package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sample_apps_compat.adapters import ProjectDocuments, WorkOrders
from sample_apps_compat.baselines import ManualFlag, branch_edit_comparison, manual_flag_read

NOW = 1_800_000_000
ADMIN = Principal("atlas-admin", "atlas", "admin")
CONTRACTOR = Principal("atlas-contractor", "atlas", "contractor")
OWNER = Principal("owner", "platform", "platform_owner")


def variation(identifier="grant", *, contract=READ, host="projects", scope="atlas-project", fields=(), **changes):
    return replace(Variation(identifier, "atlas", host, scope, CONTRACTOR.id,
                             contract.id, contract.version, contract.hash, NOW, NOW + 3600,
                             fields), **changes)


def initial():
    return LabState(0, (ProjectDocuments().manifest, WorkOrders().manifest))


def add(state, item):
    proposal = propose(state, item)
    return approve(state, proposal, ADMIN, proposal.hash)


@pytest.mark.parametrize("adapter,key,scope", [(ProjectDocuments(), "atlas-plan", "atlas-project"),
                                             (WorkOrders(), "WO-701", "A-17")])
def test_two_native_hosts_enforce_same_read_redaction_policy(adapter, key, scope):
    state = initial()
    assert not read(state, adapter, CONTRACTOR, key, NOW).allowed
    state = add(state, variation(host=adapter.manifest.host, scope=scope))
    assert "internal_notes" in dict(read(state, adapter, CONTRACTOR, key, NOW).fields)
    state = add(state, variation("redact", host=adapter.manifest.host, scope=scope,
                                contract=REDACT, fields=("internal_notes",)))
    result = read(state, adapter, CONTRACTOR, key, NOW)
    assert result.allowed
    assert "internal_notes" not in dict(result.fields)
    assert "customer_email" in dict(result.fields)
    assert result.applied == ("grant", "redact")


def test_redaction_alone_cannot_grant_and_unknown_roles_cannot_use_grant():
    state = add(initial(), variation(contract=REDACT, fields=("internal_notes",)))
    assert not read(state, ProjectDocuments(), CONTRACTOR, "atlas-plan", NOW).allowed
    state = add(state, variation("read"))
    assert not read(state, ProjectDocuments(), replace(CONTRACTOR, role="engineer"), "atlas-plan", NOW).allowed


@pytest.mark.parametrize("key,actor", [("nova-plan", CONTRACTOR), ("atlas-other", CONTRACTOR),
                                    ("atlas-plan", replace(CONTRACTOR, id="other")),
                                    ("atlas-plan", replace(CONTRACTOR, tenant="nova"))])
def test_exact_tenant_subject_scope_boundaries(key, actor):
    state = add(initial(), variation())
    assert not read(state, ProjectDocuments(), actor, key, NOW).allowed


@pytest.mark.parametrize("now,allowed", [(NOW - 1, False), (NOW, True), (NOW + 3599, True), (NOW + 3600, False)])
def test_time_boundaries(now, allowed):
    assert read(add(initial(), variation()), ProjectDocuments(), CONTRACTOR, "atlas-plan", now).allowed is allowed


def test_selective_rollback_keeps_other_redaction_and_access():
    state = add(initial(), variation())
    state = add(state, variation("notes", contract=REDACT, fields=("internal_notes",)))
    state = add(state, variation("email", contract=REDACT, fields=("customer_email",)))
    state = revoke(state, "notes", ADMIN, state.hash)
    result = read(state, ProjectDocuments(), CONTRACTOR, "atlas-plan", NOW)
    assert result.allowed and "internal_notes" in dict(result.fields)
    assert "customer_email" not in dict(result.fields)
    assert result.applied == ("email", "grant")
    state = revoke(state, "grant", ADMIN, state.hash)
    assert not read(state, ProjectDocuments(), CONTRACTOR, "atlas-plan", NOW).allowed
    assert not state.variations[2].revoked


def test_restrictions_union_without_last_write_wins():
    state = add(initial(), variation())
    state = add(state, variation("both", contract=REDACT, fields=("customer_email", "internal_notes")))
    state = add(state, variation("notes", contract=REDACT, fields=("internal_notes",)))
    assert set(dict(read(state, ProjectDocuments(), CONTRACTOR, "atlas-plan", NOW).fields)) == {"title", "content"}
    state = revoke(state, "notes", ADMIN, state.hash)
    assert set(dict(read(state, ProjectDocuments(), CONTRACTOR, "atlas-plan", NOW).fields)) == {"title", "content"}


def test_overlap_conflict_and_disjoint_interval():
    state = add(initial(), variation())
    with pytest.raises(VariationConflict, match="Overlapping"):
        propose(state, variation("duplicate"))
    assert propose(state, variation("later", starts=NOW + 3600, expires=NOW + 7200))


@pytest.mark.parametrize("changes", [{"scope": "*"}, {"subject": ""}, {"expires": NOW},
                                     {"expires": NOW + 604801}, {"starts": True},
                                     {"contract_version": 9}, {"contract_hash": "changed"},
                                     {"fields": ("title",)}, {"revoked": True}])
def test_invalid_grant_rejected(changes):
    with pytest.raises((FenceError, VariationConflict)):
        propose(initial(), variation(**changes))


@pytest.mark.parametrize("fields", [(), ("content",), ("internal_notes", "internal_notes"),
                                  ("internal_notes", "customer_email")])
def test_invalid_redaction_rejected(fields):
    with pytest.raises(FenceError):
        propose(initial(), variation(contract=REDACT, fields=fields))


def test_exact_proposal_and_tenant_approval_fences():
    state = initial()
    proposal = propose(state, variation())
    for actor in (CONTRACTOR, OWNER, replace(ADMIN, tenant="nova")):
        with pytest.raises(PermissionError):
            approve(state, proposal, actor, proposal.hash)
    with pytest.raises(FenceError):
        approve(state, proposal, ADMIN, "different")
    changed = add(state, variation("notes", contract=REDACT, fields=("internal_notes",)))
    with pytest.raises(FenceError):
        approve(changed, proposal, ADMIN, proposal.hash)
    with pytest.raises(FenceError):
        approve(state, replace(proposal, variation=variation(expires=NOW + 7200)), ADMIN, proposal.hash)


def test_preview_matches_exact_approved_effect_without_mutating():
    state = initial()
    proposal = propose(state, variation())
    before_hash = state.hash
    shown = preview(state, proposal, ProjectDocuments(), CONTRACTOR, "atlas-plan", NOW)
    after = approve(state, proposal, ADMIN, proposal.hash)
    assert not shown["observed"] and not shown["before"]["allowed"]
    assert shown["after"] == asdict(read(after, ProjectDocuments(), CONTRACTOR, "atlas-plan", NOW))
    assert state.hash == before_hash and not state.variations


@pytest.mark.parametrize("adapter_type,scope,key", [(ProjectDocuments, "atlas-project", "atlas-plan"),
                                                  (WorkOrders, "A-17", "WO-701")])
def test_upgrade_preserves_outputs_but_old_adapter_is_fenced(adapter_type, scope, key):
    v1, v2 = adapter_type(1), adapter_type(2)
    state = add(initial(), variation(host=v1.manifest.host, scope=scope))
    state = add(state, variation("redact", host=v1.manifest.host, scope=scope, contract=REDACT,
                                fields=("internal_notes",)))
    before = read(state, v1, CONTRACTOR, key, NOW)
    plan = plan_upgrade(state, v1, v2, NOW)
    assert {i.disposition for i in plan.impacts} == {"compatible"}
    upgraded = approve_upgrade(state, plan, v1, v2, OWNER, plan.hash, NOW + 1)
    assert read(upgraded, v2, CONTRACTOR, key, NOW + 1) == before
    assert read(upgraded, v1, CONTRACTOR, key, NOW + 1).reason == "host-version-fence"


def test_unsafe_semantic_migration_rejected_including_future_start():
    state = add(initial(), variation("future", contract=REDACT, fields=("internal_notes",),
                                     starts=NOW + 100, expires=NOW + 500))
    v1, bad = ProjectDocuments(), ProjectDocuments(2, unsafe_semantics=True)
    plan = plan_upgrade(state, v1, bad, NOW)
    assert plan.impacts[0].disposition == "blocked"
    assert "semantic-mismatch:internal_notes" in plan.impacts[0].reasons
    with pytest.raises(FenceError, match="Unsafe"):
        approve_upgrade(state, plan, v1, bad, OWNER, plan.hash, NOW)


def test_plan_binds_state_data_hash_version_target_and_approval_age():
    state = add(initial(), variation())
    v1, v2 = ProjectDocuments(), ProjectDocuments(2)
    plan = plan_upgrade(state, v1, v2, NOW)
    for candidate, exact, now in [(replace(plan, impacts=()), plan.hash, NOW), (plan, "bad", NOW),
                                   (plan, plan.hash, NOW + 301), (plan, plan.hash, NOW - 1)]:
        with pytest.raises(FenceError):
            approve_upgrade(state, candidate, v1, v2, OWNER, exact, now)
    with pytest.raises(FenceError):
        approve_upgrade(revoke(state, "grant", ADMIN, state.hash), plan, v1, v2, OWNER, plan.hash, NOW)
    changed = ProjectDocuments(2)
    changed.rows = (replace(changed.rows[0], content=(("caption", "tampered"),) + changed.rows[0].content[1:]),) + changed.rows[1:]
    with pytest.raises(FenceError, match="data changed"):
        approve_upgrade(state, plan, v1, changed, OWNER, plan.hash, NOW)
    with pytest.raises(PermissionError):
        approve_upgrade(state, plan, v1, v2, ADMIN, plan.hash, NOW)


def test_inactive_history_does_not_block_but_stays_recorded():
    state = add(initial(), variation(contract=REDACT, fields=("internal_notes",)))
    state = revoke(state, "grant", ADMIN, state.hash)
    plan = plan_upgrade(state, ProjectDocuments(), ProjectDocuments(2, unsafe_semantics=True), NOW)
    assert plan.impacts[0].disposition == "inactive"
    assert state.variations[0].revoked


def test_manual_baseline_can_match_valid_scoped_output():
    state = add(initial(), variation())
    state = add(state, variation("redact", contract=REDACT, fields=("internal_notes",)))
    flags = (ManualFlag("atlas", "projects", "atlas-project", CONTRACTOR.id, NOW + 3600, ("internal_notes",)),)
    for now in (NOW, NOW + 3600):
        for key in ("atlas-plan", "atlas-other", "nova-plan"):
            result = read(state, ProjectDocuments(), CONTRACTOR, key, now)
            baseline = manual_flag_read(ProjectDocuments(), CONTRACTOR, key, now, flags)
            assert (result.allowed, result.fields) == (baseline.allowed, baseline.fields)


def test_branch_comparison_executes_both_broken_and_fixed_sources():
    result = branch_edit_comparison()
    assert result["branches_broken_before_update"] == 2
    assert result["branch_source_units_edited"] == 2
    assert result["shared_adapter_source_units_edited"] == result["manual_flag_shared_adapter_source_units_edited"] == 1
    assert not result["human_time_measured"]


def test_revoke_is_idempotent_and_old_identifier_cannot_be_reused():
    state = add(initial(), variation())
    state = revoke(state, "grant", ADMIN, state.hash)
    assert revoke(state, "grant", ADMIN, state.hash) is state
    with pytest.raises(VariationConflict, match="reused"):
        propose(state, variation())
    with pytest.raises(FenceError, match="Stale"):
        revoke(state, "grant", ADMIN, "old-hash")
    with pytest.raises(PermissionError):
        revoke(state, "grant", replace(ADMIN, tenant="nova"), state.hash)


def test_restriction_applies_to_existing_role_access_without_new_grant():
    state = add(initial(), variation("member-redaction", contract=REDACT, fields=("internal_notes",),
                                     subject="atlas-member"))
    member = Principal("atlas-member", "atlas", "member")
    result = read(state, ProjectDocuments(), member, "atlas-plan", NOW)
    assert result.allowed and result.reason == "base-role"
    assert "internal_notes" not in dict(result.fields)
    assert not read(state, ProjectDocuments(), member, "nova-plan", NOW).allowed


def test_changed_manifest_or_adapter_revision_invalidates_plan():
    state = add(initial(), variation())
    v1, v2 = ProjectDocuments(), ProjectDocuments(2)
    plan = plan_upgrade(state, v1, v2, NOW)
    v2.manifest = replace(v2.manifest, adapter_revision="different-code")
    with pytest.raises(FenceError, match="changed"):
        approve_upgrade(state, plan, v1, v2, OWNER, plan.hash, NOW)


def test_unsupported_contract_target_is_blocked_even_if_fields_match():
    state = add(initial(), variation())
    v1, v2 = ProjectDocuments(), ProjectDocuments(2)
    v2.manifest = replace(v2.manifest, supported_contracts=())
    plan = plan_upgrade(state, v1, v2, NOW)
    assert plan.impacts[0].reasons == ("contract-version-or-hash-unsupported",)
    with pytest.raises(FenceError, match="Unsafe"):
        approve_upgrade(state, plan, v1, v2, OWNER, plan.hash, NOW)


def test_experiment_oracles_detect_every_declared_defect():
    from scripts.run_compatibility_lab import experiment
    result = experiment()
    assert result["passed"]
    assert len(result["positive_controls"]) == 10
    assert all(result["positive_controls"].values())
    assert len(result["defect_controls"]) == 6
    assert all(item["detected"] for item in result["defect_controls"])
    assert len(result["manual_feature_flag_comparison"]) == 20
    assert result["unsafe_migration"]["rejected"]


def test_report_is_source_bound_and_existing_evidence_is_never_overwritten(tmp_path):
    from ownstack.compatibility import digest
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "evidence"
    command = [sys.executable, str(root / "scripts/run_compatibility_lab.py"), "--output", str(output)]
    env = dict(os.environ, OWNSTACK_AI_MODE="off", OWNSTACK_MAX_LIVE_CALLS="0", NEBIUS_API_KEY="")
    completed = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr
    raw = (output / "report.json").read_bytes()
    report = json.loads(raw)
    content_digest = report.pop("content_digest")
    assert digest(report) == content_digest
    assert report["passed"] and report["source_unchanged_during_run"]
    assert report["live_inference_calls"] == 0 and not report["database_access"]
    for relative, expected in report["source_hashes"].items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected
    assert (output / "report.sha256").read_text().startswith(hashlib.sha256(raw).hexdigest())
    repeat = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=15)
    assert repeat.returncode != 0 and "FileExistsError" in repeat.stderr
    assert (output / "report.json").read_bytes() == raw
