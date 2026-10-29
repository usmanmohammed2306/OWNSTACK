"""Different loopback ports must not overwrite one another's sessions."""
import pytest
from ownstack.auth import cookie_name,SESSION_COOKIE
from ownstack.config import Settings

def test_two_workspaces_coexist_and_logout_removes_only_its_namespace(client,monkeypatch):
    monkeypatch.setenv('OWNSTACK_COOKIE_NAMESPACE','lab-a')
    a=client.post('/v1/session',json={'username':'atlas-admin','password':'pass'});assert a.status_code==200
    assert client.cookies.get('lab-a-'+SESSION_COOKIE)
    monkeypatch.setenv('OWNSTACK_COOKIE_NAMESPACE','lab-b')
    assert client.get('/v1/session').status_code==401
    b=client.post('/v1/session',json={'username':'atlas-engineer','password':'pass'});assert b.status_code==200
    assert client.get('/v1/session').json()['user_id']=='atlas-engineer'
    monkeypatch.setenv('OWNSTACK_COOKIE_NAMESPACE','lab-a')
    assert client.get('/v1/session').json()['user_id']=='atlas-admin'
    assert client.post('/v1/session/logout',headers={'X-CSRF-Token':a.json()['csrf_token']}).status_code==200
    assert client.get('/v1/session').status_code==401
    monkeypatch.setenv('OWNSTACK_COOKIE_NAMESPACE','lab-b')
    assert client.get('/v1/session').json()['user_id']=='atlas-engineer'

def test_default_names_and_secure_host_prefix_are_preserved():
    assert cookie_name(SESSION_COOKIE,Settings(cookie_namespace=''))==SESSION_COOKIE
    assert cookie_name(SESSION_COOKIE,Settings(environment='production',cookie_namespace='lab-a'))=='__Host-lab-a-'+SESSION_COOKIE

@pytest.mark.parametrize('namespace',['a b','/path','x; Secure','x'*33,'../other','UPPER'])
def test_invalid_namespaces_fail_configuration(namespace):
    with pytest.raises(ValueError,match='cookie namespace'):Settings(cookie_namespace=namespace).validate()
