from datetime import timedelta
import pytest
from sqlalchemy import func, select
from ownstack.auth import check_password, hash_secret, issue_token, parse_token
from ownstack.identity_admin import provision, rotate, validate_password
from ownstack.models import IdentityEvent, InferenceBudget, User, WebSession
from ownstack.service import utcnow

PRIVATE_TEST_PASSWORD = "synthetic-test-only-long-passphrase"


def test_provision_hashes_password_and_binds_tenant_role_and_audit(fixture_db):
    with fixture_db() as db:
        result = provision(db, actor_id="atlas-admin", tenant_id="atlas", user_id="atlas-new-member",
            role="member", password=PRIVATE_TEST_PASSWORD)
        db.commit()
        user = db.get(User, result["user_id"])
        assert user.tenant_id == "atlas" and user.role == "member"
        assert user.password_hash != PRIVATE_TEST_PASSWORD and check_password(PRIVATE_TEST_PASSWORD, user.password_hash)
        assert PRIVATE_TEST_PASSWORD not in str(result)
        assert db.scalar(select(IdentityEvent.action)) == "account_provisioned"
        assert db.get(InferenceBudget, "global").reserved_calls == 0


@pytest.mark.parametrize("actor,tenant", [("nova-admin", "atlas"), ("atlas-engineer", "atlas"), ("atlas-admin", "nova")])
def test_provision_denies_cross_tenant_and_non_admin(fixture_db, actor, tenant):
    with fixture_db() as db:
        with pytest.raises(ValueError, match="administrator"):
            provision(db, actor_id=actor, tenant_id=tenant, user_id="new-member", role="admin", password=PRIVATE_TEST_PASSWORD)
        assert db.get(User, "new-member") is None


def test_provision_cannot_overwrite_or_create_platform_owner(fixture_db):
    with fixture_db() as db:
        original = db.get(User, "atlas-admin").password_hash
        for user_id, role in [("atlas-admin", "admin"), ("new-owner", "product_owner"), ("../../escape", "member")]:
            with pytest.raises(ValueError):
                provision(db, actor_id="atlas-admin", tenant_id="atlas", user_id=user_id, role=role, password=PRIVATE_TEST_PASSWORD)
        assert db.get(User, "atlas-admin").password_hash == original


def test_rotation_revokes_cookie_and_local_token_without_reenabling(fixture_db):
    from fastapi import HTTPException
    with fixture_db() as db:
        user = db.get(User, "atlas-contractor")
        old_token = issue_token(user, "test-secret")
        user.enabled = False
        db.add(WebSession(token_hash=hash_secret("old-cookie"), user_id=user.id,
            csrf_hash=hash_secret("old-csrf"), expires_at=utcnow()+timedelta(hours=1)))
        db.commit()
        result = rotate(db, actor_id="atlas-admin", tenant_id="atlas", user_id=user.id, password=PRIVATE_TEST_PASSWORD)
        db.commit()
        assert result["revoked_sessions"] == 1 and user.enabled is False
        assert db.scalar(select(func.count(WebSession.token_hash))) == 0
        with pytest.raises(HTTPException):
            parse_token(old_token, "test-secret", expected_version=user.token_version)
        assert check_password(PRIVATE_TEST_PASSWORD, user.password_hash)


def test_rotation_scope_and_rollback_preserve_previous_password(fixture_db):
    with fixture_db() as db:
        original = db.get(User, "atlas-contractor").password_hash
        with pytest.raises(ValueError, match="unavailable"):
            rotate(db, actor_id="atlas-admin", tenant_id="atlas", user_id="nova-contractor", password=PRIVATE_TEST_PASSWORD)
        rotate(db, actor_id="atlas-admin", tenant_id="atlas", user_id="atlas-contractor", password=PRIVATE_TEST_PASSWORD)
        db.rollback()
        assert db.get(User, "atlas-contractor").password_hash == original
        assert db.scalar(select(func.count(IdentityEvent.id))) == 0


@pytest.mark.parametrize("password", ["short", "passwordpassword", "a"*129, "private\nlong-passphrase", None])
def test_invalid_passwords_are_rejected_without_echo(password):
    with pytest.raises(ValueError, match="private passphrase"):
        validate_password(password)
