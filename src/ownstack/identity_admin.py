"""Operator-run identity lifecycle. No self-signup or browser role assignment.

Requires direct database access and an enabled tenant administrator recorded as
the audit actor. Passwords are prompted, never accepted in command-line arguments.
Functions leave commit/rollback to the caller so identity and audit are atomic.
"""
import argparse
from getpass import getpass
import json
import re
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from ownstack.auth import password_hash
from ownstack.models import IdentityEvent, User, WebSession

ROLES = {"admin", "engineer", "member", "contractor"}


def validate_password(password):
    if (type(password) is not str or not 16 <= len(password) <= 128
            or any(ord(char) < 32 for char in password)
            or password.casefold() in {"passwordpassword", "demo-only-pass", "change-me-password"}):
        raise ValueError("Use a private passphrase of 16 to 128 characters without control characters")


def operator(db, actor_id, tenant_id):
    actor = db.scalar(select(User).where(User.id == actor_id).with_for_update())
    if not actor or not actor.enabled or actor.tenant_id != tenant_id or actor.role != "admin":
        raise ValueError("An enabled administrator in the exact tenant is required")
    return actor


def provision(db, *, actor_id, tenant_id, user_id, role, password):
    validate_password(password)
    operator(db, actor_id, tenant_id)
    if (role not in ROLES or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,39}", user_id)
            or db.get(User, user_id) is not None):
        raise ValueError("Choose a new valid account ID and an allowed tenant role")
    user = User(id=user_id, tenant_id=tenant_id, role=role, password_hash=password_hash(password), enabled=True)
    db.add(user)
    db.flush()
    db.add(IdentityEvent(id=str(uuid4()), tenant_id=tenant_id, actor_id=actor_id,
        subject_id=user_id, action="account_provisioned"))
    return {"user_id": user.id, "tenant_id": user.tenant_id, "role": user.role, "action": "account_provisioned"}


def rotate(db, *, actor_id, tenant_id, user_id, password):
    validate_password(password)
    operator(db, actor_id, tenant_id)
    user = db.scalar(select(User).where(User.id == user_id, User.tenant_id == tenant_id).with_for_update())
    if not user:
        raise ValueError("Account unavailable in this tenant")
    user.password_hash = password_hash(password)
    user.token_version += 1
    revoked = db.execute(delete(WebSession).where(WebSession.user_id == user.id)).rowcount
    db.add(IdentityEvent(id=str(uuid4()), tenant_id=tenant_id, actor_id=actor_id,
        subject_id=user.id, action="password_rotated"))
    return {"user_id": user.id, "action": "password_rotated", "revoked_sessions": revoked,
        "enabled": user.enabled, "sign_in_required": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["create", "rotate"])
    parser.add_argument("--actor", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--role", choices=sorted(ROLES))
    args = parser.parse_args()
    if (args.operation == "create") != (args.role is not None):
        parser.error("Use --role only when creating an account")
    password = getpass("New private passphrase: ")
    if password != getpass("Repeat passphrase: "):
        parser.error("Passphrases did not match")
    from ownstack.config import Settings
    from ownstack.db import transaction
    try:
        Settings().validate()
        with transaction() as db:
            params = dict(actor_id=args.actor, tenant_id=args.tenant, user_id=args.user, password=password)
            result = provision(db, **params, role=args.role) if args.operation == "create" else rotate(db, **params)
        print(json.dumps(result))
    except ValueError as exc:
        parser.exit(1, str(exc) + "\n")
    except SQLAlchemyError:
        parser.exit(1, "Identity change failed and was rolled back. Check private database diagnostics.\n")


if __name__ == "__main__":
    main()
