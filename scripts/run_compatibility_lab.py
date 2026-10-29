#!/usr/bin/env python3
"""Run finite, source-bound compatibility experiments without DB or inference.

Creates a NEW evidence directory. Existing evidence is never overwritten.
All actors, approvals, customers, branches and data are synthetic fixtures.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ownstack.compatibility import (READ, REDACT, FenceError, LabState, Principal,
                                   Variation, VariationConflict, approve, approve_upgrade,
                                   digest, plan_upgrade, preview, propose, read, revoke)
from sample_apps_compat.adapters import ProjectDocuments, WorkOrders
from sample_apps_compat.baselines import ManualFlag, branch_edit_comparison, manual_flag_read

NOW = 1_800_000_000  # Fixed synthetic clock, not execution time.
ADMIN = Principal("atlas-admin", "atlas", "admin")
CONTRACTOR = Principal("atlas-contractor", "atlas", "contractor")
NOVA = Principal("nova-member", "nova", "member")
OWNER = Principal("platform-owner", "platform", "platform_owner")


def new_variation(identifier, host="projects", scope="atlas-project", contract=READ, fields=()):
    return Variation(identifier, "atlas", host, scope, CONTRACTOR.id, contract.id,
                     contract.version, contract.hash, NOW, NOW + 3600, fields)


def add(state, variation):
    proposal = propose(state, variation)
    return approve(state, proposal, ADMIN, proposal.hash)


def prepared():
    state = LabState(0, (ProjectDocuments().manifest, WorkOrders().manifest))
    for host, scope in (("projects", "atlas-project"), ("workorders", "A-17")):
        state = add(state, new_variation(f"{host}-grant", host, scope))
        state = add(state, new_variation(f"{host}-notes", host, scope, REDACT, ("internal_notes",)))
        state = add(state, new_variation(f"{host}-email", host, scope, REDACT, ("customer_email",)))
    return state


def raises(expected, fn):
    try:
        fn()
    except expected:
        return True
    return False


def invariant_checks(reader=read, revoker=revoke, upgrader=approve_upgrade):
    """Same oracle definitions run against correct behavior and specified defects."""
    state = prepared()
    v1, v2 = ProjectDocuments(), ProjectDocuments(2)
    plan = plan_upgrade(state, v1, v2, NOW)
    rolled = revoker(state, "projects-notes", ADMIN, state.hash)
    after_rollback = reader(rolled, v1, CONTRACTOR, "atlas-plan", NOW)
    upgraded = upgrader(state, plan, v1, v2, OWNER, plan.hash, NOW)
    bad = ProjectDocuments(2, unsafe_semantics=True)
    bad_plan = plan_upgrade(state, v1, bad, NOW)
    return {
        "cross_tenant": not reader(state, v1, NOVA, "atlas-plan", NOW).allowed,
        "scope": not reader(state, v1, CONTRACTOR, "atlas-other", NOW).allowed,
        "expiry": not reader(state, v1, CONTRACTOR, "atlas-plan", NOW + 3600).allowed,
        "redaction": set(dict(reader(state, v1, CONTRACTOR, "atlas-plan", NOW).fields)) == {"title", "content"},
        "selective_rollback": after_rollback.allowed and
            set(dict(after_rollback.fields)) == {"title", "content", "internal_notes"},
        "upgrade_parity": reader(upgraded, v2, CONTRACTOR, "atlas-plan", NOW) ==
            reader(state, v1, CONTRACTOR, "atlas-plan", NOW),
        "old_adapter_fenced": not reader(upgraded, v1, CONTRACTOR, "atlas-plan", NOW).allowed,
        "exact_upgrade_approval": raises(FenceError, lambda: upgrader(state, plan, v1, v2, OWNER, "wrong", NOW)),
        "unsafe_semantics_blocked": raises(FenceError, lambda: upgrader(state, bad_plan, v1, bad, OWNER, bad_plan.hash, NOW)),
        "stale_plan_blocked": raises(FenceError, lambda: upgrader(rolled, plan, v1, v2, OWNER, plan.hash, NOW)),
    }


def defect_controls():
    def tenant_bypass(state, adapter, actor, key, now):
        resource = adapter.resource(key)
        return read(state, adapter, replace(actor, tenant=resource.tenant) if resource else actor, key, now)

    def expiry_bypass(state, adapter, actor, key, now):
        return read(state, adapter, actor, key, NOW)

    def drop_redaction(state, adapter, actor, key, now):
        return read(replace(state, variations=tuple(v for v in state.variations if v.contract_id != REDACT.id)),
                    adapter, actor, key, now)

    def rollback_all(state, identifier, actor, exact):
        selected = next(v for v in state.variations if v.id == identifier)
        return replace(state, revision=state.revision + 1, variations=tuple(
            replace(v, revoked=True) if v.tenant == selected.tenant else v for v in state.variations))

    def no_host_fence(state, adapter, actor, key, now):
        return read(replace(state, hosts=tuple(adapter.manifest if h.host == adapter.manifest.host else h
                                               for h in state.hosts)), adapter, actor, key, now)

    def no_approval_fence(state, plan, current, target, actor, exact, now):
        return replace(state, revision=state.revision + 1, hosts=tuple(
            target.manifest if h.host == target.manifest.host else h for h in state.hosts))

    defects = (("removed_tenant_check", {"reader": tenant_bypass}, "cross_tenant"),
               ("ignored_expiry", {"reader": expiry_bypass}, "expiry"),
               ("lost_redaction", {"reader": drop_redaction}, "redaction"),
               ("rollback_all_variations", {"revoker": rollback_all}, "selective_rollback"),
               ("removed_host_version_fence", {"reader": no_host_fence}, "old_adapter_fenced"),
               ("removed_upgrade_approval_fences", {"upgrader": no_approval_fence}, "exact_upgrade_approval"))
    result = []
    for name, kwargs, expected in defects:
        checks = invariant_checks(**kwargs)
        failures = [key for key, passed in checks.items() if not passed]
        result.append({"defect": name, "expected_detection": expected,
                       "detected": expected in failures, "failed_checks": failures})
    return result


def experiment():
    state = prepared()
    checks = invariant_checks()
    mutations = defect_controls()
    journeys = []
    for adapter_type, key, nova_key in ((ProjectDocuments, "atlas-plan", "nova-plan"),
                                        (WorkOrders, "WO-701", "WO-802")):
        v1, v2 = adapter_type(), adapter_type(2)
        before = read(state, v1, CONTRACTOR, key, NOW)
        nova_before = read(state, v1, NOVA, nova_key, NOW)
        plan = plan_upgrade(state, v1, v2, NOW)
        upgraded = approve_upgrade(state, plan, v1, v2, OWNER, plan.hash, NOW)
        after = read(upgraded, v2, CONTRACTOR, key, NOW)
        nova_after = read(upgraded, v2, NOVA, nova_key, NOW)
        rolled = revoke(upgraded, f"{v1.manifest.host}-notes", ADMIN, upgraded.hash)
        granted_rollback = revoke(rolled, f"{v1.manifest.host}-grant", ADMIN, rolled.hash)
        journeys.append({"host": v1.manifest.host, "plan": asdict(plan), "plan_hash": plan.hash,
                         "before": asdict(before), "after": asdict(after),
                         "parity": before == after, "nova_before": asdict(nova_before),
                         "nova_after": asdict(nova_after), "nova_unchanged": nova_before == nova_after,
                         "selective_redaction_rollback": asdict(read(rolled, v2, CONTRACTOR, key, NOW)),
                         "grant_rollback": asdict(read(granted_rollback, v2, CONTRACTOR, key, NOW)),
                         "expired": asdict(read(upgraded, v2, CONTRACTOR, key, NOW + 3600)),
                         "old_adapter": asdict(read(upgraded, v1, CONTRACTOR, key, NOW))})
    bad = ProjectDocuments(2, unsafe_semantics=True)
    unsafe = plan_upgrade(state, ProjectDocuments(), bad, NOW)
    conflict = raises(VariationConflict, lambda: propose(state, new_variation("duplicate")))
    flags = (ManualFlag("atlas", "projects", "atlas-project", CONTRACTOR.id, NOW + 3600,
                        ("customer_email", "internal_notes")),
             ManualFlag("atlas", "workorders", "A-17", CONTRACTOR.id, NOW + 3600,
                        ("customer_email", "internal_notes")))
    comparisons = []
    for adapter, keys in ((ProjectDocuments(), ("atlas-plan", "atlas-other", "nova-plan")),
                          (WorkOrders(), ("WO-701", "WO-802"))):
        for actor in (CONTRACTOR, NOVA):
            for key in keys:
                for clock in (NOW, NOW + 3600):
                    actual = read(state, adapter, actor, key, clock)
                    baseline = manual_flag_read(adapter, actor, key, clock, flags)
                    comparisons.append({"host": adapter.manifest.host, "actor": actor.id, "key": key,
                                        "time": clock, "same_effect": (actual.allowed, actual.fields) ==
                                        (baseline.allowed, baseline.fields)})
    initial = LabState(0, state.hosts)
    pending = propose(initial, new_variation("preview"))
    preview_result = preview(initial, pending, ProjectDocuments(), CONTRACTOR, "atlas-plan", NOW)
    return {"positive_controls": checks, "defect_controls": mutations, "journeys": journeys,
            "unsafe_migration": {"plan": asdict(unsafe), "plan_hash": unsafe.hash,
                                 "rejected": raises(FenceError, lambda: approve_upgrade(
                                     state, unsafe, ProjectDocuments(), bad, OWNER, unsafe.hash, NOW))},
            "overlapping_grant_rejected": conflict, "counterfactual_preview": preview_result,
            "manual_feature_flag_comparison": comparisons, "branch_fixture_comparison": branch_edit_comparison(),
            "passed": all(checks.values()) and all(m["detected"] for m in mutations) and conflict and
                      all(j["parity"] and j["nova_unchanged"] for j in journeys) and
                      all(row["same_effect"] for row in comparisons)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New local evidence directory")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    sources = [ROOT / "src/ownstack/compatibility.py", Path(__file__),
               ROOT / "tests/test_compatibility.py", *sorted((ROOT / "sample_apps_compat").glob("*.py"))]
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    report = {"schema": "ownstack-compatibility-lab-v1", "executed_at_utc": datetime.now(timezone.utc).isoformat(),
              "synthetic_clock": NOW, "live_inference_calls": 0, "database_access": False,
              "source_hashes": hashes,
              "limits": ["Two owned synthetic adapters, not arbitrary integrations",
                         "Semantic declarations are trusted fixture metadata, not a general proof",
                         "In-memory immutable state, not a durable production migration service",
                         "Synthetic admin and owner approvals, not independent human review",
                         "Finite defect controls, not exhaustive security",
                         "No customer, willingness-to-pay or human-time result",
                         "Content hashes detect changes but are not signed attestations"]}
    exit_code = 0
    try:
        report["result"] = experiment()
        report["passed"] = report["result"]["passed"]
        if not report["passed"]:
            exit_code = 1
    except Exception as exc:
        report.update(passed=False, error={"type": type(exc).__name__, "message": str(exc)})
        exit_code = 1
    report["elapsed_seconds"] = round(time.monotonic() - started, 6)
    report["source_unchanged_during_run"] = all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value
                                               for name, value in hashes.items())
    if not report["source_unchanged_during_run"]:
        report["passed"] = False
        exit_code = 1
    report["content_digest"] = digest(report)
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    with (args.output / "report.json").open("x") as handle:
        handle.write(serialized)
    with (args.output / "report.sha256").open("x") as handle:
        handle.write(hashlib.sha256(serialized.encode()).hexdigest() + "  report.json\n")
    print(json.dumps({"passed": report["passed"], "report": str(args.output / "report.json"),
                      "live_inference_calls": 0}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
