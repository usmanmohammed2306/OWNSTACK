from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from ownstack.api import app
from ownstack.auth import db_session, password_hash
from ownstack.db import Base, make_engine
from ownstack.models import Contract, Document, InferenceBudget, Project, Tenant, User
from ownstack.policy import CONTRACT, digest


@pytest.fixture(autouse=True)
def hermetic_runtime(monkeypatch):
    """A developer's live .env must never turn unit tests into paid inference."""
    for key, value in {
        "OWNSTACK_AI_MODE": "fixture", "NEBIUS_API_KEY": "", "NEBIUS_MODEL_ID": "",
        "NEBIUS_PATCH_MODEL_ID": "",
        "OWNSTACK_MAX_LIVE_CALLS": "0", "OWNSTACK_ENV": "local",
        "OWNSTACK_PUBLIC_ORIGIN": "http://testserver", "OWNSTACK_REQUIRE_BACKGROUND": "false",
    }.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def fixture_db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add_all([Tenant(id="atlas", name="Atlas"), Tenant(id="nova", name="Nova"), Tenant(id="platform", name="Platform")])
        db.flush()
        for name, tenant, role in [("atlas-admin", "atlas", "admin"), ("atlas-contractor", "atlas", "contractor"),
                                   ("atlas-engineer", "atlas", "engineer"), ("nova-admin", "nova", "admin"),
                                   ("nova-contractor", "nova", "contractor"), ("platform-owner", "platform", "product_owner")]:
            db.add(User(id=name, tenant_id=tenant, role=role, password_hash=password_hash("pass")))
        db.add_all([Project(id="atlas-project", tenant_id="atlas", name="Atlas", revision=1),
                    Project(id="nova-project", tenant_id="nova", name="Nova", revision=1)])
        db.flush()
        db.add_all([Document(id="atlas-doc", tenant_id="atlas", project_id="atlas-project", title="Atlas plan", body="atlas secret"),
                    Document(id="nova-doc", tenant_id="nova", project_id="nova-project", title="Nova plan", body="nova secret")])
        db.add(Contract(id=CONTRACT["id"], version=1, manifest=CONTRACT, manifest_hash=digest(CONTRACT)))
        db.add(InferenceBudget(id="global", reserved_calls=0))
        db.commit()

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[db_session] = override
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def client(fixture_db):
    return TestClient(app)


def login(client, username):
    response = client.post("/v1/session", json={"username": username, "password": "pass"})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}
