"""Durable attempt worker. Run separately from the API process."""
import argparse
import logging
import time
import os
import httpx
from sqlalchemy import select
from ownstack.ai import classify
from ownstack.db import transaction
from ownstack.config import Settings
from ownstack.models import Attempt, ChangeRequest
from ownstack.service import accept_result, claim_attempt, fail_attempt, mark_pulse, reap_expired_attempts, reap_operations
from ownstack.repair import run_repair_one


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
    try:
        result = classify(prompt, kind, settings)
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
