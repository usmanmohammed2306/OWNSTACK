"""Offline controlled comparison of LangGraph and sequential repair orchestration.

Synthetic provider/verifier, real SQL persistence and process exits. No candidate
code execution, model quality, main database access, live calls or paid resources.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for name, value in {"OWNSTACK_AI_MODE": "fixture", "OWNSTACK_MAX_LIVE_CALLS": "0",
                   "OWNSTACK_ENV": "local", "NEBIUS_API_KEY": "", "NEBIUS_MODEL_ID": "",
                   "NEBIUS_PATCH_MODEL_ID": "", "LANGSMITH_TRACING": "false",
                   "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_API_KEY": ""}.items():
    os.environ[name] = value

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from ownstack.config import Settings
from ownstack.db import Base, make_engine
from ownstack.models import ChangeRequest, EngineeringItem, Event, Evidence, InferenceBudget, Tenant, User
from ownstack.patch_agent import fixture_patch
from ownstack.pdf_oracle import CASE_IDS, ORACLE_VERSION
from ownstack.policy import Principal, digest
from ownstack.repair import (run_repair_one, serialize_run, start_repair, stop_repair)
from ownstack.repair_execution import RepairExecution
from ownstack.repair_graph import compiled_graph, workflow_identity
from ownstack.repair_models import RepairRun, RepairAttempt
from ownstack.runner import current_provenance, patch_hash
from ownstack.service import utcnow

CASES = {
    "first_pass": "awaiting_review", "failure_then_pass": "awaiting_review",
    "two_failures": "manual_handoff", "invalid_model_output": "manual_handoff",
    "invalid_patch_scope": "manual_handoff", "verifier_unavailable": "manual_handoff",
    "forged_verdict": "manual_handoff", "partial_verdict": "manual_handoff",
    "wrong_model": "manual_handoff", "human_takeover": "taken_over",
    "late_first_candidate": "awaiting_review", "request_revision_changed": "taken_over",
    "saved_state_replay": "awaiting_review", "ai_off": "manual_handoff",
    "exhausted_budget": "manual_handoff", "workflow_changed": "manual_handoff",
}
PRINCIPAL = Principal("graph-engineer", "lab", "engineer")


def oracle(patch, passed=True):
    return {"passed": passed, "patch_hash": patch_hash(patch), "oracle_version": ORACLE_VERSION,
        "checks_expected": len(CASE_IDS), "checks_completed": len(CASE_IDS),
        "cases": [{"id": key, "passed": passed, "pdf_sha256": "0" * 64} for key in sorted(CASE_IDS)],
        "runner": "synthetic-graph-lab-not-executed", "stderr": "" if passed else "Synthetic mismatch",
        **current_provenance()}


def setup_database(path):
    engine = make_engine("sqlite:///" + str(path.resolve()))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(Tenant(id="lab", name="Synthetic graph comparison"))
        db.flush()
        from ownstack.team_scope import ensure_general_team,add_general_member
        ensure_general_team(db,'lab')
        user=User(id=PRINCIPAL.user_id, tenant_id="lab", role="engineer", password_hash="not-a-login")
        db.add(user);db.flush();add_general_member(db,user)
        db.add(InferenceBudget(id="global", reserved_calls=10))
        db.commit()
    return engine, factory


def setup_run(factory, label, settings=None):
    patch = fixture_patch()
    patch["edits"][0]["new"] = "def export_pdf(project_name, rows):\n    return b'bad'\n"
    with factory() as db:
        db.add(ChangeRequest(id=label + "-request", tenant_id="lab", requester_id=PRINCIPAL.user_id,
            text="Synthetic graph lab PDF request", kind="feature", status="engineering", revision=1))
        db.flush()
        db.add(EngineeringItem(id=label + "-item", tenant_id="lab", request_id=label + "-request",
            patch=patch, patch_hash=patch_hash(patch), status="checks_failed"))
        db.add(Evidence(id=label + "-failure", tenant_id="lab", request_id=label + "-request",
            kind="patch_checks", subject_hash=patch_hash(patch), result={"passed": False},
            limitation="Synthetic starting fixture; no candidate executed."))
        db.commit()
    with factory() as db:
        run = start_repair(db, label + "-item", PRINCIPAL, label + "-key", patch_hash(patch), settings=settings)
        db.commit()
        return run.id


def summary(factory, run_id):
    with factory() as db:
        run = db.get(RepairRun, run_id)
        saved = serialize_run(db, run)
        item = db.get(EngineeringItem, run.item_id)
        return {"state": run.state, "attempt_states": [a["state"] for a in saved["attempts"]],
            "candidate_saved": [a["candidate"] is not None for a in saved["attempts"]],
            "original_preserved": item.patch_hash == run.original_patch_hash,
            "human_decision": item.human_decision, "reserved_calls": db.get(InferenceBudget, "global").reserved_calls,
            "release_state": saved["release_state"]}


def scenario(factory, engine, case, label):
    settings = Settings(ai_mode="fixture", max_live_calls=0, nebius_key="", nebius_model="")
    if case == "exhausted_budget":
        # Deliberately fake ID/key, exhausted counter, injected provider; never a dispatch.
        settings = Settings(ai_mode="nebius", max_live_calls=10, nebius_key="synthetic-never-dispatched",
                            nebius_model="nvidia/graph-lab-Nemotron")
    run_id = setup_run(factory, label, settings)
    if case == "ai_off":
        settings = Settings(ai_mode="off", max_live_calls=0)
    if case == "workflow_changed":
        with factory() as db:
            run = db.get(RepairRun, run_id)
            run.configuration = {**run.configuration, "workflow_hash": "synthetic-old-version"}
            db.commit()
    calls, checks, phase_ms = [], [], []
    def propose(_text, _settings, *, repair_context):
        calls.append(1)
        if case == "invalid_model_output":
            raise ValueError("Synthetic invalid JSON")
        if case == "human_takeover":
            with factory() as db:
                stop_repair(db, run_id)
                db.commit()
        if case == "request_revision_changed":
            with factory() as db:
                db.get(ChangeRequest, label + "-request").revision += 1
                db.commit()
        if case == "late_first_candidate" and len(calls) == 1:
            with factory() as db:
                attempt = db.get(RepairAttempt, db.get(RepairRun, run_id).current_attempt_id)
                attempt.deadline_at = utcnow() - timedelta(seconds=1)
                db.commit()
        patch = fixture_patch()
        if case == "invalid_patch_scope":
            patch["edits"][0]["path"] = "src/ownstack/policy.py"
        return patch, "different-model" if case == "wrong_model" else "fixture-not-live", {"live": False}
    def verify(patch):
        checks.append(1)
        if case == "verifier_unavailable":
            raise RuntimeError("Synthetic verifier failure")
        if case == "forged_verdict":
            return {"passed": True, "exit_code": 0}
        result = oracle(patch, case != "two_failures" and (case != "failure_then_pass" or len(checks) > 1))
        if case == "partial_verdict":
            result["cases"] = result["cases"][:-1]
        return result
    for _ in range(6):
        started = time.perf_counter_ns()
        worked = run_repair_one(factory, settings, propose=propose, verify=verify, engine=engine)
        phase_ms.append((time.perf_counter_ns() - started) / 1_000_000)
        if not worked:
            break
    saved = summary(factory, run_id)
    invariants = {
        "expected_outcome": saved["state"] == CASES[case],
        "bounded_calls": len(calls) <= 2, "bounded_attempts": len(saved["attempt_states"]) <= 2,
        "no_silent_adoption": saved["original_preserved"] and saved["human_decision"] is None,
        "not_deployed": saved["release_state"] == "not_deployed", "budget_ten_preserved": saved["reserved_calls"] == 10,
        "off_and_cap_no_dispatch": case not in {"ai_off", "exhausted_budget", "workflow_changed"} or not calls,
        "bad_scope_no_verifier": case != "invalid_patch_scope" or not checks,
        "late_candidate_discarded": case != "late_first_candidate" or saved["candidate_saved"][0] is False,
    }
    return {"case": case, "engine": engine, "saved": saved, "synthetic_generator_calls": len(calls),
            "synthetic_verifier_calls": len(checks), "phase_ms": phase_ms, "checks": invariants,
            "passed": all(invariants.values())}


def child(args):
    factory = sessionmaker(bind=make_engine("sqlite:///" + str(args.child.resolve())), expire_on_commit=False)
    # Count only synthetic dispatch starts, durably, before the explicit fault.
    def propose(*_args, **_kwargs):
        if args.fault == "after_claim":
            os._exit(23)
        with factory() as db:
            run = db.get(RepairRun, args.run_id)
            db.add(Event(id="lab-dispatch-" + args.fault, tenant_id="lab", request_id=run.request_id,
                         event_type="lab.synthetic_dispatch", payload={"live": False}))
            db.commit()
        return fixture_patch(), "fixture-not-live", {"live": False}
    original = RepairExecution.finish_generation
    def crash_after_commit(self, state):
        original(self, state)
        os._exit(24)
    if args.fault == "after_candidate_commit":
        RepairExecution.finish_generation = crash_after_commit
    run_repair_one(factory, propose=propose, verify=oracle)
    return 0


def process_experiment(factory, database, run_id, fault):
    cmd = [sys.executable, str(Path(__file__).resolve()), "--child", str(database),
           "--run-id", run_id, "--fault", fault]
    result = subprocess.run(cmd, cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                            capture_output=True, text=True, timeout=30)
    expected = 23 if fault == "after_claim" else 24
    before = summary(factory, run_id)
    called = []
    run_repair_one(factory, propose=lambda *a, **kw: called.append(1), verify=oracle)
    after = summary(factory, run_id)
    with factory() as db:
        dispatches = db.scalar(select(func.count(Event.id)).where(Event.event_type == "lab.synthetic_dispatch"))
    return {"fault": fault, "exit_code": result.returncode, "expected_exit": expected,
        "before": before, "after": after, "regeneration_calls": len(called),
        "synthetic_dispatch_count_total": dispatches,
        "passed": result.returncode == expected and not called
                  and before["reserved_calls"] == after["reserved_calls"] == 10
                  and after["state"] == ("running" if fault == "after_claim" else "awaiting_review")}


def interrupt_replay_experiment():
    """Reproduce documented node replay with synthetic counters, never a provider."""
    from typing import TypedDict
    from langgraph.graph import END, START, StateGraph
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command, interrupt
    from langsmith import tracing_context
    class State(TypedDict, total=False):
        proposed: bool
        reviewed: bool
    results = {}
    for variant in ("side_effect_before_interrupt", "separate_generation_node"):
        calls = []
        def generate(state):
            calls.append("synthetic-dispatch")
            return {"proposed": True}
        def review(state):
            decision = interrupt({"kind": "synthetic-review-only"})
            return {"reviewed": decision is True}
        def naive(state):
            generate(state)
            return review(state)
        builder = StateGraph(State)
        if variant == "side_effect_before_interrupt":
            builder.add_node("naive", naive)
            builder.add_edge(START, "naive")
            builder.add_edge("naive", END)
        else:
            builder.add_node("generate", generate)
            builder.add_node("review", review)
            builder.add_edge(START, "generate")
            builder.add_edge("generate", "review")
            builder.add_edge("review", END)
        graph = builder.compile(checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": variant}, "callbacks": []}
        with tracing_context(enabled=False):
            paused = graph.invoke({}, config)
            before = len(calls)
            completed = graph.invoke(Command(resume=True), config)
        results[variant] = {"paused": bool(paused.get("__interrupt__")),
            "calls_before_resume": before, "calls_after_resume": len(calls),
            "reviewed": completed["reviewed"]}
    results["passed"] = (results["side_effect_before_interrupt"]["calls_after_resume"] == 2
                         and results["separate_generation_node"]["calls_after_resume"] == 1
                         and all(results[name]["paused"] for name in
                                 ("side_effect_before_interrupt", "separate_generation_node")))
    results["limit"] = "Native in-memory interrupt lesson only; not the app's authenticated durable review gate"
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--child", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--run-id", help=argparse.SUPPRESS)
    parser.add_argument("--fault", choices=["after_claim", "after_candidate_commit"], help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return child(args)
    if not args.output or not 1 <= args.repeats <= 10:
        parser.error("--output NEW_DIRECTORY and --repeats 1 to 10 required")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    database = output / "synthetic-graph.db"
    engine, factory = setup_database(database)
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "case_set": digest(CASES),
        "synthetic_provider": True, "synthetic_verifier": True, "live_calls": 0,
        "compiled_workflow": workflow_identity(), "runs": [], "process_faults": [],
        "limits": ["Authored finite controls, not live Nemotron or independent review.",
                   "SQLite and synthetic verifier, not PostgreSQL, Docker isolation or a production SLA.",
                   "Timing includes local SQL and orchestration; no model/network latency.",
                   "Sequential baseline shares trusted operations; no framework superiority assumed."]}
    try:
        started = time.perf_counter_ns()
        compiled_graph()
        report["cold_compile_ms"] = (time.perf_counter_ns() - started) / 1_000_000
        for repetition in range(args.repeats):
            for case in CASES:
                # Alternate order to reduce one-sided warm-cache bias.
                engines = ["plain", "langgraph"] if repetition % 2 == 0 else ["langgraph", "plain"]
                paired = []
                for scheduler in engines:
                    result = scenario(factory, scheduler, case, f"r{repetition}-{case}-{scheduler}")
                    report["runs"].append(result)
                    paired.append(result)
                if paired[0]["saved"] != paired[1]["saved"]:
                    raise AssertionError("Orchestrator outcome mismatch")
                if not all(row["passed"] for row in paired):
                    raise AssertionError("A scenario failed its declared invariant")
                # Retain terminal/pending review evidence, stop it before next scenario.
                with factory() as db:
                    for run in db.scalars(select(RepairRun).where(RepairRun.state == "awaiting_review")):
                        stop_repair(db, run.id)
                    db.commit()
        for fault in ("after_claim", "after_candidate_commit"):
            run_id = setup_run(factory, "process-" + fault)
            result = process_experiment(factory, database, run_id, fault)
            report["process_faults"].append(result)
            if not result["passed"]:
                raise AssertionError("Process continuation failed")
            with factory() as db:
                stop_repair(db, run_id)
                db.commit()
        report["interrupt_replay_control"] = interrupt_replay_experiment()
        if not report["interrupt_replay_control"]["passed"]:
            raise AssertionError("Native interrupt replay control did not match its expectation")
        report["timing_ms"] = {}
        for scheduler in ("plain", "langgraph"):
            values = sorted(value for row in report["runs"] if row["engine"] == scheduler for value in row["phase_ms"])
            report["timing_ms"][scheduler] = {"samples": len(values), "median": statistics.median(values),
                "p95": values[max(0, int(.95 * len(values)) - 1)], "raw": values}
        report["passed"] = True
    except Exception as error:
        report["passed"], report["error_type"] = False, type(error).__name__
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["source_sha256"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
            ("src/ownstack/repair.py", "src/ownstack/repair_graph.py", "src/ownstack/repair_execution.py", "scripts/run_graph_lab.py")}
        report["executions"] = len(report["runs"])
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        engine.dispose()
    print(json.dumps({"passed": report["passed"], "executions": report["executions"],
                      "process_faults": len(report["process_faults"]), "live_calls": 0}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
