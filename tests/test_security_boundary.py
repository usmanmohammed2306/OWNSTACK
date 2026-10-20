import asyncio
from pathlib import Path
import json
import os
import time
import pytest
from fastapi.testclient import TestClient
from ownstack.api import app, SCHEMA_REVISION
from ownstack.config import Settings
from ownstack.http_security import SecurityBoundary
from ownstack import http_security
from ownstack.job_files import read_json, write_json
from ownstack.runner import candidate_payload, current_provenance
from ownstack.patch_agent import fixture_patch
from ownstack.candidate_sandbox import ALLOWED_SYSCALLS, POLICY_ID


def production(monkeypatch):
    monkeypatch.setenv('OWNSTACK_ENV','production')
    monkeypatch.setenv('OWNSTACK_PUBLIC_ORIGIN','https://ownstack.example')
    return TestClient(app,base_url='https://ownstack.example')


def test_production_rejects_host_spoofing_and_untrusted_forwarded_https(client,monkeypatch):
    secure=production(monkeypatch)
    assert secure.get('/health/live').status_code==200
    assert secure.get('/health/live',headers={'Host':'evil.example'}).status_code==400
    insecure=TestClient(app,base_url='http://ownstack.example')
    assert insecure.get('/health/live',headers={'X-Forwarded-Proto':'https'}).status_code==426
    assert secure.get('/openapi.json').status_code==404
    assert secure.get('/docs').status_code==404
    response=secure.get('/health/live')
    assert response.headers['strict-transport-security']=='max-age=31536000'
    assert response.headers['x-frame-options']=='DENY'
    assert response.headers['cache-control']=='no-store'


def test_production_host_prefix_csrf_and_legacy_cookie_rejection(client,monkeypatch):
    from ownstack.auth import SESSION_COOKIE,CSRF_COOKIE
    secure=production(monkeypatch)
    response=secure.post('/v1/session',headers={'Origin':'https://ownstack.example'},
                         json={'username':'atlas-admin','password':'pass'})
    assert response.status_code==200
    cookies=response.headers.get_list('set-cookie')
    assert all('__Host-ownstack_' in cookie and 'Secure' in cookie and 'Path=/' in cookie
               and 'Domain=' not in cookie for cookie in cookies)
    assert secure.get('/v1/me').status_code==200
    assert secure.post('/v1/session/logout',headers={'Origin':'https://ownstack.example'}).status_code==403
    csrf=secure.cookies.get('__Host-'+CSRF_COOKIE)
    assert secure.post('/v1/session/logout',headers={'Origin':'https://evil.example','X-CSRF-Token':csrf}).status_code==403
    token=secure.cookies.get('__Host-'+SESSION_COOKIE)
    secure.cookies.clear()
    secure.cookies.set(SESSION_COOKIE,token)
    assert secure.get('/v1/me').status_code==401


@pytest.mark.parametrize('origin', ['https://user:pass@ownstack.example','https://ownstack.example/path',
    'https://ownstack.example?query=1','https://ownstack.example#fragment','https://ownstack.example:bad',
    'https://ownstack.example:99999','https://ownstack.example\n'])
def test_production_origin_must_be_a_real_origin(origin):
    with pytest.raises(ValueError):
        Settings(environment='production',ai_mode='off',database_url='postgresql+psycopg://a:b@db/ownstack',
            signing_secret='s'*40,demo_password='independent-test-password',require_background=True,
            trusted_proxy_ips='10.0.0.2',public_origin=origin).validate()


@pytest.mark.parametrize('trusted',['','*','0.0.0.0/0','10.0.0.0/8','proxy.example'])
def test_production_refuses_implicit_or_broad_proxy_trust(trusted):
    with pytest.raises(ValueError):
        Settings(environment='production',ai_mode='off',database_url='postgresql+psycopg://a:b@db/ownstack',
            signing_secret='s'*40,demo_password='independent-test-password',require_background=True,
            trusted_proxy_ips=trusted,public_origin='https://ownstack.example').validate()


def boundary_status(headers,parts,monkeypatch=None):
    output=[]
    called=[]
    async def target(scope,receive,send):
        called.append(True)
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'ok'})
    messages=iter([{'type':'http.request','body':part,'more_body':index<len(parts)-1} for index,part in enumerate(parts)])
    async def receive():return next(messages)
    async def send(message):output.append(message)
    asyncio.run(SecurityBoundary(target)({'type':'http','headers':headers,'scheme':'http','path':'/'},receive,send))
    return output[0]['status'],called


@pytest.mark.parametrize('headers,parts,expected',[
    ([(b'content-length',b'65537')],[b''],413),
    ([],[b'a'*32768,b'b'*32769],413),
    ([(b'content-length',b'-1')],[b''],400),
    ([(b'content-length',b'0'),(b'content-length',b'1')],[b''],400),
    ([(b'content-length',b'2')],[b'abc'],400),
    ([(b'content-length',b'3')],[b'a',b'bc'],200),
])
def test_asgi_bounds_streamed_bodies_before_route_execution(headers,parts,expected):
    status,called=boundary_status(headers,parts)
    assert status==expected and bool(called)==(expected==200)


def test_body_read_timeout_is_local_and_does_not_run_route(monkeypatch):
    async def timeout(awaitable,seconds):
        awaitable.close()
        raise TimeoutError
    monkeypatch.setattr(http_security.asyncio,'wait_for',timeout)
    status,called=boundary_status([], [b''])
    assert status==408 and not called


@pytest.mark.parametrize('kind',['symlink','hardlink','fifo','oversize','array'])
def test_queue_messages_reject_non_regular_or_unbounded_files(tmp_path,kind):
    path=tmp_path/'message.json'
    other=tmp_path/'other'
    other.write_text('{"private":"synthetic"}')
    if kind=='symlink':path.symlink_to(other)
    elif kind=='hardlink':os.link(other,path)
    elif kind=='fifo':os.mkfifo(path)
    elif kind=='oversize':path.write_bytes(b'x'*4097)
    else:path.write_text('[]')
    with pytest.raises((OSError,ValueError)):
        read_json(path,4096)


def test_atomic_output_does_not_follow_existing_symlink(tmp_path):
    target=tmp_path/'keep'
    target.write_text('unchanged')
    outgoing=tmp_path/'result.json'
    outgoing.symlink_to(target)
    write_json(outgoing,{'passed':False})
    assert target.read_text()=='unchanged' and not outgoing.is_symlink()
    assert read_json(outgoing,4096)=={'passed':False}


def test_candidate_protocol_never_accepts_the_trusted_host_bypass():
    payload,_=candidate_payload(fixture_patch())
    assert set(json.loads(payload))=={'source','cases'}
    assert not set(ALLOWED_SYSCALLS)&{'open','openat','socket','clone','clone3','fork','vfork','execve',
        'execveat','ptrace','mount','bpf','io_uring_setup','process_vm_writev','memfd_create','seccomp','prctl'}


def test_seed_password_check_reads_stored_hashes_not_new_config(fixture_db):
    from ownstack.db_security import enabled_seed_passwords_present
    from ownstack.auth import password_hash
    from ownstack.models import User
    with fixture_db() as db:
        assert not enabled_seed_passwords_present(db)
        user=db.get(User,'atlas-admin')
        user.password_hash=password_hash('demo-only-pass')
        db.commit()
        assert enabled_seed_passwords_present(db)
        user.enabled=False;db.commit()
        assert not enabled_seed_passwords_present(db)


def test_proxy_server_trust_is_limited_to_one_peer():
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    seen=[]
    async def app(scope,receive,send):seen.append(scope['scheme'])
    async def nothing():return {'type':'http.disconnect'}
    async def send(message):pass
    guarded=ProxyHeadersMiddleware(app,trusted_hosts=['10.0.0.2'])
    for peer in ['10.0.0.99','10.0.0.2']:
        asyncio.run(guarded({'type':'http','scheme':'http','client':(peer,1000),
            'headers':[(b'x-forwarded-proto',b'https')]},nothing,send))
    assert seen==['http','https']


def test_nginx_only_accepts_https_assertion_from_original_pinned_edge_peer():
    config=(Path(__file__).resolve().parents[1]/'web/nginx.conf').read_text()
    assert 'map "$realip_remote_addr:$http_x_forwarded_proto" $ownstack_forwarded_scheme' in config
    assert '"${OWNSTACK_EDGE_INTERNAL_IP}:https" https;' in config
    assert 'default $scheme;' in config
    assert config.count('proxy_set_header X-Forwarded-Proto $ownstack_forwarded_scheme;')==3
    assert 'proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;' not in config


def test_provisioner_refuses_main_or_live_before_connecting(tmp_path,monkeypatch):
    import importlib.util
    spec=importlib.util.spec_from_file_location('provisioner',Path(__file__).resolve().parents[1]/'scripts/provision_rehearsal_role.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module.psycopg,'connect',lambda **kw:pytest.fail('must not connect'))
    for url,mode in [('postgresql+psycopg://a:b@localhost/ownstack','off'),
        ('postgresql+psycopg://a:b@remote.example/ownstack_restore_test','off'),
        ('postgresql+psycopg://a:b@localhost/ownstack_restore_test','nebius')]:
        with pytest.raises(ValueError):
            module.provision(Settings(environment='local',ai_mode=mode,max_live_calls=0,
                nebius_key='',nebius_model='',nebius_patch_model='',database_url=url),tmp_path/'runtime.env')
    assert not (tmp_path/'runtime.env').exists()


def test_database_posture_checks_ownership_and_all_role_memberships():
    from ownstack.db_security import POSTURE_SQL
    for authority in ['d.datdba=r.oid','n.nspowner=r.oid','c.relowner=r.oid','p.proowner=r.oid',
                      "pg_has_role(current_user, p.oid, 'MEMBER')"]:
        assert authority in POSTURE_SQL


def test_unsupported_platform_fails_before_loading_kernel_libraries(monkeypatch):
    from ownstack import candidate_sandbox
    monkeypatch.setattr(candidate_sandbox.platform,'machine',lambda:'unsupported')
    monkeypatch.setattr(candidate_sandbox.ctypes,'CDLL',lambda *a,**k:pytest.fail('must fail before loading'))
    with pytest.raises(RuntimeError,match='unavailable'):
        candidate_sandbox.lockdown()


@pytest.mark.parametrize('change',['missing','wrong_policy','wrong_hash','future','malformed'])
def test_readiness_fails_closed_for_bad_kernel_policy(client,fixture_db,tmp_path,monkeypatch,change):
    from sqlalchemy import text
    from ownstack.service import mark_pulse
    monkeypatch.setenv('OWNSTACK_REQUIRE_BACKGROUND','true')
    monkeypatch.setenv('OWNSTACK_VERIFIER_JOBS_DIR',str(tmp_path))
    with fixture_db() as db:
        db.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)'))
        db.execute(text('INSERT INTO alembic_version VALUES (:v)'),{'v':SCHEMA_REVISION})
        mark_pulse(db,'worker');db.commit()
    (tmp_path/'heartbeat').write_text(str(time.time()))
    record={'policy':POLICY_ID,'landlock_abi':8,'checked_at':time.time(),
            'execution_policy_hash':current_provenance()['execution_policy_hash']}
    if change=='wrong_policy':record['policy']='permissive'
    elif change=='wrong_hash':record['execution_policy_hash']='old'
    elif change=='future':record['checked_at']=time.time()+60
    elif change=='malformed':record=[]
    if change!='missing':(tmp_path/'sandbox-policy.json').write_text(json.dumps(record))
    assert client.get('/health/ready').status_code==503
