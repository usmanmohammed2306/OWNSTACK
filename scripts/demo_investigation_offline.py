"""Reproducible AI-off investigation journey. --serve exposes only loopback UI.

Creates retained private synthetic state with counter ten, never a fresh allowance.
No existing database, runtime configuration or credentials are changed. No patch
is executed. This is a policy baseline rehearsal, not successful live AI proof.
"""
import argparse
from datetime import timedelta
import json
import os
from pathlib import Path
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    # Explicit opt-in for this isolated research baseline, never the main product.
    os.environ["OWNSTACK_INVESTIGATION_BASELINE"] = "true"
    if args.serve:
        os.environ["OWNSTACK_PUBLIC_ORIGIN"] = "http://127.0.0.1:8097"
    from ownstack.config import Settings
    settings = Settings()
    if (settings.ai_mode != "off" or settings.max_live_calls != 0 or settings.nebius_key
            or settings.nebius_model or settings.nebius_patch_model or settings.environment != "local"):
        raise SystemExit("Requires local AI off, cap zero and explicitly empty provider credentials/models.")
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from sqlalchemy.orm import sessionmaker
    from ownstack.api import app
    from ownstack.auth import db_session, password_hash
    from ownstack.db import Base, make_engine
    from ownstack.models import (Approval, ChangeRequest, Contract, InferenceBudget,
        Investigation, Project, Tenant, User, Variation)
    from ownstack.policy import CONTRACT, digest
    from ownstack.service import utcnow
    os.umask(0o077)
    directory = Path(tempfile.mkdtemp(prefix="ownstack-investigation-offline-"))
    engine = make_engine("sqlite:///" + str(directory / "synthetic.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([Tenant(id="atlas", name="Atlas"), Tenant(id="nova", name="Nova")])
        db.flush()
        for tenant in ("atlas", "nova"):
            for role in ("admin", "contractor"):
                db.add(User(id=f"{tenant}-{role}", tenant_id=tenant, role=role,
                    password_hash=password_hash("demo-only-pass")))
            db.add(Project(id=f"{tenant}-project", tenant_id=tenant, name=f"Project {tenant.title()}", revision=1))
        db.add(Contract(id=CONTRACT["id"], version=1, manifest=CONTRACT, manifest_hash=digest(CONTRACT)))
        db.add(InferenceBudget(id="global", reserved_calls=10))
        db.commit()
    def dependency():
        with factory() as db:
            yield db
    app.dependency_overrides[db_session] = dependency
    checks, journeys = [], []
    with TestClient(app) as client:
        def auth(user):
            result = client.post("/v1/session", json={"username": user, "password": "demo-only-pass"})
            assert result.status_code == 200, result.text
            return {"Authorization": "Bearer " + result.json()["token"]}
        admin = auth("atlas-admin")
        for kind in ("access", "feature"):
            body = {"kind": kind, "project_id": "atlas-project", "text": "Add PDF export for Project Atlas."}
            if kind == "access":
                body.update(text="Give atlas-contractor read-only access to Project Atlas until the selected expiry.",
                    viewer_id="atlas-contractor", expires_at=(utcnow() + timedelta(days=1)).isoformat())
            created = client.post("/v1/requests", headers={**admin, "Idempotency-Key": kind}, json=body)
            assert created.status_code == 201, created.text
            req = created.json()["id"]
            path = f"/v1/requests/{req}/investigations"
            initial = client.post(path, headers={**admin, "Idempotency-Key": kind}, json={"revision": 1}).json()
            run = initial
            for _ in range(3):
                result = client.post(f'/v1/investigations/{run["id"]}/step', headers=admin,
                    json={"expected_version": run["version"]})
                assert result.status_code == 200, result.text
                run = result.json()
            assert run["state"] == "completed" and len(run["steps"]) == 3
            assert client.get(path, headers=admin).json() == [run]
            repeated = client.post(f'/v1/investigations/{run["id"]}/step', headers=admin,
                json={"expected_version": initial["version"]})
            assert repeated.json() == run
            checks.extend([kind + ":cited-handoff", kind + ":saved-refresh", kind + ":duplicate-step"])
            journeys.append({"kind": kind, "request_id": req, "run_id": run["id"],
                "handoff": run["result"]["handoff"], "observed_sources": [c["source"] for c in run["result"]["citations"]]})
        nova, contractor = auth("nova-admin"), auth("atlas-contractor")
        path = f'/v1/investigations/{journeys[0]["run_id"]}'
        assert client.get(path, headers=nova).status_code == 404
        assert client.get(path, headers=contractor).status_code == 403
        checks.extend(["nova-isolation", "contractor-role-denial"])
    with factory() as db:
        assert db.get(InferenceBudget, "global").reserved_calls == 10
        assert db.scalar(select(func.count(Approval.id))) == db.scalar(select(func.count(Variation.id))) == 0
        assert db.scalar(select(func.count(Investigation.id))) == 2
        assert all(row.status == "new" for row in db.scalars(select(ChangeRequest)))
    checks.extend(["counter-ten-preserved", "no-grants-or-approvals", "request-status-unchanged"])
    report = {"schema": "ownstack-investigation-demo-v1", "ai_mode": "off", "live_calls": 0,
        "source": "deterministic-policy-baseline", "workflow_hash": __import__("ownstack.investigation", fromlist=["identity"]).identity(),
        "checks": checks, "journeys": journeys, "reserved_calls": 10,
        "limitations": "Synthetic in-process HTTP/SQLite; no live model, PostgreSQL contention, code execution or deployment."}
    (directory / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(directory / "result.json"), "checks_passed": len(checks), "live_calls": 0}))
    if args.serve:
        from fastapi.staticfiles import StaticFiles
        import uvicorn
        app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "web/dist", html=True), name="investigation-preview")
        print("Private synthetic preview: http://127.0.0.1:8097; sign in as atlas-admin / demo-only-pass")
        try:
            uvicorn.run(app, host="127.0.0.1", port=8097, log_level="warning")
        finally:
            app.dependency_overrides.clear()
            engine.dispose()
    else:
        app.dependency_overrides.clear()
        engine.dispose()


if __name__ == "__main__":
    main()
