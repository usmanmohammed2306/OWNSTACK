"""Offline trajectory contract evaluation, with independent case expectations.

Runs the real investigation graph with scripted decisions or its deterministic
baseline. No database, provider, API key, inference reservation or application
mutation is used. This measures host guards, not model quality or prompt safety.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter

from pydantic import ValidationError

from ownstack.investigation import advance, identity, offline_decision
from ownstack.policy import digest


def synthetic_memory(case):
    """Minimal owned witnesses; never load a real tenant or private app database."""
    request = {"kind": case.get("kind", "access"), "project_id": "atlas-project",
        "viewer_id": "atlas-contractor", "viewer_enabled": True,
        "viewer_role": "contractor", "expires_at": "2026-11-01T00:00:00+00:00",
        "text": case.get("request_text", "Temporary read-only access for Project Atlas.")}
    request.update(case.get("request_overrides", {}))
    return {"snapshot": {"request": request,
        "contract": {"available": case.get("contract_available", True)},
        "engineering": {"available": False, "saved_check_passed": None}}, "steps": []}


def evaluate_case(case):
    """Score an authored case without accepting its observed result as the oracle."""
    memory = synthetic_memory(case)
    original = deepcopy(memory["snapshot"])
    trace, result, error = [], None, None
    attempted = 0
    started = perf_counter()
    script = case.get("decisions")
    for index in range(5):
        if script is not None and index >= len(script):
            break
        try:
            attempted += 1
            chosen = deepcopy(script[index]) if script is not None else offline_decision(memory)
            step = advance(memory, lambda _memory: chosen)
            memory["steps"].append(step["step"])
            trace.append({"action": step["step"]["action"], "source": step["step"].get("source")})
            result = step["result"]
            if result is not None:
                break
        except ValidationError:
            error = "SCHEMA_REJECTED"
            break
        except ValueError as exc:
            # Only graph's constant diagnostic codes are exported, never input text.
            allowed = {"STEP_LIMIT", "INVALID_TOOL_SEQUENCE", "UNSUPPORTED_CITATION"}
            error = str(exc) if str(exc) in allowed else "GRAPH_REJECTED"
            break
    observed = {step.get("source") for step in memory["steps"] if step.get("source")}
    citations = {row["source"] for row in result["citations"]} if result else set()
    hashes_valid = all(row["hash"] == digest(original[row["source"]]) for row in result["citations"]) if result else None
    outcome = "blocked" if error else "completed" if result else "incomplete"
    expected = case["expected"]
    assertions = {
        "expected_outcome": outcome == expected["outcome"],
        "expected_handoff": (result["handoff"] if result else None) == expected.get("handoff"),
        "expected_error": error == expected.get("error"),
        "snapshot_unchanged": memory["snapshot"] == original,
        "cites_observed_only": citations <= observed,
        "citation_hashes": hashes_valid is not False,
    }
    if "inspected_sources" in expected:
        assertions["expected_sources"] = sorted(observed) == sorted(expected["inspected_sources"])
    return {"id": case["id"], "group": case["group"], "passed": all(assertions.values()),
        "outcome": outcome, "handoff": result["handoff"] if result else None,
        "error": error, "trace": trace, "attempted_decisions": attempted, "citation_sources": sorted(citations),
        "assertions": assertions, "elapsed_ms": round((perf_counter() - started) * 1000, 3)}


def evaluate_file(path: Path):
    dataset = json.loads(path.read_text())
    if dataset.get("schema") != "ownstack-investigation-cases-v1" or not dataset.get("cases"):
        raise ValueError("Invalid trajectory dataset")
    cases = dataset["cases"]
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate case IDs")
    results = [evaluate_case(case) for case in cases]
    return {"schema": "ownstack-trajectory-eval-v1", "mode": "offline-graph-contract-evaluation",
        "created_at": datetime.now(timezone.utc).isoformat(), "live_calls": 0,
        "dataset_sha256": digest(dataset), "workflow_hash": identity(),
        "evaluator_sha256": digest(Path(__file__).read_text()),
        "passed": sum(row["passed"] for row in results), "total": len(results), "cases": results,
        "limitations": "Authored synthetic cases and scripted choices. Not model accuracy, injection robustness, security certification, user utility or a held-out live comparison."}
