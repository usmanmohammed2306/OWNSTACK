from fastapi.testclient import TestClient
from ownstack.api import app
from ownstack.auth import SESSION_COOKIE
from ownstack.models import IdentityEvent, User
from sqlalchemy import select
from conftest import login


def test_offboarding_revokes_cookie_and_bearer_without_revival(client, fixture_db):
    contractor = TestClient(app)
    response = contractor.post("/v1/session", json={"username": "atlas-contractor", "password": "pass"})
    old_cookie = contractor.cookies.get(SESSION_COOKIE)
    bearer = {"Authorization": "Bearer " + response.json()["token"]}
    admin = login(client, "atlas-admin")
    assert client.post("/v1/members/atlas-contractor/access", json={"enabled": False}, headers=admin).status_code == 200
    assert contractor.get("/v1/me").status_code == 401
    assert contractor.get("/v1/me", headers=bearer).status_code == 401
    assert client.post("/v1/members/atlas-contractor/access", json={"enabled": True}, headers=admin).status_code == 200
    contractor.cookies.set(SESSION_COOKIE, old_cookie)
    assert contractor.get("/v1/me").status_code == 401
    assert contractor.get("/v1/me", headers=bearer).status_code == 401
    contractor.cookies.clear()  # Remove the deliberately restored domainless test cookie.
    assert contractor.post("/v1/session", json={"username": "atlas-contractor", "password": "pass"}).status_code == 200
    assert contractor.get("/v1/me").status_code == 200


def test_member_admin_scope_and_role_cannot_escalate(client, fixture_db):
    admin = login(client, "atlas-admin")
    assert {u["id"] for u in client.get("/v1/members", headers=admin).json()} == {
        "atlas-admin", "atlas-engineer", "atlas-contractor"}
    assert client.post("/v1/members/nova-contractor/access", headers=admin, json={"enabled": False}).status_code == 404
    assert client.post("/v1/members/atlas-admin/access", headers=admin, json={"enabled": False}).status_code == 409
    engineer = login(client, "atlas-engineer")
    assert client.get("/v1/members", headers=engineer).status_code == 403
    assert client.post("/v1/members/atlas-contractor/access", headers=engineer, json={"enabled": False}).status_code == 403
    with fixture_db() as db:
        assert db.get(User, "nova-contractor").enabled
        assert db.scalar(select(IdentityEvent)) is None


def test_revoke_all_sessions_and_bearer_for_current_user(client):
    admin = login(client, "atlas-admin")
    assert client.post("/v1/members/me/revoke-sessions", headers=admin).json()["sign_in_required"]
    assert client.get("/v1/me", headers=admin).status_code == 401
    assert client.get("/v1/me").status_code == 401


def test_offboarding_cookie_mutation_requires_csrf(client):
    response = client.post("/v1/session", json={"username": "atlas-admin", "password": "pass"})
    assert client.post("/v1/members/atlas-contractor/access", json={"enabled": False}).status_code == 403
    assert client.post("/v1/members/atlas-contractor/access", json={"enabled": False},
                       headers={"X-CSRF-Token": response.json()["csrf_token"]}).status_code == 200
    events = client.get("/v1/members/audit").json()
    assert len(events) == 1 and events[0]["action"] == "account_disabled"
    assert events[0]["created_at"].endswith("+00:00")
    nova = login(client, "nova-admin")
    assert client.get("/v1/members/audit", headers=nova).json() == []
