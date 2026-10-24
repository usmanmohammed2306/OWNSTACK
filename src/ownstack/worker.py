"""Durable attempt worker. Run separately from the API process."""
import argparse
import logging
import time
import os
import httpx
from sqlalchemy import select
from ownstack.ai import classify, classify_stream
from ownstack.db import transaction
from ownstack.config import Settings
from ownstack.models import Attempt, ChangeRequest
from ownstack.service import accept_result, claim_attempt, fail_attempt, mark_pulse, reap_expired_attempts, reap_operations
from ownstack.repair import run_repair_one
from ownstack.model_stream import StreamStopped
from ownstack.policy import aware
from ownstack.service import record, utcnow


def run_one() -> bool:
    with transaction() as db:
        mark_pulse(db, "worker")
        reaped = reap_expired_attempts(db) + reap_operations(db)
        attempt_id = db.scalar(select(Attempt.id).where(Attempt.state == "queued").order_by(Attempt.number).limit(1))
        if not attempt_id:
            return bool(reaped)
        attempt = claim_attempt(db, attempt_id)
        if not attempt:
            return True
        settings = Settings()
        expected_model = settings.nebius_model if settings.ai_mode == "nebius" else "fixture"
        if settings.ai_mode == "off" or attempt.model_id != expected_model:
            # A restart/config change must not convert a fixture job into an unreserved paid call.
            fail_attempt(db, attempt_id, "AI_OFF" if settings.ai_mode == "off" else "MODEL_CONFIGURATION_CHANGED")
            return True
        request = db.get(ChangeRequest, attempt.request_id)
        prompt, kind = request.text, request.kind
    # At most sixteen safe progress records per attempt. Never persist tokens,
    # prompts, reasoning or arguments. Cancellation is checked even when no record
    # is due; acceptance is independently fenced again in accept_result.
    last_size, saved_progress = -64, 0
    last_check, cached_current = float('-inf'), False
    def still_current():
        nonlocal last_check, cached_current
        checked_at = time.monotonic()
        # A malicious one-byte transport must not cause one SQL query per byte.
        # This is a short local polling cache, NOT an authorization/result cache.
        # Every saved progress record and final acceptance rechecks without it.
        if checked_at - last_check < 0.25:
            return cached_current
        with transaction() as db:
            current = db.get(Attempt, attempt_id)
            req = db.get(ChangeRequest, current.request_id) if current else None
            cached_current = bool(req and req.current_attempt_id == attempt_id and req.revision == current.request_revision
                                  and current.state == "running" and aware(current.deadline_at) > utcnow())
        last_check = checked_at
        return cached_current

    def progress(snapshot):
        nonlocal last_size, saved_progress
        if saved_progress >= 16 or (snapshot["phase"] != "validated" and
                                   (saved_progress >= 15 or snapshot["received_bytes"] - last_size < 64)):
            return
        with transaction() as db:
            current = db.get(Attempt, attempt_id)
            req = db.scalar(select(ChangeRequest).where(ChangeRequest.id == current.request_id)
                            .with_for_update().execution_options(populate_existing=True))
            db.refresh(current)
            if (req.current_attempt_id != attempt_id or req.revision != current.request_revision
                    or current.state != "running" or aware(current.deadline_at) <= utcnow()):
                raise StreamStopped("LOCAL_STREAM_STOP")
            record(db, current.tenant_id, current.request_id, "attempt.stream_progress", {
                "attempt_id": attempt_id, "phase": snapshot["phase"],
                "received_bytes": snapshot["received_bytes"], "deltas": snapshot["deltas"],
                "source": "fixture_stream" if settings.ai_mode == "fixture" else "provider_stream"})
        last_size, saved_progress = snapshot["received_bytes"], saved_progress + 1
    try:
        result = (classify_stream(prompt, kind, settings, on_progress=progress, should_continue=still_current)
                  if settings.stream_inference else classify(prompt, kind, settings))
        if result.model_id != expected_model:
            raise ValueError("MODEL_ID_MISMATCH")
    except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError, ValueError, RuntimeError, KeyError, TypeError) as error:
        code = "TIMEOUT" if isinstance(error, httpx.TimeoutException) else "MODEL_ERROR"
        if isinstance(error, ValueError):
            code = "INVALID_OUTPUT"
        with transaction() as db:
            fail_attempt(db, attempt_id, code)
        return True
    with transaction() as db:
        accept_result(db, attempt_id, result)
    return True


def run_cycle() -> bool:
    # Give both durable queues a turn even under sustained interpretation traffic.
    normal_work = run_one()
    repair_work = run_repair_one()
    return normal_work or repair_work


def main() -> None:
    settings = Settings()
    settings.validate()
    if settings.environment == 'production' or os.getenv('OWNSTACK_ENFORCE_DB_ROLE') == 'true':
        from ownstack.db_security import runtime_role_safe, enabled_seed_passwords_present
        with transaction() as db:
            if not runtime_role_safe(db):
                raise RuntimeError('Worker requires a least-privileged application database role')
            if settings.environment == 'production' and enabled_seed_passwords_present(db):
                raise RuntimeError('Production refuses default fixture credentials')
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.once:
        run_cycle()
        return
    failures = 0
    while True:
        try:
            worked = run_cycle()
            failures = 0
            if not worked:
                time.sleep(0.5)
        except Exception as error:
            failures += 1
            logging.getLogger("ownstack.worker").error("worker_recovery type=%s", type(error).__name__)
            time.sleep(min(2 ** min(failures, 4), 10))


if __name__ == "__main__":
    main()
