"""Two-attempt engineering repair. Models propose; trusted checks and people decide.

Each external operation is preceded by a committed claim. A process death can
consume a reservation without producing a candidate, never re-dispatch the same
claim. Deadlines are local fences, not claims of remote cancellation.
"""
from datetime import timedelta
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select, update
from ownstack.config import Settings
from ownstack.db import SessionLocal
from ownstack.models import ChangeRequest, EngineeringItem, Event, Evidence, Idempotency
from ownstack.patch_agent import generation_configuration, propose_patch
from ownstack.pdf_oracle import CASE_IDS, ORACLE_VERSION, is_external_pass
from ownstack.policy import aware, digest
from ownstack.repair_models import RepairAttempt, RepairRun
from ownstack.runner import current_provenance, patch_hash, verify_patch
from ownstack.service import record, reserve_live_call, utcnow

ACTIVE = {"queued", "generating", "candidate_ready", "verifying"}


def configuration(settings):
    from ownstack.repair_graph import workflow_identity
    return {"mode": settings.ai_mode,
            "model": (settings.nebius_patch_model or settings.nebius_model)
                     if settings.ai_mode == "nebius" else "fixture-not-live",
            "timeout": settings.ai_timeout, **generation_configuration(), **workflow_identity()}


def workflow_matches(run):
    from ownstack.repair_graph import workflow_identity
    return all(run.configuration.get(key) == value for key, value in workflow_identity().items())


def bounded_feedback(checks):
    """Only bounded data is carried to the model; never commands or trusted text."""
    return {"passed": checks.get("passed") is True,
            "stderr": str(checks.get("stderr", ""))[:2000],
            "runner": str(checks.get("runner", "unknown"))[:80],
            "oracle_version": str(checks.get("oracle_version", "unknown"))[:80],
            "failed_cases": [{"id": str(row.get("id", "unknown"))[:40],
                              "reason": str(row.get("reason", "Check failed"))[:140]}
                             for row in checks.get("cases", [])[:7]
                             if isinstance(row, dict) and row.get("passed") is not True]}


def _event(db, run, suffix, payload=None):
    record(db, run.tenant_id, run.request_id, "repair." + suffix,
           {"run_id": run.id, **(payload or {})})


def _lock(db, run_id):
    # Every writer locks item before run to match existing engineer decisions.
    row = db.get(RepairRun, run_id)
    if row is None:
        return None, None
    item = db.scalar(select(EngineeringItem).where(EngineeringItem.id == row.item_id)
                     .with_for_update().execution_options(populate_existing=True))
    run = db.scalar(select(RepairRun).where(RepairRun.id == run_id)
                    .with_for_update().execution_options(populate_existing=True))
    return run, item


def _matches(db, run, item):
    request = db.get(ChangeRequest, run.request_id, populate_existing=True)
    return (item is not None and item.status == "repairing" and item.operation_id == run.id
            and item.human_decision is None and item.patch_hash == run.original_patch_hash
            and digest(item.patch) == run.original_patch_hash
            and request.revision == run.request_revision and digest(request.text) == run.request_hash)


def _end(db, run, item, state, code):
    run.state, run.error_code, run.finished_at = state, code, utcnow()
    if item.operation_id == run.id:
        item.operation_id, item.operation_deadline = None, None
        if item.status == "repairing":
            item.status = "checks_failed"
    _event(db, run, state, {"error_code": code, "remote_cancellation_verified": False})


def _append(db, run, patch, feedback, number):
    attempt = RepairAttempt(id=str(uuid4()), run_id=run.id, number=number, state="queued",
        model_id=run.configuration["model"], input_patch=patch, feedback=bounded_feedback(feedback),
        deadline_at=utcnow() + timedelta(seconds=run.configuration["timeout"] + 30))
    db.add(attempt)
    db.flush()
    run.current_attempt_id = attempt.id
    _event(db, run, "queued", {"attempt_id": attempt.id, "number": number, "synthetic": run.configuration["mode"] == "fixture"})
    return attempt


def start_repair(db, item_id, principal, key, expected_hash, max_attempts=2, settings=None):
    if not key or len(key) > 100:
        raise HTTPException(422, "Idempotency-Key required, maximum 100 characters")
    if max_attempts not in (1, 2):
        raise HTTPException(422, "Repair permits one or two attempts only")
    item = db.scalar(select(EngineeringItem).where(EngineeringItem.id == item_id,
        EngineeringItem.tenant_id == principal.tenant_id).with_for_update())
    if item is None:
        raise HTTPException(404, "Not found")
    body_hash = digest({"item_id": item_id, "patch_hash": expected_hash, "max_attempts": max_attempts})
    old = db.scalar(select(Idempotency).where(Idempotency.tenant_id == principal.tenant_id,
        Idempotency.operation == "start_repair", Idempotency.key == key))
    if old:
        if old.request_hash != body_hash:
            raise HTTPException(409, "Idempotency key reused with different body")
        return db.get(RepairRun, old.response["run_id"])
    active = db.scalar(select(RepairRun).where(RepairRun.item_id == item.id,
        RepairRun.state.in_(("running", "awaiting_review"))))
    if active:
        if active.original_patch_hash != expected_hash or active.max_attempts != max_attempts:
            raise HTTPException(409, "A different repair is already saved")
        run = active
    else:
        settings = settings or Settings()
        if settings.ai_mode == "off":
            raise HTTPException(409, "AI_OFF: saved evidence and manual patching remain available")
        settings.validate()
        if (item.status != "checks_failed" or item.human_decision or not item.patch
                or item.patch_hash != expected_hash or patch_hash(item.patch) != expected_hash):
            raise HTTPException(409, "Exact failed patch without a human decision required")
        checks = db.scalars(select(Evidence).where(Evidence.request_id == item.request_id,
            Evidence.tenant_id == item.tenant_id, Evidence.kind == "patch_checks",
            Evidence.subject_hash == expected_hash).order_by(Evidence.created_at.desc(), Evidence.id)).all()
        failure = next((row.result for row in checks if row.result.get("passed") is False), None)
        if failure is None:
            raise HTTPException(409, "Saved failed check evidence required")
        request = db.get(ChangeRequest, item.request_id)
        run = RepairRun(id=str(uuid4()), tenant_id=item.tenant_id, item_id=item.id,
            request_id=item.request_id, actor_id=principal.user_id, state="running",
            original_patch=item.patch, original_patch_hash=expected_hash,
            request_revision=request.revision, request_hash=digest(request.text),
            configuration=configuration(settings), provenance=current_provenance(),
            max_attempts=max_attempts,
            deadline_at=utcnow() + timedelta(seconds=(settings.ai_timeout + 100) * max_attempts))
        db.add(run)
        db.flush()
        # PostgreSQL row lock plus CAS also fail closed under SQLite races.
        claimed = db.execute(update(EngineeringItem).where(EngineeringItem.id == item.id,
            EngineeringItem.status == "checks_failed", EngineeringItem.patch_hash == expected_hash,
            EngineeringItem.human_decision.is_(None)).values(status="repairing", operation_id=run.id,
            operation_deadline=run.deadline_at).execution_options(synchronize_session=False))
        if claimed.rowcount != 1:
            raise HTTPException(409, "Work item changed; reload its saved status")
        _append(db, run, item.patch, failure, 1)
    db.add(Idempotency(id=str(uuid4()), tenant_id=principal.tenant_id, operation="start_repair",
        key=key, request_hash=body_hash, response={"run_id": run.id}))
    return run


def serialize_run(db, run):
    attempts = db.scalars(select(RepairAttempt).where(RepairAttempt.run_id == run.id)
                          .order_by(RepairAttempt.number)).all()
    trace = db.scalar(select(Event).where(Event.tenant_id == run.tenant_id,
        Event.request_id == run.request_id, Event.event_type == "repair.workflow_phase",
        Event.payload["run_id"].as_string() == run.id).order_by(Event.created_at.desc(), Event.id.desc()).limit(1))
    return {"id": run.id, "item_id": run.item_id, "state": run.state,
        "workflow": {"engine": trace.payload["engine"] if trace else None,
                     "schema": run.configuration.get("workflow_schema"),
                     "last_phase": trace.payload if trace else None,
                     "human_review_required": run.state == "awaiting_review",
                     "persistence": "sql-domain-ledger"},
        "max_attempts": run.max_attempts, "original_patch_hash": run.original_patch_hash,
        "error_code": run.error_code, "configuration": run.configuration, "provenance": run.provenance,
        "deadline_at": aware(run.deadline_at).isoformat(), "release_state": "not_deployed",
        "remote_cancellation_verified": False,
        "attempts": [{"id": a.id, "number": a.number, "state": a.state, "model_id": a.model_id,
            "candidate": a.candidate, "candidate_hash": a.candidate_hash, "checks": a.checks,
            "usage": a.usage, "error_code": a.error_code,
            "deadline_at": aware(a.deadline_at).isoformat()} for a in attempts]}


def _failure(db, run, item, attempt, code, *, stop=False, timed_out=False):
    attempt.state = "timed_out" if timed_out else "failed"
    attempt.error_code, attempt.finished_at = code, utcnow()
    _event(db, run, "attempt_failed", {"attempt_id": attempt.id, "error_code": code,
        "remote_cancellation_verified": False})
    if stop or attempt.number >= run.max_attempts or aware(run.deadline_at) <= utcnow():
        _end(db, run, item, "manual_handoff", code)
    else:
        _append(db, run, attempt.candidate or attempt.input_patch,
                attempt.checks or {"passed": False, "stderr": code}, attempt.number + 1)


def reap_repairs(db):
    count = 0
    ids = db.scalars(select(RepairRun.id).where(RepairRun.state.in_(("running", "awaiting_review")))).all()
    for run_id in ids:
        run, item = _lock(db, run_id)
        if run.state not in {"running", "awaiting_review"}:
            continue
        attempt = db.get(RepairAttempt, run.current_attempt_id)
        if not _matches(db, run, item):
            if attempt and attempt.state in ACTIVE:
                attempt.state, attempt.error_code, attempt.finished_at = "discarded", "ITEM_CHANGED", utcnow()
            _end(db, run, item, "taken_over", "ITEM_CHANGED")
            count += 1
        elif run.provenance != current_provenance() or not workflow_matches(run):
            if attempt and attempt.state in ACTIVE:
                attempt.state, attempt.error_code, attempt.finished_at = "discarded", "SOURCE_CHANGED", utcnow()
            _end(db, run, item, "manual_handoff", "SOURCE_CHANGED")
            count += 1
        elif run.state == "running" and (aware(run.deadline_at) <= utcnow() or
                (attempt and attempt.state in ACTIVE and aware(attempt.deadline_at) <= utcnow())):
            _failure(db, run, item, attempt, "LOCAL_DEADLINE", timed_out=True)
            count += 1
    return count


def claim_work(db, settings):
    candidates = db.scalars(select(RepairAttempt.id).where(RepairAttempt.state.in_(("queued", "candidate_ready")))
                            .order_by(RepairAttempt.number, RepairAttempt.id).limit(25)).all()
    for attempt_id in candidates:
        initial = db.get(RepairAttempt, attempt_id)
        run, item = _lock(db, initial.run_id)
        attempt = db.get(RepairAttempt, attempt_id, populate_existing=True)
        if run.state != "running" or run.current_attempt_id != attempt.id or attempt.state not in {"queued", "candidate_ready"}:
            continue
        if not _matches(db, run, item) or run.provenance != current_provenance() or not workflow_matches(run):
            attempt.state, attempt.error_code = "discarded", "ITEM_OR_SOURCE_CHANGED"
            _end(db, run, item, "taken_over", "ITEM_OR_SOURCE_CHANGED")
            continue
        if aware(attempt.deadline_at) <= utcnow() or aware(run.deadline_at) <= utcnow():
            _failure(db, run, item, attempt, "LOCAL_DEADLINE", timed_out=True)
            continue
        generating = attempt.state == "queued"
        if generating:
            if settings.ai_mode == "off" or configuration(settings) != run.configuration:
                _failure(db, run, item, attempt, "AI_OFF" if settings.ai_mode == "off" else "MODEL_CONFIGURATION_CHANGED", stop=True)
                continue
            try:
                settings.validate()
                reserve_live_call(db, settings)
            except (HTTPException, ValueError):
                _failure(db, run, item, attempt, "BUDGET_OR_CONFIGURATION_BLOCKED", stop=True)
                continue
        previous = attempt.state
        state = "generating" if generating else "verifying"
        deadline = utcnow() + timedelta(seconds=settings.ai_timeout + 5 if generating else 65)
        changed = db.execute(update(RepairAttempt).where(RepairAttempt.id == attempt.id,
            RepairAttempt.state == previous).values(state=state, started_at=utcnow(), deadline_at=deadline)
            .execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            # Item row lock serializes reservation/claim on PostgreSQL.
            raise RuntimeError("REPAIR_CLAIM_CONFLICT")
        db.refresh(attempt)
        _event(db, run, state, {"attempt_id": attempt.id, "number": attempt.number})
        request = db.get(ChangeRequest, run.request_id)
        return {"attempt_id": attempt.id, "phase": state, "text": request.text,
                "input_patch": attempt.input_patch, "feedback": attempt.feedback,
                "candidate": attempt.candidate, "model_id": attempt.model_id}
    return None


def _accepting(db, attempt_id, expected_state):
    initial = db.get(RepairAttempt, attempt_id)
    if initial is None:
        return None
    run, item = _lock(db, initial.run_id)
    attempt = db.get(RepairAttempt, attempt_id, populate_existing=True)
    if (run.state != "running" or run.current_attempt_id != attempt.id or attempt.state != expected_state):
        _event(db, run, "late_result_discarded", {"attempt_id": attempt.id})
        return None
    if not _matches(db, run, item) or run.provenance != current_provenance() or not workflow_matches(run):
        attempt.state, attempt.error_code, attempt.finished_at = "discarded", "ITEM_OR_SOURCE_CHANGED", utcnow()
        _end(db, run, item, "taken_over", "ITEM_OR_SOURCE_CHANGED")
        return None
    if aware(attempt.deadline_at) <= utcnow() or aware(run.deadline_at) <= utcnow():
        _failure(db, run, item, attempt, "LOCAL_DEADLINE", timed_out=True)
        return None
    return run, item, attempt


def save_candidate(db, attempt_id, patch, model_id, usage, settings):
    current = _accepting(db, attempt_id, "generating")
    if not current:
        return False
    run, item, attempt = current
    if configuration(settings) != run.configuration or model_id != attempt.model_id:
        _failure(db, run, item, attempt, "MODEL_CONFIGURATION_CHANGED", stop=True)
        return False
    try:
        candidate_hash = patch_hash(patch)
    except (ValueError, TypeError, KeyError):
        _failure(db, run, item, attempt, "INVALID_PATCH")
        return False
    attempt.candidate, attempt.candidate_hash = patch, candidate_hash
    attempt.usage = {key: usage.get(key) for key in ("live", "latency_ms", "input_tokens", "output_tokens")}
    attempt.state, attempt.deadline_at = "candidate_ready", utcnow() + timedelta(seconds=90)
    _event(db, run, "candidate_saved", {"attempt_id": attempt.id, "patch_hash": candidate_hash})
    return True


def finish_checks(db, attempt_id, result):
    current = _accepting(db, attempt_id, "verifying")
    if not current:
        return False
    run, item, attempt = current
    if not isinstance(result, dict):
        _failure(db, run, item, attempt, "UNTRUSTED_OR_INCOMPLETE_VERIFIER", stop=True)
        return False
    completed, cases = result.get("checks_completed"), result.get("cases")
    trusted_verdict = (result.get("oracle_version") == ORACLE_VERSION
                and type(result.get("checks_expected")) is int and result["checks_expected"] == len(CASE_IDS)
                and type(completed) is int and 0 <= completed <= len(CASE_IDS)
                and isinstance(cases, list) and len(cases) == completed
                and all(isinstance(row, dict) and type(row.get("passed")) is bool for row in cases)
                and type(result.get("passed")) is bool)
    identity = (result.get("patch_hash") == attempt.candidate_hash
                and all(result.get(key) == value for key, value in run.provenance.items()))
    if Settings().environment == 'production':
        from ownstack.candidate_sandbox import POLICY_ID
        identity = identity and result.get('isolation_profile') == POLICY_ID
    # Preserve returned checks even when identity is invalid, but never accept them.
    attempt.checks = result
    if not identity or not trusted_verdict or (result.get("passed") and not is_external_pass(result)):
        _failure(db, run, item, attempt, "UNTRUSTED_OR_INCOMPLETE_VERIFIER", stop=True)
        return False
    if result.get("passed") is not True:
        unavailable = result.get("runner") in {"unavailable", "no-network-queue-timeout"}
        _failure(db, run, item, attempt, "VERIFIER_ERROR" if unavailable else "CHECKS_FAILED", stop=unavailable)
        return False
    attempt.state, attempt.finished_at = "passed", utcnow()
    run.state, run.finished_at = "awaiting_review", utcnow()
    _event(db, run, "awaiting_review", {"attempt_id": attempt.id, "patch_hash": attempt.candidate_hash,
        "release_state": "not_deployed"})
    return True


def operation_failed(db, attempt_id, phase, code):
    current = _accepting(db, attempt_id, phase)
    if current:
        run, item, attempt = current
        _failure(db, run, item, attempt, code, stop=phase == "verifying")


def stop_repair(db, run_id):
    run, item = _lock(db, run_id)
    if run.state in {"running", "awaiting_review"}:
        attempt = db.get(RepairAttempt, run.current_attempt_id)
        if attempt and attempt.state in ACTIVE:
            attempt.state, attempt.error_code, attempt.finished_at = "discarded", "HUMAN_TAKEOVER", utcnow()
        _end(db, run, item, "taken_over", "HUMAN_TAKEOVER")
    return run


def adopt_candidate(db, run_id, expected_hash):
    run, item = _lock(db, run_id)
    attempt = db.get(RepairAttempt, run.current_attempt_id)
    if (run.state != "awaiting_review" or not _matches(db, run, item)
            or run.provenance != current_provenance() or not workflow_matches(run) or attempt.state != "passed"
            or attempt.candidate_hash != expected_hash or patch_hash(attempt.candidate) != expected_hash):
        raise HTTPException(409, "Exact passing candidate and unchanged work item required")
    db.add(Evidence(id=str(uuid4()), tenant_id=run.tenant_id, request_id=run.request_id,
        kind="superseded_patch", subject_hash=run.original_patch_hash,
        result={"patch": run.original_patch, "replacement_hash": expected_hash, "repair_run_id": run.id},
        limitation="Historical failed candidate; explicit engineer adoption is not acceptance or deployment."))
    db.add(Evidence(id=str(uuid4()), tenant_id=run.tenant_id, request_id=run.request_id,
        kind="patch_checks", subject_hash=expected_hash, result=attempt.checks,
        limitation="Finite external-oracle checks, not a security guarantee or release."))
    item.patch, item.patch_hash, item.status = attempt.candidate, expected_hash, "checks_passed"
    item.operation_id, item.operation_deadline = None, None
    run.state, run.finished_at = "adopted", utcnow()
    _event(db, run, "candidate_adopted", {"patch_hash": expected_hash, "release_state": "not_deployed"})
    return run


def run_repair_one(factory=SessionLocal, settings=None, propose=None, verify=None, *, engine="langgraph"):
    """One SQL-durable phase; graph is default, plain is a controlled comparator."""
    from ownstack.repair_execution import RepairExecution, run_sequential
    from ownstack.repair_graph import run_graph
    if engine not in {"langgraph", "plain"}:
        raise ValueError("Unknown repair orchestrator")
    execution = RepairExecution(factory, settings or Settings(), propose or propose_patch,
                                verify or verify_patch, engine=engine)
    result = (run_graph if engine == "langgraph" else run_sequential)(execution)
    return result["worked"]
