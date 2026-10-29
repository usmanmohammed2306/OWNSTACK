"""Controlled child process for the lab, never a production worker entrypoint."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import socket
import time


def validate_lab_environment():
    from sqlalchemy.engine import make_url
    url = make_url(os.environ["OWNSTACK_DATABASE_URL"])
    schema = os.environ.get("OWNSTACK_LAB_SCHEMA", "")
    if (os.environ.get("OWNSTACK_RELIABILITY_LAB") != "1" or
            not re.fullmatch(r"ownstack_lab_[0-9a-f]{32}", schema) or
            url.drivername != "postgresql+psycopg" or
            url.host not in {"db", "127.0.0.1", "localhost"} or
            url.query.get("options") != f"-csearch_path={schema},pg_catalog -cstatement_timeout=5000 -clock_timeout=2000" or
            os.environ.get("OWNSTACK_AI_MODE") != "fixture" or
            os.environ.get("OWNSTACK_MAX_LIVE_CALLS") != "0" or
            any(os.environ.get(key) for key in ("NEBIUS_API_KEY", "NEBIUS_MODEL_ID", "NEBIUS_PATCH_MODEL_ID"))):
        raise RuntimeError("Lab requires its own schema, fixture stub, empty credentials and zero cap")
    # Only outbound DB connections are allowed. This is a harness guard, not a sandbox.
    addresses = {row[4][0] for row in socket.getaddrinfo(url.host, url.port or 5432, type=socket.SOCK_STREAM)}
    connect = socket.socket.connect

    def database_only(sock, address):
        if not isinstance(address, tuple) or address[0] not in addresses or address[1] != (url.port or 5432):
            raise RuntimeError("Lab blocked non-database outbound connection")
        return connect(sock, address)

    socket.socket.connect = database_only


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["api", "worker", "reap", "redeliver"])
    parser.add_argument("--port", type=int)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--gate", choices=["none", "provider", "precommit", "postcommit"], default="none")
    parser.add_argument("--outcome", choices=["configure", "refuse", "invalid", "429", "timeout"], default="configure")
    parser.add_argument("--mutant", choices=["none", "late_fence", "snapshot_fence", "tenant_scope", "outbox", "accepted_redelivery"], default="none")
    parser.add_argument("--attempt-id")
    args = parser.parse_args()
    validate_lab_environment()
    args.directory.mkdir(parents=True, exist_ok=True)

    def emit(event, **data):
        with (args.directory / "trace.jsonl").open("a") as stream:
            stream.write(json.dumps({"event": event, "pid": os.getpid(), "monotonic_ns": time.monotonic_ns(), **data}) + "\n")

    def gate(point):
        emit(point)
        if args.gate == point.split(".")[0]:
            deadline = time.monotonic() + 25
            while not (args.directory / "release").exists():
                if time.monotonic() > deadline:
                    raise RuntimeError("Lab gate deadline exceeded")
                time.sleep(.01)

    from ownstack import service, worker
    from ownstack.db import transaction
    from ownstack.ai import AIResult
    from .mutations import mutated
    from sqlalchemy import text
    with transaction() as db:
        assert db.scalar(text("SELECT current_schema()")) == os.environ["OWNSTACK_LAB_SCHEMA"]
        assert db.scalar(text("SELECT reserved_calls FROM inference_budget WHERE id='global'")) >= 0

    if args.action == "api":
        from ownstack import api
        if args.mutant in {"snapshot_fence", "tenant_scope"}:
            name = "approve" if args.mutant == "snapshot_fence" else "scoped"
            function, fingerprint = mutated(getattr(service, name), args.mutant)
            setattr(api, name, function)
            emit("mutant.installed", kind=args.mutant, ast_sha256=fingerprint)
        elif args.mutant != "none":
            raise RuntimeError("Unsupported API mutation")
        import uvicorn
        uvicorn.run(api.app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)
        return

    if args.mutant == "outbox":
        service.record, fingerprint = mutated(service.record, "outbox")
        emit("mutant.installed", kind=args.mutant, ast_sha256=fingerprint)
    elif args.mutant in {"late_fence", "accepted_redelivery"}:
        worker.accept_result, fingerprint = mutated(service.accept_result, args.mutant)
        emit("mutant.installed", kind=args.mutant, ast_sha256=fingerprint)
    elif args.mutant != "none":
        raise RuntimeError("Unsupported worker mutation")

    if args.action == "reap":
        with transaction() as db:
            count = service.reap_expired_attempts(db) + service.reap_operations(db)
        emit("reaper.committed", count=count)
        return
    if args.action == "redeliver":
        with transaction() as db:
            accepted = worker.accept_result(db, args.attempt_id, AIResult("refuse", "Synthetic duplicate delivery", "fixture", 0, None, None))
        emit("redelivery.committed", accepted=accepted)
        return

    def synthetic_provider(prompt, kind, settings):
        assert settings.ai_mode == "fixture" and not settings.nebius_key and settings.max_live_calls == 0
        gate("provider.entered")
        if args.outcome == "invalid":
            raise ValueError("Synthetic invalid output")
        if args.outcome in {"429", "timeout"}:
            import httpx
            if args.outcome == "timeout":
                raise httpx.ReadTimeout("Synthetic timeout")
            request = httpx.Request("POST", "https://invalid.example/never-sent")
            raise httpx.HTTPStatusError("Synthetic 429", request=request, response=httpx.Response(429, request=request))
        emit("provider.returned", synthetic=True, outcome=args.outcome)
        return AIResult(args.outcome, f"Synthetic lab {args.outcome}", "fixture", 0, None, None)

    original_accept = worker.accept_result
    def instrumented_accept(db, attempt_id, result):
        accepted = original_accept(db, attempt_id, result)
        gate("precommit.reached")
        return accepted

    committed = 0
    @contextmanager
    def instrumented_transaction():
        nonlocal committed
        with transaction() as db:
            yield db
        committed += 1
        emit("transaction.committed", number=committed)
        if committed == 2:
            gate("postcommit.reached")

    worker.classify = synthetic_provider
    worker.accept_result = instrumented_accept
    worker.transaction = instrumented_transaction
    emit("worker.started")
    worked = worker.run_one()
    emit("worker.exited", worked=worked)


if __name__ == "__main__":
    main()
