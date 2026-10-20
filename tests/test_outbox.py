from datetime import timedelta
import json
import httpx
import pytest
from sqlalchemy import func, select
from ownstack.db import transaction
from ownstack.models import ChangeRequest, DeliveryReceipt, InferenceBudget, Outbox
from ownstack.outbox import MAX_DELIVERIES, HttpSink, claim, clock, finish, receive, run_one
from ownstack.policy import digest
from ownstack.service import record
from conftest import login


def queue(factory, tenant="atlas", name="one"):
    with transaction(factory) as db:
        req = ChangeRequest(id=name, tenant_id=tenant, requester_id=tenant + "-admin",
                            text="Synthetic outbox request", kind="feature")
        db.add(req)
        db.flush()
        record(db, tenant, name, "request.created", {"kind": "feature"})
        db.flush()
        return db.scalar(select(Outbox.id).where(Outbox.tenant_id == tenant))


def test_local_receipt_dispatch_does_not_touch_budget(fixture_db):
    row_id = queue(fixture_db)
    assert run_one("nova", factory=fixture_db) is False
    assert run_one("atlas", factory=fixture_db) is True
    assert run_one("atlas", factory=fixture_db) is False
    with fixture_db() as db:
        assert db.get(Outbox, row_id).state == "delivered"
        assert db.scalar(select(func.count()).select_from(DeliveryReceipt)) == 1
        assert db.get(InferenceBudget, "global").reserved_calls == 0


def test_receipt_survives_sender_crash_and_deduplicates(fixture_db):
    row_id = queue(fixture_db)
    at = clock()
    with transaction(fixture_db) as db:
        first = claim(db, "atlas", "sink", at)
    with transaction(fixture_db) as db:
        receive(db, first)  # Consumer committed, sender dies before finish.
    with transaction(fixture_db) as db:
        assert claim(db, "atlas", "sink", at + timedelta(seconds=1)) is None
        second = claim(db, "atlas", "sink", at + timedelta(seconds=31))
        assert second and second["lease_id"] != first["lease_id"]
    with transaction(fixture_db) as db:
        assert receive(db, second) == receive(db, first)
        assert finish(db, first, True, at + timedelta(seconds=31)) is False
        assert finish(db, second, True, at + timedelta(seconds=32)) is True
    with fixture_db() as db:
        assert db.get(Outbox, row_id).attempts == 2
        assert db.scalar(select(func.count()).select_from(DeliveryReceipt)) == 1


def test_retries_backoff_then_dead_letter_and_destination_is_fenced(fixture_db):
    row_id = queue(fixture_db)
    at = clock()
    for number in range(MAX_DELIVERIES):
        with transaction(fixture_db) as db:
            work = claim(db, "atlas", "sink", at)
            assert work
            assert finish(db, work, False, at)
            assert claim(db, "atlas", "different-sink", at + timedelta(minutes=3)) is None
            assert claim(db, "atlas", "sink", at) is None
        at += timedelta(minutes=3)
    with fixture_db() as db:
        row = db.get(Outbox, row_id)
        assert (row.state, row.attempts, row.last_error) == ("dead", 5, "DELIVERY_FAILED")


def test_expired_final_lease_becomes_dead_and_late_ack_is_rejected(fixture_db):
    row_id = queue(fixture_db)
    at = clock()
    with transaction(fixture_db) as db:
        db.get(Outbox, row_id).attempts = 4
    with transaction(fixture_db) as db:
        last = claim(db, "atlas", "sink", at)
    with transaction(fixture_db) as db:
        assert finish(db, last, True, at + timedelta(seconds=30)) is False
        assert claim(db, "atlas", "sink", at + timedelta(seconds=31)) is None
    with fixture_db() as db:
        assert db.get(Outbox, row_id).state == "dead"


def test_changed_envelope_cannot_reuse_receipt_or_ack(fixture_db):
    row_id = queue(fixture_db)
    with transaction(fixture_db) as db:
        work = claim(db, "atlas", "sink")
    with transaction(fixture_db) as db:
        receive(db, work)
        changed = {**work, "envelope": {**work["envelope"], "payload": {"kind": "tampered"}}}
        changed["envelope_hash"] = digest(changed["envelope"])
        with pytest.raises(ValueError, match="RECEIPT_CONFLICT"):
            receive(db, changed)
    with transaction(fixture_db) as db:
        db.get(Outbox, row_id).payload = {"kind": "tampered"}
    with transaction(fixture_db) as db:
        assert finish(db, work, True)
        assert db.get(Outbox, row_id).last_error == "ENVELOPE_CHANGED"


@pytest.mark.parametrize("endpoint", ["http://evil.example", "file:///tmp/a", "https://u:p@example.com",
                                    "https://example.com/?secret=x", "https://example.com/#x"])
def test_receiver_configuration_rejects_unsafe_destination(endpoint):
    with pytest.raises(ValueError):
        HttpSink(endpoint)


@pytest.mark.parametrize("status,receipt", [(302, {}), (429, {}), (200, {"event_id": "wrong"}),
                                          (200, "x" * 4097)])
def test_http_sink_requires_exact_bounded_ack(fixture_db, status, receipt):
    row_id = queue(fixture_db)
    def handler(request):
        assert request.headers["idempotency-key"]
        return httpx.Response(status, json=receipt)
    sink = HttpSink("https://receiver.example/events", transport=httpx.MockTransport(handler))
    assert run_one("atlas", sink, fixture_db)
    with fixture_db() as db:
        assert db.get(Outbox, row_id).state == "pending"


def test_http_sink_accepts_receiver_ack_and_sets_idempotency_header(fixture_db):
    row_id = queue(fixture_db)
    def handler(request):
        body = json.loads(request.content)
        assert request.headers["idempotency-key"] == body["event_id"]
        assert body["tenant_id"] == "atlas"
        return httpx.Response(201, json={"event_id": body["event_id"], "envelope_hash": body["envelope_hash"]})
    assert run_one("atlas", HttpSink("https://receiver.example/events", transport=httpx.MockTransport(handler)), fixture_db)
    with fixture_db() as db:
        assert db.get(Outbox, row_id).state == "delivered"


def test_operations_exposes_only_tenant_counts_and_local_alerts(client, fixture_db):
    queue(fixture_db, "atlas", "atlas-one")
    row_id = queue(fixture_db, "nova", "nova-one")
    with transaction(fixture_db) as db:
        db.get(Outbox, row_id).state = "dead"
    admin = login(client, "atlas-admin")
    report = client.get("/v1/operations", headers=admin).json()
    assert report["outbox"] == {"pending": 1}
    assert report["alert_delivery"] == "local_status_only"
    assert not any(s["code"] == "OUTBOX_DEAD" for s in report["signals"])
    assert client.get("/v1/operations", headers=login(client, "atlas-contractor")).status_code == 403


def test_two_simultaneous_file_database_claims_have_one_winner(fixture_db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    queue(fixture_db)
    barrier = Barrier(2)
    def contender():
        barrier.wait(timeout=3)
        with transaction(fixture_db) as db:
            return claim(db, "atlas", "sink")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: contender(), range(2)))
    assert sum(r is not None for r in results) == 1


def test_real_loopback_http_receipt_and_sender_ack(fixture_db):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    row_id = queue(fixture_db)
    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            size = int(self.headers["Content-Length"])
            body = json.loads(self.rfile.read(size))
            envelope_hash = body.pop("envelope_hash")
            assert self.headers["Idempotency-Key"] == body["event_id"]
            with transaction(fixture_db) as db:
                result = receive(db, {"envelope": body, "envelope_hash": envelope_hash,
                                      "destination_id": "loopback-consumer"})
            data = json.dumps(result).encode()
            self.send_response(201)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        sink = HttpSink(f"http://127.0.0.1:{server.server_port}/events", allow_loopback=True)
        assert run_one("atlas", sink, fixture_db)
        with fixture_db() as db:
            assert db.get(Outbox, row_id).state == "delivered"
            assert db.scalar(select(func.count()).select_from(DeliveryReceipt)) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()
