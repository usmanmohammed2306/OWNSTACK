"""At-least-once delivery with durable leases and a deduplicating local consumer.

Run explicitly for one tenant. Receipt mode is offline; HTTP mode needs an
operator-selected receiver implementing the acknowledgement protocol. Never
accept a destination from a request, model output or event payload.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from urllib.parse import urlsplit
from uuid import uuid4
import httpx
from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from ownstack.db import SessionLocal, transaction
from ownstack.models import DeliveryReceipt, Outbox
from ownstack.policy import aware, digest

MAX_DELIVERIES = 5
LEASE_SECONDS = 30


def clock():
    return datetime.now(timezone.utc)


def claim(db, tenant_id: str, destination_id: str, at=None):
    at = at or clock()
    eligible = and_(Outbox.tenant_id == tenant_id,
        or_(Outbox.destination_id.is_(None), Outbox.destination_id == destination_id),
        or_(and_(Outbox.state == "pending", or_(Outbox.available_at.is_(None), Outbox.available_at <= at)),
            and_(Outbox.state == "delivering", Outbox.lease_until <= at)))
    row = db.scalar(select(Outbox).where(eligible).order_by(Outbox.id)
                    .with_for_update(skip_locked=True).limit(1))
    if not row:
        return None
    if row.attempts >= MAX_DELIVERIES:
        row.state, row.last_error = "dead", "DELIVERY_LIMIT"
        row.lease_id, row.lease_until = None, None
        return None
    lease_id = str(uuid4())
    changed = db.execute(update(Outbox).where(Outbox.id == row.id, eligible, Outbox.attempts == row.attempts)
        .values(state="delivering", attempts=Outbox.attempts + 1, destination_id=destination_id,
                lease_id=lease_id, lease_until=at + timedelta(seconds=LEASE_SECONDS), last_error=None)
        .execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        return None
    envelope = {"event_id": row.event_id, "tenant_id": row.tenant_id,
                "topic": row.topic, "payload": deepcopy(row.payload)}
    return {"id": row.id, "lease_id": lease_id, "destination_id": destination_id,
            "envelope": envelope, "envelope_hash": digest(envelope)}


def finish(db, work: dict, succeeded: bool, at=None) -> bool:
    at = at or clock()
    row = db.scalar(select(Outbox).where(Outbox.id == work["id"]).with_for_update())
    if (not row or row.state != "delivering" or row.lease_id != work["lease_id"]
            or row.destination_id != work["destination_id"] or aware(row.lease_until) <= at):
        return False
    # A changed payload cannot receive an acknowledgement for an earlier envelope.
    current = {"event_id": row.event_id, "tenant_id": row.tenant_id,
               "topic": row.topic, "payload": row.payload}
    if digest(current) != work["envelope_hash"]:
        row.state, row.last_error = "dead", "ENVELOPE_CHANGED"
    elif succeeded:
        row.state, row.delivered_at, row.last_error = "delivered", at, None
    else:
        row.state = "dead" if row.attempts >= MAX_DELIVERIES else "pending"
        row.last_error = "DELIVERY_FAILED"
        row.available_at = at + timedelta(seconds=min(2 ** row.attempts, 60))
    row.lease_id, row.lease_until = None, None
    return True


def receive(db, work: dict):
    """Commit this before sender acknowledgement; replay returns the same receipt."""
    envelope = work["envelope"]
    if digest(envelope) != work["envelope_hash"]:
        raise ValueError("ENVELOPE_HASH_MISMATCH")
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    db.execute(insert(DeliveryReceipt).values(event_id=envelope["event_id"],
        destination_id=work["destination_id"], tenant_id=envelope["tenant_id"],
        envelope_hash=work["envelope_hash"], received_at=clock())
        .on_conflict_do_nothing(index_elements=[DeliveryReceipt.event_id, DeliveryReceipt.destination_id]))
    receipt = db.get(DeliveryReceipt, (envelope["event_id"], work["destination_id"]))
    if receipt.tenant_id != envelope["tenant_id"] or receipt.envelope_hash != work["envelope_hash"]:
        raise ValueError("RECEIPT_CONFLICT")
    return {"event_id": receipt.event_id, "envelope_hash": receipt.envelope_hash}


class HttpSink:
    def __init__(self, endpoint: str, *, token: str = "", allow_loopback=False, transport=None):
        parts = urlsplit(endpoint)
        local = parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1", "::1"}
        if (not parts.hostname or parts.username or parts.password or parts.query or parts.fragment
                or not (parts.scheme == "https" or (allow_loopback and local))):
            raise ValueError("Receiver must be HTTPS; explicit loopback HTTP is for local tests only")
        self.endpoint, self.token, self.transport = endpoint, token, transport
        self.destination_id = digest({"endpoint": endpoint})

    def send(self, work):
        headers = {"Idempotency-Key": work["envelope"]["event_id"]}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False, transport=self.transport) as client:
            with client.stream("POST", self.endpoint, json={**work["envelope"],
                               "envelope_hash": work["envelope_hash"]}, headers=headers) as response:
                if response.status_code not in {200, 201}:
                    raise ValueError("DELIVERY_NOT_ACKNOWLEDGED")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 4096:
                        raise ValueError("ACK_TOO_LARGE")
                receipt = json.loads(raw)
                if receipt != {"event_id": work["envelope"]["event_id"],
                               "envelope_hash": work["envelope_hash"]}:
                    raise ValueError("ACK_MISMATCH")


def run_one(tenant_id: str, sink=None, factory=SessionLocal):
    destination_id = sink.destination_id if sink else digest({"sink": "local-receipt"})
    with transaction(factory) as db:
        work = claim(db, tenant_id, destination_id)
    if not work:
        return False
    succeeded = False
    try:
        if sink:
            sink.send(work)
        else:
            with transaction(factory) as db:
                receive(db, work)
        succeeded = True
    except (httpx.HTTPError, ValueError, TypeError, UnicodeError):
        # Do not persist receiver response bodies, credentials or exception text.
        pass
    with transaction(factory) as db:
        finish(db, work, succeeded)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--endpoint", help="Explicit operator-owned HTTP receiver; otherwise local receipts")
    parser.add_argument("--allow-loopback", action="store_true")
    parser.add_argument("--limit", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be 1 to 100")
    try:
        sink = HttpSink(args.endpoint, token=os.environ.get("OWNSTACK_OUTBOX_TOKEN", ""),
                        allow_loopback=args.allow_loopback) if args.endpoint else None
        worked = sum(run_one(args.tenant, sink) for _ in range(args.limit))
    except Exception as error:
        print(json.dumps({"error_type": type(error).__name__}))
        return 1
    print(json.dumps({"claimed": worked, "sink": "http" if sink else "local-receipt", "model_calls": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
