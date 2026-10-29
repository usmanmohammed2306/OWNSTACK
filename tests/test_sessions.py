from datetime import datetime, timedelta, timezone
from ownstack.auth import SESSION_COOKIE, hash_secret
from ownstack.models import User, WebSession


def sign_in(client):
    response = client.post("/v1/session", json={"username": "atlas-admin", "password": "pass"})
    assert response.status_code == 200
    return response


def test_cookie_session_requires_csrf_and_is_revoked_on_logout(client):
    response = sign_in(client)
    cookies = response.headers.get_list("set-cookie")
    assert any("HttpOnly" in value and SESSION_COOKIE in value for value in cookies)
    assert all("SameSite=strict" in value for value in cookies)
    csrf = response.json()["csrf_token"]
    assert client.get("/v1/session").json()["user_id"] == "atlas-admin"
    assert client.post("/v1/session/logout").status_code == 403
    assert client.post("/v1/session/logout", headers={"X-CSRF-Token": csrf, "Origin": "https://evil.example"}).status_code == 403
    token = client.cookies.get(SESSION_COOKIE)
    assert client.post("/v1/session/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get("/v1/session").status_code == 401


def test_disabled_identity_and_expired_session_are_denied(client, fixture_db):
    sign_in(client)
    token = client.cookies.get(SESSION_COOKIE)
    with fixture_db() as db:
        row = db.get(WebSession, hash_secret(token))
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert client.get("/v1/me").status_code == 401
    with fixture_db() as db:
        db.get(User, "atlas-admin").enabled = False
        db.commit()
    assert client.post("/v1/session", json={"username": "atlas-admin", "password": "pass"}).status_code == 401


def test_login_rate_limit_persists_failed_attempts(client, monkeypatch):
    # This is a fixed-window limiter. A real five-minute boundary during slow
    # password hashing must not turn this persistence test into a random failure.
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):return datetime(2026,10,25,12,1,tzinfo=timezone.utc)
    monkeypatch.setattr('ownstack.auth.datetime',FixedClock)
    for _ in range(15):
        assert client.post("/v1/session", json={"username": "unknown", "password": "wrong"}).status_code == 401
    denied = client.post("/v1/session", json={"username": "unknown", "password": "wrong"})
    assert denied.status_code == 429 and denied.headers["retry-after"] == "300"


def test_production_session_has_secure_cookies_and_no_bearer_token(client, monkeypatch):
    from fastapi.testclient import TestClient
    from ownstack.api import app
    client = TestClient(app,base_url='https://testserver')
    monkeypatch.setenv("OWNSTACK_ENV", "production")
    monkeypatch.setenv("OWNSTACK_PUBLIC_ORIGIN", "https://testserver")
    response = client.post("/v1/session", headers={"Origin": "https://testserver"},
                           json={"username": "atlas-admin", "password": "pass"})
    assert response.status_code == 200
    assert "token" not in response.json()
    assert all("Secure" in value for value in response.headers.get_list("set-cookie"))
    client.cookies.clear()
    assert client.get("/v1/me", headers={"Authorization": "Bearer forged"}).status_code == 401
