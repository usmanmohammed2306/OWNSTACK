"""Create a DML-only runtime role in one NEW local restored fixture, never main.

Run inside the trusted API image on the local database container's network.
Credentials go only to a new private 0600 file, never stdout/argv. The source
database/roles, original ledger and migration owner are not altered.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
from uuid import uuid4
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url
from ownstack.config import Settings


def provision(settings, output):
    url = make_url(settings.database_url)
    if (settings.environment != 'local' or settings.ai_mode != 'off' or settings.max_live_calls != 0
            or settings.nebius_key or settings.nebius_model or settings.nebius_patch_model
            or url.drivername != 'postgresql+psycopg' or url.host not in {'127.0.0.1','localhost','db'}
            or not url.database or not url.database.startswith('ownstack_restore_') or url.query
            or output.exists() or not output.parent.is_dir() or output.parent.stat().st_mode & 0o077):
        raise ValueError('New private output and local AI-off restored fixture required')
    role, password = 'ownstack_runtime_'+uuid4().hex, secrets.token_hex(32)
    parameters = {'host':url.host,'port':url.port or 5432,'dbname':url.database,
                  'user':url.username,'password':url.password,'connect_timeout':5}
    with psycopg.connect(**parameters) as admin:
        if admin.execute("SELECT reserved_calls FROM inference_budget WHERE id='global'").fetchone() != (10,):
            raise ValueError('Existing exhausted snapshot ledger required')
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS')
                      .format(sql.Identifier(role),sql.Literal(password)))
        admin.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(url.database)))
        admin.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(url.database),sql.Identifier(role)))
        admin.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
        admin.execute('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC')
        admin.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(role)))
        admin.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}').format(sql.Identifier(role)))
        admin.execute(sql.SQL('REVOKE INSERT,UPDATE,DELETE ON alembic_version FROM {}').format(sql.Identifier(role)))
        admin.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(sql.Identifier(role)))
        admin.execute(sql.SQL('ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO {}')
                      .format(sql.Identifier(url.username),sql.Identifier(role)))
        admin.execute(sql.SQL('ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO {}')
                      .format(sql.Identifier(url.username),sql.Identifier(role)))
    denied = []
    role_parameters = {**parameters, 'user':role, 'password':password}
    for name, statement in [
        ('schema_ddl', 'CREATE TABLE public.forbidden_probe (n integer)'),
        ('temporary_table','CREATE TEMP TABLE forbidden_temp (n integer)'),
        ('truncate_probe','TRUNCATE public.recovery_probe'),
        ('migration_metadata_write', "UPDATE public.alembic_version SET version_num=version_num"),
        ('admin_role_switch','SET LOCAL ROLE ownstack')]:
        with psycopg.connect(**role_parameters) as runtime:
            blocked=False
            try:
                # Even a defective grant would be rolled back, never a destructive test.
                with runtime.transaction(force_rollback=True):
                    runtime.execute(statement)
            except psycopg.errors.InsufficientPrivilege:
                blocked=True
            if not blocked:
                raise ValueError('Runtime privilege negative check failed')
            denied.append(name)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from ownstack.db_security import runtime_role_safe
    runtime_url=url.set(username=role,password=password)
    engine=create_engine(runtime_url)
    try:
        with Session(engine) as runtime:
            if not runtime_role_safe(runtime):
                raise ValueError('Runtime role posture rejected')
    finally:
        engine.dispose()
    with psycopg.connect(**{**role_parameters,'dbname':'ownstack'}) as runtime:
        try:
            runtime.execute('SELECT reserved_calls FROM public.inference_budget').fetchone()
        except psycopg.errors.InsufficientPrivilege:
            denied.append('source_workflow_read')
        else:
            raise ValueError('New role unexpectedly reads the original source database')
    # Store a container-reachable DSN, not its shared-network loopback address.
    reachable=runtime_url.set(host='ownstack-db-1').render_as_string(hide_password=False)
    descriptor=os.open(output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(descriptor,'w') as stream:
        stream.write('OWNSTACK_REHEARSAL_RUNTIME_DATABASE_URL='+reachable+'\nOWNSTACK_ENFORCE_DB_ROLE=true\n')
    return {'passed':True,'runtime_role':role,'target_database':url.database,
            'negative_privilege_checks':denied,'source_and_target_ledger':10,'inference_calls':0,
            'credentials':'new private 0600 file, not printed','source_roles_modified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-output',required=True,type=Path)
    args=parser.parse_args()
    try:
        report=provision(Settings(),args.private_output)
    except Exception as error:
        report={'passed':False,'error_type':type(error).__name__,'inference_calls':0}
    print(json.dumps(report,indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
