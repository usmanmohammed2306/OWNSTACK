"""Small retained-fixture demo. Native provider bytes are tested separately by mocks.

Default: exercise the real saved-progress SSE/worker path in process and print
safe counts. --serve: show the actual UI on loopback 8098. Watching the one queued
synthetic request starts one fixture worker, NEVER provider inference. No existing
database, service, model ledger, learner code or public repository is changed.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    if args.serve:
        os.environ["OWNSTACK_PUBLIC_ORIGIN"] = "http://127.0.0.1:8098"
    from ownstack.config import Settings
    settings = Settings()
    if (settings.ai_mode != "off" or settings.max_live_calls != 0 or settings.nebius_key
            or settings.nebius_model or settings.nebius_patch_model or settings.environment != "local"):
        raise SystemExit("Requires local AI-off mode, cap zero and explicitly empty provider credentials/models.")
    import httpx
    from fastapi.staticfiles import StaticFiles
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from sqlalchemy.orm import sessionmaker
    from ownstack import agent_progress, worker
    from ownstack.api import app
    from ownstack.auth import db_session
    from ownstack.db import Base, make_engine
    from ownstack.models import (Approval, Attempt, ChangeRequest, Contract, Document,
        InferenceBudget, Project, Proposal, Tenant, User, Variation)
    from ownstack.auth import password_hash
    from ownstack.policy import CONTRACT, digest
    from ownstack.service import start_attempt

    os.umask(0o077)
    directory = Path(tempfile.mkdtemp(prefix="ownstack-stream-offline-"))
    engine = make_engine("sqlite:///" + str(directory / "synthetic.db"))
    Base.metadata.create_all(engine)  # Test fixture, not a migration rehearsal.
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([Tenant(id="atlas", name="Atlas"), Tenant(id="nova", name="Nova")]); db.flush()
        for tenant in ("atlas", "nova"):
            for role in ("admin", "engineer", "contractor"):
                db.add(User(id=f"{tenant}-{role}", tenant_id=tenant, role=role,
                            password_hash=password_hash("demo-only-pass")))
            db.add(Project(id=f"{tenant}-project", tenant_id=tenant, name=tenant.title(), revision=1))
        db.flush()
        db.add(Document(id="atlas-doc", tenant_id="atlas", project_id="atlas-project", title="Synthetic plan", body="Private synthetic body"))
        db.add(Contract(id=CONTRACT["id"], version=1, manifest=CONTRACT, manifest_hash=digest(CONTRACT)))
        db.add(InferenceBudget(id="global", reserved_calls=10))  # Never a fresh allowance.
        db.commit()
    def dependency():
        with factory() as db:
            yield db
    @contextmanager
    def transaction():
        with factory() as db:
            yield db
            db.commit()
    app.dependency_overrides[db_session] = dependency
    with TestClient(app) as client:
        auth = client.post("/v1/session", json={"username": "atlas-admin", "password": "demo-only-pass"}).json()
        headers = {"Authorization": "Bearer " + auth["token"], "Idempotency-Key": "offline-stream-demo"}
        created = client.post("/v1/requests", headers=headers, json={"text":
            "Give atlas-contractor read-only access to Project Atlas until the selected expiry.",
            "kind": "access", "project_id": "atlas-project", "viewer_id": "atlas-contractor",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()})
        assert created.status_code == 201
        request_id = created.json()["id"]
    with transaction() as db:
        attempt_id = start_attempt(db, db.get(ChangeRequest, request_id), "fixture", 120).id

    watched, stopped, failures = threading.Event(), threading.Event(), []
    original_snapshot, original_classify = agent_progress.saved_progress, worker.classify_stream
    def snapshot(db, *scope):
        value = original_snapshot(db, *scope)
        if value["request_id"] == request_id:
            watched.set()
        return value
    def slow_fixture(text, kind, config, *, on_progress, should_continue):
        def slow(update):
            on_progress(update)
            time.sleep(0.2)  # Deliberate display pacing, never a latency measurement.
        return original_classify(text, kind, config, on_progress=slow, should_continue=should_continue)
    def run():
        if not watched.wait(300):
            return
        try:
            assert worker.run_one()
        except Exception as error:
            failures.append(type(error).__name__)
        finally:
            stopped.set()
    def forbidden(*_a, **_k):
        raise AssertionError("Offline demo cannot contact a provider")
    fixture = Settings(ai_mode="fixture", stream_inference=True, max_live_calls=0,
                       nebius_key="", nebius_model="", nebius_patch_model="")
    with patch.object(worker, "Settings", lambda: fixture), patch.object(worker, "transaction", transaction), \
         patch.object(worker, "classify_stream", slow_fixture), patch.object(agent_progress, "saved_progress", snapshot), \
         patch.object(httpx, "post", forbidden), patch.object(httpx.Client, "stream", forbidden):
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        print(json.dumps({"synthetic_fixture": True, "ai_mode": "off", "provider_calls": 0,
            "directory": str(directory), "request_id": request_id, "attempt_id": attempt_id,
            "note": "Watching progress starts only a paced fixture worker. This is not live model evidence."}), flush=True)
        if args.serve:
            root = Path(__file__).resolve().parents[1]
            app.mount("/", StaticFiles(directory=root / "web/dist", html=True), name="offline-stream-ui")
            import uvicorn
            uvicorn.run(app, host="127.0.0.1", port=8098, log_level="warning")
        else:
            with TestClient(app) as client:
                login = client.post("/v1/session", json={"username": "atlas-admin", "password": "demo-only-pass"})
                assert login.status_code == 200
                feed = client.get(f"/v1/requests/{request_id}/progress", params={"project_id": "atlas-project",
                                  "attempt_id": attempt_id, "revision": 1})
                assert feed.status_code == 200 and "event: end\ndata: {\"code\":\"complete\"}" in feed.text
                values = [json.loads(row[6:]) for row in feed.text.splitlines() if row.startswith("data: ")]
                assert any(v.get("state") == "running" for v in values)
                assert any(v.get("response", {}).get("route") == "configure" for v in values if v.get("response"))
                assert "Private synthetic body" not in feed.text and "read-only access" not in feed.text
                print(json.dumps({"saved_feed_frames": len(values), "states": sorted({v["state"] for v in values if "state" in v}),
                                  "sources": sorted({v["source"] for v in values if "source" in v})}), flush=True)
            assert stopped.wait(5) and not failures
    with factory() as db:
        result = {"reserved_calls": db.get(InferenceBudget, "global").reserved_calls,
                  "proposals": db.scalar(select(func.count()).select_from(Proposal)),
                  "approvals": db.scalar(select(func.count()).select_from(Approval)),
                  "variations": db.scalar(select(func.count()).select_from(Variation)),
                  "attempt_state": db.get(Attempt, attempt_id).state}
        assert result["reserved_calls"] == 10 and result["approvals"] == result["variations"] == 0
        print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
