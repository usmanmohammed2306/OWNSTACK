"""Rollback-only PostgreSQL controls on the existing private restored fixture.

Prove object ownership cannot be hidden by REVOKE, and reject predefined role
membership. Creates no permanent role/table, touches no source DB, uses no AI.
"""
import json
import os
from uuid import uuid4
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from ownstack.db_security import POSTURE_SQL


def main():
    admin_url=make_url(os.environ['OWNSTACK_REHEARSAL_DATABASE_URL'])
    runtime_url=make_url(os.environ['OWNSTACK_REHEARSAL_RUNTIME_DATABASE_URL'])
    if (os.environ.get('OWNSTACK_AI_MODE')!='off' or os.environ.get('OWNSTACK_MAX_LIVE_CALLS')!='0'
            or any(os.environ.get(k) for k in ['NEBIUS_API_KEY','NEBIUS_MODEL_ID','NEBIUS_PATCH_MODEL_ID'])
            or admin_url.get_backend_name()!='postgresql'
            or admin_url.host!='ownstack-db-1' or admin_url.query or runtime_url.query
            or runtime_url.host!=admin_url.host or runtime_url.database!=admin_url.database
            or not admin_url.database.startswith('ownstack_restore_')):
        raise ValueError('Existing local restored fixture and AI off required')
    engine=create_engine(admin_url);runtime=create_engine(runtime_url)
    role='ownstack_control_'+uuid4().hex
    table='ownership_control_'+uuid4().hex
    report={'inference_calls':0,'persistent_role_created':False,'source_modified':False}
    try:
        with runtime.connect() as db:
            report['actual_runtime_safe']=db.execute(text(POSTURE_SQL)).scalar_one() is True
        with engine.connect() as db:
            outer=db.begin()
            try:
                db.exec_driver_sql(f'CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS')
                db.exec_driver_sql(f'GRANT USAGE,CREATE ON SCHEMA public TO {role}')
                db.exec_driver_sql(f'CREATE TABLE public.{table} (n integer)')
                db.exec_driver_sql(f'ALTER TABLE public.{table} OWNER TO {role}')
                db.exec_driver_sql(f'REVOKE CREATE ON SCHEMA public FROM {role}')
                db.exec_driver_sql(f'REVOKE ALL ON public.{table} FROM {role}')
                db.exec_driver_sql(f'SET LOCAL ROLE {role}')
                # Without ownership checks this non-admin role looks innocuous.
                ordinary=db.execute(text("SELECT NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole "
                    "AND NOT has_schema_privilege(current_user,'public','CREATE') "
                    f"AND NOT has_table_privilege(current_user,'public.{table}','TRUNCATE') "
                    "FROM pg_roles WHERE rolname=current_user")).scalar_one()
                report['ownership_control_ordinary_rights_revoked']=ordinary is True
                report['table_owner_rejected_after_revoke']=db.execute(text(POSTURE_SQL)).scalar_one() is False
                db.exec_driver_sql('RESET ROLE')
                # Remove only the transaction-created ownership for this next control.
                db.exec_driver_sql(f'ALTER TABLE public.{table} OWNER TO {admin_url.username}')
                db.exec_driver_sql(f'GRANT pg_read_server_files TO {role}')
                db.exec_driver_sql(f'SET LOCAL ROLE {role}')
                report['predefined_server_file_role_rejected']=db.execute(text(POSTURE_SQL)).scalar_one() is False
                db.exec_driver_sql('RESET ROLE')
            finally:
                outer.rollback()
            report['role_and_table_rolled_back']=(db.execute(text('SELECT count(*) FROM pg_roles WHERE rolname=:r'),{'r':role}).scalar_one()==0
                and db.execute(text('SELECT to_regclass(:t)'),{'t':'public.'+table}).scalar_one() is None)
            report['ledger_unchanged']=db.execute(text("SELECT reserved_calls FROM inference_budget WHERE id='global'")).scalar_one()==10
        report['passed']=all(report[k] for k in ['actual_runtime_safe','ownership_control_ordinary_rights_revoked',
            'table_owner_rejected_after_revoke','predefined_server_file_role_rejected',
            'role_and_table_rolled_back','ledger_unchanged'])
        print(json.dumps(report,indent=2))
        return 0 if report['passed'] else 1
    finally:
        engine.dispose();runtime.dispose()


if __name__=='__main__':raise SystemExit(main())
