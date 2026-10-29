"""Real LangGraph, synthetic providers, independent domain assertions and no network."""
from datetime import timedelta
import json
from threading import Barrier
import pytest
from sqlalchemy import select
from ownstack.config import Settings
from ownstack.models import EngineeringItem, Event, InferenceBudget
from ownstack.repair import (adopt_candidate, claim_work, run_repair_one, serialize_run,
                            start_repair, stop_repair)
from ownstack.repair_execution import RepairExecution
from ownstack.repair_graph import compiled_graph, run_graph, workflow_identity
from ownstack.repair_models import RepairAttempt, RepairRun
from ownstack.runner import patch_hash
from ownstack.service import utcnow
from test_repair import ENGINEER, failed_item, oracle, proposal, start
from conftest import login


@pytest.mark.parametrize("engine", ["plain", "langgraph"])
@pytest.mark.parametrize("outcome", ["pass", "retry", "exhaust", "bad_scope", "bad_oracle"])
def test_engines_preserve_bounded_domain_results(fixture_db, engine, outcome):
    run_id = start(fixture_db)
    calls = []
    def generate(*args, **kwargs):
        calls.append(1)
        if outcome == "bad_scope":
            return {"edits": [{"path": "src/ownstack/policy.py", "old": "a", "new": "b"}]}, "fixture-not-live", {}
        return proposal(*args, **kwargs)
    checks = []
    def verify(patch):
        checks.append(1)
        if outcome == "bad_oracle":
            return {"passed": True, "exit_code": 0}
        return oracle(patch, outcome != "exhaust" and (outcome != "retry" or len(checks) > 1))
    for _ in range(5):
        run_repair_one(fixture_db, propose=generate, verify=verify, engine=engine)
    with fixture_db() as db:
        run, item = db.get(RepairRun, run_id), db.get(EngineeringItem, "repair-item")
        assert run.state == ("awaiting_review" if outcome in {"pass", "retry"} else "manual_handoff")
        assert len(calls) <= 2 and len(checks) <= 2
        assert item.patch_hash == run.original_patch_hash and item.human_decision is None
        assert db.get(InferenceBudget, "global").reserved_calls == 0
        assert len(serialize_run(db, run)["attempts"]) <= 2
        if outcome == "bad_scope":
            assert checks == []


def test_graph_is_actual_framework_with_conditional_and_join_edges():
    graph = compiled_graph()
    assert type(graph).__module__.startswith("langgraph.")
    assert graph.checkpointer is None  # SQL is the only durable continuation.
    nodes = graph.get_graph().nodes
    assert {"claim", "generate", "review_scope", "review_snapshot", "verify_artifact", "persist_checks"} <= set(nodes)


def test_graph_parallel_reviewers_really_join(fixture_db, monkeypatch):
    start(fixture_db)
    run_repair_one(fixture_db, propose=proposal)
    barrier = Barrier(2)
    original_snapshot = RepairExecution.snapshot_review
    def snapshot(self):
        barrier.wait(timeout=3)
        return original_snapshot(self)
    def verifier(patch):
        barrier.wait(timeout=3)
        return oracle(patch)
    monkeypatch.setattr(RepairExecution, "snapshot_review", snapshot)
    assert run_repair_one(fixture_db, verify=verifier)
    with fixture_db() as db:
        run = db.scalar(select(RepairRun))
        assert run.state == "awaiting_review"
        phase = serialize_run(db, run)["workflow"]["last_phase"]
        assert phase["engine"] == "langgraph"
        assert {r["role"] for r in phase["reviews"]} == {"patch_scope", "current_snapshot"}
        assert phase["nodes"][-1] == "persist_checks"


def test_graph_state_and_persisted_trace_do_not_contain_prompt_code_or_settings(fixture_db):
    start(fixture_db)
    execution = RepairExecution(fixture_db, Settings(), proposal, oracle)
    result = run_graph(execution)
    encoded = json.dumps(result)
    assert result["outcome"] == "running" and result["accepted"]
    assert "text" not in result and "candidate" not in result and "settings" not in result
    assert "Add PDF export for Atlas" not in encoded and "export_pdf" not in encoded
    with fixture_db() as db:
        event = db.scalar(select(Event).where(Event.event_type == "repair.workflow_phase"))
        saved = json.dumps(event.payload)
        assert "export_pdf" not in saved and "Add PDF export for Atlas" not in saved
        assert event.payload["workflow_hash"] == workflow_identity()["workflow_hash"]


def test_external_tracing_is_disabled_even_when_developer_environment_enables_it(fixture_db, monkeypatch):
    import langsmith
    calls = []
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "synthetic-do-not-send")
    monkeypatch.setattr(langsmith.Client, "create_run", lambda *a, **kw: calls.append(1))
    start(fixture_db)
    run_repair_one(fixture_db, propose=proposal)
    assert calls == []


def test_scope_failure_never_executes_candidate_in_verifier(fixture_db):
    run_id = start(fixture_db)
    run_repair_one(fixture_db, propose=proposal)
    with fixture_db() as db:
        attempt = db.get(RepairAttempt, db.get(RepairRun, run_id).current_attempt_id)
        attempt.candidate = {"edits": []}
        db.commit()
    called = []
    run_repair_one(fixture_db, verify=lambda patch: called.append(patch))
    with fixture_db() as db:
        assert db.get(RepairRun, run_id).state == "manual_handoff"
    assert called == []


def test_workflow_source_fence_stops_ready_candidate_before_any_external_work(fixture_db, monkeypatch):
    run_id = start(fixture_db)
    run_repair_one(fixture_db, propose=proposal)
    identity = workflow_identity()
    monkeypatch.setattr("ownstack.repair_graph.workflow_identity", lambda: {**identity, "workflow_hash": "changed"})
    called = []
    run_repair_one(fixture_db, verify=lambda patch: called.append(1))
    with fixture_db() as db:
        assert db.get(RepairRun, run_id).state == "manual_handoff"
    assert called == []


def test_false_snapshot_review_cannot_be_outvoted_by_oracle(fixture_db, monkeypatch):
    run_id = start(fixture_db)
    run_repair_one(fixture_db, propose=proposal)
    original = RepairExecution.snapshot_review
    def rejected(self):
        result = original(self)
        result["reviews"][0]["passed"] = False
        return result
    monkeypatch.setattr(RepairExecution, "snapshot_review", rejected)
    run_repair_one(fixture_db, verify=oracle)
    with fixture_db() as db:
        assert db.get(RepairRun, run_id).state == "manual_handoff"
        assert db.get(RepairRun, run_id).error_code == "WORKFLOW_REVIEW_REJECTED"


def test_saved_outcome_get_never_runs_graph_and_tenant_roles_still_apply(client, fixture_db, monkeypatch):
    run_id = start(fixture_db)
    run_repair_one(fixture_db, propose=proposal)
    run_repair_one(fixture_db, verify=oracle)
    monkeypatch.setattr("ownstack.repair_graph.run_graph", lambda *a, **kw: pytest.fail("GET must not run a graph"))
    engineer, nova, admin = login(client, "atlas-engineer"), login(client, "nova-admin"), login(client, "atlas-admin")
    response = client.get(f"/v1/repairs/{run_id}", headers=engineer)
    assert response.status_code == 200 and response.json()["workflow"]["human_review_required"]
    assert client.get(f"/v1/repairs/{run_id}", headers=nova).status_code == 404
    assert client.post(f"/v1/repairs/{run_id}/adopt", headers=admin,
                       json={"patch_hash": patch_hash(proposal(None, None, repair_context={"candidate": 1, "feedback": {}})[0])}).status_code == 403
