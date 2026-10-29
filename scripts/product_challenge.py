"""A read-only product challenge, not a universal product certification.

The offline mode binds related controls to a supplied test run. The opt-in model
mode sends only authored synthetic command text to a pinned loopback checkpoint.
Neither mode executes plans, changes app data, or calls an external model API.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import time
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

import httpx
from ownstack.action_plans import validate_plan

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals/product_challenge_v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(directory: Path = DATASET):
    protocol = json.loads((directory / "protocol.json").read_text())
    cases = [json.loads(line) for line in (directory / "cases.jsonl").read_text().splitlines() if line.strip()]
    expected_fields = {"id", "band", "domain", "title", "story", "request", "required_outcome",
                       "disposition", "support", "gap", "controls", "acceptable"}
    if len(cases) != 50 or [c["id"] for c in cases] != [f"PC{i:02d}" for i in range(1, 51)]:
        raise ValueError("Exactly fifty uniquely ordered cases are required")
    if Counter(c["band"] for c in cases) != Counter({b: 10 for b in protocol["bands"]}):
        raise ValueError("Each challenge band needs ten cases")
    if len({c["request"].casefold() for c in cases}) != 50:
        raise ValueError("Duplicate command text")
    for case in cases:
        if set(case) != expected_fields:
            raise ValueError("Unexpected or missing case fields")
        for field in expected_fields - {"controls", "acceptable"}:
            if not isinstance(case[field], str) or not case[field].strip():
                raise ValueError(f"Missing {field}")
        if len(case["request"]) > 1000:
            raise ValueError("Command exceeds serving limit")
        if case["support"] not in {"owned_host_analogue", "related_control_only", "safety_control_only", "unsupported"}:
            raise ValueError("Unknown support class")
        if case["disposition"] not in {"bounded", "engineering", "refuse", "outside"}:
            raise ValueError("Unknown product disposition")
        if not isinstance(case["acceptable"], list) or not case["acceptable"]:
            raise ValueError("Expected UI behavior must be specified before evaluation")
        for plan in case["acceptable"]:
            validate_plan(json.dumps(plan), "admin")
        if not isinstance(case["controls"], list) or len(set(case["controls"])) != len(case["controls"]):
            raise ValueError("Invalid control references")
        for reference in case["controls"]:
            test_path, name = reference.split("::")
            path = (ROOT / test_path).resolve()
            if not path.is_relative_to(ROOT / "tests") or not path.is_file():
                raise ValueError("Control must refer to a project test")
            definitions = {node.name for node in ast.parse(path.read_text()).body
                           if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            if name not in definitions:
                raise ValueError(f"Missing test function: {reference}")
    return protocol, cases


def local_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment):
        raise ValueError("Only a plain loopback model endpoint is permitted")
    return value.rstrip("/")


def load_rule():
    # Fixed project source only, never an imported model result or user path.
    import sys
    training = str(ROOT / "training")
    if training not in sys.path:
        sys.path.insert(0, training)
    spec = importlib.util.spec_from_file_location("challenge_rule_baseline", ROOT / "training/rule_baseline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.baseline


def score(raw: str, case: dict) -> dict:
    """Schema validity and semantic intent are separate observations."""
    try:
        actual = validate_plan(raw, "admin").model_dump()
    except (ValueError, TypeError):
        return {"schema_valid": False, "acceptable_ui_plan": False, "actual": None}
    return {"schema_valid": True, "acceptable_ui_plan": actual in case["acceptable"], "actual": actual}


def control_evidence(cases: list[dict], junit: Path) -> dict:
    """Resolve every parametrization, including skips and absent test functions.

    A passing test is related evidence only. Source hashes record what exists at
    inspection time; they cannot prove an imported JUnit run used those bytes.
    """
    grouped = {}
    for test in ET.parse(junit).getroot().iter("testcase"):
        key = (test.get("classname", "").replace(".", "/") + ".py::"
               + test.get("name", "").split("[", 1)[0])
        outcome = "failed" if any(test.find(tag) is not None for tag in ("failure", "error")) else (
            "skipped" if test.find("skipped") is not None else "passed")
        grouped.setdefault(key, []).append(outcome)
    evidence = {}
    for reference in sorted({r for c in cases for r in c["controls"]}):
        observations = grouped.get(reference, [])
        evidence[reference] = {
            "status": "passed" if observations and set(observations) == {"passed"} else (
                "not_run" if not observations else "not_passed"),
            "observed_test_instances": len(observations),
            "outcomes": dict(Counter(observations)),
            "current_test_file_sha256": sha(ROOT / reference.split("::")[0]),
        }
    return evidence


def summarize(rows: list[dict]) -> dict:
    measures = {}
    for producer in ("rule", "model"):
        observed = [r[producer] for r in rows if producer in r]
        if observed:
            measures[producer] = {"total": len(observed),
                "schema_valid": sum(r["schema_valid"] for r in observed),
                "acceptable_ui_plan": sum(r["acceptable_ui_plan"] for r in observed)}
    times = [r["model_latency_ms"] for r in rows if "model_latency_ms" in r]
    if times:
        ordered = sorted(times)
        measures["model_latency_ms"] = {"median": statistics.median(times),
            "p95_nearest_rank": ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)],
            "scope": "model-reported generation duration, sequential local run; not HTTP latency or SLA"}
    return measures


def run(output: Path, junit: Path, endpoint: str | None = None, artifact: str | None = None):
    protocol, cases = load_cases()
    if endpoint:
        endpoint = local_endpoint(endpoint)
        if artifact is None or len(artifact) != 64 or any(c not in "0123456789abcdef" for c in artifact):
            raise ValueError("Pin the expected trained artifact SHA-256")
    elif artifact:
        raise ValueError("Artifact pin requires opt-in local model evaluation")
    # Each run owns a new directory. Earlier failures and results cannot be replaced.
    output.mkdir(parents=True, exist_ok=False)
    controls = control_evidence(cases, junit)
    baseline = load_rule()
    report = {"version": 1, "at": datetime.now(timezone.utc).isoformat(),
        "protocol": protocol, "dataset_sha256": sha(DATASET / "cases.jsonl"),
        "protocol_sha256": sha(DATASET / "protocol.json"), "evaluator_sha256": sha(Path(__file__)),
        "validator_sha256": sha(ROOT / "src/ownstack/action_plans.py"),
        "rule_source_sha256": sha(ROOT / "training/rule_baseline.py"),
        "junit_sha256": sha(junit), "related_controls": controls,
        "source_binding_limit": "Imported JUnit is not an attestation of current source; consult its original run binding.",
        "full_scenarios_executed": 0, "customer_observations": 0, "external_provider_calls": 0,
        "app_mutations": 0, "support_classes": dict(Counter(c["support"] for c in cases)), "rows": []}
    # trust_env=False avoids proxies. There are no external calls, execution tools
    # or mutations. The model is exercised directly as a local research worker,
    # not as a throughput test of the rate-limited authenticated app endpoint.
    service_key=os.getenv('OWNSTACK_PLANNER_SERVICE_TOKEN','')
    with httpx.Client(timeout=60, trust_env=False, follow_redirects=False,
                      headers={'X-OwnStack-Planner-Key':service_key} if service_key else {}) as client:
        if endpoint:
            response = client.get(endpoint + "/health"); response.raise_for_status()
            health = response.json()
            if health.get("ready") is not True or health.get("artifact") != artifact:
                raise ValueError("Expected local checkpoint is not ready")
            report["model_health"] = health
        for case in cases:
            row = {"id": case["id"], "band": case["band"], "support": case["support"],
                "complete_scenario_verified": False,
                "related_controls_all_passed": bool(case["controls"]) and all(
                    controls[r]["status"] == "passed" for r in case["controls"]),
                "rule": score(json.dumps(baseline(case["request"])), case)}
            if endpoint:
                begin = time.perf_counter()
                try:
                    response = client.post(endpoint + "/plan", json={"text": case["request"]})
                    response.raise_for_status()
                    if len(response.content) > 8192:
                        raise ValueError("Oversized result")
                    value = response.json()
                    if value.get("artifact") != artifact:
                        # Stop before mixing checkpoints or dispatching more work.
                        raise RuntimeError("Checkpoint changed during evaluation")
                    row["model"] = score(value["output"], case)
                    row["raw_model_output"] = value["output"]
                    latency = value["latency_ms"]
                    if type(latency) not in (int, float) or not 0 <= latency <= 60000:
                        raise ValueError("Invalid model measurement")
                    row["model_latency_ms"] = latency
                    row["http_elapsed_ms"] = round((time.perf_counter() - begin) * 1000, 2)
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    row["model"] = {"schema_valid": False, "acceptable_ui_plan": False, "actual": None}
                    # Class names only; no arbitrary HTTP bodies, URLs or secrets.
                    row["model_error"] = type(exc).__name__
            report["rows"].append(row)
            (output / "progress.json").write_text(json.dumps(report, indent=2) + "\n")
        report["measures"] = summarize(report["rows"])
        report["completed"] = True
        with (output / "report.json").open("x") as stream:
            stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"cases": len(cases), "related_control_status": dict(Counter(
        v["status"] for v in controls.values())), "support_classes": report["support_classes"],
        "measures": report["measures"], "full_scenarios_executed": 0,
        "external_provider_calls": 0, "app_mutations": 0}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New run directory, never an existing result")
    parser.add_argument("--junit", type=Path, required=True, help="Related existing control run, not scenario execution")
    parser.add_argument("--local-model", help="Opt in to exactly fifty sequential loopback planner generations")
    parser.add_argument("--artifact-sha256", help="Expected training manifest digest")
    args = parser.parse_args()
    run(args.output, args.junit, args.local_model, args.artifact_sha256)
