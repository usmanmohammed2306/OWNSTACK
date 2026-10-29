"""Independent expectations for the offline evaluator; no provider or database."""
import json
from pathlib import Path
import pytest
from ownstack import trajectory_eval as lab

CASES = Path(__file__).resolve().parents[1] / "evals/investigation_v1/cases.json"


def test_entire_authored_suite_runs_real_graph_without_provider(monkeypatch):
    monkeypatch.setattr("ownstack.investigation.provider_decision", lambda *a: pytest.fail("No inference allowed"))
    report = lab.evaluate_file(CASES)
    assert report["passed"] == report["total"] == 17
    assert report["live_calls"] == 0
    assert report["mode"] == "offline-graph-contract-evaluation"
    cases = {row["id"]: row for row in report["cases"]}
    assert cases["access-baseline"]["attempted_decisions"] == 3
    assert cases["extra-witness-cost-control"]["attempted_decisions"] == 4
    assert all(row["outcome"] == "blocked" for row in report["cases"] if row["group"] == "hostile-decision")
    assert all(row["assertions"]["snapshot_unchanged"] for row in report["cases"])
    assert "request_text" not in json.dumps(report)


def test_a_guard_regression_is_a_failed_case_not_a_self_graded_pass(monkeypatch):
    monkeypatch.setattr(lab, "advance", lambda *a: {"step": {"action":"conclude"},
        "result": {"handoff":"review_code", "citations":[]}})
    result = lab.evaluate_case({"id":"oracle-control", "group":"control",
        "expected":{"outcome":"blocked", "error":"UNSUPPORTED_CITATION"}})
    assert result["passed"] is False
    assert result["assertions"]["expected_outcome"] is False


def test_unexpected_runtime_failure_is_not_relabelled_a_safe_rejection(monkeypatch):
    def crash(*args):
        raise RuntimeError("infrastructure fault")
    monkeypatch.setattr(lab, "advance", crash)
    with pytest.raises(RuntimeError, match="infrastructure fault"):
        lab.evaluate_case({"id":"crash", "group":"control", "expected":{"outcome":"blocked"}})


def test_duplicate_cases_are_rejected(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"schema":"ownstack-investigation-cases-v1", "cases":[{"id":"same"}, {"id":"same"}]}))
    with pytest.raises(ValueError, match="Duplicate"):
        lab.evaluate_file(path)


def test_fifth_decision_fails_the_actual_graph_step_limit():
    case = {"id":"budget", "group":"control", "decisions":[{"action":"inspect_request", "citations":[], "note":""}],
        "expected":{"outcome":"blocked", "error":"STEP_LIMIT"}}
    memory = lab.synthetic_memory(case)
    memory["steps"] = [{"action":"inspect_request"}] * 4
    with pytest.raises(ValueError, match="STEP_LIMIT"):
        lab.advance(memory, lambda _: case["decisions"][0])
