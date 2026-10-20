"""Trusted repair operations shared by the graph and its sequential comparator.

Graph state contains identifiers/verdicts only. Private request text, source,
provider settings and credentials remain in this per-invocation execution context.
The existing relational state machine owns claims, budget, recovery and adoption.
"""
from copy import deepcopy
import httpx
from ownstack.db import transaction
from ownstack.models import EngineeringItem
from ownstack.policy import aware
from ownstack.repair_models import RepairAttempt, RepairRun
from ownstack.runner import current_provenance, patch_hash
from ownstack.service import mark_pulse, record, utcnow


class RepairExecution:
    def __init__(self, factory, settings, propose, verify, *, engine="langgraph"):
        self.factory, self.settings = factory, settings
        self.propose, self.verify, self.engine = propose, verify, engine
        self.work = None
        self.patch, self.model, self.usage, self.verdict, self.error = None, None, None, None, None

    def claim(self):
        from ownstack.repair import claim_work, reap_repairs
        with transaction(self.factory) as db:
            mark_pulse(db, "worker")
            reaped = reap_repairs(db)
            self.work = claim_work(db, self.settings)
        return {"phase": self.work["phase"] if self.work else "idle", "worked": bool(reaped or self.work),
                "attempt_id": self.work["attempt_id"] if self.work else None, "trace": ["claim"]}

    def generate(self):
        try:
            self.patch, self.model, self.usage = self.propose(self.work["text"], self.settings,
                repair_context={"candidate": deepcopy(self.work["input_patch"]),
                                "feedback": deepcopy(self.work["feedback"])})
        except Exception as error:
            self.error = "MODEL_ERROR"
            if isinstance(error, httpx.TimeoutException):
                self.error = "MODEL_TIMEOUT"
            elif isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 429:
                self.error = "MODEL_RATE_LIMITED"
            elif isinstance(error, (ValueError, KeyError, TypeError)):
                self.error = "MODEL_OUTPUT_TRUNCATED" if str(error) == "MODEL_OUTPUT_TRUNCATED" else "INVALID_MODEL_OUTPUT"
        return {"trace": ["generate"]}

    def scope_review(self):
        candidate = self.patch if self.work["phase"] == "generating" else self.work["candidate"]
        try:
            subject = patch_hash(candidate)
            passed, code = True, "ALLOWLIST_AND_ANCHOR_VALID"
        except (ValueError, KeyError, TypeError, RecursionError):
            subject, passed, code = None, False, "INVALID_PATCH_SCOPE"
        return {"reviews": [{"role": "patch_scope", "passed": passed,
                              "subject_hash": subject, "code": code}], "trace": ["review_scope"]}

    def snapshot_review(self):
        from ownstack.repair import _matches
        with self.factory() as db:
            attempt = db.get(RepairAttempt, self.work["attempt_id"])
            run = db.get(RepairRun, attempt.run_id) if attempt else None
            item = db.get(EngineeringItem, run.item_id) if run else None
            passed = bool(run and attempt and run.state == "running"
                and run.current_attempt_id == attempt.id and attempt.state == "verifying"
                and _matches(db, run, item) and run.provenance == current_provenance()
                and aware(attempt.deadline_at) > utcnow() and aware(run.deadline_at) > utcnow())
            subject = attempt.candidate_hash if attempt else None
        return {"reviews": [{"role": "current_snapshot", "passed": passed, "subject_hash": subject,
                "code": "CURRENT_REPAIR_SNAPSHOT" if passed else "STALE_REPAIR_SNAPSHOT"}],
                "trace": ["review_snapshot"]}

    def verify_artifact(self):
        try:
            self.verdict = self.verify(deepcopy(self.work["candidate"]))
        except Exception:
            self.error = "VERIFIER_ERROR"
        return {"trace": ["verify_artifact"]}

    def _trace(self, db, state, accepted):
        attempt = db.get(RepairAttempt, self.work["attempt_id"])
        run = db.get(RepairRun, attempt.run_id)
        from ownstack.repair_graph import workflow_identity
        record(db, run.tenant_id, run.request_id, "repair.workflow_phase", {
            "run_id": run.id, "attempt_id": attempt.id, "phase": self.work["phase"],
            "engine": self.engine, **workflow_identity(), "nodes": state["trace"] + [
                "persist_candidate" if self.work["phase"] == "generating" else "persist_checks"],
            "node_order": "Supersteps; parallel reviewers are not wall-clock ordered",
            "reviews": sorted(state.get("reviews", []), key=lambda row: row["role"]),
            "accepted": accepted, "saved_run_state": run.state, "release_state": "not_deployed"})

    def finish_generation(self, state):
        from ownstack.repair import operation_failed, save_candidate
        with transaction(self.factory) as db:
            if self.error:
                operation_failed(db, self.work["attempt_id"], "generating", self.error)
                accepted = False
            else:
                accepted = save_candidate(db, self.work["attempt_id"], self.patch,
                                          self.model, self.usage, self.settings)
            self._trace(db, state, accepted)
        return {"accepted": accepted, "trace": ["persist_candidate"]}

    def finish_verification(self, state):
        from ownstack.repair import finish_checks, operation_failed
        with transaction(self.factory) as db:
            if self.error:
                operation_failed(db, self.work["attempt_id"], "verifying", self.error)
                accepted = False
            else:
                reviews = state.get("reviews", [])
                expected = {"patch_scope", "current_snapshot"}
                scoped = (len(reviews) == 2 and {r["role"] for r in reviews} == expected
                          and all(r["passed"] is True and r["subject_hash"] == patch_hash(self.work["candidate"])
                                  for r in reviews))
                if not scoped:
                    operation_failed(db, self.work["attempt_id"], "verifying", "WORKFLOW_REVIEW_REJECTED")
                    accepted = False
                else:
                    result = {**self.verdict, "workflow_reviews": reviews} if isinstance(self.verdict, dict) else self.verdict
                    accepted = finish_checks(db, self.work["attempt_id"], result)
            self._trace(db, state, accepted)
        return {"accepted": accepted, "trace": ["persist_checks"]}

    def outcome(self):
        if not self.work:
            return {"outcome": "idle", "trace": ["saved_outcome"]}
        with self.factory() as db:
            attempt = db.get(RepairAttempt, self.work["attempt_id"])
            run = db.get(RepairRun, attempt.run_id)
            return {"outcome": run.state, "trace": ["saved_outcome"]}


def run_sequential(execution):
    """Same trusted operations without the graph: an honest orchestration baseline."""
    state = {"trace": [], "reviews": []}
    def step(values):
        for key, value in values.items():
            state[key] = state.get(key, []) + value if key in {"trace", "reviews"} else value
    step(execution.claim())
    if state["phase"] == "generating":
        step(execution.generate())
        step(execution.scope_review())
        step(execution.finish_generation(state))
    elif state["phase"] == "verifying":
        step(execution.scope_review())
        if state["reviews"][0]["passed"]:
            step(execution.verify_artifact())
            step(execution.snapshot_review())
        step(execution.finish_verification(state))
    step(execution.outcome())
    return state
