from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from conftest import login
from ownstack.api import app
from ownstack.auth import check_password, hash_secret
from ownstack.models import Attempt, IdentityEvent, InferenceBudget, Tenant, User, WorkspaceInvitation

PASSWORD = "private-test-passphrase-2026"


def test_versioned_passwords_preserve_legacy_accounts_and_reject_invalid_hashes():
    import hashlib
    from ownstack.auth import password_hash
    salt = b'0123456789abcdef'
    legacy = salt.hex()+':'+hashlib.pbkdf2_hmac('sha256',PASSWORD.encode(),salt,300_000).hex()
    modern = password_hash(PASSWORD, salt)
    assert modern.startswith('pbkdf2_sha256:600000:')
    assert check_password(PASSWORD,legacy) and check_password(PASSWORD,modern)
    assert not check_password('wrong',legacy) and not check_password('wrong',modern)
    for invalid in ['', 'bad:hash', 'pbkdf2_sha256:999999999:a:b', None]:
        assert not check_password(PASSWORD,invalid)


def account(**extra):
    return {"username": "customer-one", "name": "Customer One", "password": PASSWORD, **extra}


def register(client, monkeypatch, **extra):
    monkeypatch.setenv("OWNSTACK_PUBLIC_SIGNUP", "true")
    return client.post('/v1/accounts/signup', json=account(workspace="Cedar", **extra))


def issue(client, role="member"):
    response = client.post('/v1/accounts/invitations', headers=login(client, 'atlas-admin'), json={"role": role})
    assert response.status_code == 201, response.text
    return response.json()


def test_signup_creates_private_workspace_session_project_and_no_ai(client, fixture_db, monkeypatch):
    response = register(client, monkeypatch)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved['role'] == 'admin' and saved['ai_mode'] == 'off'
    assert saved['workspace_name'] == 'Cedar' and saved['display_name'] == 'Customer One'
    assert saved['tenant_id'] not in {'atlas', 'nova', 'platform'}
    assert client.get('/v1/session').json()['project_id'] == saved['project_id']
    assert client.get(f"/v1/host/projects/{saved['project_id']}/documents").status_code == 200
    for path in ['/v1/host/projects/atlas-project/documents', '/v1/host/projects/nova-project/documents']:
        assert client.get(path).status_code == 404
    assert client.get('/v1/requests').json() == []
    assert client.get('/v1/inference-budget').json()['remaining_calls'] == 0
    with fixture_db() as db:
        user = db.get(User, 'customer-one')
        assert check_password(PASSWORD, user.password_hash) and PASSWORD not in user.password_hash
        assert not db.get(Tenant, saved['tenant_id']).ai_enabled
        assert db.get(InferenceBudget, 'global').reserved_calls == 0
        assert db.scalar(select(IdentityEvent.action).where(IdentityEvent.subject_id == user.id)) == 'workspace_created'


@pytest.mark.parametrize('extra', [{'role':'admin'}, {'tenant_id':'atlas'}, {'ai_enabled':True}, {'project_id':'nova-project'}])
def test_signup_rejects_authority_fields_atomically(client, fixture_db, monkeypatch, extra):
    assert register(client, monkeypatch, **extra).status_code == 422
    with fixture_db() as db:
        assert db.scalar(select(func.count()).select_from(Tenant)) == 3
        assert db.get(User, 'customer-one') is None


def test_registration_gate_origin_duplicate_and_existing_session(client, fixture_db, monkeypatch):
    assert client.get('/v1/accounts/config').json()['signup_enabled'] is False
    assert client.post('/v1/accounts/signup', json=account(workspace='Cedar')).status_code == 403
    monkeypatch.setenv('OWNSTACK_PUBLIC_SIGNUP', 'true')
    assert client.post('/v1/accounts/signup', headers={'Origin':'https://evil.invalid'}, json=account(workspace='Cedar')).status_code == 403
    assert register(client, monkeypatch).status_code == 201
    assert register(client, monkeypatch, username='other-person').status_code == 409
    client.cookies.clear()
    assert register(client, monkeypatch).status_code == 409
    with fixture_db() as db:
        assert db.scalar(select(func.count()).select_from(Tenant)) == 4
        assert db.get(User, 'other-person') is None


@pytest.mark.parametrize('body', [account(password='short-secret'), account(username='ADMIN'),
    account(name='  '), account(password='passwordpassword'), account(name='name\ncontrol')])
def test_invalid_signup_never_echoes_secrets(client, monkeypatch, body):
    monkeypatch.setenv('OWNSTACK_PUBLIC_SIGNUP','true')
    response = client.post('/v1/accounts/signup', json={**body,'workspace':'Cedar'})
    assert response.status_code == 422
    assert body['password'] not in response.text


def test_public_signup_rate_window_survives_failed_duplicates(client, monkeypatch):
    monkeypatch.setenv('OWNSTACK_PUBLIC_SIGNUP','true')
    for i in range(5):
        client.cookies.clear()
        result = register(client, monkeypatch)
        assert result.status_code == (201 if i == 0 else 409)
    assert register(client, monkeypatch).status_code == 429


def test_invitation_sets_server_role_is_hashed_single_use_and_tenant_scoped(client, fixture_db):
    invitation = issue(client, 'contractor')
    client.cookies.clear()
    view = client.post('/v1/accounts/invitations/inspect', json={'token':invitation['token']})
    assert view.json()['role'] == 'contractor'
    response = client.post('/v1/accounts/join',json=account(token=invitation['token']))
    assert response.status_code == 201, response.text
    assert response.json()['tenant_id'] == 'atlas' and response.json()['role'] == 'contractor'
    assert client.get('/v1/host/projects/nova-project/documents').status_code == 404
    assert client.get('/v1/host/projects/atlas-project/documents').status_code == 403
    client.cookies.clear()
    assert client.post('/v1/accounts/join',json=account(username='second-person',token=invitation['token'])).status_code == 404
    with fixture_db() as db:
        row = db.get(WorkspaceInvitation, invitation['id'])
        assert row.token_hash == hash_secret(invitation['token']) and row.used_by == 'customer-one'
        assert invitation['token'] not in json.dumps({'hash':row.token_hash})
        assert db.get(User, 'second-person') is None


@pytest.mark.parametrize('reason',['expired','revoked','issuer_disabled','issuer_role_changed'])
def test_unavailable_invites_cannot_create_account(client, fixture_db, reason):
    invitation = issue(client)
    with fixture_db() as db:
        row = db.get(WorkspaceInvitation, invitation['id'])
        if reason == 'expired': row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        if reason == 'revoked': row.revoked = True
        if reason == 'issuer_disabled': db.get(User, 'atlas-admin').enabled = False
        if reason == 'issuer_role_changed': db.get(User, 'atlas-admin').role = 'member'
        db.commit()
    client.cookies.clear()
    assert client.post('/v1/accounts/join',json=account(token=invitation['token'])).status_code == 404
    with fixture_db() as db: assert db.get(User, 'customer-one') is None


def test_invitation_role_escalation_cross_tenant_revocation_and_secret_listing(client):
    invitation = issue(client)
    headers = login(client,'atlas-admin')
    listed = client.get('/v1/accounts/invitations',headers=headers)
    assert invitation['token'] not in listed.text and 'token_hash' not in listed.text
    for role in ['admin','product_owner']:
        assert client.post('/v1/accounts/invitations',headers=headers,json={'role':role}).status_code == 422
    assert client.post(f"/v1/accounts/invitations/{invitation['id']}/revoke",headers=login(client,'nova-admin')).status_code == 404
    assert client.post('/v1/accounts/invitations',headers=login(client,'atlas-engineer'),json={'role':'member'}).status_code == 403
    client.cookies.clear()
    assert client.post('/v1/accounts/join',json=account(token=invitation['token'],role='admin')).status_code == 422


def test_wrong_username_does_not_consume_invitation(client, fixture_db):
    invitation = issue(client)
    client.cookies.clear()
    assert client.post('/v1/accounts/join',json=account(username='atlas-admin',token=invitation['token'])).status_code == 409
    assert client.post('/v1/accounts/join',json=account(token=invitation['token'])).status_code == 201


def test_password_change_rotates_session_revokes_old_tokens_and_requires_current_password(client, monkeypatch):
    result = register(client, monkeypatch).json()
    old_token = result['token']; old_cookie = client.cookies.get('ownstack_session')
    csrf = {'X-CSRF-Token':result['csrf_token']}
    body = {'current_password':PASSWORD,'password':'another-private-passphrase-2026'}
    assert client.post('/v1/accounts/password',json=body).status_code == 403
    assert client.post('/v1/accounts/password',headers=csrf,json={**body,'current_password':'wrong'}).status_code == 400
    response = client.post('/v1/accounts/password',headers=csrf,json=body)
    assert response.status_code == 200
    assert response.json()['csrf_token'] != result['csrf_token']
    assert client.get('/v1/session').status_code == 200
    client.cookies.clear();client.cookies.set('ownstack_session',old_cookie)
    assert client.get('/v1/session').status_code == 401
    client.cookies.clear()
    assert client.get('/v1/me',headers={'Authorization':'Bearer '+old_token}).status_code == 401
    assert client.post('/v1/session',json={'username':' CUSTOMER-ONE ','password':body['password']}).status_code == 200
    assert client.post('/v1/session',json={'username':'customer-one','password':PASSWORD}).status_code == 401


def test_new_customer_cannot_reserve_demo_inference_even_by_direct_api(client, fixture_db, monkeypatch):
    session = register(client,monkeypatch).json()
    headers = {'X-CSRF-Token':session['csrf_token'],'Idempotency-Key':'account-request'}
    request = client.post('/v1/requests',headers=headers,json={'kind':'feature','text':'Add PDF export for Cedar.',
                          'project_id':session['project_id']}).json()
    monkeypatch.setenv('OWNSTACK_AI_MODE','nebius');monkeypatch.setenv('NEBIUS_API_KEY','synthetic-no-network')
    monkeypatch.setenv('NEBIUS_MODEL_ID','nvidia/Nemotron-Test');monkeypatch.setenv('OWNSTACK_MAX_LIVE_CALLS','40')
    assert client.post(f"/v1/requests/{request['id']}/interpret",headers=headers).status_code == 403
    assert client.post(f"/v1/requests/{request['id']}/investigations",headers=headers,json={'revision':1}).status_code == 403
    with fixture_db() as db:
        assert db.get(InferenceBudget,'global').reserved_calls == 0
        assert db.scalar(select(func.count()).select_from(Attempt)) == 0
