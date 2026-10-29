"""Prepare private deployment files and initialize a NEW synthetic demo database.

No cloud provisioning, inference, existing identity rotation or existing-database
repair. The initialize command requires migration-owner access and reads account
secrets from stdin. Runtime services never receive the owner credential.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from psycopg import Error as PostgresError

ACCOUNTS = {
    "atlas-admin": ("atlas", "admin"),
    "atlas-engineer": ("atlas", "engineer"),
    "atlas-contractor": ("atlas", "contractor"),
    "nova-admin": ("nova", "admin"),
    "nova-contractor": ("nova", "contractor"),
    "platform-owner": ("platform", "product_owner"),
}
def validate_observed_reservations(value):
    if type(value) is not int or not 20 <= value <= 40:
        raise ValueError("Supply the observed original-ledger count, between twenty and forty")
    return value


def validate_domain(domain):
    """Accept a concrete DNS hostname, never a URL, wildcard or template."""
    if (not isinstance(domain, str) or len(domain) > 253 or domain != domain.lower()
            or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain)
            or domain.endswith((".example", ".invalid", ".localhost", ".test", ".local", ".internal",
                ".example.com", ".example.org", ".example.net"))
            or domain in {"example.com", "example.org", "example.net"}):
        raise ValueError("Use the actual public DNS hostname without a scheme or path")
    return domain


def prepare(domain, destination, *, observed_reservations):
    """Create a new 0700 directory and exclusive 0600 files; never overwrite."""
    validate_domain(domain)
    validate_observed_reservations(observed_reservations)
    destination = Path(destination)
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise ValueError("Choose an existing trusted parent directory")
    destination.mkdir(mode=0o700)
    passwords = {name: secrets.token_urlsafe(32) for name in ACCOUNTS}
    values = {
        "OWNSTACK_ENV": "production", "OWNSTACK_DOMAIN": domain,
        "OWNSTACK_PUBLIC_ORIGIN": "https://" + domain,
        "OWNSTACK_SIGNING_SECRET": secrets.token_hex(32),
        "OWNSTACK_DEMO_PASSWORD": secrets.token_hex(32),
        "OWNSTACK_DB_PASSWORD": secrets.token_hex(32),
        "OWNSTACK_RUNTIME_DB_USER": "ownstack_app",
        "OWNSTACK_RUNTIME_DB_PASSWORD": secrets.token_hex(32),
        "OWNSTACK_AI_MODE": "off", "OWNSTACK_MAX_LIVE_CALLS": "0",
        "OWNSTACK_OBSERVED_RESERVATIONS": str(observed_reservations),
        "NEBIUS_API_KEY": "", "NEBIUS_MODEL_ID": "", "NEBIUS_PATCH_MODEL_ID": "",
        "OWNSTACK_AI_TIMEOUT_SECONDS": "60", "OWNSTACK_BUILD_REVISION": "uncommitted-reference",
        "OWNSTACK_SERVICE_SUBNET": "172.30.0.0/24",
        "OWNSTACK_WEB_INTERNAL_IP": "172.30.0.10", "OWNSTACK_EDGE_INTERNAL_IP": "172.30.0.20",
    }
    contents = {
        ".env.production": "".join(f"{key}={value}\n" for key, value in values.items()),
        "accounts.json": json.dumps({"version": 1, "passwords": passwords}, indent=2) + "\n",
    }
    for name, content in contents.items():
        descriptor = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
    return {"prepared": True, "accounts": len(passwords), "inference_enabled": False,
        "secrets": "private files only", "deployed": False}


def validate_accounts(payload):
    from ownstack.identity_admin import validate_password
    if (not isinstance(payload, dict) or set(payload) != {"version", "passwords"}
            or type(payload["version"]) is not int or payload["version"] != 1
            or not isinstance(payload["passwords"], dict) or set(payload["passwords"]) != set(ACCOUNTS)):
        raise ValueError("Expected a complete version-one private account bundle")
    passwords = payload["passwords"]
    for value in passwords.values():
        validate_password(value)
    if len(set(passwords.values())) != len(passwords):
        raise ValueError("Every account requires an independent private passphrase")
    return passwords


def read_account_file(path):
    """Read a small operator-owned private bundle, refusing symlinks/public files."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor) as stream:
        details = os.fstat(stream.fileno())
        if (not stat.S_ISREG(details.st_mode) or details.st_mode & 0o077
                or details.st_uid != os.geteuid() or details.st_size > 16384):
            raise ValueError("Use an operator-owned 0600 private account file")
        raw = stream.read(16385)
        if len(raw) > 16384:
            raise ValueError("Private account bundle is too large")
        return validate_accounts(json.loads(raw))


def initialize_fixture(db, payload, *, observed_reservations):
    """Atomic, empty-database-only fixture initialization; caller owns commit."""
    from ownstack.auth import password_hash
    from ownstack.db import Base
    from ownstack import models, repair_models  # noqa: F401
    from ownstack.models import Contract, Document, IdentityEvent, InferenceBudget, Project, Tenant, User
    from ownstack.policy import CONTRACT, digest
    from ownstack.team_scope import ensure_general_team,add_general_member
    from uuid import uuid4

    passwords = validate_accounts(payload)
    validate_observed_reservations(observed_reservations)
    # Inspect every current application table, including attempts and receipts.
    # Never convert an existing runtime into a new budget or rotate its users.
    existing_budget = db.get(InferenceBudget, "global")
    budget_rows = db.scalar(select(func.count()).select_from(InferenceBudget))
    if (any(db.scalar(select(func.count()).select_from(table)) for table in Base.metadata.sorted_tables
            if table.name != InferenceBudget.__tablename__)
            or budget_rows not in {0, 1}
            or (budget_rows == 1 and (existing_budget is None or existing_budget.reserved_calls != 0))):
        raise ValueError("Initialization requires an empty migrated application database")
    db.add_all([Tenant(id="atlas", name="Atlas Industries"), Tenant(id="nova", name="Nova Labs"),
        Tenant(id="platform", name="OwnStack product team")])
    db.flush()
    for tenant in ['atlas','nova','platform']:ensure_general_team(db,tenant)
    db.add_all(User(id=name, tenant_id=tenant, role=role, password_hash=password_hash(passwords[name]))
        for name, (tenant, role) in ACCOUNTS.items())
    db.flush()
    for user in db.scalars(select(User)).all():add_general_member(db,user)
    db.add_all([Project(id="atlas-project", tenant_id="atlas", name="Project Atlas", revision=1),
        Project(id="nova-project", tenant_id="nova", name="Project Nova", revision=1)])
    db.flush()
    db.add_all([
        Document(id="atlas-roadmap", tenant_id="atlas", project_id="atlas-project", title="Atlas roadmap", body="Synthetic Atlas planning notes"),
        Document(id="atlas-budget", tenant_id="atlas", project_id="atlas-project", title="Atlas budget", body="Synthetic Atlas budget"),
        Document(id="nova-roadmap", tenant_id="nova", project_id="nova-project", title="Nova roadmap", body="Synthetic Nova planning notes"),
        Contract(id=CONTRACT["id"], version=1, manifest=CONTRACT, manifest_hash=digest(CONTRACT)),
    ])
    # The original migration installs one zero counter even in an empty target.
    # Carry history forward; never decrement or replace a used ledger.
    if existing_budget is None:
        db.add(InferenceBudget(id="global", reserved_calls=observed_reservations))
    else:
        existing_budget.reserved_calls = observed_reservations
    db.add_all(IdentityEvent(id=str(uuid4()), tenant_id=tenant, actor_id=name,
        subject_id=name, action="deployment_account_initialized") for name, (tenant, _) in ACCOUNTS.items())
    db.flush()


def provision_runtime_role(db, name, password):
    """Transactional PostgreSQL DML-only role, no inherited or ownership rights."""
    from psycopg import sql
    from ownstack.identity_admin import validate_password
    validate_password(password)
    if not re.fullmatch(r"ownstack_[a-z0-9_]{3,40}", name) or db.bind.dialect.name != "postgresql":
        raise ValueError("Dedicated PostgreSQL runtime role required")
    connection = db.connection().connection.driver_connection
    with connection.cursor() as cursor:
        if cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (name,)).fetchone():
            raise ValueError("Runtime role already exists; no credentials were rotated")
        database, owner = cursor.execute("SELECT current_database(),current_user").fetchone()
        role = sql.Identifier(name)
        cursor.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS")
            .format(role, sql.Literal(password)))
        cursor.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database)))
        cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), role))
        cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        cursor.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC")
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
        cursor.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}").format(role))
        cursor.execute(sql.SQL("REVOKE INSERT,UPDATE,DELETE ON alembic_version FROM {}").format(role))
        cursor.execute(sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(role))
        cursor.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO {}")
            .format(sql.Identifier(owner), role))
        cursor.execute(sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO {}")
            .format(sql.Identifier(owner), role))


def initialize(payload):
    from ownstack.config import Settings
    from ownstack.db import transaction
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    settings = Settings()
    settings.validate()
    if (settings.environment != "production" or settings.ai_mode != "off" or settings.max_live_calls != 0
            or settings.nebius_key or settings.nebius_model or settings.nebius_patch_model):
        raise ValueError("Initial setup requires production, AI off, zero cap and empty provider fields")
    validate_accounts(payload)
    role = os.environ.get("OWNSTACK_RUNTIME_DB_USER", "")
    password = os.environ.get("OWNSTACK_RUNTIME_DB_PASSWORD", "")
    observed_reservations = validate_observed_reservations(int(os.environ.get("OWNSTACK_OBSERVED_RESERVATIONS", "")))
    with transaction() as db:
        if db.bind.dialect.name != "postgresql":
            raise ValueError("Deployment initialization requires PostgreSQL")
        db.execute(text("SELECT pg_advisory_xact_lock(1331121201)"))
        head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
        if db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != head:
            raise ValueError("Migrate this new target to the current schema first")
        initialize_fixture(db, payload, observed_reservations=observed_reservations)
        provision_runtime_role(db, role, password)
    return {"initialized": True, "synthetic_accounts": len(ACCOUNTS),
        "historical_reservations_preserved": observed_reservations,
        "inference_calls": 0, "deployed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    config = commands.add_parser("prepare")
    config.add_argument("--domain", required=True)
    config.add_argument("--private-directory", type=Path, required=True)
    config.add_argument("--observed-reservations", type=int, required=True)
    commands.add_parser("initialize")
    args = parser.parse_args()
    try:
        if args.operation == "prepare":
            result = prepare(args.domain, args.private_directory, observed_reservations=args.observed_reservations)
        else:
            raw = sys.stdin.read(16385)
            if len(raw) > 16384:
                raise ValueError("Private account bundle is too large")
            result = initialize(json.loads(raw))
        print(json.dumps(result))
    except (ValueError, OSError, SQLAlchemyError, PostgresError):
        parser.exit(1, "Deployment setup failed; no existing identity was changed. Inspect private diagnostics.\n")


if __name__ == "__main__":
    main()
