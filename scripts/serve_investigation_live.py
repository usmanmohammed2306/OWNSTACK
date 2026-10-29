"""Owner-approved live investigation rehearsal, with original central reservations.

No inference on start. A browser action invokes the actual Nebius adapter. A
private SQLite control fixture stores requests/runs, while EVERY reservation is
also conditionally committed to the existing ownstack PostgreSQL ledger through
Docker psql. Never renew the counter, migrate the old app or top up an account.
The two database commits are conservative, not a distributed atomic transaction:
central success followed by local failure still consumes a slot, never refunds it.
"""
import argparse
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import tempfile

SOURCE_ROOT = Path(__file__).resolve().parents[1]


def central(sql):
    if (SOURCE_ROOT / ".private/inference-authority-moved.json").exists() and not sql.lstrip().upper().startswith("SELECT"):
        raise RuntimeError("Inference authority moved to the single hosted runtime; local dispatch is frozen")
    result = subprocess.run(["docker", "exec", "-i", "ownstack-db-1", "psql", "-X", "-qAt",
        "-v", "ON_ERROR_STOP=1", "-U", "ownstack", "-d", "ownstack"],
        input=sql, capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError("Original budget ledger unavailable; no inference permitted")
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credits-and-prices-verified", action="store_true")
    parser.add_argument("--approved-cumulative-ceiling", type=int, required=True)
    parser.add_argument("--port", type=int, default=8097)
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    grants = {20: 10, 40: 20}
    ceiling = args.approved_cumulative_ceiling
    if not args.credits_and_prices_verified or ceiling not in grants or not 1024 <= args.port <= 65535:
        raise SystemExit("Requires explicit bounded approval, a valid loopback port and verified credits/prices.")
    lower = grants[ceiling]
    from dotenv import dotenv_values
    root = SOURCE_ROOT
    if (root / ".private/inference-authority-moved.json").exists():
        raise SystemExit("Local inference is frozen after the hosted-budget handoff. Read the retained handoff record.")
    private = dotenv_values(root / ".env")
    if not private.get("NEBIUS_API_KEY"):
        raise SystemExit("Configure the existing server key privately; never paste it into chat.")
    os.environ.update(OWNSTACK_AI_MODE="nebius", OWNSTACK_MAX_LIVE_CALLS=str(ceiling),
        OWNSTACK_INVESTIGATION_BASELINE="false", OWNSTACK_ENV="local",
        OWNSTACK_INVESTIGATION_TRANSPORT="json",
        OWNSTACK_PUBLIC_ORIGIN=f"http://127.0.0.1:{args.port}", OWNSTACK_REQUIRE_BACKGROUND="false",
        NEBIUS_API_KEY=private["NEBIUS_API_KEY"], NEBIUS_MODEL_ID=private["NEBIUS_MODEL_ID"],
        NEBIUS_PATCH_MODEL_ID=private.get("NEBIUS_PATCH_MODEL_ID", ""),
        OWNSTACK_AI_TIMEOUT_SECONDS="45")
    # Read the ORIGINAL ledger, never the old zero-counter local prototype.
    count = int(central("SELECT reserved_calls FROM inference_budget WHERE id='global';"))
    if not lower <= count <= ceiling or (count == ceiling and not args.resume):
        raise SystemExit("Original ledger does not match the approved remaining allowance.")
    os.umask(0o077)
    if args.resume:
        directory = args.resume.resolve()
        if not (directory / "authorization.json").is_file() or not (directory / "control.db").is_file():
            raise SystemExit("Resume requires the retained, previously authorized fixture.")
        if json.loads((directory / "authorization.json").read_text()).get("approved_cumulative_ceiling") != ceiling:
            raise SystemExit("Resume cannot replace a previous fixture's authorization history.")
    else:
        directory = Path(tempfile.mkdtemp(prefix="ownstack-investigation-live-", dir=root / ".private"))
    os.environ["OWNSTACK_DATABASE_URL"] = "sqlite:///" + str(directory / "control.db")
    from fastapi import HTTPException
    from fastapi.staticfiles import StaticFiles
    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker
    from ownstack import api, investigation_api, repair, service
    from ownstack.auth import db_session, password_hash
    from ownstack.config import Settings
    from ownstack.db import Base, make_engine
    from ownstack.models import Contract, InferenceBudget, Project, Tenant, User
    from ownstack.policy import CONTRACT, digest
    settings = Settings()
    settings.validate()
    engine = make_engine(settings.database_url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    if not args.resume:
        Base.metadata.create_all(engine)
        with factory() as db:
            db.add_all([Tenant(id="atlas", name="Atlas"), Tenant(id="nova", name="Nova")])
            db.flush()
            for tenant in ("atlas", "nova"):
                for role in ("admin", "engineer", "contractor"):
                    db.add(User(id=f"{tenant}-{role}", tenant_id=tenant, role=role,
                        password_hash=password_hash("demo-only-pass")))
                db.add(Project(id=f"{tenant}-project", tenant_id=tenant, name=f"Project {tenant.title()}", revision=1))
            db.add(Contract(id=CONTRACT["id"], version=1, manifest=CONTRACT, manifest_hash=digest(CONTRACT)))
            db.add(InferenceBudget(id="global", reserved_calls=count))
            db.commit()
    with factory() as db:
        if db.get(InferenceBudget, "global").reserved_calls != count:
            raise SystemExit("Ledger drift: preserve both histories and investigate, never reset either.")
    authorization = {"approved_cumulative_ceiling": ceiling, "original_count_at_prepare": count,
        "original_ledger": "ownstack-db-1/ownstack/inference_budget/global",
        "account_credit_observed_usd": 25.00, "trial_credit_observed_usd": 0.99,
        "prices_per_million": {"nano": {"input": 0.06, "output": 0.24}, "super": {"input": 0.30, "output": 0.90}},
        "policy": "Existing credits only; no top-up or paid deployment. No refunds of uncertain reservations.",
        "scope": "Synthetic control fixture; original app schema/data unchanged except authorized central budget increments."}
    if not args.resume:
        (directory / "authorization.json").write_text(json.dumps(authorization, indent=2) + "\n")
    original_reserve = service.reserve_live_call
    def reserve(db, config):
        if config.ai_mode != "nebius":
            raise HTTPException(503, "Live rehearsal never substitutes a fixture for AI")
        before = db.scalar(select(InferenceBudget.reserved_calls).where(InferenceBudget.id == "global"))
        if before is None or not lower <= before < ceiling:
            raise HTTPException(429, "Approved cumulative allowance exhausted")
        original_reserve(db, config)
        # Integers originate from the locked local ledger, never model/user SQL.
        saved = central("UPDATE inference_budget SET reserved_calls=reserved_calls+1 "
            f"WHERE id='global' AND reserved_calls={int(before)} AND reserved_calls>={lower} AND reserved_calls<{ceiling} "
            "RETURNING reserved_calls;")
        if saved != str(before + 1):
            raise HTTPException(429, "Original ledger changed; no dispatch permitted")
        with (directory / "reservations.jsonl").open("a") as log:
            log.write(json.dumps({"reserved_calls": before + 1, "at": service.utcnow().isoformat()}) + "\n")
    # Every API generation entry uses the same central bridge. No background worker
    # or patch runner is launched by this dedicated investigation rehearsal.
    for module in (service, api, investigation_api, repair):
        module.reserve_live_call = reserve
    def dependency():
        with factory() as db:
            yield db
    api.app.dependency_overrides[db_session] = dependency
    if not args.resume:
        with TestClient(api.app) as client:
            auth = client.post("/v1/session", json={"username": "atlas-admin", "password": "demo-only-pass"}).json()
            headers = {"Authorization": "Bearer " + auth["token"]}
            for kind in ("access", "feature"):
                body = {"kind": kind, "project_id": "atlas-project", "text": "Add PDF export for Project Atlas."}
                if kind == "access":
                    body.update(text="Give atlas-contractor read-only access to Project Atlas until the selected expiry.",
                        viewer_id="atlas-contractor", expires_at=(service.utcnow()+timedelta(days=1)).isoformat())
                response = client.post("/v1/requests", headers={**headers, "Idempotency-Key": "live-"+kind}, json=body)
                assert response.status_code == 201
    api.app.mount("/", StaticFiles(directory=root / "web/dist", html=True), name="live-investigation")
    print(json.dumps({"directory": str(directory), "counter": count, "ceiling": ceiling,
        "url": f"http://127.0.0.1:{args.port}", "automatic_inference": False}), flush=True)
    import uvicorn
    try:
        uvicorn.run(api.app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)
    finally:
        print(json.dumps({"original_counter_at_stop": int(central("SELECT reserved_calls FROM inference_budget WHERE id='global';"))}), flush=True)
        engine.dispose()


if __name__ == "__main__":
    main()
