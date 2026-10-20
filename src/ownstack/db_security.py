"""Fail closed on administrative runtime database privileges in production."""
from sqlalchemy import text


POSTURE_SQL = """
SELECT NOT (
    r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication OR r.rolbypassrls
    OR has_schema_privilege(current_user, 'public', 'CREATE')
    OR has_database_privilege(current_user, current_database(), 'CREATE')
    OR has_database_privilege(current_user, current_database(), 'TEMP')
    -- Ownership retains re-grant/ALTER authority even after ordinary REVOKE.
    OR EXISTS (SELECT 1 FROM pg_database d WHERE d.datname=current_database() AND d.datdba=r.oid)
    OR EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspowner=r.oid)
    OR EXISTS (SELECT 1 FROM pg_class c WHERE c.relowner=r.oid)
    OR EXISTS (SELECT 1 FROM pg_proc p WHERE p.proowner=r.oid)
    OR has_table_privilege(current_user, 'public.alembic_version', 'INSERT,UPDATE,DELETE')
    OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname='public' AND c.relkind IN ('r','p')
               AND has_table_privilege(current_user, c.oid, 'TRUNCATE'))
    -- Conservative dedicated runtime identities have no other role membership,
    -- including predefined server-file/program and owner roles.
    OR EXISTS (SELECT 1 FROM pg_roles p WHERE p.oid<>r.oid
               AND pg_has_role(current_user, p.oid, 'MEMBER'))
) FROM pg_roles r WHERE r.rolname=current_user
"""


def runtime_role_safe(db):
    return db.bind.dialect.name == 'postgresql' and db.execute(text(POSTURE_SQL)).scalar_one() is True


def enabled_seed_passwords_present(db):
    """Configuration alone never rotates passwords already stored in a database."""
    from sqlalchemy import select
    from ownstack.auth import check_password
    from ownstack.models import User
    for row in db.scalars(select(User).where(User.enabled.is_(True))):
        if check_password('demo-only-pass', row.password_hash):
            return True
    return False
