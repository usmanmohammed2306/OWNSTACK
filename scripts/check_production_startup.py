"""No-server production startup controls on the private, restored local fixture.

Uses a rollback-only identity change for the positive case. No port binding,
password rotation, account change commit, provider call or deployment occurs.
Run inside the trusted API test image with its private runtime env file.
"""
import asyncio
import json
import os
import secrets
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


def main():
    raw=os.environ.get('OWNSTACK_REHEARSAL_RUNTIME_DATABASE_URL','')
    url=make_url(raw)
    if (os.environ.get('OWNSTACK_AI_MODE')!='off' or os.environ.get('OWNSTACK_MAX_LIVE_CALLS')!='0'
            or url.get_backend_name()!='postgresql' or not url.database.startswith('ownstack_restore_')
            or url.host not in {'ownstack-db-1','localhost','127.0.0.1'} or url.query
            or any(os.environ.get(key) for key in ['NEBIUS_API_KEY','NEBIUS_MODEL_ID','NEBIUS_PATCH_MODEL_ID'])):
        raise ValueError('Private restored fixture, AI off, cap zero and empty keys required')
    os.environ.update(OWNSTACK_DATABASE_URL=raw,OWNSTACK_ENV='production',
        OWNSTACK_PUBLIC_ORIGIN='https://ownstack-security.invalid',OWNSTACK_REQUIRE_BACKGROUND='true',
        OWNSTACK_TRUSTED_PROXY_IPS='127.0.0.1',OWNSTACK_SIGNING_SECRET=secrets.token_hex(32),
        OWNSTACK_DEMO_PASSWORD=secrets.token_hex(32))
    from ownstack import api
    from ownstack.db_security import runtime_role_safe
    engine=create_engine(url)
    report={'production_defaults_rejected':False,'positive_startup_without_seed_passwords':False,
            'identity_changes_rolled_back':False,'server_started':False,'inference_calls':0}
    async def start():
        async with api.lifespan(api.app):pass
    try:
        with engine.connect() as connection:
            original=connection.execute(text('SELECT id,enabled FROM users ORDER BY id')).all()
            connection.rollback()
            with Session(engine) as db:
                assert runtime_role_safe(db)
            try:asyncio.run(start())
            except RuntimeError as error:
                if 'default fixture password' not in str(error):raise
                report['production_defaults_rejected']=True
            else:raise AssertionError('Production accepted default fixture identities')
            outer=connection.begin()
            saved_factory=api.SessionLocal
            try:
                # No session outside this connection can see these identity changes.
                connection.execute(text('UPDATE users SET enabled=false'))
                api.SessionLocal=lambda:Session(bind=connection,join_transaction_mode='create_savepoint')
                asyncio.run(start())
                report['positive_startup_without_seed_passwords']=True
            finally:
                api.SessionLocal=saved_factory
                outer.rollback()
            report['identity_changes_rolled_back']=connection.execute(text('SELECT id,enabled FROM users ORDER BY id')).all()==original
            assert connection.execute(text("SELECT reserved_calls FROM inference_budget WHERE id='global'")).scalar_one()==10
        report['passed']=all(report[key] for key in ['production_defaults_rejected',
            'positive_startup_without_seed_passwords','identity_changes_rolled_back'])
        report['limit']='Rollback-only lifecycle test, not live TLS, production identity or hosted deployment'
        print(json.dumps(report,indent=2))
        return 0 if report['passed'] else 1
    finally:engine.dispose()


if __name__=='__main__':raise SystemExit(main())
