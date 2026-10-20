"""Bounded evidence graph over authoritative SQL repair phases.

No graph checkpoints, automatic retries, LLM judges or deployment tools. SQL
records are the durable continuation; one invocation claims at most one phase.
This deliberately prevents checkpoint replay from repeating a paid operation.
"""
from functools import lru_cache
from importlib.metadata import version
import operator
from pathlib import Path
from typing import Annotated, Literal, TypedDict
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langsmith import tracing_context
from ownstack.policy import digest
from ownstack.repair_execution import RepairExecution

SCHEMA = "ownstack-repair-evidence-v1"


class RepairState(TypedDict, total=False):
    phase: Literal["idle", "generating", "verifying"]
    attempt_id: str | None
    worked: bool
    accepted: bool
    outcome: str
    reviews: Annotated[list[dict], operator.add]
    trace: Annotated[list[str], operator.add]


def workflow_identity():
    return {"workflow_schema": SCHEMA, "langgraph_version": version("langgraph"),
            "workflow_hash": digest({name: Path(__file__).with_name(name).read_text() for name in
                ("repair_graph.py", "repair_execution.py", "repair.py")})}


def _claim(state: RepairState, runtime: Runtime[RepairExecution]):
    return runtime.context.claim()


def _generate(state: RepairState, runtime: Runtime[RepairExecution]):
    return runtime.context.generate()


def _scope(state: RepairState, runtime: Runtime[RepairExecution]):
    return runtime.context.scope_review()


def _snapshot(state: RepairState, runtime: Runtime[RepairExecution]):
    return runtime.context.snapshot_review()


def _verify(state: RepairState, runtime: Runtime[RepairExecution]):
    return runtime.context.verify_artifact()


def _save_candidate(state: RepairState, runtime: Runtime[RepairExecution]):
    return runtime.context.finish_generation(state)


def _save_checks(state: RepairState, runtime: Runtime[RepairExecution]):
    return runtime.context.finish_verification(state)


def _outcome(state: RepairState, runtime: Runtime[RepairExecution]):
    return runtime.context.outcome()


@lru_cache(maxsize=1)
def compiled_graph():
    graph = StateGraph(RepairState, context_schema=RepairExecution)
    for name, node in [("claim", _claim), ("generate", _generate), ("review_scope", _scope),
                       ("review_snapshot", _snapshot), ("verify_artifact", _verify),
                       ("persist_candidate", _save_candidate), ("persist_checks", _save_checks),
                       ("saved_outcome", _outcome)]:
        graph.add_node(name, node)
    graph.add_edge(START, "claim")
    graph.add_conditional_edges("claim", lambda state: state["phase"], {
        "idle": "saved_outcome", "generating": "generate", "verifying": "review_scope"})
    graph.add_edge("generate", "review_scope")
    def after_scope(state):
        if state["phase"] == "generating":
            return "persist_candidate"
        return ["verify_artifact", "review_snapshot"] if state["reviews"][0]["passed"] else "persist_checks"
    graph.add_conditional_edges("review_scope", after_scope,
        ["persist_candidate", "verify_artifact", "review_snapshot", "persist_checks"])
    graph.add_edge(["verify_artifact", "review_snapshot"], "persist_checks")
    graph.add_edge("persist_candidate", "saved_outcome")
    graph.add_edge("persist_checks", "saved_outcome")
    graph.add_edge("saved_outcome", END)
    return graph.compile(name=SCHEMA)


def run_graph(execution):
    # A developer's LangSmith env must not export private tenant data implicitly.
    with tracing_context(enabled=False):
        return compiled_graph().invoke({"trace": [], "reviews": []}, context=execution,
            config={"recursion_limit": 12, "max_concurrency": 2, "callbacks": []})
