"""Harness guards must refuse unsafe targets before launching tools/mutations."""
from pathlib import Path
import json
import pytest
import httpx
import importlib.util

ROOT=Path(__file__).resolve().parents[1]
def load_script(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

demo_module=load_script('run_offline_demo')
recovery=load_script('rehearse_docker_recovery')
OfflineDemo, local_base=demo_module.OfflineDemo,demo_module.local_base


@pytest.mark.parametrize('url', ['https://127.0.0.1:8082','http://example.com:8082',
    'http://127.0.0.1','http://user:pass@127.0.0.1:8082','http://127.0.0.1:8082/?x=1',
    'http://127.0.0.1:8082/path','http://127.0.0.1:8082/#fragment'])
def test_http_demo_refuses_non_loopback_or_ambiguous_target(url):
    with pytest.raises(ValueError):
        local_base(url)


@pytest.mark.parametrize('bad_mode', ['fixture','nebius'])
def test_http_demo_refuses_enabled_generation_before_login(tmp_path,monkeypatch,bad_mode):
    monkeypatch.setattr(demo_module,'ROOT',tmp_path)
    calls=[]
    def respond(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200,json={'status':'ready','ai_mode':bad_mode})
    demo=OfflineDemo('http://127.0.0.1:8082',tmp_path/'.private/guard',transport=httpx.MockTransport(respond))
    report=demo.execute()
    assert not report['passed'] and report['failed_check']=='runtime_ai_off'
    assert calls==[('GET','/health/ready')]
    assert json.loads((tmp_path/'.private/guard/report.json').read_text())['passed'] is False


def test_functional_demo_paces_requests_without_retrying_mutations(tmp_path,monkeypatch):
    monkeypatch.setattr(demo_module,'ROOT',tmp_path)
    pauses=[];calls=[]
    monkeypatch.setattr(demo_module.time,'monotonic',lambda:100.)
    monkeypatch.setattr(demo_module.time,'sleep',pauses.append)
    def respond(request):
        calls.append(request.method)
        return httpx.Response(200,json={})
    demo=OfflineDemo('http://127.0.0.1:8082',tmp_path/'.private/pacing',transport=httpx.MockTransport(respond))
    try:
        demo.call('synthetic','POST','/v1/test')
        demo.call('synthetic','GET','/v1/test')
        assert pauses==[pytest.approx(.07)] and calls==['POST','GET']
    finally:
        for client in demo.clients.values():client.close()


@pytest.fixture
def recovery_env(monkeypatch,tmp_path):
    monkeypatch.setattr(recovery,'ROOT',tmp_path)
    for key,value in {'OWNSTACK_AI_MODE':'off','OWNSTACK_MAX_LIVE_CALLS':'0',
        'NEBIUS_API_KEY':'','NEBIUS_MODEL_ID':'','NEBIUS_PATCH_MODEL_ID':'','DOCKER_HOST':''}.items():
        monkeypatch.setenv(key,value)
    return tmp_path/'.private/new'


@pytest.mark.parametrize('key,value', [('OWNSTACK_AI_MODE','nebius'),('OWNSTACK_AI_MODE','fixture'),
    ('OWNSTACK_MAX_LIVE_CALLS','1'),('NEBIUS_API_KEY','synthetic'),('NEBIUS_MODEL_ID','synthetic'),
    ('NEBIUS_PATCH_MODEL_ID','synthetic'),('DOCKER_HOST','tcp://remote:2375')])
def test_recovery_refuses_live_or_remote_before_artifact_or_tool(recovery_env,monkeypatch,key,value):
    monkeypatch.setenv(key,value)
    monkeypatch.setattr(recovery.subprocess,'run',lambda *a,**k:pytest.fail('Must not launch tool'))
    with pytest.raises(ValueError):
        recovery.rehearse('ownstack-db-1',recovery_env)
    assert not recovery_env.exists()


@pytest.mark.parametrize('container',['foreign-db-1','ownstack;echo bad','../ownstack','ownstack db'])
def test_recovery_container_identifier_guard(recovery_env,container):
    with pytest.raises(ValueError):
        recovery.validate(container,recovery_env)


def test_recovery_never_overwrites_private_evidence(recovery_env):
    recovery_env.mkdir(parents=True)
    with pytest.raises(ValueError):
        recovery.validate('ownstack-db-1',recovery_env)


def test_rehearsal_overlay_clears_inference_and_requires_explicit_target():
    import yaml
    root=Path(__file__).resolve().parents[1]
    overlay=yaml.safe_load((root/'compose.rehearsal.yaml').read_text())
    for name in ('api','worker','migrate'):
        env=overlay['services'][name]['environment']
        assert env['OWNSTACK_AI_MODE']=='off' and env['OWNSTACK_MAX_LIVE_CALLS']=='0'
        assert all(env[key]=='' for key in ('NEBIUS_API_KEY','NEBIUS_MODEL_ID','NEBIUS_PATCH_MODEL_ID'))
        assert ':?' in env['OWNSTACK_DATABASE_URL']
